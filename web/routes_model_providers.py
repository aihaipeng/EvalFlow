"""Model provider management, latency testing, and model discovery APIs."""

from __future__ import annotations

import re
import time
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from execution import (
    ModelProviderConfiguration,
    ModelProviderProtocol,
    ModelProviderProxyMode,
    ModelProviderRecord,
    ModelProviderRepository,
    ModelProviderRepositoryError,
    ModelProviderSummary,
    build_model_request,
    invoke_model_protocol,
    model_api_base_url,
    model_http_client_options,
    model_protocol_headers,
    parse_model_response,
    redact_sensitive_text,
    validate_protocol_parameters,
)
from web.workflow_services import WorkflowServices


router = APIRouter(prefix="/api/model-providers", tags=["model-providers"])
REQUEST_TIMEOUT_SECONDS = 12


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ProviderConnectionRequest(_StrictModel):
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(min_length=1, max_length=4096)
    protocol: ModelProviderProtocol = ModelProviderProtocol.OPENAI_COMPATIBLE
    proxy_mode: ModelProviderProxyMode = ModelProviderProxyMode.SYSTEM
    proxy_url: str | None = Field(default=None, max_length=2048)
    proxy_username: str | None = Field(default=None, max_length=512)
    proxy_password: str | None = Field(default=None, max_length=4096)
    verify_ssl: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BASE_URL 必须是有效的 HTTP 或 HTTPS 地址")
        if parsed.username or parsed.password:
            raise ValueError("BASE_URL 不能包含用户名或密码")
        if parsed.query or parsed.fragment:
            raise ValueError("BASE_URL 不能包含 query 或 fragment")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("BASE_URL 端口无效") from exc
        return normalized

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("API Key 不能为空")
        return value

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: ModelProviderProtocol) -> ModelProviderProtocol:
        if value == ModelProviderProtocol.MANUAL:
            raise ValueError(
                "模型协议只支持 OPENAI_COMPATIBLE、OPENAI_RESPONSES 或 ANTHROPIC"
            )
        return value

    @field_validator("proxy_url", mode="before")
    @classmethod
    def validate_proxy_url(cls, value: object) -> str | None:
        if value is None or not str(value).strip():
            return None
        normalized = str(value).strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"http", "https", "socks5", "socks5h"}:
            raise ValueError("代理 URL 只支持 HTTP(S) 或 SOCKS5")
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("代理 URL 格式无效")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("代理 URL 端口无效") from exc
        return normalized

    @field_validator("proxy_username", "proxy_password", mode="before")
    @classmethod
    def normalize_proxy_credentials(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_proxy(self) -> "ProviderConnectionRequest":
        if self.proxy_mode == ModelProviderProxyMode.CUSTOM and not self.proxy_url:
            raise ValueError("自定义代理模式必须填写代理 URL")
        if self.proxy_mode == ModelProviderProxyMode.CUSTOM:
            if self.proxy_password and not self.proxy_username:
                raise ValueError("填写代理密码时必须同时填写用户名")
        else:
            self.proxy_url = None
            self.proxy_username = None
            self.proxy_password = None
        return self


class ModelAvailabilityRequest(ProviderConnectionRequest):
    model_name: str = Field(min_length=1, max_length=200)
    default_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_name")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("模型名称不能为空")
        return normalized


class ProviderEnvelope(_StrictModel):
    provider: ModelProviderRecord


class ProviderSummaryEnvelope(_StrictModel):
    provider: ModelProviderSummary


class ProviderListResponse(_StrictModel):
    providers: list[ModelProviderSummary]


class ProviderLatencyResponse(_StrictModel):
    reachable: bool
    latency_ms: int
    status_code: int


class ProviderDiscoveredModel(_StrictModel):
    id: str
    owned_by: str | None = None


class ProviderModelsResponse(_StrictModel):
    protocol: str
    endpoint: str
    latency_ms: int
    models: list[ProviderDiscoveredModel]


class ModelAvailabilityResponse(_StrictModel):
    available: bool
    latency_ms: int
    status_code: int | None
    output: Any = None
    response_body: str
    error: str | None


def get_model_repository(request: Request) -> ModelProviderRepository:
    services: WorkflowServices = request.app.state.workflow_services
    return services.model_repository


ModelRepositoryDependency = Annotated[
    ModelProviderRepository,
    Depends(get_model_repository),
]


def _get_provider_or_404(
    provider_id: str,
    repository: ModelProviderRepository,
) -> ModelProviderRecord:
    provider = repository.get(provider_id)
    if provider is None:
        raise HTTPException(404, f"模型供应商不存在: {provider_id}")
    return provider


def build_model_candidates(base_url: str) -> list[str]:
    validated = ProviderConnectionRequest(base_url=base_url, api_key="x").base_url
    base = model_api_base_url(validated)
    parsed = urlsplit(base)
    path = parsed.path.rstrip("/")
    candidates = [f"{base}/models"] if re.search(r"/v\d+$", path) else [
        f"{base}/v1/models", f"{base}/models"
    ]
    return list(dict.fromkeys(candidates))


def extract_models(payload: Any) -> list[dict[str, str | None]]:
    if not isinstance(payload, dict):
        return []
    entries = payload.get("data")
    if not isinstance(entries, list):
        entries = payload.get("models")
    if not isinstance(entries, list):
        return []
    models: dict[str, dict[str, str | None]] = {}
    for entry in entries:
        if isinstance(entry, str):
            model_id, owner = entry.strip(), None
        elif isinstance(entry, dict):
            raw_id = entry.get("id") or entry.get("name")
            model_id = str(raw_id).strip() if raw_id is not None else ""
            raw_owner = entry.get("owned_by") or entry.get("ownedBy")
            owner = str(raw_owner) if raw_owner is not None else None
        else:
            continue
        if model_id:
            models[model_id] = {"id": model_id, "owned_by": owner}
    return [models[model_id] for model_id in sorted(models, key=str.casefold)]


def _protocol_headers(protocol: str, api_key: str) -> dict[str, str]:
    return model_protocol_headers(protocol, api_key)


def _protocol_value(protocol: ModelProviderProtocol | str) -> str:
    return protocol.value if isinstance(protocol, ModelProviderProtocol) else protocol


def _validate_provider_default_bodies(body: ModelProviderConfiguration) -> None:
    protocol = _protocol_value(body.protocol)
    for model_name, config in body.model_configs.items():
        try:
            validate_protocol_parameters(protocol, config.default_body)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"模型“{model_name}”默认 Body 无效：{exc}") from exc


