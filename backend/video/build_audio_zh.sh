#!/usr/bin/env bash
# 中文配音 + 时长表。输入 narration.json（{"scenes":[{"id","text"}]}），
# 输出 audio/<id>.mp3 与 durations.json（每段 ffprobe 实测秒数，供 Manim 补时）。
# 用法: bash build_audio_zh.sh [narration.json]   覆盖: VOICE / RATE / EDGE_TTS / SAY_VOICE / SAY_RATE
# ⚠️ 本文件是**模具**（各项目 fork 的源头）。在此修 bug 不会传播到已 fork 的副本——
#    改完必须 `grep -rl build_audio_zh.sh` 找出所有副本逐一同步，否则旧副本照样静默发旧片。
# 零 API 成本：edge-tts 是本机免费通道（hermes venv 里的可执行文件），不需要 key；
# 它挂掉时退回 macOS 自带的 `say`（同样本地、零成本、无词级时刻）。
#
# 2026-10-14 修：edge-tts 端点返回 403（WSServerHandshakeError）后，本脚本**静默产出
# 0 字节的 mp3 且 rc=0**，一路把 durations.json 变成 []，stitch 于是用**旧的**
# video_only.mp4/audio_all.wav 重新封装 → final.mp4 的 mtime 变新、内容却是昨天那条片子。
# 现在每次配音都断言产物非空，空了就退回 say；两条路都不行就 exit 1（宁可失败，不许静默）。
set -uo pipefail
cd "${PROJECT_DIR:-$PWD}"   # 在项目目录里跑（不要 cd 到脚本自己的位置，产物会落错地方）
EDGE="${EDGE_TTS:-$HOME/.hermes/hermes-agent/venv/bin/edge-tts}"
VOICE="${VOICE:-zh-CN-YunyangNeural}"   # 男声新闻腔；女声 zh-CN-XiaoxiaoNeural
RATE="${RATE:-+0%}"                     # 标准语速；要提速先按字数校准（+8% 时 209 字≈42.5s，可能掉出时长规格）
SAY_VOICE="${SAY_VOICE:-Tingting}"      # macOS 本机中文声音（say -v '?' 里列出）
SAY_RATE="${SAY_RATE:-215}"             # 实测 Tingting r≈215 ≒ 5.3 字/秒，对齐 Yunyang +0%
NARR="${1:-narration.json}"
mkdir -p audio
python3 - "$NARR" <<'PY' > /tmp/vid_scene_texts.tsv
import json, sys
for s in json.load(open(sys.argv[1]))["scenes"]:
    print(f'{s["id"]}\t{s["text"]}')
PY

# tts_one <id> <text>：产出非空 audio/<id>.mp3 → 0；两条通道都失败 → 1
tts_one() {
  local sid="$1" text="$2"
  # ① edge-tts：带 --write-subtitles（WordBoundary 逐词时刻，画面节拍可对齐到词）
  if [ -x "$EDGE" ]; then
    "$EDGE" --voice "$VOICE" --rate="$RATE" --text "$text" \
        --write-media "audio/${sid}.mp3" --write-subtitles "audio/${sid}.vtt" >/dev/null 2>&1
    if [ -s "audio/${sid}.mp3" ]; then return 0; fi
  fi
  echo "  [tts] edge-tts 无输出（${sid}）→ 退回本机 say(${SAY_VOICE} r=${SAY_RATE})" >&2
  rm -f "audio/${sid}.vtt"                      # 空 vtt 会让词级解析拿到空表，不如不给
  say -v "$SAY_VOICE" -r "$SAY_RATE" -o "audio/${sid}.aiff" "$text" >/dev/null 2>&1
  if [ -s "audio/${sid}.aiff" ]; then
    ffmpeg -y -v error -i "audio/${sid}.aiff" -ar 44100 -ac 2 -b:a 160k \
        "audio/${sid}.mp3" >/dev/null 2>&1
    rm -f "audio/${sid}.aiff"
  fi
  [ -s "audio/${sid}.mp3" ]
}

: > durations.jsonl
fails=0
while IFS=$'\t' read -r sid text; do
  [ -z "$sid" ] && continue
  if ! tts_one "$sid" "$text"; then
    echo "❌ 配音失败：$sid（edge-tts 与 say 都没产出）" >&2
    fails=$((fails + 1))
    continue
  fi
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "audio/${sid}.mp3")
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
python3 -c "
import json
rows=[json.loads(l) for l in open('durations.jsonl')]
json.dump(rows, open('durations.json','w'), ensure_ascii=False, indent=1)
print('total', round(sum(r['dur'] for r in rows),1), 's',
      '| 带词级时刻', sum(1 for r in rows if r.get('words')), '/', len(rows))"

# 闸门：任何一段配音为空/零时长都不许往下走（今天那条废片就是从这里漏出去的）
n=$(python3 -c "
import json
rows=[json.loads(l) for l in open('durations.jsonl')]
print(sum(1 for r in rows if float(r.get('dur') or 0) <= 0))")
if [ "$fails" -gt 0 ] || [ "$n" -gt 0 ] || [ ! -s durations.jsonl ]; then
  echo "❌ 配音闸门：${fails} 段产出失败、${n} 段时长为 0 —— 不产出 durations.json 之外的东西，直接失败" >&2
  exit 1
fi
