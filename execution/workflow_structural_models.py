"""Workflow Structural Model contracts, graph validation, and SQLite repository."""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from execution.node_structural_models import (
    NODE_STRUCTURAL_ADAPTER,
    NodeStructuralModel,
    NodeStructuralRepository,
)
from execution.node_codec import dump_node_definition
from execution.time_utils import utc_now_iso
from execution.init_db import (
    DEFAULT_DATABASE_PATH,
    configure_sqlite_connection,
    database_initialize_lock_for,
    initialize_sqlite_pragmas,
)


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
    """Repository 返回对象，组合完整 Workflow 结构和数据库管理时间。"""

    workflow: WorkflowStructuralModel = Field(description="完整且已校验的 Workflow Structural Model。")
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
    updated_at: str = Field(description="最近结构保存时间，UTC ISO-8601。")


class WorkflowStructuralRepositoryError(RuntimeError):
    """Workflow 结构无法验证、持久化或满足 Repository 不变量时的领域错误。"""


class WorkflowNameConflictError(WorkflowStructuralRepositoryError):
    """Workflow 名称已被其他结构记录占用。"""


def _raise_workflow_integrity_error(operation: str, exc: sqlite3.IntegrityError) -> None:
    if "workflow_structural_models.name" in str(exc):
        raise WorkflowNameConflictError("Workflow 名称已存在，请使用其他名称") from exc
    raise WorkflowStructuralRepositoryError(
        f"{operation} Workflow Structural Model 失败: {exc}"
    ) from exc


def validate_workflow_graph(
    workflow: WorkflowStructuralModel,
    node_models: list[NodeStructuralModel],
) -> None:
    """验证完整 DAG、系统节点边界和 Workflow 级 Context 名称唯一性。"""

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


