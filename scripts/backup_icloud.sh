#!/bin/bash
# iCloud Drive 每日备份（对齐 Design Spec DEP-008 / F2：备份前先 wal_checkpoint 刷盘）
# 目标：iCloud Drive/AI学习小组app-backup/{db,uploads,chroma}
set -euo pipefail

REPO="/Users/xicheng/WorkBuddy/AI学习小组app"
STAMP="$(date +%Y-%m-%d)"
ICLOUD="/Users/xicheng/Library/Mobile Documents/com~apple~CloudDocs/AI学习小组app-backup"
DEST="$ICLOUD/$STAMP"
mkdir -p "$DEST/db" "$DEST/uploads" "$DEST/chroma"

cd "$REPO"

# 1) wal_checkpoint(TRUNCATE) 刷盘，避免 rsync 拷到 half-write
DB="$REPO/instance/aistudy.sqlite3"
if [ -f "$DB" ]; then
  "$REPO/.venv/bin/python" - "$DB" <<'PY'
import sqlite3, sys
try:
    con = sqlite3.connect(sys.argv[1])
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("wal_checkpoint OK")
except Exception as e:
    print(f"wal_checkpoint skipped: {e}")
PY
fi

# 2) rsync 数据层
[ -d "$REPO/instance" ] && rsync -a --delete "$REPO/instance/" "$DEST/db/instance/" 2>/dev/null || true
[ -d "$REPO/data" ] && rsync -a --delete "$REPO/data/" "$DEST/db/data/" 2>/dev/null || true
[ -d "$REPO/uploads" ] && rsync -a --delete "$REPO/uploads/" "$DEST/uploads/" 2>/dev/null || true
[ -d "$REPO/chroma_db" ] && rsync -a --delete "$REPO/chroma_db/" "$DEST/chroma/" 2>/dev/null || true
# 数据库文件直拷
[ -f "$DB" ] && rsync -a "$DB" "$DEST/db/" 2>/dev/null || true

# 3) 保留最近 7 天 + 目录说明
find "$ICLOUD" -maxdepth 1 -type d -name "2*" -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
echo "backup done -> $DEST"
