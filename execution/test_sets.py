"""SQLite-backed test-set storage used by management and batch execution."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from uuid import uuid4

from sqlalchemy import case, delete, func, insert, or_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from execution.database_schema import test_cases, test_set_columns, test_sets

from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    database_read_connection,
    database_transaction,
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
            with self._transaction() as connection:
                connection.execute(insert(test_sets).values(
                    id=test_set_id,
                    name=normalized_name,
                    description=normalized_description,
                    created_at=now,
                    updated_at=now,
                ))
                self._replace_children(
                    connection, test_set_id, normalized_columns, normalized_cases
                )
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
        predicate = None
        if query:
            pattern = f"%{query}%"
            predicate = or_(
                func.lower(test_sets.c.name).like(pattern),
                func.lower(test_sets.c.description).like(pattern),
            )
        offset = (page - 1) * page_size
        case_counts = (
            select(
                test_cases.c.test_set_id,
                func.count(test_cases.c.id).label("case_count"),
            )
            .group_by(test_cases.c.test_set_id)
            .subquery()
        )
        column_counts = (
            select(
                test_set_columns.c.test_set_id,
                func.count(test_set_columns.c.position).label("column_count"),
            )
            .group_by(test_set_columns.c.test_set_id)
            .subquery()
        )
        count_statement = select(func.count()).select_from(test_sets)
        list_statement = (
            select(
                test_sets,
                func.coalesce(case_counts.c.case_count, 0).label("case_count"),
                func.coalesce(column_counts.c.column_count, 0).label("column_count"),
            )
            .outerjoin(case_counts, case_counts.c.test_set_id == test_sets.c.id)
            .outerjoin(column_counts, column_counts.c.test_set_id == test_sets.c.id)
        )
        if predicate is not None:
            count_statement = count_statement.where(predicate)
            list_statement = list_statement.where(predicate)
        list_statement = list_statement.order_by(
            test_sets.c.updated_at.desc(), test_sets.c.id.desc()
        ).limit(page_size).offset(offset)
        with self._connect() as connection:
            total = connection.execute(count_statement).scalar_one()
            rows = connection.execute(list_statement).mappings().all()
        return [self._summary_from_row(row) for row in rows], int(total)

    def metrics(self) -> dict[str, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(
            timespec="milliseconds"
        )
        with self._connect() as connection:
            row = connection.execute(
                select(
                    func.count(test_sets.c.id).label("test_set_count"),
                    select(func.count(test_cases.c.id))
                    .scalar_subquery()
                    .label("case_count"),
                    func.coalesce(
                        func.sum(case((test_sets.c.created_at >= cutoff, 1), else_=0)),
                        0,
                    ).label("recent_count"),
                )
            ).mappings().one()
        return {
            "test_set_count": int(row["test_set_count"]),
            "case_count": int(row["case_count"]),
            "recent_count": int(row["recent_count"] or 0),
        }

    def get(self, test_set_id: str) -> TestSetRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                select(test_sets).where(test_sets.c.id == test_set_id)
            ).mappings().first()
            if row is None:
                return None
            columns = connection.execute(
                select(test_set_columns.c.column_key, test_set_columns.c.position)
                .where(test_set_columns.c.test_set_id == test_set_id)
                .order_by(test_set_columns.c.position)
            ).mappings().all()
            cases = connection.execute(
                select(test_cases.c.id, test_cases.c.position, test_cases.c.values_json)
                .where(test_cases.c.test_set_id == test_set_id)
                .order_by(test_cases.c.position)
            ).mappings().all()
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
            with self._transaction() as connection:
                cursor = connection.execute(
                    update(test_sets)
                    .where(test_sets.c.id == test_set_id)
                    .values(
                        name=normalized_name,
                        description=normalized_description,
                        updated_at=now,
                    )
                )
                if cursor.rowcount == 0:
                    raise TestSetRepositoryError("测试集不存在")
                self._replace_children(
                    connection, test_set_id, normalized_columns, normalized_cases
                )
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
            with self._transaction() as connection:
                cursor = connection.execute(
                    update(test_sets)
                    .where(test_sets.c.id == test_set_id)
                    .values(
                        name=normalized_name,
                        description=normalized_description,
                        updated_at=now,
                    )
                )
                if cursor.rowcount == 0:
                    raise TestSetRepositoryError("测试集不存在")
        except IntegrityError as exc:
            if "test_sets.name" in str(exc):
                raise TestSetNameConflictError("测试集名称已存在") from exc
            raise TestSetRepositoryError(f"更新测试集元数据失败: {exc}") from exc
        record = self.get(test_set_id)
        if record is None:
            raise TestSetRepositoryError("更新测试集元数据后读取失败")
        return record

    def delete(self, test_set_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                delete(test_sets).where(test_sets.c.id == test_set_id)
            )
        return cursor.rowcount > 0

    @staticmethod
    def _replace_children(
        connection: Connection,
        test_set_id: str,
        columns: Sequence[str],
        cases: Sequence[tuple[str, dict[str, str]]],
    ) -> None:
        connection.execute(
            delete(test_set_columns).where(test_set_columns.c.test_set_id == test_set_id)
        )
        connection.execute(
            delete(test_cases).where(test_cases.c.test_set_id == test_set_id)
        )
        column_rows = [
            {"test_set_id": test_set_id, "position": index, "column_key": key}
            for index, key in enumerate(columns)
        ]
        if column_rows:
            connection.execute(insert(test_set_columns), column_rows)
        case_rows = [
            {
                "id": case_id,
                "test_set_id": test_set_id,
                "position": index,
                "values_json": json.dumps(
                    values, ensure_ascii=False, separators=(",", ":")
                ),
            }
            for index, (case_id, values) in enumerate(cases)
        ]
        if case_rows:
            connection.execute(insert(test_cases), case_rows)

    @contextmanager
    def _connect(self, *, initialize: bool = True) -> Iterator[Connection]:
        if initialize:
            self.initialize()
        with database_read_connection(self.database_path, initialize=False) as connection:
            yield connection

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        self.initialize()
        with database_transaction(self.database_path, initialize=False) as connection:
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
