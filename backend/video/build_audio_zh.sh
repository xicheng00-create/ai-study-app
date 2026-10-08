# 来源：brain workspace/daily-video，勿就地魔改，同步靠内容比对
#!/usr/bin/env bash
# 中文配音 + 时长表。输入 narration.json（{"scenes":[{"id","text"}]}），
# 输出 audio/<id>.mp3 与 durations.json（每段 ffprobe 实测秒数，供 Manim 补时）。
# 用法: bash build_audio_zh.sh [narration.json]   覆盖: VOICE / RATE / EDGE_TTS / EDGE_RATE
# 零 API 成本：edge-tts 是本机免费通道（hermes venv 里的可执行文件），不需要 key。
set -uo pipefail
cd "${PROJECT_DIR:-$PWD}"   # 在项目目录里跑（不要 cd 到脚本自己的位置，产物会落错地方）
EDGE="${EDGE_TTS:-$HOME/.hermes/hermes-agent/venv/bin/edge-tts}"
VOICE="${VOICE:-zh-CN-YunyangNeural}"   # 男声新闻腔；女声 zh-CN-XiaoxiaoNeural
RATE="${RATE:-+0%}"                     # 0 = 标准语速；+8% 时 209 字只剩 42.5s，掉出「45–55s」规格
NARR="${1:-narration.json}"
mkdir -p audio
python3 - "$NARR" <<'PY' > /tmp/vid_scene_texts.tsv
import json, sys
for s in json.load(open(sys.argv[1]))["scenes"]:
    print(f'{s["id"]}\t{s["text"]}')
PY
: > durations.jsonl
while IFS=$'\t' read -r sid text; do
  [ -z "$sid" ] && continue
  # --write-subtitles 拿的是 edge-tts 的 WordBoundary 事件：逐词起始时刻。
  # 有了它，画面每个节拍可以对齐到「配音念到那个词」的那一刻，而不是按字数均分。
  "$EDGE" --voice "$VOICE" --rate="$RATE" --text "$text" \
      --write-media "audio/${sid}.mp3" --write-subtitles "audio/${sid}.vtt" >/dev/null 2>&1
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
