"""卡片主题分组（KNOW-008）+ 章节天数口径（KNOW-009）—— v2.7.0。

覆盖：
1. `/api/chapters` 下发 card_count 与 daily_cards（前端「预计 X 天学完」的数据源，前端不硬编码 30）；
2. `/api/knowledge/<cid>` 的卡片带 topic（card_topics 表）；
3. card_topics 为空时 topic 回落空串（前端退化为单组「全部卡片」，老库仍可用）；
4. 测评标签按「第 N 章」表述（不再回显「第X周 第Y节」）。
"""
from ai import knowledge
from conftest import login, make_student
from config import PLAN_CARDS_PER_DAY


def _chapter(client, headers, name='第 1 章 · 测试章', order_no=None):
    payload = {'name': name}
    if order_no is not None:
        payload['order_no'] = order_no
    return client.post('/api/chapters', json=payload, headers=headers).get_json()['data']['id']


def _student(client, headers, name):
    make_student(client, headers, name)
    return {'Authorization': 'Bearer ' + login(client, name, 'student123')}


def _seed_cards(client, headers, cid, monkeypatch, fronts=('概念 A', '概念 B')):
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [
        {'front': f, 'back': f + ' 的答案', 'sub_concept': 'A'} for f in fronts
    ])
    student = _student(client, headers, 'grp' + cid[:4])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [cid]},
                        headers=student).get_json()['data']['cards']
    return student, cards


def test_chapters_api_exposes_card_count_and_daily_cards(client, teacher_headers, monkeypatch):
    """KNOW-009：章节列表带卡片数 + 每日可学张数（服务端下发，前端不硬编码 30）。"""
    cid = _chapter(client, teacher_headers, '第 7 章 · 天数口径')
    _seed_cards(client, teacher_headers, cid, monkeypatch)
    student = _student(client, teacher_headers, 'days7')

    data = client.get('/api/chapters', headers=student).get_json()['data']
    assert data['daily_cards'] == PLAN_CARDS_PER_DAY == 30
    row = [c for c in data['chapters'] if c['id'] == cid][0]
    assert row['card_count'] == 2
    # 「预计 X 天学完」= ceil(2 / 30) = 1 天（章节不再挂「第X周」）
    assert row['name'].startswith('第 7 章')


def test_cards_payload_includes_topic(client, teacher_headers, monkeypatch):
    """KNOW-008：卡片带主题分组标签（LLM 离线归类结果，仅供浏览）。"""
    cid = _chapter(client, teacher_headers, '第 8 章 · 主题分组')
    student, cards = _seed_cards(client, teacher_headers, cid, monkeypatch,
                                 fronts=('什么是幻觉？', '什么是 RAG？'))

    from data.db import get_db
    with client.application.app_context():
        con = get_db()
        for i, c in enumerate(cards):
            con.execute(
                'INSERT INTO card_topics (card_id, chapter_id, topic, ord) VALUES (?,?,?,?)',
                (c['id'], cid, '基础概念' if i == 0 else '检索增强', i),
            )
        con.commit()

    got = client.get('/api/knowledge/' + cid, headers=student).get_json()['data']
    topics = {c['front']: c['topic'] for c in got['cards']}
    assert topics == {'什么是幻觉？': '基础概念', '什么是 RAG？': '检索增强'}
    # 不影响原有字段（浏览归类不参与出卡/复习）
    assert all(c['status'] == 'new' and c['back'] for c in got['cards'])


def test_cards_topic_falls_back_to_empty_string(client, teacher_headers, monkeypatch):
    """老库/未归类：card_topics 空表时 topic 为空串 → 前端退化成单组「全部卡片」。"""
    cid = _chapter(client, teacher_headers, '第 9 章 · 未归类')
    student, _ = _seed_cards(client, teacher_headers, cid, monkeypatch)
    got = client.get('/api/knowledge/' + cid, headers=student).get_json()['data']
    assert got['cards'] and all(c['topic'] == '' for c in got['cards'])


def test_quiz_label_uses_chapter_number(client, teacher_headers):
    """KNOW-009：测评标签改按「第 N 章 · 章标题」，不再回显「第X周 第Y节」。"""
    from api.class_bp import _quiz_session_label
    from data.db import get_db

    cid = _chapter(client, teacher_headers, '第 3 章 · AIPM vs 传统 PM', order_no=3)
    sid = client.post('/api/curriculum/sessions',
                      json={'title': '第2周第1节', 'chapter_ids': [cid]},
                      headers=teacher_headers).get_json()['data']['id']
    assert client.post(f'/api/curriculum/sessions/{sid}/publish',
                       headers=teacher_headers).status_code == 200

    with client.application.app_context():
        con = get_db()
        label = _quiz_session_label(con, [cid])
    assert label == '测评 · 第 3 章 · AIPM vs 传统 PM'