def _require_provider_models(body: ModelProviderConfiguration) -> None:
    if not body.models:
        raise HTTPException(422, "至少添加一个模型")


@router.get("", response_model=ProviderListResponse)
def list_providers(repository: ModelRepositoryDependency) -> ProviderListResponse:
    return ProviderListResponse(
        providers=[ModelProviderSummary.from_record(item) for item in repository.list()]
    )


@router.post("", response_model=ProviderEnvelope)
def create_provider(
    body: ModelProviderConfiguration,
    repository: ModelRepositoryDependency,
) -> ProviderEnvelope:
    _require_provider_models(body)
    _validate_provider_default_bodies(body)
    try:
        provider = repository.create(
            ModelProviderRecord(**body.model_dump(mode="json"))
        )
    except ModelProviderRepositoryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ProviderEnvelope(provider=provider)


@router.post("/latency", response_model=ProviderLatencyResponse)
async def test_latency(body: ProviderConnectionRequest) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            **model_http_client_options(
                body.base_url,
                timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                proxy_mode=body.proxy_mode,
                proxy_url=body.proxy_url,
                proxy_username=body.proxy_username,
                proxy_password=body.proxy_password,
                verify_ssl=body.verify_ssl,
            )
        ) as client:
            async with client.stream(
                "GET", body.base_url,
                headers={"user-agent": "AgentBenchModelProvider/1.0"},
            ) as response:
                return {
                    "reachable": True,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000),
                    "status_code": response.status_code,
                }
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"BASE_URL 无法访问: {type(exc).__name__}") from exc


