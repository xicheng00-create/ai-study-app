#!/bin/bash
# aistudy-run-port.sh — 以指定端口启动 AI学习小组服务（供 supervisor 用，绕开 run.sh 的 .env PORT 覆盖）
# 用法: aistudy-run-port.sh <PORT> [HOST]
# ⚠️ 关键：必须**先 source .env（拿密钥），再**用传入值覆盖** PORT/HOST/FLASK_ENV——
#     .env 里 PORT=5001 会在 source 时覆盖 shell 变量，所以覆盖赋值必须放在 source 之后。
set -euo pipefail
REPO="/Users/xicheng/WorkBuddy/AI学习小组app"
NEW_PORT="${1:-5003}"
NEW_HOST="${2:-0.0.0.0}"

cd "$REPO/backend"

# 1) 先加载 .env 的全部变量（密钥等）
if [ -f "$REPO/.env" ]; then
  set -a; source "$REPO/.env"; set +a
fi

# 2) 再**显式覆盖**端口/主机/环境（这时 $NEW_PORT 是干净的外部传值，不会被 .env 覆盖）
export FLASK_ENV="production"
export PORT="$NEW_PORT"
export HOST="$NEW_HOST"

echo "[boot] AI Study Group (waitress) on ${NEW_HOST}:${NEW_PORT} (PORT overridden)"
exec "$REPO/.venv/bin/python" -c "
from waitress import serve
from app import create_app
import os
app = create_app(os.environ.get('FLASK_ENV','production'))
serve(app, host=os.environ.get('HOST','127.0.0.1'), port=int(os.environ.get('PORT','5001')), threads=4)
"
