from __future__ import annotations

import errno
from datetime import datetime, timedelta, timezone
from itertools import chain
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from typing_extensions import TypeVar

from typed_diskcache import exception as te
from typed_diskcache.core.const import DBNAME
from typed_diskcache.core.types import Container, SettingsKey, SettingsKwargs
from typed_diskcache.database import Connection
from typed_diskcache.database.connect import transact as database_transact
from typed_diskcache.database.model import Cache as CacheTable
from typed_diskcache.database.model import Settings as SettingsTable
from typed_diskcache.database.revision import auto as revision_auto
from typed_diskcache.log import get_logger
from typed_diskcache.model import Settings, SQLiteSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from typed_diskcache.interface.disk import DiskProtocol

__all__ = []

_T = TypeVar("_T", infer_variance=True)
logger = get_logger()


def touch_gitignore(directory: Path) -> None:
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        with gitignore.open("w") as file:
            file.write("*\n")


def ensure_cache_directory(directory: Path) -> Path:
    if not directory.exists() or not directory.is_dir():
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                error_msg = (
                    f'Cache directory "{directory}" does not exist'
                    " and could not be created"
                )
                raise te.TypedDiskcacheOSError(exc.errno, error_msg) from exc
    touch_gitignore(directory)
    return directory


def init_args(
    directory: Path,
    disk_type: type[DiskProtocol] | Callable[..., DiskProtocol] | None,
    disk_args: Mapping[str, Any] | None,
    timeout: float = 60,
    **kwargs: Any,
) -> tuple[DiskProtocol, Connection, Settings, int]:
    directory = ensure_cache_directory(directory)

    conn = Connection(directory / DBNAME, 0)
    with conn.session() as session:
        sa_conn = session.connection()
        revision_auto(sa_conn)

    with conn.session() as session:
        logger.debug("Checking for existing cache settings")
        try:
            setting_records: Sequence[SettingsTable] = (
                session.execute(sa.select(SettingsTable)).scalars().all()
            )
        except OperationalError:
            logger.debug("No existing cache settings found")
            setting_records = []

    db_settings = {record.key: record.value for record in setting_records}
    disk_in_settings = SettingsKey.SERIALIZED_DISK in db_settings
    db_settings |= kwargs

    settings = kwargs_to_settings(db_settings)
    logger.debug("Cache settings: %r", settings)

    if disk_in_settings:
        logger.debug("Loading disk from settings")
        disk = settings.create_disk(directory)
    else:
        if disk_type is None:
            disk_type = settings.load_disk()
        logger.debug("Creating new disk")
        disk = disk_type(directory, **(disk_args or {}))
        serialized_disk = disk.model_dump()
        serialized_disk[1].pop("directory", None)
        settings = settings.model_copy(update={"serialized_disk": serialized_disk})

    now = datetime.now(timezone(timedelta(0)))
    new_setting_records = [
        SettingsTable(key=key, value=value, modified_at=now)
        for key, value in settings.model_dump(
            exclude={"sqlite_settings"}, by_alias=True
        ).items()
    ]
    new_sqlite_setting_records = [
        SettingsTable(key=key, value=value, modified_at=now)
        for key, value in settings.sqlite_settings.model_dump(by_alias=True).items()
    ]
    settings_key_id = {x.key: x.id for x in setting_records}
    with conn.session() as session:
        with database_transact(session):
            for record in chain(new_setting_records, new_sqlite_setting_records):
                if record.key in settings_key_id:
                    record.id = settings_key_id[record.key]
                    session.merge(record)
                else:
                    session.add(record)
            session.commit()

    conn.update_settings(settings)
    conn.timeout = float(timeout)

    with conn.session() as session:
        page_size = session.execute(sa.text("PRAGMA page_size;")).scalar_one()

    return disk, conn, settings, page_size


def wrap_default(value: _T) -> Container[_T]:
    return Container(value=value, default=True, expire_time=None, tags=frozenset())


def wrap_instnace(
    key: Any,
    value: _T,
    cache: CacheTable | sa.Row[tuple[CacheTable]],
    tags: set[str] | None = None,
) -> Container[_T]:
    return Container(
        value=value,
        default=False,
        expire_time=cache.expire_time,
        tags=frozenset(cache.tag_names) if tags is None else frozenset(tags),
        key=key,
    )


def combine_settings(
    settings: Settings | SettingsKwargs | None, kwargs: SettingsKwargs
) -> Settings:
    if not isinstance(settings, Settings):
        settings = kwargs_to_settings(settings)

    if not kwargs:
        return settings

    sqlite_kwargs = {
        key.removeprefix("sqlite_"): value
        for key, value in kwargs.items()
        if key.startswith("sqlite_")
    }
    sqlite_settings = settings.sqlite_settings.model_copy(update=sqlite_kwargs)

    return settings.model_copy(
        update=dict(kwargs) | {"sqlite_settings": sqlite_settings}
    )


def kwargs_to_settings(settings: Mapping[str, Any] | None) -> Settings:
    if not settings:
        return Settings()

    sqlite_settings = SQLiteSettings.model_validate({
        key: value for key, value in settings.items() if key.startswith("sqlite_")
    })
    return Settings.model_validate(
        dict(settings) | {"sqlite_settings": sqlite_settings}
    )
