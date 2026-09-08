"""知识卡片 API：生成、复习状态机、隔离和总览。"""
from ai import knowledge
from conftest import login, make_student


def _chapter(client, headers):
    r = client.post('/api/chapters', json={'name': '第一章'}, headers=headers)
    return r.get_json()['data']['id']


def _student(client, headers, name):
    make_student(client, headers, name)
    return {'Authorization': 'Bearer ' + login(client, name, 'student123')}


def test_generate_review_and_overview(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers); headers = _student(client, teacher_headers, 'carda')
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [
        {'front': '概念 A', 'back': '答案 A', 'sub_concept': 'A'},
        {'front': '概念 A', 'back': '重复', 'sub_concept': 'A'},
        {'front': '概念 B', 'back': '答案 B', 'sub_concept': 'B'}])
    r = client.post('/api/knowledge/generate', json={'chapter_ids': [cid]}, headers=headers)
    assert r.status_code == 200; cards = r.get_json()['data']['cards']; assert len(cards) == 2
    card = cards[0]
    r = client.post('/api/knowledge/' + card['id'] + '/review', json={'remembered': True}, headers=headers)
    updated = r.get_json()['data']['card']; assert updated['learn_count'] == 1 and updated['interval_days'] == 3 and updated['status'] == 'learning'
    r = client.post('/api/knowledge/' + card['id'] + '/review', json={'remembered': False}, headers=headers)
    updated = r.get_json()['data']['card']; assert updated['learn_count'] == 2 and updated['interval_days'] == 1 and updated['status'] == 'learning'
    overview = client.get('/api/knowledge/overview', headers=headers).get_json()['data']['chapters'][0]
    assert overview['counts']['total'] == 2 and overview['counts']['learning'] == 1


def test_card_isolation(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers); one = _student(client, teacher_headers, 'cardone'); two = _student(client, teacher_headers, 'cardtwo')
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [{'front': '私有卡', 'back': '答案', 'sub_concept': 'x'}])
    card = client.post('/api/knowledge/generate', json={'chapter_ids': [cid]}, headers=one).get_json()['data']['cards'][0]
    r = client.post('/api/knowledge/' + card['id'] + '/review', json={'remembered': True}, headers=two)
    assert r.status_code == 403
