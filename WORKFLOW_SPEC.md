<a id="workflow-spec"></a>

# Workflow Engine Specification

本文档是 Agent Bench v2 工作流引擎的唯一事实来源，面向 Workflow 设计、执行器实现、运行记录、前端配置和 Codex 检索。任何 Workflow 结构、节点字段、状态机、Context 引用、输入输出协议、重试、取消、错误或数据完整性变更，都必须先更新本文档。

核心原则：**错误显式化、拒绝静默污染**。任何配置错误、引用缺失、解析失败、输出不完整或协议异常都必须产生明确错误，不得通过未在本规范定义的转换、默认回退、部分提交或丢弃异常数据伪装成功。

顶层 Web 并发约束：**FastAPI 路由必须按照实际 I/O 模型声明。** 直接调用同步 sqlite3 Repository、openpyxl、YAML/JSON 或普通文件系统 API 的处理器必须使用普通 `def`，由 FastAPI 在线程池执行；只有调用真正可等待异步客户端的处理器才能使用 `async def`，且必须通过 `await` 或异步上下文协议执行 I/O。Excel multipart 上传必须通过 `UploadFile.file` 在同步处理器内完成读取、校验、临时写入、Workbook 解析、目标替换和配置保存，不得在事件循环中混入后半段同步处理。模型供应商连接测试使用 httpx/模型网关异步客户端，保留异步处理器。当前同步 SQLite 路由不因此迁移数据库框架。

顶层中断约束：**用户不得单独中断任何完整 Workflow Node Execution 或单节点临时测试，只能通过画布全局中断停止完整 Workflow。** 单节点临时测试运行期间禁用重复运行，不提供用户中断入口；关闭编辑器、删除节点或 Workflow、离开 Studio 时，系统必须在内部取消活动 Worker 并完成资源清理。Workflow Fail-Fast、节点超时和进程异常属于调度器内部终态处理，不属于用户单节点中断。

顶层 Context 约束：**Context 变量名严格区分大小写，任何阶段都不得执行小写归一化或其他大小写改写。** START inputs.name、所有节点 outputs.name、Context 引用和 SCRIPT 输入读取均按用户保存的原始名称精确匹配；`result`、`Result` 和 `RESULT` 是三个不同变量。HTTP Header 等外部协议自身的大小写规则不改变本约束。

顶层日志约束：**日志界面打印的全部内容必须从对应 Workflow/Node Execution Model 的已保存字段中读取，且只展示本次 Execution 的最终事实；日志不是独立的数据模型或第二份事实存储。** 完整 Workflow Execution 持久化一个 `workflow.json` 和所属 Node Execution JSON；前端只能对其中最终 Context、节点结果、request、response、error、状态、耗时及最终一次尝试对应的 console、traceback 等事实进行只读格式化展示，不得生成模型中不存在的执行内容，也不得通过日志展示反向修改 Execution Model。前序重试仍保存在 Node Execution Model 中用于离线追溯，但一律不加入日志界面。单节点临时测试仍使用同结构的前端快照，不产生持久化 Execution Model。

用户可见日志列表的通用规则：

- 每个可执行节点只列出最近 10 个已经进入终态的持久化 Node Execution，按 finished_at 从新到旧排序；PENDING/RUNNING 只显示在当前运行状态区，不提前进入历史日志。
- 每行固定显示时间、状态和耗时；SCRIPT、LLM、HTTP 额外显示最终结果概览。时间取 started_at 并显示为 `MM-DD HH:mm:ss`，满足日期精确到月日；从未开始时使用 finished_at。状态直接使用 Execution Model.status；耗时直接使用 duration_ms，null 显示 `--`。START 的 outputs 与输入提交结果相同，列表行不重复展示 outputs 概览。
- 最终结果概览只能从各节点日志章节指定的最终事实字段生成。单行截断、折叠和 JSON 美化只是视觉格式，不得保存为新字段；展开后必须显示未被概览截断的实际值。
- 点击某行后在下方展开该次执行的节点专属字段。前序重试 attempts 不展示；attempt_count 只用于告诉用户本次共执行多少次。
- 复制按钮复制当前展开区域的完整实际值。JSON 值复制为标准 JSON，string 复制解析后的真实文本；不得复制外层 JSON 序列化产生的反斜杠，也不得把视觉省略号写入复制结果。
- 单节点临时测试按相同字段顺序显示当前前端快照，但不加入最近 10 次列表，关闭编辑器或刷新页面后消失。

顶层 JSON 展示约束：**Execution Model JSON 文件中的转义只属于外层 JSON 序列化，日志界面、复制操作和下游节点必须读取解析后的实际值。** 例如实际 string 值 `{"id":3}` 在 JSON 文件中必须编码为 `"{\"id\":3}"`，但界面显示、复制结果和下游读取值均为 `{"id":3}`，不得显示或注入仅用于外层编码的反斜杠。实际 string 本身包含的反斜杠、换行或引号仍必须按其真实值保留，不得通过文本替换盲目删除。

顶层输出类型约束：**SCRIPT、LLM 和 HTTP 的 outputs.type 是目标类型；提取值或 source 实际值与目标类型不一致时，平台默认按照统一隐式转换矩阵尝试转换，不得直接忽略声明类型或按实际类型写入 Context。** 数字字符串必须使用精确十进制解析，不得先经过 binary float；number 转 integer 仅在数学值为整数且转换前后精确相等时允许。所有数值转换必须通过往返等值校验，不得产生精度丢失、NaN、Infinity 或其他非有限数。任一已定义转换无法完成、发生精度丢失或产生非有限数时，SCRIPT 使用 `SCRIPT_OUTPUT_TYPE_MISMATCH`，LLM 使用 `LLM_OUTPUT_TYPE_MISMATCH`，HTTP 使用 `HTTP_OUTPUT_TYPE_MISMATCH`，outputs 整体不提交且不执行自动重试；SCRIPT source 本身无法严格 JSON 序列化时仍使用 `SCRIPT_OUTPUT_SERIALIZATION_ERROR`。具体允许的转换路径由节点输出协议共同定义，任何未定义转换仍禁止。

顶层多值输入输出约束：**START 和所有可执行业务节点都必须允许在自身业务边界传入 0..N 个值并传出 0..N 个值，不得把节点协议固定为单输入或单输出。** 各节点使用适合自身场景的输入方式：START 使用 inputs，SCRIPT 使用只读 context Mapping，LLM/HTTP 使用 `${变量名}` Context 引用；SCRIPT、LLM、HTTP 不增加重复的统一 inputs 数组。输出声明必须支持多个 name/type/source 或节点等价绑定，多个输出分别提取和转换，但必须作为一组原子提交，任一项失败时整组 outputs 为 `{}`。END 当前是唯一例外：它不承担业务值传入、传出或聚合，只生成空 SUCCESS Node Execution 作为 Workflow 成功标志。

顶层模型与存储约束：**数据库严格且只允许保存 Structural Model；Workflow/Node Execution Model 严格且只允许保存到本机 JSON 文件。** 数据库不得创建 Execution 表、执行索引、状态摘要或日志记录，文件系统不得另存 Structural Model。当前文档已经确定新版 Workflow 契约，但 Workflow 表、Repository、API 和执行器尚未实施；旧 Workflow 实现已永久删除且不得恢复。

顶层图约束：**每个可保存和执行的 Workflow 必须恰好包含一个 START 和一个 END。** START 是唯一根节点并能到达所有其他节点，END 是唯一叶节点且所有其他节点都能到达 END；整图必须是单一弱连通 DAG，不允许空 Workflow、只有 START/END、游离节点、自环、重复 Edge 或有向环。

顶层终态约束：**任一 Node Execution 最终 FAILED，Workflow 立即执行全局 Fail-Fast；Workflow SUCCESS 的唯一判定标志是 END Node Execution SUCCESS。** 节点内部可重试错误只有在重试耗尽并最终 FAILED 后才触发 Fail-Fast。Fail-Fast 立即停止启动新节点并终止其他 RUNNING 节点；被终止节点使用 INTERRUPTED，尚未启动节点不创建 Node Execution。

## 目录

