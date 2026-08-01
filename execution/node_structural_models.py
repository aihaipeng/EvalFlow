"""Node Structural Model contracts and standalone SQLite repository."""

from __future__ import annotations

import json
import math
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from execution.database_schema import node_structural_models as node_models_table
from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    database_read_connection,
    database_transaction,
    database_initialize_lock_for,
    upgrade_database,
)
from execution.node_codec import dump_node_definition
from execution.time_utils import utc_now_iso


NODE_TYPES = ("START", "SCRIPT", "LLM", "HTTP", "END")
OUTPUT_TYPES = ("string", "number", "integer", "boolean", "object", "array", "null")
NODE_STRUCTURAL_TABLE_DESCRIPTION = (
    "Node Structural Model 的权威关系表。每行保存一个可独立创建、编辑和删除的当前节点定义；"
    "节点不直接归属 Workflow，因此不保存 workflow_id，也不保存任何执行状态、Context、输出、错误或日志。"
)
NODE_STRUCTURAL_COLUMN_DESCRIPTIONS = {
    "id": (
        "TEXT 主键。节点全局唯一的规范小写 UUIDv4；创建后不可修改，未来由 Workflow 关联表引用。"
    ),
    "type": (
        "TEXT 类型判别字段。只允许 START、SCRIPT、LLM、HTTP、END；创建后不可修改，并决定 "
        "definition_json 必须使用哪一种 Pydantic 结构校验。"
    ),
    "name": (
        "TEXT 用户可见名称，长度 1..200；数据库拒绝仅含空白的值，用于画布节点标题和管理界面检索。"
    ),
    "description": (
        "TEXT 用户可见用途说明，最大 4000 字符；无说明时保存空字符串，不保存 null。"
    ),
    "definition_json": (
        "TEXT 格式的严格 JSON object。仅保存节点类型专属配置，不重复 id、type、name、description；"
        "写入前必须通过对应 Pydantic 判别联合模型校验，禁止额外字段、NaN 和 Infinity。"
    ),
    "created_at": (
        "TEXT。节点首次成功创建时的 UTC ISO-8601 毫秒时间；后续更新保持不变。"
    ),
    "updated_at": (
        "TEXT。节点最近一次成功创建或更新时的 UTC ISO-8601 毫秒时间；列表按该字段倒序读取。"
    ),
}
LEGACY_WORKFLOW_TABLES = (
    "workflow_node_runs",
    "workflow_node_runs_v2",
    "node_runs",
    "artifacts",
    "attempts",
    "step_runs",
    "case_runs",
    "workflow_runs",
    "workflow_runs_v2",
    "runs",
    "testset_workflow_bindings",
    "testset_execution_configs",
    "workflow_drafts",
    "workflow_definitions_v2",
    "workflows",
    "schema_migrations",
)

_CONTEXT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PYTHON_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)
_STATUS_RANGE = re.compile(r"^[1-5][0-9]{2}-[1-5][0-9]{2}$")
_RESERVED_REQUEST_HEADERS = {"content-length", "transfer-encoding", "content-encoding"}


def _validate_uuid4(value: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("节点 id 必须是 UUIDv4 字符串") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError("节点 id 必须是规范 UUIDv4 字符串")
    return value.lower()


def _validate_json_value(value: Any, *, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} 不能包含 NaN 或 Infinity")
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return value
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} 的对象 key 必须是字符串")
            _validate_json_value(item, path=f"{path}.{key}")
        return value
    raise ValueError(f"{path} 必须是严格 JSON 值")


def _value_matches_type(value: Any, value_type: str) -> bool:
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "object":
        return isinstance(value, dict)
    if value_type == "array":
        return isinstance(value, list)
    return value is None


def _validate_unique_names(items: list[Any], *, label: str) -> list[Any]:
    names = [item.name for item in items]
    if len(names) != len(set(names)):
        raise ValueError(f"{label} 变量名在节点内必须唯一")
    return items


