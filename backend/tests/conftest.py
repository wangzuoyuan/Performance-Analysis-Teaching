# 共享fixtures
import pytest
from app.db.models import SessionLocal


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_minimal_exam_scope(subject=None, member_ids=("tapi-s1", "tapi-s2")):
    """为单学科化端点临时建立最小教学范围（自建自删，不依赖共享库状态）。

    单学科化后考试、班级对比、作业相关性、周关注等端点要求教师已配置 subject
    且有有成员的教学班。本函数幂等创建：教师学科、一个高二教学班、成员、一场考试
    及当前学科成绩。subject=None 时自动沿用教师已有的学科。

    返回 cleanup_fn，调用方应在 request.addfinalizer / finally 中调用它清理。
    """
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember,
        Exam, SubjectScore,
    )
    db = SessionLocal()
    created: dict = {"exam_ids": [], "tc_ids": [], "reset_teacher_subject": None}
    try:
        teacher = db.query(Teacher).first()
        if teacher:
            if subject is None:
                actual_subject = teacher.subject or "数学"
            else:
                actual_subject = subject
            if teacher.subject is None:
                created["reset_teacher_subject"] = teacher.id
                teacher.subject = actual_subject
            elif subject is not None and teacher.subject != subject:
                actual_subject = teacher.subject
        else:
            actual_subject = subject or "数学"
            teacher = Teacher(subject=actual_subject)
            db.add(teacher)
        db.flush()

        tc = db.query(TeachingClass).filter(
            TeachingClass.label == "tapi-scope", TeachingClass.grade == 2
        ).first()
        if not tc:
            tc = TeachingClass(grade=2, label="tapi-scope", subject=actual_subject, kind="教学")
            db.add(tc)
            db.flush()
            created["tc_ids"].append(tc.id)
        for sid in member_ids:
            exists = db.query(TeachingClassMember).filter(
                TeachingClassMember.teaching_class_id == tc.id,
                TeachingClassMember.student_id == sid,
            ).first()
            if not exists:
                db.add(TeachingClassMember(
                    teaching_class_id=tc.id, student_id=sid, source="manual"
                ))

        exam = db.query(Exam).filter(Exam.name == "tapi-考试").first()
        if not exam:
            exam = Exam(name="tapi-考试", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam)
            db.flush()
            created["exam_ids"].append(exam.id)
            for i, sid in enumerate(member_ids, 1):
                db.add(SubjectScore(
                    exam_id=exam.id, student_id=sid, subject=actual_subject,
                    raw_score=80 + i, name=f"测试{i}", class_num=1,
                ))
        db.commit()
    finally:
        db.close()

    def _cleanup():
        db = SessionLocal()
        try:
            for eid in created["exam_ids"]:
                db.query(SubjectScore).filter(SubjectScore.exam_id == eid).delete(synchronize_session=False)
                db.query(Exam).filter(Exam.id == eid).delete(synchronize_session=False)
            for tcid in created["tc_ids"]:
                db.query(TeachingClassMember).filter(TeachingClassMember.teaching_class_id == tcid).delete(synchronize_session=False)
                db.query(TeachingClass).filter(TeachingClass.id == tcid).delete(synchronize_session=False)
            if created["reset_teacher_subject"] is not None:
                t = db.query(Teacher).filter(Teacher.id == created["reset_teacher_subject"]).first()
                if t:
                    t.subject = None
            db.commit()
        finally:
            db.close()

    return _cleanup