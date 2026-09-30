# 逐组件渲染差异排除项（v2.16.0）

以下不是静默跳过；均为比对脚本映射项与线上实际路由结构不一致，依据为 `node scripts/style_parity.js --verbose` 的原始实测输出。

| 映射项 | 为什么这里不适用 | 依据（截图/实测值） |
|---|---|---|
| knowledge / 闪卡外框 `.kc-card` | `/knowledge` 是顶层导航路由，线上只有知识卡片列表；翻卡 DOM 仅在 `/learn` 进入异步复习态后生成，不能新增元素或改 JS 路由。 | 脚本实测 `MISSING(.kc-card)`；线上 `student.js:viewKnowledgeDeck()` 明确由 `knowledgeDeck` 状态控制。 |
| knowledge / 卡面 `.kc-face` | 同上，顶层列表不渲染翻卡卡面。 | 脚本实测 `MISSING(.kc-face)`。 |
| knowledge / 提示行 `.kc-hint` | 同上，提示行属于复习态而非列表态。 | 脚本实测 `MISSING(.kc-hint)`。 |
| progress / 章节名副行 `.chapter .nm em` | 线上保留已有的 `.chapter .mt.chapter-metrics`「已学/共」进度信息，标准稿使用 `em` 副行；两者角色不同，不能增删元素或改文案。 | 线上 DOM 实测 `MISSING(.chapter .nm em)`；`.chapter-metrics` 为 `display:block`。 |
| class / 徽章/达标 `.checkin-done` | 标准稿用 22×22 勾选框，线上已有达标文字标签；把文字替换成伪元素会改变线上文案语义，违反仅样式规则，故登记为结构角色不一致。 | 原始脚本实测线上 `50,17`、`background rgba(0,0,0,0)`，标准稿 `22,22`、珊瑚底。 |

## v2.18.0 收口 / Ray 拍板后复测（`node scripts/style_parity.js`：40 → 9）

下表逐项覆盖当前原始输出的 9 条剩余差异。`normal` 与 `0px` 语义等价，不计入差异。章节进度信息保持可见；不删节点、不改文案、不隐藏元素。

| 映射项／属性 | 标准稿 / 线上实测 | 原因与依据 |
|---|---|---|
| progress / 章节行 `.progline` → `.chapter` / `__rect` | 348×136 / 348×145（任务书初期实测 185 高） | Ray 决定保留该元素（元素零删减），标准稿无对应元素。`student.js:1288` 的 `.chapter-metrics`「已学 n / 共 m」保持可见（审计验证非 `display:none`、高度 >0、文字存在）；额外高度属于结构差异，不能藏字或删除。 |
| progress / 章节标题 `.progline .nm` → `.chapter .nm` / `__rect` | 91×37 / 249×19 | 标准稿标题含 `em` 副行；线上 `.nm` 只含章名，进度在独立 `.chapter-metrics`（`student.js:1288`）。不强迫标题折行或添加副行。 |
| progress / 章节名副行 `.progline .nm em` → `.chapter .nm em` / 组件 | 存在 / MISSING | 线上无 `em`，由 `.chapter-metrics` 呈现不同进度信息；仅样式规则禁止增加节点。 |
| knowledge / 闪卡外框 `.kc-card` / 组件 | 存在 / MISSING | 顶层 `#knowledge` 呈现学习 hub；翻卡 DOM 在异步复习态生成（`student.js:viewKnowledgeDeck()`）。 |
| knowledge / 卡面 `.kc-face` / 组件 | 存在 / MISSING | 同上，顶层路由不渲染翻卡卡面。 |
| knowledge / 提示行 `.kc-hint` / 组件 | 存在 / MISSING | 同上，提示行属于复习态。 |
| knowledge / 主按钮 `.btn` → `text=开始复习` / 组件 | 存在 / MISSING(text=开始复习) | 当前 `scripts/style_parity.js` 改用文字定位，但冷载顶层 `#knowledge` 是学习 hub；真正「开始复习」在 `#learn` 点击知识卡片入口后异步列表态（`student.js:447-510`），不改路由/节点来伪造命中。`make ui-audit` 已实际进入该列表，验证其 348×81、圆角 14、字重 800。Ray 拍板：该按钮是页面唯一主操作，配色按线上主色（橙 `#F2714E` / 白字），不按标准稿次级配色 `#F1EBDD` / `#6B6252`。 |
| learn / 任务名 `.task b` → `.task-label` / `__rect` | 204×30 / 107×30 | 标准稿将任务标签和数字放在不同结构；线上 `.task-label` 内含 `.task-progress` 且另有 `.mini-btn`（`student.js:169-170`），不以空白宽度挤压按钮。 |
| class / 徽章/达标 `.tick` → `.checkin-done` / 组件 | 存在 / MISSING | 文字标签「✓ 已打卡」仅在已打卡状态渲染（`student.js:1439`）；当前首行未达标，不伪造达标 DOM。 |
