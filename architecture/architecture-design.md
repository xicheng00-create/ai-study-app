# AI 学习小组 App — 系统架构设计

> 版本：v1.1（v1.0 架构 + 2026-09-02 pm-toolkit 再审修订）
> 日期：2026-09-02
> 状态：架构评审（再审有条件通过，待教师确认）
> 配套：PRD-AI学习小组app.md（v2.1） / prototype/index.html（v2.1） / architecture-diagram.svg
> 范围：4 用户（1 教师 + 3 学生）私有化部署，iMac 常驻 + Cloudflare 隧道

---

## 〇、决策摘要（先看这节）

| 维度 | 决策 | 一句话理由 |
|---|---|---|
| 整体风格 | **单体 Flask + waitress（单进程 / 4 线程）** | 4 人并发压力极小，部署运维最简；"单进程"≠单线程，waitress 默认 4 线程支撑 4 人并发 |
| AI 编排 | **极简三 Agent 提示词**（TUTOR / QUIZZER / GRADER） | 不引入工具注册表与 ReAct；函数即工具 |
| RAG 检索 | **纯向量**（ChromaDB cosine + chapter_id 过滤） | 继承 v1；资料量 ≤500MB，纯向量足够 |
| AI 质量门禁 | **本期不做 Evals** | 4 人规模靠 DoD 人工验收兜底；见 §十三盲区 |
| 部署进程 | **waitress 单进程 + launchd KeepAlive** | 8GB 内存下常驻 <1.5GB，**但需实测**；自启用 LaunchDaemon 而非 LaunchAgent（见 §三/§十三 F1/F4） |
| 借鉴 ChemAI | 引导式 / 巩固闭环 / 轻量审核 / SQLite WAL+ChromaDB / "监理"思想降维 | 详见 §十二 |
| 不引入 | ReAct / OCR 管道 / 四维审核 / Docker / 知识图谱 / 多客户端 / 三层评测 111 场景 | 4 人明显过度 |

---

## 一、架构原则（为什么"简"在这里是对的）

1. **KISS for 4** — 用户规模 = 一切复杂度判断的第一约束。4 用户、≤500MB 资料、单机部署，决定了"分布式/微服务/Docker/知识图谱"全部是反模式。
2. **YAGNI** — PRD 明确列入"非目标"的项（原生 App / 公网注册 / MySQL / 治理类 / 家长端）一律不做；任何"未来扩展"先不做，等真用到再补。
3. **降级保守** — AI 不确定时向保守侧兜底（拒绝 / 转人工 / 固定引导语），绝不静默给结论（对应 aicoding-toolkit 红线 #1）。
4. **状态机优先** — 任何有生命周期的业务实体（quiz `draft→published`、review `pending→done`、conversation 轮次）用状态机建模，非法转换路径必须显式测试（红线 #3）。
5. **借鉴而非复刻** — ChemAI 复杂版的"工具工厂化 / 三层 Fallback / 监理端护栏 / Checkpoint 备份"是**思想**而非**组件**；我们取其神（治理/降级/可恢复），不照搬其形（ReAct/OCR/四维审核/Docker）。
6. **Evals 风险显式化** — aicoding-toolkit 红线 #5 要求"Evals 先行 + 基线只升不降"。本期经确认**不做 Evals**（§0 决策），但必须在文档显式登记为已知盲区，触发条件出现时立即补做（见 §十三）。

---

## 二、总体架构（5 层 + 2 横切）

```
┌─────────────────────────────────────────────────────────────┐
│ L1 表现层  PWA（学生/教师，H5+ServiceWorker，离线 App Shell） │
├─────────────────────────────────────────────────────────────┤
│ L2 接入层  Cloudflare 命名隧道（固定 HTTPS 域名，仅 5001）   │
├─────────────────────────────────────────────────────────────┤
│ L3 应用层  Flask 单进程（waitress，单进程/4 线程）           │
│            ├ 静态托管 (/) + PWA shell                        │
│            ├ /api/* 路由 (JWT + 角色 + 限速 中间件)          │
│            ├ 业务服务: auth/materials/chapters/conversations │
│            │            /quizzes/attempts/progress/reports/teacher│
│            └ AI 服务: rag / agent_orchestrator / review_sched│
├─────────────────────────────────────────────────────────────┤
│ L4 AI 能力层  DeepSeek API（外部） + all-MiniLM-L6-v2（本地）│
├─────────────────────────────────────────────────────────────┤
│ L5 数据层  SQLite WAL + ChromaDB + uploads/                  │
└─────────────────────────────────────────────────────────────┘
横切: A) 安全护栏(JWT/角色/限速/输入校验)  B) 可观测+备份(/health, launchd, iCloud rsync)
```

