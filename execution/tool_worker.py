"""Subprocess entry point for Python and HTTP Workflow node execution."""

from __future__ import annotations

import base64
import json
import math
import sys
import threading
import traceback
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from types import MappingProxyType
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, TypeAdapter


_RESPONSE_ADAPTER = TypeAdapter(Any)
_STREAM_EVENT_PREFIX = "\x1e"


class _HttpResponseError(RuntimeError):
    def __init__(self, status_code: int, response: dict[str, Any]) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.response = response


class _RawHttpResponseParseError(ValueError):
    pass


def _emit_event(event: dict[str, Any]) -> None:
    sys.__stdout__.buffer.write(
        (
            _STREAM_EVENT_PREFIX
            + json.dumps(event, ensure_ascii=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
    )
    sys.__stdout__.buffer.flush()


class _LineWriter:
    encoding = "utf-8"
    errors = "replace"

    def __init__(self, stream: str) -> None:
        self.stream = stream
        self._pending = ""
        self._lock = threading.Lock()

    def write(self, value: str) -> int:
        text = str(value)
        with self._lock:
            self._pending += text
            while "\n" in self._pending:
                end = self._pending.index("\n") + 1
                line = self._pending[:end]
                self._pending = self._pending[end:]
                _emit_event({"type": "log", "stream": self.stream, "text": line})
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._pending:
                pending = self._pending
                self._pending = ""
                _emit_event({"type": "log", "stream": self.stream, "text": pending})

    def isatty(self) -> bool:
        return False


def _reject_non_finite(value: Any, seen: set[int] | None = None) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("response 包含 NaN 或 Infinity")
        return
    if isinstance(value, BaseModel):
        _reject_non_finite(value.model_dump(), seen)
        return
    if not isinstance(value, (dict, list, tuple, set, frozenset)):
        return
    seen = seen or set()
    identity = id(value)
    if identity in seen:
        raise ValueError("response 包含循环引用")
    seen.add(identity)
    values = value.values() if isinstance(value, dict) else value
    for item in values:
        _reject_non_finite(item, seen)
    seen.remove(identity)


def _serialize_response(value: Any) -> Any:
    _reject_non_finite(value)
    serialized = _RESPONSE_ADAPTER.dump_python(
        value,
        mode="json",
        warnings="error",
        serialize_as_any=True,
    )
    json.dumps(serialized, ensure_ascii=False, allow_nan=False)
    return serialized


def _execute_python(payload: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("main.py 不能为空")
    requested_names = payload.get("output_variable_names")
    namespace = {
        "__name__": "__tool_runtime__",
        "inputs": payload["inputs"],
        "config": payload["config"],
    }
    if "context" in payload:
        namespace["context"] = MappingProxyType(deepcopy(payload["context"]))
    if requested_names is None:
        namespace["response"] = None
    exec(compile(code, "<workflow-node-main.py>", "exec"), namespace, namespace)
    if requested_names is None:
        return namespace.get("response"), None
    if not isinstance(requested_names, list) or not all(
        isinstance(name, str) and name for name in requested_names
    ):
        raise ValueError("output_variable_names 必须是非空字符串数组")
    captured: dict[str, Any] = {}
    missing_names: list[str] = []
    for name in requested_names:
        if name not in namespace:
            captured[name] = None
            missing_names.append(name)
            print(
                f"[WARNING] Python 顶层变量不存在，输出 null: {name}",
                file=sys.stderr,
                flush=True,
            )
        else:
            captured[name] = namespace[name]
    payload["_missing_variable_names"] = missing_names
    return None, captured


def _proxy_url_with_auth(url: str, username: str | None, password: str | None) -> str:
    if not username:
        return url
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    credentials = quote(username, safe="")
    if password is not None:
        credentials += ":" + quote(password, safe="")
    return urlunsplit((parsed.scheme, f"{credentials}@{host}{port}", parsed.path, "", ""))


def _execute_raw_http(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload["request"]
    network = payload.get("network") or {}
    proxy = network.get("proxy") or {}
    client_options: dict[str, Any] = {
        "timeout": float(payload["config"].get("timeout_seconds", 120)),
        "follow_redirects": bool(request.get("follow_redirects", True)),
        "verify": bool(network.get("verify_ssl", True)),
    }
    mode = proxy.get("mode", "SYSTEM")
    if mode == "DIRECT":
        client_options["trust_env"] = False
    elif mode == "CUSTOM":
        if not proxy.get("url"):
            raise ValueError("CUSTOM Proxy 缺少 URL")
        client_options["trust_env"] = False
        client_options["proxy"] = _proxy_url_with_auth(
            proxy["url"], proxy.get("username"), proxy.get("password")
        )
    elif mode != "SYSTEM":
        raise ValueError(f"不支持的 Proxy 模式: {mode}")

    kwargs: dict[str, Any] = {}
    if request.get("headers"):
        headers = request["headers"]
        kwargs["headers"] = [
            (item["key"], item["value"]) if isinstance(item, dict) else tuple(item)
            for item in headers
        ] if isinstance(headers, list) else headers
    if request.get("params"):
        kwargs["params"] = request["params"]
    body_mode = request.get("body_mode", "NONE")
    if body_mode == "JSON":
        kwargs["json"] = request.get("body")
    elif body_mode == "CONTENT":
        kwargs["content"] = request.get("body")
    elif body_mode in {"FORM_DATA", "FORM_URLENCODED"}:
        form = request.get("body") or []
        kwargs["data"] = [
            (item["key"], item["value"]) if isinstance(item, dict) else tuple(item)
            for item in form
        ] if isinstance(form, list) else form

    with httpx.Client(**client_options) as client:
        response = client.request(request["method"], request["url"], **kwargs)
    response_body, response_body_type = parse_raw_http_body(
        response, request.get("response_mode", "AUTO")
    )

    def response_fact(item: httpx.Response) -> dict[str, Any]:
        try:
            body: Any = item.json()
            body_type = "JSON"
        except ValueError:
            body = item.text
            body_type = "TEXT"
        return {
            "status_code": item.status_code,
            "headers": [{"key": key, "value": value} for key, value in item.headers.multi_items()],
            "body_type": body_type,
            "body": body,
        }

    return {
        "request": {
            "method": response.request.method,
            "url": str(response.request.url),
            "headers": [
                {"key": key, "value": value}
                for key, value in response.request.headers.multi_items()
            ],
            "body_type": request.get("execution_body_type", "none"),
            "body": request.get("execution_body"),
        },
        "redirects": [response_fact(item) for item in response.history],
        "response": {
            "status_code": response.status_code,
            "headers": [{"key": key, "value": value} for key, value in response.headers.multi_items()],
            "body_type": response_body_type,
            "body": response_body,
        },
    }


def parse_raw_http_body(response: httpx.Response, mode: str) -> tuple[Any, str]:
    normalized_mode = str(mode).upper()
    if normalized_mode == "JSON":
        try:
            return response.json(), "JSON"
        except ValueError as exc:
            raise _RawHttpResponseParseError("响应 Body 不是合法 JSON") from exc
    if normalized_mode == "TEXT":
        encoding = response.encoding or "utf-8"
        try:
            return response.content.decode(encoding, errors="strict"), "TEXT"
        except (LookupError, UnicodeDecodeError) as exc:
            raise _RawHttpResponseParseError("响应 Body 无法按文本严格解码") from exc
    if normalized_mode == "BINARY":
        return base64.b64encode(response.content).decode("ascii"), "BINARY"
    if normalized_mode != "AUTO":
        raise ValueError(f"不支持的响应 Body 模式: {mode}")
    try:
        return response.json(), "JSON"
    except ValueError:
        encoding = response.encoding or "utf-8"
        try:
            return response.content.decode(encoding, errors="strict"), "TEXT"
        except (LookupError, UnicodeDecodeError):
            return base64.b64encode(response.content).decode("ascii"), "BINARY"


_parse_raw_http_body = parse_raw_http_body


def _serialize_python_variables(values: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for name, value in values.items():
        try:
            serialized[name] = _serialize_response(value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"Python 顶层变量无法序列化: {name} ({type(exc).__name__}: {exc})"
            ) from exc
    return serialized


def _execute_http(payload: dict[str, Any]) -> Any:
    request = payload["http"]
    body_type = request.get("body_type", "NONE")
    body = request.get("body")
    kwargs: dict[str, Any] = {
        "headers": request.get("headers") or {},
        "timeout": float(payload["config"].get("timeout_seconds", 30)),
        "follow_redirects": bool(payload["config"].get("follow_redirects", True)),
        "verify": bool(payload["config"].get("verify_tls", True)),
    }
    if request.get("params"):
        kwargs["params"] = request["params"]
    if body_type == "RAW":
        if isinstance(body, str):
            kwargs["content"] = body
        else:
            kwargs["json"] = body
    elif body_type in {"FORM_DATA", "FORM_URLENCODED"}:
        kwargs["data"] = body or {}
    elif body_type == "BINARY":
        kwargs["content"] = body.encode("utf-8") if isinstance(body, str) else bytes(body or [])
    response = httpx.request(request["method"], request["url"], **kwargs)
    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text
    result = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body": response_body,
    }
    if not response.is_success:
        raise _HttpResponseError(response.status_code, result)
    return result


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(payload.get("inputs"), dict):
            raise ValueError("inputs 必须是 JSON 对象")
        if not isinstance(payload.get("config"), dict):
            raise ValueError("config 必须是 JSON 对象")
    except Exception as exc:  # noqa: BLE001
        _emit_event({"type": "result", "result": {"ok": False, "error": str(exc)}})
        return

    stdout_writer = _LineWriter("stdout")
    stderr_writer = _LineWriter("stderr")
    python_variables: dict[str, Any] | None = None
    try:
        with redirect_stdout(stdout_writer), redirect_stderr(stderr_writer):
            if payload.get("mode") == "HTTP_CONFIG":
                response = _execute_http(payload)
            elif payload.get("mode") == "RAW_HTTP":
                response = _execute_raw_http(payload)
            elif payload.get("mode") == "PYTHON":
                response, python_variables = _execute_python(payload)
            else:
                raise ValueError("未知工具执行模式")
        stdout_writer.flush()
        stderr_writer.flush()
        result = {"ok": True, "response": _serialize_response(response)}
        if payload.get("mode") == "PYTHON" and python_variables is not None:
            result["python_variables"] = _serialize_python_variables(python_variables)
            if payload.get("_missing_variable_names"):
                result["missing_variable_names"] = payload["_missing_variable_names"]
    except Exception as exc:  # noqa: BLE001
        traceback_text = traceback.format_exc()
        with redirect_stderr(stderr_writer):
            print(traceback_text, end="", file=sys.stderr)
        stdout_writer.flush()
        stderr_writer.flush()
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        result["traceback"] = traceback_text
        if isinstance(exc, _HttpResponseError):
            result["response"] = _serialize_response(exc.response)
            result["http_status"] = exc.status_code
        elif isinstance(exc, _RawHttpResponseParseError):
            result["error_code"] = "HTTP_RESPONSE_PARSE_ERROR"
    _emit_event({"type": "result", "result": result})


if __name__ == "__main__":
    main()
