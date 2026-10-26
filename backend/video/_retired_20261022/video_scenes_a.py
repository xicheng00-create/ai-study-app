from video_base import *  # noqa: F403
from video_base import _phrase_starts  # noqa: F401

def k_situation(self, spec, dur, total):
    """H 钩子：一个他见过的现象。两个人 + 中间那条「跨不过去」的距离。"""
    st = spec.get("stage") or {}
    cap = T(st.get("caption", ""), 40, FG)
    fitw(cap, USABLE).move_to(np.array([0, 5.0, 0]))
    left = place(person(st.get("left", ""), FG).scale(1.6), -2.5, 0.5)
    right = place(person(st.get("right", ""), MUTED).scale(1.6), 2.5, 0.5)
    # 连线锚在**头部**高度、肩宽之外。用 get_right() 会锚到下方人名标签的右边缘，
    # 线就掉到人物脚底（2026-10-08 实测）。
    a = left[0].get_center() + RIGHT * 1.25
    b = right[0].get_center() + LEFT * 1.25
    gap = DashedLine(a, b, color=ACCENT, stroke_width=6, dash_length=0.22)
    glab = T(st.get("gap", ""), 32, ACCENT)
    fitw(glab, 6.4).next_to(gap, UP, buff=0.4)
    items = [(FadeIn(cap, shift=DOWN * 0.3), 0.9),
             (FadeIn(left, shift=UP * 0.4), 0.8),
             (FadeIn(right, shift=UP * 0.4), 0.8),
             (Create(gap), 0.7),
             (FadeIn(glab), 0.6)]
    if st.get("gap"):
        items.append((Indicate(gap, scale_factor=1.06, color=ACCENT), 1.0))
    steps(self, spec, dur, total, items)


def k_crossout(self, spec, dur, total):
    """M 误解：先把他想当然的答案画出来，再打叉。先破后立。"""
    st = spec.get("stage") or {}
    claim = capsule(st.get("claim", ""), 40, FG, DIM, 0.06, 11)
    fitw(claim, USABLE).move_to(np.array([0, 0.8, 0]))
    xx = xmark(claim[0].width * 0.95, claim[0].height * 1.5)
    xx.move_to(claim[0].get_center())
    note = T(st.get("note", ""), 38, ACCENT)
    fitw(note, USABLE).move_to(np.array([0, -2.4, 0]))
    steps(self, spec, dur, total, [
        (FadeIn(claim, shift=UP * 0.3), 1.0),
        (Create(xx), 0.7),
        (FadeIn(note, shift=UP * 0.3), 0.8),
    ])


def k_transform(self, spec, dur, total):
    """误解纠正 / 前后对照：同一个东西换了性质，变形动作本身就是「纠正」。"""
    st = spec.get("stage") or {}
    f, t = st.get("from") or {}, st.get("to") or {}
    l1 = T(f.get("label", ""), 40, FG)
    fitw(l1, 6.6).move_to(np.array([0, 0.8, 0]))
    l2 = T(t.get("label", ""), 40, ACCENT)
    fitw(l2, 6.6).move_to(np.array([0, 0.8, 0]))
    box = panel(l1.width + 0.9, l1.height + 0.8, DIM, 0.06)
    box.move_to(l1.get_center())
    r = max(1.0, l2.width / 2 + 0.5)
    ring = Circle(radius=r, color=ACCENT, stroke_width=6).set_fill(ACCENT, 0.10)
    ring.move_to(l2.get_center())
    cap = T(st.get("caption", ""), 34, MUTED)
    fitw(cap, USABLE).move_to(np.array([0, -2.6, 0]))
    steps(self, spec, dur, total, [
        (Create(box) if not BLANK else Create(box), 0.8),
        (FadeIn(l1), 0.6),
        (Transform(box, ring), 1.2),
        (ReplacementTransform(l1, l2), 0.6),
        (FadeIn(cap, shift=UP * 0.2), 0.8),
    ])


