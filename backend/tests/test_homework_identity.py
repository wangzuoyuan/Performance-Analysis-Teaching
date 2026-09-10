"""作业按「人」聚合（读时身份展开）的回归测试。

覆盖：
- 已建链旧号（g<年级>- 命名空间学号）下的缺交记录与新号合并为一人
- 复用号成员（无链）绝不并入他人
- 未建链离校者的 g<年级>- 行不出现在任何聚合
- _anon: 占位成员保持独立组
- 旧号下同日请假抑制该缺交
- 预警连击跨学号归并到代表成员学号
- student_summary 按人展开、非成员 sid 仍拒绝
- 花名册 record_count 按人合计
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base, ClassRoster, HomeworkRecord, HomeworkSemester, SpecialRecord,
    StudentAlias, StudentIdentity, Teacher, TeachingClass, TeachingClassMember,
)
from app.homework.service import kpi, rankings, student_summary, subjects, warnings
from app.main import app
from tests.conftest import seed_minimal_exam_scope


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(Teacher(subject="物理", name="测试教师"))
    db.commit()
    return db


def record(db, sid, day, status="缺交", subject="物理"):
    db.add(HomeworkRecord(
        student_id=sid, date=day, subject=subject,
        submission_status=status,
    ))


def seed_identity_scope(db):
    """成员 M=7250606（旧号 g1-7250610 已建链）、R=7250610（复用号、无链）。"""
    ident = StudentIdentity(display_name="刘某")
    db.add(ident)
    db.flush()
    db.add_all([
        ClassRoster(student_id="7250606", name="刘某", excluded=0),
        ClassRoster(student_id="7250610", name="石某", excluded=0),
        TeachingClass(id=1, grade=2, label="物A1", subject="物理", kind="教学", sort_order=1),
        TeachingClassMember(teaching_class_id=1, student_id="7250606"),
        TeachingClassMember(teaching_class_id=1, student_id="7250610"),
        StudentAlias(student_id="7250606", identity_id=ident.id, link_source="test"),
        StudentAlias(student_id="g1-7250610", identity_id=ident.id, link_source="test"),
        HomeworkSemester(
            id=1, name="测试学期", start_date="2026-03-01",
            end_date="2026-07-31", is_current=1,
        ),
    ])
    db.commit()


def test_linked_old_sid_merges_into_member():
    db = make_db()
    seed_identity_scope(db)
    record(db, "7250606", "2026-03-02")
    record(db, "7250606", "2026-03-03")
    record(db, "g1-7250610", "2026-03-05")
    record(db, "g1-7250610", "2026-03-06")
    db.commit()
    k = kpi(db, "2026-03-01", "2026-03-31")
    assert k["total_misses"] == 4
    top = {x["student_id"]: x["count"] for x in k["top_students"]}
    assert top == {"7250606": 4}

    rk = rankings(db, "2026-03-01", "2026-03-31")
    assert {s["student_id"]: s["count"] for s in rk["students"]} == {"7250606": 4}
    assert rk["names"] == ["刘某"]

    subs = subjects(db, "2026-03-01", "2026-03-31")
    detail_students = {s["student_id"] for s in subs[0]["students"]}
    assert detail_students == {"7250606"}


def test_reused_id_member_stays_separate():
    db = make_db()
    seed_identity_scope(db)
    record(db, "7250606", "2026-03-02")
    record(db, "g1-7250610", "2026-03-03")
    record(db, "7250610", "2026-03-04")  # 复用号成员石某，与刘某无关
    db.commit()
    rk = rankings(db, "2026-03-01", "2026-03-31")
    got = {s["student_id"]: s["count"] for s in rk["students"]}
    assert got == {"7250606": 2, "7250610": 1}


def test_unlinked_leaver_rows_excluded():
    db = make_db()
    seed_identity_scope(db)
    record(db, "7250606", "2026-03-02")
    record(db, "g1-7250699", "2026-03-03")  # 离校者、未建链
    db.commit()
    k = kpi(db, "2026-03-01", "2026-03-31")
    assert k["total_misses"] == 1
    assert {x["student_id"] for x in k["top_students"]} == {"7250606"}
    rk = rankings(db, "2026-03-01", "2026-03-31")
    assert {s["student_id"] for s in rk["students"]} == {"7250606"}


def test_anon_placeholder_keeps_own_group():
    db = make_db()
    seed_identity_scope(db)
    db.add(TeachingClassMember(
        teaching_class_id=1, student_id="_anon:1:王小明", name="王小明",
    ))
    db.add(ClassRoster(student_id="_anon:1:王小明", name="王小明", excluded=0))
    record(db, "_anon:1:王小明", "2026-03-05")
    record(db, "7250606", "2026-03-02")
    db.commit()
    rk = rankings(db, "2026-03-01", "2026-03-31")
    got = {s["student_id"]: s["count"] for s in rk["students"]}
    assert got == {"7250606": 1, "_anon:1:王小明": 1}


def test_leave_under_old_sid_suppresses_miss():
    db = make_db()
    seed_identity_scope(db)
    record(db, "g1-7250610", "2026-03-05")
    db.add(SpecialRecord(
        student_id="g1-7250610", date="2026-03-05", type="请假",
    ))
    record(db, "7250606", "2026-03-06")
    db.commit()
    k = kpi(db, "2026-03-01", "2026-03-31")
    assert k["total_misses"] == 1  # 03-05 请假抑制


def test_warnings_streak_across_sids():
    db = make_db()
    seed_identity_scope(db)
    for day in ("2026-03-05", "2026-03-06"):
        record(db, "g1-7250610", day)
    record(db, "7250606", "2026-03-09")
    db.commit()
    w = warnings(db, "2026-03-01", "2026-03-31")
    assert {x["student_id"] for x in w["serious"]} == {"7250606"}
    assert w["serious"][0]["streak"] == 3
    assert w["serious"][0]["dates"] == ["2026-03-05", "2026-03-06", "2026-03-09"]


def test_student_summary_person_expanded():
    db = make_db()
    seed_identity_scope(db)
    record(db, "g1-7250610", "2026-03-05")
    record(db, "7250606", "2026-03-09")
    record(db, "g1-7250699", "2026-03-10")  # 离校者，不计入
    db.commit()
    result = student_summary(db, student_id="7250606")
    assert result["total_misses"] == 2
    assert result["student"]["student_id"] == "7250606"

    # 非成员 sid 仍被拒绝（路由层守卫；服务层无花名册行找不到人）
    result2 = student_summary(db, student_id="g1-7250699")
    assert "error" in result2


def test_roster_record_count_person_total():
    cleanup = seed_minimal_exam_scope(member_ids=("tapi-s1", "tapi-s2"))
    try:
        from app.db.models import SessionLocal, TeachingClass

        db = SessionLocal()
        try:
            tc_id = db.query(TeachingClass.id).filter(
                TeachingClass.label == "tapi-scope"
            ).scalar()
            ident = StudentIdentity(display_name="测试一")
            db.add(ident)
            db.flush()
            db.add_all([
                ClassRoster(student_id="tapi-s1", name="测试一", excluded=0),
                ClassRoster(student_id="tapi-s2", name="测试二", excluded=0),
                StudentAlias(student_id="tapi-s1", identity_id=ident.id,
                             link_source="test"),
                StudentAlias(student_id="g1-tapi-old", identity_id=ident.id,
                             link_source="test"),
                HomeworkRecord(student_id="tapi-s1", date="2026-03-05",
                               subject="物理", submission_status="缺交"),
                HomeworkRecord(student_id="g1-tapi-old", date="2026-03-06",
                               subject="物理", submission_status="缺交"),
            ])
            db.commit()
        finally:
            db.close()

        client = TestClient(app)
        r = client.get(f"/api/homework/roster?teaching_class_id={tc_id}")
        assert r.status_code == 200, r.text
        rows = {x["student_id"]: x["record_count"] for x in r.json()}
        assert rows["tapi-s1"] == 2  # 本人新号 1 + 旧号 1
        assert rows["tapi-s2"] == 0
        assert "g1-tapi-old" not in rows
    finally:
        cleanup()
