"""出题（QUIZZER）：DeepSeek 生成草稿题，失败降级到模板题（L2）。

百分制评分模型（QUIZ-005）：固定 20 道选择题/是非题，每题 5 分，合计 100 分，
彻底取消问答题（essay）。POINTS 保留 essay=10 仅用于兼容库里旧题数据。
"""
import json

from ai import agents, rag
from ai.prompts import QUIZZER_SYSTEM

# 题型满分（QUIZ-005，选择/是非 5；essay=10 仅保留以兼容库里旧题数据，不再出 essay）
POINTS = {"choice": 5, "bool": 5, "essay": 10}

# 100 分预设组合（QUIZ-005）：固定 20 道 choice/bool，严禁含 essay
PRESETS = {
    "20c": {"choice": 20},
    "20b": {"bool": 20},
}

_TYPE_LABEL = {"choice": "选择题", "bool": "是非题", "essay": "问答题"}


def default_config() -> dict:
    return dict(PRESETS["20c"])


def config_total(config: dict) -> int:
    """按题型分值计算组合总分（用于校验=100）。"""
    return sum(POINTS[t] * int(config.get(t) or 0) for t in POINTS)


def validate_config(config) -> dict:
    """归一化并校验组合；只接受 choice/bool（essay 已取消），非法返回空 dict。"""
    if not isinstance(config, dict):
        return {}
    cfg = {}
    for t in ("choice", "bool"):
        n = config.get(t)
        if n is None:
            continue
        try:
            n = int(n)
        except (TypeError, ValueError):
            return {}
        if n < 0:
            return {}
        if n:
            cfg[t] = n
    return cfg


def _spec_text(config: dict) -> str:
    parts = [f"{int(config.get(t) or 0)} 道{_TYPE_LABEL[t]}" for t in ("choice", "bool") if config.get(t)]
    return "共 " + " + ".join(parts) + "（各 5 分，合计 100 分）"