详见 `architecture-diagram.svg`。

---

## 三、部署架构

```
同学手机浏览器 ──HTTPS──► Cloudflare 命名隧道 (ai-study.<域>)
                                    │
                                    ▼
                     iMac:127.0.0.1:5001 (仅本机)
                                    │
                                    ▼
                     waitress 包裹的 Flask app.py
                       (caffeinate -ims 防休眠)
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                      ▼
        SQLite (WAL)          ChromaDB               uploads/
        instance/...db        chroma_db/             files/

launchd KeepAlive 崩溃自动拉起
  ⚠️ **自启方式（F1 / pm17 事前验尸）**：PRD §9.3 用 `~/Library/LaunchAgents`（登录后自启）。iMac 若重启后**无人登录**，服务不启动 → 同学打开隧道超时。**改为 `/Library/LaunchDaemons`（开机即跑，无需登录）更稳**；若坚持 LaunchAgent，PRD §2.3 须约定"iMac 保持登录会话"。
iCloud Drive 每日 rsync 备份 (DB + chroma + uploads)
  ⚠️ **备份一致性（F2 / pm17+pm38）**：rsync 直接拷正在写入的 SQLite 可能拷到 half-write 文件 → 还原损坏。备份前先 `PRAGMA wal_checkpoint(TRUNCATE)`（或 `sqlite3 .backup`）刷盘，再 rsync（见 §十）。
```

**关键约束（来自 PRD §2.1/§2.2/§9.4，本架构刚性遵守）**：
- 隧道仅暴露 5001；iMac 防火墙不对外开端口
- `FLASK_ENV=production` 强制 `debug=False`（Werkzeug debugger 不暴露公网）
- 物理限制：iMac 断电即停 — 属约定项，不属架构可解项
- 备份目标唯一：iCloud Drive（同账号同步开启），不落外接盘

---

## 四、应用层模块划分（Flask Blueprint 粒度）

| Blueprint | 路径前缀 | 主要路由 | 鉴权 |
|---|---|---|---|
| `auth_bp` | `/api/auth` | login, refresh, me, register(teacher only) | 公开 / Bearer |
| `chapters_bp` | `/api/chapters` | 章节 CRUD | 教师写，全部读 |
| `materials_bp` | `/api/materials` | 上传/解析/列表/删除 | 教师写，全部读 |
| `conversations_bp` | `/api/conversations` | 对话 CRUD + 引导式问答（SSE 占位） | 学生本人 |
| `quizzes_bp` | `/api/quizzes` | 教师生成草稿/确认发布；学生作答/批改 | 教师发布，学生作答 |
| `attempts_bp` | `/api/attempts` | 作答记录（自动注入 user_id） | 学生本人 |
| `progress_bp` | `/api/progress` | 掌握度 M / 四态 / 薄弱点 / 巩固练习 | 学生本人 + 教师聚合 |
| `reports_bp` | `/api/reports` | 周报生成（本人） | 学生本人 |
| `teacher_bp` | `/api/teacher` | 全班概览 / 某学生详情 | 教师 |
| `health_bp` | `/health` | 探活 | 公开（仅返 up/down） |

**共享中间件 / 装饰器**（横切 A）：
- `@jwt_required` — 解析 Bearer token，注入 `g.user_id, g.role`
- `@role_required("teacher")` — 角色门禁（学生访问教师路由 → 403）
- `@rate_limit(60/day)` — 成本护栏（PRD §十三）
- `@validate_json(schema)` — 入参 schema 校验
- `@user_scope` — 读操作自动按 `user_id` 过滤（防越权读他人数据）

