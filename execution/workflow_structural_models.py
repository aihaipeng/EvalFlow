"""Workflow Structural Model contracts, graph validation, and SQLite repository."""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from sqlalchemy import delete, func, insert, literal_column, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from execution.database_schema import (
    node_structural_models as node_models_table,
    workflow_edges,
    workflow_node_bindings,
    workflow_structural_models as workflows_table,
)
from execution.node_structural_models import (
    NODE_STRUCTURAL_ADAPTER,
    NodeStructuralModel,
)
from execution.node_codec import dump_node_definition
from execution.resource_names import next_copy_name
from execution.time_utils import utc_now_iso
from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    database_read_connection,
    database_transaction,
    database_initialize_lock_for,
    upgrade_database,
)
from execution.workflow_values import template_references


WORKFLOW_STRUCTURAL_TABLE_DESCRIPTIONS = {
    "workflow_structural_models": "Workflow Structural Model 的身份、名称、说明和数据库管理时间。",
    "workflow_node_bindings": "Workflow 与独立 Node Structural Model 的一对多归属关系及画布坐标。",
    "workflow_edges": "同一 Workflow 内仅表达调度依赖的有向 Edge。",
}
WORKFLOW_STRUCTURAL_COLUMN_DESCRIPTIONS = {
    "workflow_structural_models": {
        "id": "TEXT 主键。Workflow 全局唯一的规范小写 UUIDv4，创建后不可修改。",
        "name": "TEXT 唯一。用户可见名称，保留首尾空白并按完整原文比较。",
        "description": "TEXT。用户可见用途说明，无说明时保存空字符串。",
        "created_at": "TEXT。Workflow 首次成功创建时的 UTC ISO-8601 毫秒时间。",
        "updated_at": "TEXT。所属 Workflow、Node、binding 或 Edge 最近一次成功保存时间。",
    },
    "workflow_node_bindings": {
        "workflow_id": "TEXT。所属 Workflow ID，与 node_id 共同构成主键。",
        "node_id": "TEXT 且全局唯一。引用独立 Node Structural Model。",
        "position_x": "REAL。Node 在画布中的有限 X 坐标，不参与调度。",
        "position_y": "REAL。Node 在画布中的有限 Y 坐标，不参与调度。",
    },
    "workflow_edges": {
        "id": "TEXT 主键。Edge 全局唯一的规范小写 UUIDv4。",
        "workflow_id": "TEXT。所属 Workflow ID。",
        "source_node_id": "TEXT。同一 Workflow 内的上游 Node ID。",
        "target_node_id": "TEXT。同一 Workflow 内的下游 Node ID。",
    },
}

def _validate_uuid4(value: str, *, label: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} 必须是 UUIDv4 字符串") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError(f"{label} 必须是规范 UUIDv4 字符串")
    return value.lower()


