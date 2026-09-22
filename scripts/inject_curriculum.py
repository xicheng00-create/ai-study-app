#!/usr/bin/env python3
"""通用课件注入：把 课件/第N章/（课件.md 教案 + 材料/ 源文件）上架到老师端后台。

2026-09-22：课件目录 `WxSy` → `第N章`；材料支持子目录（深度 ≤2）与 html 演示稿；
图片型 PDF/PPTX 走 OCR 文本（材料/_ocr/ 缓存）。文件发现规则见 scripts/courseware_files.py。

方案 B：不复制原件进 uploads/，仅解析文本块 + 写元数据；源文件留在 课件/ 目录（source_path 绝对路径）。
新建 session/chapter/material/chunk 一律 status='draft'（学生不可见），教师后台发布后可见。
视频链接（video_resources）默认 draft，随 session 发布。

幂等：先删该周旧数据，再注入（可重复运行）。

用法：
    ./.venv/bin/python scripts/inject_curriculum.py W3S1 W3S2   # 只注入指定 session（W3S1=第5章）
    ./.venv/bin/python scripts/inject_curriculum.py --week 3     # 注入某周全部 session
    ⚠️ 章号换算：N = (week-1)*2 + session_no（W3S1→第5章 … W8S2→第16章）
    python3 scripts/inject_curriculum.py --backfill-courseware   # 给已有章节补挂 课件.md
"""
import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
sys.path.insert(0, str(BASE / "backend"))
from ai import parser  # noqa: E402  pdfplumber/pptx 解析

sys.path.insert(0, str(Path(__file__).resolve().parent))
import courseware_files  # noqa: E402  材料文件发现（递归 + 资源包守卫）

DB = BASE / "instance" / "aistudy.sqlite3"
COURSE = BASE / "课件"

# 预抽取文本副本（与同名 PDF 内容重复），不参与切片，避免 RAG 重复召回
SKIP_SUFFIXES = ("_extracted.txt",)


def new_id():
    return str(uuid.uuid4())


