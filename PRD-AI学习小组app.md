# AI 学习小组 App — 功能需求文档 (PRD)

> 版本：v2.1（在 v2.0 基础上增强：引导式对话 + 巩固练习闭环 + 教师发布轻量审核）  
> 日期：2026-09-02  
> 状态：需求评审  
> 产物形态：可安装 PWA（手机端为主）  
> 部署方式：教师本地 iMac 常驻 + Cloudflare 隧道公网暴露  
> 用户规模：1 名教师（你）+ 3 名同学，共 4 个账号

---

## 〇、相比 v1 的关键变化（先读这节）

| 维度 | v1（原《学习助手平台》） | v2（本 PRD） |
|------|--------------------------|--------------|
| 交付形态 | 桌面浏览器 SPA | **可安装 PWA**，移动端优先，加到主屏有 App 图标 |
| 访问方式 | 本机 `localhost` | **Cloudflare 隧道**公网链接，单一入口 |
| 用户模型 | 无账号，单人 | **师生独立账号 + 角色权限**（教师 / 学生） |
| 数据隔离 | 全部共享 | **资料全班共享，对话/测评/进度按学生隔离** |
| 鉴权 | 无 | **登录 + JWT**，资料上传仅教师可操作 |
| 部署安全 | `debug=True` 直跑 | **生产配置关 debug**，隧道仅暴露必要端口 |
| 常驻运行 | 手动起 | **macOS 开机自启 + 防休眠**（launchd + caffeinate） |
| 前端托管 | 本地静态文件，API 写死 `localhost:5001` | **Flask 单源托管前端+API**，API 地址改相对路径 `/api` |

---

### 〇.1 v2.1 关键增强（来自复杂版教育 Agent 参考的降维落地）
本版参考一套复杂版「教育 Agent 全生命周期」方案（ChemAI 智辅化学），从中抽取适合本 App 的**简单模式**落地；并明确**不引入**化学专属四维审核、OCR 答题卡批改、ReAct 推理引擎、Docker/三层评测（111 场景）等过重基建：
- **功能2 升级为引导式对话**：加载学生人设（年级/薄弱章）→ 意图路由 → 苏格拉底式引导（不直接给答案）→ 递归 ≤12 轮护栏。
- **功能4 新增巩固练习闭环**：薄弱点 → 一键生成巩固练习 + 间隔复习计划（呼应参考版「诊断→推荐练习→间隔复习」）。
- **功能3 加轻量审核**：教师发布测评改为 生成草稿 → 预览/微调 → 确认发布（`status: draft → published`）。
- 治理类（权限矩阵 / 家长端周报 / 安全护栏）本期**不做**（用户确认）。

---

## 一、产品概述

### 1.1 定位
面向「AI 学习小组」的私有化 AI 辅助学习工具。教师上传学习资料（PDF / PPT / Word / Markdown / TXT），系统解析后，3 名同学各自基于资料进行**问答、自动测评、进度追踪、周报生成**；教师可统一管理局资料并纵览全班学习情况。

### 1.2 角色与场景
- **教师（你）**：上传/管理资料；查看全班每个同学的学习概览、测评成绩、薄弱点；无需亲自答题。
- **学生（3 名）**：登录后基于共享资料聊天提问、做测评、看自己的进度与周报；彼此对话互不看见。
- **部署**：服务跑在你的 iMac（`0.0.0.0:5001`），通过 `cloudflared` 隧道暴露为一个公网 HTTPS 链接，同学用手机浏览器打开、加到主屏即当成 App 使用。

### 1.3 非目标（明确不做）
- 不做原生 App 上架（App Store / 应用市场）。
- 不接公网用户注册（账号由教师创建，不开放自助注册）。
- 不引入 MySQL/云数据库——维持 SQLite（4 人规模足够，部署零依赖）。

---

## 二、部署架构（本版核心）

```
同学手机浏览器
   │  https://<your-tunnel>.trycloudflare.com   (或自定义域)
   ▼
cloudflared 隧道  ──►  iMac 本机 127.0.0.1:5001
                           │
                           ▼
                     Flask 单进程（生产模式，debug=False）
                       ├─ /            → 托管 frontend/ 静态页（PWA）
                       ├─ /api/*       → 业务接口（JWT 鉴权）
                       ├─ /manifest.webmanifest, /sw.js → PWA 资源
                       ├─ SQLite        (instance/learning_assistant.db, WAL)
                       └─ ChromaDB      (chroma_db/, 资料向量)
```

