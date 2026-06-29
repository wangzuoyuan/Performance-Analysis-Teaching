"""教学班配置与成员维护的业务逻辑（被 router 与上传钩子共用）。

成员关系四条来源（对应 D1 / 06）：
- class_num：高一行政班，成员 = 该年级 class_num==int(label) 的学号；
- parser：上传带教学班列的成绩表，按 class_label 自动加成员；
- manual / roster：老师粘贴学号/姓名清单或上传花名册 Excel（姓名→学号反查）。

姓名→学号反查（绝不自动按姓名链接身份）：唯一命中直接落；多名候选返回待人工
消歧（附行政班/最近名次）；零命中进未匹配列表。
"""
from __future__ import annotations

from typing import Optional


def name_to_student_ids(db, name: str, grade: Optional[int] = None) -> list[str]:
    """按姓名反查学号（来源 SubjectScore.name，可选 ClassRoster.name）。返回去重学号列表。"""
    from app.db.models import ClassRoster, Exam, SubjectScore
    from sqlalchemy import distinct

    ids: list[str] = []
    q = db.query(distinct(SubjectScore.student_id)).filter(SubjectScore.name == name)
    if grade is not None:
        q = q.join(Exam, Exam.id == SubjectScore.exam_id).filter(Exam.grade == grade)
    ids.extend(r[0] for r in q.all())
    # 花名册补充（作业模块可能已有该生但尚无成绩）
    rq = db.query(ClassRoster.student_id).filter(ClassRoster.name == name)
    for r in rq.all():
        if r[0] not in ids:
            ids.append(r[0])
    return ids


def student_exists(db, student_id: str) -> bool:
    """该学号是否在成绩库或花名册中出现过。"""
    from app.db.models import ClassRoster, SubjectScore

    if db.query(SubjectScore.id).filter(SubjectScore.student_id == student_id).first():
        return True
    if db.query(ClassRoster.student_id).filter(ClassRoster.student_id == student_id).first():
        return True
    return False


def student_name(db, student_id: str) -> Optional[str]:
    from app.db.models import ClassRoster, SubjectScore

    row = (
        db.query(SubjectScore.name)
        .filter(SubjectScore.student_id == student_id, SubjectScore.name.isnot(None))
        .first()
    )
    if row and row[0]:
        return row[0]
    r = db.query(ClassRoster.name).filter(ClassRoster.student_id == student_id).first()
    return r[0] if r else None


def classify_member(db, tc_grade: int, student_id: str) -> str:
    """判定成员状态：inherited（已继承跨学段学情）/ new（新学生）。
    inherited = 该学号经身份层解析出的同一人，存在比当前年级更低的学号记录。"""
    from app.analysis.scope import student_ids_of_person, identity_of
    from app.db.models import Exam, SubjectScore

    if identity_of(db, student_id) is None:
        return "new"
    ids = student_ids_of_person(db, student_id)
    # 这些学号里有没有出现在更低年级的成绩
    other = {sid for sid in ids if sid != student_id}
    if not other:
        return "new"
    lower = (
        db.query(Exam.grade)
        .join(SubjectScore, SubjectScore.exam_id == Exam.id)
        .filter(SubjectScore.student_id.in_(other), Exam.grade < tc_grade)
        .distinct()
        .all()
    )
    return "inherited" if lower else "new"


def _looks_like_student_id(token: str) -> bool:
    t = token.strip()
    return t.isdigit() and len(t) >= 5


def resolve_import(db, tc, tokens: list[str]) -> dict:
    """批量解析成员清单（学号或姓名自动判别）。matched 的直接落成员；ambiguous /
    unmatched 返回供人工跟进。返回 {matched, ambiguous, unmatched, added_count}。

    matched 项含 state(inherited/new)；ambiguous 含候选（学号/行政班/最近名次）；
    unmatched 为零命中项。绝不按姓名自动建身份链接。"""
    from app.analysis.scope import name_candidates
    from app.db.models import Exam, SubjectScore, TeachingClassMember, TotalScore

    existing = {
        r[0]
        for r in db.query(TeachingClassMember.student_id)
        .filter(TeachingClassMember.teaching_class_id == tc.id)
        .all()
    }
    matched: list[dict] = []
    ambiguous: list[dict] = []
    unmatched: list[dict] = []
    added = 0

    for token in tokens:
        token = (token or "").strip()
        if not token:
            continue
        if _looks_like_student_id(token):
            sid = token
            name = student_name(db, sid) or sid
            state = classify_member(db, tc.grade, sid)
            if sid not in existing:
                db.add(
                    TeachingClassMember(
                        teaching_class_id=tc.id, student_id=sid, source="manual"
                    )
                )
                existing.add(sid)
                added += 1
            matched.append({"student_id": sid, "name": name, "state": state})
            continue

        # 按姓名反查
        ids = name_to_student_ids(db, token)
        if not ids:
            unmatched.append({"token": token, "name": token})
        elif len(ids) > 1:
            # 同名多人：列候选（带行政班/最近名次/学号）供老师确认后用学号再加
            cands = []
            for sid in ids:
                nm = student_name(db, sid) or token
                cls = (
                    db.query(SubjectScore.class_num)
                    .filter(SubjectScore.student_id == sid, SubjectScore.class_num.isnot(None))
                    .first()
                )
                latest = (
                    db.query(TotalScore.xueji_rank, TotalScore.grade_rank)
                    .join(Exam, Exam.id == TotalScore.exam_id)
                    .filter(
                        TotalScore.student_id == sid,
                        TotalScore.total_type == "主三门",
                    )
                    .order_by(Exam.exam_date.desc(), TotalScore.id.desc())
                    .first()
                )
                cands.append(
                    {
                        "student_id": sid,
                        "name": nm,
                        "class_num": cls[0] if cls else None,
                        "latest_rank": (latest[0] or latest[1]) if latest else None,
                    }
                )
            ambiguous.append({"name": token, "candidates": cands})
        else:
            sid = ids[0]
            state = classify_member(db, tc.grade, sid)
            if sid not in existing:
                db.add(
                    TeachingClassMember(
                        teaching_class_id=tc.id, student_id=sid, source="manual"
                    )
                )
                existing.add(sid)
                added += 1
            matched.append({"student_id": sid, "name": token, "state": state})

    db.commit()
    return {
        "matched": matched,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "added_count": added,
    }


