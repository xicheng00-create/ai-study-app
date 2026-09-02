"""视频课相关推荐测试（VIDEO-003 / CHAT-010）：确定性匹配、不触 RAG/chunks。"""
import ast
import inspect
import json

from data import models


def _seed_video_link_data(client):
    with client.application.app_context():
        con = __import__("data.db", fromlist=["get_db"]).get_db()
        for cid, name in (("c1", "章1"), ("c2", "章2")):
            con.execute(
                "INSERT INTO chapters (id, folder, name, order_no, status, created_by, created_at)"
                " VALUES (?, '', ?, 0, 'published', NULL, ?)",
                (cid, name, models.utcnow()),
            )
        con.execute(
            "INSERT INTO sessions (id, week_no, session_no, title, chapter_ids, concept_tags,"
            " status, created_at) VALUES ('s1', 1, 1, 'S1', ?, ?, 'published', ?)",
            (json.dumps(["c1"]), json.dumps(["transformer"]), models.utcnow()),
        )
        con.execute(
            "INSERT INTO video_resources (id, title, url, platform, week_no, session_no,"
            " concept_tags, order_no, status, created_at)"
            " VALUES ('v1', 'Transformer 课', 'https://x/v1', 'bilibili', 1, 1, '[\"transformer\"]', 0, 'published', ?)",
            (models.utcnow(),),
        )
        con.execute(
            "INSERT INTO video_resources (id, title, url, platform, week_no, session_no,"
            " concept_tags, order_no, status, created_at)"
            " VALUES ('v2', '幻觉课', 'https://x/v2', 'ima', NULL, NULL, '[\"hallucination\"]', 1, 'published', ?)",
            (models.utcnow(),),
        )
        con.execute(
            "INSERT INTO video_resources (id, title, url, platform, week_no, session_no,"
            " concept_tags, order_no, status, created_at)"
            " VALUES ('v3', '草稿视频', 'https://x/v3', 'bilibili', 1, 1, '[\"transformer\"]', 2, 'draft', ?)",
            (models.utcnow(),),
        )
        con.commit()


def test_related_by_chapter_ids(client):
    _seed_video_link_data(client)
    from ai import video_link
    with client.application.app_context():
        out = video_link.retrieve_related_videos(chapter_ids=["c1"])
    assert [v["title"] for v in out] == ["Transformer 课"]


def test_related_by_concept_tags(client):
    _seed_video_link_data(client)
    from ai import video_link
    with client.application.app_context():
        out = video_link.retrieve_related_videos(concept_tags=["hallucination"])
    assert [v["title"] for v in out] == ["幻觉课"]


def test_draft_video_excluded_and_limit(client):
    _seed_video_link_data(client)
    from ai import video_link
    with client.application.app_context():
        out = video_link.retrieve_related_videos(chapter_ids=["c1"], concept_tags=["transformer"])
    # v1 命中（chapter + tag），v3 为 draft 被排除
    assert [v["title"] for v in out] == ["Transformer 课"]


def test_video_link_does_not_touch_rag_or_chunks(client):
    _seed_video_link_data(client)
    from ai import video_link
    # 模块 import 语句不含 rag（RAG 纯度红线，AST 级校验避开 docstring 误判）
    tree = ast.parse(inspect.getsource(video_link))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "rag" not in (node.module or "")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "rag" not in alias.name
    # 核心召回函数不触达 chunks 表
    fn_src = inspect.getsource(video_link.retrieve_related_videos)
    assert "chunks" not in fn_src
