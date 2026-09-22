# AI 学习小组 App — 设计规格说明书 (Design Spec)

> 版本：v2.1（融合 Functional + Technical；严格对齐 `architecture-design.md` v1.1；**最新稳定版：v2.2.0（2026-09-09）**；2026-09-02 增补：测评百分制评分模型 + AI 评分与教师覆核双轨 + QUIZ-005 提 P1）
> 日期：2026-09-02  
> 状态：设计评审  
> 上游文档：PRD-AI学习小组app.md（v2.1）｜architecture-design.md（v1.1，架构再审有条件通过）  
> 方法论：pm-toolkit 架构分层 / 领域建模 / API 契约 / 角色分端 UI 规格 + 架构再审（F1–F10）

---

## 〇、文档用途、决策摘要与 REQ ID 约定

本文档在 PRD v2.1 与架构设计 v1.1 之上，输出**工程可执行的融合设计规格**：每条功能需求（Functional）均绑定对应的技术设计（Technical：Blueprint / 中间件 / AI Agent / 数据表 / 状态机 / 部署约束）。

### 0.1 决策摘要（功能 ↔ 技术 双视角）

| 维度 | 功能决策（PRD） | 技术落点（architecture-design.md） | REQ |
|------|----------------|-----------------------------------|-----|
| 整体形态 | 单 PWA + 师生账号 | **单体 Flask + waitress（单进程/4 线程）**；"单进程"≠单线程 | DEP-003, F6 |
| AI 编排 | 引导式/出题/批改 | **极简三 Agent 提示词**（TUTOR/QUIZZER/GRADER）+ 两层 Fallback | CHAT-004, QUIZ-001/003 |
| RAG | 纯向量检索 | ChromaDB cosine + `chapter_id` 过滤 + 阈值 ≥0.4 | MAT-003, ARCH-RAG |
| 部署韧性 | 常驻 + 备份 | **LaunchDaemon**（非 LaunchAgent）+ iCloud rsync（先 `wal_checkpoint`） | DEP-006, DEP-008, F1/F2 |
| 数据正确性 | 重出题不污染掌握度 | `attempts.quiz_version`，M 按 `(chapter_id, 最新 published version)` 聚合 | DM-006, PROG-007, F3 |
| 安全护栏 | 越权防护 | `@user_scope` + `@role_required` + 越权读 403 集成测试 | AUTH-004, MAT-007, F9 |
| 护栏兜底 | 不静默错答 | TUTOR 输出门控 + 三层降级（两层落地） | CHAT-004, F5 |
| 测评评分 | 百分制（固定 20 道选择/是非，每题 5 分，合计 100；v1.10.0 取消问答） | AI(GRADER) 评客观分 + 教师可覆核改分；questions.points + attempts.score 改存实际得分 | QUIZ-003/005/009 |
| 可恢复性 | 防误删 | 资料 `is_deleted` 软删除 + 7 天硬删窗口 + 二次确认 | MAT-005, F7 |

### 0.2 REQ ID 编码规则

格式：`REQ-<域>-<三位序号>`。域前缀与 Functional 来源：

| 域 | 含义 | Functional 来源 |
|----|------|----------------|
| AUTH | 鉴权与账号 | PRD 功能 0 |
| MAT | 资料与章节 | PRD 功能 1 |
| CHAT | 引导式对话 | PRD 功能 2 |
| QUIZ | 测评 | PRD 功能 3 |
| PROG | 进度/掌握度/巩固 | PRD 功能 4 |
| RPT | 周报 | PRD 功能 5 |
| ADMIN | 教师管理后台 | PRD 功能 6 |
| CURR | 学习路径结构 | CR-2026-0902-LPATH |
| VIDEO | 视频资源 | CR-2026-0902-LPATH |
| DEP | 部署与运维 | PRD §2/§9/§14 |
| DM | 数据模型 | PRD §7 |
| ARCH | 架构/横切 | architecture §二/§四 |
| NFR | 非功能/盲区 | PRD §13 + architecture §十三 |
| KNOW | 知识卡片（知识点→翻转卡片+左滑右滑判记住没记住+间隔复习） | CR-2026-0908-KNOW |
| CHECKIN | 每日打卡与连胜（今日任务 → 达标 → 连胜） | CR-2026-0918-STREAK + CR-2026-0919-DECK |
| NOTIF | 通知与提醒（站内通知中心 + Web Push + 19:00 未打卡提醒） | CR-2026-0918-STREAK |
| SET | 个人设置（头像/名称/密码/提醒开关/退出） | CR-2026-0918-STREAK |

> 每条 REQ 标注 **P0/P1/P2** 并绑定**技术模块**（Blueprint / AI Agent / 层 / 状态机），见 §三与 §十四追溯矩阵。

---

## 一、设计原则（继承 architecture §一）

1. **KISS for 4** — 用户规模（1 教师 + 3 学生）是复杂度第一约束；分布式/微服务/Docker/知识图谱均为反模式。
2. **YAGNI** — PRD「非目标」项（原生 App / 公网注册 / MySQL / 治理类 / 家长端）一律不做。
3. **降级保守** — AI 不确定即兜底（拒绝/转人工/固定引导语），绝不静默给结论（红线 #1）。
4. **状态机优先** — 有生命周期的实体（quiz `draft→published→superseded`、review `pending→done`、conversation 轮次）用状态机建模，非法转换须显式测试（红线 #3）。
5. **借鉴而非复刻** — 取 ChemAI「治理/降级/可恢复」之神，不照搬 ReAct/OCR/四维审核/Docker 之形。
6. **Evals 风险显式化** — 本期确认不做 Evals，但登记为已知盲区并设触发补做条件（§十三-1 / F8）。

---

## 二、系统架构（5 层 + 2 横切，严格对齐 architecture §二）

```
┌─────────────────────────────────────────────────────────────────────┐
│ L1 表现层   PWA（学生/教师，H5 + ServiceWorker，离线 App Shell）      │
├─────────────────────────────────────────────────────────────────────┤
│ L2 接入层   Cloudflare 命名隧道（固定 HTTPS 域名，仅暴露 5001）       │
├─────────────────────────────────────────────────────────────────────┤
│ L3 应用层   Flask 单进程（waitress，单进程/4 线程）                  │
│   ├ 静态托管(/) + PWA shell                                          │
│   ├ /api/* 路由 + 横切中间件(JWT/角色/限速/校验/作用域)             │
│   └ 业务 Blueprint: auth/chapters/materials/conversations/quizzes/    │
│      attempts/progress/reports/teacher/health + AI 服务(rag/orch/review)│
├─────────────────────────────────────────────────────────────────────┤
│ L4 AI 能力层   DeepSeek API（外部）+ all-MiniLM-L6-v2（本地嵌入）    │
├─────────────────────────────────────────────────────────────────────┤
│ L5 数据层   SQLite WAL + ChromaDB + uploads/                        │
└─────────────────────────────────────────────────────────────────────┘
横切 A) 安全护栏：@jwt_required / @role_required / @rate_limit / @validate_json / @user_scope
横切 B) 可观测+备份：/health + launchd KeepAlive + iCloud rsync(wal_checkpoint)
```

### 2.1 模块—技术映射（Functional 域 → Technical 模块）

| Functional 域 | Blueprint | 层 | AI Agent | 关键数据 | 状态机 |
|---------------|-----------|----|----------|----------|--------|
| AUTH | `auth_bp` | L3 | — | users | 用户启用态 |
| MAT | `chapters_bp` + `materials_bp` | L3 | — | chapters/materials(+ChromaDB) | 软删除 |
| CHAT | `conversations_bp` | L3 | TUTOR | conversations/messages | 轮次护栏 |
| QUIZ | `quizzes_bp` + `attempts_bp` | L3 | QUIZZER/GRADER | quizzes/questions/attempts | draft→published→superseded |
| PROG | `progress_bp` + `review_sched` | L3 | QUIZZER(巩固) | attempts/review_items | 间隔复习 1→3→7 |
| RPT | `reports_bp`（v1.9.0 废弃） | L3 | TUTOR(建议) | reports/daily_advice | — |
| CLASS | `class_bp` | L3 | — | users/attempts/practice_questions/messages | — |
| ADMIN | `teacher_bp` | L3 | — | users/materials/quizzes | — |
| DEP | — | L2/L3/L5 | — | db/chroma/uploads | 备份状态 |
| 全局 | `health_bp` + 中间件 | L3/横切 | — | — | — |

---

## 三、模块分布与职责（功能 ↔ 技术 融合，核心章节）

> 每模块按「**功能需求（Functional）** + **技术设计（Technical）**」双栏展开。

### 3.1 鉴权与账号 — `auth_bp`（L3，REQ-AUTH）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| AUTH-001 | 全部 | P0 | 登录/登出，JWT 12h 有效 |
| AUTH-002 | teacher | P0 | 创建学生账号 |
| AUTH-003 | 全部 | P1 | 各自改密 |
| AUTH-004 | 全部 | P0 | `role` 决定视图（学生/教师） |
| AUTH-005 | 全部 | P1 | token 临近过期刷新 |
| AUTH-006 | 全部 | P0 | `GET /me` 返回档案 |
| AUTH-007 | 全部 | P0 | 密码 bcrypt/werkzeug 哈希，不存明文 |
| AUTH-008 | 全部 | P1 | 速率限制入口（横切，见 NFR-006） |

**Technical**
- 路由：`POST /api/auth/login|refresh|register`、`GET /api/auth/me`。
- 中间件：`@jwt_required`（注入 `g.user_id/g.role`）、`@role_required("teacher")`（教师创建账号）、`@rate_limit(60/day)`。
- 令牌：`ACCESS_TOKEN_TTL=12h` 环境变量可调；无态 JWT 服务端不落库；登出清 `localStorage`（P2 可升级 httpOnly Cookie）。
- 数据：users 表（REQ-DM-001）；`is_active` 启用态状态机。
- 错误码：`E_AUTH_*` 鉴权失败 / `E_ROLE_*` 角色不符 / `E_RATE` 限速。

### 3.2 资料与章节 — `chapters_bp` + `materials_bp`（L3，REQ-MAT）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| MAT-001 | teacher | P0 | 建/改/删 文件夹与章节 |
| MAT-002 | teacher | P0 | 上传资料并归入章节，≤30MB |
| MAT-003 | teacher | P0 | 解析分块写 ChromaDB（带 chapter_id） |
| MAT-004 | 全部 | P0 | 按章节浏览（共享只读） |
| MAT-005 | teacher | P0 | 删除资料（清向量+级联） |
| MAT-006 | teacher | P2 | 批量拖拽归章 |
| MAT-007 | 全部 | P0 | 读共享、写仅 teacher |

**Technical**
- 路由：`POST/PUT/DELETE /api/chapters`、`POST /api/materials/upload`、`GET /api/materials`、`DELETE /api/materials/:id`、`POST /api/materials/batch-upload`(P2)。
- 中间件：写操作 `@role_required("teacher")`；读操作 `@user_scope` 不适用（资料全班共享，仅作用域为「全部可读、教师可写」）。
- 解析管线（RAG §八）：`pdfplumber/python-pptx/python-docx` → 分块(≈500/overlap≈80, 按章切优先) → `all-MiniLM-L6-v2` 本地编码 → ChromaDB `material_chunks`（metadata 含 `chapter_id/page_no/chunk_idx`）。
- **F7 软删除**：MAT-005 改为 `materials.is_deleted=1` 软删除 + 前端二次确认 + iCloud 保留 **7 天**硬删窗口，避免误删全班数据（硬级联清向量+对话+关联测评延至硬删时执行）。
- 数据：chapters（DM-002）、materials（+uploaded_by/+chapter_id，DM-003）、ChromaDB（DM-010）。

### 3.3 引导式对话 — `conversations_bp`（L3，REQ-CHAT，AI: TUTOR）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| CHAT-001 | student | P0 | 进入对话加载人设（薄弱章；v1.5.0 起不再含 grade） |
| CHAT-002 | student | P0 | 选择范围（资料/章/全部）；**从卡片/课程页「去提问」进入时自动选中对应课题**——`selChapters` 置为该卡/Session 的 `chapter_ids` 并落 localStorage，scope-bar 立即显示该范围（v2.6.2，REQ-CHAT-SCOPE-002） |
| CHAT-003 | student | P1 | 意图路由（答疑/复习/出题分流） |
| CHAT-004 | student | P0 | 苏格拉底引导，不直接给答案 |
| CHAT-005 | student | P1 | ≤12 轮护栏 |
| CHAT-006 | student | P0 | 对话仅本人可见 |
| CHAT-007 | student | P1 | SSE 流式逐 token |
| CHAT-008 | student | P1 | 创建/切换/删除本人对话 |
| CHAT-009 | student | P2 | 引用标注资料原文 |
| CHAT-010 | student | P1 | 选择已作答测评错题交 TUTOR，按错题引导讲解与巩固 |

**Technical**
- 编排（architecture §5.2）：人设加载 → 选章 → ChromaDB 召回(`chapter_id` 过滤, top-k=5, cosine≥0.4) → 注入 TUTOR_SYSTEM + 历史(≤12 轮) → DeepSeek → 写回 conversations/messages。
- **F5 TUTOR 输出门控**：a) 拒绝规则（涉政/暴力/成人/诱导泄露密钥 → 转固定引导语）；b) 越界检测（非学习话题 → 回资料引导）；c) 界面标注「回答由 AI 生成，请核对资料」。
- **两层 Fallback**（architecture §5.5）：L1 DeepSeek；L2 TUTOR 提示词内固定引导语池（按意图/章节预生成）；触发（API>30s/5xx、召回为空、越界）→ 降级；**L3 固定答案不做**（宁可报错不静默错答）。
- 状态机：单次对话 turn 计数，==12 强制转「给结论+推荐练习」（CHAT-005）。
- 数据：conversations(+user_id, ±chapter_id, DM-009)、messages；隔离由 `@user_scope` 保证（CHAT-006）。
- 错误码：`E_AI_FALLBACK`（兜底触发）、`E_INVALID_INPUT`。

### 3.4 测评 — `quizzes_bp` + `attempts_bp`（L3，REQ-QUIZ，AI: QUIZZER/GRADER）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| QUIZ-001 | teacher | P0 | 生成草稿→预览微调→确认发布 |
| QUIZ-002 | student | P0 | 在线作答，可重做取最近 |
| QUIZ-003 | student | P0 | GRADER 三档自动批改 |
| QUIZ-004 | student | P1 | 测评报告（得分/错题/薄弱点） |
| QUIZ-005 | teacher | P1 | 题型/难度/数量配置（凑满 100 分组合，教师可选预设/自定义）|
| QUIZ-006 | student | P2 | 错题本 |
| QUIZ-007 | teacher | P1 | 重出生成新 version |
| QUIZ-008 | teacher | P1 | 发布态管理（draft/published） |
| QUIZ-009 | teacher | P1 | AI 评分后教师可覆核/改分（graded_by/is_reviewed）|
| QUIZ-010 | teacher | P1 | 已发布测评按已作答学生查看完整错题与得分 |

**Technical**
- **百分制评分模型（QUIZ-003/005）**：**v1.10.0 起取消问答题（essay）**——固定 20 道题，题型仅限选择题（choice）与是非题（bool），每题 5 分、合计 100 分；`questions.points` 按题型写入，`quizzes.total_points=100`（由 QUIZZER 按 QUIZ-005 配置生成，预设 20 选择/20 是非）。`POINTS` 仍保留 `essay=10` 仅兼容库里旧题数据。学生单题得分 `attempts.score∈[0,points]`。
- **QUIZZER 出题前注入 RAG（QUIZ-001/005）**：`POST /api/quizzes/draft` 生成草稿前，QUIZZER 先对所选章节做 RAG 检索，把资料正文片段拼成 `retrieved_chunks` 注入提示词，题目基于资料难度出题（不再凭通用知识漂移）。
- **评分权双轨（QUIZ-003 + QUIZ-009）**：① 客观题（选择/是非）由**系统确定性判分**（答案比对，0 或满分，零延迟零成本）；② 问答题由 **AI(GRADER)** 评 `score∈[0,10]` 并给 `reason`，`attempts.graded_by='ai'`（**v1.10.0 起新出题不再产生 essay，此分支仅兼容库里旧题**）；③ 教师可对任一题**覆核改分**（`PUT /api/attempts/:id/review` → 写 `reviewed_score`+`graded_by='teacher'`+`is_reviewed=1`）。教师默认不评分，仅在 AI 判分争议时介入。
- 路由：`POST /api/quizzes/draft`(含 `config` 预设) → `POST /api/quizzes/:id/publish`、`POST /api/quizzes/:id/attempts`、`GET /api/quizzes/:id/report`、`PUT /api/attempts/:id/review`(QUIZ-009)、`POST /api/quizzes/:id/revision`(P1)、`GET /api/quizzes?status=published`。
- 轻量审核状态机（architecture §5.3）：`draft ─[教师确认]─► published`；`published ─[重出]─► superseded`（旧版保留，新 version 走 draft→published）。
- GRADER：QUIZZER 出题（结构化 JSON，含 `answer_key`/`sub_concept`/`chapter_id`/`points`）→ 学生作答 → 客观题系统判分 + 问答题 GRADER 评 `{correct, score, reason}` 写 attempts。
- **F3 数据正确性**：`attempts` 必须带 `quiz_version`（DM-006），M 聚合取该章**最新 published version** 成绩（PROG-007），避免重出题污染掌握度；**v1.9.0 起 M 额外聚合该章自主练习 `practice_questions`（已作答，同权重，见 §3.5）**。
- 角色门禁：`quizzes_bp` 发布需 `@role_required("teacher")`；学生作答需 `@user_scope`；覆核改分需 `@role_required("teacher")`。

### 3.4.1 学生自主练习 — `practice_bp`（L3，REQ-PRACTICE，AI: QUIZZER/GRADER）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| PRACTICE-001 | student | P1 | 选章 → AI 生成练习（difficulty=hard、**题数 5-10 自定义默认 5**、仅 choice/bool、基于章节资料、**单次题目覆盖不同知识点 + 跨会话知识点不重复**——历史练过的 sub_concept 排除，如 22 知识点每次 5 道约 4-5 次练习才开始重复；v1.10.0 取消问答、v1.16.0 起不再强制 20 道/100 分、v1.16.x 起检索全章多样化抽样）|
| PRACTICE-002 | student | P0 | 在线作答 + GRADER 批改 + 提供正确答案 |
| PRACTICE-003 | student | P1 | 练习错题进入薄弱点/巩固练习依据（v1.9.0 起练习同时计入掌握度 M）|

**Technical**
- **独立数据层**：`practice_sessions`（user_id/chapter_ids/difficulty/total_points/config_json）+ `practice_questions`（session_id/chapter_id/sub_concept/type/content/options/answer_key/points/content_hash/correct/user_answer/score/reason/answered_at）。练习是学生**个人即席生成**，**不进老师 draft→publish 状态机**，不写 quizzes/questions/attempts；**v1.9.0 起练习（已作答）与测评同权重计入掌握度 M（任务书定义 A），不再是「不污染 M」**。
- **题数 5-10 自定义默认 5 + 资料驱动 + 难度 high + 同学生跨知识点不重复（v1.16.0 起，v1.17.x 强化跨会话知识点）**：`quizzer.generate_practice_questions()` 基于章节资料出 **count 道 choice/bool（count 默认 5、上限 10、下限 5，入参校验）**（**v1.10.0 起取消 essay**、v1.16.0 起不再强制 20 道/100 分），difficulty=hard；不再凑 100 分，`total_points` 写各题实际分之和，`_session_dict` 按实际 total_points 归一。RAG 检索章节资料正文注入 QUIZZER_SYSTEM；LLM 真返空时返回空列表、由端点提示「生成失败，请重试」（不再硬塞通用模板）。**同学生跨会话去重（题干级）**：`practice_questions.content_hash`（题干规范化 hash，去空格/标点/大小写）存 `hash(q.content)`，生成前查该学生历史题干注入提示词「避免重复、基于资料衍生变体」，后端 `_cap_to_max` 再按规范化 hash 过滤已出题干；不同学生可相同、同考点不同问法不算重复。**⚠️ 知识点覆盖（v1.16.x 检索广 + v1.17.x 跨会话知识点不重复）**：`_retrieve_chunks` 对练习**不再只取 material_id/chunk_idx 排序前 5 条**（那样 82-chunk 的 md 主体内容一条都进不去、题目全撞同批知识点），改为**跨全章多样化抽样**（按 material 分层 + chunk 分段各取若干，喂料上限 ~6000 字符，保证大 md 全覆盖）；`_cap_to_max` 在题干 hash 之外**加 sub_concept 维度去重**（单次题目尽量不同知识点，不足才允许同点变体）；**跨会话知识点不重复（v1.17.x）**——生成前查该生历史练过的 `sub_concept`（`practice_questions.sub_concept` distinct）做成 `exclude_sub_concepts` 注入提示词（「避免这些子概念，从其余知识点出题」）+ 后端 `_cap_to_max` 过滤 `sub_concept ∈ exclude_sub_concepts` 的题。这样每次练习命中的知识点不同，~22 知识点每次 5 道约 4-5 次才开始重复。
- **难度 hard**：`QUIZZER_SYSTEM` 注入 `{difficulty}`（normal/hard 指示）；练习固定 `difficulty='hard'`（综合运用/多步推理/概念辨析/跨知识点），老师测评默认 `normal` 不受影响。
- **批改复用 GRADER**：与测评一致（客观题确定性判分；essay AI 三档/启发式分支保留以兼容旧数据，v1.10.0 起不再产生）；`practice_questions` 写 `correct/score/user_answer/reason/answered_at`。
- **错题联动（PROG-005/006）**：`progress_bp._practice_wrong` 读取本人练习错题（correct=0 或 score<points）作为薄弱点依据（`from_practice`）与巩固练习来源章/聚焦子概念；v1.9.0 起练习同时计入 M（全错→M 下降→薄弱），错题联动逻辑保留。
- 路由：`GET /api/practice`、`POST /api/practice/generate`、`GET /api/practice/:id`、`POST /api/practice/:id/submit`（学生本人，越权 403）。

### 3.4.2 知识卡片（知识点→翻转卡片+左滑右滑判记住没记住+间隔复习）— `knowledge_bp`（L3，REQ-KNOW，AI: QUIZZER）

**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| KNOW-001 | student | P1 | **学习路径发布 / 资料发布时自动**从章节资料抽取知识点生成知识卡片（正面=知识点/问题，背面=答案/解析+一句示例）存库，**学生无需手动生成**（每章一组 ≥20 知识点，全章覆盖；已有卡复用不再重复调 LLM；失败可懒加载兜底） |
| KNOW-002 | student | P1 | 点卡 3D 翻转看答案；**左滑=没记住、右滑=记住了**（底部兜底按钮 ←没记住\|记住了→）；顶部进度 第N/总数 + 每卡状态色；**卡高随内容自适应**——长答案不裁切：卡高 = 当前卡面内容高（下限 320px，上限取「卡顶→tabbar 上沿」的可用高，大屏兜底 620px），超出上限在**卡面内滚动**（v2.6.2，REQ-KNOW-CARDFIT-001） |
| KNOW-003 | student | P1 | 系统记录每知识点**学习次数（learn_count）**+ **复习状况**（new/learning/reviewing/mastered + 间隔 1→3→7）；每日「待复习」队列优先，再学新卡。**「今日待复习」口径（v2.6.4，REQ-KNOW-DUE-001）**：= 已学过（`learn_count>0`）且**已到期或逾期**（`next_review_at ≤ 今天`，UTC+8）且未掌握；**未学的卡只算「未学」，不计入待复习**（旧口径把懒建的 new 行也当到期 → 新发布章节显示「待复习 = 全部卡片」）。**学习记录长期累计、绝不按天清空** |
| KNOW-004 | student | P1 | **卡片必须应试级细粒度且全章覆盖**（CR-2026-0919-CARDS）：① 生成时投喂**全章每一份资料的每一个切片**（按资料分层、每份保底、总预算 2 万字），不再抽样 ~18 片×300 字；② 提示词硬性要求「**一个考点一张卡**」——概念定义/数字指标/流程步骤/术语英文名/易混区别/常见误区/案例结论逐条成卡，禁止「主要包含以下几方面」式概括，且能出选择题的细节（数字、专有名词、顺序、比例、阈值、年份）必须单独成卡，每章 ≥40 张；③ **只抽本 Session 内容**——课程共用素材（如全课程行业术语表）中属于其它周次的词条一律跳过，禁止跨章错配；④ 每张卡必须绑定 `source_chunk_id`，可回溯课件原文切片；⑤ **反向也要成立**：任何一条课件切片都必须至少被一张卡片引用（无卡切片 = 覆盖缺口，须补卡），做到「课上有讲、卡片必有」 |
| KNOW-005 | teacher | P2 | **教师端知识卡片核查（REQ-TEACH-KNOW-001）**：教师可在后台**逐章/逐主题/逐卡**核对卡片内容，不再依赖查库或铸学生 token。① 章级汇总：卡片数 / 主题数 / 切片数 / **未覆盖切片数**、发布状态；② 单章明细：按 `sub_concept` 分组，每张卡附**来源资料名 + 源切片原文摘录**（可判断「卡片是否真出自课件」）；③ 只读，不改卡、不发布；④ 学生角色访问一律 403（与 `GET /api/knowledge/*` 的学生专属相反）；⑤ **绑定必须精确到「同资料内最吻合的那一条切片」**，不能只保证「片子属于同一份资料」——弱匹配（同资料内 BM25 排名 > 3 且最佳切片得分 ≥ 1.35 倍）一律改绑 |
| KNOW-006 | student | P1 | **单次复习卡组上限 100 张（v2.6.4，REQ-KNOW-DECK-001）**：点「开始复习」一次性装配的卡组 ≤ `config.SESSION_DECK_MAX`（默认 100），排序 = ①今日待复习（到期/逾期）→ ②未学 → ③学习中/复习中未到期 → ④已掌握；**阈值单点在后端并随响应下发**（`GET /api/knowledge/overview` / `GET /api/knowledge/<chapter_id>` 的 `deck_max`），前端禁止硬编码。**学习记录（`knowledge_reviews`）长期累计、绝不按天清空**；本次没复习完的卡次日自动进入下一批，无需人工干预 |