class WorkflowStructuralRepository:
    """以单个 SQLite 事务保存 Workflow、Node、binding 和 Edge 当前结构。"""

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
            NodeStructuralRepository(self.database_path).initialize()
            with self._connect(initialize=False) as connection:
                initialize_sqlite_pragmas(connection)
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_structural_models (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE CHECK(length(trim(name)) > 0),
                        description TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS workflow_node_bindings (
                        workflow_id TEXT NOT NULL,
                        node_id TEXT NOT NULL UNIQUE,
                        position_x REAL NOT NULL,
                        position_y REAL NOT NULL,
                        PRIMARY KEY(workflow_id, node_id),
                        FOREIGN KEY(workflow_id) REFERENCES workflow_structural_models(id) ON DELETE CASCADE,
                        FOREIGN KEY(node_id) REFERENCES node_structural_models(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS workflow_edges (
                        id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        source_node_id TEXT NOT NULL,
                        target_node_id TEXT NOT NULL,
                        UNIQUE(workflow_id, source_node_id, target_node_id),
                        FOREIGN KEY(workflow_id, source_node_id)
                            REFERENCES workflow_node_bindings(workflow_id, node_id) ON DELETE CASCADE,
                        FOREIGN KEY(workflow_id, target_node_id)
                            REFERENCES workflow_node_bindings(workflow_id, node_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS workflow_structural_models_by_updated
                        ON workflow_structural_models(updated_at DESC, id DESC);
                    CREATE INDEX IF NOT EXISTS workflow_edges_by_workflow
                        ON workflow_edges(workflow_id, source_node_id, target_node_id);
                    """
                )
                connection.commit()
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
        validate_workflow_graph(validated, nodes)
        now = timestamp or utc_now_iso()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO workflow_structural_models VALUES (?, ?, ?, ?, ?)",
                    (validated.id, validated.name, validated.description, now, now),
                )
                self._insert_nodes_bindings_edges(connection, validated, nodes, now)
                connection.commit()
        except sqlite3.IntegrityError as exc:
            _raise_workflow_integrity_error("创建", exc)
        return WorkflowStructuralRecord(
            workflow=validated, node_models=nodes, created_at=now, updated_at=now
        )

    def get(self, workflow_id: str) -> WorkflowStructuralRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_structural_models WHERE id = ?", (workflow_id,)
            ).fetchone()
            if row is None:
                return None
            return self._record_from_connection(connection, row)

    def list(self) -> list[WorkflowStructuralSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description, updated_at FROM workflow_structural_models "
                "ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [WorkflowStructuralSummary(**dict(row)) for row in rows]

    def update(
        self,
        workflow: WorkflowStructuralModel,
        node_models: list[NodeStructuralModel],
        *,
        timestamp: str | None = None,
    ) -> WorkflowStructuralRecord:
        validated = WorkflowStructuralModel.model_validate(workflow)
        nodes = [NODE_STRUCTURAL_ADAPTER.validate_python(node) for node in node_models]
        validate_workflow_graph(validated, nodes)
        now = timestamp or utc_now_iso()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT created_at FROM workflow_structural_models WHERE id = ?",
                    (validated.id,),
                ).fetchone()
                if current is None:
                    raise WorkflowStructuralRepositoryError(f"Workflow 不存在: {validated.id}")
                existing = {
                    row["node_id"]: row["type"]
                    for row in connection.execute(
                        "SELECT b.node_id, n.type FROM workflow_node_bindings b "
                        "JOIN node_structural_models n ON n.id = b.node_id WHERE b.workflow_id = ?",
                        (validated.id,),
                    )
                }
                incoming = {node.id: node for node in nodes}
                for node_id, node in incoming.items():
                    if node_id in existing and existing[node_id] != node.type:
                        raise WorkflowStructuralRepositoryError(
                            f"节点 type 创建后不可修改: {existing[node_id]} -> {node.type}"
                        )
                    owner = connection.execute(
                        "SELECT workflow_id FROM workflow_node_bindings WHERE node_id = ?",
                        (node_id,),
                    ).fetchone()
                    if owner is not None and owner["workflow_id"] != validated.id:
                        raise WorkflowStructuralRepositoryError(f"Node 已属于其他 Workflow: {node_id}")

                connection.execute("DELETE FROM workflow_edges WHERE workflow_id = ?", (validated.id,))
                removed = set(existing) - set(incoming)
                for node_id in removed:
                    connection.execute(
                        "DELETE FROM workflow_node_bindings WHERE workflow_id = ? AND node_id = ?",
                        (validated.id, node_id),
                    )
                    connection.execute("DELETE FROM node_structural_models WHERE id = ?", (node_id,))

                for node in nodes:
                    if node.id in existing:
                        connection.execute(
                            "UPDATE node_structural_models SET name = ?, description = ?, "
                            "definition_json = ?, updated_at = ? WHERE id = ?",
                            (node.name, node.description, dump_node_definition(node), now, node.id),
                        )
                    else:
                        self._insert_node(connection, node, now)
                for binding in validated.nodes:
                    connection.execute(
                        "INSERT INTO workflow_node_bindings(workflow_id,node_id,position_x,position_y) "
                        "VALUES (?,?,?,?) ON CONFLICT(workflow_id,node_id) DO UPDATE SET "
                        "position_x=excluded.position_x, position_y=excluded.position_y",
                        (validated.id, binding.node_id, binding.position_x, binding.position_y),
                    )
                self._insert_edges(connection, validated)
                connection.execute(
                    "UPDATE workflow_structural_models SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                    (validated.name, validated.description, now, validated.id),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            _raise_workflow_integrity_error("更新", exc)
        return WorkflowStructuralRecord(
            workflow=validated,
            node_models=nodes,
            created_at=current["created_at"],
            updated_at=now,
        )

    def delete(self, workflow_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            node_ids = [
                row["node_id"]
                for row in connection.execute(
                    "SELECT node_id FROM workflow_node_bindings WHERE workflow_id = ?",
                    (workflow_id,),
                )
            ]
            cursor = connection.execute(
                "DELETE FROM workflow_structural_models WHERE id = ?", (workflow_id,)
            )
            for node_id in node_ids:
                connection.execute("DELETE FROM node_structural_models WHERE id = ?", (node_id,))
            connection.commit()
        return cursor.rowcount > 0

    def _insert_nodes_bindings_edges(
        self,
        connection: sqlite3.Connection,
        workflow: WorkflowStructuralModel,
        nodes: list[NodeStructuralModel],
        timestamp: str,
    ) -> None:
        for node in nodes:
            self._insert_node(connection, node, timestamp)
        for binding in workflow.nodes:
            connection.execute(
                "INSERT INTO workflow_node_bindings VALUES (?, ?, ?, ?)",
                (workflow.id, binding.node_id, binding.position_x, binding.position_y),
            )
        self._insert_edges(connection, workflow)

    @staticmethod
    def _insert_node(connection: sqlite3.Connection, node: NodeStructuralModel, timestamp: str) -> None:
        connection.execute(
            "INSERT INTO node_structural_models(id,type,name,description,definition_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (node.id, node.type, node.name, node.description, dump_node_definition(node), timestamp, timestamp),
        )

    @staticmethod
    def _insert_edges(connection: sqlite3.Connection, workflow: WorkflowStructuralModel) -> None:
        for edge in workflow.edges:
            connection.execute(
                "INSERT INTO workflow_edges VALUES (?, ?, ?, ?)",
                (edge.id, workflow.id, edge.source_node_id, edge.target_node_id),
            )

    def _record_from_connection(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> WorkflowStructuralRecord:
        bindings = connection.execute(
            "SELECT node_id, position_x, position_y FROM workflow_node_bindings "
            "WHERE workflow_id = ? ORDER BY rowid",
            (row["id"],),
        ).fetchall()
        edges = connection.execute(
            "SELECT id, source_node_id, target_node_id FROM workflow_edges "
            "WHERE workflow_id = ? ORDER BY rowid",
            (row["id"],),
        ).fetchall()
        node_rows = connection.execute(
            "SELECT n.* FROM workflow_node_bindings b JOIN node_structural_models n ON n.id=b.node_id "
            "WHERE b.workflow_id = ? ORDER BY b.rowid",
            (row["id"],),
        ).fetchall()
        workflow = WorkflowStructuralModel(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            nodes=[WorkflowNodeBinding(**dict(binding)) for binding in bindings],
            edges=[WorkflowEdge(**dict(edge)) for edge in edges],
        )
        nodes = []
        for node_row in node_rows:
            payload = {
                "id": node_row["id"],
                "type": node_row["type"],
                "name": node_row["name"],
                "description": node_row["description"],
                **json.loads(node_row["definition_json"]),
            }
            nodes.append(NODE_STRUCTURAL_ADAPTER.validate_python(payload))
        validate_workflow_graph(workflow, nodes)
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
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, foreign_keys=True)
        try:
            yield connection
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()


WORKFLOW_STRUCTURAL_ADAPTER = TypeAdapter(WorkflowStructuralModel)
