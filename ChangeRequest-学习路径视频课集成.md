# Change Request — 学习路径（8 周）集成 + 视频课挂载

> CR ID：CR-2026-0902-LPATH  
> 日期：2026-09-02  
> 上游：小白AI课程8周学习路径.md（草案，章节/模块已大致定稿）｜Design-Spec v2.0｜app v1.1.0  
> 状态：待评审 → 交执行 Agent 落地  
> 执行分工：**CC（Claude Code）= 代码轨道**；**Hermes（本地 AI / LLM 编排）= AI 内容与提示词轨道**  
> 关联 REQ 域：新增 `CURR`（学习路径结构）/ `VIDEO`（视频资源），扩展 `CHAT-010`

---

## 0. 背景与三条核心决策（必须先对齐，否则范围会跑偏）

1. **RAG 纯度红线（用户硬性要求）**：RAG 检索（当前实现为 `chunks` 表关键词/章节匹配，原设计 ChromaDB）**只处理资料文件**。视频课**绝不**写入 `chunks`、不走 embedding、不进向量库。
2. **视频课 = 结构化元数据，不是语料**：视频以「标题 / URL / 平台 / 描述 / 周次 / Session / 概念标签」存于新建 `video_resources` 表；学生自行点开外链观看，AI 对话**只做"相关推荐"，不把视频内容当知识源**。
3. **`sessions`（课程单元）≠ 现有 `chapters`（资料容器）**：
   - `chapters`（folder→chapter）维持不变，仍是资料组织与 RAG 召回的作用域单元。
   - 新增 `sessions` 表表达「第 N 周 / 第 M 节 / 目标 / 关联章节 / 概念标签 / 里程碑」，通过 `chapter_ids` 引用现有章节；视频挂到 session 上。
   - 语义区分：章节是"资料归类"，session 是"学习路径节点"。

---

## 1. Design Spec 需改动清单（精确章节 delta）

> 以下为交给执行 Agent 的规格修订点，按文档章节定位。

| # | 章节 | 改动 | 关键内容 |
|---|------|------|----------|
| D1 | §0.2 REQ ID 编码规则 | 新增两行 | `CURR` 学习路径结构；`VIDEO` 视频资源 |
| D2 | §0.1 决策摘要表 | 新增一行 | 「视频课挂载 → 结构化元数据 `video_resources`，不进 RAG；TUTOR 补充上下文」 |
| D3 | §2.1 模块—技术映射 | 新增一行 | `CURR/VIDEO → curriculum_bp（L3）；明确 video_resources 不进 ChromaDB/chunks` |
| D4 | §3 模块分布 | 新增 §3.10「学习路径与视频课 — `curriculum_bp`」 | Functional（CURR-001~004 / VIDEO-001~003）+ Technical 双栏，含 RAG 纯度声明 |
| D5 | §5 领域模型 | 新增 2 表 + ER | `sessions`、`video_resources`；ER 增加 `sessions—<chapters`、`sessions—<video_resources` |
| D6 | §6.1 Blueprint 表 | 新增 `curriculum_bp` | 前缀 `/api/curriculum`，路由见 §3 |
| D7 | §6.4 关键接口 | 新增 CURR/VIDEO 路由行 | 见 §5（API 契约） |
| D8 | §7.1 TUTOR 提示词 | 新增「相关视频课」补充上下文块 | `TUTOR_SYSTEM` 增加 `{{related_videos}}` 占位；指令：相关时推荐、绝不内联为答案、标注"学员自选观看" |
| D9 | §12 阶段化落地 | 新增「阶段四：学习路径 & 视频课」 | REQ 优先级：CURR/VIDEO P0；CHAT-010 P0（与 VIDEO-003 绑定） |
| D10 | §13.2 已知盲区 | 新增 1 条 🟡 | 外部视频链接可用性（B站/ima 可能失效），以资料库原文为准；链接不校验内容安全 |
| D11 | §14 追溯矩阵 | 新增 2 行 | `CURR-001~004 / VIDEO-001~003 → curriculum_bp`，状态机「—」（纯 CRUD） |
| D12 | §15 DoD | 新增验收项 | 见 §7 本 CR |

