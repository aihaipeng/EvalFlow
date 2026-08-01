"""Shared SQLAlchemy engine and Alembic initialization for the local database."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterator, Sequence

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


class CoreRow(Mapping[str, Any]):
    """Mapping-compatible result row that also retains sqlite3 positional access."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._row[key]
        return self._row._mapping[key]

    def __iter__(self):
        return iter(self._row._mapping)

    def __len__(self) -> int:
        return len(self._row)


class CoreRows:
    def __init__(self, result: Any) -> None:
        self._result = result

    def fetchone(self) -> CoreRow | None:
        row = self._result.fetchone()
        return CoreRow(row) if row is not None else None

    def fetchall(self) -> list[CoreRow]:
        return [CoreRow(row) for row in self._result.fetchall()]

    def __iter__(self):
        return (CoreRow(row) for row in self._result)


class CoreConnection:
    """Small sqlite3-compatible facade backed by a SQLAlchemy Core connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    @property
    def in_transaction(self) -> bool:
        return self._connection.in_transaction()

    def execute(self, statement: str, parameters: Sequence[Any] | None = None):
        normalized = tuple(parameters) if parameters is not None else ()
        result = self._connection.exec_driver_sql(statement, normalized)
        return CoreRows(result) if result.returns_rows else result

    def executemany(self, statement: str, parameters: Any):
        normalized = [tuple(item) for item in parameters]
        if not normalized:
            return None
        return self._connection.exec_driver_sql(statement, normalized)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


@contextmanager
def database_connection(
    database_path: str | Path = DEFAULT_DATABASE_PATH, *, initialize: bool = True
) -> Iterator[CoreConnection]:
    """Yield a configured SQLAlchemy Core connection for repository operations."""

    if initialize:
        upgrade_database(database_path)
    engine = database_engine_for(database_path)
    with engine.connect() as connection:
        facade = CoreConnection(connection)
        try:
            yield facade
        except Exception:
            if facade.in_transaction:
                facade.rollback()
            raise
