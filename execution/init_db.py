"""Shared SQLAlchemy engine and Alembic initialization for the local database."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool


DEFAULT_DATABASE_PATH = (
    Path(__file__).resolve().parents[1] / "run_storage" / "agent_bench.sqlite3"
)
ALEMBIC_INI_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"

_INITIALIZE_LOCKS_GUARD = threading.Lock()
_INITIALIZE_LOCKS: dict[Path, threading.RLock] = {}
_ENGINES_GUARD = threading.Lock()
_ENGINES: dict[Path, Engine] = {}


def database_initialize_lock_for(database_path: str | Path) -> threading.RLock:
    """Return the shared initialization lock for a SQLite database file."""

    resolved_path = Path(database_path).resolve()
    with _INITIALIZE_LOCKS_GUARD:
        return _INITIALIZE_LOCKS.setdefault(resolved_path, threading.RLock())


def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


def database_engine_for(database_path: str | Path) -> Engine:
    """Return the shared SQLAlchemy Engine for one resolved SQLite file."""

    resolved_path = Path(database_path).resolve()
    with _ENGINES_GUARD:
        engine = _ENGINES.get(resolved_path)
        if engine is None:
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                f"sqlite:///{resolved_path.as_posix()}",
                connect_args={"timeout": 30},
                poolclass=NullPool,
            )
            event.listen(engine, "connect", _configure_sqlite)
            _ENGINES[resolved_path] = engine
        return engine


@contextmanager
def database_read_connection(
    database_path: str | Path = DEFAULT_DATABASE_PATH, *, initialize: bool = True
) -> Iterator[Connection]:
    """Yield a native SQLAlchemy connection for Core read statements."""

    if initialize:
        upgrade_database(database_path)
    with database_engine_for(database_path).connect() as connection:
        yield connection


@contextmanager
def database_transaction(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    *,
    initialize: bool = True,
    immediate: bool = False,
) -> Iterator[Connection]:
    """Commit a Core transaction on success and roll it back on failure."""

    if initialize:
        upgrade_database(database_path)
    with database_engine_for(database_path).connect() as connection:
        if immediate:
            # SQLite has no Core expression for its writer-locking transaction mode.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.begin()
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()


def upgrade_database(database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
    """Upgrade a database to the latest application schema through Alembic."""

    resolved_path = Path(database_path).resolve()
    with database_initialize_lock_for(resolved_path):
        engine = database_engine_for(resolved_path)
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
            connection.commit()
            config = Config(str(ALEMBIC_INI_PATH))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.commit()