def k_chain(self, spec, dur, total):
    """K 机制：一环一个节拍。让「力」可见 —— 点穿过链条、节点被点亮。"""
    st = spec.get("stage") or {}
    nodes = [n for n in (st.get("nodes") or []) if n][:4]
    if not nodes:
        return __import__("video_scenes_b").k_text(self, spec, dur, total)
    xs = -2.3
    ys = [2.0 - i * (4.0 / max(1, len(nodes) - 1)) for i in range(len(nodes))] \
        if len(nodes) > 1 else [0.0]
    circles, labels = VGroup(), VGroup()
    for n, y in zip(nodes, ys):
        lab = str(n.get("label") if isinstance(n, dict) else n)
        c = Circle(radius=0.34, color=PRIMARY, stroke_width=4).set_fill(PRIMARY, 0.12)
        c.move_to(np.array([xs, y, 0]))
        tl = T(lab, 36, FG)
        fitw(tl, 5.6).next_to(c, RIGHT, buff=0.5)
        circles.add(c)
        labels.add(tl)
    token = Dot(radius=0.13, color=ACCENT).move_to(circles[0].get_center())
    items = [(FadeIn(circles[0], scale=0.6), 0.6),
             (FadeIn(labels[0]), 0.5),
             (FadeIn(token, scale=0.4), 0.4)]
    for i in range(1, len(nodes)):
        a, b = circles[i - 1].get_center(), circles[i].get_center()
        arr = Arrow(a + DOWN * 0.35, b + UP * 0.35, buff=0,
                    color=PRIMARY, stroke_width=6,
                    max_tip_length_to_length_ratio=0.16)
        path = Line(a, b)
        # 「力」在这一拍里可见：箭头长出来、点沿线穿过、节点同时被点亮。
        # 三件事必须在同一拍 —— 分开播就退化成「先画框、再点亮」的排版动画。
        items.append(((GrowArrow(arr),
                       MoveAlongPath(token, path),
                       FadeIn(labels[i]),
                       circles[i].animate.set_stroke(ACCENT).set_fill(ACCENT, 0.45)),
                      0.9))
    steps(self, spec, dur, total, items)


def k_axis(self, spec, dur, total):
    """程度 / 量值：坐标轴 + 会滑动的标记。长度是比例映射，看得见「在哪一段」。"""
    st = spec.get("stage") or {}
    y = -0.5
    x0, x1 = -3.5, 3.5
    axis = Line([x0, y, 0], [x1, y, 0], color=DIM, stroke_width=6)
    ticks = VGroup(*[Line([x, y - 0.2, 0], [x, y + 0.2, 0], color=DIM, stroke_width=5)
                     for x in np.linspace(x0, x1, 5)])
    lab = T(st.get("axis", ""), 38, FG).move_to(np.array([0, y + 2.1, 0]))
    lo = T(st.get("left", ""), 30, MUTED).next_to(axis, DOWN, buff=0.35).align_to(axis, LEFT)
    hi = T(st.get("right", ""), 30, MUTED).next_to(axis, DOWN, buff=0.35).align_to(axis, RIGHT)
    at = float(st.get("at", 0.7))
    tx = x0 + (x1 - x0) * max(0.0, min(1.0, at))
    fill = Line([x0, y, 0], [x0 + 0.02, y, 0], color=ACCENT, stroke_width=12)
    mk = Triangle(color=ACCENT, fill_opacity=1).scale(0.22).rotate(PI)
    mk.move_to(np.array([x0, y + 0.75, 0]))
    glab = T(st.get("marker", ""), 30, ACCENT)
    fitw(glab, 5.0).move_to(np.array([x0, y + 1.15, 0]))
    rt = max(0.8, min(2.0, dur * 0.25))
    items = [(Create(axis), 0.6),
             (Create(ticks), 0.4),
             (FadeIn(lab), 0.5),
             (FadeIn(lo), 0.3),
             (FadeIn(hi), 0.3),
             # 一拍里同时发生：标记滑动 + 它走过的量长出来 + 标签跟上。
             # 分成三拍播就变成「先摆好、再动一下」的排版动画。
             (FadeIn(VGroup(mk, glab), shift=DOWN * 0.3), 0.6),
             ((mk.animate.move_to(np.array([tx, y + 0.75, 0])),
               glab.animate.move_to(np.array([tx, y + 1.15, 0])),
               Transform(fill, Line([x0, y, 0], [tx, y, 0],
                                    color=ACCENT, stroke_width=12))), rt)]
    steps(self, spec, dur, total, items)


