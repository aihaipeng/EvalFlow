"""Workflow Structural Model CRUD API for the local development canvas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from execution import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_EXECUTION_ROOT,
    ModelProviderRepository,
    NodeTestManager,
    WorkflowEdge,
    WorkflowNameConflictError,
    WorkflowNodeBinding,
    WorkflowStructuralModel,
    WorkflowStructuralRecord,
    WorkflowStructuralRepository,
    WorkflowStructuralRepositoryError,
    WorkflowStructuralSummary,
    WorkflowExecutionError,
    WorkflowExecutionManager,
    WorkflowExecutionStore,
)
from execution.node_structural_models import NodeStructuralModel
from web.files import open_directory_in_explorer


router = APIRouter(prefix="/api/workflows", tags=["workflows"])
DATABASE_PATH = DEFAULT_DATABASE_PATH
_repository_instance: WorkflowStructuralRepository | None = None
_repository_path: Path | None = None
EXECUTION_ROOT = DEFAULT_EXECUTION_ROOT
_manager_instance: WorkflowExecutionManager | None = None
_manager_key: tuple[Path, Path] | None = None
_node_test_manager_instance: NodeTestManager | None = None
_node_test_manager_path: Path | None = None


def _raise_repository_http_error(exc: WorkflowStructuralRepositoryError) -> None:
    status_code = 409 if isinstance(exc, WorkflowNameConflictError) else 400
    raise HTTPException(status_code, str(exc)) from exc


class _WorkflowApiModel(BaseModel):
    """Workflow API 的严格请求与响应基类。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class WorkflowNodeWrite(_WorkflowApiModel):
    """一次完整保存中的 Node Structural Model 及其画布坐标。"""

    node: Annotated[NodeStructuralModel, Field(discriminator="type")] = Field(
        description="完整 Node Structural Model。"
    )
    position_x: float = Field(description="Node 画布 X 坐标。")
    position_y: float = Field(description="Node 画布 Y 坐标。")


class WorkflowWriteRequest(_WorkflowApiModel):
    """创建或完整替换 Workflow 当前结构的请求。"""

    name: str = Field(min_length=1, max_length=200, description="保留原文的 Workflow 名称。")
    description: str = Field(default="", max_length=4000, description="Workflow 用途说明。")
    nodes: list[WorkflowNodeWrite] = Field(description="完整 Node 结构和画布坐标。")
    edges: list[WorkflowEdge] = Field(description="有向调度依赖数组。")


class WorkflowMetadataRequest(_WorkflowApiModel):
    """只修改既有 Workflow 名称和说明的请求。"""

    name: str = Field(min_length=1, max_length=200, description="保留原文的 Workflow 名称。")
    description: str = Field(default="", max_length=4000, description="Workflow 用途说明。")


class WorkflowEnvelope(_WorkflowApiModel):
    """单个完整 Workflow Structural Record 响应。"""

    workflow: WorkflowStructuralRecord = Field(description="完整 Workflow Structural Record。")


class WorkflowListResponse(_WorkflowApiModel):
    """Workflow 一级列表摘要响应。"""

    workflows: list[WorkflowStructuralSummary] = Field(description="按更新时间倒序的 Workflow 摘要。")


class WorkflowExecutionEnvelope(_WorkflowApiModel):
    """单个 Workflow Execution JSON 响应。"""

    execution: dict = Field(description="完整 Workflow Execution JSON。")


class WorkflowExecutionListResponse(_WorkflowApiModel):
    """最近 Workflow Execution JSON 列表响应。"""

    executions: list[dict] = Field(description="按创建时间倒序的最近执行。")


class NodeExecutionListResponse(_WorkflowApiModel):
    """一次 Workflow Execution 的全部 Node Execution JSON 响应。"""

    executions: list[dict] = Field(description="本次执行已经创建的 Node Execution。")


class ExecutionDirectoryResponse(_WorkflowApiModel):
    """打开本地 Execution 根目录的结果。"""

    ok: bool = Field(description="资源管理器调用是否成功。")
    path: str = Field(description="已打开的绝对目录路径。")


