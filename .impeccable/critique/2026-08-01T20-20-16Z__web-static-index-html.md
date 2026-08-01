---
target: 检查 EvalFlow 四个管理页面的易用性、UI 风格一致性与布局合理性
total_score: 24
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
p2_count: 2
p3_count: 1
timestamp: 2026-08-01T20-20-16Z
slug: web-static-index-html
---
# EvalFlow UI 审查（critique 快照）

Method: dual-agent（A: 设计审查 · B: 检测器+浏览器证据）

## 综合说明

Assessment B（检测器 + 浏览器）结果：CLI 检测器 9 个 target（index.html + 4 个 JSX + 3 个 mjs + 2 个原生 JS）全部 clean（0 findings）；真实数据下四个视图切换零 console error/warning/失败请求；页面 JS 注入不受阻。即：**功能层健康、无结构性红线**。本报告问题全部来自 Assessment A 的设计审查（代码通读 + 1440x900/1280x800 双视口实测 + 深色模式实测），主线程对 A 的关键发现做了交叉验证（CSS token 统计：790 处颜色值、三套 token 前缀体系），证据一致。

## Design Health Score

| # | 启发式 | 得分 | 关键问题 |
|---|--------|:---:|---------|
| 1 | 系统状态可见性 | 3 | 批跑列表无状态列、无 ETA，运行中靠 1s 轮询，无全局"正在执行"提示 |
| 2 | 系统与现实匹配 | 2 | "批跑/任务"混用、"执行/运行/启动"三种动词、BASE_URL/SSL Verify/Beautify 英文残留 |
| 3 | 用户控制与自由 | 3 | 画布无 Ctrl+S、`deleteKeyCode={null}` 键盘无法删除节点；取消/undo/redo 到位 |
| 4 | 一致性与标准 | 2 | 重灾区：同语义颜色 5-6 个值、按钮圆角 5/6/7/8/14px 并存、深色模式下画布保存按钮与全站分叉 |
| 5 | 错误预防 | 2 | 删除均有确认；画布有未保存修改时关闭无拦截；节点表单错误仅小字提示 |
| 6 | 识别而非回忆 | 3 | Inspector 字段内联、变量下拉好；"字段映射预览""规则显示列"需回忆含义 |
| 7 | 灵活高效 | 2 | 双击节点才开 Inspector（发现性差）、无快捷键、批跑详情长文本不截断滚动扫读低效 |
| 8 | 美学与极简 | 3 | 整体干净；批跑详情用例文本整段换行堆叠、测试集详情单列表格"一列顶天" |
| 9 | 错误识别与恢复 | 2 | 连接/超时错误有友好化；"Workflow 已停止"等原始英文直出、`toast(e.message)` 泄露 API 细节 |
| 10 | 帮助与文档 | 2 | 协议选择有 "?"、Excel 导入有内联提示；无全局帮助、无首次引导 |
| **总分** | | **24/40** | **Acceptable（需要重大改进）** |

## Design Specificity Verdict

**内容特异性强，视觉体系特异性弱。** 业务层是差异化资产：浏览器内 Excel 选区转用例的三步 Stepper、批跑详情"五卡过滤 + 期望/实际对比表 + 问题节点定位"、画布 Inspector 可拖拽缩放浮层——这些不是模板能提供的。但表层是"不同时期代码累积成的真产品"：四套弹窗实现（原生 overlay/modal + React ts-modal/execution-modal + 画布自建）、五套按钮命名（.btn/.ts-btn/.wf-primary-button/is-primary/btn-icon）、三套 token 前缀（全局 120 个无前缀 / --wf-* 90 个 / --ts-* 9 个）。检测器全 clean，未发现结构性红线；视觉漂移需要人工判断才能发现，这正是本报告的核心。

## Overall Impression

创建测试集与排障两端的情感管理做得很好（Stepper 引导 + 五卡统计 + 滚动位置保留），但中间链路（工作流配置、任务创建）反馈密度不足；最大的单一机会是把五套按钮、六种失败红、三套 token 收敛成一个体系——这是 4-5 人小团队维护成本与用户学习成本的双重杠杆。

## What's Working

1. **创建测试集的三步 Stepper**：选择文件→选择用例→保存测试集，每步有 toast 与预览确认，是全产品情感峰值。
2. **批跑详情的排障设计**：五卡统计 + 问题节点定位（"工作流停在此处"）+ 期望/实际对比；轮询时保留滚动位置与搜索框光标——对"被中断的排障工程师"最贴心的设计。
3. **无障碍基础扎实**：四套模态全部实现 Escape 关闭 + Tab 循环 + 焦点归还，toast 有 aria-live，图标按钮有 aria-label。

## Priority Issues

### [P1] 语义色全站漂移：同一"成功绿/失败红/主蓝"每页一个值
- **Why**：颜色是状态语言，用户靠色觉快速判断成败。实测同语义色跨文件 5-6 个值；深色模式下画布保存按钮（#2457d6 深蓝）与全站 primary（#78a0ff 亮蓝）直接分叉，扫视时"保存"在不同页面像不同控件。
- **证据**：主蓝 #2457d6（style.css --color-accent、workflow-canvas.css --wf-blue）vs #2563eb（test-sets.css --ts-primary）vs #1d4ed8/#315ca8/#5b8def（model-providers.css）；成功绿 #047857 vs #16a34a/#16803c vs #16a36a vs #166534/#86efac/#dcfce7 vs #2e7d32（toast.success）；失败红 #b91c1c vs #dc2626 vs #dc3545（Bootstrap 遗留 10 处）vs #c72e4e vs #be123c/#cf222e vs #c62828（toast.error）；Error 紫 #6f2aca 只出现在批跑过滤卡。
- **Fix**：--ts-primary 改为引用 var(--color-accent)；workflow-canvas.css 深色模式补 .wf-primary-button 覆盖；建立 --color-success/--color-danger 语义 token 逐步替换游离值；删除 Bootstrap 红 #dc3545。
- **Suggested command**：/impeccable colorize

