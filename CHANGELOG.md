# Changelog

## [2.1.1] - 2026-09-08

### Fixed
- **对话标签与滚动体验**：对话 pill 禁止压缩换行并按内容居中；进入会话、发送上屏与 TUTOR 回复后均自动贴底。
- **知识卡片翻转**：拖拽后的合成 click 抑制会在 400ms 和换卡后复位，新卡首次点击即可翻转。
- **AI 学习建议**：建议同时使用当天数据与最近 7 天实际活动、章节掌握度、错题知识点和最近测评；近期已有测评时不再误提示「测评还没做」。

## [2.1.0] - 2026-09-08

### Fixed
- **知识卡片甩出方向反了**：左滑（=没记住）之前触发 `reviewKnowledge(true)` 向右飞出；右滑同理向左。修正判定为 `dx > 0 → 记住了（向右飞出）`，与按钮/提示文案一致（touch + mouse 双路径）。
- **对话发送不即时上屏**：发送后 `render()` 重拉会话消息把本地刚 push 的用户消息冲掉，要等 TUTOR 回复才一起出现。新增 `_noReload`：等待回复期间重绘跳过服务器消息重拉，输入内容立即上屏 + 思考气泡。
- **「自主练习 · 最多 5 题」文案与事实不符**：入口卡/后端 docstring 残留旧口径（实际可自选 5-10 题），统一改为「5-10 题自选」。
- **AI 学习建议从未出现**：依赖 launchd 22:00 定时脚本生成，但线上从未生效 → 改为**进度页手动点击生成**，一天最多一次（当天已有直接返回，幂等）。

### Added
- **知识卡片 → 对话「去问 TUTOR」**：点开任意卡片（列表页点卡 → 详情 sheet 显示正/反面 + 复习状态）→「去问 TUTOR」自动跳到对话页并提问该知识点；请求带 `kc_ctx`（卡片 front/back/sub_concept/chapter_id），TUTOR 以卡片答案为可靠上下文做**发散详细讲解**（先讲透概念 → 结合资料展开 → 举例 → 易错点 → 延伸问题，不受 180 字限制），卡片答案不进入聊天历史文本。
- **练习历史左滑删除**：自主练习历史条目（进行中/已完成均可）左滑露出红色「删除」，确认后删除该练习会话及其题目（错题不再计入薄弱点依据）；后端 `DELETE /api/practice/<session_id>` 带归属校验（F9）。
- **AI 学习建议点击生成**（承接 Fixed 条目）：进度页「AI 学习建议」卡无建议时显示「生成今日建议」按钮（AI 按当天对话/练习/测评/薄弱章节给 3 条建议）；有建议显示生成日期 +「每天最多一次」。统计与文案逻辑抽到 `ai/advice_gen.py`，定时脚本 `daily_advice_gen.py` 与 API 共用同一口径（消灭双份漂移）。
- **进度页掌握度口径解释**：知识卡片块下方新增可展开「掌握度怎么算？」——测评/练习按得分、知识卡仅已掌握计入（每张 5 分满分）、权重按距上次复习周数减半衰减、四态阈值，全部用大白话写清。

### Changed
- **对话页移除「知识卡片」入口按钮**：卡片入口统一在学习主菜单（学习页资料库勾选 + 知识卡片入口卡），对话 composer 仅保留「咨询错题」（卡片 → 对话为单向「去问 TUTOR」）。
- **题数选择框放大**：自主练习题数 `<select>` 从原生小框改为大号选择器（44px 高、更大字号与点按区）。
- 知识卡片翻卡时 `.kc-hint` 文案与修正后方向一致（右滑=记住了 · 左滑=没记住）。

## [2.0.0] - 2026-09-08

### Changed
- **学习资料库改「可滚动多选 list」（学生选章入口统一）**：学习主菜单资料库每章带圆形勾选框，多选列表超出屏高可滚动；右上显示「已选 N」计数，底部「全选/清空」快捷操作；勾选记忆在 localStorage，下次进入自动恢复。对话页原横滑选章卡撤除——选章统一在学习页做。
- **多选集驱动跨章（REQ-KNOW/CHAT 检索范围升级）**：勾选多章后——① 对话提问按选集逐章 RAG 检索合并去重，回答片段自动标注【章名】防资料混淆；② 知识卡片列表 = 所选各章全部卡片，按章分组折叠展示（点章头展开卡网格），「开始复习」大按钮置顶（跨章合并卡组，每卡标章名）；路径提问仍按该 session 章节检索（优先级不变）。
- **知识卡片复习交互动画**：翻转不再整页重建——改为同一 DOM 切 class 驱动 3D 翻转过渡；卡片支持**跟手拖拽**（touch + mouse）：横向拖动卡片跟手位移/倾斜，超 70px 甩出判定（右滑=记住了 / 左滑=没记住），未超阈值弹回原位；按钮点击同样先播飞出动画再提交；换卡带入场动画。
- **知识卡片进度计入掌握度 M（PROG-007 口径扩展）**：`compute_mastery` 并入该章 mastered 知识卡——每张按 5 分满分计，权重 w 按 `last_review_at` 时间衰减（0.5^周，与测验作答同口径）；**仅奖不罚**：new/learning/reviewing 卡不进分子也不进分母，避免拖累 M；作答次数同步计入（满足 master 态 ≥2 次要求）。效果示例：quiz 40% + 30 张 mastered 卡 ≈ M 76%。进度页新增「知识卡片（计入掌握度）」块：各章已掌握/总数、学习中/未学/今日待复习、掌握百分比条与徽章。

### Fixed
- **复习续学兼容多章卡组**：localStorage 进度签名从单 `cid` 扩展为章 id 集（`ids`），换选集后不再误续旧进度；旧格式 `{cid}` 单章进度仍可继续。

## [1.19.0] - 2026-09-08

### Added
- **学习主菜单（hub）两入口（学生导航重构）**：「学习」tab 进入 = 学习主菜单：上方资料库竖排选章 + 下方两个入口大卡——**对话**（向 TUTOR 提问/咨询错题）与**知识卡片**（本章知识点翻卡复习）；对话页与知识卡片页 appbar 均带「← 返回」按钮，随时退回主菜单（再次点学习 tab 也强制回主菜单）。
- **知识卡片复习可暂停/退出/续学（REQ-KNOW）**：复习卡组顶部返回 + 底部「暂停退出（保存进度）」按钮，进度存 localStorage；再次「开始复习」弹「继续上次复习？」（继续/重新开始）；复习完成自动清进度。离开学习区（切其它 tab）自动退出卡片全屏态。

### Fixed
- **「操作过于频繁」误伤（NFR-006 限流结构缺陷，hermesstu 血泪）**：`rate_limit` 原本所有限流端点**共享同一 user_id 桶**（60 次/24h）——知识卡 GET/翻卡这类高频非 LLM 请求会挤占对话/练习/测评的额度，学生没聊几句全 app 429。修复：① 桶 key 加 `request.endpoint` 维度（每端点独立 60/天，互不挤占）；② `GET /api/knowledge/<chapter>` 与 `POST /api/knowledge/<id>/review` 摘除限流（纯读写无 LLM，翻卡属正常高频交互）。

## [1.18.1] - 2026-09-08

