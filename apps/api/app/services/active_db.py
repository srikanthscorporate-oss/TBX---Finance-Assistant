"""Which ClickHouse database the assistant is currently answering from.

The bundled dataset lives in `settings.ch_db` (tbx_finance) and is the default.
Initialising a user-supplied MySQL endpoint ingests into a *sibling* database and
moves this pointer, so the bundled tables -- which the test suite and every verify
gate recompute independently from data/raw -- are never truncated by a demo.

The value is interpolated into SQL (a ClickHouse database cannot be a bound
parameter), so it is validated as a bare identifier here and nowhere else.
"""
from __future__ import annotations

import re
import threading

from ..config.settings import settings

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

_lock = threading.Lock()
_active: str = settings.ch_db


class UnsafeDatabaseName(ValueError):
    """A database name that will not be interpolated into SQL."""


def check_name(name: str) -> str:
    if not _IDENT.match(name or ""):
        raise UnsafeDatabaseName(f"unsafe ClickHouse database name: {name!r}")
    return name


def active_db() -> str:
    """The database every compiled query and context read targets."""
    with _lock:
        return _active


def set_active_db(name: str) -> str:
    with _lock:
        global _active
        _active = check_name(name)
        return _active


def reset_active_db() -> str:
    """Back to the bundled dataset."""
    return set_active_db(settings.ch_db)


def source_db_name() -> str:
    """Where an ingested MySQL source is written. A sibling of the bundled
    database so the two can never overwrite one another."""
    return check_name(f"{settings.ch_db}_mysql")


def is_bundled() -> bool:
    return active_db() == settings.ch_db
