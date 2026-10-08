# 来源：brain workspace/daily-video，勿就地魔改，同步靠内容比对
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竖屏讲解视频渲染器 v3 —— 图形语法版（Manim）。

为什么有 v2 → v3：
  v2 每一场都是「文字装进方框 + 箭头连框」。按视觉设计 playbook 的分级，那是 **L1**
  （像图，其实是排版）—— 用户 2026-10-08 的判词正是这个：「箭头指向的方框，
  还只是简单地把文案拿来切」。L2 的要求是：**图形自带量、方向、状态，动画演示推理过程**。

三条硬判据（想改画面之前先读）：
  1. 擦字检验：`BLANK_TEXT=1` 渲染一遍，把字全擦掉只看图形，还能说出这一刻在发生什么吗。
  2. 帧差检验：首帧与末帧的差必须是结构性的（量变了 / A 变成 B / 某物移位），
     不能只是「多了几行字」。
  3. 箭头只表示**关系**，不表示先后。先后用位置移动或时间轴表达。

场景 id 与配音时长从同目录的 narration.json / durations.json 读；每场渲染长度
= 该段配音实测秒数 + PAD，必须与 stitch_av.sh 的 PAD 一致，否则音画全程漂移且不报错。
"""
import json
import os
import re
import numpy as np
from manim import *

# ---- 竖屏：9×16（只设 pixel_* 会把画面拉扁）----
config.frame_width = 9
config.frame_height = 16
config.pixel_width = 1080
config.pixel_height = 1920
config.background_color = "#0F1317"

BG = "#0F1317"
FG = "#F1F5F8"
MUTED = "#8A949E"
DIM = "#5A636C"
PRIMARY = "#59A9FF"
ACCENT = "#FFC24B"
RED = "#FF6B6B"
GREEN = "#5BD37A"

TOP_Y = 6.9          # 安全区上边（1080×1920 下 132px）
BOT_Y = -7.1         # 安全区下边（108px；平台控件再吃掉一档）
USABLE = 8.1         # 可用宽 972px = 画幅 90%
PAD = 0.6            # 每场配音后补的静音；必须与 stitch_av.sh 的 PAD 相同
BLANK = os.environ.get("BLANK_TEXT") == "1"   # 擦字检验：文字全部透明、图形照留


# --------------------------------------------------------------------------- #
# 基础元件
# --------------------------------------------------------------------------- #
def T(s, size=32, color=FG, weight=NORMAL):
    t = Text(str(s), font="PingFang SC", font_size=size, color=color, weight=weight)
    if BLANK:
        t.set_opacity(0)
    return t


def fitw(m, w=USABLE):
    if m.width > w:
        m.scale_to_fit_width(w)
    return m


def fith(m, h):
    if m.height > h:
        m.scale_to_fit_height(h)
    return m


def wrap(s, limit):
    """只切不写：按标点断句，超长再硬切。画面文字一律是标签，不是句子。"""
    s = str(s or "").strip()
    if not s:
        return [""]
    parts = [p for p in re.split(r"(?<=[。！？；，、：])", s) if p.strip()]
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) > limit:
            out.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        out.append(cur)
    hard = []
    for ln in out:
        while len(ln) > limit + 4:            # 单句太长才硬剁，均分不剩孤字
            n = (len(ln) + limit - 1) // limit
            step = (len(ln) + n - 1) // n
            hard.append(ln[:step])
            ln = ln[step:]
        hard.append(ln)
    return [x.strip("，。、；：") for x in hard if x.strip("，。、；：")] or [s]


def panel(w, h, color=PRIMARY, fill=0.10, sw=3.5):
    r = RoundedRectangle(width=w, height=h, corner_radius=0.22,
                         color=color, stroke_width=sw)
    r.set_fill(color, fill)
    return r


def capsule(text, size=40, color=FG, edge=PRIMARY, fill=0.10, limit=12):
    """标签 + 刚好包住它的框。框宽由文字决定，所以框本身不传递信息、只做归类。"""
    lab = VGroup(*[T(l, size, color) for l in wrap(text, limit)]).arrange(
        DOWN, buff=0.16, aligned_edge=LEFT)
    fitw(lab, USABLE - 1.0)
    box = panel(lab.width + 0.9, lab.height + 0.75, edge, fill)
    box.move_to(lab.get_center())
    return VGroup(box, lab)


def person(label="", color=FG, h=1.9):
    head = Circle(radius=0.36, color=color, stroke_width=4).set_fill(color, 0.14)
    body = Arc(radius=0.72, start_angle=0, angle=PI, color=color, stroke_width=4)
    body.next_to(head, DOWN, buff=-0.02)
    g = VGroup(head, body)
    if label:
        g.add(T(label, 30, MUTED).next_to(body, DOWN, buff=0.24))
    return VGroup(*g)


def xmark(w, h, color=RED, sw=14):
    a = Line([-w / 2, h / 2, 0], [w / 2, -h / 2, 0], color=color, stroke_width=sw)
    b = Line([-w / 2, -h / 2, 0], [w / 2, h / 2, 0], color=color, stroke_width=sw)
    return VGroup(a, b)


def tick(s=0.34, color=GREEN, sw=8):
    m = VMobject().set_points_as_corners([
        np.array([-s * 0.5, -s * 0.05, 0]),
        np.array([-s * 0.12, -s * 0.42, 0]),
        np.array([s * 0.55, s * 0.4, 0])])
    m.set_stroke(color, sw)
    return m


def disc(txt, color=ACCENT, r=0.42, size=34):
    c = Circle(radius=r, color=color, stroke_width=4).set_fill(color, 0.16)
    return VGroup(c, T(txt, size, color).move_to(c.get_center()))


# --------------------------------------------------------------------------- #
# 时序引擎：把画面节拍对到配音念到那个词的那一刻
# --------------------------------------------------------------------------- #
SPECS, DURS = {}, {}


def _load():
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        n = json.load(open(os.path.join(here, "narration.json"), encoding="utf-8"))
    except Exception:
        return
    for s in n.get("scenes", []):
        SPECS[s["id"]] = s
    try:
        for r in json.load(open(os.path.join(here, "durations.json"), encoding="utf-8")):
            DURS[r["id"]] = r
    except Exception:
        pass
    for sid, s in SPECS.items():
        s["_words"] = (DURS.get(sid) or {}).get("words") or []


def _phrase_starts(text, words, dur):
    """每个短句的开念时刻。有词级时刻就用真的，拿不到就按字数比例估。"""
    phrases = [p for p in re.split(r"(?<=[。！？；，、])", text or "") if p.strip()] or [text or ""]
    out = [None] * len(phrases)
    joined = "".join(w for w, _ in words)
    cursor = 0
    for i, p in enumerate(phrases):
        key = re.sub(r"[^\w\u4e00-\u9fff]", "", p)
        if not (joined and key):
            continue
        idx = joined.find(key[:8], max(0, cursor - 4))
        if idx < 0:
            idx = cursor
        cursor = idx + len(key)
        acc = 0
        for w, wt in words:
            if acc + len(w) > idx:
                out[i] = float(wt)
                break
            acc += len(w)
    known = [i for i, t in enumerate(out) if t is not None]
    if not known:
        tot = sum(len(p) for p in phrases) or 1
        acc = 0
        for i, p in enumerate(phrases):
            out[i] = acc * dur / tot
            acc += len(p)
        return out
    for i in range(len(out)):
        if out[i] is None:
            lo = [k for k in known if k < i]
            hi = [k for k in known if k > i]
            if lo and hi:
                a, b = out[lo[-1]], out[hi[0]]
                out[i] = a + (b - a) * (i - lo[-1]) / (hi[0] - lo[-1])
            elif lo:
                out[i] = out[lo[-1]]
            else:
                out[i] = out[hi[0]]
    return out


def cues(spec, dur, n):
    """给 n 个画面节拍分配触发时刻：视觉比配音早 0.25s，末拍前留出静止。"""
    dur = max(2.0, float(dur or 7.0))
    ts = _phrase_starts(spec.get("text", ""), spec.get("_words") or [], dur)
    if n <= 1:
        picked = [ts[0]]
    elif len(ts) >= n:
        picked = [ts[round(i * (len(ts) - 1) / (n - 1))] for i in range(n)]
    else:
        picked = [ts[0] + (ts[-1] - ts[0]) * i / (n - 1) for i in range(n)]
    out = []
    for t in picked:
        t = max(0.25, min(float(t) - 0.25, max(0.25, dur - 0.9)))
        if out and t <= out[-1] + 0.3:
            t = out[-1] + 0.3
        out.append(round(t, 2))
    return out


def steps(self, spec, dur, total, items):
    """items: [(动画或动画元组, run_time)]，按 cues() 算出的时刻逐个播，末尾补静止到 total。"""
    flat = []
    for it in items:
        a, rt = it
        if not isinstance(a, (tuple, list)):
            a = (a,)
        flat.append((tuple(a), rt))
    ts = cues(spec, dur, len(flat))
    t = 0.0
    for i, (anims, rt) in enumerate(flat):
        if ts[i] - t > 0.04:
            self.wait(ts[i] - t)
            t = ts[i]
        self.play(*anims, run_time=rt)
        t += rt
    if total > t:
        self.wait(total - t)


def place(m, x, y):
    m.move_to(np.array([float(x), float(y), 0]))
    return m


# --------------------------------------------------------------------------- #
# 图形语法：一类逻辑 → 一类图形（选型来自视觉 playbook §2）
# --------------------------------------------------------------------------- #
