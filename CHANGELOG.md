# Changelog

本项目遵循「版本号诚实规则」（CLAUDE.md §5）：任何产生 CHANGELOG 条目的改动，须同 commit 将 `backend/app.py` 的 `version` 常量 bump 到一致。

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