### Changed
- **练习跨会话知识点去重强化（PRACTICE-001）**：`quizzer._practice_system` 提示词改为「每题必须来自不同子概念 + 禁止清单」，`generate_practice_questions` 排除已练知识点后仍不足 count 时自动重试（最多 2 次）补齐——确保「这次 5 题 ≠ 下次 5 题」，约 4-5 次练习才重复。

## [1.18.0] - 2026-09-08

### Added
- **知识卡片发布自动生成（REQ-KNOW-001/002/003）**：学习路径或资料发布时生成章节共享卡片；学生首次浏览懒建个人复习态，互不影响。
- **练习题数与知识点覆盖（PRACTICE-001）**：自主练习可选 5-10 题（默认 5），跨会话避开已练子概念与重复题干。

## [1.17.0] - 2026-09-08

### Added
- **知识卡片（REQ-KNOW-001/002/003）**：章节资料抽取个人卡片，支持翻转、左右滑复习、学习次数及 1→3→7 间隔状态机。

### Changed
- **练习知识点全覆盖（PRACTICE-001）**：全章多样化材料抽样，并优先按 `sub_concept` 去重出题。


本项目遵循「版本号诚实规则」（CLAUDE.md §5）：任何产生 CHANGELOG 条目的改动，须同 commit 将 `backend/app.py` 的 `version` 常量 bump 到一致。

## [1.16.2] - 2026-09-08

### 修复
- **学习页顶部缝隙彻底根治（根因：`.seg-sticky` 硬编码 `top:74px`，但 appbar 在 iOS 实际渲染高 71px，留 3px 透明带，滚动时内容（资料库横向卡片/对话消息）从中间漏出）**：把 appbar 与「引导式/直接讲解」模式切换合并为**同一个 `.chat-head` 吸顶块**（`position:sticky;top:0`），二者成为同一不透明容器、一起钉在 `top:0`，从结构上消灭「appbar 与 seg 之间的独立缝隙」——不再依赖任何硬编码 top 对位。`.chat-head .appbar{position:static}`（去掉 appbar 自身 sticky，避免与 chat-head 抢位），`.chat-head .seg-wrap{background:var(--bg)}`，去掉旧的 `.seg-sticky{top:74px}`。
- **v1.16.1 修复不彻底的原因**：当时把 `.content.chat-view{padding-top:0}` 后只在桌面 headless 验证 `gap_px=0`，但桌面 appbar 恰渲染 74px、掩盖了 iOS 上 71px 的 3px 位移差。本次用 Playwright iPhone 13 profile + 注入 30 条真实对话 + 资料库横向卡片实测：`gapBetween=0`（appbar 底 71 与 seg 顶 71 完全相接）、逐 2px 扫描头顶不透明度 `leakCount=0`（全 opaque），path/progress/class/quiz 视图 appbar 保持 sticky 不受影响。

## [1.16.1] - 2026-09-08

### 修复
- **学习页顶部缝隙（appbar 与模式切换之间漏内容）**：`body` 为滚动容器时 `position:fixed` 子元素在 iOS 上不稳；将 `#app` 改固定高度（`100vh/100dvh` + `overflow:hidden`）+ `.screen` 设为唯一滚动容器 + `.appbar` 改 `position:sticky`。仍残留缝隙根因：`.content.chat-view` 的 `padding-top:6px` 导致 `seg-sticky` 自然 offsetTop=80（=appbar 74 + 6），未滚动时与 appbar 间有 6px 透明带，滚动时内容从此漏出。修复：`.content.chat-view{padding-top:0}`，seg 自然位即 74 与 appbar 齐平，`gap_px=0`（全滚动位置实测）。headless Chrome 点查头顶 3 采样点全部为 opaque 元素（appbar/seg/on），无内容透出；登录/班级/进度/测评视图无回归。

## [1.16.0] - 2026-09-08

### 修复
- **自主练习出题全走兜底（根因：推理模型烧预算）**：生产 `.env` 的 `DEEPSEEK_MODEL` 由 `deepseek-v4-flash`（原生推理模型）改为 `deepseek-chat`（非推理）。实测同一 QUIZZER prompt 下推理模型 `finish_reason=length`、`content len=0`、`reasoning len=3612`（2000 completion_tokens 全烧在 reasoning）→ `_chat()` 拿空 content → `quizzer_generate()` 返回 None → 无条件兜底 20 道通用模板（与章节资料无关）；改 `deepseek-chat` 后返回 `content len=4871`（真实资料题）、`reasoning len=0`。与四口之家 sikou「智能养护贴士」修法一致（短/结构化任务用 deepseek-chat）。`agents._chat` 默认 model 兜底已为非推理 `deepseek-chat`（`config.py` 默认亦然）。

### 新功能
- **自主练习改为「最多 5 道 · 只选择/是非 · 难度 high · 资料驱动 · 同学生不重复」（REQ-PRACTICE-001/002/003 重构）**：
  - 不再强制 20 道/100 分：`quizzer.generate_practice_questions()` 基于章节资料出 2~5 道 choice/bool（difficulty=hard），删除「凑 100 分」的 `_trim_to_100`/`_fill_to_100`/`_TARGET_UNITS` 逻辑；`generate_practice` 端点放开 `total != 100` 校验，`total_points` 写入实际各题分之和，`_session_dict` 按实际 `total_points` 归一（`total_points or 1`）。
  - 资料驱动 + 高难度：RAG 检索章节资料正文注入 QUIZZER_SYSTEM（`{retrieved_chunks}`），练习固定 `difficulty=hard`；LLM 真返空时返回空列表、由前端提示「生成失败，请重试」，不再硬塞通用模板。
  - 同学生跨会话去重 + 变体衍生：`practice_questions` 新增 `content_hash`（题干规范化 hash，去空格/标点/大小写）；`generate_practice` 生成前查该学生历史题干注入提示词「避免重复、基于资料衍生变体」，后端 `_cap_to_max` 再按规范化 hash 过滤历史已出题干。不同学生可相同、同考点不同问法不算重复。
  - 前端：练习入口/生成页/答题页文案从「合计 100 分」改为「最多 5 题 · N 题 · 共 X 分」。
- sw.js `CACHE` bump `v31→v32`。

## [1.15.0] - 2026-09-08

### 新功能
- **班级页新增「今日练习次数」指标（REQ-CLASS-003 强化）**：`GET /api/class/leaderboard` 新增 `today_practice`（按 UTC+8「今天」过滤 `practice_sessions.created_at`，复用 `timeutil.shanghai_date`，与 `today_turns`/`today_conversations` 一致），返回 `_sorted_entries` 排序结果。
- **班级页主屏改「两张排行榜卡片 + 其余收进弹出层」**：学生端 `viewClass()` 由 6 个分类 chips 横向切换改为主屏直接展示 **① 今日对话次数 ② 今日练习次数** 两张卡片，每卡前 3 名显示**金/银/铜奖牌**（新增 `app.js` `ICO.medal` 内联 SVG + `.rank-num.medal.{gold,silver,bronze}` 圆形徽章，替代 emoji），第 4 名起普通序号；其余排行榜（累计对话轮 / 累计练习 / 测评分数 / 掌握度）收进底部弹出层（复用 `.sheet-mask`/`openSheet`），点「更多排行榜」打开、点「关闭」收起。测评分数榜 chip 切换后重开弹层。

