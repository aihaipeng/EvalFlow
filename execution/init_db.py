"""Shared SQLite database path and initialization helpers."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


DEFAULT_DATABASE_PATH = (
    Path(__file__).resolve().parents[1] / "run_storage" / "agent_bench.sqlite3"
)

_INITIALIZE_LOCKS_GUARD = threading.Lock()
_INITIALIZE_LOCKS: dict[Path, threading.RLock] = {}


def database_initialize_lock_for(database_path: str | Path) -> threading.RLock:
    """Return the shared initialization lock for a SQLite database file."""

    resolved_path = Path(database_path).resolve()
    with _INITIALIZE_LOCKS_GUARD:
        return _INITIALIZE_LOCKS.setdefault(resolved_path, threading.RLock())


def initialize_sqlite_pragmas(connection: sqlite3.Connection) -> None:
    """Persist database-level settings required before repository schema setup."""

    connection.execute("PRAGMA journal_mode = WAL")
    configure_sqlite_connection(connection)


def configure_sqlite_connection(
    connection: sqlite3.Connection, *, foreign_keys: bool = False
) -> None:
    """Apply per-connection SQLite settings used by repository operations."""

    connection.execute("PRAGMA synchronous = NORMAL")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")
