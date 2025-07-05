from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, ClassVar, Generic

import cloudpickle
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    declared_attr,
    mapped_column,
    relationship,
    synonym,
)
from sqlalchemy_utils import ChoiceType
from typing_extensions import Self, TypeVar, override

from typed_diskcache import exception as te
from typed_diskcache.core.types import CacheMode, MetadataKey, SettingsKey
from typed_diskcache.log import get_logger
from typed_diskcache.utils.rename import camel_to_snake

if TYPE_CHECKING:
    from os import PathLike

    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncConnection
    from sqlalchemy.orm import InstrumentedAttribute


__all__ = ["Cache", "Metadata", "Settings", "Version"]

_T = TypeVar("_T", infer_variance=True, default=Any)
_T2 = TypeVar("_T2", infer_variance=True)
logger = get_logger()
_UTC = timezone(timedelta(0))


class Base(MappedAsDataclass, DeclarativeBase):
    __table__: ClassVar[sa.Table]  # pyright: ignore[reportIncompatibleVariableOverride]

    id: Mapped[int] = mapped_column(init=False, primary_key=True, autoincrement=True)

    @declared_attr.directive
    @classmethod
    def __tablename__(cls) -> str:
        return camel_to_snake(cls.__name__)

    def update(self, **kwargs: Any) -> Self:
        """update the record"""
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self


class Version(Base):
    """version table using in migration"""

    revision: Mapped[str] = mapped_column(sa.String(100))

    @classmethod
    def get(cls, connection: Connection) -> str:
        """get revision id"""
        stmt = sa.select(cls.revision).where(cls.id == 1)
        try:
            value = connection.scalar(stmt)
        except OperationalError as exc:
            raise te.TypedDiskcacheValueError("there is no version table") from exc

        if not value:
            raise te.TypedDiskcacheValueError("version table is empty")
        return value

    @classmethod
    async def aget(cls, connection: AsyncConnection) -> str:
        """get revision id"""
        stmt = sa.select(cls.revision).where(cls.id == 1)
        try:
            value = await connection.scalar(stmt)
        except OperationalError as exc:
            raise te.TypedDiskcacheValueError("there is no version table") from exc

        if not value:
            raise te.TypedDiskcacheValueError("version table is empty")
        return value

    def set(self, connection: Connection) -> None:
        """set revision id"""
        stmt = (
            sa.update(Version)
            .values(revision=self.revision)
            .where(Version.id == (self.id or 1))
        )
        connection.execute(stmt)
        logger.debug("set revision id: `%s`", self.revision)

    async def aset(self, connection: AsyncConnection) -> None:
        """set revision id"""
        stmt = (
            sa.update(Version)
            .values(revision=self.revision)
            .where(Version.id == (self.id or 1))
        )
        await connection.execute(stmt)
        logger.debug("set revision id: `%s`", self.revision)

    @classmethod
    def delete(cls, connection: Connection, version_id: int | None = None) -> None:
        """delete version table"""
        connection.execute(sa.delete(cls).where(Version.id == (version_id or 1)))
        logger.debug("delete version id: `%s`", version_id or 1)

    @classmethod
    async def adelete(
        cls, connection: AsyncConnection, version_id: int | None = None
    ) -> None:
        """delete version table"""
        await connection.execute(sa.delete(cls).where(Version.id == (version_id or 1)))
        logger.debug("delete version id: `%s`", version_id or 1)


class Settings(Base, Generic[_T]):
    """diskcache settings table"""

    __table_args__ = (sa.UniqueConstraint("key", name="settings_key"),)

    _key: Mapped[SettingsKey] = mapped_column(
        "key", ChoiceType(SettingsKey, impl=sa.String(32))
    )
    _value: Mapped[_T] = mapped_column(
        "value", sa.JSON(none_as_null=False), nullable=False, repr=False
    )
    value: Mapped[Any] = synonym("_value", init=False)
    modified_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default_factory=lambda: datetime.now(_UTC),
        server_default=sa.func.now(),
    )

    def __init__(
        self, *, key: str | SettingsKey, value: _T, modified_at: datetime | None = None
    ) -> None:
        super().__init__()
        self.key = key
        self._value = value
        if modified_at is not None:
            self.modified_at = modified_at

    @hybrid_property
    def key(self) -> SettingsKey:  # pyright: ignore[reportRedeclaration]  # noqa: D102
        return self._key

    @key.setter
    def key(self, value: str | SettingsKey) -> None:  # pyright: ignore[reportRedeclaration]
        key = SettingsKey(value)
        if key == SettingsKey.UNKNOWN:
            raise te.TypedDiskcacheValueError("unknown key")
        self._key = key

    @key.expression  # pyright: ignore[reportArgumentType]
    @classmethod
    def key(cls) -> InstrumentedAttribute[str]:  # noqa: D102
        return cls._key

    def __getitem__(self, type_: type[_T2]) -> Settings[_T2]:
        return self  # type: ignore