| KNOW-007 | student | P1 | **卡片库不得存在重复知识点（v2.6.8，CR-2026-0922-DEDUP）**：同一知识点只保留一张卡。① 答法/详略不同但同一考点的重复卡**合并为一张**，且整合后**保留各原卡独有的全部事实**（数字、名称、步骤、示例一条不丢）；② **跨章重复同样合并**（同一概念在第 1 周与第 2 周各出一张 → 只留最早出现的那张，内容取并集）；③ 判重必须同时看**主体**与**答案**——同问句但主体不同（四家 IDE 插件同模板、下限 vs 上限、通义千问 Max/Flash/Coder）**不算重复、必须保留**；④ 合并只删重复卡，**不得动考点覆盖**（被合并卡的学生复习进度自动并入保留卡，不产生孤儿行） |

| KNOW-008 | student | P1 | **浏览卡片必须按主题分组（v2.7.0，CR-2026-0922-CARDSGROUP）**：一章 300~650 张卡平铺不可用（用户实报「每个 session 几百张卡片挺多的」）。① 浏览页（「知识卡片」列表）按「**章 → 主题组 → 卡片**」两级钻取：**纵向折叠、点组展开、默认全折叠、无横向滚动**；② 主题组 = 该章卡片的 LLM 归类结果（每组 **5~80 张**，目标 15~80，**禁止**出现吞掉全章一半的巨型组、也禁止 1~4 张的碎片组；碎组并入最贴切的大主题，实在无处可去才落「其他要点」）；③ 归类**只做浏览标签**，**不得**改卡片正文、切片绑定、复习态，也不参与出卡/复习调度（分组失败或未归类时 `topic` 返回空串 → 前端退化为单组「全部卡片」，老库同样可用）；④ 分组结果落库 `card_topics` 并随 `GET /api/knowledge/<chapter_id>` 的卡片字段 `topic` 下发；⑤ 组内统计（张数/已掌握/学习中/未学/今日待复习）与章级一致 |
| KNOW-009 | student | P1 | **章节与学习时间解耦（v2.7.0，CR-2026-0922-DECHAPTER）**：章节**不得**再按「第X周·第Y节」表述，也不得用周/节暗示学习进度。① 章节展示名一律「**第 N 章 · 章标题**」（N = 全局章序 1..4，`chapters.order_no` 连续重排、`folder` 置空）；② 学习节奏**只由卡片量换算**：每章标「**预计 X 天学完 · 共 N 张卡**」，X = `ceil(卡数 / 每日可学张数)`；③ 每日可学张数**单点在后端**（`config.PLAN_CARDS_PER_DAY`，= 打卡要求 30 张/天，约一周 210 张）并随 `GET /api/chapters` 以 `daily_cards` 下发，前端**禁止硬编码 30**；④ 章节卡数同样由后端下发（`card_count`），前端不得自行维护；⑤ 测评标签等一切回显章节处统一用「第 N 章」，不再出现「第X周 第Y节」 |

**Technical**
- **独立数据层（共享内容 + 每生独立复习态，v1.17.x 重构）**：`knowledge_cards`（id, chapter_id, sub_concept, front, back, source_chunk_id, created_at）——**无 user_id，是共享内容**（每章一组，发布时生成一次）；`knowledge_reviews`（id, card_id, user_id, learn_count, interval_days, next_review_at, status CHECK(new/learning/reviewing/mastered), last_review_at, created_at, UNIQUE(card_id,user_id)）——**每学生独立复习状态**，学生首次打开该章卡组时**懒建**（默认 new）。已废弃 v1.17.0 的「knowledge_cards 带 user_id」旧形（表空可安全重建）。
- **卡片主题分组（v2.7.0，CR-2026-0922-CARDSGROUP，KNOW-008）**：`scripts/group_cards.py [--chapter N] [--apply]`——LLM 三级处理：① 主题表（资料名 + 高频 `sub_concept` + 抽样 front → 10~16 个主题，要求体量均衡）；② 逐卡归类（每批 25 张，只允许用给定主题）；③ **再平衡**（首轮实测模型会造出「模型选型与对比(280)」式巨型桶 + 一堆 1~4 张碎片组，故加大于 `MAX_TOPIC_CARDS=80` 自动拆 2~4 子主题、小于 `MIN_TOPIC_CARDS=5` 并入大主题两道工序，最多拆 2 轮）。落库 `card_topics`（card_id PK, chapter_id, topic, ord），按章先删后插幂等；默认 dry-run，`--apply` 才写库且**只写 card_topics**。建表复用 `backend/data/models.py` 的 SCHEMA/migrate（单一真相，不重复 DDL）。`topic` 经 `LEFT JOIN card_topics` 随卡片下发，无归类时为空串（前端退化为单组「全部卡片」）。
- **章节天数口径（v2.7.0，CR-2026-0922-DECHAPTER，KNOW-009）**：`GET /api/chapters` 增加 `daily_cards`（= `config.PLAN_CARDS_PER_DAY`，定义上等于 `TASK_CARDS_REQUIRED`，保证「进度口径」与「打卡口径」同源不打架）与每章 `card_count`（子查询 `COUNT(*) FROM knowledge_cards`）；前端 `App.daysFor()` = `ceil(card_count / daily_cards)`，全库 2113 张 ≈ **71 天**（第 1~4 章 = 13/19/22/18 天）。章节名与「周/节」解耦由 `scripts/rename_chapters.py` 一次性重排（幂等：`第 X 章 · 标题` 取 `·` 末段作标题，`order_no` 按原 `(folder, order_no)` 顺序重排 1..N、`folder` 置空）；种子脚本 `inject_curriculum.py` / `inject_w1.py` 同步改为 `第 N 章 · 标题`（章号 = `(week-1)*2 + session_no`，课件源目录仍按 WxSx 映射，仅不再外显）。
- **卡片去重（v2.6.8，CR-2026-0922-DEDUP，KNOW-007）**：`scripts/merge_duplicate_cards.py --plan <plan.json> [--apply]`——按计划改写保留卡 `front/back`、把重复卡的 `knowledge_reviews` 迁移到保留卡（同生两行合一：`learn_count` 取大、`status` 取更进阶、`last_review_at` 取晚、`next_review_at` 取早）、删除重复卡；默认 **dry-run**，`--apply` 前自动 `wal_checkpoint(FULL)` + 备份生产库，并产出含「被删卡全文 + 复习行全文 + 保留卡新旧正文」的回滚报告到 `backups/<日期>-cards/`。**判重流程不再用相似度阈值**：旧 `rebuild_cards.py --dedupe-db`（词元 Jaccard≥0.85 且数字集合相同）会漏「同模板异主体」、且从不跨章比较；现流程 = 候选召回（sub_concept + front 词元/字二元组）→ LLM **分组**（允许一簇拆多组，避免把四家工具合成一张）→ **对抗式复核**（换「找实质差异」立场再审，主体/数字/答案指涉不同即否）→ 信息整合（保留各卡独有事实、禁新增事实）→ 忠实度校验（新增事实/矛盾/漏信息）。复习态合并与 `_review` 懒建兼容：合并后同生仍是一卡一行，`UNIQUE(card_id,user_id)` 不冲突。
- **状态机复用 `review_sched`**（architecture §5.4）：记住了 → `learn_count++`、`interval_days = next_interval(True, cur)`（1→3→7 封顶）、状态上移（new→learning→reviewing→mastered）、`next_review_at` 按间隔顺延；没记住 → `learn_count++`、`interval_days=1`、状态降回 learning、`next_review_at` 次日重排。同卡片跨会话复习。**先翻转看答案再判 remember，不在 open 期强行判定**。
- **AI 抽取（v2.5.1 整改，CR-2026-0919-CARDS）**：`backend/ai/knowledge.py` `generate_knowledge_cards(chapter_ids)` + `prompts.py` `KNOWLEDGE_SYSTEM`。**历史缺陷**：旧实现用 `quizzer._retrieve_chunks` 抽 ~18 个切片、每片截断 300 字、总长再砍到 6000 字 → 长资料（W1S2 有 96 片）只能被模型看到约 1/5，卡片必然「只覆盖大框架、遗漏细碎考点」，用户实报「无法支撑做题」。**整改后**：`_chapter_text()` 按资料分层投喂**全章每个切片**（每片 ≤600 字、每份资料保底 1200 字、总预算 `CONTENT_BUDGET=20000`），配合 KNOW-004 的提示词硬性要求 + `MIN_CARDS=40`，并过滤重复/空正面。**批量重做历史章节**走 `scripts/rebuild_cards.py`（逐片组独立调模型，片组按教案小节切分、每片组上限 16 张，按 front 归一化精确继承复习态）。LLM 真返空返空列表、端点提示「生成失败请重试」。
- **路由（去掉「学生手动生成」主路径）**：`POST /api/knowledge/generate`（保留为**懒加载兜底**：卡片缺失时教师/系统可触发，学生一般不必点）、`GET /api/knowledge/:chapter`（卡组+该生复习态，学生首次打开自动懒建 review 行）、`POST /api/knowledge/:card/review`（body `{remembered: true|false}` → 更新该生 learn_count/interval/status/next_review）、`GET /api/knowledge/overview`（各章该生掌握进度：已掌握/学习中/未学/今日待复习）。学生本人，越权 403；蓝图 `knowledge_bp` 注册进 app.py。
- **教师端核查路由（v2.6.0，KNOW-005）**：`GET /api/teacher/knowledge`（章级汇总：`cards/sub_concepts/chunks/orphan_chunks/status`，教师可见 draft 章）+ `GET /api/teacher/knowledge/<chapter_id>`（单章明细：`groups[{sub_concept,count,cards[{front,back,source_material,source_snippet}]}]`，源切片 `re.sub(r"\s+"," ")` 折叠后截 220 字；章节不存在 404）。均 `@jwt_required + @role_required("teacher")`，**只读**（不写库、不改卡、不发布），学生访问 403。前身缺口：`GET /api/knowledge/<chapter_id>` 是**学生专属**且要求章节已发布，教师只能查库/铸学生 token 才能核对卡片内容。
- **⚠️ 自动生成钩子（v1.17.x，核心）**：`knowledge.ensure_chapter_cards(chapter_id)`（查 `knowledge_cards` 该章已有卡则复用返 True，无则 LLM 生成 + 入库返 False；LLM 失败返回 False，由懒加载兜底）。在**学习路径发布**（`curriculum_bp` 发布 session → 对其 `chapter_ids` 逐个 `ensure_chapter_cards`）与**资料发布**（`materials_bp` 发布 material → 其 `chapter_id` `ensure_chapter_cards`）处调用。同步调用 + try/except（发布请求可容忍 ~秒级 LLM 延迟，3 学生规模可接受）。
- **前端（v2.0.0 导航+多选+动画重构）**：「学习」tab = **学习主菜单 hub**（资料库**可滚动多选 list**——每章圆形勾选框 + 已选计数 + 全选/清空，勾选记忆 localStorage `aistudy_sel_chapters`；对话页原横滑选章卡已撤除，选章统一在此）；「对话」子页（多选集驱动**跨章检索**：`post_message` 带 `chapter_ids` → `tutor._retrieve_multi` 逐章 RAG 合并去重、片段【章名】标注）；点「知识卡片」→ **跨章卡片列表页**（所选各章全部卡按章分组折叠、点章头展开卡网格，「开始复习」按钮置顶）+ 复习 deck（每卡标章名，跨章合并）。复习进度 localStorage `aistudy_kc_progress` 存**章 id 集签名 `ids`**（兼容旧 `{cid}` 单章格式），暂停退出/续学；换选集不误续旧进度。**卡片动画**：翻转 = 同一 DOM 切 `is-flipped` class 驱动 3D 过渡（非整页 render）；touch/mouse 跟手拖拽（`translateX + rotate`，拖拽期 `.dragging` 关 transition），超 70px 甩出判定（右滑=记住了/左滑=没记住，播 `.out-r/.out-l` 飞出）否则弹回；按钮点击同样先飞后提交；换卡 `.kc-in` 入场动画。`Student` 状态 `learnChat`/`knowledgeIdx`/`knowledgeDeck`/`selChapters` + `viewLearnHome()`/`viewLearnChat()`/`viewKnowledge()`/`viewKnowledgeDeck()`。改前端须 bump sw.js CACHE + app.py version。

### 3.5 进度/掌握度/巩固 — `progress_bp` + `review_sched`（L3，REQ-PROG，AI: QUIZZER）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| PROG-001 | student | P1 | 本人按章四态 |
| PROG-002 | student | P1 | 对话/提问统计（按章下钻） |
| PROG-003 | student | P1 | 成绩趋势折线 |
| PROG-004 | teacher | P1 | 全班概览聚合 |
| PROG-005 | 全部 | P1 | 薄弱点列表（附错题依据） |
| PROG-006 | student | P1 | 一键巩固练习 + 间隔复习 |
| PROG-007 | 全部 | P1 | 掌握度 M 计算（时间衰减加权） |
| PROG-008 | 全部 | P1 | 四态映射阈值 |

**Technical**
- M 公式（百分制）：`M = Σ(wᵢ·score_earnedᵢ) / Σ(wᵢ·points_possibleᵢ) × 100`，`wᵢ=0.5^间隔周数`，`points_possibleᵢ` 取 `questions.points`（选择/是非 5、问答 10）；**v1.9.0 起聚合两部分——①该章最新 published version 的测评 attempts（F3），②该章自主练习 `practice_questions`（answered_at 非空，earned=score、possible=points），同一条加权公式、按章聚合、带时间衰减**；仅当两者皆无作答时才返回 `m=None`（未评估）。M 为 0–100 百分比。四态：已掌握 M≥80 且有效作答≥2；进行中 50≤M<80 或 M≥80 但<2 次；薄弱 M<50；未评估 从未测验/练习（不计入薄弱）。作答次数 = quiz attempt 行数 + 已作答 practice_questions 行数。
- 间隔复习状态机（architecture §5.4）：`review_items` `pending ─[到期+完成]─► done`；答对 `interval_days *=3`(1→3→7)，答错重置为 1。调度复用 launchd 每日扫描（不引入 Celery/Redis）。
- 数据：attempts(DM-006, 含 quiz_version)、review_items(DM-007)、questions(DM-005)。
- 薄弱点：章节级 + 知识点级(P2)，每条附 `attempts` 错题依据（拒绝凭空定性，PROG-005）；v1.8.0 起同时纳入**自主练习错题**（`practice_questions`，不改 M）作为薄弱点/巩固练习输入（REQ-PRACTICE-003）。

### 3.6 周报（已废弃 → 拆分迁移）— `reports_bp`（L3，REQ-RPT，AI: TUTOR 建议）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| RPT-001 | student | P1 | 本周概况（天数/对话/测评）→ **v1.9.0 迁移至进度页**（`GET /api/progress/weekly-stats`） |
| RPT-002 | student | P1 | 成绩分析（平均/最高/薄弱）→ **v1.9.0 迁移至进度页** |
| RPT-003 | student | P1 | AI 学习建议 → **v1.9.0 改「每日」生成**（`daily_advice` 表 + `GET /api/progress/advice` + launchd 每日脚本）。**v2.6.4（REQ-RPT-ADVICE-001/002）**：① 响应增 `is_today` / `can_generate`，**按钮可用性只看「今天是否已生成」**，不能只看 `has_advice`（旧逻辑被历史建议永久锁死按钮 → 实报「停在 09-08 且无生成按钮」）；② 生成窗口 = **上一条建议所在日（含）→ 今天**（首条则当天），窗口内「昨天+今天」的活动必须全部计入，`stats` 带 `window_since/window_days/window_label/today/yesterday` |
| RPT-004 | teacher | P2 | 教师全班周报 → **v1.9.0 改为「班级活动」**（`/api/class/leaderboard` + 共性薄弱） |
| RPT-005 | 全部 | P2 | 导出 Markdown/PDF → **v1.9.0 移除**（周报整体废弃） |

**Technical**：周报功能整体废弃，`reports_bp` 保留但不再被前端引用；原内容拆分到「进度页」与「班级」。

### 3.7 班级 — `class_bp`（L3，REQ-CLASS，无 AI）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| CLASS-001 | 全部 | P1 | 班级归属：所有 active 学生（除 `Hermestest` 测试账号）同属一个班级，实名展示 |
| CLASS-002 | 全部 | P1 | 累计对话轮次 / 累计练习次数排行 |
| CLASS-003 | 全部 | P1 | 今日对话轮次 / 今日对话次数 / **今日知识卡片学习张数**排行（今天 UTC+8；后者按 `knowledge_reviews.last_review_at` 每卡一行统计） |
| CLASS-004 | 全部 | P1 | 每次测评的分数排名历史（未参加标注「未参加」，附「已发布测评列表」） |
| CLASS-005 | 全部 | P1 | 掌握度排行（平均 M = 已评估章节 compute_mastery().m 的均值，可附「已掌握 X 章」） |
| CLASS-006 | teacher | P1 | 共性薄弱章节 + 「＋布置巩固测评」入口（跳转出题页） |

**Technical**：`GET /api/class/leaderboard`（student/teacher 均可访问）；student 限定同班集合（即除测试号外的 active 学生）、teacher 无需 `@user_scope` 可看完整排名；`Hermestest` 绝不出现。掌握度排行「平均 M」未评估章节不计入、不当 0。

### 3.8 教师管理后台 — `teacher_bp`（L3，REQ-ADMIN）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| ADMIN-001 | teacher | P1 | 学生账号管理（创建/重置/停用） |
| ADMIN-002 | teacher | P1 | 资料管理（上传/删除/解析态） |
| ADMIN-003 | teacher | P1 | 全班学习概览看板 |

**Technical**：`@role_required("teacher")`；聚合走 `/api/teacher/*` **独立路由，不**经 `@user_scope` 过滤（architecture §九 数据隔离硬约束）；`GET /api/teacher/overview`、`GET /api/teacher/students/:id/progress|quizzes`。

### 3.9 部署与运维（横切 B + L2，REQ-DEP）
**Functional / Technical 合一**（见 §四）。

### 3.10 横切安全护栏（横切 A，REQ-ARCH）
- `@jwt_required` / `@role_required` / `@rate_limit(60/day)` / `@validate_json(schema)` / `@user_scope`。
- 错误码契约：`E_AUTH_*` / `E_ROLE_*` / `E_RATE` / `E_NOT_FOUND` / `E_INVALID_INPUT` / `E_AI_FALLBACK` / `E_INTERNAL`。
- **数据隔离硬约束**：所有读操作经 `@user_scope` 自动 `WHERE user_id=g.user_id`；教师聚合走 `/api/teacher/*`；**集成测试必须含「学生 A 读学生 B → 403/空」（F9）**。

---

### 3.11 每日打卡与连胜（学生端，REQ-CHECKIN）
**Functional**
- **CHECKIN-001（P0）学生端 journey 优化**：登录成功后**首页即「今日任务」**（`learn` 视图置顶任务卡），学生不再需要自己找入口。 ✅
- **CHECKIN-002（P0）每日任务阈值**：当日复习 **distinct 知识卡片 ≥ 30 张** **且**完成 **distinct 练习题 ≥ 5 道** → 当日达标（= 打卡成功，单日只记一次）。 ✅
  - **REQ-CHECKIN-THRESHOLD-001（v2.6.3）阈值单点 + 后端下发**：阈值唯一定义在 `backend/config.py` 的 `TASK_CARDS_REQUIRED` / `TASK_QUESTIONS_REQUIRED`；后端 `data/checkin.py`、`api/checkin.py`、`ai/reminder_copy.py`、`scripts/checkin_reminder.py` 均为**动态引用**，且 `GET /api/checkin/today`（`task.cards_required` / `task.questions_required`）与 `GET /api/checkin/class`（`required`）**把阈值随响应下发**，前端一律读字段、**禁止硬编码**。调阈值 = 只改 config 一处（含副本口径）。见 §12.33。
  - **REQ-CHECKIN-PROGRESS-002（v2.6.3）进度只增不减**：进度显示口径 = `max(实时计数, 当日打卡快照)`（`data.checkin.progress_today()`）——`daily_checkins` 是达标瞬间的不可变快照，卡片库重建会重置 `knowledge_reviews` 导致实时计数回落，若直接展示实时值会出现「4/30 卡」却「✓ 今日已完成」的同屏矛盾。达标判定仍走 `counts_today`（纯净实时），不受此口径影响。见 §12.33。
- **CHECKIN-003（P0）连胜模型（Duolingo 式存活）**：达标日 +1；出现空档日归零；**今天未达标但昨天达标 → 连胜存活**（`state=pending`，天数沿用昨日值）；`longest_streak` 只增不减。 ✅
- **CHECKIN-005 / CHECKIN-006（P0）自动安排学习任务**：今日卡组（**装配优先级见 CHECKIN-009/010**，**跨章**，上限 30（v2.6.3 起，见 REQ-CHECKIN-THRESHOLD-001）与今日练习（5 道；当天已有未答完的 session 优先续答）**全部由服务端自动装配**，学生只需点「继续」。 ✅ v2.4.0 首版「到期复习卡优先 → 未学新卡按章节补齐」存在口径与兜底缺陷，已被 **CHECKIN-009/010/011** 取代，见 §12.27。
- **CHECKIN-007（P0）顶部常驻连胜条**：学生端**所有页面**常驻（🔥 图标 + 连胜天数 + 今日进度 `x/30 卡 · y/5 题` + 状态文案 `今天还没打卡` / `✓ 今日已完成`）；达标瞬间条变色 + toast「🔥 连胜 +1，已连续 N 天」。教师端不显示。 ✅
- **CHECKIN-008（P0）班级「今日打卡」区块**：班级页**置顶**（先于现有排行榜卡），按「已打卡优先」排列，每人一行：头像 + 名字 + `🔥 N 天` + `x/30 卡 · y/5 题`（达标行绿色高亮、自己标 `me`）；未打卡同学行尾「提醒 TA」按钮（→ NOTIF-006）。 ✅
- **CHECKIN-009（P0）「未学习」口径修正 + 任务优先发未学习卡**（CR-2026-0919-DECK）：「未学习」= **`learn_count = 0`（从未真正翻过卡）**，**不是**「没有 `knowledge_reviews` 行」——因为学生只要点开某章「知识卡片」浏览一次，`GET /api/knowledge/<chapter_id>` 就会为该章**全量**懒建 review 行（`status='new'`、`learn_count=0`、`next_review_at=now`）。现状把这类「只看过一眼」的卡误判为「已建行 → 不是新卡」，同时又因 `next_review_at=now ≤ today` 被塞进「到期复习」桶 → **学生永远在复习从没学过的卡，课程进度推不动**。修正后今日任务**优先发未学习卡**（按 `chapters.folder, order_no, name, kc.rowid` 课程顺序推进），再补到期复习卡。 ✅
- **CHECKIN-010（P0）卡组三档兜底，永不返回空**（CR-2026-0919-DECK）：装配优先级 **① 未学习卡 → ② 到期复习卡 → ③ 低掌握度随机补足**。第③档（**CHECKIN-010 核心**）解决用户实报死路——学生把全部卡学成 `mastered` / 未到期时会拿到 **0 张卡**，前端 `toast('今天没有可复习的卡片')` 后直接 return，**学生卡死、无法凑够当日目标张数、连胜断掉且无任何出路**。掌握度序 = `status 档位权重（new<learning<reviewing<mastered）→ learn_count → interval_days` 升序（越小越差）；从**最差的前 `max(3×limit, 20)` 张候选池内随机洗牌**后取 `limit`，同时满足「掌握度低」与「随机」。只要库中有已发布章节的卡片，卡组**绝不空**。 ✅
- **CHECKIN-011（P0）超额学习（想多学也可以）**（CR-2026-0919-DECK）：学生**可以无限继续学**，不受每日目标张数（v2.6.3 起 30 张）限制。任务行 100% 后按钮由「已完成 / disabled」变为**可点的「再学一组」**；额外卡组**排除今日已复习过的卡**（避免重复劳动刷进度），继续计入 distinct 与掌握度，但**不改变任务进度条的 10/10 语义**（`counts_today` 仍是上限口径，达标判定不受影响；**所有进度显示一律夹取到阈值上限（v2.6.3 起 30/5）**，避免超额学习后出现「19/10 卡」观感）。 ✅
- **CHECKIN-012（P1）真空引导**（CR-2026-0919-DECK）：若库中确实**一张已发布卡都没有**（真真空，非三档兜底能救），接口返回明确的 `empty_reason`；前端不再只弹一句 toast 了事，改为**给出可点击的出路**（跳「资料库」勾选章节 → 生成知识卡片）。 ✅
- **CHECKIN-013（P0）学习范围由学生自定**（CR-2026-0919-SCOPE，v2.6.5）：**每日任务只作统计数字，绝不锁定学生能学什么。** 学生勾选范围（学习 hub →「资料库」下拉多选）同时驱动 ① 对话跨章检索 ② 知识卡片复习 ③ 今日任务卡组 ④ 今日练习出题。接口：`GET /api/knowledge/today?chapter_ids=a,b,c`、`POST /api/checkin/start-practice {chapter_ids:[...]}`；响应新增 `scope:{chapter_ids,scoped,count}`。**显式范围内无卡 → `empty_reason="no_cards_in_scope"`，绝不偷偷回落全部**（否则学生以为限制了范围却拿到全量卡）；未传/空 = 全部已发布章节（老行为不变）。练习续答只复用**范围内**未答完的 session。**UI 空勾选 = 使用全部已发布章节**（与接口未传/空等价，列表页显示「N 篇 · 全部」而非「已选 0」）；勾选口径不得与接口语义分叉。 ✅

