# 来源：brain workspace/daily-video，勿就地魔改，同步靠内容比对
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导演：把知识库的**一页**，变成一条讲解视频的拍摄脚本（v3 图形语法卡片）。

为什么需要这一步（2026-10-08 Ray 的判词）：
    「你的方框还只是把文案拿来切，并没有真正去拆出里面的逻辑要点，按顺序讲解……
      你要理解这个文案到底在表达什么，它要怎么讲给一个没接触过这个概念的人。」
机械切句的流水线做不到这件事 —— 必须先有一层**理解**，才知道讲什么、按什么顺序讲。
这一层就是本文件：一次 LLM 调用，产出「骨架 → 分镜 → 每拍图形 → 每拍配音」。

设计上的三个不变量（改 prompt 之前先读）：
  1. **先减法**：强制先写一句因果骨架，页面上没进骨架的句子不许上屏。像「打字幕」的
     唯一原因就是原句漏进画面，所以约束写在最前面、并且要自检。
  2. **画面由逻辑决定**，不由页面行决定 —— 每拍先选「哪类图形」（style），再填标签。
  3. **先破后立**：开场两拍必须是「先演他以为的答案」，但**画法四选一**
     （situation / dayband / object / dialogue），且**最近 N 集用过的开场器不许重复**
     —— 2026-10-12 查出来的病：5 集里 4 集的分镜序列完全一样，开场永远「两个人 + 线 + 叉」。

用法：
    python3 director.py --page <md 路径> --out <card.json>
                        [--title 页名] [--source 相对路径] [--neighbours "a,b,c"]
                        [--date YYYY-MM-DD] [--max-chars 6000]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, "/Users/xicheng/.hermes/profiles/brain/workspace/dankoe")
from lib.llm import call  # noqa: E402  （统一入口：默认 reasoning=none + 记账）

V3 = {"situation": ("caption", "left", "right", "gap"),
      "crossout": ("claim", "note"),
      "transform": ("from", "to"),
      "chain": ("nodes",),
      "axis": ("axis", "left", "right"),
      "threshold": ("level", "line"),
      "loop": ("nodes",),
      "balance": ("left", "right"),
      "stack": ("blocks",),
      "nodes": ("center", "nodes"),
      "steps": ("steps",),
      "close": (),
      "source": (),
      # v5 开场器变体：与 situation 同功能（先演他以为的答案），但画法完全不同。
      # 不加进这张白名单，repair() 会把导演选的新画法当「未知 style」直接删掉。
      "dayband": ("caption",),
      "object": ("caption",),
      "dialogue": ("lines",)}

OPENERS = ("situation", "dayband", "object", "dialogue")

