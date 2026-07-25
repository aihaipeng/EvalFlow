"""Real SCRIPT, HTTP, and LLM adapters for WorkflowExecutor."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from execution.model_gateway import (
    build_anthropic_request,
    build_chat_completion_request,
    invoke_anthropic,
    invoke_openai_compatible,
    parse_anthropic_response,
    parse_openai_compatible_response,
)
from execution.model_providers import ModelProviderProtocol, ModelProviderRepository
from execution.targets import DEFAULT_DATABASE_PATH
from execution.workflow_contract import HttpNode, LlmNode, ScriptNode
from execution.workflow_engine import NodeExecutionError, NodeExecutionResult


_REFERENCE = re.compile(r"(?<!\\)\{\{\s*(?:ctx|context)\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)\s*\}\}")
_SCRIPT_WRAPPER = r'''
import contextlib, json, sys, traceback
payload = json.loads(sys.stdin.read())
ctx = payload["context"]
declared = set(payload["outputs"])
captured = {}
used = {}
class ContractError(Exception):
    def __init__(self, code, message): self.code, self.message = code, message
def get_val(name):
    key = str(name).lower()
    if key not in ctx: raise ContractError("CONTEXT_VARIABLE_NOT_FOUND", f"Context variable not found: {key}")
    used[key] = ctx[key]
    return json.loads(json.dumps(ctx[key], ensure_ascii=False, allow_nan=False))
def set_val(name, value):
    key = str(name).lower()
    if key not in declared: raise ContractError("SCRIPT_OUTPUT_UNDECLARED", f"Undeclared output: {key}")
    if key in captured: raise ContractError("SCRIPT_OUTPUT_DUPLICATE", f"Duplicate output: {key}")
    try: captured[key] = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except Exception as exc: raise ContractError("SCRIPT_OUTPUT_SERIALIZATION_ERROR", str(exc))
try:
    scope = {"get_val": get_val, "set_val": set_val}
    with contextlib.redirect_stdout(sys.stderr): exec(compile(payload["script"], "<workflow-script>", "exec"), scope, scope)
    print(json.dumps({"ok": True, "inputs": used, "outputs": captured}, ensure_ascii=False, allow_nan=False))
except ContractError as exc:
    print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"ok": False, "code": "SCRIPT_RUNTIME_ERROR", "message": str(exc)}, ensure_ascii=False))
'''


class WorkflowNodeAdapter:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH):
        self.database_path = Path(database_path).resolve()
        self.models = ModelProviderRepository(self.database_path)

    async def __call__(self, node, context: dict[str, Any]) -> NodeExecutionResult:
        if isinstance(node, ScriptNode):
            return await self._script(node, context)
        if isinstance(node, HttpNode):
            return await self._http(node, context)
        if isinstance(node, LlmNode):
            return await self._llm(node, context)
        raise NodeExecutionError("WORKFLOW_CONFIG_INVALID", "Unsupported workflow node type")

    async def _script(self, node: ScriptNode, context: dict[str, Any]) -> NodeExecutionResult:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", _SCRIPT_WRAPPER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = json.dumps({"script": node.script, "context": context, "outputs": [item.name for item in node.outputs]}, ensure_ascii=False).encode()
        try:
            stdout, _stderr = await process.communicate(payload)
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        try:
            result = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise NodeExecutionError("SCRIPT_RUNTIME_ERROR", "SCRIPT worker returned invalid JSON") from exc
        if not result.get("ok"):
            raise NodeExecutionError(result.get("code", "SCRIPT_RUNTIME_ERROR"), result.get("message") or "SCRIPT failed")
        return NodeExecutionResult(outputs=result["outputs"], inputs=result["inputs"])

    async def _http(self, node: HttpNode, context: dict[str, Any]) -> NodeExecutionResult:
        used: dict[str, Any] = {}
        url = _resolve(node.request.url, context, used, force_text=True)
        headers = {item.key: _resolve(item.value, context, used, force_text=True) for item in node.request.headers}
        params = [(item.key, _resolve(item.value, context, used)) for item in node.request.params]
        content = _resolve_tree(node.request.body.content, context, used)
        options: dict[str, Any] = {"verify": node.network.verify_ssl, "follow_redirects": node.request.follow_redirects, "timeout": node.execution.timeout_ms / 1000}
        proxy = node.network.proxy
        if proxy.mode == "DIRECT":
            options["trust_env"] = False
        elif proxy.mode == "CUSTOM":
            options["trust_env"] = False
            options["proxy"] = _proxy_url_with_auth(proxy.url, proxy.username, proxy.password)
        request_kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if node.request.body.type == "raw":
            request_kwargs["json" if isinstance(content, (dict, list, int, float, bool)) or content is None else "content"] = content
        elif node.request.body.type == "form_urlencoded":
            request_kwargs["data"] = [(item["key"], _text(item["value"])) for item in content]
        elif node.request.body.type == "form_data":
            request_kwargs["files"] = [(item["key"], (None, _text(item["value"]))) for item in content]
        try:
            async with httpx.AsyncClient(**options) as client:
                response = await client.request(node.request.method, url, **request_kwargs)
        except httpx.TimeoutException as exc:
            raise NodeExecutionError("HTTP_TIMEOUT", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise NodeExecutionError("HTTP_CONNECTION_ERROR", str(exc)) from exc
        response_headers = _response_headers(response)
        body = _parse_http_body(response, node.response.body_type)
        request_fact = {"method": node.request.method, "url": str(response.request.url), "headers": dict(response.request.headers), "params": params, "body_type": node.request.body.type, "body": content}
        response_fact = {"status_code": response.status_code, "headers": response_headers, "body_type": node.response.body_type, "body": body}
        if not 200 <= response.status_code < 300:
            raise NodeExecutionError("HTTP_STATUS_ERROR", f"HTTP {response.status_code}", {"response": response_fact})
        root = {"request": request_fact, "response": response_fact}
        outputs = {item.name: _extract_path(root, item.path) for item in node.outputs}
        return NodeExecutionResult(outputs=outputs, inputs=used, network=node.network.model_dump(mode="json"), request=request_fact, response=response_fact)

    async def _llm(self, node: LlmNode, context: dict[str, Any]) -> NodeExecutionResult:
        provider = self.models.get(node.model.provider_id)
        if provider is None or node.model.model_name not in provider.models:
            raise NodeExecutionError("LLM_MODEL_NOT_FOUND", "Configured LLM model was not found")
        used: dict[str, Any] = {}
        system = _resolve(node.prompt.system, context, used, force_text=True)
        user = _resolve(node.prompt.user, context, used, force_text=True)
        if user == "":
            raise NodeExecutionError("LLM_PROMPT_EMPTY", "Resolved user prompt is empty")
        config = provider.model_configs.get(node.model.model_name)
        defaults = config.default_body if config else {}
        parameters = deepcopy(node.generation.parameters)
        parameters["stream"] = node.generation.stream
        common = dict(base_url=provider.base_url, api_key=provider.api_key, timeout_seconds=node.execution.timeout_ms / 1000, proxy_mode=provider.proxy_mode, proxy_url=provider.proxy_url, proxy_username=provider.proxy_username, proxy_password=provider.proxy_password, verify_ssl=provider.verify_ssl)
        try:
            if provider.protocol == ModelProviderProtocol.ANTHROPIC:
                request_body = build_anthropic_request(model_name=node.model.model_name, messages=[{"role": "user", "content": user}], system_prompt=system, model_defaults=defaults, model_parameters=parameters)
                response = await invoke_anthropic(request_body=request_body, **common)
            else:
                messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
                request_body = build_chat_completion_request(model_name=node.model.model_name, messages=messages, model_defaults=defaults, model_parameters=parameters)
                response = await invoke_openai_compatible(request_body=request_body, **common)
        except httpx.TimeoutException as exc:
            raise NodeExecutionError("LLM_TIMEOUT", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise NodeExecutionError("LLM_REQUEST_ERROR", str(exc)) from exc
        if not response.is_success:
            raise NodeExecutionError("LLM_REQUEST_ERROR", f"LLM provider returned HTTP {response.status_code}", {"status_code": response.status_code})
        try:
            parsed = parse_anthropic_response(response) if provider.protocol == ModelProviderProtocol.ANTHROPIC else parse_openai_compatible_response(response, stream=node.generation.stream)
        except (TypeError, ValueError, KeyError) as exc:
            raise NodeExecutionError("LLM_RESPONSE_ERROR", str(exc)) from exc
        finish_reason = parsed.get("finish_reason")
        if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
            raise NodeExecutionError("LLM_OUTPUT_TRUNCATED", "LLM output was truncated", {"finish_reason": finish_reason})
        if finish_reason in {"content_filter", "safety"}:
            raise NodeExecutionError("LLM_CONTENT_FILTERED", "LLM output was filtered", {"finish_reason": finish_reason})
        if finish_reason in {"tool_calls", "function_call"}:
            raise NodeExecutionError("LLM_UNSUPPORTED_RESPONSE", "LLM returned a non-text tool response", {"finish_reason": finish_reason})
        if finish_reason not in {None, "stop", "end_turn"}:
            raise NodeExecutionError("LLM_UNSUPPORTED_FINISH_REASON", "Unsupported LLM finish reason", {"finish_reason": finish_reason})
        output = parsed["output"]
        if not isinstance(output, str):
            raise NodeExecutionError("LLM_UNSUPPORTED_RESPONSE", "LLM did not return text")
        outputs = {node.outputs[0].name: output} if node.outputs else {}
        request_fact = {"system": system, "user": user, "parameters": {k: v for k, v in request_body.items() if k not in {"model", "messages", "system"}}, "stream": node.generation.stream}
        return NodeExecutionResult(outputs=outputs, inputs=used, model=node.model.model_dump(mode="json"), request=request_fact, response=output, usage=parsed.get("usage"))


def _resolve(value: Any, context: dict[str, Any], used: dict[str, Any], *, force_text: bool = False) -> Any:
    if not isinstance(value, str):
        return value
    matches = list(_REFERENCE.finditer(value))
    if not matches:
        return value.replace(r"\{{", "{{")
    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        result = _lookup(matches[0].group(1), context, used)
        return _text(result) if force_text else deepcopy(result)
    result = value
    for match in reversed(matches):
        replacement = _text(_lookup(match.group(1), context, used))
        result = result[:match.start()] + replacement + result[match.end():]
    return result.replace(r"\{{", "{{")


def _resolve_tree(value: Any, context: dict[str, Any], used: dict[str, Any]) -> Any:
    if isinstance(value, str): return _resolve(value, context, used)
    if isinstance(value, list): return [_resolve_tree(item, context, used) for item in value]
    if isinstance(value, dict): return {key: _resolve_tree(item, context, used) for key, item in value.items()}
    return value


def _lookup(path: str, context: dict[str, Any], used: dict[str, Any]) -> Any:
    root = re.split(r"[.\[]", path, maxsplit=1)[0].lower()
    if root not in context:
        raise NodeExecutionError("CONTEXT_VARIABLE_NOT_FOUND", f"Context variable not found: {root}")
    used[root] = deepcopy(context[root])
    value = context[root]
    for token in re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", path[len(root):]):
        key, index = token
        try: value = value[key] if key else value[int(index)]
        except (KeyError, IndexError, TypeError) as exc: raise NodeExecutionError("CONTEXT_VARIABLE_NOT_FOUND", f"Context path not found: {path}") from exc
    return value


def _text(value: Any) -> str:
    if isinstance(value, str): return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_http_body(response: httpx.Response, body_type: str) -> Any:
    if len(response.content) > 10 * 1024 * 1024:
        raise NodeExecutionError("HTTP_RESPONSE_TOO_LARGE", "HTTP response exceeds 10 MB")
    if body_type == "binary":
        import base64
        return base64.b64encode(response.content).decode("ascii")
    if body_type == "text": return response.text
    if not response.content or not response.text.strip(): return None
    try: return response.json()
    except ValueError as exc: raise NodeExecutionError("HTTP_RESPONSE_JSON_INVALID", "HTTP response is not valid JSON") from exc


def _response_headers(response: httpx.Response) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in response.headers.multi_items():
        key = key.lower()
        if key not in result: result[key] = value
        elif isinstance(result[key], list): result[key].append(value)
        else: result[key] = [result[key], value]
    return result


def _extract_path(root: dict[str, Any], path: str) -> Any:
    def walk(candidate: str) -> Any:
        value: Any = root
        for key, index in re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", candidate[1:]):
            value = value[key] if key else value[int(index)]
        return value
    try:
        return deepcopy(walk(path))
    except (KeyError, IndexError, TypeError):
        if path.startswith("$.response.") and not path.startswith("$.response.body"):
            try:
                return deepcopy(walk("$.response.body" + path[len("$.response"):]))
            except (KeyError, IndexError, TypeError):
                pass
        raise NodeExecutionError("HTTP_OUTPUT_PATH_NOT_FOUND", f"HTTP output path not found: {path}")


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


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
