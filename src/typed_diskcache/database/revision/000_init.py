from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import schema
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy_utils import ChoiceType

from typed_diskcache.core.types import CacheMode, MetadataKey, SettingsKey

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

metadata = sa.MetaData()

Version = sa.Table(
    "version",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
    sa.Column("revision", sa.String(length=100), nullable=False),
    schema=None,
)
Settings = sa.Table(
    "settings",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
    sa.Column("key", ChoiceType(SettingsKey, impl=sa.String(32)), nullable=False),
    sa.Column("value", sa.JSON(none_as_null=False), nullable=False),
    sa.Column(
        "modified_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    ),
    sa.UniqueConstraint("key", name="settings_key"),
    schema=None,
)
Metadata = sa.Table(
    "metadata",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
    sa.Column("key", ChoiceType(MetadataKey, impl=sa.String(32)), nullable=False),
    sa.Column(
        "value",
        sa.Integer(),
        nullable=False,
        server_default=sa.literal(0, type_=sa.Integer()),
    ),
    sa.UniqueConstraint("key", name="metadata_key"),
    schema=None,
)
Cache = sa.Table(
    "cache",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
    sa.Column("key", sa.LargeBinary(), nullable=False),
    sa.Column("raw", sa.Boolean(), nullable=False),
    sa.Column("store_time", sa.Float(), nullable=False),
    sa.Column("access_time", sa.Float(), nullable=False),
    sa.Column("filepath", sa.String(), nullable=True),
    sa.Column("value", sa.LargeBinary(), nullable=True),
    sa.Column(
        "expire_time", sa.Float(), server_default=sa.literal(None, type_=sa.Float())
    ),
    sa.Column(
        "mode",
        ChoiceType(CacheMode, impl=sa.Integer()),
        nullable=False,
        default=CacheMode.NONE,
        server_default=sa.literal(CacheMode.NONE, type_=sa.Integer()),
    ),
    sa.Column(
        "access_count",
        sa.Integer(),
        nullable=False,
        default=0,
        server_default=sa.literal(0, type_=sa.Integer()),
    ),
    sa.Column(
        "size",
        sa.Integer(),
        nullable=False,
        default=0,
        server_default=sa.literal(0, type_=sa.Integer()),
    ),
    sa.UniqueConstraint("key", "raw", name="cache_key_raw"),
    sa.Index("cache_expire_time", "expire_time"),
    sa.Index("cache_store_time", "store_time"),
    sa.Index("cache_access_time", "access_time"),
    sa.Index("cache_access_count", "access_count"),
    schema=None,
)
Tag = sa.Table(
    "tag",
    metadata,
    sa.Column("name", sa.String(100), nullable=False),
    sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
    sa.UniqueConstraint("name", name="tag_name"),
    schema=None,
)
CacheTag = sa.Table(
    "cache_tag",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
    sa.Column("cache_id", sa.Integer(), nullable=False),
    sa.Column("tag_id", sa.Integer(), nullable=False),
    sa.UniqueConstraint("cache_id", "tag_id", name="cache_tag_cache_id_tag_id"),
    sa.ForeignKeyConstraint(
        ["cache_id"], ["cache.id"], name="cache_tag_cache_id_fkey", ondelete="CASCADE"
    ),
    sa.ForeignKeyConstraint(
        ["tag_id"], ["tag.id"], name="cache_tag_tag_id_fkey", ondelete="CASCADE"
    ),
    schema=None,
)


def upgrade(conn: Connection) -> str:
    """upgrade null -> init"""
    if conn.in_transaction() or conn.in_nested_transaction():
        func = conn.begin_nested
    else:
        func = conn.begin

    with func() as transact:
        metadata.create_all(
            conn,
            tables=[Version, Settings, Metadata, Cache, Tag, CacheTag],
            checkfirst=False,
        )
        conn.execute(sa.insert(Version).values({"revision": Path(__file__).stem}))
        _active_metadata(conn)
        transact.commit()

    return "000_init"


def downgrade(conn: Connection) -> str | None:
    """downgrade init -> null"""
    drop_tables = [
        schema.DropTable(table, if_exists=False)
        for table in (Version, Settings, Metadata, Cache, Tag, CacheTag)
    ]

    if conn.in_transaction() or conn.in_nested_transaction():
        func = conn.begin_nested
    else:
        func = conn.begin

    with func() as transact:
        _deactive_metadata(conn)
        for stmt in drop_tables:
            conn.execute(stmt)
        transact.commit()


def _active_metadata(conn: Connection) -> None:
    for key in MetadataKey:
        conn.execute(
            sqlite_insert(Metadata)
            .values(key=key.value, value=0)
            .on_conflict_do_nothing(index_elements=["key"])
        )

    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS metadata_count_insert"
            " AFTER INSERT ON cache FOR EACH ROW BEGIN"
            " UPDATE metadata SET value = value + 1"
            ' WHERE key = "count"; END'
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS metadata_count_delete"
            " AFTER DELETE ON cache FOR EACH ROW BEGIN"
            " UPDATE metadata SET value = value - 1"
            ' WHERE key = "count"; END'
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS metadata_size_insert"
            " AFTER INSERT ON cache FOR EACH ROW BEGIN"
            " UPDATE metadata SET value = value + NEW.size"
            ' WHERE key = "size"; END'
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS metadata_size_update"
            " AFTER UPDATE ON cache FOR EACH ROW BEGIN"
            " UPDATE metadata"
            " SET value = value + NEW.size - OLD.size"
            ' WHERE key = "size"; END'
        )
    )
    conn.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS metadata_size_delete"
            " AFTER DELETE ON cache FOR EACH ROW BEGIN"
            " UPDATE metadata SET value = value - OLD.size"
            ' WHERE key = "size"; END'
        )
    )


def _deactive_metadata(conn: Connection) -> None:
    conn.execute(sa.text("DROP TRIGGER IF EXISTS metadata_count_insert"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS metadata_count_delete"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS metadata_size_insert"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS metadata_size_update"))
    conn.execute(sa.text("DROP TRIGGER IF EXISTS metadata_size_delete"))