# 开场器轮换要靠历史。brain 侧由 cron 把卡片写进 cards/；本仓没有这个写入方，
# 所以 director 产出后自己归档一份（见文件末尾），默认落在 gitignore 的 instance/ 里。
CARDS_DIR = os.environ.get("VIDEO_CARDS_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "instance", "video_state", "cards")


def recent_openers(limit=7):
    """最近 N 集用过的开场器 —— 直接读已产出的卡片，不另存状态文件。

    为什么要它：开场器是「每条片子开头长什么样」的唯一来源。不给导演看历史，
    它每次都会退回最熟悉的那个 —— 实测 5 集里 4 集序列完全一样。
    """
    out = []
    try:
        fs = sorted(f for f in os.listdir(CARDS_DIR) if f.endswith(".json"))[-limit:]
    except Exception:
        return out
    for f in fs:
        try:
            sc = (json.load(open(os.path.join(CARDS_DIR, f), encoding="utf-8")).get("scenes") or [])
            if sc:
                out.append((f[:10], sc[0].get("style") or "?"))
        except Exception:
            continue
    return out


PROMPT = """你是「讲解视频」的导演。给你知识库里的**一页概念笔记**，你要交出一条 60–120 秒竖屏视频的拍摄脚本。
只输出 JSON，不要任何解释。

## 第一步：先理解（顺序不可颠倒）
把这页压成**一条逻辑骨架**：一句「因为…所以…」链，写进 skeleton 字段。
骨架里只留因果链上的节点，不许出现原句，也不许把并列的几个说法都塞进去（**一页只讲一条主张**，
其余全部砍掉）。

## 第二步：排顺序，三条硬规则
1. 依赖优先：后一拍用到的东西必须先出现。
2. 具体先于抽象：先给一个他见过的具体处境，再给抽象说法。
3. 先破后立：先演他**以为**的答案（误解），再给真正的机制。没有误解拍，就没有「剥开」。

## 减法铁律（最重要）
**这页上任何一句没进骨架的话，都不许出现在视频里** —— 画面和配音都不许。
视频之所以像「打字幕」，唯一原因就是原句漏进画面。宁可少讲，不许照抄。
配音要重写成人话，不是原文句子的裁剪。

## 可用图形（style → stage 字段；字段名与格式必须严格照抄，一个字都不要改）
- situation  开场器之一：两个人 + 中间那条跨不过去的距离。**已经用太多了，优先考虑下面三种**
  stage: {"caption":"≤14字标题","left":"≤5字","right":"≤5字","gap":"≤8字"}
- dayband    开场器之一：一天被某件事逐格填满，而要做的那一格一直空着（内容里有「时间在流逝 / 一直在做别的」时首选）
  stage: {"caption":"≤14字标题","fill":"≤5字（填满一天的那件事）","empty":"≤6字（一直空着的那格）"}
- object     开场器之一：把主角换成一个**具体物件**（手机 / 床 / 日历 / 账单 / 门 / 容器…），让它自己演
  stage: {"caption":"≤14字标题","clock":"一个在变化的读数（如 23:41）","clock2":"变化后的读数（如 23:42）","task":"≤6字（一直没发生的那件事）"}
- dialogue   开场器之一：人不出场，只有 2–3 句自我对话，左右交错排列（最不像「图解」，适合内心拉扯）
  stage: {"caption":"≤14字标题","lines":["≤12字","≤12字","≤12字"]}
- crossout   紧跟在开场器之后的第二拍：把他想当然的答案画出来，再打一个叉。**它不是开场器**
  stage: {"claim":"≤11字的错误答案","note":"≤6字的转折"}
- chain      机制。一环一拍，点会沿线穿过、节点被点亮
  stage: {"nodes":[{"label":"≤7字"},{"label":"≤7字"}]}   ← 2–4 个，必须是因果链上相邻的环节
- transform  同一个东西换了性质
  stage: {"from":{"label":"≤9字"},"to":{"label":"≤9字"},"caption":"≤12字"}
- axis       程度 / 量值，标记会滑过去、走过的量会亮起来
  stage: {"axis":"≤8字","left":"≤4字","right":"≤4字","at":0.8,"marker":"≤4字"}
- threshold  量一直涨，越过那条虚线才质变
  stage: {"level":"≤6字","line":"≤6字","below":"≤4字","above":"≤4字"}
- loop       首尾相接、自我驱动
  stage: {"nodes":["≤6字","≤6字","≤6字"]}
- balance    两个东西此消彼长，天平真的会斜
  stage: {"left":"≤5字","right":"≤5字","tilt":-0.25}
- stack      一格一格积累出来
  stage: {"blocks":["≤4字","≤4字","≤4字"],"caption":"≤12字"}
- nodes      中心 + 轨道上的邻居。**只能用「可用邻居」里给的词**，编不出来就别用这场
  stage: {"center":"页名","nodes":["邻居1","邻居2","邻居3"]}
- steps      可操作的做法，一步一拍，最后自动打勾
  stage: {"steps":["≤12字","≤12字"]}   ← 2–4 步
- close      收束：回到开场那个画面，但距离没了
  stage: {"headline":["≤8字","≤8字"],"left":"≤5字","right":"≤5字","gap":"≤6字"}
- source     出处卡，固定放最后
  stage: {"headline":"这页从哪来","lines":["文件路径","书名 · 章节"]}

## 全片结构（按此顺序；中间拍可增删，末两拍固定）
（situation / dayband / object / dialogue —— **四选一**做开场器）→ crossout
→ （chain / axis / loop / threshold / transform / balance / stack 里挑 1–5 拍）
→ steps → close → source
总长 60–120 秒 = 配音 300–560 字。每拍 5–14 秒（约 20–55 字）。

## 开场器轮换（硬规则，先读这段再选开场器）
%(recent)s

上面列过的开场器，**这次一个都不许再选**。选择顺序：
1. 内容讲「时间被耗掉 / 一直在做别的」→ `dayband`
2. 有一个具体主角物件（手机、床、日历、账单、门、容器…）→ `object`
3. 内容是自我对话、内心拉扯 → `dialogue`
4. 以上都不成立 → 才退回 `situation`

## 配音（text）的写法
- 一句只讲一件事；因果必须显式说出连接词（因为 / 所以 / 于是 / 结果）。
- 全片专业术语 ≤3 个；每个术语第一次出现，必须用一句大白话解释它。
- 全片只用**一个**中心类比，中途不许换。
- 不许编造：这页没有的机制、数字、例子一律不写。你自己推断出来的，要说得像推断
  （用「大概率 / 往往」这类词）。

## 输出前自检（逐条过，不过就改）
0. 开场器是不是又用了 recent 里列过的那个？（撞了就必须换，这是硬规则）
1. 每一拍的 stage 文字**全擦掉**，还能看出这一步在发生什么变化吗？看不出就换图形。
2. 有没有哪一拍的画面文字，与 text 逐字重叠？（有就删画面文字）
3. 有没有哪句话是原页的句子直接搬过来的？（有就删，只留骨架派生的）
4. chain 的几个节点，是因果链还是并列清单？（并列就换掉）
5. 术语超过 3 个了吗？中心类比换过没有？

## 输出格式（只输出这个 JSON）
{"date":"%(date)s","concept":"页名","source":"相对路径",
 "skeleton":"一句话因果链",
 "scenes":[{"id":"B1_Hook","style":"situation","role":"H","text":"配音原文","stage":{...}}]}
id 与 role 固定：B1_Hook/H、B2_Wrong/M、B3_*/K、B4_*/A、B5_Steps/X、B6_Close/Z、B7_Source/S。

## 这一页
标题：%(title)s
来源：%(source)s

%(page)s

## 可用邻居（只许从这里挑，而且要真的和本页有语义关系；挑不出就少用 nodes 这场）
%(neighbours)s
"""


def parse_json(raw):
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def repair(card, source_default):
    """能自动补的就补，能修的就修 —— 退回切分版（v2）比留下一点瑕疵更糟。

    2026-10-08 实测：一次「397 字偏长」+ 一次「source 拍缺 text」被判失败，
    结果整条退回 v2 切分版 —— 那正是 Ray 退回的版本。所以判据放宽成
    「**结构塌了才拒**，文案瑕疵只警告」。
    返回 (card, fatal[], warns[])。
    """
    fatal, warns, keep = [], [], []
    for s in card.get("scenes") or []:
        sid, st = s.get("id", "?"), s.get("style")
        if st not in V3:
            warns.append("%s: 未知 style %r，删掉这一拍" % (sid, st))
            continue
        if not (s.get("text") or "").strip():
            if st == "source":                       # 出处拍的文字可以自动补
                lines = (s.get("stage") or {}).get("lines") or [source_default]
                s["text"] = "出处：%s。" % lines[0]
                warns.append("%s: 自动补了 text" % sid)
            else:
                warns.append("%s: 缺 text，删掉这一拍" % sid)
                continue
        stage = s.setdefault("stage", {})
        need = V3[st][:1]                            # 首字段是必需字段
        if need and not stage.get(need[0]):
            warns.append("%s(%s): stage 缺 %s，删掉这一拍" % (sid, st, need[0]))
            continue
        keep.append(s)

    if keep and keep[-1].get("style") != "source":   # 出处必须收尾
        keep.append({"id": "B7_Source", "style": "source", "role": "S",
                     "text": "出处：%s。" % source_default,
                     "stage": {"headline": "这页从哪来", "lines": [source_default]}})
        warns.append("补了收尾的 source 拍")
    card["scenes"] = keep

    if len(keep) < 4:
        fatal.append("可用场数 %d，至少要 4 拍" % len(keep))
    if not card.get("skeleton"):
        warns.append("缺 skeleton（不影响渲染）")
    total = sum(len(s.get("text") or "") for s in keep)
    if total < 300:
        fatal.append("配音只有 %d 字，太短（目标 300–560）" % total)
    elif total > 560:
        warns.append("配音 %d 字偏长（约 %.0f 秒）" % (total, total / 4.5))
    return card, fatal, warns


def check(card):
    """旧接口：返回 fatal 列表（保留给外部调用）。"""
    return repair(card, card.get("source") or "")[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--neighbours", default="")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--max-chars", type=int, default=6000)
    ap.add_argument("--tries", type=int, default=1)
    ap.add_argument("--recent", type=int, default=7,
                    help="避开最近 N 集用过的开场器（默认 7，从 cards/ 读）")
    a = ap.parse_args()

    page = open(a.page, encoding="utf-8").read()
    page = re.sub(r"^---\n.*?\n---\n", "", page, flags=re.S)     # 去掉 frontmatter
    page = page[: a.max_chars]
    title = a.title or os.path.splitext(os.path.basename(a.page))[0]
    nbs = [x.strip() for x in a.neighbours.split(",") if x.strip()]

    rec = recent_openers(a.recent)
    if rec:
        recent_txt = ("最近 %d 集用过的开场器：\n" % len(rec)
                      + "\n".join("- %s → %s" % (d, s) for d, s in rec))
    else:
        recent_txt = "（没有历史记录 —— 挑一个最贴内容的，别默认用 situation）"
    print("[director] 要避开的开场器：%s" % [s for _, s in rec], file=sys.stderr)

    prompt = PROMPT % {"date": a.date, "title": title, "source": a.source or a.page,
                       "page": page, "recent": recent_txt,
                       "neighbours": "、".join(nbs) if nbs else "（本页没有可用邻居）"}

    best = None          # 最好的一次输出（无致命问题的），用于「重试反而更差」时兜底
    hard, soft = [], []
    for k in range(a.tries):
        raw, rec = call(prompt, stage="director")
        got = parse_json(raw)
        if got is None:
            card, hard, soft = None, ["输出不是合法 JSON"], []
        else:
            got.setdefault("date", a.date)
            got.setdefault("concept", title)
            got.setdefault("source", a.source)
            card, hard, soft = repair(got, a.source or a.page)
        print("第%d次：%d 字 / $%.4f / 致命 %s / 瑕疵 %s"
              % (k + 1, len(raw), rec.get("usd", 0), hard or "无", soft or "无"), file=sys.stderr)
        if card is not None and not hard:
            if best is None or len(soft) < len(best[1]):
                best = (card, soft)                 # 瑕疵最少的那次胜出
            if not soft:
                break
        if k < a.tries - 1:
            prompt = prompt + ("\n\n## 上一次的输出有这些问题，改掉后重新输出完整 JSON：\n- "
                               + "\n- ".join(hard + soft)
                               + "\n（提醒：每一拍都必须有 text；source 拍也要有 text；"
                                 "配音总字数控制在 300–560 字 —— 超了就删掉最不重要的那一拍，"
                                 "不要靠删句子里的字凑数。）")
    if best is None:
        print("导演失败：%s" % (hard or "输出不是合法 JSON"), file=sys.stderr)
        return 1                       # 只有这时调用方才退回切分版（v2）
    card, soft = best
    if soft:
        print("导演：有瑕疵但采用（%s）" % "；".join(soft), file=sys.stderr)
    json.dump(card, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 开场器轮换靠历史：本仓没有别的卡片写入方，所以自己归档一份（失败不影响出片）
    try:
        os.makedirs(CARDS_DIR, exist_ok=True)
        stem = os.path.splitext(os.path.basename(a.out))[0]
        with open(os.path.join(CARDS_DIR, "%s-%s.json" % (card.get("date") or a.date, stem)),
                  "w", encoding="utf-8") as fh:
            json.dump(card, fh, ensure_ascii=False, indent=1)
    except Exception as exc:
        print("[director] 归档卡片失败（不影响出片）：%s" % exc, file=sys.stderr)
    print("-->", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
