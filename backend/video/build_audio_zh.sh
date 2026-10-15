#!/usr/bin/env bash
# 中文配音 + 时长表。输入 narration.json（{"scenes":[{"id","text"}]}），
# 输出 audio/<id>.mp3 与 durations.json（每段 ffprobe 实测秒数，供 Manim 补时）。
# 用法: bash build_audio_zh.sh [narration.json]
# 覆盖: VOICE / VOICE_POOL / RATE / EDGE_TTS / SAY_VOICE / SAY_RATE / MIN_DUR
# 零 API 成本：edge-tts 是本机免费通道（hermes venv 里的可执行文件），不需要 key；
# 它挂掉时退回 macOS 自带的 `say`（同样本地、零成本、无词级时刻）。
#
# 2026-10-14 修：edge-tts 端点返回 403（WSServerHandshakeError）后，本脚本**静默产出
# 0 字节的 mp3 且 rc=0**，一路把 durations.json 变成 []，stitch 于是用**旧的**
# video_only.mp4/audio_all.wav 重新封装 → final.mp4 的 mtime 变新、内容却是昨天那条片子。
#
# 2026-10-15 修三处（pm 反证发现，brain 修）：
#  ① `$sid（` —— bash 3.2 把全角括号吃进变量名 ⇒ set -u 下致命退出。改用 ${sid}。
#  ② 写序 —— durations.json 挪到闸门**之后**落盘，失败时上一份有效时长表保持不动。
#  ③ say 兜底的判据原来只判「非空」—— 不存在的音色也能产出 1612 B / 0.0116 s 的
#     「成功」文件。现统一加 MIN_DUR 下限（默认 0.3s）。
#
# 2026-10-15 晚 重构（brain）：**全片单通道** + **音色池**。
#  ④ 原来兜底是**逐段**的（哪段失败哪段退 say）⇒ 限流从中间开始时，会产出一支
#     **混着两个音色的片子**。现在：先预探 edge，任一段失败就**整支重来**换 say。
#     宁可多花一次渲染，不许成片里两个嗓子。
#  ⑤ VOICE_POOL="a,b,c" 时按**日期**确定性挑一支（同一天重跑同一支，便于复盘）；
#     挑中哪支、走的哪条通道写进 tts_used.json。
#
# ⚠️ 本文件是**模具**（各项目 fork 的源头）。在此修 bug **不会**传播到已 fork 的副本 ——
#    改完必须 `grep -rl build_audio_zh.sh /Users/xicheng` 找出全部副本逐一同步，
#    否则旧副本照样静默发旧片。全机共 7 份（2026-10-15 pm 实测）。
set -uo pipefail
cd "${PROJECT_DIR:-$PWD}"   # 在项目目录里跑（不要 cd 到脚本自己的位置，产物会落错地方）
EDGE="${EDGE_TTS:-$HOME/.hermes/hermes-agent/venv/bin/edge-tts}"
VOICE="${VOICE:-zh-CN-YunyangNeural}"    # 男声新闻腔；女声 zh-CN-XiaoxiaoNeural
VOICE_POOL="${VOICE_POOL:-}"             # 逗号分隔的音色池；设了则覆盖 VOICE（按日期挑）
RATE="${RATE:-+0%}"                      # 标准语速；要提速先按字数校准（+8% 时 209 字≈42.5s，可能掉出时长规格）
SAY_VOICE="${SAY_VOICE:-Tingting}"       # macOS 本机中文声音（`say -v '?'` 里列出）
SAY_RATE="${SAY_RATE:-215}"              # 实测 Tingting r≈215 ≒ 5.3 字/秒，对齐 Yunyang +0%
MIN_DUR="${MIN_DUR:-0.3}"                # 单段配音最短合法时长（秒）：防「非空但极短」的假成功
PROBE_TEXT="${PROBE_TEXT:-配音通道探测。}"  # 预探用的短句（可用 env 覆盖）
NARR="${1:-narration.json}"
mkdir -p audio

# ---- 选音色：有池就按日期确定性挑一支（同一天重跑 = 同一支，便于复盘） ----
if [ -n "$VOICE_POOL" ]; then
  VOICE=$(python3 - "$VOICE_POOL" "$(date +%Y-%m-%d)" <<'PY'
import hashlib, sys
pool = [v.strip() for v in sys.argv[1].split(",") if v.strip()]
day = sys.argv[2]
print(pool[int(hashlib.sha256(day.encode()).hexdigest(), 16) % len(pool)])
PY
)
fi
if [ -z "$VOICE" ]; then
  echo "❌ 音色池为空且 VOICE 未设" >&2
  exit 1
fi

python3 - "$NARR" <<'PY' > /tmp/vid_scene_texts.tsv
import json, sys
for s in json.load(open(sys.argv[1]))["scenes"]:
    print(f'{s["id"]}\t{s["text"]}')
PY

# duraff <file>：打印时长（秒），取不到给 0
duraff() {
  ffprobe -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null || echo 0
}

# legal <file>：非空 且 时长 ≥ MIN_DUR
legal() {
  [ -s "$1" ] || return 1
  awk -v d="$(duraff "$1")" -v m="$MIN_DUR" 'BEGIN{exit !(d+0 >= m+0)}'
}

# tts_edge <id> <text>：只走 edge-tts，不做任何兜底
tts_edge() {
  local sid="$1" text="$2"
  [ -x "$EDGE" ] || return 1
  rm -f "audio/${sid}.mp3" "audio/${sid}.vtt"
  "$EDGE" --voice "$VOICE" --rate="$RATE" --text "$text" \
      --write-media "audio/${sid}.mp3" --write-subtitles "audio/${sid}.vtt" >/dev/null 2>&1
  legal "audio/${sid}.mp3" || { rm -f "audio/${sid}.mp3" "audio/${sid}.vtt"; return 1; }
  return 0
}

