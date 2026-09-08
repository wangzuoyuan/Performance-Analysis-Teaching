"""作业模块路由冒烟测试。

在 fresh 测试库创建唯一任教学科和合法教学班。仅验证端点可访问、返回结构正确，
并跑通「录入 → 查询」闭环，不读取或修改真实 ~/.exam-tracker 数据。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import seed_minimal_exam_scope


@pytest.fixture
def client():
    cleanup = seed_minimal_exam_scope()
    try:
        yield TestClient(app)
    finally:
        cleanup()


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


def test_correlation_shape(client, request):
    # 单学科化：class_num 不再允许（400）；默认范围（全部教学班并集）
    cleanup = seed_minimal_exam_scope()
    request.addfinalizer(cleanup)
    r = client.get("/api/homework/correlation?class_num=6")
    assert r.status_code == 400
    r = client.get("/api/homework/correlation")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and isinstance(body["rows"], list)
    assert body["y_field"] == "subject_rank"


def test_correlation_subject_mode(client, request):
    # subject 兼容但只允许等于当前任教学科；y_field 统一为 subject_rank
    cleanup = seed_minimal_exam_scope()
    request.addfinalizer(cleanup)
    r = client.get("/api/homework/correlation")
    assert r.status_code == 200
    body = r.json()
    assert body["y_field"] == "subject_rank"
    assert "teaching_subject" in body


def test_correlation_subjects_ranking(client, request):
    cleanup = seed_minimal_exam_scope()
    request.addfinalizer(cleanup)
    r = client.get("/api/homework/correlation/subjects?class_num=6")
    assert r.status_code == 400
    r = client.get("/api/homework/correlation/subjects")
    assert r.status_code == 200
    body = r.json()
    assert "rankings" in body
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
    if not roster:
        pytest.skip("空库没有可执行往返测试的花名册学生")
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


def _fix_semester(db_session):
    """固定学期区间，避免 derive_semester 随运行日期漂移影响 warnings 口径。"""
    from app.db.models import HomeworkSemester
    db = db_session
    row = db.query(HomeworkSemester).filter(
        HomeworkSemester.name == "测试学期",
        HomeworkSemester.start_date == "2026-09-01",
        HomeworkSemester.end_date == "2026-09-30",
    ).first()
    if row:
        row.is_current = 1
    else:
        db.add(HomeworkSemester(name="测试学期", start_date="2026-09-01",
                                end_date="2026-09-30", is_current=1))
    db.commit()


def test_full_submission_expands_and_breaks_streak(client, db_session):
    """「校本作业：全交」展开为范围内每人一条「已交」：缺-交-缺 不再被
    连续缺交预警误判为连续。"""
    from app.db.models import (
        ClassRoster, HomeworkRecord, SpecialRecord,
    )
    _fix_semester(db_session)
    db = db_session
    db.query(HomeworkRecord).delete()
    db.query(SpecialRecord).delete()
    db.commit()

    def _hits(body, sid="tapi-s1"):
        return [w for w in body["serious"] + body["warning"] if w["student_id"] == sid]

    # ① 周一 tapi-s1 缺交
    db.add(HomeworkRecord(student_id="tapi-s1", date="2026-09-07",
                          subject="校本作业", submission_status="缺交"))
    db.commit()

    # ② 周二全交：范围内每人一条「已交」，占位成员补建花名册行
    r = client.post("/api/homework/records", json={
        "raw_text": "校本作业：全交", "date": "2026-09-08", "mode": "by_subject"})
    assert r.status_code == 200
    assert r.json()["added_count"] == 2
    for sid in ("tapi-s1", "tapi-s2"):
        assert db.query(ClassRoster).filter(ClassRoster.student_id == sid).first()
    full_rows = db.query(HomeworkRecord).filter(
        HomeworkRecord.date == "2026-09-08", HomeworkRecord.subject == "校本作业").all()
    assert {row.student_id for row in full_rows} == {"tapi-s1", "tapi-s2"}
    assert all(row.submission_status == "已交" for row in full_rows)

    # ③ 周三 tapi-s1 又缺交 → 缺-交-缺：周二「已交」打断 streak，不预警
    db.add(HomeworkRecord(student_id="tapi-s1", date="2026-09-09",
                          subject="校本作业", submission_status="缺交"))
    db.commit()
    body = client.get("/api/homework/warnings").json()
    assert not _hits(body)

    # ④ 幂等：同一收交日换说法重复录入不重复计数
    r = client.post("/api/homework/records", json={
        "raw_text": "校本作业：齐", "date": "2026-09-08", "mode": "by_subject"})
    assert r.json()["added_count"] == 0

    # ⑤ 跳过规则：当天已有记录的不覆盖、请假的不算已交
    db.add(HomeworkRecord(student_id="tapi-s1", date="2026-09-10",
                          subject="校本作业", submission_status="缺交"))
    db.add(SpecialRecord(student_id="tapi-s2", date="2026-09-10", type="请假"))
    db.commit()
    r = client.post("/api/homework/records", json={
        "raw_text": "校本作业：全交", "date": "2026-09-10", "mode": "by_subject"})
    assert r.json()["added_count"] == 0

    # ⑥ 对照：删掉周二的已交记录（旧行为）→ 缺-交-缺 被误判为连续（≥2 次）
    for row in full_rows:
        db.delete(row)
    db.commit()
    body = client.get("/api/homework/warnings").json()
    assert any(w["streak"] >= 2 for w in _hits(body))


def test_smart_input_full_submission_preview_and_confirm(client, db_session):
    """智能录入「校本作业：全交」：预览整行摘要、确认后展开落库。"""
    from app.db.models import HomeworkRecord, TeachingClass
    _fix_semester(db_session)
    db = db_session
    tc = db.query(TeachingClass).filter(TeachingClass.label == "tapi-scope").first()
    assert tc is not None

    payload = {"raw_text": "校本作业：全交", "date": "2026-09-11",
               "teaching_class_id": tc.id}
    r = client.post("/api/homework/smart-input", json={**payload, "confirm": False})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert len(body["errors"]) == 0
    assert len(body["preview"]) == 1
    item = body["preview"][0]
    assert item["full_submission"] is True
    assert item["subject"] == "校本作业"
    assert item["member_count"] == 2
    # 预览不落库
    assert db.query(HomeworkRecord).filter(HomeworkRecord.date == "2026-09-11").count() == 0

    r = client.post("/api/homework/smart-input", json={**payload, "confirm": True})
    assert r.status_code == 200
    assert r.json()["added_count"] == 2
    rows = db.query(HomeworkRecord).filter(
        HomeworkRecord.date == "2026-09-11", HomeworkRecord.subject == "校本作业").all()
    assert {row.student_id for row in rows} == {"tapi-s1", "tapi-s2"}
    assert all(row.submission_status == "已交" for row in rows)
