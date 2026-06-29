"""统一的「范围解析」层（教学版核心）。

把「按班级」的口径从单一数字行政班号（class_num == N）升级为「老师可配置的
多个教学班」：每个教学班维护一份成员学号集合，所有质量分析按这个集合过滤。

所有分析端点改用 `resolve_scope(db, teaching_class_id=...)`：
- teaching_class_id 为 None → 不限定（全年级）；
- 否则返回该教学班的成员学号集合，端点用 `student_id IN ids` 过滤。

同时承载「学生身份（跨学段）」解析（见 06-学号变更与学情继承）：
学号会随分班变化，无稳定唯一字段；以姓名确认/对照表人工建链。未建链的学号
读侧退化为独立单人（零配置可用）。
"""
from __future__ import annotations

from typing import Optional


# ────────────────────────────── 教学班成员范围 ──────────────────────────────

def members_of(db, teaching_class_id: int) -> set[str]:
    """某教学班的成员学号集合。"""
    from app.db.models import TeachingClassMember

    rows = (
        db.query(TeachingClassMember.student_id)
        .filter(TeachingClassMember.teaching_class_id == teaching_class_id)
        .all()
    )
    return {r[0] for r in rows}


def resolve_scope(db, *, teaching_class_id: Optional[int] = None) -> Optional[set[str]]:
    """把 teaching_class_id 解析成学号集合；None 表示不限定（全年级）。"""
    if teaching_class_id is None:
        return None
    return members_of(db, teaching_class_id)


def members_by_class_num(db, class_num: int, exam_id: Optional[int] = None, grade: Optional[int] = None) -> set[str]:
    """按行政班号取学号集合（旧 class_num 过滤的等价物）。可限定单场考试或年级。"""
    from app.db.models import Exam, SubjectScore

    q = db.query(SubjectScore.student_id).filter(SubjectScore.class_num == class_num)
    if exam_id is not None:
        q = q.filter(SubjectScore.exam_id == exam_id)
    elif grade is not None:
        q = q.join(Exam, Exam.id == SubjectScore.exam_id).filter(Exam.grade == grade)
    return {r[0] for r in q.distinct().all()}


def resolve_scope_compat(
    db,
    *,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
    exam_id: Optional[int] = None,
    grade: Optional[int] = None,
) -> Optional[set[str]]:
    """统一范围解析（兼容旧 class_num 入参）。teaching_class_id 优先；其次 class_num
    按行政班号解析（优先用 exam_id 限定，否则 grade）；都无则 None=全年级。"""
    if teaching_class_id is not None:
        return members_of(db, teaching_class_id)
    if class_num is not None:
        return members_by_class_num(db, int(class_num), exam_id=exam_id, grade=grade)
    return None


def list_classes(db, grade: Optional[int] = None) -> list:
    """我的全部教学班（按 sort_order、id）。"""
    from app.db.models import TeachingClass

    q = db.query(TeachingClass)
    if grade is not None:
        q = q.filter(TeachingClass.grade == grade)
    return q.order_by(TeachingClass.sort_order, TeachingClass.id).all()


def my_class_labels(db, grade: Optional[int] = None) -> dict[str, int]:
    """{label: teaching_class_id}，供对比页高亮 + 前端下拉。可限定年级。"""
    return {tc.label: tc.id for tc in list_classes(db, grade)}


def all_my_member_ids(db, grade: Optional[int] = None) -> set[str]:
    """我教的所有班（可限定年级）的成员并集，供总览仪表盘 & 全局学生检索。"""
    from app.db.models import TeachingClass, TeachingClassMember
    from sqlalchemy import distinct

    q = db.query(distinct(TeachingClassMember.student_id)).join(
        TeachingClass, TeachingClass.id == TeachingClassMember.teaching_class_id
    )
    if grade is not None:
        q = q.filter(TeachingClass.grade == grade)
    return {r[0] for r in q.all()}


def student_class_map(db, grade: Optional[int] = None) -> dict[str, tuple[str, int]]:
    """学生 → 其教学班 (label, tc_id)。同一老师同年级一个学生取一条（按 sort_order
    最前者）。供考试详情、关注名单、学生页统一标注「学生旁的班级」。"""
    from app.db.models import TeachingClass, TeachingClassMember

    q = (
        db.query(
            TeachingClassMember.student_id,
            TeachingClass.label,
            TeachingClass.id,
            TeachingClass.sort_order,
        )
        .join(TeachingClass, TeachingClass.id == TeachingClassMember.teaching_class_id)
        .order_by(TeachingClass.sort_order, TeachingClass.id)
    )
    if grade is not None:
        q = q.filter(TeachingClass.grade == grade)
    mapping: dict[str, tuple[str, int]] = {}
    for student_id, label, tc_id, _order in q.all():
        if student_id not in mapping:
            mapping[student_id] = (label, tc_id)
    return mapping


def student_class_map_multi(db, grade: Optional[int] = None) -> dict[str, list[dict]]:
    """学生 → 其所属全部教学班列表（label+id+grade）。需展示多个班时用。"""
    from app.db.models import TeachingClass, TeachingClassMember

    q = (
        db.query(
            TeachingClassMember.student_id,
            TeachingClass.label,
            TeachingClass.id,
            TeachingClass.grade,
            TeachingClass.sort_order,
        )
        .join(TeachingClass, TeachingClass.id == TeachingClassMember.teaching_class_id)
        .order_by(TeachingClass.sort_order, TeachingClass.id)
    )
    if grade is not None:
        q = q.filter(TeachingClass.grade == grade)
    mapping: dict[str, list[dict]] = {}
    for student_id, label, tc_id, cgrade, _order in q.all():
        mapping.setdefault(student_id, []).append(
            {"label": label, "teaching_class_id": tc_id, "grade": cgrade}
        )
    return mapping


