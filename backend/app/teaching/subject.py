"""单科教学领域边界：学科校验、教师资料读写、领域解析。

本模块是「教师唯一任教科目」的所有后续分析的统一入口。学科值统一 trim，
拒绝空白或不支持的学科。教师 subject 是唯一来源；未配置时返回明确的领域
错误，不静默兜底。
"""
from __future__ import annotations

from typing import Optional

SUPPORTED_SUBJECTS = [
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
]
_SUPPORTED_SET = frozenset(SUPPORTED_SUBJECTS)


class InvalidSubjectError(ValueError):
    """学科值非法（空白或不支持）。"""


class SubjectNotConfiguredError(RuntimeError):
    """教师尚未配置任教科目，无法进行后续分析。"""


class SubjectConflictError(RuntimeError):
    """教学班旧 subject 与教师 subject 冲突。"""

    def __init__(self, message: str, conflicting_classes: Optional[list[dict]] = None):
        super().__init__(message)
        self.conflicting_classes = conflicting_classes or []


def validate_subject(value: Optional[str]) -> str:
    """校验并 trim 学科值。返回规范化后的学科名。

    Raises:
        InvalidSubjectError: 空白或不支持的学科。
    """
    if value is None:
        raise InvalidSubjectError("学科不能为空")
    cleaned = value.strip()
    if not cleaned:
        raise InvalidSubjectError("学科不能为空")
    if cleaned not in _SUPPORTED_SET:
        raise InvalidSubjectError(f"不支持的学科「{cleaned}」，支持：{SUPPORTED_SUBJECTS}")
    return cleaned


def _get_or_create_teacher(db):
    from app.db.models import Teacher
    teacher = db.query(Teacher).first()
    if not teacher:
        teacher = Teacher()
        db.add(teacher)
        db.commit()
        db.refresh(teacher)
    return teacher


def get_teacher_profile(db) -> dict:
    """读取教师资料，返回 subject 和 subject_configured。"""
    from app.db.models import TeachingClass
    teacher = _get_or_create_teacher(db)
    class_count = db.query(TeachingClass).count()
    return {
        "id": teacher.id,
        "name": teacher.name,
        "subject": teacher.subject,
        "subject_configured": teacher.subject is not None,
        "current_teaching_class_id": teacher.current_teaching_class_id,
        "class_count": class_count,
        # 兼容旧字段（教学版不再使用）
        "target_class_high1": teacher.target_class_high1,
        "target_class_high2": teacher.target_class_high2,
        "target_class_high3": teacher.target_class_high3,
    }


def update_teacher_profile(
    db,
    name: Optional[str] = None,
    subject: Optional[str] = None,
) -> dict:
    """更新教师姓名和/或学科。

    name 为空字符串时清除姓名（设为 None）；subject 会经过 validate_subject 校验。
    仅传入 name 时不影响 subject，反之亦然（None 表示不更新该字段）。

    Returns:
        更新后的教师资料（同 get_teacher_profile 格式）。
    """
    teacher = _get_or_create_teacher(db)

    if name is not None:
        teacher.name = name.strip() or None

    if subject is not None:
        validated = validate_subject(subject)
        # 首次设置 subject 时回填空班 / 检测冲突（见 Cycle 5）
        _apply_subject_to_classes(db, teacher, validated)
        teacher.subject = validated

    db.commit()
    db.refresh(teacher)
    return get_teacher_profile(db)


def _apply_subject_to_classes(db, teacher, new_subject: str) -> None:
    """教师首次/变更设置 subject 时，对既有教学班的回填与冲突检测。

    - 对 subject 为空的既有教学班回填该学科；
    - 如果已有教学班存在多个非空学科或与请求值冲突，抛 SubjectConflictError（409），
      不修改任何数据。

    仅当教师 subject 从 None→有值（首次设置）时触发回填。
    """
    from app.db.models import TeachingClass

    if teacher.subject is not None:
        # 教师已有 subject：只校验一致性，不回填（变更逻辑见后续阶段）
        return

    classes = db.query(TeachingClass).all()
    empty = [tc for tc in classes if not tc.subject]
    non_empty_subjects = {tc.subject for tc in classes if tc.subject}

    # 既有班已有多个不同非空学科 → 冲突
    if len(non_empty_subjects) > 1:
        conflicting = [
            {"id": tc.id, "label": tc.label, "subject": tc.subject}
            for tc in classes if tc.subject
        ]
        raise SubjectConflictError(
            f"已有教学班存在多个不同学科 {sorted(non_empty_subjects)}，无法确定唯一任教科目",
            conflicting_classes=conflicting,
        )

    # 既有班的唯一非空学科与请求值不同 → 冲突
    if non_empty_subjects and new_subject not in non_empty_subjects:
        conflicting = [
            {"id": tc.id, "label": tc.label, "subject": tc.subject}
            for tc in classes if tc.subject
        ]
        raise SubjectConflictError(
            f"请求学科「{new_subject}」与已有教学班学科 {sorted(non_empty_subjects)} 冲突",
            conflicting_classes=conflicting,
        )

    # 回填空班
    for tc in empty:
        tc.subject = new_subject