class Metadata(Base):
    """diskcache metadata table"""

    __table_args__ = (sa.UniqueConstraint("key", name="metadata_key"),)
    key: Mapped[MetadataKey] = mapped_column(
        ChoiceType(MetadataKey, impl=sa.String(32))
    )
    value: Mapped[int] = mapped_column(
        default=0, server_default=sa.literal(0, type_=sa.Integer())
    )


class Cache(Base):
    """diskcache table"""

    __table_args__ = (
        sa.UniqueConstraint("key", "raw", name="cache_key_raw"),
        sa.Index("cache_expire_time", "expire_time"),
        sa.Index("cache_store_time", "store_time"),
        sa.Index("cache_access_time", "access_time"),
        sa.Index("cache_access_count", "access_count"),
    )

    _key: Mapped[bytes] = mapped_column("key")
    raw: Mapped[bool]
    store_time: Mapped[float]
    access_time: Mapped[float]
    _filepath: Mapped[str | None] = mapped_column(
        "filepath", sa.String(), nullable=True
    )
    value: Mapped[bytes | None] = mapped_column(repr=False)

    expire_time: Mapped[float | None] = mapped_column(
        default=None, server_default=sa.literal(None, type_=sa.Float())
    )
    mode: Mapped[CacheMode] = mapped_column(
        ChoiceType(CacheMode, impl=sa.Integer()),
        default=CacheMode.NONE,
        server_default=sa.literal(CacheMode.NONE, type_=sa.Integer()),
    )
    access_count: Mapped[int] = mapped_column(
        default=0, server_default=sa.literal(0, type_=sa.Integer())
    )
    size: Mapped[int] = mapped_column(
        default=0, server_default=sa.literal(0, type_=sa.Integer())
    )

    tags: Mapped[set[Tag]] = relationship(
        default_factory=set,
        secondary=lambda: CacheTag.__table__,
        back_populates="caches",
        repr=False,
    )
    tag_names: AssociationProxy[frozenset[str]] = association_proxy(
        "tags", "name", init=False, repr=False
    )

    @hybrid_property
    def tags_count(self) -> int:  # pyright: ignore[reportRedeclaration]
        """get tags count"""
        return len(self.tags)

    @tags_count.expression
    @classmethod
    def tags_count(cls) -> sa.Label[int]:
        """get tags count"""
        return (
            sa.select(sa.func.count(CacheTag.cache_id))
            .where(CacheTag.cache_id == cls.id)
            .label("tags_count")
        )

    def __init__(  # noqa: PLR0913
        self,
        *,
        key: Any,
        raw: bool,
        store_time: float,
        access_time: float,
        value: bytes | None,
        filepath: str | PathLike[str] | None,
        expire_time: float | None = None,
        mode: CacheMode = CacheMode.NONE,
        access_count: int = 0,
        size: int = 0,
    ) -> None:
        super().__init__()
        self.key = key
        self.raw = raw
        self.store_time = store_time
        self.access_time = access_time
        self.filepath = filepath
        self.value = value
        self.expire_time = expire_time
        self.mode = mode
        self.access_count = access_count
        self.size = size

    @hybrid_property
    def key(self) -> bytes:  # pyright: ignore[reportRedeclaration]  # noqa: D102
        return self._key

    @key.setter
    def key(self, value: Any) -> None:  # pyright: ignore[reportRedeclaration]
        self._key = value if isinstance(value, bytes) else cloudpickle.dumps(value)

    @key.expression
    @classmethod
    def key(cls) -> InstrumentedAttribute[bytes]:  # noqa: D102
        return cls._key

    @hybrid_property
    def filepath(self) -> str | None:  # pyright: ignore[reportRedeclaration]  # noqa: D102
        return self._filepath

    @filepath.setter
    def filepath(self, value: str | PathLike[str] | None) -> None:  # pyright: ignore[reportRedeclaration]
        self._filepath = str(value) if value else None

    @filepath.expression
    @classmethod
    def filepath(cls) -> InstrumentedAttribute[str | None]:  # noqa: D102
        return cls._filepath

    @classmethod
    def parse_row(cls, row: sa.Row[tuple[Self]]) -> Self:
        """parse row to instance"""
        values = {
            key: getattr(row, key)
            for key in cls.__table__.columns.keys()  # noqa: SIM118
        }
        row_id = values.pop("id", None)
        new = cls(**values)
        if row_id is not None:
            new.id = row_id
        return new


class Tag(Base):
    __table_args__ = (sa.UniqueConstraint("name", name="tag_name"),)

    caches: Mapped[list[Cache]] = relationship(
        init=False,
        secondary=lambda: CacheTag.__table__,
        back_populates="tags",
        repr=False,
    )

    name: Mapped[str] = mapped_column(sa.String(100))

    @override
    def __hash__(self) -> int:
        return hash(self.name)


class CacheTag(Base):
    __table_args__ = (
        sa.UniqueConstraint("cache_id", "tag_id", name="cache_tag_cache_id_tag_id"),
        sa.ForeignKeyConstraint(
            ["cache_id"], [Cache.id], name="cache_tag_cache_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], [Tag.id], name="cache_tag_tag_id_fkey", ondelete="CASCADE"
        ),
    )

    cache_id: Mapped[int]
    tag_id: Mapped[int]