1. [文档简要说明](#chapter-1)
2. [Structural Model &amp; Execution Model](#chapter-2) ([Node 数据字典](#chapter-2-3) / [Workflow Structural Model](#chapter-2-4) / [Workflow Execution Model](#chapter-2-5) / [Batch Execution Model](#chapter-2-6))
3. [Context](#chapter-3)
4. [Node Status](#chapter-4)
5. [START](#chapter-5) ([Structural Model](#chapter-5-1) / [Execution Model](#chapter-5-2) / [Input &amp; Output Protocol](#chapter-5-3) / [用户可见日志](#chapter-5-4))
6. [SCRIPT](#chapter-6) ([Structural Model](#chapter-6-1) / [Execution Model](#chapter-6-2) / [Input &amp; Output Protocol](#chapter-6-3) / [用户可见日志](#chapter-6-4))
7. [LLM](#chapter-7) ([Structural Model](#chapter-7-1) / [Execution Model](#chapter-7-2) / [Input &amp; Output Protocol](#chapter-7-3) / [用户可见日志](#chapter-7-4))
8. [HTTP](#chapter-8) ([Structural Model](#chapter-8-1) / [Execution Model](#chapter-8-2) / [Input &amp; Output Protocol](#chapter-8-3) / [用户可见日志](#chapter-8-4))
9. [END](#chapter-9) ([Structural Model](#chapter-9-1) / [Execution Model](#chapter-9-2) / [Input &amp; Output Protocol](#chapter-9-3) / [用户可见日志](#chapter-9-4))
10. [Workflow 结构与调度约束](#chapter-10) ([图结构](#chapter-10-1) / [调度](#chapter-10-2) / [错误阶段](#chapter-10-4))
11. [执行、重试、超时与取消约束](#chapter-11) ([执行状态](#chapter-11-1) / [重试与超时](#chapter-11-3) / [取消](#chapter-11-4))
12. [错误与数据完整性约束](#chapter-12) ([显式错误](#chapter-12-2) / [原子提交](#chapter-12-3) / [日志](#chapter-12-4))

<a id="chapter-1"></a>

## 1. 文档简要说明

<a id="chapter-1-1"></a>

### 1.1 业务目标

本规范旨在确立工作流在串行并发、拓扑分支、重试补偿、主动中断及异常容错等全场景下的状态机行为准则。

在完成以下8个目标前需持续更新：

1.明确 Workflow 结构模型的定义、结构、存储规则
2.明确 Workflow 执行模型的定义、结构、存储规则
3.明确 Workflow 日志的打印内容、打印格式
4.明确不同类型 Node 的功能、输入、输出
5.明确不同类型 Node 结构模型的定义、结构、存储规则
6.明确不同类型 Node 执行模型的定义、结构、存储规则
7.明确不同类型 Node 日志的打印内容、打印格式
8.明确不同类型 Node 中变量的定义方式，传入与传出规则

<a id="chapter-1-2"></a>

### 1.2 适用范围

当前规范覆盖 START、SCRIPT、LLM、HTTP 和 END，以及 Workflow Run、NodeRun、Context、DAG 调度、重试、超时、取消、日志和错误边界。AGENT 节点与 START 的外部任务入口能力暂未定义，后续业务确认后再加入。

<a id="chapter-1-3"></a>

### 1.3 编写与检索约定

- 每个一级章节使用固定 HTML 锚点 `chapter-N`，节点子章节使用 `chapter-N-M`；章节改名时不得修改既有锚点。
- 每个参数列表必须完整列出当前层级保存的全部字段，不得只列主要字段。
- string、int、boolean 等简单字段直接在当前层级参数表说明。
- object、array 或具有独立校验规则的复杂字段，在当前层级参数表中保留字段入口，并在后续单独列出全部子字段。
- Structural Model 和 Execution Model 都采用“完整示例在前，参数列表和规则在后”的顺序。
- Structural Model 和 Execution Model 参数表统一使用“字段、类型、取值、示例、含义”五列。
- 规范未明确允许的类型转换、字段回退、默认值、覆盖、跳过或部分提交一律禁止。

<a id="chapter-2"></a>

## 2. Structural Model & Execution Model

<a id="chapter-2-1"></a>

### 2.1 概要与定义

Structural Model（结构模型）定义 Workflow 和 Node 是什么、如何连接以及应当如何执行。它是系统当前有效的权威元数据和静态拓扑蓝图，以强结构化关系模型持久化在关系型数据库中。

Execution Model（执行模型）记录 Workflow 或 Node 被触发后实际发生的客观事实。每次触发产生一个相互独立的生命周期投影；执行记录以 JSON 文件持久化在本机文件系统中，与结构模型采用读写分离和冷热隔离设计，用于在线状态更新、历史追溯和离线还原。

顶层存储与日志映射契约：

1. Structural Model 的唯一持久化位置是关系型数据库。Workflow/Node 的创建、编辑和删除直接映射为数据库 CRUD 事务，不另存 Structural Model JSON 文件。
2. Execution Model 的唯一权威正文是本机文件系统中的 JSON 文件。关系型数据库不得复制保存 Execution Model 的 inputs、request、response、attempts、outputs、error 或其他执行正文。
3. 用户可见日志全部由前端从对应 Execution Model JSON 的已保存字段读取、映射和组装。日志列表、概览、展开详情和复制内容都不是新的持久化模型，不得另存日志文件、日志数据库记录或反向写入 Execution Model。
4. Workflow Repository、ModelProviderRepository、WorkflowExecutionManager 和 NodeTestManager 是单个 FastAPI 应用生命周期内的共享资源。应用必须通过 lifespan 在接收请求前一次性创建并初始化资源，通过 `app.state` 和 FastAPI Dependency 注入路由；路由模块不得保存这些对象或路径键的可变全局单例。应用关闭时必须先拒绝新任务，再中断并等待全部活动 Workflow/节点测试线程收敛，最后释放应用状态。
5. 当前活动调度状态只存在于单个进程内，因此服务只支持单 Uvicorn worker。本约束不能通过 lifespan 消除；启用多 worker 前必须另行实现跨进程执行所有权、取消路由和锁，不得把每个 worker 的独立 Manager 误认为共享调度器。
6. Execution 实现按职责单向组合：`workflow_execution_store.py` 负责 Execution JSON，`workflow_execution_control.py` 负责取消信号，`workflow_node_runner_base.py` 负责公共 Node 生命周期，SCRIPT/LLM/HTTP Runner 分别拥有自身协议，`workflow_node_executor.py` 只负责类型注册和 Context commit，`workflow_node_tests.py` 负责临时测试，`workflow_execution.py` 只负责 DAG 调度。子进程 Runtime/Worker 属于 `execution`，Execution 域不得导入 Web；Web 兼容导出不得保存第二份运行状态。
7. 所有 SQLite Repository 必须从 `execution/init_db.py` 取得唯一默认数据库路径、按 resolved path 共享的可重入初始化锁和通用连接 PRAGMA，不得从其他业务 Repository 模块导入数据库路径或维护私有初始化锁。共享锁只协调同一数据库文件的首次初始化和迁移；Model Provider、Node Structural、Workflow Structural Repository 继续分别拥有自身业务表 Schema，中央模块不得反向导入这些 Repository 或聚合业务建表 SQL。
8. `config.yaml` 和 `.sets_meta.json` 必须由专用 Repository 在 resolved path 共享锁内执行 read-modify-write，并通过同目录临时文件、flush/fsync 和 `os.replace` 原子提交；路由不得直接 truncate 覆盖这些文件。Workflow 更新/删除涉及 Repository、Manager 和 Execution 目录的补偿事务必须由 Application Service 拥有，路由只负责 DTO 与 HTTP 错误映射。

<a id="chapter-2-2"></a>

### 2.2 职责与边界

Structural Model 和 Execution Model 是两个独立的数据层，不允许把配置声明与执行事实混合保存。

| 维度           | Structural Model                                               | Execution Model                                          |
| -------------- | -------------------------------------------------------------- | -------------------------------------------------------- |
| 核心实体       | Workflow/Node 定义                                             | Workflow/Node 执行记录                                   |
| 模型定位       | 当前权威元数据与静态拓扑蓝图                                   | 某次触发后的客观事实与独立生命周期投影                   |
| 唯一持久化位置 | 关系型数据库中的强结构化记录                                   | 本机文件系统中的 JSON 文件                               |
| 写入方式       | 用户创建、编辑、删除直接映射为数据库 CRUD 事务                 | 执行器按生命周期单向追加或更新执行事实                   |
| 生效范围       | 保存成功后立即成为后续执行使用的当前定义                       | 只描述所属的本次执行，不改变当前或历史结构定义           |
| 可变性         | 当前定义允许通过显式 CRUD 修改；执行启动时形成的结构快照不可变 | 执行期间按状态机更新，进入终态后冻结，不允许编辑历史事实 |
| 数量关系       | 每个 Workflow/Node 保存一份当前定义                            | 一个结构定义可以产生多次 Workflow/Node Execution         |
| 拓扑与配置     | 保存身份、业务规则、节点拓扑、流转条件、模板和执行约束         | 保存本次实际使用的完整结构快照及其完整性哈希             |
| 输入与 Context | 只保存输入声明、常量和 Context 引用，不保存某次执行值          | 保存本次实际 Context、输入快照及其生命周期变化           |
| 请求与响应     | 保存未解析的请求或 Prompt 模板，不保存实际响应                 | 保存本次解析后的请求、实际响应和明细数据                 |
| 状态与时间     | 不保存状态、时间、耗时或尝试次数                               | 保存状态、时间、耗时、尝试次数和节点变迁轨迹             |
| 日志与错误     | 不保存执行日志、运行错误或堆栈                                 | 保存本次执行的原始日志、最终错误和诊断明细               |
| 读取目标       | 编辑器、保存校验和未来执行                                     | 在线运行观察、历史追溯与离线还原                         |

强制边界规则：

- 保存 Workflow 或节点配置时，只更新 Structural Model，不创建或修改 Execution Model；创建、编辑和删除必须作为关系型数据库事务即时生效。
- 用户显式保存 Workflow 时严格校验 START/END、Edge、循环、可达性、游离节点、字段类型和非空配置的格式，但允许 SCRIPT、LLM、HTTP 尚未填写运行必需配置；系统不区分草稿状态。启动 Workflow Run 时只重新校验同一套图结构，不对全部业务节点做配置预检；调度到具体节点时才校验该节点运行必需配置。
- 完整 Workflow Execution 创建持久化 Workflow/Node Execution Model 时，执行器必须读取当时完整的 Workflow/Node Structural Model，生成不可变的 `structural_snapshot`。快照属于 Execution Model，不能反向写入 Structural Model；当前简化契约不保存 `structural_hash`。4.4 节的单节点临时测试不创建 Execution Model，也不持久化快照。
- 节点运行期间修改 Structural Model，只影响修改成功后新启动的执行，不得改变已经开始的 Workflow/Node Execution、其中的 `structural_snapshot` 或后续重试使用的配置。
- 历史 NodeRun 不因 Structural Model 后续修改而重写。
- Structural Model outputs 是声明数组；Execution Model outputs 是实际值对象，两者名称相同但结构和职责不同。
- Execution Model 必须保存足以离线还原本次流水线或节点执行的 Context、inputs、outputs、状态变迁、明细和原始内容；日志界面只投影这些字段，运行期内存 Context 仍是执行器的工作变量池，不是结构模型的一部分。
- Execution Model 不允许反向修改节点名称、脚本源码、HTTP 请求模板、重试配置或输出声明。
- Context 只接受最终成功执行一次性提交的 Execution Model outputs；失败执行不得修改 Context。
- Context key 冲突属于节点执行失败；并行节点发生冲突时，先完成原子提交的节点保留输出，后提交节点失败，Workflow Run 中断。
- Workflow Run 后续进入 FAILED 或 INTERRUPTED 时，不回滚此前已经完成成功事务的 NodeRun、Execution Model outputs 或 Context 写入，也不把 SUCCESS 节点改为 INTERRUPTED。已提交 Context 值只保留到本次 Run 结束并随完整 Context 一起丢弃；历史 NodeRun 的 SUCCESS 和 outputs 继续持久化用于追溯。
- Structural Model 中用户配置的 `timeout_seconds`、`retry_interval_seconds` 和 `delay_seconds` 统一使用秒，允许非负或正的有限小数；执行器在进入调度时统一换算为整数毫秒。Execution Model 中记录客观耗时的字段继续使用整数毫秒和 `_ms` 后缀。
- Execution Model 的 JSON 文件是历史事实的唯一权威记录，必须支持用户离线、异步还原完整结构快照、Context、节点状态变迁、请求、响应、输出、错误和原始内容。不存在独立日志文件或日志数据库；持久化失败必须显式暴露，不能把不完整记录伪装成可回溯的成功记录。
- Execution Model 的 started_at 和 finished_at 统一使用 Asia/Shanghai 时区和 YYYY-MM-DD HH:mm:ss 格式，例如 2026-07-24 23:11:50；字符串不附加时区后缀。
- 所有耗时统计字段统一使用整数毫秒，字段名使用 _ms 后缀，例如 duration_ms。
- SCRIPT、HTTP 和 LLM 共用平台默认执行策略：`timeout_seconds=600`、`max_attempts=0`、`retry_interval_seconds=0`、`delay_seconds=0`。省略整个 `execution`、提交空对象或省略其中任意字段时，后端必须补齐对应默认值；用户显式提交的字段只覆盖同名默认值。`delay_seconds` 只在首次尝试前等待一次，等待期间节点保持 PENDING；重试前只等待 `retry_interval_seconds`（HTTP 的有效 `Retry-After` 可覆盖该次等待）。`timeout_seconds` 对每次执行尝试分别计时，每次重试重新开始计时；NodeRun.duration_ms 包含首次延迟、全部尝试和重试等待时间。
- SCRIPT、HTTP 和 LLM 的 NodeRun 最终事实区只保存最终尝试结果，不在该摘要中重复嵌入逐次尝试记录；每次尝试和 HTTP 中间重定向过程必须进入所属 Execution Model JSON 的持久化原始日志与状态轨迹。

NodeRun 从创建开始始终使用所属节点 Execution Model 参数表定义的完整字段结构，不按状态省略字段。尚未产生的 object 值使用 `{}`，array 值使用 `[]`，允许为空的标量或尚未解析的复杂事实使用 null。运行期间顶层只有 status、started_at、finished_at、duration_ms 和 attempt_count 等生命周期字段可以实时更新；节点专属 attempts/logs 可以按各节点规则追加实际尝试并更新当前尝试的状态与时间。inputs、network/model、request、redirects、response、usage、usage_errors、outputs 和 error 等顶层最终事实字段在节点进入终态时一次性写入。重试的完整过程写入所属 Execution Model JSON 的节点专属尝试与状态轨迹。典型占位规则如下：

- 所有节点在 PENDING 时 attempt_count 为 0，started_at、finished_at、duration_ms 和 error 为 null，inputs 与 outputs 为 `{}`。
- HTTP 在实际网络配置尚未解析时 network 为 null，请求尚未形成时 request 为 null，无重定向时 redirects 为 `[]`，响应尚未收到时 response 为 null。
- LLM 在模型配置尚未解析时 model 为 null，请求尚未形成时 request 为 null；最终尝试尚未收到任何响应内容时 response_received=false 且 response=null，尚未收到 usage 时 usage 为 null，usage_errors 为 `[]`。
- NodeRun 处于 PENDING 或 RUNNING 时，上述最终事实字段保持占位值，不展示或覆盖为中间尝试数据。进入 SUCCESS、FAILED、TIMEOUT 或 INTERRUPTED 时，执行器原子写入最终事实字段并冻结完整记录；只有 status、error 以及各节点规则共同决定最终结果。

attempt_count 只在一次执行真正启动时增加：SCRIPT 子进程成功启动、HTTP 完整尝试进入实际执行、LLM 供应商请求开始发送时分别计为一次。创建 NodeRun、执行预检、等待执行资源、等待 `delay_seconds`、`retry_interval_seconds`/Retry-After 或计划下一次重试都不增加 attempt_count；在首次延迟或重试等待期间取消时保留已经实际启动的次数，不预先计入尚未开始的尝试。

Node Execution 本体不混入可编辑的 Structural Model 字段。Workflow Execution 保存启动时不可变且自包含的 `structural_snapshot`，每个 Node Execution 保存自己的节点快照；即使对应 Workflow 或 Node 后续被修改或删除，历史执行仍必须能够仅依赖本地 Execution JSON 完成离线还原。

契约管理的身份字段 `workflow_id`、`id`、`workflow_execution_id`、`node_execution_id`、`node_id` 和 `edge_id` 统一使用 UUIDv4 字符串。HTTP 响应 Body、Context 业务对象和模型管理中的外部标识不受本规则约束。

<a id="chapter-2-3"></a>

### 2.3 Node Structural Model 类与数据库数据字典

当前实现位于 `execution/node_structural_models.py`。节点是独立持久化实体，不包含 `workflow_id`；未来 Workflow 只能通过另行确认的关联表引用节点，不能把归属字段补进当前节点表。当前也不创建 Node Execution 数据库表，执行事实未来按本规范写入本地 JSON。

#### 2.3.1 类说明

| 类 | 类说明 |
| --- | --- |
| `_NodeModel` | 所有节点结构类的严格 Pydantic 基类，统一拒绝契约外字段。 |
| `NodeCommon` | 所有节点结构模型共有的身份和用户可见展示字段。 |
| `JsonVariableInput` | START 的一项初始变量声明，执行成功时按原名称和值提交到 Context。 |
| `NodeOutput` | 业务节点的一项输出绑定，声明 Context 变量名、目标类型和取值来源。 |
| `RetryExecution` | SCRIPT、LLM 和 HTTP 共用的首次延迟、单次尝试超时与自动重试声明。 |
| `StartNodeStructuralModel` | START 节点完整结构模型，只声明初始 Context 变量。 |
| `ScriptNodeStructuralModel` | SCRIPT 节点完整结构模型，保存 Python 源码、执行约束和输出绑定。 |
| `ModelReference` | LLM 节点对模型管理中供应商及模型的引用。 |
| `LlmContextMessage` | LLM 上下文中的一条有序消息模板。 |
| `LlmContextDefinition` | LLM 阻塞调用使用的有序上下文消息序列。 |
| `GenerationDefinition` | LLM 节点覆盖模型默认 Body 的供应商原生高级参数。 |
| `LlmNodeStructuralModel` | LLM 节点完整结构模型，组合模型、上下文、生成参数、执行约束和输出绑定。 |
| `HttpHeader` | HTTP 请求的一项用户 Header。 |
| `HttpParameter` | HTTP 请求的一项有序 Query 参数。 |
| `HttpFormField` | form_data 或 form_urlencoded Body 的一项有序字段。 |
| `HttpBody` | Context 解析前的 HTTP Body 编码类型和内容模板。 |
| `HttpRequest` | HTTP 方法、URL、Header、Query、重定向和 Body 声明。 |
| `HttpProxy` | SYSTEM、DIRECT 或 CUSTOM 代理路由及可选认证信息。 |
| `HttpNetwork` | 独立组合代理路由和 TLS 证书验证的网络策略。 |
| `HttpResponseDefinition` | HTTP 最终响应的 Body 表示方式和业务成功状态码。 |
| `HttpExecution` | HTTP 执行约束，在公共重试字段上增加非幂等方法和状态码策略。 |
| `HttpNodeStructuralModel` | HTTP 节点完整结构模型，面向内网 API 请求。 |
| `EndNodeStructuralModel` | END 节点完整结构模型，只作为图结构结束标志。 |
| `NodeStructuralRecord` | Repository 返回对象，组合已验证节点与数据库管理时间。 |
| `NodeStructuralRepository` | 节点结构模型 SQLite Repository，提供初始化和 CRUD。 |
| `NodeStructuralRepositoryError` | 持久化、读取或 Repository 不变量被破坏时抛出的领域错误。 |

#### 2.3.2 公共类字段

| 类.字段 | 类型 / 取值 | 必填 / 默认 | 说明 |
| --- | --- | --- | --- |
| `NodeCommon.id` | string，规范小写 UUIDv4 | 必填 | 节点全局唯一身份；创建后不可修改。 |
| `NodeCommon.type` | `START / SCRIPT / LLM / HTTP / END` | 必填 | Pydantic 判别字段；创建后不可修改。 |
| `NodeCommon.name` | string，1..200 | 必填 | 用户可见节点名称；仅空白值无效。 |
| `NodeCommon.description` | string，0..4000 | `""` | 用户填写的节点用途说明。 |
| `JsonVariableInput.name` | `[A-Za-z_][A-Za-z0-9_]*` | 必填 | 大小写敏感的 Context 变量名。 |
| `JsonVariableInput.type` | `string / number / integer / boolean / object / array / null` | 必填 | START 输入值的严格 JSON 类型。 |
| `JsonVariableInput.value` | 严格 JSON value | 必填 | 必须与 type 精确匹配，禁止 NaN 和 Infinity。 |
| `NodeOutput.name` | `[A-Za-z_][A-Za-z0-9_]*` | 必填 | 成功后写入 Context 的大小写敏感变量名。 |
| `NodeOutput.type` | 七种严格 JSON 类型 | 必填 | 输出转换的目标类型。 |
| `NodeOutput.source` | string，1..4000 | 必填 | 类型专属取值表达式；SCRIPT 中必须是顶层 Python 变量名。 |
| `RetryExecution.timeout_seconds` | strict number，`>= 0.001` | `600` | 每一次实际尝试的超时，单位秒；允许小数秒。 |
| `RetryExecution.max_attempts` | strict integer，0..10 | `0` | 最大重试次数，不包含首次尝试。 |
| `RetryExecution.retry_interval_seconds` | strict number，0..600 | `0` | 两次尝试之间的固定等待秒数；允许小数秒。 |
| `RetryExecution.delay_seconds` | strict number，0..600 | `0` | 首次尝试开始前只执行一次的等待秒数；允许小数秒。 |

#### 2.3.3 五类节点字段

下表只列类型专属字段；每类节点还必须包含 `NodeCommon` 的四个公共字段。

| 类.字段 | 类型 | 必填 / 默认 | 说明 |
| --- | --- | --- | --- |
| `StartNodeStructuralModel.inputs` | `JsonVariableInput[]` | `[]` | 按声明顺序原子提交到 Context；节点内 name 不得重复。 |
| `ScriptNodeStructuralModel.script` | string | `""` | 用户编写的完整 Python 源码；允许空值保存，执行到节点时失败。 |
| `ScriptNodeStructuralModel.execution` | `RetryExecution` | 平台默认执行策略 | SCRIPT 超时与重试配置；允许整体省略或部分覆盖。 |
| `ScriptNodeStructuralModel.outputs` | `NodeOutput[]` | `[]` | 从顶层 Python 变量读取的输出绑定；name 不得重复。 |
| `LlmNodeStructuralModel.model` | `ModelReference` | `{provider_id:"",model_name:""}` | 模型管理中的供应商和模型引用；允许空值保存。 |
| `LlmNodeStructuralModel.context` | `LlmContextDefinition` | `{messages:[SYSTEM,USER]}` | 有序消息模板；允许空内容和末尾 ASSISTANT 草稿保存。 |
| `LlmNodeStructuralModel.generation` | `GenerationDefinition` | `{parameters:{},parameters_text:""}` | 节点级供应商原生高级参数与可保存草稿文本。 |
| `LlmNodeStructuralModel.execution` | `RetryExecution` | 平台默认执行策略 | LLM 调用超时与重试配置；允许整体省略或部分覆盖。 |
| `LlmNodeStructuralModel.outputs` | `NodeOutput[]` | `[]` | 从供应商完整 response 提取值；name 不得重复。 |
| `HttpNodeStructuralModel.request` | `HttpRequest` | POST + 空 URL + none Body | HTTP 业务请求模板；允许空 URL 保存。 |
| `HttpNodeStructuralModel.network` | `HttpNetwork` | SYSTEM + verify_ssl=true | Proxy 与 SSL 验证配置；CUSTOM 允许暂缺 URL 保存。 |
| `HttpNodeStructuralModel.response` | `HttpResponseDefinition` | AUTO + 200-299 | 响应表示和成功判定配置。 |
| `HttpNodeStructuralModel.execution` | `HttpExecution` | 平台默认执行策略 | HTTP 超时与重试策略；允许整体省略或部分覆盖。 |
| `HttpNodeStructuralModel.outputs` | `NodeOutput[]` | `[]` | 从最终 request/response 提取值；name 不得重复。 |
| `EndNodeStructuralModel` | 无专属字段 | 不适用 | 只保存四个公共字段，不包含执行或变量逻辑。 |

#### 2.3.4 LLM 子结构字段

| 类.字段 | 类型 | 必填 / 默认 | 说明 |
| --- | --- | --- | --- |
| `ModelReference.provider_id` | string，0..200 | `""` | 模型供应商配置 ID；允许空值保存。 |
| `ModelReference.model_name` | string，0..200 | `""` | 供应商下已经添加的模型名称；允许空值保存。 |
| `LlmContextDefinition.messages` | `LlmContextMessage[]`，至少两项 | 空 SYSTEM、USER | 固定角色顺序；内容完整性在执行到节点时校验。 |
| `LlmContextMessage.role` | `SYSTEM / USER / ASSISTANT` | 必填 | 结构定义使用大写角色；网关请求转换为小写。 |
| `LlmContextMessage.content` | string | `""` | 支持 Context 引用的消息模板；允许空值保存。 |
| `GenerationDefinition.parameters` | JSON object | `{}` | 覆盖模型默认 Body 的节点高级参数；禁止非严格 JSON 值。 |

#### 2.3.5 HTTP 子结构字段

| 类.字段 | 类型 / 取值 | 必填 / 默认 | 说明 |
| --- | --- | --- | --- |
| `HttpHeader.key` | 合法 HTTP Header 名 | 必填 | 不支持 Context 引用；禁止 Content-Length、Transfer-Encoding、Content-Encoding。 |
| `HttpHeader.value` | string | 必填 | 支持 Context 引用；拒绝 CR、LF 和 NUL。 |
| `HttpParameter.key` | 非空 string | 必填 | Query 参数名；数组保序并允许重复 key。 |
| `HttpParameter.value` | JSON scalar | 必填 | Query 参数值，可包含 Context 引用。 |
| `HttpFormField.key` | 非空 string | 必填 | 表单字段名。 |
| `HttpFormField.value` | JSON value | 必填 | 表单字段值，可包含 Context 引用。 |
| `HttpBody.type` | `none / raw / form_data / form_urlencoded` | 必填 | Body 编码方式。 |
| `HttpBody.content` | JSON value | `null` | type=none 时必须为 null；表单类型时校验为 `HttpFormField[]`。 |
| `HttpRequest.method` | `GET / POST / PUT / PATCH / DELETE / HEAD / OPTIONS` | 必填 | HTTP 请求方法；GET/HEAD 不允许 Body。 |
| `HttpRequest.url` | HTTP/HTTPS string，0..8000 | `""` | 支持 Context 引用；允许空草稿保存，非空时自动删除首尾空白且不允许内部空白字符。 |
| `HttpRequest.follow_redirects` | boolean | `true` | 是否跟随 HTTP 重定向。 |
| `HttpRequest.headers` | `HttpHeader[]` | `[]` | 保持用户声明顺序的 Header。 |
| `HttpRequest.params` | `HttpParameter[]` | `[]` | 保持用户声明顺序的 Query 参数。 |
| `HttpRequest.body` | `HttpBody` | 必填 | 请求 Body 定义。 |
| `HttpProxy.mode` | `SYSTEM / DIRECT / CUSTOM` | `SYSTEM` | 明确决定是否使用系统代理、直连或自定义代理。 |
| `HttpProxy.url` | HTTP/HTTPS URL 或 null | `null` | CUSTOM 时必填；SYSTEM/DIRECT 时禁止填写。 |
| `HttpProxy.username` | string 或 null | `null` | CUSTOM 代理用户名。 |
| `HttpProxy.password` | string 或 null | `null` | CUSTOM 代理密码；属于敏感字段。 |
| `HttpNetwork.proxy` | `HttpProxy` | SYSTEM 空配置 | 代理路由和可选认证。 |
| `HttpNetwork.verify_ssl` | boolean | `true` | 是否验证目标服务及 HTTPS Proxy 证书，与 proxy.mode 独立。 |
| `HttpResponseDefinition.mode` | `AUTO / JSON / TEXT / BINARY` | `AUTO` | 最终响应 Body 的内存表示方式。 |
| `HttpResponseDefinition.success_statuses` | HTTP 状态码或闭区间数组 | `["200-299"]` | 决定响应是否属于业务成功。 |
| `HttpExecution.retry_non_idempotent` | boolean | `false` | 是否允许 POST/PATCH 自动重试。 |
| `HttpExecution.retry_statuses` | 100..599 integer[] | `[408,429,500,502,503,504]` | 允许触发自动重试的失败状态码，不得重复。 |

#### 2.3.6 Repository 返回类和操作

| 类.字段 / 方法 | 类型 | 说明 |
| --- | --- | --- |
| `NodeStructuralRecord.node` | Node 判别联合 | 完整且已经通过类型专属校验的节点结构模型。 |
| `NodeStructuralRecord.created_at` | UTC ISO-8601 string | 首次持久化时间。 |
| `NodeStructuralRecord.updated_at` | UTC ISO-8601 string | 最近一次成功更新时间。 |
| `NodeStructuralRepository.database_path` | filesystem path | SQLite 文件绝对路径，默认 `run_storage/agent_bench.sqlite3`。 |
| `initialize()` | void | 创建节点表和索引，并定点删除五张旧 Workflow 表。 |
| `create(node)` | `NodeStructuralRecord` | 校验后插入；重复 id 明确失败。 |
| `get(node_id)` | record 或 null | 按主键读取并重新执行完整 Pydantic 校验。 |
| `list(node_type=None)` | record[] | 按 updated_at、id 倒序列出全部节点或指定类型。 |
| `update(node)` | `NodeStructuralRecord` | 按 id 更新当前定义；id/type 不可修改，created_at 保持不变。 |
| `delete(node_id)` | boolean | 定点删除节点；不存在时返回 false。未来接入 Execution JSON 后还需按已确认规则清理该节点日志文件。 |

#### 2.3.7 SQLite 表说明

表名：`node_structural_models`

表职责：保存独立 Node Structural Model 的当前权威定义。每行对应一个节点，只保存静态定义；不保存 `workflow_id`、Edge、Context、Execution、状态、请求、响应、输出实际值、错误或日志。

| 列 | SQLite 类型 / 约束 | 详细说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 规范小写 UUIDv4；节点全局唯一，创建后不可修改，未来供 Workflow 关联表引用。 |
| `type` | `TEXT NOT NULL CHECK` | 只允许 START、SCRIPT、LLM、HTTP、END；创建后不可修改，决定 definition_json 使用的校验类。 |
| `name` | `TEXT NOT NULL CHECK(length(trim(name)) > 0)` | 用户可见名称；应用层限制 1..200 字符。 |
| `description` | `TEXT NOT NULL DEFAULT ''` | 用户可见用途说明；应用层限制最多 4000 字符，无内容保存空字符串。 |
| `definition_json` | `TEXT NOT NULL CHECK(json_valid(...) AND json_type(...)='object')` | 严格 JSON object，只保存类型专属字段；写入前经 Pydantic 校验，禁止公共字段、额外字段、NaN 和 Infinity。 |
| `created_at` | `TEXT NOT NULL` | 首次创建的 UTC ISO-8601 毫秒时间，更新时不改变。 |
| `updated_at` | `TEXT NOT NULL` | 最近一次创建或更新的 UTC ISO-8601 毫秒时间，用于列表倒序。 |

索引 `node_structural_models_by_type_updated(type, updated_at DESC, id DESC)` 服务于按节点类型筛选和最近更新排序。公共列与 `definition_json` 的边界固定如下：

| type | definition_json 允许且必须校验的顶层字段 |
| --- | --- |
| START | `inputs` |
| SCRIPT | `script / execution / outputs` |
| LLM | `model / context / generation / execution / outputs` |
| HTTP | `request / network / response / execution / outputs` |
| END | 空对象 `{}` |

初始化按依赖顺序定点删除三代旧 Workflow/Run/评测流水线表：`workflow_node_runs`、`workflow_node_runs_v2`、`node_runs`、`artifacts`、`attempts`、`step_runs`、`case_runs`、`workflow_runs`、`workflow_runs_v2`、`runs`、`testset_workflow_bindings`、`testset_execution_configs`、`workflow_drafts`、`workflow_definitions_v2`、`workflows`、`schema_migrations`。这些表均无现行代码引用，旧数据不迁移、不提供兼容读取；初始化不得删除或重建模型管理、Excel 或其他非 Workflow 表。

#### 2.3.8 Workflow 当前实施状态

Workflow Structural Model 类、完整图校验、三张关系表和事务 Repository 已实现于 `execution/workflow_structural_models.py`；Workflow/Node Execution JSON、调度执行器和单节点临时测试已实现于 `execution/workflow_execution.py`；新版 Workflow CRUD/Run/Node Test API 已实现于 `web/routes_workflows.py`，React Flow 管理页面已接入这些 API。不得恢复旧 Workflow JSON 聚合模型，也不得把 `workflow_id` 写入 `node_structural_models`。

<a id="chapter-2-4"></a>

### 2.4 Workflow Structural Model

Workflow Structural Model 只定义 Workflow 身份、展示信息、Node 归属、画布坐标和 Edge 拓扑。Node 完整定义继续由独立 `node_structural_models` 表负责；Workflow 通过 binding 引用 Node，一个 Node 实例只能属于一个 Workflow，复用必须复制为新 Node。

#### 类与字段

| 类.字段 | 类型 / 取值 | 必填 / 默认 | 说明 |
| --- | --- | --- | --- |
| `WorkflowStructuralModel.id` | 规范小写 UUIDv4 | 必填 | Workflow 全局唯一 ID，创建后不可修改。 |
| `WorkflowStructuralModel.name` | string，非空 | 必填 | 用户可见名称；保存原始首尾空白并按完整原文全局唯一。仅由空白组成的名称无效。 |
| `WorkflowStructuralModel.description` | string | `""` | 用户填写的 Workflow 用途说明。 |
| `WorkflowStructuralModel.nodes` | `WorkflowNodeBinding[]` | 必填 | 当前 Workflow 的 Node 引用和画布坐标，不嵌入 Node 定义。 |
| `WorkflowStructuralModel.edges` | `WorkflowEdge[]` | 必填 | 只表达调度依赖的有向 Edge。 |
| `WorkflowNodeBinding.node_id` | UUIDv4 | 必填 | 引用独立 Node Structural Model。 |
| `WorkflowNodeBinding.position_x` | finite number | 必填 | Node 在画布中的 X 坐标，不参与执行调度。 |
| `WorkflowNodeBinding.position_y` | finite number | 必填 | Node 在画布中的 Y 坐标，不参与执行调度。 |
| `WorkflowEdge.id` | UUIDv4 | 必填 | Edge 全局唯一 ID。 |
| `WorkflowEdge.source_node_id` | UUIDv4 | 必填 | 同一 Workflow 中的上游 Node。 |
| `WorkflowEdge.target_node_id` | UUIDv4 | 必填 | 同一 Workflow 中的下游 Node。 |
| `WorkflowStructuralRecord.workflow` | `WorkflowStructuralModel` | 必填 | 完整且已校验的当前 Workflow 定义。 |
| `WorkflowStructuralRecord.created_at` | UTC ISO-8601 毫秒时间 | 数据库管理 | 首次持久化时间。 |
| `WorkflowStructuralRecord.updated_at` | UTC ISO-8601 毫秒时间 | 数据库管理 | 最近一次成功保存 Workflow、Node、binding 或 Edge 的时间。 |

#### 数据库表

`workflow_structural_models`：

| 列 | SQLite 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 规范小写 UUIDv4。 |
| `name` | `TEXT NOT NULL UNIQUE` | 保留首尾空白并按数据库原文全局唯一；应用层拒绝纯空白。 |
| `description` | `TEXT NOT NULL DEFAULT ''` | 用户可见说明。 |
| `created_at` | `TEXT NOT NULL` | UTC ISO-8601 毫秒时间。 |
| `updated_at` | `TEXT NOT NULL` | 任一所属结构成功保存后的 UTC ISO-8601 毫秒时间。 |

`workflow_node_bindings`：

| 列 | SQLite 类型 / 约束 | 说明 |
| --- | --- | --- |
| `workflow_id` | `TEXT NOT NULL` | 引用 `workflow_structural_models.id`。 |
| `node_id` | `TEXT NOT NULL UNIQUE` | 引用 `node_structural_models.id`；UNIQUE 保证一个 Node 只属于一个 Workflow。 |
| `position_x` | `REAL NOT NULL` | 有限画布 X 坐标。 |
| `position_y` | `REAL NOT NULL` | 有限画布 Y 坐标。 |

主键为 `(workflow_id, node_id)`。Workflow 删除时 binding 级联删除；Node 删除时 binding 级联删除。

`workflow_edges`：

| 列 | SQLite 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | Edge UUIDv4。 |
| `workflow_id` | `TEXT NOT NULL` | 所属 Workflow。 |
| `source_node_id` | `TEXT NOT NULL` | 上游 Node。 |
| `target_node_id` | `TEXT NOT NULL` | 下游 Node。 |

`(workflow_id, source_node_id, target_node_id)` 必须唯一。source/target 分别使用 `(workflow_id, node_id)` 复合外键引用 binding，从数据库层保证 Edge 两端属于同一个 Workflow；删除 binding 自动删除相关 Edge。

#### CRUD 与事务

- 前端编辑状态只是会话草稿，不属于 Structural Model。用户显式保存且完整校验通过后，才通过数据库事务即时成为当前权威定义。
- 新增 Node 时，在同一事务中创建 Node Structural Model 和 binding；不允许长期存在未绑定 Node。
- 已绑定 Node 的创建、编辑、删除统一经过 `WorkflowStructuralRepository`；一次保存原子更新 Workflow、Node、binding 和 Edge，任一失败全部回滚并保持原结构不变。
- Workflow 名称按数据库原文全局唯一。创建、完整保存或 metadata 更新命中 `workflow_structural_models.name` 唯一约束时，Repository 必须转换为 `WorkflowNameConflictError`；API 必须返回 HTTP `409` 和固定文案“Workflow 名称已存在，请使用其他名称”，不得向页面暴露 SQLite `UNIQUE constraint` 原文。
- 从当前 Workflow 删除 Node 时删除 binding 和当前 Node Structural Model，但不删除历史 Execution JSON；历史文件依赖执行快照继续离线可读。删除整个 Workflow 时才定点清理其全部 Execution 目录。
- Workflow Studio 的节点右键“更换节点”只允许 `SCRIPT / LLM / HTTP` 三类业务节点互换，START/END 不显示该入口。更换不是修改既有 Node 的 type，而是在前端图中创建目标类型的新 Node ID、删除旧 Node，并把所有引用旧 ID 的入边/出边端点改到新 ID；Edge ID、节点坐标和当前选中状态保持不变。
- 更换后的 name 使用目标类型默认名称、description 为空，类型专属配置、输出声明、临时测试状态和旧节点日志均不继承；目标节点完整使用当前 `makeNode` 默认结构。旧历史 Execution JSON 继续按旧 Node ID 和快照离线可读，不迁移到新节点。
- Workflow 或当前节点临时测试运行期间禁止更换。更换进入画布撤销/重做历史并把 Workflow 标记为未保存；显式保存时 Repository 必须在同一事务中插入新 Node、更新 binding/Edge、删除旧 Node，任一失败回滚整张图。
- Workflow Studio 不提供多选节点批量对齐按钮或菜单。拖动任一节点时，前端以画布坐标对比该节点与其他节点的顶边 `position.y` 和左边 `position.x`；取整后的差值严格位于 `(-5, 5)` 时显示对应的 1px 水平或垂直参考线，等于或超过 5px 时不显示。两轴可同时命中，线段必须覆盖拖动节点和同轴命中节点的完整几何范围。
- 对齐参考线只提供视觉反馈，不吸附、不修正或舍入 Node position，也不改变选择、Edge 和执行拓扑。参考线按当前 viewport 的平移与缩放投影到屏幕，必须忽略指针事件；拖动停止后立即清空。一次拖动只在开始时写入一个撤销快照，停止时 Workflow 标记为未保存；显式保存原样持久化最终 position，重新打开必须还原相同坐标。
- Workflow RUNNING 时允许编辑并保存当前 Structural Model，活动执行只读取启动时快照；Workflow 存在活动执行时禁止删除，必须先全局中断并等待终态。

<a id="chapter-2-5"></a>

### 2.5 Workflow Execution Model

Workflow Execution 是一次独立 Workflow 生命周期的客观事实，只保存于：

```text
run_storage/workflow_executions/{workflow_id}/{workflow_execution_id}/
├── workflow.json
└── nodes/
    └── {node_execution_id}.json
```

同一个 Workflow 允许多个 Execution 并发运行，每次使用独立 ID、结构快照、Context 和 Node Execution 目录。Workflow 管理画布为了防止重复点击，在当前手动 Execution 结束前禁用运行按钮；Batch 调度器可以并发创建同一 Workflow 的多个 Execution。

#### workflow.json 完整结构

```json
{
  "id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
  "trigger": {"type": "MANUAL"},
  "status": "RUNNING",
  "structural_snapshot": {
    "workflow": {
      "id": "123e4567-e89b-42d3-a456-426614174000",
      "name": "质量检测",
      "description": ""
    },
    "nodes": [],
    "edges": []
  },
  "created_at": "2026-07-26T02:00:00.000Z",
  "started_at": "2026-07-26T02:00:00.010Z",
  "finished_at": null,
  "duration_ms": null,
  "context": {
    "commits": [],
    "final": {}
  },
  "nodes": [],
  "error": null
}
```

#### 顶层字段

| 字段 | 类型 / 取值 | 说明 |
| --- | --- | --- |
| `id` | UUIDv4 | Workflow Execution ID；模型自身不重复保存 `workflow_execution_id`。 |
| `workflow_id` | UUIDv4 | 启动时所引用的 Workflow Structural Model ID。 |
| `trigger` | object | 手工运行保存 `{"type":"MANUAL"}`；Batch 保存 `type / batch_execution_id / case_run_id / case_id / row_number`。 |
| `status` | `PENDING / RUNNING / SUCCESS / FAILED / INTERRUPTED` | Workflow 当前或最终状态。 |
| `structural_snapshot` | object | 自包含的不可变 Workflow 快照，展开完整 Node 定义和坐标，不含数据库 created_at/updated_at。 |
| `created_at` | UTC ISO-8601 毫秒时间 | JSON 被创建的时间。 |
| `started_at` | UTC ISO-8601 毫秒时间或 null | Workflow 实际开始调度的时间。 |
| `finished_at` | UTC ISO-8601 毫秒时间或 null | Workflow 进入终态的时间。 |
| `duration_ms` | non-negative integer 或 null | started_at 到 finished_at 的耗时。 |
| `context` | object | 只含 commits 和 final；不保存永远为空的 initial。 |
| `nodes` | array | START、业务节点和 END 的紧凑调度结果及 Node Execution 引用。 |
| `error` | object 或 null | Workflow 主错误；SUCCESS 时必须为 null。 |

当前简化契约明确不保存 `inputs`、`updated_at`、`metadata`、`config`、`summary`、`structural_hash` 或 `scheduling.events`。START 实际输入由 structural_snapshot、START Node Execution 和 Context commit 共同形成离线事实。

#### context.commits

```json
{
  "sequence": 1,
  "node_id": "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44",
  "node_execution_id": "4d2c6b8a-1f3e-4a90-b7d5-6c8e2f1a9b55",
  "committed_at": "2026-07-26T02:00:00.100Z",
  "values": {"question": "请审核"}
}
```

只有实际产生非空 outputs 的 SUCCESS Node Execution 生成 commit。values 必须原子写入 `context.final`，两处值必须一致；零输出的 START/END 不生成 commit。

#### nodes

```json
{
  "node_id": "550e8400-e29b-41d4-a716-446655440000",
  "node_execution_id": "5e074085-8d4a-4e0b-8f3c-2a9d6b7c3e33",
  "state": "FINISHED",
  "reason": null
}
```

`state` 只允许 `WAITING / RUNNING / FINISHED / NOT_STARTED`。READY 是执行器瞬时内部状态，不持久化。具体节点状态和时间从固定路径 `nodes/{node_execution_id}.json` 读取，不在 workflow.json 重复保存；未启动节点的 node_execution_id 为 null。任一节点最终 FAILED 后，未启动节点统一使用 `NOT_STARTED + WORKFLOW_FAILED`，RUNNING 节点被终止并在自己的 Node Execution 中记录 `INTERRUPTED + WORKFLOW_ABORTED`。

#### Node Execution 状态轨迹

Workflow JSON 不保存完整调度事件。每个已创建的 Node Execution 保存最小 `transitions`，用于离线还原节点状态变化：

```json
"transitions": [
  {"status": "PENDING", "at": "2026-07-26T02:00:00.010Z", "reason": null},
  {"status": "RUNNING", "at": "2026-07-26T02:00:00.020Z", "reason": null},
  {"status": "FAILED", "at": "2026-07-26T02:00:01.000Z", "reason": "MODEL_REQUEST_FAILED"}
]
```

#### 错误、写入和恢复

- Workflow error code 固定为 `NODE_FAILED / USER_INTERRUPTED / PROCESS_RESTARTED / PERSISTENCE_FAILED`。NODE_FAILED 同时保存触发根因的 node_id 和 node_execution_id；其他节点错误保留在各自 JSON。
- 每次 JSON 更新写入同目录临时文件，flush、fsync 后原子替换正式文件；Windows 下读取或原子替换遇到瞬时 `PermissionError` 时最多执行 6 次、每次间隔 10ms 的有界重试，最终失败仍显式抛错。Node Execution 终态先成功落盘，再更新 workflow.json 引用和 Context。
- 应用启动时扫描遗留 PENDING/RUNNING Execution，不自动续跑；Workflow 终结为 `FAILED + PROCESS_RESTARTED`，已启动但无终态的 Node Execution 终结为 `FAILED + RUNTIME_LOST`。
- Workflow Execution 全部保留，界面最多展示最近 10 次。删除 Workflow 时原子移动对应 Workflow Execution 根目录到临时回收目录，数据库删除事务失败则恢复目录，事务成功后彻底删除回收目录。

#### Workflow 管理与批量模块边界

- 当前 Workflow 管理只负责开发和测试迭代：Workflow CRUD、画布编排、完整校验、单节点临时测试、手动运行完整 Workflow、查看真实结果和错误。
- 一级 Workflow 列表业务字段只展示名称、说明、更新时间。
- 画布保留最近 10 次 Workflow Execution 历史，并增加独立“执行记录”按钮；按钮固定打开当前 Workflow 的 Execution 根目录 `run_storage/workflow_executions/{workflow_id}/`，不自动跳入最近一次或选中的单次 Execution 目录。
- 新建 Workflow 和打开已有 Workflow 时，画布先使用标准 Fit View 完整适配当前全部节点，再以画布中心为锚点把 zoom 精确乘以 `0.67`；该规则只改变初始视口，不缩小节点尺寸、文字、Inspector 或页面容器。用户之后点击 Fit View、缩放或平移仍使用标准交互，不持续强制 67%。
- Excel、用例映射、Batch Run、批量并发和批量结果页属于独立模块，不进入 Workflow Structural Model。每条用例创建独立 Workflow Execution，批量模块只负责行级调度。
- 数据库仍然只保存 Structural Model；Batch/Workflow/Node Execution 只保存本地 JSON。

#### END 调度与执行记录入口

- END 不在 Workflow 启动时预先创建。只有全部直接上游 Node Execution 均为 SUCCESS、DAG 调度器实际调度到 END 时，才创建空 END Node Execution；该 Execution 从 PENDING 进入 RUNNING 后立即 SUCCESS，随后 Workflow 才进入 SUCCESS。
- 画布最近 10 次 Workflow Execution 历史继续保留。“执行记录”按钮与历史面板并存，固定打开当前 Workflow 的 Execution 根目录，不根据当前历史选择改变目标目录。

<a id="chapter-2-6"></a>

### 2.6 Batch Execution Model

Batch Run 把一个 Excel Sheet 的每条有效数据行调度为一次独立 Workflow Execution，持久化路径固定为：

```text
run_storage/batch_executions/{batch_execution_id}/
├── batch.json
├── input/
│   ├── source.xlsx 或 source.xlsm
│   └── snapshot.json
└── cases/
    └── {case_run_id}.json
```

- 创建时冻结源 Excel 字节、SHA-256、Sheet 表头和数据行、Workflow Structural Snapshot、变量注入配置及并发数；后续修改源文件或 Workflow 不影响既有 Batch。
- 首行模式支持 `AUTO / HEADER / DATA`。AUTO 在首两列命中既有 Case ID/Question 表头别名时按表头读取，否则按数据读取；HEADER 要求有效表头区间非空且不重复，并裁掉末尾空表头列；DATA 从第一行开始读取并生成 `case_id / question / column_3...`。完全空白数据行忽略；每条有效数据行以其原始 Excel 行号作为当前 Batch 内的 Case 追溯标识。
- 变量注入配置为 `source / key / value / type`。`source=EXCEL` 时 value 必须是手填的 `col_x` 列路径，`col_1` 固定表示当前 Sheet 第一列；可追加 `.field` 与 `[index]` 从 JSON object/array 单元格中读取局部值，例如 `col_4.checks.intent.status`。`source=CUSTOM` 时 value 是用户填写的文本。type 支持 `string / number / integer / boolean / object / array / null`，object 与 array 使用严格 JSON 文本。key 必须是 Context 根变量名且在一个 Run 内唯一。
- 每个 Case 在创建阶段从其 Excel 行解析 Excel 来源变量，并将自定义值与 Excel 值转换为配置的 type；转换失败时不创建部分 Batch 目录。注入变量写入该 Case 的 START 快照，允许覆盖同名 START 默认值，节点可直接使用 `context["key"]` 读取。
- 结果校验由可选的多个校验点组成。每个校验点只保存 `result_path / operator / expected_value / type`：result_path 必须以 `context.` 开头，并从该 Case 最终 Context 读取，例如 `context.final_answer.status`；expected_value 为用户填写的文本，按 type 严格转换。所有校验点使用 AND 语义，任一校验点为 FAIL 或 ERROR 时，该 Case 状态为 FAILED，同时保留原始 Workflow execution_status 用于追溯。
- `case_id` 由 Excel 原始行号生成，只进入 Case 与 BATCH trigger 追踪字段，不自动写入 Context。业务字段是否注入由变量注入配置决定。
- Batch 状态为 `QUEUED / RUNNING / SUCCESS / COMPLETED_WITH_ERRORS / INTERRUPTED`；Case 状态为 `QUEUED / RUNNING / SUCCESS / FAILED / INTERRUPTED`。
- Case 失败不阻断同 Batch 的其他 Case。Batch 全部成功时为 SUCCESS；存在失败且未被取消时为 COMPLETED_WITH_ERRORS。
- 取消后停止新派发、全局中断活动 Workflow，未启动 Case 转为 INTERRUPTED。恢复默认只继续 QUEUED/INTERRUPTED Case；启用 `retry_failed` 后额外重跑 FAILED，SUCCESS 永不重复执行。
- 服务重启不自动续跑：RUNNING Batch 和 Case 收敛为 `INTERRUPTED + PROCESS_RESTARTED`，等待用户手工恢复。
- Workflow 被任一 Batch 引用时禁止删除，避免清理其 Workflow Execution 事实；用户删除相关终态 Batch 后才能删除 Workflow。RUNNING Batch 必须先取消并等待终态。
- 单 Batch 的 Case 并发数范围为 1 到 32；进程级共享并发槽限制多个 Batch 的总活动 Case，当前默认上限为 16。
- Batch、Case 和输入快照全部使用严格 JSON、同目录临时文件、flush、fsync 和原子替换；Windows 深层目录删除使用长路径语义。

<a id="chapter-3"></a>

## 3. Context

<a id="chapter-3-1"></a>

### 3.1 概要与定义

Context 是一次 Workflow Run 的共享变量池，用于在节点之间传递业务数据。它只保存变量名和值，不保存来源节点、路径、描述或运行日志。

```json
{
  "review_result": {
    "status": "PASS",
    "reason": "审核通过"
  },
  "review_status": "PASS"
}
```

<a id="chapter-3-2"></a>

### 3.2 生命周期

- 每次新的 Workflow Run 开始时创建空 Context。
- Context 只在当前 Workflow Run 内有效，不同 Run 之间完全隔离。
- Workflow Run 结束后释放执行器中的内存 Context；本次 Context 的最终快照及其节点提交轨迹必须保存在所属 Execution Model JSON 中，用于离线回溯。Context 不作为 Structural Model 定义的一部分，也不得因执行而回写结构模型。
- 节点只能读取当前 Context，不能直接读取其他 Run 的 Context。

<a id="chapter-3-3"></a>

### 3.3 读写规则

- 节点通过统一的输入协议读取 Context 变量。
- 节点成功后才可以把输出变量提交到 Context。
- 节点执行期间产生的中间值属于节点本地状态，不直接修改共享 Context。
- 节点提交输出前，必须在 Context 中检查所有待提交 key；只要任一 key 已存在，整个节点提交失败，不允许覆盖已有值。
- START inputs.name 与所有业务节点 outputs.name 在整个 Workflow 范围内按大小写精确比较并保持唯一；只有完全相同的变量名才视为重复。发现重复时，Workflow 保存和运行前置校验失败。运行时 Context key 冲突检查仍作为并发与数据完整性的最终防线。
- START inputs.name 与所有节点 outputs.name 输入时必须符合 `[A-Za-z_][A-Za-z0-9_]*`；Structural Model、Context、Execution Model inputs/outputs 和日志始终保存用户原始大小写，不进行规范化改写。
- Workflow 校验、Context 引用、SCRIPT context Mapping 和提交冲突检查均按变量名原始大小写精确匹配。`result`、`Result` 和 `RESULT` 可以同时声明、读取和提交，互不冲突。
- Context 引用保存时保留根变量标识符和所有嵌套对象字段的原始大小写；根变量及嵌套字段均按 JSON 对象 key 规则区分大小写。
- 输出提交必须是原子操作；检查与写入必须在同一个 Context 提交事务中完成。同一节点不得部分写入，提交失败时所有待提交输出都丢弃，并中断当前 Workflow Run。
- 节点最终成功事务必须把输出校验、Context 原子提交、Execution Model 最终事实写入和 NodeRun 转为 SUCCESS 视为一个不可分割的终态操作；未声明 outputs 时 Context 提交集合为空，但仍使用同一终态操作。任何一步失败都不得留下 SUCCESS NodeRun 或部分 Context 输出。
- 下游调度器只有在上游成功事务完整提交后，才能观察到上游 SUCCESS 和对应 Context 变量；不允许先观察状态、后等待变量异步写入。
- Context key 已存在时，节点状态为 FAILED，error.code 使用 `CONTEXT_KEY_EXISTS`；Workflow Run 停止调度尚未开始的节点。
- START 的每一项 key 必须是合法且唯一的 Context 变量名，value 使用 JSON 输入并支持字符串、数字、布尔值、对象、数组和 null；value 解析失败或不是严格 JSON 值时，START 失败且不写入任何变量。提交前执行与业务节点相同的 key 冲突检查和原子提交。
- 节点失败、超时或被中断时，其待提交输出全部丢弃，Context 保持执行前状态。
- Context 中的值必须能够序列化为严格 JSON；不可序列化值、NaN、Infinity 和循环引用不得写入。

统一 JSON 数值类型规则：

- `number` 接受有限整数和有限小数，包括运行时 int 或 float，但不接受 boolean；例如 `1`、`-2`、`1.5` 均符合 number。
- `integer` 只接受以整数表示形式解析和存储的值，不接受 float 或 boolean；例如 `1` 符合 integer，`1.0` 即使数学值等于 1 也不符合 integer。
- number 包含 integer，二者不是互斥类型；声明为 number 的输入或输出可以接收整数。
- START 输入校验使用以上规则；SCRIPT、LLM 和 HTTP outputs.source 先按下方统一隐式转换矩阵转换为用户选择的 outputs.type，再按相同严格 JSON 类型规则校验转换结果。

SCRIPT/LLM/HTTP outputs 统一隐式转换矩阵：

| outputs.type | 允许的提取值/source 值 | 转换结果 |
| ------------ | ---------------------- | -------- |
| string | string；或可严格 JSON 序列化的 object/array/integer/number/boolean/null | string 保持实际文本；object/array 转为 UTF-8 紧凑 JSON 文本；其他 JSON 标量转为 JSON 字面量文本，其中 boolean 为 `true/false`、null 为 `null` |
| integer | 非 boolean 的 integer；数学值为整数且往返精确相等的 finite number；严格 JSON number 字符串且精确十进制值为整数 | 精确十进制 integer；不接受精度丢失、非有限数、前导 `+`、非法前导零或带空白文本 |
| number | 非 boolean 的 finite integer/number；严格匹配 JSON number 语法的字符串 | integer 保持精确整数；已有 finite float 使用能往返还原同一值的最短 JSON number；数字字符串按精确十进制直接形成 JSON number，不经过 binary float |
| boolean | boolean；或大小写不敏感且精确为 `true`/`false` 的 string | boolean；不接受 `1/0`、yes/no、空白、任意对象真值或其他 Python truthiness 规则 |
| object | object；或可按严格 JSON 完整解析且根值为 object 的 string | object 的严格 JSON 深拷贝 |
| array | array；或可按严格 JSON 完整解析且根值为 array 的 string | array 的严格 JSON 深拷贝 |
| null | null；或精确为 `null` 的 string | null；不接受 `None`、空字符串或带空白文本 |

统一转换规则：

- JSON number 字符串使用 `^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$`；所有字符串按原文匹配，不执行 trim、宽松 JSON、区域数字格式或注释/尾随逗号兼容。
- object/array 转 string 时生成紧凑 JSON 文本，不转义非 ASCII 字符，不添加多余空格或换行。JSON 文件持久化该 string 时产生的必要外层转义按顶层 JSON 展示约束处理，不属于实际变量内容。
- number 转 integer 只有在数学值为整数且 integer 转回原数值后精确相等时才允许；`1.0` 可以转为 `1`，`1.2`、NaN、Infinity 和任何会损失精度的值均拒绝。
- 平台不得调用任意 Python 对象的自定义 `str()`、`int()`、`float()` 或真值判断。未列入矩阵的转换一律使用节点对应的 `*_OUTPUT_TYPE_MISMATCH`。
- 多个 outputs 分别转换并形成严格 JSON 深拷贝；任一项转换、序列化或最终类型校验失败时，整组 outputs 不提交。

<a id="chapter-3-4"></a>

### 3.4 与 Execution Model 的关系

- Context 是当前 Workflow Run 的业务状态。
- Execution Model 是节点执行记录，保存实际输入、已提交输出、状态、执行次数和错误。
- Execution Model 的 inputs 和 outputs 是运行快照，不会改变 Context 的数据结构。
- 日志界面展示所需的原始请求、原始响应和错误堆栈属于 Execution Model 运行事实，不写入 Context，也不另存为独立日志模型。

<a id="chapter-3-5"></a>

### 3.5 引用规则

HTTP、LLM 和 AGENT 节点中允许引用 Context 的配置字段统一使用以下格式：

```text
${variable_name}
```

`${...}` 中的根变量名直接对应当前 Workflow Execution 的 Context key，严格区分大小写，不存在 `ctx`、`context` 或其他命名空间前缀。

支持读取嵌套对象和数组：

```text
${review_result.status}
${devices[0].name}
```

引用语法只允许变量读取、对象字段访问和数组下标访问，不允许函数调用、运算符或任意代码。

```text
${price * 2}       不允许
${name.upper()}    不允许
```

解析规则：

- 整个字段只有一个 Context 引用时，保留变量的原始 JSON 类型。
- Context 引用嵌入普通文本时，将变量转换为文本；对象和数组使用紧凑 JSON。
- 节点字段可以在各自协议中收紧或覆盖上述类型规则；LLM Prompt 始终转换为文本，HTTP URL/Header/Params 按第八章规则处理。
- 引用的变量不存在或嵌套路径不存在时，节点在实际请求或调用开始前失败。
- 只有精确的 `${variable_name}` 及其对象字段、数组下标路径属于 Context 引用；`${ variable_name }`、`{{ variable_name }}`、`{{ ctx.variable_name }}` 和 `{{ context.variable_name }}` 均为普通文本。
- `\${variable_name}` 表示输出引用原文 `${variable_name}`，不读取 Context；反斜杠只用于转义模板起始符，解析后的文本中不保留该反斜杠。
- SCRIPT 的 Python 源码不执行模板替换；平台通过只读 context Mapping 提供当前 Context 快照，输出按 SCRIPT outputs.source 从顶层 Python 变量采集。
- Execution Model inputs 始终以 Context 根变量名为 key，并保存该根变量未经路径提取或文本转换的完整 JSON 值。例如引用 `${review_result.status}` 时记录完整的 `review_result`；同一次最终执行通过多个路径引用同一根变量时只记录一次。

<a id="chapter-4"></a>

## 4. Node Status

<a id="chapter-4-1"></a>

### 4.1 NodeRun 状态矩阵

START 和 END 都创建 Node Execution。END 不执行用户代码、网络调用、重试或 Context 操作；一旦按最终确认的创建时机生成，其空执行立即 SUCCESS。业务节点重试发生在 RUNNING 内部；Node Execution 一旦进入 FAILED 或 TIMEOUT，说明对应节点已按策略完成全部允许的尝试，不会从终态再次重试。

| 节点状态    | START | SCRIPT | LLM | HTTP | END | 触发条件                                       | 重试策略                            |
| :---------- | :---: | :----: | :-: | :--: | :-: | :--------------------------------------------- | :---------------------------------- |
| PENDING     |  √  |   √   | √ |  √  | √ | NodeRun 已创建，前置依赖已满足但尚未获得执行权 | -                                   |
| RUNNING     |  √  |   √   | √ |  √  | √ | 节点开始实际执行；重试与重试等待期间保持该状态 | 按节点 execution 策略在状态内部重试 |
| SUCCESS     |  √  |   √   | √ |  √  | √ | 执行、输出校验、Context 提交与终态事务全部成功 | ×                                  |
| FAILED      |  √  |   √   | √ |  √  | × | 最终非超时错误、输出提交失败或执行前运行时错误 | ×                                  |
| TIMEOUT     |  ×  |   √   | √ |  √  | × | 最后一次允许的执行结果为超时                   | ×                                  |
| INTERRUPTED |  √  |   √   | √ |  √  | × | 用户取消或 Fail-Fast 中断                      | ×                                  |

<a id="chapter-4-2"></a>

### 4.2 状态与 error 不变量

- PENDING、RUNNING、SUCCESS 时 error 必须为 null。
- FAILED、TIMEOUT、INTERRUPTED 时 error 必须为非空结构化 error。
- START 不执行自动重试，也不进入 TIMEOUT。
- END 只允许 PENDING、RUNNING、SUCCESS；它创建空 Node Execution 并立即成功，不声明 error、重试或超时逻辑。

<a id="chapter-4-3"></a>

### 4.3 Workflow Run 状态

Workflow Execution 自身维护状态、时间、最终 Context、紧凑节点调度结果和顶层错误，用于表示整张 Workflow 的生命周期；它与 Node Execution.status 分开记录。完整 JSON 和字段只以 2.5 节为准，本节不重复定义第二份结构。

| 状态        | 含义                                                           |
| ----------- | -------------------------------------------------------------- |
| PENDING     | Workflow Run 已创建，但尚未进入节点调度                        |
| RUNNING     | 至少一个节点已进入调度，Workflow 尚未结束                      |
| SUCCESS     | 必选 END 的 Node Execution 已进入 SUCCESS                      |
| FAILED      | 任一节点最终失败、超时、Context 冲突或缺失变量，触发 Fail-Fast |
| INTERRUPTED | 用户主动取消 Workflow Run；正在运行的节点转为 INTERRUPTED      |

状态规则：

- Workflow Execution 创建时为 PENDING；START Node Execution 被创建后转为 RUNNING，并写入 started_at。
- 只有全部直接上游 SUCCESS、END 被实际调度并产生 SUCCESS Node Execution 后，Workflow Execution 才能转为 SUCCESS。
- 任一节点最终 FAILED 或 TIMEOUT 后，Workflow 转为 FAILED 并立即触发全局 Fail-Fast。
- FAILED 时，Workflow Execution.error 保存调度器最先观察到的触发根因及其 node_id/node_execution_id；其他并行失败保留在各自 Node Execution 中，SUCCESS 时 error 为 null。
- Fail-Fast 触发后，所有已经创建但未成功终结的 PENDING/RUNNING Node Execution 必须记录为 `INTERRUPTED + WORKFLOW_ABORTED`；尚未创建的节点不补建文件，只在 workflow.json.nodes 中记录 `NOT_STARTED + WORKFLOW_FAILED`。全部终态写入后 Workflow 才写 finished_at。
- 用户主动取消时 Workflow Execution 转为 INTERRUPTED，error.code 使用 `USER_INTERRUPTED`。所有 RUNNING Node Execution 立即中断；尚未创建的节点不补建文件，只在 workflow.json.nodes 中记录 `NOT_STARTED + GLOBAL_INTERRUPTED`。Workflow 等待全部中断与 JSON 原子写入完成后再记录 finished_at；取消不执行自动重试。
- 完整 Workflow Execution 运行期间不提供用户单节点中断能力。画布节点卡片和节点编辑器不得把节点中断操作发送给正在运行的 Node Execution，也不得把该操作隐式升级为全局中断；用户主动停止只能使用画布全局中断。
- 对已进入 SUCCESS、FAILED 或 INTERRUPTED 的 Workflow Execution，或已进入任一终态的 Node Execution，再次发送取消/中断请求是幂等 no-op，不修改任何历史事实。
- Workflow Execution 进入 SUCCESS、FAILED 或 INTERRUPTED 后不再改变状态。

<a id="chapter-4-4"></a>

### 4.4 单节点临时测试

Workflow Studio 必须支持 START、SCRIPT、LLM 和 HTTP 的单节点临时测试。节点卡片和节点编辑页的运行按钮只测试当前节点草稿，不启动完整 Workflow，不创建 Workflow Execution 或 Node Execution，不要求 START/END 存在，也不执行当前节点的上游或下游节点。临时测试不得触发整图结构校验、DAG 调度或 Workflow Fail-Fast。任何节点均不提供用户可见的单节点中断按钮；END 不执行用户逻辑，也不提供运行按钮。

用户可以在节点编辑器中修改当前节点草稿后直接测试。节点 id 和 type 不允许临时修改；其他属于该节点 Structural Model 的可编辑字段均以当前草稿值参与测试。测试不会隐式保存草稿，只有用户显式点击保存且节点校验通过后，当前草稿才写入关系型数据库并成为新的 Structural Model。

测试 SCRIPT、LLM 或 HTTP 时，运行前由用户填写仅对本次测试有效的测试变量；Workflow 存在 START 时，界面以 START inputs 的名称、类型和值作为可编辑预填值，用户本次填写的同名值覆盖预填值。临时测试不得读取历史 Workflow/Node Execution 的 Context 或 outputs，不得自动执行上游节点，也不得使用模拟上游输出。缺少变量、类型不匹配或路径不存在时必须在当前测试结果中显示明确错误，不允许静默填充 null、空字符串或其他默认值。

测试 START 时使用空测试 Context，不预先写入 START inputs。界面允许用户在当前 START 草稿中临时编辑 name、description 和 inputs 的 name/type/value；确认运行后，当前草稿 inputs 是唯一输入来源，并按正常类型校验和原子提交规则写入空测试 Context 一次。测试产生的 Context 仅用于形成当前页面中的 inputs、outputs 和日志，不写回 START 或 Workflow Structural Model。

单节点测试状态、耗时、输入、输出、错误和原始日志只保存在当前页面内存中，并按对应节点已定义的日志结构实时展示。测试数据不得写入关系型数据库、不得生成或修改任何 Workflow/Node Execution JSON、不得进入最近执行历史，也不得作为后续节点或完整 Workflow 的 Context。刷新页面、关闭节点编辑器或离开 Workflow Studio 后全部清空；服务端在 Worker 终止并完成最后一个实时事件后释放该次测试内存。

临时测试运行期间再次点击运行按钮是幂等 no-op，所有节点卡片、节点右键菜单和节点编辑器均不得提供单节点中断入口。关闭正在测试的节点编辑器、删除正在测试的 Node 或所属 Workflow、离开 Workflow Studio 时，系统必须先阻止新的测试请求，在内部取消并等待活动 Worker 及其派生进程停止，再清理页面会话或提交 Structural Model 删除；该内部清理不属于用户单节点中断，也不扫描或删除测试 JSON，因为单节点测试从不创建持久化文件。

<a id="chapter-5"></a>

## 5. START

START 是每个 Workflow 必须且只能存在一个的系统入口节点。当前阶段只负责把用户在 Structural Model 中保存的 `name / type / value` 输入一次性写入当前 Execution 的 Context；上传文件、用户发言和外部任务下发能力暂不纳入本节。

<a id="chapter-5-1"></a>

### 5.1 Structural Model

#### Structural Model 示例

```json
{
  "id": "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44",
  "type": "START",
  "name": "输入审核参数",
  "description": "为本次 Workflow 提供初始变量",
  "inputs": [
    {
      "name": "conversation",
      "type": "string",
      "value": "请审核这段内容"
    },
    {
      "name": "retry_count",
      "type": "integer",
      "value": 3
    }
  ]
}
```

#### 参数列表

| 字段        | 类型   | 取值                         | 示例                                                              | 含义                               |
| ----------- | ------ | ---------------------------- | ----------------------------------------------------------------- | ---------------------------------- |
| id          | string | UUIDv4 字符串                | 2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44                              | START 节点在 Workflow 中的唯一标识 |
| type        | string | START                        | START                                                             | 系统入口节点类型                   |
| name        | string | 用户自定义                   | 输入审核参数                                                      | 画布和日志中显示的节点名称         |
| description | string | 用户自定义，可为空           | 为本次 Workflow 提供初始变量                                      | 节点业务用途说明                   |
| inputs      | array  | 可为空，且 name 在本节点唯一 | [{"name":"conversation","type":"string","value":"请审核这段内容"}] | 初始变量输入项                    |

#### inputs 参数

| 字段 | 类型       | 取值                                                  | 示例           | 含义                               |
| ---- | ---------- | ----------------------------------------------------- | -------------- | ---------------------------------- |
| name | string     | 合法变量名，且在本节点内唯一                          | conversation   | 写入 Context 的变量名              |
| type  | string     | string、number、integer、boolean、object、array、null | string         | 对 value 执行的严格 JSON 类型约束  |
| value | JSON value | 必须符合 type，且可严格 JSON 序列化                   | 请审核这段内容 | 本次 START 要写入 Context 的变量值 |

START 的 inputs 是用户在节点编辑器中填写的 `name / type / value` 行。value 不使用 Context 引用，也不执行模板替换；它是当前节点定义中保存的 JSON 值。START Structural Model 不声明 outputs；执行成功时，全部 inputs 按 name 原样形成 outputs 并一次性提交到 Context。

<a id="chapter-5-2"></a>

### 5.2 Execution Model

Execution Model 记录 START 实际输入和成功写入 Context 的结果。START 不自动重试；进入 RUNNING 后 attempt_count 固定为 1，执行前动态错误或在 PENDING 时被取消则为 0。

START `inputs=[]` 时仍创建真实 Node Execution，依次记录 PENDING、RUNNING、SUCCESS transitions，inputs 和 outputs 都是 `{}`，attempt_count 为 1；该空执行不产生 Context commit。

#### Execution Model 示例

```json
{
  "workflow_execution_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
  "node_execution_id": "4d2c6b8a-1f3e-4a90-b7d5-6c8e2f1a9b55",
  "node_id": "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44",
  "type": "START",
  "status": "SUCCESS",
  "started_at": "2026-07-25 10:00:00",
  "finished_at": "2026-07-25 10:00:01",
  "duration_ms": 1000,
  "attempt_count": 1,
  "inputs": {
    "conversation": "请审核这段内容",
    "retry_count": 3
  },
  "outputs": {
    "conversation": "请审核这段内容",
    "retry_count": 3
  },
  "logs": {
    "input_validation": {
      "status": "SUCCESS",
      "inputs": {
        "conversation": "请审核这段内容",
        "retry_count": 3
      },
      "error": null
    },
    "context_commit": {
      "status": "SUCCESS",
      "outputs": {
        "conversation": "请审核这段内容",
        "retry_count": 3
      },
      "error": null
    }
  },
  "error": null
}
```

#### 参数列表

| 字段          | 类型        | 取值                                           | 示例                                 | 含义                                   |
| ------------- | ----------- | ---------------------------------------------- | ------------------------------------ | -------------------------------------- |
| workflow_execution_id | string      | UUIDv4 字符串                                  | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10 | 所属 Workflow Execution ID            |
| workflow_id           | string      | UUIDv4 字符串                                  | 123e4567-e89b-42d3-a456-426614174000 | 所属 Workflow Structural Model ID      |
| node_execution_id   | string      | UUIDv4 字符串                                  | 4d2c6b8a-1f3e-4a90-b7d5-6c8e2f1a9b55 | 本次 START 运行记录的唯一标识          |
| node_id       | string      | UUIDv4 字符串                                  | 2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44 | Structural Model START 节点 ID         |
| type          | string      | START                                          | START                                | 节点类型                               |
| status        | string      | PENDING、RUNNING、SUCCESS、FAILED、INTERRUPTED | SUCCESS                              | START 当前或最终状态                   |
| started_at    | string/null | YYYY-MM-DD HH:mm:ss，Asia/Shanghai 或 null     | 2026-07-25 10:00:00                  | 进入 RUNNING 的时间；PENDING 时为 null |
| finished_at   | string/null | YYYY-MM-DD HH:mm:ss 或 null                    | 2026-07-25 10:00:01                  | 节点结束时间                           |
| duration_ms   | int/null    | 大于等于 0 或 null                             | 1000                                 | 节点总耗时，单位毫秒                   |
| attempt_count | int         | 0 或 1                                         | 1                                    | START 实际执行次数                     |
| inputs        | object      | name 到 JSON 值的映射                          | {"conversation":"请审核这段内容"}    | START 本次实际读取的输入值             |
| outputs       | object      | name 到 JSON 值的映射，失败时为 {}             | {"conversation":"请审核这段内容"}    | 成功提交到 Context 的变量              |
| logs          | object      | START 专属日志对象                             | 见上方完整示例                         | 输入校验与 Context 提交的完整阶段日志  |
| error         | object/null | error 对象或 null                              | null                                 | START 执行错误                         |

#### logs 参数

START 日志固定包含 `input_validation` 和 `context_commit` 两个阶段，不使用 SCRIPT、LLM 或 HTTP 的日志结构。

完整 Workflow 执行时，logs 属于持久化 START Node Execution；单节点临时测试时，前端临时快照复用相同 logs 结构和阶段状态，但不包含 workflow_execution_id、node_execution_id 或 structural_snapshot，不写数据库或 JSON。

| 字段             | 类型   | 取值                           | 示例                              | 含义                          |
| ---------------- | ------ | ------------------------------ | --------------------------------- | ----------------------------- |
| input_validation | object | input_validation 对象          | {"status":"SUCCESS","inputs":{}} | 本次实际输入及其校验结果      |
| context_commit   | object | context_commit 对象            | {"status":"SUCCESS","outputs":{}} | 本次 Context 原子提交结果     |

#### input_validation 参数

| 字段   | 类型        | 取值                                                | 示例                           | 含义                                      |
| ------ | ----------- | --------------------------------------------------- | ------------------------------ | ----------------------------------------- |
| status | string      | NOT_STARTED、RUNNING、SUCCESS、FAILED、INTERRUPTED | SUCCESS                        | 输入校验阶段当前或最终状态                |
| inputs | object      | name 到本次实际 JSON 值的映射                       | {"conversation":"请审核"}  | 完整 Workflow 或独立执行实际使用的 inputs |
| error  | object/null | 完整 error 对象或 null                              | null                           | 本阶段完整错误                            |

#### context_commit 参数

| 字段    | 类型        | 取值                                                | 示例                          | 含义                                   |
| ------- | ----------- | --------------------------------------------------- | ----------------------------- | -------------------------------------- |
| status  | string      | NOT_STARTED、RUNNING、SUCCESS、FAILED、INTERRUPTED | SUCCESS                       | Context 提交阶段当前或最终状态         |
| outputs | object      | name 到成功提交值的映射，未成功时为 {}              | {"conversation":"请审核"} | 本阶段实际提交的完整变量集合           |
| error   | object/null | 完整 error 对象或 null                              | null                          | 本阶段完整错误                         |

阶段日志规则：

- Node Execution 创建时两个阶段均为 NOT_STARTED；输入校验开始后 `input_validation.status` 转为 RUNNING，校验成功后转为 SUCCESS，再启动 `context_commit`。
- 输入校验失败时，`input_validation.status=FAILED` 并保存完整错误，`context_commit` 保持 NOT_STARTED、outputs 为 `{}`、error 为 null。
- Context 提交失败时，`input_validation.status=SUCCESS`，`context_commit.status=FAILED` 并保存完整错误，outputs 为 `{}`。
- 某阶段实际开始后被用户或 Fail-Fast 中断时，该阶段记录 INTERRUPTED 和完整错误；尚未开始的阶段保持 NOT_STARTED。Node Execution 在 PENDING 时被中断，两个阶段均保持 NOT_STARTED，原因只记录在顶层 error。
- START 成功时两个阶段均为 SUCCESS，所有阶段 error 和顶层 error 均为 null。
- Node Execution 最终为 FAILED 或 INTERRUPTED 且存在已失败或中断阶段时，顶层 error 必须与该终态阶段的 error 完全一致；顶层 error 用于列表摘要，阶段 error 用于定位失败步骤。

#### error 参数

| 字段    | 类型        | 取值                    | 示例                | 含义                         |
| ------- | ----------- | ----------------------- | ------------------- | ---------------------------- |
| code    | string      | 稳定错误码              | START_INPUT_INVALID | 机器可读错误码               |
| message | string      | 非空字符串              | 本次输入值与 type 不匹配 | 面向用户的错误说明       |
| details | object/null | 结构化 JSON 对象或 null | null                | 可选诊断信息；不写入 Context |

<a id="chapter-5-3"></a>

### 5.3 Input & Output Protocol

- START 按 inputs 数组顺序读取每一项的 name、type 和 value。
- 保存 START Structural Model 时，任一 name 重复、name 不合法、value 不是合法 JSON 或 value 与 type 不匹配，均属于配置错误；保存校验必须拒绝该配置，不创建 Workflow/Node Execution，也不创建日志。
- 完整 Workflow 启动前再次发现上述 Structural Model 配置错误时，同样拒绝启动，不创建 Workflow/Node Execution。只有已通过配置校验、但在 Execution 创建后发现 Context 冲突等动态错误时，才创建 FAILED Node Execution。
- START 临时测试允许在当前前端草稿中编辑 inputs 的 name、type 和 value，但不写回 Structural Model；临时 name/type/value 校验失败时，前端测试快照显示 FAILED，error.code 使用 `START_INPUT_INVALID`，attempt_count=0，outputs 为 `{}`。临时 `logs.input_validation` 保存实际测试 inputs 和完整错误，`logs.context_commit` 保持 NOT_STARTED；后端不创建 Node Execution 或 JSON。
- START 提交前必须检查所有 name 是否已经存在于 Context；任一 key 冲突时 error.code 为 `CONTEXT_KEY_EXISTS`，outputs 为 {}。完整 Workflow Execution 中该错误触发 Fail-Fast；START 临时测试只把当前前端快照终结为 FAILED，不创建或中断 Workflow Execution。
- 所有输入校验通过后，START 将 inputs 一次性写入 Context；outputs 与成功提交的变量集合一致。
- START 不提供独立 outputs 配置；实现不得要求用户重复声明输出名称、类型或映射，Execution Model outputs 必须由本次成功提交的全部 inputs 直接形成。
- START 不执行自动重试；用户主动取消或 Workflow Fail-Fast 中断时，按通用 NodeRun 规则记录 INTERRUPTED。
- START 临时测试从空测试 Context 开始，当前前端草稿 inputs 是唯一输入来源；不得先把 inputs 作为预填变量写入 Context，也不得在执行过程中重复提交。

<a id="chapter-5-4"></a>

### 5.4 用户可见日志

START 日志用于确认输入校验和 Context 原子提交是否成功。它不显示不存在的 request、response、console 或 traceback。

| 显示区域 | 字段来源 | 展示规则 |
| --- | --- | --- |
| 列表时间 | started_at；未开始时 finished_at | `MM-DD HH:mm:ss` |
| 列表状态 | status | 原样显示 SUCCESS、FAILED 或 INTERRUPTED |
| 列表耗时 | duration_ms | 毫秒；null 显示 `--` |
| 展开-输入 | inputs | 完整 JSON |
| 展开-输出 | outputs | 仅 SUCCESS 显示完整 JSON |
| 展开-失败阶段 | logs.input_validation.status、logs.context_commit.status | 仅 FAILED/INTERRUPTED 显示实际失败或中断阶段 |
| 展开-错误 | error | 仅 FAILED/INTERRUPTED 显示顶层完整 code/message/details，不重复显示相同的阶段 error |

示例：

```text
07-25 10:00:00  SUCCESS  1000 ms

输入
{"conversation":"请审核这段内容","retry_count":3}

输出
{"conversation":"请审核这段内容","retry_count":3}
```

失败示例：

```text
07-25 10:00:00  FAILED  12 ms

输入
{"conversation":"请审核这段内容","retry_count":3}

失败阶段
Context 提交

错误
{"code":"CONTEXT_KEY_EXISTS","message":"变量 conversation 已存在","details":{"key":"conversation"}}
```

失败阶段只通过两个阶段的真实 status 判断：input_validation 为 FAILED/INTERRUPTED 时显示“输入校验”，否则 context_commit 为 FAILED/INTERRUPTED 时显示“Context 提交”；两个阶段均未开始时显示“未开始”。界面不得打印成功阶段的重复 inputs/outputs，不得根据 outputs 反向推测 inputs，也不得把阶段 error 与顶层 error 合并成新的错误文本。

<a id="chapter-6"></a>

## 6. SCRIPT

<a id="chapter-6-1"></a>

### 6.1 Structural Model

Structural Model 只记录节点定义，不记录某次运行的输入值、实际输出值、Context、状态、日志或错误。

#### Structural Model 示例

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "SCRIPT",
  "name": "汇总审核结果",
  "description": "汇总多个审核节点的结果",
  "script": "review = context[\"review_result\"]\nreview_status = review[\"status\"]",
  "execution": {
    "timeout_seconds": 600,
    "max_attempts": 3,
    "retry_interval_seconds": 1,
    "delay_seconds": 0
  },
  "outputs": [
    {
      "name": "review_status",
      "type": "string",
      "source": "review_status"
    }
  ]
}
```

#### 与 Execution Model 的字段边界

| Structural Model               | Execution Model            | 边界                                                                   |
| ------------------------------ | -------------------------- | ---------------------------------------------------------------------- |
| id                             | node_id                    | Execution Model 只引用节点 ID，不修改 ID                               |
| type                           | type                       | Execution Model 复制节点类型用于识别记录                               |
| name、description              | 无对应业务字段             | 只用于定义态展示，不作为执行结果                                       |
| script                         | 无对应业务字段             | 作为本次执行代码输入，不写入 inputs、outputs 或 Context                |
| execution                      | attempt_count、duration_ms | execution 声明最大重试和间隔；Execution Model 记录实际执行次数及总耗时 |
| outputs 数组                   | outputs 对象               | 前者声明 name/type/source 绑定，后者保存成功采集的 name/value          |
| 无 Structural Model inputs     | inputs 对象                | SCRIPT 不预先声明输入，Execution Model 保存本次尝试获得的完整 Context 快照 |
| 无 Structural Model 状态和错误 | status、error              | 只由执行过程产生                                                       |
| 无 Structural Model 日志       | NodeRun 摘要不重复嵌入日志 | 原始日志、失败堆栈和逐次尝试细节保存在所属 Execution Model JSON；原始文本受固定 5 MiB 上限约束 |

#### 参数列表

| 字段        | 类型   | 取值               | 示例                                                   | 含义                                 |
| ----------- | ------ | ------------------ | ------------------------------------------------------ | ------------------------------------ |
| id          | string | UUIDv4 字符串      | 550e8400-e29b-41d4-a716-446655440000                   | 节点在 Workflow 中的唯一标识         |
| type        | string | SCRIPT             | SCRIPT                                                 | 节点类型为脚本                       |
| name        | string | 用户自定义         | 汇总审核结果                                           | 画布和日志中显示的节点名称           |
| description | string | 用户自定义，可为空 | 汇总多个审核节点的结果                                 | 节点业务用途说明                     |
| script      | string | Python 源码文本    | review = context["review_result"]                      | 用户编辑的完整脚本代码               |
| execution   | object | 可省略，默认平台策略 | {"timeout_seconds":600,"max_attempts":3,"retry_interval_seconds":1,"delay_seconds":0} | 执行参数；显式字段覆盖同名默认值     |
| outputs     | array  | 可为空，默认 []    | [{"name":"review_status","type":"string","source":"review_status"}] | 脚本成功时必须全部产生的输出绑定 |

SCRIPT Structural Model 直接在 script 字段保存 Python 源码字符串，不嵌套 source、language 或 version，也不提供运行语言和解释器版本选择；平台实际 Python 运行环境属于部署配置，不进入节点定义或 Execution Model。

SCRIPT Worker 固定使用启动 Agent Bench 服务的项目当前 `.venv` Python 解释器，以项目根目录作为每次尝试的初始工作目录，并继承服务进程在该次 Worker 创建时可见的环境变量快照。Worker 使用当前操作系统用户权限，不额外创建容器或文件系统/网络沙箱；用户代码对当前尝试中的工作目录或环境变量修改不得反向修改服务进程。

SCRIPT 可以 import 当前 `.venv` 已安装的标准库和第三方包。依赖不存在时，Worker 必须把原始 `ModuleNotFoundError`、完整 traceback 和 STDERR 写入本次 attempt 日志，顶层错误使用 `SCRIPT_RUNTIME_ERROR`；平台不得在保存、测试、Workflow 执行或重试期间自动调用 pip、uv 或其他包管理器安装依赖。依赖只能由用户在 Workflow 执行之外显式维护。

#### execution 参数

| 字段                       | 类型   | 取值       | 示例 | 含义                                   |
| -------------------------- | ------ | ---------- | ---- | -------------------------------------- |
| timeout_seconds            | number | >= 0.001   | 600  | 单次脚本执行超时时间，单位秒；默认 600 |
| max_attempts               | int    | 0~10       | 3    | 最大重试次数，不包含首次执行           |
| retry_interval_seconds     | number | 0~600      | 1    | 失败后、下一次重试前的固定间隔，单位秒 |
| delay_seconds              | number | 0~600      | 0    | 首次脚本执行前只等待一次，单位秒       |

暂不设置用户可配置的 retry_on 或 max_output_bytes。SCRIPT 日志使用 Execution Model 固定的 5 MiB 上限，不进入 Structural Model，也不允许节点覆盖。

max_attempts 的语义：

| 配置值 | 最大总执行次数      |
| ------ | ------------------- |
| 0      | 1 次，不重试        |
| 1      | 2 次，最多重试 1 次 |
| 3      | 4 次，最多重试 3 次 |

`delay_seconds` 只在首次执行前生效一次；重试不会再次叠加首次延迟，只等待 `retry_interval_seconds`。

SCRIPT 重试规则：Python 运行异常、超时、Context 读取错误和其他发生在用户代码执行过程中的错误允许按 max_attempts 重试。`SCRIPT_OUTPUT_MISSING`、`SCRIPT_OUTPUT_TYPE_MISMATCH` 和 `SCRIPT_OUTPUT_SERIALIZATION_ERROR` 属于代码正常结束后的确定性输出契约错误，首次出现即终结为 FAILED，不执行自动重试。画布全局中断或 Workflow Fail-Fast 产生 INTERRUPTED，同样不重试。
SCRIPT 单次尝试达到 `timeout_seconds` 时，平台终止脚本主进程及其派生进程树；进程树结束后，本次尝试记为 TIMEOUT，并按 max_attempts 和 `retry_interval_seconds` 决定是否重试。

#### outputs 参数

outputs 是脚本顶层 Python 变量到 Context 输出变量的绑定声明。平台只采集这里声明的 source；脚本中的其他局部变量、导入对象和中间值不会写入 Context。

| 字段 | 类型   | 取值                                                  | 示例          | 含义                           |
| ---- | ------ | ----------------------------------------------------- | ------------- | ------------------------------ |
| name   | string | 合法 Context 变量名，且在本节点内唯一                 | message | 写入 Context 的变量名                       |
| type   | string | string、number、integer、boolean、object、array、null | string  | 用户选择的 source 隐式转换目标类型          |
| source | string | 合法 Python 标识符                                    | msg     | 脚本正常结束后读取的顶层 Python 变量名       |

type 必须由用户在节点输出变量配置中显式选择，平台不得根据 source 当前 Python 值自动推断或改写声明类型。脚本正常结束后，平台按第 3.3 节统一隐式转换矩阵把 source 实际值转换为该目标类型；用户未选择 type 时 Structural Model 校验失败，不允许保存或运行完整 Workflow，单节点临时测试则在前端快照中显示配置错误。

name 和 source 都保留用户填写的原始大小写：name 按 Context key 精确匹配，source 按 Python 标识符精确匹配，二者均不执行小写归一化。多个 outputs 可以绑定同一个 source，以不同 name 输出同一值；outputs.name 按大小写精确比较并保持唯一，source 不要求唯一。

例如脚本定义顶层变量：

```python
msg = "介绍一下自己"
```

输出声明可以把下游变量 `message` 绑定到 Python 变量 `msg`：

```json
{
  "name": "message",
  "type": "string",
  "source": "msg"
}
```

脚本成功后形成 `{"message":"介绍一下自己"}`，下游按 Context 精确名称引用 `message`。如需同名输出，则同时把 name 和 source 填为 `msg`。

outputs 不包含 description 或表达式。source 只能引用脚本正常结束后仍存在于顶层执行命名空间的变量，不能直接引用函数局部变量、对象路径或表达式；函数结果必须先赋给顶层变量。outputs 非空时，每个 source 都必须存在并完成第 3.3 节统一隐式转换及严格 JSON 序列化；任一项失败时整组 outputs 为 `{}`。outputs 为空时，脚本正常结束即可成功且不写入 Context。

Structural Model 不定义输入变量列表。每次尝试开始时，平台把当前 Workflow Context 的隔离只读快照作为顶层变量 context 提供给脚本；单节点临时测试则使用前端本次提供的临时 Context。

<a id="chapter-6-2"></a>

### 6.2 Execution Model

Execution Model 记录一次节点执行的最终结果，不修改 Structural Model 定义。顶层 inputs、outputs 和 error 只保存最终尝试事实；logs.attempts 按实际顺序保存每次尝试的控制台原文、traceback 和错误。

#### Execution Model 示例

```json
{
  "workflow_execution_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
  "node_execution_id": "9b1deb4d-3b7d-4bad-9b1d-7c8f2a6e4d11",
  "node_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "SCRIPT",
  "status": "SUCCESS",
  "started_at": "2026-07-24 23:11:50",
  "finished_at": "2026-07-24 23:11:52",
  "duration_ms": 2000,
  "attempt_count": 2,
  "inputs": {
    "review_result": {
      "status": "PASS",
      "reason": "审核通过"
    }
  },
  "outputs": {
    "review_status": "PASS"
  },
  "logs": {
    "truncated": false,
    "captured_bytes": 198,
    "attempts": [
      {
        "attempt": 1,
        "status": "FAILED",
        "console": [
          {
            "sequence": 1,
            "stream": "STDOUT",
            "content": "开始处理审核结果\n"
          },
          {
            "sequence": 2,
            "stream": "STDERR",
            "content": "Traceback (most recent call last):\n  ...\nRuntimeError: 临时执行失败\n"
          }
        ],
        "traceback": "Traceback (most recent call last):\n  ...\nRuntimeError: 临时执行失败\n",
        "error": {
          "code": "SCRIPT_RUNTIME_ERROR",
          "message": "临时执行失败",
          "details": null
        }
      },
      {
        "attempt": 2,
        "status": "SUCCESS",
        "console": [
          {
            "sequence": 1,
            "stream": "STDOUT",
            "content": "审核结果处理完成\n"
          }
        ],
        "traceback": null,
        "error": null
      }
    ]
  },
  "error": null
}
```

#### 参数列表

| 字段          | 类型        | 取值                                                    | 示例                                 | 含义                                    |
| ------------- | ----------- | ------------------------------------------------------- | ------------------------------------ | --------------------------------------- |
| workflow_execution_id | string      | UUIDv4 字符串                                           | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10 | 所属 Workflow Execution ID                    |
| workflow_id           | string      | UUIDv4 字符串                                           | 123e4567-e89b-42d3-a456-426614174000 | 所属 Workflow Structural Model ID       |
| node_execution_id   | string      | UUIDv4 字符串                                           | 9b1deb4d-3b7d-4bad-9b1d-7c8f2a6e4d11 | 本次节点运行记录的唯一标识              |
| node_id       | string      | UUIDv4 字符串                                           | 550e8400-e29b-41d4-a716-446655440000 | Structural Model 节点 ID                |
| type          | string      | SCRIPT                                                  | SCRIPT                               | 节点类型                                |
| status        | string      | PENDING、RUNNING、SUCCESS、FAILED、TIMEOUT、INTERRUPTED | SUCCESS                              | 节点当前或最终状态                      |
| started_at    | string/null | YYYY-MM-DD HH:mm:ss 或 null                             | 2026-07-24 23:11:50                  | 进入 RUNNING 的时间；PENDING 时为 null  |
| finished_at   | string/null | YYYY-MM-DD HH:mm:ss 或 null                             | 2026-07-24 23:11:52                  | 节点最终结束时间；尚未结束时为 null     |
| duration_ms   | int/null    | 大于等于 0 或 null                                      | 2000                                 | 节点总耗时，单位毫秒；尚未结束时为 null |
| attempt_count | int         | 大于等于 0                                              | 2                                    | 实际执行次数；未开始执行时为 0          |
| inputs        | object      | 变量名到 JSON 值的映射                                  | {"review_result":{"status":"PASS"}}  | 最终尝试开始时提供给脚本的完整 Context 快照 |
| outputs       | object      | 变量名到 JSON 值的映射，默认 {}                         | {"review_status":"PASS"}             | 最终成功提交到 Context 的变量           |
| logs          | object      | SCRIPT 专属日志对象                                     | 见上方完整示例                         | 按尝试保存控制台、traceback 和错误       |
| error         | object/null | error 对象或 null                                       | null                                 | 最终执行错误；成功时为 null             |

节点状态统一使用：

```text
PENDING | RUNNING | SUCCESS | FAILED | TIMEOUT | INTERRUPTED
```

#### error 参数

| 字段    | 类型        | 取值                    | 示例                        | 含义                         |
| ------- | ----------- | ----------------------- | --------------------------- | ---------------------------- |
| code    | string      | 稳定错误码              | SCRIPT_RUNTIME_ERROR        | 机器可读错误码               |
| message | string      | 非空字符串              | review_result.status 不存在 | 面向用户的错误说明           |
| details | object/null | 结构化 JSON 对象或 null | null                        | 可选诊断信息；不写入 Context |

标准输出、标准错误、执行日志和重试失败明细不重复写入 NodeRun 最终事实区，在固定 5 MiB 原始日志载荷上限内必须原样持久化到所属 Execution Model JSON；达到上限后按 logs.truncated 规则截断原始文本，最终终态仍按 Execution Model error 规则完整保存结构化错误。

#### logs 参数

| 字段           | 类型    | 取值                          | 示例              | 含义                                      |
| -------------- | ------- | ----------------------------- | ----------------- | ----------------------------------------- |
| truncated      | boolean | true/false                    | false             | 原始日志载荷是否因 5 MiB 上限被截断       |
| captured_bytes | int     | 0~5,242,880                   | 198               | 已保存原始日志字符串的 UTF-8 字节总数     |
| attempts       | array   | 按 attempt 递增的尝试日志数组 | [{"attempt":1}] | 本次节点全部实际尝试日志                  |

#### attempts 参数

| 字段      | 类型        | 取值                                      | 示例    | 含义                                      |
| --------- | ----------- | ----------------------------------------- | ------- | ----------------------------------------- |
| attempt   | int         | 从 1 开始，严格递增                       | 1       | 本次实际尝试序号                          |
| status    | string      | RUNNING、SUCCESS、FAILED、TIMEOUT、INTERRUPTED | FAILED | 本次尝试当前或最终状态                    |
| console   | array       | console item 数组                         | []      | STDOUT/STDERR 按 Worker 接收顺序形成的原文 |
| traceback | string/null | 完整 Python traceback 或 null             | null    | 本次异常堆栈；无 Python traceback 时为 null |
| error     | object/null | 完整 error 对象或 null                    | null    | 本次尝试最终错误；SUCCESS/RUNNING 时为 null |

#### console item 参数

| 字段     | 类型   | 取值          | 示例                 | 含义                                  |
| -------- | ------ | ------------- | -------------------- | ------------------------------------- |
| sequence | int    | 从 1 开始递增 | 1                    | 当前 attempt 内的控制台原文接收顺序   |
| stream   | string | STDOUT、STDERR | STDOUT              | 原文来自标准输出或标准错误            |
| content  | string | 原始文本块    | 审核结果处理完成\n  | Worker 实际收到的内容，不做结构化提取 |

SCRIPT 日志规则：

- 实际尝试开始时立即追加 attempt 并设置 RUNNING；尝试结束后原位更新为 SUCCESS、FAILED、TIMEOUT 或 INTERRUPTED，不删除前序失败尝试。
- console 只按 Worker 实际接收顺序追加，不按换行重新切分，不合并 STDOUT/STDERR，不补换行，也不改写内容。
- 未达到日志上限时，Python traceback 必须完整保留在实际 STDERR console content 中，同时原样复制到 traceback 字段；该重复用于同时满足控制台还原和异常详情展示，并且两份字符串都计入 captured_bytes。
- Python 未捕获异常时 error 使用 SCRIPT_RUNTIME_ERROR；TIMEOUT、INTERRUPTED 或输出采集错误没有 Python traceback 时，traceback 为 null，但 error 必须按对应规则保存。
- 顶层 error 只保存最终终态错误；前序失败尝试即使后续成功，也完整保留在 logs.attempts 中。
- 完整 Workflow Execution 将 logs 持久化到 Execution Model JSON；单节点临时测试只在前端快照中维护同结构 logs，刷新或离开页面即清空。
- SCRIPT 日志界面只展示 `logs.attempts[attempt_count - 1]` 的 console、traceback 和 error；更早的 attempts 仅用于 Execution Model 离线追溯，不进入日志界面。
- 每个 SCRIPT Node Execution 或单节点临时测试的原始日志载荷上限固定为 5,242,880 bytes（5 MiB）。captured_bytes 是所有已保存 console.content 和非 null traceback 按 UTF-8 编码后的字节数之和；attempt/status/error 等结构化字段不计入该载荷预算且必须完整保留。
- 写入某个 console.content 或 traceback 后将超过上限时，只保留当前字符串能够放入剩余预算的最长合法 UTF-8 前缀，设置 truncated=true 和 captured_bytes=5,242,880；后续 console/traceback 原文不再保存。truncated 一旦为 true 不得恢复为 false。
- 日志截断不得终止 Worker、改变 attempt 或 Node Execution 状态、触发重试、修改 error、丢弃 outputs 或阻止 Context 提交。界面必须显示日志已截断，但不得把截断提示伪装成用户 STDOUT/STDERR 内容。

#### Execution Model 规则

- inputs、outputs 和 error 只保存最终执行的结果。
- attempt_count 必须等于 logs.attempts.length；每次尝试明细只保存在 logs.attempts，不重复嵌入顶层最终事实字段。
- duration_ms 记录整个节点执行耗时，包括重试等待时间。
- 脚本异常、超时、中断或输出变量采集失败时，outputs 为 `{}`。
- 脚本进程正常结束后，平台按照 Structural Model outputs 顺序读取每项 source 对应的顶层 Python 变量；缺少任一 source 时本次执行按 `SCRIPT_OUTPUT_MISSING` 失败，待提交 outputs 整体丢弃且不重试。
- 只有最终成功的 outputs 才批量写入 Context。
- 全部重试失败时，Context 保持节点执行前状态。
- Python 运行异常、超时和 Context 读取错误按 execution.max_attempts 重试；`SCRIPT_OUTPUT_MISSING`、`SCRIPT_OUTPUT_TYPE_MISMATCH`、`SCRIPT_OUTPUT_SERIALIZATION_ERROR`、画布全局中断和 Workflow Fail-Fast 不重试。

<a id="chapter-6-3"></a>

### 6.3 Input & Output Protocol

#### 用户代码接口

平台在每次 SCRIPT 尝试开始时向 Python 顶层命名空间提供：

```python
value = context["变量名"]
```

context 是当前 Workflow Context 的隔离只读 Mapping；单节点临时测试时，它来自前端本次测试提供的临时变量池，不读取历史 Execution。

#### context 规则

- 每次实际尝试开始时重新从当时的共享 Context 生成完整严格 JSON 深拷贝；同一 Node Execution 的重试不得复用上一次尝试修改过的 context。
- context 顶层支持 Python `collections.abc.Mapping` 的读取行为，包括 `context[name]`、`context.get(name, default)`、`name in context`、`len(context)`、迭代以及 `keys()`、`values()`、`items()`。
- context 不支持顶层新增、删除或修改；`context[name] = value`、`del context[name]`、`update()`、`pop()`、`clear()` 等写操作必须失败。嵌套 object/array 是隔离深拷贝，脚本可以在本地修改，但不会影响共享 Context 或其他节点。
- 变量名严格区分大小写。`context[name]` 读取不存在的 key 时，本次尝试失败，error.code 使用 `CONTEXT_VARIABLE_NOT_FOUND`；error.details 保存原始 name。用户显式使用 `context.get(name, default)` 时，缺失返回用户提供的 default，不属于平台静默回退。
- 平台不做路径解析、类型转换或来源包装；脚本直接使用标准 Python 对象访问语法处理嵌套值。
- Execution Model inputs 保存最终尝试开始时提供给脚本的完整 context 深拷贝，不尝试通过代理推断脚本实际访问了哪些 key。

```python
review = context["review_result"]
review_status = review["status"]
review_reason = review["reason"]
```

#### 顶层变量采集规则

- 只有脚本正常执行到结束后才开始采集 outputs；Python 未捕获异常、超时或中断时不读取任何 source，outputs 为 `{}`。
- 平台按 outputs 声明顺序从脚本顶层执行命名空间读取 source。source 不存在时使用 `SCRIPT_OUTPUT_MISSING`；error.details 必须包含缺失的 name 和 source。
- source 只按 Python 标识符精确读取并区分大小写，不解析 `a.b`、`items[0]`、函数调用或其他表达式。
- 函数、类、循环或异常处理块中产生的值，只有在脚本结束前赋给顶层 source 变量后才能采集。
- 平台只执行第 3.3 节统一隐式转换矩阵，不调用任意对象的 `str()`、`int()`、`float()` 或真值判断，不执行矩阵之外的隐式兼容。
- source 不能进入目标类型允许的转换路径，或解析后的 JSON 根类型不匹配时，使用 `SCRIPT_OUTPUT_TYPE_MISMATCH`；error.details 必须包含 name、source、源 Python 类型和目标 type。
- source 或转换结果不能严格 JSON 序列化时使用 `SCRIPT_OUTPUT_SERIALIZATION_ERROR`；NaN、Infinity、循环引用、非字符串 dict key、模块、函数、类实例和其他非 JSON 值均拒绝。
- 每项转换成功后立即生成严格 JSON 深拷贝；所有声明项全部转换、序列化和校验成功后才形成待提交 outputs。任一项失败时丢弃整组已采集副本，不产生部分 outputs。
- 多个 outputs 绑定同一个 source 时，为每个 name 分别生成独立 JSON 深拷贝；后续 Context 值之间不得共享可变引用。

SCRIPT source 在进入第 3.3 节统一矩阵前按以下方式映射为 JSON 类型：str 为 string，dict 为 object，list 为 array，非 bool 的 int 为 integer，finite float 为 number，bool 为 boolean，None 为 null。其他 Python 类型不能直接进入隐式转换矩阵；无法严格 JSON 序列化时使用 `SCRIPT_OUTPUT_SERIALIZATION_ERROR`。精确十进制在转换、类型校验和 Execution Model/Context JSON 写入期间都不得先转为 binary float；读取持久化 Context 时必须恢复相同数学值。

#### 提交与日志

- 顶层变量采集只形成本节点待提交 outputs，不立即修改共享 Context。
- 全部 source 采集、受控类型转换和严格 JSON 深拷贝成功后，平台一次性将待提交 outputs 写入 Context。
- 提交前平台必须检查待提交集合中的每个 name 是否已存在于 Context；任一 name 已存在时，整个集合都不写入，节点失败并中断 Workflow Run。
- 脚本异常、超时、被中断或任一校验失败时，待提交集合全部丢弃。
- 完整 Workflow Execution 中，print() 原始内容写入所属 Execution Model JSON 的 SCRIPT 日志区；单节点临时测试中只实时写入前端临时快照。两种场景都不把 print() 内容写入 Context 或 outputs，也不进行字段提取或结构化改写。

#### 用户代码示例

以下示例假设 Structural Model outputs 把 `currtime_1`、`currtime_2` 和 `review_status` 分别绑定到同名顶层 source，且三者 type 均为 string。

```python
import random
import time

time_str = time.strftime("%Y%m%d%H%M%S")
letters = [chr(random.randint(65, 90)) for _ in range(3)]
currtime = time_str + "".join(letters)
currtime_1 = currtime
currtime_2 = currtime

review = context["review_result"]
review_status = review["status"]
```

#### 成功输出示例

```json
{
  "currtime_1": "20260724153022ABC",
  "currtime_2": "20260724153022ABC",
  "review_status": "PASS"
}
```

以上对象是本次 SCRIPT 执行成功后写入 Context 的变量集合，不属于 Structural Model 节点定义。

<a id="chapter-6-4"></a>

### 6.4 用户可见日志

SCRIPT 日志按 PyCharm 控制台习惯展示最终一次 attempt 的 STDOUT、STDERR 和 traceback 原文。界面不得对 print 内容做字段提取、JSON 猜测或错误摘要替换。

| 显示区域 | 字段来源 | 展示规则 |
| --- | --- | --- |
| 列表时间 | started_at | `MM-DD HH:mm:ss` |
| 列表状态 | status | 原样显示终态 |
| 列表耗时 | duration_ms | 毫秒 |
| 最终结果概览 | `logs.attempts[attempt_count - 1].console`；为空时使用 outputs 或 error.message | 按 sequence 还原最终控制台，列表只做视觉折叠 |
| 展开-输入 | inputs | 最终尝试收到的完整只读 Context 快照 |
| 展开-控制台 | 最终 attempt.console | 按 sequence 展示 stream 和未改写 content |
| 展开-traceback | 最终 attempt.traceback | null 时不显示该块；非 null 时完整显示 |
| 展开-输出 | outputs | 成功提交到 Context 的完整 JSON |
| 展开-错误 | error | 顶层最终 code/message/details |
| 展开-日志状态 | logs.truncated、logs.captured_bytes、attempt_count | 明确是否截断及真实尝试次数 |

示例：

```text
07-24 23:11:50  SUCCESS  2000 ms  审核结果处理完成

尝试次数: 2
日志截断: false

控制台
[STDOUT] 审核结果处理完成

输出
{"review_status":"PASS"}

错误
null
```

示例中的第一次失败尝试仍保存在 logs.attempts[0]，但用户可见日志只读取最终的 logs.attempts[1]。复制控制台时只复制 content 原文，不附加界面生成的 `[STDOUT]`、颜色、行号或折叠标记；复制整条日志时字段标签与实际值可以按界面顺序输出，但不得包含前序 attempt。

<a id="chapter-7"></a>

## 7. LLM

<a id="chapter-7-1"></a>

### 7.1 Structural Model

Structural Model 描述 LLM 节点使用的模型引用、有序上下文消息、生成参数、执行约束和原始文本输出声明。不保存 API Key、Base URL、协议、Proxy、SSL、模型默认 Body 或某次运行解析后的消息。

#### Structural Model 示例

```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "type": "LLM",
  "name": "中文合规审核",
  "description": "判断内容是否符合中文要求",
  "model": {
    "provider_id": "provider-deepseek",
    "model_name": "deepseek-v4-pro"
  },
  "context": {
    "messages": [
      {
        "role": "SYSTEM",
        "content": "你是中文合规审核员，只输出审核结论文本。"
      },
      {
        "role": "USER",
        "content": "示例内容：通过审核"
      },
      {
        "role": "ASSISTANT",
        "content": "审核通过"
      },
      {
        "role": "USER",
        "content": "请审核以下内容：${conversation}"
      }
    ]
  },
  "generation": {
    "parameters": {
      "thinking": {
        "type": "disabled"
      },
      "temperature": 0,
      "top_p": 0.8,
      "max_tokens": 1024
    }
  },
  "execution": {
    "timeout_seconds": 600,
    "max_attempts": 2,
    "retry_interval_seconds": 1,
    "delay_seconds": 0
  },
  "outputs": [
    {
      "name": "llm_text",
      "type": "string",
      "source": "response.choices[0].message.content"
    },
    {
      "name": "llm_reasoning",
      "type": "string",
      "source": "response.choices[0].message.reasoning_content"
    }
  ]
}
```

#### 与 Execution Model 的字段边界

| Structural Model           | Execution Model        | 边界                                                       |
| -------------------------- | ---------------------- | ---------------------------------------------------------- |
| id                         | node_id                | Execution Model 只引用节点 ID，不修改 ID                   |
| type                       | type                   | Execution Model 复制 LLM 类型用于识别记录                  |
| name、description          | 无对应业务字段         | 只用于定义态展示，不作为模型输出                           |
| model                      | 实际请求使用的模型信息 | 前者只保存供应商和模型引用，后者记录本次调用实际使用的模型 |
| context.messages           | 实际供应商 request Body | 前者保存有序模板和 Context 引用，后者使用小写角色保存最终发送的消息序列 |
| generation.parameters / parameters_text | 实际供应商 request Body | 前者保存最近一次合法 JSON 对象和编辑器草稿文本；执行前必须得到合法 object，后者保存合并并适配后的实际请求参数 |
| execution                  | attempt_count          | 前者声明超时和重试约束，后者记录实际调用次数               |
| outputs 数组               | 实际类型化输出         | 前者声明多个 name/type/source，后者保存从同一完整 response 提取并原子提交的 Context 值 |

#### 参数列表

| 字段        | 类型   | 取值               | 示例                                                               | 含义                         |
| ----------- | ------ | ------------------ | ------------------------------------------------------------------ | ---------------------------- |
| id          | string | UUIDv4 字符串      | 7c9e6679-7425-40de-944b-e07fc1f90ae7                               | 节点在 Workflow 中的唯一标识 |
| type        | string | LLM                | LLM                                                                | 节点类型                     |
| name        | string | 用户自定义         | 中文合规审核                                                       | 画布和日志中显示的节点名称   |
| description | string | 用户自定义，可为空 | 判断内容是否符合中文要求                                           | 节点业务用途说明             |
| model       | object | 必填               | {"provider_id":"provider-deepseek","model_name":"deepseek-v4-pro"} | 模型引用                     |
| context     | object | 必填               | {"messages":[{"role":"SYSTEM","content":"..."}]}                 | 有序上下文消息定义           |
| generation  | object | 必填               | {"parameters":{"temperature":0}}                                   | 模型生成参数                 |
| execution   | object | 可省略，默认平台策略 | {"timeout_seconds":600,"max_attempts":2,"retry_interval_seconds":1,"delay_seconds":0} | 执行约束；显式字段覆盖同名默认值 |
| outputs     | array  | 可为空，默认 []    | [{"name":"llm_text","type":"string","source":"response.choices[0].message.content"}] | 多个输出变量名称、类型与提取源声明 |

#### model 参数

| 字段        | 类型   | 取值                  | 示例              | 含义           |
| ----------- | ------ | --------------------- | ----------------- | -------------- |
| provider_id | string | 模型管理中的供应商 ID | provider-deepseek | 引用模型供应商 |
| model_name  | string | 供应商已配置模型名    | deepseek-v4-pro   | 引用具体模型   |

LLM 节点不复制模型管理中的 API Key、Base URL、协议、Proxy、SSL、模型默认 Body、上下文窗口或最大输出能力。

模型引用是弱关联：模型管理允许删除供应商、删除模型或修改模型名，不因已有 Workflow 引用而阻止操作。保存 Workflow 和启动 Workflow Run 时不校验 provider_id 与 model_name 当前有效；调度到 LLM 节点时才校验。空引用使用 `LLM_CONFIGURATION_INCOMPLETE`，非空但不存在的引用使用 `LLM_MODEL_NOT_FOUND`，节点从 PENDING 直接进入 FAILED、attempt_count=0 且不重试。平台不使用历史模型配置、同名模型或节点快照回退执行。

LLM NodeRun 准备启动时解析一次当前模型管理配置，并在内存中固定本次 NodeRun 使用的供应商协议、API Key、Base URL、Proxy、SSL、模型默认 Body 和其他模型元数据。后续所有重试都使用同一份内存快照；模型管理在 NodeRun 期间发生的修改只影响之后启动的 NodeRun。该快照不写入 Execution Model，API Key 等敏感配置也不因快照机制新增持久化副本。若模型在 Workflow 运行前置校验通过后、LLM NodeRun 启动前失效，则该 NodeRun 按 `LLM_MODEL_NOT_FOUND` 从 PENDING 直接转为 FAILED，attempt_count 为 0。

#### context 参数

| 字段     | 类型  | 取值                           | 示例                                                     | 含义                 |
| -------- | ----- | ------------------------------ | -------------------------------------------------------- | -------------------- |
| messages | array | 至少两项，默认 SYSTEM、USER    | [{"role":"SYSTEM","content":"你是审核员"}]        | 按发送顺序保存的消息 |

messages 项：

| 字段    | 类型   | 取值                     | 示例       | 含义                                  |
| ------- | ------ | ------------------------ | ---------- | ------------------------------------- |
| role    | string | SYSTEM、USER、ASSISTANT  | ASSISTANT  | 结构定义角色；发送时转换为小写        |
| content | string | 可为空保存               | 审核通过   | 支持 `${变量名}` 的消息内容模板       |

结构序列固定为 `SYSTEM -> USER -> (ASSISTANT -> USER)...`。前两条消息始终存在，后续消息按 ASSISTANT、USER 交替追加；不支持手动换角色或排序。Structural Model 允许消息内容为空，也允许草稿暂时以 ASSISTANT 结束。节点执行预检要求除 SYSTEM 外的所有消息非空且最终一条消息为非空 USER；空 SYSTEM 在最终请求中省略。旧 `prompt.system / prompt.user` 已删除且不提供兼容层。

#### generation 参数

| 字段            | 类型   | 取值             | 示例                                | 含义                           |
| --------------- | ------ | ---------------- | ----------------------------------- | ------------------------------ |
| parameters      | object | 合法 JSON object | {"temperature":0,"max_tokens":1024} | 最近一次合法节点高级参数       |
| parameters_text | string | 可为空保存       | {"temperature":0                   | 高级参数编辑器草稿文本；允许暂存非法 JSON |

parameters 规则：

- 保存 LLM 草稿不要求模型有效、上下文完整或 parameters_text 是合法 JSON；只有运行到节点或单节点临时测试时才要求模型有效、除 SYSTEM 外消息非空、最终消息为 USER 且高级参数草稿可解析为 JSON object。
- parameters 可以包含供应商特有字段，以保持模型兼容性。parameters_text 非空时执行前以 parameters_text 为准解析；为空时使用 parameters。
- generation.parameters 及模型默认 Body 均不解析 Context 引用，也不参与静态 Context 引用扫描；其中形如 `${variable_name}` 的字符串按普通字符串原样参与参数合并。LLM 节点只有 context.messages[].content 支持 Context 引用。
- parameters 顶层不允许包含平台核心字段 `model`、`messages`、`input`、`prompt`、`system`、`stream`；发现顶层保留字段时属于运行前配置错误，不创建真实尝试，也不执行自动重试。
- 保留字段检查不递归进入嵌套 object；工具定义、JSON Schema 或供应商扩展对象内部可以使用同名字段，因为它们不会覆盖平台顶层请求结构。
- 模型管理中的默认 Body 使用相同的顶层保留字段集合；模型配置保存和测试时拒绝顶层保留字段，Workflow 运行前置校验再次检查。默认 Body 只能提供非保留的顶层生成参数。
- 不对白名单之外的参数做强制拒绝。
- response_format 等模型特有参数可以原样填写，但平台不解析结构化结果。
- 请求合并顺序为：平台基础请求 < 模型默认 Body < 节点 parameters；默认 Body 和 parameters 都只能覆盖非保留的生成参数。
- 合并时，双方字段均为 object 才递归合并；array、string、number、integer、boolean 和 null 均由高优先级值整体替换，不执行数组拼接或自动类型转换。
- LLM 节点只支持阻塞调用，不存在流式开关。`stream` 在模型默认 Body 和节点 parameters 中始终属于保留字段，供应商适配器必须使用对应协议的阻塞调用方式，用户不能通过高级参数重新开启流式响应。

#### execution 参数

| 字段                       | 类型   | 取值     | 示例 | 含义                                       |
| -------------------------- | ------ | -------- | ---- | ------------------------------------------ |
| timeout_seconds            | number | >= 0.001 | 600  | 单次阻塞调用总超时，单位秒；默认 600       |
| max_attempts               | int    | 0~10     | 2    | 最大重试次数，不包含首次请求               |
| retry_interval_seconds     | number | 0~600    | 1    | 失败后、下一次重试前的固定间隔，单位秒     |
| delay_seconds              | number | 0~600    | 0    | 首次模型请求开始前只等待一次，单位秒       |

LLM 重试规则：除用户主动取消或 Workflow Fail-Fast 导致的 INTERRUPTED 外，已经开始供应商请求后的模型请求错误、超时、响应解析错误和其他执行错误均允许按 max_attempts 重试。Context 引用解析错误、模型不存在、平台保留参数错误和其他执行前错误不进入重试，按通用执行前错误规则处理。
LLM `timeout_seconds` 从阻塞请求开始持续计算到完整响应接收和供应商协议解析结束，不使用片段空闲超时，也不允许无限总时长。

LLM attempts 历史内容预算按单个 Node Execution 计算，首次调用和全部重试共享固定 5,242,880 bytes（5 MiB）上限，不按 attempt 重新计算。容量省略不得终止供应商调用、改变重试决策、修改 Node Execution 状态，且不得截断或改写顶层最终事实区的 request、response、usage、usage_errors、outputs 或 error。单节点临时测试复用相同预算，但只保存在前端临时快照。

#### outputs 参数

| 字段  | 类型   | 取值                                                       | 示例                                        | 含义                          |
| ----- | ------ | ---------------------------------------------------------- | ------------------------------------------- | ----------------------------- |
| name  | string | 合法变量名，按大小写精确唯一                               | llm_text                                    | 写入 Context 的变量名         |
| type  | string | string、number、integer、boolean、object、array、null       | string                                      | 用户选择的目标输出类型        |
| source| string | 以 `response` 为根的 Python 风格提取表达式                 | response.choices[0].message.content         | 从完整供应商 response 提取值  |

LLM output 不设置 JSON Schema。每项 source 必须以 `response` 为根，支持对象字段访问、数组下标和数组过滤；提取结果再按顶层输出类型约束转换为该项声明的 type。outputs.name 按大小写精确唯一，多个 outputs 可以读取相同 source，source 不要求唯一。

<a id="chapter-7-2"></a>

### 7.2 Execution Model

Execution Model 保存某次 Workflow Run 中 LLM 节点实际发生的阻塞调用事实：实际输入、模型、供应商协议 request Body、供应商完整 response Body、逐次尝试、Token usage 及其结构化问题、状态和错误。它不保存可编辑模板、认证 Header、API Key、Proxy 凭据、独立日志或日志引用；LLM 日志界面只读取顶层最终 request、response 和 error，不展示 attempts 中的前序重试内容。

#### Execution Model 示例

```json
{
  "workflow_execution_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
  "node_execution_id": "5e074085-8d4a-4e0b-8f3c-2a9d6b7c3e33",
  "node_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "type": "LLM",
  "status": "SUCCESS",
  "started_at": "2026-07-25 00:20:10",
  "finished_at": "2026-07-25 00:20:15",
  "duration_ms": 5000,
  "attempt_count": 2,
  "inputs": {
        "conversation": "待审核的原始内容"
      },
  "model": {
        "provider_id": "provider-deepseek",
        "model_name": "deepseek-v4-pro"
      },
  "request": {
        "model": "deepseek-v4-pro",
        "messages": [
          {
            "role": "system",
            "content": "你是中文合规审核员。"
          },
          {
            "role": "user",
            "content": "请审核以下内容：待审核的原始内容"
          }
        ],
        "thinking": {
          "type": "disabled"
        },
        "temperature": 0,
        "top_p": 0.8,
        "max_tokens": 1024
      },
  "response": {
        "id": "chatcmpl-final",
        "object": "chat.completion",
        "created": 1784996415,
        "model": "deepseek-v4-pro",
        "choices": [
          {
            "index": 0,
            "message": {
              "role": "assistant",
              "content": "审核通过",
              "reasoning_content": ""
            },
            "finish_reason": "stop"
          }
        ],
        "usage": {
          "prompt_tokens": 3890,
          "completion_tokens": 245,
          "total_tokens": 4135
        }
      },
  "response_received": true,
  "usage": {
        "input_tokens": 3890,
        "output_tokens": 245,
        "total_tokens": 4135
      },
  "usage_errors": [],
  "attempts": [
        {
          "attempt": 1,
          "status": "FAILED",
          "started_at": "2026-07-25 00:20:10",
          "finished_at": "2026-07-25 00:20:12",
          "duration_ms": 2000,
          "request": {
            "model": "deepseek-v4-pro",
            "messages": [
              {
                "role": "system",
                "content": "你是中文合规审核员。"
              },
              {
                "role": "user",
                "content": "请审核以下内容：待审核的原始内容"
              }
            ],
            "thinking": {
              "type": "disabled"
            },
            "temperature": 0,
            "top_p": 0.8,
            "max_tokens": 1024
          },
          "response": {
            "error": {
              "type": "server_error",
              "message": "temporary unavailable"
            }
          },
          "response_received": true,
          "error": {
            "code": "LLM_RESPONSE_ERROR",
            "message": "供应商暂时不可用",
            "details": null
          },
          "truncated_fields": []
        },
        {
          "attempt": 2,
          "status": "SUCCESS",
          "started_at": "2026-07-25 00:20:13",
          "finished_at": "2026-07-25 00:20:15",
          "duration_ms": 2000,
          "request": {
            "model": "deepseek-v4-pro",
            "messages": [
              {
                "role": "system",
                "content": "你是中文合规审核员。"
              },
              {
                "role": "user",
                "content": "请审核以下内容：待审核的原始内容"
              }
            ],
            "thinking": {
              "type": "disabled"
            },
            "temperature": 0,
            "top_p": 0.8,
            "max_tokens": 1024
          },
          "response": {
            "id": "chatcmpl-final",
            "object": "chat.completion",
            "created": 1784996415,
            "model": "deepseek-v4-pro",
            "choices": [
              {
                "index": 0,
                "message": {
                  "role": "assistant",
                  "content": "审核通过",
                  "reasoning_content": ""
                },
                "finish_reason": "stop"
              }
            ],
            "usage": {
              "prompt_tokens": 3890,
              "completion_tokens": 245,
              "total_tokens": 4135
            }
          },
          "response_received": true,
          "error": null,
          "truncated_fields": []
        }
      ],
  "outputs": {
        "llm_text": "审核通过",
        "llm_reasoning": ""
      },
  "error": null
}
```

#### 参数列表

| 字段          | 类型        | 取值                                                    | 示例                                                               | 含义                                      |
| ------------- | ----------- | ------------------------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------- |
| workflow_execution_id | string      | UUIDv4 字符串                                           | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10                               | 所属 Workflow Execution ID                    |
| workflow_id           | string      | UUIDv4 字符串                                           | 123e4567-e89b-42d3-a456-426614174000                               | 所属 Workflow Structural Model ID         |
| node_execution_id   | string      | UUIDv4 字符串                                           | 5e074085-8d4a-4e0b-8f3c-2a9d6b7c3e33                               | 本次节点运行记录的唯一标识                |
| node_id       | string      | UUIDv4 字符串                                           | 7c9e6679-7425-40de-944b-e07fc1f90ae7                               | Structural Model 节点 ID                  |
| type          | string      | LLM                                                     | LLM                                                                | 节点类型                                  |
| status        | string      | PENDING、RUNNING、SUCCESS、FAILED、TIMEOUT、INTERRUPTED | SUCCESS                                                            | 节点当前或最终状态                        |
| started_at    | string/null | YYYY-MM-DD HH:mm:ss 或 null                             | 2026-07-25 00:20:10                                                | 进入 RUNNING 的时间；PENDING 时为 null    |
| finished_at   | string/null | YYYY-MM-DD HH:mm:ss 或 null                             | 2026-07-25 00:20:15                                                | 节点最终结束时间                          |
| duration_ms   | int/null    | 大于等于 0 或 null                                      | 5000                                                               | 节点总耗时，单位毫秒                      |
| attempt_count | int         | 大于等于 0                                              | 2                                                                  | 实际模型调用次数；未开始调用时为 0        |
| inputs        | object      | 变量名到 JSON 值的映射                                  | {"conversation":"待审核内容"}                                      | 最终调用实际引用的 Context 变量和值       |
| model         | object/null | provider_id/model_name 或 null                          | {"provider_id":"provider-deepseek","model_name":"deepseek-v4-pro"} | 最终调用实际使用的模型；尚未解析时为 null |
| request       | object/null | 供应商协议请求 Body 或 null                            | {"model":"deepseek-v4-pro","messages":[]}                              | 最终尝试实际发送的 JSON Body               |
| response      | JSON value/null | object、array、string、number、integer、boolean、null | {"id":"chatcmpl-final","choices":[]}                            | 最终尝试收到的完整响应 Body；无 Body 时为 null |
| response_received | boolean | true/false                                              | true                                                               | 最终尝试是否实际收到过响应内容             |
| usage         | object/null | usage 对象或 null                                       | {"input_tokens":3890,"output_tokens":245,"total_tokens":4135}      | 首次调用及所有重试调用的聚合 Token 统计   |
| usage_errors  | array       | UsageIssue 数组，无问题时为 []                          | []                                                                 | 所有调用中非法 usage 字段的结构化问题     |
| attempts      | array       | LLM attempt 数组，默认 []                               | [{"attempt":1,"status":"FAILED"}]                              | 全部实际调用的 request、response 和错误事实 |
| outputs       | object      | 变量名到所声明 JSON 类型值的映射，默认 {}               | {"llm_text":"审核通过"}                                            | 成功后提交到 Context 的类型化输出         |
| error         | object/null | error 对象或 null                                       | null                                                               | 最终调用错误；成功时为 null               |

#### request 规则

- request 保存适配器在 Context 解析、模型默认 Body 与节点 parameters 合并、供应商协议转换全部完成后，最终发送给供应商的 JSON Body。
- OpenAI-compatible request 保留实际 `model`、`messages` 及生成参数；Anthropic request 保留实际 `model`、`system`、`messages`、`max_tokens` 及生成参数。平台不把二者转换成统一的 system/user/parameters 快照。
- request 只保存 Body，不保存 URL、HTTP method 或 Header。API Key、Authorization、Proxy 用户名、Proxy 密码及其他认证凭据不得进入 request、attempts 或日志界面。
- 顶层 request 保存最终尝试实际发送的 Body；attempts[].request 保存对应尝试实际发送的 Body。后续重试即使 Body 与前一次完全相同，也按真实事实分别保存并计入 attempts 5 MiB 预算。

#### usage 参数

| 字段          | 类型     | 取值               | 示例 | 含义                            |
| ------------- | -------- | ------------------ | ---- | ------------------------------- |
| input_tokens  | int/null | 大于等于 0 或 null | 3890 | 所有模型调用的输入 Token 累计数 |
| output_tokens | int/null | 大于等于 0 或 null | 245  | 所有模型调用的输出 Token 累计数 |
| total_tokens  | int/null | 大于等于 0 或 null | 4135 | 所有模型调用的 Token 累计总数   |

聚合覆盖所有实际发起的模型调用；成功调用以及最终失败、超时或取消前已经收到的 usage 都参与累计。平台只累加供应商实际返回的 usage 字段；某次调用缺失 usage 时不估算、不补零，其他调用已返回的值仍参与累计，因此结果可能低于真实消耗。供应商返回 total_tokens 时始终信任该值，即使它与 input_tokens + output_tokens 不一致；仅在未返回 total_tokens、但同时返回 input_tokens 和 output_tokens 时，平台才按两者之和推导本次 total_tokens 后参与聚合。所有调用都未返回 usage 时，usage 为 null；某个字段在所有调用中都未返回且无法按上述规则推导时，该字段为 null。

input_tokens、output_tokens 和 total_tokens 只接受大于等于 0 的 integer，boolean、负数、小数、字符串和其他类型均为非法值。平台按字段独立忽略非法值，不执行类型转换；同一 usage 中的其他合法字段继续累计。非法字段按缺失处理，因此 total_tokens 非法但 input_tokens 与 output_tokens 合法时，仍按两者之和推导本次 total_tokens。所有标准字段都缺失或非法时，该次调用不产生 usage；usage 格式错误不改变模型调用的成功或失败结果。每个非法字段都必须生成一个 UsageIssue 写入 usage_errors，不得只写临时警告。

#### usage_errors 参数

| 字段    | 类型       | 取值                                      | 示例                    | 含义                        |
| ------- | ---------- | ----------------------------------------- | ----------------------- | --------------------------- |
| attempt | int        | 大于等于 1                                | 2                       | 发现问题的实际模型调用序号  |
| field   | string     | input_tokens、output_tokens、total_tokens | total_tokens            | 供应商返回的非法 usage 字段 |
| code    | string     | LLM_USAGE_VALUE_INVALID                   | LLM_USAGE_VALUE_INVALID | 非法 usage 值的稳定问题码   |
| value   | JSON value | 供应商原始值                              | "4135"                  | 未经转换的非法字段值        |
| message | string     | 非空字符串                                | 必须是大于等于 0 的整数 | 非法原因                    |

usage_errors 聚合所有实际发起调用中发现的问题，按发现顺序保存；无非法字段时为 `[]`。usage_errors 不改变模型调用的成功、失败、重试或最终 response，不写入 Context；usage 仍按上述规则保留所有合法字段。

#### attempts 参数

| 字段             | 类型            | 取值                                                    | 示例                    | 含义                                      |
| ---------------- | --------------- | ------------------------------------------------------- | ----------------------- | ----------------------------------------- |
| attempt          | int             | 从 1 开始，严格递增                                     | 1                       | 实际模型调用序号                          |
| status           | string          | RUNNING、SUCCESS、FAILED、TIMEOUT、INTERRUPTED          | FAILED                  | 本次调用当前或最终状态                    |
| started_at       | string          | Asia/Shanghai，YYYY-MM-DD HH:mm:ss                      | 2026-07-25 00:20:10     | 本次实际调用开始时间                      |
| finished_at      | string/null     | Asia/Shanghai，YYYY-MM-DD HH:mm:ss 或 null              | 2026-07-25 00:20:12     | 本次调用结束时间；RUNNING 时为 null       |
| duration_ms      | int/null        | 大于等于 0 或 null                                      | 2000                    | 本次调用耗时；RUNNING 时为 null           |
| request          | object/null     | 供应商协议请求 Body 或 null                             | {"model":"deepseek-v4-pro","messages":[]} | 本次实际发送的 Body；未形成或因预算省略时为 null |
| response         | JSON value/null | object、array、string、number、integer、boolean、null   | {"error":"timeout"}   | 本次完整响应 Body；未收到或因预算省略时为 null |
| response_received| boolean         | true/false                                              | true                    | 本次调用是否实际收到过响应内容             |
| error            | object/null     | 完整 error 对象或 null                                  | null                    | 本次调用错误；SUCCESS/RUNNING 时为 null   |
| truncated_fields | array           | `request`、`response` 的无重复字符串数组，默认 []       | ["response"]            | 因 5 MiB 预算未保存的字段                 |

attempts 与标准 JSON 规则：

- 每次供应商调用真正开始时按顺序追加一个 attempt，立即写入 started_at、设置 status=RUNNING，并把 finished_at 和 duration_ms 置为 null；`attempt_count` 必须等于 `attempts.length`，预检失败且未发起调用时 attempts 为 `[]`。
- attempt.status 和 attempt.error 只反映供应商调用、协议读取和响应解析事实，不包含后续 outputs 类型校验或 Context 提交结果。每次调用进入 SUCCESS、FAILED、TIMEOUT 或 INTERRUPTED 时写入 finished_at，并令 duration_ms 等于该 attempt 从 started_at 到供应商调用与协议解析结束的实际耗时。
- attempt duration 不包含调用开始前的资源等待、首次调用前的 `delay_seconds`、两次调用之间的 `retry_interval_seconds`、调用完成后的 outputs 校验或 Context 提交；顶层 duration_ms 包含这些发生在 Node Execution 生命周期内的时间。
- request 使用与顶层 request 相同的供应商协议 JSON Body 结构，不执行跨供应商归一化。
- 平台保存供应商阻塞 HTTP 响应的完整 Body。Body 能够按严格 JSON 完整解析时，response 保存解析后的 JSON value；不能完整解析时保存未经修改的原始 string。不得删除、重命名、提取或重排供应商业务字段；reasoning/thinking、content、usage、finish_reason/stop_reason 和错误对象均保持供应商 Body 原结构。
- 只要收到非零字节 Body，response_received 就为 true，包括 Body 为 JSON null 或空 JSON string `""`；完全没有响应 Body 时 response_received=false 且 response=null。
- “删除转义字符”只表示不把完整 JSON 再嵌套为带 `\"` 的 JSON string。实现必须通过 JSON parser 转换结构，禁止直接删除反斜杠；JSON string 内表示引号、反斜杠、换行和控制字符所必需的转义仍遵循 JSON 标准。
- attempts 中全部 request/response 共享 5,242,880 bytes（5 MiB）预算。预算只计算已保存的非 null request/response 按无额外空白、非 ASCII 字符直接使用 UTF-8 的紧凑 JSON 序列化字节数；attempt、status、error、truncated_fields 和顶层最终事实不计入预算。
- 每个 request/response 作为不可拆分的完整 JSON 字段，按实际产生顺序独立检查剩余预算。字段能够完整放入时原样保存并扣减预算；不能完整放入时保存 null，并把字段名加入当前 attempt.truncated_fields，不得截断字符串、属性、数组元素或生成非法 JSON。被省略字段不消耗预算，后续较小字段仍可在剩余预算内保存。
- truncated_fields 只表示容量截断。response_received=true 且 response=null、truncated_fields 不包含 response 表示供应商实际返回了 JSON null；response_received=false 且 response=null 表示未收到内容；response_received=true、response=null 且 truncated_fields 包含 response 表示实际收到内容但因预算省略。request 使用既有 request/null 与 truncated_fields 组合，不增加 request_received。
- attempts 是离线追溯事实，不进入日志界面。日志界面只展示顶层最终 request、response 和 error；单节点临时测试复用同一结构和预算，但只保存在前端快照。

#### error 参数

| 字段    | 类型        | 取值                    | 示例         | 含义                         |
| ------- | ----------- | ----------------------- | ------------ | ---------------------------- |
| code    | string      | 稳定错误码              | LLM_TIMEOUT  | 机器可读错误码               |
| message | string      | 非空字符串              | LLM 请求超时 | 面向用户的错误说明           |
| details | object/null | 结构化 JSON 对象或 null | null         | 可选诊断信息，不写入 Context |

#### Execution Model 规则

- inputs 只记录 system/user Prompt 实际引用过的 Context 变量。
- request 和 response 都保存供应商协议事实：request 是实际发送的 JSON Body，response 是实际收到的完整 Body。OpenAI-compatible 与 Anthropic 的字段结构允许不同，平台不得为了统一展示而改写供应商原结构。
- response 不生成额外的 json、structured 或 reasoning 字段。reasoning/thinking 已属于供应商 response 的原生字段或 content block，日志界面直接随完整 response 展示。
- 阻塞请求收到完整 Body 后保存 response；JSON Body 解析为标准 JSON value，非 JSON Body 保持原始 string。解析标准 JSON 只消除“整份 JSON 被再次编码为字符串”造成的外层转义，不得破坏 JSON string 内合法且必要的转义字符。
- 返回 Tool Call、Function Call、图片、音频或其他非文本模型内容时，完整供应商 Body 仍必须保存到 response。节点是否支持将其作为 outputs.source 的提取结果，按输出提取契约判断；平台当前不执行 Tool Call 或 Function Call。
- 供应商因最大 Token、长度限制或等价原因结束生成时，节点按 `LLM_OUTPUT_TRUNCATED` 失败；因内容安全策略、审核过滤或等价原因结束时，节点按 `LLM_CONTENT_FILTERED` 失败。供应商适配器负责把协议特有 finish_reason/stop_reason 映射为上述错误。
- 同一响应同时满足多个响应级异常条件时，按以下固定优先级选择唯一根因，不按适配器实现顺序变化：`LLM_RESPONSE_ERROR` > `LLM_UNSUPPORTED_RESPONSE` > `LLM_CONTENT_FILTERED` > `LLM_OUTPUT_TRUNCATED` > `LLM_UNSUPPORTED_FINISH_REASON`。
- LLM_OUTPUT_TRUNCATED 和 LLM_CONTENT_FILTERED 按通用 LLM 重试规则处理。outputs 为 `{}`，但最终尝试收到的完整供应商 Body 仍同时保存到顶层 response 和对应 attempts[].response；attempts 字段受共享 5 MiB 预算约束，顶层 response 不受该预算影响，已收到的 usage 继续参与聚合。
- 供应商返回了完整 Body，但 finish_reason、stop_reason 或等价结束原因无法映射为平台已支持的正常结束、长度限制、内容过滤或非文本响应类型时，节点按 `LLM_UNSUPPORTED_FINISH_REASON` 失败。error.details.finish_reason 保存供应商原始结束原因，完整 Body 仍保存在 response，并按通用 LLM 重试与 usage 聚合规则处理。
- 模型调用失败、超时或中断时，outputs 必须为 `{}`，但顶层 response 仍保存最终尝试实际收到的完整 Body；只有完全未收到响应 Body 时 response_received=false 且 response=null。
- 未声明 outputs 时，模型可以成功执行，但 outputs 为 `{}`，不执行 source 提取，也不写入 Context。
- 声明一个或多个 outputs 时，平台按 Structural Model 数组顺序对最终尝试的同一完整 response 分别执行每项 source。source 零匹配时提取结果为 null；精确一个匹配时结果为该 JSON value；多个匹配时按供应商 response 中的原始顺序组成 array，不自动取第一项。
- source 直接读取到一个 array 是“一个 array 值”，与过滤器产生多个独立匹配不同；前者保持原 array，后者由平台把多个匹配组成新的 array。
- source 提取结果再按顶层输出类型约束尝试隐式转换为 outputs.type。成功后以 outputs.name 写入待提交 outputs；转换失败、精度丢失或产生非有限数时，本次 Node Execution 以 `LLM_OUTPUT_TYPE_MISMATCH` 进入 FAILED，outputs 为 `{}`，Context 不变。
- 所有 outputs 的 source 提取、隐式转换、严格 JSON 深拷贝和 Context key 冲突检查必须全部成功后，才能一次性形成并提交 Execution Model.outputs 与 Context 更新；任一项失败时已经完成的其他项也全部丢弃，不允许部分 outputs。
- source 提取和类型转换发生在供应商调用成功之后，不改变最终 attempt 的 SUCCESS 或 attempt.error=null，也不执行自动重试；顶层和最终 attempt 的 request、response、usage 保持已产生的真实事实。
- 输出提交前必须检查声明的输出 name 是否已存在于 Context；已存在时 outputs 为 {}，节点失败并中断 Workflow Run。
- usage 是从各次供应商完整 response 中提取并归一化后的聚合统计；失败、超时或取消前已收到的 usage 同样计入。usage_errors 同样聚合所有调用中的非法字段问题。供应商原始 usage 仍保留在 response/attempts[].response 中，平台不得因生成聚合 usage 而删除或改写它；不保存另一份逐次归一化 usage 明细。
- attempt_count 记录实际模型调用次数且必须等于 attempts.length；attempts 保存每次实际调用的 request、response 和 error，但不进入日志界面。
- inputs、model、request、response、outputs 和 error 只保留最终调用事实；attempts 保存全部调用，usage 和 usage_errors 分别聚合全部实际模型调用的合法 Token 统计与非法字段问题。
- duration_ms 包含重试等待时间；只有最终成功的 outputs 才更新 Context，全部失败时 Context 保持节点执行前状态。

<a id="chapter-7-3"></a>

### 7.3 Input & Output Protocol

#### Context 输入

以下消息字段支持第三章定义的统一 Context 引用格式：

```text
context.messages[].content
```

规则：

- 只接受精确的 `${variable_name}` 格式；变量名和嵌套路径严格区分大小写。
- 支持对象字段和数组下标访问。
- 变量或嵌套路径不存在时，LLM 节点在模型请求前失败。
- `${ variable_name }`、`{{ variable_name }}`、`{{ ctx.variable_name }}` 和 `{{ context.variable_name }}` 保持普通文本，不作为 Context 引用。
- 每条 content 始终生成 string：string 按原值插入，object 和 array 转换为紧凑 JSON，number/integer、boolean 和 null 转换为 JSON 字面量文本。
- SYSTEM content 可为空；模板为空或解析后只含空白时，该条消息从最终请求中省略。
- 除 SYSTEM 外的任一消息模板为空或只含空白时，节点到达后以 `LLM_CONFIGURATION_INCOMPLETE` 从 PENDING 直接失败。消息模板非空但经 Context 解析后只含空白时，以 `LLM_MESSAGE_EMPTY` 失败，attempt_count=0，不进入自动重试。
- 最终一条消息必须是非空 USER；以 ASSISTANT 结束的草稿在节点到达后以 `LLM_CONFIGURATION_INCOMPLETE` 从 PENDING 直接失败。
- Execution Model inputs 保存全部消息解析时读取的 Context 原始值；request 按供应商协议保存转换为小写角色并注入 Context 后的最终 messages，不额外生成统一的消息字段。

#### 输出协议

LLM 通过 Structural Model.outputs.source 从完整供应商 response 中提取输出：

```text
response.choices[0].message.content
response.content[0].text
response.data[id==3]
```

source 语法：

- 根标识符固定为 `response`，严格区分大小写；不允许使用 request、inputs、Context 变量或任意 Python 表达式作为根。
- `.field` 读取对象字段；`[0]` 读取数组下标；`["field"]` 与 `[field]` 等价，均读取对象字段。字段名和响应 key 严格区分大小写。
- 数组下标使用受限的 Python 整数下标语义：`[0]` 表示第一项，`[-1]` 表示最后一项，`[-2]` 表示倒数第二项。空数组、正下标大于等于数组长度或负下标小于数组长度的相反数时，使用 `LLM_OUTPUT_SOURCE_EVALUATION_ERROR`，不得静默返回 null。
- 下标只接受无空白的十进制 integer，不接受小数、指数、前导 `+`、算术表达式或任意代码；当前不支持 `[1:]`、`[:-1]`、`[::2]` 等 Python 切片。
- 数组过滤器写作 `[field operator literal]`，支持 `<`、`>`、`<=`、`>=`、`==`、`!=` 和 `contain`。过滤器只筛选当前数组元素，不执行赋值、函数调用、算术运算或任意 Python 代码。
- 过滤条件左值是相对于当前数组元素的只读路径，支持对象字段和数组下标组合，例如 `[meta.id==3]`、`[tags[0]=="production"]`。条件路径不写 `response` 根，不允许包含另一个过滤器、通配符、函数或任意表达式。
- literal 只接受严格 JSON scalar：双引号 string、JSON number、true、false 或 null。string 必须使用双引号并按 JSON string 规则转义；不接受单引号字符串、未加引号字符串、object、array、NaN 或 Infinity。
- `==` 和 `!=` 默认按严格 JSON 类型和值比较，不执行隐式转换；integer 与 number 作为统一 JSON 数值域，使用精确数学值比较，因此 `3` 与 `3.0` 相等，但 number/string、boolean/integer 和 null/缺失字段均不相等。
- `<`、`>`、`<=`、`>=` 只允许精确 JSON 数值之间或 string 之间比较。数值使用精确数学值；string 使用未经大小写或 Unicode 归一化的 Unicode code point 字典序。其他类型组合或跨类型排序属于 source 计算错误。
- `contain` 左值为 string 时，右侧 literal 必须为 string，并按区分大小写的连续子串判断；左值为 array 时，判断数组是否包含与 literal 严格 JSON 相等的元素，不执行隐式类型转换。其他左值类型或不兼容 literal 属于 source 计算错误。
- 每个过滤器 `[]` 只允许一个条件。多个条件通过连续过滤表达 AND，例如 `response.data[id>=3][status=="active"]`；后一个过滤器只检查前一个过滤器保留的元素。首期不支持 `&&`、`||`、括号、逗号条件或 OR。
- source 在 Workflow 保存和运行前置校验时必须通过语法检查；供应商 response 的实际字段和数组内容只能在调用结束后检查。

匹配规则：

- 对象字段不存在时该分支为零匹配，最终零匹配时提取结果为 null；数组为空、数组下标越界或对非 array 使用整数下标时不是零匹配，必须使用 `LLM_OUTPUT_SOURCE_EVALUATION_ERROR`。
- 过滤数组时，某个元素不是 object 或缺少当前条件字段，该元素只视为不匹配，不中断其他元素的检查，也不把缺失字段当作 null；全部元素均未匹配时最终结果为 null。
- source 精确匹配一个值时，提取结果保持该 JSON value 的原始类型。
- source 匹配多个值时，按它们在供应商 response 中出现的顺序组成 array；不自动取第一项。
- source 直接读取一个 array 时，该 array 是单个匹配值，不再次包装成二维 array。
- 过滤器或其他路径步骤产生多个匹配分支后，后续 `.field`、对象 key 或数组下标依次应用到每个分支，并按原始分支顺序收集结果。例如 `response.data[id>=3].name` 返回所有匹配元素中存在的 name；某个分支缺少后续对象字段时只跳过该分支，任一分支发生数组下标越界时整项 source 使用 `LLM_OUTPUT_SOURCE_EVALUATION_ERROR`。
- 多个分支分别产生 array 时，每个 array 保持为独立匹配值，不执行一层或递归扁平化。例如两个分支分别得到 `["a","b"]` 与 `["c"]` 时，最终结果是 `[["a","b"],["c"]]`。
- 多匹配结果严格保留供应商 response 中的顺序与重复值，不按 string、number、object、array 或任何 JSON 值自动去重。
- 对非 object 使用字段访问、对非 array 使用数组下标或过滤器、对不支持的类型执行比较/contain，均使用 `LLM_OUTPUT_SOURCE_EVALUATION_ERROR` 使 Node Execution 进入 FAILED。该错误发生在供应商调用成功之后，最终 attempt 保持 SUCCESS 且 attempt.error 为 null；顶层 error 保存提取错误，outputs 为 `{}`，response 原样保留，不执行自动重试。
- 提取结果按顶层输出类型约束尝试隐式转换为 outputs.type；平台不执行 JSON Schema 校验，也不把 source、供应商路径或其他来源元数据写入 Context。

<a id="chapter-7-4"></a>

### 7.4 用户可见日志

LLM 日志展示最终供应商调用的完整 request 和 response，不提取“回答文本”、reasoning 或错误摘要作为另一份日志。reasoning/thinking、Tool Call、usage 和供应商错误对象均保持其在 response 中的原始位置。

| 显示区域 | 字段来源 | 展示规则 |
| --- | --- | --- |
| 列表时间 | started_at | `MM-DD HH:mm:ss` |
| 列表状态 | status | 原样显示终态 |
| 列表耗时 | duration_ms | 毫秒 |
| 最终结果概览 | response_received=true 时 response；否则 error.message | JSON/text 只做单行视觉预览，不改变实际值 |
| 展开-模型 | model | provider_id 和 model_name |
| 展开-输入 | inputs | Prompt 实际引用的 Context 原值 |
| 展开-请求 | request | 最终尝试发送的供应商协议 Body |
| 展开-响应 | response_received、response | 完整供应商 Body；必须区分未收到、JSON null 和 string |
| 展开-Token | usage、usage_errors | 聚合 Token 事实和非法 usage 原值 |
| 展开-输出 | outputs | 成功提交到 Context 的完整 JSON |
| 展开-错误 | error | 顶层最终 code/message/details |
| 展开-尝试次数 | attempt_count | 只显示次数，不展开 attempts |

示例：

```text
07-25 00:20:10  SUCCESS  3200 ms  {"id":"chatcmpl-final","choices":[{"message":{"role":"assistant","content":"审核通过"},"finish_reason":"stop"}]}

模型
{"provider_id":"provider-deepseek","model_name":"deepseek-v4-pro"}

请求
{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"请审核这段内容"}]}

响应
{"id":"chatcmpl-final","choices":[{"message":{"role":"assistant","content":"审核通过"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3890,"completion_tokens":245,"total_tokens":4135}}

Token
{"input_tokens":3890,"output_tokens":245,"total_tokens":4135}

输出
{"llm_text":"审核通过"}

错误
null
```

复制“响应”时必须复制完整 response，而不是列表中的单行概览或 outputs 提取值。attempts 中的前序 request、response 和 error 不显示、不参与复制；即使最终节点因 outputs.source 失败而为 FAILED，已经收到的最终 response 仍必须照常展示。

<a id="chapter-8"></a>

## 8. HTTP

HTTP 节点用于在内网 Workflow 中调用普通 HTTP/HTTPS API。它不是浏览器、API 网关、爬虫或完整 HTTP 调试器；平台只定义业务请求、网络入口、响应、重试和输出变量，Cookie、连接复用、协议协商、默认 Header 与重定向细节交给底层 HTTP 客户端处理。

<a id="chapter-8-1"></a>

### 8.1 Structural Model

#### Structural Model 示例

```json
{
  "id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
  "type": "HTTP",
  "name": "查询 CI 详情",
  "description": "调用内网 CMDB 接口",
  "request": {
    "method": "POST",
    "url": "https://cmdb.internal/api/ci",
    "follow_redirects": true,
    "headers": [
      {
        "key": "Authorization",
        "value": "Bearer ${api_token}"
      }
    ],
    "params": [
      {
        "key": "scope",
        "value": "${scope}"
      }
    ],
    "body": {
      "type": "raw",
      "content": {
        "name": "${ci_name}"
      }
    }
  },
  "network": {
    "proxy": {
      "mode": "DIRECT",
      "url": null,
      "username": null,
      "password": null
    },
    "verify_ssl": true
  },
  "response": {
    "mode": "AUTO",
    "success_statuses": [
      "200-299"
    ]
  },
  "execution": {
    "timeout_seconds": 30,
    "max_attempts": 2,
    "retry_interval_seconds": 1,
    "delay_seconds": 0,
    "retry_non_idempotent": false,
    "retry_statuses": [
      408,
      429,
      500,
      502,
      503,
      504
    ]
  },
  "outputs": [
    {
      "name": "ci_id",
      "type": "string",
      "source": "response.body.id"
    }
  ]
}
```

#### 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | Workflow 内唯一 UUIDv4 |
| type | string | 固定为 HTTP |
| name | string | 节点名称 |
| description | string | 可为空的用途说明 |
| request | object | 请求方法、URL、Header、Query 和 Body |
| network | object | Proxy 与 SSL 验证配置 |
| response | object | 响应表示方式与成功状态码 |
| execution | object | 总超时和重试配置 |
| outputs | array | 0..N 个输出声明 |

#### request

| 字段 | 类型 | 取值 |
| --- | --- | --- |
| method | string | GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS |
| url | string | 默认 `""`；非空时为 http:// 或 https:// URL，支持 Context 引用 |
| follow_redirects | boolean | 是否跟随重定向，默认 true |
| headers | array | `{key,value}` 数组，默认 [] |
| params | array | `{key,value}` 数组，默认 [] |
| body | object | `{type,content}` |

请求规则：

- URL 允许空值作为未完成草稿保存；运行到 HTTP 节点时空 URL 使用 `HTTP_CONFIGURATION_INCOMPLETE`，不发起请求。
- Workflow Studio 的 Endpoint 输入框在失焦时立即对用户输入执行 `trim()`；Workflow 保存序列化必须再次执行 `trim()`；后端 `HttpRequest` 在长度与 URL 格式校验前执行同样的首尾空白清理，以覆盖绕过前端的 API 客户端。三层行为必须幂等且结果一致。
- 自动清理只删除 URL 首尾空白，不修改 URL 中间字符、Context 模板或编码内容；清理后非空 URL 仍不得包含任何内部空白字符。
- headers 和 params 使用数组，允许重复 key 并保留用户配置顺序。
- Header key 不支持 Context 引用；Header value 必须是 string，支持 Context 引用。Header 名非法或 value 包含 CR/LF 时拒绝保存或运行。
- 用户可以配置业务所需的任意 Header。平台只禁止手动配置 Content-Length、Transfer-Encoding 和请求 Content-Encoding，因为三者必须与真正发送的 Body 一致。
- Content-Length、连接复用、Cookie、Host、User-Agent、Accept-Encoding、HTTP 协议版本和其他客户端默认行为不进入 Structural Model 专属规则，交给底层 HTTP 客户端处理。
- params value 允许 string、number、integer、boolean 或 null；object 和 array 不允许。发送前统一转换为 Query 字符串。
- body.type 支持 none、raw、form_data、form_urlencoded。GET/HEAD 只允许 none。
- raw content 可以是任意 JSON 值；object/array 中的字符串递归解析 Context 引用。form_data 和 form_urlencoded 使用 key/value 数组。
- 前端回读 Query/Form 时必须同时保留后端原始 JSON value 和用户可见文本；value 未编辑时重新保存必须恢复原 number/boolean/null/object/array 类型，不得因为文本输入控件而自动改成 string。用户实际修改 value 后按当前文本值保存。
- `success_statuses / retry_non_idempotent / retry_statuses` 即使暂未提供可见编辑控件，也必须进入 Canvas 会话模型并在打开、保存、单节点测试和完整运行之间原样传递，不得用平台默认值覆盖已有非默认配置。
- HTTP 节点暂不支持文件上传。需要上传文件时使用 SCRIPT 节点。
- 最终编码后的请求 Body 上限为 10 MiB；超限时不发送请求，使用 HTTP_REQUEST_TOO_LARGE。
- HTTP 客户端最终生成的 URL、Header 和 Body 才是 Execution Model 中的请求事实。

#### network

| 字段 | 类型 | 取值 |
| --- | --- | --- |
| proxy.mode | string | SYSTEM、DIRECT、CUSTOM |
| proxy.url | string/null | CUSTOM 时必填的 http:// 或 https:// Proxy URL |
| proxy.username | string/null | CUSTOM Proxy 用户名 |
| proxy.password | string/null | CUSTOM Proxy 密码 |
| verify_ssl | boolean | 是否验证目标服务和 HTTPS Proxy 的证书 |

网络规则：

- SYSTEM 使用运行进程的系统代理环境；DIRECT 禁用系统代理；CUSTOM 只使用显式 proxy.url。
- 平台不根据公网、内网 IP 或失败结果自动切换 Proxy 模式。
- DIRECT/SYSTEM 下 proxy.url、username、password 为 null；CUSTOM 不自动回退其他模式。
- verify_ssl 与 Proxy 模式独立。关闭时允许访问使用自签名证书的内网服务，界面显示非阻断安全提示。
- Proxy 凭据允许本机明文保存，并会进入 Execution Model 的 network；当前快速迭代阶段不做凭据管理或脱敏。

#### response

| 字段 | 类型 | 取值 |
| --- | --- | --- |
| mode | string | AUTO、JSON、TEXT、BINARY，默认 AUTO |
| success_statuses | array | 默认 ["200-299"] |

响应规则：

- success_statuses 接受 100..599 integer 或 `NNN-NNN` 闭区间；最终状态码命中时才执行输出提取。
- AUTO 按严格 JSON、文本、Base64 二进制的顺序选择表示。
- JSON 保存解析后的 JSON 值；TEXT 保存解码文本；BINARY 保存无前缀 Base64 string。
- JSON/TEXT 显式模式解析失败时使用 HTTP_RESPONSE_PARSE_ERROR；AUTO 会继续尝试下一种表示。
- 解压后的最终响应 Body 上限为 10 MiB。超限时使用 HTTP_RESPONSE_TOO_LARGE，不保存截断 Body。
- response.headers 使用有序 `{key,value}` 数组保存客户端返回的 Header。平台不为 Header 构建浏览器级分类、Cookie jar 或跨域安全策略。
- 重定向由底层 HTTP 客户端执行；Execution Model 只记录客户端报告的实际重定向链、最终请求和最终响应。

#### execution

| 字段 | 类型 | 取值 |
| --- | --- | --- |
| timeout_seconds | number | >= 0.001；单次尝试的唯一总超时，单位秒 |
| max_attempts | int | 0..10；最大重试次数，不含首次请求 |
| retry_interval_seconds | number | 0..600；重试间隔，单位秒 |
| delay_seconds | number | 0..600；首次请求前只等待一次，单位秒 |
| retry_non_idempotent | boolean | 是否允许 POST/PATCH 重试，默认 false |
| retry_statuses | array | 默认 [408,429,500,502,503,504] |

执行规则：

- `timeout_seconds` 覆盖一次尝试从请求准备到响应解析和输出提取的完整过程，不设置连接、读取或写入阶段超时。
- GET、HEAD、OPTIONS、PUT、DELETE 遇到 DNS、Proxy、TLS、TCP、总超时或 retry_statuses 状态码时可以重试。
- POST/PATCH 只有 retry_non_idempotent=true 时使用相同重试规则；平台不自动生成 Idempotency-Key。
- retry_statuses 与 success_statuses 同时命中时，success_statuses 优先。
- 响应只有一个合法 Retry-After 时优先使用；缺失、无效或重复时使用 `retry_interval_seconds`。
- 重试等待计入 Node Execution duration_ms，但不计入任一次 attempt.duration_ms。
- 配置错误、响应过大、响应解析错误和输出处理错误不重试。

#### outputs

每项输出包含 name、type、source：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| name | string | 写入 Context 的变量名，在节点内唯一 |
| type | string | string、number、integer、boolean、object、array、null |
| source | string | 以 request 或 response 为根的提取表达式 |

source 复用第 7.3 节已经定义的 Python 风格字段、下标、过滤和比较语法。所有输出先完成提取与第 3.3 节隐式类型转换，再一次性提交 Context；任一项失败时 outputs 为 `{}`，不部分提交。

<a id="chapter-8-2"></a>

### 8.2 Execution Model

Execution Model 保存一次 HTTP Node Execution 的客观事实。它记录实际 Context 输入、网络配置、最终请求、重定向、最终响应、每次尝试、输出和错误；不保存独立日志文件。日志界面只展示顶层最终 request、redirects、response、error、状态和耗时，前序尝试只用于历史追溯。

#### Execution Model 示例

```json
{
  "workflow_execution_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
  "node_execution_id": "3c363836-2f4a-4b6f-9f4c-1e7a8d5b2c22",
  "node_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
  "type": "HTTP",
  "status": "SUCCESS",
  "started_at": "2026-07-26 10:00:00",
  "finished_at": "2026-07-26 10:00:01",
  "duration_ms": 1000,
  "attempt_count": 1,
  "inputs": {
    "api_token": "demo-token",
    "scope": "ALL",
    "ci_name": "switch-01"
  },
  "network": {
    "proxy": {
      "mode": "DIRECT",
      "url": null,
      "username": null,
      "password": null
    },
    "verify_ssl": true
  },
  "request": {
    "method": "POST",
    "url": "https://cmdb.internal/api/ci?scope=ALL",
    "headers": [
      {
        "key": "authorization",
        "value": "Bearer demo-token"
      },
      {
        "key": "content-type",
        "value": "application/json"
      }
    ],
    "body_type": "raw",
    "body": {
      "name": "switch-01"
    }
  },
  "redirects": [],
  "response": {
    "status_code": 200,
    "headers": [
      {
        "key": "content-type",
        "value": "application/json"
      }
    ],
    "body_type": "JSON",
    "body": {
      "id": "ci-001"
    }
  },
  "attempts": [
    {
      "attempt": 1,
      "status": "SUCCESS",
      "started_at": "2026-07-26 10:00:00",
      "finished_at": "2026-07-26 10:00:01",
      "duration_ms": 1000,
      "request": {
        "method": "POST",
        "url": "https://cmdb.internal/api/ci?scope=ALL",
        "headers": [
          {
            "key": "authorization",
            "value": "Bearer demo-token"
          },
          {
            "key": "content-type",
            "value": "application/json"
          }
        ],
        "body_type": "raw",
        "body": {
          "name": "switch-01"
        }
      },
      "redirects": [],
      "response": {
        "status_code": 200,
        "headers": [
          {
            "key": "content-type",
            "value": "application/json"
          }
        ],
        "body_type": "JSON",
        "body": {
          "id": "ci-001"
        }
      },
      "error": null
    }
  ],
  "outputs": {
    "ci_id": "ci-001"
  },
  "error": null
}
```

#### 字段边界

- inputs 只保存本节点实际引用的 Context 根变量和值。
- network 保存本次最终尝试实际使用的 Proxy 与 SSL 配置。
- request 保存底层客户端最终形成的请求；headers 是实际请求 Header 数组，body 保存 Context 解析后的业务值。
- redirects 按客户端报告顺序保存每一跳的 request 和 response；没有重定向时为 []。
- response 保存最终 status_code、headers、body_type 和 body；请求发出后未收到响应时为 null。
- attempts 按真实顺序保存全部尝试；attempt_count 必须等于 attempts.length。每项包含 attempt、status、时间、duration_ms、request、redirects、response 和 error。
- 顶层 network、request、redirects、response 和 error 只保存最终尝试事实。前序尝试不得进入日志展示。
- outputs 只保存最终成功并已原子提交 Context 的值；失败、超时或中断时为 `{}`。
- 请求、响应与错误均直接保存在 Execution Model JSON，日志不得另建结构或对内容做二次结构化提取。

#### 请求与响应

request：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| method | string | 实际方法 |
| url | string | 实际完整 URL |
| headers | array | 实际 `{key,value}` Header |
| body_type | string | none、raw、form_data、form_urlencoded |
| body | JSON value | Context 解析后的业务 Body；none 时为 null |

response：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| status_code | int | 最终状态码 |
| headers | array | 实际 `{key,value}` Header |
| body_type | string/null | JSON、TEXT、BINARY 或 null |
| body | JSON value | 解析后的 JSON、文本、Base64 或 null |

底层客户端可能规范化 Header 大小写、顺序或自动加入默认 Header；Execution Model 记录客户端实际报告的结果，不尝试还原不可见的 Wire 字节。用户根据日志中显示的实际 request/response 结构编写 outputs.source。

#### 错误与重试事实

网络错误使用以下稳定错误码，并在 error.details 中保存 stage、exception_type 和底层 raw_error：

| error.code | stage |
| --- | --- |
| HTTP_DNS_ERROR | DNS |
| HTTP_PROXY_ERROR | PROXY |
| HTTP_TLS_ERROR | TLS |
| HTTP_CONNECTION_ERROR | TCP |

其他 HTTP 错误继续使用错误目录中的稳定错误码。error.message 是面向用户的概述，raw_error 是排障所需的底层原文；日志同时展示二者。

每次真正开始请求时追加一个 attempt。配置或 Context 预检失败时 attempt_count=0、attempts=[]；重试等待期间取消不会预先创建下一次 attempt。最终成功时 status=SUCCESS；请求失败、响应或输出处理失败时 status=FAILED；总超时为 TIMEOUT；全局中断为 INTERRUPTED。

<a id="chapter-8-3"></a>

### 8.3 Input & Output Protocol

以下字段支持 `${variable_name}` 及第三章定义的嵌套 Context 引用：

```text
request.url
request.headers[].value
request.params[].value
request.body.content
```

规则：

- Context 名称和路径严格区分大小写。
- 完整字段只有一个引用时保留原始 JSON 类型；嵌入普通文本时转换为文本。
- Header value 最终必须是 string；Query 最终必须是标量；Body 可以保留任意 JSON 类型。
- 缺失变量或路径在请求发出前失败。
- request.headers[].key、request.params[].key 和 Body object key 不执行模板替换。

outputs.source 的根对象固定为：

```json
{
  "request": {
    "method": "POST",
    "url": "https://cmdb.internal/api/ci",
    "headers": [],
    "body_type": "raw",
    "body": {
      "name": "switch-01"
    }
  },
  "response": {
    "status_code": 200,
    "headers": [],
    "body_type": "JSON",
    "body": {
      "id": "ci-001"
    }
  }
}
```

常用示例：

| source | 值 |
| --- | --- |
| request.url | 实际 URL |
| request.body.name | 实际请求 Body 中的 name |
| response.status_code | 最终状态码 |
| response.headers | 完整响应 Header 数组 |
| response.body | 完整响应 Body |
| response.body.id | JSON Body 中的 id |

HTTP outputs.source 使用与 LLM 相同的受限 Python 整数下标语义：支持正负整数下标，不支持切片或表达式；空数组、正负下标越界以及对非 array 使用整数下标均属于提取表达式错误。对象字段或过滤器零匹配仍得到 null，多匹配得到保持顺序和重复值的 array。提取表达式错误使用 HTTP_OUTPUT_SOURCE_EVALUATION_ERROR；隐式类型转换失败使用 HTTP_OUTPUT_TYPE_MISMATCH。两者都保留最终 request/response、使 outputs 整体不提交且不自动重试。

<a id="chapter-8-4"></a>

### 8.4 用户可见日志

HTTP 日志展示底层客户端报告的最终实际请求、重定向链、最终响应和底层错误。界面不得根据 Content-Type 重新构造另一份响应，也不得隐藏失败状态响应的 Body。

| 显示区域 | 字段来源 | 展示规则 |
| --- | --- | --- |
| 列表时间 | started_at | `MM-DD HH:mm:ss` |
| 列表状态 | status | 原样显示终态 |
| 列表耗时 | duration_ms | 毫秒 |
| 最终结果概览 | response 非 null 时 response.body；否则 error.message | JSON/text/Base64 只做视觉预览 |
| 展开-输入 | inputs | 请求实际引用的 Context 原值 |
| 展开-网络 | network | 实际 Proxy 模式、地址、凭据和 verify_ssl；不脱敏 |
| 展开-请求 | request | 直接将 Node Execution Model 顶层 request 按 JSON 格式化展示并复制，完整保留最终尝试的实际 method、url、headers、body_type、body；不得重构成 HTTP/1.1 文本或从 Structural Model 补值 |
| 展开-重定向 | redirects | 客户端报告的实际重定向链；空数组显示“无” |
| 展开-响应 | response | 最终 status_code、headers、body_type、body |
| 展开-输出 | outputs | 成功提交到 Context 的完整 JSON |
| 展开-错误 | error | 顶层最终 code/message/details；网络错误同时展示 raw_error |
| 展开-尝试次数 | attempt_count | 只显示次数，不展开 attempts |

示例：

```text
07-26 10:00:00  SUCCESS  1000 ms  {"id":"ci-001"}

网络
{"proxy":{"mode":"DIRECT","url":null,"username":null,"password":null},"verify_ssl":true}

请求
{"method":"POST","url":"https://cmdb.internal/api/ci?scope=ALL","headers":[{"key":"authorization","value":"Bearer demo-token"},{"key":"content-type","value":"application/json"}],"body_type":"raw","body":{"name":"switch-01"}}

重定向
[]

响应
{"status_code":200,"headers":[{"key":"content-type","value":"application/json"}],"body_type":"JSON","body":{"id":"ci-001"}}

输出
{"ci_id":"ci-001"}

错误
null
```

请求和响应的 Header 顺序、大小写与默认字段以 Execution Model 中客户端实际报告的值为准。失败状态码已经形成 response 时，日志必须同时展示 response 和 HTTP_STATUS_ERROR；网络失败没有 response 时，必须展示 error.details 中的 stage、exception_type 和 raw_error。前序 attempts 不展示、不参与复制。

<a id="chapter-9"></a>

## 9. END

<a id="chapter-9-1"></a>

### 9.1 Structural Model

END 是每个 Workflow 必须且只能存在一个的系统终点节点。它不承担用户代码、网络调用、Context 读取、输出聚合、重试或超时逻辑；它既是图合法性终点，也是 Workflow SUCCESS 的唯一判定标志。

#### Structural Model 示例

```json
{
  "id": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "type": "END",
  "name": "结束",
  "description": "工作流终点"
}
```

#### 参数列表

| 字段        | 类型   | 取值               | 示例                                 | 含义                             |
| ----------- | ------ | ------------------ | ------------------------------------ | -------------------------------- |
| id          | string | UUIDv4 字符串      | 0f8fad5b-d9cb-469f-a165-70867728950e | END 节点在 Workflow 内的唯一标识 |
| type        | string | END                | END                                  | 系统终点节点类型                 |
| name        | string | 用户自定义         | 结束                                 | 画布和日志展示名称               |
| description | string | 用户自定义，可为空 | 工作流终点                           | 节点业务用途说明                 |

END 不声明 inputs、outputs、execution、重试、超时或其他执行配置；当前阶段不得向 END 增加 Context 读取、变量映射或 Workflow 结果字段。

<a id="chapter-9-2"></a>

### 9.2 Execution Model

END 只在全部直接上游 SUCCESS、实际被 DAG 调度时创建一个空 Node Execution，inputs 和 outputs 都是 `{}`，不产生 Context commit。该 Execution 从 PENDING 进入 RUNNING 并立即进入 SUCCESS；END SUCCESS 后 Workflow Execution 才能进入 SUCCESS。

<a id="chapter-9-3"></a>

### 9.3 Input & Output Protocol

END 不读取 Context，不声明 outputs，也不写入 Context。它只参与保存/运行前的图结构校验并提供空 SUCCESS Node Execution 作为 Workflow 成功标志；Workflow 最终业务数据保存在 workflow.json 的 `context.final`，不得把 END 隐式解释为结果聚合节点。

<a id="chapter-9-4"></a>

### 9.4 用户可见日志

END 的空 Node Execution 是真实执行事实，不是前端伪造状态。用户可见日志行显示实际时间、SUCCESS 和耗时；展开后只显示空 inputs、空 outputs 和最小 transitions，不显示 request、response、console 或 error。

示例：

```text
07-26 10:00:03  SUCCESS  0 ms

inputs
{}

outputs
{}
```

保存或执行时发现 END 不可达、存在非法出边或其他图结构问题，错误属于 Workflow 图校验结果，不得写入 END 节点日志。

<a id="chapter-10"></a>

## 10. Workflow 结构与调度约束

<a id="chapter-10-1"></a>

### 10.1 图结构约束

- Workflow 必须配置恰好一个 START 系统节点；当前阶段 START 仅用于变量输入，用户在节点中逐项填写 name、type 和 value，START 成功后将这些变量一次性写入当前 Context。
- START 缺失或存在多个 START 时，Workflow 校验失败，不允许保存或运行。
- START 必须是入口节点，不允许存在入边；任何指向 START 的连线都会使 Workflow 校验失败。
- Workflow 必须配置恰好一个 END 节点；END 缺失或存在多个 END 时，Workflow 校验失败，不允许保存或运行。
- END 必须是终点节点，不允许存在出边；任何从 END 发出的连线都会使 Workflow 校验失败。
- 每个 Node 都必须从 START 可达并能够到达 END；存在绕过 START 的根、未连接 END 的叶、游离节点或独立子图时，Workflow 校验失败。
- END 创建空 Node Execution 并立即 SUCCESS；Workflow SUCCESS 只由 END SUCCESS 判定。
- Workflow 图必须是一个弱连通 DAG，不允许空 Workflow、自环、重复 Edge 或有向环，也不存在无 START/END 的单节点 Workflow 特例。
- Workflow 至少必须包含一个 SCRIPT、HTTP、LLM 或后续 AGENT 业务节点；只有 START/END 或完全空的 Workflow 校验失败。
- 当前 START 不定义外部字段映射，也不承担外部任务下发协议；后续外部任务入口能力另行定义。
- START 配置校验失败时不创建 Workflow Execution；START 在 Execution 中发生错误时不启动业务节点，并按 Fail-Fast 规则终止 Workflow Execution。
- START 会创建自己的 NodeRun 和 Execution Model 记录，type 为 START；inputs 保存用户输入的 key/value，outputs 保存成功提交到 Context 的变量，完整契约见第五章。
- START 不执行自动重试；任意输入解析、类型校验、key 冲突或提交错误都会立即使 START 失败并触发 Fail-Fast。

<a id="chapter-10-2"></a>

### 10.2 调度资格与并行规则

- 普通节点只有在所有入边上游节点均为 SUCCESS，且该节点已声明或可静态识别的 Context 引用变量均已存在时，才具备运行资格。
- 调度器每轮必须把全部具备运行资格的节点同时纳入调度，不设置 Workflow 级并发上限，也不按画布位置、节点类型、创建顺序或节点 ID 强制串行。所有就绪节点在同一调度轮次创建 PENDING NodeRun；实际进入 RUNNING 的先后取决于执行资源，彼此之间未通过有向边声明的相对执行顺序不保证稳定。
- 节点的静态 Context 引用必须由 START 输入或存在有向路径可达当前节点的上游节点 outputs 声明；引用自身输出、下游输出、其他无路径子图输出或不存在的变量时，Workflow 校验失败。静态引用本身不替代显式连线。
- 静态引用包含嵌套字段或数组下标时，Workflow 校验根变量存在，并要求根变量声明类型为 object 或 array；由于当前不定义完整 Schema，更深层路径只在运行时校验。
- 所有业务节点都必须等待必选 START SUCCESS，并继续满足各自全部直接上游 SUCCESS 后才可运行。
- SCRIPT 不声明静态输入变量，也不扫描 Python 源码推断 Context 依赖；调度资格只由有向边和其他可静态识别的节点引用决定。SCRIPT 实际运行时通过 context Mapping 读取变量，`context[name]` 缺失时按 SCRIPT context 规则失败。
- 上游节点成功但下游所需的静态 Context 变量不存在时，调度器为下游创建 FAILED NodeRun，error.code 使用 `CONTEXT_VARIABLE_NOT_FOUND`，不启动节点进程，并触发 Fail-Fast。

<a id="chapter-10-3"></a>

### 10.3 校验时机

- 用户显式保存 Workflow 时严格校验图结构、字段类型和已经填写的配置格式；SCRIPT 空代码、LLM 空模型/用户提示词、HTTP 空请求 URL 或 CUSTOM Proxy URL 均允许保存。
- 启动 Workflow Run 前只再次校验完整图结构，不扫描全部业务节点配置。调度到具体业务节点时才校验该节点运行必需配置；缺失时创建真实 FAILED NodeRun。
- 编辑过程中只显示提示，不阻断节点或连线编辑。
- 静态 Context 引用不替代显式有向边，边负责声明执行依赖，Context 负责传递数据。

<a id="chapter-10-4"></a>

### 10.4 错误阶段与 NodeRun 结果

| 阶段                      | 发生时机                                             | NodeRun/Workflow 记录                                                            | 重试       |
| ------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------- | ---------- |
| Structural Model 格式校验 | 保存 Workflow 或节点配置时                           | 图结构、类型或非空配置格式错误时拒绝保存；缺少业务运行配置不阻断保存              | 不重试     |
| Workflow 图运行前置校验   | 启动 Run、创建 NodeRun 前                            | 图结构错误时不创建 Workflow Run 或 NodeRun；不预检全部业务节点配置                | 不重试     |
| 执行前动态错误            | Run 已创建、NodeRun 已创建，但进程或外部调用尚未开始 | 缺少当前节点运行配置时从 PENDING 转 FAILED，attempt_count=0、started_at=null，记录友好 error | 不重试     |
| 执行中错误                | 脚本进程、HTTP 完整尝试或 LLM 供应商请求已经开始     | NodeRun 保持 RUNNING，按节点 execution 策略计数和重试；耗尽后进入 FAILED/TIMEOUT | 按节点策略 |

典型执行前动态错误包括 SCRIPT 空代码、LLM 未选择模型或未填写用户提示词、模型引用失效、HTTP 未填写 URL、CUSTOM Proxy 未填写 URL，以及 Context 根变量或嵌套路径存在性预检失败。供应商在请求已经发送后返回的参数拒绝属于执行中错误；平台在保存阶段发现的非空格式错误不属于可重试错误。

<a id="chapter-11"></a>

## 11. 执行、重试、超时与取消约束

<a id="chapter-11-1"></a>

### 11.1 通用执行状态

- Workflow 采用 Fail-Fast 策略：任一节点最终失败后，Workflow Run 立即停止，不再调度其他尚未开始的节点。
- 节点重试期间的中间失败不触发 Workflow 停止；只有重试耗尽后的最终失败、超时或输出提交冲突才触发 Fail-Fast。
- NodeRun 在首次 `delay_seconds` 等待期间保持 PENDING；首次实际尝试开始时进入 RUNNING，并在后续调用和 `retry_interval_seconds`/Retry-After 等待期间保持 RUNNING，不回退为 PENDING；只有最终成功、失败、超时或取消时才进入对应终态。
- 节点存在多次尝试时，最终成功则 NodeRun 为 SUCCESS；全部尝试失败时，以最后一次尝试或其后置处理的结果确定终态，最后结果为超时则使用 TIMEOUT，其他错误使用 FAILED。更早尝试发生过超时不会覆盖最后结果。
- Fail-Fast 触发后，立即中断所有正在运行的其他节点，并把已创建但仍为 PENDING 的 NodeRun 终结为 INTERRUPTED；两类节点的待提交输出全部丢弃。
- 每个 Workflow Run 使用同一终态协调锁串行决定 SUCCESS、FAILED、TIMEOUT、INTERRUPTED 以及 Fail-Fast/用户取消登记的先后，最先完成登记的终态生效。节点成功事务先完成时，该节点保持 SUCCESS 且已提交输出保留；失败或超时先登记时保留 FAILED/TIMEOUT；用户取消或 Fail-Fast 先登记时，尚未成功终结的 PENDING/RUNNING NodeRun 使用 INTERRUPTED。任何后到事件都不得覆盖已登记终态。
- Fail-Fast 后尚未创建 Node Execution 的节点保持无执行文件，并在 workflow.json.nodes 中记录 `NOT_STARTED + WORKFLOW_FAILED`；已经创建但尚未成功终结的 PENDING/RUNNING Node Execution 转为 `INTERRUPTED + WORKFLOW_ABORTED`，并引用触发 Fail-Fast 的 node_execution_id。
- 当前 NodeRun 不定义 SKIPPED 状态；后续实现条件分支时再重新引入。
- 节点通过运行前置校验后即创建 NodeRun，初始状态为 PENDING，此时 started_at、finished_at 和 duration_ms 均为 null；执行进程启动后更新为 RUNNING 并写入 started_at，PENDING 等待时间不计入 duration_ms。
- NodeRun 创建后、执行进程或外部调用启动前发现运行时错误时，可以从 PENDING 直接转为 FAILED；此时 attempt_count 为 0、started_at 和 duration_ms 为 null，并记录 finished_at 与非空 error。嵌套 Context 路径不存在属于该类错误。
- Fail-Fast 发生时，PENDING 和 RUNNING NodeRun 都转换为 INTERRUPTED；PENDING NodeRun 不启动执行，也不增加 attempt_count。
- Node Execution 进入 INTERRUPTED 时 error 必须非空。用户通过画布全局中断停止 Workflow 时记录用户中断原因；其他节点最终失败触发 Fail-Fast 而中断当前节点时使用 `WORKFLOW_ABORTED`，并记录触发 Fail-Fast 的 Node Execution ID。
- 所有 NodeRun 统一遵循状态与 error 不变量：PENDING、RUNNING、SUCCESS 时 error 必须为 null；FAILED、TIMEOUT、INTERRUPTED 时 error 必须为非空 error 对象。重试期间 NodeRun 保持 RUNNING，中间尝试错误不提前写入 Execution Model.error；完整过程写入所属 Execution Model JSON 的持久化原始日志与状态轨迹。
- 完整 Workflow Execution 中，SCRIPT、HTTP 和 LLM 的持久化逐次尝试日志必须按时间顺序记录每次实际尝试的开始、结束、结果和错误；HTTP 还必须记录每次实际发生的重定向请求与响应。中间尝试日志不会因后续重试成功而删除。单节点临时测试复用对应结构，但只保存在前端快照。
- SCRIPT、HTTP 和 LLM 每次失败尝试的 Node Execution Model 必须包含可诊断的原始执行内容；存在异常堆栈时应保存异常堆栈。这些内容写入所属 Node Execution Model 的节点专属事实字段，不写入 Execution Model.error.details，也不得被日志界面的结构化摘要替代；SCRIPT 原始日志及异常堆栈受第 6 章固定 5 MiB 载荷上限约束，达到上限后按 logs.truncated 规则截断，结构化 error 不得截断。
- 用户取消或 Fail-Fast 的原因仅记录在对应 NodeRun.error；取消不需要生成额外的逐次尝试持久化记录。

<a id="chapter-11-2"></a>

### 11.2 INTERRUPTED error.details

INTERRUPTED NodeRun 的 error 结构沿用各节点 Execution Model 的通用 error 字段。用户通过画布全局中断停止 Workflow 时 details 为 null；Fail-Fast 中断时 details 结构如下：

| 字段                | 类型   | 取值          | 示例                                 | 含义                             |
| ------------------- | ------ | ------------- | ------------------------------------ | -------------------------------- |
| trigger_node_execution_id | string | UUIDv4 字符串 | 5e074085-8d4a-4e0b-8f3c-2a9d6b7c3e33 | 触发 Fail-Fast 的失败 NodeRun ID |

<a id="chapter-11-3"></a>

### 11.3 重试与超时

- SCRIPT、HTTP 和 LLM 默认使用 `timeout_seconds=600`、`max_attempts=0`、`retry_interval_seconds=0`、`delay_seconds=0`；`execution` 可整体省略，也可只显式提交需要覆盖的字段。
- `timeout_seconds` 对每次实际尝试分别计时，每次重试重新开始；首次延迟和重试等待不计入单次超时，但计入 NodeRun.duration_ms。
- attempt_count 只在实际执行开始时增加；预检、资源等待、首次 `delay_seconds`、`retry_interval_seconds`、Retry-After 和尚未开始的重试不增加计数。
- 各节点允许重试的错误范围和 HTTP 方法/retry_non_idempotent 限制分别以对应节点章节为准。

<a id="chapter-11-4"></a>

### 11.4 用户取消

- 用户取消 Workflow 时，RUNNING NodeRun 立即中断，PENDING NodeRun 直接转为 INTERRUPTED，尚未创建的节点不补建 NodeRun。
- 完整 Workflow Execution 中禁止用户单独中断 PENDING 或 RUNNING NodeRun；前端不得提供该操作，后端不得把节点级中断请求转换成全局中断。用户主动停止 Workflow 的唯一入口是画布全局中断。
- 单节点临时测试不属于 Workflow Execution，但同样不提供用户中断入口；关闭编辑器、删除节点或 Workflow、离开 Studio 时只允许系统内部取消 Worker，并清理前端临时快照，不创建或修改 Node Execution。
- 对已终态 Workflow Run 或 NodeRun 重复取消是幂等 no-op，不改写历史字段。
- 取消与成功、失败、超时通过同一终态协调锁竞争，最先登记的终态生效。

<a id="chapter-12"></a>

## 12. 错误与数据完整性约束

<a id="chapter-12-1"></a>

### 12.1 总原则

所有数据处理必须遵循“错误显式化、拒绝静默污染”。节点和 Workflow 只有在契约规定的全部校验、解析、执行、输出提取、类型验证和 Context 提交完成后才能成功。

| 维度       | 工业级要求                                                                           | 禁止行为                                                        |
| :--------- | :----------------------------------------------------------------------------------- | :-------------------------------------------------------------- |
| 数据纯净度 | Context 只接收成功终态事务一次性提交的严格 JSON 值                                   | 部分写入、失败写入、覆盖旧值、NaN/Infinity、共享可变引用        |
| 类型一致性 | Structural Model 声明类型、Execution Model 实际类型与 Context 值严格一致             | 隐式字符串化、布尔值冒充整数、失败后写入 null、猜测响应类型     |
| 下游灵活性 | 通过统一 Context 引用以及 SCRIPT/LLM/HTTP outputs.source 支持组合 | 把来源信息包进变量、丢失供应商原始响应、隐式切换到 response.body |

<a id="chapter-12-2"></a>

### 12.2 显式错误

- 图结构和非空值格式错误在保存阶段显式返回；SCRIPT、LLM、HTTP 缺少运行必需配置时允许保存。调度到该节点后创建真实 Node Execution，并以 PENDING -> FAILED、attempt_count=0 记录友好配置错误，不发起 Worker、HTTP 或模型请求且不重试。
- Workflow Structural Model 保存错误与 Execution error.code 分层处理。名称唯一性冲突使用领域错误 `WorkflowNameConflictError`，API 返回 HTTP `409` 和“Workflow 名称已存在，请使用其他名称”；不得把 SQLite 异常、表名、列名或约束原文直接展示给用户。其他结构校验错误继续使用 HTTP `400` 及其面向用户的结构说明。
- 运行时错误必须写入稳定 error.code、非空 message 和约定的 details；不得只记录日志后继续成功。
- 缺失变量、嵌套路径缺失、类型不匹配、响应解析失败、协议不支持、输出缺失和 Context 冲突都必须失败，不得回退为猜测值。
- 多个错误同时发生时，使用各章节定义的优先级；未定义优先级时，以终态协调锁最先登记的错误为准，不拼接或覆盖根因。

#### 通用错误码

| error.code                  | 使用场景                                                |
| --------------------------- | ------------------------------------------------------- |
| WORKFLOW_CONFIG_INVALID     | Workflow 或节点 Structural Model 字段、类型或结构不合法 |
| WORKFLOW_GRAPH_INVALID      | 节点、Edge、循环、可达性或 START/END 图约束不合法       |
| USER_INTERRUPTED            | 用户通过画布全局中断 Workflow Execution                 |
| PROCESS_RESTARTED           | 服务进程重启时收敛遗留的 PENDING/RUNNING Workflow Execution |
| CONTEXT_VARIABLE_NOT_FOUND  | Context 根变量或嵌套路径不存在                          |
| CONTEXT_KEY_EXISTS          | Context 输出 key 已存在，原子提交被拒绝                 |
| NODE_CANCELLED_BY_USER      | 用户通过画布全局中断停止 Workflow，NodeRun 因此进入 INTERRUPTED |
| WORKFLOW_ABORTED            | Node Execution 因其他节点失败触发全局 Fail-Fast 而进入 INTERRUPTED |
| RUNTIME_LOST                | 服务重启后收敛无终态的 Node Execution 为 FAILED         |

#### START 错误码

| error.code            | 使用场景                                                        |
| --------------------- | --------------------------------------------------------------- |
| START_INPUT_INVALID   | START Structural Model 的 name/type/value 保存或启动前校验失败时不创建 Execution；START 临时测试输入校验失败时只形成前端 FAILED 快照，attempt_count=0，不创建 Node Execution |
| START_EXECUTION_ERROR | START 执行前动态错误无法归入通用 Context 错误码时的兜底码       |

#### SCRIPT 错误码

| error.code                        | 使用场景                               |
| --------------------------------- | -------------------------------------- |
| SCRIPT_RUNTIME_ERROR              | Python 未捕获异常                      |
| SCRIPT_CONFIGURATION_INCOMPLETE   | 未填写可执行 Python 代码；PENDING 直接转 FAILED，attempt_count=0 |
| SCRIPT_TIMEOUT                    | 最后一次脚本尝试超时                   |
| SCRIPT_OUTPUT_TYPE_MISMATCH       | outputs.source 顶层变量值无法按第 3.3 节统一矩阵转换为 outputs.type，或转换后的 JSON 根类型不符 |
| SCRIPT_OUTPUT_SERIALIZATION_ERROR | outputs.source 顶层变量值不能严格 JSON 序列化 |
| SCRIPT_OUTPUT_MISSING             | 脚本正常结束后找不到 outputs.source 指定的顶层变量 |
| SCRIPT_EXECUTION_ERROR            | 无法归入上述具体错误码的 SCRIPT 兜底码 |

#### LLM 错误码

| error.code                    | 使用场景                                                                |
| ----------------------------- | ----------------------------------------------------------------------- |
| LLM_MODEL_NOT_FOUND           | 模型供应商或模型引用失效                                                |
| LLM_CONFIGURATION_INCOMPLETE  | 未选择供应商/模型、非 SYSTEM 消息为空或上下文未以 USER 结束；PENDING 直接转 FAILED，attempt_count=0 |
| LLM_TIMEOUT                   | 最后一次模型调用超时                                                    |
| LLM_REQUEST_ERROR             | 已发送的供应商请求失败                                                  |
| LLM_RESPONSE_ERROR            | 供应商响应协议解析失败                                                  |
| LLM_MESSAGE_EMPTY             | 非空消息模板经 Context 解析后只含空白，未发起模型请求                  |
| LLM_UNSUPPORTED_RESPONSE      | 响应包含 Tool Call 或其他不支持的非文本内容                             |
| LLM_OUTPUT_TRUNCATED          | 供应商因长度或 Token 上限结束生成                                       |
| LLM_CONTENT_FILTERED          | 供应商因内容安全策略结束生成                                            |
| LLM_UNSUPPORTED_FINISH_REASON | 无法映射供应商结束原因                                                  |
| LLM_OUTPUT_SOURCE_EVALUATION_ERROR | outputs.source 对实际 response 使用了不兼容的字段、下标、过滤器或运算符 |
| LLM_OUTPUT_TYPE_MISMATCH      | 模型调用成功，但 outputs.source 提取值无法按统一矩阵转换为 outputs.type |
| LLM_USAGE_VALUE_INVALID       | usage_errors[].code；供应商 usage 字段不是大于等于 0 的 integer，非致命 |
| LLM_EXECUTION_ERROR           | 无法归入上述具体错误码的 LLM 兜底码                                     |

#### HTTP 错误码

| error.code                           | 使用场景                                     |
| ------------------------------------ | -------------------------------------------- |
| HTTP_DNS_ERROR                       | 目标服务域名解析失败                         |
| HTTP_CONFIGURATION_INCOMPLETE        | 未填写请求 URL 或 CUSTOM Proxy URL；PENDING 直接转 FAILED，attempt_count=0 |
| HTTP_PROXY_ERROR                     | Proxy 解析、连接、认证或隧道建立失败         |
| HTTP_TLS_ERROR                       | 目标服务或 HTTPS Proxy 的 TLS/证书失败       |
| HTTP_CONNECTION_ERROR                | TCP 或无法进一步归类的传输连接失败           |
| HTTP_TIMEOUT                         | 最后一次 HTTP 完整尝试超时                   |
| HTTP_STATUS_ERROR                    | 最终 HTTP 状态码不属于 response.success_statuses |
| HTTP_RESPONSE_TOO_LARGE              | 解压后的最终响应 Body 超过 10 MiB            |
| HTTP_REQUEST_TOO_LARGE               | 最终编码后的请求 Body 超过 10 MiB，未发送请求 |
| HTTP_RESPONSE_PARSE_ERROR            | 显式 JSON/TEXT 响应无法按所选模式解析        |
| HTTP_OUTPUT_SOURCE_EVALUATION_ERROR  | outputs.source 对实际 request/response 使用了不兼容的字段、下标、过滤器或运算符 |
| HTTP_OUTPUT_TYPE_MISMATCH            | outputs.source 提取值无法按统一矩阵转换为 outputs.type |
| HTTP_EXECUTION_ERROR                 | 无法归入上述具体错误码的 HTTP 兜底码         |

错误码使用规则：优先使用具体错误码；只有确实不存在对应具体码时才使用所属节点的 `*_EXECUTION_ERROR`。实现不得创建未列入本目录的临时错误码；新增错误码必须先更新本规范。

三类 `*_CONFIGURATION_INCOMPLETE` 以及 `LLM_MODEL_NOT_FOUND` 的 `error.details` 统一包含 `missing_fields` 数组和面向用户的 `suggestion`；`error.message` 必须直接指出节点名称和缺失配置。日志界面和临时测试快照展示该友好 message，不直接显示 Pydantic loc 或 ValidationError 原文。

<a id="chapter-12-3"></a>

### 12.3 原子提交与不可回滚事实

- 输出校验、Context 原子提交、Execution Model 最终事实写入和 NodeRun SUCCESS 必须构成不可分割的终态事务。
- 任一输出失败时整组 outputs 为 {}，不得部分提交。
- Workflow 后续 FAILED 或 INTERRUPTED 不回滚此前 SUCCESS NodeRun 及其 outputs；完整 Context 在 Run 结束后统一丢弃。
- Execution Model 终态记录冻结后不可修改；日志只是 Execution Model 的只读展示投影，不得成为独立或替代性的事实来源。

<a id="chapter-12-4"></a>

### 12.4 日志与敏感数据

- 日志无独立持久化结构、文件或数据库；每类节点的 Execution Model 必须保存该节点日志界面所需的事实字段，界面只能按节点日志规则读取并格式化这些字段。
- 日志界面只展示 Node Execution Model 的最终事实：顶层最终 request、response、error、状态与耗时，以及最终一次尝试对应的节点专属原文。前序重试内容虽然保存在 Execution Model 中，但不得进入日志展示、日志复制内容或日志概览。
- SCRIPT、HTTP、LLM 每次尝试必须记录开始、结束、结果和错误；HTTP 还记录每次重定向。
- 标准输出、标准错误、失败堆栈和中间过程原文必须写入所属 Node Execution Model 的节点专属字段，不写入 Context，也不以结构化提取结果替代原始内容。Execution Model.error.details 只保存结构化诊断；INTERRUPTED 同时在 Node Execution Model.error 中保留取消原因。
- 当前契约不定义 log_ref。HTTP 敏感 Header、Proxy 用户名和密码按既定规则明文保存和展示；实现不得声称已脱敏。
- 日志告警不能替代结构化失败。只有明确规定为非致命的数据（例如非法 LLM usage 单字段）才允许继续执行，并必须写入结构化 usage_errors，不能只记录警告。
