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


def expected_metric(subject: str, grade: int, mode: str) -> str:
    """Return the sole metric allowed by rank-metrics for this context."""
    if mode not in {"range", "frequency"}:
        raise ValueError("mode 只能是 range 或 frequency")
    if mode == "frequency" and grade in (2, 3) and subject in _ELECTIVE_SUBJECTS:
        return f"subject_grade:{subject}"
    return f"subject:{subject}"


def validate_metric_subject(metric: str, subject: str) -> None:
    """Preserve legacy validation errors for bad formats/subjects."""
    if metric.startswith("total:"):
        raise ValueError("单学科化后不再支持总分指标")
    if metric.startswith("subject:") or metric.startswith("subject_grade:"):
        metric_subject = metric.split(":", 1)[1]
        if metric_subject != subject:
            raise ValueError(
                f"指标学科「{metric_subject}」与教师任教科目「{subject}」不一致"
            )
        return
    raise ValueError(f"不支持的指标格式：{metric}")


def validate_metric(metric: str, subject: str, grade: int, mode: str) -> None:
    """Reject metrics not advertised by rank-metrics for grade/mode."""
    validate_metric_subject(metric, subject)
    expected = expected_metric(subject, grade, mode)
    if metric != expected:
        raise ValueError(
            f"当前年级和模式只支持指标「{expected}」，不支持「{metric}」"
        )


# ────────────────────────────── 上下文数据类 ──────────────────────────────


@dataclass(frozen=True)
class SingleSubjectContext:
    """单学科分析上下文：学科 + 允许的学生学号集合 + 教学班归属。

    扩展字段用于统一 label/rank 计算（六端点 + wrapper 禁止各自复制逻辑）：
    - explicit_class_id: 请求显式指定的教学班 id（None=全部模式）。
    - member_to_default_class: 每个成员学号 → 其默认教学班 id
      （重叠学生取 sort_order/id 最前者；全部模式据此分组排名）。
    - class_labels: teaching_class_id → label（显式班时强制覆盖 label）。
    """
    subject: str
    member_ids: frozenset[str]
    explicit_class_id: Optional[int] = None
    member_to_default_class: dict = None  # type: ignore[assignment]
    class_labels: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        # frozen=True 下用 object.__setattr__ 设默认值
        if self.member_to_default_class is None:
            object.__setattr__(self, "member_to_default_class", {})
        if self.class_labels is None:
            object.__setattr__(self, "class_labels", {})


def label_for_student(ctx: SingleSubjectContext, sid: str, return_tc_id: bool = False):
    """统一 label 解析：显式班优先 → 该班 label；否则成员默认班 label。

    Blocker 3：学生 x 同属 A/B，显式 teaching_class_id=B 时返回 B 的 label。
    return_tc_id=True 时返回 (label, tc_id)，供端点写回 teaching_class_id 字段。
    """
    if ctx.explicit_class_id is not None:
        tc_id = ctx.explicit_class_id
    else:
        tc_id = ctx.member_to_default_class.get(sid)
    label = ctx.class_labels.get(tc_id) if tc_id is not None else None
    if return_tc_id:
        return label, tc_id
    return label


def group_members_by_class(ctx: SingleSubjectContext) -> dict[int, set[str]]:
    """把成员按默认教学班分组。

    Blocker 5：全部模式按班分别排名的前提。显式班模式下只有一组。
    重叠学生按 member_to_default_class 的默认班归类（仅出现在一组）。
    """
    if ctx.explicit_class_id is not None:
        # 显式班：member_ids 已由 resolver 限定为该班成员（含重叠学生），
        # 直接整组返回，不再按 default_class 二次过滤。
        return {ctx.explicit_class_id: set(ctx.member_ids)}
    groups: dict[int, set[str]] = {}
    for sid in ctx.member_ids:
        tc_id = ctx.member_to_default_class.get(sid)
        if tc_id is None:
            continue
        groups.setdefault(tc_id, set()).add(sid)
    return groups