### 2.1 单源托管（必须）
- Flask 增加静态路由，将 `frontend/` 目录作为站点根（`/`）托管，前端不再依赖独立静态服务器。
- `frontend/js/api.js` 中 `BASE_URL` 由 `http://localhost:5001/api` 改为**相对路径 `/api`**，使其在任何隧道域名下都正确。
- PWA 资源 `manifest.webmanifest`、`sw.js` 置于 `frontend/` 并由 Flask 根路径提供。

### 2.2 公网暴露安全（硬性，必须做）
- `app.py` 部署时 **`debug=False`**；通过环境变量 `FLASK_ENV=production` 切换，禁止把 Werkzeug debugger 暴露公网。
- 仅暴露 `5001` 端口经由隧道；iMac 防火墙不对外开端口。
- 因链路经 Cloudflare，源站 IP 不直接暴露；但仍**必须开启 JWT 鉴权**，避免链接泄露后被滥用 DeepSeek 额度 / 任意上传。
- 可选增强：Cloudflare 侧设置访问策略（如邮箱/口令前置），作为第二道防线（不在本期强制，列为 P2）。

### 2.3 常驻运行（你选「帮我做自启防睡」）
- **开机自启**：用 `launchd` plist 在登录后自动拉起 Flask（含 venv 激活）。
- **防休眠**：登录会话内以 `caffeinate -ims python app.py` 方式运行，防止合盖/空闲休眠导致服务中断；或在 plist 中保持 `caffeinate` 包裹。
- **断电/关机仍会中断**：属物理限制，需在 PRD 外口头约定（你的 iMac 需保持通电开机）。
- 具体脚本见第九节，写定后我可帮你落到 iMac 上（含回滚说明）。

---

## 三、用户与角色模型

### 3.1 账号
| 角色 | 数量 | 能力 |
|------|------|------|
| teacher（教师） | 1 | 创建/删除学生账号；上传/删除/管理资料；查看全班进度与测评（v2 教师无独立聊天 UI，仅管理+聚合，见第八节） |
| student（学生） | 3 | 登录；基于共享资料聊天/测评；查看**自己**的进度与周报；**不能**上传/删除资料 |

- 账号由教师通过后台创建（不自助注册）。初始教师账号从环境变量/`.env` 种子注入。
- 密码使用强哈希存储（`werkzeug.security` 或 `bcrypt`），不存明文。

### 3.2 登录流程
1. 同学打开 PWA → 登录页输入账号密码 → `POST /api/auth/login`。
2. 后端校验后返回 **JWT**（Access Token）。
3. 前端存 `localStorage`，之后每个 `/api/*` 请求带 `Authorization: Bearer <token>`。
4. 前端按 `role` 决定显示「学生视图」还是「教师管理后台」。

---

## 四、页面设计（移动优先 + PWA）

### 4.1 入口与导航
- **登录页（/login）**：账号密码登录，首次打开 PWA 的落地页。
- 登录后 SPA 内 Hash Router：
  - **学生视图**：`#learn` 学习（资料聊天）｜ `#quiz` 测评｜ `#progress` 进度｜ `#report` 周报｜（右上角头像退出）
  - **教师视图**：在以上基础上增加 `#admin` 管理后台（账号管理 + 资料管理 + 全班概览）

### 4.2 PWA 要求（新增）
- `frontend/manifest.webmanifest`：名称「AI 学习小组」、图标（192/512）、`display: standalone`、主题色。
- `frontend/sw.js`：缓存 App Shell（HTML/CSS/JS/图标），支持弱网/离线打开；API 数据走网络。
- `index.html` 增加 `<meta name="viewport">`、`<link rel="manifest">`、iOS 主屏图标 `<link rel="apple-touch-icon">`。
- 移动端响应式重写：原桌面三栏布局改为单列 + 底部 Tab Bar。

---

## 五、功能模块拆解（含角色与优先级）

### 功能 0：账号与登录 — 优先级 P0（本期新增）
| 子功能 | 角色 | 优先级 | 说明 |
|--------|------|--------|------|
| 0.1 登录/登出 | 全部 | **P0** | JWT 鉴权，token 过期刷新 |
| 0.2 教师创建学生账号 | teacher | **P0** | 用户名+初始密码，可重置 |
| 0.3 修改密码 | 全部 | **P1** | 学生/教师各自改密 |
| 0.4 角色路由 | 全部 | **P0** | 登录后按 role 渲染视图 |