# ────────────────────────────── 学生身份（跨学段） ──────────────────────────────

def identity_of(db, student_id: str) -> Optional[int]:
    """学号 → identity_id；无 alias 视为独立人返回 None。"""
    from app.db.models import StudentAlias

    row = (
        db.query(StudentAlias.identity_id)
        .filter(StudentAlias.student_id == student_id)
        .first()
    )
    return row[0] if row else None


def student_ids_of_person(db, student_id: str) -> set[str]:
    """给定任一学号，返回同一人的【全部学段学号】集合；无 alias 时返回 {student_id}。"""
    from app.db.models import StudentAlias

    identity_id = identity_of(db, student_id)
    if identity_id is None:
        return {student_id}
    rows = (
        db.query(StudentAlias.student_id)
        .filter(StudentAlias.identity_id == identity_id)
        .all()
    )
    ids = {r[0] for r in rows}
    return ids or {student_id}


def link_aliases(db, identity_id: int, student_ids: list[str], source: str = "name_confirmed") -> dict:
    """把若干学号链接到同一个人（identity_id）。已链接到他人的学号会改指到此人。"""
    from app.db.models import StudentAlias

    moved = []
    for sid in student_ids:
        existing = db.query(StudentAlias).filter(StudentAlias.student_id == sid).first()
        if existing:
            existing.identity_id = identity_id
            existing.link_source = source
        else:
            db.add(StudentAlias(student_id=sid, identity_id=identity_id, link_source=source))
        moved.append(sid)
    db.commit()
    return {"identity_id": identity_id, "linked_student_ids": moved, "source": source}


def ensure_identity(db, display_name: Optional[str] = None, ext_key: Optional[str] = None, gender: Optional[str] = None) -> int:
    from app.db.models import StudentIdentity

    ident = StudentIdentity(display_name=display_name, ext_key=ext_key, gender=gender)
    db.add(ident)
    db.flush()
    return ident.id


def unlink_alias(db, student_id: str) -> bool:
    """解除某学号的身份链接，把学号还原为独立人。返回是否实际删除。"""
    from app.db.models import StudentAlias

    row = db.query(StudentAlias).filter(StudentAlias.student_id == student_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def name_candidates(db, name: str, target_grade: int = 1) -> list[dict]:
    """按姓名去某年级（默认高一）找候选人，附行政班/最近主三门名次/学号辅助辨认同名。
    供配置向导「是同一人 / 是新学生」消歧。"""
    from app.db.models import Exam, SubjectScore, TotalScore

    rows = (
        db.query(SubjectScore.student_id, SubjectScore.class_num)
        .join(Exam, Exam.id == SubjectScore.exam_id)
        .filter(Exam.grade == target_grade, SubjectScore.name == name)
        .distinct()
        .all()
    )
    candidates = []
    for student_id, class_num in rows:
        # 最近一次主三门名次
        latest_rank = (
            db.query(TotalScore.xueji_rank, TotalScore.grade_rank)
            .join(Exam, Exam.id == TotalScore.exam_id)
            .filter(
                TotalScore.student_id == student_id,
                Exam.grade == target_grade,
                TotalScore.total_type == "主三门",
            )
            .order_by(Exam.exam_date.desc(), TotalScore.id.desc())
            .first()
        )
        rank = (latest_rank[0] or latest_rank[1]) if latest_rank else None
        candidates.append(
            {
                "student_id": student_id,
                "name": name,
                "class_num": class_num,
                "grade": target_grade,
                "latest_rank": rank,
            }
        )
    return candidates


def import_crosswalk(db, rows: list[dict]) -> dict:
    """导入「学号A ↔ 学号B」对照表，批量建链（每人同一 identity）。
    rows: [{"old": "学号A", "new": "学号B", "name"?: "..."}]。
    幂等：已同链跳过；任一学号已属他人则并入/改指。绝不按姓名自动链接。"""
    from app.db.models import StudentAlias

    linked = 0
    skipped = 0
    for row in rows:
        old = str(row.get("old") or "").strip()
        new = str(row.get("new") or "").strip()
        if not old or not new or old == new:
            skipped += 1
            continue
        old_alias = db.query(StudentAlias).filter(StudentAlias.student_id == old).first()
        new_alias = db.query(StudentAlias).filter(StudentAlias.student_id == new).first()
        old_id = old_alias.identity_id if old_alias else None
        new_id = new_alias.identity_id if new_alias else None
        if old_id is not None and new_id is not None:
            if old_id == new_id:
                skipped += 1
                continue
            # 合并：把 new 这一支并到 old
            db.query(StudentAlias).filter(StudentAlias.identity_id == new_id).update(
                {StudentAlias.identity_id: old_id, StudentAlias.link_source: "crosswalk"}
            )
        elif old_id is not None:
            db.add(StudentAlias(student_id=new, identity_id=old_id, link_source="crosswalk"))
        elif new_id is not None:
            db.add(StudentAlias(student_id=old, identity_id=new_id, link_source="crosswalk"))
        else:
            display = row.get("name")
            ident_id = ensure_identity(db, display_name=display)
            db.add(StudentAlias(student_id=old, identity_id=ident_id, grade=row.get("old_grade"), link_source="crosswalk"))
            db.add(StudentAlias(student_id=new, identity_id=ident_id, grade=row.get("new_grade"), link_source="crosswalk"))
        linked += 1
    db.commit()
    return {"linked": linked, "skipped": skipped}