> 设计 Spec **结构/形态不变**（单体 Flask / 三 Agent / SQLite+chunks / waitress）。本 CR 仅新增 1 个 Blueprint + 2 张表，不引入新组件。

---

## 2. App 需改动清单（文件级，evidence-based）

### 后端（CC 轨道）
| 文件 | 改动 | 说明 |
|------|------|------|
| `backend/data/models.py` | 新增 `sessions` / `video_resources` 建表 + 索引（DDL 见 §4） | 在 `SCHEMA` 常量内追加，`idx_sessions_chapter`/`idx_videos_week_session` |
| `backend/data/seed.py` | 新增 `seed_curriculum()` | 写入 8 周 × 2 Session 的 `sessions` 行 + 约 30+ 条 `video_resources`（URL 来自白皮书，见 §6）。创建与路径对应的 `chapters` 文件夹便于映射 |
| `backend/api/curriculum.py` | **新建 Blueprint** | 路由见 §5；写操作 `@role_required("teacher")`，读操作全部可读 |
| `backend/app.py` | 注册 `curriculum_bp`（L43-52 区域） | `from api.curriculum import curriculum_bp` + `app.register_blueprint(curriculum_bp)`；版本 `version="1.2.0"`（L13，诚实版本规则） |
| `backend/ai/video_link.py` | **新建** | `retrieve_related_videos(con, chapter_ids, concept_tags) -> list[dict]`，确定性匹配（见 §6），**不调用 RAG/chunks** |
| `backend/ai/prompts.py` | `TUTOR_SYSTEM` 增加 `{{related_videos}}` 占位 + 推荐指令 | 仅注入标题/平台/URL，不注入视频"内容" |
| `backend/ai/tutor.py` | `tutor_orchestrate` 调 `retrieve_related_videos` 并注入；返回 `related_videos` | L47 之后插入；返回字典加 `related_videos` 字段（L39 签名） |
| `backend/api/conversations.py` | 消息响应 JSON 含 `related_videos` | 透传 `tutor_orchestrate` 返回的 `related_videos` |
| `CHANGELOG.md` | 追加 1.2.0 条目 | 按既有格式 |

### 前端（CC 轨道）
| 文件 | 改动 | 说明 |
|------|------|------|
| `backend/frontend/js/app.js` | `ICONS` 加 `path`；`tabbar()` 学生新增「路径」tab（key `path`）；`go()`/`boot()` hash 支持 | 教师端可在「管理」内嵌课程管理入口，或同样新增 tab |
| `backend/frontend/js/student.js` | 新增 `path` 视图 | 周→Session 手风琴：资料（链到章节/资料浏览）+ 视频（外链新标签）+「去提问」按钮（带 session 的 chapter_ids/concept 进对话） |
| `backend/frontend/js/student.js` | 对话页加「相关视频课」面板 | 渲染接口返回的 `related_videos` 为可点 chips |
| `backend/frontend/js/teacher.js` | 新增「课程管理」UI | Session CRUD 表单（周/节/标题/目标/章节多选/concept 标签）+ 视频 CRUD（标题/URL/平台/周/节/concept） |

### 测试（CC 轨道）
| 文件 | 改动 |
|------|------|
| `tests/test_curriculum.py`（新建） | Session/Video CRUD（教师可/学生 403）、学生总览可读性、视频不入 chunks |
| `tests/test_video_link.py`（新建） | 确定性匹配：按 chapter_id / concept_tags / week+session 命中；不上 RAG |
| `tests/test_isolation.py`（扩展） | 视频为共享资源，确认无 user_id 泄漏；会话可见性与角色无关 |
| `tests/test_tutor.py`（扩展） | TUTOR 响应含 `related_videos`；注入块仅含标题/URL，不含视频正文 |

---

## 3. 执行 Scope 拆分（交 Hermes 与 CC）