### 功能 1：资料与章节管理（教师专用）— 优先级 P0
资料按「文件夹（模块）→ 章节」两级组织，像文件管理器一样管理；资料归属到具体章节，向量亦带章节标签（是掌握度计算的基础）。
| 子功能 | 角色 | 优先级 | 说明 |
|--------|------|--------|------|
| 1.1 建/改/删 文件夹与章节 | teacher | **P0** | 仅教师可操作；学生不可见管理入口 |
| 1.2 上传资料并归入章节 | teacher | **P0** | PDF/PPT/Word/MD/TXT，≤30MB，上传时选择所属章节 |
| 1.3 解析 & 入库 | teacher | **P0** | 分块后写入 ChromaDB，向量带 `chapter_id` 标签 |
| 1.4 资料浏览（按章节，全班可见） | 全部 | **P0** | 学生按章节浏览/提问，但**不能删/传/建章节** |
| 1.5 资料删除（清向量+级联） | teacher | **P0** | 删除同步清理向量库、关联对话、以及引用该资料的测评（避免孤儿数据）；周报为周期汇总不绑定单资料，保留 |
| 1.6 批量上传 | teacher | **P2** | 拖拽多文件，按命名规则自动归章 |

> 学生视图中章节/资料列表为**只读**；建章节与上传入口仅在教师视图（`#admin`）出现。

### 功能 2：聊资料（RAG 引导式辅导）— 优先级 P0
沿用参考版「苏格拉底式引导」模式，从「直接问答」升级为「引导式辅导」，并加载学生人设让引导更贴合。
| 子功能 | 角色 | 优先级 | 说明 |
|--------|------|--------|------|
| 2.1 学生人设加载 | student | **P0** | 进入对话即加载该生人设（年级 + 当前薄弱章），用于调整引导难度与侧重 |
| 2.2 选择对话范围 | student | **P0** | 指定基于某份/某章/全部共享资料 |
| 2.3 意图路由 | student | **P1** | 识别用户输入类型（答疑 / 复习薄弱点 / 请求出题），分流到对应处理；**不**自动越权出题 |
| 2.4 引导式回答（苏格拉底） | student | **P0** | 检索召回 → LLM(TUTOR) 以**追问引导**为主，**不直接给最终答案**；学生答对或明确卡住再给点拨 |
| 2.5 递归控制 ≤12 轮护栏 | student | **P1** | 单次辅导对话最多 12 轮追问，超限转为「给出结论 + 建议练习」，防死循环 |
| 2.6 对话历史（**仅自己**） | student | **P0** | 按 `user_id` 隔离，看不到他人对话 |
| 2.7 流式输出 | student | **P1** | SSE 逐 token（本期建议实现，体验关键） |
| 2.8 新/历史对话切换 | student | **P1** | 创建/切换/删除自己的对话 |
| 2.9 引用标注 | student | **P2** | 引导依据标注资料原文来源 |

### 功能 3：做测评（教师发布 + 学生作答 + 批改）— 优先级 P0
测评**由教师发布、全班同题**；学生不自行出题，仅作答与查看自己的成绩。
| 子功能 | 角色 | 优先级 | 说明 |
|--------|------|--------|------|
| 3.0 教师发布测评（轻量审核） | teacher | **P0** | 选章节 → AI **生成草稿**（题目带 `chapter_id`/子概念标签，`status=draft`）→ 教师**预览/微调/确认** → 发布（`status=published`）；全班学生看到**相同题目** |
| 3.1 在线作答 | student | **P0** | 点选/文本框；**支持重做，成绩取最近一次** |
| 3.2 自动批改 | student | **P0** | LLM(GRADER) 三档评分；记录每题对错到 `attempts` |
| 3.3 测评报告 | student | **P1** | 得分/错题/本章薄弱点 |
| 3.4 题型配置 | teacher | **P2** | 教师设定题型数量/难度 |
| 3.5 错题本 | student | **P2** | 收集错题重做 |
| 3.6 重出/新版本 | teacher | **P1** | 重出生成新 `version`，历史成绩不覆盖（见 §7） |
| 3.7 发布态管理 | teacher | **P1** | `quizzes.status`：`draft`（草稿待确认）/ `published`（已发布）；学生仅见 `published`，`draft` 不可作答 |