**Technical**
- **判定只在服务端**（**CHECKIN-004**，P0）：前端无权上报「我打卡了」。计数口径 = `knowledge_reviews` 中当前用户、`date(last_review_at, UTC+8) == 今天` 的 **distinct `card_id`**；`practice_questions` 中属于该生 session、当日 `answered_at` 且已作答的 **distinct id**。阈值常量 `TASK_CARDS_REQUIRED`（现值 **30**）/ `TASK_QUESTIONS_REQUIRED`（现值 5）集中在 `backend/config.py`，**以该文件为唯一真相**（不在此写死数值，避免与实现漂移；v2.6.3 起卡数阈值 10→30，见 REQ-CHECKIN-THRESHOLD-001 / §12.33）。 ✅
- 判定触发点：`POST /api/knowledge/<card_id>/review` 成功、`POST /api/practice/<session_id>/submit` 成功后各调 `checkin.evaluate_and_maybe_complete()`；`GET /api/checkin/today` 每次做一次**惰性幂等评估**（跨日自愈）。 ✅
- **幂等**：`daily_checkins UNIQUE(user_id, checkin_date)` —— 重复调用不写第二行、不重复发通知。时区统一走 `backend/data/timeutil.py` 的 `shanghai_date()`（UTC+8），与班级榜 `today_*` 口径一致。 ✅
- 新增表 `daily_checkins`；新增 `backend/data/checkin.py`（判定/连胜/班级投影/今日卡组装配）；新增 blueprint `checkin_bp`（`/api/checkin`：`GET today` / `GET class` / `POST nudge` / `POST start-practice`）；`knowledge_bp` 增 `GET /api/knowledge/today`。 ✅
- **YAGNI（明确不做）**：补签卡、连胜冻结/复活/保护道具、打卡阈值前端可配置 UI。
- **卡组装配契约（CHECKIN-009~012，CR-2026-0919-DECK）**：
  - 装配函数仍为 `backend/data/checkin.py::build_today_deck(con, user_id, limit=None, mode="task", rng=None)`；三档顺序 **① 未学习（`learn_count=0`，按 `chapters.folder, chapters.order_no, chapters.name, kc.rowid` 课程顺序）→ ② 到期复习（`status != 'mastered'` 且 `date(next_review_at, UTC+8) ≤ today`，按 `next_review_at ASC`）→ ③ 低掌握度随机补足**；去重后截到 `limit`。
  - **第③档算法**：候选 = 已发布章节的全部卡，按 `(status 权重, learn_count ASC, interval_days ASC)` 升序取前 `POOL = max(3*limit, 20)` 张，池内 `rng.shuffle()` 后补足。`rng` 参数默认 `random.Random()`，**测试注入固定 seed 保证确定性**。
  - **永不返回空**：只要存在「已发布章节的卡」，`cards` 长度 `> 0`。真真空才返回 `cards: []` 且带 `empty_reason`（`no_published_cards`）。
  - **返回值扩展**：保留 `cards` / `required` / `short`；每张卡新增 `learn_count`（判「未学习」用，前端可显示「新卡」角标）；新增 `empty_reason`；`mode="extra"` 时新增 `extra: true`。
  - **`mode="extra"`（CHECKIN-011）**：排除**今日已复习过的卡**（`date(last_review_at, UTC+8) == today`），三档其余逻辑不变；不参与 `short` 语义（额外组不承诺凑满）。
  - **接口**：`GET /api/knowledge/today?mode=task|extra`（缺省 `task`）；`GET /api/checkin/today` 内的 `task.cards` 仍为 `mode="task"` 口径。
  - **前端**（`backend/frontend/js/student.js`）：`taskCardHtml()` 中「复习卡片」行在 `cur >= total` 时按钮**不再 `disabled`**，改为可点的「再学一组」→ `Student.startExtraDeck()`；`startTodayDeck()` 的 `if (!cards.length) { toast('今天没有可复习的卡片'); return; }` 死路改为**按 `empty_reason` 给出可点出路**（跳资料库）；`taskCardHtml`/`startTodayDeck` 共用同一翻卡视图（`knowledgeDeck`），额外组结束后返回 `learn` 视图。
  - **测验锚点**：`tests/test_checkin.py` 增「三档优先级 / 全 mastered 未到期时仍发满 10 张（低掌握随机）/ 同 seed 结果一致 / `mode=extra` 排除今日已复习 / 真真空返回 `empty_reason`」；现有「10 张算 5 题算」等用例不得回归。

- 验收点：9 张卡不算 / 10 张算；4 题不算 / 5 题算；同卡当天重复复习只计 1；跨 UTC+8 日界；连胜连续 2 天 +1；空档归零；`state=pending` 存活；幂等只 1 行 + 只 1 条通知。

### 3.12 通知与提醒（师生共用，REQ-NOTIF）
**Functional**
- **NOTIF-001（P0）站内通知中心**：**所有**通知一律落库 → App 内可看历史、未读计数、标记已读、点开跳转对应页（路径 → `path`、测评 → `quiz`、连胜类 → 学习首页）。 ✅
- **NOTIF-003（P0）老师发布新学习路径** → 全体在用学生各一条通知。 ✅
- **NOTIF-004（P0）老师发布新测评** → 全体在用学生各一条通知。 ✅
- **NOTIF-005（P0）每日 19:00 未打卡系统提醒**：个性化俏皮文案（按「当前连胜数 + 今日缺口」取用）+ 萌图；每人每天最多 1 条。 ⚠️ 脚本/文案/plist 已就绪，LaunchAgent 安装与真机跑通由 Hermes 执行。
- **NOTIF-006（P0）同学互提醒（nudge）**：班级页「提醒 TA」→ 被提醒同学收到 `peer_nudge`；**同一天同一发送者→同一接收者最多 1 次**；不能提醒自己；仅学生→学生（教师端不出现该按钮）。 ✅
- **NOTIF-007（P1）打卡成功即时通知**：本人当日**首次**达标 → 「🔥 连胜 +1 / 已连续打卡 N 天」。 ✅
- **NOTIF-008（P0）铃铛 + 未读角标**：`appbar` 右上角（学生端 + 教师端都有），点开 → 通知中心。 ✅

**Technical**
- **双通道（NOTIF-002，P0）**：站内落库 **+** Web Push（VAPID）。**无订阅 / 无密钥 / 发送异常 → 降级为只落站内，绝不 500**；收到 404/410 删除该订阅。这是「19:00 提醒」在 App 关闭时唯一可行通道。 ⚠️ 代码/降级/订阅链路已实现，真机 push 授权需 Ray 配合点授权验证。
- 新增 blueprint `notify_bp`（`/api/notifications`：`GET ""` 列表 / `GET /unread` / `POST /read` / `POST /push/subscribe` / `POST /push/unsubscribe` / `GET|POST /prefs` / `GET /vapid-public-key`）；服务层 `backend/services/notify.py`（先落库、再推送，统一入口 `notify_users()`）+ `backend/services/push.py`（pywebpush 封装）；文案池 `backend/ai/reminder_copy.py`（**纯函数、确定性、不调 LLM**）。
- 新增表 `notifications`、`push_subscriptions`、`notification_prefs`。**幂等**：`notify_users()` 对 `(user_id, type, ref_id, 当天)` 去重；发布类沿用 `class_bp.EXCLUDED_USERNAMES`（`hermestest` / `hermesstu`）排除测试号；unpublish 不发通知。
- 19:00 载体：用户域 LaunchAgent `com.aistudy.checkin-reminder` → `backend/scripts/checkin_reminder.py`（**本机直连库，不经 HTTP，无公网入口**）。
- **限流纪律**：只有会调 LLM 的端点挂 `@rate_limit`；`/api/notifications/*`、`/api/checkin/today|class` 等高频轻量端点**不挂**，避免饿死 LLM 额度。
- **平台限制（如实标注）**：iOS ≥16.4 且已「添加到主屏幕」才支持 Web Push，且权限请求**必须由用户手势触发**（放在设置页「打开提醒」按钮）；iOS **不支持**通知大图 `image`，「萌图」在 iOS 上体现为通知 `icon` + App 内通知卡片；Android / 桌面 Chrome 支持大图。
- 安全：VAPID 私钥只存 `.env`，不进 git / 不进 API 响应 / 不写日志；通知正文中用户可控字段（`display_name`）转义；nudge 发送者名字由服务端取，不接受前端传入。

### 3.13 个人设置（师生共用，REQ-SET）
**Functional**
- **SET-001（P0）**：`appbar` 右上角**头像** → 进入**独立设置页**（hash `settings`），**取代**旧 `openSheet` 简易菜单。 ✅
- **SET-002（P0）修改名称**：`display_name` 1–20 字，保存即生效。 ✅
- **SET-003（P0）修改头像**：12 个预设头像（`a1`…`a12`）选择器，**白名单校验**；空值回退「名字首字」（保持现行为）。 ✅
- **SET-004（P0）修改密码**：**复用**现有 `POST /api/auth/change-password`（不重写）。 ✅
- **SET-005（P0）打开提醒 + 退出登录**：Web Push 授权/订阅开关（设置页同时给通知中心入口）；退出登录沿用 `logout()`。 ⚠️ 开关/订阅/退订已实现，真机授权需 Ray 配合验证。

**Technical**
- `PATCH /api/auth/me`（body `{display_name?, avatar?}`）；`users` 增列 `avatar TEXT NOT NULL DEFAULT ''`，经 `models.migrate()` 增量迁移。
- 「打开提醒」按钮是**唯一**的推送权限请求入口（iOS 手势要求）；关闭 → `pushManager.unsubscribe()` + 服务端删订阅 + `push_enabled=0`。
- 师生端共用同一套设置页与通知中心（教师端**只复用**这两块，业务逻辑不改）。
- **YAGNI**：自定义头像上传（P1 待定，需 uploads + 裁剪链路）、邮件/SMS/微信通知。

---

## 四、部署架构（对齐 architecture §三，吸收 F1/F2）



```
同学手机浏览器 ──HTTPS──► Cloudflare 命名隧道 (ai-study.<域>, 仅 5001)
                                    │
                     iMac:127.0.0.1:5001 (仅本机, 防火墙不对外开)
                                    ▼
            waitress 包裹 Flask app.py (caffeinate -ims 防休眠)
              ┌──────────────┼───────────────┐
              ▼              ▼               ▼
        SQLite(WAL)      ChromaDB        uploads/
        instance/...db   chroma_db/      files/

launchd KeepAlive 崩溃自动拉起
  ⚠️ F1：改 /Library/LaunchDaemons（开机即跑，无需登录），PRD §9.3 的 LaunchAgent 重启无人登录则挂。
iCloud Drive 每日 rsync
  ⚠️ F2：备份前先 PRAGMA wal_checkpoint(TRUNCATE) 或 sqlite3 .backup 刷盘，再 rsync，避免 half-write 损坏。
```

| REQ | 项 | 技术规格（含架构发现） |
|-----|----|------------------------|
| DEP-001 | 单源托管 | Flask `serve_frontend` 托管 `frontend/`；`/` 与 `/<path>` 返 index.html；manifest/sw 同路由 |
| DEP-002 | API 相对路径 | 前端 `BASE_URL=/api` |
| DEP-003 | 生产配置 | `DEBUG=env("FLASK_ENV")!="production"`；**waitress 单进程/4 线程**（F6 澄清）；8GB 内存余量**待实测**（F4） |
| DEP-004 | 公网暴露 | 仅 5001 经隧道；JWT 强制；防火墙不开端口 |
| DEP-005 | 命名隧道 | `cloudflared tunnel create` 固定域名；**F10：部署设证书/域名过期提醒** |
| DEP-006 | 开机自启 | **/Library/LaunchDaemons**（F1，非 LaunchAgent）+ KeepAlive |
| DEP-007 | 防休眠 | `caffeinate -ims python app.py` |
| DEP-008 | 备份 | 每日 rsync（**先 wal_checkpoint**，F2）db+chroma+uploads → iCloud Drive |
| DEP-009 | CORS 收口 | 同源或 `origins=[隧道域名]`，去 `*` |
| DEP-010 | 还原演练 | 上线前删库→iCloud 还原→3 同学数据可查 |

---

## 五、领域模型（对齐 architecture §七，含 F3）

### 5.1 ER（REQ-DM-001~010）
```
users ─< chapters
users ─< conversations ─< messages
chapters ─< materials ─(向量)─► ChromaDB material_chunks(chapter_id)
chapters ─< quizzes ─< questions ─< attempts >─ users
users ─< review_items >─ chapters
users ─< reports
users ─< practice_sessions ─< practice_questions >─ chapters   (自主练习，独立于测评)
```

### 5.2 关键表字段（增量）
| 表 | 关键字段 | REQ | 备注 |
|----|----------|-----|------|
| users | id, username, password_hash, role, display_name, is_active, created_at | DM-001 | v1.5.0 起 grade 维度移除（列保留但不再使用/返回） |
| chapters | id, folder, name, order_no, created_by | DM-002 | 文件夹→章节两级 |
| materials | +uploaded_by, +chapter_id, +is_deleted(软删,F7) | DM-003 | 归属章节 |
| conversations | +user_id, ±chapter_id | DM-009 | 按学生隔离 |
| quizzes | -user_id, +chapter_ids, +version, +teacher_id, +published_at, +title, +status, +confirmed_at, +total_points(DEFAULT 100), +config_json | DM-004 | 教师发布实体；状态机；百分制总分 |
| questions | id, quiz_id, chapter_id, sub_concept, type, content, answer_key, +points(选择/是非5；v1.10.0 取消问答，essay=10 仅兼容旧数据) | DM-005 | 掌握度溯源；单题满分 |
| attempts | id, user_id, quiz_id, question_id, chapter_id, **+quiz_version(F3)**, correct, score(实际得分点), +graded_by('ai'/'teacher'), +is_reviewed, +reviewed_score, created_at | DM-006 | M 数据源之一；评分权双轨 |
| review_items | id, user_id, chapter_id, question_id(NULL), next_review_at, interval_days, status | DM-007 | 间隔复习状态机 |
| practice_sessions | id, user_id, chapter_ids(JSON), difficulty('hard', v1.9.0 隐藏不展示), total_points(实际各题分之和，v1.16.0 起非固定 100), config_json | REQ-PRACTICE-001 | 学生个人即席生成；v1.16.0 起最多 5 道；v1.9.0 起已作答计入 M |
| practice_questions | id, session_id, chapter_id, sub_concept, type, content, options, answer_key, points, content_hash(题干规范化 hash，v1.16.0), correct(可空), user_answer, score(可空), reason, answered_at | REQ-PRACTICE-001/002 | 作答结果留痕；v1.16.0 起 content_hash 供同学生跨会话去重；v1.9.0 起已作答计入 M；错题供薄弱点/巩固 |
| reports | +user_id | DM-008 | 周报归属（v1.9.0 废弃，表保留） |
| daily_advice | id, user_id, advice_date(UTC+8 日历日), stats(JSON), advice, created_at, UNIQUE(user_id, advice_date) | RPT-003(改每日) | 每日建议，每人每天一条 |
| ChromaDB | material_chunks +chapter_id | DM-010 | 按章召回 |

### 5.3 状态机
- **quiz**：`draft ─[确认]─► published ─[重出]─► superseded`（旧版保留）。
- **review_items**：`pending ─[到期+完成]─► done`；答对 `interval*=3`，答错重置 `1`。
- **用户**：`is_active 1⇄0`。
- **attempts 评分权**：`graded_by 'ai' → 'teacher'(覆核)`；`is_reviewed 0→1`（QUIZ-009，教师覆核改分后不可逆回 ai）。
- **session（学习路径发布源）**：`draft ─[发布]─► published`，可 `unpublish` 回 draft；其下章节/资料/视频 `status` 随 session 同步（发布时 → published、取消发布 → draft），学生仅见 `published`。
- **软删除**：`is_deleted 0→1`（软），7 天后硬删（F7）。

---

## 六、API 设计（Blueprint 粒度 + 契约 + 错误码）

### 6.1 Blueprint 表（architecture §四）
| Blueprint | 前缀 | 主要路由 | 鉴权 |
|-----------|------|----------|------|
| auth_bp | /api/auth | login/refresh/me/register | 公开 / Bearer |
| chapters_bp | /api/chapters | 章节 CRUD | 教师写，全部读 |
| materials_bp | /api/materials | 上传/解析/列表/删除/批量 | 教师写，全部读 |
| conversations_bp | /api/conversations | 对话 CRUD + 引导问答(SSE 占位) | 学生本人 |
| quizzes_bp | /api/quizzes | 草稿/发布/版本 | 教师发布，学生作答 |
| attempts_bp | /api/attempts | 作答记录 | 学生本人 |
| practice_bp | /api/practice | 自主练习生成/作答/批改/历史 | 学生本人 |
| progress_bp | /api/progress | 掌握度/四态/薄弱/巩固 + 每周概况/成绩 + 每日建议 | 学生本人 + 教师聚合 |
| reports_bp | /api/reports | 周报（v1.9.0 起废弃，保留不引用） | 学生本人 |
| class_bp | /api/class | 班级排行榜 6 类 + 共性薄弱 | 学生/教师 |
| teacher_bp | /api/teacher | 全班概览/详情 | 教师 |
| curriculum_bp | /api/curriculum | 学习路径 Session CRUD + 发布/取消发布 + 视频课 CRUD + 总览 | 教师写，全部读（学生仅 published） |
| health_bp | /health | 探活 | 公开 |

### 6.2 中间件（横切 A）
`@jwt_required`（解析 Bearer→g.user_id/g.role）｜`@role_required("teacher")`｜`@rate_limit(60/day)`｜`@validate_json(schema)`｜`@user_scope`（自动 `user_id` 过滤）。

### 6.3 错误码契约
成功 `{code:0,data:...}`；失败 `{code:E,msg:...}`：`E_AUTH_*` / `E_ROLE_*` / `E_RATE` / `E_NOT_FOUND` / `E_INVALID_INPUT` / `E_AI_FALLBACK` / `E_INTERNAL`。

### 6.4 关键接口（Functional↔Technical 绑定）
| REQ | Method & Path | 角色 | 中间件 |
|-----|---------------|------|--------|
| AUTH-001 | POST /api/auth/login | 全部 | @validate_json |
| AUTH-002 | POST /api/auth/register | teacher | @role_required |
| MAT-002 | POST /api/materials/upload | teacher | @role_required, @rate_limit |
| CHAT-003 | POST /api/conversations/:id/message | student | @jwt_required, @user_scope |
| QUIZ-001 | POST /api/quizzes/draft → :id/publish | teacher | @role_required |
| QUIZ-002 | POST /api/quizzes/:id/attempts | student | @jwt_required, @user_scope |
| PRACTICE-001 | POST /api/practice/generate | student | @jwt_required, @role_required |
| PRACTICE-002 | POST /api/practice/:id/submit | student | @jwt_required, @role_required |
| PROG-001 | GET /api/progress/mastery | student | @user_scope |
| PROG-006 | POST /api/review-items/generate | student | @user_scope |
| ADMIN-003 | GET /api/teacher/overview | teacher | @role_required |
| — | GET /health | 公开 | — |

---

## 七、AI 能力架构（三 Agent + 两层 Fallback + 护栏）

### 7.1 三 Agent 提示词（architecture §5.1）
- **TUTOR**：注入 `weak_chapters`/`retrieved_chunks`（v1.5.0 起不再注入 `student_grade`）；规则「不直接给答案，以追问引导；答对或卡住才给点拨」；轮次 `{turn}/12` 护栏。
- **QUIZZER**：输入 `chapter_ids/sub_concepts/spec + retrieved_chunks`（RAG 检索资料正文，题目基于资料难度出题）；产出结构化 JSON 题目集（含 `answer_key`/`sub_concept`）。
- **GRADER**：输入题目(含 `points`)+参考答案+学生作答；产出 `{correct, score, reason}`，`score∈[0,points]`（问答 0–10、客观题不调用 GRADER 改由系统确定性判分）。

> 决策：提示词即一切，不引入工具注册表；保留 `def tool_x(ctx)->Result` 统一签名，未来 Agent>5 个再升级（§十四）。

### 7.2 两层 Fallback（architecture §5.5）
| 层 | 实现 | 触发 |
|----|------|------|
| L1 | DeepSeek 生成 | 默认 |
| L2 | TUTOR 固定引导语池 | API>30s/5xx、召回为空、越界 |
| L3 | 固定答案 | **不做**（宁可报错） |

### 7.3 护栏（F5 / 红线 #1）
- DeepSeek 超时/报错 → 兜底「资料加载中，请稍后再试」+ 不写错误对话。
- 召回为空 → 兜底「未在资料中找到相关内容」+ 建议切换章节。
- 越界（请求做题/答案）→ 意图路由分流 QUIZZER / 引导点拨。
- TUTOR 输出门控：拒绝规则 + 越界检测 + 界面「AI 生成请核对」标注。

---

## 八、RAG 流水线（architecture §六）

- **离线入索引**（教师上传同步）：解析 → 分块(≈500/overlap≈80, 按章切优先) → `all-MiniLM-L6-v2` 本地编码 → ChromaDB.add(metadata:{material_id,chapter_id,page_no,chunk_idx}) → 更新 `materials.chunk_count`。
- **在线召回**：`retrieve(query, chapter_id, top_k=5)` → cosine 距离，取 `1-distance ≥ 0.4`；过弱视为召回不足触发兜底。
- 不加 BM25/HyDE（PRD §13 首字≤3s，HyDE 多 1 次 LLM 延迟 +2-3s，违反）。

---

## 九、关键流程时序（Functional↔Technical，architecture §八）

### 9.1 引导式对话
Student(PWA) → Flask(JWT+人设加载+ChromaDB 召回 chapter_id) → DeepSeek(SSE 逐 token, TUTOR, ≤12 轮) → 写 messages(user_id 隔离)。

### 9.2 教师发布测评
Teacher → 选章+QUIZ-005 配置(凑满 100 分组合) → Flask(鉴权+`@role_required`, status=draft, QUIZZER 按配置生成 questions 并赋 `points`) → 教师预览/微调 → 确认(published, published_at, confirmed_at, total_points=100)。

### 9.3 巩固练习闭环
Student(一键巩固) → 算 M 找薄弱章 → QUIZZER 出巩固题 → INSERT review_items(interval=1) → 作答+GRADER 批改 → 写 attempts(含 quiz_version) + 算新 M → review_items 答对 interval*3 / 错重置 1；每日 launchd 扫描到期项。

---

## 十、安全与护栏（降维「监理端」，对齐 architecture §九）

| ChemAI 监理项 | 本期实现 | REQ |
|---------------|----------|-----|
| JWT 4 角色+矩阵 | JWT 2 角色 + `@role_required` | AUTH-004 |
| 运行护栏 | `@rate_limit(60/day)` + 重复请求 5s 去重 | NFR-006 |
| 审批门禁 | 草稿→确认发布 | QUIZ-001/008 |
| 内容安全 | 入参长度限制 + 敏感词列表 | CHAT-004(F5) |
| Checkpoint | iCloud 每日 rsync | DEP-008 |
| 心跳 | /health + launchd KeepAlive | NFR-007 |

- **数据隔离硬约束**：读操作经 `@user_scope`；教师聚合走 `/api/teacher/*` 不经 `@user_scope`；**F9 越权读 403 用例入 DoD**。
- **F7 软删除**：资料删改软删 + 二次确认 + 7 天窗口。
- **F5 TUTOR 输出门控**：拒绝规则 + 越界检测 + 「AI 生成请核对」标注。

---

## 十一、可观测与备份（architecture §十）

| 维度 | 实现 | 验收 |
|------|------|------|
| 探活 | `GET /health` → `{status,db,chroma}` | 隧道/health 200 |
| 崩溃恢复 | launchd KeepAlive | `kill -9` 5s 内自起 |
| 备份 | 每日 rsync（**先 wal_checkpoint**，F2） | 9.4 核查 + 演练 |
| 日志 | Flask+waitress stderr → `logs/app.log` 按日轮转 | 异常可追溯 |
| 监控告警 | 不做（4 人可接受，已知盲区） | — |
| 成本 | 限速 60/天/用户 + 单请求 ≤120s；**v2.3.0 起每次 LLM 调用逐次用量记账**（`ai/usage_log.py` → `~/.hermes/app-usage/aistudy.jsonl`，供 Token 账单看板精确统计） | 超限 429 |

---

## 十二、阶段化落地（architecture §十一）

| 阶段 | Functional 范围 | 技术新增模块 | 架构影响 |
|------|----------------|--------------|----------|
| P0 阶段一 | AUTH/MAT/CHAT/QUIZ(草稿确认) | auth/chapters/materials/conversations + TUTOR+QUIZZER 草稿 | 基线架构落地 |
| P1 阶段二 | PROG/RPT/ADMIN + 巩固闭环 | progress/reports/teacher/attempts/review_items + GRADER + review_sched | 新增调度模块 |
| P2 阶段三 | SSE/错题本/引用/隧道访问策略 | SSE 中间件/错题本视图/Cloudflare Access | 不动核心，加固外层 |

### 12.1 实现状态回写（v1.0.0，2026-09-02）