### Track B — Hermes（AI 内容与提示词轨道，先于 CC 交付"输入物"）
1. **抽取并校验种子数据**：从《小白AI课程8周学习路径.md》整理出结构化 JSON——8 周 × 2 Session（week_no/session_no/title/goal/concept_tags/milestone）+ 全部视频链接（title/url/platform/description/week_no/session_no/concept_tags）。**URL 必须逐条核对可访问性**，失效的标注并回退到"资料库原文"。
2. **概念标签词表**：主标签 `transformer / hallucination / agent / tool-calling / mcp`，允许自由扩展（vibe-coding / prompt / rag / deployment）。
3. **`TUTOR_SYSTEM` 视频补充块文案 + 护栏**：
   - 占位 `{{related_videos}}` 渲染为「【相关视频课（学员自选观看）】\n- <标题>(<平台>): <URL>」。
   - 指令：仅当话题相关时推荐；**不得**把 URL 当作答案内联；不得编造视频内容；外语/失效链接不提。
4. **`retrieve_related_videos` 匹配口径**：先按 `chapter_ids` 找所属 session → 取其视频；再按 `concept_tags` 与查询/会话标签重叠补召回；上限 3 条，按 `order_no` 排序。产出该函数的"预期行为规格"（作为 CC 实现契约）。

> Hermes 交付物：`seed_curriculum.json`（数据）+ `TUTOR_VIDEO_BLOCK`（提示词文本）+ `video_link_spec.md`（匹配规格）。CC 据此实现。

### Track A — CC（Claude Code，代码轨道）
1. 按 §4 DDL 建表；按 §5 实现 `curriculum_bp`；注册到 `app.py` 并 bump 版本。
2. 实现 `ai/video_link.py`（严格遵循 Hermes 的 `video_link_spec.md`，**禁止**调用 `rag.retrieve`）。
3. 改造 `tutor.py` + `prompts.py` + `conversations.py` 注入/透传 `related_videos`。
4. 前端 `path` 页 + 教师课程管理 + 对话视频面板。
5. 补测试；本地 `pytest` 全绿；`flask` 启动自测 `/api/curriculum` 与对话返回 `related_videos`。
6. 更新 `CHANGELOG.md`。

** handoff 接口**：Hermes 产出 `seed_curriculum.json` + 提示词块 + 匹配规格 → CC 消费。两者并行可启动，但 CC 的 seed 与 tutor 改造需等 Hermes 数据/规格落地。

---

