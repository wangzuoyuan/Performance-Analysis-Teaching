"""备份/恢复与本周关注的测试。"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_backup_list_download(client):
    r = client.post("/api/backup")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] and body["filename"].endswith(".zip")
    assert body["size"] > 0

    listing = client.get("/api/backups").json()
    assert any(b["filename"] == body["filename"] for b in listing)

    # 下载该备份应为 zip
    dl = client.get(f"/api/backup/{body['filename']}/download")
    assert dl.status_code == 200
    assert dl.content[:2] == b"PK"  # zip 魔数

    # 清理刚生成的测试备份
    backup_dir = os.path.expanduser("~/.exam-tracker-backups")
    path = os.path.join(backup_dir, body["filename"])
    if os.path.exists(path):
        os.remove(path)


def test_restore_missing_file(client):
    r = client.post("/api/restore", json={"filename": "不存在-99999999.zip"})
    assert r.status_code == 404


def test_weekly_focus_shape(client):
    r = client.get("/api/weekly-focus?class_num=6")
    assert r.status_code == 200
    body = r.json()
    assert "students" in body and "week" in body
    for s in body["students"]:
        assert "student_id" in s and "name" in s and isinstance(s["reasons"], list)
