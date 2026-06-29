"""教学班配置 API 回归测试（/api/teaching/*）。

测试自建自删（fixture 清理），不污染共享库。对应 03·§2 班级配置 API。
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_label(prefix: str = "tc") -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


@pytest.fixture
def make_class():
    created: list[int] = []

    def _make(grade: int = 2, label: str | None = None, kind: str = "教学", subject: str | None = None):
        label = label or _unique_label()
        r = client.post(
            "/api/teaching/classes",
            json={"grade": grade, "label": label, "kind": kind, "subject": subject},
        )
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
        return r.json()

    yield _make

    for tcid in created:
        client.delete(f"/api/teaching/classes/{tcid}")


def test_create_list_delete_class(make_class):
    tc = make_class(grade=2, kind="教学", subject="物理")
    assert tc["label"] and tc["id"]
    r = client.get("/api/teaching/classes?grade=2")
    ids = [c["id"] for c in r.json()["classes"]]
    assert tc["id"] in ids
    # 同年级同名应拒绝（409）
    dup = client.post("/api/teaching/classes", json={"grade": 2, "label": tc["label"], "kind": "教学"})
    assert dup.status_code == 409


def test_member_crud(make_class):
    tc = make_class()
    r = client.post(f"/api/teaching/classes/{tc['id']}/members", json={"student_ids": ["100", "101", "102"]})
    assert r.json()["added"] == 3
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert {m["student_id"] for m in members} == {"100", "101", "102"}
    # 移除单个
    client.delete(f"/api/teaching/classes/{tc['id']}/members/101")
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert {m["student_id"] for m in members} == {"100", "102"}


def test_import_states(make_class):
    tc = make_class()
    # 真实学号（≥5位数字）→ matched；未知姓名 → unmatched
    r = client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100001\n7100002\n不存在姓名"},
    )
    rep = r.json()
    matched_ids = {m["student_id"] for m in rep["matched"]}
    assert "7100001" in matched_ids and "7100002" in matched_ids
    assert any(u.get("token") == "不存在姓名" for u in rep["unmatched"])


def test_current_set_get_clear(make_class):
    tc = make_class()
    client.patch("/api/teaching/current", json={"teaching_class_id": tc["id"]})
    cur = client.get("/api/teaching/current").json()
    assert cur["teaching_class_id"] == tc["id"]
    assert cur["class"]["label"] == tc["label"]
    client.patch("/api/teaching/current", json={"teaching_class_id": None})
    assert client.get("/api/teaching/current").json()["teaching_class_id"] is None


def test_candidate_classes_ok():
    r = client.get("/api/teaching/candidate-classes?grade=2")
    assert r.status_code == 200
    body = r.json()
    assert "class_nums" in body and "class_labels" in body


def test_sync_by_class_num_requires_admin(make_class):
    # 教学班（非行政）按行政班号同步应 400
    tc = make_class(grade=2, kind="教学")
    r = client.post(f"/api/teaching/classes/{tc['id']}/sync-by-class-num")
    assert r.status_code == 400
