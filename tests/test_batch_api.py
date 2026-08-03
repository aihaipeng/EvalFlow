import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from web.app import create_app
from web.routes_batch_runs import _batch_case_result, _batch_list_activity_times


def _workflow_body(name: str = "Batch API Workflow") -> dict:
    start_id, script_id, end_id = (str(uuid4()) for _ in range(3))
    return {
        "name": name, "description": "",
        "nodes": [
            {"node": {"id": start_id, "type": "START", "name": "START", "description": "", "inputs": [{"name": "input", "type": "object", "value": {}}]}, "position_x": 0, "position_y": 0},
            {"node": {"id": script_id, "type": "SCRIPT", "name": "SCRIPT", "description": "", "script": 'result = context["question"].upper()', "outputs": [{"name": "answer", "type": "string", "source": "result"}]}, "position_x": 200, "position_y": 0},
            {"node": {"id": end_id, "type": "END", "name": "END", "description": "", "outputs": [{"name": "answer", "type": "string", "source": "answer"}]}, "position_x": 400, "position_y": 0},
        ],
        "edges": [
            {"id": str(uuid4()), "source_node_id": start_id, "target_node_id": script_id},
            {"id": str(uuid4()), "source_node_id": script_id, "target_node_id": end_id},
        ],
    }


def _create_workflow(client: TestClient, body: dict | None = None) -> str:
    response = client.post("/api/workflows", json=body or _workflow_body())
    assert response.status_code == 201, response.text
    return response.json()["workflow"]["workflow"]["id"]


def _create_test_set(client: TestClient, name: str = "数据库测试集") -> str:
    response = client.post("/api/test-sets", json={
        "name": name, "description": "", "columns": ["question", "expected"],
        "cases": [
            {"id": "case-1", "values": {"question": "hello", "expected": "HELLO"}},
            {"id": "case-2", "values": {"question": "world", "expected": "WORLD"}},
        ],
    })
    assert response.status_code == 201, response.text
    return response.json()["test_set"]["id"]


def _batch_body(
    test_set_id: str, workflow_id: str, name: str = "API Run", call_order: str = "SEQUENTIAL"
) -> dict:
    return {
        "name": name, "description": "用于回归裁判模型",
        "test_set_id": test_set_id, "workflow_id": workflow_id,
        "variables": [{"source": "TEST_SET", "key": "question", "value": "question", "type": "string"}],
        "case_concurrency": 2,
        "failure_retry_count": 2,
        "call_order": call_order,
        "evaluation_rules": [],
        "case_display_column": "question",
        "rule_display_column": "expected",
    }


def test_batch_list_activity_times_include_historical_case_runs():
    batch = {
        "started_at": "2026-07-31T08:00:00+00:00",
        "finished_at": "2026-07-31T08:10:00+00:00",
    }
    cases = [
        {
            "status": "SUCCESS",
            "execution_status": "SUCCESS",
            "started_at": "2026-08-01T09:00:00+00:00",
            "finished_at": "2026-08-01T09:05:00+00:00",
        }
    ]

    assert _batch_list_activity_times(batch, cases) == (
        "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:05:00+00:00",
    )
    cases[0]["status"] = "RUNNING"
    cases[0]["execution_status"] = "RUNNING"
    cases[0]["finished_at"] = None
    assert _batch_list_activity_times(batch, cases) == (
        "2026-08-01T09:00:00+00:00",
        None,
    )


def test_batch_case_result_excludes_unfinished_and_interrupted_cases():
    for status, execution_status in [
        ("QUEUED", "NOT_STARTED"),
        ("RUNNING", "RUNNING"),
        ("INTERRUPTED", "INTERRUPTED"),
    ]:
        assert _batch_case_result(
            {
                "status": status,
                "execution_status": execution_status,
                "evaluation": {"verdict": "NOT_EVALUATED"},
            }
        ) is None

    assert _batch_case_result(
        {
            "status": "FAILED",
            "execution_status": "FAILED",
            "evaluation": {"verdict": "NOT_EVALUATED"},
        }
    ) == "Error"