### 修复 / UI 优化
- **学习页「引导式/直接讲解」toggle 吸顶（REQ-CHAT-004 强化）**：`.seg` 从内容流中提出、包进 `.seg-sticky`（`position:sticky;top:74px` 对齐 appbar 底），对话滚动时模式切换固定顶部、始终可见，不遮挡 appbar（appbar z-index 20 > seg 15）。
- **学习页资料库「越新的在越左边」（REQ-MAT-004 强化）**：`GET /api/chapters` 返回补 `created_at`，前端 `viewLearn()` 按 `created_at` 倒序渲染章节卡片（最新添加排最左），不影响选中态 /「N 篇」徽章 / 单章竖排·多章横滑逻辑。
- **输入框彻底钉底（关键 bug 根治）**：v1.14.2 把滚动从 `.screen` 移到 `body` 后，`body` 仍保留 `-webkit-overflow-scrolling:touch` —— iOS 下该属性会让 `position:fixed` 的 `.composer`/`.tabbar` 跟随滚动容器回弹/被挤走。修复：删除 `body` 的 `-webkit-overflow-scrolling:touch`，使 body 正常滚动时 fixed 输入框稳定钉在 `.tabbar`（高 78px）正上方；`.composer` 无 transform/filter/will-change/overflow 祖先（headless Chrome 实测滚动前后 `getBoundingClientRect().y` 恒定）。
- sw.js `CACHE` bump `v30→v31`。

## [1.14.2] - 2026-09-07

### 修复
- **学习页输入框「皮筋回弹」**：`.composer`/`.tabbar` 被塞进 `.screen`（`overflow-y:auto` 滚动容器），iOS 的 `-webkit-overflow-scrolling:touch` 会让 fixed 元素跟随滚动容器回弹。修复：滚动改交 `body`（`.screen` 改 `overflow:visible`），composer/tabbar fixed 相对 viewport 稳定；`.content.chat-view` 底部留白 74px→118px（composer 实测高 108px），滚动到底消息不再被输入框盖住。
- **对话多轮上下文丢失**：`tutor_orchestrate` 用当前单条消息做 RAG 检索，学生发承接语（「你帮我展开」「继续」等）检索不到资料 → `if not chunks` 直接 empty 兜底，LLM 未承接上下文（截图「没找到相关内容」）。修复：① 检索空时回退用最近一轮实质用户提问再检索；② `if not chunks and not wrong_ctx` gate 放宽为 `and not history`（有历史上下文时放行让 LLM 承接，不因单轮检索空打断）。新增 `_last_user_substantive()`。
- sw.js `CACHE` bump `v29→v30`。

## [1.14.1] - 2026-09-07

### 修复
- **资料下载进度条不显示（百分比缺失）**：`api.js` 三个 `_dlProgress*` 方法开头误写 `if (typeof $ === "undefined" || ...) return;`，而项目**无 jQuery**，`typeof $ === "undefined"` 恒真 → 进度条逻辑每次直接 return，永远不显示。修复：删除 `typeof $` 检查，改用 `document.getElementById("dlProgress")` 判存在。
- 进度条更新加节流：百分比不变不重写 DOM（`_lastPct`），避免大文件大量小 chunk 频繁重绘卡顿。
- sw.js `CACHE` bump `v28→v29`。

## [1.14.0] - 2026-09-07

### UI 优化（方向 A 原味精修 + 信息层级重排，全量所有视图）

学生端（`student.js`）+ 教师端（`teacher.js`）+ App shell（`app.js`）全局 UI 治理，只动视觉与层级，token（学生珊瑚 #F2714E / 教师靛蓝 #5B5BD6 / 米底 #FBF7F2）与布局完全不变。

- **去 decorative emoji → 共享内联 SVG 图标**：新增 `app.js` 的 `ICO` 图标库（book/video/chat/lightbulb/target/file/edit/grad/shield/clock/pin/eye/sparkle/plus/check/cross/download/arrowUp/back/warn）+ `ic(name, cls)` helper，替换全部 22 种装饰 emoji（📚🎬💬📄🎯📝🧑🎓🛡🧭📌📖💡👁⚠🎉 等）。语义字符（✅❌→✓⬇▶）保留。
- **抽内联样式 → 工具类**：新增 `.sec-title`/`.sec-title-sm`/`.sec-head`/`.mt-8/.mt-10/.mt-12`/`.mb-8/.mb-10/.mb-12`/`.grow`/`.flex`/`.ic`，替换高频内联 `font-weight:700;margin-bottom:8px`（8 处）、`flex:1`、`margin-top:12px` 等。
- **信息层级重排（学习页为主）**：
  - 模式切换 pill → **segmented control**（`.seg`），当前模式白底高亮 + 凹陷态，一眼看出「直接讲解/引导式」。
  - AI 声明条从加粗 emoji 🛡 → **安静的 `.ai-info`** 小字条，不再占视觉焦点。
  - 资料库 → 标题行加 **「N 篇」计数徽章**（`.card-count`），选中章节加**左珊瑚条**（`.chapter.active::before`）。
  - 新对话/轮数散放 → 独立**进度行**（`.row-meta`）。
  - 底部「咨询错题」从灰 pill → **珊瑚行动按钮**（`.tool-btn`）。
- **统一测评标题规范**：学生端答题页 `viewQuizTake` 标题从 raw `q.title` 改为「测评 · 第X周 第Y节」（`q.session` 反查 → session 名），对齐 v1.12.2 规范；无 session 回退 `q.title`。
- app.js 渲染错误态 `⚠️` → `${ic('warn')}`（`.note .big` 图标 40px）。
- sw.js `CACHE` bump `v27→v28`。

## [1.13.7] - 2026-09-07

### 修复
- **学习页对话输入区（composer）布局错乱**：`.composer` 横向 flex 下，按钮行（💡咨询错题）与输入行（input+send）被并排挤压，导致发送按钮点不到。修复：composer 内部包 `.composer-body`（纵向 flex：按钮行 / 选错题提示 / 输入行），「已选 N 道错题随本条发送」小字从按钮右侧移到按钮**下方**独立一行。
- sw.js `CACHE` bump `v26→v27`。

## [1.13.6] - 2026-09-07

### 修复
- **班级活动「测评分数」下拉显示裸「草稿 · X 章」**：leaderboard 返回的 `quiz_list` 补 `label`（通过 `chapter_ids` 反查已发布 session → 「测评 · 第X周 第Y节」），前端 `quizChips` 改用 `q.label || q.title`——与测评列表标题规范（v1.12.2/v1.12.4）一致，避免已发布但未改标题的测评显示难看的默认值。
- sw.js `CACHE` bump `v25→v26`。

## [1.13.5] - 2026-09-07

