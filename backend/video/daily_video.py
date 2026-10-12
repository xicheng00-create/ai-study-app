# 来源：brain workspace/daily-video，勿就地魔改，同步靠内容比对
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库每日一条 → 竖屏配音短视频（四级输出）。

用法:
    python3 daily_video.py <card.json> [--out-dir DIR]

card.json 结构（cron 的 agent 每天写一份）:
{
  "date": "2026-10-09",
  "concept": "低自尊与人际关系",
  "source": "concepts/心理学/低自尊与人际关系.md",
  "scenes": [
    {"id": "S1_Hook", "style": "title",  "kicker": "今天的场景",
     "text": "配音念的整句。", "lines": ["屏幕上第一行", "屏幕上第二行"]},
    ...
  ]
}

规则:
  - id 是渲染文件名与装配顺序的键，**必须唯一且稳定**
  - style 决定这一场用哪类图形。v3 图形语法（推荐，L2）：
      situation 两个人的处境 / crossout 先画错答案再打叉 / transform 换了性质 /
      chain 机制一环一拍（点穿过链条）/ axis 程度刻度 / threshold 阈值 /
      loop 循环 / balance 天平 / stack 积累 / nodes 真关联 / steps 可操作 /
      close 收束 / source 出处
    旧 style（title/body/action/hook/map/flow/contrast/checklist）仍接受，
    但会降级成兜底文字场 —— v2 的「方框+箭头」是 L1，已弃用。
  - text 是配音（edge-tts），stage 是画面（图形语法的字段，见 script.py 的 k_* 函数）；
    画面文字只放**标签**，不是配音原句 —— 二者逐字重叠就是字幕墙。
  - **画面是否在承担逻辑**的判据：把 stage 里的文字全擦掉（BLANK_TEXT=1），
    还能不能看出这一步在发生什么变化。看不出就是打字幕。
  - 成功的最后一行输出是 `MEDIA:<mp4 绝对路径>`，可直接被消息层当作附件发出
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = HERE
PROJ = os.path.abspath(PROJ)
ROOT = os.path.dirname(os.path.dirname(HERE))   # 仓库根（由脚本位置算，不受 --project 影响）
# 皮肤状态（.last_theme）与背景质感 PNG 的持久目录；见 video_base.STATE_DIR 注释。
STATE_DIR = os.environ.get("VIDEO_STATE_DIR") or os.path.join(ROOT, "instance", "video_state")
MANIM = os.path.expanduser(
    # 目录名里的 312 是笔误：venv 实际建在 Python 3.14.7 上（manim 0.19.2）。
    # 不要重命名目录——venv 的 console script 里 shebang 写死了这个绝对路径。
    "~/.hermes/profiles/brain/workspace/venvs/manim312/bin/manim")
STYLES = {"title", "body", "action", "source",
          # v2 视觉场景库（结构图，不是字幕）：hook 开场 / map 关系图 / flow 因果链 /
          # contrast 左右对照 / checklist 勾选清单
          "hook", "map", "flow", "contrast", "checklist",
          # v3 图形语法（L2：图形自带量/方向/状态，动画演示推理）——
          # 每场的 style 就是它用哪类图形，选型见 visual playbook §2
          "situation",   # H 钩子：两个人的处境 + 中间跨不过去的距离
          "crossout",    # M 误解：先画想当然的答案，再打叉
          "transform",   # 前后对照：同一个东西换了性质（变形动作＝纠正）
          "chain",       # K 机制：一环一拍，点沿线穿过、节点被点亮
          "axis",        # 程度/量值：轴 + 会滑动的标记，走过的量长出来
          "threshold",   # 阈值：量一直涨，越过细虚线才质变
          "loop",        # 循环：首尾相接，点不停转
          "balance",     # 此消彼长：天平真的倾斜
          "stack",       # 积累：一格一格加出来
          "nodes",       # 关系：中心 + 轨道上的真邻居（拿不到真关联就别用）
          "steps",       # 可操作：一步一拍，最后打勾
          "close",       # 收束：回到钩子的画面，把距离连上
          # v5 开场器变体（开场不必再是「两个人 + 一条线 + 一个叉」）
          "dayband",     # 一天的时间条被别的事填满，要做的那格一直空着
          "object",      # 物件特写：手机/床/日历…自己演，时间在跳
          "dialogue",    # 人不出场，只有自我对话气泡
          "text"}        # 兜底（旧卡片；新卡片不用）