> 测评记录按 `user_id` 隔离，学生只看到自己的成绩；但**题目内容全班统一**（同一 `quiz_id`）。题目→章节标签是掌握度计算的基础（见功能 4）。

### 功能 4：看进度（学习追踪）— 优先级 P1
| 子功能 | 角色 | 优先级 | 说明 |
|--------|------|--------|------|
| 4.1 我的掌握度分布（按章节） | student | **P1** | 仅本人数据，每章四态：已掌握/进行中/薄弱/未评估 |
| 4.2 我的对话/提问统计 | student | **P1** | 本人累计（可按章节下钻） |
| 4.3 我的成绩趋势 | student | **P1** | 本人历次测评折线 |
| 4.4 全班概览（教师） | teacher | **P1** | 每位同学掌握度/成绩/活跃度一览 |
| 4.5 薄弱点列表（带依据） | 全部 | **P1** | 学生看自己；教师看全班聚合；每条附错题依据 |
| 4.6 巩固练习闭环 | student | **P1** | 薄弱点 → **一键生成巩固练习**（基于薄弱章出题）；按**间隔复习**节奏排入重做计划（`review_items`），形成 诊断 → 练习 → 复测 闭环 |

#### 掌握度与薄弱点定义（核心，原 v2 未定义，本版补全）
- **单元**：以「章节」为最小掌握单元。每章掌握度分 `M ∈ [0,100]`。
- **M 计算**：`M = Σ(wᵢ · correctᵢ) / Σ(wᵢ)`，仅统计该章关联题作答；`correctᵢ` 为对错（简答取 GRADER 0–1 分）；`wᵢ` 为时间衰减权重（越近越高，如 `0.5^间隔周数`）。
- **四态映射（默认阈值，可由教师 P2 微调）**：
  - 已掌握：M ≥ 80 **且** 有效作答 ≥ 2 次
  - 进行中：50 ≤ M < 80，**或** M ≥ 80 但作答 < 2 次（证据不足）
  - 薄弱：M < 50
  - 未评估：该章从未测验 → **不计入薄弱**，单独标识（防冷启动误判）
- **薄弱点**：章节级 = M < 50 的章按 M 升序取最差 N 个；知识点级（P2）= 章内子概念经错题库聚合。每条薄弱点**附错题依据**（该生在此章错过的题），拒绝凭空定性。

### 功能 5：出周报 — 优先级 P1
| 子功能 | 角色 | 优先级 | 说明 |
|--------|------|--------|------|
| 5.1 我的本周概况 | student | **P1** | 学习天数/对话数/测评数（本人） |
| 5.2 我的成绩分析 | student | **P1** | 平均/最高/薄弱点 |
| 5.3 AI 学习建议 | student | **P1** | 下周计划建议 |
| 5.4 教师查看全班周报 | teacher | **P2** | 教师维度汇总 |
| 5.5 周报导出 | 全部 | **P2** | Markdown/PDF |

### 功能 6：教师管理后台（#admin）— 优先级 P1（本期新增）
| 子功能 | 优先级 | 说明 |
|--------|--------|------|
| 6.1 学生账号管理 | **P1** | 创建/重置密码/停用 |
| 6.2 资料管理 | **P1** | 上传/删除/查看解析状态 |
| 6.3 全班学习概览 | **P1** | 各学生进度、成绩、薄弱点聚合看板 |

---

## 六、后端 API 设计（增量）

> 既有 `/api/materials`、`/api/conversations`、`/api/quizzes`、`/api/progress`、`/api/reports` 保留，但**全部加 JWT 鉴权 + `user_id` 作用域**。

### 6.1 认证（新增）
#### POST /api/auth/login
```
Request:  { "username": "alice", "password": "******" }
Response: { "code":0, "data": { "token": "<jwt>", "role":"student", "display_name":"Alice" } }
```
#### POST /api/auth/refresh （P1）
```
Response: { "code":0, "data": { "token":"<new_jwt>" } }
```
#### GET /api/auth/me
```
Header: Authorization: Bearer <jwt>
Response: { "code":0, "data": { "id":"u_xxx", "role":"student", "display_name":"Alice" } }
```
#### POST /api/auth/register  （teacher only）
```
Header: Authorization: Bearer <teacher_jwt>
Request: { "username":"bob", "display_name":"Bob", "role":"student", "password":"******" }
Response: { "code":0, "data": { "id":"u_yyy" } }
```