### 变更
- **进度页薄弱点改独立页，按练习 / 测评分组，点组向下滚动展示错题，移除横向卡片**：学生端进度页底部「薄弱点（带错题依据）」由内嵌展开大卡改为简洁入口卡（「📌 薄弱点 · N 章 · M 道错题 ›」），点击进入独立薄弱点页（新 hash `#weak`，`Student.viewWeak()`）。
- 独立薄弱点页：章节纵向列表（掌握度 M + 错题数）→ 点章展开 → 章内按「练习错题 / 测评错题（第X周 第Y节）」分组 → 点组向下滚动展开全部错题（`fmtWrongCard` 纵向排列，杜绝横向滚动/横向卡片）。
- 后端 `progress.py` `_wrong_evidence`/`_practice_wrong` 去掉 `limit=5` 截断，薄弱点错题依据全量返回（聚合逻辑不变）。
- sw.js `CACHE` bump `v24→v25`。

## [1.13.4] - 2026-09-07

### 变更
- **TUTOR 辅导模式可切换（引导式 / 直接讲解），默认直接讲解**：学生端学习页顶部「🧑‍🎓 引导式」写死 pill 改为可点切换的两态开关（`🧑‍🎓 引导式` ↔ `💬 直接讲解`），选择写入 `localStorage("aistudy_tutor_mode")`，默认「直接讲解」。
- 后端 `post_message` 读取 `tutor_mode`（仅 `guide`/`direct`，非法或缺失默认 `direct`）传入 `tutor_orchestrate`；`TUTOR_SYSTEM` 新增 `{tutor_mode}` 槽位——普通提问按模式分流：直接讲解（给答案+解析）/ 引导式（苏格拉底反问）。
- **错题恒直接解析**：带错题咨询（`wrong_ctx` 非空）无论开关状态一律强制直接逐题输出完整解析（保持 v1.13.0 逻辑不变）。
- sw.js `CACHE` bump `v23→v24`。

## [1.13.3] - 2026-09-07

### 变更
- **资料下载改分块流式 + 进度百分比**：`api.js` `download` 由一次 `resp.blob()`（等全量拉完才有反应，大文件看起来卡死）改为 `ReadableStream` 分块流式读取。边下边更新进度条（`#dlProgress`）：有 `Content-Length` 显示「下载中 N%」+ 进度条宽度；无总长退化为显示已下载 MB。「已开始下载」toast 保留，延迟 revoke 保留（防 load failed）。
- 新增下载进度条 DOM（index.html）+ 样式（style.css）；无流式能力的老浏览器退化为一次 blob。
- sw.js `CACHE` bump `v22→v23`。

## [1.13.2] - 2026-09-07

### 修复
- **资料下载偶发 load failed**：`api.js` 的 `download` 在 `a.click()` 后**立即 `URL.revokeObjectURL`**，浏览器尚未读取 blob 就撤销对象 URL → 偶发「download load failed」。改为**延迟 revoke(120s)**。
- 下载过程加 `loadingOn/loadingOff` + 完成 `toast`，避免大文件(pptx/pdf)全量拉取时无反馈、看似卡死。
- sw.js `CACHE` bump `v21→v22`。

## [1.13.1] - 2026-09-07

### 修复
- **自主练习批改结果页**的「逐题解析」原本显示数字索引（`你的答案：2 / 参考：1`），改为与测评一致：choice/bool 显示**完整选项**并标注 ✅正确答案 / ❌你的答案（choice 索引→字母文本），essay 回退文本；保留每题得分。
- sw.js `CACHE` bump `v20→v21`。

## [1.13.0] - 2026-09-07

### 变更
- 学生「咨询错题」TUTOR 辅导**关闭引导式（苏格拉底反问）**，改为直接输出**结构化错题解析**：逐题「题目 → 你选❌ → 正确✅ → 解析(正确为何对/你选为何错) → 其他选项排除 → 核心考点」，多题末尾加「简单记忆口诀」。
- `_format_wrong_ctx` 增强：错题上下文带完整选项+字母标注+考点（供 TUTOR 输出 `A.写一篇散文` 这类）；`TUTOR_SYSTEM` 引导规则按是否带错题分支（带错题→直接解析；不带→保留引导式）。

## [1.12.4] - 2026-09-07

### 修复
- **学生「咨询错题」TUTOR 没拿到错题**：`tutor.py` 的 `if not chunks:` 门控在 `rag.retrieve` 无资料片段时直接返回「没找到资料」兜底，**忽略了 `wrong_ctx`**——学生带错题来咨询、恰好该轮检索不到资料时，TUTOR 不会讲错题。改为 `if not chunks and not wrong_ctx`：有错题时即使无资料片段，TUTOR 也按错题（题干+学生答案+参考答案）辅导。
- **咨询错题选择器标题**改显「测评 · 第X周 第Y节」，不再显示草稿默认标题「草稿·X章」。
- sw.js `CACHE` bump `v19→v20`。

## [1.12.3] - 2026-09-07

### 变更
- 进度页「薄弱点」错题明细改为**点进去按测评展开**（不再摊开）：薄弱章卡片可点击展开 → 按测评分组列出（测评 · 第X周 第Y节）→ 点某测评展开该测评错题（题目+选项+你的答案+正确答案）；练习错题单独成组。
- weak-points 后端 evidence 增加 `quiz_id` 供按测评分组；sw.js `CACHE` bump `v18→v19`。

## [1.12.2] - 2026-09-07

### 修复
- 学生端/教师端测评列表标题改显「测评 · 第X周 第Y节」（关联已发布 session 的周/节），不再显示草稿默认标题「草稿 · X章」；副标题含 session 标题（无 session 回退原标题）。
- sw.js `CACHE` bump `v17→v18`；前端 `student.js`/`teacher.js` 周/节标题无功能回归（教师端「👁 学生错题」入口保留）。

## [1.12.1] - 2026-09-07

### 修复
- 学生端前端崩溃（`Can't find variable: Student`）：CC 交付 v1.12.0 时在 `student.js` 插入「咨询错题」方法时误删了 `send()` 的方法声明（`async send() {`），导致 `send()` 函数体散落成非法语法、整个 `student.js` 解析失败 → `Student` 未定义、前端白屏报错。已补回 `async send() {`（前端 JS 语法修复）。
- sw.js `CACHE` bump `v16→v17`。

## [1.12.0] - 2026-09-07

### 新增
- 教师可在「出题 / 发布」的已发布测评中打开「👁 学生错题」：仅列出已作答学生，展示其得分及完整错题（题目、全部选项、正确答案、学生答案）。
- 学生学习页新增「💡 咨询错题」：选择已作答测评后，按关联的「第 X 周 第 Y 节 · session 标题」识别来源；本人的错题随下一条对话交给 TUTOR，获得针对性思路讲解与巩固引导。
- `GET /api/quizzes` 为测评补充已发布课程 session 标注；新增教师专用 `GET /api/quizzes/:id/student-errors`。

### 变更
- TUTOR 对话接口支持受限的 `wrong_ctx`，只注入已作答错题的题目、学生作答与正确答案；发送成功后前端清除上下文，避免后续消息误带。
- Service Worker CACHE `v15` → `v16`，确保客户端加载新界面。

### 版本
- `app.py` → `1.12.0`。