def utcnow(offset_sec=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat()


def chapter_no(s: dict) -> int:
    """章节全局序号（v2.7.0 解耦「周/节」展示口径）：每周 2 讲 → W1S1=1、W1S2=2、W2S1=3…"""
    return (int(s["week"]) - 1) * 2 + int(s["no"])


SPECS = {
    "W2S1": {
        "week": 2, "no": 1, "dir": "第3章",
        "title": "AIPM vs 传统 PM",
        "goal": (
            "用 3 个以上维度（定位/底层逻辑/价值核心）说清传统 PM 与 AIPM 的差异；"
            "理解确定性逻辑 vs 概率性逻辑 + 泛化能力；"
            "掌握 9 步工作流、场景化落地、Copilot/Autopilot、Evals 意识；"
            "建立「AI 产品经理要不要学技术」的下限与上限认知，避免两个极端误区；"
            "产出一张「传统 PM vs AIPM」对比表（差异行数 ≥ 5 行）。"
        ),
        "concept_tags": [
            "传统PM", "AIPM", "确定性逻辑", "概率性逻辑", "泛化能力", "管控不确定性",
            "9步工作流", "场景化落地", "Copilot", "Autopilot", "Evals",
            "GUI", "CUI", "结构性困境", "信息差护城河", "toB", "信任链", "Vibe Coding",
        ],
        "milestone": "一张「传统 PM vs AIPM」对比表（差异行数 ≥ 5 行）",
        "videos": [
            {
                "title": "AI 产品经理入门教程",
                "url": "https://www.bilibili.com/video/BV1XNd3YeEbf/",
                "platform": "bilibili",
                "description": "重点看：AIPM 到底是什么、与传统 PM 的核心区别、AI 产品经理的日常工作内容。对应课件 3.1–3.5 的定位与逻辑差异。",
            },
            {
                "title": "零基础转行 AI 产品经理",
                "url": "https://www.bilibili.com/video/BV1qo26BbE4x/",
                "platform": "bilibili",
                "description": "重点看：从岗位视角看 AI 产品的实际工作流、能力要求与转型路径。对应课件 3.6–3.8 的方法论与学技术讨论。",
            },
        ],
    },
    "W2S2": {
        "week": 2, "no": 2, "dir": "第4章",
        "title": "真实落地案例",
        "goal": (
            "掌握「四问拆读法」（痛点 / AI 解法 / 数据知识来源 / 边界与兜底）拆解任意 AI 落地案例；"
            "分清三类高频 AI 产品形态：RAG 知识问答、Agent 自动化、MCP 协议连接；"
            "讲清智能客服三种技术路线 PairQA / DocQA / KBQA 的差异与适用边界；"
            "掌握 KBQA 四大流程（Query 理解 / 关系识别 / 子图召回 / 答案排序）与三大落地挑战；"
            "掌握电商智能客服三大核心能力（多轮对话管理 / 意图识别 / 知识推荐）；"
            "了解知识图谱增强 RAG；MCP 概念预览；产出 3 个「我的 AI 改造场景」清单。"
        ),
        "concept_tags": [
            "四问拆读法", "PairQA", "DocQA", "KBQA", "知识图谱", "RAG", "Agent", "MCP",
            "槽位填充", "Slot Filling", "意图识别", "知识推荐", "多跳查询", "实体链接",
            "依存分析", "子图召回", "答案排序", "交互型BERT", "层次剪枝", "微服务架构",
        ],
        "milestone": "3 个「我的 AI 改造场景」清单",
        "videos": [
            {
                "title": "AI 产品经理真实落地案例解析",
                "url": "https://www.woshipm.com/?p=6252150",
                "platform": "woshipm",
                "description": "从行业落地视角讲 AI 产品经理如何拆解真实案例、提炼需求模板与方法论，与本节「四问拆读法 + 三篇技术型案例精读」互补。",
            },
        ],
    },
    "W3S1": {
        "week": 3, "no": 1, "dir": "第5章",
        "title": "信息架构",
        "goal": (
            "说清三件事的边界：产品文档（团队沟通语言）、系统架构（工程实现蓝图）、信息架构（产品逻辑骨架）三者的差异与联系；看懂一张 AI 信息架构图：能识别\"三层五维\"结构——基础支撑层、核心能力层、应用层；以及数据流、控制流、技术选型、集成关系、反馈机制五个标注维度（来源：《AI产品经理必备的产品信息架构图.pdf》p1）；动手画出最小 IA 图：拿自己 第 3–4 章列出的 1 个 AI 改造场景，套用三段式，产出第一张 6–8 个节点的 IA 图；理解 PM 与开发的协作语言：能向工程师讲清\"我描述 IA，你搭建 SA，文档是共同语言\"。"
        ),
        "concept_tags": [
            "为什么小白要先学\"信息架构\"", "产品文档家族：BRD / MRD / PRD 的角色分工", "系统架构：从 0 到 1 的落地四步法", "信息架构：产品逻辑的\"骨架\"", "重点案例：AI 产品的\"三层五维\"信息架构图", "三者关系：IA × SA × 文档",
        ],
        "milestone": "1 张信息架构图 v1（手绘/拍照）：至少 6 个节点，分三层，五维至少标 3 个。命名\"信息架构图_v1_姓名\"，发到 AI 学习小组群",
        "videos": [
            {
                "title": "PRD 与产品架构撰写教程",
                "url": "https://www.bilibili.com/video/BV1kY411G7x2/",
                "platform": "bilibili",
                "description": "讲清信息架构与需求文档的关系（含画图思路）",
            },
        ],
    },
    "W3S2": {
        "week": 3, "no": 2, "dir": "第6章",
        "title": "需求文档初写",
        "goal": (
            "理解 PRD 是什么：清楚需求文档（Product Requirements Document）在团队中承担“消除信息不对称”的沟通作用，是连接产品、设计、研发、测试的共同语言；掌握 PRD 的标准结构与写法：能独立写出包含「背景与目标 / 用户故事 / 功能列表 + 验收标准 / 边界 / 异常态」的需求卡片，并能对照模板自查；理解原型设计与需求的关系：知道原型是交互逻辑的可视化表达，先低保真验证思路，再高保真细化；理解体验设计原则如何反哺需求描述；用 WorkBuddy 辅助产出：把第 4 章（第 4 章）选定的一个 AI 改造场景，借助 AI 协作写成一份结构清晰的需求文档草稿，并完成人工修订。"
        ),
        "concept_tags": [
            "PRD 是什么", "PRD 包含什么", "原型设计原则",
        ],
        "milestone": "1 份需求文档草稿（WorkBuddy 辅助生成 + 本人修订），要求：",
        "videos": [
            {
                "title": "PRD 撰写实战模板",
                "url": "https://www.woshipm.com/?p=6252150",
                "platform": "woshipm",
                "description": "人人都是产品经理：需求文档模板，照着写第一份草稿",
            },
        ],
    },
    "W4S1": {
        "week": 4, "no": 1, "dir": "第7章",
        "title": "Prompt 工程",
        "goal": (
            "建立\"Prompt 工程\"认知：你跟大模型说的每一句话都是 Prompt，提示词决定模型在具体业务里的\"表现下限\"；掌握结构化 Prompt 的六要素（角色 / 场景 / 任务 / 示例 / 约束 / 参考），并能照模板写出稳定可控的提示词；了解进阶技巧：零样本 / 少样本、思维链 CoT、自洽性 Self-Consistency，知道它们各自解决什么问题；建立风险意识：认识 Prompt 注入攻击，记住\"分层 + 最小权限 + 过滤 + 日志\"的防御基调；产出：一套自己可复用的高频 Prompt 模板（为第 8 章装好 WorkBuddy 后直接调用做准备）。"
        ),
        "concept_tags": [
            "认知对齐：每句话都是 Prompt", "Prompt 结构模型：六要素", "四个真实模板，拆解结构化写法", "进阶技巧", "风险控制：Prompt 注入与防御", "演进与 AIPM 视角",
        ],
        "milestone": "一套高频 Prompt 模板（≥ 2 份结构化 Prompt：1 份工作场景 + 1 份自选场景），含角色 / 任务 / 上下文 / 输出格式 / 约束五要素",
        "videos": [
            {
                "title": "Prompt 工程系统教程",
                "url": "https://www.bilibili.com/video/BV1s24y1F7eq/",
                "platform": "bilibili",
                "description": "从基础到业务增效的完整讲解",
            },
            {
                "title": "吴恩达《ChatGPT Prompt Engineering》中文版",
                "url": "https://www.bilibili.com/video/BV1Bo4y1A7FU",
                "platform": "bilibili",
                "description": "经典短课，建立结构化表达习惯",
            },
        ],
    },
    "W4S2": {
        "week": 4, "no": 2, "dir": "第8章",
        "title": "实战：装 WorkBuddy → 用 WorkBuddy 装 Hermes",
        "goal": (
            "安装 WorkBuddy，完成首次对话，并让它帮你产出第一份文档（体验\"让 AI 写东西\"）；用 WorkBuddy 辅助，把 第 3–4 章的一个 AI 改造场景写成需求卡片（复用 第 5–6 章学过的需求写法）；关键实战：用自然语言让 WorkBuddy 帮忙安装 / 部署 Hermes（你的私有本地 AI 大脑），并跑通一次最小调用验证（如发\"你好\"→ 收到返回）；建立\"私有化部署\"的通识认知：知道模型为什么能跑在本地、私有化对数据安全意味着什么——但明确区分\"通识原理\"与\"Hermes 的具体装法\"。"
        ),
        "concept_tags": [
            "为什么要\"私有化部署\"：通识原理", "模型怎么\"跑在本地\"：通识类比", "容器化：私有部署常用手段", "微调与私有知识", "Hermes 的正确口径",
        ],
        "milestone": "已安装并完成首次对话的 WorkBuddy，及它产出的第一份文档",
        "videos": [
            {
                "title": "WorkBuddy 入门教程合集",
                "url": "https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a",
                "platform": "ima",
                "description": "安装 + 首次对话 + 对话生成文档",
            },
            {
                "title": "Ollama 本地部署大模型",
                "url": "https://www.bilibili.com/video/BV1hLqCYGESx/",
                "platform": "bilibili",
                "description": "",
            },
            {
                "title": "DeepSeek 本地部署",
                "url": "https://www.bilibili.com/video/BV1nMNeePEZd/",
                "platform": "bilibili",
                "description": "",
            },
        ],
    },
    "W5S1": {
        "week": 5, "no": 1, "dir": "第9章",
        "title": "范式认知（vibe coding / aicoding）",
        "goal": (
            "能用自己的话讲清 vibe coding / aicoding 是什么，以及它和传统编程的本质区别；认识主流 vibe coding 工具（以 Trae 为例）的思路：给自然语言 → AI 生成/修改代码；用大白话分清三件套各自干什么：Claude Code 写代码 / WorkBuddy 写文档与编排 / Hermes 提供智能；知道 AI 写代码也有能力边界，建立\"先想清楚要什么，再让 AI 动手\"的意识；留下一个印象：Claude Code 这类工具本身就是\"coding agent\"——能自主写代码去完成目标（第 13–14 章正式讲 Agent 概念）。"
        ),
        "concept_tags": [
            "什么是 vibe coding", "aicoding 是什么 —— 把概念落到\"三件套\"", "Trae 等工具思路", "vibe coding 的坑与\"加结构\"", "通识：AI 写代码也有能力边界", "预告",
        ],
        "milestone": "一张\"三件套分工\"便签（Claude Code / WorkBuddy / Hermes 各负责什么）",
        "videos": [
            {
                "title": "什么是 vibe coding？怎么上手",
                "url": "https://code.tutsplus.com/what-is-vibe-coding-how-to-do-it--ytc-106c",
                "platform": "web",
                "description": "英文图解，概念最清晰",
            },
            {
                "title": "vibe coding 教程合集",
                "url": "https://vibecodingwiki.com/wiki/vibecoding-tutorials",
                "platform": "web",
                "description": "多场景实操集合，挑\"搭小应用\"看",
            },
        ],
    },
    "W5S2": {
        "week": 5, "no": 2, "dir": "第10章",
        "title": "Claude Code 第一次启动",
        "goal": (
            "完成 Claude Code 的安装并跑通一个最小（hello-world 级）命令；用自然语言让 Claude Code 生成一个简单函数，并运行验证结果；理解 Claude Code 是\"写代码的 agent\"，与 WorkBuddy（写文档编排）、Hermes（提供智能）的分工边界；建立\"宁可求稳，不求速度\"的使用心态（来源：CLAUDE（中文版）.md）。"
        ),
        "concept_tags": [
            "Claude Code 是什么 + 三件套分工复盘", "与第 9 章的 Trae 思路一致，但形态不同", "使用 Claude Code 的行为准则.md）", "通识：AI 写代码也有边界",
        ],
        "milestone": "Claude Code 跑通最小任务：安装成功 + 进入对话 + 用自然语言生成并运行一个简单函数（如 average）",
        "videos": [
            {
                "title": "Claude Code 小白教程",
                "url": "https://www.bilibili.com/video/BV1qQmgB5ENs/",
                "platform": "bilibili",
                "description": "终端 coding agent 第一次启动演示",
            },
            {
                "title": "非程序员小白 Claude Code 官方教程",
                "url": "https://ima.qq.com/wiki/?shareId=6b3816551da2f69efc894947c9387cda7833893ec200c4a2942e75ab56027507",
                "platform": "ima",
                "description": "零基础友好",
            },
        ],
    },
    "W6S1": {
        "week": 6, "no": 1, "dir": "第11章",
        "title": "需求 → 规格",
        "goal": (
            "理解\"需求\"和\"规格\"的区别：需求是\"我要什么\"，规格是\"具体长什么样、怎么做\"；掌握对话式需求收敛的方法——不追求一次写清 PRD，而是用 5 轮左右的对话逐步把模糊想法逼成可执行功能清单（来源：01-requirement-chat.md）；能把第 5 章写好的需求卡片，在 Claude Code 里通过对话转成一份\"功能规格文档\"（Feature Spec），包含功能模块表、优先级；知道功能规格文档为什么是开发的\"契约\"——它让后续写代码的人（Claude Code）目标明确、不返工（来源：02-feature-spec.md）。"
        ),
        "concept_tags": [
            "需求不是一次性给清楚的——对话式收敛", "从对话到功能规格——Feature Spec", "为什么今天用 Claude Code 而不是 WorkBuddy",
        ],
        "milestone": "一份 feature-spec.md 功能规格文档（3–5 个模块、功能点带 P0/P1 优先级），由 Claude Code 在你项目目录生成",
        "videos": [
            {
                "title": "Claude Code 新手笔记：从需求到代码",
                "url": "https://lilys.ai/zh/notes/claude-code-20251026/claude-code-tutorial-for-beginners",
                "platform": "web",
                "description": "图文步骤，适合边看边做",
            },
        ],
    },
    "W6S2": {
        "week": 6, "no": 2, "dir": "第12章",
        "title": "生成原型",
        "goal": (
            "理解\"原型\"的目的：用最小成本验证\"这个东西长什么样、能不能用\"，而不是一次做完整产品（来源：00-overview.md \"前端是体验的第一印象\"、07-delivery.md 一键启动理念）；掌握用 Claude Code 从一句需求 + 一份规格生成\"个人问答小工具\"原型：一个能本地打开的页面/脚本；知道生成前先定\"好\"的标准——Eval 思维（来源：03-eval-baseline.md \"Eval 先于开发\"）；跑通原型：在本机能打开、能输入问题、能看到回应（哪怕先用模拟回答），达成里程碑\"能搭骨架\"。"
        ),
        "concept_tags": [
            "先定义\"好\"的标准，再追求\"好\"——Eval 思维", "前端原型怎么描述给 AI——设计提示词", "后端与集成——原型可以很轻", "交付与本地可运行",
        ],
        "milestone": "一个本地可打开的 prototype.html「个人问答小工具」原型（含问答界面 + 至少模拟/简易本地检索回答）",
        "videos": [
            {
                "title": "Claude Code 实战：生成可运行应用",
                "url": "https://www.bilibili.com/video/BV1qQmgB5ENs/",
                "platform": "bilibili",
                "description": "复用第 9 章教程中的\"生成项目\"章节，重点看 demo",
            },
        ],
    },
    "W7S1": {
        "week": 7, "no": 1, "dir": "第13章",
        "title": "概念白盒（RAG / Agent / 工具调用 / MCP）",
        "goal": (
            "用大白话区分 聊天（Chat） 与 Agent：知道 Agent 不是\"你问一句它答一句\"，而是会自己规划、调工具、反复试错去完成目标的智能体；理解 工具调用（tool calling / Function Calling） 是 Agent 能\"干活\"的底层能力——模型不止会说话，还能调函数去查天气、读库、发邮件；在概念层理解 MCP（Model Context Protocol）：一套给 AI 统一接工具/数据源的通用标准（类比 USB 接口），知道\"有了它能统一对接各种外部系统\"即可，不抠协议细节；浅讲 RAG（检索增强生成）：让模型先查资料再回答，可抑制第 1 章讲过的\"幻觉\"；建立一套自己的\"概念地图\"，为第 14 章把小工具接上 Hermes 打底。（不要求会写代码，听懂\"谁在干什么\"即可。）。"
        ),
        "concept_tags": [
            "AI Agent 概念", "工具调用", "MCP", "RAG",
        ],
        "milestone": "一张手绘/电子的 Agent 决策闭环图（套用自己的工作场景）",
        "videos": [
            {
                "title": "智泊AI《AI大模型零基础全套教程》· Agent / 工具调用 / MCP 章节",
                "url": "https://www.bilibili.com/video/BV1KUwazoEXH/",
                "platform": "bilibili",
                "description": "同第 1 章那套；其中《Agent 概念、组成与决策》《Agent 工具使用》《LangGraph 接入 MCP》几集正好对应上面三个概念（概念级跟看即可）",
            },
            {
                "title": "AI Agent 是什么（科普）",
                "url": "https://thehumanco.org/ai-resources/ai-agents",
                "platform": "web",
                "description": "图文讲清 Agent 与 Workflow 区别",
            },
        ],
    },
    "W7S2": {
        "week": 7, "no": 2, "dir": "第14章",
        "title": "接智能（调用第 8 章已部署的 Hermes）",
        "goal": (
            "把第 8 章已部署好的 Hermes（本地 AI 大脑）接进第 11–12 章的小工具，让它从\"空壳\"变成\"能回答问题\"的迷你 AI 助手；在概念层跑通一个 RAG demo：让小工具\"先查你的资料、再回答\"，直观看到第 1 章讲的\"幻觉\"被抑制；掌握 WorkBuddy 辅助写产品设计文档的方法，并用 ChemAI 产品设计文档作为范例结构，把自己的小工具需求落成一份分模块设计稿；理解\"本地 Hermes 接不上时\"的兜底方案：用 WorkBuddy 接入 DeepSeek 作为 LLM 后端。"
        ),
        "concept_tags": [
            "回顾：什么是\"接智能\"", "Hermes 是什么、为什么不用再装", "两条接入路线", "RAG 概念级 demo", "用 WorkBuddy 辅助写产品设计文档",
        ],
        "milestone": "一个能回答问题的迷你 AI 助手（RAG 概念级 demo，调用 第 7–8 章已部署的 Hermes；Hermes 不可用时用 DeepSeek 兜底）",
        "videos": [
            {
                "title": "DeepSeek 本地部署",
                "url": "https://www.bilibili.com/video/BV1nMNeePEZd/",
                "platform": "bilibili",
                "description": "LLM 后端接入原理参考（Hermes 同理）",
            },
            {
                "title": "Ollama 本地部署大模型",
                "url": "https://www.bilibili.com/video/BV1hLqCYGESx/",
                "platform": "bilibili",
                "description": "复习\"模型怎么跑在本地\"（Hermes 同源思路）",
            },
            {
                "title": "WorkBuddy 三大场景",
                "url": "https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a",
                "platform": "ima",
                "description": "文档/编排/可视化怎么用",
            },
        ],
    },
    "W8S1": {
        "week": 8, "no": 1, "dir": "第15章",
        "title": "落地打磨（结业项目）",
        "goal": (
            "明确结业作品的验收线：一个解决你真实小问题的 AI 小工具，且必须用到 Claude Code（搭）+ WorkBuddy（文档/编排）+ Hermes 或 DeepSeek（智能）（来源：小白AI课程16章学习路径.md 第 16 章）；掌握 vibe coding 的真实打磨节奏：多轮对话、跑测试、追加边界 prompt、用 git 做存档点（来源：Vibe-Coding-简易版.md）；能说清「Vibe Coding」与「AI Coding」的差别，知道自己的作品该停在哪一档、差距在哪（来源：VibeCoding到AICoding-PPT_20260730_141825.html）；用产品经理视角自检：Demo 本身就是沟通语言，我的 Demo 传达了什么边界（来源：产品经理要不要学技术.md）；了解 Loop Engineering「让系统替你 prompt Agent」的思路与代价（来源：循环之上-Loop-Engineering.pdf）。"
        ),
        "concept_tags": [
            "vibe coding 的真实节奏：一次不完美是常态", "从 Vibe Coding 到 AI Coding：知道自己停在哪一档", "打磨清单：从「能跑」到「能演示」", "产品经理视角：Demo 是比 PRD 更有效的沟通语言", "循环之上 Loop-Engineering",
        ],
        "milestone": "打磨后的可演示作品：主流程闭环、有边界提示、密钥合规、一键启动",
        "videos": [
            {
                "title": "Claude Code 落地实战回顾",
                "url": "https://www.bilibili.com/video/BV1qQmgB5ENs/",
                "platform": "bilibili",
                "description": "串起第 9–13 章的 coding 动作，做结业打磨参考",
            },
        ],
    },
    "W8S2": {
        "week": 8, "no": 2, "dir": "第16章",
        "title": "文档 + 展示",
        "goal": (
            "用 WorkBuddy 产出 1 页使用说明 / README，让别人不用问你就能跑起来（来源：小白AI课程16章学习路径.md 第 16 章）；学会用「进门四问」把作品的权限、成本、留痕、失败处理写清楚（来源：DeepSeek-Harness.html）；能向别人讲清自己接的「模型后端」是什么、边界在哪（Hermes 或 DeepSeek）；看懂一个纯无代码 agent 的完整搭法，知道「不写代码也能做同一件事」（来源：coze搭建智能待办事项agent.pdf）；完成组内 demo 展示与互评，达成里程碑 4：端到端交付一个简单 AI Solution。"
        ),
        "concept_tags": [
            "1 页 README 该写什么", "用 WorkBuddy 写文档的正确姿势：先喂事实，再让它成文", "理解你接的「模型后端」，并把它写进说明", "coze 搭建智能待办事项 agent", "demo 展示与互评方法",
        ],
        "milestone": "1 页 README / 使用说明（WorkBuddy 生成 + 你逐条核对过事实），含七块结构与「进门四问」边界章节",
        "videos": [
            {
                "title": "WorkBuddy 三种工作模式",
                "url": "https://ima.qq.com/wiki/?shareId=81eb2ec426d66c1e8888528afde1d61121d2b2f820636ff894cced5d5e91e48a",
                "platform": "ima",
                "description": "用 WorkBuddy 写说明/README 时参考",
            },
        ],
    },
}


def iter_source_files(sdir: Path) -> list[Path]:
    """课件.md（教案）优先，其余 材料/ 支持类型（含子目录、含 html）。
    发现规则集中在 scripts/courseware_files.py（递归深度 2 + 资源包整棵跳过）。"""
    files: list[Path] = []
    lesson = sdir / "课件.md"
    if lesson.is_file():
        files.append(lesson)
    files += courseware_files.iter_material_files(sdir / "材料")
    return files


def cleanup_week(cur, week: int) -> None:
    sids = [r[0] for r in cur.execute("SELECT id FROM sessions WHERE week_no=?", (week,)).fetchall()]
    cids: list[str] = []
    if sids:
        ph = ",".join("?" * len(sids))
        for (cj,) in cur.execute(f"SELECT chapter_ids FROM sessions WHERE id IN ({ph})", sids).fetchall():
            try:
                cids += json.loads(cj or "[]")
            except json.JSONDecodeError:
                pass
    if cids:
        cph = ",".join("?" * len(cids))
        mids = [r[0] for r in cur.execute(f"SELECT id FROM materials WHERE chapter_id IN ({cph})", cids).fetchall()]
        if mids:
            mph = ",".join("?" * len(mids))
            cur.execute(f"DELETE FROM chunks WHERE material_id IN ({mph})", mids)
        cur.execute(f"DELETE FROM materials WHERE chapter_id IN ({cph})", cids)
        cur.execute(f"DELETE FROM chapters WHERE id IN ({cph})", cids)
    cur.execute("DELETE FROM video_resources WHERE week_no=?", (week,))
    cur.execute("DELETE FROM sessions WHERE week_no=?", (week,))


def insert_material(cur, cid: str, f: Path, order: int, status: str, counts: dict) -> None:
    try:
        # 2026-09-22：图片型 PDF/PPTX 取 OCR 文本（best_text 内部按原生字数判阈值，
        # 缓存写 材料/_ocr/）。只靠原生解析会让 tutor 的检索切片看不到课件原内容。
        import ocr_materials

        text = ocr_materials.best_text(f, quiet=True)
        chunks = parser.chunk_text_list(text)
        parse_status = "parsed" if text.strip() else "failed"
    except Exception as e:  # noqa: BLE001
        chunks, text, parse_status = [], "", "failed"
        print(f"  [warn] 解析失败 {f.name}: {e}")
    ext = f.suffix.lower().lstrip(".")
    mid = new_id()
    display = f.name
    if f.name == "课件.md":
        # 课件目录 2026-09-22 起改名 `第N章`（原 WxSy）；展示名统一「第 N 章 …」（带空格，
        # 与 chapters.name / 测评标签同格式）。
        d = f.parent.name
        if d.startswith("第") and d.endswith("章") and d[1:-1].isdigit():
            display = f"第 {d[1:-1]} 章 课件（教案）.md"
        else:
            display = f"{d} 课件（教案）.md"
    cur.execute(
        "INSERT INTO materials (id, chapter_id, filename, original_name, file_type, size_bytes,"
        " uploaded_by, is_deleted, chunk_count, parse_status, created_at, status, source_path)"
        " VALUES (?,?,?,?,?,?, 'seed', 0, ?, ?, ?, ?, ?)",
        (mid, cid, mid + "." + ext, display, ext, f.stat().st_size,
         len(chunks), parse_status, utcnow(order), status, str(f)),
    )
    counts["materials"] += 1
    for c in chunks:
        cur.execute(
            "INSERT INTO chunks (id, material_id, chapter_id, chunk_idx, text, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (new_id(), mid, cid, c["chunk_idx"], c["text"], utcnow(order)),
        )
        counts["chunks"] += 1
    print(f"  [ok] {display} -> {len(chunks)} chunks ({parse_status})")


def inject_session(cur, key: str, status: str, counts: dict) -> str:
    s = SPECS[key]
    sid, cid = new_id(), new_id()
    cur.execute(
        "INSERT INTO sessions (id, week_no, session_no, title, goal, chapter_ids, concept_tags,"
        " milestone, order_no, status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'seed', ?)",
        (sid, s["week"], s["no"], s["title"], s["goal"], json.dumps([cid], ensure_ascii=False),
         json.dumps(s["concept_tags"], ensure_ascii=False), s["milestone"], s["no"], status, utcnow()),
    )
    counts["sessions"] += 1
    cname = f"第 {chapter_no(s)} 章 · {s['title']}"
    cur.execute(
        "INSERT INTO chapters (id, folder, name, order_no, created_by, created_at, status)"
        " VALUES (?,?,?,?, 'seed', ?, ?)",
        (cid, "", cname, chapter_no(s), utcnow(), status),
    )
    counts["chapters"] += 1
    print(f"\n[{key}] {cname}  (session={sid[:8]} chapter={cid[:8]} status={status})")

    sdir = COURSE / s["dir"]
    for i, f in enumerate(iter_source_files(sdir)):
        insert_material(cur, cid, f, i, status, counts)

    for i, v in enumerate(s["videos"]):
        cur.execute(
            "INSERT INTO video_resources (id, title, url, platform, description, week_no, session_no,"
            " concept_tags, order_no, status, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?, 'seed', ?)",
            (new_id(), v["title"], v["url"], v["platform"], v["description"], s["week"], s["no"],
             json.dumps(s["concept_tags"], ensure_ascii=False), i, status, utcnow(i)),
        )
        counts["videos"] += 1
    return cid


def backfill_courseware(cur, counts: dict) -> None:
    """给已有章节补挂 课件.md（历史章节从未把教案入库，导致 RAG 检索不到课上原文）。"""
    rows = cur.execute(
        "SELECT c.id, c.name, c.status, c.folder, c.order_no FROM chapters c ORDER BY c.folder, c.order_no"
    ).fetchall()
    for cid, name, status, folder, order_no in rows:
        # v2.7.0：章节名解耦为「第 N 章」（folder 置空），由全局章号反推课件目录。
        # 2026-09-22：课件目录已从 `WxSy` 改名为 `第N章`（章 1→第1章 … 章 16→第16章，同
        # models.chapter_no 口径），本函数只做「章号 → 目录名」换算，不改任何展示口径。
        try:
            chno = int(order_no)
            if chno < 1:
                raise ValueError(order_no)
            key = f"第{chno}章"
        except (ValueError, TypeError):
            print(f"  [skip] 无法解析章节序号：{name}")
            continue
        lesson = COURSE / key / "课件.md"
        if not lesson.is_file():
            print(f"  [skip] 缺文件 {lesson}")
            continue
        exists = cur.execute(
            "SELECT COUNT(*) FROM materials WHERE chapter_id=? AND original_name LIKE '%课件（教案）%'",
            (cid,),
        ).fetchone()[0]
        if exists:
            print(f"  [have] {key} 已挂课件.md")
            continue
        n = cur.execute("SELECT COUNT(*) FROM materials WHERE chapter_id=?", (cid,)).fetchone()[0]
        first = cur.execute(
            "SELECT MIN(created_at) FROM materials WHERE chapter_id=?", (cid,)
        ).fetchone()[0]
        base = datetime.fromisoformat(first) if first else datetime.now(timezone.utc)
        cur.execute(
            "UPDATE materials SET created_at=? WHERE chapter_id=?", ((base - timedelta(seconds=1)).isoformat(), cid)
        )
        insert_material(cur, cid, lesson, -1, status, counts)
        print(f"  [add] {key} 补挂课件.md（该章原有 {n} 份资料，教案排首位）")


def rechunk_all(cur, counts: dict, chapter_ids: set[str] | None = None) -> None:
    """按 best_text（原生解析 + 图片型 PDF/PPTX 的 OCR 文本）重算全部资料的切片。

    图片型幻灯片的原生文本极少，只靠原生解析会让「AI 对话切片」看不到课件原内容。
    """
    import ocr_materials

    sql = ("SELECT id, chapter_id, original_name, source_path FROM materials"
           " WHERE is_deleted=0")
    params: list[str] = []
    if chapter_ids:  # 只重算指定章节，避免动到其它章节（换 chunks.id 会让卡片绑片悬空）
        ph = ",".join("?" * len(chapter_ids))
        sql += f" AND chapter_id IN ({ph})"
        params = list(chapter_ids)
    rows = cur.execute(sql + " ORDER BY chapter_id, created_at", params).fetchall()
    for mid, cid, name, src in rows:
        p = Path(src) if src else None
        if not p or not p.is_file():
            print(f"  [skip] 源文件缺失：{name}")
            continue
        text = ocr_materials.best_text(p, quiet=True)
        chunks = parser.chunk_text_list(text)
        cur.execute("DELETE FROM chunks WHERE material_id=?", (mid,))
        for c in chunks:
            cur.execute(
                "INSERT INTO chunks (id, material_id, chapter_id, chunk_idx, text, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (new_id(), mid, cid, c["chunk_idx"], c["text"], utcnow()),
            )
            counts["chunks"] += 1
        cur.execute(
            "UPDATE materials SET chunk_count=?, parse_status=? WHERE id=?",
            (len(chunks), "parsed" if text.strip() else "failed", mid),
        )
        counts["rechunked"] += 1
        print(f"  [ok] {name[:40]:<42} -> {len(chunks):3d} 切片 / {len(text):6d} 字")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="*", help="如 W2S1 W2S2")
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--status", default="draft", choices=["draft", "published"])
    ap.add_argument("--backfill-courseware", action="store_true")
    ap.add_argument("--rechunk", action="store_true",
                    help="按 best_text（含 OCR）重算全部资料切片")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    keys = list(args.sessions)
    if args.week is not None:
        keys += [k for k, s in SPECS.items() if s["week"] == args.week and k not in keys]
    if not keys and not args.backfill_courseware and not args.rechunk:
        ap.error("请指定 session（如 W2S1）或 --week N 或 --backfill-courseware 或 --rechunk")

    con = sqlite3.connect(args.db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    cur = con.cursor()
    counts = {"sessions": 0, "chapters": 0, "materials": 0, "chunks": 0, "videos": 0,
              "rechunked": 0}

    weeks = sorted({SPECS[k]["week"] for k in keys})
    for w in weeks:
        cleanup_week(cur, w)
    injected: list[str] = []
    for k in keys:
        injected.append(inject_session(cur, k, args.status, counts))
    if args.backfill_courseware:
        print("\n[backfill-courseware]")
        backfill_courseware(cur, counts)
    if args.rechunk:
        # ⚠️ 只重算本次注入的章节：全库重算会换掉 chunks.id，
        # 让既有章节（含已发布）的 knowledge_cards.source_chunk_id 全部悬空。
        scope = set(injected) if injected else None
        print("\n[rechunk] 按 OCR 增强文本重算切片"
              + (f"（限 {len(scope)} 章）" if scope else "（全库）"))
        rechunk_all(cur, counts, scope)

    con.commit()
    print("\n=== 注入完成 ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
