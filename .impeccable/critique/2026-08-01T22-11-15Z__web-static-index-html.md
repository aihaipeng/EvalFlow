---
target: 重评 EvalFlow 四个管理页面的易用性、UI 风格一致性与布局合理性（第二轮）
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
p2_count: 2
p3_count: 0
timestamp: 2026-08-01T22-11-15Z
slug: web-static-index-html
---
# EvalFlow UI 审查重评（critique 快照 · 第二轮）

Method: dual-agent（A: 设计审查重评 · B: 检测器+浏览器证据）

## 综合说明

Assessment B：CLI 检测器 9 个 target clean，仅 2 个既有 CSS 发现（side-tab/overused-font 警告 + codex-grid advisory，与上轮相同，已分类为既有设计）；浏览器 4 视图 + 编辑页 + 弹窗全程 0 console 错误。上轮修复全部实测有效：1180px 弹窗、Zod 就地错误、代理模式中文、SSL 证书校验、深色画布保存按钮 #78a0ff 与全站一致、未保存确认、Ctrl+S 保存。新发现：画布打开时 react-flow pane 覆盖整个视口，侧边栏按钮点击被拦截（画布全屏覆盖的已知设计）。

## Design Health Score：27/40（Acceptable）— 上轮 24/40

| # | 启发式 | 得分 | 变化 | 关键问题 |
|---|--------|:---:|:---:|---------|
| 1 | 系统状态可见性 | 3 | ↑+1 | 加载/轮询/已保存徽章齐全；画布页头全局保存状态不可见（.wf-save-state 死代码），无 beforeunload |
| 2 | 系统与现实匹配 | 3 | ↑+1 | 术语统一（新建任务/接口地址/SSL 证书校验）；残留画布 toast 英文 "Workflow 已保存"、节点英文状态 PENDING/SUCCESS |
| 3 | 用户控制与自由 | 3 | ↑+1 | Ctrl+Z/Y/Delete→undo、弹窗 Esc/取消、删除确认；元数据改名自动持久化不可撤销 |
| 4 | 一致性与标准 | 2 | 持平 | 三套按钮圆角实测并存（8px/5px/10px，后置硬编码覆盖 var(--radius)）；红 6+ 色绿 5 色；:root 令牌块重复声明且值冲突 |
| 5 | 错误预防 | 3 | ↑+1 | RHF+Zod 就地错误 + aria-invalid 实测生效；画布改名确认用原生 window.confirm |
| 6 | 识别而非回忆 | 3 | ↑+1 | 搜索/筛选卡/占位提示/协议帮助齐全；result_path 需手记 Context 字段名无建议 |
| 7 | 灵活与高效 | 3 | ↑+1 | 画布快捷键全套；管理列表页无快捷键 |
| 8 | 美学与极简 | 2 | 持平 | 页面干净 1180px 无溢出；三套按钮+多套语义色叠加视觉噪音；深色主按钮白字对比度 2.54:1 |
| 9 | 错误恢复 | 3 | ↑+1 | Zod 具体文案、失败内容保留+重试、删除注明无法恢复 |
| 10 | 帮助与文档 | 2 | 持平 | 空态/工具提示/区段副标题在；无文档入口 |
| **总分** | | **27/40** | **+3** | **Acceptable（可接受）** |

## Design Specificity Verdict

内容特异性强（五类节点彩色体系贯穿画布/选择器/检查器、三步测试集导流、批量详情筛选卡），但"通用后台"痕迹仍在（三套按钮、多套语义色、双声明令牌块）。上轮修复方向正确、落地扎实（术语/Zod/Radix/1180px/画布三件套全部实测有效）；"一致性修复停在半路"——令牌层重复声明与后置硬编码覆盖让颜色/按钮碎片以更隐蔽的方式延续。

## What's Working

1. 画布编辑体验：撤销/重做、对齐参考线、逐节点已保存徽章、Ctrl+S/Backspace 进 undo
2. Zod 就地表单错误（"并发数不能小于 1"）+ aria-invalid + 失败内容保留
3. Radix 弹窗无障碍（焦点陷阱/Escape/aria-label）+ 1180px 任务弹窗布局

