# 来源：brain workspace/daily-video，勿就地魔改，同步靠内容比对
#!/usr/bin/env bash
# 分段视频 + 配音拼接 → final.mp4。场景顺序全部取自 durations.json（即配音顺序），
# 不要手写 SCENES 列表——手写会漏场、错序（2026-10-06 首版就是这么写的）。
# 前置：build_audio_zh.sh 已跑；manim -qm 已把每场渲染到 media/videos/script/720p30/<id>.mp4
# 用法: bash stitch_av.sh    覆盖: FFMPEG / VIDEO_DIR / PAD
set -uo pipefail
cd "${PROJECT_DIR:-$PWD}"   # 在项目目录里跑（产物、concat.txt、padded/ 都落在项目目录）
FF="${FFMPEG:-ffmpeg}"
V="${VIDEO_DIR:-media/videos/script/720p30}"
PAD="${PAD:-0.6}"   # 每段配音后补的静音秒数，必须与 script.py 里 pad 默认值一致
mkdir -p padded
python3 -c "import json;print('\n'.join(r['id'] for r in json.load(open('durations.json'))))" > /tmp/vid_scenes.txt
: > concat.txt
: > audio_concat.txt
while read -r sid; do
  [ -z "$sid" ] && continue
  if [ ! -f "$V/$sid.mp4" ]; then echo "❌ 缺渲染: $V/$sid.mp4（场景 id 必须与 narration.json 一致）"; exit 1; fi
  echo "file '$V/$sid.mp4'" >> concat.txt
  "$FF" -y -v error -i "audio/$sid.mp3" -af "apad=pad_dur=$PAD" -ar 44100 -ac 2 "padded/$sid.wav"
  echo "file 'padded/$sid.wav'" >> audio_concat.txt
done < /tmp/vid_scenes.txt
"$FF" -y -v error -f concat -safe 0 -i concat.txt -c copy video_only.mp4
"$FF" -y -v error -f concat -safe 0 -i audio_concat.txt -c:a pcm_s16le audio_all.wav
"$FF" -y -v error -i video_only.mp4 -i audio_all.wav -c:v copy -c:a aac -b:a 160k -shortest -movflags +faststart final.mp4
echo "--- 校验：每段画面时长应 ≈ 配音时长 + $PAD ---"
while read -r sid; do
  [ -z "$sid" ] && continue
  vd=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$V/$sid.mp4")
  ad=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "audio/$sid.mp3")
  printf "%-16s video=%-8s audio=%s\n" "$sid" "$vd" "$ad"
done < /tmp/vid_scenes.txt
echo "--- final ---"
$FF -hide_banner -i final.mp4 2>&1 | grep -E "Duration|Stream"
