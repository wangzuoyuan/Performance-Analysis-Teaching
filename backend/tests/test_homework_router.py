"""作业模块路由冒烟测试。

使用真实 ~/.exam-tracker/db.sqlite（迁移后应已有作业数据）。仅验证端点
可访问、返回结构正确，并跑通「录入 → 查询 → 删除」闭环，不污染统计口径
（用一个不存在的占位学生触发"找不到学生"，再用真实路径校验结构）。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_kpi_shape(client):
    r = client.get("/api/homework/kpi")
    assert r.status_code == 200
    body = r.json()
    assert "total_misses" in body
    assert "worst_subject" in body
    assert "top_students" in body


def test_trend_subjects_rankings(client):
    for path in ("/api/homework/trend", "/api/homework/subjects", "/api/homework/rankings"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_warnings_shape(client):
    r = client.get("/api/homework/warnings")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"serious", "warning", "counts"}


def test_correlation_shape(client):
    r = client.get("/api/homework/correlation?class_num=6")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and isinstance(body["rows"], list)
    assert body["y_field"] == "xueji_rank"


def test_correlation_subject_mode(client):
    r = client.get("/api/homework/correlation?class_num=6&subject=数学")
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "数学"
    assert body["y_field"] == "grade_percentile"


def test_correlation_subjects_ranking(client):
    r = client.get("/api/homework/correlation/subjects?class_num=6")
    assert r.status_code == 200
    body = r.json()
    assert "rankings" in body
    subjects = {x["subject"] for x in body["rankings"]}
    assert "数学" in subjects
    for row in body["rankings"]:
        assert "r" in row and "n" in row


def test_warnings_have_student_id(client):
    r = client.get("/api/homework/warnings")
    assert r.status_code == 200
    body = r.json()
    for w in body["serious"] + body["warning"]:
        assert "student_id" in w


def test_toggle_excluded_roundtrip(client):
    """对某真实学生切两次 excluded，保证最终状态还原，不污染统计。"""
    roster = client.get("/api/homework/roster").json()
    assert roster, "花名册为空，先跑迁移"
    sid = roster[0]["student_id"]
    before = roster[0]["excluded"]
    r1 = client.put(f"/api/homework/roster/{sid}/toggle-excluded")
    assert r1.status_code == 200
    assert r1.json()["excluded"] != before
    r2 = client.put(f"/api/homework/roster/{sid}/toggle-excluded")
    assert r2.json()["excluded"] == before


def test_pearson_known_values():
    from app.homework.service import _pearson
    # 完全正相关
    assert _pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    # 完全负相关
    assert _pearson([1, 2, 3, 4], [8, 6, 4, 2]) == -1.0
    # 样本不足
    assert _pearson([1, 2], [2, 4]) is None
    # 零方差
    assert _pearson([1, 1, 1], [1, 2, 3]) is None


def test_semester_roundtrip(client):
    r = client.get("/api/homework/semester")
    assert r.status_code == 200
    assert "semester_start" in r.json()


def test_add_record_unknown_student_reports_error(client):
    """录入一个不存在的学生，应返回 success 但 errors 非空、added_count=0，
    不向真实统计写入脏数据。"""
    r = client.post(
        "/api/homework/records",
        json={"raw_text": "查无此人测试XYZ：数学", "date": "2026-03-02", "mode": "by_student"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["added_count"] == 0
    assert body["errors"]
