# AI 学习小组 App — 原型设计交付概览（v3）

## 本轮完成内容（对齐 Design Spec v2.0）
1. **复制 PRD** + 已完成 PRD v2.1 升级（引导式对话/巩固闭环/教师轻量审核/章节管理）。
2. **Design Spec 已出**：`Design-Spec-AI学习小组app.md`（v2.0，融合 Functional+Technical，含 REQ 追溯矩阵、状态机、部署韧性 F1–F10、NFR 盲区）。
3. **原型升级（v3）**：对照 Design Spec 逐条补齐 PRD 已定义、原型此前缺失的细化项——

| 缺口 | v3 落地 |
|------|---------|
| CHAT-005 ≤12 轮护栏 | 轮次计数 + 「模拟第12轮（强制给结论+推荐练习）」 |
| CHAT-004 TUTOR 输出门控 | 对话顶部「回答由 AI 生成，请核对资料原文 · 越界已拦截」门控条 |
| CHAT-003 意图路由 | 答疑/复习/出题 三态 chips，出题→测评、复习→进度 |
| CHAT-008 多对话 | 对话列表 chip + 新建/删除本人对话 |
| QUIZ-004 测评报告(错题) | 提交后展示错题明细（你的答案/正确答案/原因） |
| QUIZ-007 重出新 version | 教师「重出」→ 新 draft(version+1)，旧版 superseded |
| PROG-003 成绩趋势 | SVG 折线图 |
| PROG-002 按章提问统计 | 章节状态卡显示「提问 N 次」 |
| PROG-006 间隔复习状态机 | 真正闭环：作答→答对 interval×3(1→3→7)/错重置1→done |
| ADMIN-002 资料解析态 | 已解析/解析中/解析失败 三态 + 失败重试 |
| F7 软删除 | 删除二次确认 + 7 天窗口提示 |
| RPT-004 教师全班周报 | 聚合概览 + 共性薄弱 + AI 教学建议 |

4. **文档同步**：`prototype/原型设计说明.md` 更新为 v3（变更对照 + 验证清单）。

## 关键定义（已写入 PRD / Design Spec）
- 掌握度单元 = 章节；`M = Σ(wᵢ·correctᵢ)/Σ(wᵢ)`（时间衰减）；四态：已掌握 M≥80 且≥2次 / 进行中 50–79 / 薄弱 <50 / 未评估（不计入薄弱）。
- 薄弱点带错题依据，拒绝凭空定性；掌握度按**最新 published version** 聚合（F3）。
- 引导式对话：不直接给答案、≤12 轮护栏、TUTOR 输出门控；巩固练习间隔复习 1→3→7 天。

## 预览
浏览器打开 `prototype/index.html`；登录选「教师/学生视图」。学生：苏格拉底引导+门控+多对话、作答看错题明细、进度看趋势+按章提问+间隔复习闭环。教师：草稿→确认发布、重出生成新version、资料解析态+软删除、全班周报聚合。

## 架构
- `architecture/architecture-design.md`（v1.1）+ `architecture/architecture-diagram.svg`（5 层+2 横切）。
- 关键决策：单体 Flask+waitress（单进程/4 线程）/ 极简三 Agent 提示词 / 纯向量 RAG / 不做 Evals。
- 再审修订项：LaunchDaemon 自启、备份前 wal_checkpoint、attempts.quiz_version、8GB 实测、TUTOR 门控、软删除、waitress 术语。

## 后续
- 工程落地按 Design Spec §12 三阶段推进；SSE 流式、错题本、命名隧道、launchd 自启等留待 P2/部署阶段。
