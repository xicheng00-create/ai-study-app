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
import hashlib
import json
import os
import re
import sys
import numpy as np
from manim import *

# ---- 竖屏：9×16（只设 pixel_* 会把画面拉扁）----
config.frame_width = 9
config.frame_height = 16
config.pixel_width = 1080
config.pixel_height = 1920

# --------------------------------------------------------------------------- #
# 主题皮肤（v4）：原先整片共用一张写死的皮（BG/FG/PRIMARY/ACCENT 全是常量），
# 所以不管分镜怎么变，出来的都是同一个频道。这里把「皮」抽出来：
#   四套皮 = 四套配色 + 一层质感（光晕 / 网格 / 纸纹 / 暗角）
#   选皮：VIDEO_THEME 环境变量 > 主题词匹配 > ink；连续两集不撞脸；
#         同一份 narration 重复渲染结果稳定（geocheck / 重渲不会换皮）。
# 状态目录（.last_theme 与背景 PNG 缓存）：默认 = 本文件目录；可用 VIDEO_STATE_DIR
# 指到持久目录 —— 本仓每次渲染都新建临时 project 目录，不指出来「连续两集不撞脸」会静默失效。
# --------------------------------------------------------------------------- #
STATE_DIR = os.environ.get("VIDEO_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))

THEMES = {
    "ink": {
        "name": "墨蓝夜景",
        "bg": "#0F1317", "fg": "#F1F5F8", "muted": "#8A949E", "dim": "#5A636C",
        "primary": "#59A9FF", "accent": "#FFC24B", "red": "#FF6B6B", "green": "#5BD37A",
        "glow": "#2E4C6E", "texture": "glow",
        "corner": 0.22, "fill": 0.10, "person_fill": 0.14,
    },
    "paper": {
        "name": "米白手记",
        "bg": "#F6F2EA", "fg": "#1E1A16", "muted": "#6C6359", "dim": "#948A7D",
        "primary": "#1F4E79", "accent": "#C0392B", "red": "#B03A2E", "green": "#2E7D4F",
        "glow": "#DED4C2", "texture": "rule",
        "corner": 0.14, "fill": 0.07, "person_fill": 0.85,
    },
    "grid": {
        "name": "深蓝工程",
        "bg": "#0B1F33", "fg": "#DCEAF5", "muted": "#7C9CB8", "dim": "#4E6E8A",
        "primary": "#7FB4E0", "accent": "#4FD1C5", "red": "#FF7A6B", "green": "#5BD37A",
        "glow": "#6FB6E8", "texture": "grid",
        "corner": 0.10, "fill": 0.12, "person_fill": 0.18,
    },
    "ember": {
        "name": "暖橙暗角",
        "bg": "#1A1410", "fg": "#F5E7D6", "muted": "#B39C86", "dim": "#7A6455",
        "primary": "#FFB877", "accent": "#FF9E4F", "red": "#E2725B", "green": "#8FBF7F",
        "glow": "#FF9E4F", "texture": "vignette",
        "corner": 0.26, "fill": 0.12, "person_fill": 0.75,
    },
}
THEME_ORDER = ["ink", "paper", "grid", "ember"]
# 主题词 → 皮：技术/系统走工程网格，认知/情绪/习惯走米白手记，产品/故事走暖橙
TOPIC_HINTS = [
    (r"系统|架构|接口|数据|代码|工程|服务|性能|部署|算法|模型|网络|缓存|并发|协议", "grid"),
    (r"习惯|笔记|复盘|学习|认知|阅读|写作|心理|情绪|抑郁|焦虑|专注|记忆|思考|拖延", "paper"),
    (r"产品|故事|用户|增长|品牌|营销|设计|体验|客户|市场|定价|需求|创业", "ember"),
]


def _theme_seed_text():
    """内容指纹素材：narration.json 里没有标题，所以把正文 + 标签 + 分行都算进来。"""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        n = json.load(open(os.path.join(here, "narration.json"), encoding="utf-8"))
    except Exception:
        return ""
    parts = []
    for s in n.get("scenes", []):
        parts.append(str(s.get("text", "")))
        parts += [str(x) for x in (s.get("lines") or [])]
        st = s.get("stage") or {}
        parts += [str(v) for v in st.values() if isinstance(v, (str, int, float))]
    return " ".join(parts)


def _pick_theme():
    forced = (os.environ.get("VIDEO_THEME") or "").strip()
    if forced in THEMES:
        return forced
    txt = _theme_seed_text()
    sig = hashlib.md5(txt.encode("utf-8")).hexdigest()[:12] if txt else "empty"
    state = os.path.join(STATE_DIR, ".last_theme")
    prev_sig, prev_theme = "", ""
    try:
        bits = open(state, encoding="utf-8").read().strip().split(":")
        prev_sig, prev_theme = bits[0], (bits[1] if len(bits) > 1 else "")
    except Exception:
        pass
    if sig == prev_sig and prev_theme in THEMES:
        return prev_theme                     # 同一份脚本重渲（geocheck / 补渲）→ 皮不变
    want = "ink"
    for pat, th in TOPIC_HINTS:
        if re.search(pat, txt):
            want = th
            break
    if prev_theme in THEMES and want == prev_theme:
        want = THEME_ORDER[(THEME_ORDER.index(want) + 1) % len(THEME_ORDER)]
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        open(state, "w", encoding="utf-8").write("%s:%s" % (sig, want))
    except Exception:
        pass
    return want


THEME_NAME = _pick_theme()
THEME = THEMES[THEME_NAME]
config.background_color = THEME["bg"]

BG = THEME["bg"]
FG = THEME["fg"]
MUTED = THEME["muted"]
DIM = THEME["dim"]
PRIMARY = THEME["primary"]
ACCENT = THEME["accent"]
RED = THEME["red"]
GREEN = THEME["green"]
CORNER = THEME["corner"]            # 圆角：纸张小圆角、暖橙大圆角
FILLOP = THEME["fill"]              # 面板填充透明度
PERSON_FILL = THEME["person_fill"]
print("[theme] %s (%s)" % (THEME_NAME, THEME["name"]), file=sys.stderr)

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


def panel(w, h, color=None, fill=None, sw=3.5):
    color = color or PRIMARY
    r = RoundedRectangle(width=w, height=h, corner_radius=CORNER,
                         color=color, stroke_width=sw)
    r.set_fill(color, FILLOP if fill is None else fill)
    return r


def capsule(text, size=40, color=FG, edge=PRIMARY, fill=0.10, limit=12):
    """标签 + 刚好包住它的框。框宽由文字决定，所以框本身不传递信息、只做归类。"""
    lab = VGroup(*[T(l, size, color) for l in wrap(text, limit)]).arrange(
        DOWN, buff=0.16, aligned_edge=LEFT)
    fitw(lab, USABLE - 1.0)
    box = panel(lab.width + 0.9, lab.height + 0.75, edge, fill)
    box.move_to(lab.get_center())
    return VGroup(box, lab)


def person(label="", color=None, h=1.9):
    color = color or FG
    head = Circle(radius=0.36, color=color, stroke_width=4).set_fill(color, PERSON_FILL)
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


def disc(txt, color=None, r=0.42, size=34):
    color = color or ACCENT
    c = Circle(radius=r, color=color, stroke_width=4).set_fill(color, min(0.9, FILLOP * 1.6))
    return VGroup(c, T(txt, size, color).move_to(c.get_center()))


# --------------------------------------------------------------------------- #
# 质感层（v4）：整片共用的背景 = 底色 + 一层质感（真渐变的 PNG，不是几何近似）。
# 四套皮各一种质感：glow 中心柔光 / grid 工程网格 / rule 手记横线+装订红线 / vignette 暗角。
# --------------------------------------------------------------------------- #
def _hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def _bg_png():
    """按当前皮肤生成一张真渐变背景图（按皮肤名缓存）。

    为什么不用「同心圆 / 嵌套矩形」近似：那两种做法在成片里是**硬边阶梯**，
    肉眼一看就是廉价的边框滤镜（2026-10-12 拿成片验收时被这样判掉）。
    这里用 numpy 逐像素算真渐变，再交给 ImageMobject —— 零额外依赖（Pillow 是 manim 自带的）。
    """
    path = os.path.join(STATE_DIR, ".bg_%s.png" % THEME_NAME)
    if os.path.exists(path):
        return path
    try:
        from PIL import Image
    except Exception:
        print("[bg] 缺 Pillow，退化为纯色底", file=sys.stderr)
        return None
    W, H = 288, 512                      # 9:16；小图够用（会被拉伸铺满），生成毫秒级
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    nx, ny = (xx + 0.5) / W, (yy + 0.5) / H
    base, glow, acc = _hex_rgb(BG), _hex_rgb(THEME["glow"]), _hex_rgb(ACCENT)
    img = np.ones((H, W, 3)) * base

    t = THEME["texture"]
    if t == "glow":                      # 中心柔光：平方衰减，没有任何可见环带
        d = np.sqrt(((nx - 0.5) * 0.92) ** 2 + ((ny - 0.44) * 0.55) ** 2)
        k = (np.clip(1.0 - d / 0.60, 0.0, 1.0) ** 2.2)[..., None]
        img = img * (1 - 0.60 * k) + glow * (0.60 * k)
    elif t == "vignette":                # 暗角：边缘平滑压暗 + 一点暖光
        d = np.sqrt(((nx - 0.5) * 0.72) ** 2 + ((ny - 0.45) * 0.95) ** 2)
        k = (np.clip(d / 0.66, 0.0, 1.0) ** 1.9)[..., None]
        img = img * (1 - 0.66 * k)
        g = (np.clip(1.0 - d / 0.50, 0.0, 1.0) ** 2.0)[..., None]
        img = img + glow * 0.16 * g
    elif t == "grid":                    # 工程网格：1px 线 + 低透明度
        step = W * 0.56 / 9.0
        m = (((xx % step) < 1.2) | ((yy % step) < 1.2)).astype(float)[..., None]
        img = img * (1 - 0.26 * m) + glow * (0.26 * m)
    elif t == "rule":                    # 手记：横线 + 左侧装订红线
        step = H * 0.62 / 16.0
        m = ((yy % step) < 1.0).astype(float)[..., None]
        img = img * (1 - 0.14 * m) + glow * (0.14 * m)
        mx = int(round(0.1556 * W))
        img[:, mx:mx + 1, :] = img[:, mx:mx + 1, :] * 0.55 + acc * 0.45

    # 所有皮肤共用的轻微暗角：给画面一点纵深（很淡，不抢主体）
    dv = np.sqrt(((nx - 0.5) * 0.80) ** 2 + ((ny - 0.5) * 0.95) ** 2)
    img = img * (1 - 0.14 * (np.clip(dv / 0.72, 0.0, 1.0) ** 2.0))[..., None]

    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        Image.fromarray(np.clip(img, 0, 255).astype("uint8")).save(path)
    except Exception as exc:
        print("[bg] 写背景 PNG 失败：%s" % exc, file=sys.stderr)
        return None
    return path


def bg_layer():
    g = Group()          # 必须用 Group：VGroup 只收 VMobject，而 ImageMobject 不是
    base = Rectangle(width=config.frame_width * 1.8, height=config.frame_height * 1.8)
    base.set_stroke(width=0).set_fill(BG, 1)
    g.add(base)
    p = _bg_png()
    if p:
        img = ImageMobject(p)
        img.scale_to_fit_width(config.frame_width * 1.25)   # 留边：镜头拉到 1.10 也不会露底
        img.move_to(np.array([0.0, 0.0, 0.0]))
        g.add(img)
    return g


# --------------------------------------------------------------------------- #
# 时序引擎：把画面节拍对到配音念到那个词的那一刻
# --------------------------------------------------------------------------- #
SPECS, DURS = {}, {}


def _load():
    here = os.getcwd()
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


# --------------------------------------------------------------------------- #
# 镜头层（v4）：原先场景是普通 Scene —— 元素在静态画布上出现，没有摄影。
# 这里改成 MovingCameraScene + 「自动跟拍」：每一拍取该拍动画元件的包围盒中心，
# 把镜头推过去（同时极缓慢地推近）。不逐个改 13 种语法也能全场受益。
# 位移/缩放都夹在安全范围内，绝不会裁到内容（内容区 ±7.1，画幅 ±8）。
# --------------------------------------------------------------------------- #
CAM = (os.environ.get("VIDEO_CAMERA", "1") != "0")
SAFE_HW, SAFE_HH = USABLE / 2.0, 7.10   # 内容安全半宽/半高（设计区 ±4.05 × ±7.1）
CAM_START, CAM_S_MIN, CAM_S_MAX = 1.10, 0.92, 1.06
# 取景映射：占比大（整幅构图）→ 拉到 1.06 看全；占比小（一个细节）→ 推到 0.92 看清。
# 0.92 时可视半宽 4.14 > 安全半宽 4.05、半高 7.36 > 7.10 ⇒ 再近也不裁内容。
CAM_FILL_REF = 0.30                     # 占比到这个数就算「整幅」


def _beat_target(anims):
    """按「取景」算镜头：这一拍的元件在画幅里占多大 → 决定推近还是拉远、往哪挪。

    两条硬约束保证永不裁到内容：
      · 缩放夹在 [0.92, 1.06]
      · 平移上限随缩放自动收紧：余量 = 画幅半宽(4.5s) − 安全半宽(4.05)
        ⇒ 推得越近能挪的越少，推到 0.92 时几乎不能挪。
    """
    xs0, xs1, ys0, ys1 = [], [], [], []
    for a in anims:
        m = getattr(a, "mobject", None)
        if m is None:
            continue
        try:
            w_, h_ = float(m.width), float(m.height)
            if w_ * h_ <= 0.05:
                continue
            c = np.array(m.get_center(), dtype=float)
        except Exception:
            continue
        xs0.append(c[0] - w_ / 2.0); xs1.append(c[0] + w_ / 2.0)
        ys0.append(c[1] - h_ / 2.0); ys1.append(c[1] + h_ / 2.0)
    if not xs0:
        return None
    # 注：这里不能用 get_bounding_box() —— manim 0.19.2 上它是坏的
    # （内部 getattr(self,"bounding_box") 该属性不存在，必抛 AttributeError）。
    bx0, bx1, by0, by1 = min(xs0), max(xs1), min(ys0), max(ys1)
    bw, bh = bx1 - bx0, by1 - by0
    fill = max(bw / 9.0, bh / 16.0)                    # 这一拍占了画幅多大
    r = min(1.0, fill / CAM_FILL_REF)
    s = (CAM_S_MAX - (CAM_S_MAX - CAM_S_MIN) * (1.0 - r) ** 0.7)
    s = max(CAM_S_MIN, min(CAM_S_MAX, s))
    ax = max(0.0, 4.5 * s - SAFE_HW)
    ay = max(0.0, 8.0 * s - SAFE_HH)
    cx = max(-ax, min(ax, (bx0 + bx1) / 2.0))
    cy = max(-ay, min(ay, (by0 + by1) / 2.0))
    return np.array([cx, cy, 0.0]), s


def steps(self, spec, dur, total, items):
    """items: [(动画或动画元组, run_time)]，按 cues() 算出的时刻逐个播，末尾补静止到 total。"""
    flat = []
    for it in items:
        a, rt = it
        if not isinstance(a, (tuple, list)):
            a = (a,)
        flat.append((tuple(a), rt))
    ts = cues(spec, dur, len(flat))
    cam = getattr(self, "camera", None)
    frame = getattr(cam, "frame", None) if CAM else None
    t = 0.0
    for i, (anims, rt) in enumerate(flat):
        if ts[i] - t > 0.04:
            self.wait(ts[i] - t)
            t = ts[i]
        if os.environ.get("VIDEO_CAM_DEBUG") == "1":
            names = []
            for _a in anims:
                _m = getattr(_a, "mobject", None)
                names.append("%s(%.2fx%.2f)" % (type(_a).__name__,
                                                getattr(_m, "width", -1), getattr(_m, "height", -1)))
            print("[cam-dbg] i=%d frame=%s n=%d tg=%s :: %s"
                  % (i, frame is not None, len(anims), _beat_target(anims) is not None, names),
                  file=sys.stderr)
        if frame is not None:
            tg = _beat_target(anims)
            if tg is not None:
                center, want = tg
                cur = max(1e-6, float(frame.height) / 16.0)
                if os.environ.get("VIDEO_CAM_DEBUG") == "1":
                    print("[cam] beat=%d cur=%.3f want=%.3f ratio=%.3f center=(%.2f, %.2f)"
                          % (i, cur, want, want / cur, center[0], center[1]), file=sys.stderr)
                anims = anims + (frame.animate.move_to(center).scale(want / cur),)
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