def k_threshold(self, spec, dur, total):
    """阈值 / 临界：量一直涨，越过那条线才质变。"""
    st = spec.get("stage") or {}
    box = place(panel(3.4, 7.0, DIM, 0.04, 4), -1.9, 0.2)
    y_line = 1.4
    wline = DashedLine([-3.4, y_line, 0], [-0.4, y_line, 0], color=ACCENT,
                       stroke_width=5, dash_length=0.2)
    lname = T(st.get("line", "临界点"), 30, ACCENT).next_to(wline, UP, buff=0.25).align_to(wline, LEFT)
    bar = Rectangle(width=2.6, height=0.6, color=PRIMARY, stroke_width=0)
    bar.set_fill(PRIMARY, 0.55)
    bar.move_to(np.array([-1.9, -3.0, 0]))
    below = T(st.get("below", ""), 34, MUTED)
    fitw(below, 4.0).move_to(np.array([1.6, -1.2, 0]))
    above = T(st.get("above", ""), 38, RED, BOLD)
    fitw(above, 4.0).move_to(np.array([1.6, 1.4, 0]))
    level = T(st.get("level", ""), 32, FG).next_to(box, UP, buff=0.35)
    h1, h2 = 3.4, 5.6
    items = [(FadeIn(level), 0.5),
             (Create(box), 0.7),
             (Create(wline), 0.5),
             (FadeIn(lname), 0.5),
             (FadeIn(bar), 0.5),
             (bar.animate.stretch_to_fit_height(h1).align_to(np.array([0, -3.3, 0]), DOWN), 1.2),   # 占位
             ]
    # 上一条的 align_to 目标点不对，重建（严格按锚点抬高）
    anchor = np.array([-1.9, -3.3, 0])
    bar.move_to(anchor + UP * 0.3)
    items[5] = (bar.animate.stretch_to_fit_height(h1).align_to(anchor, DOWN), 1.2)
    items.append((bar.animate.set_fill(RED, 0.6).set_stroke(RED)
                  .stretch_to_fit_height(h2).align_to(anchor, DOWN), 1.4))
    items.append((FadeIn(above, shift=DOWN * 0.3), 0.6))
    items.append((FadeIn(below), 0.1))
    steps(self, spec, dur, total, items)


def k_loop(self, spec, dur, total):
    """循环 / 反馈：首尾相接，自我驱动。点必须一直转。"""
    st = spec.get("stage") or {}
    nodes = [str(n.get("label") if isinstance(n, dict) else n)
             for n in (st.get("nodes") or [])][:4]
    if len(nodes) < 2:
        return __import__("video_scenes_b").k_text(self, spec, dur, total)
    c = Circle(radius=2.3, color=DIM, stroke_width=5).move_to(np.array([0, 0.2, 0]))
    arcs, labs = VGroup(), VGroup()
    n = len(nodes)
    for i in range(n):
        a0 = PI / 2 + i * TAU / n
        seg = Arc(radius=2.3, start_angle=a0, angle=TAU / n * 0.72,
                  color=PRIMARY, stroke_width=5).move_arc_center_to(c.get_center())
        tip = seg.get_end()
        head = Triangle(color=PRIMARY, fill_opacity=1).scale(0.16)
        head.rotate(seg.get_end() - seg.get_start())
        head.move_to(tip)
        arcs.add(VGroup(seg, head))
        p = np.array([2.3 * np.cos(a0 + TAU / n / 2) + c.get_center()[0],
                      2.3 * np.sin(a0 + TAU / n / 2) + c.get_center()[1], 0])
        tl = T(nodes[i], 32, FG)
        fitw(tl, 4.2).move_to(p).shift(np.array([0, 0.0, 0]) * (1.0 if p[1] > 0.2 else 1.0))
        labs.add(tl)
    token = Dot(radius=0.14, color=ACCENT).move_to(c.point_at_angle(PI / 2))
    items = [(Create(c, run_time=0.01), 0.01),
             (FadeIn(arcs), 1.2),
             (FadeIn(labs), 0.8),
             (FadeIn(token, scale=0.4), 0.4)]
    items.append((MoveAlongPath(token, Circle(radius=2.3).move_to(c.get_center())),
                  max(1.5, min(3.0, dur * 0.3))))
    steps(self, spec, dur, total, items)


def k_balance(self, spec, dur, total):
    """互补 / 此消彼长：天平必须真的倾斜，落点角度对应权重差。"""
    st = spec.get("stage") or {}
    pivot = np.array([0, -1.6, 0])
    beam = Line([-2.9, 0, 0], [2.9, 0, 0], color=PRIMARY, stroke_width=7)
    tri = Triangle(color=DIM, fill_opacity=0.4).scale(0.7).rotate(PI)
    tri.move_to(pivot + UP * 0.35)
    pans, labs = VGroup(), VGroup()
    for sx, key in ((-2.9, "left"), (2.9, "right")):
        pan = Circle(radius=0.46, color=ACCENT, stroke_width=4).set_fill(ACCENT, 0.12)
        pan.move_to(np.array([sx, -1.0, 0]))
        pans.add(pan)
        tl = T(st.get(key, ""), 34, FG)
        fitw(tl, 4.0).next_to(pan, DOWN, buff=0.4)
        labs.add(tl)
    beam.move_to(pivot + UP * 1.5)
    pans.shift(UP * 1.5)
    labs.shift(UP * 1.5)
    tilt = float(st.get("tilt", -0.22))
    grp = VGroup(beam, pans, labs)
    items = [(FadeIn(tri), 0.6),
             (Create(beam), 0.7),
             (FadeIn(pans), 0.6),
             (FadeIn(labs), 0.6),
             (Rotate(grp, tilt, about_point=pivot + UP * 1.5),
              max(1.0, min(2.0, dur * 0.25)))]
    steps(self, spec, dur, total, items)