# 兜底模板池：choice/bool 各 20 条（题干全局唯一），按 idx 轮转避免重复；已取消 essay
_TEMPLATES = {
    "choice": [
        {
            "content": "巩固练习/间隔复习的主要作用是？",
            "options": ["一次性测评", "间隔复习强化记忆", "替代课堂", "无需复习"],
            "answer": "1",
            "reason": "间隔复习能显著提升长期记忆",
            "sub_concept": "学习方法",
        },
        {
            "content": "苏格拉底式引导的核心原则是？",
            "options": ["直接给答案", "用追问引导学习者自己推导", "跳过提问直接讲结论", "只讲不练"],
            "answer": "1",
            "reason": "苏格拉底式引导强调追问而非直接给答案",
            "sub_concept": "学习方法",
        },
        {
            "content": "遇到不会的知识点，更推荐的做法是？",
            "options": ["直接跳过", "先自主尝试再求助，并记录错题", "照抄答案", "不复盘继续往下学"],
            "answer": "1",
            "reason": "主动尝试加错题记录更利于巩固",
            "sub_concept": "学习方法",
        },
        {
            "content": "把短期记忆转化为长期记忆，最有效的方法是？",
            "options": ["考前临时抱佛脚", "间隔重复与主动回忆", "一次性长时间背诵", "只看不做题"],
            "answer": "1",
            "reason": "间隔重复和主动回忆是巩固长期记忆的核心",
            "sub_concept": "学习方法",
        },
        {
            "content": "下列哪种学习行为最能促进深度理解？",
            "options": ["机械抄写多遍", "用自己的话复述并举例", "只看重点划线", "跳过例题"],
            "answer": "1",
            "reason": "复述和举例能激活深加工，促进理解",
            "sub_concept": "学习方法",
        },
        {
            "content": "做错题后，最有助于进步的做法是？",
            "options": ["当作没发生", "分析错因并订正复盘", "只改答案不思考", "避免再做同类题"],
            "answer": "1",
            "reason": "分析错因并复盘是查漏补缺的关键",
            "sub_concept": "学习方法",
        },
        {
            "content": "主动回忆（合上书回忆）相比反复重读，优势在于？",
            "options": ["更省时间", "更能检验是否真正掌握", "更轻松", "无需动脑"],
            "answer": "1",
            "reason": "主动回忆能暴露记忆盲区，强化提取练习",
            "sub_concept": "学习方法",
        },
        {
            "content": "分散练习（间隔练习）相比集中突击，优势在于？",
            "options": ["更利于长期记忆保持", "见效更快", "更省时间", "更适合考前"],
            "answer": "0",
            "reason": "分散练习的间隔效应更利于长期保持",
            "sub_concept": "学习方法",
        },
        {
            "content": "把新知识与已有知识建立联系，这种做法称为？",
            "options": ["机械记忆", "精细加工", "死记硬背", "瞬时记忆"],
            "answer": "1",
            "reason": "与旧知识建立联系属于精细加工策略",
            "sub_concept": "学习方法",
        },
        {
            "content": "费曼学习法的核心是？",
            "options": ["大量刷题", "用简单的话把知识讲清楚", "反复抄写", "只看视频"],
            "answer": "1",
            "reason": "费曼学习法强调用自己的话讲清概念",
            "sub_concept": "学习方法",
        },
        {
            "content": "制定学习目标时，最符合 SMART 原则的是？",
            "options": ["每天学一点", "本周内掌握第三章并能做对练习", "以后再说", "尽量多学"],
            "answer": "1",
            "reason": "具体、可衡量、有时限的目标更符合 SMART",
            "sub_concept": "学习方法",
        },
        {
            "content": "番茄工作法的核心是？",
            "options": ["连续工作数小时", "短时专注加定时休息", "多任务并行", "通宵赶工"],
            "answer": "1",
            "reason": "番茄工作法通过短时专注和定时休息保持效率",
            "sub_concept": "学习方法",
        },
        {
            "content": "遇到难题长时间卡住时，更合理的做法是？",
            "options": ["死磕到底", "暂时放下，之后带着新思路再来", "直接放弃", "照抄答案了事"],
            "answer": "1",
            "reason": "适时暂停并换思路有助于突破卡点",
            "sub_concept": "学习方法",
        },
        {
            "content": "做笔记时，更高效的做法是？",
            "options": ["逐字照抄", "用自己的话提炼要点", "只抄标题", "完全不做"],
            "answer": "1",
            "reason": "用自己的话提炼能促进理解和记忆",
            "sub_concept": "学习方法",
        },
        {
            "content": "定期自测（自我测验）的主要好处是？",
            "options": ["浪费时间", "检验掌握情况并发现盲区", "增加焦虑", "替代学习"],
            "answer": "1",
            "reason": "自测能检验掌握度并暴露知识盲区",
            "sub_concept": "学习方法",
        },
        {
            "content": "学习时保持专注，更有效的做法是？",
            "options": ["同时刷手机", "移除干扰并设定专注时段", "边学边闲聊", "频繁切换任务"],
            "answer": "1",
            "reason": "移除干扰并专注能提升学习效率",
            "sub_concept": "学习方法",
        },
        {
            "content": "多感官（看+听+写）参与学习的优势是？",
            "options": ["更热闹", "多通道编码加深记忆", "更费时间", "只适合儿童"],
            "answer": "1",
            "reason": "多感官通道编码能加深记忆痕迹",
            "sub_concept": "学习方法",
        },
        {
            "content": "学习后及时睡眠对记忆的作用是？",
            "options": ["促进记忆巩固", "导致遗忘", "没有影响", "浪费时间"],
            "answer": "0",
            "reason": "睡眠期间的记忆巩固有助于长期保持",
            "sub_concept": "学习方法",
        },
        {
            "content": "把大任务拆解为小步骤的好处是？",
            "options": ["降低行动门槛、减少拖延", "让任务更复杂", "没有好处", "浪费时间"],
            "answer": "0",
            "reason": "拆解大任务能降低启动难度并减少拖延",
            "sub_concept": "学习方法",
        },
        {
            "content": "学习过程中遇到分心，更有效的应对是？",
            "options": ["任由分心", "记录分心点并回到任务", "干脆休息整天", "责备自己"],
            "answer": "1",
            "reason": "记录分心点并回归任务比自责更有效",
            "sub_concept": "学习方法",
        },
    ],
    "bool": [
        {
            "content": "间隔复习的间隔会随答对而逐渐拉长（1→3→7）。",
            "answer": "正确",
            "reason": "答对顺延间隔、答错重置为 1",
            "sub_concept": "学习方法",
        },
        {
            "content": "苏格拉底式引导鼓励直接告诉学生最终答案。",
            "answer": "错误",
            "reason": "应以追问引导学生自己推导",
            "sub_concept": "学习方法",
        },
        {
            "content": "定期回顾与练习有助于把短期记忆转化为长期记忆。",
            "answer": "正确",
            "reason": "间隔复习是巩固长期记忆的有效手段",
            "sub_concept": "学习方法",
        },
        {
            "content": "学习新知识时，越早开始第一次复习越有利于巩固记忆。",
            "answer": "正确",
            "reason": "及时复习能抓住遗忘曲线前期的巩固窗口",
            "sub_concept": "学习方法",
        },
        {
            "content": "遇到不会的题目，照抄答案是有效的学习方法。",
            "answer": "错误",
            "reason": "照抄答案缺乏主动思考，不利于掌握",
            "sub_concept": "学习方法",
        },
        {
            "content": "集中突击比分散练习更有利于长期记忆保持。",
            "answer": "错误",
            "reason": "分散练习的间隔效应更利于长期保持",
            "sub_concept": "学习方法",
        },
        {
            "content": "主动回忆比反复重读更能检验是否真正掌握。",
            "answer": "正确",
            "reason": "主动回忆是检验掌握度的有效提取练习",
            "sub_concept": "学习方法",
        },
        {
            "content": "把新知识与已有知识联系起来，有助于理解和记忆。",
            "answer": "正确",
            "reason": "精细加工能加深理解与记忆",
            "sub_concept": "学习方法",
        },
        {
            "content": "错题整理与复盘对查漏补缺没有帮助。",
            "answer": "错误",
            "reason": "错题复盘是查漏补缺的关键手段",
            "sub_concept": "学习方法",
        },
        {
            "content": "充足的睡眠对记忆巩固没有影响。",
            "answer": "错误",
            "reason": "睡眠期间的记忆巩固对长期保持很重要",
            "sub_concept": "学习方法",
        },
        {
            "content": "制定具体可衡量的学习目标比模糊目标更有效。",
            "answer": "正确",
            "reason": "具体可衡量的目标更易执行和检验",
            "sub_concept": "学习方法",
        },
        {
            "content": "学习中适当休息、避免长时间连续学习，有助于保持效率。",
            "answer": "正确",
            "reason": "适当休息能恢复注意力，维持学习效率",
            "sub_concept": "学习方法",
        },
        {
            "content": "只被动听讲、从不提问，是最佳的学习方式。",
            "answer": "错误",
            "reason": "主动提问和参与能促进理解",
            "sub_concept": "学习方法",
        },
        {
            "content": "多感官参与（看、听、写）能加深记忆。",
            "answer": "正确",
            "reason": "多通道编码能加深记忆痕迹",
            "sub_concept": "学习方法",
        },
        {
            "content": "把大任务拆解成小步骤有助于减少拖延。",
            "answer": "正确",
            "reason": "拆解任务能降低启动门槛、减少拖延",
            "sub_concept": "学习方法",
        },
        {
            "content": "自我测验（自测）有助于发现知识盲区。",
            "answer": "正确",
            "reason": "自测能暴露记忆盲区并检验掌握度",
            "sub_concept": "学习方法",
        },
        {
            "content": "学习环境越嘈杂，越有利于专注学习。",
            "answer": "错误",
            "reason": "嘈杂环境会分散注意力，不利于专注",
            "sub_concept": "学习方法",
        },
        {
            "content": "及时向老师或同伴请教，是解决疑难的有效途径。",
            "answer": "正确",
            "reason": "及时求助能避免长时间卡壳、加速理解",
            "sub_concept": "学习方法",
        },
        {
            "content": "费曼学习法强调用简单的话把知识讲清楚。",
            "answer": "正确",
            "reason": "费曼学习法核心是讲清楚概念",
            "sub_concept": "学习方法",
        },
        {
            "content": "重复做同一道已掌握的题，比挑战新题更能提升能力。",
            "answer": "错误",
            "reason": "挑战新题更能拓展能力边界",
            "sub_concept": "学习方法",
        },
    ],
}


