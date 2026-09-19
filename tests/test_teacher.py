"""教师端知识卡片核查（REQ-KNOW-005）：只读汇总 + 单章明细 + 角色隔离。"""
from ai import knowledge  # noqa: F401  (monkeypatch 目标)
from conftest import login, make_student


def _chapter(client, headers, name='第2周·第1节 · AIPM vs 传统 PM'):
    return client.post('/api/chapters', json={'name': name}, headers=headers).get_json()['data']['id']


def _seed_cards(client, teacher_headers, cid):
    """用假生成器落 3 张卡，覆盖 2 个主题（不调真实 LLM）。

    注意 /api/knowledge/generate 是**学生专属**（教师调用 403），故用学生身份落卡。
    """
    import ai.knowledge as k
    make_student(client, teacher_headers, 'kcseed')
    sh = {'Authorization': 'Bearer ' + login(client, 'kcseed', 'student123')}
    orig = k.generate_knowledge_cards
    k.generate_knowledge_cards = lambda ids: [
        {'front': 'RAG 全称', 'back': '检索增强生成', 'sub_concept': 'RAG'},
        {'front': '向量检索步骤', 'back': '嵌入→检索→重排', 'sub_concept': 'RAG'},
        {'front': 'AI PM 与传统 PM 差异', 'back': '不确定性管理', 'sub_concept': 'PM 能力'},
    ]
    try:
        resp = client.post('/api/knowledge/generate', json={'chapter_ids': [cid]}, headers=sh)
        assert resp.status_code == 200, resp.get_json()
    finally:
        k.generate_knowledge_cards = orig


def test_teacher_knowledge_summary_and_detail(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    _seed_cards(client, teacher_headers, cid)

    summary = client.get('/api/teacher/knowledge', headers=teacher_headers)
    assert summary.status_code == 200
    row = [c for c in summary.get_json()['data']['chapters'] if c['id'] == cid][0]
    assert row['cards'] == 3 and row['sub_concepts'] == 2
    assert row['chunks'] >= 0 and row['orphan_chunks'] >= 0

    detail = client.get('/api/teacher/knowledge/' + cid, headers=teacher_headers)
    assert detail.status_code == 200
    data = detail.get_json()['data']
    assert data['card_total'] == 3
    assert sorted(g['sub_concept'] for g in data['groups']) == ['PM 能力', 'RAG']
    card = data['groups'][0]['cards'][0]
    assert set(card) >= {'id', 'front', 'back', 'source_chunk_id',
                         'source_material', 'source_snippet'}


def test_teacher_knowledge_unknown_chapter_404(client, teacher_headers):
    assert client.get('/api/teacher/knowledge/nope', headers=teacher_headers).status_code == 404


def test_teacher_knowledge_student_forbidden(client, teacher_headers):
    """学生不得访问教师端核查接口（role_required 挡在业务逻辑之前）。"""
    make_student(client, teacher_headers, 'kcstudent')
    sh = {'Authorization': 'Bearer ' + login(client, 'kcstudent', 'student123')}
    assert client.get('/api/teacher/knowledge', headers=sh).status_code == 403
    assert client.get('/api/teacher/knowledge/any', headers=sh).status_code == 403
