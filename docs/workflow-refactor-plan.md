# Workflow Refactor Plan

## Objective

Replace the legacy `workflow_drafts` protocol with the Workflow contract in
`WORKFLOW_SPEC.md`. The target is a persistent `Workflow / WorkflowRun /
NodeRun` model, a backend DAG executor, and a canvas that uses `/api/workflows`.

Current iteration prioritizes execution availability and terminal correctness.
Full definition snapshots, complete logs, failed-attempt history, and stack
trace persistence are explicitly out of scope. Their recording must never block
node execution, terminal state updates, or Context commits.

## Step 1: Contract Test Baseline

**Goal**: Turn the stable parts of `WORKFLOW_SPEC.md` into executable tests.

**Inputs**: `WORKFLOW_SPEC.md`; UUIDv4, JSON type, Context, and node status
rules.

**Outputs**: Contract test fixtures and pure validation APIs for Workflow,
START, SCRIPT, LLM, HTTP, END, Context names, and error codes.

**Dependencies**: None.

**Verification**:

```powershell
uv run pytest tests/test_workflow_contract.py
```

The tests must cover valid definitions, invalid UUID/type/name cases, Context
key normalization, duplicate output rejection, and non-persisted runtime
evidence boundaries.

## Step 2: Persistence and Workflow API

**Goal**: Persist the new Workflow definition and its WorkflowRun/NodeRun
terminal facts independently of the legacy draft tables.

**Inputs**: Step 1 domain models and validation results.

**Outputs**: New SQLite tables, repository operations, and `/api/workflows`
CRUD plus WorkflowRun query endpoints. IDs are UUIDv4 strings and timestamps
use `YYYY-MM-DD HH:mm:ss` in Asia/Shanghai.

**Dependencies**: Step 1.

**Verification**:

```powershell
uv run pytest tests/test_workflow_repository.py tests/test_workflow_api.py
```

The tests must cover restart retention, CRUD, invalid configuration rejection,
WorkflowRun-to-Workflow association, and final NodeRun fact persistence. No
legacy row is migrated or read.

## Step 3: Context and DAG Executor

**Goal**: Execute the graph according to the contract.

**Inputs**: Persisted Workflow definition, fresh per-run Context, and node
adapters supplied by Step 4.

**Outputs**: Topological scheduling, parallel ready-node dispatch, Context
reference resolution, atomic output commits, fail-fast cancellation, retries,
timeouts, and terminal WorkflowRun/NodeRun records.

**Dependencies**: Step 2. Node adapters can initially be deterministic fakes.

**Verification**:

```powershell
uv run pytest tests/test_workflow_engine.py
```

The suite must cover START-to-SCRIPT flow, multiple parallel branches,
Context key collisions, missing references, retry accounting, output atomicity,
fail-fast, and user cancellation.

## Step 4: Node Adapters and Run API

**Goal**: Connect the executor to real SCRIPT, HTTP, and LLM operations.

**Inputs**: Step 3 execution hooks, existing isolated Python worker, HTTP
client, and model-provider management.

**Outputs**: SCRIPT `get_val/set_val`, HTTP substitution/output extraction,
LLM prompt resolution/raw-text output, and start/query/cancel APIs. The start
and cancel APIs are invoked by the Workflow canvas top-right Run and Cancel
buttons; they do not introduce a separate run-center workflow.

**Dependencies**: Step 3.

**Verification**:

```powershell
uv run pytest tests/test_workflow_script.py tests/test_workflow_http.py tests/test_workflow_llm.py
uv run pytest -m live tests/test_workflow_llm_live.py
```

SCRIPT uses a real isolated process. HTTP uses a local test server. The live
LLM suite calls a real model only when credentials and model selection are
provided through process environment variables; credentials are never written
to repository files, SQLite, test fixtures, or logs.

## Step 5: Canvas Cutover and Legacy Removal

**Goal**: Switch the React Flow canvas to the new API and remove the old
`/api/workflow-drafts` path, legacy repository, legacy variable mapping, and
their tests.

**Inputs**: Stable CRUD and run API from Steps 2-4.

**Outputs**: Canvas save/run/cancel/history views backed by `/api/workflows`.

**Dependencies**: Steps 2-4.

**Verification**:

```powershell
npm run build
uv run pytest tests/test_workflow_frontend.py
uv run pytest
```

The browser end-to-end flow must create a workflow, save it, run it, inspect
terminal node records, and verify a failed node stops sibling work according to
the fail-fast rule.

## Implementation Status

| Step | Status | Regression result |
| --- | --- | --- |
| 1. Contract test baseline | Complete | Contract models validate UUIDv4, strict JSON, Context naming, graph structure and upstream references. |
| 2. Persistence and Workflow API | Complete | CRUD, run association, restart recovery and deletion protection are covered by repository/API tests. |
| 3. Context and DAG executor | Complete | Parallel dispatch, retries, timeout, fail-fast, user cancellation and Context collision tests pass. |
| 4. Node adapters and run API | Complete | Isolated SCRIPT, local HTTP, provider-backed LLM adapter and run APIs are covered; the live LLM check remains opt-in through process environment. |
| 5. Canvas cutover and legacy removal | Complete | The active canvas uses `/api/workflows`; old draft routes are unregistered and generated assets are rebuilt. |