def _template_item(qtype: str, item: dict) -> dict:
    base = {"type": qtype, "options": item.get("options", [])}
    base.update(item)
    return base


def _next_template(qtype: str, seen: set, tpl_idx: dict) -> dict:
    """模板兜底：轮转取一条 content 未出现过的题；池内不足时轮转，绝不并列重复。"""
    pool = _TEMPLATES[qtype]
    start = tpl_idx.get(qtype, 0)
    for offset in range(len(pool)):
        item = pool[(start + offset) % len(pool)]
        tpl_idx[qtype] = (start + offset + 1) % len(pool)
        if item["content"] not in seen:
            return _template_item(qtype, item)
    tpl_idx[qtype] = (start + 1) % len(pool)
    return _template_item(qtype, pool[start % len(pool)])


def _dedup(qs: list[dict]) -> list[dict]:
    """按 content 去重，保留首次出现的题（出题不重复）。"""
    seen = set()
    out = []
    for q in qs:
        c = q.get("content", "")
        if c in seen:
            continue
        seen.add(c)
        out.append(q)
    return out


def _enforce_config(qs: list[dict], config: dict) -> list[dict]:
    """按 config 裁剪题目数量，保证组合恰好 100 分且题干不重复。

    不足部分先由 generate_questions 向 DeepSeek 补发补足；仍不足才用模板兜底
    （模板按 idx 轮转并跳过已出现的 content，避免同一道题重复）。
    """
    out = []
    seen: set[str] = set()
    tpl_idx: dict = {}
    for t in POINTS:
        n = int(config.get(t) or 0)
        pool = [q for q in qs if q.get("type") == t]
        pi = 0
        for _ in range(n):
            while pi < len(pool) and pool[pi].get("content") in seen:
                pi += 1
            if pi < len(pool):
                item = pool[pi]
                pi += 1
            else:
                item = _next_template(t, seen, tpl_idx)
            seen.add(item.get("content", ""))
            out.append(item)
    return out


