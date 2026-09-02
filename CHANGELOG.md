# Changelog

本项目遵循「版本号诚实规则」（CLAUDE.md §5）：任何产生 CHANGELOG 条目的改动，须同 commit 将 `backend/app.py` 的 `version` 常量 bump 到一致。

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