### 新增
- 学生端测评结果错题改为**完整展示**：题目 + 全部选项，绿色标注「✅ 正确答案」、红色标注「❌ 你的答案」（choice 索引→选项文本；bool 正确/错误；essay 显示你的回答 vs 参考答案）。
- 测评**一次作答**：提交后不可重做（返回 400「该测评已作答，不能重复提交」），分数保留首次；已做过的测评再点进去恒显示该次结果（分数+错题），不进入答题页，之后从哪进都显示同一结果。
- 进度页**薄弱点**错题完整展示（去除仅 2 条摘要）：每个薄弱章的错题显示完整题目+选项+你的答案+正确答案（测评错题+练习错题都纳入）。

### 变更
- 错题接口（`report` / `weak-points` evidence）补充 `type`/`options` 字段供前端完整渲染；一次作答取首次成绩（`MIN(created_at)`），与「只能做一次」语义一致。

### 版本
- `app.py` → `1.11.0`；sw.js `CACHE` bump `v14→v15`。

## [1.10.2] - 2026-09-07

### 修复
- 教师端「已发布的测评」卡片原仅有「重出」无预览入口；新增「👁 预览」（复用 `Teacher.preview`，调 `GET /api/quizzes/:id` 展示题目/分值/答案）。预览弹窗标题与底部按钮按状态适配：草稿→「草稿预览」+「确认发布」，已发布→「测评预览」+仅「关闭」（已发布无需再确认发布）。
- sw.js `CACHE` bump `v13→v14` 强制手机端缓存失效拉取新版。

## [1.10.1] - 2026-09-07

### 修复
- 学生端测评答题页「返回列表」按钮无响应：`viewQuizTake()` 内联 `onclick` 只清无关的 `App.activeQuiz`（`Student.render()` 不用它分派），未清 `Student.quiz/answers/result`，而 `Student.render()` 按 `this.quiz` 分派 → 点击后仍停留答题页。改为清 `Student.quiz=null; Student.answers={}; Student.result=null`（与结果页「返回测评列表」一致），返回测评列表生效。
- sw.js `CACHE` bump `v12→v13` 强制手机端缓存失效拉取新版。

## [1.10.0] - 2026-09-03

### Changed
- **取消问答题（essay），固定 20 道选择/是非每题 5 分**：老师发布测评与学生自主练习两个出题路径一律不再生成 essay（问答题），题型仅限选择题（choice）与是非题（bool）。`quizzer.PRESETS` 只保留无 essay 组合（`20c`=20 选择 / `20b`=20 是非，默认 `20c`），删除 `10c5e`/`8c6e`；`default_config()`→`{"choice": 20}`，`validate_config()` 只接受 choice/bool；`_spec_text` 改为「20 道选择题/是非题，各 5 分，合计 100 分」。`POINTS` 仍保留 `essay=10` 以兼容库里旧题数据（`norm_question` 保留 essay 分支）。
- **出题去重**：新增 `quizzer._dedup()` 按题干 `content` 去重（保留首条）；`_enforce_config` 的模板兜底按 idx 轮转并跳过已出现的 content；`_TEMPLATES` 的 choice/bool 池扩充到各 20 条唯一题。`generate_questions` 与 `generate_practice_questions` 返回前统一 `_dedup`，确保最终集无重复题干。
- **练习出题固定 20 道**：`generate_practice_questions`/`_trim_to_100`/`_fill_to_100`/`fallback_practice_questions` 全部禁止 essay——AI 输出中的 essay 被丢弃，`_fill_to_100` 只用 choice/bool 模板补足到恰好 20 道（合计 100 分）；练习兜底改为 `_enforce_config([], {"choice": 20})`。
- **提示词收紧**：`QUIZZER_SYSTEM` 明确「只允许 choice/bool，严禁 essay」，规格改为「20 道题，每题 5 分，合计 100 分」，并加「题目不得重复：每道题的题干必须不同」。
- **教师出题前端**：`teacher.js` 的 `quizConfig` 默认 `{choice: 20}`，`QUIZ_PRESETS` 只含「20 选择 / 20 是非」，自定义输入移除「问答」字段，校验改为 `choice + bool === 20`（合计 100 分）。
- **Service Worker CACHE `v11` → `v12`**：强制用户端拉取出题改动。
- **版本 `1.9.0` → `1.10.0`**。

## [1.9.0] - 2026-09-03

### Added
- **班级功能（REQ-CLASS-001~006）**：新建 `class_bp`（`/api/class`），全部 active 学生（除 `Hermestest` 测试账号）同属一个班级，用实名展示。`GET /api/class/leaderboard` 一次返回 6 类排行榜：
  1. 累计对话轮次（累计 user 消息数）
  2. 累计练习次数（practice_sessions 数）
  3. 今日对话轮次（今天 UTC+8 的 user 消息数）
  4. 今日对话次数（今天 UTC+8 发起的对话会话数）
  5. 每次测评的分数排名历史（列出该次测评全体学生分数与排名，未参加标注「未参加」，另附「已发布测评列表」供选择）
  6. 掌握度排行（各学生已评估章节 `compute_mastery().m` 的均值「平均 M」排序，可附「已掌握 X 章」；未评估章节不计入、不当 0）
  - 学生/教师均可访问；`Hermestest` 绝不出现；教师视角额外返回共性薄弱章节（≥2 人）。
- **AI 学习建议改每日（RPT-003 改每日）**：新增 `daily_advice` 表（`UNIQUE(user_id, advice_date)` 幂等）；`GET /api/progress/advice` 返回最近一条（优先今天 UTC+8）。新增脚本 `backend/scripts/daily_advice_gen.py`（遍历 active 学生，按当天 UTC+8 对话/练习/测评数据生成建议，复用 `agents.tutor_reply`，失败模板兜底）+ launchd plist 模板 `deploy/com.aistudy.daily-advice.plist`（每天本地 22:00 触发，仅写脚本与 plist，不安装）。

### Changed
- **练习计入掌握度 M（推翻旧 F3）**：`compute_mastery()` 除聚合该章最新 published version 的 attempts 外，**额外聚合该章自主练习 `practice_questions`（answered_at 非空）**，同一条加权公式（w=0.5^间隔周数、按章聚合、earned=score、possible=points），并计入「已掌握≥2 次」作答次数；仅当该章既无测评 attempt 也无练习作答时才返回 `m=None`（未评估）。练习错题仍进薄弱点/巩固练习（PROG-005/006 保留）。
- **移除难度标注（全 App 显示层）**：`practice_sessions.difficulty` 字段保留在库中但**前端不再展示** hard/难度；清理 student.js 练习入口/卡片/生成按钮/批改页的「难度高于正式测评」「hard · 合计 100 分」「生成练习（hard）」「· hard」等文案与 hard badge。教师端无难度展示，无需改动。
- **周报废弃 → 班级**：学生底部 tab「周报」改为「班级」（`ICONS.class` 人物图标，tab key `report`→`class`），教师底部 tab「周报」改为「班级活动」；`viewReport` 整体替换为 `viewClass()`/`viewClassActivity()`。周报原「本周概况（RPT-001）/成绩分析（RPT-002）」迁移至进度页下方，`GET /api/progress/weekly-stats` 提供数据。
- **进度页结构**：掌握度四态 stat-row → AI 学习建议 → 本周概况+成绩分析 → 各章节状态 → 薄弱点 → 巩固练习闭环。
- **对话输入框固定**：`.composer` 由 `position:sticky` 改为 `position:fixed;bottom:78px`（钉在五个导航按钮 `.tabbar` 之上），学习页内容区加底部留白；`visualViewport` 脚本写 `--kb` 补偿安卓键盘高度，键盘弹起输入框不错位。
- **「今天/今日」统一 UTC+8**：新增 `data/timeutil.py`（Asia/Shanghai），班级今日榜单与每日建议日期均按 UTC+8 日历日判定（存储 UTC，转时区后比日期）。
- **Service Worker CACHE `v10` → `v11`**：强制用户端拉取本次 tab/班级/进度/输入框改动。
- **版本 `1.8.0` → `1.9.0`**（新功能）。

