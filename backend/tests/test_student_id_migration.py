"""跨届撞号迁移测试：高二重新编号撞历史旧学号的检测/改写/建链/幂等，
以及补录学号时的撞号防呆。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base, ClassRoster, Exam, StudentAlias, StudentIdentity, SubjectScore,
    Teacher, TeachingClass, TeachingClassMember, TotalScore,
)
from app.db.migrate_student_ids import (
    migrate_colliding_student_ids, strip_id_namespace,
)
from app.teaching.service import ConflictError, reassign_member_id


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(Teacher(subject="物理", name="测试教师"))
    db.commit()
    return db


def seed(db):
    """7250629 撞号：高一=刘梓烨，高二=孙仲仁（高二分班重新编号）。"""
    db.add_all([
        Exam(id=1, name="高一期末", grade=1, semester="下", exam_date="2025-06-20", exam_type="期末"),
        Exam(id=2, name="高二月考", grade=2, semester="上", exam_date="2026-09-01", exam_type="月考"),
        SubjectScore(exam_id=1, student_id="7250629", subject="物理", name="刘梓烨", raw_score=80),
        SubjectScore(exam_id=1, student_id="7250629", subject="化学", name="刘梓烨", raw_score=75),
        SubjectScore(exam_id=2, student_id="7250629", subject="物理", name="孙仲仁", raw_score=90),
        TotalScore(exam_id=1, student_id="7250629", total_type="主三门", total_score=240),
        TeachingClass(id=1, grade=2, label="物A1", subject="物理", kind="教学", sort_order=1),
        TeachingClassMember(teaching_class_id=1, student_id="7250629", name="孙仲仁", source="manual"),
        TeachingClassMember(teaching_class_id=1, student_id="2301001", name="刘梓烨", source="manual"),
        ClassRoster(student_id="2301001", name="刘梓烨", excluded=0),
    ])
    db.commit()


def score_rows(db, sid):
    return sorted(
        (r.subject, r.name) for r in db.query(SubjectScore).filter(
            SubjectScore.student_id == sid
        ).all()
    )


def test_rekey_and_auto_link():
    db = make_db()
    seed(db)
    stats = migrate_colliding_student_ids(db)
    assert stats["collisions"] == 1
    # 高一历史行改写为命名空间学号，高二行保留原号
    assert score_rows(db, "g1-7250629") == [("化学", "刘梓烨"), ("物理", "刘梓烨")]
    assert score_rows(db, "7250629") == [("物理", "孙仲仁")]
    # 旧总分行同批考试一并改指
    assert db.query(TotalScore).filter(
        TotalScore.student_id == "g1-7250629"
    ).count() == 1
    # 按姓名自动建链：g1-7250629 ↔ 2301001（高二成员里的刘梓烨）
    aliases = {
        a.student_id: a.identity_id
        for a in db.query(StudentAlias).all()
    }
    assert aliases["g1-7250629"] == aliases["2301001"]
    assert stats["linked"] == 1
    # 身份链生效后，同一人的学号集合覆盖两个学段
    from app.analysis.scope import student_ids_of_person
    assert student_ids_of_person(db, "2301001") == {"2301001", "g1-7250629"}


def test_idempotent():
    db = make_db()
    seed(db)
    migrate_colliding_student_ids(db)
    again = migrate_colliding_student_ids(db)
    assert again["collisions"] == 0
    assert again["rekeyed_rows"] == 0
    assert again["linked"] == 0


def test_member_name_decides_active_side():
    """成员/花名册姓名是高二者时，改写方向反转：高二的行成为死号。"""
    db = make_db()
    seed(db)
    # 成员表里 7250629 属刘梓烨（当前身份），孙仲仁另有新号
    db.query(TeachingClassMember).filter(
        TeachingClassMember.student_id == "7250629"
    ).update({"name": "刘梓烨"}, synchronize_session=False)
    db.add(TeachingClassMember(
        teaching_class_id=1, student_id="2301002", name="孙仲仁", source="manual",
    ))
    db.commit()
    stats = migrate_colliding_student_ids(db)
    assert score_rows(db, "7250629") == [("化学", "刘梓烨"), ("物理", "刘梓烨")]
    assert score_rows(db, "g2-7250629") == [("物理", "孙仲仁")]
    aliases = {
        a.student_id: a.identity_id for a in db.query(StudentAlias).all()
    }
    assert aliases["g2-7250629"] == aliases["2301002"]


def test_no_candidate_goes_pending():
    db = make_db()
    seed(db)
    # 高二成员里没有「刘梓烨」→ 无法自动建链
    db.query(TeachingClassMember).filter(
        TeachingClassMember.student_id == "2301001"
    ).delete()
    db.commit()
    stats = migrate_colliding_student_ids(db)
    assert stats["linked"] == 0
    assert stats["pending"] == [
        {"new_sid": "g1-7250629", "name": "刘梓烨", "reason": "no_candidate"}
    ]
    # 改写本身仍完成
    assert score_rows(db, "g1-7250629") == [("化学", "刘梓烨"), ("物理", "刘梓烨")]


def test_ambiguous_candidates_go_pending():
    db = make_db()
    seed(db)
    db.add(TeachingClassMember(
        teaching_class_id=1, student_id="2301009", name="刘梓烨", source="manual",
    ))
    db.commit()
    stats = migrate_colliding_student_ids(db)
    assert stats["linked"] == 0
    assert stats["pending"][0]["reason"] == "ambiguous"


def test_no_collision_untouched():
    db = make_db()
    seed(db)
    # 高二行删掉后不撞号，高一数据原样保留
    db.query(SubjectScore).filter(
        SubjectScore.exam_id == 2
    ).delete()
    db.commit()
    stats = migrate_colliding_student_ids(db)
    assert stats["collisions"] == 0
    assert score_rows(db, "7250629") == [("化学", "刘梓烨"), ("物理", "刘梓烨")]


def test_strip_namespace():
    assert strip_id_namespace("g1-7250629") == "7250629"
    assert strip_id_namespace("7250629") == "7250629"
    assert strip_id_namespace("_anon:1:张三") == "_anon:1:张三"
    assert strip_id_namespace("") == ""


def test_reassign_blocked_on_name_mismatch():
    """补录学号与历史成绩姓名不一致 → 拒绝（撞号防呆）。"""
    db = make_db()
    seed(db)
    migrate_colliding_student_ids(db)
    # 高一历史行已改走，给孙仲仁补 7250629（成绩同名）应放行
    tc = db.get(TeachingClass, 1)
    db.add(TeachingClassMember(
        teaching_class_id=1, student_id="_anon:1:王五", name="王五", source="manual",
    ))
    db.commit()
    # 王五补录孙仲仁的学号 → 成绩姓名不符 → 拒绝
    with pytest.raises(ConflictError):
        reassign_member_id(db, tc, "_anon:1:王五", "7250629", "王五")
    # 补录一个成绩里不存在、也不冲突的学号 → 放行
    res = reassign_member_id(db, tc, "_anon:1:王五", "2301999", "王五")
    assert res["new"] == "2301999"
    assert not db.query(TeachingClassMember).filter(
        TeachingClassMember.student_id == "_anon:1:王五"
    ).first()
