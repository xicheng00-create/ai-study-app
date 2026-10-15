#!/usr/bin/env bash
# 中文配音 + 时长表。输入 narration.json（{"scenes":[{"id","text"}]}），
# 输出 audio/<id>.mp3 与 durations.json（每段 ffprobe 实测秒数，供 Manim 补时）。
# 用法: bash build_audio_zh.sh [narration.json]
# 覆盖: VOICE / VOICE_POOL / RATE / EDGE_TTS / SAY_VOICE / SAY_RATE / MIN_DUR / TTS_DATE / AZURE_SPEECH_ENV
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
# Azure 官方语音（推荐通道）：有 key 才启用，没 key 行为与以前完全一致。
# key 从文件读，**不进聊天记录**：~/.hermes/secrets/azure_speech.env（chmod 600）两行：
#   AZURE_SPEECH_KEY=...   AZURE_SPEECH_REGION=eastasia
AZURE_SPEECH_ENV="${AZURE_SPEECH_ENV:-$HOME/.hermes/secrets/azure_speech.env}"
if [ -f "$AZURE_SPEECH_ENV" ]; then . "$AZURE_SPEECH_ENV"; fi
AZURE_SPEECH_KEY="${AZURE_SPEECH_KEY:-}"
AZURE_SPEECH_REGION="${AZURE_SPEECH_REGION:-}"
NARR="${1:-narration.json}"
mkdir -p audio

# ---- 选音色：有池就按**日期序号轮换**挑一支 ----
# 为什么不用哈希：`sha256(日期) % n` 只保证「同一天稳定」，相邻日会撞色
# —— 2026-10-15 实算：10-09~10-12 连着四天同一支，相邻日同色 5/11 对。
# 改成 `toordinal() % n`（连续整数、每天 +1）→ **相邻日必然不同**、长期绝对均匀，
# 且同日重跑仍是同一支（可复盘）。
# TTS_DATE=YYYY-MM-DD 可覆盖日期 —— 只为回归测试伪造相邻两天用，不碰系统时钟。
# 空池/全是逗号必须报清楚的人话，不能漏 python traceback。
if [ -n "$VOICE_POOL" ]; then
  TTS_DATE="${TTS_DATE:-$(date +%Y-%m-%d)}"
  picked=$(python3 - "$VOICE_POOL" "$TTS_DATE" <<'PY'
import datetime, sys
pool = [v.strip() for v in sys.argv[1].split(",") if v.strip()]
if not pool:
    sys.stderr.write("VOICE_POOL 里没有有效音色（只有逗号/空白）\n")
    sys.exit(3)
try:
    d = datetime.date.fromisoformat(sys.argv[2])
except ValueError:
    sys.stderr.write("TTS_DATE 不是 YYYY-MM-DD 格式：%r\n" % sys.argv[2])
    sys.exit(4)
sys.stdout.write(pool[d.toordinal() % len(pool)])
PY
  ) || { echo "❌ 音色池解析失败：VOICE_POOL='${VOICE_POOL}'（需为逗号分隔的音色名）" >&2; exit 1; }
  VOICE="$picked"
fi
if [ -z "$VOICE" ]; then
  echo "❌ 没有可用音色：VOICE 为空且 VOICE_POOL 没给出有效值" >&2
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

