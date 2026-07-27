# Workflow Studio 节点内聚与执行协议计划（T13.2）

## T13.27 Dify 式节点拖动对齐参考线（已完成，2026-07-27）

### 业务背景与目标

- Why：T13.21 的多选六按钮方案把低频几何命令常驻在画布工具栏，增加界面密度，也不能在单节点拖动时及时反馈节点是否对齐。
- Who / Where：Workflow 作者在新建或已有 Workflow 画布中拖动任一节点，整理串行、并行和汇聚结构的视觉位置。
- What / Priority：P1 高频编排体验。按用户确认的 `1C / 2A`，删除全部批量对齐入口；参考 Dify，仅在节点拖动时对比其他节点的顶边和左边，严格小于 `5` 个画布像素时显示水平/垂直参考线。参考线不吸附、不改写拖动坐标，松手立即消失。
- How to Measure：旧 `.wf-alignment-actions` 和六个对齐按钮为 0；两轴在阈值内可独立或同时出现，等于或超过 5px 不出现；拖动期间节点坐标不被参考线计算修改；松手标记未保存，撤销/重做和保存回读保持最终坐标；专项、构建、全量与浏览器回归通过。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.27.1 | 参考线几何 | 当前节点集合、拖动节点 / 水平和垂直线段 | Node 运行时单测 | T13.21 | completed |
| 13.27.2 | 拖动生命周期 | React Flow drag start/move/stop / 显示、清理和未保存状态 | 前端专项、生产 DOM | 13.27.1 | completed |
| 13.27.3 | 删除旧方案 | 六个图标、坐标对齐函数和 CSS / 无批量对齐入口 | 源码与生产 DOM 扫描 | 13.27.2 | completed |
| 13.27.4 | 坐标闭环 | 最终 position / undo、redo、数据库 binding、重新打开位置 | 浏览器与 API E2E | 13.27.2 | completed |
| 13.27.5 | 完整回归 | 前端、Python 与生产 bundle | pytest、Node test、build、compileall、语法、diff check | 13.27.1-13.27.4 | completed |

### 验证记录

- 几何单测 `3 passed`：覆盖双轴命中、严格 5px 边界、跨全部对齐节点延展和输入坐标不变；前端专项 `18 passed`。
- 生产画布旧对齐入口为 0。SCRIPT 拖到 START 顶边阈值内时出现 1px 水平参考线，屏幕边界与节点顶边一致；松手后参考线为 0，SCRIPT 保持 `y=42.3361`、START 为 `y=40`，确认未吸附并显示“未保存”。
- 撤销将 SCRIPT `x` 从 `30.4439` 恢复为 `45.6288`，重做精确回到 `30.4439`。保存后的 API binding 为 `position_x=30.443867618429465`、`position_y=347.20311486048024`，关闭再打开后 React Flow 位置为 `translate(30.4439px, 347.203px)`。
- `npm run build`、Python `compileall`、bundle 语法和 `git diff --check` 均成功；全量 `273 passed, 4 skipped, 1 warning`。浏览器控制台 error/warn 为 0，临时 Workflow 已删除，原有 Workflow 未改动。

## T13.26 HTTP 日志 request 直接投影 Execution Model（已完成，2026-07-27）

- Why：HTTP 日志原先把 Node Execution `request` 二次重构为 HTTP/1.1 文本，Headers 为有序数组时甚至会被漏掉，不符合日志只读投影 Execution Model 的顶层约束。
- Who / Where：Workflow 作者在 HTTP 节点日志中展开一次持久化执行或单节点临时测试，并查看/复制 request。
- What / Priority：P0 可追溯准确性。request 展示和复制必须直接使用 Node Execution Model 顶层 `request` 的格式化 JSON，不读取 Structural Model、不重组请求行、不补默认字段。
- How to Measure：页面 request JSON 与 `/runs/{execution_id}/nodes` 返回的对应 `execution.request` 深度一致；Headers、body_type 和 body 完整；复制内容等于显示内容；专项、浏览器和全量回归通过。
- 当前实现：删除 `rawHttpRequest*` 与 `HttpRequestLogSection` 重构链，HTTP 分支复用 `parameterDataText(run.request, true)` 和通用 `HttpLogSection`。
- 验证：前端专项 `18 passed`；真实 HTTP Workflow SUCCESS 后，页面 request 解析对象与 `/runs/{execution_id}/nodes` 中对应 Node Execution `request` 深度一致，完整包含实际 method/url、有序 Headers、body_type/body。页面显示与系统剪贴板均为 542 字符且 SHA-256 同为 `5bc9310a674192ffc61fb5861cc16efcf2bb961ff72255297d49eb3d086ddceb`，控制台 error/warn 为 0。
- 最终回归：`npm run build`、bundle 语法检查通过；全量 `uv run pytest -q` -> `273 passed, 4 skipped, 1 warning`。临时 Workflow 和独立 HTTP 服务均已清理；4 项 skip 为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。

## T13.25 Workflow 初始视口 67% 与全链路契约审计（已完成，2026-07-27）

### 业务背景与目标

- Why：新建或打开复杂 Workflow 时，标准 Fit View 仍占满画布，用户难以同时观察外围拓扑；同时管理模块跨前端、API、SQLite 和本地 Execution JSON，未暴露字段容易在打开保存时静默丢失。
- Who / Where：Workflow 作者首次进入新建/已有画布，以及通过页面打开、保存、运行、删除 Workflow 的完整本机流程。
- What / Priority：P0 数据一致性、P1 画布可视范围。初始视口使用标准 Fit View zoom 的 67%，不缩小节点/文字/面板；逐字段审计 Canvas Model、API DTO、Pydantic、SQLite 和 Execution JSON，并修复确认偏差。
- How to Measure：新建和已有画布实测 `initialZoom / fitZoom = 0.67` 且中心不漂移；非默认 HTTP 隐藏策略和 JSON 类型无编辑保存后不变；删除数据库失败恢复 Execution 目录；Structural Snapshot 与 API/SQLite 完全一致；全量回归通过。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.25.1 | 初始视口 67% | 标准 Fit View / 中心锚定 0.67 zoom | 前端专项、新建/已有浏览器测量 | 无 | completed |
| 13.25.2 | 前端/API/SQLite 字段审计 | 五类节点、Workflow、Edge / 无损往返矩阵 | 源码核对、复杂 HTTP 浏览器保存、SQLite 回读 | 无 | completed |
| 13.25.3 | DB/本地 JSON 一致性 | 删除、运行快照 / 可回滚目录和完整 snapshot | API 故障注入、Execution JSON 对比 | 13.25.2 | completed |
| 13.25.4 | 完整回归与规范 | 所有受影响模块 | build、compileall、pytest、diff check | 13.25.1-13.25.3 | completed |

### 审计发现与修复

- 已修复：HTTP 已有 `success_statuses / retry_non_idempotent / retry_statuses` 原先在前端重存时被硬编码默认值覆盖；现作为隐藏 Canvas 配置原样传递。
- 已修复：HTTP Query/Form 的 number/boolean/null/object/array 原先回显后被强制转为 string；现保留原始 JSON value，只有实际编辑 value 后才采用新文本。
- 已修复：删除 Workflow 原先先删 SQLite 再 `rmtree` Execution 根目录，与规范的可回滚顺序不一致；现先同盘原子暂存目录，数据库失败恢复，提交成功才清理。
- 已修复：更新 Workflow 原先在完整图校验前取消将删除节点的临时测试；现先完成 Structural 图校验，非法保存不产生取消副作用。
- 已修复：Execution JSON 读取已有 Windows 瞬时文件锁重试，但原子 `os.replace` 写入没有重试，偶发导致调度线程退出并留下 RUNNING；现读写均使用最多 6 次、10ms 间隔的有界重试，故障注入和原失败用例连续 10 次通过。
- 核对一致：Workflow 名称/说明、Node ID/type/name/description、START inputs、SCRIPT 代码、LLM 模型/Few-shot/高级参数、HTTP request/network/response/execution、outputs、位置和 Edge 均由前端 DTO 进入严格 API/Pydantic，SQLite 分列+definition_json 回读后无字段缺失。
- 核对一致：Workflow Run 从 SQLite 当前结构生成不可变 `structural_snapshot`，节点完整定义、position 和 Edge 与 API Structural Record 一致；运行状态、Context、Node Execution 只写本地 JSON，不反写 SQLite。

### 当前验证记录

- 专项 `45 passed, 1 warning`；包含非法图更新零取消副作用、Execution 目录删除失败恢复/成功清理、API/SQLite/structural_snapshot 全字段对比。
- 首轮全量回归捕获一次 Windows `os.replace` PermissionError，修复后原子写专项与配置失败组合 `4 passed`，原失败 LLM 用例连续复跑 10 次全部通过。
- 浏览器已有 Workflow：初始 zoom `0.769595`，标准 Fit View `1.14865`，比值 `0.6699996`；新建 Workflow：`0.922801 / 1.37731 = 0.6700024`。节点尺寸和 Inspector 未改变，控制台 error/warn 为 0。
- 复杂 HTTP 无编辑保存回读：Query 保持 `42 / false / null`，Form 保持 object/array/null，成功码保持 `[201,"204-205"]`，非幂等重试保持 true，重试状态保持 `[409,503]`；SQLite definition_json、API 和画布位置/Edge 一致。临时 Workflow 已删除，只保留用户“未命名工作流”。
- 最终验证：`npm run build`、Python compileall、生产 bundle/`execution.js` 语法和 `git diff --check` 通过；修复后全量 `uv run pytest -q` -> `272 passed, 4 skipped, 1 warning`。4 项 skip 为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。

## T13.24 业务节点右键更换类型（已完成，2026-07-27）

### 业务背景与目标

- Why：Workflow 作者选错业务节点类型后只能删除、重新添加并手工恢复连线，复杂图中容易破坏拓扑和位置。
- Who / Where：开发者在画布中右键 `SCRIPT / LLM / HTTP` 节点，通过二级节点选择器更换为另外一种业务节点。
- What / Priority：P1 编辑效率。用户确认 1A/2A/3A：仅三类业务节点互换；保留位置和全部 Edge 但生成新 Node ID；名称、说明和类型配置使用目标默认值，旧日志不继承。START/END 与运行中节点不可更换。
- How to Measure：菜单排除当前类型；更换后 ID 改变、位置和 Edge ID 不变、端点指向新 ID；撤销/重做稳定；保存事务删除旧 Node 并回读目标默认结构；浏览器与完整回归通过。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.24.1 | 右键菜单与原子图替换 | 旧业务节点、目标类型 / 新节点和重定向 Edge | 前端专项、撤销/重做 | 无 | completed |
| 13.24.2 | 保存事务 | 新旧 Node 与原 Edge / 新结构持久化 | Workflow API 与 Repository 回读 | 13.24.1 | completed |
| 13.24.3 | 生产浏览器 E2E | SCRIPT → HTTP | 菜单范围、默认配置、ID/位置/Edge、保存回读、清理 | 13.24.1-13.24.2 | completed |
| 13.24.4 | 完整回归与规范 | 全部受影响模块 | pytest、build、compileall、diff check | 13.24.3 | completed |

### 当前验证记录

- 前端专项 `15 passed`；生产构建成功。右键菜单复用现有 NodePicker，SCRIPT 只列 HTTP/LLM；START/END 不显示更换入口，Workflow 或节点测试运行时入口禁用。
- API 专项 `24 passed, 1 warning`：以新 ID HTTP 替换已保存 SCRIPT 后，旧 Node Structural Model 删除，新 HTTP 使用空白默认结构，两条原 Edge ID 保留且端点指向新 ID。
- 浏览器 E2E：SCRIPT `d427...` 更换为 HTTP `b24a...`，坐标均为 `translate(354px, 40px)`，两条 Edge ID 前后一致；撤销恢复原 SCRIPT/ID，重做恢复新 HTTP/ID。保存回读为 `name=HTTP / description="" / POST / url="" / SYSTEM / AUTO / timeout=600`，控制台 error/warn 为 0；临时 Workflow 删除后 GET 为 404，用户原 Workflow 未修改。
- 节点卡片运行标识同步改为类型元数据：SCRIPT=`Python`、LLM=`Gateway`、HTTP=`HTTP`，避免更换为 HTTP 后仍显示 Python。
- 最终验证：`npm run build`、Python compileall、生产 bundle 与 `execution.js` 语法检查通过；全量 `uv run pytest -q` -> `265 passed, 4 skipped, 1 warning`。4 项 skip 为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。

## T13.23 浏览器标签图标替换（已完成，2026-07-27）

- Why：系统首页显式禁用了 favicon，浏览器启动后只能显示默认地球，无法识别 Agent Bench。
- Who / Where：本机用户启动系统并在浏览器标签页、收藏入口或历史记录中识别 Agent Bench 页面。
- What / Priority：P1 视觉识别。使用用户提供的 100×100 透明纸飞机 PNG 作为唯一 favicon，不修改页面内业务图标。
- How to Measure：首页 `link[rel=icon]` 指向 `/assets/favicon.png`；资源返回 `200 image/png` 且 PNG 签名正确；真实浏览器解析到该绝对地址，控制台 error/warn 为 0。
- 实现与验证：新增 `web/static/assets/favicon.png`，替换原 `data:,` 空 favicon；Web 专项 `4 passed, 1 warning`，全量 `263 passed, 4 skipped, 1 warning`，`npm run build` 与 `git diff --check` 通过。4 项 skip 为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。

## T13.22 节点中断入口收敛与 HTTP Request Options 后端核验（已完成，2026-07-27）

### 业务背景与目标

- Why：Workflow 已明确只能整体中断，但节点卡片、右键菜单和 Inspector 仍暴露单节点中断，容易让用户误判调度语义；HTTP Request Options 虽能保存回读，也必须确认真实执行层使用这些配置。
- Who / Where：Workflow 开发者在画布运行单节点草稿或完整 Workflow，并在 HTTP Inspector 配置 Proxy、Response Body、Redirects 和 SSL Verify。
- What / When：P0 删除全部用户可见节点中断入口，保留关闭编辑器、删除节点/Workflow 和离开 Studio 时的内部 Worker 取消；P0 审计并修正 Request Options 从前端、Structural Model、执行器到 HTTP Worker 的完整传递与行为。
- How to Measure：页面只保留 Workflow 全局中断；单节点运行期间不能重复启动且内部清理仍能终止 Worker；Proxy/SSL/Redirects 正确进入 httpx，Response Body 四种模式真实生效，HTTP 状态码只按 `retry_statuses` 重试；专项、构建、浏览器和完整回归通过。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.22.1 | 收敛节点中断 UI | 节点卡片、右键菜单、Inspector / 仅保留 Workflow 中断 | 前端源码专项、生产 DOM、内部取消回归 | 无 | completed |
| 13.22.2 | 核验 Request Options | UI 配置 / httpx client 与响应事实 | 执行器 payload、Worker 响应模式、重试状态专项 | 无 | completed |
| 13.22.3 | 生产构建与浏览器联调 | 新 bundle / 实际画布交互 | npm build、浏览器节点/顶栏检查 | 13.22.1-13.22.2 | completed |
| 13.22.4 | 完整回归与规范收敛 | 全部受影响模块 | pytest、compileall、diff check、E2E | 13.22.3 | completed |

### 当前核验结果

- Proxy：SYSTEM 保留 httpx 系统环境代理，DIRECT 设置 `trust_env=false`，CUSTOM 设置 `trust_env=false` 并注入经过 URL 编码的用户名/密码；实现正确。
- SSL Verify 与 Redirects：分别传入 httpx Client 的 `verify` 与 `follow_redirects`，且与 Proxy 模式独立；实现正确。
- Response Body：原执行器未把 `response.mode` 传给 Worker，Worker 始终按 AUTO；现已传递并实现 JSON 严格解析、TEXT 严格解码、BINARY Base64 与 AUTO 逐级选择。显式 JSON/TEXT 解析失败使用 `HTTP_RESPONSE_PARSE_ERROR` 且不重试。
- 状态码重试：原执行器保存但未使用 `retry_statuses`，导致所有失败状态码都可重试；现仅连接类失败或命中配置的失败状态码时重试，并继续受 HTTP Method/`retry_non_idempotent` 限制。
- 默认超时：HTTP 与 HTTPS 不区分协议，均使用平台 `timeout_seconds=600` 秒的单次尝试默认值；每次重试重新获得完整单次超时，Worker 外层额外 2 秒只用于进程收敛，不是用户配置超时。
- 第一阶段专项：`uv run pytest tests/test_tool_execution.py tests/test_workflow_execution.py tests/test_workflow_frontend.py -q` -> `53 passed`。
- 生产构建与浏览器：`npm run build`、Python compileall 通过；真实新建草稿中节点卡片、节点右键菜单和 Inspector 的节点中断入口均为 0，顶栏 Workflow 中断为 1，控制台 error/warn 为 0，草稿未保存且未产生数据库记录。
- 最终验证：严格响应解析专项 `40 passed`；`uv run pytest -q` -> `263 passed, 4 skipped, 1 warning`。4 项 skip 为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。

## T13.21 画布多节点对齐与 LLM 上下文降噪（历史实现；节点对齐已由 T13.27 废止，2026-07-27）

### 业务背景与目标

- Why：复杂 Workflow 手工拖拽后缺少批量对齐能力，节点位置难以快速整理；LLM 上下文中重复解释消息顺序的提示占用编辑空间。
- Who / Where：Workflow 开发者在桌面画布中通过 Ctrl 多选或框选多个节点，并在左上浮动工具栏整理布局；LLM 节点作者在 Inspector 中直接编辑消息卡片。
- What / When（历史）：当时按用户确认的 1A/2A，选中至少两个节点后显示六个图标按钮。该批量对齐交互已由 T13.27 全部删除；本节仅保留历史验收事实。LLM 上下文降噪仍是现行行为。
- How to Measure（历史）：当时按选中节点包围盒验证六项坐标对齐；现行节点对齐验收以 T13.27 的拖动参考线为准。LLM Inspector 仍不得渲染两行已删除提示。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.21.1 | 六种节点坐标对齐（历史，T13.27 已删除） | 多选节点与实际尺寸 / 新 position | 前端专项、真实画布几何检查 | 13.16 | superseded |
| 13.21.2 | 浮动工具栏与历史（历史，T13.27 已删除） | 选中数量 / 条件工具组、undo/redo | 多选/单选浏览器交互、撤销检查 | 13.21.1 | superseded |
| 13.21.3 | LLM 上下文降噪 | 说明句、序列提示 / 删除后的消息列表 | 源码/CSS 扫描、生产 Inspector DOM | 13.18 | completed |
| 13.21.4 | 完整回归 | 生产 bundle 与现有 Workflow 功能 | pytest、build、语法、diff check | 13.21.1-13.21.3 | completed |

### 验证记录

- 历史验收：生产画布 Ctrl 多选两个节点后曾出现六个对齐按钮，并逐项通过边界/中心检查；该入口、函数和样式已由 T13.27 删除。
- 历史验收：批量对齐曾接入历史栈与未保存状态；现行拖动参考线的历史与保存闭环见 T13.27。
- LLM Inspector 的上下文区域只保留消息卡片和“添加消息”，说明句、序列提示及 `.wf-llm-context-intro` 样式均已删除；消息结构和运行校验不变。
- 临时验收 Workflow 已删除，浏览器 error/warn 为 0。
- 构建与回归：前端专项 `14 passed`，`npm run build`、`compileall`、bundle/`execution.js` 语法检查和 `git diff --check` 通过；顺序全量回归 `255 passed, 4 skipped, 1 warning`。首次全量运行中既有 LLM Node Execution 轮询用例在 8 秒窗口内未读取到节点而失败，单独复跑通过，随后顺序全量复跑通过；4 项 skip 与 warning 仍为未注入真实供应商环境变量和既有 Starlette/httpx 弃用提示。

## T13.20 Workflow 同名冲突友好化与执行 E2E 回归（已完成，2026-07-27）

### 业务背景与目标

- Why：Workflow 同名保存时旧接口直接暴露 SQLite `UNIQUE constraint`，用户无法快速判断应修改名称；本轮变更完成后还需重点确认单节点、串行与并行图的参数传递和执行正确性。
- Who / Where：Workflow 开发者在新建、完整保存或修改元数据时可能与现有名称冲突；开发者也会通过单节点临时运行和完整 Workflow Run 验证编排结果。
- What / When：名称冲突统一返回 `409` 和“Workflow 名称已存在，请使用其他名称”，不暴露数据库实现；完成后执行单节点、串行、多分支并行汇合三条真实 API 端到端链路。
- How to Measure：页面展示固定友好文案且原记录不受影响；单节点输入输出准确且不创建持久化 Run；串行逐跳 Context 正确；并行分支可同时观测为 RUNNING，JOIN 同时获取两侧输出；所有节点和整图终态为 SUCCESS。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.20.1 | 名称冲突领域化 | SQLite 唯一约束 / `WorkflowNameConflictError` | Repository 专项与事务回滚断言 | 无 | completed |
| 13.20.2 | API 与页面友好提示 | 同名创建、更新、metadata / `409` 文案 | API 专项、生产 API、浏览器保存 | 13.20.1 | completed |
| 13.20.3 | 执行 E2E 回归 | 单节点、串行、并行汇合图 | 真实 `8010` API、SSE、Run/Node Execution 回读 | 13.20.2 | completed |
| 13.20.4 | 权威规范同步 | URL 清理、名称冲突、E2E 验收结果 | `PLAN.md` 与 `WORKFLOW_SPEC.md` 交叉核对、diff check | 13.19-13.20.3 | completed |

### 验证记录

- Repository 将 `workflow_structural_models.name` 唯一约束统一映射为 `WorkflowNameConflictError`；API 创建、完整保存和 metadata 更新均将该领域错误转换为 `409`，其他结构错误继续返回 `400`。
- 生产 API 同名创建返回 `409` 与 `Workflow 名称已存在，请使用其他名称`，保存前后 Workflow 数量保持 `1 -> 1`；生产浏览器保存同名草稿直接显示该文案，不再出现 SQLite 错误原文。
- 单节点临时运行：输入 `{"value":"  transfer  "}`，输出 `{"result":"TRANSFER-OK"}`，`attempt_count=1`、状态 SUCCESS，持久化 Run 数量为 0。
- 串行图 `START -> A -> B -> END`：A 输出 `ALPHA:3`，B 输入包含 `step_a=ALPHA:3`，最终 Context 为 `seed=alpha / count=3 / step_a=ALPHA:3 / serial_result=ALPHA:3:SERIAL`，全部节点 SUCCESS。
- 并行汇合图 `START -> LEFT/RIGHT -> JOIN -> END`：实际观察 LEFT 与 RIGHT 同时 RUNNING；JOIN 输入包含 `left_value=fanout-L` 与 `right_value=fanout-R`，输出 `joined=fanout-L|fanout-R`，最终 Context 与全部节点状态正确。
- 三份 E2E Workflow 删除均返回 `200`；用户原有 Workflow ID 保留，新增 ID 残留为空，执行目录随 Workflow 删除清理。
- 完整回归：`uv run pytest -q` -> `254 passed, 4 skipped, 1 warning`；`compileall`、生产 bundle 与 `execution.js` 语法检查、`npm run build`、`git diff --check` 全部通过。4 项 skip 为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 规范同步：`WORKFLOW_SPEC.md` 已明确 HTTP Endpoint 的失焦、序列化和后端三级 trim 契约，以及 `WorkflowNameConflictError -> HTTP 409` 的保存错误映射；当前实施状态同步为 Structural/Execution/API/画布均已落地。规范只维护中文权威正文，已删除重复的 `Implementation Decisions (Rapid Iteration)` 英文摘要。

## T13.19 HTTP Endpoint 首尾空白自动清理（已完成，2026-07-27）

### 业务背景与目标

- Why：用户从文档、终端或调试工具复制 Endpoint 时容易携带不可见的首尾空白，旧行为会在保存阶段把本可修复的输入判为非法 URL。
- Who / Where：Workflow 开发者在生产 Workflow Studio 的 HTTP 节点 Endpoint 输入框中录入 URL；API 客户端也可能直接提交 HTTP Structural Model。
- What / When：用户确认采用方案 A；Endpoint 失焦时立即删除首尾空白，Workflow 保存序列化和后端结构校验前再次兜底清理。只处理 Endpoint URL，不修改 URL 中间字符，也不扩展到 Proxy URL。
- How to Measure：带空格 URL 失焦后输入框显示清理值；保存回读只包含清理后的 URL；直接调用 API 也获得相同结果；内部空白仍按无效 URL 拒绝。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.19.1 | 前端即时清理与保存兜底 | Endpoint 输入值 / `request.url` | 前端专项、生产构建、浏览器失焦检查 | 13.16 | completed |
| 13.19.2 | 后端统一规范化 | API `request.url` / Structural Model URL | 结构模型专项、API 保存回读 | 13.19.1 | completed |
| 13.19.3 | 完整回归 | UI 输入、保存、API 回读与现有流程 | 浏览器 E2E、全量 pytest、静态检查 | 13.19.1-13.19.2 | completed |

### 验证记录

- 生产浏览器输入 `   https://example.com/path?q=a%20b   `，失焦后输入值变为 `https://example.com/path?q=a%20b`；保存成功后 API 回读完全一致，浏览器 error/warn 为 0。
- 临时验收 Workflow `HTTP URL Trim 联调` 已删除；用户原有“未命名工作流”及其 ID 保持不变。
- 前端专项 `13 passed`，结构模型专项 `38 passed`，Workflow API 专项 `23 passed, 1 warning`；`npm run build` 通过。

## T13.18 LLM Few-shot 生产接入与前后端联调（已完成，2026-07-27）

### 业务背景与目标

- Why：LLM 节点需要从单一系统/用户提示词升级为可表达多轮示例的有序消息上下文，让 Workflow 作者能直接配置 Few-shot 请求，而不再把示例塞进一段长文本。
- Who / Where：Workflow 开发者在生产 Workflow Studio 的 LLM 节点设置页选择模型、编辑上下文消息、高级参数、运行配置和输出变量；完整运行与单节点临时测试都必须使用同一份 Structural Model。
- What / When：P0 不兼容删除旧 `prompt.system / prompt.user`，生产协议统一为 `context.messages[]`；P0 顶层约束为 LLM 草稿即使模型、消息或高级参数 JSON 未完成也可以保存，只有运行按钮和执行到节点时要求模型有效、上下文完整、参数 JSON 合法。
- How to Measure：保存/回读 LLM 节点时保留 `context.messages[]` 与 `generation.parameters_text`；运行前端按钮只在模型有效、消息最终为非空 USER、非 SYSTEM 消息非空且高级参数 JSON 合法时可用；后端执行请求按 `SYSTEM -> USER -> (ASSISTANT -> USER)...` 解析并发送，Anthropic 将非空 SYSTEM 拆到 `system`；非法参数草稿运行时不发起模型请求且 `attempt_count=0`。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.18.1 | 审计旧 prompt 残留 | `PLAN.md`、高保真原型、后端模型、执行器、前端适配器 | `rg` 扫描确认残留集中在执行器、`execution.js` 和生产 Inspector | 13.17 | completed |
| 13.18.2 | 后端协议与执行改造 | `context.messages[]`、`generation.parameters_text` | 结构模型、API、执行专项测试；OpenAI/Anthropic 请求体断言 | 13.18.1 | completed |
| 13.18.3 | 生产画布接入高保真交互 | 消息列表、折叠上下文、追加/删除、运行校验 | 前端静态专项、生产构建、bundle 语法检查 | 13.18.2 | completed |
| 13.18.4 | 联调与回归 | 保存/回读、单节点测试、完整运行、非法参数草稿 | 专项组合、全量 pytest、compileall、diff check、构建 | 13.18.2-13.18.3 | completed |
| 13.18.5 | 收敛 LLM 分区视觉层级 | 删除草稿期上下文整条警告；上下文与高级参数复用同级标题 | 前端专项、构建、生产浏览器计算样式与折叠交互 | 13.18.3 | completed |

### 验证记录

- 后端 Structural Model 增加 `generation.parameters_text` 用于保存高级参数编辑器草稿文本，允许暂存非法 JSON；执行前若非空则以该文本解析为 JSON object，解析失败使用 `LLM_CONFIGURATION_INCOMPLETE`，`missing_fields=["generation.parameters_text"]`，不发起模型请求且 `attempt_count=0`。
- 执行器已删除旧 `node.prompt` 读取路径，改为按 `context.messages[]` 顺序解析 `${变量}`；空 SYSTEM 在最终请求中省略，非 SYSTEM 解析后为空使用 `LLM_MESSAGE_EMPTY`；OpenAI 类请求发送完整小写消息序列，Anthropic 请求把 SYSTEM 写入 `system` 并发送 USER/ASSISTANT 消息序列。
- 生产 Inspector 已用消息列表替换系统/用户提示词两个文本框，支持默认 `SYSTEM -> USER`、追加 `ASSISTANT -> USER`、只从末尾删除、上下文折叠、角色提示和字符数。保存按钮不再因 LLM 模型、消息或参数草稿阻塞；运行按钮仍要求模型有效、上下文完整且参数 JSON 合法。
- 2026-07-27 视觉收敛：删除上下文底部“当前草稿可以保存”整条警告；“上下文”和“高级参数”复用同一分区、标题按钮与折叠箭头样式。生产浏览器计算样式核对两者均为 `990x38`、透明背景、无边框、零内边距，旧警告节点数量为 0；高级参数展开后 JSON 编辑器唯一可见。
- 构建与静态检查：`npm run build` 无 warning；`uv run python -m compileall -q execution web tests storage`、`node --check web/static/execution.js`、`node --check web/static/assets/workflow-canvas.js`、`git diff --check` 均通过。
- 专项回归：`uv run pytest tests/test_node_structural_models.py tests/test_workflow_execution.py tests/test_workflow_api.py tests/test_workflow_frontend.py -q` -> `93 passed, 1 warning`。全量回归：`uv run pytest -q` -> `251 passed, 4 skipped, 1 warning`。4 项为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 首次把专项与全量 pytest 并行运行时触发 Windows `.pytest_tmp` 文件锁和既有 atomic replace 竞态；随后单独复跑受影响并行调度用例通过，专项组合与全量回归按顺序均通过。

## T13.17 LLM 上下文与 Few-shot 高保真原型（已完成，2026-07-27）

### 业务背景与目标

- Why：现有 LLM 节点只有独立的系统提示词和用户提示词，无法直观表达多轮示例，Workflow 作者需要用接近 Dify 的消息序列编辑方式构建 Few-shot 上下文。
- Who / Where：Workflow 开发者在 LLM 节点设置页选择模型后，按消息顺序编辑真实请求上下文；默认只处理 SYSTEM 与 USER，复杂任务再按需追加示例消息。
- What / When：本阶段仅交付独立、可交互的桌面端高保真原型，不修改 Structural Model、Execution Model、API、生产画布或数据库；用户确认后再进入不兼容协议改造。
- How to Measure：默认准确显示 SYSTEM、USER；上下文默认展开且可整体折叠/恢复；每次点击“添加消息”自动交替追加 ASSISTANT、USER；仅允许删除新增消息且删除后仍保持合法序列；可以编辑长文本和 `${变量名}`；空 SYSTEM 规则通过角色旁 `?` 提示，最后 USER 为空显示执行校验提示；页面无重叠、裁切和横向溢出，浏览器控制台无错误。

### 高保真参考位置（后续生产改造必须参考）

- 浏览地址：`http://127.0.0.1:8010/assets/llm-context-prototype.html`（需先通过 `uv run python run.py` 启动本机服务，默认端口 8010）。
- 原型源码：`prototypes/llm-context-settings/index.jsx` 与 `prototypes/llm-context-settings/prototype.css`；后续修改交互或视觉时以这两个文件为权威来源。
- 静态入口：`web/static/assets/llm-context-prototype.html`。
- 构建产物：`web/static/assets/llm-context-prototype.js`、`web/static/assets/llm-context-prototype.css` 和 `web/static/assets/llm-context-prototype.js.LEGAL.txt`；构建产物不得作为后续手工修改源。
- 原型构建命令：`npx esbuild prototypes/llm-context-settings/index.jsx --bundle --format=iife --platform=browser --target=es2020 --minify --legal-comments=linked --outfile=web/static/assets/llm-context-prototype.js`。
- 生产落地入口：确认实施后，将原型交互迁移到 `web/frontend/workflow-canvas.jsx` 与 `web/frontend/workflow-canvas.css`，并同步修改 LLM Structural Model、Execution Model、API 数据映射和测试；不得只复制静态构建产物或只替换 UI。
- 当前状态：该地址是独立高保真，不读写 Workflow、Provider、Execution JSON 或数据库；生产 LLM 节点仍使用旧 `prompt.system / prompt.user`，不得把原型完成误记为生产协议已完成。

### 已确认边界

- 后续生产数据方向采用有序 `context.messages[]`，删除旧 `prompt.system / prompt.user`，不保留兼容层；本阶段只在原型中演示，不落地协议。
- 默认消息固定为 `SYSTEM -> USER`；“添加消息”每次追加一条，角色按 `ASSISTANT -> USER` 自动交替。角色不可手动修改，消息不可拖动排序。
- “上下文”使用默认展开的折叠区块；标题行显示当前消息数量，折叠只改变可见性，不清空或重排消息。
- SYSTEM 的“可为空；执行时自动省略空 SYSTEM”和 USER 的“最终一条 USER 是模型本次需要回答的内容”仅通过角色标题右侧的 `?` 提示展示，不在消息框下重复占用空间。
- 消息标题行进一步固定为“左侧角色名 + `?`，右侧字符数 + 可选 `×`”；删除序号、Few-shot 标签、中文角色说明、变量引用计数和消息框底部整行。默认 SYSTEM/首条 USER 不显示 `×`，新增消息仅在自身位于末尾时允许通过 `×` 删除。校验错误使用卡片错误边框和上下文级错误提示，不恢复消息框底部行。
- 允许保存空草稿；SYSTEM 为空时执行请求省略该消息。最终 USER 必填，新增消息需要满足既定顺序及内容完整性，问题在执行到节点时以友好错误提示，不静默忽略空消息。
- Few-shot 示例由一个或多个 `ASSISTANT + USER` 片段构成；默认 SYSTEM 和首条 USER 不允许删除，新增消息提供删除操作。
- 模型配置、高级参数、公共运行配置和输出变量继续保留；原型重点验证上下文区域，不改变这些模块的业务含义。

### 子任务与验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 13.17.1 | 冻结上下文原型规则 | 用户选择 1A/2B/3A；形成原型交互契约 | 对照默认顺序、追加、删除、空值和执行提示逐项审阅 | 无 | completed |
| 13.17.2 | 实现独立高保真 | 新增 `/assets/llm-context-prototype.html` 及独立样式/脚本 | 静态资源 200、脚本语法检查、按钮和字段可交互 | 13.17.1 | completed |
| 13.17.3 | 桌面浏览器验收 | 真实页面截图与交互结果 | 检查角色交替、删除约束、空值提示、滚动、溢出和控制台 | 13.17.2 | completed |

### 验证记录

- 交付 `/assets/llm-context-prototype.html` 独立页面；源码位于 `prototypes/llm-context-settings/`，使用 React 与既有 `lucide-react` 图标，不读取或写入 Workflow、Provider、Execution JSON 或数据库。
- 默认角色序列实测为 `SYSTEM -> USER`；连续点击“添加消息”后依次得到 `ASSISTANT -> USER`，按钮同步提示下一条角色。默认消息锁定；只有末尾新增消息允许删除，中间新增消息的删除按钮禁用；从末尾连续删除后恢复默认序列。
- 上下文默认展开，标题显示消息数量；折叠后消息编辑区完全隐藏，重新展开后两条默认消息及其文本完整保留。折叠不影响高级参数和后续运行配置区块。
- 角色说明已收敛到标题右侧的 `?` 悬停提示；标题左侧仅显示角色与 `?`，右侧显示实时字符数及新增消息的可选 `×`。消息框底部整行已删除；校验失败通过卡片错误边框和上下文级友好提示展示。
- 空 Few-shot USER 场景下，“保存草稿”正常提示已保存；点击运行时只标记一条错误消息，并显示“当前草稿可以保存，但需补全标记的消息后才能运行”，验证保存与执行校验边界分离。
- 桌面浏览器实测 Inspector 宽约 1064px；页面、Inspector 内容区和消息列表横向溢出均为 0。消息标题左侧仅保留角色与 `?`，右侧为实时字符数和新增消息的可选 `×`；序号、Few-shot 标签、中文角色说明、变量计数及消息框底部行均不存在。角色边色、锁定/删除状态、长文本编辑和运行配置无重叠或裁切；浏览器控制台 error/warn 为 0。
- 静态与回归：原型 bundle `node --check`、生产 `npm run build`、Python `compileall` 和 `git diff --check` 通过；Workflow 前端专项 `11 passed`；全量 `242 passed, 4 skipped, 1 warning`。4 项为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 当前边界：本任务只确认高保真交互，不代表 `context.messages[]` 已进入 Structural Model、Execution Model、API 或生产画布；用户确认原型后再执行不兼容协议改造。

## T13.16 HTTP 高保真生产接入与节点公共格式统一（已完成，2026-07-27）

### 业务目标与验收边界

- Why：独立 HTTP 原型已经完成桌面视觉与交互确认，下一步必须接入真实 Workflow Studio，解决生产 HTTP 节点仍使用旧 `API / HEADERS / PARAMS / BODY / NETWORK` 平铺布局的问题；同时防止各节点的公共运行配置、字段间距、紧凑枚举和区块分隔继续分叉。
- Who / Where：Workflow 开发者在生产画布中编辑并临时测试 HTTP、LLM、SCRIPT、START 和 END 节点；HTTP 请求配置需要高频增删键值、切换 Body/网络选项并保存回读，其他节点需要稳定一致的公共字段与运行配置。
- What / Priority：P0 接入已确认的 HTTP 请求设置布局且不改变 Structural/Execution Model；P1 审计并修复所有节点的公共格式偏差，不重做节点专属业务界面。独立原型保留为设计基准，生产接入完成前不删除。
- How to Measure：真实 HTTP 节点完整保存、关闭和重开后字段不丢失；Headers/Params/Body/Request Options 折叠及增删正常；一级区块只有一条全宽分隔线；公共字段间距为 10px，紧凑枚举为 96px；SCRIPT/LLM/HTTP 运行配置结构一致；构建、专项测试、真实浏览器流程和全量回归通过。

### 子任务与验证门禁

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 13.16.1 | 审计生产节点与数据映射 | 原型、生产 Inspector、httpConfig；差异与字段映射清单 | 源码/CSS/Structural Model 交叉扫描 | 无 | completed |
| 13.16.2 | 接入生产 HTTP 请求设置 | 既有 httpConfig；新三段式生产 UI | 前端构建、静态测试、浏览器保存/重开 | 13.16.1 | completed |
| 13.16.3 | 统一其他节点公共格式 | 10px 间距、96px 紧凑枚举、单分隔线、公共运行配置 | SCRIPT/LLM/START/END/HTTP 浏览器逐节点扫描 | 13.16.2 | completed |
| 13.16.4 | 完整回归 | 生产 bundle、API、Execution 和桌面业务流 | pytest、compileall、npm build、浏览器 E2E、SQLite/端口检查 | 13.16.2-13.16.3 | completed |

### 13.16.1 审计记录

- HTTP 生产字段完整覆盖原型，不新增也不迁移协议：`method / url / headers / params / bodyType / bodyText / bodyFields / proxyMode / proxyUrl / proxyUsername / proxyPassword / followRedirects / verifySsl / responseBodyType` 可原位复用，cURL 导入继续写入同一 `httpConfig`。
- 生产 HTTP 当前仍为旧版 `API / HEADERS / PARAMS / BODY / NETWORK` 平铺结构；Headers/Params 表头常驻，Body/Network 不可按原型折叠，Redirects/SSL Verify 使用普通 checkbox，属于 P0 生产视觉与交互差距。
- SCRIPT、LLM、HTTP 已共享唯一 `.wf-config-section` 运行配置实现，后续不得复制 HTTP 专属运行配置；START 只展示输入，END 无业务配置，继续遵守节点语义边界。
- 公共格式偏差：基础字段与运行字段已是 10px，但 HTTP Endpoint 为 9px、Request Options 为 4-8px；START/输出类型下拉为自适应宽度；LLM/HTTP 专属区与运行配置存在各自边框和间距规则。13.16.3 统一这些公共视觉约束，但模型选择器等内容型控件继续自适应。
- 节点 Inspector 固定为白色工作面，因此其中所有原生下拉框必须显式使用 `color-scheme: light`、白色背景、深色文字和浅灰边框；不得跟随全局暗色主题变成黑底。该规则统一覆盖 HTTP Request Options、START 类型和所有节点输出类型。
- 生产构建必须同时为 `workflow-canvas.js` 与负责 Structural Model 转换的 `execution.js` 写入内容哈希查询参数；两者任一继续使用旧缓存都会造成 UI 与数据适配器版本错配。浏览器回读验收必须使用两个最新哈希，不能依赖手工强制刷新。

### 13.16.2 验证记录

- 生产 Inspector 已将旧 `API / HEADERS / PARAMS / BODY / NETWORK` 替换为已确认的“请求设置 / Endpoint / Headers / Params / Body / Request Options”结构；Headers、Params 和 Body 键值区使用深色表头并支持增删，Body/Request Options 可独立折叠，Redirects/SSL Verify 使用无表格容器开关。
- 所有生产字段继续写入既有 `httpConfig`，后端 Structural Model 无变更。真实 Workflow 保存并重载后回读：Method `PUT`、URL、Params `scope=production`、Raw Body、Proxy `CUSTOM` 及 URL/认证、Response Body `JSON`、SSL Verify `false`、输出 `http_result / response.body / object` 均正确。
- 浏览器实测 Method/Proxy/Response Body 均为 96px，字段间距均为 10px；Request Options 底边为 0、运行配置顶边为唯一 1px `#dfe5ed` 分隔；页面、Inspector、请求区和输出变量行横向溢出均为 0。
- 暗色主题下曾发现原生 Proxy/Response Body 下拉跟随系统变成黑底；现统一声明 `color-scheme: light` 并显式白底深色字。计算样式为背景 `rgb(255,255,255)`、文字 `rgb(23,32,51)`，START/输出类型共用该规则。
- 首次回读曾因 `/execution.js` 无版本号命中旧缓存，表现为 Structural Model 已保存 CUSTOM 但旧适配器显示 SYSTEM；构建现同时写入 workflow bundle 与 execution.js 的 12 位内容哈希。新增静态断言后专项 `34 passed, 1 warning`。

### 13.16.3 验证记录

- 公共变量固化为 `--wf-control-gap: 10px / --wf-compact-select-width: 96px / --wf-section-divider: #dfe5ed`；基础字段、运行字段、START 类型、节点输出类型、HTTP 紧凑枚举和单节点测试类型均复用，模型选择器继续按内容自适应。
- START：类型下拉 96px、标签间距 10px、白底 light color-scheme、横向溢出 0；按节点语义不显示运行配置。SCRIPT：Python 编辑器保留，运行字段间距 10px、输出类型 96px/10px、横向溢出 0。
- LLM：模型选择器实测自适应宽 892px；模型配置底边为 0，运行配置顶边为唯一 1px `#dfe5ed` 且两区连续；运行字段 10px、输出类型 96px/10px、横向溢出 0。END：只显示名称/说明，基本字段间距 10px，无 select、无运行配置、横向溢出 0。
- HTTP：输出类型 96px/10px、白底 light color-scheme、横向溢出 0；与生产请求设置的公共规则一致。旧 `.wf-http-api-section / .wf-http-kv-* / .wf-http-network-*` 死样式已删除，避免重新覆盖新结构。
- 新增静态回归锁定生产 HTTP 组件、禁止旧 API/NETWORK 标题和死选择器，并断言公共变量、LLM/HTTP 单分隔、输出/测试类型宽度及双 bundle 哈希。组合专项最终 `36 passed, 1 warning`；首次运行中既有 Workflow 执行用例瞬时 FAILED，单独复跑通过，第二次组合全通过，保留已知 Windows 文件持久化竞态风险。

### 13.16.4 完整验证记录

- 静态与构建：`npm run build`、`node --check web/static/execution.js`、Workflow bundle `node --check`、`uv run python -m compileall -q execution web tests storage` 和 `git diff --check` 全部通过；`index.html` 同时携带两个最新 12 位内容哈希。
- 全量回归：`uv run pytest -q` -> `242 passed, 4 skipped, 1 warning in 21.17s`。4 项为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 生产浏览器 E2E：真实 HTTP Structural Model 完成全字段保存/重开，五类节点公共格式逐一实测；暗色主题下所有 Inspector 原生下拉白底深色字；页面、Inspector 和相关配置行横向溢出均为 0；最终控制台 error/warn 为 0。
- 数据与环境：`run_storage/agent_bench.sqlite3` 的 `integrity_check=ok / foreign_key_check=[]`，只包含 Structural Model 与既有 Provider/Target 表；验收 Workflow `HTTP生产布局验收-20260727` 已定点删除且无 Execution 目录。用户当前“未命名工作流”保留；只监听 `127.0.0.1:8010` 一个项目端口。

## T13.15 HTTP 节点设置界面高保真重设计（原型阶段）

### 业务背景与目标

- Workflow 作者需要像使用 Postman/Apifox 一样快速完成 Endpoint、Headers、Params 和 Body 配置，同时只在需要时展开代理、响应解析和传输选项。
- 当前 HTTP 设置把键值列头、Body 类型和 Network 字段平铺在同一层级，重复标签占用空间，代理与布尔选项扫描路径不清晰；本阶段先交付独立高保真原型，用户确认后才替换生产前端。

### 已确认原型边界

- 文案改为 `Endpoint / Headers / Params / Body / Request Options`；`Redirects / SSL Verify` 使用开关。
- Endpoint 不使用图标或独立标题行，固定放在 Method 左侧并与 Headers、Params、Body、Request Options 标题左对齐；名称和说明均使用左侧标签、右侧输入框的横向布局。
- 紧凑枚举下拉框建立后续全局公共规格：固定为 96px 宽，正常使用 10-11px 字号和清晰下拉箭头，完整容纳 `OPTIONS / SYSTEM / CUSTOM / integer / boolean` 等已知最长值；模型名称等内容型选择器使用自适应宽度，不强行套用紧凑枚举宽度。
- 所有字段标题到对应输入框或下拉框的间距统一为 10px；本阶段先在 HTTP 高保真原型验证，用户确认替换生产前端时作为所有节点的公共样式约定复用。
- Headers、Params 使用折叠面板；面板展开后才显示顶层 `key / value` 表头，并支持逐行新增和删除。
- Body 与 Headers、Params 一样使用折叠面板，标题行显示当前 Body 类型；展开后四种类型拉开间距，`form-data` 与 `x-www-form-urlencoded` 复用相同键值表格，`raw` 使用 JSON 编辑区，`none` 显示空态。
- Request Options 使用折叠面板，重新组织 Proxy、Response Body、Redirects 与 SSL Verify；CUSTOM Proxy 的 URL、用户名和密码按条件展示。Redirects 与 SSL Verify 是独立布尔设置，使用无外框、无表格底色、无中间分隔线的自然宽度水平开关组。
- HTTP 专属 Request Options 之后必须完整保留所有业务节点共有的运行配置：单次超时、最大重试次数、重试间隔和延迟执行，单位继续为秒；输出变量同样保留，不属于 HTTP 重设计的删除范围。
- 名称/说明之后新增一级“请求设置”分组，视觉规格与“运行配置”一致；Endpoint、Headers、Params、Body、Request Options 全部作为请求设置的子标题，不再直接与运行配置并列。
- 设置页固定分为基础信息、请求设置、运行配置三个一级区块；基础信息区不显示额外标题，直接展示名称和说明，请求设置与运行配置保留独立标题行；区块之间使用完整分隔线，字段不得跨区。
- 一级区块之间只允许一条全宽 `1px` 分隔线：由后一区块的顶边绘制。请求设置最后一个 Request Options 不绘制底边，避免与运行配置顶边形成两条平行线；该格式与基础信息到请求设置的分隔完全一致。
- HTTP 原型的公共运行配置不得单独设计：直接参考 SCRIPT/LLM 的现有公共组件，使用 Settings2 图标、白底区块、两列超时与重试面板，以及标签式输出变量行；HTTP 重设计只作用于请求设置。
- 超时与重试严格复用 LLM 公共字段布局：两列网格内每项使用 `64px 标签 + 10px 间距 + 自适应输入框`，标题不得放在输入框上方；Request Options 的 Proxy/Response Body 标签按文字实际宽度占位，与固定 96px 紧凑枚举下拉框保持 10px 间距。
- 公共输出变量继续使用 LLM 的变量名/提取表达式/类型/操作结构；类型属于紧凑枚举，下拉框固定为 96px，字段标签到控件保持 10px。
- “请求设置”使用与 HTTP 节点一致的 Globe 图标；Request Options 作为普通子标题不显示独立图标，与 Headers、Params、Body 保持同级。
- 原型不读取/写入 Workflow，不调用保存或运行 API，不替换现有 HTTP 节点；只用于桌面端视觉与交互确认。

### 子任务与验证

1. **现有界面与业务层级基线**（已完成，2026-07-27）
   - 现状：编辑器约 `640×896`，HTTP 主网格为 `70px / 96px / minmax(180px, 1fr) / 34px`；Headers/Params 列头常驻，Body 类型间距为 14px，Network 使用无层级的双列字段平铺。
   - 设计结论：保留现有编辑器壳、字体密度和蓝色焦点体系，将请求主路径保持展开，把集合字段与高级传输选项改为按需折叠。
2. **独立可交互高保真原型**（已完成，2026-07-27）
   - 交付：`/assets/http-node-prototype.html` 独立页面；源文件位于 `prototypes/http-node-settings/`，使用 React 与项目既有 lucide-react 图标构建，不接入生产 Workflow 状态。
   - HTTP 专属区：Endpoint、Headers、Params、Body、Request Options 全部按确认层级实现；Headers/Params/Body 表格支持新增和删除，raw 提供 JSON 编辑器与 Beautify，CUSTOM Proxy 条件显示 URL/Username/Password。
   - 公共区：保留“运行配置 / 超时与重试”的单次超时、最大重试次数、重试间隔、延迟执行四项，并保留可展开的输出变量配置；默认值为 600/0/0/0。
   - 交互验证：Params 新增后出现第三行、删除后恢复两行；Body 在 form-data 与 raw 之间正确切换；CUSTOM Proxy 三项条件字段出现；Redirects 和 SSL Verify 均可切换。
3. **桌面视觉、交互和溢出验收**（已完成，2026-07-27）
   - 视口：1440×1000；编辑器为 760×900，页面与编辑器横向溢出均为 0，键值表格、开关区、Body 折叠标题和四列运行配置内部溢出均为 0。
   - Body：标题行显示当前 `form-data` 模式；收起后四种类型和内容完全隐藏，重新展开后模式与两条 Body 数据保持不变。
   - 标签布局：名称与说明均为左侧标签、右侧输入框；Endpoint 取消图标和独立标题行，放在 Method 左侧。浏览器计算 Endpoint、Headers、Params、Body 标题起点均为 365px。
   - 分组层级：设置页固定为基础信息、请求设置、运行配置三个连续一级区块，区块宽度均为 748px；基础信息不显示额外标题，请求设置和运行配置标题行均为 44px，后两个区块使用完整全宽分隔线。名称/说明只属于基础信息区，Endpoint、Headers、Params、Body、Request Options 只属于请求设置，超时重试和输出变量只属于运行配置。
   - 分隔线回归：Request Options 末项底边为 0，运行配置顶边为唯一的全宽 1px 分隔线；基础信息→请求设置与请求设置→运行配置均使用相同 `#dfe5ed` 样式，不出现双线或重复留白。
   - 公共配置统一：运行配置为白底公共区，超时与重试计算列宽为 `328px / 328px`，输出变量使用标签式配置行且横向溢出为 0；请求设置使用一个 HTTP Globe 图标，Request Options 不存在前置图标。
   - 横向字段：所有字段标题到输入框/下拉框统一为 10px；Method、Proxy、Response Body 和输出类型等紧凑枚举下拉框统一为 96px。验收必须同时检查真实文字呈现、标题/控件重叠与页面溢出。
   - 类型列回归：输出类型标签与下拉框间距为 10px，下拉框固定为 96px；行、面板和页面横向溢出均为 0。
   - Method 与表头：Method 固定为 96px，Endpoint 到 Method 间距为 10px；表头背景为 `rgb(232, 237, 244)`、文字为 `rgb(51, 65, 88)`，数据行保持白底。
   - Method 展开层：自定义 listbox 的按钮和菜单均固定为 96px，七个选项保持居中；选择后同步值并关闭，Escape 和点击外部均能关闭。最长 `OPTIONS` 必须以浏览器实测确认可读性。
   - 公共尺寸实测：Method、Proxy、Response Body 和输出类型均为 96px；基础信息、Endpoint、Request Options、运行配置和输出类型的标题到控件距离均为 10px。`OPTIONS / SYSTEM / AUTO / string` 内容溢出为 0，Method 文字与箭头不重叠，页面及输出变量行横向溢出均为 0。
   - 视觉：Headers、Params、Body、Request Options 使用统一折叠层级；Body 四种模式间距为 30px，最长 `x-www-form-urlencoded` 完整显示；Redirects/SSL Verify 使用无表格容器的自然宽度水平开关组；运行配置与输出变量作为公共区块独立保留。
   - 浏览器：折叠、增删、Body 切换、CUSTOM Proxy 条件字段和开关均通过；控制台 error/warn 为 0；原型页面返回 HTTP 200。
   - 构建与回归：原型 bundle `node --check`、生产 `npm run build` 和 `git diff --check` 均通过；前端专项 `13 passed, 1 warning`；本轮完整回归 `240 passed, 4 skipped, 1 warning`。4 项为未注入供应商环境变量的 live 用例，warning 为既有 Starlette/httpx 弃用提示。
   - 预览：首屏、Method 展开菜单和 Request Options/运行配置区域截图保存在 `prototypes/http-node-settings/preview-top.png`、`preview-method-menu.png` 与 `preview-options.png`。

## T13.14 LLM 输出 Python 整数下标兼容（已完成）

### 业务背景与目标

- Workflow 作者无法预知模型供应商返回的 `choices` 数量，需要使用 `response.choices[-1].message.content` 稳定读取最后一条回复。
- 输出表达式必须遵循受限且可预测的 Python 整数下标语义，避免有效负下标被误判为对象字段，也避免切片或任意表达式进入执行器。

### 已确认边界与验收标准

- 支持正负十进制整数下标，例如 `[0]`、`[1]`、`[-1]` 和 `[-2]`；`[-1]` 必须返回数组最后一项。
- 空数组或正负下标越界时不返回 `null`，而是使输出提取失败；LLM 使用 `LLM_OUTPUT_SOURCE_EVALUATION_ERROR`。
- 不支持切片、算术表达式或任意 Python 执行，例如 `[1:]`、`[::2]` 和 `[1+1]` 必须拒绝。
- 类型转换失败继续使用 `LLM_OUTPUT_TYPE_MISMATCH`，不得与 source 语法、下标或求值错误混淆。

### 子任务与验证

1. **共享输出解析器整数下标语义**（已完成，2026-07-27）
   - 输出：解析器支持 Python 正负整数下标；空数组及正负越界显式失败；方括号键只接受整数、标识符或 JSON 双引号字段名，切片和表达式明确拒绝。
   - 验证：`uv run pytest tests/test_workflow_values.py -q` -> `29 passed`；覆盖用户原始表达式、多条 choices、正负越界、切片和算术表达式。
2. **LLM/HTTP source 与 type 错误码分类**（已完成，2026-07-27）
   - 输出：共享层使用独立的 source 求值异常与 outputs.type 转换异常；LLM/HTTP 执行器分别映射到 `*_OUTPUT_SOURCE_EVALUATION_ERROR` 和 `*_OUTPUT_TYPE_MISMATCH`。
   - 真实流程验证：本地 OpenAI-compatible 服务返回完整 `choices`；`[-1]` 成功提取，`[-2]` 越界使用 source 错误码，对象转 integer 使用 type 错误码。两种失败均保留完整 response、最终 attempt 为 SUCCESS、节点为 FAILED、outputs 为空且只调用一次供应商。
   - 验证：`uv run pytest tests/test_workflow_values.py tests/test_workflow_execution.py -q` -> `48 passed`。
3. **规范同步、构建与完整回归**（已完成，2026-07-27）
   - 规范：LLM/HTTP 均明确正负整数下标、越界失败以及不支持切片/表达式；对象字段或过滤器零匹配仍保持 null。
   - 回归修复：首次全量回归暴露既有全局中断竞争窗口。取消可能发生在节点检查中断之后、Worker 注册之前；`_ExecutionController.add_worker()` 现会在注册 Worker 的同一临界区读取取消状态，并利用 Worker 运行时的预取消机制阻止迟到进程启动。
   - 定向验证：Worker 注册前取消、真实 SCRIPT 全局中断及输出专项合计 `51 passed`。
   - 受影响回归：Workflow API、Structural Model、Execution Model 和输出解析共 `111 passed, 1 warning`。
   - 完整回归：`uv run pytest -q` -> `240 passed, 4 skipped, 1 warning`；4 项为未注入供应商环境变量的 live 用例，warning 为既有 Starlette/httpx 弃用提示。
   - 静态与构建：Python `compileall`、`npm run build`、Workflow bundle `node --check` 和 `git diff --check` 全部通过。
   - 端到端价值验证：本机真实 HTTP Server 分别模拟 OpenAI-compatible 模型响应和 HTTP 节点响应；LLM `response.choices[-1].message.content` 从完整 response 提取最后一条并提交 Context，越界与类型不匹配均保留供应商原始 response、只调用一次且按稳定错误码 Fail-Fast。
   - 本机服务：停止修改前启动且无热重载的旧进程后，当前代码已重新启动在唯一端口 `http://127.0.0.1:8010/`；`GET /api/workflows` 返回 HTTP 200，用户既有 Workflow 正常回读。
   - 未覆盖与风险：本轮未使用真实公网模型凭据，供应商 live 用例保持跳过；负整数下标属于平台本地 response 求值，不依赖供应商协议，因此已由完整真实 HTTP Body 端到端覆盖。切片和任意 Python 表达式按确认边界明确不支持。

## T13.11 Workflow 创建元数据与顶部说明（已完成）

### 业务背景与目标

- Workflow 作者需要在进入画布前明确名称和整体说明，并在编排过程中持续看到这两项元数据。
- 说明只描述整个 Workflow，不承担画布分区注释职责，因此不引入说明节点、连线、复制粘贴或 DAG 特例。

### 已确认边界

- 点击“新增工作流”先打开名称/说明弹窗；名称必填且最长 120 字符，说明可空且最长 2000 字符。
- 画布顶部左侧显示名称，中间显示单行说明摘要，右侧保留运行、全局变量、中断和保存操作。
- 名称和说明均为展示态，双击后进入编辑；名称使用单行输入，说明使用轻量多行浮层。
- 名称按 Enter 或失焦、说明失焦时，通过独立元数据接口立即持久化；该接口不接收或改写节点、连线和全局变量，也不触发完整 DAG 校验。
- 暗色主题下 Workflow 顶栏仍固定使用浅色控件；名称悬停和说明编辑器不得继承全局深色输入背景，也不显示原生黑色提示框。

### 验收与验证（2026-07-23）

- API 专项覆盖名称/说明规范化、空名称拒绝、缺失 Workflow、图数据保持不变，以及不完整图仍可独立更新元数据。
- 浏览器 E2E 覆盖新增弹窗、名称必填、创建后自动落库、名称双击编辑、说明双击编辑、失焦保存及刷新后列表回读；临时 Workflow 已删除。
- 暗色主题真实页面计算样式：说明编辑器与 textarea 背景均为 `rgb(255, 255, 255)`，文字为 `rgb(23, 32, 51)`，`color-scheme` 为 `light`；名称悬停不再出现黑色背景或原生黑色提示框。
- 浏览器控制台错误和警告均为 0；前端构建、Python 编译、JavaScript 语法检查和 `git diff --check` 均通过；受影响回归为 `102 passed, 1 warning`，全量回归为 `222 passed, 6 skipped, 1 warning`。

> 状态：T13.1 前端高保真原型和回归已完成；T13.2 Step 11 已完成验收并推送到 GitHub。按最新业务决策，工具管理/工具模板体系及所有画布耦合已彻底删除，工具节点完全在 Workflow 中定义；LLM 节点已接入模型管理引用、任意 JSON 高级参数和框架无关的 OpenAI-compatible 网关内核。新版 Workflow 持久化与 DAG 真实执行 API 仍尚待单独确认和实现。
>
> 更新时间：2026-07-23
>
> 范围：新版全屏 Workflow Studio 和新的工具模板体系。旧固定 Workflow、旧 Run 页面/API/执行链以及当前 Script / Agent 工具协议将被删除，不提供兼容迁移。
>
> 事实来源优先级：用户最新确认 > 本计划的“已确认决策” > `docs/enterprise-agent-test-orchestration.md` 中的既有规则。未列为“已确认”的内容不得直接实现。

## T13.10 LLM 日志 Token 与模型行布局（已完成）

### 业务背景与目标

- Workflow 作者需要在不展开日志详情的情况下比较单次 LLM 调用成本，同时快速扫描时间、状态、耗时和最终结果概览。
- LLM 设置页需要把模型选择与流式开关放在同一视觉层级，减少纵向占用并明确流式模式属于当前模型调用配置。

### 已确认边界

- 仅 LLM 日志摘要行新增 Token 列，顺序固定为“时间 / 状态 / 耗时 / Token / 概览”；HTTP、AGENT、SCRIPT 保持原五列布局。
- Token 优先读取 `usage.total_tokens`；缺失时依次兼容 OpenAI 的 `prompt_tokens + completion_tokens` 和 Anthropic 的 `input_tokens + output_tokens`。无 usage、失败、中断以及不解析 usage 的流式响应统一显示 `-- tokens`。
- Token 列固定为 `112px`，概览继续使用剩余宽度并在过长时省略，动态内容不得推动时间、状态和耗时列。
- LLM 设置页使用同一行两列布局：左侧为模型字段，右侧为“流式输出 + 开关”；开关固定 `34x19`，系统提示词从下一行开始。流式执行、usage 持久化和输出变量规则不变。

### 验收与验证（2026-07-23）

- 真实持久化日志：复用本机 Workflow“HTTP GET 9000 验证”的 DeepSeek LLM 记录，4 条摘要依次显示 `-- tokens / 166 tokens / -- tokens / 162 tokens`，未发起新的供应商调用，也未保存或修改 Workflow。
- 日志布局：真实成功行计算网格为 `18px 130px 66px 80px 112px 562px`；Token 位于耗时和概览之间，日志面板及页面横向溢出均为 0，浏览器控制台错误为 0。
- 设置布局：1440x900 下模型选择器和流式开关处于同一行，间距 `24px`；开关为 `34x19`，两者垂直中心偏差为 0，设置面板和页面横向溢出均为 0。
- 构建与回归：`npm run build`、Python `compileall`、Workflow bundle `node --check` 和 `git diff --check` 均通过；`uv run pytest tests/test_execution_frontend.py tests/test_llm_node_runs.py tests/test_model_gateway.py -q` 结果 `25 passed, 1 warning`；全量 `uv run pytest -q` 结果 `221 passed, 6 skipped, 1 warning`。6 项跳过为未注入真实供应商环境变量的 live 用例，warning 为既有 Starlette/httpx 弃用提示。

## T13.6 HTTP 节点界面与日志收敛（已完成）

### 业务目标与场景

- Workflow 编排人员通过系统 HTTP 执行器配置并运行标准请求，不需要在 HTTP 节点中查看或维护 Python 代码。
- HTTP 节点用于对接 FastAPI 或真实企业 Agent 环境；排查调用问题时只关注实际发出的请求和收到的响应，不在日志详情中混入执行器 stdout、stderr、traceback 或其他运行元信息。

### 已确认边界

- HTTP 节点配置页只保留“设置 / 日志”两个页签，删除 HTTP 的“代码 / 参数”页签；AGENT、LLM、SCRIPT 的页签规则不受影响。
- “设置”继续承载 Method、URL、Headers、Params、Body、运行配置和输出变量；本次不删除 HTTP 请求本身的 Query Params，也不改变输出变量提取协议。
- 日志列表摘要继续显示状态、运行时间和耗时；展开详情只显示“原始请求 / 原始响应”。底层运行记录和变量提取所需数据继续持久化，不因界面收敛而丢失。
- 原始请求和原始响应保持原有深色原始文本块样式，每个模块标题右侧各提供一个整段复制按钮；不拆成 JSON 字段表，也不提供逐字段复制按钮。
- 原始日志文本显式允许鼠标选中。存在浏览器文本选区时，原生 `Ctrl+C` 优先于画布节点复制；没有文本选区时继续执行既有节点复制。
- HTTP 原始请求采用 Postman 式可读布局，分为请求行、Headers、Params 和 Body。RAW Body 是合法 JSON 字符串时解析并缩进显示，不再把 JSON 作为字符串二次转义；非 JSON Body 保持原文。
- “复制原始请求”复制 Postman 式格式化文本，而不是持久化层的 JSON 包装文本；实际发出的请求、持久化记录和输出变量提取仍使用原始结构，不受展示格式影响。
- HTTP 仍由标准 HTTP 执行器执行，不支持或恢复 HTTP Python 代码模式。
- 新建 HTTP 节点的 Headers 默认包含可编辑、可删除的 `Content-Type: application/json`。该默认值只在创建节点时写入；已有节点、cURL 导入结果和用户手工删除后保存的空 Headers 均不自动补回。

### 子任务与验证

1. **HTTP 编辑器页签收敛**（已完成，2026-07-22）
   - 输出：HTTP 只显示“设置 / 日志”。
   - 验证结果：`uv run pytest tests/test_execution_frontend.py -q` -> `8 passed, 1 warning`。
2. **HTTP 日志详情收敛**（已完成，2026-07-22）
   - 输出：HTTP 展开详情只渲染原始请求和原始响应。
   - 验证结果：`uv run pytest tests/test_execution_frontend.py tests/test_workflow_node_runs.py -q` -> `18 passed, 1 warning`；成功、非 2xx 和配置失败的既有执行记录行为均通过。
3. **真实 GET 端到端验收**（已完成，2026-07-22）
   - 在桌面画布保存并运行 `GET http://127.0.0.1:9000/chat/1`，节点状态为 `SUCCESS`，响应 HTTP 200，返回订单 `ORD-20260722-0001`。
   - 展开日志确认页签仅为“设置 / 日志”，详情标题恰好为“原始请求 / 原始响应”，请求 Method 和 URL 正确；页面横向溢出为 0，浏览器控制台错误为 0。
   - 验收 Workflow 名称为“HTTP GET 9000 验证”，保留在本机数据库供人工查看。
4. **完整回归**（已完成，2026-07-22）
   - `npm run build`、`uv run python -m compileall -q execution web tests` 和 `git diff --check` 均成功。
   - `uv run pytest -q` -> `219 passed, 6 skipped, 1 warning`；6 项为未注入真实供应商凭据的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
5. **HTTP 日志复制**（已完成，2026-07-22）
   - 输出：原始请求和原始响应各一个模块复制按钮；原始文本可由用户鼠标选中后执行原生 `Ctrl+C`；恢复原有文本块视觉，不保留试验性的逐字段表格。
   - 专项验证：`uv run pytest tests/test_execution_frontend.py tests/test_workflow_node_runs.py -q` -> `19 passed, 1 warning`；`npm run build` 成功。
   - 浏览器验证：两个模块复制按钮均唯一，复制内容分别保留完整请求和响应；页面显示仍只有原始请求和原始响应两个模块。
   - 未覆盖：内置浏览器自动化无法合成原生文本拖选，未自动读取鼠标选区；已验证日志块计算样式为 `user-select: text`，且键盘和 copy 事件在存在文本选区时不会触发节点复制。需要人工鼠标拖选完成最终体验确认。
6. **HTTP 请求 Postman 分区展示**（历史完成，已被第 10 项替代）
   - 输出：请求行、Headers、Params、Body 分区；JSON RAW Body 解析为格式化 JSON；模块按钮复制格式化后的可读请求。
   - 真实历史记录验证：复用既有 `POST http://127.0.0.1:9000/admin/users` 运行记录，页面显示 `POST`、Headers、空 Params 和 `BODY · RAW`；Body 为缩进后的 `{"username": "users"}`，不存在 `\"`。
   - 复制验证：剪贴板首行为 `POST http://127.0.0.1:9000/admin/users`，包含 Headers、Params、Body 三段及可读 JSON，不包含转义引号。
   - 页面横向溢出为 0，浏览器控制台错误为 0；专项 `19 passed, 1 warning`，最终全量 `219 passed, 6 skipped, 1 warning`。
7. **新建节点默认 JSON Header 与 API Mock 全面验证**（已完成，2026-07-22）
   - 输出：`defaultHttpConfig()` 新建 Headers 为 `Content-Type: application/json`，源码契约纳入 `tests/test_execution_frontend.py`；cURL 导入和已有节点加载路径不变。
   - Mock 基线：确认 PID `28208` 监听 `127.0.0.1:9000`，按 OpenAPI 真实执行 18 个请求，覆盖 GET/POST/PUT/PATCH/DELETE、Query、JSON Body、Bearer Header、401/422、业务 `code=404` 和慢响应，全部符合 Mock 契约。
   - 节点 API：通过 `127.0.0.1:8010` 创建临时 Workflow 并执行 14 个 HTTP 节点场景，覆盖 `${变量名}` 在 URL/Header/Params/Body 中替换、输出变量提取、原始错误响应、连接失败、空 URL、慢响应和中断；结果全部符合预期，临时 Workflow 已删除。
   - 根因对照：同一 `POST /orders` RAW JSON 带默认 Header 时 HTTP 200、节点 `SUCCESS`；删除 Header 后 FastAPI 将 Body 识别为字符串并返回 HTTP 422、节点 `FAILED`。
   - 浏览器 E2E：新建节点默认项可编辑；真实 POST 日志按请求行、Headers、Params、格式化 Body 展示且两个模块复制正确；删除默认项并保存、退出、重新打开后 Headers 仍为空，未自动回填；验收临时 Workflow 已删除。
   - 最终回归：HTTP/前端专项 `19 passed, 1 warning`；`npm run build`、Python `compileall`、Workflow bundle 语法检查和 `git diff --check` 均成功；全量 `219 passed, 6 skipped, 1 warning`。
   - 未覆盖与已知缺口：当前 API Mock 的 `/upload` 仍声明 JSON Body，不能作为 form-data、x-www-form-urlencoded 或 binary 成功链路；`retryCount / retryInterval / delayExecution / repeatExecution` 当前只由前端保存，节点执行后端尚未消费，本阶段不擅自补定义执行语义。
8. **设置字段与 HTTP 日志标题可见性**（已完成，2026-07-23）
   - 业务目标：节点编辑器固定为白色设置面板；无论全局亮暗主题，名称、说明、模型、HTTP、运行配置和输出变量等所有字段标题都必须清晰可见。
   - 修复：设置页章节标题、标签页、字段名、HTTP key/value、Body 类型、折叠项及输出变量标签统一使用 `--wf-heading: #111827`；删除暗色主题将该变量覆盖为浅色的规则，避免白底白字。
   - 日志：HTTP “原始请求 / 原始响应”标题统一为 `12px / 700`，正文和深色日志内容区保持原样。
   - 浏览器 E2E：在 `data-theme=dark` 且编辑器背景 `rgb(255, 255, 255)` 的真实页面中，HTTP、LLM、重试和输出变量字段计算颜色均为 `rgb(17, 24, 39)`；两个日志标题均为 `12px / 700`，页面及面板横向溢出为 0，控制台错误为 0。
   - 回归：主题与前端专项 `13 passed, 1 warning`；`npm run build`、Python `compileall`、Workflow bundle 语法检查和 `git diff --check` 均成功；全量 `220 passed, 6 skipped, 1 warning`。
9. **HTTP 原始日志正文放大 30%**（已完成，2026-07-23）
   - 范围：只放大原始请求与原始响应正文；日志列表摘要和“原始请求 / 原始响应”标题保持原字号。
   - 字号：请求 Method `14px -> 18.2px`，URL、键值、Body 和响应正文 `13px -> 16.9px`，Headers/Params/Body 分组标签 `9px -> 11.7px`，均为精确 1.3 倍。
   - 布局：Method 列宽由 `58px` 扩为 `76px`，避免 DELETE 等较长方法名放大后挤压 URL；日志内容区继续独立滚动。
   - 浏览器 E2E：真实 HTTP 日志计算字号与上述值一致；主标题仍为 `12px`、列表摘要仍为 `10px`，页面及编辑器横向溢出为 0，控制台错误为 0。
   - 回归：主题与前端专项 `13 passed, 1 warning`；`npm run build`、Python `compileall`、Workflow bundle 语法检查和 `git diff --check` 均成功；全量 `220 passed, 6 skipped, 1 warning`。
   - 历史变化：第 10 项曾把请求改为单一 `pre` 文本块；该 HTTP/1.1 重构格式已由 T13.26 废止，当前 `pre` 直接展示 Execution Model request JSON。
10. **Postman 式完整 HTTP 原始请求**（历史实现，已由 T13.26 废止）
   - 当前规则：本项只保留 2026-07-23 的历史验收事实，不代表现行产品行为。当前 HTTP 日志 request 必须直接格式化 Node Execution Model 顶层 `request` JSON，不再生成请求行或报文文本。
   - 历史格式：单一原始文本块按“请求行、已记录 Headers、空行、原始 Body”排列；请求行为 `METHOD URL HTTP/1.1`，Query Params 使用 `URLSearchParams` 合并进 URL。
   - 历史数据处理：只展示运行记录中实际保存的 Headers，不伪造未持久化的 Host、User-Agent、Accept 或 Content-Length；RAW Body 保持原字符串且不进行 JSON 美化，表单 Body 按 URL 编码文本展示。
   - 历史交互：删除 Postman 的 Headers/Params/Body 分区组件和对应 CSS；原始请求与原始响应使用相同日志容器、`16.9px` 正文和可选择文本；“复制原始请求”复制与页面相同的报文文本。
   - 历史浏览器 E2E：真实 `POST /orders?source=raw+log` 展示请求行、两条 Header、空行和紧凑 JSON Body，不包含旧分区标签；Windows 剪贴板与页面内容一致，仅按系统规范使用 CRLF，页面横向溢出为 0，控制台错误为 0；临时 Workflow 已删除。
   - 历史回归：主题、前端及节点运行专项 `24 passed, 1 warning`；`npm run build`、Python `compileall` 和 `git diff --check` 均成功；全量 `220 passed, 6 skipped, 1 warning`。
11. **RAW JSON 请求体字段提取**（已完成，2026-07-23）
   - 业务目标：Workflow 编排人员可用 `request.body.username` 提取 HTTP RAW JSON 请求体字段，供下游节点引用，不需要把整个请求体当作字符串再次处理。
   - 数据契约：真实发送请求和运行日志继续保留变量替换后的 RAW 原字符串；仅输出变量提取上下文在 RAW Body 为合法 JSON 时使用 `json.loads` 解析。非 JSON RAW Body 保持字符串，不做隐式转换。
   - 端到端验证：节点向本地 HTTP 服务发送包含 `username / password / email / question` 的多行 RAW JSON；服务收到的原文和 `request_body.body` 与编辑内容逐字符一致，`request.body.username` 成功提取为 `test`，响应字段提取同时通过。
   - 真实页面复核：首次修复后 `8010` 仍由 2026-07-22 23:34 启动且不带 `--reload` 的旧 Uvicorn 进程提供服务，因此用户节点继续得到旧错误；重启到当前代码后，既有 `POST /register` 节点连续两次运行均为 HTTP 200 / `SUCCESS`，输出变量 `abc` 为 `test`，原始请求日志仍保存字符串。历史 `FAILED` 记录按追溯要求保留。
   - 回归：变量解析与节点运行专项 `69 passed, 1 warning`；`npm run build`、Python `compileall` 和 `git diff --check` 均成功；全量 `220 passed, 6 skipped, 1 warning`。
12. **游离节点可用变量解耦**（已完成，2026-07-23）
   - 业务目标：可用变量面板只负责展示全局变量、当前节点可见的上游输出和当前节点自身输出，不因 Workflow 尚未连线完成而拒绝加载。
   - 边界：变量面板同步草稿时使用与单节点运行相同的 `for_node_run` 不完整图模式；保存按钮和整图运行继续执行游离节点与循环依赖校验，不放宽图规则。
   - API 验证：创建无任何连线的 HTTP 节点并真实运行后，变量 API 返回 `全局变量 / 游离 HTTP` 两组，当前节点的 `username = test` 可用；既有正常连线 LLM 用例继续覆盖上游节点输出展示。
   - 浏览器 E2E：在用户既有单节点 Workflow 中打开游离 HTTP 节点变量面板，页面显示当前节点 `abc = test`，不再显示 `Workflow 存在游离节点: HTTP`，顶栏保持“已保存”，控制台错误为 0。
   - 回归：Workflow、LLM、节点运行和前端专项 `47 passed, 1 warning`；`npm run build`、Python `compileall`、Workflow bundle 语法和 `git diff --check` 均成功；全量 `221 passed, 6 skipped, 1 warning`。

## T13.3 Script 顶层变量输出（已完成）

### 业务目标与场景

- Workflow 编排人员在 Script 节点中直接编写普通 Python 顶层变量，不再为了向下游传值额外构造 `response`。
- `print()`、stdout、stderr 和 traceback 始终属于原始运行日志，不参与业务变量提取；用户继续依据真实日志定位代码错误。
- 一个 Script 可以配置多个输出，每行将一个 Python 顶层变量映射成供后续节点使用的 `${变量名}`，并可设置不同的对外名称和目标类型。

### 已确认数据契约

```text
Python 顶层变量 --输出映射--> 对外变量名 --${变量名}--> 后续节点
```

- Script 输出配置只包含：对外变量名、Python 顶层变量名、类型。
- Script 不再支持从 `request` 或 `response` 路径提取输出变量，不提供旧配置兼容。
- Python 变量不存在、变量无法 JSON 序列化或类型转换失败时，节点状态为 `FAILED`，stdout/stderr 和具体错误原因必须完整保留。
- 不同节点可以声明同名对外变量。当前节点引用变量时，唯一距离最近的上游来源覆盖更远来源。
- 两个或更多等距上游节点声明同名变量时结果存在歧义，保存和执行均应明确报错，不按画布位置或完成时间随机选择。
- 全局变量与节点输出同名时仍属于不同层级冲突；本子任务不擅自定义覆盖关系，继续沿用现有校验规则。
- HTTP、LLM、Agent 的 `request / response` 原始对象和路径提取规则不变。

### 子任务与逐步验证

1. **数据契约与图距离解析**（已完成，2026-07-22）
   - 输入：Workflow 节点、边、全局变量和输出映射。
   - 输出：Script 映射规范；唯一最近上游解析；等距歧义错误。
   - 验证结果：`uv run pytest tests/test_workflow_variables.py tests/test_workflow_drafts.py -q` -> `75 passed, 1 warning`。warning 为既有 Starlette/httpx 弃用提示。
2. **Script Worker 顶层变量采集**（已完成，2026-07-22）
   - 输入：Script 代码、`inputs`、`config`、配置的 Python 变量名。
   - 输出：只返回已声明顶层变量的 JSON 快照；缺失或不可序列化时返回真实 traceback。
   - 验证结果：`uv run pytest tests/test_tool_execution.py tests/test_workflow_node_runs.py -q` -> `17 passed, 1 warning`。覆盖多变量、别名、缺失变量、不可序列化、类型转换失败、原始日志、超时与中断。
3. **Script 节点编辑 UI**（已完成，2026-07-22）
   - 输入：Script 节点 `outputVariables`。
   - 输出：对外变量名、Python 变量、类型三列；移除 Script 的提取表达式；默认代码不再构造 `response`。
   - 验证结果：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py -q` -> `8 passed, 1 warning`。桌面浏览器交互合并到子任务 4 E2E。
4. **完整工作流回归**（已完成，2026-07-22）
   - 输入：包含多变量、别名、同名远近覆盖和等距冲突的实际 DAG。
   - 输出：后续节点可通过 `${变量名}` 使用确定值；失败/日志/中断行为不回归。
   - API 验证：三段 Script 串行 DAG 使用同名 `message`，节点数组顺序被刻意打乱；下游仍稳定取得唯一最近上游值。等距分支同名变量在保存时明确报错。
   - 浏览器 E2E：在 `http://127.0.0.1:8010/` 新建 Workflow，打开 Script 节点，确认“变量名 / Python 变量 / 类型”三列和默认 `msg` 代码；配置 `message <- msg / STRING` 后单节点运行状态为 `SUCCESS`，变量面板显示 `message = 介绍一下自己`，展开日志同时显示原始 stdout 和原始变量快照。临时 Workflow 已删除。
   - 历史草稿验证：旧 Script `response` 映射可以被列表和详情读取以供人工修正，但保存和执行均按新协议拒绝，不继续提供旧提取兼容。
   - 最终回归：`uv run pytest -q` -> `214 passed, 6 skipped, 1 warning`；6 项为未注入真实模型凭据的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
   - 静态与构建：`uv run python -m compileall -q execution web tests` 成功；`npm run build` 成功。

### T13.3 验收结论

- 简单 Script 只需声明普通顶层变量并在输出区映射一次，无需构造 `response`。
- 支持一个节点映射多个变量、同名或别名输出及严格类型转换。
- 缺失变量、不可序列化值和类型转换失败均使节点 `FAILED`，同时保留原始 stdout、stderr、变量快照和 traceback。
- 后续节点继续使用 `${变量名}`；重名来源按唯一最近上游解析，等距歧义不会产生随机结果。
- HTTP、LLM、Agent 的既有 `request / response` 路径提取未改变。

## T13.4 Script 原始控制台与可选输出（已完成）

### 业务背景与目标

- Script 作者以 PyCharm 等 Python IDE 的控制台为心智模型，需要按真实发生顺序查看 `print()`、stderr、Python traceback 和系统警告，而不是在日志页阅读经过 JSON 解析或字段拆分的内容。
- 日志只负责复现执行过程，不参与变量提取；节点间传参继续使用 T13.3 的 Python 顶层变量映射。
- 条件分支没有生成某个已配置输出时，不应把已经正常完成的脚本误判为失败。

### 已确认规则

- Script 日志显示单一原始控制台，不解析 JSON、不从日志提取字段、不把请求或变量快照混入控制台正文。
- 底层继续分别保存 stdout、stderr；同时按接收顺序保存合并后的 `console`，用于还原控制台。
- 配置的 Python 顶层变量不存在时，该对外变量输出 `null`，控制台追加明确 `[WARNING]`，节点保持 `SUCCESS`。
- 真实 Python 异常、超时、进程中断、不可序列化值和已配置类型转换失败仍按既有规则处理；本阶段不擅自放宽。
- HTTP、LLM、Agent 日志布局和 `request / response` 提取不变。

## T13.5 Script 普通 Python 兼容性（已完成）

### 业务背景与缺陷

- 用户需要将在 PyCharm 中可执行的普通非交互 Python 代码直接放入 Script，包括常见的 `response = requests.get(...)` 写法。
- 当前通用 Worker 仍为 Agent 兼容保留顶层 `response`，并在 Script 完成后强制序列化它；当 `response` 是 `requests.Response` 等普通 Python 对象时，业务代码本身成功却被平台错误判为失败。
- 历史 Workflow 仍可能保存 `response.stdout` 等旧 Script 提取配置。当前新协议在保存前拒绝这些记录，导致新代码根本没有写入和运行，页面只能看到旧失败日志。

### 已确认目标与验收

- Script 中 `response` 与其他变量名完全等价，不具备平台保留语义；只有 Agent 继续使用顶层 `response` 作为结构化结果。
- Script 只序列化明确配置的 Python 输出变量，不扫描或序列化其他局部/全局对象。
- 历史 Script 输出行缺少 `pythonVariable` 时，自动以对外变量名作为可选 Python 变量来源；不存在则按 T13.4 输出 `null` 和警告，不阻止保存或执行。
- 真实验收使用用户代码访问 `http://127.0.0.1:9000/chat/1`：HTTP 200、JSON 正常打印、节点 `SUCCESS`，且 `requests.Response` 不触发序列化错误。
- 交互式 stdin、桌面 GUI、未安装依赖和超出 Worker 进程权限的代码不属于“PyCharm 可执行即平台必然可执行”的承诺范围。

## T13.9 全节点原始日志视觉契约（已完成）

### 业务背景与目标

- Workflow 编排人员需要在 HTTP、AGENT、LLM、SCRIPT 节点中用同一种控制台视觉阅读真实请求、响应、stdout、stderr 和 traceback，避免切换节点类型后字体大小、行距和背景发生跳变。
- Script 原始控制台是本阶段的基准；日志只展示和复制真实原文，不改变底层日志结构、变量提取、最近 10 次记录或错误语义。

### Script 基准契约

- 适用范围：节点日志页中展开后的原始日志正文；不包含历史摘要行、模块标题、Provider 元信息、状态色、复制按钮和 Python 编辑器。
- 字体：`Consolas, "SFMono-Regular", monospace`。
- 字号：`14.3px`。
- 行高：`1.6`。
- 背景：纯黑 `#000000`。
- 正文：浅色 `#e3e8ef`。
- 交互：保留原始换行、独立滚动、鼠标选区、原生 `Ctrl+C` 和整段复制；不得解析或重组日志正文。
- 优先级：本节是四类节点原始日志正文的最新统一约定，覆盖 T13.6 第 9-10 项和 T13.8 中不同节点使用独立正文字号的历史记录。

### 四类节点扫描结果（2026-07-23）

| 节点 | 当前渲染 | 字体/背景 | 与 Script 契约差异 |
|---|---|---|---|
| SCRIPT | 只读控制台 `textarea` | Consolas / 14.3px / 1.6 / `#000000` / `#e3e8ef` | 基准，已符合 |
| HTTP | 原始请求、原始响应 `pre` | Consolas / 16.9px / 1.55 / `#000000` / `#dbe6f5` | 字号、行高、正文色不同 |
| LLM | 原始请求、stdout、response、stderr、traceback `pre` | Consolas / 16.9px / 1.55 / `#000000` / `#dbe6f5` | 字号、行高、正文色不同 |
| AGENT | 与 LLM 共用原始日志 `pre` | Consolas / 16.9px / 1.55 / `#000000` / `#dbe6f5` | 字号、行高、正文色不同 |

### 子任务与验收

1. **契约与差异扫描**（已完成，2026-07-23）
   - 输出：上述 Script 基准、适用边界和四类节点差异矩阵。
2. **共享样式改造**（已完成，2026-07-23）
   - 输出：`.wf-inspector` 定义 `--wf-raw-log-*` 字体、字号、行高、背景和正文色变量；Script `textarea` 与 HTTP/AGENT/LLM `pre` 共同引用。
   - 结果：四类节点统一为 Consolas / 14.3px / 1.6 / `#000000` / `#e3e8ef`，历史摘要、模块标题、状态色和复制交互不变。
   - 验证：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py tests/test_workflow_node_runs.py -q` -> `20 passed, 1 warning`。
3. **浏览器与完整回归**（已完成，2026-07-23）
   - SCRIPT 与 LLM 的浏览器计算样式均为 `rgb(0, 0, 0)` 背景、`rgb(227, 232, 239)` 正文、Consolas 字体、14.3px 字号和 22.88px 行高。
   - HTTP 真实原始请求/响应以及临时 AGENT 的请求、stdout、response、stderr 均显示同一黑底控制台；历史摘要继续使用浅色背景，长内容保留独立滚动。
   - 临时 AGENT Workflow `3e1fd08557b446b793d80faa9cc0700c` 执行 `SUCCESS` 后已删除，列表恢复为 2 个原有 Workflow。
   - 最终回归：`uv run pytest -q` -> `220 passed, 6 skipped, 1 warning`；6 项为未注入真实模型凭据的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
   - `npm run build`、`uv run python -m compileall -q execution web tests` 和 `git diff --check` 均成功。

## T13.8 Workflow Studio 字体与节点编辑器视觉调整（已完成）

### 已确认边界

- 最新决策：Script / Agent 的 Python CodeMirror 编辑器与日志统一使用 `Consolas, "SFMono-Regular", monospace`；Workflow Studio、节点设置和其他页面保持各自默认字体。
- 已下载的 Droid 字体资产继续保留但不应用到界面，避免改变本任务之外的静态资源状态。
- 只有展开后的原始日志内容使用纯黑背景，日志历史摘要行继续使用浅色背景。
- Python 编辑器可视高度由 360px 增加 50% 至 540px。
- 节点设置页中的节点名、页签、字段标签和配置分组标题使用深黑色；状态、错误和操作按钮保留语义色。

### 子任务与验证

1. **本地字体资产与作用域**（已完成，2026-07-23，最终不启用 Droid）
   - 引入 `DroidSansMonoSlashed.ttf`、OFL 1.1 文本和来源/哈希记录；字体通过 `/assets/fonts/` 由本机服务提供。
   - esbuild 将 `/assets/*` 保持为运行时静态 URL；`npm run build` 成功。
   - `uv run pytest tests/test_execution_frontend.py -q` 覆盖字体静态资源、缓存版本，以及 Python 编辑器与日志使用相同 Consolas 字体栈的最终规则。
2. **日志、编辑器高度和标题颜色**（已完成，2026-07-23）
   - Script 控制台、LLM/Agent 原始响应和 HTTP 原始请求/响应内容区使用纯黑背景；历史摘要行保持浅色。
   - 原始日志正文在既有字号上放大 30%：Script 控制台为 14.3px，HTTP/LLM/Agent 原始文本为 13px；历史摘要字号不变。
   - Python 编辑器固定内容高度由 360px 调整为 540px；设置页通过既有滚动容器访问后续运行配置。
   - 节点名、页签、字段标签、变量标题以及 LLM/HTTP/运行配置分组统一使用 `--wf-heading: #111827`；状态和错误语义色不变。
   - `npm run build` 成功；`uv run pytest tests/test_execution_frontend.py -q` -> `9 passed, 1 warning`。
3. **桌面浏览器和完整回归**（已完成，2026-07-23）
   - 浏览器确认 Python CodeMirror 与日志统一使用 Consolas 等宽字体，节点界面继续使用 Inter/Segoe UI。
   - 编辑器网格行为 `32.5px 540px`，设置容器可滚动访问运行配置；节点名、页签和字段标签计算色为 `rgb(17, 24, 39)`。
   - Script 日志历史行保持浅色，展开控制台为纯黑背景、浅色正文；放大后的 traceback 保留完整横向和纵向滚动。HTTP/LLM/Agent 黑底和 13px 正文由同一专项测试覆盖。
   - 最终回归：`uv run pytest -q` -> `220 passed, 6 skipped, 1 warning`；6 项为未注入真实模型凭据的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
   - `npm run build`、`uv run python -m compileall -q execution web tests` 和 `git diff --check` 均成功。

## T13.7 Python 编辑器与控制台复制（已完成）

### 业务目标与验收

- Script / Agent 的 `main.py` 使用 Python 语法高亮，提升长脚本的阅读、修改和排错效率；节点数据仍保存纯字符串，不改变执行协议。
- Script / Agent 不再提供独立“代码”页签；Python 编辑器嵌入“设置”页并位于运行配置上方，配置、代码和输出映射在同一滚动工作面完成。
- 用户在 Script 原始控制台拖选文本后按 `Ctrl+C`，必须复制浏览器文本选区，不能触发画布节点复制。
- 原始控制台提供独立复制按钮，一次复制本次控制台的全部原文，并显示成功或失败反馈。
- Script / Agent 代码编辑器使用适合桌面节点编辑器的 16px 字号；行号、代码和光标同步缩放。
- 日志摘要中的执行时间、耗时和最终结果概览统一为 14px，并加宽固定列；长结果继续单行省略显示。
- 画布节点多选复制、代码编辑器自身快捷键、最近 10 次日志和其他节点日志布局不得回归。

### 实施子任务

1. **现状确认**（已完成，2026-07-22）
   - 代码区为普通 textarea，项目没有可复用 CodeMirror 资产。
   - 画布已存在 `hasBrowserTextSelection()` 保护，文本选区不会被节点复制逻辑主动覆盖；仍需真实浏览器验证。
2. **CodeMirror Python 编辑器**（已完成，2026-07-22）
   - 引入 CodeMirror 6、Python language 和 one-dark 主题，`mainPy` 仍为受控字符串。
   - `npm run build` 成功；前端专项 `8 passed, 1 warning`。
3. **控制台复制按钮与反馈**（已完成，2026-07-22）
   - Script 原始控制台支持鼠标选区，并提供独立的一键复制按钮、成功状态和错误提示。
   - 普通 Clipboard API 和 `execCommand` 均不可用时，调用仅绑定本机应用的 Windows 系统剪贴板回退，确保内置浏览器仍能一键复制；最大文本与单次日志上限一致为 5 MB。
   - `npm run build` 成功；前端专项 `uv run pytest tests/test_execution_frontend.py -q` -> `8 passed, 1 warning`。
4. **构建、测试和浏览器回归**（已完成，2026-07-22）
   - 自动回归：`npm run build`、`uv run python -m compileall -q execution web tests` 和 `git diff --check` 均成功；`uv run pytest -q` -> `219 passed, 6 skipped, 1 warning`。
   - 浏览器验收：Script 设置页仅显示“设置 / 日志”，16px CodeMirror 位于运行配置上方；Python 关键字、字符串、函数、参数和常量使用不同颜色，行号与代码同步缩放，无文本遮挡。
   - 控制台验收：日志同时显示原始 stdout `stdout copy target` 和 stderr `stderr copy target`；一键复制显示“控制台已复制”，Windows 剪贴板内容与两行原文完全一致。
   - 日志正文改为只读文本控制台，浏览器原生维护鼠标选区和 `Ctrl+C`；其 `copy` 事件在组件内停止传播，画布节点复制不会覆盖日志文本。内置浏览器自动化对原生拖选合成不稳定，未将该工具限制误报为页面失败。
   - 临时验收 Workflow `ded6732203754d1ebfe73c5615462548` 已删除，列表恢复为 2 个原有 Workflow。

### 子任务

1. **解除 Script `response` 保留语义并放宽旧映射**（已完成，2026-07-22）
   - Script 模式不再预置、读取或序列化顶层 `response`；Agent 协议不变。
   - 旧 Script 输出行缺少 `pythonVariable` 时以对外变量名为可选来源，不再阻止保存。
2. **专项和真实 HTTP 运行验证**（已完成，2026-07-22）
   - 专项结果：`uv run pytest tests/test_tool_execution.py tests/test_workflow_variables.py tests/test_workflow_drafts.py tests/test_workflow_node_runs.py -q` -> `97 passed, 1 warning`。
   - 真实结果：用户提供的 `requests` 代码原样访问 `http://127.0.0.1:9000/chat/1`，Worker `ok: true`，HTTP 200 JSON 完整进入 stdout/console，顶层 `response` 未被序列化。
3. **前端历史映射归一化与浏览器回归**（已完成，2026-07-22）
   - 已完成：旧 Script 行 `name + value=response.xxx` 加载后归一化为 `pythonVariable=name` 并移除旧 value；`npm run build` 成功，前端专项 `8 passed, 1 warning`。
   - 浏览器结果：用户原代码在旧映射 Workflow 中保存并运行成功，节点 `SUCCESS`，控制台打印真实订单 JSON，遗留 `msg` 为 `null` 警告；临时 Workflow 已删除。
4. **全量回归与服务检查**（已完成，2026-07-22）
   - `uv run pytest -q` -> `217 passed, 6 skipped, 1 warning`；跳过项为未注入真实模型凭据的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
   - `uv run python -m compileall -q execution web tests`、`npm run build`、`git diff --check` 均成功。

### T13.5 验收结论

- 用户提供的 `requests` 代码无需改名即可执行，顶层 `response` 可以保存任意普通 Python 对象且不会被 Script 平台隐式序列化。
- Script 仅序列化输出区明确绑定的 Python 变量；未绑定的模块、客户端、响应对象、函数和其他运行时对象不会影响节点成功状态。
- 历史 `response.xxx` Script 映射不再阻止保存和执行，加载后自动转为同名可选顶层变量；缺失时输出 `null` 和控制台警告。
- 真实 `9000/chat/1` 与桌面浏览器两条链路均验证节点 `SUCCESS` 和完整控制台 JSON 输出。

### 子任务与验证

1. **协议记录**（已完成，2026-07-22）
   - 输出：上述可观测行为和数据边界写入计划。
   - 验证结果：用户确认日志不做字段提取，并选择缺失顶层变量输出 `null`、控制台警告、节点保持 `SUCCESS`。
2. **Worker 与持久化**（已完成，2026-07-22）
   - 输出：缺失变量补 `null` 和警告；有序 `console` 持久化及历史库迁移。
   - 验证结果：`uv run pytest tests/test_tool_execution.py tests/test_workflow_variables.py tests/test_workflow_drafts.py tests/test_workflow_node_runs.py -q` -> `95 passed, 1 warning`。覆盖 stdout/stderr 顺序、缺失变量 `null`、警告、数据库迁移、真实异常、类型失败和中断。
3. **Script 控制台 UI**（已完成，2026-07-22）
   - 输出：Script 运行详情只显示单一控制台，其他节点不回归。
   - 验证结果：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py -q` -> `8 passed, 1 warning`。桌面浏览器 E2E 合并到子任务 4。
4. **完整回归**（已完成，2026-07-22）
   - 最终回归：`uv run pytest -q` -> `215 passed, 6 skipped, 1 warning`；6 项为未注入真实模型凭据的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
   - 静态与构建：`uv run python -m compileall -q execution web tests`、`git diff --check`、`npm run build` 均成功。
   - 浏览器 E2E：临时 Workflow 的 Script 依次打印 stdout、stderr，并配置一个不存在的顶层变量；节点状态为 `SUCCESS`，结果包含 `missing: null`，展开日志只显示一个 `Script 原始控制台`，正文顺序为 stdout、stderr、`[WARNING]`，没有请求、响应或变量字段分区。
   - 清理与服务：临时 Workflow 已删除；`http://127.0.0.1:8010/` 保持单一监听端口并恢复到用户原工作流列表。

### T13.4 验收结论

- Script 日志不做字段提取，控制台原样保留 stdout、stderr、Python traceback 和系统警告的接收顺序。
- 顶层 Python 变量映射继续作为唯一节点间传参方式，控制台文本不参与传参。
- 缺失顶层变量输出 `null` 并警告，不再把正常完成的 Script 误判为失败。
- 真实执行错误仍为 `FAILED`；HTTP、LLM、Agent 的日志和输出协议未改变。

## 1. 业务背景与目标（Why）

Agent Bench v2 没有成熟的插件体系，也没有专门团队持续适配各模型厂商的协议、SDK、流式格式、结构化输出、Tool Calling、推理模式和中间件差异。现有 Agent 工具包含较多 Python 硬编码，是为了让工具作者能够直接处理供应商差异和特殊业务场景，而不是依赖平台先完成深度适配。

新版 Studio 的目标不是建设一个类似大型厂商市场的插件生态，而是解决以下实际问题：

- 新手不会从零编写完整 HTTP、LLM、Agent 或 Script 工具。
- 工具作者需要提供完整、可运行、可导入导出的起始模板。
- Workflow 编排人员需要在模板基础上修改少量代码或配置，快速得到当前 Workflow 的个性化工具。
- 画布中验证成熟的工具需要能够沉淀回模板库，供其他人再次使用。
- Workflow 必须自包含；模板被修改、删除或未随环境迁移时，已经保存的新版 Workflow 仍应可恢复和执行。
- 平台不能假装拥有并不存在的统一模型适配能力。LLM 和 Agent 必须保留完整 Python 修改能力。

本阶段的核心产品定位是：

```text
工具模板库负责提供完整起点
        ↓ 深拷贝
画布工具负责当前 Workflow 的个性化实现
        ↓ 可选发布
产生新的独立工具模板
```

## 2. 目标用户与真实场景（Who & Where）

### 2.1 工具模板作者

- 在工具模板库创建完整的 HTTP、LLM、Agent 或 Script 模板。
- 为模板提供可运行代码、类型配置、输入输出说明和安全默认值。
- 在模板库中独立测试模板。
- 通过模板包将工具交给其他 Agent Bench 用户。

### 2.2 Workflow 编排人员

- 在全屏 Studio 中新增空白工具，或从模板库选择现成模板。
- 将模板复制到画布后修改少量业务代码、Prompt、请求配置或输出处理。
- 配置当前 Workflow 特有的上游输入、下游输出、重试、延迟和重复执行。
- 不需要理解或管理模板与节点之间的版本引用关系。

### 2.3 模板接收者

- 导入其他人提供的工具模板包。
- 在模板库中独立测试导入的模板。
- 将模板复制到自己的 Workflow 中继续个性化。
- 不接收发布者的真实 API Key。

## 3. 需求真实性与优先级（What & When）

该需求来自明确的用户使用目标，不是为了抽象而抽象。工具模板化、画布工具所有权和执行自由度是 T13.2 的 P0 架构前置项，优先级高于继续细化 Agent / LLM 编辑器视觉布局。

原因如下：

- 如果所有权不明确，保存、复制、导出、删除和发布都会产生歧义。
- 如果先做 UI，后续确定深拷贝或引用模型时会整体返工。
- 如果先做“平台原生 LLM 执行器”，会形成无法持续维护的供应商适配层。
- 如果沿用旧固定 WorkflowDefinition，会把 T13.1 的任意画布原型错误套入旧执行拓扑。

## 4. 已确认的核心决策

### 4.1 新旧系统范围

- 新的“模板深拷贝到画布”模型只用于新版 Workflow Studio。
- 旧固定 Workflow、历史 Run 页面、相关 API 和固定拓扑执行链路全部删除。
- 旧 Script / Agent 工具定义、旧 ZIP 和旧 `manifest.json + main.py` 协议不提供导入或运行兼容。
- 旧本机工具数据由用户明确选择永久删除，不备份、不迁移。
- T13.2 不得直接复用旧 `WorkflowDefinition` 作为新版 DAG 协议。

### 4.2 模板与画布工具没有运行时引用关系

- 工具模板库中的对象是完整、可运行的起始模板。
- 从模板库拖入或选择模板时，系统将模板定义深拷贝为画布工具。
- 深拷贝完成后，画布工具不再引用来源模板。
- 修改模板不影响已经创建的画布工具。
- 修改画布工具不影响来源模板。
- 删除模板不影响已经保存的新版 Workflow。
- 新版 Workflow 保存和导出时包含画布工具的完整定义，不依赖目标环境仍存在来源模板。
- 不建设模板版本升级、自动传播、回滚或依赖影响分析机制。

### 4.3 画布保留工具构建能力

- 画布必须允许直接新建 HTTP、LLM、Agent 和 Script 工具。
- 用户可以从空白定义开始，也可以从模板库复制完整模板开始。
- 画布中的工具可以发布到工具模板库。
- 发布后的模板与当前画布工具相互独立，后续修改不自动同步。
- 画布不是第二套共享仓库；画布只维护当前 Workflow 内嵌的工具定义。

### 4.4 四类执行工具进入同一个工具模板体系

页面名称统一使用“工具模板”，并统一管理以下四种类型：

```text
HTTP
LLM
AGENT
SCRIPT
```

- `Start / End` 是 Workflow 系统控制节点，不是工具，不进入模板库。
- 四类工具共享模板创建、测试、搜索、筛选、导入、导出和发布生命周期。
- 四类工具不要求使用相同执行器；统一的是资产生命周期，不是运行实现。
- 类型在前端、API、`manifest.json`、`definition.json`、画布节点和运行快照中一律使用大写 `HTTP / AGENT / LLM / SCRIPT`，不接受或输出旧小写类型。

### 4.5 包结构采用 manifest + definition + 可选代码

已确认目标包结构为：

```text
{template_id}/
├── manifest.json
├── definition.json
└── main.py          # 按类型决定是否必需
```

- `manifest.json` 保存模板身份、类型、格式版本和展示元数据。
- `definition.json` 保存类型配置、输入输出、凭据要求、测试示例等结构化定义。
- `main.py` 对 LLM、Agent、Script 必需。
- `main.py` 对 HTTP 可选。
- 不再为没有 Python 实现的 HTTP 配置模式生成无意义的空 `main.py`。
- 旧 `manifest.json + main.py` Script / Agent ZIP 不再兼容；导入时必须作为无效旧格式拒绝。

### 4.6 模板必须支持独立测试

- 工具模板库继续提供独立测试运行能力。
- 模板发布或导出前应能使用测试输入验证基本可执行性。
- 测试运行不得依赖某个 Workflow 的画布位置、连线或运行历史。
- 测试使用的输入样例、凭据绑定和日志是否保存，需要在数据协议子任务中继续确认。

### 4.7 发布时移除真实 API Key

- 从画布发布模板时，自动移除真实 API Key。
- 模板只保留“需要某类凭据”的声明、安全占位或空值。
- API Key 不得从画布工具泄漏到新模板。
- 旧工具 ZIP 导入导出能力随旧协议删除，不保留明文密钥导出行为。
- Authorization Header、Cookie、自定义 Token 和代码中硬编码密钥的识别与处理尚未确认，列入开放问题。

### 4.8 统一 Python 运行数据协议

- LLM、AGENT、SCRIPT 以及 HTTP 代码模式统一使用 `inputs / config / response`。
- `inputs` 是本次运行由 Start、上游节点或运行参数传入的动态数据；模板和 Workflow 只保存映射，不保存某次运行的实际值。
- `config` 是随工具模板或画布节点保存的持久配置；凭据是否只保存引用仍需单独确认。
- `response` 是当前节点本次执行产生的标准 JSON 输出，供下游节点、运行追溯和 Artifact 使用，不写回工具模板。
- 不继续使用旧 Agent 六个固定模板参数，也不把节点配置混入 `inputs`。

## 5. 工具模板与画布工具的白话边界

```text
模板库中的工具：一份完整参考答案
画布中的工具：把参考答案复制过来后，为当前 Workflow 改出的个人版本
```

双方的职责如下：

| 工具模板库 | 画布工具 |
|---|---|
| 提供完整起始代码与配置 | 保存当前 Workflow 的完整个性化实现 |
| 可以独立测试 | 可以在 Workflow 中运行和追溯 |
| 可以导入、导出 | 随 Workflow 保存和导出 |
| 不保存画布坐标和连线 | 保存位置、连线和输入绑定 |
| 不保存 Workflow 运行状态 | 保存节点状态、耗时、日志和运行参数引用 |
| 发布后供下次复制 | 修改不回写来源模板 |

模板拖入画布是复制，不是引用：

```text
模板 A
  └── 深拷贝 → 画布工具 A'

之后：
修改模板 A   ≠ 修改画布工具 A'
修改画布 A'  ≠ 修改模板 A
```

## 6. 四类工具的职责与执行自由度

### 6.1 HTTP

HTTP 工具支持两种使用方式：

```text
配置模式
  Method / URL / Headers / Params / Body / 超时等
  由系统标准 HTTP 执行器执行

代码模式
  使用 main.py 完整接管特殊 HTTP 调用
  通过现有或新版通用 Worker 执行
```

已确认：

- 标准场景优先使用可视化配置。
- 特殊场景允许使用完整 Python。
- HTTP 的 `main.py` 可选。

尚未确认：

- 配置模式和代码模式是否通过分段控件切换。
- 切换时是否永久保留另一模式的内容。
- 配置模式如何引用上游输入和凭据。
- HTTP 代码模式已确认使用统一的 `inputs / config / response` Worker 契约。

### 6.2 LLM

LLM 不采用需要平台持续适配供应商的封闭原生执行器。

已确认：

- LLM 必须包含可完整编辑的 `main.py`。
- 用户可以修改 Client、SDK、Base URL、请求头、模型参数、推理模式、流式处理、结构化输出和响应解析。
- 模板只提供面向“一次模型调用”的默认代码结构，不限制用户最终代码能力。
- 平台不负责维护覆盖所有模型厂商的深度适配层。

### 6.3 Agent

已确认：

- Agent 必须包含可完整编辑的 `main.py`。
- 默认模板面向多步决策、Tool Calling、Middleware、状态、上下文和多轮执行。
- 允许继续使用 Python 硬编码处理供应商差异和特殊 Agent 逻辑。
- 平台不尝试把所有 Agent 行为抽象成固定表单或插件协议。

### 6.4 Script

已确认：

- Script 必须包含可完整编辑的 `main.py`。
- Script 用于通用 Python 数据处理、转换、校验和聚合等场景。
- 新版协议需决定是否支持 `${...}`；旧 Script 行为不再构成兼容约束。

### 6.5 LLM 与 Agent 只做语义分类

LLM 与 Agent 的区别用于：

- 模板分类。
- 默认代码结构。
- 编辑器布局。
- 用户意图表达。
- 后续统计和筛选。

已确认不做运行时强制限制：

- LLM Python 可以调用工具。
- Agent Python 可以只执行一次模型调用。
- 平台不通过静态扫描或沙箱规则强制两者能力边界。
- 两类代码都在受控 Worker 进程边界内执行，但用户 Python 本身保持高自由度。

## 7. 结构化定义的目标边界

`definition.json` 的目的不是封装所有供应商，而是让模板和画布能够描述、校验和渲染工具。

目标职责：

```text
definition.json
├── 输入字段或端口
├── 输出字段或端口
├── 普通配置项
├── 凭据要求
├── 类型专属配置
├── 测试输入示例
└── 输出示例或结构说明

main.py
└── 真正的自定义执行逻辑
```

尚未确认的协议细节：

- 输入输出使用简化字段表还是完整 JSON Schema。
- 输入类型集合和嵌套对象表达方式。
- 必填、默认值、说明、固定值、上游映射和全局变量如何区分。
- 多输出端口与单一 JSON `response` 如何兼容。
- 模板测试输入是否属于 `definition.json`。
- HTTP 配置与 Python 代码之间的数据传递格式。
- LLM / Agent 的普通配置是否继续使用 6 个固定模板参数，或改用结构化配置对象。

在这些字段确认前，不得直接扩展现有 `ToolManifest`。

## 8. 画布工具生命周期

### 8.1 创建

目标入口：

```text
新增 HTTP / LLM / AGENT / SCRIPT
        ↓
选择空白定义或工具模板
        ↓
深拷贝为画布独立工具
```

空白定义必须提供可理解的最小起始内容，尤其是 LLM、Agent 和 Script 的完整示例代码。

### 8.2 编辑

- 画布工具的代码和配置可以直接修改。
- 修改只影响当前 Workflow。
- 不提供“升级来源模板”“同步模板修改”或“分离副本”，因为深拷贝后本来就没有引用关系。
- 复制粘贴节点必须继续深拷贝工具定义和选区内部连线。

### 8.3 发布

发布的业务含义：从当前画布工具提取可复用部分，创建一个新的独立模板。

当前已落地的发布内容：

- 名称、说明和类型。
- `manifest.json` 身份及格式信息。
- `definition.json` 输入输出和类型配置。
- `main.py` 完整代码（适用类型）。
- 安全默认值和测试示例。

不得发布的 Workflow 实例信息：

- 画布坐标、尺寸和连线。
- 上游节点 ID、下游节点 ID和当前 Workflow 专属映射。
- 节点运行状态、执行耗时、日志和运行历史。
- 当前 Workflow 名称、Run、Case、Attempt、Artifact 数据。
- 已确认不得发布的真实 API Key。

发布始终由后端生成新模板 ID，不覆盖同 ID；同名模板允许并按各自 ID 展示。发布完成后不向画布节点写回模板引用。

### 8.4 删除

- 删除模板不影响已经复制到新版 Workflow 的画布工具。
- 删除画布工具不影响模板库。
- 旧仓储和旧 Workflow 引用规则整体删除，不进入新版生命周期。

## 9. 导入、导出与可移植性

### 9.1 模板包

- 四类模板使用同一包格式和格式版本。
- LLM、Agent、Script 包含 `main.py`。
- HTTP 配置模板可以没有 `main.py`；HTTP 代码模板包含 `main.py`。
- 导入后模板进入同一个工具模板库并可独立测试。
- 旧 Script / Agent ZIP 不兼容，并通过专项测试确认被明确拒绝且不会产生部分写入。

### 9.2 Workflow 包

- 新版 Workflow 导出包含全部画布工具定义和图结构。
- 导入目标环境不需要预先安装来源模板。
- 导入后不建立对来源模板 ID 的运行时引用。
- Workflow 是否复用模板包目录结构、是否将工具按节点逐个内嵌、如何处理重复工具定义，尚待协议设计。

### 9.3 凭据

- 从画布发布模板时移除真实 API Key，这是已确认规则。
- n8n 等项目采用凭据 Stub 和导入后重新绑定；该模式可作为参考，但尚未被确认成 Agent Bench 的最终方案。
- 新版 Workflow 导出是否保留明文密钥、改为凭据声明或要求导入后绑定，仍需单独确认。
- 当前新模板 ZIP 不会自动清理 `config` 或 `main.py` 中的全部秘密，页面导出前必须保留可信接收者警告；凭据规则确认前不得宣称可安全公开分享。

## 10. 当前 Studio UI 基线（不得回归）

以下是 T13.1 已完成并在后续布局中需要保留的行为：

- `Start / End` 为系统节点；可新增工具类型为 `HTTP / AGENT / LLM / SCRIPT`。
- 所有画布节点卡片右上角只保留运行按钮。
- 节点状态统一为 `PENDING / RUNNING / PASSED / FAILED`。
- 节点右下角显示加载圆环和本次执行耗时。
- 每次执行从 `0ms` 重新计时，`RUNNING` 期间累加，结束后固定本次耗时。
- 加载圆环只在 `RUNNING` 状态旋转。
- `FAILED` 已有状态和样式能力；T13.1 不随机制造失败。
- 单击节点只选中，双击打开可移动、八向拉伸的节点编辑器。
- 节点编辑器标题栏保留运行、保存和关闭。
- 参数通过独立“参数”页签查看，标题栏不提供参数快捷按钮。
- 参数页按 `source / name / data` 展示只读实际运行参数；大数据使用摘要、详情或 Artifact。
- 画布右上角保留运行、全局变量和保存。
- Ctrl 多选、框选、复制粘贴、Delete / Backspace、Undo / Redo 和 Dagre 自动布局继续有效。
- 系统只支持桌面浏览器，不增加移动端设计或测试。

四类工具的编辑器详细信息架构尚未确认。不得因为类型统一进入模板库而强行使用同一编辑表单。

### 10.1 当前落地状态

- 成功状态已在源码、专项测试、前端构建产物、`AGENTS.md` 和 `docs/enterprise-agent-test-orchestration.md` 中统一为 `PASSED`。
- 桌面浏览器已验证节点从 `PENDING` 进入 `RUNNING` 后结束为 `PASSED`；失败能力继续使用 `FAILED`。

## 11. 行业调研结论与适用范围

调研项目：n8n、Node-RED、Dify、Langflow、Apache NiFi。

### 11.1 可借鉴内容

- n8n：社区节点包注册节点类型，Workflow 实例保存类型、版本、参数、凭据引用和位置；新 n8n Package 使用凭据 Stub，而不是导出秘密。
- Node-RED：节点包可携带 example flows；Subflow 是可复用定义，实例保存每次使用的属性。
- Dify：Tool Plugin 将 provider、tool 参数、输出 Schema、代码和凭据声明分层，工具安装后可直接作为 Workflow 节点使用。
- Langflow：组件类声明输入输出和类型，编辑器据此生成端口和校验连接。
- Apache NiFi：版本化 Flow 与本地 Process Group 分离，支持改变版本和停止版本控制。

### 11.2 不直接照搬的内容

- Agent Bench 当前不采用 n8n / NiFi 的长期引用和版本升级模型。
- Langflow 的 `replacement` 只是显式推荐并过滤候选组件，不会自动迁移配置和连线。
- 不根据字段名称和类型自动推断任意两个工具可以无损替换。
- 不建设需要持续团队维护的统一模型供应商插件层。
- 不把设计工具中的 Detach / Variant 概念引入当前深拷贝模型；模板复制后天然独立。

### 11.3 参考资料

- n8n 节点示例：<https://github.com/n8n-io/n8n-nodes-starter/blob/master/nodes/Example/Example.node.ts>
- n8n 节点标准参数：<https://docs.n8n.io/connect/create-nodes/build-your-node/reference/base-files/standard-parameters/>
- n8n Packages：<https://docs.n8n.io/build/manage-workflows/export-and-import/n8n-packages/>
- Node-RED 节点打包：<https://nodered.org/docs/creating-nodes/packaging>
- Node-RED Example Flows：<https://nodered.org/docs/creating-nodes/examples>
- Node-RED Subflows：<https://nodered.org/docs/user-guide/editor/workspace/subflows>
- Dify Tool Plugin：<https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/tool-plugin>
- Langflow 自定义组件：<https://docs.langflow.org/components-custom-components>
- Langflow replacement 源码：<https://github.com/langflow-ai/langflow/blob/main/src/frontend/src/CustomNodes/GenericNode/components/NodeLegacyComponent/index.tsx>
- Apache NiFi Versioning：<https://nifi.apache.org/docs/nifi-docs/html/user-guide.html#versioning_dataflow>

## 12. 端到端目标流程

### 12.1 从模板创建工具

```text
进入 Workflow Studio
  → 添加 HTTP / LLM / AGENT / SCRIPT
  → 选择空白定义或工具模板
  → 系统深拷贝模板
  → 用户修改少量代码或配置
  → 配置输入输出与连线
  → 保存 Workflow
  → 创建 Run 时冻结画布工具完整快照
  → 执行、追溯和恢复
```

### 12.2 从画布发布模板

```text
在画布完成工具配置和测试
  → 点击“发布为模板”
  → 系统提取可复用定义
  → 移除真实 API Key 和实例运行数据
  → 用户确认模板名称、说明和测试示例
  → 在模板库创建独立模板
  → 原画布工具保持不变
```

### 12.3 模板跨用户复用

```text
用户 A 导出模板包
  → 用户 B 导入模板包
  → 在模板库独立测试
  → 复制到用户 B 的画布
  → 绑定本机凭据并个性化
  → 保存为自包含 Workflow
```

## 13. 可独立验证的开发子任务

每个子任务必须在验证通过后才能进入依赖任务。任何失败都暂停下游任务并记录结果。

| ID | 目标 | 输入 | 输出 | 验证方法 | 依赖 |
|---|---|---|---|---|---|
| T13.2.1 | 冻结新版术语、所有权和未决业务规则 | 本计划、现有 T13.1 原型 | 经用户确认的数据契约决策记录 | 逐项需求评审；确认所有开放问题有明确结论 | T13.1 |
| T13.2.2 | 定义四类模板和画布内嵌工具模型 | T13.2.1 | Pydantic 模型、格式版本、类型判别联合、迁移边界 | 模型单测覆盖四类型、非法额外字段、JSON 严格性和往返序列化 | T13.2.1 |
| T13.2.3 | 重建模板仓储和包格式 | T13.2.2、空 `tool_registry/` | 四类型 CRUD、刷新、导入、导出；拒绝旧 ZIP | 仓储和 ZIP 单测；路径穿越、重复 ID、无效包、旧包拒绝且无部分写入 | T13.2.2 |
| T13.2.4 | 实现模板独立测试 | T13.2.2、现有 Worker / SSE | 四类型测试启动、中断、日志、结果协议 | 每类型成功、失败、超时、中断、非法 JSON 和日志上限测试 | T13.2.2、T13.2.3 |
| T13.2.5 | 实现画布工具深拷贝与空白创建 | T13.2.2、T13.1 画布 | 四类型内嵌定义、来源模板深拷贝、复制粘贴保持 | 前端状态测试和真实浏览器 E2E；修改模板/节点互不影响 | T13.2.2、T13.2.3 |
| T13.2.6 | 实现从画布发布模板 | T13.2.3、T13.2.5 | 发布提取、实例字段剥离、API Key 清除、新模板创建 | 发布前后深比较；密钥扫描；模板独立运行；原节点不变 | T13.2.3-T13.2.5 |
| T13.2.7 | 设计并实现新版 Workflow 持久化 | T13.2.2、T13.2.5 | 图结构、内嵌工具、事务保存、更新、删除和校验 | Repository 重启回读、并发更新、无效边/节点/定义拒绝 | T13.2.2、T13.2.5 |
| T13.2.8 | 实现四类工具执行器 | T13.2.4、T13.2.7 | HTTP 配置/代码、LLM Python、AGENT Python、SCRIPT Python 执行 | 每类型真实子进程/HTTP 测试；inputs、config、response、日志、取消和超时 | T13.2.4、T13.2.7 |
| T13.2.9 | 接入 Run 快照和 DAG 调度 | T13.2.7、T13.2.8 | 新版 Workflow 快照、节点状态、依赖调度、Artifact 追溯 | 单链、分支、汇合、失败、取消、恢复、快照不变性测试 | T13.2.7、T13.2.8 |
| T13.2.10 | 完成四类节点编辑器布局 | 已确认类型协议、T13.1 UI 基线 | HTTP / LLM / Agent / Script 类型化编辑器 | 1440x900 浏览器 E2E；无溢出/重叠；代码和配置完整保存 | T13.2.5、T13.2.8 |
| T13.2.11 | 完成模板与 Workflow 导入导出 | T13.2.3、T13.2.7、凭据规则 | 跨环境模板包和自包含 Workflow 包 | A 环境导出、B 环境导入、无来源模板恢复、凭据缺失提示 | T13.2.3、T13.2.7 |
| T13.2.12 | 完整回归和文档收口 | 全部前序任务 | E2E 报告、迁移说明、风险清单、权威文档更新 | 单测、静态检查、构建、桌面完整流程和受影响模块全量回归 | T13.2.1-T13.2.11 |

## 14. 总体验收标准与价值验证（How to Measure）

### 14.1 模板独立性

- 从任意模板创建画布工具后，修改或删除模板不改变画布工具。
- 修改画布工具不改变模板。
- 新版 Workflow 在没有来源模板的环境中仍能恢复完整定义。

### 14.2 新手效率

- 新手可从四类完整模板创建节点，不需要从空文件编写完整代码。
- 模板复制后只修改少量代码或配置即可完成最小可运行流程。
- 模板库独立测试能够在进入 Workflow 前发现缺包、配置和执行错误。

### 14.3 发布复用

- 画布工具可以发布为独立模板。
- 发布不改变当前节点和任何已有模板。
- 新模板可独立测试、导出、导入并再次复制到画布。

### 14.4 安全

- 发布模板包不包含真实 API Key。
- 测试、日志、错误和 Artifact 不意外写入模板包。
- 文件导入导出继续受 `tool_registry/` 路径边界和 ZIP 安全校验约束。

### 14.5 执行与追溯

- LLM、Agent、Script 的完整 Python 在独立子进程执行。
- HTTP 配置模式和 Python 模式均可追踪输入、输出、日志、耗时和错误。
- Run 创建后冻结 Workflow 和全部内嵌工具，后续编辑不影响历史 Run。
- 节点状态和耗时遵守 `PENDING → RUNNING → PASSED / FAILED` 展示规则。

### 14.6 不兼容替换边界

- 旧固定 Workflow/Run 页面、API 和执行链不可访问且不再出现在导航中。
- 旧 Script / Agent 工具 CRUD、SSE、ZIP 和小写类型协议不可访问。
- 新工具模板只接受并输出 `HTTP / AGENT / LLM / SCRIPT`，不存在旧协议兼容层。
- 测试集、Target、FAQ、主题和新版 Workflow Studio 等保留功能不得因删除旧链路回归。

## 15. 已知风险

- 深拷贝会产生代码重复；模板修复不会自动传播到已有 Workflow。
- 没有模板引用后，无法统计哪些 Workflow 源自某个模板。
- 任意 Python 使 LLM / Agent 分类无法成为安全边界。
- 用户代码可能硬编码密钥，单纯清空结构化 API Key 字段不足以保证发布包无秘密。
- HTTP 双模式会带来配置与代码的优先级、切换和回显复杂度。
- 不兼容删除会使旧工具包、旧 Workflow 和历史 Run 无法恢复，这是用户已确认接受的永久数据损失。
- 自包含 Workflow 包可能显著增大，重复节点代码需要确定去重策略。
- 新版任意 DAG 的执行、取消、恢复和 Artifact 传播不能直接套用旧固定拓扑。
- 缺少成熟插件生态意味着依赖兼容和第三方 SDK 仍需人工维护 `pyproject.toml`。

## 16. 实现前仍需确认的开放问题

以下问题没有得到用户确认，不得自行补全：

1. HTTP CONFIG 的上游字段引用、动态 URL/Header/Body 映射和在 Workflow 中的标准 `response` 使用规则。
2. 除 API Key 外，Authorization、Cookie、Token 和代码硬编码秘密的处理范围。
3. 新版 Workflow 导出时的凭据保存、Stub 和导入后绑定规则。
4. 新版 Workflow 图结构、端口、分支、汇合、循环和失败传播规则。
5. 四类节点编辑器下一阶段的字段分组、标签页和默认展开状态。
6. 从导入模板替换已有画布节点时，是否需要保留位置、连线和输入绑定；当前只有新增深拷贝，没有自动替换协议。

## 17. 执行纪律

- 每次只实现一个可独立验证的子任务。
- 子任务开始前重新检查本计划、权威编排文档和当前 Git 差异。
- 每个子任务必须明确目标、输入、输出、验证方法和依赖。
- 验证失败时停止所有依赖任务，不得继续堆叠实现。
- 每完成一个子任务立即记录测试命令、结果、未覆盖范围和已知风险。
- 开发完成后必须运行相关单元测试、静态检查、完整构建、桌面 E2E 和受影响模块全量回归。
- 不覆盖或回滚与当前任务无关的用户改动。

## 18. 当前工作区与验证基线（2026-07-20）

### 18.1 已落地的 T13.1 原型能力

- Workflow 管理页可进入独立全屏 React Flow Studio；当前保存、测试运行、参数数据和节点运行状态均为前端本地演示，不调用旧 Workflow API，不能用于实际 Run。
- 画布支持节点拖动、连线、Dagre 自动布局、Edge `+` 插入、空白区与节点右键菜单、小地图和测试运行演示。
- 图结构历史最多保留 50 步；支持 `Ctrl+Z`、`Ctrl+Shift+Z`、`Ctrl+Y`、Ctrl 多选、框选、复制粘贴内部连线和 Delete / Backspace 删除。
- 双击节点打开默认 `1064x814`、可移动、八向缩放的编辑器；编辑器包含设置、参数和节点日志，普通字段每行两个，输出变量可动态增删。
- 节点卡片右上角只保留运行按钮；参数入口保留在编辑器“参数”页签，按 `source / name / data` 展示只读运行参数，大数据预留摘要、详情和 Artifact 入口。
- 节点右下角已显示加载圆环和本次执行耗时；每次运行从 `0ms` 开始，`RUNNING` 期间持续累加，完成后冻结，圆环仅在执行中旋转。
- HTTP 编辑器已有 Method、URL、Headers、Params、Body、cURL 导入、JSON Beautify 和 Binary 文件等前端配置能力；这些字段尚未形成新版后端执行协议。

### 18.2 当前修改和新增文件

工作区存在未提交修改，其中可能包含用户在本任务前或并行完成的改动。后续不得假定全部差异属于 T13.2，也不得回滚无关内容。

- `PLAN.md`：T13.2 业务分析、已确认决策、行业调研、开发拆解、验收标准、风险和开放问题。
- `web/frontend/workflow-canvas.jsx`：React Flow Studio 源码、节点编辑器、HTTP 配置、前端状态和执行耗时演示。
- `web/frontend/workflow-canvas.css`：Studio、节点、编辑器、参数表、耗时圆环和上下文菜单的桌面样式。
- `web/static/assets/workflow-canvas.js`：由 `npm run build:workflow` 生成的 JavaScript 构建产物，禁止绕过源文件直接修改。
- `web/static/assets/workflow-canvas.css`：Studio 静态样式资源。
- `tests/test_execution_frontend.py`：Studio 资源注册、画布交互、编辑器、HTTP、参数、状态和耗时的前端专项回归。
- `package.json`、`package-lock.json`：React、React Flow、Dagre、Lucide、react-rnd、cURL 解析和 `build:workflow` 构建依赖。
- `web/static/execution.js`、`web/static/execution.css`：Workflow 管理入口、Studio 挂载逻辑和管理页样式。
- `web/static/index.html`：Studio JavaScript/CSS 资源注册和 Workflow 导航文案。
- `docs/enterprise-agent-test-orchestration.md`：T13.1 状态、验证记录、当前限制和旧编排边界。
- `AGENTS.md`：项目当前进度、Studio 基线和 `PASSED` 成功状态。

### 18.3 最近一次已记录验证

- Studio 专项：`uv run pytest tests/test_execution_frontend.py -q`，结果 `8 passed, 1 warning`。
- 前端构建：`npm run build` 成功；构建脚本依次执行 `build:editor` 和 `build:workflow`。
- 静态检查：`node --check` 和 `git diff --check` 通过。
- 桌面浏览器 E2E：在 `1440x900` 下验证拖动、菜单、编辑器缩放、参数页、HTTP 配置和状态演示；页面横向溢出为 0，浏览器控制台错误为 0。
- 全量回归：`uv run pytest -q`，结果 `295 passed, 7 skipped, 1 warning`。
- 7 个跳过项包括 6 个缺少供应商凭据的 Agent live 矩阵和 1 个 Windows 符号链接权限测试；warning 为既有 Starlette/httpx 弃用提示。
- 真实模型历史矩阵已覆盖 DeepSeek `deepseek-v4-pro` 和 DashScope `qwen3.7-max`；真实内网 FastAPI 联调仍未完成，不得宣称真实环境全链路通过。
- 上述结果是最近一次已记录基线；后续改动不能仅引用旧结果，必须重新执行受影响验证。

> 基线更新：上述 `295 passed` 是删除旧 Workflow/Run 链路前的历史结果。Step 2 删除对应实现和测试后，当前剩余测试基线更新为 `153 passed, 6 skipped, 1 warning`，详见第 21 节。

## 19. 下一步具体执行计划

### 19.1 当前已完成批次

- 旧工具与旧 Workflow/Run 不兼容删除。
- 四类大写模板模型、仓储、CRUD、安全 ZIP、独立测试和统一执行 Worker。
- 工具模板页面、画布深拷贝、节点代码映射和发布为独立新模板。
- `definition.json` 使用简化字段列表；HTTP 使用 `CONFIG / CODE` 并只执行当前模式；测试 inputs 和日志不持久化。

### 19.2 下一批必须确认的三个问题

1. 新版 Workflow 是否禁止循环，以及分支、汇合和多入边节点的执行条件。
2. 节点端口和边是否只表达控制流，还是同时携带命名数据映射。
3. 节点失败、超时或中断后，下游是全部跳过、按边策略继续，还是允许节点级容错配置。

在这三项确认前不得建立 Workflow 持久化模型或 DAG 调度器，因为它们会直接决定图 Schema、校验规则、运行快照和恢复语义。

### 19.3 当前验证基线

- `npm run build`、Python `py_compile`、JavaScript `node --check` 和 `git diff --check` 通过。
- `uv run pytest -q`：`106 passed, 1 warning`。
- 桌面浏览器覆盖模板 CRUD/ZIP 回读、独立运行成功/中断、模板深拷贝和画布发布；临时模板均已清理。

### 19.4 后续依赖顺序

严格按以下顺序推进，不跨越未验证依赖：

```text
T13.2.1-T13.2.6 已完成
  → T13.2.7 Workflow 持久化
  → T13.2.8 四类执行器（模板独立执行部分已提前完成）
  → T13.2.9 DAG 调度、Run 快照与追溯
  → T13.2.10 四类节点编辑器
  → T13.2.11 模板与 Workflow 导入导出
  → T13.2.12 全量回归、迁移说明和文档收口
```

每项完成后立即执行第 13 节定义的验证并记录命令、结果、未覆盖范围和风险。最终必须覆盖模型单测、仓储与 ZIP 安全、真实子进程和 HTTP、Repository 重启回读、DAG 单链/分支/汇合/失败/取消/恢复、Run 快照不变性、桌面 `1440x900` E2E、前端完整构建、静态检查和全量 pytest 回归。

## 20. 持续有效的项目约束

- `docs/enterprise-agent-test-orchestration.md` 只作为已完成旧实现的历史记录；其中要求保留旧 Workflow/Run/工具链路的内容已被用户最新决策覆盖。
- 新版 Studio 不得直接复用旧 `WorkflowDefinition`、旧 Run 快照或旧工具协议作为任意 DAG 协议。
- 系统只支持桌面浏览器；不得增加移动端断点、触控专用逻辑或移动端回归测试。
- 不恢复旧评测流水线、`inputs/.tools.json` 或工具 `tags` 逻辑。
- Excel 文件操作限制在 `inputs/`，工具文件操作限制在 `tool_registry/`；导入导出必须继续执行路径穿越和 ZIP 安全校验。
- `config.yaml` 只保存当前 Excel 和 Sheet，不得保存业务配置、编排进度或凭据。
- API Key 只可注入测试或运行进程，不得写入代码、测试、文档或提交内容；旧工具 ZIP 明文密钥导出行为随旧链路删除。
- 用户代码继续使用当前 `.venv`，不自动安装依赖；缺包时人工修改 `pyproject.toml` 后执行 `uv sync`，禁止在编辑器用户代码中调用 `pip` 或 `uv`。
- 工作区可能包含用户未提交改动；后续修改必须先检查差异，不覆盖或回滚与当前子任务无关的内容。

## 21. 分步执行记录

### Step 1：永久删除旧本机工具数据（completed，2026-07-20）

- 目标：在不建立兼容层的前提下清空旧 Script / Agent 工具数据，为四类大写工具模板重建空仓储。
- 输入：`tool_registry/` 下 6 个旧 UUID 工具目录；用户明确选择 `1A` 永久删除且不备份。
- 输出：6 个一级工具目录及其中旧 `manifest.json + main.py` 已永久删除；`tool_registry/` 根目录和 `.gitkeep` 保留。
- 路径安全：删除前解析 `tool_registry/` 绝对路径，并逐项校验所有删除目标的父目录严格等于该根目录；未对工作区其他路径执行删除。
- 验证：删除命令退出码为 0；删除后 `Get-ChildItem -Force tool_registry` 只返回 `.gitkeep`。
- 依赖结论：Step 1 已通过，可以开始 Step 2 拆除旧固定 Workflow/Run 页面、API 注册和执行链。

### Step 2：拆除旧固定 Workflow/Run 页面、API 和执行链（completed，2026-07-20）

- 目标：彻底移除旧固定拓扑 Workflow、旧 Run 中心及其后端执行链，同时保留测试集、Target、新版 Workflow Studio、工具模板入口和 FAQ。
- 前端输出：侧栏删除“运行中心”；`web/static/execution.js` 重建为仅包含 Target CRUD 和前端本地 Workflow Studio，不再包含旧 Run、固定 Workflow 编辑器、测试集绑定或旧 API 请求。
- API 输出：FastAPI 不再注册 `web/routes_workflows.py` 和 `web/routes_runs.py`；`GET /api/workflows` 与 `GET /api/runs` 均返回 404。
- 后端删除：删除旧 `routes_workflows.py`、`routes_runs.py`、`run_events.py`，以及旧 Artifact、Connector、Preparation、Workflow、Case Executor、Scheduler、Results、Run Repository 和 Run Models 模块。
- Target 保留：新增 `execution/targets.py`，以独立 `TargetRepository` 管理现有 `targets` 表；旧 Workflow/Run 表即使仍存在于本机 SQLite，也不再被程序读取或通过 API 暴露。
- 测试清理：删除只验证旧 Artifact、Connector、Run Repository、Preparation、固定 Workflow、Case Executor、Scheduler、Run API 和 Run Events 的测试；Target 测试改为验证独立仓储初始化、重启回读和 CRUD。
- 专项验证：`uv run pytest tests/test_targets.py tests/test_execution_frontend.py tests/test_web_app.py -q`，结果 `37 passed, 1 warning`。
- 静态验证：保留 Python 文件通过 `py_compile`；`node --check web/static/execution.js` 和 `git diff --check` 通过。
- 引用验证：在 `web/` 和 `execution/` 生产源码中扫描 `/api/runs`、`/api/workflows`、旧路由、`RunRepository`、`RunScheduler`、`WorkflowService` 和 `CaseWorkflowExecutor`，结果为零命中。
- 全量回归：`uv run pytest -q`，结果 `153 passed, 6 skipped, 1 warning`，耗时 11.41 秒；6 个跳过项为未注入真实模型凭据的 live 测试，warning 仍为既有 Starlette/httpx 弃用提示。
- 依赖结论：Step 2 已通过；下一步必须先确认 `definition.json`、HTTP 双模式和凭据规则，再建立四类大写工具模板模型。

### Step 3：冻结首批新模板协议（completed，2026-07-20）

- `definition.json`：选择简化字段列表，不实现完整 JSON Schema。输入输出字段使用 `name / type / required / description / example`；复杂对象在当前迭代统一声明为 `JSON`。
- HTTP 双模式：使用大写 `CONFIG / CODE` 作为明确执行模式；切换时保留配置和代码两边内容，但运行时只执行当前模式。
- Python 数据协议：继续遵守已确认的 `inputs / config / response`；`inputs` 是动态上游数据，`config` 是节点持久配置，`response` 是本次标准 JSON 输出。
- 凭据决策：独立凭据仓储、凭据槽、Workflow 默认绑定、节点覆盖、运行时秘密解析和导入后重新绑定全部延后，写入待优化清单，不阻塞当前快速迭代。
- 当前迭代边界：新模板模型不增加 `credential_id`、凭据仓储表或绑定 API/UI；`config` 保持通用 JSON。不得因此宣称模板导出已具备完整秘密保护能力。
- 安全风险：用户仍可能把 API Key、Authorization、Cookie、Token 或密码写入 `config` 或 `main.py`。发布/导出前的已知字段清理、代码秘密扫描和日志脱敏仍未实现，相关功能完成前不得宣称模板包可安全公开分享。
- 验证：逐项对照用户选择 `1A / 2A` 和“凭据功能待优化、当前跳过”的最新决定，本计划已移除凭据功能对 T13.2.2/T13.2.3 的阻塞依赖；`git diff --check -- PLAN.md` 必须通过。
- 依赖结论：Step 3 已完成，可以开始 Step 4 建立四类大写工具模板模型和空仓储。

### Step 4：建立四类大写工具模板模型、仓储和 CRUD API（completed，2026-07-20）

- 目标：在空 `tool_registry/` 上建立不兼容旧协议的四类工具模板数据层，为后续前端、导入导出、独立测试和画布深拷贝提供唯一事实模型。
- 模块替换：删除旧 `web/tool_registry.py` 和 `web/routes_tools.py`；新增 `web/tool_templates.py` 和 `web/routes_tool_templates.py`。
- API：新入口为 `/api/tool-templates`；旧 `/api/tools` 不再注册并返回 404。
- 类型：`manifest.json`、`definition.json` 和 API 只接受 `HTTP / AGENT / LLM / SCRIPT`；小写 `http / agent / llm / script` 由 Pydantic 直接拒绝，不做规范化。
- 包结构：每个模板目录必须包含 `manifest.json + definition.json`；AGENT、LLM、SCRIPT 必须包含 `main.py`；HTTP `CONFIG` 模式可无 `main.py`，HTTP `CODE` 模式必须包含。
- 简化字段：输入输出使用 `name / type / required / description / example`，字段类型当前限定为 `STRING / NUMBER / INTEGER / BOOLEAN / JSON`；重复字段名和非法 JSON example 被拒绝。
- 通用配置：`definition.config` 保存严格 JSON 对象；当前不包含凭据引用或绑定字段。
- HTTP：`execution_mode` 只接受 `CONFIG / CODE`；配置结构包含 Method、URL、Headers、Params、Body Type 和 Body；从 CODE 切回 CONFIG 时已保存的 `main.py` 继续保留。
- 仓储：支持显式刷新、列表、读取、创建、整体更新和删除；模板 ID 与目录名一致，ID 和类型创建后不可修改，同 ID 拒绝覆盖。
- 不兼容验证：旧目录只有 `manifest.json + main.py` 时刷新结果明确报告“缺少 definition.json”，不会加载到有效快照；旧 `/api/tools` 返回 404。
- 测试清理：删除旧工具迁移、旧小写类型、六参数 Agent、旧 `/api/tools`、旧 SSE、旧 ZIP 和旧真实模型工具矩阵测试，新增 `tests/test_tool_templates.py`。
- 专项验证：`uv run pytest tests/test_tool_templates.py -q`，结果 `11 passed, 1 warning`。
- 静态验证：`web/tool_templates.py`、`web/routes_tool_templates.py`、`web/app.py` 通过 `py_compile`；`git diff --check` 通过。
- 未覆盖：本步未实现 ZIP 导入导出、模板独立执行、SSE/中断、工具模板前端、画布深拷贝、发布模板和凭据保护，不得把 CRUD 通过解释为完整模板流程通过。
- 依赖结论：Step 4 已通过，可以进入 Step 5 工具模板前端和画布深拷贝；独立执行需要在后续执行器子任务单独验证。

### Step 5：工具模板前端、画布深拷贝和大写状态统一（completed，2026-07-20）

- 目标：提供四类大写工具模板的桌面管理入口，并验证模板复制到画布后成为不依赖来源模板的完整节点副本。
- 前端输出：一级导航改为“工具模板”，提供 `HTTP / AGENT / LLM / SCRIPT` 大写类型创建、筛选、编辑和删除；旧运行中心入口已移除。
- 画布输出：Studio 顶部新增工具模板面板，从 `/api/tool-templates` 加载模板；选择模板时深拷贝 `definition` 和 `main_py`，节点不保存来源模板 ID。
- 节点协议：节点类型统一为 `START / HTTP / AGENT / LLM / SCRIPT / END`；运行状态统一为 `PENDING / RUNNING / PASSED / FAILED`。
- 代码编辑：真实浏览器首次验证发现模板 `main.py` 虽已进入节点对象，但编辑器仍显示旧默认代码；现已改为受控读取和写回节点 `mainPy`，空白 Python 节点默认使用 `response = inputs`，符合 `inputs / config / response` 新协议。
- 独立性验证：通过 UI 创建并保存一个临时 AGENT 模板，复制到画布后确认名称、说明和 `main.py` 正确；在画布中把代码修改为节点专属内容并保存，再通过新 API 删除仓库模板。删除后模板面板显示为空，但画布节点、专属代码和已保存状态仍保留，证明没有运行时来源引用。
- 状态与耗时 E2E：临时画布节点从 `PENDING` 经运行后进入 `PASSED`，耗时从 `0ms` 累加并在完成后冻结为本次实测的 `907ms`；节点右上角只有运行按钮。桌面视口为 `1440x900`，页面横向溢出为 `0px`，截图未发现控件重叠或文本越界。
- 数据清理：E2E 临时模板已通过 `DELETE /api/tool-templates/{id}` 删除；`tool_registry/` 已恢复为只包含 `.gitkeep`。
- 专项验证：`uv run pytest tests/test_tool_templates.py tests/test_tool_templates_frontend.py tests/test_execution_frontend.py tests/test_targets.py tests/test_web_app.py -q`，结果 `51 passed, 1 warning`。
- 构建与静态验证：`npm run build` 成功；`node --check` 覆盖 `app.js`、`tool-templates.js`、`execution.js` 和 Workflow bundle；`git diff --check` 通过。
- 全量回归：`uv run pytest -q`，结果 `85 passed, 1 warning`；warning 为既有 Starlette/httpx 弃用提示。旧真实模型测试已随不兼容旧工具执行协议删除，因此本轮没有 live 跳过项，也不得用本结果宣称新执行器已通过真实模型验证。
- 未覆盖：模板 ZIP 导入导出、模板独立执行、SSE/中断、HTTP CONFIG 执行器、Workflow 持久化、画布发布模板和凭据保护均尚未实现。`web/static/app.js` 中仍有不可达的旧工具管理前端代码，旧 Worker 模块当前也未通过 API 暴露；应在对应替换步骤删除，不能把不可达解释为兼容支持。
- 依赖结论：Step 5 已通过，可以进入 Step 6 四类工具模板 ZIP 导入导出；凭据仓储与绑定继续保留在第 22 节，不作为后续实现前置条件。

### Step 6：四类工具模板 ZIP 导入导出（completed，2026-07-20）

#### Step 6.1：安全归档层与批量原子写入（completed）

- 目标：在不把 ZIP 解压到文件系统的前提下解析和生成统一模板包，并确保任一模板无效或 ID 冲突时整批不写入。
- 输入格式：只允许 `{id}/manifest.json + {id}/definition.json + 可选 {id}/main.py`；一个 ZIP 可以包含一个或多个模板。
- 安全边界：拒绝绝对路径、`..`、反斜杠路径、符号链接、加密条目、重复路径、未知文件、超过 300 个条目、压缩包超过 20 MB、解压后超过 50 MB以及异常压缩比。
- 不兼容规则：根目录旧 `manifest.json + main.py` 和缺少 `definition.json` 的旧 Script / Agent 包均明确拒绝。
- 仓储输出：新增批量创建操作；写入前统一检查包内重复 ID 和仓储现有 ID，写入中异常时删除本批已创建目录并同步回滚内存快照。同名模板仍允许，模板 ID 冲突拒绝覆盖。
- 专项验证：`uv run pytest tests/test_tool_template_archives.py tests/test_tool_templates.py -q`，结果 `18 passed, 1 warning`；覆盖多模板往返、HTTP CONFIG 无 `main.py`、路径穿越、旧布局、未知文件、同 ID 冲突和无部分写入。
- 静态验证：`web/tool_templates.py`、`web/tool_template_archives.py` 通过 `py_compile`；相关文件 `git diff --check` 通过。
- 依赖结论：Step 6.1 已通过，可以开始 Step 6.2 导入导出 API；尚未接入 Web API 和前端按钮。

#### Step 6.2：模板 ZIP 导入导出 API（completed）

- 导入 API：`POST /api/tool-templates/import` 接收单个 `.zip` 文件；先限制读取到 20 MB，再调用安全归档层整包解析和批量原子写入。成功返回导入数量和完整模板列表。
- 导出 API：`POST /api/tool-templates/export` 接收 `template_ids`；非空时只导出指定模板，空列表导出全部。重复请求 ID 去重，任一 ID 不存在时拒绝请求，不生成不完整包。
- ID 规则：导入保留包内模板 ID；目标仓储已有同 ID 时整包返回 400，不覆盖、不自动换 ID。同名但不同 ID 仍允许。
- 往返验证：在源仓储创建 AGENT 和 HTTP 模板，仅导出指定 AGENT 后切换到新的空仓储导入，模板对象与 `manifest.json / definition.json / main.py` 内容保持一致并可由仓储回读。
- 失败验证：含“一个新模板 + 一个冲突模板”的 ZIP 导入返回 400，新模板目录没有产生；旧根目录包和非 `.zip` 文件均返回 400，仓储保持为空。
- 专项验证：`uv run pytest tests/test_tool_template_archives.py tests/test_tool_templates.py -q`，结果 `21 passed, 1 warning`。
- 静态验证：`web/routes_tool_templates.py`、归档层和仓储通过 `py_compile`，相关文件 `git diff --check` 通过。
- 依赖结论：Step 6.2 已通过，可以开始 Step 6.3 工具模板页面导入导出和桌面 E2E。

#### Step 6.3：工具模板页面与 ZIP 往返 E2E（completed）

- 前端输出：工具模板页新增“导入 ZIP”“导出全部”，每行新增仅图标的“导出工具模板”；文件输入支持一次选择多个 ZIP，并逐包累计导入数量和失败原因。
- 安全提示：每次导出前明确提示当前不会自动清理 `config` 或 `main.py` 中的凭据，只能交给可信接收者；凭据仓储、自动剥离和脱敏仍属于第 22 节待优化项。
- 真实流程：在新启动的 8013 服务中通过页面创建 SCRIPT 模板，填写 Inputs、Config、Outputs 和 `main.py`；调用同一真实导出 API 生成标准 ZIP，删除源模板，再调用真实导入 API恢复模板。浏览器刷新后名称、说明、大写类型和四段完整内容均与导出前一致。
- UI 验证：页面显示多 ZIP 导入、导出全部和单模板导出三个入口；`1440x900` 桌面截图未发现控件重叠或文本越界，页面横向溢出小于等于 `0px`。
- 自动化限制：当前浏览器控制层不提供本地文件输入能力，无法自动执行隐藏 `<input type="file">` 的文件选择；真实 ZIP 上传改由同一 8013 服务 API执行，随后由浏览器完成页面回读。文件选择事件绑定由前端专项测试和 JavaScript 语法检查覆盖。
- 数据清理：E2E 模板、临时 ZIP 和 8013 测试服务均已清理；`tool_registry/` 恢复为只含 `.gitkeep`。
- 专项验证：`uv run pytest tests/test_tool_template_archives.py tests/test_tool_templates.py tests/test_tool_templates_frontend.py -q`，结果 `23 passed, 1 warning`。
- 构建与静态验证：`npm run build` 成功；Python `py_compile`、四个相关 JavaScript `node --check` 和 `git diff --check` 均通过。
- 全量回归：`uv run pytest -q`，结果 `95 passed, 1 warning`；warning 仍为既有 Starlette/httpx 弃用提示。
- 未覆盖：模板独立执行、SSE/中断、HTTP CONFIG 执行器、Workflow 持久化、画布发布模板和凭据保护尚未实现。
- 依赖结论：Step 6 已完成，可以进入 Step 7 模板独立执行；ZIP 包格式不再阻塞后续跨环境模板测试。

### Step 7：工具模板独立执行（completed，2026-07-20）

#### Step 7.1：统一可中断执行内核（completed）

- 目标：彻底替换旧 Agent 六参数和 `${...}` 编译协议，让四类模板在进入 Workflow 前即可按新协议真实运行。
- 模块替换：删除 `web/agent_runtime.py` 和 `web/agent_worker.py`；新增通用 `tool_runtime.py`、`tool_worker.py` 和 `tool_execution.py`。
- Python 协议：AGENT、LLM、SCRIPT 以及 HTTP CODE 在独立子进程顶层获得 `inputs`、`config`，并通过顶层 `response` 返回严格 JSON；不再执行旧固定模板参数替换。
- HTTP CONFIG：同样在可终止子进程内使用 httpx 发起真实请求；支持 Method、URL、Headers、Params、RAW、FORM_DATA、FORM_URLENCODED 和 BINARY body，标准 response 包含 `status_code / headers / body`，非 2xx 作为执行失败。
- 运行控制：统一 120 秒默认超时、运行 ID 占用、预中断、进程树终止、stdout/stderr 流式日志和显式 flush；NaN、Infinity、循环引用及不可 JSON 序列化 response 均拒绝。
- 修复记录：首轮测试发现 Windows 子进程协议中文受系统代码页影响，已改为 ASCII JSON 转义传输并在解析后恢复 Unicode；同时修复空 Params 覆盖 URL 原有查询串的问题。
- 专项验证：`uv run pytest tests/test_tool_execution.py tests/test_run_stream.py -q`，结果 `10 passed`；覆盖三类 Python 成功、config 合并、无换行 flush、严格 JSON 失败、超时、中断、真实 HTTP CONFIG 请求、日志顺序/上限和单消费者。
- 静态验证：三个新执行模块通过 `py_compile`，相关文件 `git diff --check` 通过。
- 依赖结论：Step 7.1 已通过，可以开始 Step 7.2 启动、SSE 和中断 API；尚未提供模板页面运行入口。

#### Step 7.2：模板运行启动、SSE 和中断 API（completed）

- 启动：`POST /api/tool-templates/{template_id}/runs` 接收本次 `run_id / inputs / timeout_seconds`，快照当前模板对象后立即返回 `RUNNING`；测试 inputs 和超时不写回模板。
- 日志与结果：`GET /api/tool-templates/runs/{run_id}/events` 使用无回放、单消费者 SSE，按序发送 `log`，终态发送 `complete` 或 `interrupted`；终态包含严格 JSON response、latency 和日志截断标志。
- 中断：`POST /api/tool-templates/runs/{run_id}/interrupt` 调用统一进程树终止；不存在的运行返回 404，重复运行 ID 返回 409。
- 失败协议：用户代码异常、NaN/Infinity 等 response 序列化错误保留 Traceback 日志并以 `ok: false` 完成，不使用旧 `repr()` 回退。
- 专项验证：`uv run pytest tests/test_tool_template_runs.py tests/test_tool_execution.py tests/test_run_stream.py -q`，结果 `13 passed, 1 warning`；覆盖真实 API启动、SSE 日志、成功 response、严格失败、重复 ID、中断和缺失运行。
- 静态验证：路由、事件流和执行模块通过 `py_compile`；相关文件 `git diff --check` 通过。
- 依赖结论：Step 7.2 已通过，可以开始 Step 7.3 模板编辑页独立测试面板和桌面 E2E。

#### Step 7.3：模板独立测试页面、旧执行链清理和 E2E（completed）

- 页面输出：模板编辑页新增“独立测试”区，包含本次 Inputs JSON、运行/中断、`PENDING / RUNNING / PASSED / FAILED` 状态、100ms 累计耗时、实时日志、response 和清空按钮。
- 运行语义：点击运行先保存当前编辑内容但不刷新页面，再启动新 Worker，确保执行眼前版本；测试 Inputs、状态、耗时和日志均不写入模板，刷新后消失。
- 浏览器成功流程：真实 SCRIPT 模板输出 `stream-log`，使用持久 `config.prefix` 和本次 `inputs.question` 生成 `response.answer`；页面实测 `RUNNING → PASSED`，终态耗时 240ms，日志与 response 完整显示。
- 浏览器中断流程：把同一模板改为输出日志后休眠 10 秒，运行中点击中断；页面进入 `FAILED`，耗时冻结约 2.1 秒，运行按钮恢复，中断按钮禁用，Worker 及进程树已终止。
- 桌面布局：`1440x900` 截图确认测试 Inputs 和日志区并排、按钮和状态无重叠，页面横向溢出小于等于 `0px`。
- 彻底清理：删除不可达的旧 `/api/tools` 前端管理、旧 Agent/Script SSE UI、旧工具弹窗、旧 Agent Worker/Runtime；删除只服务旧工具编辑器的 CodeMirror 源码、bundle、测试、npm 依赖和构建步骤。生产源码扫描 `/api/tools`、`agent_runtime`、`agent_worker` 均为零命中。
- E2E 清理：临时模板和 8013 测试服务已删除，`tool_registry/` 只保留 `.gitkeep`。
- 专项验证：执行内核/运行 API/事件流/前端面板结果 `15 passed, 1 warning`；清理后的前端专项结果 `16 passed, 1 warning`。
- 构建与静态验证：`npm run build` 现只构建 Workflow bundle并成功；Python 编译、JavaScript 语法和 `git diff --check` 通过。
- 全量回归：`uv run pytest -q`，结果 `103 passed, 1 warning`；warning 为既有 Starlette/httpx 弃用提示。
- 未覆盖：本步没有真实供应商 API Key，因此只证明新 Python Worker 和本地 HTTP CONFIG 真实请求；不得宣称 DeepSeek/Qwen 新协议 live 矩阵已通过。画布发布模板、Workflow 持久化、DAG 调度、Run 追溯和凭据保护尚未实现。
- 依赖结论：Step 7 已完成，可以开始 Step 8 画布工具发布为独立新模板。

### Step 8：画布工具发布为独立模板（completed，2026-07-20）

#### Step 8.1：独立发布 API 与 API Key 清理（completed）

- 发布契约：`POST /api/tool-templates/publish` 接收完整大写类型、名称、说明、definition 和可选 `main.py`；后端每次生成新的模板 ID，不接受来源模板 ID，不覆盖现有模板，同名允许。
- 独立性：重复发布同一请求生成两个不同 ID 的完整模板，发布对象与当前画布节点及任何来源模板均无运行时引用。
- 秘密处理：发布时递归清空 `config` 中明确命名为 `api_key / apiKey` 的值，保留配置结构；不猜测性修改 Python 代码中的字符串。Authorization、Cookie、Token、其他密码和日志脱敏仍属于待优化范围。
- 校验：请求 `type` 必须与 `definition.type` 一致，Python 类型和 HTTP CODE 继续由 ToolTemplate 模型强制要求 `main.py`。
- 专项验证：`uv run pytest tests/test_tool_templates.py -q`，结果 `13 passed, 1 warning`；覆盖不同 ID、同名、嵌套 API Key 清理、代码保留和类型不匹配无写入。
- 静态验证：发布路由通过 `py_compile`，相关文件 `git diff --check` 通过。
- 依赖结论：Step 8.1 已通过，可以开始 Step 8.2 画布节点定义转换、右键发布和桌面 E2E。

#### Step 8.2：画布右键发布与桌面 E2E（completed）

- 入口：HTTP、AGENT、LLM、SCRIPT 节点右键菜单新增“发布为工具模板”；Start/End 系统节点不显示该命令。节点卡片右上角仍只有运行，编辑器标题栏仍只有运行/保存/关闭。
- 定义转换：模板来源节点优先深拷贝其内嵌 definition；空白节点生成简化 inputs/outputs/config。HTTP 节点把 Headers、Params、Body Type 和 Body 行转换回标准 HTTP definition；Python 节点携带当前 `mainPy`。
- 发布行为：前端只发送完整类型、名称、说明、definition 和 `main_py`，不发送或保存来源模板 ID；发布成功后仅把后端返回的新模板加入当前模板面板缓存，不反向绑定当前节点。
- 风险提示：发布确认明确说明 config API Key 会清空、代码秘密不会自动修改；后端继续作为最终清理边界。
- 浏览器 E2E：在空仓储的 Studio 中右键“规则校验”SCRIPT，确认菜单存在发布项并完成确认；页面显示成功 Toast，模板面板立即出现“规则校验 SCRIPT”。后端回读得到新 UUID、空 inputs/outputs/config 和 `response = inputs`。Start 节点右键菜单只有运行/拷贝/删除，无发布项。
- 清理回归：真实浏览器首次进入 Workflow 时发现 `execution.js` 尚有三个已删除 CodeMirror 销毁函数调用，导致主区为空；已删除残留调用并增加生产前端零引用断言，导航复测通过。
- 数据清理：E2E 发布模板和 8013 测试服务均已删除，`tool_registry/` 只保留 `.gitkeep`。
- 专项验证：`uv run pytest tests/test_execution_frontend.py tests/test_tool_templates.py -q`，结果 `21 passed, 1 warning`；修复导航后 Studio 专项 `8 passed, 1 warning`。
- 构建与静态验证：`npm run build`、Python `py_compile`、JavaScript `node --check` 和 `git diff --check` 全部通过。
- 全量回归：`uv run pytest -q`，结果 `106 passed, 1 warning`；warning 为既有 Starlette/httpx 弃用提示。
- 依赖结论：Step 8 已完成。下一阶段是新版 Workflow 持久化与 DAG 协议；分支/汇合、端口、失败传播、循环和输入映射仍在第 16 节列为未确认业务规则，未确认前不得自行实现执行语义。

### Step 9：发布前全量验收与环境清理（completed，2026-07-20）

- 目标：确认 T13.2 当前已实现范围可构建、可回归且不包含 E2E 临时数据，再提交并推送本次不兼容重构。
- 浏览器清理：恢复临时 `1440x900` 视口覆盖，并清理 `http://127.0.0.1:8013/` 的测试标签页；不影响用户当前 `8012` 服务页面。
- 数据清理：复核 `tool_registry/` 只包含 `.gitkeep`，没有临时模板目录或测试 ZIP。
- 生产构建：`npm run build` 通过，重新生成 Workflow JavaScript/CSS bundle。
- 全量回归：`uv run pytest -q` 结果为 `106 passed, 1 warning`，耗时 3.79 秒；warning 仍为既有 Starlette/httpx 弃用提示。
- 静态检查：生产 Python `compileall`、`app.js / tool-templates.js / execution.js / workflow-canvas.js` 的 `node --check`、常见真实令牌值模式扫描和 `git diff --check` 全部通过；README 中只存在环境变量名和 `<your-key>` 占位示例。
- E2E 覆盖：本阶段已覆盖工具模板 CRUD、ZIP 往返、模板删除后的画布深拷贝、SCRIPT 独立执行、运行中断、画布发布新模板、系统节点禁止发布，以及桌面布局无横向溢出或可见重叠。
- 未覆盖与风险：没有真实供应商 API Key，因此不得宣称新 AGENT/LLM Worker 已通过 DeepSeek/Qwen live 验证；Workflow 持久化、DAG 执行、Run 追溯和独立凭据仓储仍未实现，必须先完成第 16 节业务规则确认。
- 价值验证：新手可从四类模板复制完整定义到画布后少量修改，画布个性化节点也可发布为独立模板；两者无来源绑定，模板删除、更新或同名均不会改变既有画布节点。

### Step 10：模型管理（in progress，2026-07-21）

#### 业务背景与目标（Why）

- Agent Bench 当前需要在 LLM、AGENT 和其他模型调用场景中反复填写供应商连接；本功能集中管理供应商、BASE_URL、API Key 和已选模型，减少重复配置并为后续画布节点选择模型提供稳定数据源。
- 当前阶段不建设供应商插件生态或深度 SDK 适配，只支持 OpenAI-compatible 与 Anthropic 模型发现；Header Override、Body Override 和导入导出继续延后。

#### 用户与真实场景（Who & Where）

- 本机 Workflow / Agent 作者从左侧一级导航进入“模型管理”，搜索和维护已有供应商连接。
- 点击“新增模型”进入独立新增页面，完成测速、获取模型、选择多个模型并保存；编辑时复用同一页面和完整配置。
- 一条记录代表一个供应商连接及其多个已选模型，同名供应商允许由独立 ID 区分。

#### 已确认规则与优先级（What & When）

- P0：供应商列表、新增、编辑、删除、搜索、BASE_URL 测速、模型发现、手工模型兜底和重启后持久化。
- 供应商名称、官网链接选填；API Key、BASE_URL 必填；至少添加一个模型后才能保存。
- API Key 明文保存在本机 SQLite；列表页不展示 Key，编辑页按用户选择完整回显。不得把真实 Key 写入代码、测试、文档、日志或 Git。
- 协议探测复用已验证的 OpenAI Bearer 与 Anthropic `x-api-key` 逻辑；模型端点支持完整版本路径与 `/v1/models`、`/models` 补全。
- Header Override、Body Override、凭据加密/绑定和导入导出不在本批实现范围，继续保留在待优化项。

#### 可独立验证子任务

| 子任务 | 目标 | 输入 | 输出 | 验证方法 | 依赖 |
|---|---|---|---|---|---|
| Step 10.1 | 本地持久化与 API | 已确认字段和模型发现原型 | SQLite Repository；CRUD、测速、模型发现 API | Repository 重启回读；API CRUD；Stub 真实 HTTP；非法 URL/响应和密钥不进入错误信息 | 无 |
| Step 10.2 | 一级导航、列表和新增/编辑页 | Step 10.1 API；独立原型视觉 | 模型管理列表、搜索、独立表单、连接状态、模型选择和删除确认 | 前端契约测试；JS 语法；桌面浏览器新增/编辑/搜索/删除 | Step 10.1 |
| Step 10.3 | 集成验收与发布 | 完成的前后端 | E2E 记录、全量回归、更新计划并推送 | `pytest`、`npm run build`、Python/JS 静态检查、真实浏览器业务流、密钥扫描 | Step 10.1-10.2 |

#### 验收标准与价值验证（How to Measure）

- 左侧“模型管理”可稳定进入，新增按钮打开独立页面，布局与供应商连接原型一致且适配现有明暗主题。
- 使用本地 OpenAI-compatible Stub 完成测速、模型发现、选择多个模型、保存、列表回读、编辑和删除；页面无横向溢出、控件重叠或控制台错误。
- 服务重启后供应商、官网、BASE_URL、完整 API Key 和模型列表保持一致；列表和普通错误响应不泄露 API Key。
- 受影响专项测试、前端构建、静态检查和全量回归全部通过后才能标记完成。

#### Step 10.1：模型供应商持久化与 API（completed）

- 持久化：复用被 Git 忽略的 `run_storage/agent_bench.sqlite3`，新增独立 `model_providers` 表；一条记录保存可选名称/官网、完整 API Key、BASE_URL、协议、模型端点和多个模型。
- API：新增供应商列表、创建、单条读取、完整更新、删除、BASE_URL 测速和模型发现接口；列表与删除响应使用不含 API Key 的摘要，单条编辑接口按已确认的 3B 完整回显。
- 协议探测：支持 OpenAI Bearer 与 Anthropic `x-api-key`，自动处理根 BASE_URL、版本化 `/v1` 路径以及 chat/responses/messages 完整端点；失败允许前端进入手工模型模式。
- 安全边界：BASE_URL 拒绝非 HTTP(S)、内嵌用户名密码、query、fragment 和非法端口；上游错误只返回协议、端点、HTTP 状态或异常类型，不返回请求 Header、响应正文或 API Key。
- 验证：`uv run pytest tests/test_model_providers.py -q` 结果 `13 passed, 1 warning`；覆盖 Repository 重启回读、完整 CRUD、列表密钥剥离、字段校验、端点归一化、真实本地 OpenAI-compatible HTTP 探测和错误密钥扫描。
- 静态检查：新增后端与测试通过 `py_compile`，相关文件 `git diff --check` 通过；warning 为既有 Starlette/httpx 弃用提示。
- 依赖结论：Step 10.1 已通过，可以开始 Step 10.2 前端；尚未接入一级导航或页面。

#### Step 10.2：一级导航、模型列表和新增/编辑页（completed）

- 导航与资产：左侧一级导航新增“模型管理”；新增独立 `model-providers.js/css`，静态资源使用显式无缓存 GET 路由，不把模型业务继续堆入 `app.js`。
- 管理列表：支持新增、刷新、供应商/地址/协议/模型前端搜索、名称进入编辑、官网跳转、协议与模型摘要、更新时间、编辑和删除；API Key 不进入列表响应和 DOM。
- 新增/编辑页：复用供应商连接原型的双列表单、连接状态带、测速、模型发现、下拉选择、手工模型兜底和已选模型列表；增加保存/返回，编辑页按已确认 3B 完整回显 API Key。
- 主题和布局：全部颜色复用现有语义变量并提供协议状态的暗色覆盖；仅实现桌面布局。首次 `1440x900` 截图发现时间内容把操作列推入表格内部滚动区，已改为固定列布局，复测操作按钮完整可见、页面与表格横向溢出均为 0。
- 浏览器 E2E：在 8026 Agent Bench 与 8027 本地 OpenAI-compatible Stub 中完成左侧导航、新增、HTTP 200 测速、发现 3 个模型、选择 `deepseek-chat / qwen-max`、保存、无结果/模型名搜索、编辑页密钥完整回显、名称更新、服务重启后 SQLite 回读和页面删除清理。
- E2E 修复：刷新首页发现既有 `viewSets()` 引用已删除的 `setSortMark` 导致主区为空；补回最小排序标记函数并新增回归测试。全新浏览器标签复测测试集首屏与模型管理均可渲染，控制台错误为 0。
- 专项验证：模型后端、前端、主题和 Web 入口组合结果 `22 passed, 1 warning`；E2E 修复后的集合页/模型页组合结果 `22 passed, 1 warning`；JavaScript/Python 语法和相关 `git diff --check` 通过。
- 数据清理：E2E 模型供应商已从 SQLite 删除；列表恢复为 0 个供应商。8027 Stub 将在最终回归后关闭，8026 Agent Bench 保留为交付服务。
- 依赖结论：Step 10.2 已通过，可以开始 Step 10.3 全量回归、计划收口和发布。

#### Step 10.3：集成验收与发布（completed）

- 全量回归：`uv run pytest -q` 结果 `123 passed, 1 warning`，耗时 12.47 秒；warning 为既有 Starlette/httpx 弃用提示。
- 生产构建：`npm run build` 成功，Workflow JavaScript/CSS bundle 正常生成。
- 静态检查：`execution/`、`web/` 通过 Python `compileall`；`app.js / model-providers.js / tool-templates.js / execution.js` 通过 `node --check`；全仓 `git diff --check` 通过。
- 安全扫描：带令牌边界的真实 `sk-` Key 形态扫描为零命中。初次宽泛扫描命中的 `sk-background / sk-stroke` 均为 Workflow bundle 中 CSS 标识片段，不是凭据。
- 数据与服务：SQLite 中 E2E 供应商数量为 0；本地 Stub 8027 已关闭；集成后的 Agent Bench 服务保留在 `http://127.0.0.1:8026/`，首页与模型管理均返回正常。
- 最终价值验证：用户可以从一级导航集中管理供应商连接，通过 API Key + BASE_URL 自动发现模型或手工添加，保存多个模型并在重启后继续编辑；列表不暴露密钥，编辑页按明确选择完整回显。
- 已知风险：API Key 当前按用户选择在本机 SQLite 明文保存并在编辑页完整回显；任何能访问该本机 Web 页或数据库的用户都可读取。凭据加密、绑定和脱敏仍属于第 22.1 节待优化项。
- 结论：Step 10 全部验收通过，可以提交并推送当前分支。

### Step 11：Workflow 工具内聚与 LLM 模型参数（completed，2026-07-21）

#### 最新业务方向（Why / Who & Where）

- 用户明确提出删除工具管理页面与耦合逻辑，工具节点只在 Workflow 中创建、编辑和保存；此前“工具模板库作为起点、画布发布回模板”的方向被本节最新决策取代。
- Workflow / Agent 作者从模型管理维护供应商连接与模型清单，在 LLM 节点中引用已有模型，不重复填写 API Key 或 BASE_URL。
- LLM 节点的模型选择 UI 参考用户提供的 Dify 截图：顶部搜索、供应商分组折叠、供应商连接状态、模型单选和当前项勾选。
- LLM 节点需要允许用户自行添加高级参数；Header/Body Override 仍属于模型连接层后续能力，不与本批节点参数混为一谈。

#### 行业调研：高级参数与默认值

- Dify 使用供应商/具体模型下发的 `parameter_rules` 动态生成控件，可选参数通过开关决定是否写入；SDK 通用模板为 Temperature `0`、Top P `1`、Presence/Frequency Penalty `0`、Max Tokens `64`，但具体模型可覆盖，例如 `gpt-4o-mini` 把 Max Tokens 改为 `512`，`gpt-5` 则去掉常规采样参数并增加 Reasoning Effort `medium`、Verbosity `medium`、Streaming `true`、Service Tier `auto`。
- n8n 的 OpenAI Chat Model 使用固定 Options 集合：Temperature `0.7`、Top P `1`、Presence/Frequency Penalty `0`、Max Tokens `-1`（不限制）、Timeout `60000ms`、Max Retries `2`、Response Format `text`。
- Langflow OpenAI 组件默认 Temperature `0.1`、Seed `1`、Max Retries `5`、Timeout `700s`，Max Tokens 未设置时传 `None`；同时提供任意 `model_kwargs` 字典作为供应商扩展逃生口。统一 Language Model 组件只保留 Temperature `0.1`、Stream `false` 和可选 Max Tokens。
- Flowise OpenAI Chat 默认 Temperature `0.9`、Streaming `true`；Max Tokens、Top P、Presence/Frequency Penalty、Timeout 和 Stop Sequence 都是可选且不设置默认值。
- 结论：不存在可靠的跨供应商默认参数。Agent Bench 若强行写入平台默认值，会覆盖供应商或具体模型默认行为；当前最稳妥策略是节点默认不发送高级参数，用户显式添加后才持久化和发送。

#### 调研来源

- Dify SDK 参数模板：<https://github.com/langgenius/dify-plugin-sdks/blob/main/src/dify_plugin/entities/model/schema.py>
- Dify `gpt-4o-mini` 与 `gpt-5` 模型 Schema：<https://github.com/langgenius/dify-official-plugins/tree/main/models/openai/models/llm>
- n8n OpenAI Chat Model：<https://github.com/n8n-io/n8n/blob/master/packages/@n8n/nodes-langchain/nodes/llms/LMChatOpenAi/LmChatOpenAi.node.ts>
- Langflow OpenAI / Language Model：<https://github.com/langflow-ai/langflow/tree/main/src/lfx/src/lfx/components>
- Flowise ChatOpenAI：<https://github.com/FlowiseAI/Flowise/blob/main/packages/components/nodes/chatmodels/ChatOpenAI/ChatOpenAI.ts>

#### 专有参数透传补充调研

- `model_kwargs` 是 LangChain 构造参数，不是供应商协议。当前 `ChatOpenAI` 会把 `model_kwargs` 展开为 OpenAI SDK 的顶层调用参数；SDK 未声明的千问/DeepSeek 扩展字段可能直接触发 `TypeError`，通常必须通过 `extra_body` 才能进入 HTTP Body。
- 当前 `ChatAnthropic` 对 `thinking` 和 `output_config` 有显式字段，也会把 `model_kwargs` 合并进请求 payload，但这仍是框架实现细节，不适合作为 Workflow 持久化契约。
- Open WebUI 使用“默认不设置”的标准参数，并在自定义模型管理中提供 `custom_params`；Dify 使用具体模型 Schema 白名单；n8n/Flowise 使用固定 Options；Langflow 使用 `model_kwargs`/`model_kwargs` 字典作为逃生口。它们共同说明 UI 数据应与具体 SDK 解耦。
- Agent Bench 节点字段统一命名为 `modelParameters`：保存原始 JSON 对象。OpenAI-compatible 直连时合并到请求 Body；使用 OpenAI SDK 的用户代码可将其传给 `extra_body`；Anthropic 已知字段可直接展开，未知网关字段可走 SDK 的 `extra_body`。不得把持久化字段命名为 `model_kwargs`。
- 千问 `enable_thinking / thinking_budget`、DeepSeek `thinking / reasoning_effort`、Anthropic `thinking / output_config` 都可以由该 JSON 数据结构表达；最终能否生效仍由所选供应商、模型和协议端点决定，平台不伪造兼容保证。

#### 已确认决策（1A / 2B / 3A）

- 彻底删除工具模板仓储、CRUD/ZIP/独立运行 API、左侧工具模板页面、画布模板面板、深拷贝和发布入口；不保留隐藏后台兼容。通用 Worker、进程中断和运行流内核保留，供后续 Workflow 节点执行复用。
- LLM 高级参数只提供一个任意 JSON 对象编辑器，不提供 Temperature 等固定快捷控件；默认值为 `{}`，平台不主动向供应商发送任何高级参数。
- Token 消耗默认无平台上限：基础请求不发送 `max_tokens` 或 `max_completion_tokens`，由供应商和模型自身上限处理；用户需要限制时可在节点 `modelParameters` 中显式添加。
- LLM 节点只保存 `provider_id + model_name` 和节点自己的高级参数，不复制 API Key、BASE_URL 或完整供应商记录。供应商或模型被删除后，节点显示“模型已失效”并要求重新选择。
- 模型选择器采用用户截图结构：顶部搜索、供应商分组折叠、绿色连接状态、模型单选和当前模型勾选。
- 最新确认采用模型网关式 Body 合并：基础请求、模型级默认参数和节点 `modelParameters` 递归合并，越靠近节点的值优先；数组和非对象值整体替换。
- 用户选择 `1B / 2A`：节点参数可以覆盖包括 `model`、`messages`、`stream` 在内的全部基础请求字段；嵌套对象递归合并，不设置保留字段白名单。

#### 可独立验证子任务

| 子任务 | 目标 | 输入 | 输出 | 验证方法 | 依赖 |
|---|---|---|---|---|---|
| Step 11.1 | 删除工具模板后端和页面 | 1A；现有模板仓储/API/UI | 模板文件、路由、导航、ZIP/运行测试全部删除；通用 Worker 保留 | `/api/tool-templates` 与静态资产 404；生产源码零引用；Worker 专项通过 | 无 |
| Step 11.2 | 删除画布模板耦合 | Step 11.1；当前 React Flow Studio | 顶部模板面板、加载/深拷贝、发布菜单与 API 调用删除；四类空白节点保留 | 前端源码断言、构建、Studio 基线回归 | Step 11.1 |
| Step 11.3 | LLM 模型引用与高级 JSON | 模型管理列表 API；2B/3A；用户 UI 参考 | 分组模型选择器、失效态、`providerId/modelName/modelParameters` 节点状态 | 模型列表加载、搜索/折叠/选择、JSON 校验、删除后失效测试 | Step 11.2 |
| Step 11.4 | 集成验收与发布 | 完成的清理和 LLM 编辑器 | E2E、全量回归、计划收口和 GitHub 提交 | 1440x900 浏览器 E2E、构建、静态检查、全量 pytest、密钥扫描 | Step 11.1-11.3 |

#### Step 11.1：删除工具模板后端和一级页面（completed）

- 删除范围：删除模板 Pydantic/目录仓储、ZIP 归档、CRUD/刷新/导入导出/发布/独立运行 API、模板运行适配器、左侧页面与脚本、迁移脚本、`tool_registry/` 占位和全部模板专项测试；不保留隐藏 API 兼容。
- 保留范围：保留 `tool_runtime.py / tool_worker.py / run_stream.py` 作为 Workflow 节点通用子进程、HTTP、进程中断和 SSE 流内核；模块文案已去除“模板”语义。
- 内核测试重写：`test_tool_execution.py` 不再构造 ToolTemplate，直接发送通用 Worker payload；继续覆盖 Python `inputs/config/response`、无换行 flush、NaN/Infinity、超时、中断和真实 HTTP 请求。
- 页面与文档：删除左侧“工具模板”、`tool-templates.js` 静态路由和专属 CSS；README 与 `.gitignore` 删除 `tool_registry` 说明和规则。
- 专项验证：`uv run pytest tests/test_tool_execution.py tests/test_run_stream.py tests/test_tool_removal.py tests/test_web_app.py -q` 结果 `13 passed, 1 warning`；Python 编译和 `git diff --check` 通过。
- 零引用验证：除下一步待处理的 React Flow 画布源码/CSS 和构建产物外，`web/ execution/ README.md / .gitignore` 对 `tool-template / ToolTemplate / tool_registry / viewToolTemplates` 零命中。
- 依赖结论：Step 11.1 已完成，可以开始 Step 11.2 画布模板耦合删除。

#### Step 11.2：删除画布模板耦合（completed）

- 删除范围：React Flow Studio 顶部“工具模板”入口、模板加载状态和 `/api/tool-templates` 请求、模板深拷贝、发布方法、右键“发布为工具模板”操作及全部专属样式均已删除。
- 保留范围：`HTTP / AGENT / LLM / SCRIPT` 四类空白节点的新增、编辑、复制、连线、状态演示和历史操作继续保留。
- 构建验证：`npm run build` 成功，重新生成 `workflow-canvas.js / workflow-canvas.css`，`node --check web/static/assets/workflow-canvas.js` 通过。
- 专项验证：`uv run pytest tests/test_execution_frontend.py tests/test_tool_removal.py -q` 结果 `10 passed, 1 warning`；`git diff --check` 通过。
- 零引用验证：`web/ execution/ README.md / .gitignore` 以及生成资源对工具模板标识和显示文案零命中。
- 依赖结论：Step 11.2 已完成，可以开始 Step 11.3 LLM 模型引用、任意 JSON 参数和网关式递归合并。

#### Step 11.3：LLM 模型引用、高级 JSON 与网关合并（completed）

- 网关内核：新增与 LangChain 解耦的 OpenAI-compatible 请求组装与 HTTP 传输；合并顺序为“基础请求 → 模型默认参数 → 节点 `modelParameters`”，后层优先，对象递归合并，数组和标量整体替换。
- Token 默认：基础请求不包含 `max_tokens` 或 `max_completion_tokens`，Agent Bench 默认不限制 token 消耗；节点显式填写时仍按普通高级参数合并并透传。
- 覆盖边界：按已确认的 `1B / 2A`，节点参数可覆盖 `model`、`messages`、`stream` 及任意其他 Body 字段，平台不维护保留字段白名单，也不翻译供应商专有参数。
- 节点状态：LLM 节点只保存 `providerId / modelName / modelParameters`；API Key、BASE_URL 和供应商完整记录仍由模型管理持有，不进入 Workflow 节点状态。高级参数默认为空对象 `{}`。
- 选择器 UI：接入不含密钥的 `/api/model-providers` 列表，实现供应商分组、搜索、折叠、连接状态、当前模型勾选和刷新；供应商或模型删除后显示“模型已失效”并禁用节点保存/运行。
- JSON 编辑：使用任意 JSON 对象编辑器；非法 JSON 或顶层非对象时显示明确错误并禁用保存/运行，修复为合法对象后即恢复。
- 自动化验证：`uv run pytest tests/test_model_gateway.py tests/test_execution_frontend.py tests/test_tool_removal.py -q` 结果 `25 passed, 1 warning`；`npm run build`、生成 bundle 的 `node --check` 和 `git diff --check` 全部通过。
- 真实浏览器 E2E：在 `1440x900` 下验证 DeepSeek 选择、搜索过滤、当前项选中、供应商折叠、非法/合法 JSON 切换和无裁切重叠；通过创建临时供应商、选择、删除并刷新，实测“模型已失效”与禁用状态，临时数据已清理。
- 范围约束：新网关内核已可独立真实调用，但新 Workflow Studio 仍是前端本地状态和演示运行，本步没有实现 Workflow 持久化或 DAG 真实执行 API，不得宣称画布端到端模型执行已完成。
- 真实模型验证：新增受 `live` marker 控制的网关集成测试，固定覆盖千问 `qwen3.7-max` 和 DeepSeek `deepseek-v4-pro`；未注入环境变量时安全跳过，不影响公开回归。为验证稳定性，每个模型顺序执行两轮真实请求。
- 真实业务场景：测试使用企业客服 Agent 合规评测，输入用户退款问题、三条明确策略以及一段“未授权即宣称退款完成，并索取身份证、银行卡和验证码”的高风险回复；要求模型输出包含 `passed / score / summary / issues / recommendation` 的严格 JSON。
- 真实调用结果：使用用户提供的两家凭据仅在 pytest 进程内执行 `uv run pytest tests/test_model_gateway.py tests/test_model_gateway_live.py -m live -q`，结果 `4 passed, 4 deselected in 25.22s`。千问和 DeepSeek 各两轮均返回可解析且字段完整的 JSON，均稳定判定该 Agent 回复不通过并输出具体问题和改进建议。
- 覆盖价值：live 请求故意在基础层放入错误模型、错误消息和 `stream: true`，再由节点参数覆盖为真实模型、完整的 system/user 业务消息和 `stream: false`；模型默认层的 `response_format: {"type": "json_object"}` 被保留，千问同时直透 `enable_thinking: false`。四次请求均明确断言不存在 `max_tokens / max_completion_tokens`。
- 密钥边界：API Key 未写入测试、文档、代码、命令输出或 Git 跟踪文件；DeepSeek 密钥从本机模型仓储读入子进程，千问密钥只注入单次 pytest 进程。
- 依赖结论：Step 11.3 及两家真实模型验证已完成，可以进入 Step 11.4 全量回归与发布。

#### Step 11.4：集成验收与发布（completed）

- 业务验收：工具管理一级页面、仓储、CRUD/ZIP/独立运行 API、画布模板面板、深拷贝和发布入口均已删除；`HTTP / AGENT / LLM / SCRIPT` 节点继续由 Workflow Studio 直接创建和编辑。
- LLM 交互验收：`1440x900` 真实浏览器覆盖模型列表加载、搜索、供应商折叠、当前项勾选、DeepSeek 选择、非法/合法高级 JSON、删除供应商后的失效态和禁用操作；截图无裁切、重叠或文本越界。
- 真实模型回归：千问 `qwen3.7-max` 和 DeepSeek `deepseek-v4-pro` 各连续两轮企业 Agent 合规评测，结果 `4 passed, 4 deselected in 25.22s`；全程不发送 token 上限，两家均稳定返回字段完整且业务判定正确的结构化 JSON。
- 全量回归：`uv run pytest -q` 结果 `100 passed, 4 skipped, 1 warning in 11.47s`；4 个跳过项为默认未注入两家凭据时的两轮 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 构建与静态检查：`npm run build` 成功生成 Workflow JS/CSS bundle；`execution/` 和 `web/` Python `compileall`、`app.js / model-providers.js / execution.js / workflow-canvas.js` 的 `node --check`、`git diff --check` 全部通过。
- 清理与安全：生产源码对 `tool-template / ToolTemplate / tool_registry / viewToolTemplates` 零引用；Git 跟踪及待提交文件中的真实 `sk-` 凭据形态扫描为 0；失效引用 E2E 临时供应商已删除。
- 已知边界：模型网关的请求组装、递归合并和真实 HTTP 传输已验证；画布仍为前端本地草稿与演示运行，尚未把该网关接入 Workflow 持久化和 DAG 执行后端，因此不宣称 Workflow 端到端真实 LLM 执行已完成。
- 价值结论：Workflow 作者可在 LLM 节点引用已管理模型，使用任意 JSON 直透国内外供应商参数，节点优先覆盖模型默认值，并在默认情况下不受 Agent Bench token 上限限制。
- GitHub 发布：主体改造提交为 `8e8b072`（`Remove tool templates and add model gateway`），已推送到 `origin/codex/tool-template-refactor`。

### Step 12：LLM 真实执行、持久化日志与编辑器收敛（in progress，2026-07-21）

#### 业务背景与目标（Why）

- LLM 节点已能选择模型和编辑高级参数，但当前仍存在不属于网关执行器的 Python“代码”页签、与日志重复的独立“参数”页签，且运行仍是 900ms 前端演示，无法支持真实调试。
- 本阶段目标是让 Workflow 作者在 LLM 节点内完成真实模型验证，并在页面刷新后仍能追溯该节点最近 10 次的输入、输出和错误。

#### 用户与真实场景（Who & Where）

- Workflow / Agent 作者在画布双击 LLM 节点，选择已管理模型，填写可选系统提示词和用户提示词模板，可在模板中以 `${变量名}` 引用 Workflow 变量。
- 作者可在系统提示词为空、高级参数为 `{}` 时直接运行节点；用户提示词解析后必须非空，未解析变量必须在发起供应商请求前失败。
- 作者切换到“日志”后，先扫描月日时间、终态、耗时和最终结果摘要，再按需展开某次运行查看完整输入快照、无密钥请求、输出、usage、HTTP 元数据或错误堆栈。

#### 已确认规则与优先级（What & When）

- `1A`：LLM 编辑器删除“代码”和独立“参数”页签，只保留“设置 / 日志”；原参数快照合并到每次日志详情。AGENT / SCRIPT 的代码能力不受影响。
- `2A`：系统提示词和用户提示词放在设置页模型选择之后，系统提示词选填；用户提示词支持 `${变量名}`，单节点验证时从 Workflow 全局变量解析。
- `3B`：Workflow 草稿、节点 ID 和运行日志保存到本机 SQLite，浏览器刷新后可恢复；每个 Workflow 节点只保留最近 10 次尝试，成功和失败都计入，第 11 次完成后删除最旧记录。
- 日志最新确认 `1A`：执行器仍解析模型输出供节点结果和下游使用，但日志展开区不对供应商响应做结构化拆分，只原样打印完整 HTTP Body/SSE；失败时原样打印已脱敏错误与 traceback。
- 变量祖先规则 `1A`：“之前节点”以画布边反向可达的所有祖先节点为准，与画布 x/y 位置无关；未连接到当前节点的分支变量不可见。
- 原生数据契约：阻塞执行的 `request` 是节点实际发出的原生请求数据，`response` 是节点收到的原生响应数据，平台不注入固定 `body / output / usage` 包装字段。输出变量从这两个根对象提取，例如 `request.messages[0].content` 或 `response.usage[total_tokens]`。
- 提取语法：所有 `HTTP / LLM / AGENT / SCRIPT` 节点统一使用受限 Python 风格路径；支持点访问、整数数组下标和字符串字典键，`response.usage["total_tokens"]`、`response.usage['total_tokens']`、`response.usage[total_tokens]` 等价。禁止函数调用、运算、切片及任意代码执行，路径缺失时节点失败并报告完整表达式。
- 列表过滤：支持 `response.data[id==3]`、`response.data[status=="PASSED"].result` 和嵌套条件 `response.data[meta.id==3].name`；条件只支持 `==` 与标量值。过滤结果必须唯一，0 条或多条均失败，不静默取第一条。
- 流式边界 `1A`：流式模式只实时展示并持久化供应商原始 SSE，不解析流式响应、不构造可提取的 `response`、不生成输出变量；页面隐藏输出变量配置但保留草稿值，切回默认阻塞模式后恢复。
- 变量冲突规则 `3A`：全局变量、当前节点输出变量及当前节点全部祖先输出变量在可见范围内禁止同名；草稿保存时直接拒绝并指明冲突节点。不会汇合到同一下游的隔离分支可以使用相同名称。
- 变量面板：每个节点编辑器右上角增加变量按钮，按“全局变量 → 祖先节点 → 当前节点”分组显示变量名和最近成功运行值；未产生值时显示空值状态。
- 参数替换：`${变量名}` 扩展到节点所有字符串参数，字符串值原样替换，对象/数组以 JSON 序列化后嵌入；缺失变量在执行前失败并记录日志。当前阶段首先在已具备真实执行器的 LLM 节点验证，其他节点仍不伪造真实执行结果。
- 提示词交互：用户直接键入 `${变量名}`；删除用户提示词旁的“插入变量”下拉框，节点右上角变量查看按钮继续用于核对可见变量和值。
- 日志安全：API Key、Authorization 和完整供应商记录不得进入 Workflow 草稿或运行日志；日志中的请求 Body 仅包含实际模型请求字段。
- Token 规则不变：平台默认不发送 `max_tokens / max_completion_tokens`，真实节点运行不增加隐式 token 上限。
- 本阶段只建立 Workflow Studio 草稿与 LLM 单节点运行协议，不自行补全 DAG 调度、分支/汇合、失败传播或其他节点的真实执行语义。

#### 验收标准与价值验证（How to Measure）

- LLM 编辑器只显示“设置 / 日志”；设置页依次显示模型、系统提示词、用户提示词、高级参数、运行配置和输出变量，在 `1440x900` 桌面视口无遮挡、重叠或文本越界。
- 有效模型 + 非空用户提示词在空系统提示词和 `{}` 高级参数下可真实运行；`${变量名}` 正确替换，缺失变量产生可追溯的 `FAILED` 记录且不请求供应商。
- 日志折叠栏显示 `MM-DD HH:mm:ss`、`PASSED / FAILED`、耗时和最终结果摘要；展开后能看到完整输入、请求、执行事件、输出、usage 或错误。
- 同一节点制造 11 次运行后 API 和页面均只返回最新 10 次；重启 Repository、刷新页面和重新打开 Workflow 后记录不丢失。
- 千问 `qwen3.7-max` 和 DeepSeek `deepseek-v4-pro` 需要用真实业务提示词完成节点 API 和页面回读验证；不使用短 token 限制或仅回固定字符串的形式化测试。

#### 可独立验证子任务

| 子任务 | 目标 | 输入 | 输出 | 验证方法 | 依赖 |
|---|---|---|---|---|---|
| Step 12.1 | 草稿与日志持久化 | 当前 React Flow 节点/边；3B | SQLite Workflow draft + node run repository、CRUD/日志 API | Repository 重启回读、11 留 10、级联删除、API 严格校验 | 无 |
| Step 12.2 | 真实 LLM 单节点执行 | Step 12.1；模型管理；`${变量名}` | 变量解析、网关请求、非流式/流式响应解析、PASSED/FAILED 持久化日志 | Stub 真实 HTTP、缺变量无上游请求、错误/输出/usage、无密钥 | Step 12.1 |
| Step 12.3 | LLM 布局与前后端联调 | Step 12.1-12.2；1A/2A/3B | 两页签编辑器、草稿保存/恢复、真实运行、10 条可展开日志 | 前端契约、构建、`1440x900` 浏览器 E2E、刷新回读 | Step 12.1-12.2 |
| Step 12.4 | 真实模型、全量回归与发布 | 完成的 LLM 单节点链路 | 千问/DeepSeek 记录、计划收口、GitHub 提交 | live 业务场景、全量 pytest、构建、静态/密钥扫描 | Step 12.1-12.3 |

#### Step 12.1：Workflow 草稿与节点日志持久化（completed）

- 仓储：新增独立 `workflow_drafts / workflow_node_runs` SQLite 表和 `WorkflowDraftRepository`；草稿保存名称、说明、React Flow 节点/边及全局变量，不恢复旧 Workflow/Run 固定拓扑协议。
- 图校验：节点和边 ID 必须非空且唯一，节点 `data` 必须为对象，边的 source/target 必须引用存在节点，Pydantic 继续拒绝未知顶层字段。
- 运行记录：每条记录保存节点/模型身份、输入快照、无密钥请求 Body、事件、输出、usage、HTTP 元数据和结构化错误；终态写入与同节点裁剪在同一事务完成，最多保留 10 条。
- API：新增 `/api/workflow-drafts` 列表/CRUD、单条读取和 `/{workflow_id}/nodes/{node_id}/runs` 日志列表；删除草稿时通过 SQLite 外键级联删除所有节点记录。
- 验证：`uv run pytest tests/test_workflow_drafts.py tests/test_targets.py tests/test_model_providers.py -q` 结果 `48 passed, 1 warning in 9.52s`；覆盖 Repository 重启回读、11 次仅留最新 10 次、FAILED 记录、级联删除、完整 API CRUD 和非法图拒绝。Python 编译和 `git diff --check` 通过。
- 依赖结论：Step 12.1 已通过，可以在该持久化契约上实现 Step 12.2 真实 LLM 单节点执行。

#### Step 12.2：真实 LLM 单节点执行（completed）

- 执行入口：`POST /api/workflow-drafts/{workflow_id}/nodes/{node_id}/runs` 只从已保存草稿读取 LLM 节点和全局变量，不接受客户端另外传入的模型、Prompt 或凭据，避免“页面配置”与“实际执行”两套事实。
- 变量解析：用户提示词支持已确认的 `${变量名}`；字符串原样替换，其他 JSON 值序列化后替换。缺失变量、变量重名或解析后空 Prompt 都在请求供应商前失败，并持久化 `FAILED` 记录。
- 真实请求：后端按 `providerId / modelName` 从本机模型管理获取 BASE_URL 和 API Key，系统提示词非空时才加入 messages，用户提示词必须存在，`modelParameters` 继续可覆盖任意 Body 字段。
- 响应解析：新增 OpenAI-compatible 非流式 JSON 与缓冲 SSE `data:` 响应解析，支持合并 `content / reasoning_content`、usage 和 finish reason；没有任何隐式 `max_tokens / max_completion_tokens`。
- 真实日志：运行开始即写入 `RUNNING`，最终更新为 `PASSED / FAILED`；记录变量解析、模型请求、HTTP 结果和输出事件，并保存输入快照、无密钥请求 Body、完整输出、usage、request ID 或结构化错误/堆栈。
- 密钥保护：响应错误、异常和 traceback 写入前执行已知 API Key 值与 Bearer 字段脱敏；节点请求和 API 返回均不包含 Authorization。
- Stub 验证：`uv run pytest tests/test_model_gateway.py tests/test_llm_node_runs.py tests/test_llm_node_runs_live.py tests/test_workflow_drafts.py -m 'not live' -q` 结果 `14 passed, 2 deselected, 1 warning in 1.64s`；覆盖真实本地 HTTP、空系统提示词/空高级参数、变量替换、usage/request ID、缺变量零上游请求、HTTP 429、密钥脱敏和 SSE 合并。
- 真实模型验证：使用用户提供的千问 `qwen3.7-max` 和 DeepSeek `deepseek-v4-pro` 凭据仅在 pytest 进程内执行新节点 API，结果 `2 passed, 1 warning in 12.81s`。两家均以空系统提示词、`${agent_answer}` 真实业务变量和无 token 上限完成企业 Agent 合规评测，返回正确结构化结果并通过日志 API 完整回读。
- 静态与安全验证：Python 编译、`git diff --check` 和待提交文件真实 `sk-` 形态扫描通过，密钥文件命中数为 0。
- 依赖结论：Step 12.2 已通过，可以开始 Step 12.3 LLM 布局收敛、草稿恢复和真实日志前端。

#### Step 12.2A：统一原生请求/响应提取规则（completed，2026-07-22）

- 解析器：新增节点类型无关的受限 Python 风格路径解析器，只允许 `request / response` 根、点访问、字符串键和整数下标，不使用 `eval()`。
- 字符串兼容：双引号、单引号和无引号标识符键等价；纯整数（含负数）保持数组下标语义，带引号的数字仍是字符串字典键。
- 失败规则：未知根对象、函数调用、切片、非法键、缺失键、越界下标和不可继续访问的标量均明确失败，错误包含完整提取表达式。
- 通用性验证：`uv run pytest tests/test_workflow_variables.py -q` 结果 `17 passed`；覆盖所有四类可执行节点共用同一 `extract_output_variables` 契约。
- 依赖结论：统一解析器验证通过，下一项将 LLM 阻塞执行改为原生 `request / response`，并移除流式响应解析和流式输出变量。

#### Step 12.2B：列表条件提取（completed，2026-07-22）

- 语法：在统一路径解析器中加入安全过滤 token，支持数组元素字段、嵌套字段、数字/布尔/null/字符串比较和过滤后继续点访问。
- 唯一性：`response.data[id==3]` 必须恰好匹配一条；空结果和重复结果均持久化为执行失败，错误报告表达式和匹配数量。
- 验证：`uv run pytest tests/test_workflow_variables.py -q` 结果 `24 passed`，同时覆盖 `HTTP / LLM / AGENT / SCRIPT` 共用输出映射契约。
- 依赖结论：列表过滤规则已确认并通过验证，可以接入 LLM 原生请求/响应运行契约。

#### Step 12.2C：LLM 原生请求/响应与流式边界（completed，2026-07-22）

- 阻塞执行：变量提取上下文改为实际发送的 `request_body` 和供应商成功响应 JSON；原始响应文本仅用于日志，不再伪装成 `response.body` 包装字段。
- 流式执行：删除缓冲 SSE 的模型解析、usage/最终内容拼接和输出变量提取；运行记录的 `response_body`/`output` 均为脱敏后的完整原始 SSE，`output_variables` 为空。
- 模式强制：阻塞端点固定发送 `stream: false`，流式端点固定发送 `stream: true`，避免高级 JSON 与端点模式不一致。
- 变量面板：跳过没有输出变量的祖先节点，只保留全局变量、有输出变量的祖先和当前节点。
- 验证：`uv run pytest tests/test_workflow_variables.py tests/test_llm_node_runs.py tests/test_workflow_drafts.py tests/test_model_gateway.py -q` 结果 `43 passed, 1 warning`。
- 依赖结论：后端契约通过，可以进入前端交互收敛和真实浏览器流式回归。

#### Step 12.3A：提示词与流式开关交互（completed，2026-07-22）

- 提示词：删除用户提示词旁的变量插入按钮，用户直接输入 `${变量名}`；右上角变量查看按钮仍保留。
- 输出开关：使用单个默认关闭的 `role=switch` 控件；高级参数编辑器隐藏 `stream` 字段，切换开关是唯一输出模式入口。
- 输出变量：LLM 流式模式隐藏输出变量配置，保留草稿数据；切回阻塞模式后恢复配置，阻塞模式显示“提取表达式”字段。
- 验证：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py tests/test_workflow_variables.py tests/test_llm_node_runs.py tests/test_workflow_drafts.py -q` 结果 `46 passed, 1 warning`。
- 依赖结论：前端交互收敛通过，下一步进行真实浏览器的默认阻塞和流式端到端验证。

#### Step 12.3B：输出变量类型与过滤比较（completed，2026-07-22）

- 类型契约：所有节点输出映射统一支持大写 `AUTO / STRING / INTEGER / NUMBER / BOOLEAN / OBJECT / ARRAY`；旧映射缺省为 `AUTO`，保存时拒绝未知类型。
- 转换时机：先按 `request / response` 原生路径提取，再执行目标类型转换，最后写入运行记录和下游变量；`null` 对所有类型保持 `null`。
- 严格转换：`STRING` 使用 JSON 语义序列化非字符串值；`INTEGER / NUMBER / BOOLEAN` 拒绝不安全的隐式转换；`OBJECT / ARRAY` 接受原生对象/数组或合法 JSON 字符串；转换失败使节点 `FAILED`，错误包含变量名和目标类型。
- 过滤器：统一路径过滤增加 `< / > / <= / >= / == / != / contain`；`contain` 仅支持字符串子串，比较不自动做日期解析或跨类型强制转换；仍只允许一个条件且必须唯一命中。
- 验证：`uv run pytest tests/test_workflow_variables.py tests/test_llm_node_runs.py tests/test_workflow_drafts.py -q` 结果 `70 passed, 1 warning`。
- 依赖结论：类型转换和过滤器后端契约已通过，可以接入所有节点的输出变量编辑 UI。

#### Step 12.3C：输出变量类型编辑器（completed，2026-07-22）

- 通用布局：`HTTP / LLM / AGENT / SCRIPT` 共用输出变量行调整为“变量名｜类型｜提取表达式｜操作”，类型下拉固定提供 `AUTO / STRING / INTEGER / NUMBER / BOOLEAN / OBJECT / ARRAY`。
- 默认与兼容：新增输出变量默认 `AUTO`；旧草稿缺少 `type` 时按 `AUTO` 展示和执行，不需要数据迁移。
- 流式边界：LLM 流式模式继续隐藏整组输出变量配置并保留草稿，阻塞模式恢复后可编辑目标类型。
- 日志修复：运行中的流式记录不再显示 `undefined`，未收到数据时显示“正在接收原始响应…”，收到数据后显示原始片段摘要。
- 验证：`uv run pytest tests/test_execution_frontend.py tests/test_workflow_variables.py tests/test_llm_node_runs.py tests/test_workflow_drafts.py -q` 结果 `78 passed, 1 warning`；`npm run build` 成功生成最新 Workflow JS/CSS bundle。
- 依赖结论：前后端类型配置已通过专项验证，可以进入浏览器持久化、真实模型和全量发布回归。

#### Step 12.3D：流式输出标题与对齐（completed，2026-07-22）

- 交互文案：LLM 设置页的输出开关标题由“输出方式”统一改为“流式输出”，开关旁不再重复显示文字，仅保留可访问的 `aria-label`。
- 布局：标题显式左对齐，开关保持独立控件，避免重复文案导致的视觉拥挤；默认关闭和流式模式语义不变。
- 验证：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py -q` 结果 `8 passed, 1 warning`；`git diff --check` 通过。
- 浏览器验收：在当前持久化 Workflow 的 LLM 编辑器实测仅出现一处“流式输出”，旧“输出方式”文案计数为 0，`role=switch` 控件计数为 1；标题左对齐 CSS 已加载生效，开关语义未改变。
- 反馈修正：标题增加 `font-weight: 600`，设置 `min-height: 19px`、`display: flex` 和 `align-items: center`，与开关轨道保持同高并垂直对齐；专项前端测试更新为 `8 passed, 1 warning`，构建重新成功。
- 依赖结论：标题调整已通过专项验证，可以继续进行浏览器端到端和发布回归。

#### Step 12.3E：输出类型真实浏览器端到端（completed，2026-07-22）

- 配置：在持久化 Workflow 的 DeepSeek LLM 节点中，将 `llm_output` 设为 `STRING`，新增 `token_count | INTEGER | response.usage.total_tokens`，通过节点保存入口持久化。
- 真实执行：使用本机模型管理中的 `deepseek-v4-pro` 完成一次阻塞运行，终态 `PASSED`、耗时 `7441ms`；`llm_output` 为原生字符串，`token_count` 为 `Int64=427`，与 `usage.total_tokens=427` 完全一致。
- 日志与回读：原始响应日志长度为 `1326` 字符，未因输出提取做结构化替换；草稿 API 回读确认两行类型分别持久化为 `STRING / INTEGER`，表达式保持不变。
- 价值结论：已用真实供应商响应证明“提取 → 类型转换 → 保存变量 → 草稿恢复”的完整链路可用，而非仅依赖 Stub 或静态前端断言。

#### Step 12.3F：节点变量值复制（completed，2026-07-22）

- 使用场景：Workflow 作者查看全局、祖先和当前节点变量时，可直接复制完整变量值用于参数填写、提取表达式调试或与原始日志核对。
- 交互：变量面板改为“变量名｜变量值｜操作”三列；每条有值变量提供独立复制图标和变量名工具提示，尚无值时按钮禁用。
- 数据语义：字符串复制原值，对象/数组复制格式化 JSON；复制内容不受列表中的单行省略显示影响。优先使用 Clipboard API，并保留本机浏览器兼容回退；成功或失败均显示提示。
- 验证：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py -q` 结果 `8 passed, 1 warning`；`git diff --check` 通过。
- 浏览器验收：刷新最新 bundle 后，当前节点的 `llm_output / token_count` 均出现唯一复制按钮；点击 `token_count` 后页面真实显示“已复制变量 token_count”，未读取系统剪贴板内容。
- 依赖结论：变量值复制前端契约已通过，可以进入真实页面交互回归。

#### Step 12.3G：复制权限失败兼容（completed，2026-07-22）

- 问题复现：部分嵌入式浏览器会暴露 `navigator.clipboard`，但在实际点击时拒绝写入权限；原逻辑在该情况下直接失败，未尝试兼容路径。
- 修复：Clipboard API 写入失败后自动降级到聚焦隐藏文本框、选中完整内容并执行 `document.execCommand('copy')`；资源版本号递增，确保浏览器加载最新 bundle。
- 验证：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py -q` 结果 `8 passed, 1 warning`；浏览器刷新后点击 `复制变量值 token_count`，剪贴板实际读回本次运行的 `1426`，并显示“已复制变量 token_count”。
- 依赖结论：复制按钮已覆盖 Clipboard API 正常、权限拒绝降级和对象/数组格式化语义，可继续最终全量回归。

#### Step 12.3H：节点编辑器窗口与浏览器缩放（completed，2026-07-22）

- 业务目标：用户缩小节点编辑器时保留更多画布上下文，放大时提高提示词、代码和日志的可读性；浏览器整体缩放必须继续同步作用于编辑器字体。
- 窗口缩放：以节点编辑器本次打开时的尺寸为 `1.0` 基准，拖动八向缩放手柄时按宽高比例中的较小值连续缩放编辑器全部文字与控件，限制在 `0.75–1.35`，避免最小窗口不可读和最大窗口内容溢出。
- 浏览器缩放：不接管或抵消浏览器原生缩放；编辑器内部比例与浏览器缩放倍率叠加，重新打开或刷新时均以当时视口建立新的 `1.0` 基准。
- 专项验证：`npm run build` 成功；`uv run pytest tests/test_execution_frontend.py -q` 结果 `8 passed, 1 warning`。
- 浏览器 A 验收：编辑器基线 `1064x896`、标题可视高度 `18px`；放大到 `1172x1001` 后比例 `1.065`、标题高度 `19.17px`；缩小到 `952x811` 后比例 `0.865`、标题高度 `15.57px`；内容容器 `scrollWidth == clientWidth`，无横向溢出。
- 浏览器 B 验收：未对页面添加自定义浏览器缩放拦截或反向补偿；编辑器的内部缩放比例只由 Rnd 八向拖拽回调改变，浏览器缩放由浏览器原生作用于整个编辑器，刷新时重新建立当前视口的 `1.0` 基准。桌面浏览器自动化快捷键不暴露浏览器级缩放状态，因此不宣称通过快捷键改变浏览器倍率。
- 发布处理：前端资源版本递增至 `v=26`，避免用户刷新时复用旧 bundle。
- 依赖结论：节点编辑器窗口缩放和浏览器原生缩放边界已收敛，可以进入最终全量回归与发布。

#### Step 12.4：真实模型、全量回归与发布（completed，2026-07-22）

- 真实模型：千问 `qwen3.7-max` 和 DeepSeek `deepseek-v4-pro` 已在 Step 12.2 的真实企业 Agent 合规评测场景通过；Step 12.3E 另以 DeepSeek 真实响应验证 `STRING / INTEGER` 提取、类型转换、日志与草稿恢复。
- 前端 E2E：已覆盖模型选择、阻塞运行、原始日志、输出类型、变量复制、流式标题以及节点编辑器窗口放大/缩小；复制验收以剪贴板真实读回值为准，不再只依赖提示消息。
- 全量回归：`uv run pytest -q` 结果 `171 passed, 6 skipped, 1 warning in 14.30s`；6 项跳过均为未在本轮进程注入 live 环境变量的真实供应商用例，warning 为既有 Starlette/httpx 弃用提示。
- 构建与静态检查：`npm run build`、`node --check web/static/assets/workflow-canvas.js`、`uv run python -m compileall -q execution web` 和 `git diff --check` 全部通过。
- 安全扫描：待提交文件 `sk-` 候选扫描排除构建产物中的 CSS 标识符后，带数字的凭据候选为 0；未把用户 API Key 写入代码、测试、文档或提交内容。
- 测试数据清理：真实 E2E 临时 Workflow `fe539097aaca4befbd2c049abe0990ef` 已通过删除 API 清理，随后 GET 返回 `404`。
- 发布结果：功能与测试改造已提交为 `8d405e9`（`Add persistent LLM workflow execution`），并成功推送到 `origin/codex/tool-template-refactor`；随后本计划收口记录单独提交并同步推送。

#### Step 13：Script 节点参数页签收敛（completed，2026-07-22）

##### 业务背景与目标（Why）

- Script 节点的“参数”页签当前只展示只读的 `parameterRecords` 快照，不负责配置脚本输入；在真实编辑场景中通常为空，并与变量面板、日志详情形成重复入口。
- 本步骤目标是让 Workflow 作者在 Script 节点内按实际工作流完成三件事：在“代码”页编写脚本，在右上角变量面板核对可引用值，在“设置 → 输出变量”声明下游变量；执行结果和错误统一进入“日志”。

##### 用户与真实场景（Who / Where）

- 用户：编排评测 Workflow 的业务或测试工程师。
- 场景：用户双击 Script 节点修改 `main.py`，需要查看上游输出并确认脚本结果；此时参数快照既不能编辑输入，也不能替代日志和变量面板。

##### 需求范围与优先级（What / When）

- 高优先级、前端交互收敛：Script 编辑器只保留“设置 / 代码 / 日志”三页。
- “设置”继续保留名称、说明、运行配置和输出变量；“代码”继续保留 `main.py`；“日志”继续保留运行状态、结果和错误。
- 右上角变量面板继续作为 Script 调试输入的唯一查看入口；不新增一套参数映射 UI。
- 共享 `parameterRecords` 数据结构暂不删除，因为 HTTP / AGENT 仍使用参数查看能力；本步骤不改后端运行协议、不改变历史草稿读取。
- 已确认 `1A 2A`：本步骤同时为 `HTTP / AGENT / LLM / SCRIPT` 接入真实执行；日志按“原始请求 / 原始 stdout / 原始 response / 原始 stderr 与 traceback”分区展示，但不改写原始文本；输出变量只能依据原始 `request / response` 结构提取。

##### 可独立验证子任务

| 子任务 | 目标 | 输入/输出 | 验证方法 | 依赖 |
|---|---|---|---|---|
| 13.1 | 原始日志持久化 | Worker stdout/stderr；运行记录新增原始流字段 | Worker 流归属、SQLite 重启回读、10 条保留 | 无 |
| 13.2 | 四类真实执行 | HTTP 配置、AGENT/SCRIPT `main.py`、LLM 网关 | 四类成功/失败、request/response 提取、无密钥日志 | 13.1 |
| 13.3 | 统一日志 UI | 四类运行记录 | 浏览器展开原始四区、错误定位、节点状态 | 13.2 |
| 13.4 | 集成发布 | 完整 Workflow Studio | 全量 pytest、构建、真实浏览器、推送 | 13.1-13.3 |

##### 验收标准与价值验证（How to Measure）

- Script 节点编辑器不显示“参数”按钮，且节点切换或旧状态恢复时不会渲染参数面板。
- Script 的“设置 / 代码 / 日志”、变量按钮和输出变量配置均可正常使用；HTTP / AGENT 的参数页签保持不变。
- `npm run build`、专项前端测试和真实浏览器双击 Script 流程通过，桌面布局无重叠或横向溢出。
- 实现进度：已加入 `isScript / showParametersTab` 路由判定；切换节点时重置到 `initialTab`，避免从 HTTP/AGENT 参数页切换到 Script 后残留隐藏面板。`npm run build` 成功，`uv run pytest tests/test_execution_frontend.py -q` 为 `8 passed, 1 warning`，`node --check web/static/assets/workflow-canvas.js` 通过。
- 13.1 已完成：`WorkflowNodeRunRecord` 增加 `stdout/stderr`，SQLite 自动迁移 `stdout_body/stderr_body`；Worker 事件携带原始流来源并分别收集。`uv run pytest tests/test_tool_execution.py tests/test_workflow_drafts.py -q` 为 `15 passed, 1 warning`，Python 编译通过。
- 13.2 已完成：HTTP 使用真实请求配置进入 Worker，AGENT/SCRIPT 使用真实 `main.py` 子进程；四类节点统一按 `request / response` 提取输出变量。成功/失败均保存原始 stdout、stderr、response 和 traceback，HTTP 非 2xx 保留原始响应。专项 `uv run pytest tests/test_workflow_node_runs.py -q` 为 `5 passed, 1 warning`，与既有 LLM/Worker/草稿专项合计 `24 passed, 1 warning`。
- 13.3 已完成：四类节点共用可展开运行历史，摘要显示日期、状态、耗时和最终结果；详情按原始请求、stdout、response、stderr、traceback 分区展示，空区不伪造内容，保留原始文本。运行入口与日志加载扩展到 HTTP/AGENT/LLM/SCRIPT。`npm run build`、`node --check web/static/assets/workflow-canvas.js` 和 `uv run pytest tests/test_execution_frontend.py -q`（`8 passed, 1 warning`）通过；节点执行专项现为 `6 passed, 1 warning`。
- 13.4 已完成：浏览器真实 Script 成功运行以 `212ms` 进入 `PASSED`，展开日志显示原始 request/stdout/response/stderr，并提取 `browser_value=浏览器回归`；失败运行以 `222ms` 进入 `FAILED`，保留执行前 stdout、用户 stderr、Worker traceback 和路由 traceback。全量回归 `177 passed, 6 skipped, 1 warning in 16.92s`，构建、Python/JS 静态检查和 `git diff --check` 通过；临时 Workflow 删除后 GET 为 `404`。
- 13.5 发布完成：提交 `7f15ac9`（`Add real workflow node execution logs`）已推送到 `origin/codex/tool-template-refactor`。

#### Step 14：Workflow 与节点中断控制（completed，2026-07-22）

##### 业务背景与目标（Why）

- 当前画布运行会按定时器触发节点，运行按钮可重复点击，后端节点请求没有可由画布调用的统一取消协议；长耗时测试容易重复消耗资源，也无法在发现配置错误后及时停止。
- 目标是在画布级和节点级提供一致的运行锁、中断入口、耗时计时与可重新运行能力，同时保证中断后的执行范围可预测。

##### 已确认需求（What）

- 画布运行期间禁用重复运行；运行按钮左侧显示累计计时器；顶部“全局变量”右侧和画布右键菜单均提供中断入口；中断后可重新从头运行。
- 历史需求曾要求节点卡片、节点右键菜单和编辑器标题栏提供中断入口；该用户入口已由 T13.22 全部废止，当前只保留节点运行锁和系统内部清理取消。
- 历史节点中断调度语义已废止；当前完整 Workflow 只能全局中断，单节点临时测试不提供用户中断。

##### 实现前必须确认

- 中断节点在既定四状态中显示 `FAILED` 还是恢复 `PENDING`。
- 在分支 Workflow 中，“后续节点”是仅指被中断节点的图后代，还是停止本次 Workflow 的所有剩余节点。
- 当前按横坐标定时触发的画布演示调度是否在本步骤升级为依据连线的真实 DAG 调度。
- 用户已确认：`PASSED` 全局更名为 `SUCCESS`，最终状态集合为 `PENDING / RUNNING / SUCCESS / FAILED / INTERRUPTED`；执行失败与用户中断严格区分；节点级中断仅停止当前节点及其图后代，独立分支继续；调度采用 `3B` 真实 DAG，依赖满足后独立分支并行。任一节点 `FAILED` 或 `INTERRUPTED` 后，其图后代在本次运行中保持未执行。

##### Step 14 可独立验证子任务

| 子任务 | 目标 | 输入/输出 | 验证方法 | 依赖 |
|---|---|---|---|---|
| 14.1 | 后端节点取消协议 | 活动运行注册、Worker/LLM 取消、`INTERRUPTED` 记录 | 重复运行拒绝、运行中中断、终态中断无副作用、日志回读 | 无 |
| 14.2 | 并行 DAG 调度 | 节点/边、SUCCESS/FAILED/INTERRUPTED | 独立分支并行、后代阻断、失败分支不影响独立分支 | 14.1 |
| 14.3 | 画布级控制 | 运行锁、计时器、顶部/右键中断 | 连续点击禁用、中断全部活动节点、重新从头运行 | 14.1-14.2 |
| 14.4 | 节点级控制 | 卡片/右键/编辑器运行与中断 | 运行锁、三处中断一致、后代不执行、节点可重跑 | 14.1-14.3 |
| 14.5 | 集成发布 | 完整 Workflow Studio | 专项/全量 pytest、构建、真实浏览器 E2E、推送 | 14.1-14.4 |

##### 14.1 后端节点取消协议（completed，2026-07-22）

- 状态契约：`WorkflowNodeRunStatus` 统一提供 `PENDING / RUNNING / SUCCESS / FAILED / INTERRUPTED`；SQLite 初始化会把历史 `PASSED` 行迁移为 `SUCCESS`，内部查询命名同步为 `latest_success_run`。
- 活动运行：节点运行按 `(workflow_id, node_id)` 注册；同一节点已有活动运行时返回 HTTP `409`。活动 Worker 保存 `run_id`，中断接口终止 Worker 进程树；LLM 非流式任务取消当前 asyncio 任务。
- 流式 LLM：响应生成器开始时绑定实际任务，支持中断前置竞态、运行中 `CancelledError` 和客户端断开后的清理；已接收的原始 chunk 保存到 `response_body`，最终记录为 `INTERRUPTED` 并保留 `INTERRUPTED` 错误事件。
- API：新增 `POST /api/workflow-drafts/{workflow_id}/nodes/{node_id}/interrupt`；未运行、已完成或已中断节点返回 `{"interrupted": false}`，不创建额外运行记录。
- 验证：`uv run pytest tests/test_workflow_node_runs.py::test_script_node_can_be_interrupted_and_rejects_duplicate_runs -q` 通过；`uv run pytest tests/test_llm_node_runs.py::test_llm_stream_can_be_interrupted_and_persists_partial_raw_response -q` 通过；两项均覆盖重复启动、运行中断、日志回读和中断后重跑/部分原始响应。现有 Workflow/LLM/节点专项合计 `23 passed, 1 warning`；Python 编译通过。
- 依赖结论：后端节点级取消协议已具备稳定终态和清理语义，可以进入真实 DAG 调度实现；此前业务数据提取测试中的字符串 `PASSED` 保持原样，不属于运行状态。

##### 14.2 并行 DAG 调度（completed，2026-07-22）

- 调度规则：运行入口依据 Workflow 连线构建前驱表；无前驱节点同时进入就绪队列，独立分支通过 `Promise.race` 并行推进；只有节点返回 `SUCCESS` 才会解锁后继节点。
- 失败隔离：节点返回 `FAILED` 或 `INTERRUPTED` 时，仅将其图后代标记为本次未执行并保持 UI `PENDING`；没有依赖关系的分支继续执行。Workflow 级中断会设置全局中断标记，停止活动节点且不再启动剩余节点。
- 运行锁：Workflow 活动期间 `运行` 按钮禁用；同一节点通过 ref 活动表避免重复调用，节点运行结束或中断后可再次启动。节点卡片、右键菜单和编辑器标题栏共享同一中断回调。
- 控件（历史实现）：当时曾在节点卡片、节点右键菜单和编辑器标题栏提供节点中断；T13.22 已删除三处入口，仅保留 Workflow 全局中断与节点运行锁。
- 状态：前端统一展示 `PENDING / RUNNING / SUCCESS / FAILED / INTERRUPTED`，节点运行历史摘要对 `INTERRUPTED` 显示中断错误而非伪造成功结果。
- 验证：`npm run build`、`node --check web/static/assets/workflow-canvas.js`、`git diff --check` 通过；资源版本断言同步为 `v=28` 后，`uv run pytest tests/test_execution_frontend.py tests/test_workflow_node_runs.py tests/test_llm_node_runs.py tests/test_workflow_drafts.py -q` 结果为 `31 passed, 1 warning`，覆盖前端契约、Script/HTTP/LLM 执行和取消协议。

##### 14.3 画布级控制（completed，2026-07-22）

- 真实浏览器运行锁：临时 Workflow 进入运行后，顶部运行按钮禁用、中断按钮启用，累计计时器从 `810ms` 持续增长；活动 Script 节点同步显示 `RUNNING` 并禁用节点运行入口。
- 顶部中断：点击顶部中断后，活动 Script 进入 `INTERRUPTED`，Workflow 提示“Workflow 已中断”，运行按钮重新启用且中断按钮禁用；本次计时器冻结在 `10.0s`。
- 重新运行：中断后再次点击顶部运行，Script 重新进入 `RUNNING`，证明 Workflow 可从头启动新一轮执行；随后再次中断，终态仍稳定为 `INTERRUPTED`。
- 右键中断：运行期间在画布空白区打开右键菜单，确认“中断测试”存在并可实际终止活动 Script；菜单关闭后节点保持 `INTERRUPTED`，未继续启动剩余节点。
- 依赖结论：画布运行锁、累计计时、两处中断入口和中断后重跑已通过真实浏览器验收，可以进入节点三入口验收。

##### 14.4 节点级控制（completed，2026-07-22）

> 本节是 2026-07-22 的历史验收记录；其中用户节点中断入口已由 T13.22 废止，不代表当前产品能力。

- 编辑器入口：30 秒 Script 运行时，编辑器运行按钮禁用、中断按钮启用，卡片耗时从 `0ms` 累加；点击编辑器中断后节点进入 `INTERRUPTED`，运行按钮恢复且中断按钮禁用。
- 卡片入口：卡片运行后同样禁用重复运行并启用中断；点击卡片中断后状态为 `INTERRUPTED`，运行入口重新可用。
- 右键入口：节点右键菜单显示“中断此步骤”，运行期间点击后真实终止 Worker，菜单关闭且节点进入 `INTERRUPTED`。
- 原始日志：最近一次中断记录摘要显示 `07-22 03:28:23 / INTERRUPTED / 23.6s / 用户中断节点`；展开后保留原始 request 和原始 stdout `browser interrupt`，没有因中断丢弃运行前已输出内容。
- 成功状态：同一节点此前完整运行记录在卡片和日志中均显示 `SUCCESS`，不再显示 `PASSED`。
- 依赖结论：节点卡片、右键菜单和编辑器三处运行锁/中断语义一致，且中断日志满足原始输出铁律，可以进入集成发布回归。

##### 14.5 集成发布（completed，2026-07-22）

- 状态契约：源码、前端构建产物、测试和项目说明统一使用 `PENDING / RUNNING / SUCCESS / FAILED / INTERRUPTED`；历史 SQLite `PASSED` 自动迁移并有专项测试覆盖。
- 调度与中断：后端阻塞/流式节点取消、同节点 `409` 运行锁、前端真实 DAG 并行、失败/中断后代阻断、画布和节点全部中断入口均完成。
- 浏览器回归：覆盖编辑器、卡片、节点右键、画布顶部和画布右键五类入口；验证运行禁用、累计计时、原始 stdout 保留、中断终态和重新运行。
- 最终回归并入 Step 15.3：全量 `185 passed, 6 skipped, 1 warning`，构建、JS/Python 静态检查和差异检查均通过。

#### Step 15：禁止游离节点（completed，2026-07-22）

##### 业务背景与目标（Why）

- Workflow 保存后会被真实 DAG 调度执行；若节点不在完整执行链上，用户容易误以为该节点会参与测试，实际却永远不会启动或无法汇入结束节点。
- 目标是在不妨碍拖拽编辑的前提下，确保每个可执行节点都属于完整的 `START → ... → END` 有向路径。

##### 用户与真实场景（Who / Where）

- 用户：在 Workflow Studio 编排企业 Agent 测试流程的业务或测试工程师。
- 场景：用户可以在编辑过程中临时断开节点；只有点击保存或运行时才需要得到明确错误，并定位所有不可从 START 到达或无法到达 END 的节点。

##### 已确认范围与优先级（What / When）

- 采用严格规则 `1A`：每个业务节点必须同时满足“可从 START 到达”和“可以到达 END”；完全无边、只有入边、只有出边、断裂分支均属于游离节点。
- 采用双层校验 `2A`：前端保存/运行立即拦截，后端草稿保存和节点运行接口同步拒绝，避免绕过页面。
- 仅在保存和执行时检测；拖拽、连线和删除过程不实时打断编辑。

##### 可独立验证子任务

| 子任务 | 目标 | 输入/输出 | 验证方法 | 依赖 |
|---|---|---|---|---|
| 15.1 | 后端图完整性校验 | nodes/edges；结构化错误 | 合法 DAG、无边、不可达、死路、API 保存/运行拒绝 | 无 |
| 15.2 | 前端保存/运行拦截 | 当前 React Flow 图；节点名称提示 | 前端专项断言与构建 | 15.1 |
| 15.3 | 端到端回归与发布 | Workflow Studio 完整流程 | 真实浏览器、专项/全量测试、构建、推送 | 15.1-15.2 |

##### 验收标准与价值验证（How to Measure）

- 合法分支 DAG 可以保存和运行；任一业务节点不在完整 `START → END` 路径上时，保存和运行均失败。
- 错误提示包含游离节点名称，用户无需逐条排查连线。
- 直接调用后端 API 不能绕过规则；历史草稿仍可读取和编辑，在重新保存或运行时才触发校验。
- 节点中断、`SUCCESS` 状态、原始日志和现有变量提取能力不受影响。

##### 15.1 后端图完整性校验（completed，2026-07-22）

- 共享规则：新增保存/执行时图校验；要求且仅允许一个 `START` 和一个 `END`，并通过正向可达集与反向可达集的交集判断每个节点是否处于完整 `START → END` 路径。
- 错误定位：无边、从 START 不可达、无法到达 END 和断裂分支均返回 HTTP `422`，错误包含全部游离节点名称或 ID。
- 历史兼容：规则不放入草稿 Pydantic 读取模型；历史无效草稿仍可 GET 和编辑，但 PUT 保存或节点执行时被拒绝。
- 防绕过：草稿 POST/PUT、阻塞节点运行和流式 LLM 运行均调用同一后端校验；活动运行先原子注册，再校验并在失败时清理，保持重复运行 `409` 语义。
- 测试夹具：Script/Agent/HTTP/LLM 执行用例统一升级为 `START → 业务节点 → END`，下游 LLM 用例升级为完整串行路径。
- 验证：`uv run pytest tests/test_workflow_drafts.py tests/test_workflow_node_runs.py tests/test_llm_node_runs.py -q` 结果 `28 passed, 1 warning`；覆盖合法并行 DAG、无边、不可达、死路、更新绕过、历史草稿执行绕过、重复启动、中断及原始流日志。
- 依赖结论：后端保存和执行边界已收敛，可以接入前端保存/运行即时提示。

##### 15.2 前端保存/运行拦截（completed，2026-07-22）

- 前端规则：React Flow 当前节点/边通过与后端一致的正向、反向可达性算法校验；缺少唯一 START/END 或存在不在完整路径上的节点时返回明确错误。
- 触发时机：`persistDraft`、节点运行和画布运行三个入口调用校验；拖拽、连线、删除、复制和粘贴过程中不执行校验，允许用户临时断开图。
- 交互结果：保存失败状态显示为“保存失败”，Toast 列出游离节点名称；运行不会启动计时器、不会把节点改成 `RUNNING`，也不会向后端发送执行请求。
- 构建发布：`npm run build` 成功生成最新 JS/CSS bundle，首页资源版本递增为 `v=29`。
- 验证：`node --check web/static/assets/workflow-canvas.js`、`git diff --check` 通过；`uv run pytest tests/test_execution_frontend.py -q` 结果 `8 passed, 1 warning`。
- 依赖结论：前后端规则一致，可以进入真实浏览器的无边、死路、合法路径保存/运行验收。

##### 15.3 端到端回归与发布（completed，2026-07-22）

- 浏览器无边场景：删除默认 HTTP 中间节点后点击保存，页面显示 `Workflow 存在游离节点: 开始, 执行企业 Agent, 模型质量判断, 规则校验, 完成`，状态变为“保存失败”；点击运行不会启动 Workflow 计时器、不会出现 `RUNNING`。
- 浏览器合法场景：撤销删除恢复 `START → HTTP → AGENT → (LLM/SCRIPT) → END` 完整路径后保存成功并显示“Workflow 草稿已保存”。
- 后端死路/不可达：专项覆盖无边、只有入边、只有出边和完整并行分支；直接 POST/PUT/节点运行 API 均按规则返回 `422` 或正常接受合法图。
- 回归结果：全量 `uv run pytest -q` 为 `185 passed, 6 skipped, 1 warning in 18.60s`；专项草稿/节点/LLM/前端为 `37 passed, 1 warning`。
- 构建检查：`npm run build`、`node --check web/static/assets/workflow-canvas.js`、`uv run python -m compileall -q execution web tests`、`git diff --check` 全部通过。
- 状态契约：运行状态对外统一为 `PENDING / RUNNING / SUCCESS / FAILED / INTERRUPTED`；SQLite 历史 `PASSED` 仅作为一次性迁移输入，普通响应字段中的同名业务值保持原样。
- 安全：代码、测试、文档和构建产物未发现用户 API Key 候选；浏览器临时 Workflow 已删除，API 列表回到 0 条。

##### 15.4 单节点调试与完整图校验解耦（completed，2026-07-22）

- 业务修正：节点卡片和节点编辑器右上角的运行按钮只运行当前节点，不依赖 `START / END`，也不要求当前 Workflow 已形成完整路径。
- 保存边界：显式保存节点或 Workflow、以及画布级运行仍执行完整 `START → END` 校验；单节点运行只创建/更新内部运行快照，不把界面标记为“已保存”，不清除未保存状态。
- 后端边界：草稿 POST/PUT 仅在 `for_node_run=true` 的内部运行快照请求中允许不完整图；节点阻塞/流式运行接口不再校验整张图，但继续校验当前节点的模型、提示词、参数或代码。
- 验证：`uv run pytest tests/test_workflow_drafts.py tests/test_workflow_node_runs.py tests/test_llm_node_runs.py tests/test_execution_frontend.py -q` 结果 `37 passed, 1 warning`；覆盖显式保存拒绝、不完整图快照允许和单节点自身配置失败。
- 浏览器验收：使用仅含一个 LLM、完全没有 `START / END` 的临时 Workflow，选择 DeepSeek 并填写提示词后从编辑器右上角启动；节点立即进入 `RUNNING`，运行按钮禁用、中断按钮启用，最终在 `15.5s` 进入 `SUCCESS`。临时 Workflow 随后删除。
- 发布回归：前端资源升级为 `v=30`；全量 `uv run pytest -q` 结果 `185 passed, 6 skipped, 1 warning in 18.53s`，JS/Python 静态检查和 `git diff --check` 通过。

#### Step 16：弱化 START/END 并完善画布图编辑（completed，2026-07-22）

##### 业务背景与目标（Why）

- 当前 START/END 只承担装饰性连线作用，却被错误地作为 Workflow 保存和运行的硬性前置条件；这会让单节点和多入口/多出口 DAG 增加无意义的配置成本。
- 目标是让调度器根据真实连线自动识别起点和终点，同时保留用户在需要时手工添加 START/END 的能力，并让连线删除、游离提示可见且可操作。

##### 用户与真实场景（Who / Where）

- 用户：在 Workflow Studio 中快速验证单节点、编排并行分支和维护已有流程的测试工程师。
- 场景：用户可以直接运行一个孤立的当前节点；画布运行前需要知道哪些节点未接入图；编辑连线时需要点击选中后用 Delete/Backspace 或右键删除。

##### 已确认范围与优先级（What / When）

- 不再强制要求 START/END；入度为 0 的节点自动作为执行起点，出度为 0 的节点自动作为终点。
- 右键画布可添加 `START` 和 `END`，系统节点与业务节点均可按需使用。
- 连线支持选中高亮、Delete/Backspace 删除和右键菜单删除。
- 保存或运行检测到游离节点时必须显示明确提示，不能静默阻止。

##### 可独立验证子任务

| 子任务 | 目标 | 输入/输出 | 验证方法 | 依赖 |
|---|---|---|---|---|
| 16.1 | 新图规则与提示 | 可选 START/END、游离节点错误 | 后端/前端合法单节点、并行 DAG、孤立节点、保存/运行错误 | 无 |
| 16.2 | 连线编辑交互 | 选中/高亮/删除/右键删除 | 浏览器点击连线、键盘删除、右键删除 | 16.1 |
| 16.3 | 系统节点添加 | 画布右键 START/END | 浏览器菜单添加并持久化 | 16.1 |
| 16.4 | 集成回归与发布 | Workflow Studio 完整流程 | 全量测试、构建、真实浏览器、推送 | 16.1-16.3 |

##### 验收标准与价值验证（How to Measure）

- 单节点和不含 START/END 的合法 DAG 可以保存和运行。
- 完全无连线的业务节点被识别为游离节点；保存和运行均显示包含节点名称的提示。
- 连线点击后有选中高亮；Delete、Backspace 和右键“删除”均能移除连线并更新图。
- 画布右键菜单可添加 START/END，新增节点可继续连线、保存和参与 DAG 调度。

##### 16.1 新图规则与提示（completed，2026-07-22）

- START/END 可选：后端和前端均不再要求 START/END 存在或唯一；调度器继续把所有入度为 0 的节点视为起点，把所有出度为 0 的节点视为终点。
- 新建默认图：删除装饰性 START/END，只保留 `HTTP → AGENT → (LLM / SCRIPT)` 业务节点和真实依赖。
- 游离定义：单节点 Workflow 合法；多节点时，入度与出度总和均为 0 的节点视为游离。多个彼此独立但内部有连线的分支可并行存在。
- DAG 安全：前后端增加 Kahn 拓扑检测，发现循环依赖时显示涉及节点并拒绝保存/画布运行。
- 可见提示：全局 Toast 层级从 `1000` 提升到 `3000`，高于全屏 Workflow Studio 的 `2000`，保存和运行错误不再被画布遮挡。
- 验证：`uv run pytest tests/test_workflow_drafts.py tests/test_execution_frontend.py tests/test_workflow_node_runs.py tests/test_llm_node_runs.py -q` 结果 `37 passed, 1 warning`；覆盖单节点、并行 DAG、游离节点、循环依赖、单节点调试和现有中断协议。
- 依赖结论：图规则与提示边界已通过，可以进入连线选中/删除和系统节点菜单的真实浏览器验收。

##### 16.2 连线编辑交互（completed，2026-07-22）

- 选中高亮：连线点击后独占选中，节点选择被清空；真实浏览器计算样式从中性灰 `rgb(154, 168, 186) / 1.7px` 变为蓝色 `rgb(36, 87, 214) / 2px`。
- 键盘删除：Workflow Studio 在连线点击时主动获得焦点；Delete/Backspace 同时支持选中节点和选中连线。浏览器实测 Delete 后连线数从 3 降到 2。
- 右键删除：新增 `onEdgeContextMenu` 和独立 `edge-context-menu`，右键连线会选中该线并显示“删除连线”；删除共用统一历史记录逻辑，支持 Ctrl+Z 恢复。
- 依赖结论：连线已具备可见选中、键盘删除和右键删除三条完整交互路径，可以进入系统节点菜单验收。

##### 16.3 系统节点添加与可见错误（completed，2026-07-22）

- 画布菜单：右键空白区展开“添加节点”后显示 `开始 START / 结束 END / HTTP / AGENT / LLM / SCRIPT`；Edge `+` 插入仍只提供四种业务节点，避免把 START/END 插入流程中段。
- 浏览器添加：分别点击 START 和 END 菜单项后，对应系统节点真实出现在画布；节点继续使用既有单向 Handle 规则。
- 游离提示：删除默认 AGENT 后，保存和画布运行均显示 `Workflow 存在游离节点`；运行未启动计时器。Toast 的 `z-index: 3000` 确保提示位于全屏画布和编辑器之上。
- 无系统节点保存：默认 `HTTP → AGENT → (LLM / SCRIPT)` 图不含 START/END，浏览器实测保存成功；临时 Workflow 删除后 API 仅保留用户原有数据。
- 依赖结论：系统节点可选入口、游离提示和无 START/END 保存均已通过真实浏览器验收，可以进入全量集成回归。

##### 16.4 集成回归与发布（completed，2026-07-22）

- 专项回归：Workflow 草稿、前端契约、四类节点运行、LLM 阻塞/流式和中断专项合计 `37 passed, 1 warning`。
- 全量回归：`uv run pytest -q` 结果 `185 passed, 6 skipped, 1 warning in 17.93s`；6 项跳过仍是未向本轮进程注入真实供应商环境变量的 live 用例。
- 构建检查：`npm run build`、`node --check web/static/assets/workflow-canvas.js`、`uv run python -m compileall -q execution web tests` 和 `git diff --check` 全部通过。
- 发布资源：Workflow JS/CSS 资源版本升级为 `v=31`；`AGENTS.md` 同步记录 START/END 可选、隐式起止、连线编辑、游离/循环校验和单节点运行边界。
- 测试数据：浏览器 E2E 创建的无 START/END 临时 Workflow 已删除，API 仅保留用户原有 Workflow。

### Step 17：Anthropic 原生协议与内网模型连接（in progress，2026-07-22）

#### 业务背景与目标（Why）

- 模型管理虽可识别 `ANTHROPIC`，但 Workflow LLM 节点只实现了 OpenAI-compatible 请求，导致已保存的 Anthropic 模型无法执行。
- 企业内网模型网关常使用私有 IP、自签名证书，并且不应经过公司 VPN 注入的系统代理；目标是在不降低公网连接安全性的前提下打通这类本机调试场景。

#### 用户与真实场景（Who / Where）

- 企业测试工程师在本机模型管理中配置 OpenAI-compatible 或 Anthropic 供应商，再从 Workflow LLM 节点选择模型进行阻塞或流式验证。
- Step 18 已取代早期内网 IP 自动直连策略：BASE_URL 地址类型不再改变路由，用户必须显式选择 SYSTEM、DIRECT 或 CUSTOM；TLS 证书校验继续与代理模式独立。

#### 已确认范围与优先级（What / When）

- P0：模型管理明确支持 `OPENAI_COMPATIBLE / ANTHROPIC` 两种可执行协议，手工添加模型不再等价于不可执行的 `MANUAL` 协议。
- P0：实现 `build_anthropic_request / invoke_anthropic / parse_anthropic_response`，覆盖 Anthropic 原生阻塞与流式节点路径。
- P0：HTTPX 客户端参数只由显式代理模式和 TLS 开关决定，不再包含地址类型启发式。
- 代理采用已确认的 `1A` 及 Step 18 最终细化：前端下拉、API、数据库与运行时统一使用 `SYSTEM / DIRECT / CUSTOM`。SYSTEM 继承环境变量；DIRECT 设置 `trust_env=False`；CUSTOM 始终使用保存的 HTTP(S)/SOCKS URL及可选认证。正向 `verify_ssl` 默认 `true`，关闭后统一设置 `verify=False`。
- 模型齿轮采用已确认的 `2A`：保存上下文窗口、最大输出 Token 能力和默认 Body JSON；前两项只作为模型元数据，不伪造跨厂商请求字段。
- 参数采用已确认的 `3A`：平台基础请求 < 模型默认 Body < LLM 节点高级参数，后层递归覆盖前层；数组和标量整体替换。
- 每个已添加模型在齿轮旁提供独立测试按钮；测试使用页面当前连接配置、代理和该模型默认 Body 发起真实阻塞推理，不打开弹窗，只在模型行标记可用/不可用并通过轻量提示反馈 HTTP 状态与延迟；不持久化为 Workflow 节点日志，也不隐式保存供应商。
- Anthropic Messages API 强制要求 `max_tokens`；节点未显式设置时使用 `8192` 作为协议必需兼容值，用户 `modelParameters.max_tokens` 优先覆盖。OpenAI-compatible 仍不注入 token 上限。

#### 可独立验证子任务

| 子任务 | 目标 | 输入/输出 | 验证方法 | 依赖 |
|---|---|---|---|---|
| 17.1 | 协议与内网传输内核 | 两类请求/响应和 URL；httpx 参数 | MockTransport、URL/请求/响应、内外网参数单测 | 无 |
| 17.2 | 模型管理接入 | 显式协议；测速和模型发现 | API、前端契约、本地 HTTP 服务 | 17.1 |
| 17.3 | Workflow LLM 接入 | Anthropic 阻塞/流式原始日志 | 本地 Anthropic 网关节点 E2E、中断与变量提取 | 17.1-17.2 |
| 17.4 | 集成回归与发布 | 完整业务流程和文档 | 专项/全量测试、构建、静态检查、浏览器 E2E、GitHub 推送 | 17.1-17.3 |

##### 17.1 协议与内网传输内核（completed，2026-07-22）

- 新增 Anthropic 原生请求构建、`/v1/messages` URL、`x-api-key / anthropic-version` Header、HTTP 调用和非流式响应解析；文本块按原顺序合并，usage 与 stop reason 保持原生语义。
- Anthropic 基础请求仅因原生协议强制要求而默认加入 `max_tokens: 8192`，模型默认参数和节点高级参数仍可递归覆盖全部字段；OpenAI-compatible 的无默认 token 上限契约未改变。
- Step 18 已删除共享内网 IP 判断；此阶段新增的 Anthropic 请求、代理参数构建和证书验证能力继续复用同一 HTTPX 传输内核。
- 验证：`uv run pytest tests/test_model_gateway.py -q` 结果 `8 passed`；覆盖内外网判定、三类 Anthropic BASE_URL、Body 深度合并、专有 Header、原生响应文本/usage/stop reason 和既有 OpenAI 流式解析。
- 依赖结论：共享协议内核可供模型管理和 Workflow 执行复用；模型级代理模式、默认 Body 和上下文元数据仍需按最新需求确认后进入 17.2。

##### 17.2 模型管理接入（completed，2026-07-22）

- 所有新增设置严格收口在“模型管理 → 供应商详情”：协议、代理模式、自定义代理认证、SSL 证书验证、模型默认 Body、上下文元数据、最大输出能力和单模型测试均不进入画布配置。
- 协议在界面对用户统一显示为 `OpenAI / Anthropic`；持久化仍使用稳定的 `OPENAI_COMPATIBLE / ANTHROPIC` 标识。供应商列表、详情摘要和模型行均使用用户可见名称。
- 每个模型的齿轮弹窗可保存 `context_window / max_output_tokens / default_body`；前两项仅是能力元数据，默认 Body 在执行时位于平台基础请求与节点高级参数之间。
- 每个模型的测试按钮使用详情页当前连接、协议、代理和默认 Body 发起真实阻塞请求；测试不打开结果弹窗，模型行按钮直接标记可用/不可用，轻量提示反馈 HTTP 状态与延迟，且不隐式保存供应商。
- 专项验证：`uv run pytest tests/test_model_gateway.py tests/test_model_providers.py tests/test_model_providers_frontend.py -q` 结果 `33 passed, 1 warning`；`node --check web/static/model-providers.js` 通过。
- 浏览器 E2E：DeepSeek `deepseek-v4-pro` 真实单模型请求已验证返回 HTTP 200；详情页确认 `OpenAI / Anthropic`、三种代理模式、测试与齿轮按钮均在模型管理内，未点击保存且未修改用户数据。测试反馈已按最新要求改为无弹窗行内状态，待 17.4 最终浏览器回归复核。

##### 17.3 Workflow LLM 接入（completed，2026-07-22）

- Workflow 后端根据模型管理中已保存的协议选择 OpenAI-compatible 或 Anthropic 原生执行路径；画布和节点编辑 UI 未增加协议、代理、模型默认 Body、上下文或测试配置。
- Anthropic 阻塞请求使用 `/v1/messages`、`x-api-key`、`anthropic-version`，系统提示词写入顶层 `system`；响应保留原始 Body，并解析文本、usage 和 stop reason 供日志与输出变量使用。
- OpenAI 与 Anthropic 均按“平台基础请求 < 模型默认 Body < 节点高级参数”递归合并；模型能力元数据 `context_window / max_output_tokens` 不会被伪装成跨厂商请求字段。
- 阻塞和流式请求统一消费供应商显式代理配置；目标 IP 类型不会覆盖用户选择。代理密码与 API Key 不进入持久化日志或错误文本。
- Anthropic 流式请求原样发送 SSE 到前端并持久化原始响应，不执行结构化解析、不提取输出变量；失败和中断继续保留已收到的真实原文与错误。
- 专项验证：`uv run pytest tests/test_llm_node_runs.py tests/test_model_gateway.py tests/test_model_providers.py tests/test_model_providers_frontend.py -q` 结果 `41 passed, 1 warning`；新增本地 Anthropic 假网关覆盖路径、Header、系统提示词、默认 Body/节点覆盖、usage、变量提取和流式原文。`node --check` 与 Python `compileall` 均通过。

##### 17.4 集成回归与发布（completed，2026-07-22）

- 构建：`npm run build` 通过，Workflow 构建产物无业务差异；模型管理使用独立静态 JS/CSS，无需修改画布资源版本。
- 全量回归：`uv run pytest -q` 结果 `202 passed, 6 skipped, 1 warning`；6 项跳过仍是未向本轮进程注入真实供应商环境变量的 live 用例，warning 为既有 Starlette/httpx 弃用提示。
- 静态检查：Python `compileall`、`node --check web/static/model-providers.js`、Workflow bundle 语法检查和 `git diff --check` 均通过。
- 浏览器 E2E：模型管理详情显示 `OpenAI / Anthropic` 与统一代理枚举 `SYSTEM / DIRECT / CUSTOM`，DeepSeek `deepseek-v4-pro` 真实测试返回 HTTP 200；无结果弹窗，模型行测试按钮直接变为绿色勾选并显示可用、HTTP 状态和延迟提示。齿轮与测试按钮并列，页面无溢出；未点击保存且未修改用户供应商数据。
- 详情页操作布局：删除右上角“未测试”徽标，保存按钮从底部操作栏移动到右上角且只保留一个入口；测速和模型获取状态继续在页面中部“连接状态”区域展示。专项 `25 passed, 1 warning`，浏览器确认标题栏、表单和操作栏布局正常。
- SSL 解耦的早期负向开关已由 Step 18 迁移为正向 `verify_ssl`：默认验证证书，用户关闭后才设置 `verify=False`；三种代理模式与 TLS 继续相互独立。
- 代理布局优化：代理模式下拉缩短，独立 SSL 开关移动到其右侧同一行并保持垂直对齐；CUSTOM 展开区和连接行为不变。前端专项 `3 passed, 1 warning`、全量 `202 passed, 6 skipped, 1 warning`、JS/Python 静态检查和真实浏览器视觉验收均通过，未保存用户数据。
- 范围核对：协议、代理、模型默认配置与测试交互只改动模型管理详情；画布源码和构建产物均无 Git 差异。
- GitHub 发布：实现提交 `2be91ef` 已推送到 `origin/codex/tool-template-refactor`；提交前扫描确认没有 API Key 形式的秘密进入 Git 差异。

#### 验收标准与价值验证（How to Measure）

- Anthropic 节点向 `/v1/messages` 发送 `x-api-key / anthropic-version`，阻塞响应可得到文本、usage、stop reason，原始 request/response 可供输出变量提取。
- Anthropic 流式节点原样展示和持久化 SSE，不做结构化提取；失败和中断仍保存真实原始响应与错误。
- 私有 IP 与域名遵循相同的显式代理模式；关闭“验证 SSL 证书”后可访问自签名 HTTPS，开关开启时保持证书校验。
- OpenAI-compatible 节点、模型管理 CRUD/发现、运行锁、中断、日志和最近 10 次记录无回归。

### Step 18：Provider 显式路由与 TLS 信任（completed，2026-07-22）

#### 业务背景与目标（Why）

- 通过内网 IP 猜测并覆盖用户代理选择会让 `CUSTOM` 被静默忽略，也无法覆盖内部域名、内网代理和跨网段代理；目标是让 Provider 在不同网络环境下具有稳定、可解释的连接行为。
- 代理路由与 TLS 证书信任是两项独立决策。TLS 使用正向、默认安全的语义，避免负向开关造成误解。

#### 用户与真实场景（Who / Where）

- 本机企业测试工程师可能处于公司 VPN、全局代理、显式 HTTP/SOCKS 代理或直连网络中，需要准确选择请求路径。
- 内部模型服务可能使用受信 CA、自签名证书或企业内部 CA；关闭证书验证只能作为当前快速联调手段，不能与内网地址自动绑定。

#### 已确认范围与优先级（What / When）

- P0：严格执行 `SYSTEM / DIRECT / CUSTOM`。`SYSTEM` 使用 HTTPX 环境变量及 `NO_PROXY`；`DIRECT` 设置 `trust_env=False`；`CUSTOM` 设置显式代理并且不再被目标 IP 类型覆盖。
- P0：前端、API、持久化和运行时统一使用正向 `verify_ssl`，默认 `true`；仅在用户关闭“验证 SSL 证书”开关时传递 `verify=False`。
- P0：代理帮助只解释三种路由模式，公网/内网作为辅助示例，不参与运行时自动判断。
- P1 deferred：支持自定义 CA Bundle，使企业内部 CA 场景无需关闭证书验证。

#### 可独立验证子任务

| 子任务 | 目标 | 验证方法 | 依赖 |
|---|---|---|---|
| 18.1 | 删除 IP 启发式，严格执行三种代理模式 | HTTPX 客户端参数矩阵单测 | 无 |
| 18.2 | `verify_ssl` 正向契约与旧本机数据迁移 | Repository/API/Workflow 专项测试 | 18.1 |
| 18.3 | 正向开关和模式帮助 | 前端契约、JS 语法、桌面浏览器 E2E | 18.2 |
| 18.4 | 集成回归与发布 | 全量 pytest、静态检查、密钥扫描、GitHub 推送 | 18.1-18.3 |

##### 18.1 显式代理路由（completed，2026-07-22）

- 删除内网 IP/回环 IP/链路本地 IP 的自动路由判断，HTTPX 参数只由 `SYSTEM / DIRECT / CUSTOM` 决定；CUSTOM 对内网 IP 仍传递显式代理。
- 验证：`uv run pytest tests/test_model_gateway.py -q` 结果 `8 passed`，覆盖公网域名与内网 IP 在三种代理模式下使用完全一致的路由规则。

##### 18.2 正向 TLS 契约（completed，2026-07-22）

- 前端、模型管理 API、Pydantic 模型、SQLite Repository、模型测试和 Workflow 阻塞/流式请求统一使用 `verify_ssl`，默认 `true`；`false` 时 HTTPX 才收到 `verify=False`。
- SQLite 初始化新增 `verify_ssl` 列；检测到旧 `skip_ssl_verify` 列时按反向语义迁移，保留已有 Provider 的连接行为。列表 API 继续隐藏 TLS/代理细节，详情 API 返回正向值。
- 验证：模型网关、Provider Repository/API、Workflow LLM 与前端契约合计 `45 passed, 1 warning`；覆盖旧表迁移、三种代理模式独立 TLS 值和 CUSTOM 对内网地址不再旁路。

##### 18.3 模式帮助与安全开关（completed，2026-07-22）

- 代理模式下拉保持紧凑，右侧使用正向“验证 SSL 证书”滑动开关，默认开启；关闭后同一行显示红色“不安全”提示。
- `?` 支持悬停 CSS 与原生点击展开，内容直接解释 SYSTEM（环境变量及 NO_PROXY）、DIRECT（忽略环境代理）和 CUSTOM（始终使用显式 HTTP(S)/SOCKS5 代理），并明确 TLS 与代理模式独立。
- 前端契约和 JS 语法已纳入 18.2 的 `45 passed` 专项；桌面浏览器验证帮助点击、开关启停/恢复和无溢出布局。迁移后的 DeepSeek Provider 使用 SYSTEM + `verify_ssl=true` 真实测试返回 HTTP 200，页面行内显示可用；未点击保存。

##### 18.4 集成回归与本地提交（completed，2026-07-22）

- `npm run build` 通过且 Workflow 构建产物无 Git 差异；Python `compileall`、模型管理 JS 与 Workflow bundle 语法检查、`git diff --check` 全部通过。
- 全量 `uv run pytest -q` 结果 `203 passed, 6 skipped, 1 warning`；6 项跳过仍是未向本轮进程注入真实供应商环境变量的 live 用例，warning 为既有 Starlette/httpx 弃用提示。
- 浏览器完整流程确认正向 TLS 默认值、模式帮助、关闭验证的不安全提示、SYSTEM 状态恢复和 DeepSeek 真实 HTTP 200；未保存或修改用户 Provider。
- Git 差异未包含画布文件，API Key 形式秘密扫描结果为 0。按用户最新要求只创建本地提交，由用户自行推送当前分支。

#### 验收标准与价值验证（How to Measure）

- 相同代理模式不因 BASE_URL 是公网 IP、内网 IP 或域名而改变；CUSTOM 始终使用用户填写的代理。
- `verify_ssl=true` 时不向 HTTPX 注入 `verify=False`；关闭开关后所有代理模式统一使用 `verify=False`。
- 帮助提示明确说明三种模式与 TLS 独立关系；默认页面显示证书验证开启。
- 现有 Provider 的旧 `skip_ssl_verify` 值迁移后语义保持一致，API Key 和代理密码不进入列表或日志。

## 22. 待优化项目

### 22.1 独立凭据仓储与绑定

- 建立仅保存在本机的加密或受保护凭据仓储，支持 API Key、Bearer Token、Basic Auth、Cookie、自定义 Header、Client Secret 和证书等类型。
- 工具模板只声明凭据需求，不保存真实秘密；Workflow 可设置默认凭据，节点可按需覆盖。
- 节点保存 `credential_id` 或槽位绑定，运行时只在内存中解析并注入 `config["credentials"]`。
- 模板独立测试、节点运行和 Workflow 运行共用缺失凭据预检查及“绑定并运行”流程。
- 画布内复制节点可保留同机绑定；发布模板和导出 Workflow 必须剥离本机凭据 ID；导入后显示未绑定并要求接收者重新选择。
- 删除或失效凭据后，引用节点必须进入明确的“凭据失效”状态并禁止运行。
- 对日志、错误、Artifact 和用户主动打印内容增加已知秘密值脱敏；明确无法可靠识别任意 Python 硬编码秘密的残余风险。

### 22.2 Provider 自定义 CA Bundle

- 在模型管理供应商详情增加可选的本机 CA Bundle 配置，支持企业内部 CA 和自签名根证书；文件路径和证书内容不得进入 Workflow 或导出数据。
- 运行时使用 `ssl.create_default_context(cafile=...)` 构建 HTTPX SSLContext，并保持 `verify_ssl=true`；模型发现、测速、单模型测试、Workflow 阻塞和流式请求必须复用同一证书上下文。
- CA 文件缺失、格式错误或不可读取时在发起网络请求前给出明确错误；不得静默降级为 `verify=False`。
- UI 优先引导用户配置内部 CA，关闭“验证 SSL 证书”仅保留为可信内网临时联调手段，并持续显示“不安全”状态。

### 22.3 SCRIPT 节点待优化项

#### 业务背景与目标（Why）

- SCRIPT 是企业 Agent 测试流程中的 Python 胶水层，用于调用公网或内网接口、读取和转换数据、执行规则校验、聚合结果并向后续节点输出多个业务变量。
- 当前产品面向本机使用，核心价值是“普通非交互 Python 在环境和权限允许时可直接运行、原始控制台可以排错、顶层变量可以稳定传递”，不是建立受限插件生态。
- 优化目标是提高运行配置的真实性、单节点测试的可复现性和 Python 环境问题的可诊断性，同时继续遵守原始日志铁律。

#### 目标用户与真实场景（Who & Where）

- Workflow 编排人员在 Workflow Studio 中编写和调试 Python，通过 `inputs` 读取全局变量和上游输出，并将明确配置的 Python 顶层变量映射为下游 `${变量名}`。
- 用户会直接复用在 PyCharm 中运行的 `requests`、JSON 处理、文件处理和业务校验代码，需要看到真实 stdout、stderr、traceback 和依赖错误。
- 单节点调试经常需要复用上游某次成功输出；如果只能隐式读取“最近一次成功结果”，测试输入可能陈旧或随历史运行变化，无法稳定复现问题。

#### 行业调研结论

| 产品 | Code / Function 节点的代表能力 | 对 Agent Bench 的适用判断 |
|---|---|---|
| Dify | Python/JavaScript、声明式输入输出、独立沙箱、自动重试、失败分支和输出限制 | 借鉴重试与失败语义；严格沙箱不符合当前真实 Python、内网请求和文件处理定位 |
| n8n | 整批/逐条执行、固定并编辑测试数据、独立 Task Runner、代码格式化和受控依赖 | 优先借鉴固定测试输入；逐条/整批模式需等待数组、循环和聚合协议 |
| Node-RED | 多输出、异步完成、节点/流程/全局状态、启动/停止钩子、日志级别和动态状态 | 更适合长期事件流；持久状态和生命周期会降低本项目测试可复现性 |
| Langflow | 类型化输入输出、Python Interpreter、Mock Data、依赖声明、Check & Save | 借鉴语法检查、依赖诊断和测试数据能力，不引入其完整组件框架 |
| Flowise | 显式输入变量、全局变量、运行时状态、工具调用和沙箱执行 | 显式变量已具备；工具调用和运行时状态当前会扩大执行协议和维护成本 |

参考资料：

- Dify Code：<https://github.com/langgenius/dify-docs/blob/main/en/self-host/use-dify/nodes/code.mdx>
- n8n Code：<https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.code/>
- n8n Pin and Mock Data：<https://github.com/n8n-io/n8n-docs/blob/main/docs/build/work-with-data/pin-and-mock-data.md>
- Node-RED Function：<https://nodered.org/docs/user-guide/writing-functions>
- Langflow Python Interpreter：<https://docs.langflow.org/python-interpreter>
- Flowise Custom Function：<https://github.com/FlowiseAI/Flowise/blob/main/packages/components/nodes/utilities/CustomFunction/CustomFunction.ts>

#### 需求真实性与优先级（What & When）

| 优先级 | 优化项 | 决策与原因 |
|---|---|---|
| P0 | 运行配置真实性 | 当前前端展示 `retryCount / retryInterval / delayExecution / repeatExecution`，后端实际只从 `data.config` 读取超时；界面值与执行行为不一致，属于正确性缺陷 |
| P0 | 超时与重试契约 | 优先落实节点超时、重试次数和重试间隔；每次尝试必须可追溯，总耗时累加，中断必须终止当前尝试及等待中的后续重试 |
| P0 | 暂停未定义配置 | “延迟执行”当前价值较低；“重复执行”涉及副作用、停止条件和多次结果合并。协议确认前隐藏或删除，禁止继续展示无效配置 |
| P1 | 固定测试输入/上游快照 | 单节点测试可选择并编辑确定的全局变量和上游输出快照，避免依赖上游最近一次成功结果；不得影响正式整图执行语义 |
| P1 | Python 语法检查 | 使用与 Worker 相同的 Python 解释器执行 `compile()`，在不启动节点运行的情况下返回准确文件名、行号、列号和原始错误 |
| P1 | 依赖检查与环境可见性 | 识别代码中可静态判断的顶层 import，显示已安装、缺失和版本；动态 import 明确标为无法静态确认；不得自动执行 `pip` 或修改环境 |
| P2 | 显式代码格式化 | 只在用户主动点击时格式化 Python，不在保存或运行时静默改写代码；格式化失败不得覆盖原代码 |
| P2 | 常用起始模板 | 提供 HTTP 请求、JSON 转换、断言校验和多个顶层输出变量等最小模板，帮助用户快速写出可运行代码，但不恢复工具仓库或模板运行时引用 |
| P2 | 文件与 Artifact 输出 | 为报告、图片、大型 JSON 等非普通变量结果建立受控 Artifact 契约，避免把大文件或 Base64 数据塞入节点变量；不得暴露任意本机路径 |
| P3 | 代码持久化历史与 Diff | 在多人协作或版本追溯需求明确后再实现，不阻塞当前本机快速迭代 |
| P3 | 资源限制与更强隔离 | 当前继续使用独立子进程；只有产品转为远程、多用户或执行不可信代码时，才把容器隔离、CPU/内存限制升级为 P0 |

#### 保持不变的执行与日志契约

- SCRIPT 继续只支持 Python，不增加 JavaScript、交互式 stdin、桌面 GUI、完整断点调试器或插件市场。
- 用户代码继续运行在项目 `.venv` 的独立子进程中，允许使用已安装标准库和第三方包；依赖仍通过 `pyproject.toml + uv sync` 显式管理。
- `print()`、stdout、stderr、Python traceback 和平台警告继续按接收顺序显示原始内容，不做结构化提取、重组、摘要替换或自动脱敏推断。
- 日志只用于诊断，不参与业务变量提取；节点输出继续来自输出区明确映射的 Python 顶层变量。
- 未配置输出变量时脚本可以成功；已配置但不存在的顶层变量继续输出 `null`、写入原始警告并保持 `SUCCESS`；真实执行异常仍为 `FAILED`。
- 不增加持久节点上下文、启动/停止钩子或隐式跨 Run 状态，避免测试结果依赖历史执行。
- 不增加“逐条/整批执行”、多输出路由或 Script 内调用其他画布工具，除非数组、条件分支、循环、聚合和副作用规则先完成独立业务确认。

#### 待确认的业务规则

- 重试范围：只重试异常、超时和明确的可重试错误，还是所有 `FAILED`；用户代码已经产生外部副作用时是否允许自动重试。
- 重试日志：每次 attempt 独立保留完整控制台，还是在同一节点运行记录中按 attempt 分段；两种方案都不得丢失原始文本。
- 固定测试输入是否持久化到 Workflow 草稿。建议采用 n8n 语义：只对单节点调试生效，正式整图执行始终忽略固定数据并使用真实上游输出，实施前必须确认。

#### 验收标准与价值验证（How to Measure）

- 配置重试 2 次时，最多执行 3 个 attempt；每次开始时间、结束状态、错误、控制台和耗时可追溯，节点总耗时等于全部尝试与间隔的累计时间。
- 节点运行、重试等待或延迟阶段点击中断后，不再开始新的 attempt；当前 Worker 及派生进程被终止，节点状态为 `INTERRUPTED`，后代节点不执行。
- 节点设置页不存在任何保存后不影响执行的运行配置；未完成后端契约的字段必须隐藏或标为不可用，不能以可编辑状态误导用户。
- 单节点测试可以固定、编辑、清除和重新获取输入快照；同一快照重复运行得到相同输入，正式整图运行不读取测试快照。
- 语法错误在 Worker 启动前返回 `<workflow-node-main.py>` 的准确行号、列号和原始消息；检查过程不产生节点运行记录。
- 依赖检查能列出已安装包及版本和明确缺失包；不会安装包、修改 `pyproject.toml`、执行用户代码或声称动态 import 已验证。
- 原始控制台在成功、失败、超时、重试和中断场景中始终保留真实 stdout、stderr 与 traceback 顺序，继续支持鼠标选择、原生 `Ctrl+C` 和整段复制。
- 多个输出变量仍按“对外变量名 + Python 顶层变量名 + 类型”独立转换并传递；新增优化不得恢复基于日志、`request` 或固定 `response` 结构的 Script 字段提取。

#### 实施顺序与验证门禁

1. **运行配置审计与协议冻结**：列出前端所有配置字段、持久化位置和后端消费者；确认重试、副作用、attempt 日志与测试快照规则。验证为字段到行为的一一对应表，未确认项不得进入实现。
2. **超时与重试后端闭环**：实现 attempt、累计耗时、中断和后代阻断，并补充异常、超时、先失败后成功、连续失败和重试等待中断测试。专项测试通过后再改前端。
3. **运行配置 UI 收敛**：只展示已经具备后端行为的字段，移除或隐藏延迟/重复执行；使用真实 API 和浏览器 E2E 验证保存、重开、运行与日志。
4. **固定测试输入**：在不影响正式执行的前提下实现测试快照 CRUD 和单节点执行入口；覆盖上游历史变化、快照清除和整图忽略快照。
5. **语法与依赖诊断**：复用 Worker Python 环境完成只读检查；覆盖标准库、已安装第三方包、缺失包、动态 import 和语法错误。
6. **P2 能力评估**：模板、格式化和 Artifact 分别按独立业务需求立项，每项都需单独测试，不与 P0/P1 打包上线。

每个子任务必须依次执行相关单元测试、静态检查、前端构建、真实 API 流程和桌面浏览器 E2E；前一项未通过时暂停依赖任务。完整回归必须继续覆盖 Script 普通 Python、原始日志、多个顶层输出变量、超时、中断、后代阻断以及 HTTP/AGENT/LLM 节点不回归。

### 22.4 HTTP 节点待优化项（调研完成，开发未开始）

#### 状态与决策边界

- 本节记录 2026-07-23 对 Dify、n8n、Azure Logic Apps 和 Postman 官方能力的调研结论，以及结合企业 Agent 测试场景形成的候选优化项。
- 本节不是已确认开发需求。除已在历史沟通中明确的规则外，标记为“待确认”的行为不得直接实现。
- HTTP 节点的目标不是复制完整 Postman，而是稳定调用内网 FastAPI 或真实企业 Agent 环境、传递上游变量、保留可追溯原始请求与响应，并为下游 SCRIPT / AGENT 分析提供可靠数据。

#### 业务背景与目标（Why）

- 当前基础请求编辑能力已经覆盖 Method、URL、Headers、Params、Body、cURL 导入、`${变量名}` 替换、类型化输出变量和原始请求/响应日志；继续堆叠普通 API 客户端功能的边际价值有限。
- 主要风险转为执行正确性和规模承载：部分运行配置只在前端保存但后端不消费；Body 类型存在界面可选但运行协议不完整的情况；非 2xx 响应无法继续提取变量；大响应完整进入 SQLite 和浏览器后会在批量 Run 中放大存储与渲染成本。
- 优化顺序应为“执行正确性 > 结果可追溯 > 内网连接能力 > 功能广度”。

#### 用户与真实场景（Who / Where）

- 企业测试工程师在本机画布中配置 HTTP 节点，调用内网 FastAPI 数据提取层或未来真实企业 Agent 环境。
- 单次企业 Agent 调用可能持续四到五分钟，响应可能包含数百到数千行数据；测试人员需要在失败后查看原始请求/响应，并把结构化字段继续传递给下游节点。
- 并发数、整批重复执行、定时任务和 Run 级等待策略属于 Run 调度，不应继续堆在单个 HTTP 节点中。

#### 同类产品能力对照

| 能力 | 同类产品 | 当前状态 | 候选结论 |
|---|---|---|---|
| Method、URL、Headers、Params、Body | Dify / n8n 标配 | 已支持 | 保留现状 |
| cURL 导入 | n8n / Postman 支持 | 已支持 | 当前足够，不优先增加 OpenAPI 导入或 cURL 导出 |
| 上游变量引用 | Dify 支持深层变量，n8n 支持表达式 | 已支持 `${变量名}` 和输出提取 | 保持受限表达式，后续可补变量选择与插入交互 |
| 超时 | Dify 区分连接、读取、写入；n8n 支持请求超时 | UI 没有真实超时输入；Worker 外层默认 120 秒，HTTPX 内层默认 30 秒 | P0：统一单一配置来源并真实生效 |
| 重试 | Dify 支持次数/间隔；Logic Apps 支持固定/指数策略 | `retryCount / retryInterval` 只在前端保存 | P0：实现已确认的连接失败/超时重试 |
| Body 类型 | Dify / n8n 支持 JSON、Raw、URL encoded、multipart 和文件 | RAW 可用；FORM_DATA 由 `data=` 发送；Binary 界面可选但后端拒绝 | P0：修正真实协议或隐藏尚不可用入口 |
| HTTP 错误策略 | Dify 支持错误分支；n8n 支持 Never Error | 非 2xx 一律 FAILED，不能提取输出变量 | P0/P1：允许保留响应并按策略决定是否继续 |
| 响应结构 | Dify 输出 body/status/headers/files；n8n 可返回完整响应 | 已输出 `status_code / headers / body` | 当前结构可保留 |
| 大响应处理 | 常见文件变量、Artifact、截断预览或响应优化 | 完整响应进入 SQLite 和浏览器 | P0：建立完整 Artifact 与受控预览 |
| 认证与凭据 | Basic、Bearer、API Key、OAuth、凭据复用 | 只能手填 Header | P1：依赖 22.1，先做本机凭据绑定，不一次实现全部 OAuth |
| SSL、代理、重定向 | Dify / n8n 提供节点或连接配置 | 后端存在隐藏默认值，前端不可设置 | P1：复用 Provider 的显式路由和 TLS 语义 |
| 分页、批处理 | n8n 支持 | 不支持 | 当前企业 Agent 调用场景不需要，暂缓 |
| 请求前后脚本 | Postman 支持 | 可通过独立 SCRIPT 节点实现 | 不并入 HTTP 节点 |

#### 候选优先级（What / When）

##### P0：执行正确性与规模风险

1. **统一并落实超时与重试**
   - 删除当前 HTTPX 30 秒与 Worker 120 秒的隐式双重默认，建立可解释的单一配置来源。
   - 已确认规则继续有效：连接失败或超时按自定义次数和间隔重试；收到业务响应后不重试。HTTP 429/5xx 是否属于可重试服务失败仍未确认，不得自行加入。
   - 每次尝试必须记录序号、失败类型、等待时间和最终结果；中断必须终止当前请求和后续重试。

2. **修正 Body 类型真实性**
   - `application/x-www-form-urlencoded` 必须按 URL encoded 发送，`multipart/form-data` 必须产生真实 multipart 请求。
   - 切换 Body 类型时必须处理新建节点默认的 `Content-Type: application/json`，避免表单数据仍声明为 JSON。
   - Binary 在文件变量、持久化和 Artifact 协议确认前不得继续表现为已可运行功能。

3. **保留失败响应并支持后续分析**
   - 只要远端已经返回 HTTP 响应，就必须保留并允许提取 `response.status_code / response.headers / response.body`。
   - 节点状态与 Workflow 是否继续执行必须拆开定义，支持负向测试用例分析 400、401、422、500 等响应；默认继续还是默认终止仍待确认。

4. **大响应 Artifact 化**
   - 完整原始响应保存为本机 Artifact，运行记录保存路径或 ID、大小、摘要、哈希和受控预览；不得只截断后丢失原文。
   - 输出变量提取必须针对完整响应执行，不得因日志预览截断而改变测试判断。
   - Artifact 大小上限、保留周期、压缩方式和清理策略尚未确认。

##### P1：内网连接与可维护性

- 依赖 22.1 增加本机凭据绑定，首批只考虑 Bearer、API Key、Basic 和自定义 Header；真实秘密不得进入 Workflow 导出、Git 或普通日志。
- 为 HTTP 节点或 Target 建立显式 `SYSTEM / DIRECT / CUSTOM` 代理模式、正向 SSL 验证开关、按需自定义 CA 和重定向策略；不得按公网/内网 IP 自动猜测路由。
- 在 Headers、Params、Body 等字段增加可见变量选择/插入，不扩展为任意 Python 或 JavaScript 表达式。
- 增加变量解析后的请求预览，但凭据和已知秘密必须脱敏；原始执行日志继续记录真实请求的非秘密部分。

##### P2：有真实用例后再评估

- 重复 Query 参数和数组编码格式、Cookie Jar、客户端证书、OAuth1/OAuth2、文件上传/下载、分页和批处理。
- GraphQL、SSE、WebSocket、gRPC 等协议不作为当前 HTTP 节点的隐式扩展。

#### 明确不并入 HTTP 节点的能力

- 并发数、整批重复执行、延迟执行和定时任务属于 Run 调度。
- 业务断言、响应质量判断和前后置脚本分别由 SCRIPT / AGENT 节点承担。
- 面向 LLM 的通用“响应优化”不替代当前明确、可追溯的输出变量提取。

#### 待确认决策

1. 超时口径：`A` 一次节点运行共享总超时预算；`B` 每次重试重新获得完整超时时间。当前推荐 A，但未确认。
2. 非 2xx 默认行为：`A` 节点标记失败但可配置继续下游分析；`B` 始终终止当前流程。当前推荐 A，但未确认。
3. Binary：`A` 先隐藏，等文件变量与 Artifact 协议完成后开放；`B` 立即实现本机文件上传。当前推荐 A，但未确认。
4. 配置覆盖层级：系统默认、Run 参数和节点参数之间的优先级尚未确认；不得自行定义覆盖关系。

#### 初步开发拆分（确认范围后执行）

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 |
|---|---|---|---|---|
| 22.3.1 | 超时与重试内核 | 节点/Run 配置；尝试记录与最终结果 | 本地慢服务、连接失败、超时、中断、非重试业务响应 | 待确认决策 1、4 |
| 22.3.2 | Body 协议真实性 | 四类 Body 配置；真实 HTTP 报文 | 本地 Mock 验证 Content-Type、原始字节、multipart 边界和变量替换 | 待确认决策 3 |
| 22.3.3 | 失败响应策略 | 非 2xx 原始响应；状态与继续策略 | 400/401/422/500 节点与下游变量 E2E | 待确认决策 2、真实 DAG 执行语义 |
| 22.3.4 | 大响应 Artifact | 完整响应；Artifact 元数据、预览和提取结果 | 大 JSON/文本/二进制响应、清理、恢复和浏览器性能测试 | Artifact 契约 |
| 22.3.5 | 凭据与网络选项 | credential_id、代理/TLS/CA/重定向 | 密钥脱敏、三代理模式、自签名 HTTPS 和导入导出测试 | 22.1、22.2 |
| 22.3.6 | 集成回归 | 完整 HTTP 节点业务流程 | 单元测试、构建、静态检查、桌面浏览器 E2E、全量回归 | 22.3.1-22.3.5 中本期范围 |

#### 候选验收标准（How to Measure）

- 页面展示的每个运行配置都必须被后端消费并能从运行记录证明生效，不允许继续存在“可填写但无执行语义”的控件。
- 连接失败/超时与收到 HTTP 响应必须可区分；重试次数、等待时间和最终状态可追溯，业务响应不会被默认重复调用。
- RAW、JSON、URL encoded、multipart 和未来 Binary 的页面名称、Content-Type、真实报文及日志一致。
- 非 2xx 响应原文和结构化字段不会丢失，是否继续执行遵循已确认策略。
- 大响应不直接无限制进入 SQLite 和浏览器，但完整原文仍可回溯，变量提取结果不受预览限制。
- HTTP 节点优化不得把 Run 调度、SCRIPT 断言或 AGENT 质量判断重新耦合进节点内部。

#### 调研来源

- Dify HTTP Request: <https://docs.dify.ai/en/cloud/use-dify/nodes/http-request>
- n8n HTTP Request: <https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest>
- Azure Logic Apps error handling and retry policies: <https://learn.microsoft.com/en-us/azure/logic-apps/error-exception-handling>
- Postman request settings: <https://learning.postman.com/docs/use/send-requests/create-requests/request-settings/>

### 22.5 DeepSeek `deepseek-v4-pro` LLM 节点高级参数实测（completed，2026-07-23）

#### 业务背景与验收口径

- Why：企业测试工程师需要在 Workflow LLM 节点直接覆盖模型请求参数，并能从节点日志确认参数确实进入请求、模型成功响应以及 token 消耗，避免仅依据供应商文档声明可用。
- Who / Where：本机 Agent Bench `http://127.0.0.1:8010/`，模型管理中的 `DeppSeek / deepseek-v4-pro`，专用 Workflow `deepseek-v4-pro 高级参数验证`（ID `93fb7ecc003043ae942d6d605cdcbeea`）及 LLM 节点 `LLM_mrwdl894_rmnsw`。
- What / When：按用户确认的 `1A / 2A / 3A` 执行广泛兼容矩阵；请求字段进入实际 Body、节点成功且响应结构合理即记为“接口接受”，存在可观察语义时再单独证明生效。该 live 结果只代表 2026-07-23 当前供应商端点，不固化为跨模型通用契约。
- How to Measure：逐次通过高级参数 JSON 框保存并运行，核对持久化日志中的 `request_body / response_body / usage / error`；使用 JSON 输出、logprobs、工具调用、thinking 开关、stop 截断和流式 usage 作为可观察语义验证。

#### Live 矩阵结果

| 参数 / 组合 | 结果 | 可观察证据与边界 |
|---|---|---|
| `{}` | SUCCESS | 基线输出 `OK`，usage 完整 |
| `temperature / top_p / max_tokens / frequency_penalty / presence_penalty / stop` | 接受 | 全部进入请求；`max_tokens: 16` 将完成 token 限制为 16，`stop: ["XYZ"]` 将 `ABCXYZ` 截断为 `ABC` |
| `response_format: {"type":"json_object"}` | 生效 | 返回合法 JSON `{"result":"OK"}` |
| `logprobs: true / top_logprobs: 2` | 生效 | 阻塞响应包含逐 token `logprob` 与两个候选 `top_logprobs`，包括 reasoning token |
| `tools / tool_choice: "auto"` | 生效 | 返回 `finish_reason: "tool_calls"` 和 `get_weather({"city":"北京"})` |
| `tool_choice: "required"` | 有条件生效 | 默认 thinking 模式返回 HTTP 400 `Thinking mode does not support this tool_choice`；同时设置 `thinking.type: "disabled"` 后成功返回工具调用 |
| `thinking: {"type":"enabled"}` | 生效 | 响应包含 `reasoning_content` 与 `reasoning_tokens` |
| `thinking: {"type":"disabled"}` | 生效 | `reasoning_content` 为 null，短提示只消耗 1 completion token |
| `max_completion_tokens` | 接受 | `max_completion_tokens: 16` 请求成功并返回结构化 usage |
| `stream_options: {"include_usage":true}` | 生效 | 必须配合右侧“流式输出”开关；最终 SSE chunk 包含 usage。流式 response 仍保留原始 SSE，同时从 usage 事件提取并持久化顶层 `usage` 供日志展示 |
| `n` | 仅支持 1 | `n: 1` 成功；`n: 2` 返回 HTTP 400 `currently only n = 1 is supported` |
| `seed / user` | 接受但无法证明生效 | 请求成功且字段进入 Body；当前响应没有足以证明语义生效的信号 |
| `enable_thinking: false` | 接受但未生效 | 请求成功，但响应仍包含 reasoning 且 32 个 completion token 全为 reasoning；不得用它替代 `thinking.type: "disabled"` |
| `reasoning_effort: "low"` | 接受但无法证明生效 | 请求成功，但仍生成完整 reasoning；没有观察到可区分效果 |
| `top_k / min_p / repetition_penalty` | 接受但无法证明生效 | 组合请求成功；供应商会静默接受未知字段，因此不能据此宣称采样语义已实现 |
| 未知字段对照 | 被静默接受 | `definitely_not_a_real_parameter: true` 仍 SUCCESS，证明“HTTP 成功”只能说明网关接受，不能单独证明字段被模型消费 |

#### 结论与保留状态

- 已直接观察到语义生效的参数：`max_tokens`、`stop`、`response_format`、`logprobs`、`top_logprobs`、`tools`、`tool_choice`、`thinking`、`stream_options`。官方候选 `temperature`、`top_p`、`frequency_penalty`、`presence_penalty` 和兼容字段 `max_completion_tokens` 均被当前端点接受，但本轮没有为每个采样参数建立统计显著的独立效果证明。
- `stream` 不属于高级参数框的可编辑字段，画布右侧“流式输出”开关是唯一入口；节点保存时由平台写入最终请求。
- 不推荐依赖 `enable_thinking`、`reasoning_effort`、`top_k`、`min_p`、`repetition_penalty`、`seed` 或 `user`，除非后续增加能证明实际语义的对照测试。
- 专用 Workflow 和最近 10 条节点运行日志已保留；节点当前停在已验证的非流式配置 `thinking.disabled + temperature 0 + top_p 0.8 + max_tokens 128`。节点历史上限固定为 10，完整矩阵以本节为长期记录。
- 官方候选参数来源：DeepSeek Chat Completion 文档 <https://api-docs.deepseek.com/api/create-chat-completion>。

### 22.6 LLM JSON 参考示例与格式化（completed，2026-07-23）

- Why：企业测试人员需要在 LLM 节点和模型默认 Body 中快速识别常用 DeepSeek 参数，但参考内容不能自动改变模型行为、token 成本或已保存配置。
- Who / Where：Workflow LLM 节点“高级参数”编辑器，以及模型管理单模型“默认 Body JSON”配置弹窗。
- What / When：按用户确认的 `1A / 2C / 3A`，两处空编辑器只显示同一组浅色斜体 placeholder；用户输入后参考内容自动消失，不写入状态、不参与请求。两处右上角均提供 Beautify，合法 JSON 对象格式化为两空格缩进，无效 JSON 保留原文并显示错误。
- 模型配置弹窗保持原有 `560px` 宽度，默认 Body 编辑区通过更高优先级样式固定最小高度 `280px`，解决通用 `.input` 将其压缩至 `42px` 最小高度的问题；实测整张弹窗高度为 `542px`，桌面视口内无溢出。
- Workflow LLM 节点高级参数正文同步提升至最小高度 `280px`（含 `34px` 工具栏的编辑器整体最小高度 `314px`）；实测正文 `280px`、整体含边框 `316px`，与运行配置间隔 `43px`，节点编辑器内部滚动且无模块重叠。
- 验收：空 LLM 参数只显示参考值；输入后 placeholder 消失；两处 Beautify 均完成真实页面格式化；无效 JSON 分别显示“高级参数不是合法 JSON”和“默认 Body 不是合法 JSON”；取消弹窗和重载 Workflow 后，模型默认 Body 与节点参数均保持原持久化值。

### 22.7 节点日志请求/响应标题与流式 token（completed，2026-07-23）

- Why：节点调试需要快速区分完整 request/response 并直接复制；LLM 流式运行此前固定保存 `usage=None`，日志行无法显示实际 token 消耗。
- Who / Where：桌面 Workflow Studio 中展开 HTTP、LLM 或其他业务节点的单次运行日志；LLM 用户同时覆盖 OpenAI-compatible 与 Anthropic 协议的流式调用。
- What / When：请求/响应标题统一为 `request / response`，标题字号与日志行时间同为 `14px`，标题行最右侧提供复制完整内容的图标按钮。OpenAI-compatible 流式请求由平台写入 `stream_options.include_usage=true`；流结束后从 OpenAI usage 事件或 Anthropic `message_start / message_delta` 事件合并 usage 并持久化。
- 边界：流式 response 仍保存并展示脱敏后的原始 SSE，不提取流式输出变量；usage 解析失败或供应商未返回 usage 时保持 `None`，不把估算值冒充真实 token。历史记录若 `usage` 为空但原始 SSE 含 usage，前端只为展示提取该真实值，不回写或改造历史数据。
- 验收：HTTP 与 LLM 日志均显示 `request / response`、复制按钮位于标题最右侧且复制完整正文；OpenAI 流式运行记录保存 `total_tokens`，Anthropic 保存合并后的 `input_tokens / output_tokens`，前端日志行显示对应 token 总数。

## 23. Node Structural Model 独立持久化（completed，2026-07-26）

### 23.1 新节点表、模型与 Repository（completed）

- Why：Node Structural Model 必须成为关系型数据库中的独立权威定义，与旧 Workflow JSON 聚合存储和本地 Execution JSON 完全解耦。
- Who / Where：本机 Workflow Studio 后续保存 START / SCRIPT / LLM / HTTP / END 节点时，通过 `execution/node_structural_models.py` 写入 `run_storage/agent_bench.sqlite3`。
- What：采用用户确认的 `1A / 2A / 3=旧链路全部删除`。节点当前不存 `workflow_id`；公共字段使用关系列，类型专属字段保存为严格校验后的 `definition_json`；不迁移旧 Workflow 数据。
- 表：`node_structural_models(id, type, name, description, definition_json, created_at, updated_at)`；`type` 和 JSON object 由 SQLite CHECK 约束，`type/updated_at/id` 建联合索引。
- 类与字段说明：所有节点 Pydantic 类和 Repository 领域异常均提供中文职责 docstring，全部 Pydantic 字段通过 `Field(description=...)` 提供业务说明；数据库表与全部七列通过 `NODE_STRUCTURAL_TABLE_DESCRIPTION` 和 `NODE_STRUCTURAL_COLUMN_DESCRIPTIONS` 提供可直接生成数据字典的程序可读详细说明。
- Repository：支持 initialize/create/get/list/update/delete；写入前使用 START/SCRIPT/LLM/HTTP/END 判别联合模型严格验证，额外字段拒绝，UUIDv4、变量类型、输出绑定、HTTP 网络与请求结构分别校验；`id` 和 `type` 创建后不可修改。
- 不兼容清理入口：Repository 初始化按依赖顺序删除 `workflow_node_runs / workflow_drafts / workflow_node_runs_v2 / workflow_runs_v2 / workflow_definitions_v2`。
- 验证：`uv run pytest tests/test_node_structural_models.py -q` -> `11 passed`。覆盖真实 SQLite Schema、字段说明完整性、五类节点重启恢复、公共列/definition_json 边界、CRUD、`type` 不可变、数据库 CHECK 与旧表删除。

### 23.2 旧 Workflow 后端与前端耦合链路删除（completed）

- 结果：已删除旧 Workflow contract/repository/engine/adapter/API 和相关测试；首页删除“工作流管理”入口及 Workflow bundle 加载，`execution.js` 收敛为 Target 管理，不再调用 `/api/workflows`。
- 保留边界：`web/frontend/workflow-canvas.jsx`、对应 CSS 以及现有构建产物仍保留，但不从首页加载、不连接已删除 API，待新节点 API 和未来 Workflow 关联模型确认后再接入。
- 路由验收：`/api/workflows` 与 `/api/workflow-drafts` 均返回 404；未保留兼容层。
- 验证：`uv run pytest tests/test_web_app.py tests/test_targets.py tests/test_set_frontend.py tests/test_model_providers_frontend.py tests/test_faq_frontend.py tests/test_theme_frontend.py -q` -> `49 passed, 1 warning`；warning 为既有 Starlette/httpx 弃用提示。
- 依赖：23.1 已验证通过。

### 23.3 Node Structural Model 数据字典与真实数据库初始化（completed）

- 目标：在 `WORKFLOW_SPEC.md` 记录代码类、全部字段、SQLite 表、全部列、JSON 边界及五类 definition 的详细说明，并只对真实数据库定点初始化新表和删除旧 Workflow 表。
- 文档完成：`WORKFLOW_SPEC.md` 第 2.3 节已经逐类说明所有节点结构类、逐字段说明公共/START/SCRIPT/LLM/HTTP/END 及嵌套结构，记录 Repository 返回字段与 CRUD，并给出 SQLite 七列、约束、索引和各 type 的 `definition_json` 顶层字段边界。
- 范围纠正：删除规范中已过时的 Workflow/Edge Structural Model 持久化示例，明确当前没有 Workflow/Edge 表、Repository、API 或 Workflow Execution，不得向独立节点表补入 `workflow_id`。
- 防回归验证：新增反射测试，要求 `execution/node_structural_models.py` 中每个定义类都有 docstring、每个 Pydantic 字段都有 description；`uv run pytest tests/test_node_structural_models.py -q` -> `12 passed`。
- 旧表范围复核：真实数据库还存在两代更早的 Workflow/Run/评测流水线表；现行代码全仓检索确认无引用后，显式旧表清单扩展为 16 张表，并增加“删除旧表但保留 Target 表和数据”的自动化测试。
- Repository 交叉回归：`uv run pytest tests/test_node_structural_models.py tests/test_targets.py tests/test_model_providers.py -q` -> `67 passed, 1 warning`；warning 为既有 Starlette/httpx 弃用提示。
- 真实数据库：已对 `run_storage/agent_bench.sqlite3` 执行 `NodeStructuralRepository.initialize()`。新表七列顺序为 `id/type/name/description/definition_json/created_at/updated_at`，索引存在，16 张旧表剩余数为 0。
- 数据保全：初始化前后 `targets=0`、`model_providers=4`，计数一致；初始化后现行表仅为 `model_providers / node_structural_models / targets`。
- 依赖：23.1、23.2 已验证通过。

### 23.4 完整回归与交付检查（completed）

- 目标：运行全量 pytest、Python 编译检查、前端构建、FastAPI 路由和桌面完整业务流程回归，并检查 Git diff 与未覆盖风险。
- 单元与模块回归：`uv run pytest` -> `131 passed, 4 skipped, 1 warning`。4 项 skipped 是当前进程未注入真实模型密钥的 live 用例；warning 为既有 Starlette/httpx 弃用提示。
- 静态与构建：`uv run python -m compileall -q execution web storage` 成功；`npm run build` 成功生成保留但不加载的 Workflow Studio bundle；`git diff --check` 通过。
- 数据库验收：真实 SQLite `PRAGMA integrity_check=ok`，`PRAGMA foreign_key_check=[]`；节点表 SQL、七列和联合索引与文档一致。
- 浏览器 E2E：在 `http://127.0.0.1:8010/` 真实桌面页面确认一级导航只包含测试集、Target、模型管理和 FAQ；Target 管理可加载；模型管理仍显示 4 个供应商；浏览器控制台无 error。
- 未覆盖范围：没有运行需要真实供应商凭据的 4 项 live 模型测试；Node Structural Model 尚未提供 Web CRUD API，也未重新接入保留的 React Flow Studio，这两项均符合本阶段只建节点类、Repository 和数据库表的已确认范围。
- 依赖：23.1 至 23.3 已验证通过。

## 24. Workflow Structural Model 与 Execution Model（design in progress，2026-07-26）

### 24.1 业务背景、目标与范围

- Why：Workflow 管理的目标是让用户开发、调试和反复验证一张可执行 DAG；工作流结构必须成为数据库中的当前权威定义，每次手动执行必须形成可离线回溯且不污染结构定义的本地 JSON 事实。
- Who / Where：当前用户是本机 Workflow 管理页面中的工作流开发者；在画布中创建、编辑、保存、单节点测试、手动运行完整 Workflow，并从真实 Context、节点结果、错误和原始日志判断 Workflow 是否可用。
- What / When（P0）：实现 Workflow/Node/Edge 关系型持久化、完整图校验、手动 Workflow Execution、全局中断、Fail-Fast、Context 传递、Execution JSON、节点原始日志和执行记录目录入口。
- What / When（后续模块，不进入当前 P0）：导入 Excel、读取用例与期望结果、选择已验证 Workflow、把每行数据映射为输入、调度高并发执行和汇总批量结果。
- 顶层隔离：数据库严格只保存 Structural Model；Workflow/Node/未来 Batch Execution 严格只保存本机 JSON。不得创建 Execution 数据库表、索引、摘要或日志表。

### 24.2 Workflow Structural Model 已确认契约

- 表结构采用三张严格关系表：
  - `workflow_structural_models(id, name, description, created_at, updated_at)`。
  - `workflow_node_bindings(workflow_id, node_id, position_x, position_y)`，复合主键 `(workflow_id,node_id)`，`node_id` 全局 UNIQUE。
  - `workflow_edges(id, workflow_id, source_node_id, target_node_id)`，`(workflow_id,source_node_id,target_node_id)` UNIQUE。
- `node_structural_models` 不增加 workflow_id。Workflow 通过 binding 引用 Node；一个 Node 实例只能属于一个 Workflow，复用时必须复制为新的 Node。
- Workflow 模型只保存 binding 引用和坐标，不嵌入 Node 完整定义；后端读取画布时通过 JOIN 组装。Execution structural_snapshot 为离线自包含而展开完整 Node。
- Workflow 名称全局唯一，保留用户输入的首尾空白并按完整原文比较；纯空白名称无效。一级列表业务字段只展示名称、说明、更新时间。
- 类边界：`WorkflowStructuralModel` 保存 id/name/description/nodes/edges；`WorkflowStructuralRecord` 组合 workflow 与数据库管理的 created_at/updated_at；binding 使用 `node_id/position_x/position_y`；Edge 使用 `id/source_node_id/target_node_id`。
- 数据库完整性：Workflow 删除级联 binding/Edge；Node 删除级联 binding；Edge source/target 使用 `(workflow_id,node_id)` 复合外键引用 binding，保证两端属于同一 Workflow。
- 不允许长期存在未绑定 Node。新增画布 Node 时在同一事务创建 Node 和 binding；已绑定 Node 的所有修改统一经过 `WorkflowStructuralRepository`。
- 前端编辑只是会话草稿；用户点击保存时执行完整校验，并用一个数据库事务原子保存 Workflow、Node、binding 和 Edge。失败全部回滚，成功后立即成为新 Execution 使用的当前定义。
- 从当前 Workflow 删除 Node 时删除当前 Node/binding/Edge，但保留历史 Execution JSON；删除整个 Workflow 时才清理全部历史 Execution。存在活动 Execution 时禁止删除 Workflow，必须先全局中断并等待终态。

### 24.3 图结构与 START/END 已确认契约

- 每个可保存、执行的 Workflow 必须恰好包含一个 START 和一个 END；前端未保存草稿可以暂时不完整，但不完整结构不能进入数据库。
- START 是唯一根节点、无入边并能到达所有其他节点；END 是唯一叶节点、无出边且所有其他节点都能到达 END。
- 整图必须是一个弱连通 DAG；拒绝空 Workflow、只有 START/END、游离节点、独立子图、自环、重复 Edge 和有向环。至少包含一个 SCRIPT/LLM/HTTP 业务节点。
- 多上游节点固定使用 AND Join；所有直接上游 SUCCESS 后才具备运行资格。所有同轮具备资格的节点并发启动，不设置 Workflow 级节点并发上限。
- START inputs 固定为 `name / type / value`；value 是用户在 START 编辑表单填写并保存到 Structural Model 的严格 JSON 值，不使用 source/default/required，不在运行弹窗临时覆盖。
- START value 必须与 type 严格匹配，不执行隐式转换；inputs 成功时全部变量原子提交到空 Context。`inputs=[]` 仍创建立即 SUCCESS 的空 START Node Execution，但不产生 Context commit。
- END 不读取 Context、不声明 outputs、不执行用户代码或网络调用。END 创建立即 SUCCESS 的空 Node Execution，inputs/outputs 均为 `{}`，不产生 Context commit。
- Workflow SUCCESS 的唯一判定标志是 END Node Execution SUCCESS。

### 24.4 Workflow Execution Model 已确认契约

- 同一个 Workflow 允许多个 Execution 并发运行，每次使用独立 ID、结构快照、Context 和目录。Workflow 管理画布只限制当前手动 Execution 期间重复点击；未来外部批量调度器可并发创建同一 Workflow 的多个 Execution。
- 本地目录固定为：

```text
run_storage/workflow_executions/{workflow_id}/{workflow_execution_id}/
├── workflow.json
└── nodes/{node_execution_id}.json
```

- workflow.json 顶层字段固定为 `id / workflow_id / trigger / status / structural_snapshot / created_at / started_at / finished_at / duration_ms / context / nodes / error`。
- 当前 trigger 只保存 `{"type":"MANUAL"}`；未来 Batch 模块可扩展 `BATCH + batch_execution_id + case_id`，但这些字段不进入 Workflow Structural Model。
- 当前明确不保存顶层 inputs、updated_at、metadata、config、summary、structural_hash 或 scheduling.events。
- Execution 时间统一保存 UTC ISO-8601 毫秒格式；前端转换为 Asia/Shanghai 并显示 `MM-DD HH:mm:ss`。
- structural_snapshot 自包含 Workflow id/name/description、全部 Node 完整定义、坐标和 Edge；不包含数据库 created_at/updated_at。运行开始后只读取该快照，数据库后续修改不影响本次执行或重试。
- context 只保存 `commits / final`，不保存固定为空的 initial。非空 outputs 成功提交时追加 `sequence/node_id/node_execution_id/committed_at/values`，values 与 final 原子一致；零输出节点不生成 commit。
- workflow.json.nodes 只保存 `node_id/node_execution_id/state/reason`；state 固定为 `WAITING/RUNNING/FINISHED/NOT_STARTED`。READY 是执行器内部瞬时状态，不持久化，节点具体状态和时间从 Node Execution JSON 读取。
- 每个 Node Execution 保存最小 transitions 数组，用 `status/at/reason` 离线还原 PENDING、RUNNING 和终态变化；Workflow JSON 不重复保存完整调度事件。
- Workflow 状态固定为 `PENDING/RUNNING/SUCCESS/FAILED/INTERRUPTED`；error code 固定为 `NODE_FAILED/USER_INTERRUPTED/PROCESS_RESTARTED/PERSISTENCE_FAILED`。
- 节点内部中间尝试失败不终止 Workflow；只有 Node Execution 最终 FAILED 才触发全局 Fail-Fast。Fail-Fast 停止启动新节点，终止所有其他 RUNNING 节点并写入 `INTERRUPTED + WORKFLOW_ABORTED`；未启动节点不创建 Node Execution，在 workflow.json.nodes 中写入 `NOT_STARTED + WORKFLOW_FAILED`。
- 全局中断停止新调度并终止全部 RUNNING Worker；已 SUCCESS/FAILED 节点保持原状态。完整 Workflow 运行时禁止用户单独中断节点，单节点中断只属于前端临时测试。
- JSON 每次更新必须使用同目录临时文件、flush、fsync 和原子替换。Node 终态先落盘，再更新 workflow.json 的引用和 Context。
- 服务重启不自动续跑。遗留 PENDING/RUNNING Workflow 终结为 `FAILED + PROCESS_RESTARTED`，无终态 Node 终结为 `FAILED + RUNTIME_LOST`。
- Execution JSON 全部保留，界面最多展示最近 10 次。删除 Workflow 时先把该 Workflow 的 Execution 根目录原子移动到临时回收目录，再提交结构删除事务；事务失败恢复目录，成功后彻底清理。

### 24.5 Workflow 管理交互已确认契约

- 一级 Workflow 管理只服务开发和测试迭代，不承担 Excel、期望结果或批量调度。列表业务字段只显示名称、说明、更新时间。
- 用户可以从画布编辑和保存完整结构；完整 Workflow 手动运行直接使用已保存 START values，不弹出临时输入覆盖表单。
- 当前画布手动 Execution 未结束前运行按钮禁用，防止重复点击；底层引擎仍支持外部并发执行。
- 画布提供最近 10 次 Workflow Execution 的查看能力；列表行显示时间、状态、耗时，展开读取最终 Context、节点结果和 Workflow error。
- 新增“执行记录”按钮，点击后打开保存 Workflow/Node Execution JSON 的本地目录。日志和历史界面全部从 Execution JSON 映射，不创建独立日志文件或数据库记录。
- Node 单节点测试继续只形成前端临时快照，不创建 Workflow/Node Execution JSON，不进入历史；节点原始输出、请求、响应和错误遵守各节点现有日志契约。

### 24.6 执行阶段最终确认（completed，2026-07-26）

1. END 不在 Workflow 启动时创建。全部直接上游 SUCCESS、DAG 实际调度到 END 时才创建空 Node Execution，并立即 SUCCESS；随后 Workflow 才进入 SUCCESS。
2. 画布最近 10 次 Workflow Execution 历史继续保留；“执行记录”按钮固定打开当前 Workflow 的 Execution 根目录 `run_storage/workflow_executions/{workflow_id}/`，不跳入最近一次或选中的单次目录。

### 24.7 实施拆分（in progress）

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 |
| --- | --- | --- | --- | --- |
| 24.7.1（completed，2026-07-26） | Workflow Structural 类、三张表与 Repository | 当前 Node 表；Workflow/Binding/Edge 模型与事务 CRUD | 真实 SQLite Schema、FK、级联、唯一名称、重启恢复、事务回滚测试 | 无；结构层不依赖 24.6 的执行交互决策 |
| 24.7.2（completed，2026-07-26） | Workflow API 与完整校验 | Structural Repository；CRUD/保存/读取/删除 API | API CRUD、START/END、连通、DAG、变量唯一和模型引用测试 | 24.7.1 |
| 24.7.3（completed，2026-07-26） | Workflow 管理页面重新接入 | 保留 React Flow 源码；新版 API | 桌面浏览器创建、编辑、保存、重载、删除和错误提示 E2E | 24.7.2 |
| 24.7.4（completed，2026-07-26） | Workflow/Node Execution JSON 与调度器 | Structural snapshot；节点执行适配器 | 串行、并行、AND Join、Context、Fail-Fast、全局中断、原子写入、重启收敛测试 | 24.7.2、24.6 |
| 24.7.5（completed，2026-07-26） | 手动运行、单节点临时测试、执行记录与日志 | Execution JSON；画布入口 | START/END 空执行、单节点草稿/中断/零持久化、完整运行、失败、中断、最近 10 次、打开目录和原始节点日志 E2E | 24.7.3、24.7.4 |
| 24.7.6（completed，2026-07-26） | 全量回归 | 全部当前模块 | pytest、compileall、npm build、SQLite integrity、桌面完整流程 | 24.7.1-24.7.5 |

#### 24.7.1 验证记录

- 新增 `execution/workflow_structural_models.py`：定义 `WorkflowStructuralModel`、`WorkflowNodeBinding`、`WorkflowEdge`、record/summary、完整图校验和 `WorkflowStructuralRepository`；全部类和字段都有业务说明。
- 真实创建 `workflow_structural_models / workflow_node_bindings / workflow_edges`，通过复合外键保证 Edge 两端属于同一 Workflow；数据库不创建任何 Execution 或日志表。
- create/update/delete 将 Workflow、Node、binding、Edge 放在一个 `BEGIN IMMEDIATE` 事务内；更新失败回滚全部结构，删除 Workflow 同事务删除当前所属 Node。
- 保存前显式拒绝缺少/重复 START 或 END、纯系统节点、bindings 与 Node 不一致、自环、重复 Edge、有向环、非唯一根叶、不可达节点、重复 Context 变量和无效 LLM 模型引用。
- 验证命令：`uv run pytest tests/test_workflow_structural_models.py tests/test_node_structural_models.py -q`。
- 验证结果：`22 passed in 0.35s`。

#### 24.7.2 验证记录

- 新增 `web/routes_workflows.py` 并注册 `/api/workflows`：提供摘要列表、完整创建、详情读取、完整更新、元数据更新和删除。
- API 请求只接受完整 Node Structural Model、坐标和 Edge；明确拒绝旧草稿的 `global_variables`、节点 `config` 等额外字段，不提供独立 Node CRUD 入口。
- POST 由服务端生成 Workflow UUIDv4；PUT 复用路径 ID，名称保留首尾空白；列表响应只返回 `id/name/description/updated_at`。
- 无效图、重复名称和无效 LLM 模型引用返回明确 400，Pydantic 契约外字段返回 422，任何失败均不产生部分结构写入。
- 验证命令：`uv run pytest tests/test_workflow_api.py tests/test_workflow_structural_models.py tests/test_node_structural_models.py tests/test_web_app.py -q`。
- 验证结果：`31 passed, 1 warning in 0.79s`；warning 为既有 Starlette/httpx 弃用提示。
- 已在真实 `run_storage/agent_bench.sqlite3` 初始化三张 Workflow Structural 表；查询结果为 `workflow_edges / workflow_node_bindings / workflow_structural_models`，`PRAGMA integrity_check` 返回 `ok`。

#### 24.7.3 验证记录

- 一级导航重新接入 Workflow 管理；列表业务字段仅展示名称、说明、按本地 Asia/Shanghai 转换的更新时间，操作列提供编辑和应用内确认删除。
- React Flow 画布通过新版 `/api/workflows` 读取和保存完整 Structural Model；新建默认图固定为合法 `START → SCRIPT → END`，刷新后从数据库恢复相同 3 个节点、2 条 Edge 和坐标。
- 前端同步删除过时 AGENT、`global_variables` 和 LLM 流式开关；START 在节点设置中使用 `name/type/value`，SCRIPT/LLM/HTTP 输出统一使用 `name/type/source`。
- 当前 Structural 阶段显式禁用完整 Workflow 运行按钮，不请求尚未实施的 `/runs`，因此打开节点不会产生 `Not Found` 伪日志；24.7.4/24.7.5 完成后由真实执行接口启用。
- 非法图在前端保存前明确显示原因并进入“保存失败”，不会静默不保存；后端仍执行同一套权威校验作为最终防线。
- 构建与自动回归：`npm run build` 成功；`uv run pytest tests/test_workflow_frontend.py tests/test_workflow_api.py tests/test_workflow_structural_models.py tests/test_node_structural_models.py tests/test_web_app.py -q` -> `34 passed, 1 warning`。
- 浏览器 E2E：真实完成新增、保存、返回列表、重新打开、恢复 3 Node/2 Edge、START `question=请审核这段内容` 保存与重载、删除结构后的非法图提示、应用内确认删除、空列表恢复；最终浏览器 console error 为 0。
- 视觉验证：桌面列表和全屏画布截图无文字/控件重叠；画布首屏完整展示 START、SCRIPT、END 和两条连线。
- E2E 创建的临时 Workflow 已删除；真实数据库四张 Structural 表记录数均为 0，`PRAGMA integrity_check` 返回 `ok`。
- 本阶段完整回归：`uv run pytest -q` -> `149 passed, 4 skipped, 1 warning in 10.34s`；4 项跳过为未注入真实供应商凭据的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 静态与构建：`uv run python -m compileall execution web tests`、`npm run build`、`git diff --check` 全部成功。

#### 24.7.4 验证记录

- 新增 `execution/workflow_execution.py`：Execution JSON 原子存储、进程重启收敛、Structural Snapshot、Context commits/final、同轮并发 DAG 调度、AND Join、Fail-Fast、全局中断和 START/END/SCRIPT/LLM/HTTP 执行适配器。
- Execution 唯一事实固定写入 `run_storage/workflow_executions/{workflow_id}/{execution_id}/workflow.json + nodes/{node_execution_id}.json`；未创建任何 Execution、日志或状态数据库表。
- END 只在全部直接上游 SUCCESS、调度器实际选中后创建 PENDING/RUNNING/SUCCESS 空 Node Execution；任一上游失败或全局中断时 END 不创建文件。
- SCRIPT 复用可中断 Python Worker，顶层注入只读 `context`，保留原始 STDOUT/STDERR/traceback，按声明采集多个顶层变量；缺失输出、类型失败和序列化失败不重试。
- 新增统一变量模块 `execution/workflow_values.py`：大小写敏感 `${name.path[index]}`、request/response 字段/下标/过滤表达式、`< > <= >= == != contain` 和第 3.3 节七种目标类型隐式转换矩阵。
- HTTP 与 LLM 均通过可中断子进程发出真实阻塞 HTTP 请求；LLM 支持 OpenAI-compatible 与 Anthropic，强制 `stream=false`，按“模型默认 Body < 节点参数”构造实际供应商请求并保存原始 response。
- 新增运行 API：启动、最近 10 次、Execution 详情、Node Execution 列表、幂等全局中断和打开固定 Workflow Execution 根目录；活动 Execution 存在时拒绝删除 Workflow。
- 验证命令：`uv run pytest tests/test_workflow_execution.py tests/test_workflow_values.py tests/test_tool_execution.py -q` -> `38 passed`；`uv run pytest tests/test_workflow_api.py tests/test_workflow_execution.py -q` -> `17 passed, 1 warning`。
- 真实场景覆盖：串行 Context 传递、并行双 SCRIPT、输出缺失 Fail-Fast、30 秒脚本进程树中断、重启恢复、真实本机 HTTP GET、OpenAI POST 与 Anthropic Messages POST；warning 为既有 Starlette/httpx 弃用提示。

#### 24.7.5 阶段验证记录

- 已完成后端单节点临时测试：新增进程内 Node Test 会话、SSE 实时快照、节点级中断和删除 Workflow/Node 前的活动 Worker 收敛；START/SCRIPT/LLM/HTTP 复用完整执行的真实节点路径，END 明确拒绝测试。
- 测试请求直接携带当前未保存 Node Structural 草稿和本次临时 Context，不执行整图校验、上游、下游或 DAG 调度；同一 Workflow/Node 活动期间重复启动返回同一 test_id。
- 服务端只在 Worker 生命周期内保存有界事件队列；最终前端快照剥离 workflow_execution_id、node_execution_id、structural_snapshot 和 transitions，终态 SSE 交付后释放会话。
- 零持久化验证：单节点测试结束后 `/runs` 仍为空、`run_storage/workflow_executions/{workflow_id}` 不存在、数据库中的已保存 SCRIPT 仍保持测试前源码。
- 专项验证：`uv run pytest tests/test_workflow_api.py -q` -> `12 passed, 1 warning`。覆盖未保存 SCRIPT 草稿与临时 Context、START 空 Context、重复启动幂等、30 秒 Worker 真实中断、END 拒绝和删除 Workflow 前中断；warning 为既有 Starlette/httpx 弃用提示。
- 已完成前端单节点测试对接：START 使用当前草稿直接测试；SCRIPT/LLM/HTTP 打开仅本次有效的变量表，按 START inputs 自动预填 name/type/value，并允许新增、删除和覆盖；提交时严格构造大小写敏感 JSON Context。
- 节点卡片、节点右键菜单和编辑器运行/中断均绑定 Node Test API，不再触发 runAll 或全局中断；END 不展示运行/中断按钮。节点计时器在 RUNNING 期间累加，终态快照以“临时”标记独立展示，不写入 runHistory 或最近 10 次。
- 全新未保存 Workflow 使用前端临时 Workflow UUID 隔离 Node Test，因此测试不会为取得后端路径而隐式创建 Structural Model；显式保存后切换到真实 Workflow ID。
- 自动化与构建：`npm run build` 成功；`uv run pytest tests/test_workflow_frontend.py tests/test_workflow_api.py -q` 连续两轮均为 `16 passed, 1 warning`。warning 为既有 Starlette/httpx 弃用提示。
- 桌面单节点 E2E：在既有 Workflow 中把当前未保存 SCRIPT 草稿改为读取预填 START 变量 `name=123`，运行成功且临时日志展开显示 `inputs={name:123}`、原始 `console=123`、`outputs={abc:123}`；草稿无需保存。随后测试 30 秒 SCRIPT，卡片和编辑器运行按钮禁用、计时累加，节点中断真实终止 Worker 并进入 INTERRUPTED；关闭编辑器后临时快照从页面清除。
- 桌面完整 Workflow E2E：保存 1 秒 SCRIPT 后点击画布运行，运行按钮在终态前禁用、全局中断启用、顶栏计时累加；START 先 SUCCESS、SCRIPT RUNNING、END PENDING，最终 START/SCRIPT/END 全部 SUCCESS，END 仅在上游成功后生成，Workflow 总耗时 1.5s。
- 历史和日志 E2E：最近执行历史显示本地月日时间/SUCCESS/耗时，展开后 `context.final={name:123,abc:123}` 且包含三个真实 Node Execution；SCRIPT 持久日志只映射最终 Execution，展开显示 inputs、原始 console `123` 和 outputs。执行记录按钮返回“已打开执行记录目录”。
- 清理 E2E：删除测试 Workflow 后一级列表为 0；对应 `run_storage/workflow_executions/{workflow_id}` 不存在，四张 Structural 表计数均为 0，`PRAGMA integrity_check=ok`、`foreign_key_check=[]`。
- 视觉修复：浏览器截图发现顶栏五个操作按钮被压成两行；已调整三列最小宽度并令操作按钮禁止收缩和换行，重新构建及桌面截图确认“运行 / 历史 / 执行记录 / 中断 / 保存”均为单行且无重叠。

#### 24.7.6 验证记录

- 全量自动回归：`uv run pytest -q` -> `188 passed, 4 skipped, 1 warning in 15.47s`。4 项 skipped 为当前进程未注入真实供应商 API Key 的 live 用例；warning 为既有 Starlette/httpx 弃用提示。
- 静态与构建：`uv run python -m compileall -q execution web tests storage` 成功；`npm run build` 成功，生成 Workflow JS 948.9 KiB、CSS 63.8 KiB；`git diff --check` 无空白错误，只有 Windows 工作区既有 LF/CRLF 转换提示。
- 数据库：真实 `run_storage/agent_bench.sqlite3` 的 `PRAGMA integrity_check=ok`、`foreign_key_check=[]`；按表名扫描不存在任何 execution 或 log 数据库表，继续严格只保存 Structural Model。
- Execution 清理：完整 E2E 删除 Workflow 后 `run_storage/workflow_executions/{workflow_id}` 已定点删除，Execution 根目录为空；四张 Structural 表计数均为 0。
- 进程：关闭旧 05:22 服务进程树后，以当前代码重启 `http://127.0.0.1:8010/`；最终仅一个监听进程 PID 26492，不存在重复项目端口。
- Git 边界：未提交、未推送；工作区包含本轮开始前已有的不兼容 Workflow 重构删除和用户文档改动，全部按原状态保留且未回滚。

### 24.8 可观测验收标准（How to Measure）

- 保存后数据库只出现四类 Structural 表，不出现任何 Workflow/Node Execution、运行索引或日志表。
- 非法图、缺失/重复 START 或 END、纯系统节点图、变量冲突和无效 Node 配置均显式拒绝保存和运行，不产生 Execution JSON。
- 合法 Workflow 保存后重启服务仍可从三张 Workflow 表和 Node 表完整恢复相同节点、配置、坐标和 Edge。
- 手动执行只读取启动快照；运行期间修改当前结构不改变已开始执行，历史 JSON 可在数据库结构被修改后独立离线读取。
- START/END 均产生真实 Node Execution；START values 原子进入 Context，END SUCCESS 是 Workflow SUCCESS 的唯一标志。
- 任一节点最终 FAILED 后不再启动新节点，其他 RUNNING Worker 被真实终止，Workflow/Node JSON、Context 和原始日志不存在部分成功或伪造状态。
- 同一 Workflow 的多个 Execution 可以并发且目录、Context、状态和日志完全隔离；Workflow 管理页面不会因连续点击产生重复手动执行。
- 一级 Workflow 列表只显示名称、说明、更新时间；执行记录入口能够打开真实 JSON 目录，日志内容全部来自对应 Execution JSON。

### 24.9 可用变量映射最新 Node Execution（completed，2026-07-27）

- Why：工作流开发者执行完整 Workflow 后，需要立即从节点右上角“可用变量”确认本节点实际写入 Context 的结果；此前面板只读取 Structural Model 的输出声明，并把业务节点值固定为 `null / 尚无值`，与真实 Execution 和日志相矛盾。
- Who / Where：Workflow Studio 中执行完整 Workflow 后，打开 START/SCRIPT/LLM/HTTP 节点编辑器并点击右上角“变量”。
- What / Priority：P0 展示正确性缺陷。变量面板不再从卡片 `runHistory` 状态副本猜测值；每次打开时以 `cache: no-store` 读取最新 Workflow Execution 和所属 Node Execution JSON，按 `node_id + outputs.name` 映射实际结果。找不到输出键时才显示“尚无值”。
- 值语义：是否可用使用 `hasOwnProperty` 判断，因此空字符串、`0`、`false` 和 `null` 都属于真实可用值并允许复制，不能被 truthy 判断误判为空。
- 缓存修复：`index.html` 为 Workflow bundle 增加 `?v=20260727-variables`，避免浏览器继续复用修复前的同名静态 JS。
- 真实数据核对：最近三次 SCRIPT Node Execution 均保存 `structural_snapshot.outputs=[{name:msg,type:string,source:msg}]`、`outputs={msg:"介绍一下自己"}` 和原始 console；数据库和 Execution Model 无需修改。
- 浏览器 E2E：刷新后打开“规则校验”变量面板，`msg` 立即显示“介绍一下自己”，复制按钮启用；点击后页面提示“已复制变量 msg”。
- 自动验证：`npm run build` 成功；专项回归 `26 passed, 1 warning`；最终 `uv run pytest -q` -> `190 passed, 4 skipped, 1 warning in 16.50s`；Python compileall 和 `git diff --check` 通过。4 项 skipped 仍为未注入真实供应商密钥的 live 测试，warning 为既有 Starlette/httpx 弃用提示。

### 24.10 全节点变量作用域与草稿实时同步（completed，2026-07-27）

- Why：工作流开发者新增输出声明或完成单节点临时测试后，必须立即确认当前节点和全部上游节点可向后传递的变量；旧实现只在按钮首次点击时生成静态列表，并按画布数组位置而非 DAG 依赖判断“之前节点”。
- Who / Where：任意 START/SCRIPT/LLM/HTTP/END 节点编辑器右上角“变量”面板，覆盖未保存草稿、临时节点测试和完整 Workflow Execution 三种状态。
- 顶层规则一：只要当前草稿定义了输出变量，面板必须显示变量名；尚无本次或持久化结果时显示“尚无值”，不能隐藏整条声明。临时测试 `temporaryRun.outputs` 优先于最新持久化 Node Execution `outputs`；关闭编辑器后临时快照按既有契约清除并回退到持久化值。
- 顶层规则二：任意节点变量面板固定展示该节点全部 DAG 祖先和当前节点的变量。前端通过 Edge 反向遍历确定祖先集合，再对子图执行拓扑排序；不再使用 `nodes.slice(0, index)` 猜测作用域，也不展示不汇入当前节点的旁支变量。
- 实时刷新：Inspector 使用稳定 ref 保存最新变量加载函数，只在面板开关、当前节点、输出声明或临时输出真正变化时刷新；新增、删除、重命名输出或临时测试终态无需关闭编辑器即可更新，避免父组件无关重渲染反复取消请求。
- 值来源：完整运行仍直接读取最新 Workflow/Node Execution JSON；临时运行读取前端临时快照；声明层来自当前未保存 Node Structural 草稿。空字符串、`0`、`false`、`null` 继续按 key 存在性判断为可用值。
- Bundle 一致性：构建脚本按生成 JS 内容计算 12 位 SHA-256，并自动回写 `index.html` 的 `workflow-canvas.js?v={hash}`；后续每次 `npm run build` 都会自然失效浏览器旧缓存，不再人工维护固定版本号。
- Windows 加固：专项回归暴露轮询读取 Execution JSON 与 `os.replace` 短暂冲突的 `PermissionError`；Store 对该瞬时窗口增加最多 5 次、每次 10ms 的限定重试，并新增明确测试，不吞掉持续权限错误。
- 浏览器 E2E：完整 Workflow 运行后 `msg=介绍一下自己`；新增未执行的 `message` 立即显示为“尚无值”；SCRIPT 临时测试后 `message` 立即显示真实值；打开下游 END 可同时看到上游 SCRIPT 的 `msg/message`。验收 Workflow 已删除，测试前真实数据库已是 0 条 Workflow，清理后仍为 0。
- 验证：`npm run build` 成功；专项 `29 passed, 1 warning`，Windows 原子读取场景单独复跑 `2 passed`；全量 `uv run pytest -q` -> `192 passed, 4 skipped, 1 warning in 15.76s`；compileall、`git diff --check`、`PRAGMA integrity_check=ok`、`foreign_key_check=[]` 均通过。

### 24.11 节点秒级执行配置与首次延迟（completed，2026-07-27）

#### 业务分析与已确认边界

- Why：Workflow 开发者需要用符合真实使用习惯的秒单位配置节点超时、失败重试等待和首次延迟，避免前端手工换算毫秒，也必须明确区分“首次延迟”与“重试间隔”。
- Who / Where：用户在 Workflow Studio 的 SCRIPT、LLM、HTTP 节点设置页配置执行策略；START/END 是即时系统标志节点，不加入执行等待配置。
- What / Priority：P0 契约一致性改造。旧 `timeout_ms / delay_ms` 不兼容删除，Structural Model 改为必填 `timeout_seconds / max_attempts / retry_interval_seconds / delay_seconds`；三个秒字段支持小数，后端统一换算为整数毫秒。
- 执行语义：`delay_seconds` 只在首次实际尝试前等待一次，等待期间 Node Execution 保持 PENDING；首次尝试开始后进入 RUNNING。后续重试不再叠加首次延迟，只等待 `retry_interval_seconds`；HTTP 唯一合法 Retry-After 可覆盖该次重试等待。
- 计时语义：`timeout_seconds` 每次实际尝试独立计时；Node Execution `duration_ms` 包含首次延迟、全部实际尝试和重试等待。Execution Model 的事实耗时继续用整数毫秒，不把配置字段单位扩散到执行事实。

#### 子任务与逐步验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 24.11.1 | 更新权威契约 | 已确认 1A/2A/3A；WORKFLOW_SPEC 秒字段和等待语义 | 扫描旧 `timeout_ms / delay_ms` 配置语义无残留 | 无 | completed |
| 24.11.2 | 后端 Structural Model、存储和执行器改造 | 秒字段；统一毫秒换算、PENDING 首次延迟、独立重试间隔 | 模型/API/执行专项测试，覆盖小数秒、旧字段拒绝、延迟/重试/超时/中断 | 24.11.1 | completed |
| 24.11.3 | 三类节点前端对接 | SCRIPT/LLM/HTTP 设置表单 | 构建、前端专项测试、保存与回显 E2E | 24.11.2 | completed |
| 24.11.4 | 完整回归 | 后端、前端、SQLite、桌面业务流 | pytest、compileall、npm build、diff check、SQLite integrity、浏览器 E2E | 24.11.2-24.11.3 | completed |

#### 验收标准

- SCRIPT、LLM、HTTP 均以秒显示、保存和回显单次超时、重试间隔、首次延迟，支持例如 `0.25` 秒；START/END 不出现这些控件。
- API/数据库只接受新字段，旧 `_ms` 字段得到明确校验错误，不做兼容迁移或静默换算。
- 配置 `delay_seconds=0.2` 时首次 Worker/请求在约 200ms 后只启动一次；发生重试时只额外等待 `retry_interval_seconds`，不重复等待首次延迟。
- 首次延迟可被全局中断或单节点临时测试中断，未开始尝试时 `attempt_count=0`；实际开始后状态和计数符合 Execution Model 契约。
- 小数秒超时由后端统一转换为整数毫秒执行，超时、中断和最终原始日志保持真实；完整 Workflow 与单节点临时测试使用相同语义。

#### 24.11.2 验证记录

- `RetryExecution` 已改为严格的 `timeout_seconds / max_attempts / retry_interval_seconds / delay_seconds`；三个秒字段拒绝字符串、NaN/Infinity 和越界值，允许整数或小数 JSON number。
- 新增唯一 `seconds_to_milliseconds()` 换算入口。SCRIPT、LLM、HTTP 的 Worker 超时、首次延迟和重试间隔都先换算为整数毫秒，再进入现有执行接口。
- 完整 Workflow 的业务节点在首次延迟期间写入真实 PENDING Node Execution，Workflow 节点条目同步为 PENDING；延迟完成后才进入 RUNNING。用户中断或 Fail-Fast 能在无 Worker 的延迟期内收敛，且 `attempt_count=0`。
- 完整 Workflow 与单节点临时测试复用 `_begin_business_node`，不存在两套延迟语义。Node Execution `duration_ms` 从 PENDING 生命周期开始累计，因此包含首次延迟。
- 专项验证：`uv run pytest tests/test_node_structural_models.py tests/test_workflow_execution.py tests/test_workflow_api.py tests/test_workflow_structural_models.py -q` -> `53 passed, 1 warning in 7.17s`。warning 为既有 Starlette/httpx 弃用提示。
- 新增回归覆盖：小数秒 round-trip、旧 `_ms` 字段拒绝、非法秒值、真实 PENDING 延迟、延迟期全局中断、首次延迟/重试间隔各调用一次、超时秒值统一换算。

#### 24.11.3 验证记录

- SCRIPT、LLM、HTTP 设置页统一使用“单次超时（秒）/最大重试次数/重试间隔（秒）/延迟执行（秒）”；START/END 仍为即时系统节点，不显示运行配置。
- 前端保存和回读统一映射 `timeout_seconds / max_attempts / retry_interval_seconds / delay_seconds`，支持小数；构建产物及 `index.html` 的内容哈希已同步更新。
- 前端专项验证：`uv run pytest tests/test_workflow_frontend.py tests/test_execution_frontend.py tests/test_workflow_api.py -q` -> `38 passed, 1 warning`；`npm run build` 成功。
- 浏览器 E2E 在唯一临时 Workflow `秒级配置验收-20260727` 中保存 SCRIPT 配置 `0.5 / 0 / 0.2 / 0.25`，API Structural Model 与退出后重新打开的 Inspector 均精确回读四个值。
- 真实 Workflow 执行观测到 SCRIPT 在启动后及 100ms 时均为 `PENDING / attempt_count=0 / started_at=null`，随后三个节点均为 SUCCESS；API 运行中 SCRIPT `duration_ms=462`，浏览器运行中显示 `485ms`，均包含 250ms 首次延迟。
- 验收 Workflow 删除前执行目录存在，删除后 `run_storage/workflow_executions/{workflow_id}` 定点消失；原有用户 Workflow `未命名工作流` 保持不变。

#### 24.11.4 验证记录

- 全量回归：`uv run pytest -q` -> `202 passed, 4 skipped, 1 warning in 16.67s`；4 项跳过为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 静态与构建：`uv run python -m compileall -q execution web tests storage` 成功；`npm run build` 成功；`git diff --check` 成功。
- SQLite：`PRAGMA integrity_check` 返回 `ok`；`PRAGMA foreign_key_check` 返回空；数据库表仅包含 Structural Model 与既有模型供应商/Target 表，不存在 Execution 或日志表。
- 运行环境：验收结束后只保留 `127.0.0.1:8010` 一个项目监听端口，测试创建的 Workflow 和 Execution JSON 均已清理，用户原有 Workflow 未修改。

### 24.12 业务节点十分钟系统默认超时（completed，2026-07-27）

#### 业务分析与已确认边界

- Why：默认执行策略必须由后端契约统一提供，确保画布、直接 API 和后续批量调度创建的节点行为一致；十分钟默认超时兼顾真实 LLM、HTTP 和 Python 任务耗时，同时避免无限执行。
- Who / Where：Workflow 开发者在画布新建 SCRIPT、LLM、HTTP 节点，或其他模块通过新版 Workflow API 创建节点；START/END 仍为即时系统标志节点。
- What / Priority：P0 契约一致性。平台默认 `timeout_seconds=600 / max_attempts=0 / retry_interval_seconds=0 / delay_seconds=0`；省略整个 `execution`、提交空对象或只提交部分字段时由后端补齐，显式字段覆盖同名默认值。
- How to Measure：三类业务节点在模型/API 中省略与部分覆盖均得到预期完整值；前端新节点显示 600 秒；保存、回读和真实执行使用同一值；START/END 无运行配置且既有日志与状态语义不变。

#### 子任务与逐步验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 24.12.1 | 更新权威契约 | 用户确认十分钟默认值与显式字段覆盖 | 扫描“无默认值/必须显式填写”和 120 秒默认语义无残留 | 无 | completed |
| 24.12.2 | 后端系统默认策略 | Pydantic 默认值、整体省略与部分覆盖 | 模型/API 专项测试 | 24.12.1 | completed |
| 24.12.3 | 前端统一 | 新节点和异常回读兜底改为 600 秒 | 前端专项测试、生产构建、浏览器 E2E | 24.12.2 | completed |
| 24.12.4 | 完整回归 | 全量后端、前端、SQLite 与运行环境 | pytest、compileall、build、diff check、数据库和端口检查 | 24.12.2-24.12.3 | completed |

#### 24.12.1 验证记录

- `WORKFLOW_SPEC.md` 顶层边界、公共字段表、三类节点字段表、SCRIPT/LLM execution 章节和重试顶层规则均已统一为平台默认 `600 / 0 / 0 / 0`。
- 契约明确支持省略整个 `execution`、提交空对象及部分字段覆盖；显式字段只覆盖同名默认值，未提交字段继续使用平台默认值。
- 文档扫描确认“必须显式填写且无契约默认值”和 120 秒默认语义无残留；HTTP 章节中的 30 秒仅作为显式覆盖示例保留。

#### 24.12.2 验证记录

- `RetryExecution` 在后端权威模型中定义 `timeout_seconds=600 / max_attempts=0 / retry_interval_seconds=0 / delay_seconds=0`，继续保留严格 JSON number/integer、有限数和范围校验。
- SCRIPT、LLM、HTTP 的 `execution` 分别使用 `RetryExecution` 或 `HttpExecution` 默认工厂；省略整个对象、提交 `{}` 和部分字段覆盖均得到完整策略，HTTP 专属重试字段继续使用既有默认值。
- API 创建 Workflow 时会把后端补齐后的完整执行策略写入 Structural Model 并原样返回，不依赖画布补值。
- 专项验证：`uv run pytest tests/test_node_structural_models.py tests/test_workflow_api.py -q` -> `39 passed, 1 warning in 2.31s`；warning 为既有 Starlette/httpx 弃用提示。

#### 24.12.3 验证记录

- Workflow Canvas 新节点初始化、运行配置输入兜底和 Structural Model 回读兜底均已从 120 秒统一为 600 秒；重试次数、重试间隔和延迟执行继续默认为 0。
- `npm run build` 成功并更新 Workflow bundle 与内容哈希；专项 `uv run pytest tests/test_workflow_frontend.py tests/test_workflow_api.py tests/test_node_structural_models.py -q` -> `47 passed, 1 warning in 2.10s`。
- 浏览器 E2E 在未保存临时草稿中逐一新增并打开 SCRIPT、LLM、HTTP，三者均显示 `600 / 0 / 0 / 0`；START/END 不显示运行配置。
- 临时草稿退出时未保存，数据库 Workflow 列表保持用户原有两条，未创建或删除用户数据。

#### 24.12.4 验证记录

- 第二次全量回归：`uv run pytest -q` -> `211 passed, 4 skipped, 1 warning in 16.57s`；4 项跳过为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- 首次全量回归中 `test_missing_script_output_fails_fast_and_never_creates_end_execution` 曾一次得到瞬时 `PERSISTENCE_FAILED`；该用例立即单独复跑通过、第二次全量通过，并连续复跑 10 次全部通过。未发现本次默认策略变更引入的稳定回归，保留 Windows 文件持久化瞬时竞态作为已知残余风险。
- `uv run python -m compileall -q execution web tests storage`、`npm run build` 和 `git diff --check` 均成功。
- SQLite `integrity_check=ok`、`foreign_key_check=[]`，不存在 Execution 或日志数据库表；Execution Model 继续只保存在本地 JSON。
- 运行环境只监听 `127.0.0.1:8010`；浏览器临时草稿未保存，用户现有两条 Workflow 均保留。

### 24.13 允许保存不完整业务节点并在到达节点时友好失败（completed，2026-07-27）

#### 业务分析与已确认边界

- Why：Workflow 管理用于开发和测试迭代，用户必须能够先保存完整合法的图结构，再逐步配置和测试业务节点；保存不能等同于可执行性校验。
- Who / Where：开发者在 Workflow Studio 保存包含未配置 SCRIPT、LLM 或 HTTP 的合法 DAG，并通过完整运行或单节点临时测试发现当前节点配置问题。
- What / Priority：P0 可用性。保存继续严格校验 START/END、循环、游离节点、连线、类型及非空格式；不引入 DRAFT/READY。调度到缺配置节点时创建 PENDING -> FAILED 的真实 Node Execution，attempt_count=0、不重试并 Fail-Fast；临时测试复用同一逻辑但只保留前端快照。
- How to Measure：三类空白节点均可保存和回读；非法非空 URL 等仍拒绝；完整运行只在到达对应节点时失败且后代 NOT_STARTED；三类错误均提供稳定 code、中文 message、missing_fields 和 suggestion；临时测试一致且不写 JSON。

#### 子任务与逐步验证

| 子任务 | 目标 | 输入 / 输出 | 验证方法 | 依赖 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 24.13.1 | 更新权威契约 | 1A/2A/3A 与错误码 | 矛盾语义和错误码扫描 | 无 | completed |
| 24.13.2 | Structural Model 与保存 | 空白 SCRIPT/LLM/HTTP 可持久化，图结构仍严格 | 模型、Repository、API 专项测试 | 24.13.1 | completed |
| 24.13.3 | Execution Model 与临时测试 | PENDING -> FAILED、attempt_count=0、友好错误、Fail-Fast | 执行器与 API SSE 专项测试 | 24.13.2 | completed |
| 24.13.4 | 前端与完整回归 | 保存成功、日志/Toast 友好、浏览器真实流程 | 构建、浏览器 E2E、pytest、SQLite、端口检查 | 24.13.3 | completed |

#### 24.13.1 验证记录

- 权威契约明确不引入 DRAFT/READY；保存和启动只严格校验合法 DAG、字段类型及非空配置格式，业务节点缺少运行配置不阻断持久化。
- 调度到当前节点时才校验运行必需配置，缺失时创建 PENDING -> FAILED、attempt_count=0、started_at=null 的 Node Execution，不启动真实执行且不重试，随后按 Fail-Fast 停止后代。
- 新增 `SCRIPT_CONFIGURATION_INCOMPLETE / LLM_CONFIGURATION_INCOMPLETE / HTTP_CONFIGURATION_INCOMPLETE`，并统一 `missing_fields / suggestion` 友好详情；非空失效模型继续使用 `LLM_MODEL_NOT_FOUND`。
- 文档扫描确认“保存与运行前完整配置校验”“模型引用保存时必须有效”等旧语义无残留。

#### 24.13.2 验证记录

- SCRIPT.script、LLM model/prompt、HTTP request/network/response 均提供可持久化空白默认结构；HTTP 空 URL 和 CUSTOM 空 Proxy URL 允许保存，但填写后的非法非空 URL 仍按 Structural Model 格式校验拒绝。
- Workflow Repository 保存与更新不再访问模型仓库校验弱引用；空引用和非空失效引用都能保存，等待调度到 LLM 节点时判定。
- API 在合法 START -> 业务节点 -> END 图中分别保存并回读完全空白 SCRIPT、LLM、HTTP；已有 START/END、循环、游离节点和连线校验保持不变。
- 专项验证：`uv run pytest tests/test_node_structural_models.py tests/test_workflow_structural_models.py tests/test_workflow_api.py -q` -> `58 passed, 1 warning in 2.55s`；warning 为既有 Starlette/httpx 弃用提示。

#### 24.13.3 验证记录

- 三类业务执行入口均在首次 delay 和真实尝试前检查当前节点：空 SCRIPT、空 LLM 模型/用户提示词、空 HTTP URL 或 CUSTOM Proxy URL 直接写入 PENDING 后终结为 FAILED，不调用 Worker。
- 配置失败保持 `started_at=null / duration_ms=null / attempt_count=0 / attempts=[]`，transitions 精确为 PENDING -> FAILED，错误包含稳定 code、节点名称、missing_fields 和 suggestion；不进入自动重试。
- 非空但失效的 LLM 引用延后到该节点到达时使用 `LLM_MODEL_NOT_FOUND` 友好失败；后代 END 不创建 Node Execution，Workflow 按既有 Fail-Fast 进入 FAILED。
- 单节点临时测试复用相同执行器，最终前端快照字段与完整 Node Execution 一致，但不创建 Workflow/Node Execution JSON。
- 专项验证：`uv run pytest tests/test_workflow_execution.py tests/test_workflow_api.py -q` -> `38 passed, 1 warning in 7.55s`；首次运行发现测试夹具自动提供默认脚本，修正为空字符串后全套通过。

#### 24.13.4 验证记录

- 公共 API 客户端统一先读取 text 再尝试 JSON，JSON detail 数组会合并为可读 message，纯文本 500 直接展示原文，不再产生 `Unexpected token` 二次解析错误。
- 单节点临时测试终态 FAILED 时立即 Toast Node Execution 的友好 message + suggestion；完整 Workflow FAILED 时优先读取最终 FAILED/TIMEOUT Node Execution，而不是只展示 Workflow 的笼统 NODE_FAILED。
- 浏览器 E2E 创建独立 `START -> 空白 LLM -> END`：空白 LLM 成功保存并回读；点击运行后 START SUCCESS、LLM FAILED、END 保持未执行，Toast 显示“节点‘待配置模型’未完成模型配置”及模型选择建议。
- 浏览器日志概览与展开内容均来自真实 LLM Node Execution：`PENDING -> FAILED / attempt_count=0 / started_at=null / duration_ms=null / attempts=[]`，错误包含三个 missing_fields 和 suggestion。验收 Workflow 与 Execution 目录随后定点删除，用户 Workflow 未删除。
- 专项前端及 Workflow 回归 `87 passed, 1 warning`；全量 `uv run pytest -q` -> `228 passed, 4 skipped, 1 warning in 17.62s`。4 项跳过为未注入真实供应商环境变量的 live 测试，warning 为既有 Starlette/httpx 弃用提示。
- `uv run python -m compileall -q execution web tests storage`、`npm run build`、`git diff --check` 和契约矛盾扫描均通过；SQLite integrity=ok、foreign_key_check=[]，数据库无 Execution/日志表。
- 运行服务已重启到当前代码，只保留 `127.0.0.1:8010` 一个监听端口；最终 Workflow 列表只保留用户当前 `未命名工作流`。
