import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from web.tool_worker import _parse_raw_http_body
from web.tool_runtime import (
    interrupt_tool_run,
    is_tool_run_active,
    stream_tool_worker,
)


@pytest.mark.parametrize(
    ("mode", "content", "content_type", "expected"),
    [
        ("JSON", b'{"ok":true}', "application/json", ({"ok": True}, "JSON")),
        ("TEXT", "中文".encode(), "text/plain; charset=utf-8", ("中文", "TEXT")),
        ("BINARY", b"\xff\x00", "application/octet-stream", (base64.b64encode(b"\xff\x00").decode(), "BINARY")),
        ("AUTO", b"\xff\x00", "application/octet-stream", (base64.b64encode(b"\xff\x00").decode(), "BINARY")),
    ],
)
def test_raw_http_response_mode_controls_body_representation(mode, content, content_type, expected):
    response = httpx.Response(200, content=content, headers={"content-type": content_type})

    assert _parse_raw_http_body(response, mode) == expected


def test_raw_http_explicit_json_mode_rejects_non_json_body():
    response = httpx.Response(200, text="not-json")

    with pytest.raises(ValueError):
        _parse_raw_http_body(response, "JSON")


def _python_payload(code: str, config=None, inputs=None) -> dict:
    return {
        "mode": "PYTHON",
        "code": code,
        "inputs": inputs or {},
        "config": config or {},
    }


def test_python_worker_shares_inputs_config_response_protocol():
    logs = []
    payload = _python_payload(
        'print("working", end="", flush=True)\nresponse = {"value": inputs["value"] + config["suffix"]}',
        config={"suffix": "!"},
        inputs={"value": "Workflow"},
    )

    result = stream_tool_worker(payload, logs.append, "run-python")

    assert result == {
        "ok": True,
        "response": {"value": "Workflow!"},
        "stdout": "working",
        "stderr": "",
        "console": "working",
    }
    assert "".join(logs) == "working"


def test_python_worker_captures_only_declared_top_level_variables():
    payload = _python_payload(
        'msg = "介绍一下自己"\nscore = "95"\nprint(msg, flush=True)'
    )
    payload["output_variable_names"] = ["msg", "score"]

    result = stream_tool_worker(payload, lambda _text: None, "run-script-outputs")

    assert result == {
        "ok": True,
        "response": None,
        "python_variables": {"msg": "介绍一下自己", "score": "95"},
        "stdout": "介绍一下自己\n",
        "stderr": "",
        "console": "介绍一下自己\n",
    }


def test_python_worker_missing_top_level_variable_outputs_null_and_warning():
    payload = _python_payload("print('before extraction', flush=True)")
    payload["output_variable_names"] = ["msg"]

    result = stream_tool_worker(payload, lambda _text: None, "run-script-missing")

    assert result["ok"] is True
    assert result["python_variables"] == {"msg": None}
    assert result["stdout"] == "before extraction\n"
    assert result["stderr"] == "[WARNING] Python 顶层变量不存在，输出 null: msg\n"
    assert result["console"] == (
        "before extraction\n"
        "[WARNING] Python 顶层变量不存在，输出 null: msg\n"
    )


def test_python_worker_console_preserves_stdout_stderr_order():
    payload = _python_payload(
        "import sys\n"
        "print('stdout 1', flush=True)\n"
        "print('stderr 1', file=sys.stderr, flush=True)\n"
        "print('stdout 2', flush=True)\n"
    )
    payload["output_variable_names"] = []

    result = stream_tool_worker(payload, lambda _text: None, "run-console-order")

    assert result["ok"] is True
    assert result["stdout"] == "stdout 1\nstdout 2\n"
    assert result["stderr"] == "stderr 1\n"
    assert result["console"] == "stdout 1\nstderr 1\nstdout 2\n"


def test_script_worker_does_not_reserve_or_serialize_response_variable():
    payload = _python_payload(
        "import requests\n"
        "response = requests.Response()\n"
        "response.status_code = 200\n"
        "print(response.status_code, flush=True)\n"
    )
    payload["output_variable_names"] = []

    result = stream_tool_worker(payload, lambda _text: None, "run-response-variable")

    assert result["ok"] is True
    assert result["response"] is None
    assert result["python_variables"] == {}
    assert result["console"] == "200\n"


def test_python_worker_reports_unserializable_top_level_variable():
    payload = _python_payload("msg = object()")
    payload["output_variable_names"] = ["msg"]

    result = stream_tool_worker(payload, lambda _text: None, "run-script-invalid")

    assert result["ok"] is False
    assert "Python 顶层变量无法序列化: msg" in result["error"]
    assert "Traceback" in result["stderr"]


def test_python_worker_rejects_non_json_response_and_reports_traceback():
    logs = []

    result = stream_tool_worker(
        _python_payload("response = float('nan')"),
        logs.append,
        "run-invalid-json",
    )

    assert result["ok"] is False
    assert "NaN" in result["error"]
    assert "Infinity" in result["error"]
    assert "Traceback" in "".join(logs)
    assert "Traceback" in result["stderr"]


def test_python_worker_timeout_terminates_process():
    logs = []

    result = stream_tool_worker(
        _python_payload("import time\ntime.sleep(10)\nresponse = {}"),
        logs.append,
        "run-timeout",
        timeout_seconds=0.2,
    )

    assert result == {
        "ok": False,
        "timed_out": True,
        "stdout": "",
        "stderr": "执行超时，已终止子进程（0.2 秒）\n",
        "console": "执行超时，已终止子进程（0.2 秒）\n",
    }
    assert "执行超时" in "".join(logs)
    assert not is_tool_run_active("run-timeout")


def test_python_worker_can_be_interrupted():
    holder = {}
    thread = threading.Thread(
        target=lambda: holder.setdefault(
            "result",
            stream_tool_worker(
                _python_payload("import time\ntime.sleep(10)\nresponse = {}"),
                lambda _text: None,
                "run-interrupt",
            ),
        )
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not is_tool_run_active("run-interrupt") and time.monotonic() < deadline:
        time.sleep(0.01)

    assert is_tool_run_active("run-interrupt")
    assert interrupt_tool_run("run-interrupt") is True
    thread.join(timeout=5)

    assert holder["result"] == {
        "ok": False,
        "interrupted": True,
        "stdout": "",
        "stderr": "",
        "console": "",
    }
    assert not is_tool_run_active("run-interrupt")


def test_http_worker_executes_real_request():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length))
            payload = json.dumps(
                {
                    "path": self.path,
                    "body": body,
                    "header": self.headers.get("x-workflow"),
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = stream_tool_worker(
            {
                "mode": "HTTP_CONFIG",
                "inputs": {},
                "config": {},
                "http": {
                    "method": "POST",
                    "url": f"http://127.0.0.1:{server.server_port}/execute?mode=test",
                    "headers": {"x-workflow": "yes"},
                    "params": {},
                    "body_type": "RAW",
                    "body": {"question": "hello"},
                },
            },
            lambda _text: None,
            "run-http-config",
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result["ok"] is True
    assert result["response"]["status_code"] == 200
    assert result["response"]["body"] == {
        "path": "/execute?mode=test",
        "body": {"question": "hello"},
        "header": "yes",
    }
