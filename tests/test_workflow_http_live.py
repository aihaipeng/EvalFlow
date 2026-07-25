import asyncio
import os

import pytest

from execution.workflow_adapters import WorkflowNodeAdapter
from execution.workflow_contract import HttpNode
from execution.workflow_engine import NodeExecutionError


pytestmark = pytest.mark.live
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.mock"


def _base_url() -> str:
    if os.getenv("WORKFLOW_HTTP_LIVE") != "1":
        pytest.skip("WORKFLOW_HTTP_LIVE=1 is required")
    return os.getenv("WORKFLOW_HTTP_BASE_URL", "http://127.0.0.1:9000").rstrip("/")


def _node(method: str, path: str, *, body=None, headers=None, params=None) -> HttpNode:
    body_type = "none" if body is None else "raw"
    return HttpNode.model_validate(
        {
            "id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            "type": "HTTP",
            "name": f"{method} {path}",
            "description": "api-mock live matrix",
            "request": {
                "method": method,
                "url": f"{_base_url()}{path}",
                "follow_redirects": True,
                "headers": headers or [],
                "params": params or [],
                "body": {"type": body_type, "content": body},
            },
            "network": {"proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None}, "verify_ssl": True},
            "response": {"body_type": "json"},
            "execution": {"timeout_ms": 5000, "max_attempts": 0, "delay_ms": 0},
            "outputs": [{"name": "api_code", "type": "integer", "path": "$.response.body.code"}],
        }
    )


@pytest.mark.parametrize(
    ("method", "path", "body", "headers", "params", "expected_code"),
    [
        ("GET", "/chat", None, None, None, 200),
        ("GET", "/chat/1", None, None, None, 200),
        ("GET", "/orders", None, None, [{"key": "page", "value": 1}, {"key": "size", "value": 5}], 200),
        ("GET", "/orders/ORD-001", None, None, None, 200),
        ("POST", "/orders", {"source": "workflow"}, None, None, 200),
        ("POST", "/auth/login", {"username": "admin", "password": "secret"}, None, None, 200),
        ("POST", "/upload", {"fileName": "report.pdf"}, None, None, 200),
        ("PUT", "/orders/ORD-001", {"remark": "verified"}, None, None, 200),
        ("PATCH", "/orders/ORD-001/status", {"status": "paid"}, None, None, 200),
        ("DELETE", "/orders/ORD-001", None, None, None, 200),
        ("GET", "/admin/users", None, [{"key": "Authorization", "value": f"Bearer {TOKEN}"}], None, 200),
        ("GET", "/admin/settings", None, [{"key": "Authorization", "value": f"Bearer {TOKEN}"}], None, 200),
        ("POST", "/admin/users", {"username": "workflow_user"}, [{"key": "Authorization", "value": f"Bearer {TOKEN}"}], None, 200),
        ("POST", "/register", {"username": "workflow", "password": "secret1", "email": "workflow@example.com"}, None, None, 200),
        ("GET", "/slow", None, None, [{"key": "delay", "value": 1}], 200),
    ],
)
def test_http_node_api_mock_full_matrix(method, path, body, headers, params, expected_code, tmp_path):
    result = asyncio.run(WorkflowNodeAdapter(tmp_path / "workflow.sqlite3")(_node(method, path, body=body, headers=headers, params=params), {}))

    assert result.outputs == {"api_code": expected_code}
    assert result.request["method"] == method
    assert result.response["status_code"] == 200
    assert result.response["body"]["code"] == expected_code


def test_http_node_api_mock_preserves_unauthorized_log_facts(tmp_path):
    node = _node("GET", "/admin/users")

    with pytest.raises(NodeExecutionError) as captured:
        asyncio.run(WorkflowNodeAdapter(tmp_path / "workflow.sqlite3")(node, {}))

    assert captured.value.code == "HTTP_STATUS_ERROR"
    assert captured.value.result.request["url"].endswith("/admin/users")
    assert captured.value.result.response["status_code"] == 401
    assert captured.value.result.response["body"] == {"detail": "缺少认证令牌"}
