"""SQLite-backed test-set storage used by management and batch execution."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    CoreConnection,
    database_connection,
    database_initialize_lock_for,
    upgrade_database,
)
from execution.time_utils import utc_now_iso


class TestSetRepositoryError(RuntimeError):
    """Base error for persisted test-set operations."""


class TestSetNameConflictError(TestSetRepositoryError):
    """Raised when a test-set name is already in use."""



@dataclass(frozen=True)
class TestSetColumn:
    key: str
    position: int


@dataclass(frozen=True)
class TestCaseRecord:
    id: str
    position: int
    values: dict[str, str]


@dataclass(frozen=True)
class TestSetSummary:
    id: str
    name: str
    description: str
    case_count: int
    column_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TestSetRecord:
    id: str
    name: str
    description: str
    columns: tuple[TestSetColumn, ...]
    cases: tuple[TestCaseRecord, ...]
    created_at: str
    updated_at: str


def _normalize_name(value: str) -> str:
    name = value.strip()[:120]
    if not name:
        raise TestSetRepositoryError("测试集名称不能为空")
    return name


def _normalize_description(value: str | None) -> str:
    return (value or "").strip()[:1000]


def _normalize_columns(columns: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(column).strip()[:120] for column in columns)
    if not normalized or any(not column for column in normalized):
        raise TestSetRepositoryError("测试集至少需要一个非空字段")
    if len(set(normalized)) != len(normalized):
        raise TestSetRepositoryError("测试集字段名不能重复")
    return normalized


def _normalize_cases(
    cases: Sequence[dict[str, Any]], columns: Sequence[str]
) -> tuple[tuple[str, dict[str, str]], ...]:
    expected_keys = set(columns)
    normalized: list[tuple[str, dict[str, str]]] = []
    seen_ids: set[str] = set()
    for item in cases:
        raw_values = item.get("values")
        if not isinstance(raw_values, dict):
            raise TestSetRepositoryError("用例 values 必须是对象")
        if set(raw_values) != expected_keys:
            raise TestSetRepositoryError("每条用例必须包含且仅包含当前测试集字段")
        values = {
            key: "" if raw_values[key] is None else str(raw_values[key])
            for key in columns
        }
        if not any(value.strip() for value in values.values()):
            continue
        case_id = str(item.get("id") or uuid4())
        if case_id in seen_ids:
            raise TestSetRepositoryError("用例 ID 不能重复")
        seen_ids.add(case_id)
        normalized.append((case_id, values))
    return tuple(normalized)


class TestSetRepository:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH):
        self.database_path = Path(database_path).resolve()
        self._initialize_lock = database_initialize_lock_for(self.database_path)
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            upgrade_database(self.database_path)
            self._initialized = True

    def create(
        self,
        *,
        name: str,
        description: str = "",
        columns: Sequence[str],
        cases: Sequence[dict[str, Any]],
    ) -> TestSetRecord:
        normalized_name = _normalize_name(name)
        normalized_description = _normalize_description(description)
        normalized_columns = _normalize_columns(columns)
        normalized_cases = _normalize_cases(cases, normalized_columns)
        test_set_id = str(uuid4())
        now = utc_now_iso()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO test_sets(id, name, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (test_set_id, normalized_name, normalized_description, now, now),
                )
                self._replace_children(
                    connection, test_set_id, normalized_columns, normalized_cases
                )
                connection.commit()
        except IntegrityError as exc:
            if "test_sets.name" in str(exc):
                raise TestSetNameConflictError("测试集名称已存在") from exc
            raise TestSetRepositoryError(f"创建测试集失败: {exc}") from exc
        record = self.get(test_set_id)
        if record is None:
            raise TestSetRepositoryError("创建测试集后读取失败")
        return record

    def list(
        self, *, page: int = 1, page_size: int = 20, name_query: str = ""
    ) -> tuple[list[TestSetSummary], int]:
        query = name_query.strip().casefold()
        where = ""
        params: list[Any] = []
        if query:
            where = "WHERE lower(ts.name) LIKE ? OR lower(ts.description) LIKE ?"
            pattern = f"%{query}%"
            params.extend((pattern, pattern))
        offset = (page - 1) * page_size
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM test_sets ts {where}", params
            ).fetchone()["COUNT(*)"]
            rows = connection.execute(
                f"""
                SELECT ts.*,
                       COUNT(DISTINCT tc.id) AS case_count,
                       COUNT(DISTINCT tsc.position) AS column_count
                FROM test_sets ts
                LEFT JOIN test_cases tc ON tc.test_set_id = ts.id
                LEFT JOIN test_set_columns tsc ON tsc.test_set_id = ts.id
                {where}
                GROUP BY ts.id
                ORDER BY ts.updated_at DESC, ts.id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        return [self._summary_from_row(row) for row in rows], int(total)

    def metrics(self) -> dict[str, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(
            timespec="milliseconds"
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS test_set_count,
                    COALESCE((SELECT COUNT(*) FROM test_cases), 0) AS case_count,
                    SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS recent_count
                FROM test_sets
                """,
                (cutoff,),
            ).fetchone()
        return {
            "test_set_count": int(row["test_set_count"]),
            "case_count": int(row["case_count"]),
            "recent_count": int(row["recent_count"] or 0),
        }

    def get(self, test_set_id: str) -> TestSetRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM test_sets WHERE id = ?", (test_set_id,)
            ).fetchone()
            if row is None:
                return None
            columns = connection.execute(
                """
                SELECT column_key, position FROM test_set_columns
                WHERE test_set_id = ? ORDER BY position
                """,
                (test_set_id,),
            ).fetchall()
            cases = connection.execute(
                """
                SELECT id, position, values_json FROM test_cases
                WHERE test_set_id = ? ORDER BY position
                """,
                (test_set_id,),
            ).fetchall()
        return TestSetRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            columns=tuple(
                TestSetColumn(key=item["column_key"], position=int(item["position"]))
                for item in columns
            ),
            cases=tuple(
                TestCaseRecord(
                    id=item["id"],
                    position=int(item["position"]),
                    values=json.loads(item["values_json"]),
                )
                for item in cases
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update(
        self,
        test_set_id: str,
        *,
        name: str,
        description: str,
        columns: Sequence[str],
        cases: Sequence[dict[str, Any]],
    ) -> TestSetRecord:
        normalized_name = _normalize_name(name)
        normalized_description = _normalize_description(description)
        normalized_columns = _normalize_columns(columns)
        normalized_cases = _normalize_cases(cases, normalized_columns)
        now = utc_now_iso()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE test_sets
                    SET name = ?, description = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (normalized_name, normalized_description, now, test_set_id),
                )
                if cursor.rowcount == 0:
                    raise TestSetRepositoryError("测试集不存在")
                self._replace_children(
                    connection, test_set_id, normalized_columns, normalized_cases
                )
                connection.commit()
        except IntegrityError as exc:
            if "test_sets.name" in str(exc):
                raise TestSetNameConflictError("测试集名称已存在") from exc
            raise TestSetRepositoryError(f"更新测试集失败: {exc}") from exc
        record = self.get(test_set_id)
        if record is None:
            raise TestSetRepositoryError("更新测试集后读取失败")
        return record

    def update_metadata(
        self,
        test_set_id: str,
        *,
        name: str,
        description: str,
    ) -> TestSetRecord:
        normalized_name = _normalize_name(name)
        normalized_description = _normalize_description(description)
        now = utc_now_iso()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE test_sets
                    SET name = ?, description = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (normalized_name, normalized_description, now, test_set_id),
                )
                if cursor.rowcount == 0:
                    raise TestSetRepositoryError("测试集不存在")
                connection.commit()
        except IntegrityError as exc:
            if "test_sets.name" in str(exc):
                raise TestSetNameConflictError("测试集名称已存在") from exc
            raise TestSetRepositoryError(f"更新测试集元数据失败: {exc}") from exc
        record = self.get(test_set_id)
        if record is None:
            raise TestSetRepositoryError("更新测试集元数据后读取失败")
        return record

    def delete(self, test_set_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM test_sets WHERE id = ?", (test_set_id,)
            )
            connection.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _replace_children(
        connection: CoreConnection,
        test_set_id: str,
        columns: Sequence[str],
        cases: Sequence[tuple[str, dict[str, str]]],
    ) -> None:
        connection.execute(
            "DELETE FROM test_set_columns WHERE test_set_id = ?", (test_set_id,)
        )
        connection.execute(
            "DELETE FROM test_cases WHERE test_set_id = ?", (test_set_id,)
        )
        connection.executemany(
            """
            INSERT INTO test_set_columns(test_set_id, position, column_key)
            VALUES (?, ?, ?)
            """,
            ((test_set_id, index, key) for index, key in enumerate(columns)),
        )
        connection.executemany(
            """
            INSERT INTO test_cases(id, test_set_id, position, values_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                (
                    case_id,
                    test_set_id,
                    index,
                    json.dumps(values, ensure_ascii=False, separators=(",", ":")),
                )
                for index, (case_id, values) in enumerate(cases)
            ),
        )

    @contextmanager
    def _connect(self, *, initialize: bool = True) -> Iterator[CoreConnection]:
        if initialize:
            self.initialize()
        with database_connection(self.database_path, initialize=False) as connection:
            yield connection

    @staticmethod
    def _summary_from_row(row: Any) -> TestSetSummary:
        return TestSetSummary(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            case_count=int(row["case_count"]),
            column_count=int(row["column_count"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