class NodeTestRequest(_WorkflowApiModel):
    """使用当前未保存节点草稿和本次临时 Context 启动测试。"""

    node: Annotated[NodeStructuralModel, Field(discriminator="type")] = Field(
        description="当前前端节点草稿，不要求已经保存。"
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="只对本次测试有效、大小写敏感的严格 JSON 变量池。",
    )


class NodeTestEnvelope(_WorkflowApiModel):
    """单节点临时测试身份和当前前端快照。"""

    test_id: str = Field(description="仅用于本次事件连接和中断的临时 UUID。")
    node_id: str = Field(description="被测试的节点 ID。")
    status: str = Field(description="当前临时状态。")
    snapshot: dict[str, Any] = Field(description="不含 Execution 身份或结构快照的临时事实。")


class NodeTestCancelResponse(_WorkflowApiModel):
    """单节点临时测试中断请求结果。"""

    test_id: str = Field(description="被请求中断的临时测试 ID。")
    interrupted: bool = Field(description="是否找到并通知了活动 Worker。")


def _get_repository() -> WorkflowStructuralRepository:
    """返回当前数据库路径对应的 Repository，支持测试隔离临时数据库。"""

    global _repository_instance, _repository_path
    path = Path(DATABASE_PATH).resolve()
    if _repository_instance is None or _repository_path != path:
        _repository_instance = WorkflowStructuralRepository(path)
        _repository_path = path
    return _repository_instance


def _get_manager() -> WorkflowExecutionManager:
    """返回当前数据库和 Execution 根目录对应的进程内调度器。"""

    global _manager_instance, _manager_key
    database_path = Path(DATABASE_PATH).resolve()
    execution_root = Path(EXECUTION_ROOT).resolve()
    key = (database_path, execution_root)
    if _manager_instance is None or _manager_key != key:
        structural_repository = WorkflowStructuralRepository(database_path)
        _manager_instance = WorkflowExecutionManager(
            structural_repository,
            ModelProviderRepository(database_path),
            WorkflowExecutionStore(execution_root),
        )
        _manager_key = key
    return _manager_instance


def _get_node_test_manager() -> NodeTestManager:
    """返回当前数据库路径对应的进程内单节点临时测试管理器。"""

    global _node_test_manager_instance, _node_test_manager_path
    database_path = Path(DATABASE_PATH).resolve()
    if (
        _node_test_manager_instance is None
        or _node_test_manager_path != database_path
    ):
        _node_test_manager_instance = NodeTestManager(
            WorkflowStructuralRepository(database_path),
            ModelProviderRepository(database_path),
        )
        _node_test_manager_path = database_path
    return _node_test_manager_instance


def _get_or_404(workflow_id: str) -> WorkflowStructuralRecord:
    record = _get_repository().get(workflow_id)
    if record is None:
        raise HTTPException(404, f"Workflow 不存在: {workflow_id}")
    return record


def _structural_model(
    workflow_id: str, body: WorkflowWriteRequest
) -> tuple[WorkflowStructuralModel, list[NodeStructuralModel]]:
    bindings = [
        WorkflowNodeBinding(
            node_id=item.node.id,
            position_x=item.position_x,
            position_y=item.position_y,
        )
        for item in body.nodes
    ]
    workflow = WorkflowStructuralModel(
        id=workflow_id,
        name=body.name,
        description=body.description,
        nodes=bindings,
        edges=body.edges,
    )
    return workflow, [item.node for item in body.nodes]


@router.get("", response_model=WorkflowListResponse)
def list_workflows() -> WorkflowListResponse:
    """列出 Workflow 管理页所需的名称、说明和更新时间摘要。"""

    return WorkflowListResponse(workflows=_get_repository().list())


@router.post("", response_model=WorkflowEnvelope, status_code=201)
def create_workflow(body: WorkflowWriteRequest) -> WorkflowEnvelope:
    """完整校验并原子创建 Workflow、Node、binding 和 Edge。"""

    workflow, nodes = _structural_model(str(uuid4()), body)
    try:
        record = _get_repository().create(workflow, nodes)
    except WorkflowStructuralRepositoryError as exc:
        _raise_repository_http_error(exc)
    return WorkflowEnvelope(workflow=record)


