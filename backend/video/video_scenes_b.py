from video_base import *  # noqa: F403
from video_base import _phrase_starts  # noqa: F401
def k_stack(self, spec, dur, total):
    """积累 / 复利：一格一格加出来，看得见每一格加了多少。"""
    st = spec.get("stage") or {}
    blocks = [str(b.get("label") if isinstance(b, dict) else b) for b in (st.get("blocks") or [])][:6]
    if not blocks:
        return k_text(self, spec, dur, total)
    x, y0, side = -1.4, -3.4, 1.0
    items, cnts = [], []
    cap = T(st.get("caption", ""), 34, MUTED)
    fitw(cap, USABLE).move_to(np.array([0, 4.6, 0]))
    items.append((FadeIn(cap), 0.5))
    for i, b in enumerate(blocks):
        sq = Square(side_length=side, color=PRIMARY, stroke_width=4)
        sq.set_fill(PRIMARY, 0.10 + 0.08 * i)
        sq.move_to(np.array([x, y0 + side / 2 + i * side, 0]))
        tl = T(b, 36, FG).move_to(sq.get_center())
        num = T(str(i + 1), 34, ACCENT).move_to(np.array([x + 1.6, sq.get_center()[1], 0]))
        items.append((FadeIn(VGroup(sq, tl), shift=UP * 0.25), 0.5))
        items.append((FadeIn(num), 0.3))
    steps(self, spec, dur, total, items)


def k_nodes(self, spec, dur, total):
    """关系 / 结构：中心 + 轨道上的真邻居。找不到真实关联就别用这场。"""
    st = spec.get("stage") or {}
    center = str(st.get("center", ""))
    nbs = [str(n) for n in (st.get("nodes") or []) if str(n).strip()][:6]
    core = Circle(radius=0.95, color=ACCENT, stroke_width=5).set_fill(ACCENT, 0.14)
    core.move_to(np.array([0, 0.2, 0]))
    clab = T(center, 34, FG)
    fitw(clab, 2.4).move_to(core.get_center())
    items = [(FadeIn(core, scale=0.6), 0.6), (FadeIn(clab), 0.5)]
    for i, nb in enumerate(nbs):
        ang = PI / 2 + i * TAU / max(1, len(nbs))
        p = core.get_center() + np.array([3.0 * np.cos(ang), 4.2 * np.sin(ang), 0])
        d = Dot(radius=0.3, color=PRIMARY).move_to(p)
        tl = T(nb, 30, FG)
        fitw(tl, 3.6)
        tl.next_to(d, DOWN if p[1] < core.get_center()[1] else UP, buff=0.26)
        ln = Line(core.get_center(), p, color=PRIMARY, stroke_width=3)
        items.append((Create(ln), 0.35))
        items.append((FadeIn(VGroup(d, tl)), 0.4))
    steps(self, spec, dur, total, items)


def k_steps(self, spec, dur, total):
    """可操作：一步一拍的判定/动作清单，最后打勾。"""
    st = spec.get("stage") or {}
    ss = [str(s) for s in (st.get("steps") or []) if str(s).strip()][:4]
    if not ss:
        return k_text(self, spec, dur, total)
    ys = [2.2 - i * (4.8 / max(1, len(ss) - 1)) for i in range(len(ss))] if len(ss) > 1 else [0.4]
    items = []
    last = None
    for i, (s, y) in enumerate(zip(ss, ys)):
        d = disc(str(i + 1)).move_to(np.array([-2.9, y, 0]))
        lab = VGroup(*[T(l, 32, FG) for l in wrap(s, 11)]).arrange(
            DOWN, buff=0.14, aligned_edge=LEFT)
        fitw(lab, 4.6)
        lab.next_to(d, RIGHT, buff=0.5)
        lab.align_to(d, UP).shift(DOWN * 0.1)
        items.append((FadeIn(d, scale=0.5), 0.5))
        items.append((FadeIn(lab, shift=RIGHT * 0.2), 0.5))
        last = lab
    tk = tick(0.5)
    tk.next_to(last, DOWN, buff=0.45).align_to(last, LEFT)
    items.append((Create(tk), 0.6))
    steps(self, spec, dur, total, items)


