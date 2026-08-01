import asyncio
import json

import httpx
import pytest

from execution import (
    DEFAULT_ANTHROPIC_MAX_TOKENS,
    anthropic_messages_url,
    build_anthropic_request,
    build_chat_completion_request,
    build_model_request,
    build_responses_request,
    chat_completions_url,
    deep_merge_model_request,
    extract_streaming_usage,
    invoke_anthropic,
    invoke_openai_compatible,
    invoke_openai_responses,
    model_inference_url,
    model_http_client_options,
    model_protocol_headers,
    parse_anthropic_response,
    parse_model_payload,
    parse_openai_compatible_response,
    parse_openai_responses_response,
    responses_url,
)


def test_deep_merge_lets_user_parameters_override_every_request_field():
    base = {
        "model": "model-from-selector",
        "messages": [{"role": "user", "content": "base"}],
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"strict": False, "name": "base"},
        },
        "stop": ["base"],
    }
    defaults = {
        "temperature": 0.7,
        "response_format": {"json_schema": {"strict": True}},
    }
    user = {
        "model": "model-from-user",
        "messages": [{"role": "user", "content": "override"}],
        "stream": True,
        "response_format": {"json_schema": {"name": "user"}},
        "stop": ["user"],
    }

    merged = deep_merge_model_request(base, defaults, user)

    assert merged == {
        "model": "model-from-user",
        "messages": [{"role": "user", "content": "override"}],
        "stream": True,
        "temperature": 0.7,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"strict": True, "name": "user"},
        },
        "stop": ["user"],
    }
    assert base["response_format"]["json_schema"]["name"] == "base"


def test_build_chat_request_keeps_provider_defaults_when_user_does_not_override():
    request = build_chat_completion_request(
        model_name="qwen-plus",
        messages=[{"role": "user", "content": "hello"}],
        model_defaults={
            "temperature": 0.5,
            "thinking": {"enabled": False, "budget": 1024},
        },
        model_parameters={
            "thinking": {"enabled": True},
            "enable_thinking": True,
        },
    )

    assert request == {
        "model": "qwen-plus",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
        "temperature": 0.5,
        "thinking": {"enabled": True, "budget": 1024},
        "enable_thinking": True,
    }
    assert "max_tokens" not in request
    assert "max_completion_tokens" not in request


def test_chat_completions_url_preserves_gateway_base_path():
    assert chat_completions_url("https://api.deepseek.com") == (
        "https://api.deepseek.com/chat/completions"
    )
    assert chat_completions_url(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/"
    ) == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert chat_completions_url(
        "https://gateway.example/v1/chat/completions"
    ) == "https://gateway.example/v1/chat/completions"


def test_responses_request_and_url_use_native_contract():
    request = build_responses_request(
        model_name="gpt-5",
        messages=[{"role": "user", "content": "hello"}],
        model_defaults={
            "reasoning": {"effort": "medium"},
            "temperature": 0.2,
            "max_output_tokens": 512,
        },
        model_parameters={
            "reasoning": {"summary": "auto"},
            "max_output_tokens": 256,
        },
    )

    assert request == {
        "model": "gpt-5",
        "input": [{"role": "user", "content": "hello"}],
        "stream": False,
        "reasoning": {"effort": "medium", "summary": "auto"},
        "temperature": 0.2,
        "max_output_tokens": 256,
    }
    assert "messages" not in request
    assert responses_url("https://api.openai.com/v1") == (
        "https://api.openai.com/v1/responses"
    )
    assert responses_url("https://gateway.example/v1/responses") == (
        "https://gateway.example/v1/responses"
    )
    assert responses_url("https://gateway.example/v1/chat/completions") == (
        "https://gateway.example/v1/responses"
    )


def test_protocol_urls_normalize_other_protocol_endpoints():
    assert chat_completions_url("https://gateway.example/v1/responses") == (
        "https://gateway.example/v1/chat/completions"
    )
    assert anthropic_messages_url(
        "https://gateway.example/v1/chat/completions"
    ) == "https://gateway.example/v1/messages"
    assert responses_url("https://gateway.example/v1/messages") == (
        "https://gateway.example/v1/responses"
    )


@pytest.mark.parametrize(
    ("protocol", "parameters", "field"),
    [
        ("OPENAI_COMPATIBLE", {"input": "wrong"}, "input"),
        ("OPENAI_RESPONSES", {"messages": []}, "messages"),
        ("ANTHROPIC", {"response_format": {"type": "json_object"}}, "response_format"),
    ],
)
def test_protocol_request_rejects_fields_from_other_protocols(
    protocol, parameters, field
):
    with pytest.raises(ValueError, match=field):
        build_model_request(
            protocol,
            model_name="model",
            messages=[{"role": "user", "content": "hello"}],
            model_parameters=parameters,
        )