**错误码契约**（PRD 风格 `{"code":0,"data":...}` / 失败 `{"code":E,"msg":...}`）：
- `E_AUTH_*` 鉴权失败 / `E_ROLE_*` 角色不符 / `E_RATE` 限速 / `E_NOT_FOUND` / `E_INVALID_INPUT` / `E_AI_FALLBACK` AI 兜底触发 / `E_INTERNAL`

---

## 五、AI 能力架构（核心，最简化形态）

### 5.1 三 Agent 提示词即一切

```python
# ai/prompts.py（伪代码，仅示意）
TUTOR_SYSTEM = """你是苏格拉底式辅导老师。
- 学生人设: {student_grade}, 薄弱章: {weak_chapters}
- 资料依据: {retrieved_chunks}
- 规则: 不直接给答案,以追问引导;学生答对或明确卡住才给点拨
- 护栏: 本次辅导轮次 {turn}/{max_turn=12};超限请转「给结论+推荐练习」"""

QUIZZER_SYSTEM = """你是出题老师。
- 章节: {chapter_ids};子概念: {sub_concepts}
- 题型/难度/数量: {spec}
- 产出: 结构化 JSON 题目集(含 answer_key 与 sub_concept)"""

GRADER_SYSTEM = """你是批改老师。
- 题目+参考答案: {question}
- 学生作答: {student_answer}
- 产出: {correct: 0|1, score: 0..1, reason: str}"""
```

**为什么是"提示词即一切"而不是"工具注册表"**：
- 决策 §0 已确认不要注册表。ChemAI 工具工厂化适合 25+5 工具、4 角色、跨域调用的复杂场景；我们 3 个 Agent、零工具调用、纯文本生成，注册表是负收益。
- 但保留"函数即工具"的统一签名 `def tool_x(ctx) -> Result`，将来若 Agent 超过 5 个或出现多步推理，再升级为注册表（演进路径 §十四）。

### 5.2 引导式对话编排（功能 2）

```
学生发问 ─► 加载学生人设 (grade, weak_chapters) ─► 选对话范围 (chapter_id)
       ─► 检索召回 (ChromaDB top-k, chapter_id 过滤)
       ─► 注入 TUTOR_SYSTEM + 历史消息(≤12 轮)
       ─► DeepSeek 生成
       ─► (若 turn==12) 强制注入「给结论+推荐练习」转交
       ─► 写回 conversations/messages
```

**护栏**（aicoding-toolkit 红线 #1 "AI 不确定即兜底"）：
- DeepSeek 超时/报错 → 兜底"资料加载中，请稍后再试"+ 不写错误对话
- 检索召回为空 → 兜底"未在资料中找到相关内容"+ 建议切换章节
- 检测到学生越界（请求做题 / 请求答案）→ 意图路由分流到 QUIZZER / 引导式点拨

### 5.3 教师发布测评（功能 3，轻量审核）

```
教师选章+题型 ─► LLM(QUIZZER) ─► 草稿 quiz(status=draft, questions[] 教师可见)
            ─► 教师预览/微调 ─► 教师点击确认 ─► quiz.status=published, published_at, confirmed_at
            ─► 学生列表只显示 status=published
```

状态机（红线 #3 "状态机优先"）：
```
draft ──[教师确认]──► published
published ──[教师重出]──► superseded (旧版本保留, 新 version 走 draft→published)
```

### 5.4 巩固练习闭环（功能 4.6，借 ChemAI 错因诊断+间隔复习）

```
学生进度页 ─► 计算 M (章节) ─► 识别薄弱章 (M<50)
        ─► 一键"生成巩固练习" ─► LLM(QUIZZER) 基于薄弱章出题
        ─► 写入 attempts + review_items(next_review_at=now+1d, interval_days=1)
        ─► 每日调度 (cron/launchd 轻量任务) 扫描 review_items
        ─► 到期项推送给学生;学生完成/跳过
        ─► 答对 → interval_days *= 3 顺延 (1→3→7 天)
        ─► 答错 → interval_days 重置为 1, 重新进入循环
```

调度实现：复用 launchd，每天一次扫描；不引入 Celery / Redis（4 人用杀鸡刀）。

### 5.5 借鉴 ChemAI 的"三层 Fallback"（降维实现两层即可）