def _missing(qs: list[dict], config: dict) -> dict:
    """统计各题型还缺几道（DeepSeek 生成数不足部分）。"""
    missing = {}
    for t in POINTS:
        n = int(config.get(t) or 0)
        have = sum(1 for q in qs if q.get("type") == t)
        if have < n:
            missing[t] = n - have
    return missing


def _retrieve_chunks(chapter_ids: list[str], query: str) -> list[dict]:
    """出题前检索章节资料正文；query 为空取整章片段，否则按子概念相关度召回。"""
    chunks: list[dict] = []
    seen: set[str] = set()
    for cid in chapter_ids:
        got = rag.retrieve(query, cid, top_k=5)
        if not got and query:
            # 子概念关键词未命中时，退化为整章资料片段（保证有资料喂给 DeepSeek）
            got = rag.retrieve("", cid, top_k=5)
        for c in got:
            if c["chunk_id"] in seen:
                continue
            seen.add(c["chunk_id"])
            chunks.append(c)
    return chunks


def _chunk_text(chunks: list[dict]) -> str:
    if not chunks:
        return "（无相关片段）"
    return "\n".join(f"- {c['text'][:300]}" for c in chunks)


def fallback_questions(chapter_ids: list[str], config: dict | None = None) -> list[dict]:
    """无 API/失败时的模板题（保证覆盖所选章节与 100 分组合）。"""
    cfg = config or default_config()
    return _enforce_config([], cfg)