## [1.8.0] - 2026-09-03

### Added
- **学生端自主练习（REQ-PRACTICE-001~003）**：学生在「测评」tab 可像老师一样**根据资料生成练习**（选章 → AI 出题 → 立刻做 → 立刻批改 → 立刻看答案），不进入老师发布状态机。
  1. **题型与数量由 AI 自主决定**：练习出题走独立入口 `quizzer.generate_practice_questions()`（difficulty=hard、AI 自由组合 choice/bool/essay），后端按题型分值强制校验合计恰好 100 分——超 100 裁剪、不足 100 先补发后模板兜底，任何情况保证 100 分（选择/是非 5 分、问答 10 分）。
  2. **难度 hard**：`QUIZZER_SYSTEM` 新增 `{difficulty}` 槽位与难度指示（normal 基础题 / hard 综合运用·多步推理·概念辨析·跨知识点）；老师测评默认 normal 不变，练习固定传 hard。
  3. **复用 GRADER 批改**：客观题确定性判分、问答题 AI/启发式三档，与测评完全一致；提交返回每题得分 + 正确答案（answer_key），作答前不露答案。
  4. **错题联动薄弱点/巩固（PROG-005/006）**：练习错题（correct=0 或 score<points）进入 `_practice_wrong`，作为薄弱点列表 `from_practice` 依据与「一键巩固练习」的来源章/聚焦子概念；**不改变测评掌握度 M**（M 仍只聚合 published quizzes）。
- **独立数据层（防污染）**：新增 `practice_sessions`（user_id/chapter_ids/difficulty/total_points/config_json）+ `practice_questions`（session_id/chapter_id/sub_concept/type/content/options/answer_key/points/correct/user_answer/score/reason/answered_at），均 `CREATE TABLE IF NOT EXISTS` 幂等建表，不塞进 quizzes/questions/attempts。
- **新增 API**：`GET /api/practice`（历史列表）、`POST /api/practice/generate`、`GET /api/practice/:id`、`POST /api/practice/:id/submit`（学生本人，越权 403）。
- **前端入口**：`viewQuizList()` 顶部新增「🎯 自主练习」卡片；练习视图支持多选章、生成、作答（复用 choice/bool/essay 渲染）、提交批改、逐题解析；进度页薄弱点标注「练习错题」。

### Changed
- **Service Worker CACHE `v9` → `v10`**：强制用户端拉取本次 `student.js` 改动。
- **版本 `1.7.2` → `1.8.0`**（新功能）。

## [1.7.2] - 2026-09-03

### Fixed
- **QUIZZER 出题接入 RAG 检索资料正文（根因①）**：`backend/ai/quizzer.py` 的 `generate_questions()` 出题前先对所选章节做 RAG 检索，把资料正文片段拼成 `retrieved_chunks` 注入 `QUIZZER_SYSTEM`，明确要求「严格基于下方检索到的资料内容出题、难度贴合资料实际」，只有资料缺失时再用通用知识出简单题——修复此前只传 `chapter_ids/sub_concepts/spec`、DeepSeek 凭通用知识出题导致难度漂移、不贴合学生上传课件的问题。`rag.retrieve()` 补支持 query 为空时直接返回章节资料片段（供出题等无 query 场景喂原文）。
- **修模板兜底重复题（根因②）**：`_enforce_config()` 在 DeepSeek 生成数不足配置数时，不再用同一个模板题硬塞 N 次；改为先向 DeepSeek 补发一次请求补足缺口题型，补发仍失败才用模板兜底，且兜底模板按 idx 轮转多样化（选择/是非/问答各 3 套），杜绝「5 道一模一样的怪题」。

## [1.7.1] - 2026-09-03

### Added
- **教师端测评草稿预览（QUIZ-001 P0 补全）**：生成草稿后，草稿卡片新增「👁 预览」按钮，点开用底部弹层展示该草稿全部题目（题型/分值/选项/参考答案），教师在确认发布前可审核题目内容与答案是否正确；预览弹层内可直接「确认发布」或「关闭」。补齐设计规格 QUIZ-001「生成草稿→预览微调→确认发布」中缺失的「预览」环节——此前草稿卡只有「确认发布/放弃」，无法点开查看题目。修复 ``GET /api/quizzes/:id`` 查询遗漏 ``answer_key`` 字段的问题（此前教师端预览拿不到答案，答案为 None）；学生端仍按原逻辑不返回 answer_key（作答前不可见）。

### Changed
- **版本 `1.7.0` → `1.7.1`**（修 bug/补功能）。
- **Service Worker CACHE `v8` → `v9`**：强制用户端拉取本次 ``teacher.js`` 改动（SW 的 ASSETS 缓存了 `/js/teacher.js`，引用不带版本号，需 bump CACHE 才能拿到新版，否则预览按钮不出现）。

## [1.7.0] - 2026-09-03

### Added
- **新对话标题自动总结对话内容（CHAT-008）**：学生发送首条消息时，后端 `post_message` 自动取首条用户消息前 18 字符（去多余空白）生成有意义的标题，替换默认「新对话」，避免对话 pill 列表一排「新对话」；响应同时返回 `title`。前端对话 pill 标题单行不折行、超出省略（`.pill-t`），修复「新对/话」折行观感。
- **对话 pill 长按删除（CHAT-008）**：学习页对话 pill 支持长按（~600ms，touchstart/touchend + mousedown/mouseup 双兼容）弹出底部确认层「删除对话/取消」，确认后调 `DELETE /api/conversations/:id` 删除并刷新；与单击切换 `selectConv` 不冲突（长按后抑制补发的 click）。
- **资料库多章节横向滑动卡片组（CHAT-002）**：章节 ≥2 个时资料库改为 `overflow-x:auto` 横向卡片（固定宽度、隐藏滚动条、可左右滑动），单章保持竖排；卡片仍显示章节名+分组名，点击仍切换 `App.activeChapter`。
- **下方小字随选中章节动态提示（CHAT-002）**：已选章节显示「已选择：{章节名}，开始提问（不会直接给答案）」，未选则提示「请从上方资料库选择章节，开始提问」。

### Changed
- **Service Worker CACHE `v7` → `v8`**：强制用户端拉取本次 `student.js/style.css` 改动。
- **版本 `1.6.0` → `1.7.0`**（新功能）。

## [1.6.0] - 2026-09-03