| 层级 | ChemAI | 本期 |
|---|---|---|
| L1 | LLM | DeepSeek 生成 |
| L2 | 模板回答 | TUTOR 提示词内的固定引导语池（按意图/章节预生成） |
| L3 | 固定答案 | 不做（4 人没意义，宁可报错也不静默错答） |

**触发条件**（任意满足即降级到下一层）：
- DeepSeek API 超时 > 30s / 5xx
- 响应包含敏感词 / 越界内容
- 检索召回为空且学生问题超出资料范围

---

## 六、RAG 流水线

### 6.1 离线入索引（教师上传时同步执行）

```
PDF/PPTX/DOCX/MD/TXT
   │  pdfplumber / python-pptx / python-docx / 原样
   ▼
文本分块 (chunk_size≈500, overlap≈80, 按章节切优先)
   │  每块带 metadata: {material_id, chapter_id, page_no, chunk_idx}
   ▼
all-MiniLM-L6-v2.encode() (本地, batch)
   ▼
ChromaDB.add(ids, embeddings, documents, metadatas)
   │  collection=material_chunks
   │  metadata filter: chapter_id 必备
   ▼
SQLite.materials.chunk_count 更新 (便于前端展示"已解析")
```

### 6.2 在线召回

```python
def retrieve(query: str, chapter_id: str|None, top_k=5) -> list[Chunk]:
    q_emb = embedder.encode([query])[0]
    where = {"chapter_id": chapter_id} if chapter_id else None
    res = chroma_collection.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        where=where,
        include=["documents","metadatas","distances"]
    )
    # cosine distance → 取阈值 0.6 内；过弱则视为召回不足（触发兜底）
    return [c for c in res["documents"][0] if 1-res["distances"][0][i] >= 0.4]
```

**为什么不加 BM25 / HyDE**（决策 §0）：
- 纯向量在 4 人、≤500MB 资料、章节粒度召回场景下命中率已 >85%（v1 经验）
- BM25 增加一套索引与查询路径，复杂度 +1 文件、收益边际
- HyDE 每次查询多 1 次 LLM，延迟 +2-3s，违反 PRD §十三 "首字 ≤3s" 目标

---

## 七、数据模型（精简视图，完整字段见 PRD §7）

```
users ─< chapters
users ─< conversations ─< messages
chapters ─< materials ─(向量)─► ChromaDB material_chunks
chapters ─< quizzes ─< questions ─< attempts >─ users
users ─< review_items >─ chapters
users ─< reports
```

**关键设计点**：
- `quizzes` 移除 `user_id`（题目全班共用）；新增 `status`/`version`/`teacher_id`/`confirmed_at`
- `attempts` 才是按学生隔离的，作答记录是掌握度 M 的唯一数据源
- **`attempts` 必须带 `quiz_version`**（PRD §7 未列，再审补）：教师重出题生成新 `version` 后，M 按 `(chapter_id, quiz_version)` 聚合、**只取该章最新已发布 version** 的成绩，避免旧版成绩污染掌握度（F3 / pm34 状态机）
- `review_items` 间隔复习状态机：`pending` ──[到期+学生完成]──► `done` ──[重错]──► `pending(interval=1)`
- ChromaDB `material_chunks` 的 `chapter_id` 是按章召回 + 掌握度溯源的唯一桥梁
- 不引入知识图谱 / 错因标签表（4 人过度，4 章以内错因靠 attempts 即可重建）

---

## 八、关键流程时序

### 8.1 引导式对话（功能 2）

```
Student  PWA        Flask          ChromaDB       DeepSeek
  │         │            │              │              │
  │ 提问+Q  │            │              │              │
  ├────────►│            │              │              │
  │         │ JWT校验+人设加载         │              │
  │         │ 检索 (chapter_id)        │              │
  │         ├───────────►│              │              │
  │         │◄── chunks ─┤              │              │
  │         │ 拼 TUTOR_SYSTEM+history  │              │
  │         ├─────────────────────────┼──────────────►│
  │         │◄── SSE 逐 token ────────────────────────┤
  │◄────────┤            │              │              │
  │         │ 写 messages              │              │
```

### 8.2 教师发布测评（功能 3）