def test_batch_copy_name_api_keeps_appending_until_unique(tmp_path: Path):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        source = client.post(
            "/api/batch-runs",
            json=_batch_body(test_set_id, workflow_id, "诊断任务"),
        ).json()["batch"]
        for name in ("诊断任务_copy", "诊断任务_copy_copy"):
            response = client.post(
                "/api/batch-runs",
                json=_batch_body(test_set_id, workflow_id, name),
            )
            assert response.status_code == 201, response.text

        copy_name = client.get(
            f"/api/batch-runs/{source['id']}/copy-name"
        )

    assert copy_name.status_code == 200
    assert copy_name.json() == {"name": "诊断任务_copy_copy_copy"}


def test_batch_api_previews_database_set_creates_starts_and_traces_cases(tmp_path: Path):
    application = create_app(database_path=tmp_path / "database.sqlite3", execution_root=tmp_path / "workflow-executions")
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)

        preview = client.post("/api/batch-runs/preview", json={"test_set_id": test_set_id})
        assert preview.status_code == 200, preview.text
        assert preview.json()["test_set_id"] == test_set_id
        assert preview.json()["headers"] == ["question", "expected"]
        assert preview.json()["total_rows"] == 2
        assert "sheet_name" not in preview.json()
        assert "header_mode" not in preview.json()

        created = client.post("/api/batch-runs", json=_batch_body(test_set_id, workflow_id))
        assert created.status_code == 201, created.text
        batch = created.json()["batch"]
        batch_id = batch["id"]
        created_at = batch["created_at"]
        updated_at = batch["updated_at"]
        assert batch["input"]["test_set_id"] == test_set_id
        assert batch["input"]["test_set_name"] == "数据库测试集"
        assert batch["description"] == "用于回归裁判模型"
        assert batch["failure_retry_count"] == 2
        assert batch["input"]["display_columns"] == {"case": "question", "rule": "expected"}
        assert "filename" not in batch["input"]
        assert "sheet_name" not in batch["input"]
        listed = client.get("/api/batch-runs").json()["batches"][0]
        assert listed["created_at"] == created_at
        assert listed["updated_at"] == updated_at
        assert listed["started_at"] is None
        assert listed["finished_at"] is None

        started = client.post(f"/api/batch-runs/{batch_id}/start")
        assert started.status_code == 202, started.text
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            batch = client.get(f"/api/batch-runs/{batch_id}").json()["batch"]
            if batch["status"] == "SUCCESS":
                break
            time.sleep(0.03)
        assert batch["summary"]["success"] == 2
        listed = client.get("/api/batch-runs").json()["batches"][0]
        assert listed["summary"]["success"] == 2
        assert listed["started_at"] == batch["started_at"]
        assert listed["finished_at"] == batch["finished_at"]
        assert listed["created_at"] == created_at
        assert listed["updated_at"] == updated_at
        cases = client.get(f"/api/batch-runs/{batch_id}/cases").json()["cases"]
        assert [case["case_id"] for case in cases] == ["case-1", "case-2"]
        assert [case["row_number"] for case in cases] == [1, 2]
        assert all(len(case["workflow_execution_ids"]) == 1 for case in cases)
        assert [case["initial_context"] for case in cases] == [
            {"question": "hello"},
            {"question": "world"},
        ]
        assert all("start_inputs" not in case for case in cases)
        execution = client.get(
            f"/api/workflows/{workflow_id}/runs/{cases[0]['workflow_execution_ids'][0]}"
        ).json()["execution"]
        assert execution["context"]["initial"] == {"question": "hello"}

        assert client.delete(f"/api/batch-runs/{batch_id}").status_code == 200
        assert client.delete(f"/api/workflows/{workflow_id}").status_code == 200


def test_batch_rule_display_column_is_optional_and_does_not_fallback(tmp_path: Path):
    application = create_app(database_path=tmp_path / "database.sqlite3", execution_root=tmp_path / "workflow-executions")
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        body = _batch_body(test_set_id, workflow_id, "Optional Rule Column")
        body["rule_display_column"] = ""

        created = client.post("/api/batch-runs", json=body)

        assert created.status_code == 201, created.text
        batch = created.json()["batch"]
        assert batch["input"]["display_columns"] == {"case": "question", "rule": None}
        assert batch["configuration"]["rule_display_column"] is None