### Added
- **学生端对话/切换添加即时加载反馈（外网慢优化，纯前端）**：外网同学走 Cloudflare 隧道有 ~130ms RTT，点一下要等 1-2 秒像「没反应」。新增两层反馈——
  1. **全局加载条**（`api.js` 的 `request()` 统一驱动 + `app.js` 的 `loadingOn/loadingOff`）：所有 API 请求期间顶部显示「加载中…」旋转指示，并发计数、首个请求显示、全部结束隐藏。覆盖切章节/发消息/加载课程/下载等所有操作。
  2. **TUTOR 思考气泡**（`student.js` 的 `pendingReply` flag + `.typing` 三点动画）：发消息等待 DeepSeek 回复期间，对话区立即出现「TUTOR 正在思考」跳动气泡，响应后替换为真实回复；失败时移除气泡。

### Changed
- **Service Worker CACHE `v6` → `v7`**：强制用户端拉取本次改动的 `api.js/app.js/student.js/style.css`（`network-first` 联网必拿最新）。

## [1.5.1] - 2026-09-03

### Changed
- **TUTOR 对话不再每轮弹"相关视频课"（用户反馈"一直出现"）**：`tutor_orchestrate` 仅当学生提问**主动问及视频课**（含"视频/课程/b站/网课/看视频"等关键词）时才召回 `related_videos`，普通提问返回空数组（前端自然不渲染卡片）；TUTOR 提示词引导规则强化为**优先基于【资料依据】引导、多指向章节资料原文**，只在学生明确问视频时才提一句。（前端 `relatedVideos` 每次取后端返回，后端空则卡片消失。）
- **服务默认绑定 `0.0.0.0`（网络优化）**：`deploy/run.sh` 的 `HOST` 默认从 `127.0.0.1` 改为 `0.0.0.0`，允许局域网内手机/设备直连 iMac `192.168.50.22:5001`（实测 5ms，远快于 Cloudflare tunnel 的 130ms+，且 QUIC 易断连）。根治"点一下反应半秒"：后端此前只监听 127.0.0.1，手机只能走不稳的 quick tunnel。

### Added
- **AI 学习小组 app iCloud 定时备份（DEP-008）**：新增 launchd 任务 `com.xicheng.aistudy-icloud-backup`（每天 03:20），调用 `scripts/backup_icloud.sh`（wal_checkpoint 刷盘 + rsync 备份 db/uploads/chroma 到 iCloud Drive，保留 7 天）。此前只有四口之家的备份，本 app 备份脚本存在但未定时触发。

## [1.5.0] - 2026-09-02

### Changed
- **移除年级（grade）维度（前后端）**：学生端学习页删掉「🧑‍🎓 年级」pill；教师端新建学生表单删掉「年级（可选）」输入框及提交字段；后端 `/api/auth/login`、`/api/auth/register`、`/api/teacher` 列表不再返回/接收 `grade`。DB 保留 `grade` 列（不动 schema、避免迁移风险）但清空存量值。

### Fixed
- **学生进度页显示未发布章节的测评（bug）**：`/api/progress/mastery`、`/weak-points`、`/review-items/generate` 的 `_all_chapters` 改为只查询 `status='published'` 的章节——未发布 session（如 W1S2 保持 draft）的章节不再出现在学生进度/掌握度/薄弱点/巩固练习里，避免「学生看到两个未测评」的错误（发布状态机：章节 status 随 session 同步）。

## [1.4.3] - 2026-09-02

### Fixed
- **管理后台卡片头部改为两行布局**：标题（含副标题）独占一行、`flex:1` 完整显示；「上传/编辑/删除」按钮移到标题下方单独一行、右对齐——彻底解决长标题被按钮挤压成竖排/wrap 的问题（用户要求：按钮不必与标题同排）。
- **资料文件名完整显示不省略**：去掉 `text-overflow:ellipsis;white-space:nowrap`，改 `word-break:break-word` + `flex:1;min-width:0`，长文件名（如「1-智泊AI大模型解决方案专家课-2026.4.2-灵玑.pptx」）完整显示、必要时换行，不再被省略号截断。
- **PWA 缓存强制失效**：Service Worker `CACHE` 从 `v5` bump 到 `v6`，确保用户手机端能拉到本次 UI 修复后的 `teacher.js`。

## [1.4.2] - 2026-09-02

### Fixed
- **管理后台卡片标题竖排（灾难）**：`.adm-card .meta` 改 `flex:1 1 auto; min-width:0` + `.nm` 加 `overflow-wrap/word-break:break-word`，修复长标题（如「第1周·第1节·大模型是什么：概念扫盲」）在 flex 布局中被挤压成单字一行竖排的问题。
- **卡片头按钮分散不齐**：上传/编辑/删除三个按钮打包进 `display:flex; margin-left:auto; flex-shrink:0` 容器，统一靠右同排，修复因标题宽度不同导致按钮被 wrap 拆分到不同行的参差布局；资料行「下载/删」去掉行内 `padding` 覆盖、统一为标准 `.mini-btn`，长文件名 `flex:1` 可伸缩省略避免挤压。

## [1.4.1] - 2026-09-02

### Fixed
- **按钮尺寸统一对齐**：`.mini-btn` 统一 `height:32px; min-width:64px; display:inline-flex; align-items:center; justify-content:center; white-space:nowrap`，修复「下载/删/上传/编辑/删除」按钮因文字宽不同导致宽高不一、对不齐；学生路径页 `.dl` 下载按钮补样式。
- **禁止页面缩放（界面不稳）**：viewport 加 `maximum-scale=1.0, user-scalable=no`；`html/body` 加 `touch-action:manipulation` + `text-size-adjust:100%`，修复双指/双击缩放导致布局抖动的「灾难」观感。

## [1.4.0] - 2026-09-02

### Added
- **资料下载（方案 B，去重）**：`materials` 新增 `source_path`（源文件绝对路径，指向课件/），新增 `GET /api/materials/:id/download`（`send_file` serve 课件/ 源文件）；学生/教师前端加「⬇ 下载」按钮（学生仅已发布可下，教师全下）。源文件**不复制**进 uploads/（单份存储，避免重复），app 直接 serve 课件/。
- **W1 课程注入**：注入 W1S1《大模型是什么：概念扫盲》+ W1S2《AI 产品地图》——2 个 Session + 2 章节（一对一）+ 7 份资料（解析出 152 个文本块）+ 5 条视频链接，全部默认 `draft`（学生不可见，教师后台确认发布后学生才可见）。

## [1.3.0] - 2026-09-02

### Added
- **测评百分制评分模型（QUIZ-005/003/009，Design-Spec §12.4）**：`quizzes` 增 `total_points(DEFAULT 100)` + `config_json`；`questions` 增 `points`（选择/是非 5、问答 10）；`attempts` 增 `graded_by('ai'/'teacher')`、`is_reviewed`、`reviewed_score`，`score` 改存实际得分点。SQLite 幂等迁移：存量题按题型补默认分、存量二元 `score(0/1)` 按对应题满分一次性换算为得分点（不破坏掌握度）。
- **100 分组合（QUIZ-005）**：教师可选预设（10 选择+5 问答 / 8 选择+6 问答 / 20 选择）或自定义并校验合计=100；QUIZZER 默认规格由「3 道题」改为 100 分组合，且按 config 补齐/裁剪保证恰好 100 分。
- **评分权双轨 + 教师覆核改分（QUIZ-009）**：客观题系统确定性判分（0 或满分）；问答题 AI(GRADER) 评 0–10；新增 `PUT /api/attempts/:id/review`（教师覆核，写 `reviewed_score`+`graded_by='teacher'`+`is_reviewed=1`，覆核后不可逆回 ai）。
- **M 公式百分制（PROG-007）**：`M = Σ(wᵢ·score_earnedᵢ)/Σ(wᵢ·points_possibleᵢ)×100`，教师覆核分优先于 AI 分（effective score）。
- **展示层**：测评报告/进度/周报改显百分制得分率；教师后台「全班进度」增「测评覆核」入口（逐题改分）。