```
Teacher  PWA        Flask          DeepSeek      DB
  │         │            │              │         │
  │ 选章+规格│            │              │         │
  ├────────►│            │              │         │
  │         │ 鉴权+教师角色              │         │
  │         │ quiz.status=draft          │         │
  │         │ 生成 questions[]           │         │
  │         ├───────────►│              │         │
  │         │◄─ 草稿 ────┤              │         │
  │         │ INSERT draft + questions  │         │
  │         ├──────────────────────────┼────────►│
  │ 预览/微调│            │              │         │
  │ 点击确认 │            │              │         │
  ├────────►│            │              │         │
  │         │ UPDATE status=published   │         │
  │         │ published_at, confirmed_at│         │
  │         ├──────────────────────────┼────────►│
  │◄── 成功 ─┤           │              │         │
```

### 8.3 巩固练习闭环（功能 4.6）

```
Student  PWA        Flask          DeepSeek     DB
  │         │            │              │         │
  │ 一键巩固 │            │              │         │
  ├────────►│            │              │         │
  │         │ 算 M, 找薄弱章             │         │
  │         │ LLM(QUIZZER) 出巩固题      │         │
  │         ├───────────►│              │         │
  │         │◄── questions ─┤            │         │
  │         │ INSERT review_items(interval=1)     │
  │         ├──────────────────────────┼────────►│
  │ 作答+批改│            │              │         │
  ├────────►│            │              │         │
  │         │ 写 attempts, 算新 M        │         │
  │         │ review_items: 对→interval*3,错→1     │
  │◄── 答对 3 天后再推 ──┤              │         │
  (每日 launchd 扫描 review_items 到期项)
```

---

## 九、安全与护栏（降维版"监理端"）

ChemAI 监理端包含：JWT 4 角色 + 权限矩阵 + 运行护栏 + 内容安全 + 测试指标 + 15s 心跳 + Checkpoint。我们降维为：

| ChemAI 监理项 | 本期实现 | 理由 |
|---|---|---|
| JWT 4 角色 + 权限矩阵 | JWT 2 角色 (teacher/student) + `@role_required` | 4 人无需 4 角色 + 矩阵 |
| 运行护栏（限速/调去重） | `@rate_limit(60/day)` + 重复请求 5s 去重 | 成本护栏足够 |
| 审批门禁 | 草稿→确认发布 | 等价于教师人工审批 |
| 迷幻控制 B123 / 内容安全 | 入参长度限制 + 简单敏感词列表 | 4 人风险面窄 |
| Checkpoint 持久化 | iCloud Drive 每日 rsync | 等价于离线 Checkpoint |
| 15s 心跳 | `/health` 探活 + launchd KeepAlive | 探活 + 自动拉起 |

**数据隔离硬约束**（PRD §6.3 强化）：
- 所有读操作必须经过 `@user_scope`，自动注入 `WHERE user_id = g.user_id`
- 教师聚合走 `/api/teacher/*` 独立路由，**不**通过 `@user_scope` 过滤
- 测试用例必须包含"学生 A 尝试读学生 B 数据 → 403/空"用例（集成测试清单见 §十六 F9）

**补充护栏（pm26 安全审核 + pm23 权限，再审新增）**：
- **TUTOR 输出护栏（F5）**：TUTOR 仅 prompt 注入召回 chunk，无程序化校验。补一层轻量输出门控——a) 拒绝规则（涉政/暴力/成人/诱导泄露密钥等关键词 → 转固定引导语）；b) 越界检测（识别到学生问非学习话题 → 回到资料引导）；c) 界面标注"回答由 AI 生成，请核对资料"，不让学生误信。
- **删除级联软删除（F7 / pm23）**：教师删资料触发"清向量+级联对话/测评"（PRD §1.5）属不可逆灾难。改为 `is_deleted` 软删除 + 前端二次确认 + iCloud 保留 7 天硬删除窗口，避免误删全班数据。

---

## 十、可观测与备份

| 维度 | 实现 | 验收 |
|---|---|---|
| 探活 | `GET /health` → `{"status":"up","db":"ok","chroma":"ok"}` | 隧道域名/health 200 |
| 崩溃恢复 | launchd `KeepAlive=true` 自动拉起 | `kill -9` 后 5s 内自起 |
| 备份 | launchd 每日 `rsync`（**先 wal_checkpoint / sqlite .backup**）DB + chroma + uploads → iCloud Drive | 9.4 核查 + 14.1 演练 + F2 一致性 |
| 日志 | Flask + waitress stderr 落 `logs/app.log`（按日轮转） | 异常可追溯 |
| 监控告警 | **不做**（4 人可接受） | 已知盲区 §十三 |
| DeepSeek 成本 | 限速 60/天/用户 + 单请求 ≤120s | 超限 429 |