def test_external_context_requirements_allow_draft_but_block_start_and_schedule_enable(
    tmp_path: Path,
):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_body = _workflow_body("External Context Workflow")
        business = workflow_body["nodes"][1]["node"]
        business_id = business["id"]
        business.clear()
        business.update(
            {
                "id": business_id,
                "type": "HTTP",
                "name": "外部变量请求",
                "description": "",
                "request": {
                    "url": "https://example.invalid/${tenant}/${payload.items[0]}"
                },
            }
        )
        workflow_id = _create_workflow(client, workflow_body)
        test_set_id = _create_test_set(client)

        created = client.post(
            "/api/batch-runs",
            json=_batch_body(test_set_id, workflow_id, "Missing External Variables"),
        )

        assert created.status_code == 201, created.text
        batch_id = created.json()["batch"]["id"]
        disabled = client.put(
            f"/api/batch-runs/{batch_id}/schedule",
            json={
                "enabled": False,
                "cadence": "DAILY",
                "run_at": "",
                "run_time": "09:00",
                "weekdays": ["1"],
                "month_day": 1,
                "timezone": "UTC",
                "overlap_policy": "SKIP",
            },
        )
        assert disabled.status_code == 200, disabled.text

        started = client.post(f"/api/batch-runs/{batch_id}/start")
        assert started.status_code == 400
        assert "payload" in started.text
        assert "tenant" in started.text
        assert "任务变量未声明" in started.text
        assert (
            client.get(f"/api/batch-runs/{batch_id}").json()["batch"]["status"]
            == "QUEUED"
        )

        run_at = (datetime.now(UTC) + timedelta(minutes=5)).replace(
            tzinfo=None
        ).isoformat(timespec="milliseconds")
        enabled = client.put(
            f"/api/batch-runs/{batch_id}/schedule",
            json={
                "enabled": True,
                "cadence": "ONCE",
                "run_at": run_at,
                "run_time": "09:00",
                "weekdays": [],
                "month_day": 1,
                "timezone": "UTC",
                "overlap_policy": "SKIP",
            },
        )
        assert enabled.status_code == 400
        assert "payload" in enabled.text
        assert "tenant" in enabled.text
        assert "任务变量未声明" in enabled.text
        assert client.get(
            f"/api/batch-runs/{batch_id}/schedule"
        ).json()["schedule"]["enabled"] is False

        updated_body = _batch_body(
            test_set_id, workflow_id, "Wrong External Variable Type"
        )
        updated_body["variables"].extend(
            [
                {
                    "source": "CUSTOM",
                    "key": "tenant",
                    "value": "east",
                    "type": "string",
                },
                {
                    "source": "CUSTOM",
                    "key": "payload",
                    "value": "not-an-object",
                    "type": "string",
                },
            ]
        )
        saved = client.put(f"/api/batch-runs/{batch_id}", json=updated_body)
        assert saved.status_code == 200, saved.text

        wrong_type = client.post(f"/api/batch-runs/{batch_id}/start")
        assert wrong_type.status_code == 400
        assert "payload" in wrong_type.text
        assert "object 或 array" in wrong_type.text
        assert "当前类型为 string" in wrong_type.text


