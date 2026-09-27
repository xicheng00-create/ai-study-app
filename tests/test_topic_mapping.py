"""PROG-011 无证据不能猜主题。"""
from ai import mastery, quizzer


def test_no_topic_fallback(client):
    from data.db import get_db
    with client.application.app_context():
        con = get_db()
        assert quizzer.assign_topic(con, 'missing', {'content': 'any'}) is None
        assert mastery.card_mastery(con, 'missing', 'missing') == []


def test_card_gate():
    assert not mastery.can_master_card({'events': 1, 'acc': 100})
    assert not mastery.can_master_card({'events': 2, 'acc': 79})
    assert mastery.can_master_card({'events': 2, 'acc': 80})


def test_shared_topic_weighted_accuracy(client):
    from data.db import get_db
    from data import models
    with client.application.app_context():
        con = get_db()
        now = models.utcnow()
        con.execute("INSERT INTO users (id,username,password_hash,role,created_at) VALUES ('u','u','x','student',?)", (now,))
        con.execute("INSERT INTO chapters (id,name,created_at) VALUES ('ch','章',?)", (now,))
        for i, topic in enumerate(('主题甲', '主题甲', '主题乙')):
            card = f'card{i}'
            con.execute("INSERT INTO knowledge_cards (id,chapter_id,front,back,created_at) VALUES (?, 'ch', ?, 'back', ?)", (card, card, now))
            con.execute("INSERT INTO card_topics (card_id,chapter_id,topic) VALUES (?, 'ch', ?)", (card, topic))
            con.execute("INSERT INTO knowledge_reviews (id,card_id,user_id,next_review_at,created_at,status) VALUES (?, ?, 'u', ?, ?, 'learning')", (f'r{i}', card, now, now))
        con.execute("INSERT INTO practice_sessions (id,user_id,created_at) VALUES ('ps','u',?)", (now,))
        for i, score in enumerate((5, 0)):
            con.execute("INSERT INTO practice_questions (id,session_id,chapter_id,content,points,score,answered_at,topic) VALUES (?, 'ps', 'ch', ?, 5, ?, ?, '主题甲')", (f'q{i}', f'q{i}', score, now))
        cards = mastery.card_mastery(con, 'u', 'ch')
        assert [c['acc'] for c in cards] == [50, 50, None]
        assert [c['m'] for c in cards] == [45, 45, 40]
        assert mastery.compute_mastery(con, 'u', 'ch')['evidence_cards'] == 2
        assert quizzer.assign_topic(con, 'ch', {'content': '主题甲相关问题'}) == '主题甲'
        assert quizzer.assign_topic(con, 'ch', {'content': '主题甲与主题乙'}) is None
