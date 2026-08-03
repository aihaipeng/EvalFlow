# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 最高产品准则

- 所有产品、交互、信息架构和技术方案必须站在目标用户的真实任务与使用环境中设计，以降低学习成本和排障成本为最高优先级，不得优先迁就内部数据结构、实现便利或技术术语。
- 用户界面必须使用用户能够理解的业务语言和操作路径；合理默认、熟悉概念与渐进披露优先，原始 JSON、Context、内部状态、错误堆栈和实现细节只能作为深入调试信息，不能成为用户完成核心任务的前提。
- 运行结果和异常信息必须先给出可行动结论，再提供证据和原始数据。失败场景至少直接回答：哪里失败、期望是什么、实际是什么、下一步如何处理；能够定位到规则或节点时，不得只展示笼统状态或要求用户自行遍历日志。
- 每项设计必须以真实用户故事验证，而不只验证功能存在。核心流程的验收标准是目标用户无需理解系统内部实现即可完成操作；用例失败后，用户应能在 10 秒内识别失败位置、期望值、实际值和建议动作。
- 当视觉表现、技术实现便利或历史结构与本准则冲突时，本准则优先；但不得以简化体验为由牺牲数据正确性、安全性、可追溯性或必要的专业能力。

## 执行任务的强制流程

- 动手前结合当前业务场景确认 Why、Who/Where、What/When 和可观测的验收标准。
- 未确认的业务逻辑不得自行补全；确需澄清时，单次只问最多 3 个最高优先级问题，并提供互斥选项或示例， 最推荐的放在首位。
- 多模块或跨系统任务必须拆成可独立验证的子任务，写清目标、输入/输出、验证方法和依赖。每个子任务验证通过后才能进入下一项。
- 开发完成后必须给出并执行端到端测试方案，同时运行受影响模块回归；不能只依赖静态字符串测试。
- 工作区可能已有用户改动，禁止回滚或覆盖与当前任务无关的差异。

## 必读文档

开始任何任务前必须完整阅读根目录 `AGENTS.md`（强制执行流程）。当前事实、已确认业务规则、逐步验证记录和未确认项统一记录在 `PLAN.md`（倒序，最新任务在最上方，每个任务包含 Why/Who/What/验收标准/子任务拆解/验证记录）；两者优先于历史文档和 Git 历史。`WORKFLOW_SPEC.md` 是 Workflow 引擎的唯一事实来源：任何 Workflow 结构、节点字段、状态机、Context、输入输出协议、重试、取消、错误或数据完整性变更，必须先更新该文档再改代码。

## 常用命令

```powershell
uv python install 3.14              # 首次：安装 Python 3.14（仅需一次）
uv sync --locked --python 3.14      # 安装/同步 Python 依赖
uv run python run.py                # 启动本机服务 http://127.0.0.1:8010
uv run pytest -q                    # 全量 Python 测试
uv run pytest tests/test_workflow_execution.py -q             # 单文件
uv run pytest tests/test_batch_api.py::test_case -q           # 单用例
npm run typecheck                   # OpenAPI 漂移检查 + TypeScript
npm run openapi:generate            # 路由契约变更后重新导出 OpenAPI 并生成前端类型
npm run test:frontend               # 前端几何/对齐纯函数测试
npm run test:e2e                    # Playwright 浏览器 E2E（自动启动隔离服务器 :8765）
npx playwright test tests/e2e/management.spec.mjs   # 单文件 E2E；-g "用例名" 单条用例
npm run dev                         # Vite dev server（前端开发时热更新，仍需单独启动 run.py）
npm ci && npm run build             # 修改 web/frontend 后重建全部 4 个 React bundle
```

- 修改 `web/frontend/` 源码后必须 `npm run build`：Vite 从单一配置构建 4 个按需入口和共享 chunk 到 `web/static/assets/vite/`，FastAPI 按 manifest 注入内容哈希资源；构建产物提交进仓库，日常运行不依赖 Node.js。
- live 模型测试：设置 `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` 后 `uv run pytest -m live -q`；无密钥时自动 skip，属正常现象。
- pytest 临时目录统一输出到 `.pytest_tmp/`（`pyproject.toml` 中 `addopts = --basetemp=.pytest_tmp`），每个测试用例的临时目录命名为 `test_<name>0`、`test_<name>1`…，已加入 `.gitignore`。
- 交付前的完整回归惯例（见 PLAN.md 各任务验证记录）：
  `uv run pytest -q && python -m compileall . && npm run typecheck && npm run test:frontend && npm run build && npm run test:e2e && git diff --check`；
  另对真实数据库副本执行 `PRAGMA integrity_check` / `PRAGMA foreign_key_check` 并核对升级前后行数不变。