# 练习自由组合：目标 20 个 5 分单位（恰好 100 分）
_TARGET_UNITS = 20


def _q_units(raw: dict) -> int:
    """单题占用 5 分单位数（choice/bool=1、essay=2），非法题型按 choice 计。"""
    qtype = raw.get("type", "choice")
    if qtype not in POINTS:
        qtype = "choice"
    return POINTS[qtype] // 5


def _norm_practice(raw: dict) -> dict:
    """练习题目原始 dict 归一化：确保 type 合法、options/answer 为预期结构。"""
    qtype = raw.get("type", "choice")
    if qtype not in POINTS:
        qtype = "choice"
    options = raw.get("options") or []
    if isinstance(options, str):
        options = [options]
    answer = raw.get("answer", raw.get("answer_key", ""))
    if isinstance(answer, (int, float)):
        answer = str(answer)
    return {
        "type": qtype,
        "content": raw.get("content", ""),
        "options": [str(o) for o in options],
        "answer": str(answer),
        "reason": raw.get("reason", ""),
        "sub_concept": raw.get("sub_concept", ""),
    }


def _practice_total(qs: list[dict]) -> int:
    """练习题目集总分（按题型赋分求和）。"""
    return sum(POINTS[q["type"]] for q in qs)


def _trim_to_100(qs: list[dict]) -> list[dict]:
    """AI 出题超 100 分时，按原顺序贪心保留恰好 20 单位（5 分一单位）。"""
    out = []
    units = 0
    for q in qs:
        u = _q_units(q)
        if units + u <= _TARGET_UNITS:
            out.append(q)
            units += u
    return out


def _fill_to_100(qs: list[dict]) -> list[dict]:
    """AI 出题不足 100 分时，只用 choice/bool 模板按 idx 轮转补足到恰好 20 道（各 5 分）。"""
    out = list(qs)
    seen = {q.get("content", "") for q in out}
    tpl_idx: dict = {}
    units = _practice_total(out) // 5
    while units < _TARGET_UNITS:
        # 交替 choice/bool 提升多样性，跳过 content 已出现过的模板
        qtype = "choice" if units % 2 == 0 else "bool"
        item = _next_template(qtype, seen, tpl_idx)
        seen.add(item.get("content", ""))
        out.append(item)
        units += 1
    return out


def _practice_system(chapter_ids: list[str], sub_concepts: str, chunk_txt: str) -> str:
    spec = "固定 20 道题，只允许选择题（choice）和是非题（bool），每题 5 分，合计 100 分"
    return QUIZZER_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        sub_concepts=sub_concepts or "不限",
        spec=spec,
        retrieved_chunks=chunk_txt[:4000],
        difficulty="hard",
    )