**令牌策略（明确，补缺 v1 未定义项）**：
- Access Token 有效期 `ACCESS_TOKEN_TTL = 12h`（环境变量可调）；无状态 JWT，服务端不落库。
- 续期：`POST /api/auth/refresh` 在 token 临近过期时换发新 token（前端于 401 或定时阈值触发）；v2 不引入 refresh token，保持简单。
- 登出：前端清除本地 token 即可（服务端无状态，无需黑名单；如需强制失效可加短期 deny list，列为 P2）。
- 存储：token 存 `localStorage`（见 9.4 安全核查的 XSS 权衡说明）。

### 6.2 资料（作用域调整）
- `GET /api/materials`：全部登录用户可见（共享）。
- `POST /api/materials/upload`：**teacher only**。
- `DELETE /api/materials/:id`：**teacher only**。
- 其余字段同 v1（增加 `uploaded_by` 记录上传教师）。

### 6.3 对话 / 测评 / 进度 / 周报（作用域调整）
- 所有写操作自动注入当前 `user_id`；所有读操作按 `user_id` 过滤（学生只看自己）。
- 新增教师聚合接口（teacher only）：
  - `GET /api/teacher/overview` → 全班进度/成绩/活跃度汇总
  - `GET /api/teacher/students/:id/progress` → 某学生进度
  - `GET /api/teacher/students/:id/quizzes` → 某学生测评

> 接口详细字段（请求/响应体）沿用 v1 第四节对应小节，仅补充 `user_id` 服务端注入与鉴权头，不再重复铺陈。

---

## 七、数据库设计（增量）

> 沿用 v1 第八节全部表，新增/调整如下：

### 7.1 用户表：users（新增）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| username | VARCHAR(64) UNIQUE | 登录名 |
| password_hash | VARCHAR(128) | 哈希（bcrypt/werkzeug） |
| role | VARCHAR(10) | teacher / student |
| display_name | VARCHAR(64) | 显示名 |
| grade | VARCHAR(32) | 年级/学段（学生人设，用于引导式对话定位与侧重）；可空 |
| is_active | BOOLEAN DEFAULT 1 | 是否启用 |
| created_at | DATETIME | 创建时间 |

### 7.2 章节表：chapters（新增，功能 1 支撑）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| folder | VARCHAR(64) | 所属文件夹（模块）名 |
| name | VARCHAR(128) | 章节名 |
| order_no | INT | 同文件夹内排序 |
| created_by | VARCHAR(36) FK→users | 建章教师 |

### 7.3 既有表调整
- `materials`：新增 `uploaded_by VARCHAR(36)`（FK→users）；新增 `chapter_id VARCHAR(36) FK→chapters`（归属章节，原扁平列表改为挂到章节下）。
- `conversations`：新增 `user_id VARCHAR(36) FK`（归属学生）；可选 `chapter_id` 记录对话所属章节。
- `quizzes`：改为**教师发布实体**，新增 `chapter_ids VARCHAR(255)`（覆盖章节，逗号分隔）、`version INT DEFAULT 1`、`teacher_id VARCHAR(36) FK`、`published_at DATETIME`、`title VARCHAR(128)`、`status VARCHAR(16) DEFAULT 'published'`（`draft`/`published`，支撑 3.0 轻量审核）、`confirmed_at DATETIME`（教师确认发布时间）；**移除** `user_id`（题目不属于单个学生，全班共用）。
- `reports`：新增 `user_id VARCHAR(36) FK`。
- 新增 `questions` 表（测评题目）：`id, quiz_id FK, chapter_id FK, sub_concept VARCHAR(128), type, content, answer_key`（题目带章节/子概念标签，是掌握度 M 与薄弱点计算的溯源依据）。
- 新增 `attempts` 表（每生每题作答）：`id, user_id FK, quiz_id FK, question_id FK, chapter_id FK, correct TINYINT, score FLOAT, created_at`；掌握度 M 由该表按 `chapter_id` 聚合计算。
- 新增 `review_items` 表（巩固练习 / 间隔复习计划，支撑 4.6）：`id, user_id FK, chapter_id FK, question_id FK(NULL 可), next_review_at DATETIME, interval_days INT DEFAULT 1, status VARCHAR(16) DEFAULT 'pending'`（`pending`/`done`）；掌握度回升后顺延间隔（1→3→7 天），形成间隔复习节奏。
- `messages`：通过 `conversation_id` 间接归属，无需单独 user_id；如需直查可加 `user_id`。
- ChromaDB 集合 `material_chunks`：新增 `chapter_id` 字段（向量带章节标签，支持按章节检索）。