@router.get("/{workflow_id}", response_model=WorkflowEnvelope)
def get_workflow(workflow_id: str) -> WorkflowEnvelope:
    """读取可完整还原画布的 Workflow Structural Record。"""

    return WorkflowEnvelope(workflow=_get_or_404(workflow_id))


@router.put("/{workflow_id}", response_model=WorkflowEnvelope)
def update_workflow(workflow_id: str, body: WorkflowWriteRequest) -> WorkflowEnvelope:
    """完整校验并原子替换既有 Workflow 当前结构。"""

    current = _get_or_404(workflow_id)
    next_node_ids = {item.node.id for item in body.nodes}
    removed_node_ids = {
        node.id for node in current.node_models if node.id not in next_node_ids
    }
    try:
        for node_id in removed_node_ids:
            _get_node_test_manager().cancel_node(workflow_id, node_id)
    except WorkflowExecutionError as exc:
        raise HTTPException(409, str(exc)) from exc
    workflow, nodes = _structural_model(workflow_id, body)
    try:
        record = _get_repository().update(workflow, nodes)
    except WorkflowStructuralRepositoryError as exc:
        _raise_repository_http_error(exc)
    return WorkflowEnvelope(workflow=record)


@router.put("/{workflow_id}/metadata", response_model=WorkflowEnvelope)
def update_workflow_metadata(
    workflow_id: str, body: WorkflowMetadataRequest
) -> WorkflowEnvelope:
    """复用当前合法图，只更新 Workflow 名称和说明。"""

    current = _get_or_404(workflow_id)
    workflow = current.workflow.model_copy(
        update={"name": body.name, "description": body.description}
    )
    try:
        record = _get_repository().update(workflow, current.node_models)
    except WorkflowStructuralRepositoryError as exc:
        _raise_repository_http_error(exc)
    return WorkflowEnvelope(workflow=record)


@router.delete("/{workflow_id}", response_model=WorkflowEnvelope)
def delete_workflow(workflow_id: str) -> WorkflowEnvelope:
    """删除 Workflow 及其当前 Node、binding 和 Edge，并返回删除前快照。"""

    current = _get_or_404(workflow_id)
    manager = _get_manager()
    try:
        _get_node_test_manager().cancel_workflow(workflow_id)
    except WorkflowExecutionError as exc:
        raise HTTPException(409, str(exc)) from exc
    if manager.has_active_workflow(workflow_id):
        raise HTTPException(409, "Workflow 存在活动 Execution，请先全局中断并等待终态")
    if not _get_repository().delete(workflow_id):
        raise HTTPException(404, f"Workflow 不存在: {workflow_id}")
    manager.store.delete_workflow_root(workflow_id)
    return WorkflowEnvelope(workflow=current)


@router.post(
    "/{workflow_id}/node-tests",
    response_model=NodeTestEnvelope,
    status_code=202,
)
def start_node_test(workflow_id: str, body: NodeTestRequest) -> NodeTestEnvelope:
    """测试当前节点草稿，不校验整图、不执行上下游且不创建持久化事实。"""

    try:
        envelope, _created = _get_node_test_manager().start(
            workflow_id, body.node, body.context
        )
    except WorkflowExecutionError as exc:
        raise HTTPException(400, str(exc)) from exc
    return NodeTestEnvelope.model_validate(envelope)


