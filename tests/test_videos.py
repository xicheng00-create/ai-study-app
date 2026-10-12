"""视频 API 幂等、角色隔离和分段读取。"""
from pathlib import Path

from ai import knowledge
from conftest import login, make_student
from data import models
from data.db import get_db


def test_video_request_and_range(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': '视频章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'vidstudent')
    student = {'Authorization': 'Bearer ' + login(client, 'vidstudent', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [{'front': '讲解', 'back': '解释', 'sub_concept': '讲解'}])
    card = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards'][0]['id']
    path = f'/api/videos/card/{card}'
    assert client.get(path, headers=student).get_json()['data']['status'] == 'none'
    ids = [client.post(path + '/request', headers=student).get_json()['data']['video_id'] for _ in range(3)]
    assert len(set(ids)) == 1
    with client.application.app_context():
        con = get_db()
        assert con.execute('SELECT count(*) FROM card_videos WHERE core_card_id=?', (card,)).fetchone()[0] == 1
        con.execute("UPDATE card_videos SET status='ready',file_name='stub.mp4' WHERE id=?", (ids[0],)); con.commit()
    assert client.post(path + '/request', headers=student).get_json()['data']['status'] == 'ready'
    assert len(client.get('/api/videos', headers=student).get_json()['data']) == 1
    assert client.get('/api/videos', headers=teacher_headers).status_code == 403
    assert client.post(path + '/request', headers=teacher_headers).status_code == 403
    assert client.get('/api/videos/card/no-such-card', headers=student).status_code == 404
    media = Path(client.application.root_path).parent / 'instance/media/videos/stub.mp4'; media.parent.mkdir(parents=True, exist_ok=True)
    try:
        media.write_bytes(b'0' * 2048)
        resp = client.get('/media/videos/stub.mp4', headers={'Range': 'bytes=0-1023'})
        assert resp.status_code == 206 and resp.headers['Content-Range'] == 'bytes 0-1023/2048'
    finally: media.unlink(missing_ok=True)


def test_batch_api_dedup_idempotency_and_permissions(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': '批量章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'batchstudent')
    student = {'Authorization': 'Bearer ' + login(client, 'batchstudent', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [{'front': f'卡{i}', 'back': '解', 'sub_concept': '主题'} for i in range(4)])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards']; ids = [c['id'] for c in cards]
    with client.application.app_context():
        con = get_db(); before = con.execute('SELECT count(*) FROM card_videos').fetchone()[0]
        for cid, status in ((ids[0], 'ready'), (ids[1], 'queued')):
            con.execute('INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,requested_at) VALUES(?,?,?,?,?,?)', (models.new_id(), cid, chapter, status, cid, models.utcnow()))
        con.commit()
    with client.application.app_context():
        before = get_db().execute('SELECT count(*) FROM card_videos').fetchone()[0]
    response = client.post('/api/videos/batch', json={'card_ids': ids[:3]}, headers=student); assert response.status_code == 200
    data = response.get_json()['data']; assert data['skipped'] == 1 and data['queued'] == 1 and data['pending'] == 2
    with client.application.app_context():
        assert get_db().execute('SELECT count(*) FROM card_videos').fetchone()[0] - before == 1
        assert get_db().execute('SELECT count(*) FROM card_video_batch_items WHERE batch_id=?', (data['batch_id'],)).fetchone()[0] == 2
    again = client.post('/api/videos/batch', json={'card_ids': list(reversed(ids[:3]))}, headers=student).get_json()['data']
    with client.application.app_context():
        assert again['batch_id'] == data['batch_id'] and get_db().execute('SELECT count(*) FROM card_video_batches').fetchone()[0] == 1
    assert client.post('/api/videos/batch', json={'card_ids': [str(i) for i in range(101)]}, headers=student).status_code == 400
    make_student(client, teacher_headers, 'batchother'); other = {'Authorization': 'Bearer ' + login(client, 'batchother', 'student123')}
    assert client.get('/api/videos/batch/' + data['batch_id'], headers=other).status_code == 404


def test_batch_notification_exactly_once(client, teacher_headers, monkeypatch):
    import video_worker
    chapter = client.post('/api/chapters', json={'name': '通知章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'batchnotify'); student = {'Authorization': 'Bearer ' + login(client, 'batchnotify', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [{'front': f'通知{i}', 'back': '解', 'sub_concept': '主题'} for i in range(3)])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards']; ids = [c['id'] for c in cards]
    batch = client.post('/api/videos/batch', json={'card_ids': ids}, headers=student).get_json()['data']
    with client.application.app_context():
        con = get_db()
        for idx, cid in enumerate(ids):
            vid = con.execute('SELECT id FROM card_videos WHERE core_card_id=?', (cid,)).fetchone()['id']
            con.execute("UPDATE card_videos SET status='ready',file_name='stub.mp4' WHERE id=?", (vid,)); video_worker._notify_video_requests(con, vid)
            count = con.execute("SELECT count(*) FROM notifications WHERE type='card_video_batch_ready'").fetchone()[0]
            assert count == (1 if idx == 2 else 0)
        note = con.execute("SELECT user_id,ref_kind,ref_id FROM notifications WHERE type='card_video_batch_ready'").fetchone()
        user = con.execute("SELECT id FROM users WHERE username='batchnotify'").fetchone()[0]
        assert note['user_id'] == user and note['ref_kind'] == 'card_videos' and note['ref_id'] == batch['batch_id']


def test_video_index_reverse_and_counts(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': '索引章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'indexstudent'); student = {'Authorization': 'Bearer ' + login(client, 'indexstudent', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [{'front': '核心', 'back': '解', 'sub_concept': '主题'}, {'front': '相关', 'back': '解', 'sub_concept': '主题'}])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards']
    index = client.get('/api/videos/index', headers=student).get_json()['data']
    assert all(index['all_cards'][c['id']]['status'] == 'none' for c in cards)
    with client.application.app_context():
        con = get_db(); vid = models.new_id()
        con.execute("INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,requested_at) VALUES(?,?,?,'ready','核心',?)", (vid, cards[0]['id'], chapter, models.utcnow()))
        con.execute('INSERT INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,1)', (vid, cards[0]['id']))
        con.execute('INSERT INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,0)', (vid, cards[1]['id'])); con.commit()
    reverse = client.get(f'/api/videos/{vid}/cards', headers=student).get_json()['data']
    assert len(reverse) == 2 and reverse[0]['is_core'] and reverse[0]['id'] == cards[0]['id']
    index = client.get('/api/videos/index', headers=student).get_json()['data'
    ]
    assert index['all_cards'][cards[1]['id']]['video_id'] == vid and index['chapters'][chapter]['videos'] == 1
    assert client.get(f'/api/videos/{vid}/cards', headers=teacher_headers).status_code == 403
    assert client.get('/api/videos/index', headers=teacher_headers).status_code == 403


def test_video_index_all_states_and_chapter_topic_summary(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': '视频汇总章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'summarystudent')
    student = {'Authorization': 'Bearer ' + login(client, 'summarystudent', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [
        {'front': '主题甲一', 'back': '解', 'sub_concept': '甲'}, {'front': '主题甲二', 'back': '解', 'sub_concept': '甲'}, {'front': '主题乙', 'back': '解', 'sub_concept': '乙'}])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards']
    with client.application.app_context():
        con = get_db()
        for idx, topic, order in ((0, '甲主题', 1), (1, '甲主题', 1), (2, '乙主题', 2)):
            con.execute('INSERT INTO card_topics(card_id,chapter_id,topic,ord) VALUES(?,?,?,?)', (cards[idx]['id'], chapter, topic, order))
        for idx, status in ((0, 'queued'), (1, 'generating'), (2, 'failed')):
            con.execute('INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,requested_at) VALUES(?,?,?,?,?,?)', (models.new_id(), cards[idx]['id'], chapter, status, cards[idx]['front'], models.utcnow()))
        con.commit()
    index = client.get('/api/videos/index', headers=student).get_json()['data']
    assert [index['all_cards'][c['id']]['status'] for c in cards] == ['queued', 'generating', 'failed']
    assert index['chapters'][chapter]['videos'] == 0
    assert index['topics'][f'{chapter}|甲主题']['cards_total'] == 2
    assert index['topics'][f'{chapter}|甲主题']['cards_with_video'] == 0
    assert client.get('/api/videos/index', headers=teacher_headers).status_code == 403


def test_video_listing_adjacent_topics_fields(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': '跨主题章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'adjstudent')
    student = {'Authorization': 'Bearer ' + login(client, 'adjstudent', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [
        {'front': '核心', 'back': '解', 'sub_concept': '甲'}, {'front': '关联', 'back': '解', 'sub_concept': '乙'}])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards']
    with client.application.app_context():
        con = get_db()
        for card, topic, order in ((cards[0], '甲主题', 1), (cards[1], '乙主题', 2)):
            con.execute('INSERT INTO card_topics(card_id,chapter_id,topic,ord) VALUES(?,?,?,?)', (card['id'], chapter, topic, order))
        vid = models.new_id()
        con.execute("INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,file_name,requested_at) VALUES(?,?,?,'ready','核心','core.mp4',?)", (vid, cards[0]['id'], chapter, models.utcnow()))
        con.execute('INSERT INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,1)', (vid, cards[0]['id']))
        con.execute('INSERT INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,0)', (vid, cards[1]['id']))
        con.commit()
    item = client.get('/api/videos', headers=student).get_json()['data'][0]
    assert item['n_cards'] == 2 and item['adjacent_cards'] == 1 and item['adjacent_topics'] == 2


def test_video_index_card_link_set_and_core_flags(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': '链接集合章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'linksetstudent')
    student = {'Authorization': 'Bearer ' + login(client, 'linksetstudent', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [{'front': f'卡{i}', 'back': '解', 'sub_concept': '主题'} for i in range(3)])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards']
    with client.application.app_context():
        con = get_db(); video_ids = []
        for i, status in enumerate(('ready', 'queued', 'failed')):
            vid = models.new_id(); video_ids.append(vid)
            con.execute("INSERT INTO card_videos(id,core_card_id,chapter_id,status,title,requested_at) VALUES(?,?,?,?,?,?)", (vid, cards[i]['id'], chapter, status, cards[i]['front'], models.utcnow()))
            con.execute('INSERT INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,1)', (vid, cards[i]['id']))
        con.commit()
        linked_ids = {r[0] for r in con.execute('SELECT DISTINCT card_id FROM card_video_links')}
    data = client.get('/api/videos/index', headers=student).get_json()['data']
    assert set(data['cards']) >= linked_ids
    assert {cid for cid, entry in data['cards'].items() if entry['is_core']} == {c['id'] for c in cards}
    assert [data['cards'][c['id']]['status'] for c in cards] == ['ready', 'queued', 'failed']
    assert all(data['cards'][c['id']]['n_cards'] == 1 for c in cards)
    assert all(data['cards'][c['id']]['video_id'] == video_ids[i] for i, c in enumerate(cards))
