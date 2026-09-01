# CLAUDE.md · AI 学习小组 App — AI 行为准则

## 1. 项目背景
- 定位：1 教师 + 3 学生的私有学习小组 Web App「AI 学习小组」（AI Study Group），教师上传资料、学生苏格拉底引导式对话、教师发布测评、间隔复习巩固、进度掌握度、周报。
- 前端：PWA（H5 + ServiceWorker，离线 App Shell），目录 `frontend/`，设计风格 Apple native minimal + 暖珊瑚 #F2714E（学生）/ 教师靛蓝 #5B5BD6。
- 后端：单体 **Flask + waitress（单进程/4 线程）** + SQLite WAL + ChromaDB + DeepSeek（三 Agent 提示词），自托管于用户 Mac（24/7），Cloudflare 命名隧道暴露 5001。
- 同步模型：REST JSON，`/api/*` 前缀；成功 `{code:0,data:...}`，失败 `{code:E,msg:...}`。

## 2. 核心原则
1. 先读规格再编码：`Design-Spec-AI学习小组app.md`（需求追溯，唯一事实来源）+ `PRD-AI学习小组app.md`（需求）+ `architecture/architecture-design.md`（架构）。实现前先核对对应 REQ-ID。
2. 每阶段可运行可验收：完成一个功能即冒烟验证（curl/脚本），不堆积未验证代码。
3. 手术式修改：只写解决问题所需的最少代码，不重构无关代码、不引入多余依赖。
4. 安全底线不妥协：密码一律哈希（werkzeug）、SQL 全参数绑定、用户输入长度校验、JWT 鉴权、越权读返回 403/空。
5. 降级保守：AI 不确定时向保守侧兜底（拒绝/转固定引导语），绝不静默给结论。

## 3. 项目特定规范
- **语言**：中文注释，只注关键逻辑，不逐行解释。
- **代码风格**：PEP8；单文件 < 300 行，超则拆模块；函数单一职责。
- **API 风格**：RESTful `/api/*` 前缀（Blueprint 粒度：auth/chapters/materials/conversations/quizzes/attempts/progress/reports/teacher/health）；JSON 进出；错误统一 `{code:E,msg:...}` + 4xx/5xx。
- **时间存储**：一律 UTC（ISO 8601）。"今天"判定在前端本地时区做。
- **数据库**：SQLite WAL + busy_timeout；表结构变更写迁移函数，不手工改库。生产库用 `instance/<db>.sqlite` 或 `data/`，勿提交运行时产物。
- **鉴权**：`Authorization: Bearer <JWT>`；JWT 12h；角色 teacher/student；`@role_required("teacher")` 门禁；所有读操作经 `@user_scope` 自动 `WHERE user_id=g.user_id`。
- **AI 层**：三 Agent 提示词（TUTOR/QUIZZER/GRADER）在 `ai/prompts.py`；RAG 检索在 `ai/rag.py`（ChromaDB cosine + chapter_id 过滤，阈值 ≥0.4）；两层 Fallback（DeepSeek → 固定引导语池）；TUTOR 输出门控（拒绝规则 + 越界检测 + 界面「回答由 AI 生成」标注）。
- **强制校验**：每次改完必须跑 `python -m py_compile` + 冒烟测试；交付前过一遍自检清单（见 §7 验证清单）。

## 4. 标准开发流程
- 思考层：先列改动点与影响面，再动手。
- 规格层：新功能先核对 Design-Spec 的 REQ-ID；**任何交付（含 bug 修复、纯前端改动）必须同步回写 Design-Spec 对应 REQ-ID 的状态与说明**。需求缺失时提问题确认，不猜。
- 实现层：写→验→报（每次改动立即验证并一句话汇报）。
- 质量层：py_compile + `make lint test smoke` + 关键路径异常兜底（前端渲染 try/catch 防断 boot 链）。
- 版本层：Conventional Commits；版本号诚实规则（见 §5）。

## 5. 版本号诚实规则
- 任何产生 `CHANGELOG.md` 条目的改动，必须同 commit 把 `app.py` 的 `version="x.y.z"` 常量 bump 到与 CHANGELOG 完全一致（即使纯前端改动）。
- 版本语义：`x.0.0` 重构 / `x.y.0` 新功能 / `x.y.z` 修 bug。`curl /health` 返回 version 复验。

## 6. 多 Agent 协作（防撞车）
本项目由 Hermes（调度/运维/验收）+ Claude Code（开发）共同维护。纪律：
1. 开工前 `git status` 必须干净；工作树脏 = 有人在改，停手确认。
2. 同时只有一个 agent 改代码。
3. 改完立即 commit（Conventional Commits），不堆积。
4. push 前 `git pull --rebase`；push 后确认成功。
5. 大改留痕（commit message 写清影响面）。
6. 验收闸门：交付前 `make lint test smoke`；push 后 GitHub Actions CI 复验。
7. 冲突不硬解，报 Hermes 协调，不 `--force`。
8. 版本号诚实规则（§5）三方同守。

## 7. 验证清单（每次交付前）
- [ ] `python -m py_compile` 通过
- [ ] `make lint test smoke` 全绿
- [ ] `app.py` version == CHANGELOG 最新条目版本
- [ ] Design-Spec 对应 REQ-ID 已回写（状态 + 说明）
- [ ] 数据隔离：学生 A 读学生 B → 403/空（F9）
- [ ] push 成功（HEAD -> main）
- [ ] 重启后 health 返回新 version

## 8. 目录结构（Design Spec 附录 A）
```
backend/   app.py · config.py
           auth/routes.py · api/{chapters,materials,conversations,quizzes,attempts,progress,reports,teacher,health}.py
           ai/{prompts,rag,tutor,quizzer,grader,review_sched,fallback}.py
           data/{models,chroma_client,seed}.py · middleware/{rate_limit,error_handler,input_validation}.py
           scripts/{launchd_install,backup_rsync,restore_test}.sh
frontend/  index.html · manifest.webmanifest · sw.js · js/{api,app,learn,quiz,progress,report,admin}.js · css/
tests/     test_*.py（pytest + cov≥70% 目标）
deploy/    runbook · 备份/自启脚本
```