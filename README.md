# Agent Bench

Agent Bench 是一个本机运行的企业 Agent 测试编排工具。它用于管理 Excel 测试集、模型供应商和可视化 Workflow，并通过画布 HTTP 节点对接被测服务，创建、运行、恢复和追溯批量测试。

当前版本支持：

- Excel 测试集上传、分页浏览、任意 Sheet 批量执行和字段映射
- Script / Agent 工具 CRUD、ZIP 导入导出、SSE 日志和运行中断
- Workflow HTTP 节点、请求模板、连接失败重试和大响应 Artifact
- Parser、Evaluator、Check Aggregator、Case Aggregator 固定工作流
- 多 Run 调度、Case 并发、取消、手工恢复和完整执行追溯
- DeepSeek 与 DashScope 真实模型工具链测试

系统只面向桌面浏览器和本机使用，服务固定绑定 `127.0.0.1`。
Workflow 和节点测试调度器保存进程内活动状态，因此当前部署只支持单个 Uvicorn worker；`run.py` 已按该约束启动。不要使用 `--workers 2` 或其他多进程部署参数。
同步 SQLite、文件和 Excel 操作由 FastAPI 同步处理器在线程池执行；模型供应商连接测试使用异步 HTTP 客户端，避免慢本地 I/O 阻塞事件循环。

## 环境要求

