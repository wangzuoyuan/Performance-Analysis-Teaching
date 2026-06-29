"""学生成长/谈话档案路由测试（真实 DB，自建自清理，不留脏数据）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

SID = "7250636"  # 吴辰轩（class 6 真实学号）


@pytest.fixture
def client():
    return TestClient(app)


def test_note_crud_and_followup(client):
    # 建
    r = client.post(
        "/api/notes",
        json={"student_id": SID, "category": "谈话", "content": "测试谈话内容", "follow_up": "一周后再谈"},
    )
    assert r.status_code == 200
    note = r.json()
    nid = note["id"]
    assert note["category"] == "谈话"
    assert note["follow_up_done"] is False

    # 查
    rows = client.get(f"/api/notes/{SID}").json()
    assert any(n["id"] == nid for n in rows)

    # 改：勾选跟进完成
    r = client.put(f"/api/notes/{nid}", json={"follow_up_done": True})
    assert r.status_code == 200
    assert r.json()["follow_up_done"] is True

    # 非法分类回落到「其他」
    r = client.put(f"/api/notes/{nid}", json={"category": "乱填"})
    assert r.json()["category"] == "谈话"  # 非法值被忽略，保留原值

    # 删（清理）
    assert client.delete(f"/api/notes/{nid}").status_code == 200
    assert all(n["id"] != nid for n in client.get(f"/api/notes/{SID}").json())


def test_empty_content_rejected(client):
    r = client.post("/api/notes", json={"student_id": SID, "content": "   "})
    assert r.status_code == 400