### 测试文件速查

| 文件 | 覆盖领域 |
|---|---|
| `tests/test_workflow_execution.py` | Workflow DAG 调度、Context 提交、Fail-Fast |
| `tests/test_workflow_structural_models.py` | Workflow/Node/Edge CRUD 与图校验 |
| `tests/test_workflow_api.py` | Workflow REST API |
| `tests/test_tool_execution.py` | SCRIPT 节点子进程执行与输出提取 |
| `tests/test_batch_scheduler.py` | Batch Case 并发、取消、恢复 |
| `tests/test_batch_api.py` | Batch REST API |
| `tests/test_batch_execution_store.py` | Batch/Case JSON 原子存储 |
| `tests/test_batch_execution_history.py` | Batch 执行历史 |
| `tests/test_batch_schedule.py` | APScheduler 定时触发 |
| `tests/test_case_evaluator.py` | Case 结果校验规则 |
| `tests/test_test_sets.py` | 测试集 SQLite Repository |
| `tests/test_test_sets_api.py` | 测试集 REST API |
| `tests/test_model_providers.py` | 模型供应商 Repository |
| `tests/test_model_gateway.py` | 模型网关调用（无真实密钥） |
| `tests/test_model_gateway_live.py` | 真实模型调用（需 `-m live`） |
| `tests/test_workflow_values.py` | Context 引用解析与类型转换 |
| `tests/test_node_structural_models.py` | 五类节点 Structural Model |
| `tests/test_run_stream.py` | SSE 流式推送 |
| `tests/test_web_app.py` | FastAPI 应用与路由基础 |
| `tests/test_backend_architecture.py` | 架构约束（import 方向等） |
| `tests/test_resource_names.py` | 资源命名规范 |
| `tests/*_frontend*.py` | 前端纯函数/几何计算 |
| `tests/e2e/*.spec.mjs` | Playwright 浏览器 E2E |

### 开发关键细节

- **E2E 隔离环境**：Playwright 自动启动 `tests/e2e_server.py`，在 **8765** 端口以临时目录独立 SQLite 运行，不与 8010 开发数据库共享数据。`playwright.config.mjs` 配置 `workers: 1`（串行执行），使用 Chromium channel，失败时保留 trace 和截图。
- **数据库迁移**：① 在 `execution/database_schema.py` 修改 `MetaData` 表定义 → ② 在 `migrations/versions/` 创建 `YYYYMMDD_NNNN_描述.py`，设置 `down_revision` 指向上一个版本 → ③ 启动时 `upgrade_database()` 自动执行未应用迁移。迁移使用应用托管连接（`migrations/env.py` 拒绝 CLI 直连），`render_as_batch=True`（适配 SQLite ALTER 限制）。
- **OpenAPI 类型链路**：`scripts/export_openapi.py` 从 FastAPI 路由导出 OpenAPI JSON → `openapi-typescript` 生成 `web/frontend/generated/openapi.d.ts` → `scripts/check_openapi.py` 检查契约是否与后端同步。修改路由签名后必须 `npm run openapi:generate`，CI 门禁 `npm run typecheck` 包含此漂移检查。
- **前端构建**：必须使用 `npm ci`（非 `npm install`）保证与 `package-lock.json` 一致。`npm run build` 内部执行 `vite build`，从四入口生成内容哈希资源和 `manifest.json` 到 `web/static/assets/vite/`。FastAPI 通过 manifest 注入正确的哈希路径。构建产物提交进仓库，日常运行不依赖 Node.js。

## 架构

本机单用户 FastAPI 应用，固定绑定 `127.0.0.1:8010`。Workflow 和节点测试调度器保存进程内活动状态，因此**只支持单个 Uvicorn worker**，禁止 `--workers` 多进程参数。

### 依赖方向（强制）

