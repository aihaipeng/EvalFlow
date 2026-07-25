"""Domain models and pure validation for the Workflow specification.

This module intentionally has no database, network, worker, or FastAPI
dependency. It is the input boundary shared by persistence and the executor.
"""

from __future__ import annotations

import json
import math
import re
from enum import Enum
from typing import Any, Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONTEXT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
CONTEXT_REFERENCE_PATTERN = re.compile(r"(?<!\\)\{\{\s*(?:ctx|context)\.([A-Za-z_][A-Za-z0-9_]*)")
SCRIPT_GET_VAL_PATTERN = re.compile(r"\bget_val\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\)")
OUTPUT_TYPES = frozenset({"string", "number", "integer", "boolean", "object", "array", "null"})
LLM_RESERVED_PARAMETER_KEYS = frozenset({"model", "messages", "input", "prompt", "system", "stream"})
ERROR_CODES = frozenset(
    {
        "WORKFLOW_CONFIG_INVALID",
        "WORKFLOW_GRAPH_INVALID",
        "WORKFLOW_CANCELLED",
        "WORKFLOW_PROCESS_RESTARTED",
        "CONTEXT_VARIABLE_NOT_FOUND",
        "CONTEXT_KEY_EXISTS",
        "NODE_CANCELLED_BY_USER",
        "NODE_CANCELLED_BY_FAIL_FAST",
        "START_INPUT_INVALID",
        "START_EXECUTION_ERROR",
        "SCRIPT_RUNTIME_ERROR",
        "SCRIPT_TIMEOUT",
        "SCRIPT_OUTPUT_UNDECLARED",
        "SCRIPT_OUTPUT_TYPE_MISMATCH",
        "SCRIPT_OUTPUT_SERIALIZATION_ERROR",
        "SCRIPT_OUTPUT_DUPLICATE",
        "SCRIPT_OUTPUT_MISSING",
        "SCRIPT_EXECUTION_ERROR",
        "LLM_MODEL_NOT_FOUND",
        "LLM_TIMEOUT",
        "LLM_REQUEST_ERROR",
        "LLM_RESPONSE_ERROR",
        "LLM_PROMPT_EMPTY",
        "LLM_STREAM_INCOMPLETE",
        "LLM_UNSUPPORTED_RESPONSE",
        "LLM_OUTPUT_TRUNCATED",
        "LLM_CONTENT_FILTERED",
        "LLM_UNSUPPORTED_FINISH_REASON",
        "LLM_USAGE_VALUE_INVALID",
        "LLM_EXECUTION_ERROR",
        "HTTP_CONNECTION_ERROR",
        "HTTP_TIMEOUT",
        "HTTP_STATUS_ERROR",
        "HTTP_URL_INVALID_HOST",
        "HTTP_HEADER_DUPLICATE",
        "HTTP_TOO_MANY_REDIRECTS",
        "HTTP_REDIRECT_DOWNGRADE_BLOCKED",
        "HTTP_REDIRECT_INVALID_LOCATION",
        "HTTP_RESPONSE_TOO_LARGE",
        "HTTP_RESPONSE_CONTENT_ENCODING_ERROR",
        "HTTP_RESPONSE_JSON_INVALID",
        "HTTP_RESPONSE_DECODE_ERROR",
        "HTTP_OUTPUT_PATH_NOT_FOUND",
        "HTTP_OUTPUT_TYPE_MISMATCH",
        "HTTP_EXECUTION_ERROR",
    }
)


