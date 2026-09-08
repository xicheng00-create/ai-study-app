# AI 学习小组 App — 设计规格说明书 (Design Spec)

> 版本：v2.1（融合 Functional + Technical；严格对齐 `architecture-design.md` v1.1；**最新稳定版：v1.18.1（2026-09-08）**；2026-09-02 增补：测评百分制评分模型 + AI 评分与教师覆核双轨 + QUIZ-005 提 P1）
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
| CHAT-002 | student | P0 | 选择范围（资料/章/全部） |
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
| KNOW-002 | student | P1 | 点卡 3D 翻转看答案；**左滑=没记住、右滑=记住了**（底部兜底按钮 ←没记住\|记住了→）；顶部进度 第N/总数 + 每卡状态色 |
| KNOW-003 | student | P1 | 系统记录每知识点**学习次数（learn_count）**+ **复习状况**（new/learning/reviewing/mastered + 间隔 1→3→7）；每日「待复习」队列优先，再学新卡 |

**Technical**
- **独立数据层（共享内容 + 每生独立复习态，v1.17.x 重构）**：`knowledge_cards`（id, chapter_id, sub_concept, front, back, source_chunk_id, created_at）——**无 user_id，是共享内容**（每章一组，发布时生成一次）；`knowledge_reviews`（id, card_id, user_id, learn_count, interval_days, next_review_at, status CHECK(new/learning/reviewing/mastered), last_review_at, created_at, UNIQUE(card_id,user_id)）——**每学生独立复习状态**，学生首次打开该章卡组时**懒建**（默认 new）。已废弃 v1.17.0 的「knowledge_cards 带 user_id」旧形（表空可安全重建）。
- **状态机复用 `review_sched`**（architecture §5.4）：记住了 → `learn_count++`、`interval_days = next_interval(True, cur)`（1→3→7 封顶）、状态上移（new→learning→reviewing→mastered）、`next_review_at` 按间隔顺延；没记住 → `learn_count++`、`interval_days=1`、状态降回 learning、`next_review_at` 次日重排。同卡片跨会话复习。**先翻转看答案再判 remember，不在 open 期强行判定**。
- **AI 抽取**：新增 `backend/ai/knowledge.py` `generate_knowledge_cards(chapter_ids)` + `prompts.py` `KNOWLEDGE_SYSTEM`（要求 JSON `[{front, back, sub_concept}]`，遍布全章、覆盖不同子概念、back 含答案/解析/一句示例）；LLM 真返空返空列表、端点提示「生成失败请重试」。
- **路由（去掉「学生手动生成」主路径）**：`POST /api/knowledge/generate`（保留为**懒加载兜底**：卡片缺失时教师/系统可触发，学生一般不必点）、`GET /api/knowledge/:chapter`（卡组+该生复习态，学生首次打开自动懒建 review 行）、`POST /api/knowledge/:card/review`（body `{remembered: true|false}` → 更新该生 learn_count/interval/status/next_review）、`GET /api/knowledge/overview`（各章该生掌握进度：已掌握/学习中/未学/今日待复习）。学生本人，越权 403；蓝图 `knowledge_bp` 注册进 app.py。
- **⚠️ 自动生成钩子（v1.17.x，核心）**：`knowledge.ensure_chapter_cards(chapter_id)`（查 `knowledge_cards` 该章已有卡则复用返 True，无则 LLM 生成 + 入库返 False；LLM 失败返回 False，由懒加载兜底）。在**学习路径发布**（`curriculum_bp` 发布 session → 对其 `chapter_ids` 逐个 `ensure_chapter_cards`）与**资料发布**（`materials_bp` 发布 material → 其 `chapter_id` `ensure_chapter_cards`）处调用。同步调用 + try/except（发布请求可容忍 ~秒级 LLM 延迟，3 学生规模可接受）。
- **前端**：学习页「知识卡片」入口 → 独立知识点卡片页（`Student` 状态 `knowledgeIdx`/`knowledgeDeck` + `viewKnowledge()`/`viewKnowledgeDeck()`，沿用 practice 视图模式）；卡片 3D `flip` + 左右滑动判 remember（touchmove 阈值 + 兜底按钮）；学习页显示打卡进度。改前端须 bump sw.js CACHE + app.py version。

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
| RPT-003 | student | P1 | AI 学习建议 → **v1.9.0 改「每日」生成**（`daily_advice` 表 + `GET /api/progress/advice` + launchd 每日脚本） |
| RPT-004 | teacher | P2 | 教师全班周报 → **v1.9.0 改为「班级活动」**（`/api/class/leaderboard` + 共性薄弱） |
| RPT-005 | 全部 | P2 | 导出 Markdown/PDF → **v1.9.0 移除**（周报整体废弃） |

**Technical**：周报功能整体废弃，`reports_bp` 保留但不再被前端引用；原内容拆分到「进度页」与「班级」。

### 3.7 班级 — `class_bp`（L3，REQ-CLASS，无 AI）
**Functional**
| REQ | 角色 | 优先级 | 说明 |
|-----|------|--------|------|
| CLASS-001 | 全部 | P1 | 班级归属：所有 active 学生（除 `Hermestest` 测试账号）同属一个班级，实名展示 |
| CLASS-002 | 全部 | P1 | 累计对话轮次 / 累计练习次数排行 |
| CLASS-003 | 全部 | P1 | 今日对话轮次 / 今日对话次数排行（今天 UTC+8） |
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
| 成本 | 限速 60/天/用户 + 单请求 ≤120s | 超限 429 |

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
> - **NFR-006**：`@rate_limit(60/day)` LLM 限速已实现（✅）

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
> - **班级活动「测评分数」下拉标题规范（v1.13.6，REQ-CLASS-004 强化）**：leaderboard 返回的 `quiz_list` 补 `label`（通过 `chapter_ids` 反查已发布 session → 「测评 · 第X周 第Y节」），前端 `quizChips` 改用 `q.label || q.title`——避免已发布但未改标题的测评在班级活动下拉显示难看的默认值「草稿 · X 章」（✅）。
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
| NFR-006 | 限速 | ≤60 LLM 调用/用户/天、单请求 ≤120s；超限 429 |
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


### 12.7 v1.17.0（2026-09-08）
- **REQ-KNOW-001/002/003 已实现**：按全章资料抽取个人知识卡片；独立卡片页支持 3D 翻转、左滑未记住/右滑记住及按钮兜底；记录学习次数和 1→3→7 间隔复习状态机。
- **PRACTICE-001 已实现覆盖强化**：全章按材料、分段多样化抽样，并在收敛题目时按 `sub_concept` 去重；知识点充足时练习题互不重复。

### 12.18 实现状态回写（v1.18.0，2026-09-08）
- **REQ-KNOW-001/002/003 已实现升级**：章节卡片在学习路径或资料发布时自动生成并共享；`knowledge_reviews` 按学生记录懒建复习状态、学习次数与 1→3→7 状态机，学生不再需要手动生成。
- **PRACTICE-001 已实现升级**：自主练习题数可选 **5-10（默认 5）**；除题干 hash 外，按当前章节过滤该学生跨会话已练 `sub_concept`，提示词和结果收敛均执行过滤。