> 已按「A 方案」完成 P0 阶段一 + P1 阶段二核心闭环，**未引入** ChromaDB / 向量嵌入 / torch / sentence-transformers：
> - **AUTH-001~008**：JWT 12h + 登录/注册/改密/me/refresh 已实现（✅）
> - **MAT-001~005/007**：章节 CRUD + 资料上传解析（pdfplumber/python-pptx/python-docx，MD/TXT 直读）+ 软删除（F7）已实现（✅）；MAT-006 批量上传 P2 未做
> - **CHAT-001~006/008**：引导式对话（TUTOR 苏格拉底、≤12 轮护栏、仅本人可见、多对话）已实现；**RAG 降维**为 SQLite `chunks` 表 + `retrieve(query, chapter_id)` 关键词/章节匹配 top-k=5（替代 ChromaDB，MAT-003/ARCH-RAG 降维实现）（✅）；CHAT-007 SSE、CHAT-009 引用标注 P2 未做
> - **QUIZ-001~003/007/008**：草稿→确认发布、学生作答、GRADER 三档批改、重出新 version、`attempts.quiz_version` 落地（F3）已实现（✅，注：当前为对错二元计分，百分制得分模型见 §12.4 待实现）；**v1.7.1 补全 QUIZ-001「预览」环节**——草稿卡片新增「👁 预览」按钮，调 `GET /api/quizzes/:id` 展示全部题目/分值/选项/参考答案（后端本就返回草稿题目+answer_key，仅前端此前缺预览入口）；QUIZ-005 题型配置（百分制组合，P1 redesign）待做、QUIZ-006 错题本 P2 未做
> - **PROG-001/004/005/006/007/008**：掌握度 M 四态（时间衰减 + 最新 version 聚合）+ 间隔复习 1→3→7 + 薄弱点带错题依据已实现（✅）
> - **RPT-001~003**：学生周报（概况/成绩/AI 建议）已实现（✅）；RPT-004 教师全班周报降维为聚合概览、RPT-005 导出 P2 未做
> - **ADMIN-001~003**：学生账号管理（创建/重置/停用）+ 资料管理 + 全班概览已实现（✅）
> - **DEP-003/001（F6）**：production 关闭 debug、waitress 单进程/4 线程、`/health` 探活已实现（✅）；LaunchDaemon 自启/隧道/备份脚本已就绪（deploy/、scripts/），部署动作待执行
> - **NFR-006**：`@rate_limit(60/day)` LLM 限速已实现（✅）；**v1.19.0 起按 (user_id, endpoint) 独立计数**（原全端点共享一桶会互相挤占、误伤高频非 LLM 请求如知识卡翻卡），知识卡 GET/review 摘除限流

### 12.2 实现状态回写（v1.1.0，2026-09-02）

> - **MAT-001 强化（章节编辑/删除入口）**：教师后台章节卡片新增「编辑」（`PUT /api/chapters/:id` 改文件夹/章节名）与「删除」（`DELETE /api/chapters/:id`，其下有资料时后端拦截须先软删资料）按钮——老师可完全自定义课程结构（✅）。后端接口本就存在，本次补前端入口。
> - **底部导航固定（UI 修复）**：`.tabbar` 由 `position:sticky` 改为 `position:fixed`（居中 max-width:520px），钉在屏幕底部不再随内容滚动（✅）。

### 12.3 实现状态回写（v1.1.1，2026-09-02）

> - **QUIZ-002/003 bool 是非题作答修复（前端 bug）**：`viewQuizTake()` 原本 bool 与 choice 走同一 `options` 分支，bool 的 `options` 为空数组 → 只显示题干、无作答控件。现为 bool 题单独渲染「正确 / 错误」按钮；`pick()` 兼容 choice 索引与 bool 文本；`openReview()` 巩固练习同补 bool 按钮，并对复习项 `options`（后端 JSON 字符串）做 `JSON.parse` 归一化，修复 choice/essay 复习题打不开的同类渲染 bug（✅）。后端 `grader._deterministic`（bool 按 `answer_key` 字符串比对）无需改动。

**偏离登记**：RAG 由「ChromaDB 纯向量 + all-MiniLM-L6-v2」降维为「SQLite chunks 关键词/章节匹配」，不引入本地嵌入模型；检索无命中/LLM 不可用/越界时降级到固定引导语池（两层 Fallback L1→L2），L3 固定答案不做。

### 12.4 已实现（测评百分制评分模型，2026-09-02 设计增补，v2.1 → v1.3.0）

> 以下 v2.1 新增设计已按本规格实现并落地（§三/§五/§七/§九/§十二 已含全部字段、接口与公式）：
> - **QUIZ-005 提 P1**：教师可选 100 分组合（v1.10.0 起预设：20 选择 / 20 是非；或自定义并校验 `choice+bool===20`=100 分，取消问答）；QUIZZER 默认规格由「3 道题」改为 100 分组合（✅）。
> - **数据模型（DM-004/005/006）**：`quizzes.total_points=100` + `config_json`；`questions.points`（选择/是非 5、问答 10）；`attempts.score` 改存实际得分点、`graded_by('ai'/'teacher')`、`is_reviewed`、`reviewed_score`；SQLite 幂等迁移（存量题按题型补分、存量二元 score 一次性换算）已落地（✅）。
> - **评分权双轨（QUIZ-003/009）**：客观题系统确定性判分；问答题 AI(GRADER) 评 0–10；新增 `PUT /api/attempts/:id/review` 教师覆核改分（✅）。
> - **M 公式（PROG-007）**：由对错二元改为百分制得分率 `Σ(score)/Σ(points)×100`（✅）。
> - **展示层**：测评报告/进度/周报改显百分制总分与得分率；教师后台加覆核改分入口（✅）。

---

### 12.5 实现状态回写（v1.4.0，2026-09-02）

> - **资料下载（MAT-003/004 强化，方案 B 去重）**：`materials` 新增 `source_path`（源文件绝对路径，指向课件/）；新增 `GET /api/materials/:id/download`（`send_file` serve 课件/ 源文件，学生仅已发布可下 / 教师全下）。源文件**不复制**进 uploads/（单份存储避免重复），app 直接 serve 课件/（✅）。
> - **资料下载分块流式 + 进度百分比（v1.13.3，MAT-003/004 强化）**：前端 `api.js` `download` 由一次 `resp.blob()` 改为 `ReadableStream` 分块流式读取——边下边更新进度条（`#dlProgress`，有 `Content-Length` 显示「下载中 N%」+ 进度条宽度，无总长退化为显示已下载 MB），避免大文件(pptx/pdf)全量拉取时无反馈、看似卡死。无流式能力浏览器退化为一次 blob；延迟 revoke 保留（防偶发 load failed）（✅）。
> - **W1 课程注入（CURR/VIDEO）**：注入 W1S1《大模型是什么：概念扫盲》+ W1S2《AI 产品地图》——2 Session + 2 章节（一对一）+ 7 资料（152 文本块）+ 5 视频链接，全 `draft`（发布后学生可见）。注入脚本 `scripts/inject_w1.py`（幂等可重跑），W2–W8 复用扩展（✅）。
> - **UI 稳定（v1.4.1）**：`.mini-btn`/`.dl` 统一尺寸（height/min-width/inline-flex）修复按钮不对齐；viewport `maximum-scale=1,user-scalable=no` + `touch-action:manipulation` + `text-size-adjust:100%` 禁止页面缩放（✅）。
> - **UI 修复（v1.4.2）**：管理后台卡片头标题竖排修复——`.adm-card .meta` 改 `flex:1 1 auto; min-width:0` + `.nm` 加 `overflow-wrap/word-break:break-word`（长标题不再被 flex 挤压成单字一行）；卡片头「上传/编辑/删除」打包进 `margin-left:auto; flex-shrink:0` 容器统一靠右同排（修复按钮因标题宽度被 wrap 拆散）；资料行「下载/删」去掉行内 `padding` 覆盖、统一标准 `.mini-btn`（✅）。
> - **UI 修复（v1.4.3）**：管理后台卡片头改**两行布局**——标题（含副标题）独占一行、`flex:1` 完整显示，「上传/编辑/删除」移到标题下方单独一行右对齐（彻底解决长标题被按钮挤压成竖排/wrap，用户要求按钮不必与标题同排）；资料文件名去掉 `ellipsis` 改 `word-break:break-word` 完整显示不省略；Service Worker `CACHE` bump `v5→v6` 强制手机端缓存失效拉取新版（✅）。
> - **移除年级维度（v1.5.0）**：学生端学习页删「🧑‍🎓 年级」pill；教师端新建学生表单删「年级（可选）」输入框；后端 `/api/auth/login/register`、`/api/teacher` 列表不再返回/接收 `grade`（DB 保留列但清空）。同步 CHAT-001/TUTOR 不再注入 `grade`（✅）。
> - **进度可见性修复（v1.5.0）**：`/api/progress/{mastery,weak-points,review-items/generate}` 的 `_all_chapters` 只查询 `status='published'` 章节——未发布 session（如 W1S2 draft）不再进学生进度/掌握度/薄弱点/巩固练习（修复「学生看到两个未测评」）（✅）。
> - **TUTOR 视频推荐降频（v1.5.1）**：`tutor_orchestrate` 仅当学生提问主动问及视频课（含"视频/课程/b站/网课"等关键词）才召回 `related_videos`，普通提问返回空数组；TUTOR 提示词强化"优先基于【资料依据】引导、多指向章节资料原文，仅学生明确问视频才提一句"（修复"对话里一直出现相关视频课"）（✅）。
> - **网络优化（v1.5.1）**：`deploy/run.sh` 服务默认绑定 `0.0.0.0`，允许局域网手机直连 iMac `192.168.50.22:5001`（实测 5ms），减少对不稳 Cloudflare tunnel（130ms+、QUIC 易断）的依赖（根治"点一下反应半秒"）（✅）。
> - **iCloud 定时备份（v1.5.1，DEP-008）**：新增 launchd `com.xicheng.aistudy-icloud-backup`（每日 03:20），调用 `scripts/backup_icloud.sh`（wal_checkpoint 刷盘 + rsync 备份 db/uploads/chroma 到 iCloud Drive，保留7天）。此前仅四口之家有备份，本 app 脚本存在但未定时（✅）。

### 12.6 实现状态回写（v1.7.0，2026-09-03）

> - **CHAT-008 强化（对话标题总结）**：后端 `post_message` 检测首条用户消息，取内容前 18 字符（去多余空白）自动生成标题并写回 `conversations.title`，响应返回 `title`；前端对话 pill 标题单行不折行、超出省略（`.pill-t`），修复一排「新对话」及「新对/话」折行观感（✅）。
> - **CHAT-008 强化（对话 pill 长按删除）**：学习页对话 pill 支持长按（~600ms，touchstart/touchend + mousedown/mouseup 双兼容，抑制长按后补发的 click）弹出底部确认层「删除对话/取消」，确认后调既有 `DELETE /api/conversations/:id` 删除并刷新列表（✅）。
> - **CHAT-002 强化（资料库横滑卡片组 + 动态提示）**：章节 ≥2 个时资料库改为 `overflow-x:auto` 横向卡片（固定宽度、隐藏滚动条、可左右滑动），单章保持竖排；下方小字随 `App.activeChapter` 动态提示（已选显示章节名，未选提示从上方资料库选择）（✅）。

### 12.7 实现状态回写（v1.9.0，2026-09-03）

> - **练习计入掌握度 M（任务书定义 A，推翻旧 F3）**：`compute_mastery()` 额外聚合该章自主练习 `practice_questions`（answered_at 非空），与测评同一条加权公式（w=0.5^间隔周数、按章聚合、earned=score、possible=points），并计入「已掌握≥2 次」作答次数；仅当该章既无测评 attempt 也无练习作答时才返回 m=None（✅）。练习错题进薄弱点/巩固练习（PROG-005/006）保留。
> - **移除难度标注（全 App）**：`practice_sessions.difficulty` 字段保留但前端不再展示 hard/难度；清理 student.js 练习入口/卡片/生成/批改页全部难度文案与 hard badge（✅）。
> - **班级功能（REQ-CLASS-001~006）**：新建 `class_bp`（`/api/class/leaderboard`）返回 6 类排行榜；周报 tab 改为「班级」（学生）/「班级活动」（教师），`viewReport` 整体替换为 `viewClass()`/`viewClassActivity()`（✅）。`Hermestest` 绝不出现。
> - **班级活动「测评分数」下拉标题规范（v1.13.6，REQ-CLASS-004 强化）**：leaderboard 返回的 `quiz_list` 补 `label`（通过 `chapter_ids` 反查已发布 session → 「测评 · 第 N 章 · 章标题」），前端 `quizChips` 改用 `q.label || q.title`——避免已发布但未改标题的测评在班级活动下拉显示难看的默认值「草稿 · X 章」（✅）。**v2.7.1 起**：该 label 由 `api/class_bp.py::_quiz_session_label()` 单点产出章号口径（不再出现「第X周 第Y节」，见 §12.41）；`api/quizzes.py::_quiz_session()` 同样只回 `chapter_no`，前端测评标题不再自己拼周/节。
> - **AI 建议改每日（RPT-003）**：新增 `daily_advice` 表 + `GET /api/progress/advice` + 每日生成脚本 `backend/scripts/daily_advice_gen.py` + launchd plist（✅）。
> - **周报迁移（RPT-001/002）**：本周概况/成绩分析迁移至进度页（`GET /api/progress/weekly-stats`），进度页结构为「四态 → AI 建议 → 本周概况/成绩 → 各章节 → 薄弱点 → 巩固闭环」（✅）。
> - **对话输入框固定**：`.composer` 改 `position:fixed;bottom:78px` 钉在 tabbar 之上，`visualViewport` 脚本写 `--kb` 补偿键盘高度（✅）。
> - **今日/今天统一 UTC+8**：新增 `data/timeutil.py`（Asia/Shanghai），班级今日榜单与每日建议日期按 UTC+8 日历日判定（✅）。

### 12.8 实现状态回写（v1.10.1，2026-09-07）

> - **QUIZ-002 学生答题页「返回列表」按钮无响应（前端 bug）**：`viewQuizTake()` 的「返回列表」`onclick` 只清了无关字段 `App.activeQuiz`（`Student.render()` 根本不用它分派），未清 `Student.quiz/answers/result` → 点击后 `render()` 仍按 `this.quiz` 走答题页。修复：改为清 `Student.quiz=null; Student.answers={}; Student.result=null`（与结果页「返回测评列表」按钮一致），返回测评列表生效（✅）。

### 12.9 实现状态回写（v1.10.2，2026-09-07）

> - **QUIZ-001/008 已发布测评可预览（前端增强）**：教师端「已发布的测评」卡片原仅有「重出」无预览入口；新增「👁 预览」（复用 `Teacher.preview`，调 `GET /api/quizzes/:id` 展示题目/分值/答案）。预览弹窗标题与底部按钮按状态适配：草稿→「草稿预览」+「确认发布」，已发布→「测评预览」+仅「关闭」（已发布无需再确认发布）（✅）。

### 12.10 实现状态回写（v1.11.0，2026-09-07）

> - **QUIZ-002/004 + PROG-005（学生端错题完整展示 + 测评一次作答，前后端）**：① 错题改为完整渲染题目+全部选项，绿标「✅正确答案」红标「❌你的答案」（choice 索引→文本、bool 正确/错误、essay 你的回答 vs 参考答案）——`report.wrong` 与 `weak-points evidence` 补 `type`/`options` 字段；② 测评**一次作答**：`submit_attempt` 加「该测评已作答」限制（400），`report`/`list_quizzes` 取成绩改 `MIN(created_at)`（首次），`openQuiz` 对已作答测评恒显示该次结果（分数+错题）不重做；③ 进度页薄弱点错题完整展示（去除 `slice(0,2)` 摘要），测评错题+练习错题都完整显示（✅）。

### 12.11 实现状态回写（v1.12.0，2026-09-07）

> - **QUIZ-010（教师看学生错题，✅）**：`GET /api/quizzes/:id/student-errors` 仅教师可调用，按当前测评版本的首次作答汇总，只返回有 attempt 的学生；每人返回得分与题目、选项、学生答案、正确答案。已发布卡片新增「👁 学生错题」，学生列表可进入完整错题展示。
> - **CHAT-010（咨询错题辅导，✅）**：学习页新增「💡 咨询错题」，仅列本人已作答测评，并显示命中 published session 的「第 X 周 第 Y 节 · 标题」（未命中标为未关联）；选中后取本人 report 错题，以受限 `wrong_ctx` 随下一条消息传入 TUTOR。TUTOR 提示词优先逐题引导正确思路与巩固，发送成功即清空上下文，避免误带。
> - **测评课程标注（✅）**：`GET /api/quizzes` 基于 quiz `chapter_ids` 与已发布 session 的 `chapter_ids` 首个交集补充 `session`，未命中返回 `null`。

### 12.12 实现状态回写（v1.13.4，2026-09-07）

> - **CHAT-004/005（TUTOR 辅导模式可开关，✅）**：普通提问（无错题）从「恒引导式」改为**可切换「引导式 / 直接讲解」，默认直接讲解**。前端学习页顶部「🧑‍🎓 引导式」写死 pill 改为两态开关，选择写入 `localStorage("aistudy_tutor_mode")`（`guide`/`direct`）；`post_message` 读取 `tutor_mode`（非法/缺失默认 `direct`）传给 `tutor_orchestrate`，`TUTOR_SYSTEM` 新增 `{tutor_mode}` 槽位按模式分流。**错题辅导（wrong_ctx 非空）恒强制直接逐题输出完整解析**，不受开关影响（维持 v1.13.0 逻辑）。

### 12.13 实现状态回写（v1.13.5，2026-09-07）

> - **PROG-005（薄弱点改独立页，✅）**：学生端进度页底部「薄弱点（带错题依据）」由内嵌折叠大卡改为**入口卡**（「📌 薄弱点 · N 章 · M 道错题 ›」），点击进入独立薄弱点页（新 hash `#weak`，`Student.viewWeak()`）。独立页为**章节纵向列表**（掌握度 M + 错题数）→ 点章展开 → 章内按**「练习错题 / 测评错题（第X周 第Y节，用 `/api/quizzes` quizMap 反查 session 标题）」分组** → 点组**向下滚动展开全部错题**（复用 `fmtWrongCard` 纵向排列，杜绝横向滚动/横向卡片）。交互状态：`weakOpen`（展开章）+ `weakGroupOpen`（`${chapter_id}:${quiz_id|practice}` 组级展开）。后端 `_wrong_evidence`/`_practice_wrong` 去掉 `limit=5` 截断、全量返回错题依据（聚合逻辑不变）。

### 12.14 实现状态回写（v1.15.0，2026-09-08）

> - **CLASS-003 强化（今日练习次数，✅）**：`GET /api/class/leaderboard` 新增 `today_practice`（`practice_sessions.created_at` 按 UTC+8「今天」过滤，`_sorted_entries` 排序）；班级页 `viewClass()` 主屏改为**两张排行榜卡片**（① 今日对话次数 `today_conversations` ② 今日练习次数 `today_practice`），前 3 名金/银/铜奖牌（内联 SVG，非 emoji）、第 4 名起普通序号；其余排行榜（累计对话轮/累计练习/测评分数/掌握度）收进底部弹出层（`openClassMore` 复用 `openSheet`，点「关闭」收起，测评分数 chip 切换后重开弹层）——数据后端全保留、仅 UI 收进弹层。
> - **CHAT-004 强化（模式切换吸顶，✅）**：学习页「引导式/直接讲解」segmented control 从内容流提出、包 `.seg-sticky`（`position:sticky;top:74px`），对话滚动时固定顶部、始终可见，不遮挡 appbar。
> - **MAT-004 强化（资料库「越新越左」，✅）**：`GET /api/chapters` 返回补 `created_at`，`viewLearn()` 按 `created_at` 倒序渲染章节卡片（最新添加排最左），选中态/「N 篇」徽章/单章竖排·多章横滑不变。
> - **输入框钉底根治（UI 修复，✅）**：`body` 移除 `-webkit-overflow-scrolling:touch`（该属性在 body 滚动时会让 iOS `position:fixed` 的 `.composer`/`.tabbar` 跟随回弹），输入框稳定钉在 `.tabbar`（78px）正上方；headless Chrome 实测滚动前后 `.composer` `getBoundingClientRect().y` 恒定。

### 12.15 实现状态回写（v1.16.0，2026-09-08）

> - **自主练习出题全走兜底（根因修复，✅）**：生产 `.env` 的 `DEEPSEEK_MODEL` 由 `deepseek-v4-flash`（原生推理模型）改为 `deepseek-chat`（非推理）。实测推理模型对大 JSON 出题 prompt `finish_reason=length`、`content len=0`、`reasoning len=3612`、2000 completion_tokens 全烧在 reasoning → `_chat()` 拿空 content → `quizzer_generate()` 返回 None → 无条件兜底硬编码模板；改 `deepseek-chat` 后 `content len=4871`、`reasoning len=0`（真实资料题）。与四口之家 sikou「智能养护贴士」修法一致（短/结构化任务用 deepseek-chat）。
> - **PRACTICE-001/002/003 重构（最多 5 道 + 资料驱动 + 难度 high + 同学生不重复，✅）**：`generate_practice_questions()` 不再强制 20 道/100 分，改为基于章节资料出 **2~5 道 choice/bool（difficulty=hard）**；端点放开 `total != 100` 校验，`total_points` 写实际分之和、`_session_dict` 按实际归一；LLM 真返空返回空列表、前端提示「生成失败，请重试」（不再硬塞通用模板）。`practice_questions` 新增 `content_hash`（题干规范化 hash），生成前查该学生历史题干注入提示词（避免重复 + 基于资料衍生变体）并在后端按 hash 过滤，同学生跨会话不重复、不同学生可相同。
> - **前端文案（✅）**：练习入口/生成页/答题页「合计 100 分」改为「最多 5 题 · N 题 · 共 X 分」；sw.js `CACHE` bump `v31→v32`。

### 12.16 实现状态回写（v1.14.0~v1.14.2，2026-09-07）

> - **全局 UI 精修 + 信息层级重排（v1.14.0，CHAT-004 视图 / NFR-005 兼容强化，✅）**：用户明确拒绝「原味精修/方向A」后，落地**方向 B = 信息层级重排**（交付标准 = 一眼看出差异，而非代码更干净）。三件事：① 去 emoji → 共享内联 SVG 图标库（`app.js` `ICO` + `ic(name,cls)`，学生珊瑚/教师靛蓝自适应）；② 内联样式抽工具类（`.sec-title/.sec-head/.mt-*/.mb-*/.grow/.flex`）；③ 学习页层级重排（模式切换 pill → `.seg` segmented control、AI 声明 → `.ai-info` 安静小字、资料库加 `.card-count` 篇数徽章 + 选中章 `.chapter.active::before` 左珊瑚条、轮数 → `.row-meta` 进度行、底部咨询错题 → `.tool-btn` 珊瑚行动按钮）。sw.js CACHE bump。
> - **MAT-003/004 强化（资料下载进度条修复，v1.14.1，✅）**：下载进度条始终不显示——前半空方法 `_dlProgress*` 开头 `if (typeof $ === "undefined" || !document.getElementById("dlProgress")) return;` 因**本项目从未引入 jQuery**，`typeof $ === "undefined"` 恒真 → 整个条件恒真 → 进度条逻辑每次直接 return 永不显示。修复 = 删掉 `typeof $` 守卫，只留 `document.getElementById("dlProgress")` 判存在；+ 节流优化（进度更新降频，避免大文件高频更新卡顿）。
> - **CHAT-004 强化（对话区皮筋回弹 + 多轮上下文丢失，v1.14.2，✅）**：① 输入框皮筋回弹 = `.composer`/`.tabbar` 放在 `-webkit-overflow-scrolling:touch` 滚动容器内，iOS 滚动时 `position:fixed` 元素跟滚回弹 → 滚动改交 `body`（`body{overflow-y:auto}`、`.screen{overflow:visible}`），composer/tabbar 才真正相对 viewport、聊天内容 padding-bottom ≥ composer 实测高；② 对话多轮上下文丢失 = `tutor_orchestrate` 用**当前单条 content** 做 RAG 检索，学生发承接语（「你帮我展开」「继续」）检索 0 chunks 命中 `if not chunks and not wrong_ctx` gate 直接兜底、LLM 根本没被调 → 检索空回退 `_last_user_substantive(history)` 取最近一轮实质提问再检索 + gate 放宽为 `and not history`（有历史上下文就放行让 LLM 承接，不因单轮检索空打断）。

### 12.17 实现状态回写（v1.16.1~v1.16.2，2026-09-08）

> - **CHAT-004 视图（学习页 appbar 与模式切换顶部缝隙根治，✅）**：v1.16.1 定位 appbar 与「引导式/直接讲解」模式切换之间出现缝隙——`.seg-sticky{position:sticky;top:74px}` 硬编码 top 对齐，但 iOS appbar 实际渲染 **71px**，留 **3px 透明带**，滚动时资料库横向卡片/对话消息从缝隙漏出。v1.16.2 **根治**：把 appbar 与模式切换**合并为同一 `.chat-head` 吸顶块**（`position:sticky;top:0;z-index:30;background:var(--bg)`），二者成为同一不透明容器一起钉在 `top:0`——从结构上消灭「appbar 与 seg 独立缝隙」，不再依赖任何硬编码 top 对位；`.chat-head .appbar{position:static;border-bottom:none}`（去掉 appbar 自身 sticky、避免与 chat-head 抢位）。**教训**：`position:sticky` 用硬编码 top（如 `top:74px`）对齐另一个可变高度祖先/兄弟是**根本脆弱**——iOS/安卓字体度量差几像素即漏缝；要根治应把要一起固定的元素包进**同一不透明 sticky 容器**。诊断「顶部漏缝」用 `scripts/verify_header_no_leak.py`（iPhone profile + 逐 2px 扫 header 带 alpha），勿手写不同版本 headless 脚本。

