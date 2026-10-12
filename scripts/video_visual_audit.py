#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""讲解视频「视觉层」机械断言（REQ-VID-030~033）。

为什么要有这个脚本：皮肤/镜头/开场器这些口径都是**看不出来就静默失效**的东西
（写死常数不报错、皮肤选错不报错、开场器退回 situation 也不报错）。所以每条口径
都配一条能真红的断言，而不是只写在 Design-Spec 里。

用法：
    python3 scripts/video_visual_audit.py          # 全绿才算过
    python3 scripts/video_visual_audit.py --red    # 反证：故意短路「不撞脸」→ R4 必须真红

退出码：0 = 全部通过；1 = 有断言失败（打印是哪一条）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(ROOT, "backend", "video")
MANIM = os.path.expanduser("~/.hermes/profiles/brain/workspace/venvs/manim312/bin/manim")
SEED = ("script.py", "video_base.py", "video_scenes_a.py", "video_scenes_b.py")

NAR_A = {"scenes": [{"id": "s1", "style": "object", "text": "手机屏幕上的时间从二十三点四十一跳到四十二。",
                     "stage": {"caption": "屏幕上的时间", "clock": "23:41", "clock2": "23:42", "task": "那件事"}}]}
NAR_B = {"scenes": [{"id": "s1", "style": "dayband", "text": "一天二十四格全被别的事填满了。",
                     "stage": {"caption": "一天被填满了", "fill": "刷手机", "empty": "那件事"}}]}

fails = []
total = 0


def _grp(pat, text, grp=0):
    m = re.search(pat, text, re.S | re.M)
    return m.group(grp) if m else ""


def check(name, ok, detail=""):
    global total
    total += 1
    print("%-46s %s%s" % (name, "PASS" if ok else "FAIL", ("  " + detail) if detail else ""))
    if not ok:
        fails.append(name)
    return ok


def seed(proj, nar):
    os.makedirs(proj, exist_ok=True)
    for f in SEED:
        shutil.copy2(os.path.join(VIDEO, f), os.path.join(proj, f))
    with open(os.path.join(proj, "narration.json"), "w", encoding="utf-8") as fh:
        json.dump(nar, fh, ensure_ascii=False)


def render(proj, state, scene, extra_env=None, red=False):
    env = dict(os.environ, VIDEO_STATE_DIR=state)
    env.update(extra_env or {})
    env.pop("VIDEO_THEME", None)
    if red:
        env["VIDEO_THEME"] = "ink"          # 反证：把皮肤钉死 → 「不撞脸」必然失效
    p = subprocess.run([MANIM, "-ql", "--disable_caching", "-v", "ERROR", "script.py", scene],
                       cwd=proj, env=env, capture_output=True, text=True, timeout=600)
    out = (p.stdout or "") + (p.stderr or "")
    theme = re.search(r"\[theme\] (\w+)", out)
    cams = [float(x) for x in re.findall(r"\[cam\] beat=\d+ cur=[\d.]+ want=([\d.]+)", out)]
    return p.returncode, (theme.group(1) if theme else None), cams, out