---

## 十一、阶段化落地（引用 PRD §10，架构不变仅补模块）

| 阶段 | 范围 | 新增模块 | 架构影响 |
|---|---|---|---|
| **P0 阶段一** | 账号 + 资料 + 引导式对话 + 教师草稿确认 | auth / chapters / materials / conversations / TUTOR+QUIZZER 草稿 | 基线架构落地 |
| **P1 阶段二** | 进度 + 周报 + 管理后台 + 巩固闭环 | progress / reports / teacher / attempts / review_items + GRADER + launchd 每日调度 | 新增 review_sched 模块 + attempts 写入路径 |
| **P2 阶段三** | SSE / 错题本 / 引用标注 / 命名隧道访问策略 | SSE 中间件 / 错题本视图 / Cloudflare Access | 不动核心，加固外层 |

---

## 十二、借鉴 ChemAI 决策留痕

| ChemAI 组件 | 本期处理 | 理由 |
|---|---|---|
| 4 客户端（教师/学生/家长/管理员） | 仅 2 端（教师/学生） | 4 人无需家长/管理员端 |
| ReAct 推理引擎 | **不引入** | PRD §0.1 明确不做；4 人过度 |
| 工具注册表 + 工厂 | **不引入**（函数即工具） | 3 Agent、零工具调用，负收益 |
| 4 维审核（系数/反应/产物/分子） | 替换为「教师人工确认」 | 学科无关，4 人有效 |
| OCR 4 引擎管道 | **不引入** | 学生在线作答，无需 OCR |
| 三层 Fallback | 降维为两层（LLM + 模板） | L3 固定答案 4 人意义低 |
| SQLite WAL + ChromaDB | **完全沿用** | 已被 PRD 验证 |
| 监理端护栏 | 降维 6 项 | 见 §九对照表 |
| Checkpoint 持久化 | 替换为 iCloud rsync | 等价但更简 |
| 苏格拉底引导 + 学生人设 | **完全沿用** | 核心，PRD §2.4/§8 |
| 错因诊断 + 间隔复习 | **完全沿用**（1→3→7d） | 巩固练习闭环，PRD §4.6 |
| 知识图谱 | **不引入** | 4 章以内图谱负收益 |
| Docker / 三层评测 111 场景 | **不引入** | 单体+人工 DoD 足够 |
| SSE 流式 | P2 | PRD §阶段三 |
| MiniLM 文档解析 | **沿用**（all-MiniLM-L6-v2） | 完全一致 |

---

## 十三、风险与已知盲区

按 aicoding-toolkit 视角，4 人规模 + "能简单就简单"带来的盲区，显式登记：

1. **🔴 不做 Evals（已知）** — aicoding-toolkit 红线 #5 要求 Evals 先行 + 基线只升不降。本期决策不做。**触发条件（任一满足即补做）**：
   - TUTOR 回答被教师连续 2 次吐槽"质量下降"
   - QUIZZER 草稿被教师 3 次以上大改
   - 新增第 4 个 Agent 能力
   - 引入新版本 DeepSeek 模型
   **兜底机制**：PRD §15 DoD 清单 + 教师日常体感。
   **主动检测（F8，再审补充）**：TUTOR 偏离苏格拉底（≤12 轮内直接给答案）难靠体感早发现 → 加埋点：记录每次对话"是否在护栏内给最终答案"比例，周报附给教师，偏差 >阈值即预警。低成本可落地。