## 十三、NFR 与已知盲区（融合 PRD §13 + architecture §十三）

### 13.1 NFR（REQ-NFR）
| REQ | 维度 | 目标 |
|-----|------|------|
| NFR-001 | 性能 | RAG 首字 ≤3s(流式)，完整 P95 ≤12s |
| NFR-002 | 可用性 | ≥99%（前提 iMac 通电）；launchd KeepAlive 自拉起 |
| NFR-003 | 并发 | 峰值 4 人；SQLite WAL + waitress 4 线程 |
| NFR-004 | 容量 | 资料 ≤500MB |
| NFR-005 | 兼容 | iOS15+/Android10+；PWA 主屏 |
| NFR-006 | 限速 | ≤60 LLM 调用/用户/天、单请求 ≤120s；超限 429；**v1.19.0 起按 (user_id, endpoint) 独立计数**（知识卡 GET/review 摘除限流，纯读写无 LLM） |
| NFR-007 | 可观测 | /health + 自动拉起 |

### 13.2 已知盲区（显式登记）
1. **🔴 不做 Evals（F8）** — 触发补做：TUTOR 连续 2 次被吐槽质量下降 / QUIZZER 草稿 3 次以上大改 / 新增第 4 个 Agent / 换 DeepSeek 新模型。主动检测：埋点记录「护栏内给最终答案」比例，周报附教师，偏差超阈预警。
2. **🟡 单点部署** — iMac 断电即停，约定项（通电+备份+演练）。
3. **🟡 JWT in localStorage** — XSS 已知，4 人可接受，P2 升级 httpOnly。
4. **🟡 8GB 内存（F4）** — 常驻余量**待实测** `memory_pressure`/`vm_stat`，保留 ≥1.5GB；不足则关后台重 App / ChromaDB 按需加载 / **不得**同时跑 Hermes 量化或本地 LLM。
5. **🟡 SQLite 并发** — WAL 4 人够；>10 人迁移 Postgres。
6. **🟢 PWA iOS 限制** — 后台同步受限，本场景无碍。
7. **🟢 成本** — 月 <¥10，但无上限，限速兜底。
8. **🟢 隧道外泄** — JWT+角色兜底，P2 可加 Cloudflare Access。

---

## 十四、REQ 追溯矩阵（功能 ↔ 技术 融合）

| PRD 功能 | REQ 组 | Blueprint | AI Agent | 状态机 | 阶段 |
|----------|--------|-----------|----------|--------|------|
| 0 账号 | AUTH-001~008 | auth_bp | — | 用户启用态 | P0/P1 |
| 1 资料章节 | MAT-001~007 | chapters_bp/materials_bp | — | 软删除(F7) | P0/P2 |
| 2 引导对话 | CHAT-001~009 | conversations_bp | TUTOR | 轮次护栏 | P0/P1/P2 |
| 3 测评 | QUIZ-001~009 | quizzes_bp/attempts_bp | QUIZZER/GRADER | draft→published→superseded；评分权 ai→teacher(覆核) | P0/P1/P2 |
| 4 进度巩固 | PROG-001~008 | progress_bp/review_sched | QUIZZER | 间隔复习 1→3→7 | P1 |
| 5 周报→班级 | RPT-001~003(迁移/改每日) / CLASS-001~006 | progress_bp/class_bp（reports_bp 废弃） | TUTOR(建议) | — | P1/P2 |
| 6 教师后台 | ADMIN-001~003 | teacher_bp | — | — | P1 |
| 部署运维 | DEP-001~010 | — | — | 备份状态 | P0/P1 |
| 数据模型 | DM-001~010 | — | — | 见 §5.3 | P0/P1 |
| 架构/横切 | ARCH-001~ | 中间件+health | — | — | P0 |
| 非功能 | NFR-001~007 | — | — | — | P1 |

---

## 十五、验收标准 DoD（融合 PRD §15 + 架构 F 发现）

**P0 阶段一**
- [ ] AUTH-001/005/006：4 账号登录，JWT 12h 有效可续
- [ ] AUTH-004 + MAT-007 + **F9**：学生看不见他人对话；学生上传接口 403；**学生 A 读学生 B → 403/空 集成测试通过**
- [ ] MAT-002/003 + CHAT-004(F5)：教师传 PDF→学生引导式对话（不直接给答案、≤12 轮、TUTOR 输出门控生效）
- [ ] QUIZ-001/008：草稿→确认两步；`draft` 不可作答
- [x] QUIZ-002/003 + **F3**：完成测评→见百分制得分；`attempts.quiz_version` 与 `attempts.score`(实际得分) 落地
- [ ] DEP-001/005/006(F1)：手机加主屏、离线启 Shell；**LaunchDaemon 开机自启（非 LaunchAgent）**
- [ ] DEP-003(F6)：production 下无 Werkzeug debugger；waitress 单进程/4 线程

**P1 阶段二**
- [x] PROG-001/004 + **F3**：进度仅本人；教师概览聚合 3 人；M 按最新 version 聚合（百分制得分率）
- [x] **QUIZ-005/009 + 百分制**：教师可选 100 分组合；AI 评分+教师覆核改分；questions.points/attempts.score 落地
- [ ] RPT-001~003：周报含统计+AI 建议
- [ ] NFR-006：单用户超额 429
- [ ] **F7**：资料删除走软删+二次确认+7 天窗口

**P2 阶段三**
- [ ] CHAT-007/009 + QUIZ-006：SSE、引用、错题本可用
- [ ] DEP-010 + **F2**：备份还原演练通过；备份前 `wal_checkpoint`

**阶段四：学习路径 & 视频课（CURR/VIDEO，v1.2.0）**
- [ ] CURR-001/002：教师可建/改/删 Session；学生 `GET /api/curriculum` 只见 published session（周→节→资料+视频）
- [ ] CURR-003：发布 Session → 其下 chapters/materials/video_resources status 同步 published，学生立即可见；取消发布回 draft
- [ ] VIDEO-001/002：教师增删改视频；学生按 Session 看 published 视频，新标签打开外链
- [ ] VIDEO-003 + CHAT-010：进 Session 提问，对话响应含 `related_videos`；`ai/video_link` 未 import `ai.rag`（RAG 纯度）
- [ ] 数据隔离：视频/路径共享，无 user_id 泄漏；学生读仅 published（draft 隐藏）

---

## 十六、风险、演进与架构再审结论

### 16.1 架构再审（architecture §十六，F1–F10 已吸收）
- 架构形态（单体/三 Agent/纯向量/SQLite+Chroma）维持不变。
- 修订集中在**部署韧性（F1/F2）** 与 **数据正确性（F3）**，不引入新组件。
- F4/F5/F7 为上线前必须落实的实现期清单。

### 16.2 演进路径（architecture §十四）
| 触发信号 | 升级项 |
|----------|--------|
| TUTOR/QUIZZER/GRADER 任 1 质量被吐槽 ≥2 次 | 补极简 Golden 集(10-20 条) |
| 资料 >50 份 / 单章 >100MB | 评估混合检索(向量+BM25) |
| Agent >5 个 | 工具注册表 + 统一路由 |
| 用户 >10 人 | SQLite→Postgres；waitress→gunicorn 2 worker |
| 用户 >50 人 | 拆 AI 独立服务 + 消息队列 |

### 16.3 ChemAI 借鉴留痕（architecture §十二，降维要点）
沿用：苏格拉底引导 + 人设、错因诊断 + 间隔复习(1→3→7)、SQLite WAL+ChromaDB、MiniLM、监理端护栏思想、Checkpoint→iCloud rsync。  
不引入：ReAct、OCR 管道、四维审核、Docker、知识图谱、多客户端、三层评测 111 场景、SSE(降 P2)。

---

## 附录 A：代码组织（architecture 附录 A 精要）
```
backend/ app.py(config+蓝图注册+静态托管) · config.py
  auth/routes.py · api/{chapters,materials,conversations,quizzes,attempts,progress,reports,teacher,health}.py
  ai/{prompts,rag,tutor,quizzer,grader,review_sched,fallback}.py
  data/{models,chroma_client,seed}.py · middleware/{rate_limit,error_handler,input_validation}.py
  scripts/{launchd_install,backup_rsync,restore_test}.sh
frontend/ index.html · manifest.webmanifest · sw.js · js/{api,auth,learn,quiz,progress,report,admin}.js · css/
```

---

> 本文档 v2.0 在 PRD v2.1 与 architecture-design.md v1.1 之上融合 Functional 与 Technical 设计：每条 REQ 绑定 Blueprint/AI Agent/数据表/状态机/部署约束，并已吸收架构再审 F1–F10（LaunchDaemon、wal_checkpoint、quiz_version、8GB 实测、TUTOR 门控、软删除、越权读 403、Evals 盲区）。待教师对架构与本文档签字后进入 P0 阶段一实现。


### 12.17a v1.17.0（2026-09-08）
- **REQ-KNOW-001/002/003 已实现**：按全章资料抽取个人知识卡片；独立卡片页支持 3D 翻转、左滑未记住/右滑记住及按钮兜底；记录学习次数和 1→3→7 间隔复习状态机。
- **PRACTICE-001 已实现覆盖强化**：全章按材料、分段多样化抽样，并在收敛题目时按 `sub_concept` 去重；知识点充足时练习题互不重复。

### 12.18 实现状态回写（v1.18.0，2026-09-08）
- **REQ-KNOW-001/002/003 已实现升级**：章节卡片在学习路径或资料发布时自动生成并共享；`knowledge_reviews` 按学生记录懒建复习状态、学习次数与 1→3→7 状态机，学生不再需要手动生成。
- **PRACTICE-001 已实现升级**：自主练习题数可选 **5-10（默认 5）**；除题干 hash 外，按当前章节过滤该学生跨会话已练 `sub_concept`，提示词和结果收敛均执行过滤。

### 12.19 实现状态回写（v1.19.0，2026-09-08）
- **REQ-KNOW-002 导航补全（学习主菜单 + 复习可退出）**：「学习」tab = 学习主菜单 hub（资料库竖排选章 + **对话/知识卡片两入口大卡**）；对话/知识卡片页均带 appbar「←」随时退回主菜单（再次点学习 tab 亦回主菜单）。复习卡组顶部返回 + 底部「**暂停退出（保存进度）**」，进度存 localStorage，再次开始复习弹「继续上次复习？」（继续/重新开始），完成自动清进度；离开学习区自动退出卡片全屏态——解决「复习中途无退出、无法回对话」缺陷。
- **NFR-006 限流结构修复（429 误伤根因）**：`rate_limit` 由「全端点共享 user_id 桶」改为「**(user_id, endpoint) 桶**」——各端点 60/天独立互不挤占；知识卡 `GET /knowledge/:chapter`（纯读）与 `POST /knowledge/:card/review`（翻卡状态机，无 LLM）摘除限流。学生正常对话/练习/翻卡不再触发「操作过于频繁」。

### 12.20 实现状态回写（v2.0.0，2026-09-08）
- **MAT 选章 = hub 可滚动多选 list（REQ-KNOW/CHAT 检索范围升级）**：学习主菜单资料库每章加圆形勾选框，列表超屏可滚，已选计数 + 全选/清空，勾选集记忆 localStorage（`aistudy_sel_chapters`）；对话页横滑选章卡撤除，选章统一在学习页。多选集驱动：① 对话 `post_message` 带 `chapter_ids` → 新 `tutor._retrieve_multi` 逐章 RAG 检索、按 chunk_id 去重合并、片段【章名】标注（防跨章资料混淆）；路径提问（askCtx）仍按 session 章节优先。② 知识卡片跨章合并：列表按章分组折叠（点章头展开网格）、「开始复习」置顶跨章复习、deck 每卡标章名；复习进度签名改 `ids`（章集），兼容旧 `{cid}`。
- **REQ-KNOW-002 翻卡交互动画**：翻转由整页 render 重建改为同一 DOM 切 `is-flipped` class → CSS 3D 过渡真正生效；touch/mouse **跟手拖拽**（横向位移+倾斜、竖向滚动不劫持），超 70px 甩出（右滑=记住了/左滑=没记住）播 `.out-r/.out-l` 飞出动画后提交，未超阈值弹性回位；按钮点击同样先飞后提交；换卡 `.kc-in` 入场动画。
- **PROG-007 掌握度口径扩展（知识卡计入 M）**：`compute_mastery` JOIN 该章 `knowledge_reviews`（status='mastered' 且 last_review_at 非空）每张按 5 分满分 × 时间衰减权重 w(last_review_at) 计入分子分母，attempts 同步累加；**仅奖不罚**——new/learning/reviewing 卡不进分母，不因未掌握卡拉低 M（示例：quiz 40% + 30 张 mastered 卡 ≈ M 76%）。进度页新增「知识卡片（计入掌握度）」块（`GET /api/knowledge/overview`）：各章已掌握/总数、学习中/未学/今日待复习、进度条 + 百分比徽章。

### 12.21 实现状态回写（v2.1.0，2026-09-08，用户 9 项真机反馈集中修复）
- **REQ-KNOW-002 甩出方向反了（bug 修复）**：拖拽判定原为 `dx<0 → reviewKnowledge(true)`，左滑被当成「记住了」向右飞出。改为 `dx > 0 → 记住了（.out-r 右飞）/ dx < 0 → 没记住（.out-l 左飞）`，touch + mouse 双路径一致，与按钮语义及 `.kc-hint` 文案对齐。
- **对话即时上屏（CHAT-002 体验修复）**：根因 = `send()` 本地 push 用户消息后 `render()` → `viewLearnChat` 重拉服务器消息（POST 尚未落库）把本地消息冲掉，须等 TUTOR 回复才整体出现。新增发送期 `_noReload` 标志：等待回复期间重绘跳过 messages 重拉；`send()` 重构为公共 `doSend(content, decorate)`。
- **REQ-KNOW 卡片 → 对话「去问 TUTOR」**：卡片列表点任意卡 → 详情 sheet（front/back + 复习状态徽章）→「去问 TUTOR」跳对话页自动提问该知识点；`post_message` 新增可选 `kc_ctx`（白名单字段 front/back/sub_concept/chapter_id，非 dict 400），`tutor_orchestrate` 注入 `TUTOR_SYSTEM.knowledge_card` 段并强制直接模式**发散详细讲解**（讲透概念 → 结合资料展开 → 例子 → 易错点 → 延伸问题，不受 ≤180 字限制）；kc 首问不因资料检索空而 fallback（卡片答案即可靠上下文）。对话页原「知识卡片」入口按钮撤除（卡片入口统一在 hub；卡片→对话为单向）。
- **PRACTICE 历史左滑删除**：`DELETE /api/practice/<session_id>`（归属校验 F9，连同 practice_questions 级联删除，其错题不再计入薄弱点依据）；前端历史条目 swipe-row 结构（swipe-main + 底层红删除钮），左滑跟手露出、超 40px 吸附、点击确认 sheet 删除；拖动结束抑制补发 click。
- **PRACTICE 题数选择放大**：原生 `<select>` 改大号 `.count-sel`（44px 高、16px 字重、大点按区）；入口卡「最多 5 题」文案与事实不符 → 「5-10 题自选」。
- **RPT-003 建议改为点击生成（一天最多一次）**：原依赖 launchd 22:00 定时脚本，线上从未生效。新增 `POST /api/progress/advice/generate`——当天已有直接返回（幂等，`generated=False`），无则按当日（UTC+8）对话/练习/测评/薄弱章生成写库（UNIQUE(user_id, advice_date) upsert）；统计与文案逻辑收敛到新模块 `ai/advice_gen.py`（`today_stats`/`build_advice_text`），`daily_advice_gen.py` 定时脚本改为调用同一函数（消灭双份口径漂移）。进度页无建议时显示「生成今日建议」按钮，有建议显示日期 +「每天最多一次」。
- **PROG-007 口径解释可视化**：进度页知识卡片块下新增可展开「掌握度怎么算？（含知识卡片口径）」：①测评/练习按得分加权；②卡片仅已掌握计入、每张 5 分满分，学习/复习/未学不罚不计；③权重按距上次复习周数减半（0.5^周）衰减、越近贡献越大；④M≥80 且作答≥2=已掌握 / 50–80 进行中 / <50 薄弱 / 无作答未评估。

### 12.22 实现状态回写（v2.1.1，2026-09-08，四项体验修复）
- **REQ-KNOW-002 翻卡首次点击修复**：拖拽结束的 `_suppressClick` 除了吞掉合成 click 外，400ms 后自动复位；成功换卡与开始/续学/重置卡组时也显式清除，因此滑动后新卡首次单击即可加上 `is-flipped` 翻转。
- **CHAT-002 对话标签与自动贴底修复**：`.pill` 固定内容宽度且禁止换行、`.pill-wrap` 纵向居中，横向溢出继续滚动；进入会话、乐观上屏思考气泡和 TUTOR 回复渲染后均在下一帧将 `.content.chat-view` 贴到最底。
- **RPT-003 近期学习上下文升级**：`advice_gen` 在同一只读查询链路内按 UTC+8 汇总近 7 天对话、练习、测评章节活动次数，计算各章掌握度状态并提取测评/练习错题知识点和最近测评日期/章节；LLM 提示与无 LLM 兜底均据此给出三条具体建议。近期已有测评时明确引用事实，不再误提示未测评。

### 12.23 实现状态回写（v2.2.0，2026-09-08）
- **CLASS-003 今日知识卡片学习张数（✅）**：`GET /api/class/leaderboard` 新增 `today_knowledge`，按 UTC+8 当日 `knowledge_reviews.last_review_at` 过滤并按 `user_id` 聚合；每张卡仅一条 review 状态行，同卡当天多次复习仍只计 1 张。学生班级页将「今日知识卡片学习张数」以 cards 图标置顶，教师班级活动将「今日知识卡片」设为首个且默认选中 chip；其余排行榜与学生端「更多排行榜」保持不变。

### 12.24 实现状态回写（v2.3.0，2026-09-12）

> **AI 层逐次调用用量记账（§7 AI 能力架构 + §11 可观测·成本，✅）**。此前「Token 账单」只能按库中消息条数推算各调用方花费（下限口径），无法精确对账。本次新增 `backend/ai/usage_log.py`（仅标准库），每次 **HTTP 成功且拿到 JSON** 的 DeepSeek 调用追加一行 JSONL 到 `~/.hermes/app-usage/aistudy.jsonl`（路径可由环境变量 `LLM_USAGE_LOG` 覆盖）；记录字段 `timestamp`(UTC+8)/`model`/`feature`/`prompt_tokens`/`prompt_cache_hit_tokens`/`completion_tokens`/`total_tokens`，与 Token 账单看板对接契约一致。
> - `agents._chat` 新增 `feature` 参数（默认 `"unknown"`），在请求实发 `model` 上、`data` 解析成功后、`return` 之前调用 `log_usage(model, data.get("usage"), feature)`；四个 Agent 包装函数分别传 `tutor`/`quizzer`/`grader`/`knowledge`（`reports.py`、`advice_gen.py`、`daily_advice_gen.py` 经 `tutor_reply` 亦归 `tutor`）。
> - **不记路径**：未配置 key / 5xx / 超时 / 异常（返回 `None`）一律不记，重试逻辑不动。
> - **故障隔离**：`log_usage` 全程 `try/except` 吞异常，写盘失败绝不影响 AI 功能；未新增任何依赖。
> - **测试隔离**：`tests/conftest.py` 新增全局 autouse fixture，将 `LLM_USAGE_LOG` 指向 `tmp_path`，避免既有测试污染真实 `~/.hermes/app-usage/aistudy.jsonl`；`tests/test_usage_log.py` 覆盖「成功记一行+字段齐全 / 四 feature 标签 / 失败不记 / 写盘失败不影响主流程」。
> - **回写锚点**：本项无专属 REQ-ID，归属 §7（AI 层调用封装）与 §11（可观测·成本）横切能力；§11 表格「成本」行已同步标注。

### 12.25 实现状态回写（v2.4.0，2026-09-18）

- **本次迭代 REQ**：`CHECKIN-001~008`（每日打卡与连胜）、`NOTIF-001~008`（通知与提醒）、`SET-001~005`（个人设置）——定义见 §3.11 / §3.12 / §3.13，域前缀已登记进 §0.2 表（`CR-2026-0918-STREAK`）。
- **状态：已实现（学生端 journey / 打卡连胜 / 通知中心 / Web Push 订阅 / 独立设置页）。** 执行方案 `DesignSpec-学生端打卡连胜与通知-执行方案.md`（仓库根目录）。
- **逐条状态**（✅ 已完成 / ⚠️ 代码已交付、真机验证待 Hermes 执行）：

| 域 | 状态 | 说明 |
|---|---|---|
| CHECKIN-001~008 | ✅ | 服务端唯一判定 + 幂等（`daily_checkins UNIQUE`）+ 今日卡组/练习自动装配 + 顶部连胜条 + 班级今日打卡 |
| NOTIF-001/003/004/006/007/008 | ✅ | 通知中心（列表/未读/已读/跳转）、发布路径/测评通知、nudge 限流、streak_done 即时通知、铃铛未读角标 |
| NOTIF-002 | ⚠️ | Web Push（VAPID）订阅/推送/降级/404-410 删订阅已实现；真机 push 授权需 Ray 配合点授权 |
| NOTIF-005 | ⚠️ | `checkin_reminder.py` + 文案池 + 萌图 + plist 已交付；LaunchAgent 已安装（2026-09-19）；**收件人口径经 v2.4.1 修正，见 §12.26**。真机 19:00 触发需 Ray 配合 |
| SET-001~004 | ✅ | 独立设置页、改名（1–20 字）、预设头像（a1..a12 白名单）、复用改密端点 |
| SET-005 | ⚠️ | Web Push 授权/订阅开关已实现；真机授权需 Ray 配合验证 |

- **实测证据**：
  - `python -m py_compile` 通过；`node --check backend/frontend/js/{api,app,student,teacher}.js backend/frontend/sw.js` 通过；`make lint test smoke` 全绿（`make all` exit=0，`102 passed`，smoke `/health` 返回 `version:2.4.0`，端口 5002 已释放）。
  - `tests/test_checkin.py`：9 张卡不算 / 10 张算、4 题不算 / 5 题算、同卡重复只计 1、跨 UTC+8 日界、连胜连续 +1、断连归零、`state=pending` 存活、幂等（1 行 `daily_checkins` + 1 条 `streak_done` 通知）。
  - `tests/test_notify.py`：通知落库 + 未读 + 已读、nudge 同日同对限流 400、发布 session/quiz 后每生各 1 条、push 发送抛错仍落库且 HTTP 200（降级）。
  - `PATCH /api/auth/me` 改名/换头像生效，非法头像/空名返回 400。
- **版本一致性**：`backend/app.py version == 2.4.0`；`CHANGELOG.md` 新增 2.4.0 条目；`sw.js` CACHE bump `v42 → v43`；`requirements.txt` 登记 `pywebpush>=2.0`。
- **验收基建修复（Hermes，2026-09-18，不涉业务代码）**：`tests/conftest.py` 新增 autouse fixture `_no_real_llm`（全局清空 `DEEPSEEK_API_KEY`）+ `client` fixture 内补 `app.config["DEEPSEEK_API_KEY"] = ""`。根因：`config.py` 的 key 是**模块首次 import 时**绑定的类属性，验收脚本 `set -a; source .env` 后再跑 pytest，收集阶段 `import ai/*` 已让 config 记下真 key；而 `agents._config()` 在应用上下文里优先读 `current_app.config`，`monkeypatch.setenv` 盖不住 → 单测**真去打 DeepSeek**，`test_advice_uses_recent_quiz_chapter_mastery_and_wrong_concept` 与 `test_essay_three_tiers` 随模型措辞随机失败（该不确定性在 v2.3.0 之前已存在，非 v2.4.0 引入）。修后 `make lint test smoke` exit=0，`make test` 连跑 3 轮均 exit=0。
- **范围边界（未越界）**：只做学生端 journey/打卡/通知；教师端**仅复用**设置页与通知中心（共享 `appbar`/`viewSettings`/`viewNotifications`），教师端业务逻辑未动；未碰「按章节浏览卡片 / 自主练习 / 测评」既有逻辑。
- **诚实清单（未做）**：真机 Web Push 授权与推送、19:00 LaunchAgent 安装与真机触发（均需 Hermes/Ray 配合）；补签卡 / 连胜道具 / 自定义头像上传 / 教师端打卡报表（YAGNI，见 §9 登记）。

### 12.26 实现状态回写（v2.4.1，2026-09-19，NOTIF-005 收件人口径修复）

