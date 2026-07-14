"""单科排名指标层（阶段4单科教学化重构）。

本模块已完全单科教学化：
- 不再查询/引用总分表
- rank_metric_options 只返回当前任教学科的唯一选项

rank_range_filter / rank_frequency_stats 逻辑已内联到 router.py 端点中。
"""
from __future__ import annotations

from typing import Any, Optional

# ── 频次区间常量（供 router.py / chat/tools.py 等导入）──

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


def _normalize_percentile(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    if number > 1:
        number = number / 100
    return max(0, min(number, 1))


def _percentile_bin(value: Optional[float]) -> Optional[str]:
    pct = _normalize_percentile(value)
    if pct is None:
        return None
    for key, _, lower, upper in PERCENTILE_BINS:
        if pct <= upper and (pct > lower or lower == 0):
            return key
    return PERCENTILE_BINS[-1][0]


def _grade_score_bin(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    score = int(round(float(value)))
    if score in GRADE_SCORE_VALUES:
        return f"g{score}"
    return None


def _rank_bin(rank: Optional[int]) -> Optional[str]:
    if rank is None or rank < 1:
        return None
    start = ((int(rank) - 1) // 40) * 40 + 1
    return f"r{start}_{start + 39}"


def _rank_bin_label(key: str) -> str:
    start, end = key.removeprefix("r").split("_")
    return f"{start}-{end}名次数"


def _parse_exam_ids(exam_ids: Optional[str | list[int]]) -> list[int]:
    if not exam_ids:
        return []
    if isinstance(exam_ids, list):
        return [int(value) for value in exam_ids]
    return [int(part) for part in str(exam_ids).split(",") if part.strip()]


# ── 兼容层：chat/tools.py 仍调用旧签名，内部委托单科逻辑 ──


def rank_range_filter(
    *,
    exam_id: int,
    metric: str,
    rank_min: int = 1,
    rank_max: int = 100,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
) -> dict[str, Any]:
    """兼容入口：chat/tools.py 调用。委托 router 端点逻辑（单学科化）。"""
    from app.db.models import SessionLocal
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank,
    )
    from app.db.models import Exam, SubjectScore
    from app.analysis.scope import student_class_map

    db = SessionLocal()
    try:
        ctx = resolve_single_subject_context(db, teaching_class_id=teaching_class_id)
        subject = ctx.subject
        member_ids = ctx.member_ids

        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise ValueError("考试不存在")

        rank_min = max(1, int(rank_min))
        rank_max = int(rank_max)
        rank_map = compute_subject_rank(db, subject, exam_id, member_ids, exam_grade=exam.grade)
        label_map = student_class_map(db, exam.grade)

        subject_rows = (
            db.query(SubjectScore)
            .filter(
                SubjectScore.exam_id == exam_id,
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(member_ids),
                SubjectScore.raw_score.isnot(None) | SubjectScore.grade_score.isnot(None),
            )
            .all()
        )
        rows = []
        for r in subject_rows:
            sr = rank_map.get(r.student_id)
            if sr is None or not (rank_min <= sr <= rank_max):
                continue
            label, _ = label_map.get(r.student_id, (None, None))
            rows.append({
                "student_id": r.student_id,
                "name": r.name or r.student_id,
                "class_label": label,
                "raw_score": r.raw_score,
                "grade_score": r.grade_score,
                "grade_percentile": r.grade_percentile,
                "subject_rank": sr,
            })
        rows.sort(key=lambda x: (x["subject_rank"], x["student_id"]))
        return {
            "teaching_subject": subject,
            "metric_basis": "subject_rank",
            "exam": {"id": exam.id, "name": exam.name, "grade": exam.grade, "exam_date": exam.exam_date},
            "metric": metric,
            "rank_min": rank_min,
            "rank_max": rank_max,
            "teaching_class_id": teaching_class_id,
            "rows": rows,
        }
    finally:
        db.close()


def rank_frequency_stats(
    *,
    grade: int,
    metric: str,
    exam_ids: Optional[str | list[int]] = None,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
    recent_count: int = 5,
) -> dict[str, Any]:
    """兼容入口：chat/tools.py 调用。委托单学科频次统计。"""
    from app.db.models import SessionLocal, Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank,
        normalize_percentile,
        valid_exam_ids_for_subject,
        _ELECTIVE_SUBJECTS,
    )
    from app.analysis.scope import student_class_map

    db = SessionLocal()
    try:
        ctx = resolve_single_subject_context(db, teaching_class_id=teaching_class_id, grade=grade)
        subject = ctx.subject
        member_ids = ctx.member_ids

        is_grade_score_mode = metric.startswith("subject_grade:")

        valid_ids = valid_exam_ids_for_subject(db, subject, member_ids, grade=grade)
        parsed = _parse_exam_ids(exam_ids)
        if parsed:
            selected_ids = sorted(set(parsed) & valid_ids)
        else:
            all_valid = (
                db.query(Exam)
                .filter(Exam.id.in_(valid_ids), Exam.grade == grade)
                .order_by(Exam.exam_date, Exam.id)
                .all()
            )
            n = max(1, min(int(recent_count or 5), 12))
            selected_ids = [e.id for e in all_valid[-n:]]

        exams = (
            db.query(Exam).filter(Exam.id.in_(selected_ids)).order_by(Exam.exam_date, Exam.id).all()
        ) if selected_ids else []

        label_map = student_class_map(db, grade)

        if is_grade_score_mode:
            bins = [{"key": b[0], "label": b[1], "separator_after": b[3]} for b in GRADE_SCORE_BINS]
        else:
            bins = [{"key": b[0], "label": b[1]} for b in PERCENTILE_BINS]

        student_rows: dict[str, dict[str, Any]] = {}
        for exam in exams:
            rows = (
                db.query(SubjectScore)
                .filter(
                    SubjectScore.exam_id == exam.id,
                    SubjectScore.subject == subject,
                    SubjectScore.student_id.in_(member_ids),
                    SubjectScore.raw_score.isnot(None) | SubjectScore.grade_score.isnot(None),
                )
                .all()
            )
            for r in rows:
                sid = r.student_id
                label, _ = label_map.get(sid, (None, None))
                entry = student_rows.setdefault(
                    sid,
                    {"student_id": sid, "name": r.name or sid, "class_label": label, "total_count": 0},
                )
                if r.name:
                    entry["name"] = r.name
                if is_grade_score_mode:
                    bin_key = _grade_score_bin(r.grade_score)
                else:
                    pct = normalize_percentile(r.grade_percentile)
                    bin_key = _percentile_bin(pct) if pct is not None else None
                if bin_key:
                    entry[bin_key] = entry.get(bin_key, 0) + 1
                    entry["total_count"] += 1

        rows_out = []
        for entry in student_rows.values():
            for bin_info in bins:
                entry.setdefault(bin_info["key"], 0)
            rows_out.append(entry)
        rows_out.sort(
            key=lambda row: (
                -sum((i + 1) * row.get(b["key"], 0) for i, b in enumerate(bins)),
                row["student_id"],
            )
        )
        return {
            "teaching_subject": subject,
            "grade": grade,
            "metric": metric,
            "teaching_class_id": teaching_class_id,
            "exams": [{"id": e.id, "name": e.name, "exam_date": e.exam_date} for e in exams],
            "bins": bins,
            "rows": rows_out,
        }
    finally:
        db.close()