def die(msg):
    print("FAIL: " + msg, file=sys.stderr)
    sys.exit(1)


def run(cmd, cwd=None, env=None, label="", allow_fail=False):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    dt = time.time() - t0
    print("  [%s] %.1fs rc=%d" % (label or cmd[0], dt, p.returncode), flush=True)
    if allow_fail:
        return p.stdout
    if p.returncode != 0:
        sys.stderr.write(p.stdout[-3000:] + "\n" + p.stderr[-3000:] + "\n")
        die("%s 失败" % (label or cmd[0]))
    return p.stdout


def wrap(text, limit=13):
    """没给 lines 时按标点折行。"""
    parts = [s for s in re.split(r"(?<=[。，；！？、—])", text) if s.strip()]
    lines, cur = [], ""
    for part in parts:
        if len(cur) + len(part) > limit and cur:
            lines.append(cur)
            cur = part
        else:
            cur += part
    if cur:
        lines.append(cur)
    return [ln.strip("，。") for ln in lines if ln.strip("，。")] or [text]


def check_style_drift():
    """在系统 Python 下按文本核对渲染器 KINDS 与本档 STYLES。"""
    path = os.path.join(PROJ, "script.py")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as exc:
        die("无法读取渲染器 script.py：%s" % exc)
    m = re.search(r"^KINDS\s*=\s*\{", text, re.M)
    if not m:
        die("script.py 缺少可解析的 KINDS 注册")
    depth, i = 0, m.end() - 1
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        die("script.py 的 KINDS 注册未闭合")
    body = text[m.end():i]
    keys = set(re.findall(r"[\"']([A-Za-z_]+)[\"']\s*:", body))
    if not keys:
        die("script.py 的 KINDS 没有可解析的键")
    missing = keys - STYLES
    if missing:
        die("script.py 的 KINDS 注册了 %s，但本文件 STYLES 白名单里没有"
            % sorted(missing))
    gone = STYLES - keys
    if gone:
        print("[warn] STYLES 里有渲染器已不存在的 style：%s" % sorted(gone),
              file=sys.stderr)


def check_duration(proj, dur):
    """最终成片须落在配音总长的 0.85–1.6 倍。"""
    durations = os.path.join(proj, "durations.json")
    try:
        rows = json.load(open(durations, encoding="utf-8"))
        want = sum(float(row["dur"]) for row in rows)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        die("无法读取有效的配音时长表：%s" % exc)
    if want <= 0:
        die("配音总时长必须大于 0")
    try:
        got = float(dur)
    except (TypeError, ValueError):
        die("无法读取 final.mp4 的 ffprobe 时长：%r" % dur)
    if not 0.85 * want <= got <= 1.6 * want:
        die("成片时长异常：%.1fs，但配音合计 %.1fs（疑似截断或空片）" % (got, want))
    return want