class WorkflowContractError(ValueError):
    """Raised when a value cannot satisfy the Workflow contract."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, use_enum_values=True)


def validate_uuid4(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise WorkflowContractError(f"{field_name} must be a UUIDv4 string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise WorkflowContractError(f"{field_name} must be a UUIDv4 string") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise WorkflowContractError(f"{field_name} must be a canonical UUIDv4 string")
    return str(parsed)


def normalize_context_name(value: str) -> str:
    if not isinstance(value, str) or not CONTEXT_NAME_PATTERN.fullmatch(value):
        raise WorkflowContractError("Context variable name is invalid")
    return value.lower()


def ensure_strict_json(value: Any) -> Any:
    """Return a deep JSON copy while rejecting non-finite or non-JSON values."""

    def reject_invalid(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise WorkflowContractError("JSON values cannot contain NaN or Infinity")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise WorkflowContractError("JSON object keys must be strings")
            for nested in item.values():
                reject_invalid(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                reject_invalid(nested)
        elif item is None or isinstance(item, (str, int, float, bool)):
            return
        else:
            raise WorkflowContractError("Value is not JSON serializable")

    reject_invalid(value)
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise WorkflowContractError("Value is not strict JSON") from exc


def value_matches_type(value: Any, declared_type: str) -> bool:
    if declared_type not in OUTPUT_TYPES:
        raise WorkflowContractError(f"Unsupported output type: {declared_type}")
    if declared_type == "null":
        return value is None
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "object":
        return isinstance(value, dict)
    return isinstance(value, list)


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class NodeType(str, Enum):
    START = "START"
    SCRIPT = "SCRIPT"
    LLM = "LLM"
    HTTP = "HTTP"
    END = "END"


class ExecutionConfiguration(_ContractModel):
    timeout_ms: int = Field(gt=0)
    max_attempts: int = Field(ge=0, le=10)
    delay_ms: int = Field(ge=0, le=600000)


class ContextDeclaration(_ContractModel):
    name: str
    type: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_context_name(value)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in OUTPUT_TYPES:
            raise ValueError("Unsupported Context value type")
        return value


class StartInput(ContextDeclaration):
    data: Any

    @model_validator(mode="after")
    def validate_data(self):
        value = ensure_strict_json(self.data)
        if not value_matches_type(value, self.type):
            raise ValueError("START data does not match its declared type")
        self.data = value
        return self


class ScriptOutput(ContextDeclaration):
    pass


class HttpOutput(ContextDeclaration):
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("$.request") and not value.startswith("$.response"):
            raise ValueError("HTTP output path must begin with $.request or $.response")
        return value


class BaseNode(_ContractModel):
    id: str
    name: str = Field(min_length=1)
    description: str = ""

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="node.id")

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class StartNode(BaseNode):
    type: Literal[NodeType.START] = NodeType.START
    inputs: list[StartInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_inputs(self):
        _ensure_unique_names(self.inputs, "START inputs")
        return self


class ScriptNode(BaseNode):
    type: Literal[NodeType.SCRIPT] = NodeType.SCRIPT
    script: str
    execution: ExecutionConfiguration
    outputs: list[ScriptOutput] = Field(default_factory=list)

    @field_validator("script")
    @classmethod
    def validate_script(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SCRIPT script cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_unique_outputs(self):
        _ensure_unique_names(self.outputs, "SCRIPT outputs")
        return self


class LlmModelReference(_ContractModel):
    provider_id: str = Field(min_length=1)
    model_name: str = Field(min_length=1)


class LlmPrompt(_ContractModel):
    system: str = ""
    user: str = Field(min_length=1)


class LlmGeneration(_ContractModel):
    stream: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        copied = ensure_strict_json(value)
        reserved = set(copied) & LLM_RESERVED_PARAMETER_KEYS
        if reserved:
            raise ValueError(f"LLM parameters contain reserved keys: {sorted(reserved)}")
        return copied


class LlmNode(BaseNode):
    type: Literal[NodeType.LLM] = NodeType.LLM
    model: LlmModelReference
    prompt: LlmPrompt
    generation: LlmGeneration
    execution: ExecutionConfiguration
    outputs: list[ScriptOutput] = Field(default_factory=list, max_length=1)

    @model_validator(mode="after")
    def validate_outputs(self):
        _ensure_unique_names(self.outputs, "LLM outputs")
        if self.outputs and self.outputs[0].type != "string":
            raise ValueError("LLM output type must be string")
        return self


class HttpHeader(_ContractModel):
    key: str = Field(min_length=1)
    value: str

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not HEADER_NAME_PATTERN.fullmatch(value):
            raise ValueError("HTTP header name is invalid")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("HTTP header value contains a control character")
        return value


class HttpParam(_ContractModel):
    key: str = Field(min_length=1)
    value: Any

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: Any) -> Any:
        copied = ensure_strict_json(value)
        if isinstance(copied, (dict, list)):
            raise ValueError("HTTP parameter value must be a scalar")
        return copied


class HttpBody(_ContractModel):
    type: Literal["none", "raw", "form_data", "form_urlencoded"] = "none"
    content: Any = None

    @model_validator(mode="after")
    def validate_content(self):
        content = ensure_strict_json(self.content)
        if self.type == "none" and content is not None:
            raise ValueError("HTTP none body requires null content")
        self.content = content
        return self


class HttpRequest(_ContractModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    url: str = Field(min_length=1)
    follow_redirects: bool = True
    headers: list[HttpHeader] = Field(default_factory=list)
    params: list[HttpParam] = Field(default_factory=list)
    body: HttpBody

    @model_validator(mode="after")
    def validate_request(self):
        if not (self.url.startswith("http://") or self.url.startswith("https://")):
            raise ValueError("HTTP URL must use http or https")
        if self.method in {"GET", "HEAD"} and self.body.type != "none":
            raise ValueError("GET and HEAD require a none body")
        names = [header.key.lower() for header in self.headers]
        if len(names) != len(set(names)):
            raise ValueError("HTTP header names must be unique ignoring case")
        return self


class ProxyConfiguration(_ContractModel):
    mode: Literal["SYSTEM", "DIRECT", "CUSTOM"] = "SYSTEM"
    url: str | None = None
    username: str | None = None
    password: str | None = None

    @model_validator(mode="after")
    def validate_proxy(self):
        if self.mode == "CUSTOM":
            if not self.url or not self.url.startswith(("http://", "https://")):
                raise ValueError("CUSTOM proxy requires an HTTP or HTTPS URL")
        elif any(value is not None for value in (self.url, self.username, self.password)):
            raise ValueError("SYSTEM and DIRECT proxy fields must be null")
        return self


class HttpNetwork(_ContractModel):
    proxy: ProxyConfiguration
    verify_ssl: bool = True


class HttpResponseConfiguration(_ContractModel):
    body_type: Literal["json", "text", "binary"] = "json"


class HttpNode(BaseNode):
    type: Literal[NodeType.HTTP] = NodeType.HTTP
    request: HttpRequest
    network: HttpNetwork
    response: HttpResponseConfiguration
    execution: ExecutionConfiguration
    outputs: list[HttpOutput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outputs(self):
        _ensure_unique_names(self.outputs, "HTTP outputs")
        return self


class EndNode(BaseNode):
    type: Literal[NodeType.END] = NodeType.END


NodeDefinition = Annotated[
    Union[StartNode, ScriptNode, LlmNode, HttpNode, EndNode],
    Field(discriminator="type"),
]


class WorkflowEdge(_ContractModel):
    edge_id: str
    source: str
    target: str

    @field_validator("edge_id")
    @classmethod
    def validate_edge_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="edge.edge_id")

    @field_validator("source", "target")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="edge.node_id")


class WorkflowDefinition(_ContractModel):
    workflow_id: str
    name: str = Field(min_length=1)
    description: str = ""
    nodes: list[NodeDefinition] = Field(min_length=1)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow_id(cls, value: str) -> str:
        return validate_uuid4(value, field_name="workflow.workflow_id")

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_graph_and_context(self):
        if not self.name:
            raise ValueError("Workflow name cannot be empty")
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Workflow node ids must be unique")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Workflow edge ids must be unique")
        node_id_set = set(node_ids)
        pairs: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.source not in node_id_set or edge.target not in node_id_set:
                raise ValueError("Workflow edge references an unknown node")
            if edge.source == edge.target:
                raise ValueError("Workflow cannot contain self edges")
            pair = (edge.source, edge.target)
            if pair in pairs:
                raise ValueError("Workflow cannot contain duplicate directed edges")
            pairs.add(pair)
        if not any(node.type in {NodeType.SCRIPT, NodeType.LLM, NodeType.HTTP} for node in self.nodes):
            raise ValueError("Workflow requires at least one business node")
        starts = [node for node in self.nodes if node.type == NodeType.START]
        ends = [node for node in self.nodes if node.type == NodeType.END]
        if len(starts) > 1 or len(ends) > 1:
            raise ValueError("Workflow supports at most one START and one END")
        _validate_graph_rules(self.nodes, self.edges, starts, ends)
        _validate_global_context_names(self.nodes)
        _validate_context_references(self.nodes, self.edges)
        return self


def _ensure_unique_names(values: list[ContextDeclaration], label: str) -> None:
    names = [value.name for value in values]
    if len(names) != len(set(names)):
        raise ValueError(f"{label} contains duplicate names")


def _validate_global_context_names(nodes: list[NodeDefinition]) -> None:
    names: list[str] = []
    for node in nodes:
        if isinstance(node, StartNode):
            names.extend(item.name for item in node.inputs)
        elif isinstance(node, (ScriptNode, LlmNode, HttpNode)):
            names.extend(item.name for item in node.outputs)
    if len(names) != len(set(names)):
        raise ValueError("Workflow Context output names must be globally unique")


def _validate_context_references(nodes: list[NodeDefinition], edges: list[WorkflowEdge]) -> None:
    """Reject references that cannot be supplied by a graph ancestor."""

    incoming = {node.id: set() for node in nodes}
    for edge in edges:
        incoming[edge.target].add(edge.source)

    ancestors: dict[str, set[str]] = {}
    for node in nodes:
        reachable: set[str] = set()
        pending = list(incoming[node.id])
        while pending:
            source = pending.pop()
            if source in reachable:
                continue
            reachable.add(source)
            pending.extend(incoming[source])
        ancestors[node.id] = reachable

    producers: dict[str, str] = {}
    for node in nodes:
        declarations = node.inputs if isinstance(node, StartNode) else node.outputs if isinstance(node, (ScriptNode, LlmNode, HttpNode)) else []
        for declaration in declarations:
            producers[declaration.name] = node.id

    for node in nodes:
        for name in _node_context_references(node):
            producer = producers.get(name)
            if producer is None:
                raise ValueError(f"Context reference does not exist: {name}")
            if producer not in ancestors[node.id]:
                raise ValueError(f"Context reference is not provided by an upstream node: {name}")


def _node_context_references(node: NodeDefinition) -> set[str]:
    if isinstance(node, ScriptNode):
        return {value.lower() for value in SCRIPT_GET_VAL_PATTERN.findall(node.script)}
    if isinstance(node, LlmNode):
        return _template_references(node.prompt.system) | _template_references(node.prompt.user)
    if isinstance(node, HttpNode):
        values: list[Any] = [node.request.url, node.request.body.content]
        values.extend(item.value for item in node.request.headers)
        values.extend(item.value for item in node.request.params)
        return _tree_template_references(values)
    return set()


def _tree_template_references(value: Any) -> set[str]:
    if isinstance(value, str):
        return _template_references(value)
    if isinstance(value, list):
        return set().union(*(_tree_template_references(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(_tree_template_references(item) for item in value.values())) if value else set()
    return set()


def _template_references(value: str) -> set[str]:
    return {match.lower() for match in CONTEXT_REFERENCE_PATTERN.findall(value)}


def _validate_graph_rules(
    nodes: list[NodeDefinition],
    edges: list[WorkflowEdge],
    starts: list[NodeDefinition],
    ends: list[NodeDefinition],
) -> None:
    node_ids = {node.id for node in nodes}
    outgoing = {node_id: set() for node_id in node_ids}
    incoming = {node_id: set() for node_id in node_ids}
    for edge in edges:
        outgoing[edge.source].add(edge.target)
        incoming[edge.target].add(edge.source)
    start = starts[0] if starts else None
    end = ends[0] if ends else None
    if start and incoming[start.id]:
        raise ValueError("START cannot have incoming edges")
    if end and outgoing[end.id]:
        raise ValueError("END cannot have outgoing edges")
    if len(nodes) > 1:
        isolated = [node_id for node_id in node_ids if not outgoing[node_id] and not incoming[node_id]]
        if isolated:
            raise ValueError("Workflow cannot contain isolated nodes")
    if end:
        reachable_to_end = {end.id}
        pending = [end.id]
        while pending:
            target = pending.pop()
            for source in incoming[target]:
                if source not in reachable_to_end:
                    reachable_to_end.add(source)
                    pending.append(source)
        business_ids = {node.id for node in nodes if node.type in {NodeType.SCRIPT, NodeType.LLM, NodeType.HTTP}}
        if not business_ids <= reachable_to_end:
            raise ValueError("Every business node must reach END")
    indegree = {node_id: len(incoming[node_id]) for node_id in node_ids}
    pending = [node_id for node_id, count in indegree.items() if count == 0]
    visited = 0
    while pending:
        source = pending.pop()
        visited += 1
        for target in outgoing[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    if visited != len(nodes):
        raise ValueError("Workflow cannot contain a cycle")