### [P1] 按钮体系五套并存，同一页面内混用两套
- **Why**：控件是界面语法。test-sets 页面 toolbar 用原生 .btn（radius 8px），同一页面详情/弹窗用 .ts-btn（radius 7px→8px 文件内双定义），画布用 .wf-*（radius 5px、字号 12px Inter）；style.css 内 .btn 双定义（6px vs 8px）。圆角漂移全景：按钮 5/6/7/8px、弹窗 12/14px、卡片 10px。
- **Fix**：以 .btn 为唯一基类，ts-btn/wf-primary-button 收敛为修饰符；radius 全走 var(--radius)；删 test-sets.css L114 重复定义；画布按钮字号 12px→13px 对齐全站。
- **Suggested command**：/impeccable polish

### [P2] 术语漂移："批跑/任务/执行/运行/启动"与英文残留
- **Why**：4-5 名测试工程师用户，"批跑"仅出现在启动弹窗标题（"选择批跑方式"），页面/列表全叫"任务"；CTA 动词四种（新建测试集/新增模型/新增工作流/创建任务）；英文残留 BASE_URL、SSL Verify、Beautify、SYSTEM/DIRECT/CUSTOM、画布执行历史 context.final/node executions/error；状态文案全大写 PASS/FAILED（过滤卡）vs Pass/Failed（详情）vs SUCCESS/FAILED（画布历史）。
- **Fix**：统一动词；"选择批跑方式"改"选择执行方式"；BASE_URL→接口地址、SSL Verify→SSL 证书校验、Beautify→格式化；过滤卡改中文并统一状态文案。
- **Suggested command**：/impeccable clarify

### [P2] 错误文案两级分化：一半友好一半原始
- **Why**：已有优秀友好化层（连接失败/超时转中文，execution.js L1436-1442），但同一弹窗内"报错概览"直出原始英文 "Workflow 已停止"；三个 React 页面 mutation onError 全部 toast(e.message) 直接透传（model-providers.jsx L101、batch-runs.jsx L21/25、test-sets.jsx 各 catch）。
- **Fix**：为 INTERRUPTED 增加"工作流已被中断"映射；React 页面复用脱敏/翻译层，过滤堆栈与 HTTP 细节。
- **Suggested command**：/impeccable harden

### [P3] 画布关闭无未保存保护，删除节点无键盘路径
- **Why**：画布是耗时最长的编辑场景，误关代价高；deleteKeyCode={null} 使键盘用户无法删除节点；无 Ctrl+S。
- **Fix**：onClose 前检查 saveState==='未保存' 弹确认（复用 openExecutionConfirm）；恢复 deleteKeyCode 并在输入框焦点时不误删；加 ctrl+s 保存监听。
- **Suggested command**：/impeccable harden

## Persona Red Flags

**Alex（专家用户）**：无任何快捷键（Ctrl+S/Ctrl+Enter 全缺）；双击开 Inspector 是唯一入口，批量配置 5 类节点反复双击低效；分页/筛选/排序全部鼠标点。

**Jordan（新手）**："批跑方式：全量执行/断点续跑/失败重跑"无解释；字段设置提示"删除默认字段时，剩余的 col_x 会按顺序重新编号"——col_x 是黑话；START 变量 array/object 填错只报"值不是合法 JSON"无示例。

**Sam（无障碍依赖）**：模态无障碍是亮点；但画布节点不可键盘删除；Inspector 操作按钮仅 28x28px；表头 12px #526079 对比度约 4.2:1 低于小字号 AA；节点选中色 #16803c 对色弱用户区分度低。

**被中断的排障工程师**：批跑详情位置/筛选/搜索保留（优秀），但切页再回来所有筛选清零（状态全在模块内存），刷新后直接回测试集列表找不到刚才的批次；长用例文本整段换行堆叠（无截断），100 条 ERROR 要滚大量文本找目标用例。

## Minor Observations

1. 侧边栏宽度双重定义（--sidebar-w: 200px vs L1399 216px），实测 216px，可拖拽 140-400px。
2. toast 第三组语义色：toast.success #2e7d32 vs 全局绿 #047857；toast.error #c62828 vs #b91c1c。
3. "关闭"作为用例详情主按钮会落到默认 save 图标（label 推导图标机制）。
4. 编辑场景标题层级各自为政：测试集详情 14px 无 h1、供应商编辑器 h1 20px、画布无 h1 用 16px 名称按钮、列表页 24px。
5. 空状态四种做法：测试集/供应商/工作流空态有 CTA，批跑空态"尚未创建任务"无按钮。
6. React 页面输入框 40px vs 原生 .btn 36px，同排底边不齐。
7. 深色模式四套 CSS 各自维护（7/16/28/119 条 dark 规则），未来 token 变更要同步五处。

## Questions to Consider

1. 画布是全屏覆盖式（侧边栏消失），其余三页在 SPA 框架内——是否让画布融入 SPA 框架，还是反过来让三页向画布的沉浸式靠拢？
2. 既有全局 token 和 data-theme 机制，为什么 React 页面的本地 token（--ts-primary/--wf-blue）不直接指向全局变量？
3. 批跑详情是信息最密集、排障价值最高的页面，却是纯原生字符串拼接渲染；下一轮迭代（ETA/瀑布图/失败聚类）打算在原生拼串上继续堆还是迁 React？这个决策决定未来三年一致性维护成本。