@pytest.mark.parametrize(
    ("protocol", "url_suffix", "request_field", "payload", "expected_output"),
    [
        (
            "OPENAI_COMPATIBLE",
            "/chat/completions",
            "messages",
            {"choices": [{"message": {"content": "chat"}}]},
            "chat",
        ),
        (
            "OPENAI_RESPONSES",
            "/responses",
            "input",
            {"status": "completed", "output_text": "responses"},
            "responses",
        ),
        (
            "ANTHROPIC",
            "/messages",
            "messages",
            {"content": [{"type": "text", "text": "claude"}]},
            "claude",
        ),
    ],
)
def test_protocol_adapter_contract_matrix(
    protocol, url_suffix, request_field, payload, expected_output
):
    request = build_model_request(
        protocol,
        model_name="model",
        messages=[
            {"role": "system", "content": "policy"},
            {"role": "user", "content": "hello"},
        ],
    )
    headers = model_protocol_headers(protocol, "secret")

    assert model_inference_url(
        protocol, "https://gateway.example/v1/chat/completions"
    ).endswith(url_suffix)
    assert request_field in request
    assert parse_model_payload(protocol, payload)["output"] == expected_output
    if protocol == "ANTHROPIC":
        assert request["system"] == "policy"
        assert "authorization" not in headers
        assert headers["x-api-key"] == "secret"
    else:
        assert headers["authorization"] == "Bearer secret"
        assert "x-api-key" not in headers


def test_anthropic_request_uses_required_default_and_user_overrides():
    request = build_anthropic_request(
        model_name="claude-sonnet",
        system_prompt="Follow policy",
        messages=[{"role": "user", "content": "Review this"}],
        model_defaults={"temperature": 0.2, "metadata": {"source": "default"}},
        model_parameters={
            "max_tokens": 16384,
            "thinking": {"type": "enabled", "budget_tokens": 2048},
            "metadata": {"case": "42"},
        },
    )

    assert request == {
        "model": "claude-sonnet",
        "system": "Follow policy",
        "messages": [{"role": "user", "content": "Review this"}],
        "max_tokens": 16384,
        "stream": False,
        "temperature": 0.2,
        "thinking": {"type": "enabled", "budget_tokens": 2048},
        "metadata": {"source": "default", "case": "42"},
    }
    assert DEFAULT_ANTHROPIC_MAX_TOKENS >= 8192
    assert build_anthropic_request(
        model_name="claude-sonnet",
        messages=[{"role": "user", "content": "hello"}],
    )["max_tokens"] == DEFAULT_ANTHROPIC_MAX_TOKENS


def test_anthropic_url_and_explicit_proxy_client_policy():
    assert anthropic_messages_url("https://api.anthropic.com") == (
        "https://api.anthropic.com/v1/messages"
    )
    assert anthropic_messages_url("https://gateway.example/anthropic/v1") == (
        "https://gateway.example/anthropic/v1/messages"
    )
    assert anthropic_messages_url("https://gateway.example/v1/messages") == (
        "https://gateway.example/v1/messages"
    )
    internal = model_http_client_options(
        "https://10.20.30.40:8443/v1", timeout_seconds=120
    )
    public = model_http_client_options(
        "https://api.anthropic.com", timeout_seconds=120
    )
    assert internal == {"follow_redirects": True, "timeout": 120}
    assert public == {"follow_redirects": True, "timeout": 120}
    assert model_http_client_options(
        "https://api.anthropic.com",
        timeout_seconds=120,
        proxy_mode="DIRECT",
    ) == {
        "follow_redirects": True,
        "timeout": 120,
        "trust_env": False,
    }
    assert model_http_client_options(
        "https://api.anthropic.com",
        timeout_seconds=120,
        proxy_mode="SYSTEM",
        verify_ssl=False,
    ) == {
        "follow_redirects": True,
        "timeout": 120,
        "verify": False,
    }
    assert model_http_client_options(
        "https://10.20.30.40:8443/v1",
        timeout_seconds=120,
        verify_ssl=False,
    ) == {
        "follow_redirects": True,
        "timeout": 120,
        "verify": False,
    }
    assert model_http_client_options(
        "https://api.anthropic.com",
        timeout_seconds=120,
        proxy_mode="CUSTOM",
        proxy_url="http://proxy.internal:8080",
        proxy_username="domain user",
        proxy_password="p@ss:word",
        verify_ssl=False,
    ) == {
        "follow_redirects": True,
        "timeout": 120,
        "trust_env": False,
        "proxy": "http://domain%20user:p%40ss%3Aword@proxy.internal:8080",
        "verify": False,
    }
    assert model_http_client_options(
        "https://10.20.30.40:8443/v1",
        timeout_seconds=120,
        proxy_mode="CUSTOM",
        proxy_url="http://proxy.internal:8080",
    ) == {
        "follow_redirects": True,
        "timeout": 120,
        "trust_env": False,
        "proxy": "http://proxy.internal:8080",
    }