def k_close(self, spec, dur, total):
    """Z 收束：回到钩子的画面，把距离连上，一句话锁住。"""
    st = spec.get("stage") or {}
    head = VGroup(*[T(l, 44, FG, BOLD) for l in (st.get("headline") or [])])
    if st.get("headline") and isinstance(st["headline"], str):
        head = VGroup(*[T(l, 44, FG, BOLD) for l in [st["headline"]]])
    head.arrange(DOWN, buff=0.3, aligned_edge=LEFT)
    fitw(head, USABLE).move_to(np.array([0, 4.4, 0]))
    left = place(person(st.get("left", ""), FG).scale(1.6), -2.5, -0.6)
    right = place(person(st.get("right", ""), MUTED).scale(1.6), 2.5, -0.6)
    link = Line(left[0].get_center() + RIGHT * 1.25, right[0].get_center() + LEFT * 1.25,
                color=GREEN, stroke_width=7)
    glab = T(st.get("gap", ""), 32, GREEN)
    fitw(glab, 6.0).next_to(link, UP, buff=0.35)
    items = [(FadeIn(head, shift=DOWN * 0.3), 0.8),
             (FadeIn(left, shift=UP * 0.3), 0.6),
             (FadeIn(right, shift=UP * 0.3), 0.6),
             (Create(link), 0.7),
             (FadeIn(glab), 0.6)]
    steps(self, spec, dur, total, items)


def k_source(self, spec, dur, total):
    """出处卡：讲完必须能回溯。"""
    st = spec.get("stage") or {}
    lines = [str(x) for x in (st.get("lines") or []) if str(x).strip()]
    head = T(st.get("headline", "这页从哪来"), 34, ACCENT)
    fitw(head, USABLE).move_to(np.array([0, 4.4, 0]))
    body = VGroup(*[T(l, 28, MUTED if i else FG) for i, l in enumerate(lines)])
    body.arrange(DOWN, buff=0.35, aligned_edge=LEFT)
    fitw(body, USABLE - 1.2)
    card = panel(max(4.6, body.width + 1.1), body.height + 1.4, DIM, 0.05)
    card.move_to(np.array([0, 0.4, 0]))
    body.move_to(card.get_center())
    steps(self, spec, dur, total, [
        (FadeIn(head, shift=DOWN * 0.3), 0.7),
        (Create(card), 0.7),
        (FadeIn(body), 0.8),
    ])


def k_text(self, spec, dur, total):
    """兜底（旧卡片 / 结构字段缺失）：干净的分行文字场。不用于新卡片。"""
    head = spec.get("headline") or spec.get("title") or spec.get("concept") or ""
    if isinstance(head, str):
        head = wrap(head, 10)[:2]
    body = VGroup(*[T(l, 54, FG, BOLD) for l in head]).arrange(
        DOWN, buff=0.28, aligned_edge=LEFT)
    fitw(body, USABLE).move_to(np.array([0, 2.2, 0]))
    rule = Line([-1.4, 0, 0], [1.4, 0, 0], color=ACCENT, stroke_width=8)
    rule.next_to(body, DOWN, buff=0.55).align_to(body, LEFT)
    lines = spec.get("lines") or wrap(spec.get("text", ""), 14)[:4]
    tail = VGroup(*[T(l, 30, MUTED) for l in lines]).arrange(
        DOWN, buff=0.24, aligned_edge=LEFT)
    fitw(tail, USABLE).next_to(rule, DOWN, buff=0.6).align_to(body, LEFT)
    steps(self, spec, dur, total, [
        (FadeIn(body, shift=DOWN * 0.3), 0.9),
        (Create(rule), 0.5),
        (FadeIn(tail), 0.9),
    ])