## Priority Issues

### [P1] 深色模式全部主按钮白字对比度仅 2.54:1（WCAG AA 要求 4.5:1）
- **Why**：暗色 --color-accent #78a0ff + 白字（style.css:1489），画布保存按钮实测 rgb(120,160,255) 白字；全站主按钮深色模式不可读（Sam 与深夜排障用户）
- **Fix**：深色主色改深蓝（#3b6fe0/#4f7ee8 保持白字）或浅底深字；收敛暗色 --color-accent 为唯一值（现 #5b8cff vs #78a0ff 双声明）
- **Suggested command**：/impeccable colorize

### [P1] 按钮圆角三套并存（后置硬编码架空 var(--radius)）
- **Why**：--radius 最终 10px（:root 双声明），但 style.css:1620 硬编码 .btn 8px、workflow-canvas.css:3980 硬编码画布按钮 5px、ts-btn 10px——实测三套圆角
- **Fix**：删两处后置硬编码块统一走 var(--radius)；合并 :root 双令牌块为单一事实来源（--color-accent-hover/暗色 accent 各声明两次且值不同）
- **Suggested command**：/impeccable polish

### [P1] 语义色族未收敛：红 6+ 色、绿 5 色、蓝 3 色
- **Why**：--red #b91c1c 与 --color-danger #dc2626 并存；画布内 #b4233d/#be2948/#d63d3d/#e56b81 等散落；通过率 GitHub 绿 #2ea44f 游离；#16803c（START 节点色）仍在 JSX
- **Fix**：删 --red 全部改 var(--color-danger)；节点分类色迁 CSS 变量；.batch-pass-rate 三色用 token
- **Suggested command**：/impeccable colorize

### [P2] 画布未保存确认用原生 window.confirm，且无 beforeunload
- **Why**：与全站 Radix 弹窗风格相悖、阻塞式；浏览器刷新/关标签直接丢未保存图结构
- **Fix**：换 ConfirmDialog（components/dialog.jsx 现成）；加 beforeunload；恢复画布页头保存状态指示（.wf-save-state 死代码）
- **Suggested command**：/impeccable harden

### [P2] Zod 双重报错 + 冒号半/全角混用
- **Why**：任务弹窗提交失败时就地错误与 toast 重复展示同一文案；"加载测试集失败："（全角）vs "加载模型供应商失败:"（半角）
- **Fix**：移除 errors 回调里的 toast（就地错误已足够）；统一错误前缀标点
- **Suggested command**：/impeccable clarify

## Persona Red Flags

- **Alex**：画布层快捷键到位；管理列表页零快捷键；改名自动持久化不可 Ctrl+Z 撤销（与画布撤销落差）
- **Jordan**：节点英文状态（PENDING/SUCCESS）与全中文界面并置；"注入到工作流 Context"无解释；API Key 无"从哪里找"提示
- **Sam**：深色主按钮 2.54:1 致命；--text-subtle #7b8798 3.65:1、SCRIPT 橙 #c56a12 3.86:1 不达标；Radix 焦点/Escape/aria-label 正向
- **被中断的排障工程师**：批量详情滚动/搜索保持是亮点；画布返回被原生 confirm 打断；深色模式主按钮不可读加重深夜排障负担

## Minor Observations

画布元数据自动持久化 vs 图结构手动保存（同屏两种保存模型无状态区分）；供应商编辑器返回无未保存保护；"任务重叠"在"仅执行一次"下仍可操作；.ts-btn.danger 实心红 vs .btn-danger 描边粉同一语义两种形态；批量详情英文状态与中文结果标签混排；节点图标色 JSX 硬编码 hex 可迁 CSS 变量。

## Questions to Consider

1. 全站主色/危险色收敛为单一 token + 深色主按钮改深蓝——上轮遗留的"三套按钮、六种红"是否一次清零？是先删后建还是继续叠加？
2. 画布元数据自动保存、图结构手动保存——用户凭什么知道"保存"按钮保存了什么？要不要做页头常驻保存状态指示？
3. 节点英文状态（PENDING/SUCCESS）是刻意的"技术画布"风格还是漏网术语漂移？