def compute_rank_multi_class(
    ctx: SingleSubjectContext,
    rows_by_sid: dict,
    exam_grade: Optional[int],
) -> dict[str, int]:
    """全部模式按班分别排名；显式班只排该班。

    Blocker 5：每个学生按其实际所属教学班独立排名，不能把 A/B 合并成一个池。
    rows_by_sid: {student_id: SubjectScore-like row}。
    """
    groups = group_members_by_class(ctx)
    combined: dict[str, int] = {}
    for _tc_id, member_set in groups.items():
        rows = [rows_by_sid[sid] for sid in member_set if sid in rows_by_sid]
        if not rows:
            continue
        ranks = _competition_rank_from_rows(rows, ctx.subject, exam_grade)
        combined.update(ranks)
    return combined


def resolve_single_subject_context(
    db,
    *,
    teaching_class_id: Optional[int] = None,
    grade: Optional[int] = None,
) -> SingleSubjectContext:
    """解析教师唯一任教学科 + 允许的教学班成员范围 + 教学班归属。

    与 resolve_exam_context 的区别：grade 可选，用于按年级过滤成员范围
    （rank-frequency 需要按年级限定）。

    扩展（Blocker 3/4/5）：
    - 显式 teaching_class_id 时，其 grade 必须与请求 grade（或其考试 grade）
      一致，否则 ValueError（跨年级拒绝）。
    - 填充 explicit_class_id / member_to_default_class / class_labels，
      供六端点统一 label/rank 计算。

    Returns:
        SingleSubjectContext(subject, member_ids, explicit_class_id,
        member_to_default_class, class_labels)

    Raises:
        SubjectNotConfiguredError / SubjectConflictError / NoTeachingScopeError /
        ValueError
    """
    from app.analysis.exam_context import resolve_exam_context, NoTeachingScopeError
    from app.db.models import TeachingClass, TeachingClassMember

    # resolve_exam_context remains the authority for the teacher's configured
    # subject and explicit-class subject conflict checks.  Its all-class member
    # union is intentionally NOT reused here: legacy classes of another subject
    # may still exist in the database and must never expand a single-subject
    # analysis scope.
    base_ctx = resolve_exam_context(db, teaching_class_id=teaching_class_id)
    subject = base_ctx.subject

    classes_q = db.query(TeachingClass).filter(TeachingClass.subject == subject)
    if teaching_class_id is not None:
        classes_q = classes_q.filter(TeachingClass.id == teaching_class_id)
    if grade is not None:
        classes_q = classes_q.filter(TeachingClass.grade == grade)
    classes = classes_q.order_by(TeachingClass.sort_order, TeachingClass.id).all()

    if teaching_class_id is not None and not classes:
        # Distinguish a cross-grade selection from a missing/foreign class so
        # callers get an explicit domain error instead of an empty data set.
        tc = db.query(TeachingClass).filter(TeachingClass.id == teaching_class_id).first()
        if tc is not None and grade is not None and tc.grade != grade:
            raise ValueError(
                f"教学班「{tc.label}」属于年级 {tc.grade}，与请求年级 {grade} 不一致"
            )
        raise ValueError("教学班不存在或不属于当前任教学科")
    if not classes:
        raise NoTeachingScopeError("当前任教学科没有可用教学班")

    class_ids = [tc.id for tc in classes]
    member_rows = (
        db.query(TeachingClassMember.teaching_class_id, TeachingClassMember.student_id)
        .filter(TeachingClassMember.teaching_class_id.in_(class_ids))
        .all()
    )
    member_ids = {
        sid for _tc_id, sid in member_rows
        if sid and not sid.startswith("_anon:")
    }
    if not member_ids:
        raise NoTeachingScopeError("当前任教学科的教学班没有有效成员")

    class_labels = {tc.id: tc.label for tc in classes}
    member_to_default: dict[str, int] = {}
    # classes are already in sort_order/id order; setdefault gives overlapping
    # students one deterministic default class in all-class mode.
    members_by_class: dict[int, list[str]] = {}
    for tc_id, sid in member_rows:
        if sid and not sid.startswith("_anon:"):
            members_by_class.setdefault(tc_id, []).append(sid)
    for tc in classes:
        for sid in members_by_class.get(tc.id, []):
            member_to_default.setdefault(sid, tc.id)

    return SingleSubjectContext(
        subject=subject,
        member_ids=frozenset(member_ids),
        explicit_class_id=teaching_class_id,
        member_to_default_class=member_to_default,
        class_labels=class_labels,
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
    from app.db.models import Exam, SubjectScore

    q = (
        db.query(SubjectScore.exam_id)
        .join(Exam, Exam.id == SubjectScore.exam_id)
        .filter(
            SubjectScore.subject == subject,
            SubjectScore.student_id.in_(member_ids),
        )
        .filter(
            SubjectScore.raw_score.isnot(None)
            | SubjectScore.grade_score.isnot(None)
        )
    )
    if grade is not None:
        q = q.filter(Exam.grade == grade)
    return {row[0] for row in q.distinct().all()}


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
    """Competition ranking（同分同名次）— 单一合并池（旧入口，保留兼容）。

    注意：本函数把所有 member_ids 当成一个池排名。新代码应改用
    compute_subject_rank_contextual 以遵守「全部模式按班分别排名」的口径
    （Blocker 5）。
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


def compute_subject_rank_contextual(
    db,
    ctx: "SingleSubjectContext",
    exam_id: int,
    exam_grade: Optional[int] = None,
) -> tuple[dict[str, int], dict]:
    """按上下文计算排名（Blocker 5：全部模式按班分别排名）。

    返回 (rank_map, rows_by_sid)。
    rank_map: {student_id: rank}，每班独立从 rank1 开始。
    rows_by_sid: {student_id: SubjectScore row}，供端点构建响应行。
    """
    from app.db.models import SubjectScore

    rows = (
        db.query(SubjectScore)
        .filter(
            SubjectScore.exam_id == exam_id,
            SubjectScore.subject == ctx.subject,
            SubjectScore.student_id.in_(ctx.member_ids),
        )
        .filter(
            SubjectScore.raw_score.isnot(None)
            | SubjectScore.grade_score.isnot(None)
        )
        .all()
    )
    rows_by_sid = {r.student_id: r for r in rows}
    rank_map = compute_rank_multi_class(ctx, rows_by_sid, exam_grade)
    return rank_map, rows_by_sid


def _competition_rank_from_rows(
    rows: list,
    subject: str,
    exam_grade: Optional[int],
) -> dict[str, int]:
    """从 SubjectScore 行列表计算 competition rank（同分同名次 + 跳号）。

    统一量纲规则（禁止逐行选不同 basis 后放入同一排名池）：
    - 高二/高三选考学科（物化生政史地）：整个池统一用 grade_score 降序。
      仅 grade_score 有值的行也可排名；grade_score 为 None 的行不参与。
    - 其他学科：先看参与排名的所有行是否都有规范化后的 grade_percentile。
      若全部有 percentile，则整个池按 percentile **升序**（越小越好）；
      只要有任一行缺 percentile，则整个池统一回退为 raw_score 降序，
      raw_score 缺失者不参与排名。
    """
    is_elective_high = exam_grade in (2, 3) and subject in _ELECTIVE_SUBJECTS

    if is_elective_high:
        scored = [
            (s.student_id, float(s.grade_score))
            for s in rows
            if s.grade_score is not None
        ]
        scored.sort(key=lambda x: x[1], reverse=True)  # grade_score 高=好
    else:
        normed = [
            (s.student_id, normalize_percentile(s.grade_percentile))
            for s in rows
            if s.raw_score is not None or s.grade_score is not None
        ]
        all_have_pct = all(pct is not None for _sid, pct in normed) and len(normed) > 0
        if all_have_pct:
            scored = [(sid, pct) for sid, pct in normed if pct is not None]
            scored.sort(key=lambda x: x[1])  # percentile 越小越好 → 升序
        else:
            scored = [
                (s.student_id, float(s.raw_score))
                for s in rows
                if s.raw_score is not None
            ]
            scored.sort(key=lambda x: x[1], reverse=True)  # raw 高=好

    rank_map: dict[str, int] = {}
    prev_val = None
    prev_rank = 0
    for idx, (sid, val) in enumerate(scored, 1):
        if prev_val is not None and val == prev_val:
            rank_map[sid] = prev_rank
        else:
            rank_map[sid] = idx
            prev_rank = idx
            prev_val = val
    return rank_map


def percentile_to_rank(percentile: Optional[float], cohort_size: Optional[int]) -> Optional[int]:
    """百分位换算为近似名次（percentile 越小 → rank 越小）。"""
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