@router.get("/{workflow_id}/node-tests/{test_id}/events")
def stream_node_test_events(workflow_id: str, test_id: str) -> StreamingResponse:
    """以 SSE 交付实时临时快照；终态交付后服务端立即释放会话。"""

    manager = _get_node_test_manager()

    def events():
        try:
            for event in manager.iter_events(workflow_id, test_id):
                if event is None:
                    yield ": keepalive\n\n"
                    continue
                event_type = str(event.get("type", "snapshot"))
                payload = json.dumps(event, ensure_ascii=False, allow_nan=False)
                yield f"event: {event_type}\ndata: {payload}\n\n"
        except WorkflowExecutionError as exc:
            payload = json.dumps(
                {"type": "error", "message": str(exc)}, ensure_ascii=False
            )
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{workflow_id}/node-tests/{test_id}/cancel",
    response_model=NodeTestCancelResponse,
)
def cancel_node_test(workflow_id: str, test_id: str) -> NodeTestCancelResponse:
    """幂等中断单节点临时测试，不影响活动 Workflow Execution。"""

    return NodeTestCancelResponse(
        test_id=test_id,
        interrupted=_get_node_test_manager().cancel(workflow_id, test_id),
    )


@router.post("/{workflow_id}/runs", response_model=WorkflowExecutionEnvelope, status_code=202)
def start_workflow_execution(workflow_id: str) -> WorkflowExecutionEnvelope:
    """使用当前 Structural Snapshot 异步启动一次手动 Workflow Execution。"""

    _get_or_404(workflow_id)
    try:
        execution = _get_manager().start(workflow_id)
    except (WorkflowExecutionError, WorkflowStructuralRepositoryError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return WorkflowExecutionEnvelope(execution=execution)


@router.get("/{workflow_id}/runs", response_model=WorkflowExecutionListResponse)
def list_workflow_executions(workflow_id: str) -> WorkflowExecutionListResponse:
    """读取最近 10 次 Workflow Execution，全部事实来自本地 JSON。"""

    _get_or_404(workflow_id)
    return WorkflowExecutionListResponse(
        executions=_get_manager().store.list(workflow_id, limit=10)
    )


@router.get(
    "/{workflow_id}/runs/{execution_id}", response_model=WorkflowExecutionEnvelope
)
def get_workflow_execution(
    workflow_id: str, execution_id: str
) -> WorkflowExecutionEnvelope:
    """读取一次完整 Workflow Execution JSON。"""

    execution = _get_manager().store.get_workflow(workflow_id, execution_id)
    if execution is None:
        raise HTTPException(404, f"Workflow Execution 不存在: {execution_id}")
    return WorkflowExecutionEnvelope(execution=execution)


@router.get(
    "/{workflow_id}/runs/{execution_id}/nodes", response_model=NodeExecutionListResponse
)
def list_node_executions(
    workflow_id: str, execution_id: str
) -> NodeExecutionListResponse:
    """读取一次 Workflow Execution 已创建的全部 Node Execution JSON。"""

    if _get_manager().store.get_workflow(workflow_id, execution_id) is None:
        raise HTTPException(404, f"Workflow Execution 不存在: {execution_id}")
    return NodeExecutionListResponse(
        executions=_get_manager().store.get_nodes(workflow_id, execution_id)
    )


@router.post(
    "/{workflow_id}/runs/{execution_id}/cancel",
    response_model=WorkflowExecutionEnvelope,
)
def cancel_workflow_execution(
    workflow_id: str, execution_id: str
) -> WorkflowExecutionEnvelope:
    """幂等全局中断一次活动 Workflow Execution。"""

    manager = _get_manager()
    current = manager.store.get_workflow(workflow_id, execution_id)
    if current is None:
        raise HTTPException(404, f"Workflow Execution 不存在: {execution_id}")
    if current.get("status") not in {"SUCCESS", "FAILED", "INTERRUPTED"}:
        manager.cancel(execution_id)
    latest = manager.store.get_workflow(workflow_id, execution_id) or current
    return WorkflowExecutionEnvelope(execution=latest)


@router.post(
    "/{workflow_id}/execution-directory", response_model=ExecutionDirectoryResponse
)
def open_workflow_execution_directory(workflow_id: str) -> ExecutionDirectoryResponse:
    """打开当前 Workflow 固定的 Execution 根目录。"""

    _get_or_404(workflow_id)
    path = _get_manager().store.workflow_root(workflow_id, create=True)
    return ExecutionDirectoryResponse(ok=True, path=open_directory_in_explorer(path))
