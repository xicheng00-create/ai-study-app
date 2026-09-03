# Changelog

本项目遵循「版本号诚实规则」（CLAUDE.md §5）：任何产生 CHANGELOG 条目的改动，须同 commit 将 `backend/app.py` 的 `version` 常量 bump 到一致。

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
