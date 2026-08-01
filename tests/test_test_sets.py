from __future__ import annotations

import sqlite3

import pytest

from execution.test_sets import (
    TestSetNameConflictError as NameConflictError,
    TestSetRepository as Repository,
    TestSetRepositoryError as RepositoryError,
)


def _cases(*rows: tuple[str, str]) -> list[dict]:
    return [
        {"values": {"col_1": first, "col_2": second}}
        for first, second in rows
    ]


def test_repository_creates_lists_and_reads_test_sets(tmp_path) -> None:
    repository = Repository(tmp_path / "agent-bench.sqlite3")

    created = repository.create(
        name="客服回归集",
        description="核心客服问答",
        columns=["col_1", "col_2"],
        cases=_cases(("问题一", "答案一"), ("问题二", "答案二")),
    )

    assert [column.key for column in created.columns] == ["col_1", "col_2"]
    assert [case.position for case in created.cases] == [0, 1]
    assert created.cases[0].values == {"col_1": "问题一", "col_2": "答案一"}

    summaries, total = repository.list(name_query="客服")
    assert total == 1
    assert summaries[0].id == created.id
    assert summaries[0].case_count == 2
    assert summaries[0].column_count == 2


def test_repository_updates_full_state_directly(tmp_path) -> None:
    repository = Repository(tmp_path / "agent-bench.sqlite3")
    created = repository.create(
        name="原名称",
        columns=["col_1", "col_2", "col_3"],
        cases=[{"values": {"col_1": "a", "col_2": "b", "col_3": "c"}}],
    )
    existing_id = created.cases[0].id

    updated = repository.update(
        created.id,
        name="新名称",
        description="已编辑",
        columns=["col_1", "col_2"],
        cases=[
            {"id": existing_id, "values": {"col_1": "a", "col_2": "c"}},
            {"values": {"col_1": "next", "col_2": "value"}},
        ],
    )

    assert updated.name == "新名称"
    assert [column.key for column in updated.columns] == ["col_1", "col_2"]
    assert updated.cases[0].id == existing_id
    assert updated.cases[0].values == {"col_1": "a", "col_2": "c"}


def test_repository_skips_blank_cases_on_create_and_update(tmp_path) -> None:
    repository = Repository(tmp_path / "agent-bench.sqlite3")

    created = repository.create(
        name="忽略空白行",
        columns=["col_1", "col_2"],
        cases=[
            {"values": {"col_1": "", "col_2": "  \t"}},
            {"values": {"col_1": "有效值", "col_2": ""}},
        ],
    )

    assert [case.values for case in created.cases] == [
        {"col_1": "有效值", "col_2": ""}
    ]

    updated = repository.update(
        created.id,
        name=created.name,
        description=created.description,
        columns=["col_1", "col_2"],
        cases=[
            {"values": {"col_1": " ", "col_2": ""}},
            {"values": {"col_1": "更新后有效值", "col_2": ""}},
        ],
    )

    assert [case.values for case in updated.cases] == [
        {"col_1": "更新后有效值", "col_2": ""}
    ]


def test_repository_rejects_duplicate_names_and_invalid_case_shapes(tmp_path) -> None:
    repository = Repository(tmp_path / "agent-bench.sqlite3")
    repository.create(name="唯一名称", columns=["col_1"], cases=[])

    with pytest.raises(NameConflictError):
        repository.create(name="唯一名称", columns=["col_1"], cases=[])

    with pytest.raises(NameConflictError):
        repository.create(name="唯一名称".upper(), columns=["col_1"], cases=[])

    with pytest.raises(RepositoryError, match="仅包含"):
        repository.create(
            name="字段错误",
            columns=["col_1", "col_2"],
            cases=[{"values": {"col_1": "missing"}}],
        )


def test_repository_hard_delete_cascades_children(tmp_path) -> None:
    database = tmp_path / "agent-bench.sqlite3"
    repository = Repository(database)
    created = repository.create(
        name="待删除",
        columns=["col_1", "col_2"],
        cases=_cases(("a", "b")),
    )

    assert repository.delete(created.id) is True
    assert repository.get(created.id) is None
    assert repository.delete(created.id) is False

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM test_set_columns").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM test_cases").fetchone()[0] == 0


def test_repository_removes_legacy_version_column_without_data_loss(tmp_path) -> None:
    database = tmp_path / "agent-bench.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE test_sets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE test_set_columns (
                test_set_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                column_key TEXT NOT NULL,
                PRIMARY KEY(test_set_id, position),
                UNIQUE(test_set_id, column_key),
                FOREIGN KEY(test_set_id) REFERENCES test_sets(id) ON DELETE CASCADE
            );
            CREATE TABLE test_cases (
                id TEXT PRIMARY KEY,
                test_set_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                values_json TEXT NOT NULL,
                UNIQUE(test_set_id, position),
                FOREIGN KEY(test_set_id) REFERENCES test_sets(id) ON DELETE CASCADE
            );
            INSERT INTO test_sets VALUES ('set-1', '历史测试集', '保留数据', 8, '2026-07-01', '2026-07-02');
            INSERT INTO test_set_columns VALUES ('set-1', 0, 'col_1');
            INSERT INTO test_cases VALUES ('case-1', 'set-1', 0, '{"col_1":"value"}');
            """
        )

    repository = Repository(database)
    record = repository.get("set-1")

    assert record is not None
    assert record.name == "历史测试集"
    assert record.cases[0].values == {"col_1": "value"}
    with sqlite3.connect(database) as connection:
        fields = [row[1] for row in connection.execute("PRAGMA table_info(test_sets)")]
    assert "version" not in fields