def test_batch_schedule_api_persists_and_triggers_once_while_app_is_running(tmp_path: Path):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        batch = client.post(
            "/api/batch-runs",
            json=_batch_body(test_set_id, workflow_id, "Scheduled Task"),
        ).json()["batch"]
        run_at = (datetime.now(UTC) + timedelta(seconds=1.5)).replace(
            tzinfo=None
        ).isoformat(timespec="milliseconds")

        saved = client.put(
            f"/api/batch-runs/{batch['id']}/schedule",
            json={
                "enabled": True,
                "cadence": "ONCE",
                "run_at": run_at,
                "run_time": "09:00",
                "weekdays": ["1", "2", "3", "4", "5"],
                "month_day": 1,
                "timezone": "UTC",
                "overlap_policy": "SKIP",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["schedule"]["enabled"] is True
        listed = client.get("/api/batch-runs").json()["batches"][0]
        assert listed["schedule"]["batch_id"] == batch["id"]

        deadline = time.monotonic() + 10
        current = None
        while time.monotonic() < deadline:
            current = client.get(f"/api/batch-runs/{batch['id']}").json()["batch"]
            if current["status"] == "SUCCESS":
                break
            time.sleep(0.05)

        assert current and current["status"] == "SUCCESS"
        schedule = client.get(
            f"/api/batch-runs/{batch['id']}/schedule"
        ).json()["schedule"]
        assert schedule["enabled"] is False
        assert schedule["next_run_at"] is None
        assert schedule["last_run_at"] is not None
        assert schedule["last_error"] is None


def test_batch_schedule_survives_application_restart(tmp_path: Path):
    database_path = tmp_path / "database.sqlite3"
    execution_root = tmp_path / "workflow-executions"
    application = create_app(database_path=database_path, execution_root=execution_root)
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        batch_id = client.post(
            "/api/batch-runs",
            json=_batch_body(test_set_id, workflow_id, "Persistent Schedule"),
        ).json()["batch"]["id"]
        saved = client.put(
            f"/api/batch-runs/{batch_id}/schedule",
            json={
                "enabled": True,
                "cadence": "DAILY",
                "run_at": "",
                "run_time": "23:59",
                "weekdays": ["1", "2", "3", "4", "5"],
                "month_day": 1,
                "timezone": "UTC",
                "overlap_policy": "QUEUE",
            },
        ).json()["schedule"]

    restarted = create_app(database_path=database_path, execution_root=execution_root)
    with TestClient(restarted) as client:
        restored = client.get(
            f"/api/batch-runs/{batch_id}/schedule"
        ).json()["schedule"]

    assert restored["enabled"] is True
    assert restored["overlap_policy"] == "QUEUE"
    assert restored["next_run_at"] == saved["next_run_at"]


def test_batch_api_rejects_legacy_excel_fields_and_unknown_test_set_mapping(tmp_path: Path):
    application = create_app(database_path=tmp_path / "database.sqlite3", execution_root=tmp_path / "workflow-executions")
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        legacy = client.post("/api/batch-runs/preview", json={"filename": "cases.xlsx", "sheet_name": "Cases"})
        assert legacy.status_code == 422
        invalid = client.post("/api/batch-runs", json={
            **_batch_body(test_set_id, workflow_id),
            "variables": [{"source": "TEST_SET", "key": "question", "value": "missing", "type": "string"}],
        })
        assert invalid.status_code == 400
        assert "测试集字段不存在" in invalid.text


def test_batch_api_preserves_optional_evaluation_rule_name(tmp_path: Path):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        body = _batch_body(test_set_id, workflow_id, "Named Rule Run")
        body["evaluation_rules"] = [
            {
                "name": "回答状态",
                "result_path": "answer",
                "operator": "EQ",
                "expected_value": "HELLO",
                "type": "string",
            },
            {
                "name": "回答非空",
                "result_path": "answer",
                "operator": "NOT_EMPTY",
                "expected_value": "",
                "type": "string",
            },
        ]

        response = client.post("/api/batch-runs", json=body)

        assert response.status_code == 201, response.text
        batch = response.json()["batch"]
        assert batch["evaluation_rules"][0]["name"] == "回答状态"
        assert batch["evaluation_rules"][0]["result_path"] == "context.answer"
        assert batch["evaluation_rules"][1]["operator"] == "NOT_EMPTY"


def test_edit_run_uses_latest_test_set_and_workflow_but_preserves_original_snapshot(tmp_path: Path):
    application = create_app(database_path=tmp_path / "database.sqlite3", execution_root=tmp_path / "workflow-executions")
    with TestClient(application) as client:
        workflow_body = _workflow_body()
        workflow_id = _create_workflow(client, workflow_body)
        test_set_id = _create_test_set(client)
        original = client.post("/api/batch-runs", json=_batch_body(test_set_id, workflow_id, "Original Run"))
        assert original.status_code == 201, original.text
        original_id = original.json()["batch"]["id"]

        test_set = client.get(f"/api/test-sets/{test_set_id}").json()["test_set"]
        test_set["cases"][0]["values"]["question"] = "changed"
        updated_set = client.put(f"/api/test-sets/{test_set_id}", json={
            "name": "数据库测试集 v2", "description": "", "columns": test_set["columns"],
            "cases": [{"id": case["id"], "values": case["values"]} for case in test_set["cases"]],
        })
        assert updated_set.status_code == 200

        workflow_body["name"] = "Batch API Workflow v2"
        script = next(item["node"] for item in workflow_body["nodes"] if item["node"]["type"] == "SCRIPT")
        script["script"] = 'result = "v2:" + context["question"]'
        assert client.put(f"/api/workflows/{workflow_id}", json=workflow_body).status_code == 200

        refreshed_list_item = client.get("/api/batch-runs").json()["batches"][0]
        assert refreshed_list_item["input"]["test_set_name"] == "数据库测试集 v2"
        assert refreshed_list_item["workflow"]["name"] == "Batch API Workflow v2"

        edited = client.post("/api/batch-runs", json=_batch_body(test_set_id, workflow_id, "Edited Run"))
        assert edited.status_code == 201, edited.text
        edited_batch = edited.json()["batch"]
        original_batch = client.get(f"/api/batch-runs/{original_id}").json()["batch"]
        assert edited_batch["workflow"]["name"] == "Batch API Workflow v2"
        assert edited_batch["input"]["test_set_name"] == "数据库测试集 v2"
        assert original_batch["workflow"]["name"] == "Batch API Workflow"
        assert original_batch["input"]["test_set_name"] == "数据库测试集"
        original_case = client.get(f"/api/batch-runs/{original_id}/cases").json()["cases"][0]
        edited_case = client.get(f"/api/batch-runs/{edited_batch['id']}/cases").json()["cases"][0]
        assert original_case["source_values"]["question"] == "hello"
        assert edited_case["source_values"]["question"] == "changed"


def test_task_save_applies_to_next_round_and_preserves_previous_round(tmp_path: Path):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_body = _workflow_body("Reusable Workflow")
        workflow_id = _create_workflow(client, workflow_body)
        test_set_id = _create_test_set(client, "Reusable Set")
        task_body = _batch_body(test_set_id, workflow_id, "Reusable Task")
        created = client.post("/api/batch-runs", json=task_body)
        assert created.status_code == 201, created.text
        task_id = created.json()["batch"]["id"]

        assert client.post(f"/api/batch-runs/{task_id}/start").status_code == 202
        first = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            first = client.get(f"/api/batch-runs/{task_id}").json()["batch"]
            if first["status"] == "SUCCESS":
                break
            time.sleep(0.03)
        assert first and first["status"] == "SUCCESS"
        first_round_id = first["execution_round_id"]

        test_set = client.get(f"/api/test-sets/{test_set_id}").json()["test_set"]
        test_set["cases"][0]["values"]["question"] = "changed"
        assert client.put(
            f"/api/test-sets/{test_set_id}",
            json={
                "name": test_set["name"],
                "description": test_set["description"],
                "columns": test_set["columns"],
                "cases": [
                    {"id": case["id"], "values": case["values"]}
                    for case in test_set["cases"]
                ],
            },
        ).status_code == 200
        workflow_body["name"] = "Reusable Workflow v2"
        script = next(
            item["node"]
            for item in workflow_body["nodes"]
            if item["node"]["type"] == "SCRIPT"
        )
        script["script"] = 'result = "v2:" + context["question"]'
        assert client.put(f"/api/workflows/{workflow_id}", json=workflow_body).status_code == 200

        task_body["name"] = "Reusable Task Edited"
        saved = client.put(f"/api/batch-runs/{task_id}", json=task_body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["batch"]["configuration"]["name"] == "Reusable Task Edited"

        restarted = client.post(f"/api/batch-runs/{task_id}/start")
        assert restarted.status_code == 202, restarted.text
        second = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            second = client.get(f"/api/batch-runs/{task_id}").json()["batch"]
            if second["status"] == "SUCCESS":
                break
            time.sleep(0.03)
        assert second and second["status"] == "SUCCESS"
        assert second["execution_round_number"] == 2
        assert second["workflow"]["name"] == "Reusable Workflow v2"
        current_cases = client.get(f"/api/batch-runs/{task_id}/cases").json()["cases"]
        assert current_cases[0]["source_values"]["question"] == "changed"

        rounds = client.get(f"/api/batch-runs/{task_id}/rounds").json()["rounds"]
        assert [item["number"] for item in rounds] == [2, 1]
        previous_cases = client.get(
            f"/api/batch-runs/{task_id}/cases?round_id={first_round_id}"
        ).json()["cases"]
        assert previous_cases[0]["source_values"]["question"] == "hello"
        assert len(previous_cases[0]["workflow_execution_ids"]) == 1
        previous_batch = client.get(
            f"/api/batch-runs/{task_id}?round_id={first_round_id}"
        ).json()["batch"]
        assert previous_batch["execution_round_number"] == 1
        previous_case = client.get(
            f"/api/batch-runs/{task_id}/cases/{previous_cases[0]['id']}?round_id={first_round_id}"
        ).json()["case"]
        assert previous_case["id"] == previous_cases[0]["id"]


def test_task_configuration_can_be_saved_while_current_round_is_running(tmp_path: Path):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_body = _workflow_body("Slow Workflow")
        script = next(
            item["node"]
            for item in workflow_body["nodes"]
            if item["node"]["type"] == "SCRIPT"
        )
        script["script"] = 'import time\ntime.sleep(1)\nresult = context["question"]'
        workflow_id = _create_workflow(client, workflow_body)
        test_set_id = _create_test_set(client, "Slow Set")
        task_body = _batch_body(test_set_id, workflow_id, "Slow Task")
        task_body["case_concurrency"] = 1
        created = client.post("/api/batch-runs", json=task_body).json()["batch"]
        task_id = created["id"]
        created_at = created["created_at"]
        updated_at = created["updated_at"]

        assert client.post(f"/api/batch-runs/{task_id}/start").status_code == 202
        task_body["name"] = "Saved During Run"
        saved = client.put(f"/api/batch-runs/{task_id}", json=task_body)

        assert saved.status_code == 200, saved.text
        batch = saved.json()["batch"]
        assert batch["status"] == "RUNNING"
        assert batch["name"] == "Saved During Run"
        assert batch["configuration"]["name"] == "Saved During Run"
        assert batch["execution_configuration"]["name"] == "Slow Task"
        assert batch["created_at"] == created_at
        assert batch["updated_at"] > updated_at

        assert client.post(f"/api/batch-runs/{task_id}/cancel").status_code == 200
        assert client.post(f"/api/batch-runs/{task_id}/cancel").status_code == 400
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            batch = client.get(f"/api/batch-runs/{task_id}").json()["batch"]
            if batch["status"] == "STOPPED":
                break
            time.sleep(0.03)
        assert batch["status"] == "STOPPED"
        assert batch["finished_at"]
        cases = client.get(f"/api/batch-runs/{task_id}/cases").json()["cases"]
        assert [case["status"] for case in cases] == ["INTERRUPTED", "QUEUED"]
        assert sum(len(case["workflow_execution_ids"]) for case in cases) == 1
        listed = client.get("/api/batch-runs").json()["batches"][0]
        assert listed["finished_at"] == batch["finished_at"]
        assert listed["updated_at"] == batch["updated_at"]


def test_batch_api_applies_reverse_call_order(tmp_path: Path):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        created = client.post(
            "/api/batch-runs",
            json=_batch_body(test_set_id, workflow_id, "Reverse Run", "REVERSE"),
        )

        assert created.status_code == 201, created.text
        batch = created.json()["batch"]
        case_payload = client.get(f"/api/batch-runs/{batch['id']}/cases").json()
        cases = case_payload["cases"]
        assert batch["input"]["call_order"] == {"mode": "REVERSE", "random_seed": None}
        assert [case["case_id"] for case in cases] == ["case-2", "case-1"]
        assert [case["row_number"] for case in cases] == [2, 1]
        assert [case["call_number"] for case in cases] == [1, 2]
        assert case_payload["summary"] == {
            "Pass": 0,
            "Failed": 0,
            "Error": 0,
            "Running": 0,
            "Pending": 2,
        }
        assert case_payload["total_all"] == 2
        assert case_payload["batch"]["id"] == batch["id"]
        assert case_payload["batch"]["workflow"] == {"id": workflow_id, "name": "Batch API Workflow"}
        assert "structural_snapshot" not in case_payload["batch"]["workflow"]

        filtered = client.get(f"/api/batch-runs/{batch['id']}/cases?q=hello").json()
        assert filtered["total"] == 1
        assert filtered["cases"][0]["case_id"] == "case-1"

        pending = client.get(
            f"/api/batch-runs/{batch['id']}/cases?state=Pending"
        ).json()
        assert pending["total"] == 2
        assert {case["case_id"] for case in pending["cases"]} == {"case-1", "case-2"}

        assert client.delete(f"/api/batch-runs/{batch['id']}/cases/{cases[0]['id']}").status_code == 405


def test_manual_case_cannot_be_cancelled_and_batch_start_continues_remaining_cases(tmp_path: Path):
    application = create_app(
        database_path=tmp_path / "database.sqlite3",
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client)
        batch = client.post(
            "/api/batch-runs",
            json=_batch_body(test_set_id, workflow_id, "Manual Case"),
        ).json()["batch"]
        cases = client.get(f"/api/batch-runs/{batch['id']}/cases").json()["cases"]

        started = client.post(
            f"/api/batch-runs/{batch['id']}/cases/{cases[0]['id']}/start"
        )
        assert started.status_code == 200, started.text
        cancelled = client.post(
            f"/api/batch-runs/{batch['id']}/cases/{cases[0]['id']}/cancel"
        )
        assert cancelled.status_code == 405

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = client.get(f"/api/batch-runs/{batch['id']}").json()["batch"]
            if current["status"] == "QUEUED" and current["summary"]["success"] == 1:
                break
            time.sleep(0.03)
        assert current["summary"]["queued"] == 1

        started_batch = client.post(f"/api/batch-runs/{batch['id']}/start")
        assert started_batch.status_code == 202, started_batch.text
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = client.get(f"/api/batch-runs/{batch['id']}").json()["batch"]
            if current["status"] == "SUCCESS":
                break
            time.sleep(0.03)

        final_cases = client.get(f"/api/batch-runs/{batch['id']}/cases").json()["cases"]
        assert current["execution_round_number"] == 1
        assert current["summary"]["success"] == 2
        assert [len(case["workflow_execution_ids"]) for case in final_cases] == [1, 1]


def test_batch_history_api_records_full_runs_and_deletes_with_task(tmp_path: Path):
    database_path = tmp_path / "database.sqlite3"
    application = create_app(
        database_path=database_path,
        execution_root=tmp_path / "workflow-executions",
    )
    with TestClient(application) as client:
        workflow_id = _create_workflow(client)
        test_set_id = _create_test_set(client, "History Test Set")
        created = client.post(
            "/api/batch-runs",
            json=_batch_body(test_set_id, workflow_id, "History Task"),
        )
        assert created.status_code == 201, created.text
        batch_id = created.json()["batch"]["id"]

        started = client.post(f"/api/batch-runs/{batch_id}/start")
        assert started.status_code == 202, started.text
        deadline = time.monotonic() + 10
        batch = None
        while time.monotonic() < deadline:
            batch = client.get(f"/api/batch-runs/{batch_id}").json()["batch"]
            if batch["status"] == "SUCCESS":
                break
            time.sleep(0.03)
        assert batch and batch["status"] == "SUCCESS"

        response = client.get(f"/api/batch-runs/{batch_id}/history")
        assert response.status_code == 200, response.text
        history = response.json()["history"]
        assert len(history) == 1
        assert history[0]["test_set_name"] == "History Test Set"
        assert history[0]["workflow_name"] == "Batch API Workflow"
        assert history[0]["total_cases"] == 2
        assert history[0]["executed_cases"] == 2
        assert history[0]["passed_cases"] == 2
        assert history[0]["started_at"] <= history[0]["finished_at"]

        deleted = client.delete(f"/api/batch-runs/{batch_id}")
        assert deleted.status_code == 200, deleted.text
        assert application.state.workflow_services.batch_history.list_recent(batch_id) == []
        assert client.get(f"/api/batch-runs/{batch_id}/history").status_code == 404