- Windows 10 或 Windows 11
- [uv](https://docs.astral.sh/uv/)
- Git，仅在通过 Git 获取项目时需要
- Node.js 不是运行依赖；只有修改 Workflow 前端源码并重新构建静态资源时才需要

## 安装与启动

从 GitHub 克隆项目并进入项目目录：

```powershell
git clone https://github.com/aihaipeng/agent-bench-v2.git
cd agent-bench-v2
```

首次安装 Python 与项目依赖：

```powershell
uv python install 3.14
uv sync --locked --python 3.14
```

以后启动项目只需执行：

```powershell
uv run python run.py
```

浏览器打开 [http://127.0.0.1:8010](http://127.0.0.1:8010)。停止服务时在 PowerShell 中按 `Ctrl+C`。

首次启动不需要创建配置文件。系统在缺少 `config.yaml` 时使用安全默认值，并在首次上传测试集后自动创建本机配置。

### 数据库初始化

不需要手动创建数据库或执行建表 SQL。系统在首次访问模型或 Workflow 等相关页面/API 时自动完成以下操作：

- 创建 `run_storage/` 本地数据目录；
- 创建 `run_storage/agent_bench.sqlite3` SQLite 数据库；
- 使用 `CREATE TABLE IF NOT EXISTS` 创建当前版本所需的模型、Node、Workflow、节点绑定和 Edge 表及索引。

数据库初始化由 Repository 统一管理，请勿手工创建同名表或使用旧版本 Workflow 表结构。全新克隆的仓库不包含 `run_storage/` 中的本地数据，因此首次运行看到空的模型和 Workflow 列表是正常行为。

如果需要把另一台机器的已有数据迁移过来，应在服务停止后整体备份和迁移 `run_storage/`；测试集还需要同步 `inputs/` 和 `config.yaml`。这些目录和文件可能包含 API Key、请求响应与执行日志，不应提交到 GitHub。

## 首次使用

1. 在“测试集”页面上传 `.xlsx` 或 `.xlsm` 文件。
2. Excel 可以有表头，也可以从第一行直接保存数据；无表头的旧格式默认把前两列识别为 `case_id / question`。
3. 在“Workflow 管理”页面创建 START、业务节点和 END，START 声明批量输入变量。
4. 在“运行调度”页面选择测试集、Sheet、首行模式和 Workflow，把 Excel 列映射到 START 变量或 object 字段。
5. 设置 Case 并发数，创建并手工启动 Run；在详情页查看、取消或恢复 Case。

仓库不附带真实测试集、API Key、Workflow 或运行记录。新用户需要在页面中创建自己的本地数据。

## 开发与测试

```powershell
# 全量测试
uv run pytest -q

# 启动开发服务
uv run python run.py

# 修改 Workflow 前端源码后重新构建
npm ci
npm run build
```

缺少真实模型凭据时，对应 live Agent 用例会跳过，不影响其他功能测试。

## 真实模型测试

真实模型矩阵使用 DeepSeek `deepseek-v4-pro` 和 DashScope `qwen3.7-max`。在当前 PowerShell 进程设置所需环境变量后运行：

```powershell
$env:DEEPSEEK_API_KEY = "<your-key>"
$env:DASHSCOPE_API_KEY = "<your-key>"
uv run pytest tests/test_agent_live_integration.py -m live -q
```

`DEEPSEEK_BASE_URL` 和 `DASHSCOPE_BASE_URL` 为可选覆盖项。测试只把密钥注入单次运行请求，并断言临时工具 manifest 未保存密钥。

## 本地数据与安全

以下内容只保存在本机，并已被 `.gitignore` 排除：

- `config.yaml`：当前选择的测试集和 Sheet
- `inputs/`：Excel 测试集及本地元数据
- `run_storage/`：SQLite、请求响应、日志和运行 Artifact
- `outputs/`、`logs/`：导出结果和本地日志
- `.env*`、证书私钥、虚拟环境、依赖目录和测试缓存

公开仓库只保留 [config.example.yaml](config.example.yaml) 和 `inputs/.gitkeep` 作为安全模板或空目录占位。不要强制添加被忽略的运行数据。

## 项目结构

```text
run.py                              # Uvicorn 本机服务入口，固定监听 127.0.0.1:8010
pyproject.toml / uv.lock            # Python 版本、运行依赖和锁定依赖
package.json / package-lock.json    # Workflow 前端构建依赖与 npm 脚本

web/
├─ app.py                           # FastAPI 应用、路由注册和静态站点挂载
├─ routes_*.py                      # 测试集、配置、模型和 Workflow API
├─ local_config_service.py          # 本地配置应用服务
├─ workflow_services.py             # lifespan 管理的 Workflow 应用级资源
├─ frontend/                        # Workflow Studio React Flow 源码与样式
│  ├─ workflow-canvas.jsx
│  ├─ workflow-canvas.css
│  └─ workflow-alignment.mjs
└─ static/                          # 单页应用及可直接运行的已构建静态资源
   └─ assets/workflow-canvas.*      # npm run build 生成的 Workflow bundle

execution/
├─ init_db.py                       # SQLite 默认路径、共享初始化锁与连接设置
├─ model_providers.py               # 模型供应商配置与 SQLite Repository
├─ model_gateway.py                 # 模型协议调用与响应解析
├─ node_codec.py / time_utils.py    # Structural 公共序列化与时间
├─ node_structural_models.py        # 五类 Node Structural Model 与持久化
├─ workflow_structural_models.py    # Workflow、binding、Edge 与事务仓储
├─ workflow_application.py          # Workflow 跨资源应用事务
├─ workflow_execution.py            # 完整 Workflow DAG 调度与公开兼容入口
├─ workflow_execution_store.py      # Execution JSON 原子存储与进程恢复
├─ workflow_execution_control.py    # 取消信号与活动 Worker 控制
├─ workflow_node_executor.py        # Node Runner 注册、分派与 Context commit
├─ workflow_*_runner.py             # 公共生命周期及 SCRIPT/LLM/HTTP Runner
├─ tool_runtime.py / tool_worker.py # 可取消子进程 Runtime 与 Worker
├─ workflow_node_tests.py           # 单节点临时测试会话与 SSE
├─ batch_inputs.py                  # Excel 行到 START 输入映射与冻结快照
├─ batch_execution_store.py         # Batch/Case 原子 JSON 存储与恢复
├─ batch_scheduler.py               # Case 并发、取消和手工恢复
└─ workflow_values.py               # Context 引用、类型转换与输出提取

storage/
├─ excel.py                         # Excel 测试集读取
├─ atomic_files.py                  # 同路径锁和原子文本替换
├─ local_config.py                  # config.yaml Repository
└─ excel_set_meta.py                # 测试集元数据 Repository
scripts/build-workflow.mjs          # Workflow 前端生产构建脚本
tests/                              # Python 单元/集成测试及 Node 几何测试
docs/                               # 产品需求与企业编排业务基线
prototypes/                         # HTTP、LLM 等高保真交互原型，不参与生产运行

WORKFLOW_SPEC.md                    # 当前 Workflow Structural/Execution 契约
PLAN.md                             # 分阶段实现决策、验收记录与回归结果
config.example.yaml                 # 可公开提交的本地配置模板

inputs/                             # 本机 Excel 测试集，内容不提交
run_storage/
├─ agent_bench.sqlite3              # Structural Model SQLite 数据库，不提交
├─ workflow_executions/             # Workflow/Node Execution JSON，不提交
└─ batch_executions/                # Batch/Case/Input Snapshot JSON，不提交
outputs/ / logs/                    # 本地导出结果与日志，不提交
```

更完整的业务边界和执行语义见 [企业 Agent 测试编排需求基线](docs/enterprise-agent-test-orchestration.md)。
