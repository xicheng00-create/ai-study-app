"""共享知识卡片：学生个人复习态、状态机及发布钩子。"""
from ai import knowledge
from conftest import login, make_student


def _chapter(client, headers):
    return client.post('/api/chapters', json={'name': '第一章'}, headers=headers).get_json()['data']['id']


def _student(client, headers, name):
    make_student(client, headers, name)
    return {'Authorization': 'Bearer ' + login(client, name, 'student123')}


def test_shared_cards_lazy_review_and_state_machine(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers); one = _student(client, teacher_headers, 'carda')
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [
        {'front': '概念 A', 'back': '答案 A', 'sub_concept': 'A'},
        {'front': '概念 A', 'back': '重复', 'sub_concept': 'A'},
        {'front': '概念 B', 'back': '答案 B', 'sub_concept': 'B'}])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [cid]}, headers=one).get_json()['data']['cards']
    assert len(cards) == 2 and all(c['status'] == 'new' for c in cards)
    card = cards[0]
    updated = client.post('/api/knowledge/' + card['id'] + '/review', json={'remembered': True}, headers=one).get_json()['data']['card']
    assert (updated['learn_count'], updated['interval_days'], updated['status']) == (1, 3, 'learning')
    updated = client.post('/api/knowledge/' + card['id'] + '/review', json={'remembered': False}, headers=one).get_json()['data']['card']
    assert (updated['learn_count'], updated['interval_days'], updated['status']) == (2, 1, 'learning')
    overview = client.get('/api/knowledge/overview', headers=one).get_json()['data']['chapters'][0]
    assert overview['counts']['total'] == 2 and overview['counts']['learning'] == 1
    two = _student(client, teacher_headers, 'cardb')
    theirs = client.get('/api/knowledge/' + cid, headers=two).get_json()['data']['cards']
    assert all(c['status'] == 'new' and c['learn_count'] == 0 for c in theirs)


def test_review_unknown_card_forbidden(client, teacher_headers):
    headers = _student(client, teacher_headers, 'cardone')
    r = client.post('/api/knowledge/missing/review', json={'remembered': True}, headers=headers)
    assert r.status_code == 403


def test_session_publish_ensures_chapter_cards(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers); calls = []
    monkeypatch.setattr(knowledge, 'ensure_chapter_cards', lambda chapter_id: calls.append(chapter_id) or 0)
    sid = client.post('/api/curriculum/sessions', json={'title': '第一节', 'chapter_ids': [cid]}, headers=teacher_headers).get_json()['data']['id']
    assert client.post(f'/api/curriculum/sessions/{sid}/publish', headers=teacher_headers).status_code == 200
    assert calls == [cid]
