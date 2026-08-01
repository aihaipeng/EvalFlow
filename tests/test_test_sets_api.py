from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from web.app import create_app


def _client(tmp_path):
    application = create_app(
        database_path=tmp_path / "agent-bench.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    return TestClient(application)


def _create_payload(name: str = "客服测试集") -> dict:
    return {
        "name": name,
        "description": "覆盖客服问答",
        "columns": ["col_1", "col_2"],
        "cases": [
            {"values": {"col_1": "问题一", "col_2": "答案一"}},
            {"values": {"col_1": "问题二", "col_2": "答案二"}},
        ],
    }


def test_test_set_api_crud_and_metrics(tmp_path) -> None:
    with _client(tmp_path) as client:
        created_response = client.post("/api/test-sets", json=_create_payload())
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()["test_set"]
        assert "version" not in created
        assert created["columns"] == ["col_1", "col_2"]
        assert len(created["cases"]) == 2

        listed = client.get("/api/test-sets").json()
        assert listed["total"] == 1
        assert listed["metrics"] == {
            "test_set_count": 1,
            "case_count": 2,
            "recent_count": 1,
        }
        assert listed["items"][0]["name"] == "客服测试集"
        assert "version" not in listed["items"][0]

        updated_response = client.put(
            f"/api/test-sets/{created['id']}",
            json={
                "name": "客服测试集修改后",
                "description": "新说明",
                "columns": ["question"],
                "cases": [
                    {
                        "id": created["cases"][0]["id"],
                        "values": {"question": "问题一"},
                    }
                ],
            },
        )
        assert updated_response.status_code == 200, updated_response.text
        updated = updated_response.json()["test_set"]
        assert "version" not in updated
        assert updated["columns"] == ["question"]
        assert updated["cases"][0]["values"] == {"question": "问题一"}

        metadata_response = client.put(
            f"/api/test-sets/{created['id']}/metadata",
            json={"name": "客服回归测试集", "description": "仅更新元数据"},
        )
        assert metadata_response.status_code == 200, metadata_response.text
        metadata_updated = metadata_response.json()["test_set"]
        assert metadata_updated["name"] == "客服回归测试集"
        assert metadata_updated["description"] == "仅更新元数据"
        assert metadata_updated["columns"] == ["question"]
        assert metadata_updated["cases"][0]["values"] == {"question": "问题一"}

        deleted = client.delete(f"/api/test-sets/{created['id']}")
        assert deleted.status_code == 200
        assert client.get(f"/api/test-sets/{created['id']}").status_code == 404


def test_test_set_api_rejects_duplicate_names_invalid_fields_and_legacy_version(tmp_path) -> None:
    with _client(tmp_path) as client:
        assert client.post("/api/test-sets", json=_create_payload()).status_code == 201
        duplicate = client.post("/api/test-sets", json=_create_payload())
        assert duplicate.status_code == 409

        invalid = _create_payload("字段错误")
        invalid["cases"][0]["values"] = {"col_1": "缺少字段"}
        response = client.post("/api/test-sets", json=invalid)
        assert response.status_code == 400

        legacy = {**_create_payload("旧版请求"), "expected_version": 1}
        response = client.put("/api/test-sets/not-found", json=legacy)
        assert response.status_code == 422


def test_test_set_schema_contains_only_runtime_fields(tmp_path) -> None:
    database = tmp_path / "agent-bench.sqlite3"
    with _client(tmp_path):
        pass

    with sqlite3.connect(database) as connection:
        test_sets = [row[1] for row in connection.execute("PRAGMA table_info(test_sets)")]
        columns = [row[1] for row in connection.execute("PRAGMA table_info(test_set_columns)")]
        cases = [row[1] for row in connection.execute("PRAGMA table_info(test_cases)")]

    assert test_sets == [
        "id",
        "name",
        "description",
        "created_at",
        "updated_at",
    ]
    assert columns == ["test_set_id", "position", "column_key"]
    assert cases == ["id", "test_set_id", "position", "values_json"]
