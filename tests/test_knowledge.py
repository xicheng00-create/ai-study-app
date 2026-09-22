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


def test_overview_due_excludes_unlearned_and_counts_overdue(client, teacher_headers, monkeypatch):
    """v2.6.4：未学卡片不算「今日待复习」；已学且到期/逾期才计入；deck_max 随响应下发。

    故障现场（2026-09-19）：刚发布章节时「今日待复习 2384 张」（= 全部未学卡片）。
    """
    from datetime import timedelta

    from config import SESSION_DECK_MAX
    from data import timeutil
    from data.db import get_db

    cid = _chapter(client, teacher_headers); one = _student(client, teacher_headers, 'carddue')
    monkeypatch.setattr(knowledge, 'generate_knowledge_cards', lambda ids: [
        {'front': '概念 A', 'back': '答案 A', 'sub_concept': 'A'},
        {'front': '概念 B', 'back': '答案 B', 'sub_concept': 'B'}])
    cards = client.post('/api/knowledge/generate', json={'chapter_ids': [cid]}, headers=one).get_json()['data']
    assert cards['deck_max'] == SESSION_DECK_MAX

    def counts():
        ov = client.get('/api/knowledge/overview', headers=one).get_json()['data']
        assert ov['deck_max'] == SESSION_DECK_MAX
        return [c['counts'] for c in ov['chapters'] if c['chapter_id'] == cid][0]

    got = client.get('/api/knowledge/' + cid, headers=one).get_json()['data']
    assert got['deck_max'] == SESSION_DECK_MAX
    first = counts()
    assert first['total'] == 2 and first['today_due'] == 0 and first['new'] == 2   # 未学 ≠ 待复习

    # 复习一张且记住：interval=3 天 → 未到期，仍不计入今日待复习
    card_id = cards['cards'][0]['id']
    client.post('/api/knowledge/' + card_id + '/review', json={'remembered': True}, headers=one)
    assert counts()['today_due'] == 0

    # 把到期日改到昨天（逾期未复习）→ 计入今日待复习
    past = (timeutil.shanghai_now() - timedelta(days=1)).astimezone().isoformat()
    with client.application.app_context():
        con = get_db()
        con.execute("UPDATE knowledge_reviews SET next_review_at=? WHERE card_id=?", (past, card_id))
        con.commit()
    after = counts()
    assert after['today_due'] == 1 and after['learning'] == 1


def _seed_materials(client, cid, n_materials=4, n_chunks=20):
    """直插资料与切片：模拟长资料章节（旧实现只抽 ~18 片，必然漏内容）。"""
    from data.db import get_db
    with client.application.app_context():
        con = get_db()
        for mi in range(n_materials):
            mid = f'm{mi}'
            con.execute(
                'INSERT INTO materials (id,chapter_id,filename,original_name,file_type,size_bytes,'
                'is_deleted,chunk_count,parse_status,created_at,status)'
                ' VALUES (?,?,?,?,?,?,0,?,?,?,?)',
                (mid, cid, mid + '.md', f'资料{mi}.md', 'md', 10, n_chunks, 'parsed',
                 f'2026-09-0{mi + 1}', 'published'),
            )
            for ci in range(n_chunks):
                con.execute(
                    'INSERT INTO chunks (id,material_id,chapter_id,chunk_idx,text,created_at)'
                    ' VALUES (?,?,?,?,?,?)',
                    (f'{mid}c{ci}', mid, cid, ci, f'资料{mi}第{ci}段考点内容', '2026-09-01'),
                )
        con.commit()


def test_chapter_text_covers_every_material_and_chunk(client, teacher_headers):
    """卡片生成输入必须覆盖全章每份资料的每一段，而不是只抽样 18 个切片。"""
    cid = _chapter(client, teacher_headers)
    _seed_materials(client, cid, n_materials=4, n_chunks=20)
    with client.application.app_context():
        text = knowledge._chapter_text(cid)
    assert len(text) > 0
    for mi in range(4):
        assert f'资料{mi}.md' in text, '每份资料都要出现在提示词里'
        assert f'资料{mi}第0段考点内容' in text
        assert f'资料{mi}第19段考点内容' in text, '资料的末段也要被投喂，不能被抽样截断'
    assert '（本章暂无解析出的资料切片）' not in text


def test_generate_cards_prompt_demands_fine_grained_coverage(client, teacher_headers, monkeypatch):
    """提示词必须明确要求穷尽式细粒度抽取（覆盖一次投诉的根因）。"""
    from ai import agents
    cid = _chapter(client, teacher_headers)
    _seed_materials(client, cid, n_materials=2, n_chunks=5)
    seen = {}

    def fake(system):
        seen['system'] = system
        return [{'front': '考点一', 'back': '答案一', 'sub_concept': '小节一'},
                {'front': '考点一', 'back': '重复', 'sub_concept': '小节一'},
                {'front': '', 'back': '无正面', 'sub_concept': 'x'}]

    monkeypatch.setattr(agents, 'knowledge_generate', fake)
    with client.application.app_context():
        cards = knowledge.generate_knowledge_cards([cid])
    assert [c['front'] for c in cards] == ['考点一'], '重复与空正面都要被过滤'
    assert '一个考点一张卡片' in seen['system']
    assert '目标 ≥40 张' in seen['system'], '张数下限（v2.7.5 起为「目标」，非硬指标）'
    assert '资料0.md' in seen['system']
    # v2.7.5：价值门槛必须对每一次生成一律适用，且张数让位于价值门槛（KNOW-010⑤⑥）
    assert '对每一次生成一律适用' in seen['system']
    assert '张数下限让位于价值门槛' in seen['system']
    for kw in ('课程元信息', '纯数值记忆', '课件代码实现细节', '纯清单罗列',
               '学习路径', '课程定位'):
        assert kw in seen['system'], f'价值门槛必须点名禁产：{kw}'


def test_rebuild_script_prompt_shares_value_bar():
    """离线批量脚本的提示词必须与在线路径同一价值门槛（v2.7.5 补的真旁路）。

    背景：v2.7.4 只改了 `prompts.KNOWLEDGE_SYSTEM`，而 `scripts/rebuild_cards.py`
    的 `SYSTEM_TMPL` 仍写「拆成**应试级**知识卡片」+「凡是能出选择题的细节
    （数字、专有名词、模块名、顺序、比例、阈值、年份、倍数）都必须单独成卡」——
    该脚本是「批量重做章节 / --fill-orphans 补无卡切片」的入口，未来章节做重建
    或补卡时会照旧批量产低价值卡。本用例把这份契约钉死：两条生成路径必须同门槛。
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    src = (root / 'scripts' / 'rebuild_cards.py').read_text(encoding='utf-8')
    marker = 'SYSTEM_TMPL = """'
    head = src.index(marker) + len(marker)
    tpl = src[head:src.index('"""', head)]
    assert '理解型' in tpl, '离线路径必须是「理解型」口径'
    for kw in ('课程元信息', '纯数值记忆', '课件代码实现细节', '纯清单罗列'):
        assert kw in tpl, f'离线生成路径也必须禁产：{kw}'
    assert '学习路径' in tpl and '课程定位' in tpl, '离线路径同样要禁课程定位/学习路径'
    for banned in ('应试级', '必须单独成卡'):
        assert banned not in tpl, f'离线路径不得残留旧口径：{banned}'
