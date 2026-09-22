# 学习路径集成 · 执行方案（Design-Spec v2.1 增量 + CC 任务书）

> CR：`ChangeRequest-学习路径视频课集成.md` 已定稿结构。本文为**执行层细化**，在 CR 基础上新增用户拍板的**发布状态机**。
> 分工：**CC（Claude Code）= 代码轨道**；Hermes = 编排/验收 + 后续 seed 数据注入。
> 状态：**先实现机制，不灌数据**（课件仍在 WIP，用户确认后再注入）。

---

## 0. 用户决策（已拍板，作为唯一约束）

| # | 决策 | 落地 |
|---|------|------|
| 1 | 发布单元 = **Session（整包）** | `sessions.status ∈ {draft, published}`；发布/取消发布为 session 级开关 |
| 2 | 预置内容**进现有 `chapters`/`materials` 表，加 `status` 列** | 现有数据默认 `published`（不改变现状）；预置导入默认 `draft`（学生隐藏） |
| 3 | 内容可见性**跟随所属 session 状态** | 上传到已发布 session → `published`（立即可见）；上传到未发布 session → `draft`，等该 session 发布才可见 |

**核心状态机（相对 CR「全部可读」的重要修订）**：
> session 是发布源，内容状态由所属 session 驱动。
> `sessions.status` = `draft ─[发布]─► published`；其下内容（章节/资料/视频）随 session 同步可见性。
> 普通内容（老师手动建、不归属 session）默认 `published`，始终可见（延续现状）。

---

## 1. REQ 域增量（Design-Spec §0.2 编码规则）

| 域 | 含义 | 来源 | REQ |
|----|------|------|-----|
| `CURR` | 学习路径结构 | CR | CURR-001~004 |
| `VIDEO` | 视频资源 | CR | VIDEO-001~003 |

扩展：`CHAT-010`（对话响应返回 `related_videos`，绑定 VIDEO-003）。

---

## 2. 数据结构（Design-Spec §5 / §5.3 状态机）