def test_openai_compatible_transport_forwards_body_without_parameter_translation():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await invoke_openai_compatible(
                base_url="https://gateway.example/v1",
                api_key="test-secret",
                request_body={
                    "model": "custom-model",
                    "messages": [],
                    "enable_thinking": True,
                    "vendor_extension": {"level": "high"},
                },
                client=client,
            )

    response = asyncio.run(invoke())

    assert response.status_code == 200
    assert captured == {
        "url": "https://gateway.example/v1/chat/completions",
        "authorization": "Bearer test-secret",
        "body": {
            "model": "custom-model",
            "messages": [],
            "enable_thinking": True,
            "vendor_extension": {"level": "high"},
        },
    }


def test_openai_responses_transport_and_parser_keep_native_contract():
    captured = {}
    native_response = {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "content": [
                    {"type": "reasoning_text", "text": "internal reasoning"}
                ],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "model "},
                    {"type": "output_text", "text": "ready"},
                ],
            }
        ],
        "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=native_response)

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await invoke_openai_responses(
                base_url="https://gateway.example/v1/chat/completions",
                api_key="responses-secret",
                request_body={
                    "model": "gpt-5",
                    "input": [{"role": "user", "content": "check"}],
                    "reasoning": {"effort": "low"},
                },
                client=client,
            )

    response = asyncio.run(invoke())

    assert captured == {
        "url": "https://gateway.example/v1/responses",
        "authorization": "Bearer responses-secret",
        "body": {
            "model": "gpt-5",
            "input": [{"role": "user", "content": "check"}],
            "reasoning": {"effort": "low"},
        },
    }
    assert parse_openai_responses_response(response) == {
        "output": "model ready",
        "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
        "finish_reason": "completed",
    }


def test_anthropic_transport_and_response_parser_keep_native_contract():
    captured = {}
    native_response = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "internal"},
            {"type": "text", "text": "policy "},
            {"type": "text", "text": "failed"},
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 8},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers["x-api-key"]
        captured["version"] = request.headers["anthropic-version"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=native_response)

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await invoke_anthropic(
                base_url="https://gateway.example/anthropic/v1",
                api_key="anthropic-secret",
                request_body={
                    "model": "claude-sonnet",
                    "messages": [{"role": "user", "content": "review"}],
                    "max_tokens": 8192,
                },
                client=client,
            )

    response = asyncio.run(invoke())

    assert captured == {
        "url": "https://gateway.example/anthropic/v1/messages",
        "api_key": "anthropic-secret",
        "version": "2023-06-01",
        "body": {
            "model": "claude-sonnet",
            "messages": [{"role": "user", "content": "review"}],
            "max_tokens": 8192,
        },
    }
    assert parse_anthropic_response(response) == {
        "output": "policy failed",
        "usage": {"input_tokens": 12, "output_tokens": 8},
        "finish_reason": "end_turn",
    }


def test_parse_streaming_response_combines_output_and_usage():
    response = httpx.Response(
        200,
        text=(
            'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"world"},"finish_reason":"stop"}],'
            '"usage":{"total_tokens":12}}\n\n'
            "data: [DONE]\n\n"
        ),
    )

    assert parse_openai_compatible_response(response, stream=True) == {
        "output": "hello world",
        "usage": {"total_tokens": 12},
        "finish_reason": "stop",
    }


def test_extract_streaming_usage_supports_openai_and_anthropic_events():
    openai_body = (
        'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":5,'
        '"total_tokens":12}}\n\n'
        "data: [DONE]\n\n"
    )
    anthropic_body = (
        'event: message_start\n'
        'data: {"type":"message_start","message":{"usage":{"input_tokens":9,'
        '"output_tokens":1}}}\n\n'
        'event: message_delta\n'
        'data: {"type":"message_delta","usage":{"output_tokens":6}}\n\n'
    )

    assert extract_streaming_usage(openai_body) == {
        "prompt_tokens": 7,
        "completion_tokens": 5,
        "total_tokens": 12,
    }
    assert extract_streaming_usage(anthropic_body) == {
        "input_tokens": 9,
        "output_tokens": 6,
    }
    assert extract_streaming_usage("data: not-json\n\n") is None