def sync_by_class_num(db, tc) -> int:
    """高一/行政班：按 int(label) 从成绩库重算成员（仅覆盖 source=class_num 行，
    保留 manual/roster/parser）。返回成员总数。"""
    from app.db.models import Exam, SubjectScore, TeachingClassMember

    if tc.kind != "行政":
        return db.query(TeachingClassMember).filter(
            TeachingClassMember.teaching_class_id == tc.id
        ).count()
    try:
        cn = int(tc.label)
    except (TypeError, ValueError):
        return db.query(TeachingClassMember).filter(
            TeachingClassMember.teaching_class_id == tc.id
        ).count()

    ids = {
        r[0]
        for r in (
            db.query(SubjectScore.student_id)
            .join(Exam, Exam.id == SubjectScore.exam_id)
            .filter(Exam.grade == tc.grade, SubjectScore.class_num == cn)
            .distinct()
            .all()
        )
    }
    db.query(TeachingClassMember).filter(
        TeachingClassMember.teaching_class_id == tc.id,
        TeachingClassMember.source == "class_num",
    ).delete(synchronize_session=False)
    for sid in ids:
        db.add(
            TeachingClassMember(
                teaching_class_id=tc.id, student_id=sid, source="class_num"
            )
        )
    db.commit()
    return db.query(TeachingClassMember).filter(
        TeachingClassMember.teaching_class_id == tc.id
    ).count()


def sync_members_after_upload(db, exam) -> None:
    """上传新考试后：对 kind=行政 班按 class_num 重算成员；对成绩带 class_label
    的，把对应学号补为 source=parser 成员（不覆盖已有 manual/roster）。"""
    from app.db.models import SubjectScore, TeachingClass, TeachingClassMember

    classes = (
        db.query(TeachingClass).filter(TeachingClass.grade == exam.grade).all()
    )
    for tc in classes:
        if tc.kind == "行政":
            sync_by_class_num(db, tc)
        # parser 来源：本考试里 class_label 命中本班标签的学号自动加入
        existing = {
            r[0]
            for r in db.query(TeachingClassMember.student_id)
            .filter(TeachingClassMember.teaching_class_id == tc.id)
            .all()
        }
        sids = {
            r[0]
            for r in (
                db.query(SubjectScore.student_id)
                .filter(
                    SubjectScore.exam_id == exam.id,
                    SubjectScore.class_label == tc.label,
                )
                .distinct()
                .all()
            )
        }
        for sid in sids:
            if sid not in existing:
                db.add(
                    TeachingClassMember(
                        teaching_class_id=tc.id, student_id=sid, source="parser"
                    )
                )
                existing.add(sid)
    db.commit()


def candidate_classes(db, grade: int) -> dict:
    """扫出该年级可选的行政班号 + 教学班标签（建班向导预填用）。"""
    from app.db.models import Exam, SubjectScore
    from sqlalchemy import distinct

    class_nums = sorted(
        {
            r[0]
            for r in (
                db.query(distinct(SubjectScore.class_num))
                .join(Exam, Exam.id == SubjectScore.exam_id)
                .filter(Exam.grade == grade, SubjectScore.class_num.isnot(None))
                .all()
            )
        }
    )
    class_labels = sorted(
        {
            r[0]
            for r in (
                db.query(distinct(SubjectScore.class_label))
                .join(Exam, Exam.id == SubjectScore.exam_id)
                .filter(Exam.grade == grade, SubjectScore.class_label.isnot(None))
                .all()
            )
        }
    )
    return {
        "grade": grade,
        "class_nums": class_nums,
        "class_labels": class_labels,
    }
