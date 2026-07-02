from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base, ClassRoster, HomeworkRecord, HomeworkSemester, SpecialRecord,
    TeachingClass, TeachingClassMember,
)
from app.homework.parser import parse_name_action
from app.homework.service import dashboard, warnings


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_scope(db):
    db.add_all([
        ClassRoster(student_id="A1", name="同名", excluded=0),
        ClassRoster(student_id="A2", name="同名", excluded=0),
        ClassRoster(student_id="B1", name="乙", excluded=0),
        ClassRoster(student_id="X1", name="排除", excluded=1),
        TeachingClass(id=1, grade=2, label="物A1", kind="教学", sort_order=1),
        TeachingClass(id=2, grade=2, label="物A2", kind="教学", sort_order=2),
        TeachingClassMember(teaching_class_id=1, student_id="A1"),
        TeachingClassMember(teaching_class_id=1, student_id="A2"),
        TeachingClassMember(teaching_class_id=1, student_id="X1"),
        TeachingClassMember(teaching_class_id=2, student_id="A1"),
        TeachingClassMember(teaching_class_id=2, student_id="B1"),
        HomeworkSemester(
            id=1, name="测试学期", start_date="2026-03-01",
            end_date="2026-07-01", is_current=1,
        ),
    ])
    db.commit()


def record(db, sid, day, status="缺交", subject="物理", evaluation=None):
    db.add(HomeworkRecord(
        student_id=sid, date=day, subject=subject,
        submission_status=status, evaluation=evaluation,
    ))


def test_all_scope_is_configured_union_and_deduplicated():
    db = make_db()
    seed_scope(db)
    record(db, "A1", "2026-03-01")
    record(db, "B1", "2026-03-01")
    record(db, "X1", "2026-03-01")
    db.commit()
    result = dashboard(db, "2026-03-01", "2026-03-31")
    assert result["scope"]["member_count"] == 3
    assert result["kpi"]["total_misses"] == 2
    assert {x["student_id"] for x in result["rankings"]["missing"]} == {"A1", "B1"}


def test_consecutive_two_yellow_three_red_and_submission_breaks():
    db = make_db()
    seed_scope(db)
    for day in ("2026-03-02", "2026-03-03"):
        record(db, "A1", day)
    for day in ("2026-03-01", "2026-03-02", "2026-03-03"):
        record(db, "B1", day)
    db.commit()
    result = warnings(db, "2026-03-01", "2026-03-31")
    assert {x["student_id"] for x in result["warning"]} == {"A1"}
    assert {x["student_id"] for x in result["serious"]} == {"B1"}

    record(db, "B1", "2026-03-04", status="已交")
    db.commit()
    result = warnings(db, "2026-03-01", "2026-03-31")
    assert "B1" not in {x["student_id"] for x in result["serious"]}


def test_leave_excluded_and_dashboard_awards():
    db = make_db()
    seed_scope(db)
    record(db, "A1", "2026-03-01")
    db.add(SpecialRecord(student_id="A1", date="2026-03-01", type="请假"))
    for day, evaluation in (
        ("2026-06-20", "优秀"), ("2026-06-21", "认真"), ("2026-06-22", "进步"),
    ):
        record(db, "A2", day, status="已交", evaluation=evaluation)
    record(db, "A1", "2026-06-20", status="已交", evaluation="马虎")
    record(db, "A1", "2026-06-21", status="已交", evaluation="潦草")
    for day in ("2026-03-02", "2026-03-03", "2026-03-04"):
        db.add(SpecialRecord(student_id="B1", date=day, type="忘带"))
    db.commit()
    result = dashboard(db, "2026-03-01", "2026-07-01")
    assert result["kpi"]["total_misses"] == 0
    assert {x["student_id"] for x in result["honors"]["excellent"]} == {"A2"}
    assert {x["student_id"] for x in result["warnings"]["forgot"]} == {"B1"}
    assert {x["student_id"] for x in result["warnings"]["quality"]} == {"A1"}
    assert result["submission_rates"]
    assert result["semester_compare"][0]["name"] == "测试学期"


def test_name_action_parser_supports_status_evaluation_and_special():
    names = {"张三"}
    missing = parse_name_action("张三数学缺交订正", names)
    assert missing["submission_status"] == "缺交"
    assert missing["subject"] == "数学"
    excellent = parse_name_action("张三物理优秀", names)
    assert excellent["submission_status"] == "已交"
    assert excellent["evaluation"] == "优秀"
    forgot = parse_name_action("张三忘带英语作业", names)
    assert forgot["special_type"] == "忘带"
