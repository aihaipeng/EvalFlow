# 技术审查与开源替换评估（T13.39）

> 状态：2026-08-02 已完成 P0 整改、P1 替换、P2 条件验证和最终回归。下方 A/B/C 清单保留为实施前审计证据；“实施结果”是当前状态的权威摘要。
> 对齐状态：本报告已与根目录 `PLAN.md` T13.39 的范围、状态、验收数据和暂缓边界对齐。
> 调研方式：4 路并行子域调研（Workflow 执行内核 / Batch 调度与存储 / 前端 / Repository 与模型网关）+ 主线程自查（全量测试基线、安全模块、文档一致性）。
> 测试基线：实施前 `392 passed, 4 skipped`；实施后 `420 passed, 4 skipped`，另有前端静态 `61 passed`、Node `8 passed`、Playwright `5 passed`。
> 约束：本报告「确认的问题」= 代码实证且与规格/承诺对照成立；「疑似」= 需进一步验证，不得直接当作已确认缺陷修复。
> 与本报告衔接：修复项应以子任务形式进入根目录 `PLAN.md`（倒序，最新在上），逐项验证后回填。

### 对齐后的业务目标与决策口径

- **Why**：A 类契约缺陷直接影响运行正确性，必须先修；其后只用成熟组件替换构建、接口契约、弹窗和管理表单等通用能力，把维护投入留给冻结快照、执行追溯、取消/续跑和结果校验等业务核心。
- **Who / Where**：4 至 5 名测试工程师继续在本机浏览器使用 SQLite 单机应用；替换不得要求 Redis、Docker、独立数据库、云端服务或新的运维角色。
- **What / When**：A 类缺陷按 P0 完成；Vite、OpenAPI 类型客户端、Radix 弹窗和 SQLAlchemy Core 深化按 P1 完成；React Hook Form、Zod 与 axe 按 P2 完成，TanStack Table 和 Excel 网格保持条件项。
- **How to Measure**：替换前后 API、SQLite schema、Workflow/Batch 状态机和 Execution JSON 证据语义不变；全量 pytest、生产构建、类型检查与 Playwright E2E 通过；每项还必须证明重复实现、原始 SQL、手工焦点逻辑或前后端契约漂移点实际减少。

### 实施结果（当前状态）

| 范围 | 结果 | 可观测证据 |
|---|---|---|
| P0 A1-A20 | **已修复** | 新增 Workflow/Batch/Repository/网关契约与故障注入测试；全量 Python 从审计基线 392 增至 420 通过 |
| Batch 前端双写 | **已清理** | `execution.js` 删除约 640 行不可达 Batch 管理代码；React 页面统一列表、配置、历史、定时和退避轮询 |
| Vite 多入口 | **已采用** | 删除 4 个 `scripts/build-*.mjs`；单一配置生成 4 个内容哈希入口、共享 chunk 和 manifest；FastAPI 按需注入 |
| TypeScript/OpenAPI | **已采用（供应商、任务）** | OpenAPI 可重复导出/漂移检查；`openapi-fetch<paths>` 接管对应 API；`tsc --noEmit` 进入门禁 |
| Radix Dialog/AlertDialog | **已采用** | 模型、任务、测试集和节点测试弹窗完成迁移；Playwright 验证 Esc、焦点返回和 axe。原生 Workflow 删除/Batch 结果详情作为已登记兼容桥，禁止扩展 |
| SQLAlchemy Core 深化 | **已完成** | 6 个 Repository 使用 Core 表达式与显式事务；sqlite3 facade 删除；只隔离保留 `BEGIN IMMEDIATE`/PRAGMA |
| RHF + Zod PoC | **证明净收益并保留** | 任务基础表单 8 组手写受控字段改为注册式字段；一份 schema 覆盖创建/编辑/复制，5 个字段就地显示错误 |
| TanStack Table | **条件未触发，不引入** | 当前列表没有列隐藏、批量选择、服务端排序等新增能力，引入只会增加抽象层 |
| Glide Data Grid | **门禁未通过，不替换** | 免费 XLSX、多 Sheet、多矩形选择、Ctrl 叠加、暗色主题和大表门禁未同时成立，FortuneSheet + SheetJS 保持隔离 |
| axe / Playwright | **已进入门禁** | 5 条 Chromium E2E 覆盖四目录、三类资源 CRUD/保存和任务全流程；WCAG A/AA 扫描无违规 |
| 并发 UI 改动合并 | **已完成** | 当前“新建供应商 / 新建任务”等术语和视觉样式作为最终基线，架构替换未回退用户改动 |

