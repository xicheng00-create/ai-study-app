# 小白 AI 课程 · 8 周学习路径设计

> 面向：**职场成人 · 零技术基础**
> 节奏：**每周 4 小时 = 2 次 × 2 小时**（低密度、易坚持）
> 总目标：① 建立对 LLM 的技术基础认知 → ② 掌握产品管理基本功 → ③ 用 aicoding 搭出一个简单 AI Solution
> 工具栈：**Hermes（本地 AI 系统/LLM 后端）· WorkBuddy（工作区智能体/文档与编排）· Claude Code（终端 coding agent）**
> 取材自：`AI Product Management` 资料库（L1–L4、先导课、vibe coding 实操、解决方案专家资料、PM核心能力筑基）

---

## 一、课程三条主线（贯穿全 8 周）

| 主线 | 一句话目标 | 主要对应资料 |
|---|---|---|
| **A. LLM 技术认知** | 知道大模型是什么、能/不能做什么、RAG/Agent 是什么就够了（不深挖算法） | 先导课·预习三、L1-1、L2-10/11、L3 拓展 |
| **B. 产品管理基础** | 会用 PM 语言描述需求、画信息架构、写需求文档 | PM核心能力筑基、解决方案专家资料、L1-2/6/7/8 |
| **C. aicoding 实战** | 用三件套从一句话需求搭出能跑的小 AI 应用 | 先导课·预习四、L1-4/5、vibe coding 实操、L3-28/29 |

**降密度原则**：L2/L3/L4 里大量「RAG 三讲 / Agent 三讲 / 企业智能客服四讲 / 低成本私有化」属于进阶内容，本路径**只在概念层点到为止**，标记为「延伸/选修」，不强制，确保小白不劝退。

---

## 二、工具栈分工（学员必须分清"谁干什么"）

| 工具 | 角色定位 | 小白怎么用 |
|---|---|---|
| **Claude Code** | 终端里的 coding agent——写代码、改应用、搭骨架 | 用自然语言说需求，它生成/修改项目代码 |
| **WorkBuddy** | 工作区智能体——写 PRD/文档、做自动化、出可视化、辅助撰写 | 用对话产出文档、流程图、报告，编排任务 |
| **Hermes** | 你的本地 AI 系统 / 可选 LLM 后端 | 作为作品的"大脑"接入点，或当作"已部署 AI 系统"范例理解 |

> 一句话记忆：**Claude Code 写代码，WorkBuddy 写文档与编排，Hermes 提供智能。**

---

## 三、8 周详细路径

> 📺 标记 = 该 Session 推荐的网络视频课（B 站 / 官方教程 / 优质博文）。视频课作为**补充观摩**，不替代资料库原文；每 Session 挑 1 个看完即可，不强求全看。链接来自公开网络资源，访问异常时以资料库原文为准。