# tts_say <id> <text>：只走 macOS say，不做任何兜底（无词级时刻 → 调用方按字数比例）
tts_say() {
  local sid="$1" text="$2"
  rm -f "audio/${sid}.mp3" "audio/${sid}.vtt"
  say -v "$SAY_VOICE" -r "$SAY_RATE" -o "audio/${sid}.aiff" "$text" >/dev/null 2>&1
  if [ -s "audio/${sid}.aiff" ]; then
    ffmpeg -y -v error -i "audio/${sid}.aiff" -ar 44100 -ac 2 -b:a 160k "audio/${sid}.mp3" >/dev/null 2>&1
    rm -f "audio/${sid}.aiff"
  fi
  legal "audio/${sid}.mp3" || { rm -f "audio/${sid}.mp3"; return 1; }
  return 0
}

# probe <channel>：单次短句预探，判断这条通道当前能不能用
probe() {
  local ch="$1"
  if [ "$ch" = "edge" ]; then
    [ -x "$EDGE" ] || return 1
    rm -f audio/_probe.mp3
    "$EDGE" --voice "$VOICE" --rate="$RATE" --text "$PROBE_TEXT" --write-media audio/_probe.mp3 >/dev/null 2>&1
    legal audio/_probe.mp3
  else
    [ -n "$SAY_VOICE" ]
  fi
}

# render_all <channel>：整片用同一条通道渲染。任一段失败 → 立刻返回 1（不留半成品）
render_all() {
  local ch="$1" sid text dur
  : > durations.jsonl
  while IFS=$'\t' read -r sid text; do
    [ -z "$sid" ] && continue
    if [ "$ch" = "edge" ]; then
      tts_edge "$sid" "$text" || { echo "  [tts] edge 在 ${sid} 段失败" >&2; return 1; }
    else
      tts_say "$sid" "$text" || { echo "  [tts] say 在 ${sid} 段失败" >&2; return 1; }
    fi
    dur=$(duraff "audio/${sid}.mp3")
    python3 - "$sid" "$dur" "audio/${sid}.vtt" <<'PY' >> durations.jsonl
import json, re, sys
sid, dur, vtt = sys.argv[1], sys.argv[2], sys.argv[3]
words = []
try:
    blocks = open(vtt, encoding="utf-8").read().split("\n\n")
    pat = re.compile(r"(\d+):(\d+):([\d.]+)\s*-->")
    for b in blocks:
        m = pat.search(b)
        if not m:
            continue
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        lines = [x for x in b.splitlines() if x.strip()
                 and "-->" not in x and not x.strip().startswith(("WEBVTT", "NOTE"))]
        if lines:
            words.append([lines[-1].strip(), round(t, 3)])
except Exception:
    pass
print(json.dumps({"id": sid, "mp3": f"audio/{sid}.mp3", "dur": float(dur),
                  "words": words}, ensure_ascii=False))
PY
    echo "$sid  ${dur}s"
  done < /tmp/vid_scene_texts.tsv
  return 0
}

echo "[tts] 音色=${VOICE}${VOICE_POOL:+（池 ${VOICE_POOL}）} 语速=${RATE}" >&2

# ---- 先预探，再整片渲染；edge 中途失败就整支重来换 say（绝不留混音色） ----
CH="edge"; probe edge || CH="say"
[ "$CH" = "say" ] && echo "  [tts] edge 预探失败（403/限流）→ 整片改用本机 say(${SAY_VOICE} r=${SAY_RATE})" >&2

if ! render_all "$CH"; then
  if [ "$CH" = "edge" ]; then
    echo "  [tts] edge 中途失败 → 整支重来，全部改用 say（避免混音色）" >&2
    CH="say"
    render_all "$CH" || { echo "❌ 配音失败：两条通道都产出不了合法音频" >&2; exit 1; }
  else
    echo "❌ 配音失败：say 通道也产出不了合法音频" >&2
    exit 1
  fi
fi

# 记录本次实际用的是什么（复盘靠它）
python3 - "$VOICE" "$CH" "$RATE" "$VOICE_POOL" <<'PY'
import json, sys, datetime
json.dump({"date": datetime.date.today().isoformat(), "voice": sys.argv[1],
           "channel": sys.argv[2], "rate": sys.argv[3], "pool": sys.argv[4] or None},
          open("tts_used.json", "w"), ensure_ascii=False, indent=1)
PY

# 汇总：只打印，不落盘 —— durations.json 的落盘挪到闸门之后
python3 -c "
import json
rows=[json.loads(l) for l in open('durations.jsonl')]
print('total', round(sum(r['dur'] for r in rows),1), 's',
      '| 带词级时刻', sum(1 for r in rows if r.get('words')), '/', len(rows))"

# 闸门：任何一段配音为空/零时长都不许往下走（今天的废片就是从这里漏出去的）
n=$(python3 -c "
import json
rows=[json.loads(l) for l in open('durations.jsonl')]
print(sum(1 for r in rows if float(r.get('dur') or 0) <= 0))")
if [ "$n" -gt 0 ] || [ ! -s durations.jsonl ]; then
  echo "❌ 配音闸门：${n} 段时长为 0 —— 上一份 durations.json 保持不动，直接失败" >&2
  exit 1
fi

# 闸门通过后才落盘：失败时上一份有效时长表保持不动
python3 -c "
import json
rows=[json.loads(l) for l in open('durations.jsonl')]
json.dump(rows, open('durations.json','w'), ensure_ascii=False, indent=1)
print('durations.json 已写入', len(rows), '段')"