补充修复：全量回归发现 Windows 深目录中的 Execution JSON/ZIP 可能超过 `MAX_PATH`，现已对原子写入、归档和读取使用扩展长度路径；该修复不改变 manifest 或 Execution JSON 协议。

最终数据库验证使用真实库副本连续升级两次：Alembic 版本保持 `20260802_0001`，11 张业务表行数不变，`integrity_check=ok`、`foreign_key_check=[]`；验证过程没有修改用户原始数据库。

## 一、项目存在的问题

### A 类：执行契约偏差 / 真实缺陷（最优先修复）

#### Workflow 执行内核（12 项确认，对照 WORKFLOW_SPEC.md）

| # | 问题 | 位置 |
|---|---|---|
| A1 | `LLM_RESPONSE_PARSE_ERROR` 不重试，规格 7.3 明确模型请求错误/超时/**响应解析错误**均允许按 max_attempts 重试 | `execution/workflow_llm_runner.py:229-237` |
| A2 | `usage_errors`、`truncated_fields` 初始化后从不填充——功能未实现（规格 7.2 要求非法 usage 生成 UsageIssue；SCRIPT 的 5MiB 截断已实现，LLM 的没有） | `execution/workflow_llm_runner.py:42,155` |
| A3 | HTTP Retry-After 未实现，重试等待只用 `retry_interval_seconds`（规格要求响应只有一个合法 Retry-After 时优先使用） | `execution/workflow_http_runner.py:224-227` |
| A4 | 规格错误目录之外的自造码 `HTTP_CONTEXT_RESOLUTION_ERROR`（规格 12.2 禁止临时错误码）；LLM 缺变量被错报为 `LLM_MESSAGE_EMPTY`/`LLM_EXECUTION_ERROR`，判定靠 `str(exc).startswith("LLM ")` 字符串前缀匹配，脆弱；按规格应报 `CONTEXT_VARIABLE_NOT_FOUND` | `execution/workflow_http_runner.py:74`、`execution/workflow_llm_runner.py:125-133` |
| A5 | 非 array 用过滤器静默返回 null；跨类型 `<`/`>` 比较、`contain` 对 dict 静默返回 False——规格 7.3 要求这些属于 source 计算错误必须显式报错 | `execution/workflow_values.py:244-245,176-200` |
| A6 | `SCRIPT_OUTPUT_SERIALIZATION_ERROR` 是死码：`tool_worker.py` 序列化失败只返回 `ok=False` 无 `error_code`，`workflow_script_runner.py:93-99` 全映射为 `SCRIPT_RUNTIME_ERROR` | `execution/tool_worker.py:277-286` |
| A7 | 超大有限数（如 `float(Decimal('1e400'))`）抛 `OverflowError` 而非 `WorkflowValueError`/类型错误，`math.isfinite` 检查走不到，异常冒泡被兜底包成 `NODE_FAILED`，错误码错乱（规格 3.3 要求 `*_OUTPUT_TYPE_MISMATCH`） | `execution/workflow_values.py:337` |
| A8 | Fail-Fast 触发后未消费的 future 使 `workflow.json` 的 `nodes[]` 悬挂在 RUNNING/PENDING，而其 Node Execution JSON 已写盘为 INTERRUPTED——两处事实不一致（有竞态依赖，但代码路径明确存在） | `execution/workflow_execution.py:247-283` |
| A9 | PENDING 期间被中断的节点写入非 null `duration_ms`（规格 11.1 要求 PENDING 时为 null）；同文件 `_fail_pending_configuration` 路径正确保持 null，两条路径不一致 | `execution/workflow_node_runner_base.py:105-128` |
| A10 | 静态 Context 引用校验未实现：规格 10.2 要求保存/启动时静态引用分析（引用不存在/自身输出/下游输出即校验失败），当前只在运行时发现缺失变量（且错误码还报错，见 A4） | `execution/workflow_execution.py` 调度循环 |
| A11 | `_run` 兜底 except 把所有异常标为 `PERSISTENCE_FAILED`，掩盖调度器自身逻辑 bug 与 commit 内部错误的真实根因 | `execution/workflow_execution.py:304-306` |
| A12 | `SCRIPT_OUTPUT_MISSING` 的 error.details 缺 name 字段；多个 source 缺失只报告第一个 | `execution/workflow_script_runner.py:103-107` |

#### Batch 层（5 项确认）

| # | 问题 | 位置 |
|---|---|---|
| A13 | `replace_current` 两步 `os.replace` 存在崩溃窗口：`cases` 与 `input` 目录替换之间进程崩溃 → cases 目录缺失、batch.json 仍是旧轮、下次 `prepare_execution` 抛 `FileNotFoundError` 无恢复路径、`.pc-*/.pi-*` 残留永久堆积——直接违反「进程重启后收敛」硬约束（`recover_incomplete` 不处理此场景） | `execution/batch_execution_store.py:182-197,452-485` |
| A14 | 数值校验 EQ/NE 的 int/float 陷阱：`case_evaluator.py` 要求 `type(actual) is type(expected)`，而 Context 中 `1.0` 经 JSON round-trip 是 float、`convert_output("1.0","number")` 返回 int——用户配置 expected `"1.0"` 匹配实际 `1.0` 判 FAIL；NE 方向反偏；GT/GTE/LT/LTE 不受影响 | `execution/case_evaluator.py:96-100`、`execution/workflow_values.py:335-336` |
| A15 | 定时触发双重 `prepare_execution`（`run_due` 一次 + `start` 无条件再来一次），每次触发全量 case JSON 写两次；RANDOM 调用序两轮种子不同但被执行第二轮，语义无破坏，属确定性写放大 | `execution/batch_schedule.py:406-411`、`execution/batch_scheduler.py:51-81` |
| A16 | Case 轮询 `while True` + `time.sleep(0.03)` 无超时、不检查 `cancel_event`：Workflow 线程已死/`workflow.json` 损坏时永久自旋占用全局槽位；取消后 `failure_retry_count` 重试循环不检查 cancel_event，取消后仍发起新 Workflow 执行 | `execution/batch_scheduler.py:382-390,330-355` |
| A17 | 单条用例线程（`_run_single_case`）不在 `shutdown` join 集合；`execution_mode=="SINGLE_CASE"` 时 `cancel()` 返回 False——应用退出时在飞单条用例无人等待，依赖 daemon 线程与下次启动收敛 | `execution/batch_scheduler.py:228-247` |

#### Repository / 模型网关层（3 项确认）

| # | 问题 | 位置 |
|---|---|---|
| A18 | 3 处 `json.loads` 无 try/except：数据损坏时抛裸 `JSONDecodeError` → 路由层 500；而 `node_structural_models.py:806-820` 同类路径会包装领域错误，处理不一致（违反「错误显式化」） | `execution/model_providers.py:348-349`、`execution/batch_schedule.py:302`、`execution/workflow_structural_models.py:575` |
| A19 | 历史去重对 NULL `execution_round_id` 失效：SQL 中 `NULL = NULL` 恒为 NULL，`deduplicate=True` 永不命中已有行 → 重复历史记录 | `execution/batch_execution_history.py:74-77` |
| A20 | 模型网关三个 `invoke_openai_compatible`/`invoke_openai_responses`/`invoke_anthropic` 约 3×36 行几乎相同；且生产执行走 subprocess RAW_HTTP（可取消、可中断），网关异步客户端只服务连接测试与 live 测试——双 HTTP 栈各自维护超时/代理/SSL 逻辑，行为漂移风险真实 | `execution/model_gateway.py:247-358` |

### B 类：实施前技术债快照（前端最重）

> 本节记录立项时的代码证据，使用现在时是为了保留审计原貌，不代表当前实现状态；实际处置以文首“实施结果”和第三节为准。

1. **execution.js 与 React 双写（违反 PLAN 自定规则「页面迁移后删除对应旧实现，禁止长期双写」）**：`web/static/execution.js:587-1225` 约 640 行原生批跑列表是不可达死代码，`window.viewBatchRuns` 双重定义（execution.js:898 vs batch-runs.jsx:27）靠 index.html 加载顺序碰巧不冲突，React bundle 加载失败时旧实现会「意外复活」；已产生可见分叉（原生表头「名称/0 个 Run」vs React「任务/0 个任务」、原生轮询自适应退避 2-10s vs React 平 1s、原生 Progress 有 STOPPING 态 React 没有）。**不能整文件删**：工作流列表（439-581）、模态系统（55-143）、批跑详情（1227-1608）、节点↔结构模型序列化（221-437）仍是活动代码，且被 app.js 与两个 React 页面直接调用（`openExecutionConfirm`、`viewBatchDetail`、`viewWorkflows`/`openWorkflowCanvas` 桥）。
2. 节点图↔结构模型互转写两遍（`execution.js:221-437` 与 `workflow-canvas.jsx:812-952`）；分页组件 4 份（app.js:272-320、test-sets.jsx:222-227、model-providers.jsx:36-44、batch-runs.jsx:16）；模态焦点陷阱 5 份；时间格式化 4 份；模型协议默认参数表 2 份（workflow-canvas.jsx:155-173 与 model-providers.jsx:8-12）；图标两套体系（lucide-react vs assets/icons.js 快照，后者无再生成脚本）。
3. 4 个 `scripts/build-*.mjs` 是同一构建逻辑（esbuild → 去尾空白 → sha256 前 12 位 → 正则替换 index.html）复制 4 份。由于当前已有 4 个 React 入口，已越过 PLAN T13.38 设定的 Vite 复评阈值；应由 Vite 多入口构建和 manifest 接管共享依赖、代码分割、哈希资源与 FastAPI 静态注入，而不是继续扩展手工正则替换。另：index.html 中 `style.css`/`execution.css`/`assets/icons.js` 的 `?v=` 哈希无任何脚本再生成，改动源文件后会过期；app.py 对顶层静态文件返回 no-cache 头，`execution.js?v=` 实际冗余。
4. **性能隐患**：全项目零 `React.memo`——节点测试运行期每 100ms `setNodes` → 全部节点 data 重建 → 所有节点与未 memo 的 Inspector 全量重渲染（workflow-canvas.jsx:2390-2396,2913-2927）；`runAll` 每 250ms 轮询两个端点（运行期约 8 req/s，2741-2753）；batch-runs.jsx:25 活动任务期平 1s 全列表轮询（不如被替换原生的自适应退避）；`onNodeDrag` 每帧全画布对齐线计算（3255-3257）；app.js:369-375 对 `document.body` 全子树 MutationObserver。
5. `web/run_stream.py` 是生产死代码（SSE 生产唯一入口是 routes_workflows.py 的 sse-starlette `EventSourceResponse`），被 `tests/test_tool_removal.py:42` 契约锁住保留；`workflow-canvas.jsx` 内 `showParametersTab` 恒为 false 死分支（1497）。
6. **改造前证据，已解决**：`execution/init_db.py:71-78` 的迁移期 PRAGMA 与 `database_connection` 事务陷阱。当前 Alembic 连接顺序已修正，6 个 Repository 均使用显式事务，`database_connection` facade 已删除。
7. `execution/__init__.py` 183 行统一重导出约 80 个符号（模型网关全部函数、全部 Repository/Store），execution 域依赖粒度不可见，任何模块改动都影响公共 API 表面。
8. **README.md 过时**：第 8、10 行描述的「Script / Agent 工具 CRUD、ZIP 导入导出」「Parser、Evaluator、Check Aggregator、Case Aggregator 固定工作流」在代码中已全部不存在（grep 实证），与 CLAUDE.md「旧工具协议已不兼容删除」约束相悖。
9. 测试空洞：无 `CONTEXT_KEY_EXISTS` 运行时冲突测试（A8 因此无暴露）；无 SCRIPT 5MiB 截断测试；无 LLM usage_errors 测试（功能未实现）；无 Retry-After 测试；无 TIMEOUT→重试→成功链路；无 misfire/refresh 并发测试；无数值 EQ int/float 陷阱测试（A14 未被发现）；无 `replace_current` 中断恢复测试（A13 未被发现）；无 shutdown 与并发 cancel/start/resume 竞态测试；E2E 仅 4 条（目录切换/供应商 CRUD/测试集+画布建保存/任务创建复制定时启动详情），画布内部编辑（拖拽、undo/redo、五类节点表单、SSE 直播）零覆盖；Python 前端测试仍以源码字符串断言为主，与 PLAN 承诺「不得再以源码字符串断言作为唯一证明」相悖。
10. 依赖噪音：全量测试 1 个 `StarletteDeprecationWarning`（fastapi/testclient 的 httpx→httpx2 迁移提示）；3 个前端 .mjs 测试（workflow_alignment/workflow_execution_timing/workflow-inspector-layout）未挂进 package.json scripts，只能 `node --test` 手动跑；现有 Playwright 只检查功能和浏览器错误，尚未接入 `@axe-core/playwright` 的 WCAG A/AA 自动检查。

### C 类：低风险观察（仅供参考，不阻塞）

- `web/local_clipboard.py` 66 行手写 Win32 ctypes 剪贴板（pyperclip 可替代，收益小）
- `execution/test_sets.py` 用 dataclass 而非 pydantic，与其他 Repository 不一致（低危）
- `execution/init_db.py:24-26` 引擎/锁缓存按 resolved path 永不释放（生产单库无影响，测试进程累积）
- `execution/sensitive_data.py` redact 是精确子串替换 + Bearer 正则，供应商回显截断/变形 key 时不命中（非实际缺陷）
- SCRIPT 用户脚本契约依赖 `requests`（T13.38.1 已补为显式直接依赖）
- `web/frontend/model-providers.jsx`（123 行）与 `batch-runs.jsx`（27 行）短小是因为长行压缩 + 复用外部包，非缺实现

## 二、开源替换评估结论

**审计时总体判断：T13.38 已完成数据库迁移入口、服务端状态、定时触发和 SSE 交付层替换；执行内核等业务核心继续不换。构建链、前后端接口契约、通用弹窗，以及 SQLAlchemy Core 的实际使用深度存在明确替换收益，执行顺序必须是“先修 A 类真实缺陷，再做 P1 通用基础能力替换”。这些动作现已完成，当前结论见文首“实施结果”。** 以下按候选保留立项时逐项评估。

| 自研组件 | 候选 | 结论 | 关键理由 |
|---|---|---|---|
| DAG 调度器（`workflow_execution.py` `_run`，核心约 120 行） | Prefect / LangGraph / Temporal / Argo | **不换** | Temporal/Argo 强制常驻服务/集群，违反单机约束；Prefect/LangGraph 状态机语义不匹配（无原子 outputs 组提交、无冲突即失败、无 Fail-Fast 杀进程树、无恰好一 START/END）；LangGraph 还会恢复 T13.38.1 已删除的 LangChain 依赖族。 |
| Context 路径/类型转换矩阵（`workflow_values.py` 354 行） | jsonpath-ng / jmespath / jsonata | **不换** | 语义正好相反：本项目「字段缺失=零匹配→null、数组下标越界/对非 array 用下标=必须报错」，JSONPath 全部静默返回空集；jsonata 表达式/函数能力违反「禁止任意代码」安全约束；354 行是规格 3.3/7.3 矩阵唯一实现且已有测试锚定 |
| 模型网关（`model_gateway.py` 609 行） | LiteLLM / OpenAI / Anthropic SDK | **不换** | T13.38 明令不得无验证替换；生产走可取消 subprocess RAW_HTTP，SDK 无法驻留该语义与现有证据格式；`forbidden_fields` 互斥校验与 vendor 扩展透传（`enable_thinking` 等）是差异化能力，SDK 会规范化或拒绝 |
| Repository 数据访问（改造前 6 个 Repository、66 个 `execute/executemany` 调用点） | SQLAlchemy Core 表达式 / JSON 类型；SQLAlchemy ORM | **已完成：深化 Core；不做 ORM 重写** | 改造前通过 `CoreConnection` facade 执行 SQLite 原始 SQL；当前已改为 `select/insert/update/delete`、SQLAlchemy JSON 类型和显式事务，facade 已删除，仅在 `init_db.py` 隔离保留必要的 `BEGIN IMMEDIATE`/PRAGMA。全量 ORM 重写仍无业务收益。 |
| Execution JSON 证据存储（两个 Store 共 1221 行） | SQLite / DuckDB | **不换** | 违反硬约束「Execution Model 只允许存本机 JSON 文件」；人工可读、可 grep、可直接打开的 JSON 证据是测试人员排障核心；正确做法是修 A13（两步替换改整目录原子交换/先写新 batch.json 再换目录） |
| 结果校验 EvaluationRule（`case_evaluator.py` 176 行） | jsonpath-ng / jsonata | **不换** | 与 `workflow_values.resolve_path` 方言一致性（大小写敏感、受限下标、无代码执行）+ 每条规则事实快照契约是根基；jsonpath-ng 有正则 ReDoS 历史问题 |
| 线程模型（Semaphore+ThreadPoolExecutor+Event） | anyio / asyncio | **不换** | 全套执行链是同步/线程模型；`anyio.to_thread` 无法中断线程，「优雅停止先中断 Worker 再等待」取消链在 asyncio 下无等价物；P4/P5 属于边界防护缺失，补超时与 join 集合即可 |
| APScheduler 3.11 集成 | 4.0 预发布 / 自研轮询 | **不换**（参数微调） | T13.38 明文禁止 4.0；自研轮询是旧方案已删除。可微调：`misfire_grace_time` 从 1s 放宽（大 batch 触发占满 worker 时 1 秒窗口会静默丢 ONCE 任务）、把 `prepare_execution` 移出触发路径 |
| Workflow 手写撤销栈（28 行核心）/ 节点表单 / 对齐线 | zundo / react-hook-form / 参考线库 | **Workflow 内不换** | 撤销栈与 ReactFlow 内部 store 同步是硬约束，zundo 要求 zustand 双层 store 冲突；RHF 与 Workflow「每键 onChange→patch 节点 data」直写模式冲突；对齐线是纯函数 + node:test 锚定；dagre 已用于自动布局。此结论不适用于供应商和任务配置等普通提交型表单。 |
| 手写剪贴板 / 进程树终止 | pyperclip / psutil | **暂缓** | 收益小（66/16 行）；psutil 替换后需重验 test_tool_execution.py 12 个取消测试；取消语义（`_EXECUTION_STATES`/`interrupt_tool_run`）是业务硬约束 |
| JSON 序列化 | orjson | **暂缓** | orjson 默认返回 bytes，紧凑格式、异常类型和可选排序行为都需要重验现有 Execution JSON 字节内容与断言；当前写入量以 KB 为主，速度收益不足以覆盖兼容成本。 |
| 管理页提交型表单 | React Hook Form + Zod | **P2 条件采用** | 仅用于供应商、任务创建/编辑和定时设置，统一脏状态、字段级错误与提交校验；不得复制后端全部 Pydantic 规则，也不得用于 Workflow 节点实时画布状态。先以任务配置一页验证代码量和错误定位是否实际下降，再决定扩展。 |
| 前端图级状态管理 | zustand / jotai / XState | **不引入** | START 唯一根、消息交替、节点 Execution 状态与 ReactFlow 内部 store 强耦合；改状态库不能减少业务状态，只会增加同步层。可治理点仍是把 `workflow-canvas.jsx` 的 state/ref 按职责抽成组合式 hook。 |
| 网格 Excel | Univer / Glide Data Grid 替换 FortuneSheet | **维持现状；允许隔离 PoC** | Univer 的 XLSX 导入导出仍属 Pro 能力，不符合免费本机边界。FortuneSheet 1.0.4 当前用于只读、多 Sheet、多区域选取；可用 MIT 的 Glide Data Grid 对“多矩形选择、键盘、暗色主题、超大表格、bundle”做隔离 PoC，但未同时通过这些门禁前不得替换。 |
| 前端构建链 | Vite 多入口 + manifest | **P1 推荐替换** | 4 个构建脚本和手工哈希注入已经形成重复维护点；Vite 可生成共享 chunk、内容哈希和 manifest，FastAPI 只需按 manifest 注入入口资源。必须保持当前页面按需加载、离线启动和静态部署，不引入 Node 常驻服务。 |
| 前后端 API 客户端 | TypeScript + openapi-typescript + openapi-fetch | **P1 推荐替换** | 当前 `window.API`、动态 URL 和响应字段完全靠人工同步。由 FastAPI OpenAPI 生成 `paths` 类型并用轻量 fetch 客户端访问，可在构建期发现字段、路径和请求体漂移；先迁移供应商、任务页面，Workflow 动态结构后迁。 |
| 通用弹窗与确认框 | Radix Dialog / AlertDialog | **P1 推荐替换** | 当前至少 5 套焦点陷阱和 7 个 `aria-modal` 实例分别维护 Esc、Tab 循环、焦点返回和遮罩点击。Radix 为无样式 primitive，可保留现有视觉并统一 WAI-ARIA/键盘行为；先封装项目级 Dialog，再逐页替换。 |
| 管理列表状态 | TanStack Table | **P2 条件采用** | 目前列表只含简单过滤和分页，直接全量迁移收益有限；当排序、列隐藏、批量选择或服务端分页扩展时，再用 headless Table 统一三套列表逻辑并保留现有 DOM/CSS。 |
| SSE 交付 | sse-starlette | **已换完** | 唯一「该换已换」的正面范式：交付层换库、`workflow_node_tests.py` 保留有界队列/会话/keepalive 语义；`EventSourceResponse(ping=15)` 同步生成器自动走线程池不阻塞事件循环 |

### 推荐替换项的独立验收标准

| 顺序 | 替换项 | 独立验收标准 | 回滚边界 |
|---|---|---|---|
| P1-1 | Vite 多入口构建 | 仅保留一份构建配置；manifest 自动生成内容哈希；四个页面仍可按需加载；初始传输和总 bundle 不高于当前；`npm run build` 与全部 Playwright 通过 | 只回滚构建配置和静态资源注入，不修改业务组件 |
| P1-2 | TypeScript + OpenAPI 客户端 | FastAPI OpenAPI 可重复生成；供应商和任务 API 不再手写 DTO/动态路径；`tsc --noEmit` 进入门禁；故意修改后端字段时前端类型检查必须失败 | 保留 API 路由和 payload，不在该步骤改业务协议 |
| P1-3 | Radix Dialog / AlertDialog | 逐个替换后 Esc、Tab/Shift+Tab、初始焦点、关闭焦点返回、遮罩点击和可访问名称通过 Playwright；视觉快照与现有主题一致 | 以项目级 Dialog 包装层为回滚单位，不直接重写页面样式 |
| P1-4 | SQLAlchemy Core 深化 | 已按 Repository 独立迁移并验证；改造前 66 个执行点已归零，`CoreConnection` 已删除；真实数据库副本、唯一约束、事务失败和排序行为不变 | Alembic 版本和 schema 未随查询迁移改变；仅隔离保留必要 PRAGMA/`BEGIN IMMEDIATE` |
| P2-1 | React Hook Form + Zod | 先在任务配置 PoC；代码量、重复校验和无关重渲染至少一项可量化下降；错误必须显示在具体字段旁；创建/编辑/复制 E2E 通过 | 未证明净收益则删除 PoC，不扩展到 Workflow 画布 |
| P2-2 | TanStack Table / Glide Data Grid | Table 只在管理列表能力扩展时采用；Glide PoC 必须同时通过多 Sheet、多矩形选择、Ctrl 叠加、暗色主题、大表性能和 XLSX 导入 E2E | FortuneSheet + SheetJS 适配层保留到 PoC 全部门禁通过 |

## 三、非替换动作的实施状态

1. **已完成**：删除 `execution.js` 原生 Batch 管理死代码约 640 行；历史弹窗、确认框和 API 请求已迁入 React，结果详情桥保留且通过 E2E。
2. **已完成**：Vite 迁移后没有新增 `window.API` 或供应商/任务动态 URL；现存 `viewWorkflows`、`openWorkflowCanvas`、`viewBatchDetail` 是明确兼容边界。
3. **已完成**：全部 `.mjs` 已纳入 `npm run test:frontend`，Playwright 已加入 `@axe-core/playwright` WCAG A/AA 门禁。
4. **已完成**：APScheduler misfire、refresh 并发和 prepare 单一职责按 A15 修复并由调度专项覆盖。
5. **已完成**：WorkflowNode/Inspector 使用 `React.memo`，Workflow 轮询退避至 2 秒，Batch 活动轮询按运行时长退避至 5 秒。
6. **已完成**：模型网关三协议复用统一端点 helper；Repository 通过 SQLAlchemy Core 消除 facade 和 SQL 字符串样板。
7. **已完成**：README、CLAUDE、PLAN 和本报告已按当前五类节点、Vite、OpenAPI 和 SQLAlchemy Core 架构同步。

## 四、后续边界

本轮计划已经收口，没有未完成的 P0/P1/P2 实施项。后续只在真实能力增长时重新评估两项条件候选：管理列表出现列隐藏、批量选择或服务端排序后再评估 TanStack Table；Excel 网格同时满足免费 XLSX、多 Sheet、多矩形选择、Ctrl 叠加、暗色主题和大表性能门禁后再评估 Glide Data Grid。继续维持“执行核心不换”决策，不引入 LangGraph、Prefect、Temporal、Celery、LiteLLM 或供应商 SDK 来迁就通用框架。

## 五、官方调研依据

- Vite 后端集成与构建 manifest：<https://vite.dev/guide/backend-integration.html>
- OpenAPI TypeScript / `openapi-fetch`：<https://openapi-ts.dev/openapi-fetch/>
- Radix Dialog 与可访问性：<https://www.radix-ui.com/primitives/docs/components/dialog>、<https://www.radix-ui.com/primitives/docs/overview/accessibility>
- React Hook Form 与 Zod：<https://react-hook-form.com/>、<https://zod.dev/>
- TanStack Table headless 设计：<https://tanstack.com/table/latest/docs/introduction>
- Playwright + axe 可访问性测试：<https://playwright.dev/docs/accessibility-testing>
- Glide Data Grid 多区域选择：<https://docs.grid.glideapps.com/extended-quickstart-guide/working-with-selections>
- Univer Pro 能力边界：<https://docs.univer.ai/guides/pro>