### 第 1 周 · 大模型是什么：建立 AI 基础认知
- **目标**：搞懂 LLM 是什么、Token/上下文/幻觉/微调等术语，破除"AI 很神秘"的恐惧。
- **Session 1（2h）概念扫盲**
  - 先导课·预习三《大模型基础认知》
  - 解决方案专家资料《零基础人员如何入门 AI？.pdf》
  - 先导课《智泊AI大模型解决方案专家课》PPT — 先看全景：AI 产品经理能力地图与课程总览
  - 解决方案专家资料《行业黑话大全.md》— 5 个术语卡片可从此取词，降低后续阅读门槛
  - 🧱 **浅讲 Transformer（1–2 分钟，不深挖）**：大模型（LLM）的底层"架构"叫 **Transformer**，核心是"注意力机制"——让模型读一句话时能判断哪些词彼此相关。小白只需记住这个名字 + 它解决的是"理解上下文"问题，数学/内部结构不要求。
  - 动手：用大白话记 5 个术语卡片（Token / 上下文窗口 / Transformer / 幻觉 / 微调）。
  - 📺 **推荐视频课**：
    - [智泊AI《AI大模型零基础全套教程》](https://www.bilibili.com/video/BV1KUwazoEXH/) — **前 30 分钟（认识大模型 + 学习指南）** 最贴合本周，零基础友好；本套也是 W7「Agent / 工具调用 / MCP」章节的来源（跨周主线视频）
    - [吴恩达《Generative AI for Everyone》中文版](https://www.bilibili.com/video/BV11G411X7nZ/) — 零基础讲清 AI 能做什么，最通俗
    - [李宏毅《生成式AI导论 2024》](https://www.bilibili.com/video/av1251133686/) — 体系最完整，适合想多懂一点的人
    - [大模型零基础全套教程](https://www.bilibili.com/video/BV1D5QRYkEmg/) — 偏实操演示
  - 📌 **Transformer 想多懂一点（进阶选看）**：同系列后续《Transformer 结构简介》一集（约第 69 集），仅兴趣者看，不强求。
- **Session 2（2h）AI 产品地图**
  - L1-1《建立 AI 产品认知与了解 AI 产品现状及岗位》
  - L1-3《AI 大模型时代机会》PDF — 看 AI 在哪些行业已落地，为"AI 能解决什么"打样
  - 💡 **讲清"幻觉"（hallucination）**：大模型会"一本正经地编造"看似合理但错误/不存在的内容。这是 PM 必须向用户/老板讲清的边界——AI 不是搜索引擎，不能保证 100% 准确。本周先建立认知，W7 会讲用 RAG / 限定范围来抑制。
  - 讨论：AI 现在能做什么、不能做什么（含幻觉带来的风险与应对）。
  - 📺 **推荐视频课**：
    - [卡帕西《ChatGPT 与大语言模型》讲解](https://www.bilibili.com/video/BV16cNEeXEer/) — 业界大牛讲 LLM 原理与边界，建立"产品地图"
- **本周产出**：一张「我眼中的 AI」概念卡片（图文即可）。

### 第 2 周 · 从用户视角看：AI 能解决什么
- **目标**：建立"问题 → AI 解法"直觉；理解 AIPM 与传统 PM 的区别。
- **Session 1（2h）AIPM vs 传统 PM**
  - L1-2 / L1-3《传统 PM 与 AIPM 的区别及 AI 产品基本工作流程》
  - PM核心能力筑基《39、AI产品经理初了解》《40、大模型应用PM vs 传统PM》《2、大模型产品toC还是toB？》《3、产品经理能力模型》— 把"AIPM 是什么"讲透
  - L1-2 课后导读《产品经理到底要不要学技术.md》— 帮你判断本课程要学到什么程度
  - 📺 **推荐视频课**：
    - [AI 产品经理入门教程](https://www.bilibili.com/video/BV1XNd3YeEbf/) — 系统讲 AIPM 是什么、与传统 PM 区别
    - [零基础转行 AI 产品经理](https://www.bilibili.com/video/BV1qo26BbE4x/) — 从岗位视角看 AI 产品工作流
- **Session 2（2h）真实落地案例**
  - 解决方案专家资料《AI 场景落地案例》《需求文档模板案例》— 案例库共 30+ 篇（智能客服/推荐/风控/RAG 等），按需取 2–3 篇精读
  - 精读示例：《美团智能客服案例拆解》《Agent 电商智能客服项目实战（已脱敏）》《基于知识图谱的 RAG 智能客服》
  - 动手：列出**自己工作中 3 个可被 AI 改造的场景**。
  - 📺 **推荐视频课**：
    - [AI 产品经理真实落地案例解析](https://www.woshipm.com/?p=6252150) — 人人都是产品经理：行业落地案例与需求模板参考
- **本周产出**：3 个"我的 AI 改造场景"清单。
- 🏁 **里程碑 1（认知）**：能向同事用 3 句话说清"什么是大模型、能干嘛"。

### 第 3 周 · 产品管理基本功（一）：需求与信息架构
- **目标**：学会用 PM 语言描述需求；看懂/画出信息架构图。
- **Session 1（2h）信息架构**
  - 解决方案专家资料《AI 产品经理必备的产品信息架构图.pdf》
  - PM核心能力筑基《14、产品文档-信息架构设计的核心思路》《13、产品文档-系统架构从0到1的落地》《12、产品文档-全面了解产品文档》— 系统学信息架构与产品文档
  - 📺 **推荐视频课**：
    - [PRD 与产品架构撰写教程](https://www.bilibili.com/video/BV1kY411G7x2/) — 讲清信息架构与需求文档的关系（含画图思路）
- **Session 2（2h）需求文档初写**
  - 解决方案专家资料《需求文档模板案例》
  - PM核心能力筑基《17、产品文档-产品PRD文档落地》《16、产品体验设计原则及产品原型设计》— PRD 与原型怎么写
  - 动手：用 **WorkBuddy** 辅助，把第 2 周的一个场景写成需求卡片。
  - 📺 **推荐视频课**：
    - [PRD 撰写实战模板](https://www.woshipm.com/?p=6252150) — 人人都是产品经理：需求文档模板，照着写第一份草稿
- **本周产出**：1 份需求文档草稿（WorkBuddy 辅助生成）。

### 第 4 周 · 产品管理基本功（二）：Prompt 工程与 AI 工作流
- **目标**：掌握"向 AI 表达需求"的技巧；并**提前把 WorkBuddy + Hermes 装好跑通**，为后续 aicoding 实战铺路。
- **Session 1（2h）Prompt 工程**
  - L1-6 / L1-7《Prompt 工程：业务增效关键点（上/下）》
  - 📺 **推荐视频课**：
    - [Prompt 工程系统教程](https://www.bilibili.com/video/BV1s24y1F7eq/) — 从基础到业务增效的完整讲解
    - [吴恩达《ChatGPT Prompt Engineering》中文版](https://www.bilibili.com/video/BV1Bo4y1A7FU) — 经典短课，建立结构化表达习惯
- **Session 2（2h）实战：装 WorkBuddy → 让 WorkBuddy 帮忙装 Hermes**
  - 目标：早期就建立"用 WorkBuddy 干活 + 本地 AI 大脑 Hermes 就位"的能力，后续周次直接复用，不再卡环境。
  - 动手（全程实操，不讲课）：
    1. 安装 **WorkBuddy**，完成首次对话，让它帮你产出一份文档（体验"让 AI 写东西"）。
    2. 用 WorkBuddy 辅助，把第 2 周的一个 AI 改造场景写成需求卡片（或改造一个重复工作流）。
    3. **关键实战**：用自然语言让 **WorkBuddy 帮忙安装 / 部署 Hermes**（你的本地 AI 大脑），跑通一次最小调用验证（如发"你好"→ 收到返回）。
  - 📺 **推荐视频课**：
    - [WorkBuddy 入门教程合集](https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a) — 安装 + 首次对话 + 对话生成文档
    - [WorkBuddy 三种工作模式](https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a) — Agent / Plan / Ask 怎么切
    - [WorkBuddy 三大场景](https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a) — 文档 / 编排 / 可视化怎么用
  - 📌 **关于"部署 Hermes"的视频课**：Hermes 是你的**私有本地 AI 系统**，公开网络没有"如何部署 Hermes"的视频；本课以"用 WorkBuddy 实操安装"为唯一教学路径（讲师提供 Hermes 安装包 / 脚本）。原理层可补看本地大模型部署公开课：
    - [Ollama 本地部署大模型](https://www.bilibili.com/video/BV1hLqCYGESx/)
    - [DeepSeek 本地部署](https://www.bilibili.com/video/BV1nMNeePEZd/)
    - 资料库内部课件：**L2-19《低成本打造私有化大模型实战》**、解决方案专家资料《2025主流AI智能客服系统技术对比分析，RAG、知识库、私有化部署能力.pdf》—— 私有化部署思路直接对应 Hermes 部署
- **本周产出**：一套高频 Prompt 模板 + 已装好的 WorkBuddy + 已部署并跑通的 Hermes（可调用）。
- 🏁 **里程碑 2（PM 基础 + 工具就位）**：能写需求 + Prompt，且 WorkBuddy 已装、Hermes 已可调用。

### 第 5 周 · aicoding 入门：认识三件套
- **目标**：理解 vibe coding / aicoding 范式；分清三件套各自干什么（WorkBuddy + Hermes 已在 W4 就位，本周只补 Claude Code）。
- **Session 1（2h）范式认知**
  - 先导课·预习四《vibe coding》
  - 先导课·预习四《Vibe Coding 基础.pdf》《Trae 零基础入门.pdf》— vibe coding 工具与思路补充
  - L1-4 / L1-5《vibe coding 基础夯实与垂直行业分析》
  - 💡 **预告**：Claude Code 这类工具本身就是"coding agent"——能自主写代码去完成目标。它的"自主干活"本质，W7 会正式讲 Agent 概念，先有个印象即可。
  - 📺 **推荐视频课**：
    - [什么是 vibe coding？怎么上手](https://code.tutsplus.com/what-is-vibe-coding-how-to-do-it--ytc-106c) — 英文图解，概念最清晰
    - [vibe coding 教程合集](https://vibecodingwiki.com/wiki/vibecoding-tutorials) — 多场景实操集合，挑"搭小应用"看
- **Session 2（2h）Claude Code 第一次启动**
  - 说明：WorkBuddy 与 Hermes 已在 **W4** 装好并跑通，本周只需补齐写代码的 agent —— **Claude Code**。
  - Claude Code：安装并跑通一个 hello-world 级命令；用自然语言让它生成一个简单函数。
  - 📺 **推荐视频课**：
    - [Claude Code 小白教程](https://www.bilibili.com/video/BV1qQmgB5ENs/) — 终端 coding agent 第一次启动演示
    - [非程序员小白 Claude Code 官方教程](https://ima.qq.com/wiki/?shareId=6b3816551da2f69efc894947c9387cda7833893ec200c4a2942e75ab56027507) — 零基础友好
- **本周产出**：Claude Code 跑通最小任务；三件套环境全部就绪（WorkBuddy + Hermes 来自 W4）。

### 第 6 周 · aicoding 实战（一）：用 Claude Code 搭骨架
- **目标**：用自然语言让 Claude Code 生成一个简单应用的骨架。
- **Session 1（2h）需求 → 规格**
  - vibe coding 实操《00-overview》《01-requirement-chat》《02-feature-spec》
  - 动手：把第 3 周的需求卡片，用对话转成功能规格。
  - 📺 **推荐视频课**：
    - [Claude Code 新手笔记：从需求到代码](https://lilys.ai/zh/notes/claude-code-20251026/claude-code-tutorial-for-beginners) — 图文步骤，适合边看边做
- **Session 2（2h）生成原型**
  - 实操：让 Claude Code 从一句需求生成"个人问答小工具"原型（本地可运行页面/脚本）。
  - 📺 **推荐视频课**：
    - [Claude Code 实战：生成可运行应用](https://www.bilibili.com/video/BV1qQmgB5ENs/) — 复用 W5 教程中的"生成项目"章节，重点看 demo
- **本周产出**：一个可本地运行的迷你原型。
- 🏁 **里程碑 3（能搭骨架）**：能用一句话需求让 Claude Code 产出可运行骨架。

### 第 7 周 · aicoding 实战（二）：接上"智能"（RAG/Agent 浅解 + Hermes）
- **目标**：概念级理解 RAG / Agent；把 LLM 能力接进应用，让小工具"能回答"（Hermes 已在 W4 部署好，本周直接调用）。
- **Session 1（2h）概念白盒（点到为止）**
  - L2-10《大模型架构白盒与商业选型》
  - L2-11《RAG 全流程解析》前段（只理解"检索增强"是什么）
  - L2-14/15/16《Agent 工作流与应用落地实践》三讲 — 看 Agent 怎么从概念落到真实工作流
  - 解决方案专家资料《MCP 实践：基于 MCP 实现 Agent 知识库系统》《基于 MCP 搭建"私人旅行助手"智能体》— 直接对应上方"MCP"概念，看标准怎么落地
  - 先导课·图解大模型《LangChain 快速入门》+ L2-12《RAGFlow 入门与实战》/ L2-11《基于 FastGPT 构建人事 RAG 管理系统》— 工具调用与 RAG 落地参考（选看）
  - 🤖 **AI Agent 概念（核心）**：Agent = 能"自己规划步骤、调用工具、反复试错"去完成目标的 AI，区别于"你问一句它答一句"的聊天。三要素：感知/输入 → 思考规划 → 行动（调工具）。
  - 🔧 **工具调用（tool calling）**：大模型不止能"说话"，还能"调函数"——比如查天气、读数据库、发邮件。工具调用是 Agent 能"干活"的底层能力。
  - 🔌 **MCP（概念级）**：Model Context Protocol，一套"给 AI 接工具/数据源"的通用标准（类似 USB 接口）。知道"有了 MCP，AI 就能统一对接各种外部系统"即可，不要求懂协议细节。
  - 📺 **推荐视频课**：
    - [智泊AI《AI大模型零基础全套教程》· Agent / 工具调用 / MCP 章节](https://www.bilibili.com/video/BV1KUwazoEXH/) — 同 W1 那套；其中《Agent 概念、组成与决策》《Agent 工具使用》《LangGraph 接入 MCP》几集正好对应上面三个概念（概念级跟看即可）
    - [AI Agent 是什么（科普）](https://thehumanco.org/ai-resources/ai-agents) — 图文讲清 Agent 与 Workflow 区别
- **Session 2（2h）接智能（调用 W4 已部署的 Hermes）**
  - 用 **W4 已部署的 Hermes** 作为 LLM 后端，让第 6 周的小工具"能回答问题"；或用 WorkBuddy 接入 DeepSeek 兜底。
  - L3 拓展《用 WorkBuddy 辅助完成文档撰写》
  - 📺 **推荐视频课**：
    - [DeepSeek 本地部署](https://www.bilibili.com/video/BV1nMNeePEZd/) — LLM 后端接入原理参考（Hermes 同理）
    - [Ollama 本地部署大模型](https://www.bilibili.com/video/BV1hLqCYGESx/) — 复习"模型怎么跑在本地"（Hermes 同源思路）
    - [WorkBuddy 三大场景](https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a) — 文档/编排/可视化怎么用
    - 资料库内部课件：**L2-19《低成本打造私有化大模型实战》** — 私有化部署复盘，理解 Hermes 后端怎么跑
- **本周产出**：一个能回答问题的迷你 AI 助手（RAG 概念级 demo，调用本地 Hermes）。
- 📌 进阶（选修）：L2-12/13 RAG 痛点调优、L2-14/15/16 Agent 工作流——学有余力再看。

### 第 8 周 · 结业：端到端搭一个简单 AI Solution + 展示
- **目标**：整合所学，交付一个解决自己真实小问题的 AI 作品。
- **Session 1（2h）落地打磨**
  - L3-28 / L3-29《AI coding 落地实现（一/二）》
  - 加餐课《deepseek harness》（理解如何接模型后端）
  - L3 加餐课《循环之上 Loop-Engineering》PDF — 进阶：让 Agent 持续自我迭代（学有余力看）
  - 动手：完善作品功能与边界。
  - 📺 **推荐视频课**：
    - [Claude Code 落地实战回顾](https://www.bilibili.com/video/BV1qQmgB5ENs/) — 串起 W5–W7 的 coding 动作，做结业打磨参考
- **Session 2（2h）文档 + 展示**
  - 用 **WorkBuddy** 写 1 页使用说明 / README
  - 组内（AI学习小组）展示 demo，互相点评。
  - 📺 **推荐视频课**：
    - [WorkBuddy 三种工作模式](https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a) — 用 WorkBuddy 写说明/README 时参考
- **结业项目**：一个解决你真实小问题的 AI 小工具
  - 示例：个人知识问答助手 / 自动周报生成器 / 简易智能客服 demo
  - 必须用到 **Claude Code（搭）+ WorkBuddy（文档/编排）+ Hermes 或 DeepSeek（智能）**
- **本周产出**：可演示作品 + 1 页说明。
- 🏁 **里程碑 4（交付）**：端到端交付一个简单 AI Solution。

---

## 四、阶段里程碑与评估方式

| 周次 | 里程碑 | 验收（轻量） |
|---|---|---|
| W2 | 认知 | 能 3 句话讲清大模型 |
| W4 | PM 基础 | 1 份需求 + 1 套 Prompt |
| W6 | 能搭骨架 | Claude Code 产出可运行原型 |
| W8 | 交付作品 | 可演示 AI 小工具 + 说明 |

> 评估以"每周产出物"为准，不做考试；W8 以作品展示代替笔试，契合成人自学、低密度原则。

---

## 五、资料 → 周次 映射表（方便备课/取料）

| 资料（来自 AI Product Management） | 用到周次 |
|---|---|
| 先导课·预习三《大模型基础认知》 | W1 |
| 解决方案专家资料《零基础人员如何入门 AI？》 | W1 |
| L1-1 建立 AI 产品认知 | W1 |
| L1-2 / L1-3 传统PM与AIPM区别 | W2 |
| 解决方案专家资料《AI 场景落地案例》《需求文档模板案例》 | W2/W3 |
| 解决方案专家资料《AI 产品经理必备的产品信息架构图》 | W3 |
| PM核心能力筑基与AI转型指南（选修） | W3 |
| L1-6 / L1-7 Prompt 工程 | W4 |
| L1-8 / L1-9 大模型赋能工作流 | W4（工作流思路，概念层） |
| **W4S2 实战：WorkBuddy 安装 + 用 WorkBuddy 部署 Hermes** | W4（核心提前量） |
| L2-19《低成本打造私有化大模型实战》 | W4（Hermes 部署原理）/ W7 |
| 解决方案专家资料《2025主流AI智能客服系统技术对比分析，RAG、知识库、私有化部署能力》 | W4（Hermes 私有化部署参考） |
| 先导课·预习四《vibe coding》 | W5 |
| L1-4 / L1-5 vibe coding 基础 | W5 |
| 202604 vibe coding 实操（00/01/02） | W6 |
| L2-10 架构白盒 / L2-11 RAG 解析 | W7 |
| L3 拓展·用 WorkBuddy 辅助文档撰写 | W7 |
| L3-28 / L3-29 AI coding 落地实现 | W8 |
| 加餐课·deepseek harness | W8 |
| 外部视频·智泊AI《AI大模型零基础全套教程》(BV1KUwazoEXH) | W1（前 30 分钟 认识大模型）+ W7（Agent / 工具调用 / MCP 章节）— 跨周主线视频 |
| 概念融合：Transformer 浅讲 / 幻觉 hallucination | W1 |
| 概念融合：AI Agent 概念 / 工具调用 tool calling / MCP | W7 |
| 先导课《智泊AI大模型解决方案专家课》PPT / 解决方案专家资料《行业黑话大全.md》 | W1（全景 + 术语取词） |
| L1-3《AI 大模型时代机会》 | W1 / W2 |
| PM核心《39 AI产品经理初了解》《40 大模型应用PM vs 传统PM》《2 toC/toB》《3 能力模型》 | W2 |
| L1-2 课后导读《产品经理到底要不要学技术》 | W2 |
| 解决方案专家资料·AI场景落地案例库（30+ 篇，精读美团/Agent电商/RAG客服等） | W2 |
| PM核心《14 信息架构核心思路》《13 系统架构落地》《12 产品文档》 | W3 |
| PM核心《17 PRD文档落地》《16 产品原型设计》 | W3 |
| 先导课·预习四《Vibe Coding 基础.pdf》《Trae 零基础入门.pdf》 | W5 |
| L2-14/15/16《Agent 工作流与应用落地实践》三讲 | W7 |
| 解决方案专家资料《MCP 实践：基于 MCP 实现 Agent 知识库系统》《基于 MCP 搭建私人旅行助手》 | W7（MCP 概念落地） |
| 图解大模型《LangChain 快速入门》+ L2-12 RAGFlow + L2-11 FastGPT人事RAG | W7（选看） |
| L3 加餐课《循环之上 Loop-Engineering》 | W8（进阶） |

**标记为延伸/选修（不强制）**：L2-12~19（RAG/Agent/私有化深挖）、L3-21~27（教育 agent 全生命周期，偏项目实战）、L4 全阶段（多行业作品集、企业智能客服、DeepResearch，属进阶）、大厂面试真题、图解大模型系列。

**本轮深挖新挖出的高价值资料（建议补进备课）**：
- 部署实战：**L2-19《低成本打造私有化大模型实战》**、解决方案专家资料《2025主流AI智能客服系统技术对比分析，RAG、知识库、私有化部署能力.pdf》、L2-15《Docker 安装教程.pdf》、L3-21 高考志愿填报作业 `deploy/DEPLOY.md` + `本地穿透-Mac指南.md`。
- RAG / 低代码：L2-12《RAGFlow 入门与实战》、L2-11《基于FastGPT构建人事RAG管理系统》、L2-16《Coze实操.pdf》。
- 多行业作品集（L4 阶段 8 套案例 PPT：发票识别、简历筛选、合同审查、自媒体处理、AI资讯助手、工业设备智维、风控报告、企业智能客服）—— 可作 W8 结业作品灵感库。
- 说明：以上多为进阶/选修，按"降密度原则"只作参考，不强制。

**本轮（用户要求再加料）新增匹配课程周次的资料**：
- W1：先导课《智泊AI大模型解决方案专家课》PPT（全景）、解决方案专家资料《行业黑话大全.md》（术语取词）
- W2：PM核心《39 AI产品经理初了解》《40 大模型应用PM vs 传统PM》《2 toC/toB》《3 能力模型》、L1-2 课后导读《产品经理要不要学技术》、解决方案专家资料·AI场景落地案例库（30+ 篇，精读 2–3 篇）
- W3：PM核心《14 信息架构核心思路》《13 系统架构落地》《12 产品文档》《17 PRD文档落地》《16 产品原型设计》
- W5：先导课·预习四《Vibe Coding 基础.pdf》《Trae 零基础入门.pdf》
- W7：L2-14/15/16《Agent 工作流与应用落地实践》三讲、解决方案专家资料《MCP 实践：基于 MCP 实现 Agent 知识库系统》《基于 MCP 搭建私人旅行助手》、图解大模型《LangChain 快速入门》、L2-12 RAGFlow、L2-11 FastGPT人事RAG
- W8：L3 加餐课《循环之上 Loop-Engineering》PDF（进阶）

---

## 六、给讲师 / 自学者的备注
1. **密度控制**：每 Session 2h = 约 50min 讲解/共读 + 60min 动手 + 10min 复盘；动手优先，少灌概念。
2. **先问后做**：每周动手前，先让学员用自己工作场景举例，避免"听懂但不会用"。
3. **三件套要早装**：**W4 就完成 WorkBuddy 安装 + 用 WorkBuddy 部署 Hermes**（本路径关键提前量）；W5 补装 Claude Code。三件套在 W5 末全部就绪，W6 起直接实战不卡。
4. **Hermes 定位**：W4 即由 WorkBuddy 帮装并跑通最小调用，小白从第一节实战就见到"本地 AI 大脑"长什么样；W7 再把它接进自己的作品，认知负荷已提前摊销。
5. **可裁剪**：若学员完全无编程意愿，W6–W8 可降级为"用 WorkBuddy + Hermes 搭无代码 AI 工作流"，不强制写代码。
6. **视频课定位**：📺 标记的网络视频为**补充观摩材料**，与资料库原文互为补充；链接取自公开平台，若某条失效，以同主题资料库原文或搜索"主题关键词 + 教程"替代即可。
7. **本轮概念融合（用户点名的盲区）**：① **Transformer** 在 W1 浅讲（1–2 分钟，不深挖，只记名字与"理解上下文"作用），进阶见同系列第 69 集；② **幻觉 hallucination** 在 W1S2 讲清"编造"本质与 PM 边界，W7 接 RAG 抑制；③ **AI Agent 概念 / 工具调用 / MCP** 集中在 W7S1 概念白盒，配智泊AI教程对应章节；④ W5 加一句 Claude Code 即"coding agent"的预告。智泊AI全套教程作为**跨周主线视频**：W1 看前 30 分钟、W7 看 Agent/工具/MCP 章节。