- **REQ 归属**：`NOTIF-005`（每日 19:00 未打卡连胜提醒）。本次为**缺陷修复**，REQ 定义本身不变，仅修正实现口径。
- **缺陷**：v2.4.0 按执行方案 §2.6 把 19:00 提醒的收件人钉为 `notification_prefs.push_enabled = 1 AND remind_1900 = 1`。但 `push_enabled` 语义是**浏览器推送订阅开关**且默认 `0`（须学生先进设置页点「打开提醒」才会写 1），而 `notification_prefs` 行是懒创建的（无记录时无行）→ **两个条件叠加导致该提醒实际发不出任何人**，站内通道被推送开关连坐。手动试跑 `[checkin_reminder] sent=0` 即为此症状（当时确无 prefs 行，掩盖了问题）。
- **修复**：`backend/scripts/checkin_reminder.py` 抽出 `eligible_students(con)`，改为 `LEFT JOIN notification_prefs` + `COALESCE(np.remind_1900, 1) = 1`。**口径**：站内提醒默认发给全体在用学生（排除测试号 `EXCLUDED_USERNAMES`、排除当日已达标者、排除显式关掉 `remind_1900` 的人）；**Web Push 仍只投递给已存在订阅行的学生**（订阅行存在本身即代表其点过「打开提醒」），双通道职责解耦。
- **新增测试**：`tests/test_checkin_reminder.py`（importlib 按路径加载脚本，不污染 `scripts/` 包结构）4 项——① 收件人口径（无 prefs 行默认可收 / `remind_1900=0` 排除 / 已达标排除 / 测试号排除）；② 三条俏皮文案与萌图映射齐全；③ 端到端重跑幂等（同日不重复落库）。`pytest -q --no-cov tests/test_checkin_reminder.py` → **4 passed**。
- **版本一致性**：`backend/app.py version == 2.4.1`；`CHANGELOG.md` 新增 `## [2.4.1] - 2026-09-19`；`sw.js` CACHE 保持 `v43`（无前端改动，不需 bump）。
- **范围边界**：仅动提醒脚本收件人查询 + 补测试 + CHANGELOG + 版本号，未触碰打卡判定、通知中心、Web Push 发送链路。

### 12.27 实现状态回写（v2.5.0，2026-09-19）

- **本次迭代 REQ**：`CHECKIN-009`（未学习口径 + 未学优先）、`CHECKIN-010`（三档兜底永不空）、`CHECKIN-011`（超额学习）、`CHECKIN-012`（真空引导）——定义见 §3.11（Functional + Technical 两处）。
- **状态：已实现。** 执行方案 `DesignSpec-学生端卡组兜底与超额学习-执行方案.md`（仓库根目录）。
- **逐条状态**（✅ 已完成）：

| REQ | 状态 | 说明 |
|---|---|---|
| CHECKIN-009 | ✅ | 「未学习」改为 `learn_count=0`；今日任务优先发未学卡（`chapters.folder, order_no, name, kc.rowid` 课程顺序） |
| CHECKIN-010 | ✅ | 三档装配 ①未学 → ②到期复习 → ③低掌握随机补足；只要存在已发布卡则 `cards` 必非空 |
| CHECKIN-011 | ✅ | 任务行达标后「再学一组」（可点）→ `?mode=extra` 卡组，排除今日已复习，进度 key 隔离 |
| CHECKIN-012 | ✅ | 接口返回 `empty_reason`；真真空前端给「去资料库」可点出路 |
| CHECKIN-013 | ✅ | `chapter_ids` 贯通今日卡组与练习；范围外无卡不回落；hub 资料库下移 + 折叠下拉多选 |

- **缺陷定位（触发本迭代，Hermes 已实测复现，2026-09-19，只读诊断）**：
  - 真实库中 `hermesstu` 已学满 64 张卡（43 `mastered` + 21 `reviewing`，`next_review_at=2026-09-21` 未到期）→ 旧 `build_today_deck` 返回 **0 张**、`short=True` → 前端直接 `toast('今天没有可复习的卡片')` 并 `return`，**无任何出路**。
  - 同库 `Qingran`（`learning`:4 + `new`:60）、`Winnie`（`new`:64）的 60/64 张 `new` 行 **`learn_count` 全为 0** —— 是 `GET /api/knowledge/<chapter_id>` 浏览章节时 `_review()` **全量懒建**出来的，学生从未真正翻过，却既不算「新卡」又被算作「到期」→ 任务永远发旧卡、推不动新课。

- **实现改动**：
  1. `backend/data/checkin.py::build_today_deck(con, user_id, limit=None, mode="task", rng=None)` —— 三档装配 + `mode`（白名单回落）+ `rng`（测试注入固定 seed）+ `empty_reason` + 每卡带 `learn_count`；`mode="extra"` 排除今日已复习、`short` 恒 False、返回 `extra: True`。档① 未学卡按 **`chapters.folder, chapters.order_no, chapters.name, kc.rowid` 课程顺序**排序（`LEFT JOIN chapters`）。
  2. `backend/api/knowledge.py::today_deck` —— 接受 `?mode=task|extra`，非法值回落 `task`，不返回 4xx；`GET /api/checkin/today` 内 `task.cards` 仍为 `mode="task"` 口径不变。
  3. `backend/frontend/js/student.js` —— `taskCardHtml()` 给 `task()` 加 `afterDone` 参数，「复习卡片」行达标后变可点「再学一组」；`startTodayDeck()` 空卡组按 `empty_reason` 给「去资料库」出路；新增 `startExtraDeck()`；`_kcTodayKey()` 加 `_extra` 后缀隔离额外组进度，任务组续学不受影响。
  4. `tests/test_checkin.py` —— 增 8 项卡组装配用例（见下），既有用例不回归。

- **实测证据**：
  - `python -m py_compile` 通过；`node --check backend/frontend/js/student.js` 通过；`make lint test smoke` exit=0（`set -a; source .env; set +a`），`114 passed`，覆盖率 ≥50%，smoke `/health` 返回 `version:2.5.0`，端口 5002 已释放。
  - 新增用例：`test_deck_three_tier_priority`（三档优先级）、`test_deck_unlearned_means_learn_count_zero`（未学习口径）、`test_deck_mastered_still_fills`（全 mastered 仍发满 10 张——用户 bug 回归）、`test_deck_same_seed_deterministic`（同 seed 一致）、`test_deck_low_mastery_priority`（低掌握度优先）、`test_deck_extra_excludes_today_reviewed`（extra 排除今日已复习）、`test_deck_empty_reason_no_published_cards`（真真空 empty_reason）、`test_deck_order_follows_course_order`（档① 课程顺序，见下）。
- **修正记录（2026-09-19，同 commit）**：档① 初版按 `kc.chapter_id, kc.rowid` 排序，但 `chapters.id` 是 **UUID**，字典序与课程顺序无关。Hermes 真机核对发现 Han/Qingran/Winnie 首组 10 张卡**全部来自「第1周·第2节 · AI 产品地图」**（第2节 id `2f757690-…` 字典序 < 第1节 id `d6213d0c-…`），课程顺序倒置。修正为按 `chapters.folder, order_no, name, kc.rowid` 排序，并补回归单测 `test_deck_order_follows_course_order`（id 字典序与 `order_no` 相反时仍先发 `order_no` 小的章）。
- **修正记录 2（2026-09-19，超额学习进度显示）**：超额学习放开后 `progress.cards` 会 >10。Hermes 线上实测（真实账号 `hermesstu`，`GET /api/checkin/today`）返回 `progress={"cards":19,"questions":5}`、`done=true`。任务卡 `student.js:127-128` 已夹取（显示 10/10 正确），但连胜条 `app.js:120`（`streak-cap`）与班级页 `student.js:1239`（`st`）未夹取，会直接渲染「19/10 卡」。修正：两处显示一律 `Math.min(..., 10/5)`；服务端 `progress` 口径**不改**（打卡判定要真实 distinct 数，超额学习必须继续计入），只夹显示。
- **版本一致性**：`backend/app.py version == 2.5.0`（**保持不变**，该版本尚未发布）；`CHANGELOG.md` 在 `## [2.5.0]` 条目内补「档① 按课程顺序」「进度显示夹取」说明；`sw.js` CACHE bump `v44 → v45`（本次有前端 JS 改动）；`requirements.txt` 无新增依赖（符合边界）。
- **范围边界（未越界）**：未改 `GET /api/knowledge/<chapter_id>` 的懒建行行为（KNOW 域既有设计，仅在判定口径上绕过）；未改打卡判定 `counts_today` / `evaluate_and_maybe_complete` 与阈值常量；未改服务端 `progress` 口径；未动教师端；未新增依赖。
- **诚实清单（未做）**：真机验证（线上 5003 重启 + Ray 真机复测 `hermesstu` 卡死场景）由 Hermes 执行；补签卡 / 连胜道具 / 卡组配比学生自定义（YAGNI，见 §9 登记）。

### 12.28 实现状态回写（v2.5.1，2026-09-19，知识卡片考点覆盖整改）

- **本次迭代 REQ**：`KNOW-004`（卡片应试级细粒度 + 全章覆盖 + 切片绑定）——定义见 §3.4.2（Functional + Technical 两处）。变更请求号 `CR-2026-0919-CARDS`。
- **状态：已实现。** 触发原因：用户实报「随堂测试与作业考题里的大量考点、细节知识点现有卡片完全没覆盖；卡片偏笼统、撑不起做题」，要求全章节卡片（含往期）统一翻新。

**根因（三条，均经只读诊断确认）**

| # | 根因 | 证据 | 修法 |
|---|---|---|---|
| 1 | **输入被物理截断**：生成时抽 ~18 个切片、每片截 300 字、总长砍到 6000 字 | W1S2 有 96 切片 → 模型只看到约 1/5 | `_chapter_text()` 按资料分层投喂**全章每片**（每片 ≤600 字、每份保底 1200 字、预算 `CONTENT_BUDGET=20000`） |
| 2 | **提示词只要求「遍布全章」**，未要求细粒度 | 产出多为「主要包含以下几方面」式框架卡 | `KNOWLEDGE_SYSTEM` 改为应试级硬约束：一个考点一张卡、禁止概括、数字/顺序/阈值/年份必须单列、`MIN_CARDS=40` |
| 3 | **教案（`课件.md`）从未入库** → RAG 与卡片都检索不到「课上有讲」原文 | W1S1/W1S2 的 `课件.md` 未作为 material 存在 | `inject_curriculum.py` 补挂教案为 material + 重算切片 |

**新发现（施工中发现，非用户报障）**
1. **图片型 PDF/PPTX 文本层几乎为空**：《40、大模型应用PM vs 传统PM.pdf》12.6MB 只抽出 1760 字、22.5MB 的 pptx 只得 1095 字（幻灯片是图片）→ 新增 `scripts/ocr.swift`（macOS Vision OCR，PDF 逐页 3 倍渲染、PPTX 按 rels 顺序取内嵌图）+ `scripts/ocr_materials.py`（缓存 `材料/_ocr/*.ocr.txt`，原生文本 ≥4000 字跳过）+ `inject_curriculum.py --rechunk` 按 `best_text` 重算。10 份素材补 4.9 万字，**全库切片 152 → 483 条**。
2. **教案被当成一个整片组**：定长切片里小标题几乎不落切片开头，导致整份教案只出 16 张卡就被上限截断——**最重要的教案反而覆盖最差**。修法：`split_lesson()` 拼全文按 `#` 标题定小节区间再取相交切片，69 个教案小节逐一成组。
3. **共用术语表跨章错配**：`行业黑话大全.md` 是全课程共用，模型把「毛利率/护城河/K因子/WAU」等其它周次词条做成了 W1S1 卡片。修法：**仅对共用素材**启用相关性强护栏（`SHARED_MATERIALS`），专属资料改为「必须穷尽抽取」——护栏若滥用反而会把本课真题考点（人形机器人量产元年、AI 医疗融资 37 亿）误判为外章丢弃（实测 W1S2 覆盖率一度 16/36，修正后回升）。
4. **补漏卡绑错切片**：`fill_gaps` 用关键词 `LIKE` 取首条命中，「AI」「工具」等泛词会把卡片绑到无关切片（「智能编程」卡被绑到「行业黑话」表）。修法：新增 `_bind_by_content()`，按**卡片正面+背面**与切片正文的词元重合度取最吻合者（`--rebind-recent`）。

**审计工具自身的三个坑（同一轮修掉，否则报告会骗人）**
1. 候选卡只按**正面**匹配 → 大量假阴性（「插件」写在「智能体」卡的**背面**却被判未覆盖）→ 改为正反两面按词元重合度预筛，并把答案要点一并给模型。
2. 把**流程性小节**（学习目标 / 前置与衔接 / 动手任务 / 备课参考材料 / 常见误区 / 答疑 / 视频课对应）当考点 → 结构性误报 → `META_HEAD` 剔除。
3. 把整章 200~360 张卡一次性丢给模型 → 它扫不完、漏判明摆着的匹配（「政府工作报告」考点被人形机器人卡覆盖却判未覆盖）→ 改为按词元预筛 ≤40 张候选卡配对呈现。

**产出（本地库，不入 git）**

| 章节 | 切片 | 卡片（重做前 → 后） | sub_concept | 绑定切片 | 状态 |
|---|---|---|---|---|---|
| 第1周·第1节 大模型是什么 | 106 | 34 → **208** | 117 | 208/208 | published |
| 第1周·第2节 AI 产品地图 | 114 | 30 → **279** | 100 | 279/279 | published |
| 第2周·第1节 AIPM vs 传统 PM | 139 | 0 → **359** | 179 | 359/359 | draft（待发布） |
| 第2周·第2节 真实落地案例 | 124 | 0 → **254** | 140 | 254/254 | draft（待发布） |
| **合计** | **483** | **64 → 1100** | — | **1100/1100** | — |

- **上架**：W2S1/W2S2 共 2 章节 + 13 份资料 + 3 条视频链接入库（`status='draft'`，学生不可见）；W1S1/W1S2 补挂 `课件.md`。源文件**不复制**进 `uploads/`，material 记 `source_path` 绝对路径 + 下载代理（方案 B）。
- **结构审计**：`scripts/audit_alignment.py` → **✓ 未发现结构性问题**（章节↔资料↔切片↔卡片一一对应；0 张卡未绑切片、0 张跨章错配、素材源文件均可下载）。
- **考点覆盖审计**：`audit_alignment.py --llm --save-report` → 配 `rebuild_cards.py --fill-gaps` 两轮补漏（共补 13 张）。**补漏提示词写死「原文检索不到依据就不出卡」**（宁报缺口也不编造）。终审 **51/55 = 93%**，其中 W2S1 **11/11**、W2S2 **2/2** 已达 100%；剩余 4 条经关键词回检确认**课件原文中根本没有出处**，判定为**题库超纲**而非卡片缺失，交教研处理：`学习使用AI时重点应放在？`、`以下关于AI能力的认识最符合资料观点的是？`、`AI4S 产业链上游环节的核心定位`、`巩固练习/间隔复习的主要作用`（仅出现在 W7S2/W8S1 课件，W1S2 素材无此内容）。
- **实测证据**：`py_compile` 通过；`ruff check backend/` All checks passed；`make smoke` → `{"version":"2.5.1","status":"up"}`；`pytest -q` 全绿，覆盖率 **76.3%**（门槛 50%）。
- **版本一致性**：`backend/app.py version == 2.5.1` == `CHANGELOG.md` 最新条目；前端与 `sw.js` CACHE **无改动**（本次纯后端 + 脚本），保持 `aistudy-shell-v45`。
- **范围边界（未越界）**：未改学习路径/打卡/通知/测评任何既有逻辑；未改前端；未新增运行时依赖（OCR 走 macOS 自带 Swift/Vision，脚本仅在本地跑）；`backups/`（含学生数据）已加 `.gitignore`。
- **诚实清单（未做）**：W2S1/W2S2 发布动作留给用户在教师端确认（本次只到 `draft`）；「题库超纲」的 4~5 道题未擅自改写或删除（属教研决策）；卡片质量抽样人工复核仍建议由 Ray 抽看。

### 12.29 实现状态回写（v2.6.0，2026-09-19，无卡切片补卡 + 教师端卡片核查页）

- **本次迭代 REQ**：`KNOW-004`⑤（**反向覆盖**：每条切片都必须被卡片引用）+ `KNOW-005`（教师端知识卡片核查）。变更请求号 `CR-2026-0919-CARDS2`。
- **状态：已实现。** 触发原因：用户要求「先做 C（补 339 条无卡切片），再做 B（教师端可逐章查卡），最后做 A（发布 W2S1/W2S2）」。

**C — 无卡切片补卡（`scripts/rebuild_cards.py --fill-orphans`）**

| 轮次 | 触发原因 | 待补切片 | 补卡 |
|---|---|---|---|
| 1 | 首版噪声过滤 | 282 | +1064 |
| 2 | 修「水印整条丢弃」误杀 | 51（W2S1 50 + W1S1 1） | +198 |
| 3 | 修「表格分隔行触发重复检测」误杀 | 6 | +22 |
| **合计** | | | **+1284 → 全场 2384 张** |

- **为什么必须做**：卡片按「片组」生成、`source_chunk_id` 是单值、绑片按重合度取最吻合的一条 → 一个片组只有 1–2 条切片「中签」。实测 483 条切片里 **339 条无卡**，抽样确认其中确有实质考点（术语对照表、价格阶梯表、厂商底模对比、检索流程、公式、代码片段）。
- **绑定策略**：`1 切片 = 1 次调用`，卡片直接绑定该切片 —— **由构造保证精确**，不做事后反查（对比 `fill_gaps` + `--rebind-recent` 的「按重合度找片」）。
- **噪声过滤两次自我纠错（本轮最重要教训）**：
  1. **水印必须按词删，不能按切片删**：旧规则「文本含 `教学监督邮箱：feedback@…` 即整条丢弃」误杀 50 条「水印+真考点」混排切片（「从优化工具效率转向重构创作模式」「移动互联网的逻辑陷阱」）。改为 `_clean()` 清洗后再判。
  2. **表格分隔行不是内容**：12 字片段出现 ≥4 次即判噪声的规则被 Markdown 表格分隔行触发，把「AI 编程工具四家对比表」「技术概念清单表」「Redis 会话代码」整条丢掉——**那正是最典型的细碎考点**。改为先按行删分隔行/框线行（保留数据行），重复阈值收紧到 ≥6 次（否则 `current_state.` 这类变量名重复 4 次也会误判）。
- **代码**：`_clean()` / `_boiler()` / `_max_repeat()` / `orphan_chunks()` / `gen_for_orphan()` / `fill_orphans()`；CLI `--fill-orphans [chapter_id前缀] [--limit N] [--dry-run]`。

**B — 教师端知识卡片核查页**

- 后端 `backend/api/teacher.py`：`knowledge_summary()` + `knowledge_chapter()`（详见 §3.4.2 Technical）。只读；学生 403；未知章节 404。
- 前端 `teacher.js`：`viewKnowledge()` / `openKcards()` / `toggleKgroup(i)` / `showKcard(id)` / `backToKcardList()`；`render()` 增 `knowledge` 分支；`app.js` tabbar 在 `knowledge` 视图高亮「课程」。
- 设计取舍：**不新增第 6 个 tab**（教师端已有 5 个 tab，再加会挤），改为从「课程」页各 Session 的关联章节钻进去；列表**默认折叠**、点主题展开、点卡弹窗——符合「钻取式 + 纵向折叠 + 无横滑」的既定 UI 基线。

**产出（本地库，不入 git）**

| 章节 | 切片 | 有卡切片 | 卡片（本轮前 → 后） | sub_concept | 绑定 | 状态 |
|---|---|---|---|---|---|---|
| 第1周·第1节 大模型是什么 | 106 | 106 | 208 → **437** | 247 | 437/437 | published |
| 第1周·第2节 AI 产品地图 | 114 | 114 | 279 → **625** | 235 | 625/625 | published |
| 第2周·第1节 AIPM vs 传统 PM | 139 | 138 | 359 → **733** | 375 | 733/733 | published（v2.6.0 随 A） |
| 第2周·第2节 真实落地案例 | 124 | 124 | 254 → **589** | 282 | 589/589 | published（v2.6.0 随 A） |
| **合计** | **483** | **482** | **1100 → 2384** | **1139** | **2384/2384** | — |

- **唯一未覆盖切片**：OCR 纯噪声 `oai.cn • • •`（清洗后 30 字），结构上不构成考点。
- **结构审计**：`audit_alignment.py` → **✓ 未发现结构性问题**；悬空绑定 0、未绑切片 0。
- **实测证据**：`ruff check backend/` 通过；`tests/test_teacher.py` 3 项通过；`pytest -q` 全绿（覆盖率见 §12.28 口径）；`make smoke` → `{"version":"2.6.0","status":"up"}`。
- **版本一致性**：`backend/app.py version == 2.6.0` == `CHANGELOG.md` 最新条目；前端有改动 → `sw.js` CACHE **v45 → v46**。
- **范围边界（未越界）**：未改学生端卡片/对话/练习/打卡/测评任何逻辑；教师端新增仅只读；未新增运行时依赖（OCR 走 macOS 自带 Swift/Vision，仅本地跑）。
- **诚实清单（未做）**：① 「题库超纲」的 4 条仍待教研决策；② 卡片总量 1100 → 2384 是**抽样式增长**，质量仍需人工抽样（教师端核查页 v2.6.0 起可直接在后台抽查，不必再查库）；③ 补卡后**未重跑 LLM 考点覆盖审计**（`--llm` 会再花一轮 LLM 调用），覆盖结论仍以 §12.28 的 51/55 为准——若要刷新需另跑一次。

### 12.30 实现状态回写（v2.6.1，2026-09-19，卡片↔切片绑定精度修复）

- **本次迭代 REQ**：`KNOW-005`⑤（新增：绑定必须精确到「同资料内最吻合的那一条切片」）。变更请求号 `CR-2026-0919-BIND`。
- **状态：已实现。** 触发原因：v2.6.0 教师端核查页上线后，人工抽查点开「什么是 MCP（Model Context Protocol）？由谁在何时提出？」那张卡，弹窗里展示的**来源切片原文却是 Agentic RAG 段落** —— 顺着查下去发现绑定错位是**全库级**问题，而此前所有审计（结构审计 / 覆盖率审计 / LLM 考点审计）**都没有任何一项能发现它**（因为卡片有绑定、切片有卡、资料对得上，只是「绑错了同资料里的哪一条」）。

**问题量化（新增 `scripts/audit_binding.py`，纯本地 BM25、零 LLM 成本）**

在同**一份资料**的切片池内，给「该卡实际绑定的切片」按与卡片正文的 BM25 相似度排名：

| 排名 | 卡片数 | 含义 |
|---|---|---|
| 第 1 名 | 1456 | 绑对了（同资料内最吻合） |
| 第 2–3 名 | 358 | 近似可接受 |
| **第 4 名及以后** | **570** | **绑错，其中一批与卡片零词面重合** |
| **精确率** | **61.1%** | 1456 / 2384 |
| 回绑后 | **84.9%** | 第 4 名以后 **570 → 2** |

**典型错例**：① 「什么是 MCP…」→ 绑到同资料讲 Agentic RAG 的切片（MCP 原文在相邻切片）；② 「Nova Premier 的核心优势是什么？」「GPT-5.4 的核心优势与关键评测成绩是什么？」→ 绑到文档标题切片（`# 国内外大模型现状总结归纳分析（最终版）`），真正内容在后面的表格切片；③ 「Veo 3.1 / Kling 3.0 的厂商、核心能力与发布时间」→ 绑到上一张表格的尾部切片。

**根因（三条路径，只有第一条是精确的）**
1. **按构造绑定**（逐片生成时直接写入 `source_chunk_id`）→ 精确，v2.6.0 的 `--fill-orphans` 走的就是这条。
2. **按内容重合度事后回绑**（`fill_gaps` + `--rebind-recent`）→ 会错，重合度只保证「同资料」，不保证「同一条切片」。
3. **教案「片组」路径**：一个片组跨多条切片，卡片默认绑到**片组首片** → 组内跨片时必然错位（错例 ② 的首片就是文档标题）。

**修法（保守、可回滚）**
- `scripts/audit_binding.py --rebind`：仅当「同资料内排名 > 3 **且** 最佳切片 BM25 得分 ≥ 绑定切片的 1.35 倍」才改绑，**只改 `source_chunk_id`，不动卡片文字**，**只在同一份资料内改绑**（绝不跨资料，避免把「资料级错配」换成更隐蔽的「切片级错配」）。实测改绑 568 张。
- **防复发**：`rebuild_cards.py` 在三条生成路径（全量重做 / `--fill-gaps` / `--fill-orphans`）之后**自动调用回绑**，`--no-rebind` 才能关（默认开）。以后再上架新课件，绑定精度不再依赖人工抽查运气。
- `--top N` 打印最差卡片（现绑 vs 更佳切片对照），`--report x.json` 落盘明细，便于人工复核。

**实测证据**
- 回绑后重算：精确率 **84.9%**（第 1 名 2024 / 第 2–3 名 358 / 第 4 名及以后 **2**）；MCP 那张卡已改绑到 `chunk_idx 17`（含 `Anthropic在2024年底提出的开放标准协议…"AI的USB接口"` 原文）。
- `audit_alignment.py` → **✓ 未发现结构性问题**；悬空绑定 0、未绑切片 0（回绑不改变覆盖关系，只改指向）。
- `ruff check backend/` 通过；`pytest -q` 全绿；`make smoke` → `{"version":"2.6.1","status":"up"}`。
- 备份：`backups/2026-09-19-cards/aistudy.sqlite3.pre-rebind.bak`（回绑前库态）、`bind-audit-before.json` / `bind-audit-after.json`（审计明细）。

**版本一致性**：`backend/app.py version == 2.6.1` == `CHANGELOG.md` 最新条目；**前端无改动 → `sw.js` CACHE 保持 v46**。
**范围边界（未越界）**：未改任何卡片文字、未改提示词、未改前端、未动学生端逻辑；新增脚本为本地工具，不进运行时依赖。
**诚实清单（仍待办）**：① 剩 358 张排名 2–3 的卡片属「近似」，未强改（强改会引入噪声，且部分为近义切片，两者都算对）；② 2 张排名 > 3 的卡片未满足 1.35 倍阈值（同资料内无更优切片），需人工判断。

### 12.31 考点覆盖审计复跑（2384 张卡库态，2026-09-19）