2. **🟡 单点部署** — iMac 断电即停；无 SLA；架构层面无解，属约定项（iMac 保持通电 + iCloud 备份 + 还原演练）。
3. **🟡 JWT in localStorage** — XSS 风险已知；4 人内部工具可接受；P2 可升级 httpOnly Cookie（迁移需前后端协同）。
4. **🟡 8GB 内存硬限制** — 初版估算"常驻 5.5GB、余 2.5GB"偏乐观。**再审修正（F4 / pm38 约束评估）**：macOS Tahoe 在 8GB 上内存压力大、常 swap；上线前必须实测 `memory_pressure` 与 `vm_stat`，保留 ≥1.5GB 物理余量。若不足：① 关闭 iMac 后台重 App（浏览器多标签等）；② ChromaDB 改为按需加载而非常驻全部向量；③ **不得**在此机同时跑 Hermes 量化 / 本地 LLM（8GB 硬约束）。架构仍成立，但数字是"待实测"非"已证实"。
5. **🟡 SQLite 并发** — WAL 模式 4 人够；后续扩组（>10 人）需迁移 Postgres。
6. **🟢 PWA iOS 限制** — ServiceWorker 后台同步受限，本场景无碍；已记录 PRD §12。
7. **🟢 DeepSeek 成本** — 限速 60/天/用户 + 单请求 ≤120s；4 人低频使用成本极低（月 <¥10），但无上限。
8. **🟢 隧道链接外泄** — 一旦泄露即开放使用；JWT+角色校验兜底；P2 可加 Cloudflare Access 前置。

---

## 十四、演进路径（什么时候该升级）

| 触发信号 | 升级项 | 复杂度 |
|---|---|---|
| TUTOR/QUIZZER/GRADER 任意 1 个质量被吐槽 ≥2 次 | 补极简 Golden 集（10-20 条） | 低 |
| 资料 >50 份 / 单章 >100MB | 评估混合检索（向量+BM25） | 中 |
| Agent 能力 >5 个 | 引入工具注册表 + 统一路由 | 中 |
| 用户 >10 人 | SQLite → Postgres；waitress → gunicorn 2 worker | 中 |
| 用户 >50 人 | 拆 AI 独立服务（FastAPI）+ 消息队列 | 高 |
| 教师要求"周报自动生成" | 加 launchd 周任务 + reports_cron | 低 |
| 上线后 1 个月内 | 执行一次"删库→iCloud 还原→3 名同学数据可查"演练 | 一次性 |

---

## 十五、与 PRD 的对齐确认

| PRD 章节 | 架构对应 | 状态 |
|---|---|---|
| §2 部署架构 | §三 | ✅ 一致 |
| §3 用户与角色 | §四 + §九 | ✅ |
| §4 页面与 PWA | L1 表现层 | ✅ |
| §5 功能模块 | §四 + §五 | ✅ |
| §6 API 设计 | §四 Blueprint 表 | ✅ |
| §7 数据库设计 | §七 | ✅ |
| §8 系统提示词 | §5.1 | ✅（TUTOR 引导式已升级） |
| §9 部署与运维 | §三 + §十 | ✅ |
| §10 阶段规划 | §十一 | ✅ |
| §12 风险 | §十三 | ✅（含新增 8 项） |
| §13 NFR | §十 + §十三 | ✅（首字 ≤3s 流式 P2） |
| §14 数据安全备份 | §九 + §十 | ✅ |
| §15 DoD | §十一阶段化 | ✅（F9 已反写越权读 403 用例） |

---

## 十六、架构再审（2026-09-02，pm-toolkit 方法论）

用 PM Toolkit 的 `pm39 架构设计` / `pm38 技术选型(约束评估)` / `pm17 事前验尸` / `pm23 权限分级` / `pm34 领域建模(状态机)` / `pm26 AI 安全审核` 重新审计 v1.0。结论：**有条件通过**——分层 / 模块边界 / 数据流表达规范（pm39）达标；发现 3 个 P0 级真问题 + 4 个 P1 + 3 个 P2，均已修订或登记（见 §0 / §三 / §七 / §九 / §十 / §十三）。

### 再审发现清单（按严重度）