> 历史数据按 §14.2 丢弃，v2 全新初始化，故新增 `NOT NULL` 列无脏数据风险。

---

## 八、系统提示词（沿用 v1，略调）

TUTOR / QUIZZER / GRADER 三套提示词**沿用 v1 第六节**，仅微调：
- **TUTOR**：升级为**引导式（苏格拉底）**：① 注入学生人设（年级 + 薄弱章）；② 优先以**追问引导**思考，**不直接给最终答案**，学生答对或明确卡住再给点拨；③ 单次辅导 **≤12 轮**，超限转「给结论 + 推荐练习」；④ 引用资料原文作为引导依据。
- **GRADER**：不变。
- 教师视图不调用对话型提示词；教师仅做管理与聚合。

---

## 九、部署与运维脚本（落地清单）

> 以下为「帮我做自启防睡」的可执行方案，PRD 定稿后我可帮你写入 iMac 并给出回滚步骤。

### 9.1 生产启动配置
- `config.py` 增加 `PROD` 开关：`DEBUG = os.getenv("FLASK_ENV") != "production"`。
- `app.py`：`app.run(host="0.0.0.0", port=5001, debug=Config.DEBUG)`；生产用 `waitress`/`gunicorn` 替代 `app.run`（推荐 `waitress`，纯 Python 易装）。
- Flask 增加静态托管：
  ```python
  @app.route("/")
  @app.route("/<path:path>")
  def serve_frontend(path=""):
      return send_from_directory(FRONTEND_DIR, "index.html")
  ```
  并将 `manifest.webmanifest`、`sw.js` 置于 `frontend/` 根，由同一路由提供。

### 9.2 Cloudflare 隧道（建议命名隧道，保证链接稳定）
> ⚠️ 随机隧道 `trycloudflare.com` 每次重启链接都会变，同学需频繁更新书签——对 3 人长期使用不友好，**建议用命名隧道拿到固定域名**（P0）。

```bash
# 安装（一次）
brew install cloudflared
# 登录并配置命名隧道（一次性，拿到固定域名如 ai-study.xxxx.com）
cloudflared tunnel login
cloudflared tunnel create ai-study-group
# 在 ~/.cloudflared 配置文件中映射本机 5001
cloudflared tunnel route dns ai-study-group ai-study.<你的域名>
# 常驻运行（配合 9.3 自启）
cloudflared tunnel run ai-study-group
```
- 若暂用随机隧道（`cloudflared tunnel --url http://localhost:5001`）仅适合演示；正式交付必须用命名隧道固定链接。
- 域名建议用你自有域名（Cloudflare 托管）或 cloudflare 免费子域；链接仍仅私发 3 名同学。

### 9.3 macOS 开机自启 + 防休眠
- `~/Library/LaunchAgents/com.aiStudyGroup.plist`（登录后自启）：
  ```xml
  <plist version="1.0">
    <dict>
      <key>Label</key><string>com.aiStudyGroup</string>
      <key>ProgramArguments</key>
      <array>
        <string>/usr/bin/caffeinate</string>
        <string>-ims</string>
        <string>/Users/xicheng/2026-05-19-task-7/backend/venv/bin/python</string>
        <string>/Users/xicheng/2026-05-19-task-7/backend/app.py</string>
      </array>
      <key>WorkingDirectory</key><string>/Users/xicheng/2026-05-19-task-7/backend</string>
      <key>EnvironmentVariables</key>
      <dict><key>FLASK_ENV</key><string>production</string></dict>
      <key>RunAtLoad</key><true/>
      <key>KeepAlive</key><true/>
    </dict>
  </plist>
  ```
  - `caffeinate -ims`：阻止系统休眠（-m 合盖、-i 空闲、-s 系统），保证服务常驻。
  - 加载：`launchctl load ~/Library/LaunchAgents/com.aiStudyGroup.plist`
  - 卸载（回滚）：`launchctl unload ...` 后删 plist。
- **物理限制**：断电/关机仍中断，需 iMac 保持通电。

