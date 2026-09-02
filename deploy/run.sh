#!/bin/bash
# ai-study 服务启动脚本（launchd / 手动两用）
# 用法: run.sh [PORT]  服务端口默认 5001
set -euo pipefail

REPO="/Users/xicheng/WorkBuddy/AI学习小组app"
VENV="$REPO/.venv"
# app 模块在 backend/ 子目录，须 cd 到 backend 才能 `from app import create_app`
cd "$REPO/backend"

# 加载 .env（生产密钥 + DeepSeek key + 端口）
if [ -f "$REPO/.env" ]; then
  set -a; source "$REPO/.env"; set +a
fi

PORT="${PORT:-5001}"
# 默认绑定 0.0.0.0：允许局域网内手机/设备直连 iMac 的 192.168.50.22:5001（2ms 极速），
# 减少对 Cloudflare tunnel（130ms RTT、QUIC 易断）的依赖。tunnel 仍访问 127.0.0.1 不受影响。
HOST="${HOST:-0.0.0.0}"

export FLASK_ENV="${FLASK_ENV:-production}"
# 防止 Werkzeug debugger 暴露公网：production 强制 debug=False

echo "[boot] AI Study Group (waitress) on ${HOST}:${PORT}"
exec "$VENV/bin/python" -c "
from waitress import serve
from app import create_app
import os
app = create_app(os.environ.get('FLASK_ENV','production'))
serve(app, host=os.environ.get('HOST','127.0.0.1'), port=int(os.environ.get('PORT','5001')), threads=4)
"
