#!/bin/bash
# AI 视频讲解 · 生成 worker 启动脚本（launchd / 手动两用）
# 用法: bash deploy/run-video-worker.sh
# 职责：加载 .env → 以仓库 venv 跑 backend/video_worker.py（单进程 FIFO 队列）。
# 依赖（PATH 由 plist 或本脚本保证）：ffmpeg/ffprobe(Homebrew)、python3、
# ~/.hermes/hermes-agent/venv/bin/edge-tts（配音）、manim（绝对路径，见 backend/video/daily_video.py）。
set -euo pipefail

REPO="/Users/xicheng/WorkBuddy/AI学习小组app"
VENV="$REPO/.venv"

# 加载 .env（DATABASE_PATH / DEEPSEEK key / FLASK_ENV 等）
if [ -f "$REPO/.env" ]; then
  set -a; source "$REPO/.env"; set +a
fi

export FLASK_ENV="${FLASK_ENV:-production}"
export PATH="/Users/xicheng/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

cd "$REPO"
exec "$VENV/bin/python" "$REPO/backend/video_worker.py"