## [1.2.0] - 2026-09-02

### Added
- **学习路径（8 周）集成 + 发布状态机（REQ-CURR-001~003）**：新增 `sessions` 表（week_no/session_no/title/goal/chapter_ids/concept_tags/status）与发布机制；`chapters`/`materials` 加 `status` 列（迁移，现有数据默认 `published`）。session 是发布源——发布时其下章节/资料/视频 `status` 同步 `published`（学生立即可见），取消发布回 `draft`；学生 `GET /api/curriculum` 只见 published session，`GET /api/chapters`、`GET /api/materials` 同样只返回 `status='published'`（教师见全部）。
- **视频课挂载（REQ-VIDEO-001~003）**：新增 `video_resources` 表（结构化元数据，**不进 RAG/chunks/embedding**）；新建 `curriculum_bp`（`/api/curriculum`）提供 Session CRUD + 发布/取消发布 + 视频课 CRUD + 总览。
- **TUTOR 视频融合（CHAT-010）**：新建 `ai/video_link.py`（纯 SQL + 标签匹配的确定性召回，**禁 import `ai.rag`、不触达 `chunks`**）；`TUTOR_SYSTEM` 增 `{{related_videos}}` 占位 + 推荐指令（仅标题/平台/URL，不内联视频内容）；对话响应透传 `related_videos` 供前端「相关视频课」面板渲染。
- **前端**：学生新增「路径」tab（周→节手风琴：资料 + 视频外链 + 去提问）；教师新增「课程管理」tab（Session/视频 CRUD + 发布/取消发布按钮）；对话页渲染 `related_videos` chips。
- **测试**：新增 `test_curriculum.py` / `test_video_link.py` / `test_tutor.py`，扩展 `test_isolation.py`（视频共享无 user_id 泄漏）。

### Note
- `seed_curriculum()` 仅留接口空实现（**不灌真实课件数据**）；8 周课件由 Hermes 后续注入。

## [1.1.1] - 2026-09-02

### Fixed
- **bool 是非题前端无法作答**（REQ-QUIZ-002/003）：`Student.viewQuizTake()` 中 bool 题与 choice 题走同一条 `options` 分支，而 bool 题的 `options` 为空数组，导致只显示题干、无任何作答控件。现为 bool 题单独渲染「正确 / 错误」两个按钮；`Student.pick()` 兼容 choice 索引与 bool 文本，`answerReview()` 复用该值经后端 `grader._deterministic`（bool 用 `answer_key` 字符串比对）正确评分。
- **巩固练习（openReview）bool/choice 渲染缺失**：复习项 `question.options` 后端存的是 JSON 字符串，前端直接 `.map` 会抛错（choice/essay 复习题整体打不开）；现前端先 `JSON.parse` 归一化为数组，并为 bool 复习题补「正确 / 错误」按钮。

## [1.1.0] - 2026-09-02

### Fixed
- **顶部标题栏不固定**：`.appbar` 从 `position:sticky` 改为 `position:fixed`（居中 max-width:520px，与底部对称）。此前整个 App shell（appbar+内容+tabbar）渲染在 `.screen` 内，`.screen` 是 `flex:1` 嵌在 `min-height:100vh` 的 `#app` 里，内容高时滚动发生在 body 而非 `.screen`，`sticky` 失去吸附上下文而跟着滚走；现 `.screen` 加 `padding-top:68px` 容让，顶部固定死。配套 SW cache bump 到 v3 让客户端立即拿到新 CSS。
- **底部导航栏不固定**：`.tabbar` 从 `position:sticky` 改为 `position:fixed`（居中 max-width:520px），现在会真正钉在屏幕底部，不再随内容滚动。
- **GRADER 空答案误给分**（REQ-QUIZ-003）：essay 题空答案也会调 LLM，LLM 可能对空答给分 → 现在空答案一律判「未作答 0 分」，不等 LLM。

### Added
- **章节编辑 / 删除入口**（REQ-MAT-001 强化）：教师后台章节卡片新增「编辑」「删除」按钮；编辑可改文件夹与章节名（调 `PUT /api/chapters/:id`，后端已存在）；删除二次确认（调 `DELETE /api/chapters/:id`，其下有资料时后端拦截，需先软删资料）。老师可完全自定义课程结构。

## [1.0.0] - 2026-09-02

### Added（可用核心 MVP，P0 → P1，不依赖 torch/ChromaDB）
- **数据层**：SQLite WAL + busy_timeout 建表/迁移；`users/chapters/materials/chunks/conversations/messages/quizzes/questions/attempts/review_items/reports` 全量表（REQ-DM-001~010）。
- **鉴权**：JWT 12h（Bearer）、登录/登出/注册（教师建学生）、`/me`、`refresh`、改密；`@jwt_required`/`@role_required`/`@user_scope`（F9 越权读 403）。
- **资料与章节**：章节 CRUD（教师写、全班读）；资料上传解析（pdfplumber/python-pptx/python-docx，MD/TXT 直读）分块写 SQLite `chunks`；软删除（F7）。
- **引导式对话**：TUTOR 苏格拉底引导（不直接给答案）、≤12 轮护栏、人设加载（年级+薄弱章）、多对话管理、意图门控；RAG 降维为关键词/章节检索 top-k=5 + 两层 Fallback。
- **测评**：教师草稿→确认发布（QUIZZER 出题，失败降级模板题）；学生作答 + GRADER 三档批改（choice/bool 确定性，essay LLM 兜底启发式）；重出新 version（旧版 superseded）；`attempts.quiz_version` 落地（F3）。
- **进度/掌握度**：M 四态（时间衰减加权，仅聚合最新 published version）；薄弱点带错题依据；巩固练习 + 间隔复习 1→3→7 闭环（答错重置 1）。
- **周报**：学生周报（学习天数/对话/测评/成绩/薄弱/AI 建议）。
- **教师后台**：学生账号管理（创建/重置/停用）、全班概览聚合（不经理 `@user_scope`）、共性薄弱章节。
- **PWA 前端**：学生/教师双视图（Apple native minimal）；登录 → 学生(学习/测评/进度/周报)、教师(后台/发布/进度/周报)；`manifest.webmanifest` + `sw.js` 离线 App Shell + 图标。

### Changed
- 移除 ChromaDB / sentence-transformers / torch / openai 依赖；`requirements.txt` 精简。
- `/health` 改为真实 SQLite 探活，返回 `{status,db,rag,version}`。

### Security
- 密码 werkzeug 哈希；SQL 全参数绑定；输入长度校验；LLM 限速 `@rate_limit(60/day)`；TUTOR 输出门控 + 两层 Fallback。