发布 W2S1/W2S2 后，用**新的库态**重跑 `scripts/audit_alignment.py --llm`（上次跑是 1100 张卡时代）：

| 章节 | 上次（1100 张卡） | 本次（2384 张卡） |
|---|---|---|
| 第1周·第1节 | — | 20/21 |
| 第1周·第2节 | — | 19/21 |
| 第2周·第1节 | — | **11/11** |
| 第2周·第2节 | — | **2/2** |
| **合计** | 51/55 | **52/55（94.5%）** |

**对 3 条「疑似未覆盖」逐条人工核验（不惜工本地查库比对，因为「报缺口」比「假报覆盖」安全，但假报缺口会误导教研）**：
1. 【W1S2 随堂题】AI4S 产业链中，上游环节的核心定位是什么？ → **审计误判（假阴性）**。库中已有卡「AI4S产业链的三层结构分别是什么，各层定位与价值特征如何？」，答案就是「**上游（定格局）：算力基础设施，确定性最高**」，且已绑定源切片（`AI大模型时代机会 (1).pdf` #7，原文含「上游（定格局）：算力基础设施→确定性最高」）。原因是审计的候选预筛（≤40 张）把这张卡筛掉了。
2. 【W1S1 随堂题】以下关于 AI 能力的认识，最符合资料观点的是？ → **审计误判（假阴性）**。W1S1 已有「AI 能做什么」「AI能力」「AI 幻觉」「能力边界」类卡片（幻觉 26 张 / 边界 7 张），该题为宽口径综合题，无法由单张卡「唯一命中」。
3. 【W1S2 随堂题】巩固练习 / 间隔复习的主要作用是？ → **真·无依据，不补**。全库 483 条切片中**没有任何一条**含「巩固练习」或「间隔复习」（已用 SQL 全库检索确认）——该题考的是**学习方法**（记忆规律/复习机制），**不是课件内容**。按 KNOW-004 的「原文找不到依据就不出卡」硬约束**不生成卡片**，列入教研决策：确认题目出处，或从题库移除。

**结论**：**真实覆盖 54/55**（3 条告警中 2 条为审计假阴性，1 条超出课件范围）。审计的 `--llm` 判定是「疑似」而非判定，**报缺口必须人工复核**，否则会把已覆盖的考点重复补卡（反而制造重复卡片）。


### 12.32 实现状态回写（v2.6.2，2026-09-19，卡片长答案卡高自适应 + 「去提问」直达对话并选中课题）

- **本次迭代 REQ**：`KNOW-002`（追加：卡高随内容自适应，REQ-KNOW-CARDFIT-001）、`CHAT-002`（追加：从卡片/课程页进入时自动选中对应课题，REQ-CHAT-SCOPE-002）。变更请求号 `CR-2026-0919-CARDFIT`。
- **状态：已实现。** 触发原因：使用者复习时反馈两条学生端缺陷 —— ① **卡片翻到背面、字数多的时候卡片 size 不调节**（答案溢出卡框，后半段看不到）；② **「去提问」按钮没有直接进入对话页面、也没有选中相关课题**。

**根因（两条都是「结构性」而非「样式参数」问题）**

| # | 症状 | 根因 | 位置 |
|---|---|---|---|
| ① | 长答案被裁切 | 卡面是 `position:absolute; inset:0` 的 3D 翻转结构，卡高**只由 CSS `min-height:320px` 决定、不随内容走**；本库单卡答案实测最长 **522 字 = 内容高 709px**，远超 320px 卡框 | `css/style.css` `.kc-face` / `.kc-card` |
| ② | 点了不进对话页 | `askSession()` 只设 `App.state.hash`，**没设 `learnChat`** → `render()` 按子视图分发时落回**学习主页**；同时 `selChapters`（资料范围）沿用旧勾选 | `js/student.js` `askSession()` |
| ②' | 进了对话页但范围不对 | `askKcTutor()` 设了 `activeChapter` 却未把该章放进 `selChapters`，`viewLearnChat()` 的兜底逻辑（`sel.indexOf(activeChapter) < 0` → 取 `sel[0]`）把范围**覆盖回旧选集首章** | `js/student.js` `askKcTutor()` + `viewLearnChat()` |

**修法**

1. `Student.kcFit()`（新增）：翻转 / 换卡 / 窗口尺寸变化时，按当前卡面**实测内容高**设卡高 —— 下限 320px、上限取**「卡顶 → 底部 tabbar 上沿」的真实可用高**（大屏兜底 620px）；`.kc-face` 加 `overflow-y:auto`，超上限部分在**卡面内滚动**而非被切掉。上限按**布局坐标**（视口坐标 + 当前滚动量）计算，不随「用户滚到哪」漂移；`.kc-card` transition 补 `height .3s ease`，拉伸与翻转同步播放。测量前先清内联高度**落回 `min-height`**，否则量到的是被旧卡高撑大的值。
2. 卡背安全居中：`.kc-back` 改 `justify-content:flex-start` + 首尾子元素 `margin:auto` —— 短答案仍视觉居中，长答案从顶部开始（flex 居中 + overflow 会把顶部内容顶出可视区且滚不到，是同一类 bug 的第二个坑）。
3. `render()` 尾加钩子：知识卡片全屏态下新卡入场后 `requestAnimationFrame(() => Student.kcFit())`（换卡后无需用户再点一次才自适应）。
4. `askSession()`：显式置 `learnChat = true` + 清卡片/详情子视图态 + 走 `go("learn")` 正规路由；`selChapters` 置为该 Session 的 `chapter_ids` 并落 localStorage → scope-bar 立即显示该节范围。`askKcTutor()` 同修（`selChapters = [card.chapter_id]`）。

4. **静态资源版本号穿透 CDN 缓存（本次新发现 + 新规则）**：Cloudflare 对 `/js/*.js`、`/css/*.css` 强制 `cache-control: max-age=14400`（4h）**并覆盖源站 Cache-Control**，且 Service Worker 的 network-first 也走这层 HTTP 缓存 —— 结果是「前端上线了但用户 4 小时内还在跑旧 JS」，`sw.js` CACHE bump 无效。修法：`index.html` 的 css/js 与 SW 注册 URL 加 `?v=<版本号>`，`sw.js` 预缓存 ASSETS 同版本。**新规则：每次前端改动必须同步改 `index.html` 的 `?v=` 与 `sw.js` 的 CACHE 名**（已写进 index.html 顶部注释）。

**版本一致性**：`backend/app.py version = "2.6.2"` == CHANGELOG 最新条目 == `index.html` 的 `?v=`；前端有改动 → `sw.js` CACHE `aistudy-shell-v46 → v47`（强制旧缓存失效）。

**范围边界与诚实清单**
- 只改前端三文件（`css/style.css`、`js/student.js`、`js/app.js`），**未动任何接口、未动卡片数据、未重新生成卡片**；卡高上限 620px 是经验值，超长答案（>620px）改为卡面内滚动而非继续拉高页面。
- 验收方式（已实测，非推断）：本地 `127.0.0.1:5003` + 公网 `/health` 均 `2.6.2`；线上 `index.html` 带 `?v=2.6.2`、`/js/student.js?v=2.6.2` 含新代码；学生端真实 DOM 驱动 —— ① 522 字卡翻面后卡高 320→322px（= 当时可用高）、卡底 487 < 底栏顶 499 不重叠、`overflow-y:auto` 生效且可滚到底、文字不出卡框；② 「去提问」真实按钮 → h1「对话」、scope-bar「第2周·第2节 · 真实落地案例」、`selChapters` 持久化。
- **未经 iOS Safari 真机人工验收**（本机无 GUI 自动化权限），移动端手势/滚动惯性需使用者一手确认。

### 12.33 实现状态回写（v2.6.3，2026-09-19，每日任务阈值 10→30 + 阈值下发 + 进度不回退）

- **状态：已实现。** 触发原因：① 使用者要求「每天的连胜任务改成 30 张卡和 5 道题」；② 使用者手机实报「**4/10 卡却显示 ✓ 今日已完成**」。
- 变更请求号：`CR-2026-0919-THRESHOLD`。

**变更 1：阈值 10 → 30（单点）**

| 项 | 值 |
|---|---|
| 唯一真相 | `backend/config.py` `TASK_CARDS_REQUIRED = 30`、`TASK_QUESTIONS_REQUIRED = 5`（不变） |
| 自动随动的动态引用 | `data/checkin.py`（达标判定 / 卡组装配 `limit` / 班级投影）、`api/checkin.py`、`ai/reminder_copy.py`（催办文案）、`scripts/checkin_reminder.py` |
| 原本的硬编码散点（已消除） | `js/app.js` `streakBar()`、`js/student.js` `taskCardHtml()` / `_checkinBlock()` 各有写死的 `10`/`5`；`tests/test_checkin.py` 多处 |
| 下发字段 | `GET /api/checkin/today` → `task.cards_required` / `task.questions_required`；`GET /api/checkin/class` → `required: {cards, questions}` |

**变更 2：「4/10 卡却已完成」根因与修法（不是判定 bug，是口径冲突）**

| # | 事实 | 来源 |
|---|---|---|
| ① | 该账号当天 **01:38 已写入打卡行** `cards_done=10, questions_done=5, streak_after=1` | `daily_checkins` 实测 |
| ② | 当天 **12:08 之后** 实时计数仅 **4**（`knowledge_reviews` 当天行数 = 4） | `counts_today` 口径实测 |
| ③ | 该账号 `knowledge_reviews` 有 **2384 行**（= 重建后卡片全集），`last_review_at` 已大面积重置、`next_review_at` 为 11:49 那批 —— 即**教师端重建卡片库把复习记录重置了** | 库态实测 |
| ④ | `done` 取的是**当日快照是否存在**（幂等、不回退）；进度数字取的是**实时统计** ⇒ 快照 10 + 实时 4 = 同屏矛盾 | `streak_info()` vs `counts_today()` |

- **修法**：新增 `data.checkin.progress_today(con, user_id)` —— **展示口径** = `max(实时, 当日快照)`，进度只增不减；`/api/checkin/today` 与 `class_today()` 改用它。达标判定链路（`evaluate_and_maybe_complete` → `counts_today`）**保持不变**，即「今天确实达标过」这一事实不被推翻、也不被伪造（无快照时就是纯实时值，不凭空抬高）。
- **防复发**：`tests/test_checkin.py::test_progress_today_never_regresses`（快照下限 + 无快照不抬高）；`test_checkin_card_threshold_and_distinct` 改用常量 `TASK_CARDS_REQUIRED` 并断言下发字段 —— 今后调阈值不会再出现「测试写死 10 而代码是 30」的错配。

**版本一致性**：`backend/app.py version = "2.6.3"` == CHANGELOG 最新条目 == `index.html` 的 `?v=` == `sw.js` 的 `const V`；前端有改动 → `sw.js` CACHE `aistudy-shell-v47 → v48`。

**范围边界与诚实清单**
- 只改 3 个前端文件 + 3 个后端文件 + 1 个测试文件；**未重新生成卡片、未改卡片内容、未动学生数据**。
- 使用者手机上那个账号（Hermes 测试学生）**当天已有的一条 10 卡达标快照保留不动**（属既成历史）；按新口径它会显示 `10/30 卡 · ✓ 今日已完成`——即「当天达标过一次」的事实 + 只有 10 张被计数的现实，二者不再互相矛盾。
- 30 张卡组由服务端三档装配（未学 → 到期 → 低掌握度补足）自动凑满，库存 2384 张、4 章全 published，容量充足。
- `make lint` ✓ ｜ `make test` 覆盖率 **76.45%** ｜ `make smoke` → `2.6.3`。

### 12.34 实现状态回写（v2.6.4，2026-09-19，待复习口径 + 单次卡组上限 100 + AI 建议按钮/窗口）

**本次迭代 REQ**：`KNOW-003`（追加：「今日待复习」口径 = 已学且到期/逾期，未学不算）、`KNOW-006`（新增：单次复习卡组上限 100 张，阈值后端下发）、`RPT-003`（追加：`is_today`/`can_generate` + 生成窗口 = 上一条建议日 → 今天）。变更请求号 `CR-2026-0919-DECKADVICE`。

**三项实报 → 根因 → 修法**

| # | 用户实报 | 根因（数据确凿） | 修法（v2.6.4） |
|---|---------|----------------|---------------|
| 1 | 待复习「两千多张」，太多 | `GET /api/knowledge/overview` 的 `today_due` = 「非 mastered 且 `next_review_at` = 今天」；而 `knowledge_reviews` 是**首次打开章节时懒建**（`next_review_at = now`）⇒ 4 章 2384 张**未学**卡片全部落进「今日待复习」 | 口径改为：`learn_count > 0` 且 `next_review_at ≤ 今天` 且 `status != mastered`；未学只计 `new`。学生端同步新增 `Student.kcDue()`（含**本地日期**兜底，弃用 `toISOString()` 的 UTC 日） |
| 2 | 「每次学习最多一百张」，不要每天清空 | 「开始复习」一次性装配**全量**卡组（`cardsAll.length` = 2384）；`knowledge_reviews` 其实**从未被清空**（全库无 `DELETE FROM knowledge_reviews`），是**卡组装配**没有上限所致 | 新增 `config.SESSION_DECK_MAX = 100`（单点）；`kcDeckOrder()` = 待复习 → 未学 → 学习中/复习中未到期 → 已掌握，`slice(0, cap)`；`deck_max` 随 `overview` 与 `/{chapter_id}` 响应下发，前端不硬编码；`knowledgeCards`（本次卡组）与 `knowledgeAllCards`（全量）分离，退出复习恢复全量 |
| 3 | AI 建议停在 09-08，且**没有**生成按钮；窗口是否含昨天→今天 | ① `GET /api/progress/advice` 今天无建议时**回退返回历史建议**（`has_advice=True`），前端按钮条件写成只看 `has_advice` ⇒ 有历史建议 = 按钮永久消失（该账号 11 天未更新）；② 生成只统计**当天**（`today_stats`，UTC+8），上午生成即漏掉当天后续；③ `recent_learning_context`（近 7 天章节活动/掌握度/错题）**本来就覆盖昨天→今天**，缺的是四个计数与文案 | ① `/advice` 增 `is_today` / `can_generate`，前端**按键可见性由 `can_generate` 决定**（历史建议照常展示 + 标注「今日还没生成」+ 给按钮）；② `today_stats(con, uid, since=...)` 支持窗口，`/advice/generate` 取「最近一条建议的 `advice_date`」为起点，`stats` 带 `window_since/window_days/window_label/today/yesterday`；③ 提示词明确「统计窗口 + 今天/昨天明细」 |

**阈值与口径单点（新增，防漂移）**

| 项 | 唯一定义 | 下发位置 | 前端读取点 |
|----|---------|---------|-----------|
| 单次卡组上限 | `config.SESSION_DECK_MAX = 100` | `GET /api/knowledge/overview.deck_max`、`GET /api/knowledge/<chapter_id>.deck_max` | `student.js::kcDeckOrder/kcDeckSize`、列表页按钮与总览文案 |
| 每日任务张数/题数 | `config.TASK_CARDS_REQUIRED` / `TASK_QUESTIONS_REQUIRED` | `GET /api/checkin/today.task.*`、`GET /api/checkin/class.required` | `app.js::streakBar`、`student.js::taskCardHtml/_checkinBlock`（v2.6.3 已做） |
| 建议可生成性 | 当天 `daily_advice` 行是否存在 | `GET /api/progress/advice.can_generate`、`POST /api/progress/advice/generate` | `student.js` 进度页建议卡 |

**回归用例（3 个新增）**
- `tests/test_knowledge.py::test_overview_due_excludes_unlearned_and_counts_overdue`：未学 → `today_due=0`；复习后（interval 3 天）→ 仍 0；`next_review_at` 改昨日（逾期）→ 1；三处 `deck_max` 断言。
- `tests/test_daily_advice.py::test_advice_stale_row_keeps_generate_button`：仅有 09-08 历史建议时 `can_generate=True`（按钮必须在）→ 生成后 `is_today=True/can_generate=False`，且 `stats.window_since == "2026-09-08"`。
- `tests/test_daily_advice.py::test_advice_window_covers_yesterday_and_today`：`since=昨天` → 窗口内 2 次对话（今天 1 / 昨天 1）、`window_days=2`；`since=None` → 仅今天 1 次。

**范围边界与诚实清单**
- 改 3 个后端文件（`config.py` / `api/knowledge.py`、`api/progress.py`、`ai/advice_gen.py`）+ 1 个前端文件（`student.js`）+ 2 个测试文件；**未重新生成卡片、未改卡片内容、未删除任何复习记录**。
- 手工数据操作（经用户明确指示）：删除测试学生 `hermesstu` **2026-09-19 当天那一条打卡行**（改前备份 `backups/2026-09-19-cards/aistudy.sqlite3.pre-clean-checkin.bak`）→ 连胜归零、今日任务回到未完成态，可完整复现「学 100 张卡」的新流程。
- 「每次最多 100 张」= **单次装配上限**，不等于每日上限；每日任务卡组仍是 30 张（CHECKIN-002）。当天学完 100 张后可再次进入，卡组按「待复习 → 未学」继续装配下一批。
- `make lint` → `All checks passed!` ｜ `make test` → 覆盖率 **76.60%**（门槛 50%）｜ `make smoke` → `version 2.6.4`。

### 12.35 实现状态回写（v2.6.5，2026-09-19，范围自定 + 资料库折叠下拉 + 建议按钮常显）

- **后端**：`data/checkin.build_today_deck(con, user_id, limit=None, mode="task", rng=None, chapter_ids=None)`
  —— `chapter_ids` 非空时先 `SELECT ... WHERE chapter_id IN (...)` 收窄三档候选池；返回体加 `scope`；
  `empty_reason` 三分支：`no_published_cards`（库真空）/ `no_cards_in_scope`（范围真空）/ `short`（凑不满）。
  `api/knowledge.today_deck()` 读 `?chapter_ids=`（逗号分隔）；`api/checkin.start_practice()` 读 body `chapter_ids`，
  续答查询同样按范围过滤（`pq.chapter_id IN (...)`），范围外无卡返回 `所选章节暂无可练习内容`。
- **前端**：`student._scopeIds()` / `_scopeQs()` 统一拼范围查询串；`startTodayDeck` / `startExtraDeck` / `continuePractice` 全部带范围。
  hub 顺序 = 今日任务 → 对话 → 知识卡片 → 资料库；资料库 `.lib-head` 可点折叠（localStorage `aistudy_lib_open`，默认收起）。
  RPT-003 建议按钮**常显**：`can_generate=false` 时渲染 disabled 的「今日已生成 · 明天可再生成」。
- **测试**：`tests/test_checkin.py::test_today_deck_respects_student_scope`、
  `::test_start_practice_respects_student_scope`（16 passed）。

### 12.36 实现状态回写（v2.6.6，2026-09-19，资料库折叠头重叠修复 + 勾选口径统一）

**本次迭代 REQ**：`CHECKIN-013`（追加：UI「空勾选」必须与接口「未传/空 = 全部已发布章节」同口径，不得分叉）。变更请求号 `CR-2026-0919-LIBHEAD`（用户实报截图，纯前端）。

**两项实报 → 根因 → 修法**

| # | 用户实报 | 根因 | 修法（v2.6.6） |
|---|---------|------|---------------|
| 1 | 资料库折叠头右侧「按钮重叠」 | `.lib-caret` 收起态用 `transform:rotate(-90deg)` 指示方向，**旋转圆心偏移**后箭头压住右侧 `.card-count` pill | 收起态改为**不旋转**（收起 `▾` / 展开 `▴`）；`.lib-head` 三段 flex 明确 `flex:1 1 auto`（标题，超长省略）+ `flex:0 0 auto`（pill / caret），`gap:10px` |
| 2 | 「已选 0」与真实生效范围不一致 | `selChapterIds()` 勾选为空时**本就兜底为全部章节**，但列表页副标题仍渲染「已选 0」→ 与真实行为矛盾、误导学生 | 口径统一：空勾选显示 `N 篇 · 全部`（副标题 `全部 N 章`），收起态 hint 补「不勾选 = 按全部资料」 |

**锚点与验证**：`backend/frontend/css/style.css:286-298`（`.lib-tools` / `.lib-head` / `.lib-caret`）、
`backend/frontend/js/student.js:104-133`（`scopeLabel` / `libCount` / `lib-hint`）。
前端三件套同步：`app.py version 2.6.6` / `sw.js CACHE v51` / `index.html ?v=2.6.6`。

### 12.37 实现状态回写（v2.6.7，2026-09-19，全选/清空纵向压住 pill + CSS chevron 箭头）

**本次迭代 REQ**：`CHECKIN-013`（追加：资料库折叠头/工具行的**几何无重叠** = 横向 + 纵向双达标）。变更请求号 `CR-2026-0919-LIBHEAD2`（用户**二次**实报截图，纯前端）。

**两项实报 → 根因 → 修法**

| # | 用户实报 | 根因 | 修法（v2.6.7） |
|---|---------|------|---------------|
| 1 | 资料库「全选/清空」压住 pill（v2.6.6 修完仍未解决） | 真正碰撞是**纵向**：`.lib-tools` 用 `margin:-4px 0 8px` 负上边距（旧版靠 `.card-head` 的 10px 下边距抵消），v2.6.5 起折叠头换成 `.lib-head`（无下边距）后按钮行被顶进 pill 下边缘 | `.lib-tools{margin:10px 0 10px}` 改正间距 + `.lib-card .lib-head{margin-bottom:0}` |
| 2 | 箭头「浮在 pill 上方」 | 字符 `▾/▴` 自身**字形度量偏上**，`line-height` 居中永远对不齐 pill 中线 | 箭头改 **CSS chevron**：`::before` 画 7px 方块 + `border-right/bottom`，`rotate(45deg)`（收起）/ `rotate(-135deg)`（展开，`.lib-caret.on`），容器 `18×18` flex 居中 —— 视觉居中且无字形差异 |

**教训（已写进 skill Pitfalls）**：修「重叠」必须**同时量横向与纵向**（`pill.right < caret.left`（横）**且** `tools.top > head.bottom`（纵，留 ≥6px））。v2.6.6 只量了横向就宣布修好 → 用户回来说「还是没有解决」。

**锚点**：`backend/frontend/css/style.css:286-298`（`.lib-tools` / `.lib-caret::before`）、`backend/frontend/js/student.js` 资料库折叠头渲染。
前端三件套同步：`app.py version 2.6.7` / `sw.js CACHE v52` / `index.html ?v=2.6.7`。

**共同诚实清单（v2.6.6 / v2.6.7）**：两次均为**纯前端**改动（`css/style.css` + `js/student.js` 局部），未改后端接口、未改数据、未新增依赖；`make lint test smoke` 全绿（v2.6.7 覆盖率 77.14%，冒烟 `version 2.6.7`）；**未 bump 除前端三件套外的任何版本**。本次回写仅补文档，**不产生 CHANGELOG 条目、不 bump `app.py` version**（与 `a4a64a5` v2.6.1 回写先例一致）。

### 12.38 实现状态回写（v2.6.8，2026-09-22，知识卡片重复知识点合并）

- **本次迭代 REQ**：`KNOW-007`（卡片库不得存在重复知识点）——定义见 §3.4.2（Functional + Technical 两处）。变更请求号 `CR-2026-0922-DEDUP`。
- **状态：已实现。** 触发原因：用户实报「你 review 一下所有的知识卡片，重复的知识点合并一下」。

**根因（三条，均经只读诊断确认）**

| # | 根因 | 证据 | 修法 |
|---|---|---|---|
| 1 | **旧判据只比「问句词元」且数字必须相同** | `rebuild_cards.py --dedupe-db` = 词元 Jaccard≥0.85 且 `digits` 集合相同 | 判据作废，改为「主体 + 答案」双看：LLM 分组 + 对抗式复核（详见 §3.4.2 Technical） |
| 2 | **从不跨章比较** | `dedupe_db()` 内层循环 `if a["chapter_id"] != b["chapter_id"]: continue`；Token / 幻觉 / 流式输出 / 微调 / RAG / CoT / Vibe Coding 在第 1、2 周各有一张 | 候选召回与分组不再按章切分；跨章重复只留**最早出现**的那张，正文取并集 |
| 3 | **多次增量补卡未回头重跑去重** | `--fill-orphans` / `--fill-gaps` 后同章仍有 5 组满足旧判据（≥0.85 数字相同）却未被合并；最极端「幻觉」一组 9 张 | 每次补卡后应重跑去重；本次一次性清干净并复测 |

**施工中发现（非用户报障）**

1. **「同模板异主体」是最危险的误合并源**：LLM 单轮裁定把 `GitHub Copilot / Cline-Roo Code / Continue.dev / Tabnine`（四家工具、同一问句模板）判成「同一工具同信息，保留最完整卡」→ 会把四张卡合成一张。修法：① 输出格式从「一簇一个保留卡」改为**一簇可拆多组**；② 追加**对抗式复核**（换「主动找实质差异」的立场再审），主体/数字/答案指涉不同即否。该轮共否掉 59 组。
2. **保留卡可能信息更少**：按「复习进度优先 → 最早章 → 信息最全」选定保留卡后，「大模型为什么此时才兴起」留下的是只答「硬件进步」的卡，而列全 4 个原因的卡被删；AGI、Vibe Coding 同病。修法：给**所有**确认组跑一遍「信息整合」（要求保留每张原卡独有事实、禁新增），再跑**忠实度校验**（`fabricated` / `conflict` / `missing`），138 组中仅 1 组告警（「共 5 项」实际列 4 项）并已人工修正。
3. **源卡自身缺陷会被忠实继承**：整合卡照抄了「共 5 项：」（只有 4 项）与「（以及第四个工具）」。修法：人工修正为不写数量断言 / 补全 `searchFAQ`（依据同章另一张卡的四工具清单）。
4. **数字守卫式校验会误报**：「4 个技术原因」整合后出现 `1. 2. 3.` 列表序号，被数字集合守卫判为「新数字」。修法：守卫按「原卡数字并集的超集」判定 + 复核提示词里明确「序号不算新增事实」。

