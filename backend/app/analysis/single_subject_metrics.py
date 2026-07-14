"""单学科分析指标层（阶段4核心）。

统一解析后端教师唯一任教学科、教学班成员范围、考试/年级和有效成绩。
所有六个分析端点（rank-metrics / rank-range / rank-frequency / focus-list /
subject-weakness / band-trend）共用本模块。

核心原则：
- 学科由后端教师上下文解析（resolve_teaching_subject），前端不可传入也不可信
- 数据只来自当前任教学科 SubjectScore，绝不查询总分表
- 有效成绩：raw_score 或 grade_score 至少一个非空；percentile-only 残留无效
- 范围限定为当前教学班成员集合或全部所教教学班成员并集
- subject_rank 用 competition ranking（同分同名次）
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Optional


# ────────────────────────────── 领域常量 ──────────────────────────────

BASE_SUBJECTS = ["语文", "数学", "英语"]
ELECTIVE_SUBJECTS = ["物理", "化学", "生物", "政治", "历史", "地理"]
_ELECTIVE_SUBJECTS = frozenset(ELECTIVE_SUBJECTS)

PERCENTILE_BINS = [
    ("p0_20", "前20%", 0, 0.2),
    ("p20_40", "20%-40%", 0.2, 0.4),
    ("p40_60", "40%-60%", 0.4, 0.6),
    ("p60_80", "60%-80%", 0.6, 0.8),
    ("p80_100", "后20%", 0.8, 1.0),
]
GRADE_SCORE_VALUES = [70, 67, 64, 61, 58, 55, 52, 49, 46, 43, 40]
GRADE_SCORE_SEPARATOR_AFTER = {67, 58, 49, 43}
GRADE_SCORE_BINS = [
    (f"g{score}", f"{score}分", score, score in GRADE_SCORE_SEPARATOR_AFTER)
    for score in GRADE_SCORE_VALUES
]


# ────────────────────────────── 上下文数据类 ──────────────────────────────


@dataclass(frozen=True)
class SingleSubjectContext:
    """单学科分析上下文：学科 + 允许的学生学号集合。"""
    subject: str
    member_ids: frozenset[str]


def resolve_single_subject_context(
    db,
    *,
    teaching_class_id: Optional[int] = None,
    grade: Optional[int] = None,
) -> SingleSubjectContext:
    """解析教师唯一任教学科 + 允许的教学班成员范围。

    与 resolve_exam_context 的区别：grade 可选，用于按年级过滤成员范围
    （rank-frequency 需要按年级限定）。

    Returns:
        SingleSubjectContext(subject=教师任教科目, member_ids=允许学号集合)

    Raises:
        SubjectNotConfiguredError / SubjectConflictError / NoTeachingScopeError /
        ValueError
    """
    from app.analysis.exam_context import resolve_exam_context
    from app.analysis.scope import student_class_map_multi

    ctx = resolve_exam_context(db, teaching_class_id=teaching_class_id)
    member_ids = set(ctx.member_ids)

    # rank-frequency 按 grade 过滤成员
    if grade is not None:
        member_class_map = student_class_map_multi(db, None)
        member_ids = {
            sid for sid in member_ids
            if any(
                info["grade"] == grade
                for info in member_class_map.get(sid, [])
            )
        }

    return SingleSubjectContext(
        subject=ctx.subject,
        member_ids=frozenset(member_ids),
    )


# ────────────────────────────── 有效成绩判定 ──────────────────────────────


def is_valid_score(row) -> bool:
    """有效成绩：raw_score 或 grade_score 至少一个非空。"""
    return row.raw_score is not None or row.grade_score is not None


def valid_exam_ids_for_subject(
    db,
    subject: str,
    member_ids: frozenset[str] | set[str],
    grade: Optional[int] = None,
) -> set[int]:
    """获取当前学科在成员范围内确有真实分数的考试 id 集合。"""
    from app.db.models import SubjectScore

    q = (
        db.query(SubjectScore.exam_id)
        .filter(
            SubjectScore.subject == subject,
            SubjectScore.student_id.in_(member_ids),
        )
        .filter(
            SubjectScore.raw_score.isnot(None)
            | SubjectScore.grade_score.isnot(None)
        )
        .distinct()
    )
    return {row[0] for row in q.all()}


# ────────────────────────────── subject_rank 计算 ──────────────────────────────


def normalize_percentile(value: Optional[float]) -> Optional[float]:
    """百分位规范化为 0..1。支持 0..1 和 0..100 两种刻度。"""
    if value is None:
        return None
    number = float(value)
    if number > 1:
        number = number / 100
    return max(0, min(number, 1))


def compute_subject_rank(
    db,
    subject: str,
    exam_id: int,
    member_ids: frozenset[str] | set[str],
    exam_grade: Optional[int] = None,
) -> dict[str, int]:
    """Competition ranking（同分同名次）。

    优先规范化后的 grade_percentile（高=好→rank小）。
    缺 percentile 时，高二/三选考学科用 grade_score 降序，其他用 raw_score 降序。
    同分同排名。返回 {student_id: rank}。
    """
    from app.db.models import SubjectScore

    rows = (
        db.query(SubjectScore)
        .filter(
            SubjectScore.exam_id == exam_id,
            SubjectScore.subject == subject,
            SubjectScore.student_id.in_(member_ids),
        )
        .filter(
            SubjectScore.raw_score.isnot(None)
            | SubjectScore.grade_score.isnot(None)
        )
        .all()
    )

    return _competition_rank_from_rows(rows, subject, exam_grade)


def _competition_rank_from_rows(
    rows: list,
    subject: str,
    exam_grade: Optional[int],
) -> dict[str, int]:
    """从 SubjectScore 行列表计算 competition rank。"""
    valid = []
    for s in rows:
        pct = normalize_percentile(s.grade_percentile)
        if pct is not None:
            valid.append((s.student_id, pct, "pct"))
        elif exam_grade in (2, 3) and subject in _ELECTIVE_SUBJECTS:
            if s.grade_score is not None:
                valid.append((s.student_id, float(s.grade_score), "gs"))
        else:
            if s.raw_score is not None:
                valid.append((s.student_id, float(s.raw_score), "raw"))

    if not valid:
        return {}

    # 百分位：高=好 → 降序；raw_score/grade_score：高=好 → 降序
    valid.sort(key=lambda x: x[1], reverse=True)
    rank_map: dict[str, int] = {}
    prev_val = None
    prev_rank = 0
    for idx, (sid, val, _kind) in enumerate(valid, 1):
        if prev_val is not None and val == prev_val:
            rank_map[sid] = prev_rank
        else:
            rank_map[sid] = idx
            prev_rank = idx
            prev_val = val
    return rank_map


def percentile_to_rank(percentile: Optional[float], cohort_size: Optional[int]) -> Optional[int]:
    """百分位换算为名次（percentile 越高 → rank 越小）。"""
    pct = normalize_percentile(percentile)
    if pct is None or not cohort_size:
        return None
    return max(1, int(math.ceil(pct * cohort_size)))


# ────────────────────────────── 频次区间 ──────────────────────────────


def percentile_bin_value(value: Optional[float]) -> Optional[str]:
    """百分位 → 五等分区间 key。"""
    pct = normalize_percentile(value)
    if pct is None:
        return None
    for key, _, lower, upper in PERCENTILE_BINS:
        if pct <= upper and (pct > lower or lower == 0):
            return key
    return PERCENTILE_BINS[-1][0]


def band_classify(subject_rank: Optional[int], band_cfg: dict) -> list[str]:
    """根据 subject_rank + band_config 返回段位标签列表。

    返回的标签是 focus-list 使用的 issues（临界段/薄弱段）。
    高分段不返回标签（不进入 focus-list）。
    """
    if subject_rank is None:
        return []
    issues: list[str] = []
    if band_cfg["critical_min"] <= subject_rank <= band_cfg["critical_max"]:
        issues.append("临界段")
    if subject_rank >= band_cfg["weak_min"]:
        issues.append("薄弱段")
    return issues


def grade_score_bin_value(value: Optional[float]) -> Optional[str]:
    """等级分 → 精确分值 bin key。"""
    if value is None:
        return None
    score = int(round(float(value)))
    if score in GRADE_SCORE_VALUES:
        return f"g{score}"
    return None