`web routes -> application services -> execution/storage 域 -> runtime ports`。`execution/` 和 `storage/` 禁止导入 `web`。应用级资源由 `web/workflow_services.py` 在 FastAPI lifespan 中创建并通过 Dependency 注入路由；路由不得持有模块级可变 Repository 单例，也不得跨模块导入私有 helper。

### 双模型存储（强制）

- **Structural Model**（Workflow/Node/Edge/Model Provider/测试集/调度计划元数据）只允许存 SQLite（`run_storage/agent_bench.sqlite3`）。表定义统一集中在 `execution/database_schema.py`（SQLAlchemy Core `MetaData`），启动时由 `execution/init_db.py::upgrade_database()` 通过 Alembic 升级到最新版本；Repository 通过 `database_read_connection()` 或自动提交/回滚的 `database_transaction()` 使用共享 Engine 和 Core 表达式，不保留 sqlite3 facade。默认路径、按 resolved path 共享的初始化锁和 PRAGMA（WAL/foreign_keys）统一由 `execution/init_db.py` 拥有。改表结构必须同时改 `database_schema.py` 并新增手写的 `migrations/versions/` 迁移版本（命名 `YYYYMMDD_NNNN_描述.py`，启动时由 `upgrade_database()` 自动执行）；Alembic 迁移只能经应用托管连接执行（`migrations/env.py` 拒绝 CLI 直连），禁止在 Repository 中手写 DDL。
- **Execution Model**（Workflow/Node/Batch/Case 运行记录）只允许存本机 JSON 文件（`run_storage/workflow_executions/`、`run_storage/batch_executions/`）。数据库不得创建 Execution 表，文件系统不得另存 Structural Model。例外：`batch_execution_history` 表只存 Batch 列表页展示用的运行摘要元数据（不含 Case 级执行证据，完整执行事实仍以 JSON 为准），属已确认的 Structural 定位。

### 执行链

- 五类节点：START / SCRIPT / LLM / HTTP / END。`execution/workflow_execution.py` 负责 DAG 拓扑调度、Context 原子提交、全局中断和旧公共 import 的兼容重导出。
- `workflow_node_executor.py` 是注册表协调器，只做通用生命周期、Context commit 和类型分派；具体协议在 `workflow_script_runner.py` / `workflow_llm_runner.py` / `workflow_http_runner.py`（共享基类 `workflow_node_runner_base.py`）。
- SCRIPT 在可取消子进程中执行（`execution/tool_runtime.py` / `tool_worker.py`；`web/` 下同名文件只是无状态兼容导出层）。子进程 stderr 被父进程捕获，子进程不持有日志文件句柄。
- 单节点临时测试（`workflow_node_tests.py`）走同一个 Node Executor 注册表，使用 SSE（Server-Sent Events）推送执行进度到前端，不产生持久化 Execution Model JSON。测试会话在关闭编辑器或刷新页面后消失。运行期间禁用重复运行，不提供用户中断入口。

### Context 变量流

- START 节点的 `inputs` 是 Context 的初始来源（Batch Run 时注入测试集字段值，手动 Run 时来自用户填入的变量）。
- SCRIPT 节点通过只读 `context` Mapping 读取上游变量（如 `context["threshold"]`）。
- LLM/HTTP 节点通过 `${变量名}` 模板引用读取 Context 中的变量值，模板在节点执行前解析为实际值。
- 每个业务节点的 `outputs` 是多个 `name/type/source` 原子组：多个输出分别提取和类型转换，任一项失败整组不提交且不自动重试。成功提交后下游节点立即可见。
- 变量名严格大小写敏感（`result`、`Result`、`RESULT` 是三个不同变量），全程不做归一化。
- 类型转换只允许规范定义的矩阵：数值必须往返等值、无精度丢失；转换失败使用对应错误码（`SCRIPT_OUTPUT_TYPE_MISMATCH` 等），不静默回退。
- Batch Run：Excel 行经 `batch_inputs.py` 映射为 START 输入并冻结快照（源 Excel/Workflow 后续修改不影响已建 Run）；`batch_scheduler.py` 负责 Case 有界并发、失败隔离、取消和手工恢复（成功 Case 不重跑）；`batch_execution_store.py` 原子 JSON 存储与进程重启收敛；Case 结果校验在 `case_evaluator.py`（EvaluationRule：校验项/路径/运算符/预期值/类型，全部通过才 PASS，任一失败或配置错误即 FAIL）。
- 定时触发由 `batch_schedule.py` 通过 APScheduler 3.11 管理，计划持久化在 SQLite `batch_schedules` 表；调度 Job 只保存任务 ID，不序列化 API Key、代理密码或完整任务快照。

