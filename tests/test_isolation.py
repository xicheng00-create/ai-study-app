"""数据隔离测试（F9 / AUTH-004 / MAT-007）：学生 A 读学生 B → 403/空。"""
from conftest import login, make_student


def _create_student_conversation(client, token, chapter_id=None):
    h = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/conversations",
                       json={"title": "私有对话", "chapter_id": chapter_id}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]


def test_student_a_cannot_read_student_b_conversation(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    make_student(client, teacher_headers, "bob")
    alice = login(client, "alice", "student123")
    bob = login(client, "bob", "student123")

    conv_b = _create_student_conversation(client, bob)
    # 学生 A 直接读学生 B 的对话 → 403
    resp = client.get(f"/api/conversations/{conv_b}",
                      headers={"Authorization": f"Bearer {alice}"})
    assert resp.status_code == 403
    # 学生 A 的对话列表为空，不包含 B 的对话
    resp = client.get("/api/conversations", headers={"Authorization": f"Bearer {alice}"})
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.get_json()["data"]["conversations"]]
    assert conv_b not in ids


def test_student_cannot_upload_material(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    import io
    resp = client.post(
        "/api/materials/upload",
        data={"chapter_id": "x", "file": (io.BytesIO(b"data"), "a.md")},
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert resp.status_code == 403


def test_student_cannot_create_chapter(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    resp = client.post("/api/chapters", json={"name": "越权章节"},
                       headers={"Authorization": f"Bearer {alice}"})
    assert resp.status_code == 403


def test_student_cannot_access_teacher_overview(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    resp = client.get("/api/teacher/overview",
                      headers={"Authorization": f"Bearer {alice}"})
    assert resp.status_code == 403


def test_teacher_overview_only_teacher(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    make_student(client, teacher_headers, "bob")
    resp = client.get("/api/teacher/overview", headers=teacher_headers)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["student_count"] == 2
