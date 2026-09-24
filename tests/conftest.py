"""pytest 公共 fixture：临时库 + 测试客户端（隔离真实 instance 库）。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """全局屏蔽真实 LLM：单测一律走兜底/桩，保证确定性、不产生真实 API 花费。

    config.py 的 DEEPSEEK_API_KEY 是「模块首次 import 时」绑定的类属性；验收/CI 会
    `set -a; source .env` 后再跑 pytest，此时 config 被 import 就已拿到真 key，
    于是批改（essay 三档）、每日建议等断言会随模型措辞随机失败。
    需要假 key 的测试自己 monkeypatch.setenv 覆盖即可（测试级覆盖在此之后生效）。
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")


@pytest.fixture(autouse=True)
def _isolate_usage_log(tmp_path, monkeypatch):
    """全局隔离 LLM 用量日志，避免测试写入真实 ~/.hermes/app-usage/aistudy.jsonl。"""
    monkeypatch.setenv("LLM_USAGE_LOG", str(tmp_path / "app-usage" / "aistudy.jsonl"))


@pytest.fixture(autouse=True)
def _isolate_card_gate_log(tmp_path, monkeypatch):
    """全局隔离卡片止血闸门审计日志，避免测试写入真实 instance/logs/card_gate.jsonl。

    在线写卡路径（knowledge.ensure_chapter_cards → cardgate.filter_new_cards → _audit）默认落
    生产审计日志；测试里 LLM 不可用必然走「降级全保留」，每次 pytest 都会往生产取证通道追加
    gate_degraded 噪声（2026-09-25 审计实测 99.2% 的行来自测试），使 KNOW-014 的告警通道失真。
    需要断言日志内容的测试（tests/test_card_gate.py）自己 setenv 覆盖即可，测试级覆盖在此之后生效。
    """
    monkeypatch.setenv("CARD_GATE_LOG", str(tmp_path / "card_gate.jsonl"))


@pytest.fixture(autouse=True)
def _stub_quizzer_source(monkeypatch):
    """出题链路打桩（v2.7.4：题源=知识卡片，无卡片或模型不出题则返回空）。

    v2.7.4 起出题不再有「通用模板兜底」，测评/练习的 API 测试若不造卡、不提供模型输出，
    draft/practice 只会返回「无卡片/生成失败」。此处统一打桩：任意章节都取得到卡片，
    模型按题型产出足量且同调用内唯一的题目；需要特定行为的测试可自行再覆盖。
    """
    from ai import agents, quizzer

    def fake_cards(chapter_ids, per_sub=3, max_cards=50):
        return [{"id": f"card-{cid}-{i}", "chapter_id": cid, "sub_concept": f"子概念{i}",
                 "front": f"{cid} 的知识点 {i} 是什么", "back": f"{cid} 的知识点 {i} 的解析"}
                for cid in chapter_ids for i in range(30)]

    counter = {"n": 0}

    def fake_generate(system):
        counter["n"] += 1
        base = counter["n"]
        out = []
        for qtype in ("choice", "bool"):
            for i in range(30):
                out.append({
                    "type": qtype,
                    "content": f"第{base}批-{qtype}-题{i}",
                    "options": ["正确", "错误"] if qtype == "bool" else ["A", "B", "C", "D"],
                    "answer": "0",
                    "reason": "",
                    "sub_concept": f"子概念{i}",
                })
        return out

    # 保留真实取卡函数：验取卡本身的用例（tests/test_quizzer.py）需要它真跑
    if not hasattr(quizzer, "_real_retrieve_cards"):
        quizzer._real_retrieve_cards = quizzer._retrieve_cards
    monkeypatch.setattr(quizzer, "_retrieve_cards", fake_cards)
    # 保留真实包装器：验用量账的用例（tests/test_usage_log.py）需要它真跑一遍
    if not hasattr(agents, "_real_quizzer_generate"):
        agents._real_quizzer_generate = agents.quizzer_generate
    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 测试专用临时库 + 禁用 LLM（走兜底，确定性）
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("TEACHER_USERNAME", "teacher")
    monkeypatch.setenv("TEACHER_PASSWORD", "teacher123")

    from app import create_app

    app = create_app("development")
    app.config["TESTING"] = True
    # 单测确定性：config.py 的类属性在「首次 import 时」就绑定了当时的 .env key，
    # 只在 os.environ 上 setenv 覆盖不到 current_app.config，而 agents._config 在应用上下文里
    # 优先读 current_app.config → 测试会真去打 DeepSeek，断言随模型措辞随机失败。
    # （其它测试文件在收集阶段 import ai/* 就会触发 config 导入，故必须在这里再兜一层）
    app.config["DEEPSEEK_API_KEY"] = ""
    return app.test_client()


def login(client, username, password):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["token"]


@pytest.fixture
def teacher_token(client):
    return login(client, "teacher", "teacher123")


@pytest.fixture
def teacher_headers(client, teacher_token):
    return {"Authorization": f"Bearer {teacher_token}"}


def make_student(client, teacher_headers, username, password="student123", display_name=None):
    resp = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "role": "student",
            "display_name": display_name or username.title(),
        },
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]