def seed_project(proj):
    """渲染工作目录必须自带 script.py + 两个 sh。

    按**内容**从规范目录同步，而不是「缺了才拷」：否则规范目录里修好的渲染器
    永远传不到已经存在的项目目录，成片会静默地用旧渲染器出片（2026-10-08 踩过 ——
    新场景库写好了，DanKoe 那条还是按旧字幕版渲染）。
    这几个文件是派生物、不允许按项目各自魔改，所以直接覆盖是安全的。
    """
    os.makedirs(proj, exist_ok=True)
    for fn in ("script.py", "video_base.py", "video_scenes_a.py", "video_scenes_b.py", "build_audio_zh.sh", "stitch_av.sh"):
        src = os.path.join(PROJ, fn)
        dst = os.path.join(proj, fn)
        if not os.path.exists(src):
            continue
        same = os.path.exists(dst) and open(src, "rb").read() == open(dst, "rb").read()
        if not same:
            shutil.copyfile(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--project", default=None,
                    help="渲染工作目录（默认 workspace/daily-video）。"
                         "给不同调用方各自的目录，才不会互相覆盖 narration.json/audio/。")
    ap.add_argument("--name-prefix", default="daily",
                    help="产物文件名前缀，默认 daily")
    args = ap.parse_args()
    if args.out_dir is None:
        args.out_dir = os.path.join(PROJ, "out")

    with open(args.card, encoding="utf-8") as f:
        card = json.load(f)
    check_style_drift()
    scenes = card.get("scenes") or []
    if not scenes:
        die("card.json 里没有 scenes")

    ids, seen = [], set()
    for s in scenes:
        sid = s.get("id")
        if not sid:
            die("每个 scene 必须有 id")
        if sid in seen:
            die("scene id 重复: %s" % sid)
        seen.add(sid)
        s["id"] = re.sub(r"[^0-9A-Za-z_]", "_", sid)
        s.setdefault("style", "body")
        if s["style"] not in STYLES:
            die("未知 style: %s" % s["style"])
        if not s.get("text"):
            die("scene %s 缺 text（配音）" % s["id"])
        if not s.get("lines"):
            s["lines"] = wrap(s["text"])
        ids.append(s["id"])

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die("缺 %s" % tool)
    if not os.path.exists(MANIM):
        die("缺 manim: %s" % MANIM)

    os.makedirs(PROJ, exist_ok=True)
    proj = os.path.abspath(args.project or PROJ)
    seed_project(proj)

    with open(os.path.join(proj, "narration.json"), "w", encoding="utf-8") as f:
        json.dump({"scenes": scenes}, f, ensure_ascii=False, indent=1)
    print("narration.json 已写入 (%d 场)" % len(scenes), flush=True)

    print("① 配音 …", flush=True)
    run(["bash", "build_audio_zh.sh"], cwd=proj, label="edge-tts")

    print("② 渲染 …", flush=True)
    # 渲染跑在一次性 project 目录里，皮肤状态必须外置到持久目录，否则「不撞脸」静默失效。
    os.makedirs(STATE_DIR, exist_ok=True)
    run([MANIM, "-qm", "script.py"] + ids, cwd=proj, label="manim",
        env=dict(os.environ, VIDEO_STATE_DIR=STATE_DIR))

    print("③ 拼接 …", flush=True)
    vids = []
    base = os.path.join(proj, "media", "videos", "script")
    for root, _dirs, files in os.walk(base):
        if "partial_movie_files" in root:
            continue
        for fn in files:
            if fn == ids[0] + ".mp4":
                vids.append(root)
    if not vids:
        die("找不到渲染产物目录")
    vdir = os.path.relpath(vids[0], proj)
    env = dict(os.environ, VIDEO_DIR=vdir)
    final = os.path.join(proj, "final.mp4")
    before = os.path.getmtime(final) if os.path.exists(final) else 0
    # stitch_av.sh 末尾是 ffmpeg 探测（无输出文件 → 必然 exit 1），别信它的返回码；
    # 以「final.mp4 是否新鲜」为准。
    run(["bash", "stitch_av.sh"], cwd=proj, env=env, label="ffmpeg", allow_fail=True)

    if not os.path.exists(final) or os.path.getmtime(final) <= before:
        die("stitch 没产出新的 final.mp4")
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", final],
        capture_output=True, text=True).stdout.strip()

    # 时长体检：见 check_duration() 注释 ——「文件变新」不等于「不是废片」。
    check_duration(proj, dur)

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = card.get("date") or time.strftime("%Y-%m-%d")
    stem = "%s-%s" % (args.name_prefix, stamp)
    out = os.path.join(args.out_dir, stem + ".mp4")
    # 同一天可能跑多次（人工验证 / 重跑）。直接覆盖会让上一次发出去的附件指向新内容，
    # 所以同日再跑就加序号。
    n = 2
    while os.path.exists(out):
        out = os.path.join(args.out_dir, "%s-%d.mp4" % (stem, n))
        n += 1
    shutil.copyfile(final, out)
    print("成片 %ss → %s" % (round(float(dur), 1) if dur else "?", out), flush=True)
    print("MEDIA:" + out)


if __name__ == "__main__":
    main()