### 2.1 新增表（对齐 CR §4 DDL + status 列）

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    week_no      INTEGER NOT NULL,
    session_no   INTEGER NOT NULL,
    title        TEXT NOT NULL,
    goal         TEXT NOT NULL DEFAULT '',
    chapter_ids  TEXT NOT NULL DEFAULT '[]',   -- JSON 数组，引用 chapters.id（预置时唯一归属，消除多 session 歧义）
    concept_tags TEXT NOT NULL DEFAULT '[]',
    milestone    TEXT DEFAULT '',
    order_no     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    created_by   TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_resources (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    platform     TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    week_no      INTEGER,
    session_no   INTEGER,
    concept_tags TEXT NOT NULL DEFAULT '[]',
    order_no     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    created_by   TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_week ON sessions(week_no, session_no);
CREATE INDEX IF NOT EXISTS idx_videos_ws ON video_resources(week_no, session_no);
```

### 2.2 现有表加列（含迁移）
- `chapters` / `materials` 各加 `status TEXT NOT NULL DEFAULT 'published'`（SQLite `ALTER TABLE ADD COLUMN`；现有行自动 `'published'`，不破坏现状）。
- `video_resources` 不进 RAG/chunks/embedding（RAG 纯度红线）。

### 2.3 状态机（Design-Spec §5.3 追加）
- **session**：`draft ─[发布]─► published`（发布时**同步其下内容 status → published**）；`published ─[取消发布]─► draft`（其下内容回 draft，可选）。
- **内容可见性**：`status='published'` 才对学生可见；`status='draft'` 仅教师后台可见。
- 现有 quiz / review_items / 软删除状态机不变。

---

## 3. API 契约（新增 `curriculum_bp`，前缀 `/api/curriculum`）

| Method & Path | 角色 | 说明 | REQ |
|---|---|---|---|
| `GET /api/curriculum` | 全部 | 学习路径总览：weeks→sessions（**只含 `status='published'`**；每 session 带关联章节资料列表 + 视频列表） | CURR-002 |
| `POST /api/curriculum/sessions` | teacher | 建 Session（status=draft） | CURR-001 |
| `PUT /api/curriculum/sessions/:id` | teacher | 改 Session | CURR-001 |
| `DELETE /api/curriculum/sessions/:id` | teacher | 删 Session（级联删其视频；章节/资料保留或软标 —— 见 `**` 说明） | CURR-001 |
| `POST /api/curriculum/sessions/:id/publish` | teacher | **发布**：session.status='published'，其下 content.status 同步='published' | CURR-003 |
| `POST /api/curriculum/sessions/:id/unpublish` | teacher | **取消发布**（可选）：回 draft，content 随动 | CURR-003 |
| `POST /api/curriculum/videos` | teacher | 建视频（status 随所属 session；session 为 draft 则 draft，published 则 published） | VIDEO-001 |
| `PUT /api/curriculum/videos/:id` | teacher | 改视频 | VIDEO-001 |
| `DELETE /api/curriculum/videos/:id` | teacher | 删视频 | VIDEO-001 |
| `GET /api/curriculum/videos` | 全部 | 视频列表（学生只见 `status='published'`） | VIDEO-002 |

> `**` 关于「会话删除是否级联删章节/资料」：**推荐不硬删**——会话删除仅删 session 与视频；其下章节/资料若不被其他 published session 引用，教师可另行处理（避免误删全班数据，延续 F7 软删精神）。CC 执行时如无法干净判定，**保留章节/资料，只在教师端提示**。

### 3.1 现有接口加过滤（学生可见性）
- `GET /api/chapters`：学生仅返回 `status='published'` 的章节；教师返回全部。
- `GET /api/materials`：学生仅返回 `status='published'` 且 `is_deleted=0`；教师返回全部（含 draft）。
- 鉴权：写 `@role_required("teacher")`；读 `@jwt_required`。视频/路径为共享资源，**不**经 `@user_scope`。

### 3.2 RAG 纯度
- `ai/video_link.py` **禁止** import `ai.rag` / 触达 `chunks`；纯 SQL + 标签匹配。

---

## 4. 前端

- **`app.js`**：`ICONS` 加 `path`；`tabbar()`（学生）加「路径」tab（key `path`）；`go()`/`boot()` hash 支持。
- **`student.js`**：新增 `path` 视图（周→Session 手风琴：资料外链/链到章节 + 视频新标签 + 「去提问」带 chapter_ids/concept 进对话）；对话页加「相关视频课」面板（渲染 `related_videos` chips）。
- **`teacher.js`**：新增「课程管理」——Session CRUD 表单（周/节/标题/目标/章节多选/concept）+ **发布/取消发布按钮**；视频 CRUD（标题/URL/平台/周/节/concept）。

---

## 5. CC 改动清单（文件级）

**后端**
| 文件 | 改动 |
|------|------|
| `backend/data/models.py` | `SCHEMA` 追加 `sessions`/`video_resources` 建表 + 索引；`chapters`/`materials` 加 `status` 列（迁移） |
| `backend/api/curriculum.py` | **新建** Blueprint（§3 全部路由 + publish/unpublish 联动） |
| `backend/api/chapters.py` | `GET` 学生过滤 `status='published'` |
| `backend/api/materials.py` | `GET` 学生过滤 `status='published'` |
| `backend/ai/video_link.py` | **新建** `retrieve_related_videos(chapter_ids, concept_tags)`，确定性匹配，**禁 import rag** |
| `backend/ai/prompts.py` | `TUTOR_SYSTEM` 增 `{{related_videos}}` 占位 + 推荐指令（仅标题/平台/URL，不内联内容） |
| `backend/ai/tutor.py` | 调 `retrieve_related_videos` 注入；响应加 `related_videos` 字段 |
| `backend/api/conversations.py` | 消息响应透传 `related_videos` |
| `backend/app.py` | 注册 `curriculum_bp`；`version="1.2.0"`（诚实版本规则） |
| `backend/data/seed.py` | **留接口空实现** `seed_curriculum()`（等用户 data，不灌真实数据） |
| `CHANGELOG.md` | 追加 1.2.0 条目（学习路径 + 视频课 + 发布状态机） |

**前端**：`app.js`（path tab）、`student.js`（path 页 + 视频面板）、`teacher.js`（课程管理 + 发布按钮）。

**测试**：`tests/test_curriculum.py`（Session/Video CRUD 教师可、学生 403 写；学生总览只见 published；发布后内容可见）、`tests/test_video_link.py`（确定性匹配、不触 rag）、`tests/test_isolation.py`（视频共享、无 user_id 泄漏）、`tests/test_tutor.py`（响应含 related_videos、不含视频正文）。

---

## 6. 验收 DoD（追加 Design-Spec §15）

- [ ] CURR-001/002：教师建/改/删 Session；学生 `GET /api/curriculum` 只见 **published** session（周→节→资料+视频）
- [ ] CURR-003：发布 Session → 其下 `chapters`/`materials`/`video_resources` status 同步 `published`，学生立即可见；取消发布回 draft
- [ ] VIDEO-001/002：教师增删改视频；学生按 Session 看 published 视频，新标签打开外链
- [ ] VIDEO-003/CHAT-010：进 Session 提问，对话响应含 `related_videos`；`ai/video_link` 未 import `ai.rag`
- [ ] 数据隔离：视频/路径共享，无 user_id 泄漏；学生读仅 published（draft 隐藏）
- [ ] 回归：既有 P0/P1 测试全绿；版本号 `1.2.0`；CHANGELOG 已记
- [ ] `make lint test smoke` 全绿；`/health` 返回 1.2.0

---

## 7. 约束（CLAUDE.md §2 手术式 + 本项目红线）

1. 只改解决此需求所需代码，不重构无关功能、不引入新依赖。
2. **不引入 torch/ChromaDB**（RAG 保持 SQLite chunks 关键词匹配对齐 F4）。
3. 视频/路径**绝不**写入 `chunks` / embedding（RAG 纯度红线）。
4. 中文注释只注关键逻辑；`py_compile` + `make lint` 通过。
5. **版本号诚实规则**：`backend/app.py` version → `1.2.0`（新功能）；同 commit CHANGELOG + Design-Spec（§0.2 REQ 域 / §5.3 状态机 / §6.1 Blueprint / §15 DoD）同步回写。
6. **不要 push**（supervisor 会推）。改完 commit（Conventional Commits）。
7. **不要灌真实课件数据**（用户 WIP，等确认）。`seed_curriculum()` 留接口；真实数据由 Hermes 后续注入。
