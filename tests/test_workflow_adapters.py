import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from execution.workflow_adapters import WorkflowNodeAdapter
from execution.workflow_contract import HttpNode, ScriptNode
from execution.workflow_engine import NodeExecutionError


def script_node(source: str) -> ScriptNode:
    return ScriptNode.model_validate(
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "type": "SCRIPT",
            "name": "Script",
            "description": "",
            "script": source,
            "execution": {"timeout_ms": 2000, "max_attempts": 0, "delay_ms": 0},
            "outputs": [{"name": "result", "type": "object"}],
        }
    )


def test_script_adapter_runs_real_isolated_python_and_tracks_used_inputs(tmp_path):
    adapter = WorkflowNodeAdapter(tmp_path / "workflow.sqlite3")
    node = script_node("value = get_val('source')\nset_val('result', {'nested': value})")

    result = asyncio.run(adapter(node, {"source": "ok", "unused": "ignored"}))

    assert result.outputs == {"result": {"nested": "ok"}}
    assert result.inputs == {"source": "ok"}


def test_script_adapter_rejects_undeclared_output(tmp_path):
    adapter = WorkflowNodeAdapter(tmp_path / "workflow.sqlite3")
    node = script_node("set_val('other', 'no')")

    with pytest.raises(NodeExecutionError) as captured:
        asyncio.run(adapter(node, {}))

    assert captured.value.code == "SCRIPT_OUTPUT_UNDECLARED"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/fail":
            body = json.dumps({"error": "temporary"}).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps({"id": "ci-001", "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def test_http_adapter_calls_local_service_and_extracts_output(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        node = HttpNode.model_validate(
            {
                "id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
                "type": "HTTP",
                "name": "HTTP",
                "description": "",
                "request": {
                    "method": "GET",
                    "url": f"http://127.0.0.1:{server.server_port}/ci/{{{{ ctx.ci_name }}}}",
                    "follow_redirects": True,
                    "headers": [],
                    "params": [],
                    "body": {"type": "none", "content": None},
                },
                "network": {"proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None}, "verify_ssl": True},
                "response": {"body_type": "json"},
                "execution": {"timeout_ms": 2000, "max_attempts": 0, "delay_ms": 0},
                "outputs": [{"name": "ci_id", "type": "string", "path": "$.response.body.id"}],
            }
        )
        result = asyncio.run(WorkflowNodeAdapter(tmp_path / "workflow.sqlite3")(node, {"ci_name": "SWITCH_1"}))

        assert result.outputs == {"ci_id": "ci-001"}
        assert result.inputs == {"ci_name": "SWITCH_1"}
        assert result.response["status_code"] == 200
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_http_adapter_preserves_request_and_response_on_status_error(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        node = HttpNode.model_validate(
            {
                "id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
                "type": "HTTP",
                "name": "HTTP failure",
                "description": "",
                "request": {"method": "GET", "url": f"http://127.0.0.1:{server.server_port}/fail", "follow_redirects": True, "headers": [], "params": [], "body": {"type": "none", "content": None}},
                "network": {"proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None}, "verify_ssl": True},
                "response": {"body_type": "json"},
                "execution": {"timeout_ms": 2000, "max_attempts": 0, "delay_ms": 0},
                "outputs": [],
            }
        )

        with pytest.raises(NodeExecutionError) as captured:
            asyncio.run(WorkflowNodeAdapter(tmp_path / "workflow.sqlite3")(node, {}))

        assert captured.value.code == "HTTP_STATUS_ERROR"
        assert captured.value.result.request["url"].endswith("/fail")
        assert captured.value.result.response["status_code"] == 503
        assert captured.value.result.response["body"] == {"error": "temporary"}
    finally:
        server.shutdown()
        thread.join(timeout=2)
