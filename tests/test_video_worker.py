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
