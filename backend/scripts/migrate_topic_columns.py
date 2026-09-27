"""幂等主题列迁移：先在线备份 SQLite（含 WAL），绝不回填历史归属。"""
import os
import sqlite3
from pathlib import Path


def migrate(path):
    path = Path(path)
    backup = path.with_name(path.name + '.pre-topic.bak')
    with sqlite3.connect(path) as con:
        with sqlite3.connect(backup) as dst:
            con.backup(dst)
        for table in ('questions', 'practice_questions'):
            cols = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
            if 'topic' not in cols:
                con.execute(f'ALTER TABLE {table} ADD COLUMN topic TEXT')


if __name__ == '__main__':
    migrate(os.environ.get('DATABASE_PATH', 'instance/aistudy.sqlite3'))
