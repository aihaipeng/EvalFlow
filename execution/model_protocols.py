"""Protocol contracts shared by provider management and workflow execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


OPENAI_CHAT_COMPLETIONS = "OPENAI_COMPATIBLE"
OPENAI_RESPONSES = "OPENAI_RESPONSES"
ANTHROPIC_CLAUDE_MESSAGES = "ANTHROPIC"
ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class ModelProtocolContract:
    code: str
    label: str
    endpoint_suffix: str
    forbidden_fields: frozenset[str]


MODEL_PROTOCOL_CONTRACTS = {
    OPENAI_CHAT_COMPLETIONS: ModelProtocolContract(
        code=OPENAI_CHAT_COMPLETIONS,
        label="OpenAI Chat Completions",
        endpoint_suffix="/chat/completions",
        forbidden_fields=frozenset(
            {"input", "instructions", "max_output_tokens", "system", "anthropic_version"}
        ),
    ),
    OPENAI_RESPONSES: ModelProtocolContract(
        code=OPENAI_RESPONSES,
        label="OpenAI Responses API",
        endpoint_suffix="/responses",
        forbidden_fields=frozenset(
            {
                "messages",
                "max_tokens",
                "max_completion_tokens",
                "response_format",
                "system",
                "stop_sequences",
            }
        ),
    ),
    ANTHROPIC_CLAUDE_MESSAGES: ModelProtocolContract(
        code=ANTHROPIC_CLAUDE_MESSAGES,
        label="Anthropic Claude Messages",
        endpoint_suffix="/messages",
        forbidden_fields=frozenset(
            {
                "input",
                "instructions",
                "max_output_tokens",
                "max_completion_tokens",
                "response_format",
                "reasoning",
                "reasoning_effort",
                "text",
                "seed",
                "frequency_penalty",
                "presence_penalty",
                "logprobs",
                "top_logprobs",
            }
        ),
    ),
}

_KNOWN_INFERENCE_SUFFIXES = ("/chat/completions", "/responses", "/messages")


def model_protocol_contract(protocol: str) -> ModelProtocolContract:
    try:
        return MODEL_PROTOCOL_CONTRACTS[str(protocol)]
    except KeyError as exc:
        raise ValueError(f"不支持的模型协议: {protocol}") from exc


def model_api_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip().rstrip("/"))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("BASE_URL 必须是有效的 HTTP 或 HTTPS 地址")
    path = parsed.path.rstrip("/")
    for suffix in _KNOWN_INFERENCE_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def model_inference_url(protocol: str, base_url: str) -> str:
    contract = model_protocol_contract(protocol)
    parsed = urlsplit(model_api_base_url(base_url))
    path = parsed.path.rstrip("/")
    if protocol == ANTHROPIC_CLAUDE_MESSAGES and path.rsplit("/", 1)[-1].lower() not in {
        "v1",
        "v2",
    }:
        path = f"{path}/v1"
    path = f"{path}{contract.endpoint_suffix}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def model_protocol_headers(protocol: str, api_key: str) -> dict[str, str]:
    model_protocol_contract(protocol)
    if protocol == ANTHROPIC_CLAUDE_MESSAGES:
        return {
            "accept": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "x-api-key": api_key,
        }
    return {
        "accept": "application/json",
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }


def validate_protocol_parameters(
    protocol: str,
    *layers: Mapping[str, Any] | None,
) -> None:
    contract = model_protocol_contract(protocol)
    incompatible: set[str] = set()
    for layer in layers:
        if layer is None:
            continue
        if not isinstance(layer, Mapping):
            raise TypeError("模型请求参数必须是 JSON 对象")
        incompatible.update(set(layer) & contract.forbidden_fields)
    if incompatible:
        fields = "、".join(sorted(incompatible))
        raise ValueError(
            f"{contract.label} 不支持参数：{fields}。请移除其他协议的字段后重试"
        )