## 4. 数据模型增量（DDL）

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    week_no      INTEGER NOT NULL,
    session_no   INTEGER NOT NULL,
    title        TEXT NOT NULL,
    goal         TEXT NOT NULL DEFAULT '',
    chapter_ids  TEXT NOT NULL DEFAULT '[]',   -- JSON 数组，引用 chapters.id
    concept_tags TEXT NOT NULL DEFAULT '[]',   -- JSON 数组，如 ["transformer","hallucination"]
    milestone    TEXT DEFAULT '',
    order_no     INTEGER NOT NULL DEFAULT 0,
    created_by   TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_resources (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    platform     TEXT NOT NULL DEFAULT '',     -- bilibili / ima / others
    description  TEXT NOT NULL DEFAULT '',
    week_no      INTEGER,
    session_no   INTEGER,                       -- NULL = 整周
    concept_tags TEXT NOT NULL DEFAULT '[]',
    order_no     INTEGER NOT NULL DEFAULT 0,
    created_by   TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_week ON sessions(week_no, session_no);
CREATE INDEX IF NOT EXISTS idx_videos_ws ON video_resources(week_no, session_no);
```

> `materials` / `chapters` / `chunks` **不动**。视频与资料的唯一关联是 session 上的 `chapter_ids`（间接），视频本身零向量化。

---

## 5. API 契约增量（`curriculum_bp`，前缀 `/api/curriculum`）

| Method & Path | 角色 | 说明 | REQ |
|---|---|---|---|
| `GET /api/curriculum` | 全部 | 学习路径总览：weeks→sessions（含 materials 列表[由 chapter_ids 聚合] + videos 列表） | CURR-002 |
| `POST /api/curriculum/sessions` | teacher | 建 Session | CURR-001 |
| `PUT /api/curriculum/sessions/:id` | teacher | 改 Session | CURR-001 |
| `DELETE /api/curriculum/sessions/:id` | teacher | 删 Session | CURR-001 |
| `POST /api/curriculum/videos` | teacher | 建视频 | VIDEO-001 |
| `PUT /api/curriculum/videos/:id` | teacher | 改视频 | VIDEO-001 |
| `DELETE /api/curriculum/videos/:id` | teacher | 删视频 | VIDEO-001 |
| `GET /api/curriculum/videos` | 全部 | 视频列表（学生按 Session 过滤展示） | VIDEO-002 |

- 鉴权：写 `@role_required("teacher")`；读 `@jwt_required`（全部可读，视频/路径为共享资源，**不**经 `@user_scope`）。
- 错误码复用 `E_AUTH_*` / `E_ROLE_*` / `E_INVALID_INPUT` / `E_NOT_FOUND`；视频 URL 不强制可达校验（盲区 D10）。
- 对话接口 `POST /api/conversations/:id/message` 响应新增字段 `related_videos: [{title,url,platform}]`（CHAT-010 / VIDEO-003）。

---

## 6. TUTOR 视频融合设计（确定性，不进 RAG）

```
学生进入某 Session 的"去提问"
   → 取 session.chapter_ids[0] 作为 RAG 作用域（维持原 chunks 召回）
   → 同时取 session.concept_tags + chapter_ids
   → video_link.retrieve_related_videos(chapter_ids, concept_tags)
       ① 按 chapter_ids 反查所属 sessions → 取其 video_resources
       ② 按 concept_tags 重叠补召回（查询/会话标签）
       ③ 取 order_no 前 3 条，返回 [{title,url,platform}]
   → 注入 TUTOR_SYSTEM {{related_videos}} 作为"补充推荐上下文"
   → TUTOR 仅在相关时向学生推荐，并标注"学员自选观看"
   → 响应透传 related_videos 供前端面板渲染
```

**护栏（红线）**：
- `video_link` **禁止** import `ai.rag`；纯 SQL + 标签匹配，O(视频总数≈30)，零延迟。
- TUTOR 不得把视频 URL 当作事实答案内联；不得编造视频标题/内容。
- 召回为空时静默（不报错、不降级），视频是"锦上添花"非必需。

---

## 7. 验收 DoD（新增，追加到 Design Spec §15）

**阶段四：学习路径 & 视频课**
- [ ] CURR-001/002：教师可建/改/删 Session；学生 `GET /api/curriculum` 看到 8 周结构（周→Session→资料+视频）
- [ ] VIDEO-001/002：教师可增删改视频；学生按 Session 看到视频列表，点击新标签打开外链
- [ ] VIDEO-003 + CHAT-010：进入 Session 提问时，对话响应含 `related_videos`；`ai.video_link` 未 import `ai.rag`（RAG 纯度）
- [ ] 数据隔离：视频/路径为共享资源，学生读取不依赖 `@user_scope`；无 user_id 字段泄漏（扩展 test_isolation）
- [ ] 回归：既有 P0/P1 测试全绿；版本号 `1.2.0`；CHANGELOG 已记

---

## 8. 风险 / 盲区 / 开放问题

| 项 | 等级 | 处理 |
|---|---|---|
| 外部视频链接失效（B站/ima） | 🟡 | 盲区 D10；链接失效以资料库原文为准；seed 时 Hermes 逐条核验 |
| 视频内容不可控（非自托管） | 🟡 | 仅作"外链推荐"，绝不作为知识源；不校验内容安全 |
| session 多章节 → RAG 单 chapter_id | ⚪ | 取 `chapter_ids[0]` 作 RAG 作用域，视频匹配用全部；后续可扩展多章并集 |
| 白皮书未定稿 | ⚪ | 结构已稳定；seed 用当前版本，定稿后教师后台微调即可（CURR-001 已覆盖） |
| 概念标签体系 | ⚪ | 先 5 主标签，自由扩展；不做强制词表校验 |

---

## 9. 版本与文档

- `backend/app.py` `version` → `"1.2.0"`（诚实版本规则，L12-13 注释）。
- `CHANGELOG.md` 追加：`1.2.0 — 学习路径(8周)集成 + 视频课挂载（CURR/VIDEO），RAG 纯度保持`。
- Design Spec 按 §1（D1–D12）修订至 v2.1；本 CR 闭合后归档。
