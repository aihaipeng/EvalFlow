import asyncio
import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from execution.model_providers import ModelProviderRepository
from execution.targets import DEFAULT_DATABASE_PATH
from execution.workflow_adapters import WorkflowNodeAdapter
from execution.workflow_contract import WorkflowDefinition
from execution.workflow_engine import WorkflowExecutor
from execution.workflows import WorkflowRecord, WorkflowRepository, workflow_now


pytestmark = pytest.mark.live


def _uuid() -> str:
    return str(uuid4())


def _deepseek_model() -> tuple[str, str]:
    requested_provider = os.getenv("WORKFLOW_LIVE_PROVIDER_ID")
    requested_model = os.getenv("WORKFLOW_LIVE_MODEL", "deepseek-v4-pro")
    providers = ModelProviderRepository().list()
    for provider in providers:
        if requested_provider and provider.id != requested_provider:
            continue
        if requested_model in provider.models:
            return provider.id, requested_model
    pytest.skip("A configured deepseek-v4-pro provider is required")


def _workflow(base_url: str) -> WorkflowDefinition:
    provider_id, model_name = _deepseek_model()
    workflow_id = _uuid()
    start_id, login_id, order_id, summary_id = (_uuid() for _ in range(4))
    admin_id, review_id, reply_id, aggregate_id, end_id = (_uuid() for _ in range(5))
    execution = {"timeout_ms": 10000, "max_attempts": 1, "delay_ms": 100}
    llm_execution = {"timeout_ms": 180000, "max_attempts": 1, "delay_ms": 200}
    direct = {"proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None}, "verify_ssl": True}
    api_host = urlsplit(base_url).netloc

    nodes = [
        {"id": start_id, "type": "START", "name": "Live inputs", "description": "", "inputs": [
            {"name": "api_host", "type": "string", "data": api_host},
            {"name": "order_id", "type": "string", "data": "ORD-LIVE-9001"},
        ]},
        {"id": login_id, "type": "HTTP", "name": "Login", "description": "", "request": {"method": "POST", "url": "http://{{ ctx.api_host }}/auth/login", "follow_redirects": True, "headers": [{"key": "Content-Type", "value": "application/json"}], "params": [], "body": {"type": "raw", "content": {"username": "admin", "password": "secret"}}}, "network": direct, "response": {"body_type": "json"}, "execution": execution, "outputs": [{"name": "access_token", "type": "string", "path": "$.response.body.data.accessToken"}]},
        {"id": order_id, "type": "HTTP", "name": "Load order", "description": "", "request": {"method": "GET", "url": "http://{{ ctx.api_host }}/orders/{{ ctx.order_id }}", "follow_redirects": True, "headers": [], "params": [], "body": {"type": "none", "content": None}}, "network": direct, "response": {"body_type": "json"}, "execution": execution, "outputs": [{"name": "order_data", "type": "object", "path": "$.response.body.data"}]},
        {"id": summary_id, "type": "SCRIPT", "name": "Prepare order", "description": "", "script": "import json\norder = get_val('order_data')\nset_val('order_summary', json.dumps({'orderId': order['orderId'], 'status': order['status'], 'amount': order['amount'], 'currency': order['currency']}, ensure_ascii=False, separators=(',', ':')))", "execution": execution, "outputs": [{"name": "order_summary", "type": "string"}]},
        {"id": admin_id, "type": "HTTP", "name": "Load administrators", "description": "", "request": {"method": "GET", "url": "http://{{ ctx.api_host }}/admin/users", "follow_redirects": True, "headers": [{"key": "Authorization", "value": "Bearer {{ ctx.access_token }}"}], "params": [], "body": {"type": "none", "content": None}}, "network": direct, "response": {"body_type": "json"}, "execution": execution, "outputs": [{"name": "admin_total", "type": "integer", "path": "$.response.body.data.total"}]},
        {"id": review_id, "type": "LLM", "name": "Risk review", "description": "", "model": {"provider_id": provider_id, "model_name": model_name}, "prompt": {"system": "你是订单风险审核员，只输出简短中文结论。", "user": "审核订单并指出风险：{{ ctx.order_summary }}"}, "generation": {"stream": False, "parameters": {"thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": 1024}}, "execution": llm_execution, "outputs": [{"name": "review_text", "type": "string"}]},
        {"id": reply_id, "type": "LLM", "name": "Customer reply", "description": "", "model": {"provider_id": provider_id, "model_name": model_name}, "prompt": {"system": "你是中文客服，只输出简短中文回复。设备名、SKU 和英文术语可以保留。", "user": "根据订单生成客户回复：{{ ctx.order_summary }}"}, "generation": {"stream": False, "parameters": {"thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": 1024}}, "execution": llm_execution, "outputs": [{"name": "reply_text", "type": "string"}]},
        {"id": aggregate_id, "type": "SCRIPT", "name": "Aggregate", "description": "", "script": "review = get_val('review_text')\nreply = get_val('reply_text')\nadmin_total = get_val('admin_total')\nset_val('final_report', {'review': review, 'reply': reply, 'adminTotal': admin_total, 'status': 'PASS'})", "execution": execution, "outputs": [{"name": "final_report", "type": "object"}]},
        {"id": end_id, "type": "END", "name": "End", "description": ""},
    ]
    edges = [
        {"edge_id": _uuid(), "source": start_id, "target": login_id},
        {"edge_id": _uuid(), "source": start_id, "target": order_id},
        {"edge_id": _uuid(), "source": login_id, "target": admin_id},
        {"edge_id": _uuid(), "source": order_id, "target": summary_id},
        {"edge_id": _uuid(), "source": summary_id, "target": review_id},
        {"edge_id": _uuid(), "source": summary_id, "target": reply_id},
        {"edge_id": _uuid(), "source": admin_id, "target": aggregate_id},
        {"edge_id": _uuid(), "source": review_id, "target": aggregate_id},
        {"edge_id": _uuid(), "source": reply_id, "target": aggregate_id},
        {"edge_id": _uuid(), "source": aggregate_id, "target": end_id},
    ]
    return WorkflowDefinition.model_validate({"workflow_id": workflow_id, "name": f"Live complex validation {workflow_now()}", "description": "HTTP + parallel LLM + SCRIPT Context validation", "nodes": nodes, "edges": edges})


@pytest.mark.parametrize("round_index", range(3))
def test_complex_live_workflow_persists_logs_and_context_flow(round_index):
    if os.getenv("WORKFLOW_COMPLEX_LIVE") != "1":
        pytest.skip("WORKFLOW_COMPLEX_LIVE=1 is required")
    base_url = os.getenv("WORKFLOW_HTTP_BASE_URL", "http://127.0.0.1:9000").rstrip("/")
    repository = WorkflowRepository(DEFAULT_DATABASE_PATH)
    workflow = _workflow(base_url)
    repository.create_workflow(WorkflowRecord.model_validate(workflow.model_dump(mode="json")))

    run = asyncio.run(WorkflowExecutor(repository, WorkflowNodeAdapter()).run(workflow))
    node_runs = {item.node_id: item for item in repository.list_node_runs(run.run_id)}
    by_name = {node.name: node_runs[node.id] for node in workflow.nodes if node.type != "END"}

    assert run.status == "SUCCESS"
    assert round_index in {0, 1, 2}
    assert len(node_runs) == 8
    assert all(item.status == "SUCCESS" for item in node_runs.values())
    assert by_name["Load order"].inputs == {"api_host": urlsplit(base_url).netloc, "order_id": "ORD-LIVE-9001"}
    assert by_name["Prepare order"].inputs["order_data"] == by_name["Load order"].outputs["order_data"]
    assert by_name["Risk review"].inputs["order_summary"] == by_name["Prepare order"].outputs["order_summary"]
    assert by_name["Customer reply"].inputs["order_summary"] == by_name["Prepare order"].outputs["order_summary"]
    assert by_name["Load administrators"].inputs["access_token"] == by_name["Login"].outputs["access_token"]
    assert by_name["Load administrators"].request["headers"]["authorization"] == f"Bearer {by_name['Login'].outputs['access_token']}"
    assert by_name["Load administrators"].response["body"]["data"]["total"] == 3
    assert by_name["Risk review"].request["user"].endswith(by_name["Prepare order"].outputs["order_summary"])
    assert by_name["Risk review"].response == by_name["Risk review"].outputs["review_text"]
    assert by_name["Customer reply"].response == by_name["Customer reply"].outputs["reply_text"]
    assert by_name["Risk review"].usage is not None
    assert by_name["Customer reply"].usage is not None
    assert by_name["Aggregate"].inputs == {
        "review_text": by_name["Risk review"].outputs["review_text"],
        "reply_text": by_name["Customer reply"].outputs["reply_text"],
        "admin_total": 3,
    }
    assert by_name["Aggregate"].outputs["final_report"] == {
        "review": by_name["Risk review"].outputs["review_text"],
        "reply": by_name["Customer reply"].outputs["reply_text"],
        "adminTotal": 3,
        "status": "PASS",
    }
