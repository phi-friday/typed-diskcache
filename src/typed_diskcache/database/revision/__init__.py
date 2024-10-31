from __future__ import annotations

import re
from contextlib import contextmanager, suppress
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from typing_extensions import Self, override

from typed_diskcache import exception as te
from typed_diskcache.core.const import REVISION_MAXIMA
from typed_diskcache.database.connect import transact as connect_transact
from typed_diskcache.database.model import Version
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Connection
    from sqlalchemy.engine.base import Transaction


__all__ = ["auto", "upgrade", "downgrade"]

_REVISION = re.compile(r"(\d{3})_(.*)")
logger = get_logger()


class Revision(NamedTuple):
    num: int
    name: str | None = None
    fullname: str | None = None

    @classmethod
    def parse(cls, value: str | int) -> Self:
        if isinstance(value, int):
            with suppress(StopIteration):
                file = next(Path(__file__).parent.glob(f"{value}_*.py"))
                if _REVISION.match(file.stem):
                    split = file.stem.split("_", 1)
                    return cls(int(split[0]), split[1], file.stem)
            return cls(value)

        if _REVISION.match(value):
            split = value.split("_", 1)
            return cls(int(split[0]), split[1], value)

        logger.debug("searching revision file: `%s`", value)
        with suppress(StopIteration):
            file = next(Path(__file__).parent.glob(f"*{value}.py"))
            if not _REVISION.match(file.stem):
                error_msg = f"revision `{value}` not found"
                raise te.TypedDiskcacheFileNotFoundError(error_msg)
            logger.debug(
                "Found revision file: `%s`", file.relative_to(Path(__file__).parent)
            )
            split = file.stem.split("_", 1)
            return cls(int(split[0]), split[1], file.stem)

        error_msg = f"revision `{value}` not found"
        raise te.TypedDiskcacheFileNotFoundError(error_msg)

    @override
    def __str__(self) -> str:
        return f"{self.num:03}"


def auto(conn: Connection, target_revision: str | int | Revision | None = None) -> None:
    """auto upgrade or downgrade database to target revision

    Args:
        conn: The connection to the database.
        target_revision: The target revision to upgrade or downgrade.
            Defaults to None.
    """
    current = _parse_revision(conn)
    logger.debug("current revision is `%s`", current)
    if target_revision is None:
        target_revision = Revision(REVISION_MAXIMA)
    elif isinstance(target_revision, (str, int)):
        target_revision = Revision.parse(target_revision)
    logger.debug("target revision is `%s`", target_revision)
    if current is not None and target_revision.num == current.num:
        logger.debug("current revision is up to date")
        return
    revisions, target_revision = _prepare_revisions(target_revision)

    with connect_transact(conn):
        with _transact(conn) as (_, transact):
            if current is None or target_revision.num >= current.num:
                _upgrade_process(conn, current, target_revision, revisions)
                transact.commit()
                conn.commit()
                return
            if target_revision.num < current.num:
                _downgrade_process(conn, current, target_revision, revisions)
                transact.commit()
                conn.commit()
                return
    logger.debug("current revision is up to date")


def upgrade(conn: Connection, target_revision: str | int | Revision) -> None:
    """upgrade database to target revision

    Args:
        conn: The connection to the database.
        target_revision: The target revision to upgrade.
    """
    current = _parse_revision(conn)
    revisions, target_revision = _prepare_revisions(target_revision)
    if current is not None:
        if target_revision.num < current.num:
            error_msg = (
                f"target revision `{target_revision.num:03}` is lower than current"
            )
            raise te.TypedDiskcacheValueError(error_msg)
        if target_revision.num == current.num:
            logger.debug("current revision is up to date")
            return

    with connect_transact(conn):
        with _transact(conn) as (_, transact):
            _upgrade_process(conn, current, target_revision, revisions)
            transact.commit()
            conn.commit()


def downgrade(conn: Connection, target_revision: str | int | Revision) -> None:
    """downgrade database to target revision

    Args:
        conn: The connection to the database.
        target_revision: The target revision to downgrade.
    """
    current = _parse_revision(conn)
    revisions, target_revision = _prepare_revisions(target_revision)
    if current is not None:
        if target_revision.num > current.num:
            error_msg = (
                f"target revision `{target_revision.num:03}` is higher than current"
            )
            raise te.TypedDiskcacheValueError(error_msg)
        if target_revision.num == current.num:
            logger.debug("current revision is up to date")
            return

    with connect_transact(conn):
        with _transact(conn) as (_, transact):
            _downgrade_process(conn, current, target_revision, revisions)
            transact.commit()
            conn.commit()


def _upgrade_process(
    conn: Connection,
    current: Revision | None,
    target_revision: Revision,
    revisions: dict[int, tuple[Revision, Path]],
) -> None:
    with _transact(conn) as (_, transact):
        for num, (_, file) in sorted(revisions.items(), key=lambda x: x[0]):
            if (
                current is not None and num <= current.num
            ) or num > target_revision.num:
                continue
            module = import_module(f"typed_diskcache.database.revision.{file.stem}")
            next_revision = Revision(num, fullname=file.stem)
            logger.debug("upgrade revision from `%s` to `%s`", current, next_revision)
            version = module.upgrade(conn)
            current = next_revision
            if version is None:
                Version.delete(conn)
            else:
                Version(version).set(conn)
        transact.commit()


def _downgrade_process(
    conn: Connection,
    current: Revision | None,
    target_revision: Revision,
    revisions: dict[int, tuple[Revision, Path]],
) -> None:
    with _transact(conn) as (_, transact):
        for num, (_, file) in sorted(
            revisions.items(), key=lambda x: x[0], reverse=True
        ):
            if (
                current is not None and num > current.num
            ) or num <= target_revision.num:
                continue
            module = import_module(f"typed_diskcache.database.revision.{file.stem}")
            next_revision = Revision(num, fullname=file.stem)
            logger.debug("downgrade revision from `%s` to `%s`", current, next_revision)
            version = module.downgrade(conn)
            current = next_revision
            if version is None:
                Version.delete(conn)
            else:
                Version(version).set(conn)
        transact.commit()


def _parse_revision(conn: Connection) -> Revision | None:
    from typed_diskcache.database.model import Version

    try:
        version = Version.get(conn)
    except te.TypedDiskcacheValueError:
        return None

    return Revision.parse(version)


def _prepare_revisions(
    target_revision: str | int | Revision,
) -> tuple[dict[int, tuple[Revision, Path]], Revision]:
    if isinstance(target_revision, (str, int)):
        target_revision = Revision.parse(target_revision)
    revisions = {
        (_rev := Revision.parse(x.stem)).num: (_rev, x)
        for x in Path(__file__).parent.glob("*.py")
        if _REVISION.match(x.stem)
    }
    if target_revision.num != REVISION_MAXIMA and target_revision.num not in revisions:
        error_msg = f"revision `{target_revision.num:03}` not found"
        raise te.TypedDiskcacheFileNotFoundError(error_msg)

    return revisions, target_revision


@contextmanager
def _transact(
    conn: Connection,
) -> Generator[tuple[Connection, Transaction], None, None]:
    if conn.in_transaction() or conn.in_nested_transaction():
        func = conn.begin_nested
        logger.debug("begin nested transaction", stacklevel=3)
    else:
        func = conn.begin
        logger.debug("begin transaction", stacklevel=3)

    with func() as transact:
        try:
            yield conn, transact
        except BaseException:
            transact.rollback()
            raise
