"""worker 状态机（不运行 Manim）。"""
from data import models
from data.db import get_db
from video_worker import claim, process, recover


def test_worker_recovery_and_transitions(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': 'worker章'}, headers=teacher_headers).get_json()['data']['id']
    with client.application.app_context():
        con = get_db()
        card = models.new_id()
        con.execute('INSERT INTO knowledge_cards(id,chapter_id,front,back,created_at) VALUES(?,?,?,?,?)', (card, chapter, '卡', '解', models.utcnow()))
        vid = models.new_id()
        con.execute("INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,requested_at) VALUES(?,?,?,'generating','卡',?)", (vid, card, chapter, models.utcnow()))
        con.commit()
        recover(con)
        assert con.execute('SELECT status FROM card_videos WHERE id=?', (vid,)).fetchone()[0] == 'queued'
        row = claim(con)
        assert row['id'] == vid
        assert con.execute('SELECT status FROM card_videos WHERE id=?', (vid,)).fetchone()[0] == 'generating'
        import video_worker
        monkeypatch.setattr(video_worker, 'render', lambda *args: ([], '{}', 80.0, 1024))
        process(con, row)
        assert con.execute('SELECT status FROM card_videos WHERE id=?', (vid,)).fetchone()[0] == 'ready'
        assert con.execute('SELECT count(*) FROM card_video_links WHERE video_id=? AND is_core=1', (vid,)).fetchone()[0] == 1
        con.execute("UPDATE card_videos SET status='queued' WHERE id=?", (vid,))
        con.commit()
        row = claim(con)
        def fail(*args):
            raise ValueError('渲染失败')
        monkeypatch.setattr(video_worker, 'render', fail)
        process(con, row)
        assert con.execute('SELECT status,error FROM card_videos WHERE id=?', (vid,)).fetchone()[:] == ('failed', '渲染失败')


def test_claim_returns_none_if_another_worker_won(client, teacher_headers):
    import sqlite3
    chapter = client.post('/api/chapters', json={'name': 'claim-race'}, headers=teacher_headers).get_json()['data']['id']
    with client.application.app_context():
        con = get_db(); card = models.new_id(); vid = models.new_id()
        con.execute('INSERT INTO knowledge_cards(id,chapter_id,front,back,created_at) VALUES(?,?,?,?,?)', (card,chapter,'卡','解',models.utcnow()))
        con.execute("INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,requested_at) VALUES(?,?,?,'queued','卡',?)", (vid,card,chapter,models.utcnow())); con.commit()
        path = con.execute('PRAGMA database_list').fetchone()[2]
        other = sqlite3.connect(path)
        class RacingConnection:
            def execute(self, sql, params=()):
                if sql.startswith("UPDATE card_videos SET status='generating'"):
                    other.execute("UPDATE card_videos SET status='generating' WHERE id=?", (vid,))
                    other.commit()
                return con.execute(sql, params)
            def commit(self):
                con.commit()
        try:
            assert claim(RacingConnection()) is None
            assert con.execute('SELECT status FROM card_videos WHERE id=?',(vid,)).fetchone()[0] == 'generating'
        finally:
            other.close()


def test_concurrent_queue_sources(client, teacher_headers):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from data.video_queue import enqueue
    chapter = client.post('/api/chapters', json={'name': 'queue-race'}, headers=teacher_headers).get_json()['data']['id']
    with client.application.app_context():
        con = get_db(); card = models.new_id()
        uid = con.execute("SELECT id FROM users WHERE role='teacher'").fetchone()[0]
        con.execute('INSERT INTO knowledge_cards(id,chapter_id,front,back,created_at) VALUES(?,?,?,?,?)', (card,chapter,'卡','解',models.utcnow())); con.commit()
        path = con.execute('PRAGMA database_list').fetchone()[2]
        barrier = Barrier(3)
        def submit(source):
            db = sqlite3.connect(path, timeout=10); db.row_factory = sqlite3.Row
            try:
                # All callers observe missing before any INSERT.
                assert db.execute('SELECT id FROM card_videos WHERE core_card_id=?', (card,)).fetchone() is None
                barrier.wait(timeout=5)
                row = enqueue(db, card, uid)
                db.execute('INSERT INTO card_video_requests(id,video_id,card_id,user_id,source,notify,created_at) VALUES(?,?,?,?,?,?,?)', (models.new_id(),row['id'],card,uid,source,int(source != 'prewarm'),models.utcnow()))
                db.commit()
                return row['id']
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=3) as pool:
            ids = list(pool.map(submit, ['manual','batch','prewarm']))
        assert len(set(ids)) == 1
        assert con.execute('SELECT count(*) FROM card_videos WHERE core_card_id=?', (card,)).fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM card_video_requests WHERE card_id=?', (card,)).fetchone()[0] == 3
