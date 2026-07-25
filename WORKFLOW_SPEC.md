<a id="workflow-spec"></a>

# Workflow Engine Specification

本文档是 Agent Bench v2 工作流引擎的唯一事实来源，面向 Workflow 设计、执行器实现、运行记录、前端配置和 Codex 检索。任何 Workflow 结构、节点字段、状态机、Context 引用、输入输出协议、重试、取消、错误或数据完整性变更，都必须先更新本文档。

核心原则：**错误显式化、拒绝静默污染**。任何配置错误、类型不一致、引用缺失、解析失败、输出不完整或协议异常都必须产生明确错误，不得通过隐式转换、默认回退、部分提交或丢弃异常数据伪装成功。

## 目录

1. [文档简要说明](#chapter-1)
2. [Design-Time & Run-Time](#chapter-2) ([Workflow / Edge Design-Time](#chapter-2-3))
3. [Context](#chapter-3)
4. [Node Status](#chapter-4)
5. [START](#chapter-5) ([Design-Time](#chapter-5-1) / [Run-Time](#chapter-5-2) / [Input & Output Protocol](#chapter-5-3))
6. [SCRIPT](#chapter-6) ([Design-Time](#chapter-6-1) / [Run-Time](#chapter-6-2) / [Input & Output Protocol](#chapter-6-3))
7. [LLM](#chapter-7) ([Design-Time](#chapter-7-1) / [Run-Time](#chapter-7-2) / [Input & Output Protocol](#chapter-7-3))
8. [HTTP](#chapter-8) ([Design-Time](#chapter-8-1) / [Run-Time](#chapter-8-2) / [Input & Output Protocol](#chapter-8-3))
9. [END](#chapter-9) ([Design-Time](#chapter-9-1) / [Run-Time](#chapter-9-2) / [Input & Output Protocol](#chapter-9-3))
10. [Workflow 结构与调度约束](#chapter-10) ([图结构](#chapter-10-1) / [调度](#chapter-10-2) / [错误阶段](#chapter-10-4))
11. [执行、重试、超时与取消约束](#chapter-11) ([执行状态](#chapter-11-1) / [重试与超时](#chapter-11-3) / [取消](#chapter-11-4))
12. [错误与数据完整性约束](#chapter-12) ([显式错误](#chapter-12-2) / [原子提交](#chapter-12-3) / [日志](#chapter-12-4))

<a id="chapter-1"></a>

## 1. 文档简要说明

<a id="chapter-1-1"></a>

### 1.1 业务目标

本规范用于保证企业 Agent 工作流在多节点串行、并行、重试、取消和异常场景下仍具有可解释、可追踪、可复现的数据行为。实现者不得把未定义行为解释为自动兼容，也不得为了“继续运行”而污染 Context 或伪造成功状态。

<a id="chapter-1-2"></a>

### 1.2 适用范围

当前规范覆盖 START、SCRIPT、LLM、HTTP 和 END，以及 Workflow Run、NodeRun、Context、DAG 调度、重试、超时、取消、日志和错误边界。AGENT 节点与 START 的外部任务入口能力暂未定义，后续业务确认后再加入。

<a id="chapter-1-3"></a>

### 1.3 编写与检索约定

- 每个一级章节使用固定 HTML 锚点 `chapter-N`，节点子章节使用 `chapter-N-M`；章节改名时不得修改既有锚点。
- 每个参数列表必须完整列出当前层级保存的全部字段，不得只列主要字段。
- string、int、boolean 等简单字段直接在当前层级参数表说明。
- object、array 或具有独立校验规则的复杂字段，在当前层级参数表中保留字段入口，并在后续单独列出全部子字段。
- Design-Time 和 Run-Time 都采用“完整示例在前，参数列表和规则在后”的顺序。
- Design-Time 和 Run-Time 参数表统一使用“字段、类型、取值、示例、含义”五列。
- 规范未明确允许的类型转换、字段回退、默认值、覆盖、跳过或部分提交一律禁止。

<a id="chapter-2"></a>

## 2. Design-Time & Run-Time

<a id="chapter-2-1"></a>

### 2.1 概要与定义

Design-Time 定义 Workflow 和节点以后应当如何执行，是用户可编辑、跨多个 Run 长期存在的配置。Run-Time 记录某次 Workflow Run 中实际发生的事实，是执行过程中形成、终态后不可编辑的历史记录。

<a id="chapter-2-2"></a>

### 2.2 职责与边界

Design-Time 和 Run-Time 是两个独立的数据层，不允许把配置声明与执行事实混合保存。

| 维度       | Design-Time                                        | Run-Time                                               |
| ---------- | -------------------------------------------------- | ------------------------------------------------------ |
| 目标       | 定义节点以后应当如何执行                           | 记录节点某一次实际上如何执行                           |
| 创建时机   | 用户创建或编辑节点时                               | Workflow Run 调度到该节点时                            |
| 生命周期   | 跨多个 Workflow Run 长期存在                       | 只属于一个 Workflow Run                                |
| 可变性     | 用户显式保存后可以更新                             | 执行过程中追加状态，结束后作为历史记录不可编辑         |
| 数量关系   | Workflow 中每个节点一份定义                        | 一个 Design-Time 节点可以产生多个 NodeRun              |
| 重试关系   | execution 声明允许如何重试                         | attempt_count 记录实际执行次数；逐次尝试细节只保留在临时日志 |
| 输入       | 保存模板、常量和 Context 引用，不保存本轮实际值    | inputs 保存最终执行实际读取的 Context 变量和值         |
| 输出       | outputs 声明节点成功时必须产生的变量及其类型或提取路径 | outputs 保存本次成功后实际提交到 Context 的变量名和值  |
| 请求       | 保存尚未解析的 URL、Header、Params、Body 或 Prompt | 保存 Context 解析后实际使用的请求内容                  |
| 响应       | 不保存响应                                         | 保存本次实际收到的响应                                 |
| 状态与时间 | 不保存运行状态、开始时间、结束时间或耗时           | 保存 status、started_at、finished_at、duration_ms      |
| 日志与错误 | 不保存日志、错误或堆栈                             | NodeRun.error 保存最终错误；完整日志和逐次尝试细节临时保存 |
| Context    | 不保存某次 Run 的 Context                          | 只保存 inputs/outputs 快照；Context 本体仍是独立变量池 |

强制边界规则：

- 保存 Workflow 或节点配置时，只更新 Design-Time，不创建或修改 Run-Time。
- 用户显式保存 Workflow 时执行完整结构和配置校验，校验失败则禁止保存；启动 Workflow Run 前再次执行同一套完整校验，失败则不创建 Workflow Run 或 NodeRun。编辑过程中只显示提示，不阻断节点或连线编辑。
- 启动节点时，执行器读取该次执行使用的 Design-Time 配置；运行中产生的数据只能写入 Run-Time、日志或待提交输出。
- 节点运行期间修改 Design-Time，不得改变已经开始的 NodeRun 或其中后续重试使用的配置。
- 历史 NodeRun 不因 Design-Time 后续修改而重写。
- Design-Time outputs 是声明数组；Run-Time outputs 是实际值对象，两者名称相同但结构和职责不同。
- Run-Time inputs 和 outputs 只是最终执行的快照，不是 Context 的另一份主存储。
- Run-Time 不允许反向修改节点名称、脚本源码、HTTP 请求模板、重试配置或输出声明。
- Context 只接受最终成功执行一次性提交的 Run-Time outputs；失败执行不得修改 Context。
- Context key 冲突属于节点执行失败；并行节点发生冲突时，先完成原子提交的节点保留输出，后提交节点失败，Workflow Run 中断。
- Workflow Run 后续进入 FAILED 或 CANCELLED 时，不回滚此前已经完成成功事务的 NodeRun、Run-Time outputs 或 Context 写入，也不把 SUCCESS 节点改为 CANCELLED。已提交 Context 值只保留到本次 Run 结束并随完整 Context 一起丢弃；历史 NodeRun 的 SUCCESS 和 outputs 继续持久化用于追溯。
- 所有时间数值字段统一使用整数毫秒，字段名使用 _ms 后缀。
- 当前处于快速迭代阶段，Workflow 执行可用性和终态正确性优先于快照和日志保留。完整运行日志、失败堆栈和逐次尝试细节只属于执行期间的临时观测数据，不定义持久化证据结构；观测数据记录失败不得阻塞节点执行、终态判定或 Context 提交。
- Run-Time 的 started_at 和 finished_at 统一使用 Asia/Shanghai 时区和 YYYY-MM-DD HH:mm:ss 格式，例如 2026-07-24 23:11:50；字符串不附加时区后缀。
- 所有耗时统计字段统一使用整数毫秒，字段名使用 _ms 后缀，例如 duration_ms。
- SCRIPT、HTTP 和 LLM 的 timeout_ms、max_attempts、delay_ms 都必须由用户在节点 Design-Time 中显式填写，不提供契约默认值。timeout_ms 对每次执行尝试分别计时，每次重试重新开始计时；NodeRun.duration_ms 包含全部尝试和重试等待时间。
- SCRIPT、HTTP 和 LLM 的 NodeRun 只保存最终尝试事实，不嵌入逐次尝试记录；每次尝试和 HTTP 中间重定向过程只进入当前 Run 的临时日志。

NodeRun 从创建开始始终使用所属节点 Run-Time 参数表定义的完整字段结构，不按状态省略字段。尚未产生的 object 值使用 `{}`，array 值使用 `[]`，允许为空的标量或尚未解析的复杂事实使用 null。运行期间只有 status、started_at、finished_at、duration_ms 和 attempt_count 等生命周期字段可以实时更新；inputs、network/model、request、redirects、response、usage、usage_errors、outputs 和 error 等最终事实字段在节点进入终态时一次性写入。重试的完整过程只进入临时日志。典型占位规则如下：

- 所有节点在 PENDING 时 attempt_count 为 0，started_at、finished_at、duration_ms 和 error 为 null，inputs 与 outputs 为 `{}`。
- HTTP 在实际网络配置尚未解析时 network 为 null，请求尚未形成时 request 为 null，无重定向时 redirects 为 `[]`，响应尚未收到时 response 为 null。
- LLM 在模型配置尚未解析时 model 为 null，请求尚未形成时 request 为 null，最终文本尚未形成时 response 为 null，尚未收到 usage 时 usage 为 null，usage_errors 为 `[]`。
- NodeRun 处于 PENDING 或 RUNNING 时，上述最终事实字段保持占位值，不展示或覆盖为中间尝试数据。进入 SUCCESS、FAILED、TIMEOUT 或 CANCELLED 时，执行器原子写入最终事实字段并冻结完整记录；只有 status、error 以及各节点规则共同决定最终结果。

attempt_count 只在一次执行真正启动时增加：SCRIPT 子进程成功启动、HTTP 完整尝试进入实际执行、LLM 供应商请求开始发送时分别计为一次。创建 NodeRun、执行预检、等待执行资源、等待 delay_ms/Retry-After 或计划下一次重试都不增加 attempt_count；在重试等待期间取消时保留已经实际启动的次数，不预先计入尚未开始的下一次尝试。

NodeRun 本体不混入 Design-Time 字段。Workflow Run 通过 workflow_id 关联其启动时的 Workflow；当前阶段不保存不可变 Workflow 快照或节点定义快照，因此历史 Run 不保证能够还原已修改或删除的节点配置。完整快照、失败尝试摘要和持久化日志将在后续迭代另行定义，不得作为当前执行、终态判定或 Context 提交的前置条件。

契约管理的身份字段 `workflow_id`、`id`、`run_id`、`node_run_id`、`node_id` 和 `edge_id` 统一使用 UUIDv4 字符串。HTTP 响应 Body、Context 业务对象和模型管理中的外部标识不受本规则约束。

<a id="chapter-2-3"></a>

### 2.3 Workflow 与 Edge Design-Time

Workflow Design-Time 是一份可持久化的 DAG 定义。nodes 保存完整节点 Design-Time，edges 只表达调度依赖，不携带变量、条件、映射或运行数据。

#### Workflow Design-Time 示例

```json
{
  "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
  "name": "审核并汇总",
  "description": "输入内容后执行脚本汇总",
  "nodes": [
    {
      "id": "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44",
      "type": "START",
      "name": "输入内容",
      "description": "提供初始内容",
      "inputs": [
        {
          "name": "conversation",
          "type": "string",
          "data": "请审核这段内容"
        }
      ]
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "type": "SCRIPT",
      "name": "汇总结果",
      "description": "输出原始内容",
      "script": "value = get_val(\"conversation\")\nset_val(\"result\", value)",
      "execution": {
        "timeout_ms": 120000,
        "max_attempts": 0,
        "delay_ms": 0
      },
      "outputs": [
        {
          "name": "result",
          "type": "string"
        }
      ]
    },
    {
      "id": "0f8fad5b-d9cb-469f-a165-70867728950e",
      "type": "END",
      "name": "结束",
      "description": "工作流终点"
    }
  ],
  "edges": [
    {
      "edge_id": "4c1f2e3d-6b7a-48c9-9d01-23456789abcd",
      "source": "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44",
      "target": "550e8400-e29b-41d4-a716-446655440000"
    },
    {
      "edge_id": "5d2e3f4a-7b8c-49d0-a123-456789abcdef",
      "source": "550e8400-e29b-41d4-a716-446655440000",
      "target": "0f8fad5b-d9cb-469f-a165-70867728950e"
    }
  ]
}
```

#### Workflow 参数列表

| 字段 | 类型 | 取值 | 示例 | 含义 |
| --- | --- | --- | --- | --- |
| workflow_id | string | UUIDv4 字符串 | 123e4567-e89b-42d3-a456-426614174000 | Workflow Design-Time 的唯一标识 |
| name | string | 非空用户自定义文本 | 审核并汇总 | Workflow 展示名称 |
| description | string | 用户自定义，可为空 | 输入内容后执行脚本汇总 | Workflow 业务用途说明 |
| nodes | array | 至少一个业务节点的完整节点定义 | 见上方完整示例 | 画布节点集合 |
| edges | array | 可为空的 Edge 定义数组 | 见上方完整示例 | 有向调度依赖集合 |

#### Edge 参数

| 字段 | 类型 | 取值 | 示例 | 含义 |
| --- | --- | --- | --- | --- |
| edge_id | string | UUIDv4 字符串 | 4c1f2e3d-6b7a-48c9-9d01-23456789abcd | Edge 在 Workflow 内的唯一标识 |
| source | string | nodes[].id 中存在的 UUIDv4 | 2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44 | 上游节点 ID |
| target | string | nodes[].id 中存在的 UUIDv4 | 550e8400-e29b-41d4-a716-446655440000 | 下游节点 ID |

Workflow 参数与 Edge 规则：

- workflow_id、nodes[].id 和 edges[].edge_id 在各自作用域内必须唯一；nodes[].id 统一遵循本规范的 UUIDv4 规则。
- source 和 target 必须引用同一 Workflow 中存在的不同节点；自环和重复的 source/target 有向边属于配置错误。
- edges 不定义端口、Handle、变量映射、条件表达式或运行数据；节点间数据只通过第三章 Context 传递。
- 节点类型只能是 START、SCRIPT、LLM、HTTP 或 END；各节点的完整字段分别由第五至第九章定义。

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
- Workflow Run 结束后丢弃完整 Context，不持久化 Context 本体；仅保留各节点 Run-Time 中的 inputs/outputs 快照。Context 不作为 Design-Time 定义的一部分。
- 节点只能读取当前 Context，不能直接读取其他 Run 的 Context。

<a id="chapter-3-3"></a>

### 3.3 读写规则

- 节点通过统一的输入协议读取 Context 变量。
- 节点成功后才可以把输出变量提交到 Context。
- 节点执行期间产生的中间值属于节点本地状态，不直接修改共享 Context。
- 节点提交输出前，必须在 Context 中检查所有待提交 key；只要任一 key 已存在，整个节点提交失败，不允许覆盖已有值。
- START inputs.name 与所有业务节点 outputs.name 在整个 Workflow 范围内必须全局唯一；发现重复变量名时，Workflow 保存和运行前置校验失败。运行时 Context key 冲突检查仍作为并发与数据完整性的最终防线。
- START inputs.name 与所有节点 outputs.name 输入时必须符合 `[A-Za-z_][A-Za-z0-9_]*`；保存 Design-Time 时统一转换为小写，Context 和 Run-Time inputs/outputs 只使用转换后的规范名。
- Context 根变量名不区分大小写；Workflow 校验、Context 引用、SCRIPT get_val/set_val 和提交冲突检查都先转换为小写。`result`、`Result` 和 `RESULT` 视为同一变量，不能重复声明。
- Context 引用保存时只将根变量标识符转换为小写，保留用户选择的 `ctx` 或 `context` 前缀。嵌套 JSON 对象字段不是 Context 变量名，不转换大小写并继续按 JSON 规则区分大小写。
- 输出提交必须是原子操作；检查与写入必须在同一个 Context 提交事务中完成。同一节点不得部分写入，提交失败时所有待提交输出都丢弃，并中断当前 Workflow Run。
- 节点最终成功事务必须把输出校验、Context 原子提交、Run-Time 最终事实写入和 NodeRun 转为 SUCCESS 视为一个不可分割的终态操作；未声明 outputs 时 Context 提交集合为空，但仍使用同一终态操作。任何一步失败都不得留下 SUCCESS NodeRun 或部分 Context 输出。
- 下游调度器只有在上游成功事务完整提交后，才能观察到上游 SUCCESS 和对应 Context 变量；不允许先观察状态、后等待变量异步写入。
- Context key 已存在时，节点状态为 FAILED，error.code 使用 `CONTEXT_KEY_EXISTS`；Workflow Run 停止调度尚未开始的节点。
- START 的每一项 key 必须是合法且唯一的 Context 变量名，value 使用 JSON 输入并支持字符串、数字、布尔值、对象、数组和 null；value 解析失败或不是严格 JSON 值时，START 失败且不写入任何变量。提交前执行与业务节点相同的 key 冲突检查和原子提交。
- 节点失败、超时或被中断时，其待提交输出全部丢弃，Context 保持执行前状态。

- Context 中的值必须能够序列化为严格 JSON；不可序列化值、NaN、Infinity 和循环引用不得写入。

统一 JSON 数值类型规则：

- `number` 接受有限整数和有限小数，包括运行时 int 或 float，但不接受 boolean；例如 `1`、`-2`、`1.5` 均符合 number。
- `integer` 只接受以整数表示形式解析和存储的值，不接受 float 或 boolean；例如 `1` 符合 integer，`1.0` 即使数学值等于 1 也不符合 integer。
- number 包含 integer，二者不是互斥类型；声明为 number 的输入或输出可以接收整数。
- START 输入校验、SCRIPT set_val 类型校验和 HTTP outputs.path 提取类型校验统一使用以上规则。

<a id="chapter-3-4"></a>

### 3.4 与 Run-Time 的关系

- Context 是当前 Workflow Run 的业务状态。
- Run-Time 是节点执行记录，保存实际输入、已提交输出、状态、执行次数和错误。
- Run-Time 的 inputs 和 outputs 是运行快照，不会改变 Context 的数据结构。
- 日志、原始请求、原始响应和错误堆栈属于独立运行数据，不写入 Context。

<a id="chapter-3-5"></a>

### 3.5 引用规则

HTTP、LLM 和 AGENT 节点中允许引用 Context 的配置字段统一使用以下格式：

```text
{{ context.variable_name }}
{{ ctx.variable_name }}
```

context 和 ctx 完全等价，都指向当前 Workflow Run 的 Context。界面插入变量时默认生成完整形式 {{ context.variable_name }}；保存时保留用户原始写法，不自动改写 ctx。

支持读取嵌套对象和数组：

```text
{{ context.review_result.status }}
{{ ctx.devices[0].name }}
```

引用语法只允许变量读取、对象字段访问和数组下标访问，不允许函数调用、运算符或任意代码。

```text
{{ context.price * 2 }}       不允许
{{ context.name.upper() }}    不允许
```

解析规则：

- 整个字段只有一个 Context 引用时，保留变量的原始 JSON 类型。
- Context 引用嵌入普通文本时，将变量转换为文本；对象和数组使用紧凑 JSON。
- 节点字段可以在各自协议中收紧或覆盖上述类型规则；LLM Prompt 始终转换为文本，HTTP URL/Header/Params 按第八章规则处理。
- 引用的变量不存在或嵌套路径不存在时，节点在实际请求或调用开始前失败。
- 同一字段中可以混合使用 context 和 ctx。
- {{ variable_name }} 不符合 Context 引用语法，始终保持普通文本。
- \{{ ctx.variable_name }} 表示输出引用原文 {{ ctx.variable_name }}，不读取 Context。
- SCRIPT 的 Python 源码不执行模板替换，继续通过 get_val 和 set_val 访问 Context。
- Run-Time inputs 始终以 Context 根变量名为 key，并保存该根变量未经路径提取或文本转换的完整 JSON 值。例如引用 `{{ ctx.review_result.status }}` 时记录完整的 `review_result`；同一次最终执行通过多个路径引用同一根变量时只记录一次。

<a id="chapter-4"></a>

## 4. Node Status

<a id="chapter-4-1"></a>

### 4.1 NodeRun 状态矩阵

END 不创建 NodeRun，因此 END 列全部为“×”。重试发生在 RUNNING 内部；NodeRun 一旦进入 FAILED 或 TIMEOUT，说明对应节点已按策略完成全部允许的尝试，不会从终态再次重试。

| 节点状态 | START | SCRIPT | LLM | HTTP | END | 触发条件 | 重试策略 |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| PENDING | √ | √ | √ | √ | × | NodeRun 已创建，前置依赖已满足但尚未获得执行权 | - |
| RUNNING | √ | √ | √ | √ | × | 节点开始实际执行；重试与重试等待期间保持该状态 | 按节点 execution 策略在状态内部重试 |
| SUCCESS | √ | √ | √ | √ | × | 执行、输出校验、Context 提交与终态事务全部成功 | × |
| FAILED | √ | √ | √ | √ | × | 最终非超时错误、输出提交失败或执行前运行时错误 | × |
| TIMEOUT | × | √ | √ | √ | × | 最后一次允许的执行结果为超时 | × |
| CANCELLED | √ | √ | √ | √ | × | 用户取消或 Fail-Fast 中断 | × |

<a id="chapter-4-2"></a>

### 4.2 状态与 error 不变量

- PENDING、RUNNING、SUCCESS 时 error 必须为 null。
- FAILED、TIMEOUT、CANCELLED 时 error 必须为非空结构化 error。
- START 不执行自动重试，也不进入 TIMEOUT。
- END 只是 Workflow 结束标记，不产生 NodeRun 或节点状态。

<a id="chapter-4-3"></a>

### 4.3 Workflow Run 状态

Workflow Run 自身维护状态、时间和顶层错误摘要字段，用于表示整张 Workflow 的生命周期；它与节点的 NodeRun.status 分开记录。当前阶段 Workflow Run 不记录 inputs 或 outputs，不提供 Workflow 级最终结果读取能力；节点级 Run-Time 仍保留各自的输入输出快照，但不定义最终结果节点或聚合返回协议。

#### Workflow Run 示例

```json
{
  "run_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
  "status": "SUCCESS",
  "started_at": "2026-07-25 10:00:00",
  "finished_at": "2026-07-25 10:00:15",
  "duration_ms": 15000,
  "error": null
}
```

#### 参数列表

| 字段        | 类型        | 取值                                                           | 示例                                  | 含义                                  |
| ----------- | ----------- | -------------------------------------------------------------- | ------------------------------------- | ------------------------------------- |
| run_id      | string      | UUIDv4 字符串                                                  | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10  | Workflow Run 的唯一标识               |
| workflow_id | string      | UUIDv4 字符串                                                  | 123e4567-e89b-42d3-a456-426614174000 | 被执行 Workflow 的唯一标识            |
| status      | string      | PENDING、RUNNING、SUCCESS、FAILED、CANCELLED                     | SUCCESS                               | Workflow Run 当前状态                 |
| started_at  | string/null | Asia/Shanghai，YYYY-MM-DD HH:mm:ss 或 null                     | 2026-07-25 10:00:00                   | 首个 NodeRun 创建时间；尚未调度时为 null |
| finished_at | string/null | Asia/Shanghai，YYYY-MM-DD HH:mm:ss 或 null                     | 2026-07-25 10:00:15                   | Workflow Run 结束时间                  |
| duration_ms | int/null    | 大于等于 0 或 null                                              | 15000                                 | Workflow Run 总耗时，单位毫秒          |
| error       | object/null | error 对象或 null                                               | null                                  | Workflow Run 顶层错误摘要              |

#### error 参数

| 字段        | 类型        | 取值                    | 示例                                      | 含义                                  |
| ----------- | ----------- | ----------------------- | ----------------------------------------- | ------------------------------------- |
| code        | string      | 稳定错误码              | CONTEXT_VARIABLE_NOT_FOUND                | Workflow Run 根因错误码               |
| message     | string      | 非空字符串              | 缺少 Context 变量 conversation             | Workflow Run 根因说明                 |
| node_run_id | string/null | UUIDv4 字符串或 null    | 4d2c6b8a-1f3e-4a90-b7d5-6c8e2f1a9b55      | 触发失败的 NodeRun；取消时为 null     |
| details     | object/null | 结构化 JSON 对象或 null | null                                      | 可选诊断信息                          |

| 状态      | 含义                                                                 |
| --------- | -------------------------------------------------------------------- |
| PENDING   | Workflow Run 已创建，但尚未进入节点调度                             |
| RUNNING   | 至少一个节点已进入调度，Workflow 尚未结束                            |
| SUCCESS   | START（如有）和全部业务节点均成功，且配置的 END 已到达                 |
| FAILED    | 任一节点最终失败、超时、Context 冲突或缺失变量，触发 Fail-Fast         |
| CANCELLED | 用户主动取消 Workflow Run；正在运行的节点转为 CANCELLED              |

状态规则：

- Workflow Run 创建时为 PENDING；首个节点创建 NodeRun 后转为 RUNNING，并以该时刻作为 started_at；PENDING 等待阶段不计入 duration_ms。
- START（如有）和全部业务节点的 NodeRun 均为 SUCCESS，且配置的 END 已到达时，Workflow Run 才转为 SUCCESS；未配置 END 时不检查 END 条件。调度遗漏、仍为 PENDING 或未创建 NodeRun 的业务节点都不能被视为成功。
- 任一节点最终 FAILED 或 TIMEOUT 后转为 FAILED，并立即触发 Fail-Fast。
- FAILED 时，Workflow Run.error 保存调度器最先观察到的触发 Fail-Fast 根因及其 node_run_id；其他并行失败保留在各自 NodeRun 中，SUCCESS 时 error 为 null。
- Fail-Fast 触发后，所有已创建但未成功终结的 PENDING/RUNNING NodeRun 都必须记录为 CANCELLED；待这些 NodeRun 完成终态写入后，Workflow Run 才写入 finished_at。RUNNING 节点的中断收尾时间计入 duration_ms。
- 用户主动取消时 Workflow Run 转为 CANCELLED，error.code 使用 `WORKFLOW_CANCELLED` 且 node_run_id 为 null。所有 RUNNING NodeRun 立即中断并使用 `NODE_CANCELLED_BY_USER`，所有已创建但仍为 PENDING 的 NodeRun 直接转为 CANCELLED，attempt_count 为 0、started_at 和 duration_ms 为 null，并记录 finished_at 与 `NODE_CANCELLED_BY_USER` error；尚未创建的节点不补建 NodeRun。Workflow Run 等待全部中断与状态写入完成后再记录 finished_at；尚未创建任何 NodeRun 时 started_at 和 duration_ms 均为 null，只记录取消时的 finished_at。取消不执行自动重试。
- 用户在画布中对某个 PENDING 或 RUNNING 节点发起中断，等价于用户取消整个 Workflow Run，不支持仅取消单个节点后继续 Workflow。已为 SUCCESS、FAILED、TIMEOUT 或 CANCELLED 的节点再次收到中断请求时不影响仍在运行的 Workflow。
- 对已进入 SUCCESS、FAILED 或 CANCELLED 的 Workflow Run，或已进入任一终态的 NodeRun，再次发送取消/中断请求是幂等 no-op；平台返回当前记录，不修改 status、error、finished_at、duration_ms、outputs 或其他历史字段，也不返回状态冲突错误。
- Workflow Run 进入 SUCCESS、FAILED 或 CANCELLED 后不再改变状态。

<a id="chapter-5"></a>

## 5. START

START 是 Workflow 的可选系统入口节点。当前阶段只负责把用户配置的变量输入一次性写入当前 Run 的 Context；外部任务下发能力暂不纳入本节。

<a id="chapter-5-1"></a>

### 5.1 Design-Time

#### Design-Time 示例

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
      "data": "请审核这段内容"
    },
    {
      "name": "retry_count",
      "type": "integer",
      "data": 3
    }
  ]
}
```

#### 参数列表

| 字段        | 类型   | 取值                         | 示例                                                     | 含义                                  |
| ----------- | ------ | ---------------------------- | -------------------------------------------------------- | ------------------------------------- |
| id          | string | UUIDv4 字符串                | 2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44                     | START 节点在 Workflow 中的唯一标识    |
| type        | string | START                        | START                                                    | 系统入口节点类型                      |
| name        | string | 用户自定义                   | 输入审核参数                                             | 画布和日志中显示的节点名称            |
| description | string | 用户自定义，可为空           | 为本次 Workflow 提供初始变量                             | 节点业务用途说明                      |
| inputs      | array  | 可为空，且 name 在本节点唯一 | [{"name":"conversation","type":"string","data":"请审核这段内容"}] | 初始变量输入项                        |

#### inputs 参数

| 字段 | 类型       | 取值                                                  | 示例           | 含义                                  |
| ---- | ---------- | ----------------------------------------------------- | -------------- | ------------------------------------- |
| name | string     | 合法变量名，且在本节点内唯一                          | conversation   | 写入 Context 的变量名                 |
| type | string     | string、number、integer、boolean、object、array、null | string         | 对 data 执行的严格 JSON 类型约束      |
| data | JSON value | 必须符合 type，且可严格 JSON 序列化                  | 请审核这段内容 | 本次 START 要写入 Context 的变量值     |

START 的 inputs 是用户在节点编辑器中填写的 `name / type / data` 行。data 不使用 Context 引用，也不执行模板替换；它是当前节点定义中保存的 JSON 值。

<a id="chapter-5-2"></a>

### 5.2 Run-Time

Run-Time 记录 START 实际输入和成功写入 Context 的结果。START 不自动重试；进入 RUNNING 后 attempt_count 固定为 1，执行前动态错误或在 PENDING 时被取消则为 0。

#### Run-Time 示例

```json
{
  "run_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "node_run_id": "4d2c6b8a-1f3e-4a90-b7d5-6c8e2f1a9b55",
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
  "error": null
}
```

#### 参数列表

| 字段          | 类型        | 取值                                                           | 示例                                      | 含义                                  |
| ------------- | ----------- | -------------------------------------------------------------- | ----------------------------------------- | ------------------------------------- |
| run_id        | string      | UUIDv4 字符串                                                  | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10      | 本次 Workflow Run 的唯一标识          |
| node_run_id   | string      | UUIDv4 字符串                                                  | 4d2c6b8a-1f3e-4a90-b7d5-6c8e2f1a9b55      | 本次 START 运行记录的唯一标识         |
| node_id       | string      | UUIDv4 字符串                                                  | 2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44      | Design-Time START 节点 ID              |
| type          | string      | START                                                          | START                                     | 节点类型                              |
| status        | string      | PENDING、RUNNING、SUCCESS、FAILED、CANCELLED                  | SUCCESS                                   | START 当前或最终状态                  |
| started_at    | string/null | YYYY-MM-DD HH:mm:ss，Asia/Shanghai 或 null                    | 2026-07-25 10:00:00                       | 进入 RUNNING 的时间；PENDING 时为 null |
| finished_at   | string/null | YYYY-MM-DD HH:mm:ss 或 null                                    | 2026-07-25 10:00:01                       | 节点结束时间                          |
| duration_ms   | int/null    | 大于等于 0 或 null                                             | 1000                                      | 节点总耗时，单位毫秒                  |
| attempt_count | int         | 0 或 1                                                         | 1                                         | START 实际执行次数                   |
| inputs        | object      | name 到 JSON 值的映射                                         | {"conversation":"请审核这段内容"}        | START 本次实际读取的输入值            |
| outputs       | object      | name 到 JSON 值的映射，失败时为 {}                            | {"conversation":"请审核这段内容"}        | 成功提交到 Context 的变量             |
| error         | object/null | error 对象或 null                                              | null                                      | START 执行错误                        |

#### error 参数

| 字段    | 类型        | 取值                    | 示例                          | 含义                         |
| ------- | ----------- | ----------------------- | ----------------------------- | ---------------------------- |
| code    | string      | 稳定错误码              | START_INPUT_INVALID           | 机器可读错误码               |
| message | string      | 非空字符串              | data 与 type 不匹配           | 面向用户的错误说明           |
| details | object/null | 结构化 JSON 对象或 null | null                          | 可选诊断信息；不写入 Context |

<a id="chapter-5-3"></a>

### 5.3 Input & Output Protocol

- START 按 inputs 数组顺序读取每一项的 name、type 和 data。
- 任一 name 重复、name 不合法、data 不是合法 JSON 或 data 与 type 不匹配时，均属于 START Design-Time 配置错误；Workflow 保存或运行前置校验必须拒绝该配置，不创建 Workflow Run 或 NodeRun。只有已通过配置校验、但在 Run 创建后发现 Context 冲突等动态错误时，START 才按通用执行前错误规则创建 FAILED NodeRun，attempt_count 为 0，outputs 为 {}。
- START 提交前必须检查所有 name 是否已经存在于 Context；任一 key 冲突时 error.code 为 `CONTEXT_KEY_EXISTS`，outputs 为 {}，Workflow 触发 Fail-Fast。
- 所有输入校验通过后，START 将 inputs 一次性写入 Context；outputs 与成功提交的变量集合一致。
- START 不执行自动重试；用户主动取消或 Workflow Fail-Fast 中断时，按通用 NodeRun 规则记录 CANCELLED。

<a id="chapter-6"></a>

## 6. SCRIPT

<a id="chapter-6-1"></a>

### 6.1 Design-Time

Design-Time 只记录节点定义，不记录某次运行的输入值、实际输出值、Context、状态、日志或错误。

#### Design-Time 示例

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "SCRIPT",
  "name": "汇总审核结果",
  "description": "汇总多个审核节点的结果",
  "script": "review = get_val(\"review_result\")\nset_val(\"review_status\", review[\"status\"])",
  "execution": {
    "timeout_ms": 120000,
    "max_attempts": 3,
    "delay_ms": 1000
  },
  "outputs": [
    {
      "name": "review_status",
      "type": "string"
    }
  ]
}
```

#### 与 Run-Time 的字段边界

| Design-Time                     | Run-Time                   | 边界                                                            |
| ------------------------------- | -------------------------- | --------------------------------------------------------------- |
| id                              | node_id                    | Run-Time 只引用节点 ID，不修改 ID                               |
| type                            | type                       | Run-Time 复制节点类型用于识别记录                               |
| name、description               | 无对应业务字段             | 只用于定义态展示，不作为执行结果                                |
| script                          | 无对应业务字段             | 作为本次执行代码输入，不写入 inputs、outputs 或 Context         |
| execution                       | attempt_count、duration_ms | execution 声明最大重试和间隔；Run-Time 记录实际执行次数及总耗时 |
| outputs 数组                    | outputs 对象               | 前者声明成功时必须全部产生的 name/type，后者保存成功产生的 name/value |
| 无 Design-Time inputs           | inputs 对象                | SCRIPT 不预先声明输入，Run-Time 按实际 get_val 调用记录         |
| 无 Design-Time 状态和错误       | status、error              | 只由执行过程产生                                                |
| 无 Design-Time 日志             | 无 Run-Time 字段           | 完整日志、失败堆栈和逐次尝试细节只临时保存                    |

#### 参数列表

| 字段        | 类型   | 取值               | 示例                                                  | 含义                                  |
| ----------- | ------ | ------------------ | ----------------------------------------------------- | ------------------------------------- |
| id          | string | UUIDv4 字符串      | 550e8400-e29b-41d4-a716-446655440000                  | 节点在 Workflow 中的唯一标识          |
| type        | string | SCRIPT             | SCRIPT                                                | 节点类型为脚本                        |
| name        | string | 用户自定义         | 汇总审核结果                                          | 画布和日志中显示的节点名称            |
| description | string | 用户自定义，可为空 | 汇总多个审核节点的结果                                | 节点业务用途说明                      |
| script      | string | Python 源码文本    | review = get_val("review_result")                     | 用户编辑的完整脚本代码                |
| execution   | object | 必填               | {"timeout_ms":120000,"max_attempts":3,"delay_ms":1000} | 执行参数                              |
| outputs     | array  | 可为空，默认 []    | [{"name":"review_status","type":"string"}]            | 脚本成功时必须全部产生的完整输出声明   |

SCRIPT Design-Time 直接在 script 字段保存 Python 源码字符串，不嵌套 source、language 或 version，也不提供运行语言和解释器版本选择；平台实际 Python 运行环境属于部署配置，不进入节点定义或 Run-Time。

#### execution 参数

| 字段         | 类型 | 取值     | 示例 | 含义                             |
| ------------ | ---- | -------- | ---- | -------------------------------- |
| timeout_ms   | int  | 大于 0   | 120000 | 单次脚本执行超时时间，单位毫秒   |
| max_attempts | int  | 0~10     | 3    | 最大重试次数，不包含首次执行     |
| delay_ms     | int  | 0~600000 | 1000 | 两次重试之间的固定间隔，单位毫秒 |

暂不设置 retry_on 和 max_output_bytes。

max_attempts 的语义：

| 配置值 | 最大总执行次数      |
| ------ | ------------------- |
| 0      | 1 次，不重试        |
| 1      | 2 次，最多重试 1 次 |
| 3      | 4 次，最多重试 3 次 |

delay_ms 只在一次执行失败后、下一次重试开始前生效，不表示节点首次执行前的延迟。

SCRIPT 重试规则：除用户主动取消或 Workflow Fail-Fast 导致的 CANCELLED 外，脚本异常、超时、Context 读取错误、set_val 校验错误、输出类型错误和其他执行错误均允许按 max_attempts 重试。
SCRIPT 单次尝试达到 timeout_ms 时，平台终止脚本主进程及其派生进程树；进程树结束后，本次尝试记为 TIMEOUT，并按 max_attempts 和 delay_ms 决定是否重试。

#### outputs 参数

outputs 是脚本输出声明。脚本只能通过 set_val 写入这里声明的变量；未声明的变量不能写入 Context。

| 字段 | 类型   | 取值                                                  | 示例          | 含义                           |
| ---- | ------ | ----------------------------------------------------- | ------------- | ------------------------------ |
| name | string | 合法变量名，且在本节点内唯一                          | review_status | 写入 Context 的变量名          |
| type | string | string、number、integer、boolean、object、array、null | string        | 运行时执行的严格 JSON 类型约束 |

outputs 不包含 description 或输出路径。脚本应直接生成下游需要的值；嵌套对象由下游脚本使用 Python 对象访问语法读取。

outputs 是成功结果的完整声明，不只是允许写入的白名单。outputs 非空时，脚本成功结束前必须通过 set_val 为每一项声明产生一次值；缺少任一声明输出时，本次执行失败，error.code 使用 `SCRIPT_OUTPUT_MISSING`。outputs 为空时，脚本未调用 set_val 即可成功结束。

Design-Time 不定义输入变量列表。脚本通过 get_val 从当前 Workflow Run 的 Context 读取变量。

<a id="chapter-6-2"></a>

### 6.2 Run-Time

Run-Time 记录一次节点执行的最终结果，不修改 Design-Time 定义。执行层可以按 Design-Time 配置重试，但 Run-Time 不保留各次尝试明细。

#### Run-Time 示例

```json
{
  "run_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "node_run_id": "9b1deb4d-3b7d-4bad-9b1d-7c8f2a6e4d11",
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
  "error": null
}
```

#### 参数列表

| 字段          | 类型        | 取值                                                           | 示例                  | 含义                                       |
| ------------- | ----------- | -------------------------------------------------------------- | --------------------- | ------------------------------------------ |
| run_id        | string      | UUIDv4 字符串                                                  | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10 | 本次 Workflow Run 的唯一标识               |
| node_run_id   | string      | UUIDv4 字符串                                                  | 9b1deb4d-3b7d-4bad-9b1d-7c8f2a6e4d11 | 本次节点运行记录的唯一标识                 |
| node_id       | string      | UUIDv4 字符串                                                  | 550e8400-e29b-41d4-a716-446655440000 | Design-Time 节点 ID                        |
| type          | string      | SCRIPT                                                         | SCRIPT                | 节点类型                                   |
| status        | string      | PENDING、RUNNING、SUCCESS、FAILED、TIMEOUT、CANCELLED          | SUCCESS               | 节点当前或最终状态                         |
| started_at    | string/null | YYYY-MM-DD HH:mm:ss 或 null                                    | 2026-07-24 23:11:50   | 进入 RUNNING 的时间；PENDING 时为 null      |
| finished_at   | string/null | YYYY-MM-DD HH:mm:ss 或 null                                    | 2026-07-24 23:11:52   | 节点最终结束时间；尚未结束时为 null        |
| duration_ms   | int/null    | 大于等于 0 或 null                                             | 2000                  | 节点总耗时，单位毫秒；尚未结束时为 null    |
| attempt_count | int         | 大于等于 0                                                     | 2                     | 实际执行次数；未开始执行时为 0             |
| inputs        | object      | 变量名到 JSON 值的映射                                        | {"review_result":{"status":"PASS"}} | 最终执行实际读取的 Context 变量和值        |
| outputs       | object      | 变量名到 JSON 值的映射，默认 {}                                | {"review_status":"PASS"} | 最终成功提交到 Context 的变量               |
| error         | object/null | error 对象或 null                                              | null                  | 最终执行错误；成功时为 null                 |

节点状态统一使用：

```text
PENDING | RUNNING | SUCCESS | FAILED | TIMEOUT | CANCELLED
```

#### error 参数

| 字段    | 类型        | 取值                    | 示例                        | 含义                         |
| ------- | ----------- | ----------------------- | --------------------------- | ---------------------------- |
| code    | string      | 稳定错误码              | SCRIPT_RUNTIME_ERROR        | 机器可读错误码               |
| message | string      | 非空字符串              | review_result.status 不存在 | 面向用户的错误说明           |
| details | object/null | 结构化 JSON 对象或 null | null                        | 可选诊断信息；不写入 Context |

完整标准输出、标准错误和执行日志属于临时观测数据，不写入 NodeRun；重试期间的失败尝试不持久化，最终终态只按 Run-Time error 规则保存结构化错误。

#### Run-Time 规则

- inputs、outputs 和 error 只保存最终执行的结果。
- attempt_count 记录实际执行次数，但不保存每次尝试的详细数据。
- duration_ms 记录整个节点执行耗时，包括重试等待时间。
- 脚本异常、超时、中断或 set_val 校验失败时，outputs 为 {}。
- 脚本进程正常结束后，平台校验所有 Design-Time outputs 是否都已通过 set_val 产生；缺少任一项时本次执行按 `SCRIPT_OUTPUT_MISSING` 失败，待提交 outputs 整体丢弃，并按 SCRIPT 重试规则处理。
- 只有最终成功的 outputs 才批量写入 Context。
- 全部重试失败时，Context 保持节点执行前状态。
- 除用户主动取消或 Workflow Fail-Fast 导致的 CANCELLED 外，所有最终失败原因均按 execution.max_attempts 执行重试。

<a id="chapter-6-3"></a>

### 6.3 Input & Output Protocol

#### 用户代码接口

平台向 Python 脚本提供：

```python
value = get_val(name)
set_val(name, value)
```

| 调用                 | 参数                                 | 含义                    |
| -------------------- | ------------------------------------ | ----------------------- |
| get_val(name)        | name: string                         | 从当前 Context 读取变量 |
| set_val(name, value) | name: string、value: JSON 可序列化值 | 写入本节点待提交输出    |

#### get_val 规则

- 变量存在时返回 Context 原始 JSON 值的深拷贝，包括嵌套对象和数组；每次 get_val 调用都返回独立副本，脚本修改返回对象不得改变 Context 或同一变量的其他副本。
- 变量不存在时立即使本次 SCRIPT 执行失败，error.code 使用 `CONTEXT_VARIABLE_NOT_FOUND`，不会返回 Python None。
- 平台不做路径解析、类型转换或来源包装；脚本直接使用 Python 对象访问语法处理嵌套值。

```python
review = get_val("review_result")
status = review["status"]
reason = review["reason"]
set_val("review_status", status)
set_val("review_reason", reason)
```

#### set_val 规则

- name 未在 Design-Time outputs 中声明时，立即使本次执行失败，error.code 使用 `SCRIPT_OUTPUT_UNDECLARED`。
- value 不符合声明的 type 时，平台不自动转换，error.code 使用 `SCRIPT_OUTPUT_TYPE_MISMATCH`。
- value 不是严格 JSON 可序列化值时，error.code 使用 `SCRIPT_OUTPUT_SERIALIZATION_ERROR`。
- set_val 在调用时完成类型校验和严格 JSON 深拷贝，待提交集合保存该副本；脚本在 set_val 返回后继续修改原对象，不得改变已经捕获的输出值。
- 同一次执行中重复设置同名变量时，本次执行失败，error.code 使用 `SCRIPT_OUTPUT_DUPLICATE`。
- name 输入时必须符合 [A-Za-z_][A-Za-z0-9_]*，保存后按第三章规则转换为小写，且在 outputs 中唯一。
- outputs 中声明的每个 name 都必须在脚本正常结束前恰好调用一次 set_val；未设置的声明输出使本次执行失败。

严格类型对应关系：

| outputs.type | 允许的 Python 值            |
| ------------ | --------------------------- |
| string       | str                         |
| number       | int 或 float，但不允许 bool |
| integer      | int，但不允许 bool          |
| boolean      | bool                        |
| object       | dict                        |
| array        | list                        |
| null         | None                        |

#### 提交与日志

- set_val 只写入本节点待提交集合，不立即修改共享 Context。
- 脚本成功结束后，平台一次性将待提交集合写入 Context。
- 提交前平台必须检查待提交集合中的每个 name 是否已存在于 Context；任一 name 已存在时，整个集合都不写入，节点失败并中断 Workflow Run。
- 脚本异常、超时、被中断或任一校验失败时，待提交集合全部丢弃。
- print() 只进入执行期间的临时观测日志，不会写入 Run-Time、Context 或 outputs。

#### 用户代码示例

以下独立示例假设 Design-Time outputs 已声明 `currtime_1`、`currtime_2` 和 `review_status`，且三者 type 均为 string。

```python
import random
import time

time_str = time.strftime("%Y%m%d%H%M%S")
letters = [chr(random.randint(65, 90)) for _ in range(3)]
currtime = time_str + "".join(letters)

set_val("currtime_1", currtime)
set_val("currtime_2", currtime)

review = get_val("review_result")
set_val("review_status", review["status"])
```

#### 成功输出示例

```json
{
  "currtime_1": "20260724153022ABC",
  "currtime_2": "20260724153022ABC",
  "review_status": "PASS"
}
```

以上对象是本次 SCRIPT 执行成功后写入 Context 的变量集合，不属于 Design-Time 节点定义。

<a id="chapter-7"></a>

## 7. LLM

<a id="chapter-7-1"></a>

### 7.1 Design-Time

Design-Time 描述 LLM 节点使用的模型引用、Prompt、生成参数、执行约束和原始文本输出声明。不保存 API Key、Base URL、协议、Proxy、SSL、模型默认 Body 或某次运行的实际 Prompt。

#### Design-Time 示例

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
  "prompt": {
    "system": "你是中文合规审核员，只输出审核结论文本。",
    "user": "请审核以下内容：{{ ctx.conversation }}"
  },
  "generation": {
    "stream": false,
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
    "timeout_ms": 120000,
    "max_attempts": 2,
    "delay_ms": 1000
  },
  "outputs": [
    {
      "name": "llm_text",
      "type": "string"
    }
  ]
}
```

#### 与 Run-Time 的字段边界

| Design-Time                | Run-Time               | 边界                                                       |
| -------------------------- | ---------------------- | ---------------------------------------------------------- |
| id                         | node_id                | Run-Time 只引用节点 ID，不修改 ID                          |
| type                       | type                   | Run-Time 复制 LLM 类型用于识别记录                         |
| name、description          | 无对应业务字段         | 只用于定义态展示，不作为模型输出                           |
| model                      | 实际请求使用的模型信息 | 前者只保存供应商和模型引用，后者记录本次调用实际使用的模型 |
| prompt.system、prompt.user | 实际解析后的 Prompt    | 前者保存模板和 Context 引用，后者是本次调用使用的文本      |
| generation.parameters      | 实际合并后的模型参数   | 前者保存节点级参数，后者是合并后的请求参数                 |
| execution                  | attempt_count          | 前者声明超时和重试约束，后者记录实际调用次数               |
| outputs 数组               | 实际原始文本输出       | 前者最多声明一个 string 输出，后者保存实际模型文本         |

#### 参数列表

| 字段        | 类型   | 取值               | 示例                                                               | 含义                         |
| ----------- | ------ | ------------------ | ------------------------------------------------------------------ | ---------------------------- |
| id          | string | UUIDv4 字符串      | 7c9e6679-7425-40de-944b-e07fc1f90ae7                             | 节点在 Workflow 中的唯一标识 |
| type        | string | LLM                | LLM                                                                | 节点类型                     |
| name        | string | 用户自定义         | 中文合规审核                                                       | 画布和日志中显示的节点名称   |
| description | string | 用户自定义，可为空 | 判断内容是否符合中文要求                                           | 节点业务用途说明             |
| model       | object | 必填               | {"provider_id":"provider-deepseek","model_name":"deepseek-v4-pro"} | 模型引用                     |
| prompt      | object | 必填               | {"system":"...","user":"..."}                                      | Prompt 定义                  |
| generation  | object | 必填               | {"stream":false,"parameters":{"temperature":0}}                    | 流式开关和生成参数           |
| execution   | object | 必填               | {"timeout_ms":120000,"max_attempts":2,"delay_ms":1000}             | 执行约束                     |
| outputs     | array  | 可为空，最多一个   | [{"name":"llm_text","type":"string"}]                              | 原始文本输出声明             |

#### model 参数

| 字段        | 类型   | 取值                  | 示例              | 含义           |
| ----------- | ------ | --------------------- | ----------------- | -------------- |
| provider_id | string | 模型管理中的供应商 ID | provider-deepseek | 引用模型供应商 |
| model_name  | string | 供应商已配置模型名    | deepseek-v4-pro   | 引用具体模型   |

LLM 节点不复制模型管理中的 API Key、Base URL、协议、Proxy、SSL、模型默认 Body、上下文窗口或最大输出能力。

模型引用是弱关联：模型管理允许删除供应商、删除模型或修改模型名，不因已有 Workflow 引用而阻止操作。保存 Workflow 和启动 Workflow Run 时都必须校验 provider_id 与 model_name 当前有效；任一引用不存在时校验失败，错误码使用 `LLM_MODEL_NOT_FOUND`，不创建 Workflow Run 或 NodeRun。平台不使用历史模型配置、同名模型或节点快照回退执行。

LLM NodeRun 准备启动时解析一次当前模型管理配置，并在内存中固定本次 NodeRun 使用的供应商协议、API Key、Base URL、Proxy、SSL、模型默认 Body 和其他模型元数据。后续所有重试都使用同一份内存快照；模型管理在 NodeRun 期间发生的修改只影响之后启动的 NodeRun。该快照不写入 Run-Time，API Key 等敏感配置也不因快照机制新增持久化副本。若模型在 Workflow 运行前置校验通过后、LLM NodeRun 启动前失效，则该 NodeRun 按 `LLM_MODEL_NOT_FOUND` 从 PENDING 直接转为 FAILED，attempt_count 为 0。

#### prompt 参数

| 字段   | 类型   | 取值   | 示例                           | 含义           |
| ------ | ------ | ------ | ------------------------------ | -------------- |
| system | string | 可为空 | 你是中文合规审核员。           | 系统提示词模板 |
| user   | string | 非空   | 请审核：{{ ctx.conversation }} | 用户提示词模板 |

Prompt 当前只支持 system 和 user 两个字段，不支持 messages[]、assistant 示例消息或其他角色。

#### generation 参数

| 字段       | 类型    | 取值                   | 示例                                | 含义                           |
| ---------- | ------- | ---------------------- | ----------------------------------- | ------------------------------ |
| stream     | boolean | true/false，默认 false | false                               | 是否启用流式输出               |
| parameters | object  | 合法 JSON object       | {"temperature":0,"max_tokens":1024} | 节点高级参数，原样参与请求合并 |

parameters 规则：

- parameters 可以包含供应商特有字段，以保持模型兼容性。
- generation.parameters 及模型默认 Body 均不解析 Context 引用，也不参与静态 Context 引用扫描；其中形如 `{{ ctx.variable_name }}` 的字符串按普通字符串原样参与参数合并。LLM 节点只有 prompt.system 和 prompt.user 支持 Context 引用。
- stream 单独保存，不重复放入 parameters。
- parameters 顶层不允许包含平台核心字段 `model`、`messages`、`input`、`prompt`、`system`、`stream`；发现顶层保留字段时属于配置错误，Workflow 校验失败，不创建 NodeRun，也不执行自动重试。
- 保留字段检查不递归进入嵌套 object；工具定义、JSON Schema 或供应商扩展对象内部可以使用同名字段，因为它们不会覆盖平台顶层请求结构。
- 模型管理中的默认 Body 使用相同的顶层保留字段集合；模型配置保存和测试时拒绝顶层保留字段，Workflow 运行前置校验再次检查。默认 Body 只能提供非保留的顶层生成参数。
- 不对白名单之外的参数做强制拒绝。
- response_format 等模型特有参数可以原样填写，但平台不解析结构化结果。
- 请求合并顺序为：平台基础请求 < 模型默认 Body < 节点 parameters；默认 Body 和 parameters 都只能覆盖非保留的生成参数。
- 合并时，双方字段均为 object 才递归合并；array、string、number、integer、boolean 和 null 均由高优先级值整体替换，不执行数组拼接或自动类型转换。

#### execution 参数

| 字段         | 类型 | 取值     | 示例   | 含义                             |
| ------------ | ---- | -------- | ------ | -------------------------------- |
| timeout_ms   | int  | 大于 0   | 120000 | 非流式调用总超时；流式调用片段空闲超时，单位毫秒 |
| max_attempts | int  | 0~10     | 2      | 最大重试次数，不包含首次请求     |
| delay_ms     | int  | 0~600000 | 1000   | 两次重试之间的固定间隔，单位毫秒 |

LLM 重试规则：除用户主动取消或 Workflow Fail-Fast 导致的 CANCELLED 外，已经开始供应商请求后的模型请求错误、超时、响应解析错误和其他执行错误均允许按 max_attempts 重试。Context 引用解析错误、模型不存在、平台保留参数错误和其他执行前错误不进入重试，按通用执行前错误规则处理。
LLM stream=false 时，timeout_ms 从请求开始持续计算到完整响应结束；stream=true 时，timeout_ms 表示相邻有效流式事件之间的最大空闲时间，文本、reasoning、usage、心跳或其他可被供应商协议合法解析的事件都会重新计时；空行、损坏帧或无法解析的事件不重置，不设置额外总时长上限。
LLM stream=true 时，只有收到当前供应商适配协议定义的完成信号，才能把已接收文本组装为最终 response。完成信号可以是协议规定的结束事件、结束帧或明确的完成字段，但不能只依赖 TCP/HTTP 连接关闭；连接在完成信号前关闭时，本次调用按 `LLM_STREAM_INCOMPLETE` 失败，即使已经收到部分文本。该错误按通用 LLM 重试规则处理，失败尝试的 response 为 null、outputs 为 {}，已收到的 usage 仍参与聚合。

#### outputs 参数

| 字段 | 类型   | 取值                         | 示例     | 含义                          |
| ---- | ------ | ---------------------------- | -------- | ----------------------------- |
| name | string | 合法变量名，且本节点最多一项 | llm_text | 写入 Context 的原始文本变量名 |
| type | string | 固定 string                  | string   | 原始模型文本类型              |

LLM 输出不设置 path，不声明 object、array 或 JSON Schema。用户需要结构化字段时，应由下游 SCRIPT 节点解析原始文本。

<a id="chapter-7-2"></a>

### 7.2 Run-Time

Run-Time 保存某次 Workflow Run 中 LLM 节点最终发生的调用事实：实际输入、模型、平台统一请求、最终原始文本、Token usage 及其结构化问题、重试次数、状态和错误。它不保存可编辑模板、不保存供应商实际 Wire JSON、不保存流式中间片段，也不保存日志引用。

#### Run-Time 示例

```json
{
  "run_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "node_run_id": "5e074085-8d4a-4e0b-8f3c-2a9d6b7c3e33",
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
        "system": "你是中文合规审核员。",
        "user": "请审核以下内容：待审核的原始内容",
        "parameters": {
          "temperature": 0,
          "max_tokens": 1024
        },
        "stream": false
      },
  "response": "{\"status\":\"PASS\",\"reason\":\"符合要求\"}",
  "usage": {
        "input_tokens": 3890,
        "output_tokens": 245,
        "total_tokens": 4135
      },
  "usage_errors": [],
  "outputs": {
        "llm_text": "{\"status\":\"PASS\",\"reason\":\"符合要求\"}"
      },
  "error": null
}
```

#### 参数列表

| 字段          | 类型        | 取值                                                           | 示例                  | 含义                               |
| ------------- | ----------- | -------------------------------------------------------------- | --------------------- | ---------------------------------- |
| run_id        | string      | UUIDv4 字符串                                                  | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10 | 本次 Workflow Run 的唯一标识       |
| node_run_id   | string      | UUIDv4 字符串                                                  | 5e074085-8d4a-4e0b-8f3c-2a9d6b7c3e33 | 本次节点运行记录的唯一标识          |
| node_id       | string      | UUIDv4 字符串                                                  | 7c9e6679-7425-40de-944b-e07fc1f90ae7 | Design-Time 节点 ID                |
| type          | string      | LLM                                                            | LLM                   | 节点类型                           |
| status        | string      | PENDING、RUNNING、SUCCESS、FAILED、TIMEOUT、CANCELLED          | SUCCESS               | 节点当前或最终状态                 |
| started_at    | string/null | YYYY-MM-DD HH:mm:ss 或 null                                    | 2026-07-25 00:20:10   | 进入 RUNNING 的时间；PENDING 时为 null |
| finished_at   | string/null | YYYY-MM-DD HH:mm:ss 或 null                                    | 2026-07-25 00:20:15   | 节点最终结束时间                   |
| duration_ms   | int/null    | 大于等于 0 或 null                                             | 5000                  | 节点总耗时，单位毫秒               |
| attempt_count | int         | 大于等于 0                                                     | 2                     | 实际模型调用次数；未开始调用时为 0 |
| inputs        | object      | 变量名到 JSON 值的映射                                        | {"conversation":"待审核内容"} | 最终调用实际引用的 Context 变量和值 |
| model         | object/null | provider_id/model_name 或 null                                | {"provider_id":"provider-deepseek","model_name":"deepseek-v4-pro"} | 最终调用实际使用的模型；尚未解析时为 null |
| request       | object/null | 平台统一 request 对象或 null                                   | {"system":"...","user":"...","stream":false} | 最终调用的跨供应商统一请求快照 |
| response      | string/null | 原始模型文本或 null                                            | 审核通过              | 最终返回的原始文本                 |
| usage         | object/null | usage 对象或 null                                              | {"input_tokens":3890,"output_tokens":245,"total_tokens":4135} | 首次调用及所有重试调用的聚合 Token 统计 |
| usage_errors  | array       | UsageIssue 数组，无问题时为 []                                 | []                    | 所有调用中非法 usage 字段的结构化问题 |
| outputs       | object      | 变量名到 string 的映射，默认 {}                               | {"llm_text":"审核通过"} | 成功后提交到 Context 的原始文本    |
| error         | object/null | error 对象或 null                                              | null                  | 最终调用错误；成功时为 null        |

#### request 参数

| 字段       | 类型    | 取值                     | 示例                                | 含义                             |
| ---------- | ------- | ------------------------ | ----------------------------------- | -------------------------------- |
| system     | string  | 可为空                   | 你是中文合规审核员。                | 解析后的系统提示词               |
| user       | string  | 非空                     | 请审核以下内容：待审核的原始内容    | 解析后的用户提示词               |
| parameters | object  | 合并后的合法 JSON object | {"temperature":0,"max_tokens":1024} | 平台、模型和节点参数合并后的统一参数 |
| stream     | boolean | true/false               | false                               | 本次请求是否使用流式输出         |

#### usage 参数

| 字段          | 类型 | 取值       | 示例 | 含义                  |
| ------------- | ---- | ---------- | ---- | --------------------- |
| input_tokens  | int/null | 大于等于 0 或 null | 3890 | 所有模型调用的输入 Token 累计数         |
| output_tokens | int/null | 大于等于 0 或 null | 245  | 所有模型调用的输出 Token 累计数         |
| total_tokens  | int/null | 大于等于 0 或 null | 4135 | 所有模型调用的 Token 累计总数           |

聚合覆盖所有实际发起的模型调用；成功调用以及最终失败、超时或取消前已经收到的 usage 都参与累计。平台只累加供应商实际返回的 usage 字段；某次调用缺失 usage 时不估算、不补零，其他调用已返回的值仍参与累计，因此结果可能低于真实消耗。供应商返回 total_tokens 时始终信任该值，即使它与 input_tokens + output_tokens 不一致；仅在未返回 total_tokens、但同时返回 input_tokens 和 output_tokens 时，平台才按两者之和推导本次 total_tokens 后参与聚合。所有调用都未返回 usage 时，usage 为 null；某个字段在所有调用中都未返回且无法按上述规则推导时，该字段为 null。

input_tokens、output_tokens 和 total_tokens 只接受大于等于 0 的 integer，boolean、负数、小数、字符串和其他类型均为非法值。平台按字段独立忽略非法值，不执行类型转换；同一 usage 中的其他合法字段继续累计。非法字段按缺失处理，因此 total_tokens 非法但 input_tokens 与 output_tokens 合法时，仍按两者之和推导本次 total_tokens。所有标准字段都缺失或非法时，该次调用不产生 usage；usage 格式错误不改变模型调用的成功或失败结果。每个非法字段都必须生成一个 UsageIssue 写入 usage_errors，不得只写临时警告。

#### usage_errors 参数

| 字段    | 类型        | 取值                                      | 示例                                      | 含义                         |
| ------- | ----------- | ----------------------------------------- | ----------------------------------------- | ---------------------------- |
| attempt | int         | 大于等于 1                                | 2                                         | 发现问题的实际模型调用序号   |
| field   | string      | input_tokens、output_tokens、total_tokens | total_tokens                              | 供应商返回的非法 usage 字段  |
| code    | string      | LLM_USAGE_VALUE_INVALID                   | LLM_USAGE_VALUE_INVALID                   | 非法 usage 值的稳定问题码    |
| value   | JSON value  | 供应商原始值                              | "4135"                                   | 未经转换的非法字段值         |
| message | string      | 非空字符串                                | 必须是大于等于 0 的整数                   | 非法原因                     |

usage_errors 聚合所有实际发起调用中发现的问题，按发现顺序保存；无非法字段时为 `[]`。usage_errors 不改变模型调用的成功、失败、重试或最终 response，不写入 Context；usage 仍按上述规则保留所有合法字段。

#### error 参数

| 字段    | 类型        | 取值                    | 示例         | 含义                         |
| ------- | ----------- | ----------------------- | ------------ | ---------------------------- |
| code    | string      | 稳定错误码              | LLM_TIMEOUT  | 机器可读错误码               |
| message | string      | 非空字符串              | LLM 请求超时 | 面向用户的错误说明           |
| details | object/null | 结构化 JSON 对象或 null | null         | 可选诊断信息，不写入 Context |

#### Run-Time 规则

- inputs 只记录 system/user Prompt 实际引用过的 Context 变量。
- request 是跨供应商稳定的平台统一结构，保存 Context 解析后的 system/user、合并后的 parameters 和实际 stream 配置；供应商适配器据此生成 OpenAI、Anthropic 等协议的实际 Wire 请求。
- Run-Time 不保存供应商实际发送的 Wire JSON；不同供应商的 messages、system、input 等协议字段不得反向改变统一 request 结构。
- response 只保存模型最终原始文本，不保存供应商完整响应 JSON。
- 不解析 response，不生成 json、structured 或 reasoning 字段。
- 非流式请求收到完整文本后保存 response。
- 流式请求只在所有片段拼接完成后保存最终 response，不保存中间片段。
- 供应商返回多个文本块或流式文本片段时，严格按接收顺序直接拼接，不自动插入空格、换行或其他分隔符。
- reasoning、usage、心跳和其他协议元数据不属于模型文本，不拼接到 response。明确存在但内容为 `""` 的文本字段或文本块是有效空文本；供应商成功结束但完全没有返回文本字段或文本块时，节点按 `LLM_UNSUPPORTED_RESPONSE` 失败。
- 返回 Tool Call、Function Call、图片、音频或其他非文本模型内容时，节点按 `LLM_UNSUPPORTED_RESPONSE` 失败，即使同一响应中还包含文本；平台不执行、忽略或序列化这些内容。该错误按通用 LLM 重试规则处理，失败尝试的 response 为 null、outputs 为 {}，已收到的 usage 仍按聚合规则统计。
- 供应商因最大 Token、长度限制或等价原因结束生成时，节点按 `LLM_OUTPUT_TRUNCATED` 失败；因内容安全策略、审核过滤或等价原因结束时，节点按 `LLM_CONTENT_FILTERED` 失败。供应商适配器负责把协议特有 finish_reason/stop_reason 映射为上述错误；流式和非流式调用使用相同规则。
- 同一响应同时满足多个响应级异常条件时，按以下固定优先级选择唯一根因，不按适配器实现顺序变化：`LLM_RESPONSE_ERROR` > `LLM_STREAM_INCOMPLETE` > `LLM_UNSUPPORTED_RESPONSE` > `LLM_CONTENT_FILTERED` > `LLM_OUTPUT_TRUNCATED` > `LLM_UNSUPPORTED_FINISH_REASON`。
- LLM_OUTPUT_TRUNCATED 和 LLM_CONTENT_FILTERED 按通用 LLM 重试规则处理。即使供应商已经返回部分文本，失败尝试的 Run-Time response 仍为 null、outputs 为 {}；部分文本只进入临时日志，已收到的 usage 继续参与聚合。
- 供应商返回了协议完成信号，但 finish_reason、stop_reason 或等价结束原因无法映射为平台已支持的正常结束、长度限制、内容过滤或非文本响应类型时，节点按 `LLM_UNSUPPORTED_FINISH_REASON` 失败。error.details.finish_reason 保存供应商原始结束原因；失败尝试的 response 为 null、outputs 为 {}，并按通用 LLM 重试与 usage 聚合规则处理。
- 模型成功返回空字符串时，response 记录为 `""`，视为有效最终文本；声明 outputs 时将空字符串写入 Context，不触发自动重试。
- 模型调用失败、超时、中断或没有形成完整最终文本时，response 为 null，outputs 必须为 {}。
- 未声明 outputs 时，模型可以成功执行，但 outputs 为 {}，不写入 Context。
- 声明 outputs 后，完整 response 作为 string 值批量写入 Context。
- 输出提交前必须检查声明的输出 name 是否已存在于 Context；已存在时 outputs 为 {}，节点失败并中断 Workflow Run。
- usage 是首次调用和所有重试调用的聚合统计；失败、超时或取消前已收到的 usage 同样计入。usage_errors 同样聚合所有调用中的非法字段问题。usage 不属于模型文本，也不会自动写入 Context；不保存逐次 usage 明细。
- attempt_count 记录实际模型调用次数，但不保存每次调用的详细记录。
- inputs、model、request、response、outputs 和 error 只保留最终调用；usage 和 usage_errors 例外，分别聚合所有实际模型调用的合法 Token 统计与非法字段问题。
- duration_ms 包含重试等待时间；只有最终成功的 outputs 才更新 Context，全部失败时 Context 保持节点执行前状态。

<a id="chapter-7-3"></a>

### 7.3 Input & Output Protocol

#### Context 输入

以下 Prompt 字段支持第三章定义的统一 Context 引用格式：

```text
prompt.system
prompt.user
```

规则：

- {{ context.variable_name }} 与 {{ ctx.variable_name }} 等价。
- {{ ctx.ci_name }} 与 {{ctx.ci_name}} 等价，双花括号内侧的首尾空白不影响解析。
- 支持对象字段和数组下标访问。
- 变量或嵌套路径不存在时，LLM 节点在模型请求前失败。
- {{ variable_name }} 保持普通文本，不作为 Context 引用。
- prompt.system 和 prompt.user 始终生成 string：string 按原值插入，object 和 array 转换为紧凑 JSON，number/integer、boolean 和 null 转换为 JSON 字面量文本。
- prompt.user 的 Design-Time 模板必须为非空字符串；Context 解析后若最终 prompt.user 为精确空字符串 `""`，节点在模型请求前以 `LLM_PROMPT_EMPTY` 失败，attempt_count 为 0，不进入自动重试。仅包含空白字符的字符串不视为空字符串。
- Run-Time inputs 保存转换前的 Context 原始值；request.system 和 request.user 保存转换后的最终文本。

#### 输出协议

LLM 输出是模型最终返回的原始文本字符串：

```text
模型返回的完整文本，包括 Markdown、JSON 文本、换行和前后空白
```

- 不执行 JSON 解析。
- 不执行 Schema 校验。
- 不提取 reasoning、status 或其他子字段。
- Design-Time 声明 outputs 后，完整文本作为该变量的 string 值写入 Context。
- 下游需要结构化字段时，由 SCRIPT 使用 get_val 和 json.loads 自行处理。

<a id="chapter-8"></a>

## 8. HTTP

<a id="chapter-8-1"></a>

### 8.1 Design-Time

Design-Time 描述 HTTP 节点的持久化配置：接口模板、认证 Header、网络策略、执行约束和输出声明。它不保存某次运行解析后的 Context 值、实际请求、实际响应、状态、日志或错误。

#### Design-Time 示例

```json
{
  "id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
  "type": "HTTP",
  "name": "查询 CI 详情",
  "description": "根据设备名称查询 CMDB",
  "request": {
    "method": "POST",
    "url": "https://cmdb.example.com/api/ci/{{ ctx.ci_name }}",
    "follow_redirects": true,
    "headers": [
      {
        "key": "Content-Type",
        "value": "application/json"
      },
      {
        "key": "Authorization",
        "value": "Bearer {{ context.api_token }}"
      }
    ],
    "params": [
      {
        "key": "scope",
        "value": "{{ ctx.scope }}"
      }
    ],
    "body": {
      "type": "raw",
      "content": {
        "name": "{{ ctx.ci_name }}",
        "timeZone": "{{ context.time_zone }}"
      }
    }
  },
  "network": {
    "proxy": {
      "mode": "CUSTOM",
      "url": "http://proxy.example.com:8080",
      "username": "proxy-user",
      "password": "proxy-password"
    },
    "verify_ssl": true
  },
  "response": {
    "body_type": "json"
  },
  "execution": {
    "timeout_ms": 30000,
    "max_attempts": 3,
    "delay_ms": 1000
  },
  "outputs": [
    {
      "name": "sent_ci_name",
      "type": "string",
      "path": "$.request.body.name"
    },
    {
      "name": "ci_id",
      "type": "string",
      "path": "$.response.body.id"
    },
    {
      "name": "ci_detail",
      "type": "object",
      "path": "$.response.body"
    }
  ]
}
```

#### 与 Run-Time 的字段边界

| Design-Time               | Run-Time                   | 边界                                                              |
| ------------------------- | -------------------------- | ----------------------------------------------------------------- |
| id                        | node_id                    | Run-Time 只引用节点 ID，不修改 ID                                 |
| type                      | type                       | Run-Time 复制 HTTP 类型用于识别记录                               |
| name、description         | 无对应业务字段             | 只用于定义态展示，不作为请求或响应数据                            |
| request                   | request                    | 前者保存模板、常量和 Context 引用；后者保存解析后最终发送的请求   |
| network                   | network                    | 前者保存期望的 Proxy/SSL 配置；后者保存最终实际使用的完整网络配置 |
| response                  | response                   | 前者保存响应 Body 解析类型；后者保存本次实际收到的 HTTP 响应      |
| execution                 | attempt_count、duration_ms | 前者声明超时、重试上限和间隔；后者记录实际请求次数及总耗时        |
| outputs 数组              | outputs 对象               | 前者声明 name/type/path；后者保存提取并成功提交的 name/value      |
| 无 Design-Time inputs     | inputs 对象                | Run-Time 只记录最终请求实际引用的 Context 变量和值                |
| 无 Design-Time 状态和错误 | status、error              | 只由执行过程产生                                                  |
| 无 Design-Time 日志       | 无 Run-Time 字段           | 完整日志、失败堆栈和逐次尝试细节只临时保存                      |

#### 参数列表

| 字段        | 类型   | 取值               | 示例                                                                        | 含义                                              |
| ----------- | ------ | ------------------ | --------------------------------------------------------------------------- | ------------------------------------------------- |
| id          | string | UUIDv4 字符串      | 6ba7b810-9dad-41d1-80b4-00c04fd430c8                                      | 节点在 Workflow 中的唯一标识                      |
| type        | string | HTTP               | HTTP                                                                        | 节点类型为 HTTP 请求                              |
| name        | string | 用户自定义         | 查询 CI 详情                                                                | 画布和日志中显示的节点名称                        |
| description | string | 用户自定义，可为空 | 根据设备名称查询 CMDB                                                       | 节点业务用途说明                                  |
| request     | object | 必填               | {"method":"POST","url":"https://cmdb.example.com/api/ci/{{ ctx.ci_name }}"} | HTTP 请求定义                                     |
| network     | object | 必填               | {"proxy":{"mode":"CUSTOM"},"verify_ssl":true}                               | Proxy 和 SSL 验证配置                             |
| response    | object | 必填               | {"body_type":"json"}                                                          | 响应 Body 解析配置                                |
| execution   | object | 必填               | {"timeout_ms":30000,"max_attempts":3,"delay_ms":1000}                       | 超时和重试参数                                    |
| outputs     | array  | 可为空，默认 []    | [{"name":"ci_id","type":"string","path":"$.response.body.id"}]              | 从 request/response 提取并写入 Context 的输出声明 |

#### request 参数

| 字段    | 类型   | 取值                                         | 示例                                                  | 含义                        |
| ------- | ------ | -------------------------------------------- | ----------------------------------------------------- | --------------------------- |
| method  | string | GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS | POST                                                  | HTTP 请求方法               |
| url     | string | HTTP 或 HTTPS URL                            | https://cmdb.example.com/api/ci/{{ ctx.ci_name }}     | 请求地址，支持 Context 引用 |
| follow_redirects | boolean | true/false，默认 true              | true                                                  | 是否自动跟随 3xx 重定向     |
| headers | array  | 可为空，默认 []                              | [{"key":"Content-Type","value":"application/json"}]   | 请求 Header 列表            |
| params  | array  | 可为空，默认 []                              | [{"key":"scope","value":"{{ ctx.scope }}"}]           | Query 参数列表              |
| body    | object | 必填                                         | {"type":"raw","content":{"name":"{{ ctx.ci_name }}"}} | 请求 Body 定义              |

协议规则：

- HTTP 节点同时支持 http:// 和 https:// 请求地址。
- request.url 只允许 http 和 https 协议，不接受其他 URL scheme。
- request.url 禁止包含 userinfo，不允许 `https://user:password@example.com/api` 等内嵌账号密码形式；认证必须通过 request.headers 配置。静态 URL 在保存和运行前置校验时检查，Context 解析后的最终 URL 在请求发出前再次检查；违反时属于配置错误，不发送请求，也不进入自动重试。
- GET 和 HEAD 请求只允许 body.type=none；配置 raw、form_data 或 form_urlencoded 属于配置错误，Workflow 保存和运行前置校验失败，不创建 NodeRun，也不进入自动重试。其他已支持方法按 body 规则处理。
- request.url 的域名和 path 引用必须指向声明类型为 string 的变量；端口引用允许 string 或 integer，解析后必须是十进制 1～65535。其他类型、非数字端口或越界端口属于配置错误，Workflow 校验失败，不创建 NodeRun，也不执行自动重试。
- request.url 的协议必须是静态 http 或 https，不允许 Context 引用；域名、端口和 path 允许使用 Context 引用。request.url 可以包含不带 Context 引用的静态 Query，并与 request.params 合并；动态 Query 参数必须使用 request.params 配置。静态 Fragment 允许保存，但发送请求前自动删除，Fragment 中不允许 Context 引用；Run-Time request.url 不包含 Fragment。
- 域名包含非 ASCII 字符时按 IDNA 转换为 Punycode；Run-Time request.url 保存转换后的域名，inputs 保留转换前的 Context 原始值。静态域名无法转换时属于配置错误；运行时域名值无法转换时节点失败，error.code 使用 `HTTP_URL_INVALID_HOST`，不自动重试并触发 Fail-Fast。
- Context 字符串插入 URL path 时，按 UTF-8 和 RFC 3986 执行百分号编码；非保留字符保持原样，空格、斜杠、百分号及其他保留字符按路径片段编码。变量值始终视为未编码原始值，已有 `%XX` 序列中的 `%` 仍编码为 `%25`。Run-Time request.url 保存编码后的最终 URL，inputs 保存编码前的 Context 原始值。
- HTTP 与 HTTPS 使用相同的 Context 引用、请求参数、输出提取、Proxy 和重试契约。
- 目标 URL 或实际 Proxy 任一使用 https:// 时，verify_ssl 对对应 TLS 连接生效；只有目标与 Proxy 都不使用 TLS 时才忽略该开关。

#### headers 参数

| 字段  | 类型   | 取值                         | 示例             | 含义                                |
| ----- | ------ | ---------------------------- | ---------------- | ----------------------------------- |
| key   | string | RFC 7230/9110 合法 Header 名 | Content-Type     | Header 名，不支持 Context 引用      |
| value | string | RFC 7230/9110 合法 Header 值 | application/json | Header 值，支持 Context 引用        |

Header 规则：

- request.headers[].value 的 Design-Time 类型必须是 string；非字符串值属于配置错误，不进行运行时类型转换。
- Header value 中的 Context 引用必须指向声明类型为 string 的变量；引用 number、integer、boolean、object、array 或 null 类型变量时，Workflow 校验失败。
- Header 名和值必须符合 RFC 7230/9110；Header 名不是合法 token，或值中包含 CR、LF 等非法控制字符时，Workflow 校验失败。
- request.headers 的 Header 名按大小写不敏感规则检查唯一性；归一化后重复的 Header 名属于配置错误，error.code 使用 `HTTP_HEADER_DUPLICATE`。例如 `X-Trace` 与 `x-trace` 不能同时配置，平台不自动合并或发送多个同名请求 Header 行。
- body.type 为 form_data 或 form_urlencoded 时，Content-Type 由平台管理，Design-Time request.headers 不允许配置 Content-Type；发现时属于配置错误。form_data 在每次 HTTP 尝试中自动生成 multipart/form-data Content-Type 及匹配的 boundary，form_urlencoded 自动生成 application/x-www-form-urlencoded Content-Type。最终实际值记录在 Run-Time request.headers 中。
- Header 配置错误在保存或运行前置校验阶段发现，不创建 NodeRun，也不进入自动重试。

#### params 参数

| 字段  | 类型       | 取值                                   | 示例       | 含义                                   |
| ----- | ---------- | -------------------------------------- | ---------- | -------------------------------------- |
| key   | string     | 非空字符串                             | scope      | Query 参数名，不支持 Context 引用      |
| value | JSON scalar | string、number、integer、boolean、null | USER_SCOPE | Query 参数值，支持 Context 引用        |

Query 参数规则：

- request.params[].value 只允许 string、number、integer、boolean 或 null，不允许 object 或 array。
- string 按原值发送；number/integer、boolean 和 null 转换为 JSON 字面量字符串，例如 `3`、`true`、`null`。
- Context 引用必须指向允许的标量类型；引用 object 或 array 类型变量时，Workflow 校验失败，属于配置错误，不创建 NodeRun，也不进入自动重试。
- Query 参数值始终视为未编码原值，并使用 UTF-8 的标准 application/x-www-form-urlencoded 编码；空格编码为 `+`，已有 `+` 编码为 `%2B`，已有 `%XX` 中的 `%` 编码为 `%25`，其他需要转义的字节执行百分号编码。重复参数保持数组中的配置顺序。
- 合并静态 Query 与 request.params 时，request.params 按 key 精确匹配并覆盖静态 Query 中的全部同名项；key 区分大小写。未冲突的静态参数保留，request.params 自身的重复项按配置顺序全部保留。

headers 和 params 使用数组而不是对象，以保留配置顺序；params 允许同名项，headers 按上述规则禁止大小写归一后的同名项。

#### body 参数

| 字段    | 类型       | 取值                                          | 示例                         | 含义                         |
| ------- | ---------- | --------------------------------------------- | ---------------------------- | ---------------------------- |
| type    | string     | none、raw、form_data、form_urlencoded         | raw                          | Body 类型                    |
| content | JSON value | 根据 type 决定                                | {"name":"{{ ctx.ci_name }}"} | Body 内容，支持 Context 引用 |

| body.type       | content                                 |
| --------------- | --------------------------------------- |
| none            | null                                    |
| raw             | 字符串、对象、数组或其他 JSON 值        |
| form_data       | key/value 数组，value 支持 Context 引用 |
| form_urlencoded | key/value 数组，value 支持 Context 引用 |

raw 序列化规则：

- content 为 object 或 array 时，平台递归遍历其中所有字符串值并解析 Context 引用；对象 key 不执行模板解析或改写。
- 任一字符串值完整等于一个 Context 引用时，该位置替换为 Context 原始 JSON 值，因此可以形成嵌套 object、array、number、integer、boolean 或 null；引用嵌入普通文本时按第三章规则转换为字符串。
- content 为 string 时，按 UTF-8 原文发送，不追加引号或执行 JSON 转义。
- content 为 object、array、number、integer、boolean 或 null 时，按紧凑 JSON 序列化后以 UTF-8 发送。
- 平台不根据 content 类型自动添加或修改 Content-Type；Content-Type 完全由用户在 request.headers 中配置。

#### form_data/form_urlencoded content 参数

| 字段  | 类型       | 取值         | 示例              | 含义                            |
| ----- | ---------- | ------------ | ----------------- | ------------------------------- |
| key   | string     | 非空字符串   | name              | 表单字段名，不支持 Context 引用 |
| value | JSON value | 合法 JSON 值 | {{ ctx.ci_name }} | 表单字段值，支持 Context 引用   |

表单 value 序列化规则：

- 平台递归扫描 form_data/form_urlencoded content 数组中每一项的 value 并解析其中的 Context 引用；表单字段 key 不执行模板解析或改写。value 内部为 object 或 array 时，同样递归处理其中所有字符串值。
- value 为 string 时按原值编码。
- value 为 object 或 array 时，先转换为紧凑 JSON 字符串，再按对应的 multipart/form-data 或 application/x-www-form-urlencoded 规则编码。
- value 为 number、integer、boolean 或 null 时，转换为 JSON 字面量字符串，例如 `3`、`true`、`null`，再按对应表单规则编码。
- 当前 form_data 只生成普通文本字段，不支持文件、文件路径、Base64 文件描述、二进制 Part、文件名或 Part Content-Type 等文件上传语义。字符串形式的本机路径只作为普通文本发送，平台不得读取文件系统；object/array 仍只按上述规则序列化为 JSON 文本。

#### network 参数

```json
{
  "proxy": {
    "mode": "SYSTEM",
    "url": null,
    "username": null,
    "password": null
  },
  "verify_ssl": true
}
```

| 字段       | 类型    | 取值                  | 示例                                                    | 含义                        |
| ---------- | ------- | --------------------- | ------------------------------------------------------- | --------------------------- |
| proxy      | object  | 必填                  | {"mode":"CUSTOM","url":"http://proxy.example.com:8080"} | Proxy 配置                  |
| verify_ssl | boolean | true/false，默认 true | true                                                    | 是否验证目标 HTTPS 服务及 HTTPS Proxy 的 TLS 证书 |

#### proxy 参数

| 字段     | 类型        | 取值                                | 示例                          | 含义                           |
| -------- | ----------- | ----------------------------------- | ----------------------------- | ------------------------------ |
| mode     | string      | SYSTEM、DIRECT、CUSTOM，默认 SYSTEM | CUSTOM                        | Proxy 模式                     |
| url      | string/null | CUSTOM 时必填                       | http://proxy.example.com:8080 | 自定义代理地址                 |
| username | string/null | CUSTOM 时可选                       | proxy-user                    | 自定义代理用户名，允许直接保存 |
| password | string/null | CUSTOM 时可选                       | proxy-password                | 自定义代理密码，允许直接保存   |

| mode   | 行为                                                                 |
| ------ | -------------------------------------------------------------------- |
| SYSTEM | 使用运行进程的系统代理环境，包括 HTTP_PROXY、HTTPS_PROXY 和 NO_PROXY |
| DIRECT | 禁用系统代理，直接连接目标地址                                       |
| CUSTOM | 只使用本节点配置的 proxy.url，不读取系统代理                         |

网络规则：

- 不根据公网 IP、内网 IP、域名或请求失败情况自动切换 Proxy 模式。
- SYSTEM 和 DIRECT 模式下，proxy.url、proxy.username、proxy.password 必须为 null。
- CUSTOM 模式下，proxy.url 必须是合法的 http:// 或 https:// 代理地址，只允许 HTTP 和 HTTPS scheme；SOCKS 及其他协议不受支持。proxy.url 禁止包含 userinfo，不允许使用 `http://user:password@host` 形式；认证只通过独立的 username 和 password 字段配置，两者可以为空。
- CUSTOM 代理连接失败时，不自动回退到 SYSTEM 或 DIRECT。
- verify_ssl 与 Proxy 模式相互独立。
- verify_ssl 是节点唯一的 TLS 证书验证开关，同时控制目标 HTTPS 服务和实际使用的 HTTPS Proxy。verify_ssl 为 true 时两者均执行证书验证；为 false 时两者均关闭证书验证，不提供独立的 Proxy SSL 开关。
- http:// 目标本身不使用 TLS；但通过 https:// Proxy 访问时，verify_ssl 仍控制 Proxy TLS 证书验证。目标与 Proxy 都不使用 TLS 时，运行时忽略 verify_ssl 但保留 Design-Time 配置值。
- verify_ssl 为 false 时不改变 Proxy 选择。
- verify_ssl 为 false 时，界面持续显示非阻断式安全提示，不阻止保存或运行。

#### response 配置参数

| 字段      | 类型   | 取值                 | 示例 | 含义                       |
| --------- | ------ | -------------------- | ---- | -------------------------- |
| body_type | string | json、text、binary，默认 json | json | 响应 Body 的显式解析类型   |

响应解析规则：

- body_type 为 json 时，零字节 Body 或去除首尾空白后为空的 Body 记录为 null，节点可以继续成功；2xx 响应的其他 Body 必须能够解析为严格 JSON，解析失败时节点失败，error.code 使用 `HTTP_RESPONSE_JSON_INVALID`，不执行自动重试，并触发 Fail-Fast。非 2xx 的 JSON 回退规则见 Run-Time 章节。
- body_type 为 text 时，优先使用响应 Content-Type 中声明的 charset 解码；未声明 charset 时使用 UTF-8，不执行 JSON 解析。
- body_type 为 text 且响应 Body 为零字节时，response.body 记录为空字符串 `""`。
- 2xx 响应的 charset 不受支持或内容无法按选定编码解码时，HTTP 节点失败，error.code 使用 `HTTP_RESPONSE_DECODE_ERROR`，不执行自动重试，并触发 Fail-Fast；不使用替换字符，也不回退其他编码。非 2xx 的解码失败规则见 Run-Time 章节。
- body_type 为 binary 时，HTTP Content-Encoding 解压后的 Body 字节按标准 Base64 编码；Run-Time response.body 只保存不含 Data URI、MIME 前缀或换行的纯 Base64 字符串，不保存传输层压缩字节。
- body_type 为 binary 且响应 Body 为零字节时，response.body 记录为空字符串 `""`。
- json、text 和 binary 响应统一按 HTTP Content-Encoding 解压后的 Body 字节数计算，最大允许 10,485,760 bytes（10 MB）；传输层压缩字节数不作为限制依据。平台必须在接收和解压过程中持续检查上限，超过上限时立即停止读取与解压，节点失败，error.code 使用 `HTTP_RESPONSE_TOO_LARGE`。该错误优先于 HTTP_STATUS_ERROR，不执行自动重试，不保存截断内容，并触发 Fail-Fast；已收到的 status_code 和 headers 可以保留，response.body 记录为 null。解压后的 Body 再进入 JSON 解析、文本解码或 Base64 编码。
- Content-Encoding 不受支持、压缩数据损坏或解压过程失败时，节点使用 `HTTP_RESPONSE_CONTENT_ENCODING_ERROR`，不回退保存压缩原始字节，也不执行自动重试。该错误优先于 HTTP_STATUS_ERROR；已收到的 status_code 和 headers 保留，response.body_type 记录 Design-Time 配置值，response.body 为 null，并触发 Fail-Fast。
- 平台不根据响应 Content-Type 自动选择或覆盖 body_type。

#### execution 参数

| 字段         | 类型 | 取值     | 示例  | 含义                             |
| ------------ | ---- | -------- | ----- | -------------------------------- |
| timeout_ms   | int  | 大于 0   | 30000 | 单次 HTTP 完整尝试超时时间，包含请求处理和全部重定向，单位毫秒 |
| max_attempts | int  | 0~10     | 3     | 最大重试次数，不包含首次请求     |
| delay_ms     | int  | 0~600000 | 1000  | 两次重试之间的固定间隔，单位毫秒 |

max_attempts 和 delay_ms 的语义与 SCRIPT 节点一致。

#### outputs 参数

| 字段 | 类型   | 取值                                                  | 示例               | 含义                                           |
| ---- | ------ | ----------------------------------------------------- | ------------------ | ---------------------------------------------- |
| name | string | 合法变量名，且在本节点内唯一                          | ci_id              | 成功后写入 Context 的变量名                    |
| type | string | string、number、integer、boolean、object、array、null | string             | 输出变量声明类型                               |
| path | string | 受限 JSONPath：对象字段和数组下标                       | $.response.body.id | 从标准 request/response 提取根对象中读取变量值 |

path 必须以 $.request 或 $.response 开头，只允许对象字段访问和数组下标访问；不支持通配符、过滤器、表达式、函数或隐式 Body 路径。

#### 敏感 Header

- 不建设统一凭据管理，HTTP 节点不定义 credential_id。
- 目标 API 的认证信息统一通过 request.headers 配置。
- CUSTOM Proxy 的认证信息只通过 network.proxy.username 和 network.proxy.password 配置。
- 直接填写 Authorization、Proxy-Authorization、Cookie、Set-Cookie、X-API-Key、API-Key 等敏感 Header 时，界面显示非阻断式警告。
- 警告只用于提示，不弹出确认框，不阻止保存或运行。
- 敏感 Header 在 Run-Time、日志和界面中均展示原值，不进行脱敏。
- Workflow 导出和运行记录持久化可以包含明文敏感信息。

<a id="chapter-8-2"></a>

### 8.2 Run-Time

Run-Time 保存某次 Workflow Run 中 HTTP 节点最终发生的执行事实：引用输入、网络配置、最终请求、响应、重试次数、输出、状态和错误。它不保存可编辑模板，也不保存日志或日志引用，不反向修改 Design-Time。

#### Run-Time 示例

```json
{
  "run_id": "8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10",
  "node_run_id": "3c363836-2f4a-4b6f-9f4c-1e7a8d5b2c22",
  "node_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
  "type": "HTTP",
  "status": "SUCCESS",
  "started_at": "2026-07-24 23:11:50",
  "finished_at": "2026-07-24 23:11:51",
  "duration_ms": 1000,
  "attempt_count": 2,
  "inputs": {
        "ci_name": "SWITCH_1.100.2.142",
        "api_token": "demo-token",
        "scope": "USER_SCOPE",
        "time_zone": "Asia/Shanghai"
      },
  "network": {
        "proxy": {
          "mode": "CUSTOM",
          "url": "http://proxy.example.com:8080",
          "username": "proxy-user",
          "password": "proxy-password"
        },
        "verify_ssl": true
      },
  "request": {
        "method": "POST",
        "url": "https://cmdb.example.com/api/ci/SWITCH_1.100.2.142",
        "follow_redirects": true,
        "body_type": "raw",
        "headers": [
          {
            "key": "content-type",
            "value": "application/json"
          },
          {
            "key": "authorization",
            "value": "Bearer demo-token"
          }
        ],
        "params": [
          {
            "key": "scope",
            "value": "USER_SCOPE"
          }
        ],
        "body": {
          "name": "SWITCH_1.100.2.142",
        "timeZone": "Asia/Shanghai"
      }
      },
  "redirects": [],
  "response": {
        "status_code": 200,
        "headers": {
          "content-type": "application/json",
          "set-cookie": [
            "session=a",
            "route=b"
          ]
        },
        "body_type": "json",
        "body": {
          "id": "ci-001",
          "name": "SWITCH_1.100.2.142"
        }
      },
  "outputs": {
        "sent_ci_name": "SWITCH_1.100.2.142",
        "ci_id": "ci-001",
        "ci_detail": {
          "id": "ci-001",
          "name": "SWITCH_1.100.2.142"
        }
      },
  "error": null
}
```

#### 参数列表

| 字段          | 类型        | 取值                                                           | 示例                  | 含义                                       |
| ------------- | ----------- | -------------------------------------------------------------- | --------------------- | ------------------------------------------ |
| run_id        | string      | UUIDv4 字符串                                                  | 8f14e45f-ea67-4a2f-9f4b-5e4c7c3b2a10 | 本次 Workflow Run 的唯一标识               |
| node_run_id   | string      | UUIDv4 字符串                                                  | 3c363836-2f4a-4b6f-9f4c-1e7a8d5b2c22 | 本次节点运行记录的唯一标识                 |
| node_id       | string      | UUIDv4 字符串                                                  | 6ba7b810-9dad-41d1-80b4-00c04fd430c8 | Design-Time 节点 ID                        |
| type          | string      | HTTP                                                           | HTTP                  | 节点类型                                   |
| status        | string      | PENDING、RUNNING、SUCCESS、FAILED、TIMEOUT、CANCELLED          | SUCCESS               | 节点当前或最终状态                         |
| started_at    | string/null | YYYY-MM-DD HH:mm:ss 或 null                                    | 2026-07-24 23:11:50   | 进入 RUNNING 的时间；PENDING 时为 null      |
| finished_at   | string/null | YYYY-MM-DD HH:mm:ss 或 null                                    | 2026-07-24 23:11:51   | 节点最终结束时间；尚未结束时为 null        |
| duration_ms   | int/null    | 大于等于 0 或 null                                             | 1000                  | 节点总耗时，单位毫秒；尚未结束时为 null    |
| attempt_count | int         | 大于等于 0                                                     | 2                     | 逻辑调用次数，包含首次调用和重试，不包含重定向；未开始时为 0 |
| inputs        | object      | 变量名到 JSON 值的映射                                        | {"ci_name":"SWITCH_1.100.2.142"} | 最终逻辑调用实际引用的 Context 变量和值     |
| network       | object/null | network 对象或 null                                            | {"proxy":{"mode":"CUSTOM"},"verify_ssl":true} | 最终逻辑调用实际使用的网络配置；尚未解析时为 null |
| request       | object/null | request 对象或 null                                            | {"method":"POST","url":"https://cmdb.example.com/api/ci"} | 最终一跳实际发送的请求                      |
| redirects     | array       | 可为空，默认 []                                                | []                    | 按顺序记录最终响应前的 3xx 请求与响应      |
| response      | object/null | response 对象或 null                                           | {"status_code":200,"body_type":"json","body":{}} | 最终实际响应                                |
| outputs       | object      | 变量名到 JSON 值的映射，默认 {}                                | {"ci_id":"ci-001"} | 成功后提交到 Context 的变量                 |
| error         | object/null | error 对象或 null                                              | null                  | 最终逻辑调用错误；成功时为 null             |

#### network 参数

| 字段       | 类型    | 取值       | 示例                                                    | 含义                      |
| ---------- | ------- | ---------- | ------------------------------------------------------- | ------------------------- |
| proxy      | object  | proxy 对象 | {"mode":"CUSTOM","url":"http://proxy.example.com:8080"} | 本次实际使用的 Proxy 配置 |
| verify_ssl | boolean | true/false | true                                                    | 本次请求是否验证 SSL 证书 |

#### proxy 参数

| 字段     | 类型        | 取值                   | 示例                          | 含义                             |
| -------- | ----------- | ---------------------- | ----------------------------- | -------------------------------- |
| mode     | string      | SYSTEM、DIRECT、CUSTOM | CUSTOM                        | 本次实际使用的 Proxy 模式        |
| url      | string/null | 代理 URL 或 null       | http://proxy.example.com:8080 | 本次实际使用的自定义代理地址     |
| username | string/null | 用户名或 null          | proxy-user                    | 本次实际使用的代理用户名，不脱敏 |
| password | string/null | 密码或 null            | proxy-password                | 本次实际使用的代理密码，不脱敏   |

#### request 参数

| 字段    | 类型       | 取值                                         | 示例                                                | 含义                             |
| ------- | ---------- | -------------------------------------------- | --------------------------------------------------- | -------------------------------- |
| method  | string     | GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS | POST                                                | 实际发送的 HTTP 方法             |
| url     | string     | 完整 HTTP/HTTPS URL                          | https://cmdb.example.com/api/ci/SWITCH_1.100.2.142  | Context 解析、Query 合并并编码后的实际完整 URL |
| follow_redirects | boolean | true/false                              | true                                                | 本次请求是否自动跟随 3xx 重定向  |
| body_type | string     | none、raw、form_data、form_urlencoded        | raw                                                 | 本次实际发送的请求 Body 类型     |
| headers | array      | key/value 数组                               | [{"key":"content-type","value":"application/json"}] | 实际发送的全部 Header，包含客户端自动生成项，敏感值不脱敏 |
| params  | array      | key/value 数组                               | [{"key":"scope","value":"USER_SCOPE"}]              | 静态 Query 与 request.params 合并后的最终结构化参数 |
| body    | JSON value | 合法 JSON 值                                 | {"name":"SWITCH_1.100.2.142"}                       | Context 引用解析后的请求 Body；body_type 为 none 时是 null |

request.body 的 Run-Time 形状由 body_type 决定：

| body_type       | request.body Run-Time 形状                                              |
| --------------- | ----------------------------------------------------------------------- |
| none            | null                                                                    |
| raw             | Context 解析后的 JSON 值                                                |
| form_data       | Context 解析后的 key/value 数组，保留配置顺序和重复 key                |
| form_urlencoded | Context 解析后的 key/value 数组，保留配置顺序和重复 key                |

form_data 和 form_urlencoded 的 Run-Time body 不保存 multipart boundary、编码后的字符串或 Wire 字节。数组 value 保留 Context 解析后的 JSON 类型，实际发送前再按 Design-Time 规则转换为表单文本；request.url 和 request.headers 记录最终编码及自动 Content-Type 事实。

#### request.headers 参数

| 字段  | 类型   | 取值                       | 示例             | 含义                         |
| ----- | ------ | -------------------------- | ---------------- | ---------------------------- |
| key   | string | 小写 RFC 7230/9110 合法 Header 名 | content-type | 实际请求 Header 名           |
| value | string | RFC 7230/9110 合法 Header 值 | application/json | 实际发送的 Header 值         |

#### request.params 参数

| 字段  | 类型   | 取值       | 示例       | 含义                           |
| ----- | ------ | ---------- | ---------- | ------------------------------ |
| key   | string | 非空字符串 | scope      | 实际发送的 Query 参数名        |
| value | string | 字符串     | USER_SCOPE | 实际编码并发送的 Query 参数值  |

#### response 参数

| 字段        | 类型       | 取值                  | 示例                                        | 含义                                                   |
| ----------- | ---------- | --------------------- | ------------------------------------------- | ------------------------------------------------------ |
| status_code | int        | 100~599               | 200                                         | HTTP 响应状态码                                        |
| headers     | object     | Header 名到 string 或 string 数组的映射 | {"content-type":"application/json","set-cookie":["session=a","route=b"]} | 完整响应 Header；同名 Header 的多个值保存为数组 |
| body_type   | string     | json、text、binary    | json                                        | 本次实际使用的响应 Body 解析类型                       |
| body        | JSON value | JSON 值或字符串       | {"id":"ci-001","name":"SWITCH_1.100.2.142"} | json 为解析值；text 为文本；binary 为 Base64 字符串    |

#### redirects 参数

redirects 中每一项记录一次产生 3xx 的请求和对应响应，按实际跳转顺序排列：

| 字段    | 类型   | 取值          | 示例                                             | 含义                              |
| ------- | ------ | ------------- | ------------------------------------------------ | --------------------------------- |
| request  | object | request 对象                                | {"method":"GET","url":"https://a.example"} | 产生本次 3xx 响应的实际请求       |
| response | object | 只包含 status_code 和 headers 的响应对象   | {"status_code":302,"headers":{"location":"https://b.example"}} | 本次 3xx 响应，不保存 Body        |

顶层 request 和 response 保存重定向完成后的最终一跳请求与响应；无重定向时 redirects 为 []，顶层 request 即初始请求。
redirects[].response 不包含 body_type 或 body，不读取也不解析中间 3xx Body；Design-Time response.body_type 只用于最终响应。

#### error 参数

| 字段    | 类型        | 取值                    | 示例          | 含义                         |
| ------- | ----------- | ----------------------- | ------------- | ---------------------------- |
| code    | string      | 稳定错误码              | HTTP_TIMEOUT  | 机器可读错误码               |
| message | string      | 非空字符串              | HTTP 请求超时 | 面向用户的错误说明           |
| details | object/null | 结构化 JSON 对象或 null | null          | 可选诊断信息，不写入 Context |

#### Run-Time 规则

输入与请求：

- inputs 只记录 request.url、request.headers[].value、request.params[].value 和 request.body.content 实际引用过的 Context 变量。
- Context 根变量或嵌套路径存在性预检失败时，NodeRun 按通用规则以 attempt_count=0 从 PENDING 直接转为 FAILED，request 和 response 都为 null。
- 请求已完成解析但未收到响应时，保留 request，response 为 null。
- request 记录实际发送值；request.headers 包含最终 HTTP 消息中用户配置、Cookie 处理以及客户端自动生成的全部 Header，例如 host、content-length、content-type boundary 和 accept-encoding。自动生成字段与用户配置发生覆盖关系时，只记录客户端最终实际发送的有效值；敏感 Header 不脱敏。
- request.body_type 记录该跳实际使用的 Body 类型；body_type 为 none 时 request.body 固定为 null。301、302、303 重定向将请求改为 GET 并移除 Body 时，后续请求的 body_type 记录为 none；redirects[].request 使用相同规则。
- Run-Time request.headers[].key 统一转换为小写；Design-Time 保留用户填写的 Header 名大小写，redirects[].request 使用相同的小写记录规则。
- request.url 保存合并并编码后的完整实际 URL；request.params 保存该跳实际 URL 携带的完整结构化 Query 参数列表，两者允许重复表达 Query 以兼顾精确请求追踪和结构化提取。
- 初始请求的 request.params 来自静态 Query 与 Design-Time params 的合并结果；每次重定向后，redirects[].request.params 和顶层最终 request.params 都从该跳实际 URL 重新形成，包含 Location 新增、删除或替换的全部 Query 参数，并保留实际顺序和重复 key。request.url 是精确百分号编码的权威值，request.params 是按 UTF-8 application/x-www-form-urlencoded 规则解码后的 key/value 字符串列表。
- network 记录完整 Proxy 配置；proxy.username 和 proxy.password 不脱敏。

响应与输出：

- 只有 HTTP 状态码 200~299 表示本次请求成功。
- 1xx、3xx、4xx 和 5xx 响应均表示本次请求失败，error.code 使用 `HTTP_STATUS_ERROR`，但必须保留 response。
- follow_redirects 为 false 时不跟随 3xx，直接按失败响应处理；为 true 时允许自动跟随重定向。
- follow_redirects 为 true 时最多跟随 10 次；超过上限时节点失败，error.code 使用 `HTTP_TOO_MANY_REDIRECTS`，不执行自动重试，并触发 Fail-Fast。
- 重定向到不同协议、域名或端口时，原请求 Header 全部原样转发，包括 Authorization、Cookie 和其他敏感 Header；平台不自动剥离或脱敏。
- 重定向方法采用标准客户端行为：301、302、303 可以将 POST 改为 GET 并移除请求 Body；307、308 保持原请求方法和 Body。redirects[].request 必须记录每一跳实际发送的方法和 Body。
- 重定向响应中的 Set-Cookie 按标准 HTTP Cookie 规则处理，并根据 Domain、Path、Secure 等属性决定后续跳转是否携带；redirects[].request 和顶层 request 记录实际发送的 Cookie Header。
- 禁止从 HTTPS 重定向到 HTTP；检测到降级 Location 后不发送下一跳请求，节点失败，error.code 使用 `HTTP_REDIRECT_DOWNGRADE_BLOCKED`，不执行自动重试，并触发 Fail-Fast。HTTP 重定向到 HTTPS 允许正常跟随。
- Location 允许使用相对 URL，并基于产生该 3xx 的当前请求 URL 解析为绝对地址；无法解析为合法 HTTP/HTTPS URL 时节点失败，error.code 使用 `HTTP_REDIRECT_INVALID_LOCATION`，不执行自动重试，并触发 Fail-Fast。
- request 和 response 是 HTTP 请求与响应在 Run-Time 中的唯一标准记录。
- redirects 按顺序保存重定向链中的 3xx 请求和响应；顶层 request/response 保存最终一跳。
- response.headers 的 Header 名统一转换为小写，并按大小写不敏感规则归并；单值 Header 保存为 string，同名 Header 的多个值按接收顺序保存为 string 数组。
- Run-Time 不定义额外的原始请求、原始响应引用字段，也不定义独立的原始 Body 字段。
- 每次 HTTP 尝试及重定向的临时日志都使用与 Run-Time 相同的结构化 request/response 形状记录当次事实；最终尝试结束后，仅最终事实写入 Run-Time。平台不单独持久化另一份原始请求、原始响应或 Wire Body。
- response.body 按 Design-Time response.body_type 解析；平台不根据 Content-Type 自动判断。
- 非 2xx 响应优先保留 HTTP 状态错误；当配置 body_type=json 但 Body 无法解析为 JSON 时，回退为 text，按文本字符编码规则保存 Body，并将 Run-Time response.body_type 记录为 text，不改写 `HTTP_STATUS_ERROR` 为 JSON 解析错误。
- 非 2xx 响应按 text 规则解码仍失败时，继续保留 `HTTP_STATUS_ERROR`，response.body_type 记录为 text，response.body 记录为 null；不改写为 `HTTP_RESPONSE_DECODE_ERROR`。
- json 响应解析后不保证保留原始空格、换行、字段顺序或数字文本格式；text 保存解码后的文本；binary 保存 HTTP Content-Encoding 解压后 Body 字节的 Base64 字符串。
- 收到成功响应后，再按照 Design-Time outputs.path 提取声明输出。
- 输出提取失败时，最终执行失败，保留 request 和 response，但 outputs 为 {}。
- 输出提交前必须检查所有声明输出的 name 是否已存在于 Context；任一 name 已存在时，outputs 整体不提交，节点失败并中断 Workflow Run。
- JSONPath 提取值必须符合 outputs.type 声明；类型不匹配时，outputs 整体不提交，节点失败并触发 Fail-Fast，不自动转换类型，也不写入 null。
- 只有最终成功的 outputs 才批量写入 Context。
- 请求失败、超时、中断或输出处理失败时，outputs 必须为 {}。

重试：

- execution.max_attempts 表示最多重试次数，不包含首次请求。
- timeout_ms 对一次完整 HTTP 尝试使用单一截止时间：在 Context 根变量和嵌套路径存在性预检通过后，计时覆盖实际 Context 替换、URL 与 Body 序列化、DNS、Proxy、TCP/TLS、请求发送、全部重定向、响应 Body 完整接收与解压、响应解析和 outputs.path 提取。预检失败按通用规则以 attempt_count=0 结束；进入重试后重新开始 timeout_ms 计时。
- 重试前的 delay_ms 或 Retry-After 等待不计入任一次 timeout_ms，但计入 NodeRun.duration_ms。
- 自动重试只适用于 GET、HEAD、OPTIONS、PUT、DELETE 幂等方法。
- POST 和 PATCH 不自动重试，即使 max_attempts 大于 0。
- 幂等方法仅在连接失败、请求超时、HTTP 408、HTTP 429、HTTP 500、HTTP 502、HTTP 503、HTTP 504 时自动重试。
- HTTP 429 或 503 提供合法 Retry-After 时优先按该值等待；同时支持十进制秒数和 RFC 9110 HTTP 日期格式，日期已过期时等待 0 ms。无效或未提供 Retry-After 时使用节点 Design-Time 的 delay_ms。最终等待时间最大不超过该节点的 timeout_ms。重试等待时间计入 NodeRun.duration_ms，但不计入单次 timeout_ms。
- 其他 HTTP 状态、Context 引用错误、SSL 验证错误、配置错误、重定向错误、响应过大、响应 JSON 解析错误、文本解码错误和输出提取错误不自动重试。
- attempt_count 记录首次调用和重试形成的逻辑调用次数，不包含重定向产生的网络请求；重定向次数由 redirects.length 表示。
- 仅保留最终逻辑调用的 inputs、network、request、redirects、response、outputs 和 error。
- duration_ms 包含重试等待时间；中间失败但后续成功时，NodeRun.status 最终为 SUCCESS。
- 全部请求失败时，Context 保持节点执行前状态。

<a id="chapter-8-3"></a>

### 8.3 Input & Output Protocol

#### Context 输入

以下 HTTP 配置字段支持第三章定义的统一 Context 引用格式：

```text
request.url
request.headers[].value
request.params[].value
request.body.content
```

request.headers[].key 和 request.params[].key 不支持 Context 引用。

引用规则：

- {{ context.variable_name }} 与 {{ ctx.variable_name }} 等价。
- {{ ctx.ci_name }} 与 {{ctx.ci_name}} 等价，双花括号内侧的首尾空白不影响解析。
- 支持对象字段和数组下标访问。
- request.body.content 为 string 时直接解析；为 object 或 array 时递归解析所有字符串值，对象 key 和表单字段 key 始终保持原文。Workflow 静态引用校验必须扫描整个 content 树中的所有字符串值。
- request.body.content 或其任一字符串值完整等于一个引用时保留 Context 原始 JSON 类型；request.url 的域名和 path、Header value 必须解析为 string，端口允许 string 或 integer，Query 参数允许的标量最终转换为 string。
- 引用嵌入文本时转换为文本；对象和数组转换为紧凑 JSON。
- 变量或嵌套路径不存在时，HTTP 节点在发出请求前失败。
- {{ variable_name }} 保持普通文本，不作为 Context 引用。

#### request/response 与输出提取

outputs.path 使用受限 JSONPath，并从以下统一根对象中读取。路径只允许对象字段和数组下标访问：

```json
{
  "request": {
    "method": "POST",
    "url": "https://cmdb.example.com/api/ci",
    "body_type": "raw",
    "headers": [],
    "params": [],
    "body": {
      "name": "SWITCH_1.100.2.142"
    }
  },
  "response": {
    "status_code": 200,
    "headers": {
      "content-type": "application/json"
    },
    "body": {
      "id": "ci-001"
    }
  }
}
```

| path                   | 提取内容                 |
| ---------------------- | ------------------------ |
| $.request.method       | 实际请求方法             |
| $.request.url          | Context 解析后的最终 URL |
| $.request.body_type    | 实际请求 Body 类型       |
| $.request.body.name    | 实际请求 Body 中的 name  |
| $.response.status_code | HTTP 状态码              |
| $.response.headers     | 完整响应 Header          |
| $.response.body        | 完整响应 Body            |
| $.response.body.id     | JSON 响应 Body 中的 id   |

$.response.body.id 与 $.response.id 不等价。平台不会在字段不存在时自动转入 response.body 查找。

只有 HTTP 节点最终成功，声明的 outputs 才写入 Context。JSONPath 找不到值时使用 `HTTP_OUTPUT_PATH_NOT_FOUND`；提取值与 outputs.type 不匹配时使用 `HTTP_OUTPUT_TYPE_MISMATCH`。两类错误都使 outputs 整体不提交，并触发 Fail-Fast。

<a id="chapter-9"></a>

## 9. END

<a id="chapter-9-1"></a>

### 9.1 Design-Time

END 是可选的系统终点标记，用于显式表达 Workflow 的汇聚终点。每个 Workflow 最多配置一个 END；END 不允许出边，配置 END 时每个业务节点都必须存在一条可到达 END 的有向路径。

#### Design-Time 示例

```json
{
  "id": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "type": "END",
  "name": "结束",
  "description": "工作流终点"
}
```

#### 参数列表

| 字段 | 类型 | 取值 | 示例 | 含义 |
| --- | --- | --- | --- | --- |
| id | string | UUIDv4 字符串 | 0f8fad5b-d9cb-469f-a165-70867728950e | END 节点在 Workflow 内的唯一标识 |
| type | string | END | END | 系统终点节点类型 |
| name | string | 用户自定义 | 结束 | 画布和日志展示名称 |
| description | string | 用户自定义，可为空 | 工作流终点 | 节点业务用途说明 |

END 不声明 inputs、outputs、execution、重试、超时或其他执行配置。

<a id="chapter-9-2"></a>

### 9.2 Run-Time

END 不执行用户代码或网络调用，不创建 NodeRun，也不进入 PENDING、RUNNING、SUCCESS、FAILED、TIMEOUT 或 CANCELLED。END 可达且全部前置业务节点成功后，由调度器完成 Workflow Run 的成功判定。

<a id="chapter-9-3"></a>

### 9.3 Input & Output Protocol

END 不读取 Context，不声明 outputs，也不写入 Context。Workflow 级结果读取协议当前未定义，不得把 END 隐式解释为结果聚合节点。

<a id="chapter-10"></a>

## 10. Workflow 结构与调度约束

<a id="chapter-10-1"></a>

### 10.1 图结构约束

- Workflow 可以配置专门的 START 系统节点；当前阶段 START 仅用于变量输入，用户在节点中逐项填写 key 和 value，START 成功后将这些变量一次性写入当前 Context，后续节点才能读取这些变量。
- 每个 Workflow 最多配置一个 START 节点；配置多个 START 节点时，Workflow 校验失败，不允许保存或运行。
- START 必须是入口节点，不允许存在入边；任何指向 START 的连线都会使 Workflow 校验失败。
- END 节点可选；未配置 END 时，START（如有）和全部业务节点均进入终态后，Workflow Run 即结束。
- 每个 Workflow 最多配置一个 END 节点；配置多个 END 节点时，Workflow 校验失败，不允许保存或运行。
- END 必须是终点节点，不允许存在出边；任何从 END 发出的连线都会使 Workflow 校验失败。
- 配置 END 时，每个业务节点都必须存在一条可到达 END 的有向路径；存在未连接到 END 的终点分支或子图时，Workflow 校验失败。
- END 不创建 NodeRun，只作为 Workflow 的结束标记；Workflow Run 结束时间在 END 可达且其前置节点完成后记录。
- Workflow 图不允许循环依赖，也不允许同时没有入边和出边的完全游离节点；仅包含一个业务节点且没有 START/END 时，作为单节点 Workflow 特例允许保存和运行。允许多个并行根节点；未配置 END 时允许多个互不连通但各自至少包含一条边的 DAG 子图。
- Workflow 至少必须包含一个 SCRIPT、HTTP、LLM 或后续 AGENT 业务节点；只有 START/END 或完全空的 Workflow 校验失败。
- 当前 START 不定义外部字段映射，也不承担外部任务下发协议；后续外部任务入口能力另行定义。
- START 配置校验失败时不创建 Workflow Run；START 在 Run 中发生执行前动态错误或执行失败时不启动业务节点，并按 Fail-Fast 规则终止 Workflow Run；未配置 START 时，Context 保持为空，除非其他节点先写入变量。
- START 会创建自己的 NodeRun 和 Run-Time 记录，type 为 START；inputs 保存用户输入的 key/value，outputs 保存成功提交到 Context 的变量，完整契约见第五章。
- START 不执行自动重试；任意输入解析、类型校验、key 冲突或提交错误都会立即使 START 失败并触发 Fail-Fast。

<a id="chapter-10-2"></a>

### 10.2 调度资格与并行规则

- 普通节点只有在所有入边上游节点均为 SUCCESS，且该节点已声明或可静态识别的 Context 引用变量均已存在时，才具备运行资格。
- 调度器每轮必须把全部具备运行资格的节点同时纳入调度，不设置 Workflow 级并发上限，也不按画布位置、节点类型、创建顺序或节点 ID 强制串行。所有就绪节点在同一调度轮次创建 PENDING NodeRun；实际进入 RUNNING 的先后取决于执行资源，彼此之间未通过有向边声明的相对执行顺序不保证稳定。
- 节点的静态 Context 引用必须由 START 输入或存在有向路径可达当前节点的上游节点 outputs 声明；引用自身输出、下游输出、其他无路径子图输出或不存在的变量时，Workflow 校验失败。静态引用本身不替代显式连线。
- 静态引用包含嵌套字段或数组下标时，Workflow 校验根变量存在，并要求根变量声明类型为 object 或 array；由于当前不定义完整 Schema，更深层路径只在运行时校验。
- 配置了 START 时，普通节点还必须等待 START 成功；未配置 START 时，无入边的根节点可以直接作为首批节点运行。
- SCRIPT 的动态 get_val 变量无法在调度阶段静态识别时，在脚本运行期间按 SCRIPT 的 get_val 规则校验；变量不存在时同样失败。
- 上游节点成功但下游所需的静态 Context 变量不存在时，调度器为下游创建 FAILED NodeRun，error.code 使用 `CONTEXT_VARIABLE_NOT_FOUND`，不启动节点进程，并触发 Fail-Fast。

<a id="chapter-10-3"></a>

### 10.3 校验时机

- 用户显式保存 Workflow 时执行完整结构和配置校验；校验失败禁止保存。
- 启动 Workflow Run 前再次执行同一套完整校验；校验失败不创建 Workflow Run 或 NodeRun。
- 编辑过程中只显示提示，不阻断节点或连线编辑。
- 静态 Context 引用不替代显式有向边，边负责声明执行依赖，Context 负责传递数据。

<a id="chapter-10-4"></a>

### 10.4 错误阶段与 NodeRun 结果

| 阶段 | 发生时机 | NodeRun/Workflow 记录 | 重试 |
| --- | --- | --- | --- |
| Design-Time 配置校验 | 保存 Workflow 或节点配置时 | 校验失败，不创建 Workflow Run 或 NodeRun | 不重试 |
| Workflow 运行前置校验 | 启动 Run、创建 NodeRun 前 | 校验失败，不创建 Workflow Run 或 NodeRun | 不重试 |
| 执行前动态错误 | Run 已创建、NodeRun 已创建，但进程或外部调用尚未开始 | NodeRun 从 PENDING 转 FAILED，attempt_count=0，started_at=null，记录 error | 不重试 |
| 执行中错误 | 脚本进程、HTTP 完整尝试或 LLM 供应商请求已经开始 | NodeRun 保持 RUNNING，按节点 execution 策略计数和重试；耗尽后进入 FAILED/TIMEOUT | 按节点策略 |

典型执行前动态错误包括模型配置在前置校验后失效、Context 根变量或嵌套路径存在性预检失败、URL/Proxy 解析失败。供应商在请求已经发送后返回的参数拒绝属于执行中错误；平台在保存或运行前置阶段发现的保留字段、类型和结构错误不属于可重试错误。

<a id="chapter-11"></a>

## 11. 执行、重试、超时与取消约束

<a id="chapter-11-1"></a>

### 11.1 通用执行状态

- Workflow 采用 Fail-Fast 策略：任一节点最终失败后，Workflow Run 立即停止，不再调度其他尚未开始的节点。
- 节点重试期间的中间失败不触发 Workflow 停止；只有重试耗尽后的最终失败、超时或输出提交冲突才触发 Fail-Fast。
- NodeRun 从首次进入 RUNNING 起，在重试调用和 delay_ms 等待期间始终保持 RUNNING，不回退为 PENDING；只有最终成功、失败、超时或取消时才进入对应终态。
- 节点存在多次尝试时，最终成功则 NodeRun 为 SUCCESS；全部尝试失败时，以最后一次尝试或其后置处理的结果确定终态，最后结果为超时则使用 TIMEOUT，其他错误使用 FAILED。更早尝试发生过超时不会覆盖最后结果。
- Fail-Fast 触发后，立即中断所有正在运行的其他节点，并把已创建但仍为 PENDING 的 NodeRun 终结为 CANCELLED；两类节点的待提交输出全部丢弃。
- 每个 Workflow Run 使用同一终态协调锁串行决定 SUCCESS、FAILED、TIMEOUT、CANCELLED 以及 Fail-Fast/用户取消登记的先后，最先完成登记的终态生效。节点成功事务先完成时，该节点保持 SUCCESS 且已提交输出保留；失败或超时先登记时保留 FAILED/TIMEOUT；用户取消或 Fail-Fast 先登记时，尚未成功终结的 PENDING/RUNNING NodeRun 使用 CANCELLED。任何后到事件都不得覆盖已登记终态。
- Fail-Fast 后尚未进入执行调度的节点不创建 NodeRun；已创建但仍为 PENDING 的 NodeRun 转为 CANCELLED，attempt_count 为 0、started_at 和 duration_ms 为 null，并记录 finished_at、`NODE_CANCELLED_BY_FAIL_FAST` error 及 trigger_node_run_id；已运行节点中断后使用相同错误码记录 CANCELLED。
- 当前 NodeRun 不定义 SKIPPED 状态；后续实现条件分支时再重新引入。
- 节点通过运行前置校验后即创建 NodeRun，初始状态为 PENDING，此时 started_at、finished_at 和 duration_ms 均为 null；执行进程启动后更新为 RUNNING 并写入 started_at，PENDING 等待时间不计入 duration_ms。
- NodeRun 创建后、执行进程或外部调用启动前发现运行时错误时，可以从 PENDING 直接转为 FAILED；此时 attempt_count 为 0、started_at 和 duration_ms 为 null，并记录 finished_at 与非空 error。嵌套 Context 路径不存在属于该类错误。
- Fail-Fast 发生时，PENDING 和 RUNNING NodeRun 都转换为 CANCELLED；PENDING NodeRun 不启动执行，也不增加 attempt_count。
- NodeRun 进入 CANCELLED 时 error 必须非空。用户主动取消节点或 Workflow 时使用 `NODE_CANCELLED_BY_USER`；其他节点最终失败触发 Fail-Fast 而中断当前节点时使用 `NODE_CANCELLED_BY_FAIL_FAST`，并在 error.details.trigger_node_run_id 中记录触发 Fail-Fast 的 NodeRun ID。
- 所有 NodeRun 统一遵循状态与 error 不变量：PENDING、RUNNING、SUCCESS 时 error 必须为 null；FAILED、TIMEOUT、CANCELLED 时 error 必须为非空 error 对象。重试期间 NodeRun 保持 RUNNING，中间尝试错误不提前写入 Run-Time.error；完整过程只进入临时日志。
- SCRIPT、HTTP 和 LLM 的临时执行日志必须按时间顺序记录每次实际尝试的开始、结束、结果和错误；HTTP 还必须记录每次实际发生的重定向请求与响应。中间尝试日志不会因后续重试成功而删除。
- SCRIPT、HTTP 和 LLM 每次失败尝试的临时执行日志必须包含可诊断的错误信息；存在异常堆栈时必须记录完整堆栈。完整日志不写入 Run-Time.error.details，也不属于当前持久化契约。
- 用户取消或 Fail-Fast 的原因仅记录在对应 NodeRun.error；取消不需要生成额外的逐次尝试持久化记录。

<a id="chapter-11-2"></a>

### 11.2 CANCELLED error.details

CANCELLED NodeRun 的 error 结构沿用各节点 Run-Time 的通用 error 字段。用户主动取消时 details 为 null；Fail-Fast 中断时 details 结构如下：

| 字段                | 类型   | 取值          | 示例                                 | 含义                              |
| ------------------- | ------ | ------------- | ------------------------------------ | --------------------------------- |
| trigger_node_run_id | string | UUIDv4 字符串 | 5e074085-8d4a-4e0b-8f3c-2a9d6b7c3e33 | 触发 Fail-Fast 的失败 NodeRun ID |

<a id="chapter-11-3"></a>

### 11.3 重试与超时

- SCRIPT、HTTP 和 LLM 的 timeout_ms、max_attempts、delay_ms 必须由用户在 Design-Time 显式填写，不提供契约默认值。
- timeout_ms 对每次实际尝试分别计时，每次重试重新开始；重试等待不计入单次 timeout_ms，但计入 NodeRun.duration_ms。
- attempt_count 只在实际执行开始时增加；预检、资源等待、delay_ms、Retry-After 和尚未开始的重试不增加计数。
- 各节点允许重试的错误范围、HTTP 幂等方法限制和流式空闲超时分别以对应节点章节为准。

<a id="chapter-11-4"></a>

### 11.4 用户取消

- 用户取消 Workflow 时，RUNNING NodeRun 立即中断，PENDING NodeRun 直接转为 CANCELLED，尚未创建的节点不补建 NodeRun。
- 用户中断单个 PENDING 或 RUNNING 节点等价于取消整个 Workflow Run；当前不支持局部取消后继续执行。
- 对已终态 Workflow Run 或 NodeRun 重复取消是幂等 no-op，不改写历史字段。
- 取消与成功、失败、超时通过同一终态协调锁竞争，最先登记的终态生效。

<a id="chapter-12"></a>

## 12. 错误与数据完整性约束

<a id="chapter-12-1"></a>

### 12.1 总原则

所有数据处理必须遵循“错误显式化、拒绝静默污染”。节点和 Workflow 只有在契约规定的全部校验、解析、执行、输出提取、类型验证和 Context 提交完成后才能成功。

| 维度 | 工业级要求 | 禁止行为 |
| :--- | :--- | :--- |
| 数据纯净度 | Context 只接收成功终态事务一次性提交的严格 JSON 值 | 部分写入、失败写入、覆盖旧值、NaN/Infinity、共享可变引用 |
| 类型一致性 | Design-Time 声明类型、Run-Time 实际类型与 Context 值严格一致 | 隐式字符串化、布尔值冒充整数、失败后写入 null、猜测响应类型 |
| 下游灵活性 | 通过统一 Context 引用、HTTP JSONPath、SCRIPT get_val/set_val 和 LLM 原始文本支持组合 | 把来源信息包进变量、强制解析 LLM JSON、隐式切换到 response.body |

<a id="chapter-12-2"></a>

### 12.2 显式错误

- 配置错误在保存或运行前置校验阶段显式返回，禁止创建不合法的执行记录。
- 运行时错误必须写入稳定 error.code、非空 message 和约定的 details；不得只记录日志后继续成功。
- 缺失变量、嵌套路径缺失、类型不匹配、响应解析失败、协议不支持、输出缺失和 Context 冲突都必须失败，不得回退为猜测值。
- 多个错误同时发生时，使用各章节定义的优先级；未定义优先级时，以终态协调锁最先登记的错误为准，不拼接或覆盖根因。

#### 通用错误码

| error.code | 使用场景 |
| --- | --- |
| WORKFLOW_CONFIG_INVALID | Workflow 或节点 Design-Time 字段、类型或结构不合法 |
| WORKFLOW_GRAPH_INVALID | 节点、Edge、循环、可达性或 START/END 图约束不合法 |
| WORKFLOW_CANCELLED | 用户取消 Workflow Run |
| WORKFLOW_PROCESS_RESTARTED | 服务进程重启时收敛遗留的 PENDING/RUNNING WorkflowRun |
| CONTEXT_VARIABLE_NOT_FOUND | Context 根变量或嵌套路径不存在 |
| CONTEXT_KEY_EXISTS | Context 输出 key 已存在，原子提交被拒绝 |
| NODE_CANCELLED_BY_USER | NodeRun 因用户取消进入 CANCELLED |
| NODE_CANCELLED_BY_FAIL_FAST | NodeRun 因其他节点失败级联进入 CANCELLED |

#### START 错误码

| error.code | 使用场景 |
| --- | --- |
| START_INPUT_INVALID | name、type 或 data 配置不合法；用于配置校验结果，不创建 NodeRun |
| START_EXECUTION_ERROR | START 执行前动态错误无法归入通用 Context 错误码时的兜底码 |

#### SCRIPT 错误码

| error.code | 使用场景 |
| --- | --- |
| SCRIPT_RUNTIME_ERROR | Python 未捕获异常 |
| SCRIPT_TIMEOUT | 最后一次脚本尝试超时 |
| SCRIPT_OUTPUT_UNDECLARED | set_val name 未在 outputs 声明 |
| SCRIPT_OUTPUT_TYPE_MISMATCH | set_val value 与声明类型不一致 |
| SCRIPT_OUTPUT_SERIALIZATION_ERROR | set_val value 不能严格 JSON 序列化 |
| SCRIPT_OUTPUT_DUPLICATE | 同一次尝试重复 set_val 同名变量 |
| SCRIPT_OUTPUT_MISSING | 脚本结束时缺少已声明输出 |
| SCRIPT_EXECUTION_ERROR | 无法归入上述具体错误码的 SCRIPT 兜底码 |

#### LLM 错误码

| error.code | 使用场景 |
| --- | --- |
| LLM_MODEL_NOT_FOUND | 模型供应商或模型引用失效 |
| LLM_TIMEOUT | 最后一次模型调用超时 |
| LLM_REQUEST_ERROR | 已发送的供应商请求失败 |
| LLM_RESPONSE_ERROR | 供应商响应协议解析失败 |
| LLM_PROMPT_EMPTY | Context 解析后最终 prompt.user 为精确空字符串，未发起模型请求 |
| LLM_STREAM_INCOMPLETE | 流式连接未收到协议完成信号 |
| LLM_UNSUPPORTED_RESPONSE | 响应包含 Tool Call 或其他不支持的非文本内容 |
| LLM_OUTPUT_TRUNCATED | 供应商因长度或 Token 上限结束生成 |
| LLM_CONTENT_FILTERED | 供应商因内容安全策略结束生成 |
| LLM_UNSUPPORTED_FINISH_REASON | 无法映射供应商结束原因 |
| LLM_USAGE_VALUE_INVALID | usage_errors[].code；供应商 usage 字段不是大于等于 0 的 integer，非致命 |
| LLM_EXECUTION_ERROR | 无法归入上述具体错误码的 LLM 兜底码 |

#### HTTP 错误码

| error.code | 使用场景 |
| --- | --- |
| HTTP_CONNECTION_ERROR | DNS、Proxy、TCP 或 TLS 连接失败 |
| HTTP_TIMEOUT | 最后一次 HTTP 完整尝试超时 |
| HTTP_STATUS_ERROR | 最终 HTTP 状态码不是 2xx |
| HTTP_URL_INVALID_HOST | 运行时 Host 无法按 IDNA/URL 规则解析 |
| HTTP_HEADER_DUPLICATE | Design-Time 存在大小写归一后重复 Header |
| HTTP_TOO_MANY_REDIRECTS | 重定向次数超过 10 |
| HTTP_REDIRECT_DOWNGRADE_BLOCKED | HTTPS 重定向到 HTTP 被阻止 |
| HTTP_REDIRECT_INVALID_LOCATION | Location 无法解析为合法 HTTP/HTTPS URL |
| HTTP_RESPONSE_TOO_LARGE | 解压后的响应 Body 超过 10 MB |
| HTTP_RESPONSE_CONTENT_ENCODING_ERROR | Content-Encoding 不支持或解压失败 |
| HTTP_RESPONSE_JSON_INVALID | 2xx JSON Body 解析失败 |
| HTTP_RESPONSE_DECODE_ERROR | text Body 字符编码不支持或解码失败 |
| HTTP_OUTPUT_PATH_NOT_FOUND | outputs.path 找不到值 |
| HTTP_OUTPUT_TYPE_MISMATCH | outputs.path 提取值与声明类型不一致 |
| HTTP_EXECUTION_ERROR | 无法归入上述具体错误码的 HTTP 兜底码 |

错误码使用规则：优先使用具体错误码；只有确实不存在对应具体码时才使用所属节点的 `*_EXECUTION_ERROR`。实现不得创建未列入本目录的临时错误码；新增错误码必须先更新本规范。

<a id="chapter-12-3"></a>

### 12.3 原子提交与不可回滚事实

- 输出校验、Context 原子提交、Run-Time 最终事实写入和 NodeRun SUCCESS 必须构成不可分割的终态事务。
- 任一输出失败时整组 outputs 为 {}，不得部分提交。
- Workflow 后续 FAILED 或 CANCELLED 不回滚此前 SUCCESS NodeRun 及其 outputs；完整 Context 在 Run 结束后统一丢弃。
- Run-Time 终态记录冻结后不可修改，日志不得作为替代 Run-Time 的事实来源。

<a id="chapter-12-4"></a>

### 12.4 日志与敏感数据

- SCRIPT、HTTP、LLM 每次尝试必须记录开始、结束、结果和错误；HTTP 还记录每次重定向。
- 完整标准输出、标准错误、失败堆栈和中间过程日志属于临时日志，不写入 Context、Run-Time.error.details 或其他持久化证据结构。CANCELLED 只在 NodeRun.error 中保留取消原因。
- 当前契约不定义 log_ref。HTTP 敏感 Header、Proxy 用户名和密码按既定规则明文保存和展示；实现不得声称已脱敏。
- 日志告警不能替代结构化失败。只有明确规定为非致命的数据（例如非法 LLM usage 单字段）才允许继续执行，并必须写入结构化 usage_errors，不能只记录警告。

## Implementation Decisions (Rapid Iteration)

- The current implementation prioritizes execution availability and terminal
  correctness. Workflow/node definition snapshots, complete logs, failed-attempt
  records, and stack-trace persistence are deferred. Observability write failures
  must not block node execution, terminal-state updates, or Context commits.
- A WorkflowRun stores workflow_id but does not preserve an immutable workflow
  snapshot. Historical runs therefore do not guarantee reconstruction of a
  Workflow definition that was later changed or deleted.
- A Workflow with any WorkflowRun history cannot be deleted. This prevents a
  persisted WorkflowRun and NodeRun from becoming orphaned while snapshots are
  intentionally deferred.
- The new /api/workflows protocol is incompatible with /api/workflow-drafts.
  Legacy definitions and run records are not migrated or read by the new
  repository.
- The new repository uses versioned table names (`workflow_definitions_v2`,
  `workflow_runs_v2`, and `workflow_node_runs_v2`) so an existing legacy SQLite
  file cannot shadow the new schema. This is isolation, not data migration.
- During the cutover, the new executor uses dependency-based parallel dispatch
  and a Context commit lock. This is the selected baseline for stable multi-node
  execution; node adapters are isolated from scheduling and can be replaced
  without changing fail-fast or Context atomicity semantics.
- The canvas does not persist visual node coordinates in the execution contract.
  On load, missing coordinates are laid out automatically; the engine ignores
  presentation state.
- Only the canvas top-right Run and Cancel actions execute or cancel a complete
  WorkflowRun. Node-card and node-editor actions do not start an independent
  NodeRun in the new protocol.
- The Workflow run and cancel APIs are the backend actions for the Workflow
  canvas top-right Run and Cancel buttons. Run creates a WorkflowRun; Cancel
  cancels that active WorkflowRun and the canvas refreshes status from
  WorkflowRun and NodeRun query results. No separate run-center interaction is
  introduced in this iteration.
- On process startup, any persisted PENDING/RUNNING WorkflowRun is explicitly
  finalized as FAILED with WORKFLOW_PROCESS_RESTARTED; its active NodeRuns are
  finalized as CANCELLED. This prevents a restart from leaving an indefinitely
  running record.
- Save-time Context dependency validation resolves HTTP/LLM template references
  and literal SCRIPT calls such as `get_val("result")`. A dynamically built
  SCRIPT key cannot be inferred safely, so it remains a runtime lookup and
  fails explicitly with CONTEXT_VARIABLE_NOT_FOUND when absent.
- The HTTP canvas exposes only contract-supported request body types (`none`,
  `raw`, `form_data`, `form_urlencoded`). Binary data remains a response parsing
  option, not a request-body upload mode in this iteration.
- Each canvas node exposes a log entry that projects the latest WorkflowRun's
  persisted NodeRun facts. START and SCRIPT show inputs/outputs; HTTP shows
  inputs/request/response/outputs; LLM also shows model and usage. END has no
  NodeRun by contract and therefore displays no runtime log. The panel does not
  reconstruct deprecated `stdout`, `stderr`, `request_body`, or `response_body`
  fields.
