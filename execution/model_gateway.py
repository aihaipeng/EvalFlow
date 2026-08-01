"""Framework-independent model request composition and HTTP transport."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.parse import quote

import httpx

from execution.model_protocols import (
    ANTHROPIC_CLAUDE_MESSAGES,
    ANTHROPIC_VERSION,
    OPENAI_CHAT_COMPLETIONS,
    OPENAI_RESPONSES,
    model_inference_url,
    model_protocol_headers,
    validate_protocol_parameters,
)


DEFAULT_ANTHROPIC_MAX_TOKENS = 8192


def deep_merge_model_request(
    *layers: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge request layers recursively, with later layers taking precedence."""

    merged: dict[str, Any] = {}
    for layer in layers:
        if layer is None:
            continue
        if not isinstance(layer, Mapping):
            raise TypeError("模型请求参数必须是 JSON 对象")
        merged = _merge_objects(merged, layer)
    return merged


def _merge_objects(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _merge_objects(current, value)
        else:
            result[key] = deepcopy(value)
    return result


def build_chat_completion_request(
    *,
    model_name: str,
    messages: Sequence[Mapping[str, Any]],
    model_defaults: Mapping[str, Any] | None = None,
    model_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a chat request where model defaults and node parameters may override all fields."""

    validate_protocol_parameters(
        OPENAI_CHAT_COMPLETIONS, model_defaults, model_parameters
    )
    base_request = {
        "model": model_name,
        "messages": [deepcopy(dict(message)) for message in messages],
        "stream": False,
    }
    return deep_merge_model_request(
        base_request,
        model_defaults,
        model_parameters,
    )


def build_responses_request(
    *,
    model_name: str,
    messages: Sequence[Mapping[str, Any]],
    model_defaults: Mapping[str, Any] | None = None,
    model_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an OpenAI Responses API request using the native input field."""

    validate_protocol_parameters(OPENAI_RESPONSES, model_defaults, model_parameters)
    base_request = {
        "model": model_name,
        "input": [deepcopy(dict(message)) for message in messages],
        "stream": False,
    }
    request = deep_merge_model_request(
        base_request,
        model_defaults,
        model_parameters,
    )
    request.pop("messages", None)
    return request


def build_anthropic_request(
    *,
    model_name: str,
    messages: Sequence[Mapping[str, Any]],
    system_prompt: str = "",
    model_defaults: Mapping[str, Any] | None = None,
    model_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an Anthropic Messages request with fully overridable body fields."""

    validate_protocol_parameters(
        ANTHROPIC_CLAUDE_MESSAGES, model_defaults, model_parameters
    )
    base_request: dict[str, Any] = {
        "model": model_name,
        "messages": [deepcopy(dict(message)) for message in messages],
        "max_tokens": DEFAULT_ANTHROPIC_MAX_TOKENS,
        "stream": False,
    }
    if system_prompt.strip():
        base_request["system"] = system_prompt
    return deep_merge_model_request(
        base_request,
        model_defaults,
        model_parameters,
    )


def build_model_request(
    protocol: str,
    *,
    model_name: str,
    messages: Sequence[Mapping[str, Any]],
    model_defaults: Mapping[str, Any] | None = None,
    model_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if protocol == ANTHROPIC_CLAUDE_MESSAGES:
        system_parts = [
            str(message.get("content", ""))
            for message in messages
            if str(message.get("role", "")).lower() == "system"
            and str(message.get("content", "")).strip()
        ]
        anthropic_messages = [
            message
            for message in messages
            if str(message.get("role", "")).lower() != "system"
        ]
        return build_anthropic_request(
            model_name=model_name,
            messages=anthropic_messages,
            system_prompt="\n\n".join(system_parts),
            model_defaults=model_defaults,
            model_parameters=model_parameters,
        )
    if protocol == OPENAI_RESPONSES:
        return build_responses_request(
            model_name=model_name,
            messages=messages,
            model_defaults=model_defaults,
            model_parameters=model_parameters,
        )
    if protocol == OPENAI_CHAT_COMPLETIONS:
        return build_chat_completion_request(
            model_name=model_name,
            messages=messages,
            model_defaults=model_defaults,
            model_parameters=model_parameters,
        )
    raise ValueError(f"不支持的模型协议: {protocol}")


def chat_completions_url(base_url: str) -> str:
    return model_inference_url(OPENAI_CHAT_COMPLETIONS, base_url)


def responses_url(base_url: str) -> str:
    return model_inference_url(OPENAI_RESPONSES, base_url)


def anthropic_messages_url(base_url: str) -> str:
    return model_inference_url(ANTHROPIC_CLAUDE_MESSAGES, base_url)


def model_http_client_options(
    base_url: str,
    *,
    timeout_seconds: float,
    proxy_mode: str = "SYSTEM",
    proxy_url: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    verify_ssl: bool = True,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "follow_redirects": True,
        "timeout": timeout_seconds,
    }
    if proxy_mode == "DIRECT":
        options["trust_env"] = False
    elif proxy_mode == "CUSTOM":
        if not proxy_url:
            raise ValueError("自定义代理模式缺少代理 URL")
        options.update(
            {
                "trust_env": False,
                "proxy": _proxy_url_with_auth(
                    proxy_url,
                    username=proxy_username,
                    password=proxy_password,
                ),
            }
        )
    elif proxy_mode != "SYSTEM":
        raise ValueError(f"不支持的代理模式: {proxy_mode}")
    if not verify_ssl:
        options["verify"] = False
    return options


def _proxy_url_with_auth(
    proxy_url: str,
    *,
    username: str | None,
    password: str | None,
) -> str:
    if not username:
        return proxy_url
    parsed = urlsplit(proxy_url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    credentials = quote(username, safe="")
    if password is not None:
        credentials += ":" + quote(password, safe="")
    netloc = f"{credentials}@{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def anthropic_headers(api_key: str) -> dict[str, str]:
    return model_protocol_headers(ANTHROPIC_CLAUDE_MESSAGES, api_key)


async def _invoke_endpoint(
    protocol: str,
    *,
    base_url: str,
    api_key: str,
    request_body: Mapping[str, Any],
    timeout_seconds: float,
    proxy_mode: str,
    proxy_url: str | None,
    proxy_username: str | None,
    proxy_password: str | None,
    verify_ssl: bool,
    client: httpx.AsyncClient | None,
) -> httpx.Response:
    if protocol not in {
        OPENAI_CHAT_COMPLETIONS,
        OPENAI_RESPONSES,
        ANTHROPIC_CLAUDE_MESSAGES,
    }:
        raise ValueError(f"不支持的模型协议: {protocol}")
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        **model_http_client_options(
            base_url,
            timeout_seconds=timeout_seconds,
            proxy_mode=proxy_mode,
            proxy_url=proxy_url,
            proxy_username=proxy_username,
            proxy_password=proxy_password,
            verify_ssl=verify_ssl,
        ),
    )
    try:
        return await active_client.post(
            model_inference_url(protocol, base_url),
            headers=model_protocol_headers(protocol, api_key),
            json=deepcopy(dict(request_body)),
        )
    finally:
        if owns_client:
            await active_client.aclose()


async def invoke_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    request_body: Mapping[str, Any],
    timeout_seconds: float = 120,
    proxy_mode: str = "SYSTEM",
    proxy_url: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    verify_ssl: bool = True,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """Send a prepared request without translating provider-specific parameters."""

    return await _invoke_endpoint(
        OPENAI_CHAT_COMPLETIONS,
        base_url=base_url,
        api_key=api_key,
        request_body=request_body,
        timeout_seconds=timeout_seconds,
        proxy_mode=proxy_mode,
        proxy_url=proxy_url,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
        verify_ssl=verify_ssl,
        client=client,
    )


async def invoke_openai_responses(
    *,
    base_url: str,
    api_key: str,
    request_body: Mapping[str, Any],
    timeout_seconds: float = 120,
    proxy_mode: str = "SYSTEM",
    proxy_url: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    verify_ssl: bool = True,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """Send a prepared native OpenAI Responses API request."""

    return await _invoke_endpoint(
        OPENAI_RESPONSES,
        base_url=base_url,
        api_key=api_key,
        request_body=request_body,
        timeout_seconds=timeout_seconds,
        proxy_mode=proxy_mode,
        proxy_url=proxy_url,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
        verify_ssl=verify_ssl,
        client=client,
    )


async def invoke_anthropic(
    *,
    base_url: str,
    api_key: str,
    request_body: Mapping[str, Any],
    timeout_seconds: float = 120,
    proxy_mode: str = "SYSTEM",
    proxy_url: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    verify_ssl: bool = True,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """Send a prepared native Anthropic Messages request."""

    return await _invoke_endpoint(
        ANTHROPIC_CLAUDE_MESSAGES,
        base_url=base_url,
        api_key=api_key,
        request_body=request_body,
        timeout_seconds=timeout_seconds,
        proxy_mode=proxy_mode,
        proxy_url=proxy_url,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
        verify_ssl=verify_ssl,
        client=client,
    )


async def invoke_model_protocol(
    protocol: str,
    *,
    base_url: str,
    api_key: str,
    request_body: Mapping[str, Any],
    timeout_seconds: float = 120,
    proxy_mode: str = "SYSTEM",
    proxy_url: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    verify_ssl: bool = True,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    return await _invoke_endpoint(
        protocol,
        base_url=base_url,
        api_key=api_key,
        request_body=request_body,
        timeout_seconds=timeout_seconds,
        proxy_mode=proxy_mode,
        proxy_url=proxy_url,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
        verify_ssl=verify_ssl,
        client=client,
    )


def parse_openai_compatible_response(
    response: httpx.Response,
    *,
    stream: bool,
) -> dict[str, Any]:
    """Extract final output and usage from buffered JSON or SSE responses."""

    if stream:
        return _parse_streaming_response(response.text)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("模型响应不是合法 JSON") from exc
    return parse_openai_compatible_payload(payload)


def parse_openai_compatible_payload(payload: Any) -> dict[str, Any]:
    """Normalize a buffered OpenAI-compatible response payload."""

    if not isinstance(payload, dict):
        raise ValueError("模型响应必须是 JSON 对象")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("模型响应缺少 choices")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("模型响应缺少 message")
    output = message.get("content")
    if output in (None, ""):
        output = message.get("reasoning_content")
    if output in (None, ""):
        output = deepcopy(message)
    usage = payload.get("usage")
    return {
        "output": deepcopy(output),
        "usage": deepcopy(usage) if isinstance(usage, dict) else None,
        "finish_reason": choice.get("finish_reason"),
    }


def parse_openai_responses_response(response: httpx.Response) -> dict[str, Any]:
    """Extract text, usage, and completion state from a Responses API result."""

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("模型响应不是合法 JSON") from exc
    return parse_openai_responses_payload(payload)


def parse_openai_responses_payload(payload: Any) -> dict[str, Any]:
    """Normalize a Responses payload without exposing reasoning as output."""

    if not isinstance(payload, dict):
        raise ValueError("模型响应必须是 JSON 对象")

    output: Any = payload.get("output_text")
    output_items = payload.get("output")
    if not isinstance(output, str) or not output:
        if not isinstance(output_items, list):
            raise ValueError("Responses API 模型响应缺少 output")
        text_parts = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        output = "".join(text_parts) or deepcopy(output_items)

    status = payload.get("status")
    incomplete_details = payload.get("incomplete_details")
    finish_reason = status
    if status == "incomplete" and isinstance(incomplete_details, dict):
        finish_reason = incomplete_details.get("reason") or status
    usage = payload.get("usage")
    return {
        "output": deepcopy(output),
        "usage": deepcopy(usage) if isinstance(usage, dict) else None,
        "finish_reason": finish_reason,
    }


def parse_anthropic_response(response: httpx.Response) -> dict[str, Any]:
    """Extract final output and usage from a native Anthropic message response."""

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("模型响应不是合法 JSON") from exc
    return parse_anthropic_payload(payload)


def parse_anthropic_payload(payload: Any) -> dict[str, Any]:
    """Normalize a buffered Anthropic Messages response payload."""

    if not isinstance(payload, dict):
        raise ValueError("模型响应必须是 JSON 对象")
    content = payload.get("content")
    if not isinstance(content, list):
        raise ValueError("Anthropic 模型响应缺少 content")
    text_parts = [
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    output: Any = "".join(text_parts)
    if not output:
        output = deepcopy(content)
    usage = payload.get("usage")
    return {
        "output": output,
        "usage": deepcopy(usage) if isinstance(usage, dict) else None,
        "finish_reason": payload.get("stop_reason"),
    }


def parse_model_payload(protocol: str, payload: Any) -> dict[str, Any]:
    parser = {
        OPENAI_CHAT_COMPLETIONS: parse_openai_compatible_payload,
        OPENAI_RESPONSES: parse_openai_responses_payload,
        ANTHROPIC_CLAUDE_MESSAGES: parse_anthropic_payload,
    }.get(protocol)
    if parser is None:
        raise ValueError(f"不支持的模型协议: {protocol}")
    return parser(payload)


def parse_model_response(protocol: str, response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("模型响应不是合法 JSON") from exc
    return parse_model_payload(protocol, payload)


def extract_streaming_usage(body: str) -> dict[str, Any] | None:
    """Collect usage fields from OpenAI-compatible or Anthropic SSE events."""

    usage: dict[str, Any] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = httpx.Response(200, content=data).json()
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        candidates = [payload.get("usage")]
        message = payload.get("message")
        if isinstance(message, dict):
            candidates.append(message.get("usage"))
        for candidate in candidates:
            if isinstance(candidate, dict):
                usage.update(deepcopy(candidate))
    return usage or None


def _parse_streaming_response(body: str) -> dict[str, Any]:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: dict[str, Any] | None = None
    finish_reason: Any = None
    event_count = 0
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = httpx.Response(200, content=data).json()
        except ValueError as exc:
            raise ValueError("流式模型响应包含非法 JSON 事件") from exc
        if not isinstance(payload, dict):
            continue
        event_count += 1
        if isinstance(payload.get("usage"), dict):
            usage = deepcopy(payload["usage"])
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            continue
        choice = choices[0]
        finish_reason = choice.get("finish_reason") or finish_reason
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        if isinstance(delta.get("content"), str):
            content_parts.append(delta["content"])
        if isinstance(delta.get("reasoning_content"), str):
            reasoning_parts.append(delta["reasoning_content"])
    if event_count == 0:
        raise ValueError("流式模型响应不包含 data 事件")
    output = "".join(content_parts) or "".join(reasoning_parts)
    if not output:
        raise ValueError("流式模型响应没有输出内容")
    return {
        "output": output,
        "usage": usage,
        "finish_reason": finish_reason,
    }