def _run_gate_probe(name, code):
    """在临时副本真实执行闸门，并返回原始输出与退出码。"""
    p = subprocess.run([sys.executable, "-c", code], cwd=VIDEO,
                       capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    check(name, p.returncode != 0, "rc=%d %s" % (p.returncode, out.strip()[-180:]))
    return p.returncode, out


def gate_probes():
    """真实坏构建：删 STYLES 键、分别以空片/单拍时长触发 die。"""
    style_code = r'''
import daily_video as d
from unittest.mock import patch
with patch.object(d, "STYLES", set(d.STYLES) - {"dialogue"}):
    d.check_style_drift()
'''
    evidence = []
    rc, out = _run_gate_probe("R7 闸门 RED：删除 STYLES 键打印缺失", style_code)
    evidence.append("[delete STYLES dialogue] exit=%d\n%s" % (rc, out))
    check("R7 闸门输出包含缺失 style", rc != 0 and "dialogue" in out and "STYLES" in out)
    with tempfile.TemporaryDirectory(prefix="video-gate-") as tmp:
        with open(os.path.join(tmp, "durations.json"), "w", encoding="utf-8") as fh:
            json.dump([{"id": "a", "dur": 10.0}, {"id": "b", "dur": 20.0}], fh)
        for label, value in (("空片", "0"), ("只拼第一拍", "10")):
            code = "import daily_video as d; d.check_duration(%r, %s)" % (tmp, value)
            rc, out = _run_gate_probe("R8 闸门 RED：%s" % label, code)
            evidence.append("[%s] exit=%d\n%s" % (label, rc, out))
            check("R8 闸门输出包含时长异常（%s）" % label,
                  rc != 0 and "成片时长异常" in out)
    os.makedirs(os.path.join(ROOT, "docs", "audit", "video"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "audit", "video", "REQ-VID-V5-GATES-RED.txt"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(evidence) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", action="store_true", help="反证模式：R4 必须失败")
    a = ap.parse_args()

    vb = open(os.path.join(VIDEO, "video_base.py"), encoding="utf-8").read()
    sc = open(os.path.join(VIDEO, "script.py"), encoding="utf-8").read()
    di = open(os.path.join(VIDEO, "director.py"), encoding="utf-8").read()
    dv = open(os.path.join(VIDEO, "daily_video.py"), encoding="utf-8").read()

    # R1 皮肤层与镜头层在册
    check("R1 皮肤层在册（THEMES/_pick_theme/bg_layer）",
          all(k in vb for k in ("THEMES = {", "def _pick_theme", "def bg_layer", "def _bg_png")))
    check("R1 镜头层在册（MovingCameraScene + _beat_target）",
          "MovingCameraScene" in sc and "def _beat_target" in vb and "bg_layer()" in sc)
    # R2 开场器双侧注册
    check("R2 KINDS 注册三开场器",
          all(k in sc for k in ('"dayband"', '"object"', '"dialogue"')))
    check("R2 director V3 白名单含三开场器（防 repair 删拍）",
          all(k in di.split("PROMPT =")[0] for k in ('"dayband"', '"object"', '"dialogue"')))

    # R7 第 4 个白名单：daily_video.STYLES 是渲染前 preflight 的唯一名单，
    # 它跟 KINDS 漂移 = 出片那一刻 die、整条视频退化成纯文字推送（2026-10-12 实测）。
    styles = set(re.findall(r'"([A-Za-z_]+)"', _grp(r"^STYLES = \{.*?\n\n", dv)))
    kinds = set(re.findall(r'"([A-Za-z_]+)"\s*:', _grp(r"^KINDS\s*=\s*\{(.*?)\n\}", sc, 1)))
    check("R7 STYLES ⊇ KINDS（第 4 个白名单不漂移）",
          kinds <= styles and all(k in styles for k in ("dayband", "object", "dialogue")),
          "缺 %s" % sorted(kinds - styles))
    check("R7 渲染前真跑漂移校验（check_style_drift）",
          "def check_style_drift" in dv and "check_style_drift()" in dv.split("def main")[1])
    check("R8 成片时长体检在册（0.85–1.6 × 配音之和）",
          "def check_duration" in dv and "0.85 * want <= got <= 1.6 * want" in dv
          and "check_duration(proj, dur)" in dv)

    gate_probes()

    tmp = tempfile.mkdtemp(prefix="video-visual-audit-")
    try:
        pa, pb = os.path.join(tmp, "a"), os.path.join(tmp, "b")
        seed(pa, NAR_A)
        seed(pb, NAR_B)
        sa = os.path.join(tmp, "state")     # 同一状态目录 = 连续两集的真实情形（皮肤历史共享）

        rc1, th1, _, _ = render(pa, sa, "s1", red=a.red)
        rc2, th2, _, _ = render(pa, sa, "s1", red=a.red)
        rc3, th3, cams, out3 = render(pb, sa, "s1", {"VIDEO_CAM_DEBUG": "1"}, red=a.red)

        # R3 同稿重渲稳定（geocheck / 补渲不换皮）
        check("R3 同稿重渲皮肤稳定", rc1 == 0 and th1 == th2, "%s / %s" % (th1, th2))
        # R4 换稿不撞脸（上一集皮肤相同则顺延）
        check("R4 换一份稿子皮肤不重复", th3 is not None and th3 != th1, "%s → %s" % (th1, th3))
        # R5 镜头真在动，且夹在 [0.92, 1.06]
        inrange = bool(cams) and all(0.92 <= c <= 1.06 for c in cams)
        check("R5 镜头推拉（want∈[0.92,1.06] 且至少两拍不同）",
              rc3 == 0 and inrange and len(set(cams)) >= 2, "want=%s" % cams)

        # R6 开场器历史注入 prompt
        cards = os.path.join(tmp, "cards")
        os.makedirs(cards, exist_ok=True)
        for n, sty in (("2026-10-10-a.json", "dayband"), ("2026-10-11-b.json", "dialogue")):
            with open(os.path.join(cards, n), "w", encoding="utf-8") as fh:
                json.dump({"date": n[:10], "scenes": [{"style": sty}]}, fh, ensure_ascii=False)
        sys.path.insert(0, VIDEO)
        os.environ["VIDEO_CARDS_DIR"] = cards
        import director as D            # noqa: E402
        rec = D.recent_openers(7)
        prompt = D.PROMPT % {"date": "2026-10-12", "title": "t", "source": "s", "page": "p",
                             "recent": "\n".join("- %s → %s" % (d, s) for d, s in rec),
                             "neighbours": "n"}
        check("R6 recent_openers 读到历史", rec == [("2026-10-10", "dayband"), ("2026-10-11", "dialogue")], str(rec))
        check("R6 prompt 注入「不许重复」段", "开场器轮换" in prompt and "dayband" in prompt and "不许再选" in prompt)

        if a.red:
            # 反证模式 1：R7 判据必须能识别漂移（塞一个假 style，期望 FAIL）
            check("R7 反证：假 style 能被判据抓住（此项应 FAIL）",
                  (kinds | {"zz_fake_style"}) <= styles, "假 style 被漏过了")
            # 反证模式 2：R4 应该失败（皮肤被钉死）→ 若 R4 仍 PASS，说明断言是假的
            if "R4 换一份稿子皮肤不重复" not in fails:
                print("\n反证失败：皮肤钉死后 R4 仍然 PASS —— 该断言不可证伪")
                return 1
            print("\n反证成功：皮肤钉死后 R4 真红（该断言可证伪）")
            return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d 条断言失败：%s" % (len(fails), fails) if fails else "\n全部断言通过（%d 条）" % total)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
