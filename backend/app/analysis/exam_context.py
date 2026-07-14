"""考试分析上下文：当前任教学科 + 允许的教学班成员范围。

本模块是阶段2「考试列表 + 考试详情」单学科垂直切片的统一入口。它把教师
唯一任教科目与教学班成员范围解析成一个不可分割的上下文对象，供 /api/exams
和 /api/exams/{id} 使用。

核心原则：
- 学科由后端教师上下文解析，前端不传也不可信；
- 成员范围只有两种：「当前教学班」（该班成员集合）或「全部教学班」（该教师所有
  教学班成员并集去重）；
- 无教师 subject 或无有效教学范围时抛出明确的领域错误，绝不退化为全年级；
- teaching_class_id 必须存在且其 subject 与教师任教科目一致（空 subject 视为
  一致），否则抛 ValueError / SubjectConflictError，绝不静默降级。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.teaching.subject import (
    resolve_teaching_subject,
    SubjectNotConfiguredError,
    SubjectConflictError,
)


class NoTeachingScopeError(RuntimeError):
    """教师已配置 subject 但没有任何有成员的教学班，无法确定分析范围。"""


@dataclass(frozen=True)
class ExamAnalysisContext:
    """考试分析上下文：学科 + 允许的学生学号集合。"""
    subject: str
    member_ids: frozenset[str]


def resolve_exam_context(
    db,
    *,
    teaching_class_id: Optional[int] = None,
) -> ExamAnalysisContext:
    """解析考试分析上下文：当前任教学科 + 允许的教学班成员范围。

    Args:
        db: SQLAlchemy session。
        teaching_class_id: 当前选中的教学班 id。None 表示「全部教学班」
            （该教师所有教学班成员并集去重）。

    Returns:
        ExamAnalysisContext(subject=教师任教科目, member_ids=允许学号集合)。

    Raises:
        SubjectNotConfiguredError: 教师尚未配置 subject。
        SubjectConflictError: 给定教学班的 subject 与教师任教科目冲突。
        NoTeachingScopeError: 没有任何有成员的教学班，或指定教学班无成员。
        ValueError: teaching_class_id 不存在。
    """
    from app.analysis.scope import members_of, all_my_member_ids

    # 1) 学科解析 + teaching_class_id 存在性/一致性校验
    #    resolve_teaching_subject 内部校验：id 不存在→ValueError；
    #    该班 subject 非空且≠教师 subject→SubjectConflictError。
    subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)

    # 2) 成员范围解析
    if teaching_class_id is not None:
        member_ids = members_of(db, teaching_class_id)
        if not member_ids:
            raise NoTeachingScopeError(
                f"教学班 {teaching_class_id} 没有成员，无法进行考试分析"
            )
    else:
        member_ids = all_my_member_ids(db)
        if not member_ids:
            raise NoTeachingScopeError(
                "没有任何有成员的教学班，请先在设置中配置教学班成员"
            )

    return ExamAnalysisContext(
        subject=subject,
        member_ids=frozenset(member_ids),
    )
