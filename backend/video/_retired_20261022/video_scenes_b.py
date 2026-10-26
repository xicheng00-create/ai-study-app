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




# --------------------------------------------------------------------------- #
# 开场器变体（v5）：拆掉「固定开场两拍 = 两个人 + 一条线 + 一个叉」的死局。
# 功能要求不变（先演他以为的答案），但**画法可以是完全不同的东西**：
#   dayband  一天的时间条被刷手机填满、那件事那格始终空着
#   object   物件特写：一台手机的屏幕，时间在跳，任务框一直空
#   dialogue 两组对话气泡（人根本不出场）
# director 不再被迫选 situation，改为按内容挑开场器。
# --------------------------------------------------------------------------- #
def k_dayband(self, spec, dur, total):
    """开场器·一天的时间条：24 格被「刷手机」逐格填满，而要做的那件事那格一直空着。"""
    st = spec.get("stage") or {}
    cap = T(st.get("caption", ""), 40, FG)
    fitw(cap, USABLE).move_to(np.array([0, 5.6, 0]))
    y = 2.0
    band = RoundedRectangle(width=USABLE, height=1.45, corner_radius=0.22,
                            color=PRIMARY, stroke_width=3.5)
    band.set_fill(PRIMARY, 0.06).move_to(np.array([0, y, 0]))
    n = 24
    cells, fill = [], []
    for i in range(n):
        x0 = -USABLE / 2 + USABLE * i / n
        c = Rectangle(width=USABLE / n - 0.06, height=1.16, stroke_width=0)
        c.set_fill(ACCENT, 0.55).move_to(np.array([x0 + USABLE / (2 * n), y, 0]))
        cells.append(c)
    for i in range(n):
        if i < n - 5:          # 只填到虚线空框左侧为止，否则填充块会压进空框里
            fill.append(cells[i])
    ticks = VGroup()
    for i in range(0, n + 1, 3):
        x = -USABLE / 2 + USABLE * i / n
        ticks.add(Line([x, y - 0.86, 0], [x, y - 0.62, 0], color=DIM, stroke_width=2))
    slot = DashedVMobject(
        RoundedRectangle(width=USABLE / n * 5, height=1.16, corner_radius=0.12,
                         color=RED, stroke_width=3),
        num_dashes=18)
    slot.move_to(np.array([USABLE / 2 - USABLE / n * 2.5, y, 0]))
    slot_lab = T(st.get("empty", "那件事"), 28, RED)
    fitw(slot_lab, USABLE / n * 5 - 0.3).next_to(slot, DOWN, buff=0.30)
    left_lab = T(st.get("fill", "刷手机"), 30, ACCENT)
    left_lab.next_to(band, UP, buff=0.34).align_to(band, LEFT).shift(RIGHT * 0.5)
    cursor = Triangle(stroke_width=0).set_fill(ACCENT, 1.0).scale(0.30)
    cursor.rotate(PI)
    cursor.next_to(band, UP, buff=0.10).align_to(band, LEFT)
    cursor.shift(RIGHT * 0.30)
    steps(self, spec, dur, total, [
        (FadeIn(cap, shift=DOWN * 0.3), 0.8),
        (Create(band), 0.7),
        (FadeIn(ticks), 0.5),
        (LaggedStart(*[GrowFromEdge(c, DOWN) for c in fill], lag_ratio=0.10), 1.6),
        (FadeIn(left_lab), 0.5),
        ((Create(slot), FadeIn(slot_lab)), 0.8),
        (cursor.animate.align_to(band, RIGHT).shift(LEFT * 0.2), 1.2),
    ])