def resolve_teaching_subject(db, teaching_class_id: Optional[int] = None) -> str:
    """统一领域解析：返回教师唯一任教科目。

    教师 subject 是所有后续分析的统一来源。本函数不做成绩查询，只解析领域边界。

    Args:
        db: SQLAlchemy session。
        teaching_class_id: 可选。给定时会校验该教学班的旧 subject 是否与教师
            subject 一致；空 subject 视为一致（回填后的预期状态），不同则冲突。

    Returns:
        教师的任教科目（规范化后的学科名）。

    Raises:
        SubjectNotConfiguredError: 教师尚未配置 subject（或教师记录不存在）。
        SubjectConflictError: 给定教学班的旧 subject 与教师 subject 冲突。
        ValueError: teaching_class_id 不存在。
    """
    from app.db.models import Teacher, TeachingClass

    teacher = db.query(Teacher).first()
    if not teacher or not teacher.subject:
        raise SubjectNotConfiguredError("教师尚未配置任教科目，请先在设置中选择你的学科")

    subject = teacher.subject

    if teaching_class_id is not None:
        tc = db.query(TeachingClass).filter(TeachingClass.id == teaching_class_id).first()
        if not tc:
            raise ValueError(f"教学班 {teaching_class_id} 不存在")
        # 空 subject 视为一致（回填后的预期状态）
        if tc.subject and tc.subject != subject:
            raise SubjectConflictError(
                f"教学班「{tc.label}」的学科「{tc.subject}」与教师任教科目「{subject}」冲突",
                conflicting_classes=[{"id": tc.id, "label": tc.label, "subject": tc.subject}],
            )

    return subject


# ────────────────────────────── 教学班 CRUD 学科继承 ──────────────────────────────


def create_class_with_subject(
    db,
    grade: int,
    label: str,
    kind: str = "教学",
    note: Optional[str] = None,
    sort_order: int = 0,
    subject: Optional[str] = None,
) -> dict:
    """新建教学班，自动继承教师 subject。

    - 前端不再需要提交 subject，后端从教师 subject 继承；
    - 教师未配置 subject → SubjectNotConfiguredError（API 层映射 409）；
    - 兼容旧客户端携带 subject：必须与教师 subject 一致，否则 SubjectConflictError。

    Returns:
        新建教学班的 payload（含 subject）。
    """
    from app.db.models import TeachingClass

    teacher_subject = resolve_teaching_subject(db)  # 未配置会抛 SubjectNotConfiguredError

    if subject is not None:
        requested = validate_subject(subject)
        if requested != teacher_subject:
            raise SubjectConflictError(
                f"请求学科「{requested}」与教师任教科目「{teacher_subject}」冲突",
            )

    label = label.strip()
    if not label:
        raise ValueError("label 不能为空")

    exists = (
        db.query(TeachingClass)
        .filter(TeachingClass.grade == grade, TeachingClass.label == label)
        .first()
    )
    if exists:
        raise ValueError(f"{grade} 年级已存在教学班「{label}」")

    tc = TeachingClass(
        grade=grade,
        label=label,
        subject=teacher_subject,
        kind=kind if kind in ("行政", "教学") else "教学",
        note=note,
        sort_order=sort_order,
    )
    db.add(tc)
    db.commit()
    db.refresh(tc)
    return _class_payload(db, tc)


def update_class_subject_aware(
    db,
    tc_id: int,
    label: Optional[str] = None,
    subject: Optional[str] = None,
    kind: Optional[str] = None,
    note: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> dict:
    """修改教学班：禁止改成与教师 subject 不同的值。

    - subject 不传或传相同值 → OK；
    - subject 传不同值 → SubjectConflictError；
    - 其他字段（label/kind/note/sort_order）正常更新。
    """
    from app.db.models import TeachingClass

    tc = db.query(TeachingClass).filter(TeachingClass.id == tc_id).first()
    if not tc:
        raise ValueError(f"教学班 {tc_id} 不存在")

    teacher_subject = resolve_teaching_subject(db)

    if subject is not None:
        requested = validate_subject(subject)
        if requested != teacher_subject:
            raise SubjectConflictError(
                f"教学班学科必须与教师任教科目「{teacher_subject}」一致，不能改为「{requested}」",
            )
        # 相同值：无需修改（tc.subject 已是 teacher_subject 或即将同步）

    if label is not None:
        tc.label = label.strip() or tc.label
    if kind is not None and kind in ("行政", "教学"):
        tc.kind = kind
    if note is not None:
        tc.note = note
    if sort_order is not None:
        tc.sort_order = sort_order

    db.commit()
    db.refresh(tc)
    return _class_payload(db, tc)


def _class_payload(db, tc) -> dict:
    """构造教学班响应 payload（与 teaching/router.py 的 _class_payload 同构）。"""
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


def get_current_class_payload(db) -> dict:
    """返回当前选中的教学班 payload。

    classes/current 响应中的 subject 始终反映教师任教科目（回填后与教师一致）。
    无当前班时 class 为 None。
    """
    from app.db.models import Teacher, TeachingClass

    teacher = db.query(Teacher).first()
    tc_id = teacher.current_teaching_class_id if teacher else None
    tc = (
        db.query(TeachingClass).filter(TeachingClass.id == tc_id).first()
        if tc_id
        else None
    )
    return {
        "teaching_class_id": tc_id,
        "class": _class_payload(db, tc) if tc else None,
    }