| 编号 | 技能视角 | 问题 | 严重度 | 处置 |
|---|---|---|---|---|
| F1 | pm17 事前验尸 | LaunchAgent 需登录才启，iMac 重启无人登录则服务挂 | P0 | 改 LaunchDaemon（§三） |
| F2 | pm17 / pm38 | rsync 直接拷正在写的 SQLite → 备份可能不一致 | P0 | 备份前 wal_checkpoint / sqlite .backup（§三/§十） |
| F3 | pm34 状态机 | `attempts` 缺 `quiz_version` → 教师重出题后 M 跨版本污染 | P0 | `attempts` 加 `quiz_version`（§七） |
| F4 | pm38 约束评估 | 8GB 内存"余 2.5GB"未实测，Tahoe 常 swap | P1 | 标注待实测 + 降级预案（§十三-4） |
| F5 | pm26 安全审核 | TUTOR 输出仅 prompt 注入，无程序化护栏 | P1 | 加轻量输出门控（§九） |
| F6 | pm39 / 术语 | waitress"单 worker"易误读为单线程 | P1 | 澄清单进程/4 线程（§0/§二） |
| F7 | pm23 权限 | 教师误删资料级联硬删，不可恢复 | P1 | 软删除 + 二次确认（§九） |
| F8 | pm17 / 质量 | Evals 纯被动触发，质量退化发现晚 | P2 | 加偏离埋点主动检测（§十三-1） |
| F9 | pm23 / 测试 | 数据隔离缺显式集成测试清单 | P2 | 越权读 403 用例列入 DoD（§九/§十五） |
| F10 | pm17 | 命名隧道域名/证书过期 → 链接失效 | P2 | 部署时设提醒 + Cloudflare 续期（§十三） |

### 再审结论

- **架构形态（单体 / 三 Agent / 纯向量 / SQLite+Chroma）维持不变**——4 人规模下仍是最简且正确。
- 修订集中在两个真正会出事的维度：**部署韧性（F1/F2）** 与 **数据正确性（F3）**，不引入新组件、不增加复杂度。
- F4/F5/F7 为"上线前必须落实"的实现期清单，非架构变更。
- 与 PRD 对齐表（§十五）维持全 ✅；F9 已反写进 DoD 意识。

---

## 附录 A：代码组织建议（落地时参考）

```
backend/
├── app.py                    # Flask 入口 + 蓝图注册 + 静态托管
├── config.py                 # DEBUG/PROD/JWT 密钥/限速配置
├── auth/
│   ├── jwt_utils.py          # 签发/解析/装饰器
│   └── routes.py
├── api/
│   ├── chapters.py
│   ├── materials.py
│   ├── conversations.py
│   ├── quizzes.py
│   ├── attempts.py
│   ├── progress.py
│   ├── reports.py
│   ├── teacher.py
│   └── health.py
├── ai/
│   ├── prompts.py            # TUTOR/QUIZZER/GRADER 三套系统提示词
│   ├── rag.py                # 检索 + chunk 拼装
│   ├── tutor.py              # 引导式对话编排 + 12 轮护栏
│   ├── quizzer.py            # 出题（草稿生成）
│   ├── grader.py             # 批改
│   ├── review_sched.py       # 间隔复习调度（P1）
│   └── fallback.py           # 模板兜底
├── data/
│   ├── models.py             # SQLAlchemy
│   ├── chroma_client.py
│   └── seed.py               # 初始教师账号种子
├── middleware/
│   ├── rate_limit.py
│   ├── error_handler.py
│   └── input_validation.py
└── scripts/
    ├── launchd_install.sh    # plist 安装
    ├── backup_rsync.sh       # iCloud 备份
    └── restore_test.sh       # 还原演练脚本

frontend/
├── index.html
├── manifest.webmanifest
├── sw.js
├── js/
│   ├── api.js                # BASE_URL='/api' 相对路径
│   ├── auth.js
│   ├── learn.js              # 引导式对话 UI
│   ├── quiz.js
│   ├── progress.js           # 四态 + 巩固练习
│   ├── report.js
│   └── admin.js
└── css/
```

---

## 附录 B：架构图

详见同目录 `architecture-diagram.svg`（单页分层图）。

---

_本文档由软件架构师基于 PRD v2.1 + 原型 v2.1 + ChemAI 复杂版（系统架构图/核心业务流程图）综合设计，遵循"能简单就简单"原则，所有复杂度判断以 4 人规模为第一约束。决策已与教师确认（4 项分叉点全走最简）。v1.1 已通过 pm-toolkit 再审（§十六），修订 F1–F7，F8–F10 登记为实现期清单。待教师对本文档签字后进入 P0 阶段一实现。_