def generate_practice_questions(chapter_ids: list[str], sub_concepts: str = "") -> list[dict]:
    """自主练习出题（difficulty=hard，固定 20 道 choice/bool 各 5 分，后端强制合计=100）。"""
    query = (sub_concepts or "").strip()
    chunk_txt = _chunk_text(_retrieve_chunks(chapter_ids, query))
    qs = [_norm_practice(q) for q in (agents.quizzer_generate(_practice_system(chapter_ids, sub_concepts, chunk_txt)) or [])]
    if not qs:
        return fallback_practice_questions(chapter_ids)

    # 彻底取消 essay：只保留 choice/bool，并先去除 DeepSeek 自身重复题干
    qs = _dedup([q for q in qs if q["type"] in ("choice", "bool")])
    if not qs:
        return fallback_practice_questions(chapter_ids)

    total = _practice_total(qs)
    if total > 100:
        qs = _trim_to_100(qs)
        total = _practice_total(qs)
    if total < 100:
        # 先向 DeepSeek 补发一次补足缺口；仍不足用模板兜底
        missing_units = _TARGET_UNITS - total // 5
        fill_system = QUIZZER_SYSTEM.format(
            chapter_ids=",".join(chapter_ids),
            sub_concepts=sub_concepts or "不限",
            spec=f"请补充 {missing_units} 道题（只允许选择/是非，各 5 分）",
            retrieved_chunks=chunk_txt[:4000],
            difficulty="hard",
        )
        extra = [_norm_practice(q) for q in (agents.quizzer_generate(fill_system) or [])]
        if extra:
            extra = _dedup([q for q in extra if q["type"] in ("choice", "bool")])
            have = {q.get("content", "") for q in qs}
            for q in extra:
                if _practice_total(qs) + POINTS[q["type"]] <= 100 and q.get("content", "") not in have:
                    qs.append(q)
                    have.add(q.get("content", ""))
        qs = _fill_to_100(qs)

    # 最终兜底校验：任何情况都保证恰好 100 分
    if _practice_total(qs) != 100:
        qs = _fill_to_100(_trim_to_100(qs))
    return _dedup(qs)


def fallback_practice_questions(chapter_ids: list[str]) -> list[dict]:
    """无 LLM 时的练习兜底：20 道选择（合计 100 分，无 essay）。"""
    return [_norm_practice(q) for q in _enforce_config([], {"choice": 20})]


def generate_questions(chapter_ids: list[str], sub_concepts: str = "", spec: str = "",
                       config: dict | None = None, difficulty: str = "normal") -> list[dict]:
    cfg = config or default_config()
    spec_text = spec or _spec_text(cfg)
    # 出题前 RAG 检索章节资料正文，注入提示词（题目基于资料难度出题，根因①）
    query = (sub_concepts or "").strip()
    chunk_txt = _chunk_text(_retrieve_chunks(chapter_ids, query))

    system = QUIZZER_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        sub_concepts=sub_concepts or "不限",
        spec=spec_text,
        retrieved_chunks=chunk_txt[:4000],
        difficulty=difficulty,
    )
    qs = agents.quizzer_generate(system)
    if not qs:
        return fallback_questions(chapter_ids, cfg)

    # 生成数不足：向 DeepSeek 补发一次补足缺口题型（根因②，不再用同一模板硬塞）
    missing = _missing(qs, cfg)
    if missing:
        fill_spec = "、".join(f"{n} 道{_TYPE_LABEL[t]}" for t, n in missing.items())
        fill_system = QUIZZER_SYSTEM.format(
            chapter_ids=",".join(chapter_ids),
            sub_concepts=sub_concepts or "不限",
            spec=fill_spec,
            retrieved_chunks=chunk_txt[:4000],
            difficulty=difficulty,
        )
        extra = agents.quizzer_generate(fill_system)
        if extra:
            qs = qs + extra
    return _dedup(_enforce_config(qs, cfg))


def norm_question(raw: dict, chapter_id: str) -> dict:
    """规范化为入库结构（type/content/options/answer_key/points）。"""
    qtype = raw.get("type", "choice")
    if qtype not in ("choice", "bool", "essay"):
        qtype = "choice"
    options = raw.get("options") or []
    if isinstance(options, str):
        options = [options]
    answer = raw.get("answer", raw.get("answer_key", ""))
    if isinstance(answer, (int, float)):
        answer = str(answer)
    return {
        "type": qtype,
        "content": raw.get("content", ""),
        "options": json.dumps([str(o) for o in options], ensure_ascii=False),
        "answer_key": str(answer),
        "sub_concept": raw.get("sub_concept", ""),
        "reason": raw.get("reason", ""),
        "points": POINTS[qtype],
    }
