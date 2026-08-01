# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 必读文档

开始任何任务前必须完整阅读根目录 `AGENTS.md`（强制执行流程）。当前事实、已确认业务规则、逐步验证记录和未确认项统一记录在 `PLAN.md`（倒序，最新任务在最上方）；两者优先于历史文档和 Git 历史。`WORKFLOW_SPEC.md` 是 Workflow 引擎的唯一事实来源：任何 Workflow 结构、节点字段、状态机、Context、输入输出协议、重试、取消、错误或数据完整性变更，必须先更新该文档再改代码。

## 常用命令

```powershell
uv sync --locked --python 3.14      # 首次安装 Python 依赖
uv run python run.py                # 启动本机服务 http://127.0.0.1:8010
uv run pytest -q                    # 全量 Python 测试
uv run pytest tests/test_workflow_execution.py -q             # 单文件
uv run pytest tests/test_batch_api.py::test_case -q           # 单用例
node --test tests/*.test.mjs        # 前端几何/对齐测试（3 个 .mjs 用例）
npm run test:e2e                    # Playwright 浏览器 E2E（自动启动隔离服务器 :8765）
npm ci && npm run build             # 修改 web/frontend 后重建全部 4 个 React bundle
```

- 修改 `web/frontend/` 源码后必须 `npm run build`：4 个 React 页面分别由 `scripts/build-*.mjs`（esbuild）构建到 `web/static/assets/`，构建脚本自动改写 `index.html` 里的 `?v=` 版本哈希；构建产物提交进仓库，日常运行不依赖 Node.js。
- live 模型测试：设置 `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` 后 `uv run pytest -m live -q`；无密钥时自动 skip，属正常现象。
- 交付前的完整回归惯例（见 PLAN.md 各任务验证记录）：`uv run pytest -q` + `python -m compileall` + `npm run build` + `git diff --check`。

## 架构

本机单用户 FastAPI 应用，固定绑定 `127.0.0.1:8010`。Workflow 和节点测试调度器保存进程内活动状态，因此**只支持单个 Uvicorn worker**，禁止 `--workers` 多进程参数。

### 依赖方向（强制）

`web routes -> application services -> execution/storage 域 -> runtime ports`。`execution/` 和 `storage/` 禁止导入 `web`。应用级资源由 `web/workflow_services.py` 在 FastAPI lifespan 中创建并通过 Dependency 注入路由；路由不得持有模块级可变 Repository 单例，也不得跨模块导入私有 helper。

### 双模型存储（强制）

- **Structural Model**（Workflow/Node/Edge/Model Provider/测试集/调度计划元数据）只允许存 SQLite（`run_storage/agent_bench.sqlite3`）。表定义统一集中在 `execution/database_schema.py`（SQLAlchemy Core `MetaData`），启动时由 `execution/init_db.py::upgrade_database()` 通过 Alembic 升级到最新版本；Repository 经 `database_connection()` 取得共享 Engine 的 Core 连接（`CoreConnection`/`CoreRow` 是 sqlite3 风格 facade，Repository 保持原生 SQL 写法）。默认路径、按 resolved path 共享的初始化锁和 PRAGMA（WAL/foreign_keys）统一由 `execution/init_db.py` 拥有。改表结构必须同时改 `database_schema.py` 并新增手写的 `migrations/versions/` 迁移版本；Alembic 迁移只能经应用托管连接执行（`migrations/env.py` 拒绝 CLI 直连），禁止在 Repository 中手写 DDL。
- **Execution Model**（Workflow/Node/Batch/Case 运行记录）只允许存本机 JSON 文件（`run_storage/workflow_executions/`、`run_storage/batch_executions/`）。数据库不得创建 Execution 表，文件系统不得另存 Structural Model。

### 执行链

- 五类节点：START / SCRIPT / LLM / HTTP / END。`execution/workflow_execution.py` 负责 DAG 拓扑调度、Context 原子提交、全局中断和旧公共 import 的兼容重导出。
- `workflow_node_executor.py` 是注册表协调器，只做通用生命周期、Context commit 和类型分派；具体协议在 `workflow_script_runner.py` / `workflow_llm_runner.py` / `workflow_http_runner.py`（共享基类 `workflow_node_runner_base.py`）。
- SCRIPT 在可取消子进程中执行（`execution/tool_runtime.py` / `tool_worker.py`；`web/` 下同名文件只是无状态兼容导出层）。
- 单节点临时测试（`workflow_node_tests.py`）走同一个 Node Executor，使用 SSE 推送，不产生持久化 Execution Model。
- Batch Run：Excel 行经 `batch_inputs.py` 映射为 START 输入并冻结快照（源 Excel/Workflow 后续修改不影响已建 Run）；`batch_scheduler.py` 负责 Case 有界并发、失败隔离、取消和手工恢复（成功 Case 不重跑）；`batch_execution_store.py` 原子 JSON 存储与进程重启收敛；Case 结果校验在 `case_evaluator.py`（EvaluationRule：校验项/路径/运算符/预期值/类型，全部通过才 PASS，任一失败或配置错误即 FAIL）。
- 定时触发由 `batch_schedule.py` 通过 APScheduler 3.11 管理，计划持久化在 SQLite `batch_schedules` 表；调度 Job 只保存任务 ID，不序列化 API Key、代理密码或完整任务快照。

### 路由与本地文件约束

- FastAPI 处理器按实际 I/O 模型声明：直接调用同步 sqlite3 / openpyxl / 文件系统的用普通 `def`（线程池执行）；只有真正 `await` 异步客户端（如模型供应商连接测试的 httpx）才用 `async def`。
- 测试集、供应商和 Workflow 等结构化数据必须通过对应 SQLite Repository 在事务中写入；路由不得直接操作数据库文件或维护第二份事实来源。

### 前端

- `web/static/app.js` 是手写 SPA 外壳（侧边栏导航、主题切换、按视图挂载 feature bundle）；`web/frontend/` 是 4 个 React 页面源码：`workflow-canvas.jsx`（React Flow @xyflow/react 工作流画布）、`test-sets.jsx`（测试集管理）、`model-providers.jsx`（供应商管理）、`batch-runs.jsx`（任务调度），后两个为 React 18 + TanStack Query；各自经 `scripts/build-*.mjs` 构建为 `web/static/assets/*.js`。供应商管理旧原生脚本已删除；任务调度原生 `execution.js` 仍在 `index.html` 中加载。
- 只支持桌面浏览器，不新增移动端适配或回归。

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
