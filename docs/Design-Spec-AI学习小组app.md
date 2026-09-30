
## §12.66 v2.14.0 五屏标准稿组件映射与持续适用条款

标准稿冻结源：`docs/reference/style-draft-2026-09-27.html`（v3，帧 2 结构已按线上真实测评页修正；不得修改）。本轮只移植渲染样式和必要的纯样式包裹，不改变线上渲染函数、文案、事件、接口或路由。

| 屏幕 | 标准稿组件 class | app 真实 DOM 对应 | 样式要点 |
|---|---|---|---|
| 进度 | `.topbar`, `.topbar-inner`, `.brand`, `.streak` | `.appbar`, `.streak-bar` | 暖纸底、1px hairline、橙色行动色 |
| 进度 | `.body`, `.display`, `.sub`, `.sectitle` | `.content`, `.appbar h1`, `.appbar .sub`, `.sec-title` | 34/22/17.5/11.5 字级层次，12px 节奏 |
| 进度 | `.stats` / `.stats div` | `.dcard .grid` / `.dcard .grid>div` | 三列等宽；上下线贯穿；竖线端到端 |
| 进度 | `.progline`, `.bar`, `.tag` | `.chapter`, `.chapter-bar`, `.badge` | 掌握度橙、覆盖率深灰、徽章 8px |
| 测评 | `.rowlist`, `.row`, `.primary` | `.qcard`, `.card`, `.btn` | 自主练习、教师发布测评、薄弱点、闭环均保留线上结构 |
| 测评 | `.sectitle`, `.points` | `.sec-title`, `.weak`, `.rev-item` | 仅换皮，不把 demo 帧 2 的「今日任务」迁入测评页 |
| 知识卡片 | `.kc-scene`, `.kc-card`, `.kc-face`, `.actions` | `.kc-scene`, `.kc-card`, `.kc-face`, `.kc-actions` | 1px hairline、16px 圆角、阴影、翻卡交互不变 |
| 学习 | `.primary`, `.row.task`, `.rowlist.grid` | `.home-card`, `.task-card`, `.home-card` | 线上真实任务名「复习卡片 / 刷练习题」，入口「资料库 / 知识卡片 / 对话」 |
| 班级 | `.row.task`, `.row.me`, `.pos` | `.checkin-row`, `.rank-row`, `.rank-num` | 达标淡绿；本人行保留橙色语义边界 |
| 全局 | `.topbar`, `.streak`, `.foot` | `.appbar`, `.streak-bar`, `.tabbar` | 通知、头像、连胜条、五 tab 均不得删除 |

### 持续适用条款（对后续一律适用）

- **触发点**：任何学生端五屏视觉改动、组件新增/迁移、CSS token 修改，或审计脚本改动。
- **覆盖路径**：`backend/frontend/css/style.css`、`backend/frontend/js/app.js`、`backend/frontend/js/student.js`、`backend/frontend/index.html`、`backend/frontend/sw.js`、`scripts/ui_audit.js`、`scripts/style_parity.js` 以及对应审计/报告文档。
- **约束**：标准稿只作视觉计算值来源；线上真实结构与文案优先。测评页固定为自主练习、教师发布章节测评、薄弱点、巩固闭环四段，今日任务只能出现在学习页。
- **违规处置**：先以 `git diff` 回退结构/文案/事件变更，再修样式；`make ui-audit`、`node scripts/style_parity.js` 任一红即不得交付。任何新增机械断言必须附「植入违规 → FAIL」证据（diff 或 sha256、退出码）。

### v2.14.0 实现状态回写

- 进度数据三格使用闭合 `#E5DECC` hairline，三列等宽并垂直居中；全站组件沿标准稿暖纸 token 对齐。
- 测评页未复制标准稿旧帧的今日任务，线上四段结构与文案保持原样；学习页保留真实任务名与入口。

- **v2.14.0 火焰条款补充**：`streakBar()` 必须输出原版文本元素 `🔥 ${streak} 天`；五条学生路由均由 `appbar()` 常驻挂载。审计用正则 `/^🔥\s*\d+\s*天$/` 检查 `.streak-flame`，缺失即 FAIL。反证方式：临时将 `.streak-flame` 输出替换为空文本运行 `node scripts/ui_audit.js`，预期退出码 2；恢复后退出码 0。

## §12.67 v2.15.0 五屏组件级对齐
- 标准稿：`docs/reference/style-draft-2026-09-27.html`，计算值为唯一视觉目标；线上结构与文案保持不变。
- 组件映射：进度 `.feature→.dcard`、`.bignum→.dcard .hero .v`、`.stats→.dcard .grid`、`.progline→.chapter`；测评 `.sub→.appbar .sub`、`.row→.card`、`.primary→.btn`；知识卡片 `.kc-face→.kc-face`、`.btn→.kc-actions .btn`、`.kc-hint→.kc-hint`；学习 `.primary→.primary`、`.row.task→.task-card`、`.rowlist.grid .row→.home-card`、`.row.plain→.remind-card`；班级 `.row.task→.checkin-row`、`.row.me→.rank-row.me`、末行→`.btn.ghost`。
- `scripts/style_parity.js` 使用同一浏览器读取标准稿和线上计算值，逐项比较 rect 与九项样式值；任一差异或组件缺失退出 1。
- v2.15.0 进度英雄数字目标为 64px/900/墨色；三格横线满宽、竖线与横线端点相接、等宽。审计断言以该目标为准。