class _NodeModel(BaseModel):
    """所有节点结构类的严格 Pydantic 基类，统一拒绝契约外字段。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class NodeCommon(_NodeModel):
    """所有节点结构模型共有的身份字段和用户可见展示字段。"""

    id: str = Field(description="节点全局唯一的规范 UUIDv4。")
    type: str = Field(description="节点类型判别字段。")
    name: str = Field(min_length=1, max_length=200, description="用户可见节点名称。")
    description: str = Field(
        default="", max_length=4000, description="节点用途说明，允许为空。"
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_uuid4(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("节点名称不能为空")
        return value


class JsonVariableInput(_NodeModel):
    """START 的一项初始变量声明，执行成功时按原名称和值提交到 Context。"""

    name: str = Field(description="写入 Context 的大小写敏感变量名。")
    type: Literal["string", "number", "integer", "boolean", "object", "array", "null"] = Field(
        description="用户声明的严格 JSON 类型。"
    )
    value: Any = Field(description="与 type 精确匹配的严格 JSON 值。")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _CONTEXT_NAME.fullmatch(value):
            raise ValueError("输入变量名格式无效")
        return value

    @model_validator(mode="after")
    def validate_value(self) -> "JsonVariableInput":
        _validate_json_value(self.value)
        if not _value_matches_type(self.value, self.type):
            raise ValueError("输入变量 value 与 type 不匹配")
        return self


class NodeOutput(_NodeModel):
    """业务节点的一项输出绑定，声明 Context 变量名、目标类型和取值来源。"""

    name: str = Field(description="成功后写入 Context 的大小写敏感变量名。")
    type: Literal["string", "number", "integer", "boolean", "object", "array", "null"] = Field(
        description="输出值的目标 JSON 类型。"
    )
    source: str = Field(
        min_length=1,
        max_length=4000,
        description="从节点实际结果读取值的类型专属表达式。",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _CONTEXT_NAME.fullmatch(value):
            raise ValueError("输出变量名格式无效")
        return value


class RetryExecution(_NodeModel):
    """SCRIPT、LLM 和 HTTP 共用的首次延迟、单次超时与自动重试声明。"""

    timeout_seconds: float = Field(
        default=600,
        strict=True,
        ge=0.001,
        description="单次实际尝试的总超时，单位秒；默认 600，允许小数秒。",
    )
    max_attempts: int = Field(
        default=0,
        strict=True,
        ge=0,
        le=10,
        description="最大重试次数，默认 0，不包含首次尝试。",
    )
    retry_interval_seconds: float = Field(
        default=0,
        strict=True,
        ge=0,
        le=600,
        description="两次尝试之间的等待时间，单位秒；默认 0，允许小数秒。",
    )
    delay_seconds: float = Field(
        default=0,
        strict=True,
        ge=0,
        le=600,
        description="首次实际尝试前只执行一次的等待时间，单位秒；默认 0，允许小数秒。",
    )

    @field_validator("timeout_seconds", "retry_interval_seconds", "delay_seconds")
    @classmethod
    def validate_finite_seconds(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("执行时间必须是有限秒数")
        return value


class StartNodeStructuralModel(NodeCommon):
    """START 节点结构模型，只声明工作流开始时写入 Context 的初始变量。"""

    type: Literal["START"] = Field(default="START", description="固定节点类型 START。")
    inputs: list[JsonVariableInput] = Field(
        default_factory=list, description="按声明顺序原子提交到 Context 的输入数组。"
    )

    @field_validator("inputs")
    @classmethod
    def validate_inputs(cls, value: list[JsonVariableInput]) -> list[JsonVariableInput]:
        return _validate_unique_names(value, label="START inputs")


class ScriptNodeStructuralModel(NodeCommon):
    """SCRIPT 节点结构模型，保存完整 Python 源码、执行约束和顶层变量输出绑定。"""

    type: Literal["SCRIPT"] = Field(default="SCRIPT", description="固定节点类型 SCRIPT。")
    script: str = Field(
        default="",
        description="用户编写的完整 Python 源码文本；允许空值保存。",
    )
    execution: RetryExecution = Field(
        default_factory=RetryExecution,
        description="脚本超时与重试配置；省略时使用平台默认执行策略。",
    )
    outputs: list[NodeOutput] = Field(
        default_factory=list, description="从顶层 Python 变量读取的输出绑定。"
    )

    @field_validator("outputs")
    @classmethod
    def validate_outputs(cls, value: list[NodeOutput]) -> list[NodeOutput]:
        _validate_unique_names(value, label="SCRIPT outputs")
        for output in value:
            if not _PYTHON_NAME.fullmatch(output.source):
                raise ValueError("SCRIPT outputs.source 必须是顶层 Python 变量名")
        return value


class ModelReference(_NodeModel):
    """LLM 节点对模型管理中一个供应商及其模型的稳定引用。"""

    provider_id: str = Field(
        default="", max_length=200, description="模型供应商配置 ID；允许空值保存。"
    )
    model_name: str = Field(
        default="", max_length=200, description="供应商下已添加的模型名称；允许空值保存。"
    )


class LlmContextMessage(_NodeModel):
    """LLM 上下文中的一条有序消息模板。"""

    role: Literal["SYSTEM", "USER", "ASSISTANT"] = Field(
        description="消息角色；结构定义使用固定的大写枚举。"
    )
    content: str = Field(
        default="", description="支持 Context 变量引用的消息模板；允许空值保存。"
    )


class LlmContextDefinition(_NodeModel):
    """LLM 阻塞调用使用的有序上下文消息序列。"""

    messages: list[LlmContextMessage] = Field(
        default_factory=lambda: [
            LlmContextMessage(role="SYSTEM"),
            LlmContextMessage(role="USER"),
        ],
        min_length=2,
        description=(
            "固定以 SYSTEM、USER 开始并按 ASSISTANT、USER 交替追加的消息模板；"
            "允许空内容和暂时停在 ASSISTANT 的草稿。"
        ),
    )

    @field_validator("messages")
    @classmethod
    def validate_messages(
        cls, value: list[LlmContextMessage]
    ) -> list[LlmContextMessage]:
        expected_roles = ["SYSTEM", "USER"]
        expected_roles.extend(
            "ASSISTANT" if index % 2 == 0 else "USER"
            for index in range(2, len(value))
        )
        actual_roles = [message.role for message in value]
        if actual_roles != expected_roles:
            raise ValueError(
                "LLM context.messages 必须遵循 SYSTEM -> USER -> "
                "(ASSISTANT -> USER)... 的固定顺序"
            )
        return value


class GenerationDefinition(_NodeModel):
    """LLM 节点覆盖模型默认 Body 的供应商原生高级参数。"""

    parameters: dict[str, Any] = Field(
        default_factory=dict, description="用户覆盖的供应商原生高级参数 JSON 对象。"
    )
    parameters_text: str = Field(
        default="",
        max_length=20000,
        description="高级参数编辑器的草稿文本；允许暂存非 JSON 内容，执行前再校验。",
    )

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_value(value, path="generation.parameters")
        return value


class LlmNodeStructuralModel(NodeCommon):
    """LLM 节点结构模型，保存模型引用、上下文、生成参数、执行约束和输出绑定。"""

    type: Literal["LLM"] = Field(default="LLM", description="固定节点类型 LLM。")
    model: ModelReference = Field(
        default_factory=ModelReference,
        description="模型管理中的供应商和模型引用；允许空值保存。",
    )
    context: LlmContextDefinition = Field(
        default_factory=LlmContextDefinition,
        description="有序上下文消息模板；消息内容允许空值保存。",
    )
    generation: GenerationDefinition = Field(
        default_factory=GenerationDefinition, description="节点级高级模型参数。"
    )
    execution: RetryExecution = Field(
        default_factory=RetryExecution,
        description="模型调用超时与重试配置；省略时使用平台默认执行策略。",
    )
    outputs: list[NodeOutput] = Field(
        default_factory=list,
        description="从协议解析结果 result 或供应商原始 response 提取的输出绑定。",
    )

    @field_validator("outputs")
    @classmethod
    def validate_outputs(cls, value: list[NodeOutput]) -> list[NodeOutput]:
        return _validate_unique_names(value, label="LLM outputs")


class HttpHeader(_NodeModel):
    """HTTP 请求的一项用户 Header；Header 值可在执行时引用 Context。"""

    key: str = Field(description="不含 Context 引用的 HTTP Header 名。")
    value: str = Field(description="支持 Context 引用的 HTTP Header 值模板。")

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not _HEADER_NAME.fullmatch(value):
            raise ValueError("HTTP Header 名无效")
        if value.lower() in _RESERVED_REQUEST_HEADERS:
            raise ValueError(f"HTTP Header 由平台管理，不能手动配置: {value}")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("HTTP Header 值包含非法控制字符")
        return value


class HttpParameter(_NodeModel):
    """HTTP 请求的一项有序 Query 参数；同名参数可按数组顺序重复出现。"""

    key: str = Field(min_length=1, description="Query 参数名。")
    value: str | int | float | bool | None = Field(
        description="支持 Context 引用的 JSON 标量参数值。"
    )

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: Any) -> Any:
        _validate_json_value(value, path="HTTP Query value")
        return value


class HttpFormField(_NodeModel):
    """HTTP form_data 或 form_urlencoded Body 中的一项有序字段。"""

    key: str = Field(min_length=1, description="表单字段名。")
    value: Any = Field(description="支持 Context 引用的严格 JSON 字段值。")

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: Any) -> Any:
        return _validate_json_value(value, path="HTTP form value")


class HttpBody(_NodeModel):
    """Context 解析前的 HTTP Body 编码类型和内容模板。"""

    type: Literal["none", "raw", "form_data", "form_urlencoded"] = Field(
        default="none", description="请求 Body 编码方式。"
    )
    content: Any = Field(
        default=None, description="Body 模板；结构由 type 决定并支持 Context 引用。"
    )
    template_text: str | None = Field(
        default=None, description="raw Body 的原始 JSON 模板文本。"
    )

    @model_validator(mode="after")
    def validate_content(self) -> "HttpBody":
        if self.type == "none":
            if self.content is not None or self.template_text is not None:
                raise ValueError("HTTP none Body 的 content 和 template_text 必须是 null")
            return self
        if self.type == "raw" and self.template_text is not None:
            if self.content is not None:
                raise ValueError("HTTP raw Body 不能同时提供 content 和 template_text")
            return self
        if self.template_text is not None:
            raise ValueError("只有 HTTP raw Body 可以提供 template_text")
        _validate_json_value(self.content, path="HTTP body.content")
        if self.type in {"form_data", "form_urlencoded"}:
            self.content = TypeAdapter(list[HttpFormField]).validate_python(self.content)
        return self


class HttpRequest(_NodeModel):
    """HTTP 节点的业务请求声明，包含方法、URL、Header、Query、重定向和 Body。"""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = Field(
        default="POST", description="HTTP 请求方法。"
    )
    url: str = Field(
        default="",
        max_length=8000,
        description="支持 Context 引用的 HTTP/HTTPS URL；允许空值保存。",
    )
    follow_redirects: bool = Field(
        default=True, description="是否由底层 HTTP 客户端跟随重定向。"
    )
    headers: list[HttpHeader] = Field(
        default_factory=list, description="保持用户声明顺序的请求 Header。"
    )
    params: list[HttpParameter] = Field(
        default_factory=list, description="保持用户声明顺序的 Query 参数。"
    )
    body: HttpBody = Field(default_factory=HttpBody, description="请求 Body 定义。")

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        if value == "":
            return value
        if not _HTTP_URL.match(value) or any(character.isspace() for character in value):
            raise ValueError("HTTP URL 必须以 http:// 或 https:// 开头且不能包含空白")
        return value

    @model_validator(mode="after")
    def validate_method_body(self) -> "HttpRequest":
        if self.method in {"GET", "HEAD"} and self.body.type != "none":
            raise ValueError("GET/HEAD 请求不允许配置 Body")
        return self


class HttpProxy(_NodeModel):
    """HTTP 节点显式选择的 SYSTEM、DIRECT 或 CUSTOM 代理路由及可选认证信息。"""

    mode: Literal["SYSTEM", "DIRECT", "CUSTOM"] = Field(
        default="SYSTEM", description="请求使用的 Proxy 路由模式。"
    )
    url: str | None = Field(default=None, description="CUSTOM 模式的 HTTP/HTTPS Proxy URL。")
    username: str | None = Field(default=None, description="CUSTOM Proxy 用户名。")
    password: str | None = Field(default=None, description="CUSTOM Proxy 密码。")

    @model_validator(mode="after")
    def validate_mode(self) -> "HttpProxy":
        if self.mode == "CUSTOM":
            if not self.url:
                return self
            parsed = urlsplit(self.url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise ValueError("CUSTOM Proxy URL 必须是有效 HTTP/HTTPS 地址")
        elif any(value is not None for value in (self.url, self.username, self.password)):
            raise ValueError("SYSTEM/DIRECT Proxy 不能设置 url 或凭据")
        return self


class HttpNetwork(_NodeModel):
    """HTTP 请求的网络策略，独立组合代理路由和 TLS 证书验证。"""

    proxy: HttpProxy = Field(default_factory=HttpProxy, description="Proxy 路由与凭据。")
    verify_ssl: bool = Field(default=True, description="是否验证目标及 HTTPS Proxy 证书。")


class HttpResponseDefinition(_NodeModel):
    """HTTP 最终响应的 Body 表示方式和业务成功状态码声明。"""

    mode: Literal["AUTO", "JSON", "TEXT", "BINARY"] = Field(
        default="AUTO", description="最终响应 Body 的表示方式。"
    )
    success_statuses: list[int | str] = Field(
        default_factory=lambda: ["200-299"],
        description="视为成功的状态码或闭区间数组。",
    )

    @field_validator("success_statuses", mode="before")
    @classmethod
    def validate_statuses(cls, value: Any) -> Any:
        if not isinstance(value, list) or not value:
            raise ValueError("success_statuses 必须是非空数组")
        for item in value:
            if isinstance(item, bool):
                raise ValueError("success_statuses 不接受 boolean")
            if isinstance(item, int) and 100 <= item <= 599:
                continue
            if isinstance(item, str) and _STATUS_RANGE.fullmatch(item):
                start, end = (int(part) for part in item.split("-"))
                if start <= end:
                    continue
            raise ValueError(f"success_statuses 项无效: {item}")
        return value


class HttpExecution(RetryExecution):
    """HTTP 执行约束，在公共超时重试字段上增加方法和状态码重试策略。"""

    retry_non_idempotent: bool = Field(
        default=False, description="是否允许 POST/PATCH 自动重试。"
    )
    retry_statuses: list[int] = Field(
        default_factory=lambda: [408, 429, 500, 502, 503, 504],
        description="允许触发自动重试的 HTTP 失败状态码。",
    )

    @field_validator("retry_statuses")
    @classmethod
    def validate_retry_statuses(cls, value: list[int]) -> list[int]:
        if any(isinstance(item, bool) or not 100 <= item <= 599 for item in value):
            raise ValueError("retry_statuses 只接受 100..599 integer")
        if len(value) != len(set(value)):
            raise ValueError("retry_statuses 不能重复")
        return value


class HttpNodeStructuralModel(NodeCommon):
    """HTTP 节点结构模型，面向内网 API 请求并保存请求、网络、响应、重试和输出配置。"""

    type: Literal["HTTP"] = Field(default="HTTP", description="固定节点类型 HTTP。")
    request: HttpRequest = Field(
        default_factory=HttpRequest,
        description="业务 HTTP 请求模板；允许空 URL 保存。",
    )
    network: HttpNetwork = Field(
        default_factory=HttpNetwork,
        description="Proxy 与 SSL 验证配置；CUSTOM 允许暂缺 URL 保存。",
    )
    response: HttpResponseDefinition = Field(
        default_factory=HttpResponseDefinition,
        description="响应解析和成功判定配置。",
    )
    execution: HttpExecution = Field(
        default_factory=HttpExecution,
        description="HTTP 总超时与重试策略；省略时使用平台默认执行策略。",
    )
    outputs: list[NodeOutput] = Field(
        default_factory=list, description="从最终 request/response 提取的输出绑定。"
    )

    @field_validator("outputs")
    @classmethod
    def validate_outputs(cls, value: list[NodeOutput]) -> list[NodeOutput]:
        return _validate_unique_names(value, label="HTTP outputs")


class EndNodeStructuralModel(NodeCommon):
    """END 节点结构模型，只作为 Workflow 的结构终点。"""

    type: Literal["END"] = Field(default="END", description="固定节点类型 END。")

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_outputs(cls, value: Any) -> Any:
        """兼容读取旧 END outputs，并在下一次保存时清除该历史配置。"""

        if isinstance(value, dict) and "outputs" in value:
            value = {key: item for key, item in value.items() if key != "outputs"}
        return value


NodeStructuralModel: TypeAlias = Annotated[
    StartNodeStructuralModel
    | ScriptNodeStructuralModel
    | LlmNodeStructuralModel
    | HttpNodeStructuralModel
    | EndNodeStructuralModel,
    Field(discriminator="type"),
]
NODE_STRUCTURAL_ADAPTER = TypeAdapter(NodeStructuralModel)


class NodeStructuralRecord(_NodeModel):
    """Repository 返回对象，组合完整节点结构模型与数据库管理的创建、更新时间。"""

    node: NodeStructuralModel = Field(description="完整、已验证的节点 Structural Model。")
    created_at: str = Field(description="首次持久化时间，UTC ISO-8601。")
    updated_at: str = Field(description="最近更新时间，UTC ISO-8601。")


class NodeStructuralRepositoryError(RuntimeError):
    """节点结构模型无法持久化、读取或满足 Repository 不变量时抛出的领域错误。"""


class NodeStructuralRepository:
    """独立持久化节点结构模型，并在首次初始化时定点删除旧 Workflow 表。"""

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

    def create(
        self, node: NodeStructuralModel, *, timestamp: str | None = None
    ) -> NodeStructuralRecord:
        validated = NODE_STRUCTURAL_ADAPTER.validate_python(node)
        now = timestamp or utc_now_iso()
        try:
            with self._transaction() as connection:
                connection.execute(insert(node_models_table).values(
                    id=validated.id,
                    type=validated.type,
                    name=validated.name,
                    description=validated.description,
                    definition_json=dump_node_definition(validated),
                    created_at=now,
                    updated_at=now,
                ))
        except IntegrityError as exc:
            raise NodeStructuralRepositoryError(f"写入节点 Structural Model 失败: {exc}") from exc
        return NodeStructuralRecord(node=validated, created_at=now, updated_at=now)

    def get(self, node_id: str) -> NodeStructuralRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                select(node_models_table).where(node_models_table.c.id == node_id)
            ).mappings().first()
        return self._from_row(row) if row else None

    def list(self, *, node_type: str | None = None) -> list[NodeStructuralRecord]:
        with self._connect() as connection:
            statement = select(node_models_table)
            if node_type is not None:
                if node_type not in NODE_TYPES:
                    raise NodeStructuralRepositoryError(f"节点类型无效: {node_type}")
                statement = statement.where(node_models_table.c.type == node_type)
            rows = connection.execute(
                statement.order_by(
                    node_models_table.c.updated_at.desc(), node_models_table.c.id.desc()
                )
            ).mappings().all()
        return [self._from_row(row) for row in rows]

    def update(
        self, node: NodeStructuralModel, *, timestamp: str | None = None
    ) -> NodeStructuralRecord:
        validated = NODE_STRUCTURAL_ADAPTER.validate_python(node)
        now = timestamp or utc_now_iso()
        with self._transaction() as connection:
            current = connection.execute(
                select(node_models_table.c.type, node_models_table.c.created_at).where(
                    node_models_table.c.id == validated.id
                )
            ).mappings().first()
            if current is None:
                raise NodeStructuralRepositoryError(f"节点不存在: {validated.id}")
            if current["type"] != validated.type:
                raise NodeStructuralRepositoryError(
                    f"节点 type 创建后不可修改: {current['type']} -> {validated.type}"
                )
            connection.execute(
                update(node_models_table)
                .where(node_models_table.c.id == validated.id)
                .values(
                    type=validated.type,
                    name=validated.name,
                    description=validated.description,
                    definition_json=dump_node_definition(validated),
                    updated_at=now,
                )
            )
        return NodeStructuralRecord(
            node=validated, created_at=current["created_at"], updated_at=now
        )

    def delete(self, node_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                delete(node_models_table).where(node_models_table.c.id == node_id)
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
    def _from_row(row: Any) -> NodeStructuralRecord:
        try:
            definition = json.loads(row["definition_json"])
            node = NODE_STRUCTURAL_ADAPTER.validate_python(
                {
                    "id": row["id"],
                    "type": row["type"],
                    "name": row["name"],
                    "description": row["description"],
                    **definition,
                }
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise NodeStructuralRepositoryError(
                f"节点 Structural Model 数据损坏: {row['id']}"
            ) from exc
        return NodeStructuralRecord(
            node=node, created_at=row["created_at"], updated_at=row["updated_at"]
        )
