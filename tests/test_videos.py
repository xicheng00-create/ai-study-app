"""视频 API 幂等、角色隔离和分段读取。"""
from pathlib import Path

from ai import knowledge
from conftest import login, make_student
from data.db import get_db


def test_video_request_and_range(client, teacher_headers, monkeypatch):
    chapter = client.post('/api/chapters', json={'name': '视频章'}, headers=teacher_headers).get_json()['data']['id']
    make_student(client, teacher_headers, 'vidstudent')
    student = {'Authorization': 'Bearer ' + login(client, 'vidstudent', 'student123')}
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [
        {'front': '讲解', 'back': '解释', 'sub_concept': '讲解'}])
    card = client.post('/api/knowledge/generate', json={'chapter_ids': [chapter]}, headers=student).get_json()['data']['cards'][0]['id']
    path = f'/api/videos/card/{card}'
    assert client.get(path, headers=student).get_json()['data']['status'] == 'none'
    ids = [client.post(path + '/request', headers=student).get_json()['data']['video_id'] for _ in range(3)]
    assert len(set(ids)) == 1
    with client.application.app_context():
        con = get_db()
        assert con.execute('SELECT count(*) FROM card_videos WHERE core_card_id=?', (card,)).fetchone()[0] == 1
        con.execute("UPDATE card_videos SET status='ready',file_name='stub.mp4' WHERE id=?", (ids[0],))
        con.commit()
    assert client.post(path + '/request', headers=student).get_json()['data']['status'] == 'ready'
    assert len(client.get('/api/videos', headers=student).get_json()['data']) == 1
    assert client.get('/api/videos', headers=teacher_headers).status_code == 403
    assert client.post(path + '/request', headers=teacher_headers).status_code == 403
    assert client.get('/api/videos/card/no-such-card', headers=student).status_code == 404
    media = Path(client.application.root_path).parent / 'instance/media/videos/stub.mp4'
    media.parent.mkdir(parents=True, exist_ok=True)
    try:
        media.write_bytes(b'0' * 2048)
        resp = client.get('/media/videos/stub.mp4', headers={'Range': 'bytes=0-1023'})
        assert resp.status_code == 206 and resp.headers['Content-Range'] == 'bytes 0-1023/2048'
    finally:
        media.unlink(missing_ok=True)