### 9.4 安全核查清单（上线前）
- [ ] `FLASK_ENV=production`（debug 关闭）
- [ ] JWT 密钥从环境变量读取，不硬编码
- [ ] 资料上传/删除接口已加 teacher 角色校验
- [ ] 对话/测评/进度/周报读接口已加 `user_id` 过滤
- [ ] DeepSeek API Key 仅在 `.env`，不进仓库
- [ ] 隧道链接仅发给 3 名同学，不外泄
- [ ] CORS 收口为同源（Flask 已单源托管前端，勿保留 `*`）；如保留 `CORS(app)` 须显式 `origins=[隧道域名]`
- [ ] JWT 存 `localStorage` 已知 XSS 风险：内部 4 人工具可接受，但前端须避免 `eval`/字符串拼接、保留 CSP；后续可升级 httpOnly Cookie
- [ ] 已配置按用户速率限制（见十三 NFR），防止单同学刷爆 DeepSeek 额度
- [ ] 已执行一次备份恢复演练（见十四），确认 iMac 故障可还原同学数据

---

## 十、开发阶段规划（修订）

**阶段一（P0 闭环）**：账号登录 + 教师传资料 + 学生**引导式**聊资料 + 教师**生成草稿→确认发布**测评
- 后端：用户表 + JWT 鉴权 + 角色校验 + 单源托管前端 + 关 debug
- 前端：登录页 + 移动端学习页（引导式对话）+ 测评页（教师确认发布）+ PWA manifest/sw + API 相对路径
- AI：TUTOR 引导式 + QUIZZER 草稿 + GRADER 批改三套提示词

**阶段二（P1）**：进度（本人+教师概览）+ 周报（本人）+ 教师管理后台 + **巩固练习闭环（间隔复习）**
- 后端：进度/周报加 user_id 作用域 + 教师聚合接口
- 前端：进度页 + 周报页 + `#admin` 后台

**阶段三（P2）**：体验与安全增强
- 流式输出(SSE)、错题本、引用标注、批量上传、Cloudflare 访问策略前置、周报导出

---

## 十一、交互流程概览

```
教师登录后台 → 上传资料 → 解析入库(ChromaDB) → 全班可见
        ↓
同学登录(手机PWA) → 选章节资料 → 加载学生人设 → 提问
   → 向量检索 → LLM(TUTOR) 引导式追问(不直接给答案, ≤12轮, 仅本人对话)
        ↓
教师选章 → LLM(QUIZZER) 生成草稿 → 教师预览/微调/确认 → 发布(全班同题)
        ↓
同学作答 → LLM(GRADER) 批改(仅本人成绩) → 标记薄弱章 → 一键生成巩固练习(间隔复习)
        ↓
同学看进度/周报(本人, 含巩固计划) ；教师看 #admin 全班概览
        ↓ (每周)
同学生成周报 → 汇总本人数据 → LLM 建议
```

---

## 十二、风险与待确认

1. **公网安全**：隧道链接一旦外泄即开放使用——已用 JWT+角色校验兜底，但仍建议链接仅私发；可选 Cloudflare 访问策略加第二道锁（P2）。
2. **常驻依赖**：服务可用性 = iMac 开机且通电。断电信道即断，需约定。
3. **成本**：DeepSeek API 按量计费，4 人低频使用成本极低，但无上限；角色校验防止越权调用。
4. **SQLite 并发**：4 人规模 WAL 模式足够；若后续扩组再考虑迁移。
5. **PWA iOS 限制**：iOS Safari 对 `sw.js` 缓存与 standalone 模式有部分限制（如不支持后台同步），本场景无碍，已记录在案。

### 12.1 已闭环决策（教师确认）
| 决策项 | 结论 |
|--------|------|
| 备份目标 | **iCloud Drive**（每日 `rsync`，不落外接盘） |
| 同学年龄 | 3 名均**成年**，无监护人知情同意环节 |
| v1 历史数据 | **丢弃**，v2 全新初始化，无迁移脚本 |
| 部署动作 | 本期**仅产出 PRD**，不实际部署（脚本见第九/十四节，留作后续执行参考） |

> 剩余开放项仅一项：**命名隧道固定域名**（见 §9.2）——需教师提供自有/Cloudflare 托管域名或免费子域，部署时配置。

---

## 十三、非功能性需求（NFR，补全）