**产出（本地库，不入 git；`.gitignore` 已含 `instance/`）**

| 章节 | 卡片（合并前 → 后） | 涉及合并组 |
|---|---|---|
| 第1周·第1节 大模型是什么 | 437 → **398**（-39） | 34 |
| 第1周·第2节 AI 产品地图 | 625 → **587**（-38） | 32 |
| 第2周·第1节 AIPM vs 传统 PM | 733 → **678**（-55） | 41 |
| 第2周·第2节 真实落地案例 | 589 → **552**（-37） | 31 |
| **合计** | **2384 → 2215**（删 169 张） | **138**（同章 131 / 跨章 7） |

- **落库方式**：`scripts/merge_duplicate_cards.py --plan backups/2026-09-22-cards/plan-*.json --apply`（默认 dry-run；`--apply` 自动 `wal_checkpoint(FULL)` + 备份生产库）。备份 `backups/2026-09-22-cards/aistudy.sqlite3.pre-dedup-20260922-181425.bak`；回滚报告 `dedup-report-20260922T101425Z.json`（含 169 张被删卡全文、169 行复习行全文、138 张保留卡新旧正文）。
- **数据一致性实测**：卡片 2384 → 2215；`knowledge_reviews` 2390 → 2221（169 行并入保留卡）；**孤儿复习行 0**；空正文卡 0；`status` 分布 learning 66→60 / reviewing 7→6 / mastered 3 / new 2314→2152（合一只取更进阶的一份，无进度丢失）。
- **复测（对合并后库重跑原判据）**：章内「Jaccard≥0.85 且数字相同」重复组 **5 → 0**、跨章 9 → 1；章内 ≥0.70 由 33 → 13、≥0.60 由 105 → 37。残留 14 组逐组人工确认**全部是不同主体**（通义千问 Max/Flash/Coder、SWE-bench Verified/Pro、Redis/MySQL、Copilot/Autopilot、下限/上限、Command A Reasoning/Vision/Translate…），属「正确地没合并」。
- **实测证据**：`make lint test smoke` 全绿；`scripts/merge_duplicate_cards.py` py_compile 通过；生产库真实落库前后均 `curl /health` 正常。
- **版本一致性**：`backend/app.py version == 2.6.8` == `CHANGELOG.md` 最新条目；**前端文件零改动**，`sw.js` CACHE 保持 `v52`、`index.html` 保持 `?v=2.6.7`（遵循 v2.5.1「纯后端 + 脚本改动不 bump 前端」先例）。
- **范围边界（未越界）**：未改任何后端接口/业务逻辑；未改前端；未新增运行时依赖（去重脚本只用标准库 + `urllib`）；未改 `audit/`、未删任何非重复卡、未动 `source_chunk_id` 绑定（绑定随保留卡保留）。
- **诚实清单（未做 / 仍需人工）**：① 残留的 ≥0.60 近重复 37 组**未合并**（判据认为不是同一考点，如需更强合并需人工定裁）；② 卡片正文整合由 LLM 产出，虽经「忠实度校验 + 逐组人工复核可疑项」双重把关，**建议 Ray 抽看 10~20 张被改写正文**（报告 JSON 里 `old_back`/`new_back` 可直接对比）；③ 未处理「同知识点但跨章节表述不一致」之外的教研问题（如题库超纲 4~5 题，见 §12.28）。
- ⚠️ **口径修正（当日 v2.6.9）**：本节的复测数字（「重复组 5 → 0」「残留 37 组」）是用**词元 + 二元组**口径跑出来的，该口径对**短问句换语序**不敏感（`幻觉是什么？` vs `什么是幻觉？` 词元 Jaccard 恰好 **0.0**、二元组 0.33），所以「残留已归零」的结论**过于乐观**——实际漏了 70 组 / 75 张。v2.6.9 补合后详见 §12.39。

### 12.39 实现状态回写（v2.6.9，2026-09-22，补合漏检的重复知识点）

- **根因（2.6.8 召回盲区两条）**：① **换语序即隐形**——词元切分对短问句贪婪取 2–4 字（`幻觉是什么？`→`幻觉是什`、`什么是幻觉？`→`什么是幻`），词元 Jaccard **0.0**；二元组 `{幻觉,觉是,是什,什么}` vs `{什么,么是,是幻,幻觉}` Jaccard **0.33**，两个指标同时低于阈值 → 中文短问句「X 是什么 / 什么是 X / X 的定义」这一最普遍的重复形态**整类漏检**。② **子标签硬分区**——召回在 `sub_concept` 内比较，而同一考点被标到不同标签（「幻觉」分散在 `术语卡片` / `核心术语幻觉` / `AI 核心术语` / `AI质量指标`），跨标签的同考点卡从不比较。
- **施工修正**：候选召回加第三条路「**按字袋（忽略语序）** Jaccard ≥0.65 **且**二元组 ≥0.55」（限 front ≤80 字符）并集；取消标签硬分区；规模可控时直接**暴力两两比较**（2140 张、带 `|长度差| ≤ 14` 剪枝），避免倒排索引「泛词桶过大被跳过」而漏召回。
- **产出**：候选 **145 簇 / 366 卡**（上界可删 221）→ LLM 分组 67 组 → 对抗式复核**否掉 67 组**、确认 **70 组** → 信息整合 70 组 → 忠实度校验通过 → **删卡 75 张**（2215 → **2140**）、改写保留卡 68 张。**累计两轮 2384 → 2140（删 244）**。
- **第三轮补合（v2.6.10，修掉本节的护栏 bug）**：本节把按字袋候选路写成「按字袋 ≥0.65 **且**二元组 ≥0.55」——换语序短句的二元组恰好 **0.33**，**护栏把要修的那类又挡回去了**（端到端验收发现「幻觉是什么？」/「什么是幻觉？」仍未合）。改为「norm ≤30 字的短 front **只看按字袋 ≥0.70**」后重跑：在 2140 张库上召回 115 簇 / 278 卡 → 对抗式复核否掉 70 组 → 确认 **26 组** → 删卡 **27 张**（2140 → **2113**）。**累计三轮 2384 → 2113（删 271）**，孤儿 0。
- **落库方式**：沿用 `scripts/merge_duplicate_cards.py`（第二轮 plan = `/tmp/kc2_plan.json`）；先在**测试副本** `/tmp/kc2_test` 跑 `--apply` 验证（2215 → 2140、孤儿 0）才动生产库；生产库备份 `backups/2026-09-22-cards/aistudy.sqlite3.pre-dedup-20260922-182340.bak`、回滚报告 `dedup-report-20260922T102340Z.json`。
- **数据一致性实测**：卡数 **2140**、复习行 **2146**、**孤儿 0**、空正文 0；章分布 **379 / 570 / 655 / 536**（合计 2140）；状态分布 `new 2073 / learning 64 / reviewing 6 / mastered 3`。
- **复核**：7 个高危组（组规模 ≥3、跨章、组内实体/数字不一致、校验告警）逐条人工确认**全部正确合并**（如 `什么是 AGI？大模型和 AGI 是什么关系？`＋2 变体、`什么是大模型（大语言模型）？`＋`什么是大语言模型（LLM）？`＋`什么是 LLM（大语言模型）？`、`相比传统 Naive RAG…四项优化？`＋2 变体）。
- **残留定性（第二轮复测，按字袋口径）**：≥0.75 → 17 组、≥0.60 → 46 组、≥0.50 → 66 组。逐组抽样：**绝大多数是「同模板异主体」（正确地未合并）**，如 6 家 AI 编程工具同模板、3 家 rerank 榜单同模板、`传统 PM 与 AIPM 在 X 上的区别`（8 个维度）、`OKR/KPI/PMF/MVP 全称`、`PRD/MRD/BRD 缩写`。**少数是「同考点但各源资料命名口径不一致」**，典型：`AI 产业三层结构` 在不同卡写作 `基础模型层/模型服务层/应用层`、`基础设施层/模型层/应用层`、`上游基础层/中游模型层/下游应用层` 三种口径 → 属**教研口径冲突**，判据（「答案表述不一致不合并」）保守保留，**需教研定稿统一命名后再合并**（已记入诚实清单）。
- **版本一致性**：`backend/app.py version == 2.6.9` == `CHANGELOG.md` 最新条目；前端三件套不动（`sw.js v52` / `index.html ?v=2.6.7`）。
- **LLM 用量**：第二轮 **301 次调用 ≈ $0.083**（两轮累计 855 次 ≈ $0.27），逐次记账 `~/.hermes/app-usage/aistudy.jsonl`（`feature` 前缀 `kc-dedupe2*`）。
- **诚实清单（未做 / 仍需人工）**：① 「同考点命名口径冲突」的卡未合并（需教研定裁，见上）；② 残留 ≥0.60 的 46 组中判据未合并的属保守正确，但如需更强合并需人工逐组定裁；③ 卡片正文由 LLM 整合，仍建议 Ray 抽看 10~20 张（回滚报告 `old_back`/`new_back` 可对比）；④ 复测口径的教训已回写 `llm-content-dedup` skill（召回指标必须「换语序不变」）。

### 12.40 实现状态回写（v2.7.0，2026-09-22，章节解耦学习时间 + 浏览卡片主题分组）

- **用户诉求（原话）**：「我觉得每一个 session 几百张卡片挺多的，能不能在浏览所有卡片那里对卡片进行适当的分组，而且我觉得每天最多学习 30 张所以一个星期最多学习 210 张，所以现在的 week1 week2 有点不现实，感觉需要解耦章节和学习时间的关系，不要提及 week 几，然后按照卡片的数量去写（预计 x 天学完）这样，全量重命名，不要 WxSx，直接第几章第几章就行」→ 拆成 KNOW-008（主题分组）+ KNOW-009（章数解耦），定义为**新功能**，版本落 **2.7.0**。
- **章节全量重命名（KNOW-009）**：`scripts/rename_chapters.py`（默认 dry-run、`--apply` 才写库、改前自动备份到 `backups/2026-09-22-chapters/`）——按原 `(folder, order_no, name)` 顺序重排 `order_no` = 1..N、`folder` 置空、`name` = 「第 N 章 · <原标题（取 `·` 末段）>」。**幂等**：对新名再跑一次结果不变。落库后实测 4 章全部为新口径（全库检索「第X周」「第Y节」「未分组」均为 0 命中）。种子脚本 `inject_curriculum.py`（新增 `chapter_no()` 助手）与 `inject_w1.py` 同步改口径——章号 = `(week-1)*2 + session_no`；课件源目录仍按 `W{week}S{session}` 映射（`backfill_courseware` 改由 `order_no` 反推，不再解析 `folder`，否则 folder 置空后课件回填会静默跳过）。
- **天数口径（KNOW-009）**：`config.PLAN_CARDS_PER_DAY = TASK_CARDS_REQUIRED`（30 张/天，**单点定义**，避免「进度 30 张/天」与「打卡 30 张/天」两个旋钮漂移）；`GET /api/chapters` 增发 `daily_cards` + 每章 `card_count`；前端 `App.daysFor()` = `Math.max(1, ceil(card_count / daily_cards))`，`App.chapterSubtitle()` = 「预计 X 天学完 · 共 N 张卡」。**实测天数**：第 1~4 章 = **13 / 19 / 22 / 18 天**（371 / 564 / 644 / 534 张），全库 2113 张 ≈ **71 天**。
- **主题分组（KNOW-008）**：`card_topics(card_id PK, chapter_id, topic, ord)` + 索引 `(chapter_id, ord)`，建表在 `models.SCHEMA` 与 `migrate()` 双写（老库启动即补表）；`scripts/group_cards.py` 建表**复用** `models.SCHEMA/migrate`（单一真相，不重复 DDL），LLM 三级处理：
  1. **主题表**：投喂该章资料名 + 高频 `sub_concept`(≤120) + 等距抽样 `front`(≤80) → 10~16 个主题（要求体量均衡）；
  2. **逐卡归类**：每批 25 张、4 并发，**只允许**用给定主题（禁止新造），失败批次不影响其他批；
  3. **再平衡**（关键）：首轮实测模型会造出巨型桶（章 2「模型选型与对比」**280** 张、章 3「产品经理视角」**356** 张、章 4「RAG与知识库」**253** 张）＋一堆 1~4 张碎片组，展开后**仍是卡片墙** → 加大于 `MAX_TOPIC_CARDS=80` 自动拆 2~4 子主题（最多 `SPLIT_ROUNDS=2` 轮）、小于 `MIN_TOPIC_CARDS=5` 并入最贴切大主题（实在无处可去才落「其他要点」）。
  - **最终落库实测**：`card_topics` **2113 行** = 卡片数（**0 未归类 / 0 孤儿**）；章 1~4 = **20 / 23 / 24 / 20 组**，最大组 **47 / 76 / 68 / 64** 张，兜底组「其他要点」**0 张**；拆分动作 2 / 3 / 4 / 1 次。抽样质量：章 4 分出「KBQA与图检索技术 / Query 理解与实体识别 / 子图检索与答案排序 / 美团智能客服案例 / 电商系统部署与监控」等可直接消费的主题。
  - **不改内容**：本迭代**只写 `card_topics`**，`knowledge_cards` 全表未动（施工前后均为 2113 张，`git` 亦无卡片数据文件变更）；`topic` 经 `LEFT JOIN card_topics` 随 `GET /api/knowledge/<chapter_id>` 下发，未归类时返回空串 → 前端 `Student.topicGroups()` 退化为单组「全部卡片」，老库/分组失败均可用。
  - **前端**：`student.js` 浏览页由「章 → 卡片墙」改「**章 → 主题组 → 卡片**」两级纵向折叠（`knowledgeGroupOpen` / `knowledgeTopicOpen` 双层展开态，主题下标而非主题名作 key，避免中文名含引号拼串出错）；组间按卡片数降序、组内保持接口原顺序（后端已按复习状态/到期排序）；章头与总览均标「预计 X 天学完」；`teacher.js` 的 `folder` 兜底文案由「未分组」改「课程章节」（folder 现已统一为空）。
- **门禁**：`make lint test smoke` 全绿（含新增 `tests/test_card_grouping.py` 4 条）。**版本一致性**：`backend/app.py version == 2.7.0` == CHANGELOG 头；前端三件套同步 bump（`sw.js CACHE v52→v53`、`?v=2.6.7→2.7.0`）。
- **LLM 用量**：分组两轮（含首轮废弃运行）逐次记账 `~/.hermes/app-usage/aistudy.jsonl`，`feature` 前缀 `kc-topic*`（taxonomy / assign / split / split-assign / merge）。
- **诚实清单（未做 / 仍需人工）**：① 主题名由 LLM 生成，**未逐组人工核对全部 87 组**（已抽样看章 4 与各章首尾组）；已记录一处**语义相邻**：章 3 同时存在「AIPM角色与能力转型」与「AIPM角色与思维转变」两个近义组名（组内卡片不重复，仅命名口径相近），如需可下一轮合并；② 分组为**派生数据**，卡片增删后需重跑 `scripts/group_cards.py --apply`（未接入自动任务，卡片变更后 `topic` 可能指向已删卡 → `LEFT JOIN` 自然丢弃，不会报错）；③ 学习天数按「每天 30 张新卡」静态折算，未计入复习负担（间隔复习会占用每日额度）。

### 12.41 实现状态回写（v2.7.1，2026-09-22，修「学习路径页仍在提周/节」）

- **问题（用户实报「全局都改了？？？」+ iPhone 截图）**：v2.7.0 的 KNOW-009 只解耦了 `chapters`（章节名 / 知识卡片 / 测评下拉标签），**「学习路径」页（学生「路径」tab）不在其中**——它读 `/api/curriculum`，而该接口按 `sessions` 表的 `week_no/session_no` 分组返回 `weeks→sessions`，页面副标题还写着「8 周 · 周/节进度」。同类残留还有：学生测评标题 4 处（前端用 `s.week_no/s.session_no` 自己拼串）、教师端课程管理列表、视频课列表、教师端建/改表单（周次 + 节次两个输入框）、发布通知文案（「第X周 第Y节 · 标题」）。**根因：全站存在两套序号体系**（`chapters.order_no` 与 `sessions.(week_no, session_no)`），v2.7.0 只统一了前者。
- **处理（合为一套章号）**：
  - 换算单点：`data/models.py::chapter_no(week, session)` / `week_session(n)`（章号 = `(week-1)*2 + session_no`），`api/curriculum.py`、`api/quizzes.py` 共用，**禁止各处重写公式**。
  - 对外口径：`GET /api/curriculum` → `{chapters: […], daily_cards}`（章号升序扁平列表，每章含 `card_count` / `days`）；`GET /api/curriculum/videos` → `chapter_no`（未绑定为 `null`）；`quizzes._quiz_session()` → `{chapter_no, title}`。**库表列不动**（`sessions` / `video_resources` 的周/节是发布状态机与视频绑定键，不做破坏性迁移）。
  - 写入兼容：`POST/PUT /api/curriculum/sessions|videos` 优先读 `chapter_no`，缺省回落 `week_no/session_no`（旧脚本、旧测试零改动；视频 `chapter_no: null` = 显式解绑）。
  - 前端：`student.js::viewPath()` 去周分组 → 「第 N 章 · 章标题」+「预计 X 天学完 · 共 N 张卡」，标题栏「N 章 · 预计 X 天学完」；测评标题 4 处改「测评 · 第 N 章 · 章标题」（同时去掉与之重复的副标题章节名）；`teacher.js` 课程管理 / 视频课改章号，建改表单的两个输入框合并为「章号」。
- **验证**：`make lint test smoke` 全绿；新增 `tests/test_curriculum.py::test_curriculum_speaks_chapter_no_only`（断言响应无 `weeks`、会话无 `week_no/session_no`、章号升序、章号入参落库正确、旧入参兼容 W3S2 = 第 6 章）。
- **教训（防再犯）**：**口径类需求必须先做全站口径盘点**——「数据结构字段 + 用户可见文案 + 硬编码字符串」三路 grep 齐查，否则会出现「改完章节表，另一张表还在讲周/节」的半覆盖交付。已同步写入 runbook `ai-study-app-production` 的 Pitfalls。
- **v2.7.2 微调（同日）**：测评标签统一为「测评 · 第 N 章 · 章标题」（带空格），与章节名写法一致——此前同一屏会出现「测评 · 第2章 · AI 产品地图」与「覆盖：第 2 章 · AI 产品地图」两种格式。
- **数据文案同步（同日，非代码）**：清掉**用户可见数据**里的课程周/节口径 6 行（`materials.original_name` 4 行「W2S1 课件（教案）.md」→「第 3 章 课件（教案）.md」，映射与该资料实际挂载的章 `order_no` 逐行核对一致；`sessions.milestone` 1 行「本周产出」→「本章产出」；`video_resources.description` 1 行「本节」→「本章」）。改前 `VACUUM INTO` 备份至 `backups/2026-09-22-week-text/`。**剩余**：`knowledge_cards` 正文里仍有 62 处提到「本周 / 本节 / W1S2 / W2S1」等（属**课程原始 8 周课件的叙述**，其中「留到 W7」「W3 起」等指向**从未建章的周次**，机械替换会指向不存在的章号）——**待产品确认后再定**（选项：LLM 逐卡改写成章号口径 / 保留原文 / 只在浏览态折叠显示）。

### 12.42 实现状态回写（v2.7.3，2026-09-22，章号口径下沉到数据与源文档）

**REQ-ID：KNOW-010（全站章号口径 · 数据与源文档层）** —— 状态：✅ 已交付。

- **需求（用户原话追加）**：「我选 1，而且**课件文件夹里面的也要改**」。承接 v2.7.0~v2.7.2 的 UI/接口口径统一，本轮把口径迁移**下沉两层**：① 库内用户可见文本（知识卡片正文、资料路径）；② 盘上源文档（课件目录名、课件 md 正文、课程总路径文档）+ 派生数据（RAG 切片）。
- **换算与边界（单点，不搞第二套口径）**：章 N = `(周-1)*2 + 节`（与 `data/models.chapter_no()` 同式，共 16 章）。**已发布 4 章（第 1~4 章）写具体章号；未发布章节在卡片侧用「后续章节」**（app 只见 4 章，避免指向不存在章号）；**课件侧一律写具体章号**（课件树 16 章齐备、`课件/第13章` 可解析）。这处有意的不对称已写入 CHANGELOG 诚实清单。
- **落地方式（两层，可复现）**：
  - ① **LLM 语义改写**：只投喂「含口径串的段块」，模型返回整块替换；**长度比护栏**（0.55~1.7）+ 空块拒收；`temperature=0`、显式关 thinking、逐次记账 `~/.hermes/app-usage/aistudy.jsonl`（`feature=aistudy:chapter-naming-*`）。
  - ② **确定性收尾**（关键）：LLM 对**回溯性指代与裸周号**（「接进第 6 周的小工具」「W4 已部署的 Hermes」「第7周 · Session 2」标题、「本 Session」）漏改率不低（首轮 39 文件残留 15 处 + 42 处 `本 Session`）—— 这些形态规则极固定，用正则收尾（裸 `Wx`→`第 2x-1–2x 章`、`第N周`→区间、`WxSy/`→`第N章/` 路径不带空格、章号空格归一化）比再喂一次模型更可靠。
  - ③ **RAG 同步**：改 md 正文必然使 `chunks.text` 陈旧 → 复用 `ai.parser.extract_text + chunk_text_list` **定向**重切片（只重算 `.md` 资料，PDF/PPTX 不动、不触发 OCR），与入库路径同源。
  - ④ **受保护文档处理**：`小白AI课程16章学习路径.md`（原 `小白AI课程8周学习路径.md`）是课件引用 30 次的「课程总路径」源文档，同时在**受保护文档清单**（8 项已核准归档，**保持 tracked**）里 —— 按 CLAUDE.md §6.7「冲突不硬解」先报 Hermes 裁决，**最终维持归档口径**：改名 + 正文迁移 + 同步 30 处引用；文件名变化必须同步进审计白名单 `ARCHIVED_OK`（不同步 = 次日假 FAIL）。过程留痕见 CHANGELOG 2.7.3 与 commit `c2d39a5`。
- **验证**：`make lint test smoke` 全绿；口径残留自检 **卡片 0 处（首轮曾误报「残留 5 处全合法」，实为假阴性，见教训 6）/ 教案 md 0 处 / md 切片 0 处 / 课程总路径文档 0 处**；课件目录 16 个改名后文件计数 939 不变；`materials.source_path` 全库 `课件/W%` 命中 **0**；`chunks` 排版残留 0（483 片）。
- **教训（新增，防再犯）**：
  1. **「改口径」要分层盘点**：UI 文案 → 接口出口 → 库内数据 → **派生数据（向量/切片/分组）** → **盘上源文档**。前两轮只查到第三层就收工，才出现「全局都改了？？？」→「课件文件夹也要改」两次返工。
  2. **LLM 改写必须配确定性收尾**：模型擅长处理需要语义判断的（「留到 W7」→「后续章节」），**不擅长**处理固定形态的回溯指代与标题；两者叠加才是「高覆盖 + 可复现」。
  3. **改磁盘正文 = 必须重切片**，且要**定向**重切片（避免为了 33 条切片跑全量 OCR）。
  4. **受保护文档冲突先报再动，且「报」之前先读 runbook 里该主题的定调段**：这批文档同日已拍板「维持归档」，而助手在 1 小时后把它重新当成「未解决 GAP」端出选项、(c) 还写成「移出跟踪」→ 用户选中 → 助手默默推翻了用户自己的裁定（且因白名单豁免，次日审计**不会**报错 = 静默漂移）。**端二选一前先 `grep` runbook 确认没有既有裁定；若选项与既有一致性冲突，必须在选项里写明。**
  5. **已归档文件改名 = git 记录为「改名 + 内容改」**，正常入库即可（保持 tracked），无需先 untrack —— 先 untrack 反而要二次提交回退（本次 `3d28406` → `c2d39a5`）。
  6. **「残留 0」必须先证明模式集完备，否则只是「我的正则瞎了」**：首轮用 `第\d+周 / WxSy / Session \d` 三式扫，报「残留 5 处全合法」；换成语义完备的模式集（+ 中文数字周 `第一周` + 裸 `W3`/`W6/W8` + 无数字 `本 Session`）后同库扫出 **95 处真残留**，其中 `sub_concept` 值「本Session产出」有 9 张卡（**是 UI 分组标签**，最容易被漏且最显眼）。
     → 判定收尾的固定动作：用**两种颗粒度**扫（精确串 + 语义形态），两者都要 0 才算完；数字型模式一定要同时覆盖**阿拉伯数字与中文数字**，指代型要同时覆盖**带数字与不带数字**。
  7. **替换规则的「边界断言」会自己制造畸形文本**：裸周号正则为了不误伤 `W1S1` 写了 `(?<![A-Za-z0-9])W\d(?![0-9S])`，结果 `W6/W8` 里 `/` 被吞进负向断言 → 只换了 `W6`，产出「后续章节/W8」半截 + 「后续 后续章节」双写。
     → 规律：**凡负向断言（`(?<!…)`）都要为「并列/分隔符」场景单独测一遍**（`W6/W8`、`W6、W8`、`W6-W8`），并在替换后扫一次「替换产物 + 原分隔符」的组合残留。