@router.post("/models", response_model=ProviderModelsResponse)
async def fetch_models(body: ProviderConnectionRequest) -> dict[str, Any]:
    attempts: list[str] = []
    async with httpx.AsyncClient(
        **model_http_client_options(
            body.base_url,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            proxy_mode=body.proxy_mode,
            proxy_url=body.proxy_url,
            proxy_username=body.proxy_username,
            proxy_password=body.proxy_password,
            verify_ssl=body.verify_ssl,
        )
    ) as client:
        for endpoint in build_model_candidates(body.base_url):
            protocol = _protocol_value(body.protocol)
            started_at = time.perf_counter()
            try:
                response = await client.get(
                    endpoint, headers=_protocol_headers(protocol, body.api_key)
                )
            except httpx.HTTPError as exc:
                attempts.append(f"{protocol} {endpoint}: {type(exc).__name__}")
                continue
            if not response.is_success:
                attempts.append(f"{protocol} {endpoint}: HTTP {response.status_code}")
                continue
            try:
                models = extract_models(response.json())
            except ValueError:
                attempts.append(f"{protocol} {endpoint}: 响应不是 JSON")
                continue
            if not models:
                attempts.append(f"{protocol} {endpoint}: 未发现模型")
                continue
            return {
                "protocol": protocol,
                "endpoint": endpoint,
                "latency_ms": round((time.perf_counter() - started_at) * 1000),
                "models": models,
            }
    summary = "；".join(attempts[-4:]) if attempts else "没有可用的模型端点"
    raise HTTPException(502, f"自动获取模型失败，可手工添加模型。{summary}")


@router.post("/test-model", response_model=ModelAvailabilityResponse)
async def test_model_availability(body: ModelAvailabilityRequest) -> dict[str, Any]:
    prompt = "请回复：模型连接正常。不要补充其他内容。"
    messages = [{"role": "user", "content": prompt}]
    protocol = _protocol_value(body.protocol)
    try:
        request_body = build_model_request(
            protocol,
            model_name=body.model_name,
            messages=messages,
            model_defaults=body.default_body,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    request_body["model"] = body.model_name
    request_body["stream"] = False
    if protocol == "OPENAI_RESPONSES":
        request_body["input"] = messages
    else:
        request_body["messages"] = messages
    started_at = time.perf_counter()
    try:
        response = await invoke_model_protocol(
            protocol,
            base_url=body.base_url,
            api_key=body.api_key,
            request_body=request_body,
            proxy_mode=body.proxy_mode,
            proxy_url=body.proxy_url,
            proxy_username=body.proxy_username,
            proxy_password=body.proxy_password,
            verify_ssl=body.verify_ssl,
        )
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        response_body = redact_sensitive_text(
            response.text,
            body.api_key,
            body.proxy_password,
        )
        if not response.is_success:
            return {
                "available": False,
                "latency_ms": latency_ms,
                "status_code": response.status_code,
                "output": None,
                "response_body": response_body,
                "error": f"HTTP {response.status_code}",
            }
        parsed = parse_model_response(protocol, response)
        return {
            "available": True,
            "latency_ms": latency_ms,
            "status_code": response.status_code,
            "output": parsed["output"],
            "response_body": response_body,
            "error": None,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "available": False,
            "latency_ms": round((time.perf_counter() - started_at) * 1000),
            "status_code": None,
            "output": None,
            "response_body": "",
            "error": redact_sensitive_text(
                f"{type(exc).__name__}: {exc}",
                body.api_key,
                body.proxy_password,
            ),
        }


@router.get("/{provider_id}", response_model=ProviderEnvelope)
def get_provider(
    provider_id: str,
    repository: ModelRepositoryDependency,
) -> ProviderEnvelope:
    return ProviderEnvelope(provider=_get_provider_or_404(provider_id, repository))


@router.put("/{provider_id}", response_model=ProviderEnvelope)
def update_provider(
    provider_id: str,
    body: ModelProviderConfiguration,
    repository: ModelRepositoryDependency,
) -> ProviderEnvelope:
    current = _get_provider_or_404(provider_id, repository)
    protocol_changed = _protocol_value(current.protocol) != _protocol_value(body.protocol)
    if protocol_changed:
        body = body.model_copy(
            update={"models": [], "model_configs": {}, "model_endpoint": None}
        )
    else:
        _require_provider_models(body)
    _validate_provider_default_bodies(body)
    record = ModelProviderRecord(
        id=current.id,
        created_at=current.created_at,
        **body.model_dump(mode="json"),
    )
    try:
        saved = repository.update(record)
    except ModelProviderRepositoryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ProviderEnvelope(provider=saved)


@router.delete("/{provider_id}", response_model=ProviderSummaryEnvelope)
def delete_provider(
    provider_id: str,
    repository: ModelRepositoryDependency,
) -> ProviderSummaryEnvelope:
    provider = _get_provider_or_404(provider_id, repository)
    if not repository.delete(provider_id):
        raise HTTPException(404, f"模型供应商不存在: {provider_id}")
    return ProviderSummaryEnvelope(provider=ModelProviderSummary.from_record(provider))
