import asyncio

from execution.workflow_contract import WorkflowDefinition
from execution.workflow_engine import NodeExecutionError, NodeExecutionResult, WorkflowExecutor
from execution.workflows import WorkflowRecord, WorkflowRepository


WORKFLOW_ID = "123e4567-e89b-42d3-a456-426614174000"
START_ID = "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44"
LEFT_ID = "550e8400-e29b-41d4-a716-446655440000"
RIGHT_ID = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
END_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def definition() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate({"workflow_id": WORKFLOW_ID, "name": "Parallel", "description": "", "nodes": [
        {"id": START_ID, "type": "START", "name": "Start", "description": "", "inputs": [{"name": "input", "type": "string", "data": "x"}]},
        {"id": LEFT_ID, "type": "SCRIPT", "name": "Left", "description": "", "script": "pass", "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0}, "outputs": [{"name": "left", "type": "string"}]},
        {"id": RIGHT_ID, "type": "SCRIPT", "name": "Right", "description": "", "script": "pass", "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0}, "outputs": [{"name": "right", "type": "string"}]},
        {"id": END_ID, "type": "END", "name": "End", "description": ""}], "edges": [
        {"edge_id": "4c1f2e3d-6b7a-48c9-9d01-23456789abcd", "source": START_ID, "target": LEFT_ID},
        {"edge_id": "5d2e3f4a-7b8c-49d0-a123-456789abcdef", "source": START_ID, "target": RIGHT_ID},
        {"edge_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "source": LEFT_ID, "target": END_ID},
        {"edge_id": "8d2e3f4a-7b8c-49d0-a123-456789abcdef", "source": RIGHT_ID, "target": END_ID}]})


def test_parallel_nodes_complete_in_one_workflow_run(tmp_path):
    workflow = definition()
    repo = WorkflowRepository(tmp_path / "workflow.sqlite3")
    repo.create_workflow(WorkflowRecord.model_validate(workflow.model_dump(mode="json")))

    async def adapter(node, context):
        await asyncio.sleep(0.01)
        return NodeExecutionResult(outputs={"left": "ok"} if node.id == LEFT_ID else {"right": "ok"})

    run = asyncio.run(WorkflowExecutor(repo, adapter).run(workflow))
    node_runs = repo.list_node_runs(run.run_id)

    assert run.status == "SUCCESS"
    assert {item.node_id for item in node_runs} == {START_ID, LEFT_ID, RIGHT_ID}
    assert all(item.status == "SUCCESS" for item in node_runs)


def test_failed_parallel_branch_fails_workflow(tmp_path):
    workflow = definition()
    repo = WorkflowRepository(tmp_path / "workflow.sqlite3")
    repo.create_workflow(WorkflowRecord.model_validate(workflow.model_dump(mode="json")))

    async def adapter(node, context):
        if node.id == LEFT_ID:
            raise NodeExecutionError(
                "SCRIPT_RUNTIME_ERROR",
                "boom",
                result=NodeExecutionResult(inputs={"input": context["input"]}),
            )
        await asyncio.sleep(0.02)
        return NodeExecutionResult(outputs={"right": "ok"})

    run = asyncio.run(WorkflowExecutor(repo, adapter).run(workflow))
    node_runs = {item.node_id: item for item in repo.list_node_runs(run.run_id)}

    assert run.status == "FAILED"
    assert run.error.code == "SCRIPT_RUNTIME_ERROR"
    assert node_runs[LEFT_ID].attempt_count == 1
    assert node_runs[LEFT_ID].inputs == {"input": "x"}
    assert node_runs[LEFT_ID].outputs == {}
    assert node_runs[RIGHT_ID].status == "CANCELLED"
    assert node_runs[RIGHT_ID].error.code == "NODE_CANCELLED_BY_FAIL_FAST"
    assert node_runs[RIGHT_ID].error.details == {"trigger_node_run_id": node_runs[LEFT_ID].node_run_id}


def test_user_cancel_marks_active_nodes_with_user_reason(tmp_path):
    workflow = definition()
    repo = WorkflowRepository(tmp_path / "workflow.sqlite3")
    repo.create_workflow(WorkflowRecord.model_validate(workflow.model_dump(mode="json")))

    async def adapter(node, context):
        await asyncio.sleep(10)
        return NodeExecutionResult(outputs={"left": "ok"} if node.id == LEFT_ID else {"right": "ok"})

    async def scenario():
        task = asyncio.create_task(WorkflowExecutor(repo, adapter).run(workflow))
        for _ in range(100):
            runs = repo.list_workflow_runs(workflow.workflow_id)
            if runs and len(repo.list_node_runs(runs[0].run_id)) >= 3:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        return await task

    run = asyncio.run(scenario())
    node_runs = repo.list_node_runs(run.run_id)

    assert run.status == "CANCELLED"
    assert run.error.code == "WORKFLOW_CANCELLED"
    cancelled = [item for item in node_runs if item.status == "CANCELLED"]
    assert len(cancelled) == 2
    assert {item.error.code for item in cancelled} == {"NODE_CANCELLED_BY_USER"}


def test_script_retry_recovers_and_records_attempt_count(tmp_path):
    workflow = definition()
    payload = workflow.model_dump(mode="json")
    for node in payload["nodes"]:
        if node["id"] == LEFT_ID:
            node["execution"]["max_attempts"] = 1
    workflow = WorkflowDefinition.model_validate(payload)
    repo = WorkflowRepository(tmp_path / "workflow.sqlite3")
    repo.create_workflow(WorkflowRecord.model_validate(workflow.model_dump(mode="json")))
    attempts = {LEFT_ID: 0, RIGHT_ID: 0}

    async def adapter(node, context):
        attempts[node.id] += 1
        if node.id == LEFT_ID and attempts[node.id] == 1:
            raise NodeExecutionError("SCRIPT_RUNTIME_ERROR", "transient")
        return NodeExecutionResult(outputs={"left": "ok"} if node.id == LEFT_ID else {"right": "ok"})

    run = asyncio.run(WorkflowExecutor(repo, adapter).run(workflow))
    node_runs = {item.node_id: item for item in repo.list_node_runs(run.run_id)}

    assert run.status == "SUCCESS"
    assert node_runs[LEFT_ID].attempt_count == 2


def test_node_timeout_fails_workflow_without_zombie_run(tmp_path):
    workflow = definition()
    payload = workflow.model_dump(mode="json")
    for node in payload["nodes"]:
        if node["id"] == LEFT_ID:
            node["execution"] = {"timeout_ms": 10, "max_attempts": 0, "delay_ms": 0}
    workflow = WorkflowDefinition.model_validate(payload)
    repo = WorkflowRepository(tmp_path / "workflow.sqlite3")
    repo.create_workflow(WorkflowRecord.model_validate(workflow.model_dump(mode="json")))

    async def adapter(node, context):
        if node.id == LEFT_ID:
            await asyncio.sleep(1)
        return NodeExecutionResult(outputs={"left": "ok"} if node.id == LEFT_ID else {"right": "ok"})

    run = asyncio.run(WorkflowExecutor(repo, adapter).run(workflow))
    statuses = {item.status for item in repo.list_node_runs(run.run_id)}

    assert run.status == "FAILED"
    assert "TIMEOUT" in statuses
    assert "RUNNING" not in statuses
    timed_out = next(item for item in repo.list_node_runs(run.run_id) if item.status == "TIMEOUT")
    assert timed_out.attempt_count == 1


def test_twenty_parallel_nodes_complete_repeatedly(tmp_path):
    repo = WorkflowRepository(tmp_path / "workflow.sqlite3")
    start_id = "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44"
    end_id = "0f8fad5b-d9cb-469f-a165-70867728950e"
    nodes = [{"id": start_id, "type": "START", "name": "Start", "description": "", "inputs": []}]
    edges = []
    for index in range(20):
        node_id = f"00000000-0000-4000-8000-{index + 1:012d}"
        nodes.append({"id": node_id, "type": "SCRIPT", "name": f"N{index}", "description": "", "script": "pass", "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0}, "outputs": [{"name": f"out_{index}", "type": "integer"}]})
        edges.append({"edge_id": f"10000000-0000-4000-8000-{index + 1:012d}", "source": start_id, "target": node_id})
        edges.append({"edge_id": f"20000000-0000-4000-8000-{index + 1:012d}", "source": node_id, "target": end_id})
    nodes.append({"id": end_id, "type": "END", "name": "End", "description": ""})
    workflow = WorkflowDefinition.model_validate({"workflow_id": "30000000-0000-4000-8000-000000000001", "name": "Fanout", "description": "", "nodes": nodes, "edges": edges})
    repo.create_workflow(WorkflowRecord.model_validate(workflow.model_dump(mode="json")))
    active = 0
    peak = 0

    async def adapter(node, context):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.005)
        active -= 1
        index = int(node.name[1:])
        return NodeExecutionResult(outputs={f"out_{index}": index})

    for _ in range(3):
        run = asyncio.run(WorkflowExecutor(repo, adapter).run(workflow))
        assert run.status == "SUCCESS"
        assert all(item.status == "SUCCESS" for item in repo.list_node_runs(run.run_id))
    assert peak > 1
