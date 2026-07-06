"""教学班配置 API（挂 /api/teaching）。

班 CRUD / 成员增删查 / 批量导入（四态）/ 按行政班同步 / 候选班 / 当前班，
以及跨学段身份链接（姓名确认 + 学号对照表）。详见 03·§2 与 06·§5。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.models import get_db
from app.teaching import service
from app.analysis import scope

router = APIRouter(prefix="/teaching", tags=["teaching"])


def _get_or_404(db, model, **filters):
    obj = db.query(model).filter_by(**filters).first()
    if not obj:
        raise HTTPException(404, f"{model.__name__} 不存在")
    return obj


def _member_profile(db, tc_id: int) -> list[dict]:
    """成员列表：学号 / 姓名 / 来源 / 行政班 / 状态（inherited/new）。"""
    from app.db.models import (
        ClassRoster,
        SubjectScore,
        TeachingClassMember,
    )

    members = (
        db.query(TeachingClassMember)
        .filter(TeachingClassMember.teaching_class_id == tc_id)
        .order_by(TeachingClassMember.created_at, TeachingClassMember.id)
        .all()
    )
    out = []
    for m in members:
        is_anon = service.is_anon_sid(m.student_id)
        name = m.name or service.student_name(db, m.student_id)
        if not name and not is_anon:
            name = m.student_id
        cls = (
            db.query(SubjectScore.class_num)
            .filter(
                SubjectScore.student_id == m.student_id,
                SubjectScore.class_num.isnot(None),
            )
            .first()
        )
        roster = db.query(ClassRoster).filter(ClassRoster.student_id == m.student_id).first()
        out.append(
            {
                "student_id": m.student_id,
                "name": name,
                "has_student_id": not is_anon,
                "source": m.source,
                "class_num": roster.class_num if roster else (cls[0] if cls else None),
                "state": "name_only" if is_anon else service.classify_member(db, _tc_grade(db, tc_id), m.student_id),
            }
        )
    return out


def _tc_grade(db, tc_id: int) -> int:
    from app.db.models import TeachingClass

    tc = db.query(TeachingClass).filter(TeachingClass.id == tc_id).first()
    return tc.grade if tc else 0


def _class_payload(db, tc) -> dict:
    from app.db.models import TeachingClassMember

    count = (
        db.query(TeachingClassMember)
        .filter(TeachingClassMember.teaching_class_id == tc.id)
        .count()
    )
    return {
        "id": tc.id,
        "grade": tc.grade,
        "label": tc.label,
        "subject": tc.subject,
        "kind": tc.kind,
        "note": tc.note,
        "sort_order": tc.sort_order,
        "member_count": count,
        "created_at": tc.created_at.isoformat() if tc.created_at else None,
    }


# ────────────────────────────── 班 CRUD ──────────────────────────────

@router.get("/classes")
def list_classes(grade: Optional[int] = None, db=Depends(get_db)):
    from app.db.models import TeachingClass

    q = db.query(TeachingClass)
    if grade is not None:
        q = q.filter(TeachingClass.grade == grade)
    tcs = q.order_by(TeachingClass.sort_order, TeachingClass.id).all()
    return {"classes": [_class_payload(db, tc) for tc in tcs]}


class ClassCreate(BaseModel):
    grade: int
    label: str
    subject: Optional[str] = None
    kind: str = "教学"
    note: Optional[str] = None
    sort_order: int = 0


@router.post("/classes")
def create_class(payload: ClassCreate, db=Depends(get_db)):
    from app.db.models import TeachingClass

    label = payload.label.strip()
    if not label:
        raise HTTPException(400, "label 不能为空")
    exists = (
        db.query(TeachingClass)
        .filter(TeachingClass.grade == payload.grade, TeachingClass.label == label)
        .first()
    )
    if exists:
        raise HTTPException(409, f"{payload.grade} 年级已存在教学班「{label}」")
    tc = TeachingClass(
        grade=payload.grade,
        label=label,
        subject=payload.subject,
        kind=payload.kind if payload.kind in ("行政", "教学") else "教学",
        note=payload.note,
        sort_order=payload.sort_order,
    )
    db.add(tc)
    db.commit()
    db.refresh(tc)
    return _class_payload(db, tc)


class ClassUpdate(BaseModel):
    label: Optional[str] = None
    subject: Optional[str] = None
    kind: Optional[str] = None
    note: Optional[str] = None
    sort_order: Optional[int] = None


@router.put("/classes/{tc_id}")
def update_class(tc_id: int, payload: ClassUpdate, db=Depends(get_db)):
    from app.db.models import TeachingClass

    tc = _get_or_404(db, TeachingClass, id=tc_id)
    if payload.label is not None:
        tc.label = payload.label.strip() or tc.label
    if payload.subject is not None:
        tc.subject = payload.subject
    if payload.kind is not None and payload.kind in ("行政", "教学"):
        tc.kind = payload.kind
    if payload.note is not None:
        tc.note = payload.note
    if payload.sort_order is not None:
        tc.sort_order = payload.sort_order
    db.commit()
    db.refresh(tc)
    return _class_payload(db, tc)


@router.delete("/classes/{tc_id}")
def delete_class(tc_id: int, db=Depends(get_db)):
    from app.db.models import Teacher, TeachingClass, TeachingClassMember

    tc = _get_or_404(db, TeachingClass, id=tc_id)
    db.query(TeachingClassMember).filter(
        TeachingClassMember.teaching_class_id == tc_id
    ).delete(synchronize_session=False)
    teacher = db.query(Teacher).first()
    if teacher and teacher.current_teaching_class_id == tc_id:
        teacher.current_teaching_class_id = None
    db.delete(tc)
    db.commit()
    return {"ok": True, "deleted": tc_id}


# ────────────────────────────── 成员 ──────────────────────────────

@router.get("/classes/{tc_id}/members")
def list_members(tc_id: int, db=Depends(get_db)):
    from app.db.models import TeachingClass

    _get_or_404(db, TeachingClass, id=tc_id)
    return {"members": _member_profile(db, tc_id)}


class MembersAdd(BaseModel):
    student_ids: Optional[list[str]] = None
    names: Optional[list[str]] = None


@router.post("/classes/{tc_id}/members")
def add_members(tc_id: int, payload: MembersAdd, db=Depends(get_db)):
    from app.db.models import TeachingClass

    tc = _get_or_404(db, TeachingClass, id=tc_id)
    res = service.add_by_names_and_ids(db, tc, payload.student_ids, payload.names)
    res["members"] = _member_profile(db, tc_id)
    return res


class MemberReassign(BaseModel):
    new_student_id: str
    name: Optional[str] = None


@router.patch("/classes/{tc_id}/members/{student_id}")
def reassign_member(tc_id: int, student_id: str, payload: MemberReassign, db=Depends(get_db)):
    """修改成员学号（「学号换了」/ 给仅姓名成员补学号）。连带迁移花名册 / 缺交 /
    特殊 / 档案 / 身份别名等教师侧数据；成绩表不动。"""
    from app.db.models import TeachingClass

    tc = _get_or_404(db, TeachingClass, id=tc_id)
    try:
        res = service.reassign_member_id(db, tc, student_id, payload.new_student_id, payload.name)
    except service.ConflictError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    res["members"] = _member_profile(db, tc_id)
    return {"ok": True, **res}


class MemberRemove(BaseModel):
    pass


@router.delete("/classes/{tc_id}/members/{student_id}")
def remove_member(tc_id: int, student_id: str, db=Depends(get_db)):
    from app.db.models import TeachingClassMember

    row = (
        db.query(TeachingClassMember)
        .filter(
            TeachingClassMember.teaching_class_id == tc_id,
            TeachingClassMember.student_id == student_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "成员不存在")
    db.delete(row)
    db.commit()
    return {"ok": True, "removed": student_id}


class ImportPayload(BaseModel):
    tokens: Optional[list[str]] = None
    text: Optional[str] = None
    upsert: bool = False  # 覆盖模式：按姓名匹配并更新已有成员的学号


@router.post("/classes/{tc_id}/members/import")
def import_members(tc_id: int, payload: ImportPayload, db=Depends(get_db)):
    from app.db.models import TeachingClass

    tc = _get_or_404(db, TeachingClass, id=tc_id)
    lines = payload.text.split("\n") if payload.text else []
    report = service.resolve_import(
        db, tc, lines=lines, tokens=payload.tokens or [], upsert=payload.upsert
    )
    report["members"] = _member_profile(db, tc_id)
    return report


@router.post("/classes/{tc_id}/sync-by-class-num")
def sync_by_class_num(tc_id: int, db=Depends(get_db)):
    from app.db.models import TeachingClass

    tc = _get_or_404(db, TeachingClass, id=tc_id)
    if tc.kind != "行政":
        raise HTTPException(400, "仅行政班（高一，label 为数字）支持按行政班号同步")
    count = service.sync_by_class_num(db, tc)
    return {"ok": True, "member_count": count, "members": _member_profile(db, tc_id)}


# ────────────────────────────── 候选班 / 当前班 ──────────────────────────────

@router.get("/candidate-classes")
def candidate_classes(grade: int, db=Depends(get_db)):
    return service.candidate_classes(db, grade)


@router.get("/current")
def get_current(db=Depends(get_db)):
    from app.db.models import Teacher, TeachingClass

    teacher = db.query(Teacher).first()
    tc_id = teacher.current_teaching_class_id if teacher else None
    tc = db.query(TeachingClass).filter(TeachingClass.id == tc_id).first() if tc_id else None
    return {
        "teaching_class_id": tc_id,
        "class": _class_payload(db, tc) if tc else None,
    }


class CurrentPayload(BaseModel):
    teaching_class_id: Optional[int] = None


@router.patch("/current")
def set_current(payload: CurrentPayload, db=Depends(get_db)):
    from app.db.models import Teacher, TeachingClass

    teacher = db.query(Teacher).first()
    if not teacher:
        teacher = Teacher()
        db.add(teacher)
    if payload.teaching_class_id is not None:
        _get_or_404(db, TeachingClass, id=payload.teaching_class_id)
    teacher.current_teaching_class_id = payload.teaching_class_id
    db.commit()
    return {"ok": True, "teaching_class_id": teacher.current_teaching_class_id}


# ────────────────────────────── 跨学段身份链接 ──────────────────────────────

@router.get("/name-candidates")
def name_candidates_endpoint(name: str, grade: int = 1, db=Depends(get_db)):
    return {"name": name, "target_grade": grade, "candidates": scope.name_candidates(db, name, grade)}


class LinkPayload(BaseModel):
    identity_id: Optional[int] = None
    student_ids: list[str]
    source: str = "name_confirmed"
    display_name: Optional[str] = None


@router.post("/link")
def link_aliases_endpoint(payload: LinkPayload, db=Depends(get_db)):
    identity_id = payload.identity_id
    if identity_id is None:
        identity_id = scope.ensure_identity(db, display_name=payload.display_name)
        db.commit()
    return scope.link_aliases(db, identity_id, payload.student_ids, payload.source)


@router.delete("/alias/{student_id}")
def unlink_alias_endpoint(student_id: str, db=Depends(get_db)):
    removed = scope.unlink_alias(db, student_id)
    return {"ok": removed, "student_id": student_id}


class CrosswalkPayload(BaseModel):
    rows: list[dict]


@router.post("/import-crosswalk")
def import_crosswalk_endpoint(payload: CrosswalkPayload, db=Depends(get_db)):
    return scope.import_crosswalk(db, payload.rows)


@router.get("/identity/{student_id}")
def identity_endpoint(student_id: str, db=Depends(get_db)):
    """返回某学号对应的全部学号集合（用于学生画像展示「学段履历」）。"""
    identity_id = scope.identity_of(db, student_id)
    ids = sorted(scope.student_ids_of_person(db, student_id))
    return {"student_id": student_id, "identity_id": identity_id, "all_student_ids": ids}