### 路由与本地文件约束

- FastAPI 处理器按实际 I/O 模型声明：直接调用同步 SQLAlchemy / 文件系统的用普通 `def`（线程池执行）；只有真正 `await` 异步客户端（如模型供应商连接测试的 httpx）才用 `async def`。
- 测试集、供应商和 Workflow 等结构化数据必须通过对应 SQLite Repository 在事务中写入；路由不得直接操作数据库文件或维护第二份事实来源。

### 前端

- `web/static/app.js` 是手写 SPA 外壳（侧边栏导航、主题切换、按视图挂载 feature bundle）；`web/frontend/` 是 4 个 React 页面源码：`workflow-canvas.jsx`（React Flow 工作流画布）、`test-sets.jsx`（测试集管理）、`model-providers.jsx`（供应商管理）、`batch-runs.jsx`（任务调度）。前端为 JSX 页面 + TS API 模块混用（如 `batch-api.ts`），`tsc` 只检查 `.ts`/`.d.ts`，JSX 文件不经类型检查（`tsconfig.json` 的 `include` 只含 `web/frontend/**/*.ts` 和 `*.d.ts`）。Vite 统一生成 manifest 和内容哈希入口；供应商与任务 API 使用 `openapi-typescript` + `openapi-fetch`，提交型任务表单使用 React Hook Form + Zod，弹窗使用 Radix primitives。`execution.js` 只保留 Workflow 列表和 Batch 结果详情等活动兼容桥，不得新增 Batch 列表/配置双写。
- 只支持桌面浏览器，不新增移动端适配或回归。
- 前端静态测试（`test_*_frontend.py`）直接断言已构建的 `web/static/` 和源码 `web/frontend/` 文件内容，是一种静态契约测试模式，不经浏览器。前端纯函数测试（`tests/*.test.mjs`）使用 Node.js 原生 `node --test` 运行。

完整目录说明见 README.md「项目结构」。

## 关键行为约束（WORKFLOW_SPEC.md 顶层约束摘要）

- **错误显式化、拒绝静默污染**：任何配置错误、引用缺失、解析失败或协议异常必须产生明确错误，不得用未定义的转换、默认回退或部分提交伪装成功。
- Context 变量名严格大小写敏感，任何阶段不得做大小写归一化。
- 节点 outputs 是原子组：多个输出分别提取和类型转换，任一项失败整组不提交且不自动重试；类型转换只允许规范定义的矩阵，数值必须往返等值、无精度丢失。
- Workflow 必须恰好一个 START、一个 END 的单一弱连通 DAG；任一 Node Execution 最终 FAILED 立即全局 Fail-Fast；Workflow SUCCESS 的唯一标志是 END Node Execution SUCCESS。
- 日志界面只对已保存 Execution Model 字段做只读格式化，不是第二份事实存储；JSON 外层转义不得泄漏到展示、复制或下游读取值中。
- 用户不能单独中断完整 Workflow 中的单个 Node Execution 或单节点临时测试，只能通过画布全局中断停止完整 Workflow。
- 旧 Script/Agent 工具协议、旧固定 Workflow/Run 页面、API 和执行链已不兼容删除，不得恢复。
- APScheduler 固定在 3.11.x 稳定分支，禁止采用仍有兼容风险的 4.0 预发布分支；任何框架替换必须保持现有 SQLite 唯一事实来源、API 契约和执行证据语义，禁止引入 Redis、Docker 或常驻外部服务（决策记录见 PLAN.md T13.38）。

## 本地数据与安全

`run_storage/` 和 `logs/` 均为本机数据且已被 `.gitignore` 排除，不得强制提交。测试集保存在 `run_storage/agent_bench.sqlite3`；Excel 仅在浏览器本地解析，不上传、不写入服务器目录。API Key 不得写入代码、测试、文档、模板包或提交内容；live 测试只通过环境变量注入。
