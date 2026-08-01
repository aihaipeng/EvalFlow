"""Model provider configuration models and SQLite repository."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from execution.database_schema import model_providers

from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    database_read_connection,
    database_transaction,
    database_initialize_lock_for,
    upgrade_database,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ModelProviderProtocol(str, Enum):
    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"
    OPENAI_RESPONSES = "OPENAI_RESPONSES"
    ANTHROPIC = "ANTHROPIC"
    MANUAL = "MANUAL"


class ModelProviderProxyMode(str, Enum):
    SYSTEM = "SYSTEM"
    DIRECT = "DIRECT"
    CUSTOM = "CUSTOM"


class _ModelProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ModelRuntimeConfiguration(_ModelProviderModel):
    context_window: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    default_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("default_body")
    @classmethod
    def validate_default_body(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("模型默认 Body 必须是合法 JSON 对象") from exc
        return value


class ModelProviderConfiguration(_ModelProviderModel):
    name: str | None = Field(default=None, max_length=120)
    website_url: str | None = Field(default=None, max_length=2048)
    api_key: str = Field(min_length=1, max_length=4096)
    base_url: str = Field(min_length=1, max_length=2048)
    protocol: ModelProviderProtocol
    proxy_mode: ModelProviderProxyMode = ModelProviderProxyMode.SYSTEM
    proxy_url: str | None = Field(default=None, max_length=2048)
    proxy_username: str | None = Field(default=None, max_length=512)
    proxy_password: str | None = Field(default=None, max_length=4096)
    verify_ssl: bool = True
    model_endpoint: str | None = Field(default=None, max_length=2048)
    models: list[str] = Field(max_length=500)
    model_configs: dict[str, ModelRuntimeConfiguration] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("website_url", "model_endpoint", mode="before")
    @classmethod
    def normalize_optional_url(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().rstrip("/")
        if not normalized:
            return None
        return _validate_http_url(normalized, "URL")

    @field_validator("proxy_url", mode="before")
    @classmethod
    def normalize_proxy_url(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().rstrip("/")
        if not normalized:
            return None
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

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("API Key 不能为空")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validate_http_url(value.strip().rstrip("/"), "BASE_URL")

    @field_validator("models", mode="before")
    @classmethod
    def normalize_models(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("模型必须是数组")
        models: list[str] = []
        seen: set[str] = set()
        for raw_model in value:
            if not isinstance(raw_model, str):
                raise ValueError("模型名称必须是字符串")
            model = raw_model.strip()
            if not model:
                raise ValueError("模型名称不能为空")
            if len(model) > 200:
                raise ValueError("模型名称不能超过 200 个字符")
            if model not in seen:
                seen.add(model)
                models.append(model)
        return models

    @model_validator(mode="after")
    def validate_connection_and_model_configs(self) -> "ModelProviderConfiguration":
        if self.protocol == ModelProviderProtocol.MANUAL:
            raise ValueError(
                "模型协议只支持 OPENAI_COMPATIBLE、OPENAI_RESPONSES 或 ANTHROPIC"
            )
        if self.proxy_mode == ModelProviderProxyMode.CUSTOM:
            if not self.proxy_url:
                raise ValueError("自定义代理模式必须填写代理 URL")
            if self.proxy_password and not self.proxy_username:
                raise ValueError("填写代理密码时必须同时填写用户名")
        else:
            self.proxy_url = None
            self.proxy_username = None
            self.proxy_password = None
        unknown_models = sorted(set(self.model_configs) - set(self.models))
        if unknown_models:
            raise ValueError("模型配置引用了未添加模型: " + ", ".join(unknown_models))
        return self


class ModelProviderRecord(ModelProviderConfiguration):
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)


class ModelProviderSummary(_ModelProviderModel):
    id: str
    name: str | None
    website_url: str | None
    base_url: str
    protocol: ModelProviderProtocol
    proxy_mode: ModelProviderProxyMode
    model_endpoint: str | None
    models: list[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: ModelProviderRecord) -> "ModelProviderSummary":
        return cls(
            **record.model_dump(
                mode="json",
                exclude={
                    "api_key",
                    "proxy_url",
                    "proxy_username",
                    "proxy_password",
                    "verify_ssl",
                    "model_configs",
                },
            )
        )


class ModelProviderRepositoryError(RuntimeError):
    pass


def _validate_http_url(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} 必须是有效的 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} 不能包含用户名或密码")
    if parsed.fragment:
        raise ValueError(f"{label} 不能包含 fragment")
    if parsed.query:
        raise ValueError(f"{label} 不能包含 query")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} 端口无效") from exc
    return value


class ModelProviderRepository:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH):
        self.database_path = Path(database_path).resolve()
        self._initialize_lock = database_initialize_lock_for(self.database_path)
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            upgrade_database(self.database_path)
            self._initialized = True

    def create(self, record: ModelProviderRecord) -> ModelProviderRecord:
        values = record.model_dump(mode="json")
        try:
            with self._transaction() as connection:
                connection.execute(insert(model_providers).values(
                    id=values["id"], name=values["name"],
                    website_url=values["website_url"], api_key=values["api_key"],
                    base_url=values["base_url"], protocol=values["protocol"],
                    proxy_mode=values["proxy_mode"], proxy_url=values["proxy_url"],
                    proxy_username=values["proxy_username"],
                    proxy_password=values["proxy_password"],
                    verify_ssl=int(values["verify_ssl"]),
                    model_endpoint=values["model_endpoint"],
                    models_json=json.dumps(values["models"], ensure_ascii=False),
                    model_configs_json=json.dumps(
                        values["model_configs"], ensure_ascii=False
                    ),
                    created_at=values["created_at"], updated_at=values["updated_at"],
                ))
        except IntegrityError as exc:
            raise ModelProviderRepositoryError(f"写入模型供应商失败: {exc}") from exc
        return record

    def get(self, provider_id: str) -> ModelProviderRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                select(model_providers).where(model_providers.c.id == provider_id)
            ).mappings().first()
        return self._from_row(row) if row else None

    def list(self) -> list[ModelProviderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                select(model_providers).order_by(
                    model_providers.c.updated_at.desc(), model_providers.c.id.desc()
                )
            ).mappings().all()
        return [self._from_row(row) for row in rows]

    def update(self, record: ModelProviderRecord) -> ModelProviderRecord:
        values = record.model_dump(mode="json")
        with self._transaction() as connection:
            cursor = connection.execute(
                update(model_providers)
                .where(model_providers.c.id == values["id"])
                .values(
                    name=values["name"], website_url=values["website_url"],
                    api_key=values["api_key"], base_url=values["base_url"],
                    protocol=values["protocol"], proxy_mode=values["proxy_mode"],
                    proxy_url=values["proxy_url"],
                    model_endpoint=values["model_endpoint"],
                    proxy_username=values["proxy_username"],
                    proxy_password=values["proxy_password"],
                    verify_ssl=int(values["verify_ssl"]),
                    models_json=json.dumps(values["models"], ensure_ascii=False),
                    model_configs_json=json.dumps(
                        values["model_configs"], ensure_ascii=False
                    ),
                    updated_at=values["updated_at"],
                )
            )
        if cursor.rowcount == 0:
            raise ModelProviderRepositoryError(f"模型供应商不存在: {record.id}")
        return record

    def delete(self, provider_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                delete(model_providers).where(model_providers.c.id == provider_id)
            )
        return cursor.rowcount > 0

    @contextmanager
    def _connect(self, *, initialize: bool = True):
        if initialize:
            self.initialize()
        with database_read_connection(self.database_path, initialize=False) as connection:
            yield connection

    @contextmanager
    def _transaction(self):
        self.initialize()
        with database_transaction(self.database_path, initialize=False) as connection:
            yield connection

    @staticmethod
    def _from_row(row: Any) -> ModelProviderRecord:
        try:
            models = json.loads(row["models_json"])
            model_configs = json.loads(row["model_configs_json"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise ModelProviderRepositoryError(
                f"模型供应商 JSON 数据损坏: {row['id']}"
            ) from exc
        return ModelProviderRecord(
            id=row["id"], name=row["name"], website_url=row["website_url"],
            api_key=row["api_key"], base_url=row["base_url"],
            protocol=row["protocol"], proxy_mode=row["proxy_mode"],
            proxy_url=row["proxy_url"], proxy_username=row["proxy_username"],
            proxy_password=row["proxy_password"],
            verify_ssl=bool(row["verify_ssl"]),
            model_endpoint=row["model_endpoint"],
            models=models, created_at=row["created_at"],
            model_configs=model_configs,
            updated_at=row["updated_at"],
        )