def k_object(self, spec, dur, total):
    """开场器·物件特写：一台手机（屏幕上的时间在跳），旁边那件事一直空着。"""
    st = spec.get("stage") or {}
    cap = T(st.get("caption", ""), 40, FG)
    fitw(cap, USABLE).move_to(np.array([0, 5.6, 0]))
    body = RoundedRectangle(width=4.3, height=7.4, corner_radius=0.55,
                            color=FG, stroke_width=5)
    body.set_fill(BG, 0.5).move_to(np.array([0, 0.4, 0]))
    screen = RoundedRectangle(width=3.7, height=6.6, corner_radius=0.40,
                              color=PRIMARY, stroke_width=3)
    screen.set_fill(PRIMARY, 0.08).move_to(body.get_center())
    notch = RoundedRectangle(width=1.3, height=0.20, corner_radius=0.10,
                             color=FG, stroke_width=0)
    notch.set_fill(FG, 0.65).move_to(screen.get_top() + DOWN * 0.34)
    clock = T(st.get("clock", "23:41"), 96, FG, BOLD).move_to(screen.get_center() + UP * 1.3)
    clock2 = T(st.get("clock2", "23:42"), 96, MUTED, BOLD).move_to(clock.get_center())
    feed = VGroup()
    for i in range(3):
        r = RoundedRectangle(width=3.0, height=0.60, corner_radius=0.14,
                             color=DIM, stroke_width=2)
        r.set_fill(DIM, 0.10).move_to(screen.get_center() + DOWN * (0.30 + i * 0.80))
        feed.add(r)
    task = DashedVMobject(
        RoundedRectangle(width=3.0, height=0.60, corner_radius=0.14, color=RED, stroke_width=3),
        num_dashes=16)
    task.move_to(screen.get_center() + DOWN * (0.30 + 3 * 0.80))
    # 标签必须放在虚线框**里面**：放框下会被机身下沿的粗描边压掉（实拍踩过）
    task_lab = T(st.get("task", "那件事"), 26, RED).move_to(task.get_center())
    steps(self, spec, dur, total, [
        (FadeIn(cap, shift=DOWN * 0.3), 0.8),
        (FadeIn(body), 0.6),
        (FadeIn(screen), 0.5),
        (FadeIn(notch), 0.3),
        (FadeIn(clock, scale=0.85), 0.6),
        (ReplacementTransform(clock, clock2), 1.0),      # 时间在走
        (LaggedStart(*[FadeIn(r, shift=UP * 0.2) for r in feed], lag_ratio=0.25), 1.2),
        ((Create(task), FadeIn(task_lab)), 0.9),
    ])


def _bubble(text, side="left", color=None, w=5.2, size=30):
    color = color or PRIMARY
    lab = VGroup(*[T(l, size, FG) for l in wrap(text, 10)]).arrange(
        DOWN, buff=0.14, aligned_edge=LEFT)
    fitw(lab, w - 1.0)
    box = RoundedRectangle(width=max(w, lab.width + 1.1), height=lab.height + 0.75,
                           corner_radius=0.30, color=color, stroke_width=3)
    box.set_fill(color, 0.12).move_to(lab.get_center())
    tail = RoundedRectangle(width=0.34, height=0.34, corner_radius=0.06,
                            color=color, stroke_width=0).set_fill(color, 0.12)
    tail.rotate(PI / 4)
    if side == "left":
        tail.next_to(box, DOWN, buff=-0.16).align_to(box, LEFT).shift(RIGHT * 0.55)
    else:
        tail.next_to(box, DOWN, buff=-0.16).align_to(box, RIGHT).shift(LEFT * 0.55)
    return VGroup(box, lab, tail)


def k_dialogue(self, spec, dur, total):
    """开场器·对话气泡：人不出场，只出两组话（最省钱、也最不像「图解」的一种）。"""
    st = spec.get("stage") or {}
    lines = st.get("lines") or [st.get("a", ""), st.get("b", "")]
    cap = T(st.get("caption", ""), 40, FG)
    fitw(cap, USABLE).move_to(np.array([0, 5.8, 0]))
    bs = []
    xs, ys = (-1.0, 1.2, -0.5), (2.9, -0.1, -3.0)
    for i, tx in enumerate(lines[:3]):
        small = i == 2                       # 第三句是「声音变小」：更小、更淡
        b = _bubble(tx, "left" if i % 2 == 0 else "right",
                    MUTED if i % 2 == 0 else ACCENT,
                    w=5.2 if not small else 4.2, size=30 if not small else 25)
        if small:
            b.set_opacity(0.7)
        b.move_to(np.array([xs[i], ys[i], 0]))
        bs.append(b)
    anims = [(FadeIn(cap, shift=DOWN * 0.3), 0.8)]
    for b in bs:
        anims.append((FadeIn(b, shift=UP * 0.3), 1.0))
    steps(self, spec, dur, total, anims)