# tts_azure <id> <text>：Azure 官方 REST。只出音频（词级时刻要 SDK/WebSocket）→ 与 say 路同为 0 words。
tts_azure() {
  local sid="$1" text="$2" esc code
  [ -n "$AZURE_SPEECH_KEY" ] && [ -n "$AZURE_SPEECH_REGION" ] || return 1
  # 文本必须 XML 转义后再进 SSML（中文文案里的 & < > 会直接弄坏请求）
  esc=$(python3 -c 'import sys,html;sys.stdout.write(html.escape(sys.argv[1],quote=False))' "$text")
  rm -f "audio/${sid}.mp3" "audio/${sid}.vtt"
  code=$(printf '%s' "<speak version='1.0' xml:lang='zh-CN'><voice name='${VOICE}'><prosody rate='${RATE}'>${esc}</prosody></voice></speak>" | \
    curl -sS --max-time 30 -o "audio/${sid}.mp3" -w '%{http_code}' \
      -X POST "https://${AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1" \
      -H "Ocp-Apim-Subscription-Key: ${AZURE_SPEECH_KEY}" \
      -H "Content-Type: application/ssml+xml" \
      -H "X-Microsoft-OutputFormat: audio-24khz-48kbitrate-mono-mp3" \
      -H "User-Agent: brain-kb-tts" \
      --data-binary @- 2>/dev/null)
  [ "$code" = "200" ] || { echo "  [tts] azure HTTP ${code}（key/region 不对？）" >&2; rm -f "audio/${sid}.mp3"; return 1; }
  legal "audio/${sid}.mp3" || { rm -f "audio/${sid}.mp3"; return 1; }
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

# probe <channel>：单次短句预探，判断这条通道当前能不能用（预探产物一律清掉）
probe() {
  local ch="$1" ok=1
  case "$ch" in
    azure)
      [ -n "$AZURE_SPEECH_KEY" ] && [ -n "$AZURE_SPEECH_REGION" ] || return 1
      tts_azure _probe "$PROBE_TEXT" && ok=0
      rm -f audio/_probe.mp3 audio/_probe.vtt
      return $ok ;;
    edge)
      [ -x "$EDGE" ] || return 1
      rm -f audio/_probe.mp3
      "$EDGE" --voice "$VOICE" --rate="$RATE" --text "$PROBE_TEXT" --write-media audio/_probe.mp3 >/dev/null 2>&1
      legal audio/_probe.mp3 && ok=0
      rm -f audio/_probe.mp3   # 成功那次也会留文件，必须清掉
      return $ok ;;
    say)
      [ -n "$SAY_VOICE" ] ;;
    *) return 1 ;;
  esac
}

# render_all <channel>：整片用同一条通道渲染。任一段失败 → 立刻返回 1（不留半成品）
render_all() {
  local ch="$1" sid text dur
  : > durations.jsonl
  while IFS=$'\t' read -r sid text; do
    [ -z "$sid" ] && continue
    case "$ch" in
      azure) tts_azure "$sid" "$text" || { echo "  [tts] azure 在 ${sid} 段失败" >&2; return 1; } ;;
      edge)  tts_edge  "$sid" "$text" || { echo "  [tts] edge 在 ${sid} 段失败"  >&2; return 1; } ;;
      say)   tts_say   "$sid" "$text" || { echo "  [tts] say 在 ${sid} 段失败"   >&2; return 1; } ;;
      *) return 1 ;;
    esac
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

# ---- 通道优先级：Azure 官方（有 key 时）→ edge-tts 免费通道（会限流）→ 本机 say ----
# 每条通道都是「整片渲一次」：任一段失败就换下一条重渲整支，绝不让一支片里两个嗓子。
CANDS=()
if [ -n "$AZURE_SPEECH_KEY" ] && [ -n "$AZURE_SPEECH_REGION" ]; then CANDS+=("azure"); fi
CANDS+=("edge" "say")

CH=""
for c in "${CANDS[@]}"; do
  if ! probe "$c"; then
    echo "  [tts] $c 预探不过 → 跳过" >&2
    continue
  fi
  if render_all "$c"; then CH="$c"; break; fi
  echo "  [tts] $c 中途失败 → 整支重来换下一条通道（避免混音色）" >&2
done
if [ -z "$CH" ]; then
  echo "❌ 配音失败：${CANDS[*]} 全部产出不了合法音频" >&2
  exit 1
fi
echo "[tts] 实际通道=${CH}" >&2

# 记录本次实际用的是什么（复盘靠它）
python3 - "$VOICE" "$CH" "$RATE" "$VOICE_POOL" "${TTS_DATE:-}" "$SAY_VOICE" "$SAY_RATE" <<'PY'
import json, sys, datetime
# 参数顺序必须与上面的 shell 调用一一对应（踩过：少解一个值会把日期当嗓音名）。
voice, ch, rate, pool, tts_date, say_voice, say_rate = sys.argv[1:8]
# 留痕必须记「实际用的是哪天的挑法」：TTS_DATE 被伪造时不能记成系统日期（否则复盘时会撒谎）。
d = tts_date or datetime.date.today().isoformat()
is_say = ch == "say"
json.dump({"date": d,
           # voice / rate 是「标称」值（池里挑中的那支、请求的语速）。
           # 走 say 路时真正出声的嗓子与语速都是本机 say 的，必须在 *_actual 里如实记
           # —— 否则会出现「标称云扬、实发 Tingting」这种撒谎的留痕。
           # 注：channel=say 时 rate_actual 是 say -r 的值（词/分），其余通道同 rate（百分比）。
           "voice": voice,
           "voice_actual": say_voice if is_say else voice,
           "channel": ch,
           "rate": rate,
           "rate_actual": say_rate if is_say else rate,
           "pool": pool or None},
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