class _WorkflowModel(BaseModel):
    """Workflow 结构类的严格 Pydantic 基类，统一拒绝契约外字段。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class WorkflowNodeBinding(_WorkflowModel):
    """一个 Workflow 对独立 Node Structural Model 的引用和画布坐标。"""

    node_id: str = Field(description="被当前 Workflow 引用的 Node UUIDv4。")
    position_x: float = Field(description="Node 在画布中的有限 X 坐标。")
    position_y: float = Field(description="Node 在画布中的有限 Y 坐标。")

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        return _validate_uuid4(value, label="node_id")

    @field_validator("position_x", "position_y")
    @classmethod
    def validate_position(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("画布坐标必须是有限数")
        return value


class WorkflowEdge(_WorkflowModel):
    """同一 Workflow 内从一个 Node 指向另一个 Node 的调度依赖。"""

    id: str = Field(description="Edge 全局唯一的 UUIDv4。")
    source_node_id: str = Field(description="上游 Node UUIDv4。")
    target_node_id: str = Field(description="下游 Node UUIDv4。")

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_uuid4(value, label="edge id")

    @field_validator("source_node_id", "target_node_id")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return _validate_uuid4(value, label="edge node id")


class WorkflowStructuralModel(_WorkflowModel):
    """Workflow 当前权威结构，只保存身份、展示信息、Node 引用坐标和 Edge。"""

    id: str = Field(description="Workflow 全局唯一的规范 UUIDv4。")
    name: str = Field(min_length=1, max_length=200, description="保留原文的用户可见名称。")
    description: str = Field(default="", max_length=4000, description="Workflow 用途说明。")
    nodes: list[WorkflowNodeBinding] = Field(description="Node 引用和画布坐标数组。")
    edges: list[WorkflowEdge] = Field(description="有向调度依赖数组。")

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_uuid4(value, label="workflow id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Workflow 名称不能为空")
        return value

    @model_validator(mode="after")
    def validate_collection_identity(self) -> "WorkflowStructuralModel":
        node_ids = [binding.node_id for binding in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        edge_pairs = [(edge.source_node_id, edge.target_node_id) for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Workflow nodes 不能重复引用同一 Node")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Workflow Edge id 不能重复")
        if len(edge_pairs) != len(set(edge_pairs)):
            raise ValueError("Workflow 不能包含重复 Edge")
        return self


class WorkflowStructuralRecord(_WorkflowModel):
    """Repository 返回对象，组合可继续编辑的 Workflow 草稿和数据库管理时间。"""

    workflow: WorkflowStructuralModel = Field(description="已持久化的 Workflow Structural Model 草稿。")
    node_models: list[Annotated[NodeStructuralModel, Field(discriminator="type")]] = Field(
        description="Workflow bindings 所引用的完整 Node Structural Model 数组。"
    )
    created_at: str = Field(description="首次持久化时间，UTC ISO-8601。")
    updated_at: str = Field(description="最近结构保存时间，UTC ISO-8601。")


class WorkflowStructuralSummary(_WorkflowModel):
    """Workflow 一级列表使用的最小只读摘要。"""

    id: str = Field(description="Workflow UUIDv4。")
    name: str = Field(description="用户可见名称。")
    description: str = Field(description="用户可见说明。")
    node_count: int = Field(description="当前绑定的节点数量。")
    updated_at: str = Field(description="最近结构保存时间，UTC ISO-8601。")


class WorkflowStructuralRepositoryError(RuntimeError):
    """Workflow 结构无法验证、持久化或满足 Repository 不变量时的领域错误。"""


class WorkflowNameConflictError(WorkflowStructuralRepositoryError):
    """Workflow 名称已被其他结构记录占用。"""


def _raise_workflow_integrity_error(operation: str, exc: IntegrityError) -> None:
    if "workflow_structural_models.name" in str(exc):
        raise WorkflowNameConflictError("Workflow 名称已存在，请使用其他名称") from exc
    raise WorkflowStructuralRepositoryError(
        f"{operation} Workflow Structural Model 失败: {exc}"
    ) from exc


def validate_workflow_graph(
    workflow: WorkflowStructuralModel,
    node_models: list[NodeStructuralModel],
    *,
    validate_context: bool = True,
) -> None:
    """验证完整 DAG、系统节点边界，并按需验证 Workflow Context。"""

    models = [NODE_STRUCTURAL_ADAPTER.validate_python(node) for node in node_models]
    by_id = {node.id: node for node in models}
    binding_ids = [binding.node_id for binding in workflow.nodes]
    if len(models) != len(by_id):
        raise WorkflowStructuralRepositoryError("Node Structural Model id 不能重复")
    if set(binding_ids) != set(by_id):
        raise WorkflowStructuralRepositoryError("Workflow bindings 与 Node Structural Models 必须一一对应")

    starts = [node for node in models if node.type == "START"]
    ends = [node for node in models if node.type == "END"]
    business = [node for node in models if node.type in {"SCRIPT", "LLM", "HTTP"}]
    if len(starts) != 1:
        raise WorkflowStructuralRepositoryError("Workflow 必须恰好包含一个 START")
    if len(ends) != 1:
        raise WorkflowStructuralRepositoryError("Workflow 必须恰好包含一个 END")
    if not business:
        raise WorkflowStructuralRepositoryError("Workflow 至少包含一个 SCRIPT、LLM 或 HTTP 业务节点")

    adjacency = {node_id: set() for node_id in binding_ids}
    reverse = {node_id: set() for node_id in binding_ids}
    for edge in workflow.edges:
        if edge.source_node_id not in adjacency or edge.target_node_id not in adjacency:
            raise WorkflowStructuralRepositoryError("Edge 两端必须属于当前 Workflow")
        if edge.source_node_id == edge.target_node_id:
            raise WorkflowStructuralRepositoryError("Workflow 不允许自环")
        adjacency[edge.source_node_id].add(edge.target_node_id)
        reverse[edge.target_node_id].add(edge.source_node_id)

    start_id = starts[0].id
    end_id = ends[0].id
    roots = [node_id for node_id in binding_ids if not reverse[node_id]]
    leaves = [node_id for node_id in binding_ids if not adjacency[node_id]]
    if roots != [start_id]:
        raise WorkflowStructuralRepositoryError("START 必须是唯一根节点且不能有入边")
    if leaves != [end_id]:
        raise WorkflowStructuralRepositoryError("END 必须是唯一叶节点且不能有出边")

    indegree = {node_id: len(reverse[node_id]) for node_id in binding_ids}
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited: list[str] = []
    while ready:
        current = ready.pop()
        visited.append(current)
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(visited) != len(binding_ids):
        raise WorkflowStructuralRepositoryError("Workflow 不允许有向环")

    reachable = {start_id}
    pending = [start_id]
    while pending:
        current = pending.pop()
        for target in adjacency[current] - reachable:
            reachable.add(target)
            pending.append(target)
    if reachable != set(binding_ids):
        raise WorkflowStructuralRepositoryError("所有节点都必须从 START 可达")

    can_reach_end = {end_id}
    pending = [end_id]
    while pending:
        current = pending.pop()
        for source in reverse[current] - can_reach_end:
            can_reach_end.add(source)
            pending.append(source)
    if can_reach_end != set(binding_ids):
        raise WorkflowStructuralRepositoryError("所有节点都必须能够到达 END")

    if not validate_context:
        return

    context_names: list[str] = []
    for node in models:
        if node.type == "START":
            context_names.extend(item.name for item in node.inputs)
        elif node.type in {"SCRIPT", "LLM", "HTTP"}:
            context_names.extend(item.name for item in node.outputs)
    duplicates = sorted({name for name in context_names if context_names.count(name) > 1})
    if duplicates:
        raise WorkflowStructuralRepositoryError(
            f"Workflow Context 变量名必须唯一: {', '.join(duplicates)}"
        )

    declarations: dict[str, tuple[str, str]] = {}
    for node in models:
        if node.type == "START":
            declarations.update(
                {item.name: (node.id, item.type) for item in node.inputs}
            )
        elif node.type in {"SCRIPT", "LLM", "HTTP"}:
            declarations.update(
                {item.name: (node.id, item.type) for item in node.outputs}
            )

    for node in models:
        values: list[Any] = []
        if node.type == "LLM":
            values.extend(message.content for message in node.context.messages)
        elif node.type == "HTTP":
            values.append(node.request.url)
            values.extend(header.value for header in node.request.headers)
            values.extend(parameter.value for parameter in node.request.params)
            values.append(
                node.request.body.template_text
                if node.request.body.template_text is not None
                else node.request.body.model_dump(mode="json")["content"]
            )
        else:
            continue

        ancestors: set[str] = set()
        pending = list(reverse[node.id])
        while pending:
            ancestor = pending.pop()
            if ancestor in ancestors:
                continue
            ancestors.add(ancestor)
            pending.extend(reverse[ancestor])

        for root_name, path in template_references(values):
            declaration = declarations.get(root_name)
            if declaration is None:
                raise WorkflowStructuralRepositoryError(
                    f"节点“{node.name}”引用的 Context 变量不存在: {path}"
                )
            producer_id, declared_type = declaration
            if producer_id not in ancestors:
                raise WorkflowStructuralRepositoryError(
                    f"节点“{node.name}”的 Context 引用必须来自 START 或可达上游节点: {path}"
                )
            if path != root_name and declared_type not in {"object", "array"}:
                raise WorkflowStructuralRepositoryError(
                    f"节点“{node.name}”的嵌套 Context 引用要求根变量为 object 或 array: {path}"
                )


class WorkflowStructuralRepository:
    """以 SQLite 事务保存可不完整的 Workflow 编辑草稿。"""

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
        self,
        workflow: WorkflowStructuralModel,
        node_models: list[NodeStructuralModel],
        *,
        timestamp: str | None = None,
    ) -> WorkflowStructuralRecord:
        validated = WorkflowStructuralModel.model_validate(workflow)
        nodes = [NODE_STRUCTURAL_ADAPTER.validate_python(node) for node in node_models]
        now = timestamp or utc_now_iso()
        try:
            with self._transaction(immediate=True) as connection:
                connection.execute(insert(workflows_table).values(
                    id=validated.id,
                    name=validated.name,
                    description=validated.description,
                    created_at=now,
                    updated_at=now,
                ))
                self._insert_nodes_bindings_edges(connection, validated, nodes, now)
        except IntegrityError as exc:
            _raise_workflow_integrity_error("创建", exc)
        return WorkflowStructuralRecord(
            workflow=validated, node_models=nodes, created_at=now, updated_at=now
        )

    def get(self, workflow_id: str) -> WorkflowStructuralRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                select(workflows_table).where(workflows_table.c.id == workflow_id)
            ).mappings().first()
            if row is None:
                return None
            return self._record_from_connection(connection, row)

    def list(self) -> list[WorkflowStructuralSummary]:
        node_count_subquery = (
            select(func.count(workflow_node_bindings.c.node_id))
            .where(workflow_node_bindings.c.workflow_id == workflows_table.c.id)
            .correlate(workflows_table)
            .scalar_subquery()
            .label("node_count")
        )
        with self._connect() as connection:
            rows = connection.execute(
                select(
                    workflows_table.c.id,
                    workflows_table.c.name,
                    workflows_table.c.description,
                    node_count_subquery,
                    workflows_table.c.updated_at,
                ).order_by(
                    workflows_table.c.updated_at.desc(), workflows_table.c.id.desc()
                )
            ).mappings().all()
        return [WorkflowStructuralSummary(**dict(row)) for row in rows]

    def copy(self, workflow_id: str) -> WorkflowStructuralRecord:
        """Atomically duplicate a Workflow with independent structural identities."""

        now = utc_now_iso()
        try:
            with self._transaction(immediate=True) as connection:
                row = connection.execute(
                    select(workflows_table).where(workflows_table.c.id == workflow_id)
                ).mappings().first()
                if row is None:
                    raise WorkflowStructuralRepositoryError(
                        f"Workflow 不存在: {workflow_id}"
                    )
                current = self._record_from_connection(connection, row)
                existing_names = {
                    item["name"]
                    for item in connection.execute(
                        select(workflows_table.c.name)
                    ).mappings()
                }
                try:
                    copied_name = next_copy_name(
                        current.workflow.name, existing_names
                    )
                except ValueError as exc:
                    raise WorkflowStructuralRepositoryError(str(exc)) from exc
                node_ids = {
                    node.id: str(uuid4()) for node in current.node_models
                }
                copied_nodes = [
                    node.model_copy(update={"id": node_ids[node.id]})
                    for node in current.node_models
                ]
                copied_workflow = WorkflowStructuralModel(
                    id=str(uuid4()),
                    name=copied_name,
                    description=current.workflow.description,
                    nodes=[
                        binding.model_copy(
                            update={"node_id": node_ids[binding.node_id]}
                        )
                        for binding in current.workflow.nodes
                    ],
                    edges=[
                        edge.model_copy(
                            update={
                                "id": str(uuid4()),
                                "source_node_id": node_ids[edge.source_node_id],
                                "target_node_id": node_ids[edge.target_node_id],
                            }
                        )
                        for edge in current.workflow.edges
                    ],
                )
                connection.execute(insert(workflows_table).values(
                    id=copied_workflow.id,
                    name=copied_workflow.name,
                    description=copied_workflow.description,
                    created_at=now,
                    updated_at=now,
                ))
                self._insert_nodes_bindings_edges(
                    connection, copied_workflow, copied_nodes, now
                )
        except IntegrityError as exc:
            _raise_workflow_integrity_error("复制", exc)
        return WorkflowStructuralRecord(
            workflow=copied_workflow,
            node_models=copied_nodes,
            created_at=now,
            updated_at=now,
        )

    def update(
        self,
        workflow: WorkflowStructuralModel,
        node_models: list[NodeStructuralModel],
        *,
        timestamp: str | None = None,
    ) -> WorkflowStructuralRecord:
        validated = WorkflowStructuralModel.model_validate(workflow)
        nodes = [NODE_STRUCTURAL_ADAPTER.validate_python(node) for node in node_models]
        now = timestamp or utc_now_iso()
        try:
            with self._transaction(immediate=True) as connection:
                current = connection.execute(
                    select(workflows_table.c.created_at).where(
                        workflows_table.c.id == validated.id
                    )
                ).mappings().first()
                if current is None:
                    raise WorkflowStructuralRepositoryError(f"Workflow 不存在: {validated.id}")
                existing = {
                    row["node_id"]: row["type"]
                    for row in connection.execute(
                        select(
                            workflow_node_bindings.c.node_id,
                            node_models_table.c.type,
                        )
                        .join(
                            node_models_table,
                            node_models_table.c.id == workflow_node_bindings.c.node_id,
                        )
                        .where(workflow_node_bindings.c.workflow_id == validated.id)
                    ).mappings()
                }
                incoming = {node.id: node for node in nodes}
                for node_id, node in incoming.items():
                    if node_id in existing and existing[node_id] != node.type:
                        raise WorkflowStructuralRepositoryError(
                            f"节点 type 创建后不可修改: {existing[node_id]} -> {node.type}"
                        )
                    owner = connection.execute(
                        select(workflow_node_bindings.c.workflow_id).where(
                            workflow_node_bindings.c.node_id == node_id
                        )
                    ).mappings().first()
                    if owner is not None and owner["workflow_id"] != validated.id:
                        raise WorkflowStructuralRepositoryError(f"Node 已属于其他 Workflow: {node_id}")

                connection.execute(
                    delete(workflow_edges).where(
                        workflow_edges.c.workflow_id == validated.id
                    )
                )
                removed = set(existing) - set(incoming)
                for node_id in removed:
                    connection.execute(
                        delete(workflow_node_bindings).where(
                            workflow_node_bindings.c.workflow_id == validated.id,
                            workflow_node_bindings.c.node_id == node_id,
                        )
                    )
                    connection.execute(
                        delete(node_models_table).where(node_models_table.c.id == node_id)
                    )

                for node in nodes:
                    if node.id in existing:
                        connection.execute(
                            update(node_models_table)
                            .where(node_models_table.c.id == node.id)
                            .values(
                                name=node.name,
                                description=node.description,
                                definition_json=dump_node_definition(node),
                                updated_at=now,
                            )
                        )
                    else:
                        self._insert_node(connection, node, now)
                for binding in validated.nodes:
                    statement = sqlite_insert(workflow_node_bindings).values(
                        workflow_id=validated.id,
                        node_id=binding.node_id,
                        position_x=binding.position_x,
                        position_y=binding.position_y,
                    )
                    connection.execute(statement.on_conflict_do_update(
                        index_elements=[
                            workflow_node_bindings.c.workflow_id,
                            workflow_node_bindings.c.node_id,
                        ],
                        set_={
                            "position_x": statement.excluded.position_x,
                            "position_y": statement.excluded.position_y,
                        },
                    ))
                self._insert_edges(connection, validated)
                connection.execute(
                    update(workflows_table)
                    .where(workflows_table.c.id == validated.id)
                    .values(
                        name=validated.name,
                        description=validated.description,
                        updated_at=now,
                    )
                )
        except IntegrityError as exc:
            _raise_workflow_integrity_error("更新", exc)
        return WorkflowStructuralRecord(
            workflow=validated,
            node_models=nodes,
            created_at=current["created_at"],
            updated_at=now,
        )

    def save_node(
        self,
        workflow_id: str,
        node: NodeStructuralModel,
        *,
        position_x: float,
        position_y: float,
        timestamp: str | None = None,
    ) -> WorkflowStructuralRecord:
        """只保存一个节点及其位置，不改动其他节点和连线。"""

        validated_node = NODE_STRUCTURAL_ADAPTER.validate_python(node)
        binding = WorkflowNodeBinding(
            node_id=validated_node.id,
            position_x=position_x,
            position_y=position_y,
        )
        now = timestamp or utc_now_iso()
        try:
            with self._transaction(immediate=True) as connection:
                workflow_row = connection.execute(
                    select(workflows_table).where(workflows_table.c.id == workflow_id)
                ).mappings().first()
                if workflow_row is None:
                    raise WorkflowStructuralRepositoryError(
                        f"Workflow 不存在: {workflow_id}"
                    )

                current = connection.execute(
                    select(
                        node_models_table.c.type,
                        workflow_node_bindings.c.workflow_id,
                    )
                    .select_from(
                        node_models_table.outerjoin(
                            workflow_node_bindings,
                            node_models_table.c.id == workflow_node_bindings.c.node_id,
                        )
                    )
                    .where(node_models_table.c.id == validated_node.id)
                ).mappings().first()
                if current is not None and current["workflow_id"] not in {None, workflow_id}:
                    raise WorkflowStructuralRepositoryError(
                        f"Node 已属于其他 Workflow: {validated_node.id}"
                    )
                if current is not None and current["type"] != validated_node.type:
                    raise WorkflowStructuralRepositoryError(
                        f"节点 type 创建后不可修改: {current['type']} -> {validated_node.type}"
                    )

                if current is None:
                    self._insert_node(connection, validated_node, now)
                else:
                    connection.execute(
                        update(node_models_table)
                        .where(node_models_table.c.id == validated_node.id)
                        .values(
                            name=validated_node.name,
                            description=validated_node.description,
                            definition_json=dump_node_definition(validated_node),
                            updated_at=now,
                        )
                    )
                statement = sqlite_insert(workflow_node_bindings).values(
                    workflow_id=workflow_id,
                    node_id=binding.node_id,
                    position_x=binding.position_x,
                    position_y=binding.position_y,
                )
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[
                            workflow_node_bindings.c.workflow_id,
                            workflow_node_bindings.c.node_id,
                        ],
                        set_={
                            "position_x": statement.excluded.position_x,
                            "position_y": statement.excluded.position_y,
                        },
                    )
                )
                connection.execute(
                    update(workflows_table)
                    .where(workflows_table.c.id == workflow_id)
                    .values(updated_at=now)
                )
                saved_row = dict(workflow_row)
                saved_row["updated_at"] = now
                record = self._record_from_connection(connection, saved_row)
        except IntegrityError as exc:
            _raise_workflow_integrity_error("保存节点到", exc)
        return record

    def delete(self, workflow_id: str) -> bool:
        with self._transaction(immediate=True) as connection:
            node_ids = [
                row["node_id"]
                for row in connection.execute(
                    select(workflow_node_bindings.c.node_id).where(
                        workflow_node_bindings.c.workflow_id == workflow_id
                    )
                ).mappings()
            ]
            cursor = connection.execute(
                delete(workflows_table).where(workflows_table.c.id == workflow_id)
            )
            for node_id in node_ids:
                connection.execute(
                    delete(node_models_table).where(node_models_table.c.id == node_id)
                )
        return cursor.rowcount > 0

    def _insert_nodes_bindings_edges(
        self,
        connection: Connection,
        workflow: WorkflowStructuralModel,
        nodes: list[NodeStructuralModel],
        timestamp: str,
    ) -> None:
        for node in nodes:
            self._insert_node(connection, node, timestamp)
        for binding in workflow.nodes:
            connection.execute(insert(workflow_node_bindings).values(
                workflow_id=workflow.id,
                node_id=binding.node_id,
                position_x=binding.position_x,
                position_y=binding.position_y,
            ))
        self._insert_edges(connection, workflow)

    @staticmethod
    def _insert_node(connection: Connection, node: NodeStructuralModel, timestamp: str) -> None:
        connection.execute(insert(node_models_table).values(
            id=node.id,
            type=node.type,
            name=node.name,
            description=node.description,
            definition_json=dump_node_definition(node),
            created_at=timestamp,
            updated_at=timestamp,
        ))

    @staticmethod
    def _insert_edges(connection: Connection, workflow: WorkflowStructuralModel) -> None:
        for edge in workflow.edges:
            connection.execute(insert(workflow_edges).values(
                id=edge.id,
                workflow_id=workflow.id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
            ))

    def _record_from_connection(
        self, connection: Connection, row: Any
    ) -> WorkflowStructuralRecord:
        bindings = connection.execute(
            select(
                workflow_node_bindings.c.node_id,
                workflow_node_bindings.c.position_x,
                workflow_node_bindings.c.position_y,
            )
            .where(workflow_node_bindings.c.workflow_id == row["id"])
            .order_by(literal_column("rowid"))
        ).mappings().all()
        edges = connection.execute(
            select(
                workflow_edges.c.id,
                workflow_edges.c.source_node_id,
                workflow_edges.c.target_node_id,
            )
            .where(workflow_edges.c.workflow_id == row["id"])
            .order_by(literal_column("rowid"))
        ).mappings().all()
        bindings_alias = workflow_node_bindings.alias("bindings")
        node_rows = connection.execute(
            select(node_models_table)
            .select_from(
                bindings_alias.join(
                    node_models_table,
                    node_models_table.c.id == bindings_alias.c.node_id,
                )
            )
            .where(bindings_alias.c.workflow_id == row["id"])
            .order_by(literal_column("bindings.rowid"))
        ).mappings().all()
        workflow = WorkflowStructuralModel(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            nodes=[WorkflowNodeBinding(**dict(binding)) for binding in bindings],
            edges=[WorkflowEdge(**dict(edge)) for edge in edges],
        )
        nodes = []
        for node_row in node_rows:
            try:
                definition = json.loads(node_row["definition_json"])
            except (json.JSONDecodeError, TypeError) as exc:
                raise WorkflowStructuralRepositoryError(
                    f"节点定义数据损坏: {node_row['id']}"
                ) from exc
            payload = {
                "id": node_row["id"],
                "type": node_row["type"],
                "name": node_row["name"],
                "description": node_row["description"],
                **definition,
            }
            nodes.append(NODE_STRUCTURAL_ADAPTER.validate_python(payload))
        return WorkflowStructuralRecord(
            workflow=workflow,
            node_models=nodes,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @contextmanager
    def _connect(self, *, initialize: bool = True):
        if initialize:
            self.initialize()
        with database_read_connection(self.database_path, initialize=False) as connection:
            yield connection

    @contextmanager
    def _transaction(self, *, immediate: bool = False):
        self.initialize()
        with database_transaction(
            self.database_path, initialize=False, immediate=immediate
        ) as connection:
            yield connection


WORKFLOW_STRUCTURAL_ADAPTER = TypeAdapter(WorkflowStructuralModel)