| 维度 | 目标 | 说明 |
|------|------|------|
| 性能/延迟 | RAG 问答首字 ≤ 3s（流式），非流式完整回答 P95 ≤ 12s | 受 DeepSeek + 向量检索影响；4 人规模无并发压力 |
| 可用性 | 目标 ≥ 99%（前提：iMac 通电开机） | 单点部署无冗余；故障=人工重启，无 SLA 承诺 |
| 并发 | 峰值 4 用户同时在线，单用户连续对话 | SQLite WAL + waitress 多线程足够 |
| 容量 | 资料总量 ≤ 500MB（约数十份）；向量库随资料增长 | ChromaDB 本地磁盘，iMac 256GB+ 充裕 |
| 兼容性 | iOS 15+ / Android 10+ 移动浏览器；PWA 主屏 | 不保证旧版 WebView |
| 限速（成本护栏） | 每用户 ≤ 60 次 LLM 调用/天、单请求 ≤ 120s | 防止单一同学刷爆 DeepSeek 额度；超限返回 429 + 友好提示 |
| 可观测 | `/health` 可探活；崩溃由 launchd `KeepAlive` 自动拉起 | 无独立监控告警（4 人规模可接受），见十四备份 |

## 十四、数据安全、备份与迁移（补全）

### 14.1 备份与灾难恢复（关键缺口）
单台 iMac + 本地 SQLite/ChromaDB，**无备份 = 同学进度与资料向量全丢**。必须：
- **数据库**：`learning_assistant.db`（含 `-wal/-shm`）每日定时拷到 iCloud Drive（已确认为唯一备份目标）；ChromaDB 目录一并备份。
- **资料原文**：`uploads/` 目录随库一起备份（向量可重建，但原文丢了无法重解析）。
- **演练**：上线后做一次「删库 → 从备份恢复 → 同学数据可查」的还原验证（见 9.4 核查项）。
- 已确认备份目标为 **iCloud Drive**：`launchd` 每日 `rsync` 到 `~/Library/Mobile Documents/com~apple~CloudDocs/2026-05-19-task-7_backup/`，不落外接盘。iMac 需保持登录同一 iCloud 账号且 Drive 同步开启。

### 14.2 v1 历史数据处置（已决定：丢弃，全新初始化）
- 教师确认：**丢弃 v1 全部历史数据**，v2 不做数据迁移。
- 上线部署前删除现有 `instance/learning_assistant.db`（含 `-wal/-shm`）、`chroma_db/` 全部集合、`uploads/` 旧资料，`.env` 一并重新生成（密钥不沿用旧值）。
- 启动 v2 时由种子脚本重建空库：写入初始教师账号（来自 `.env` 种子），学生账号由教师后台创建。
- 因无迁移负担，v2 表结构可自由将 `user_id` 等新增列设为 `NOT NULL`，无脏数据 / NOT NULL 失败风险。

### 14.3 隐私与知情同意
- 教师默认可查看每位同学的全部对话/测评/进度（产品设计使然）。
- 已确认 3 名同学均为成年人，**无未成年监护人知情同意环节**。
- 上线前仍以群公告形式告知同学「学习数据对教师可见」，取得知情同意即可。

### 14.4 CORS 收口
- Flask 已单源托管前端，`CORS(app)` 的 `*` 不再必要；生产改为仅允许同源或显式 `origins=[隧道域名]`，降低跨站调用面。

## 十五、验收标准（Definition of Done，补全）

**阶段一 DoD（P0 闭环可交付）**
- [ ] 4 个账号可注册/登录，JWT 12h 有效、过期可续
- [ ] 学生看不到他人对话；教师不能上传（接口 403 验证通过）
- [ ] 教师上传 PDF/PPT → 学生可在 `#learn` 进入**引导式对话**（不直接给答案、≤12 轮护栏）
- [ ] 教师发布测评需经「生成草稿 → 确认」两步（接口校验 `status=draft` 不可被学生作答）
- [ ] 学生完成一套测评 → 看到得分与薄弱点
- [ ] 手机 Safari/Chrome 打开隧道链接、加到主屏、离线可启动 App Shell
- [ ] `FLASK_ENV=production` 下无 Werkzeug debugger 暴露

**阶段二 DoD（P1）**
- [ ] 学生进度页仅本人数据；教师 `#admin` 全班概览正确聚合 3 人
- [ ] 周报含本人统计 + AI 建议
- [ ] 限速生效：单用户超额返回 429

**阶段三 DoD（P2）**
- [ ] SSE 流式输出可用；错题本/引用标注可用
- [ ] 备份还原演练通过；Cloudflare 访问策略（可选）已加
