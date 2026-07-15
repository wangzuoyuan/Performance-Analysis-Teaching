from collections import Counter
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["analysis"])


class BandConfigPayload(BaseModel):
    high_score_max: int
    critical_min: int
    critical_max: int
    weak_min: int


# 选考学科：高二/高三 物化生政史地
_ELECTIVE_SUBJECTS = frozenset(["物理", "化学", "生物", "政治", "历史", "地理"])


def _validate_metric_matches_subject(
    metric: str,
    subject: str,
    *,
    grade: int,
    mode: str,
):
    """Validate against the single metric advertised for grade/mode."""
    from app.analysis.single_subject_metrics import validate_metric

    validate_metric(metric, subject, grade, mode)


def _percentile_bin_from_rank(rank: int, cohort_size: int) -> Optional[str]:
    """从 subject_rank 换算百分位 bin（cohort_size 为该场有效人数）。"""
    from app.analysis.rank_metrics import PERCENTILE_BINS
    if cohort_size <= 0 or rank <= 0:
        return None
    pct = rank / cohort_size  # rank 1 → pct 最小
    for key, _, lower, upper in PERCENTILE_BINS:
        if pct <= upper and (pct > lower or lower == 0):
            return key
    return PERCENTILE_BINS[-1][0]


def _percentile_bin(pct: float) -> Optional[str]:
    """从规范化百分位（0..1）返回 bin key。"""
    from app.analysis.rank_metrics import PERCENTILE_BINS
    for key, _, lower, upper in PERCENTILE_BINS:
        if pct <= upper and (pct > lower or lower == 0):
            return key
    return PERCENTILE_BINS[-1][0]


def _rank_key_for_subject(subject: str, exam_grade: int):
    """返回 (rank_value_extractor, lower_is_better) 用于 scope_rank 计算。

    - 高二/高三选考学科：用 grade_score（越高越好）；raw_score 为空时仍可排名。
    - 其他学科（语数英、高一单科）：用 raw_score（越高越好）。
    """
    if exam_grade in (2, 3) and subject in _ELECTIVE_SUBJECTS:
        return (lambda s: s.grade_score, False)
    return (lambda s: s.raw_score, False)


def _competition_rank(scores: list, extract_value, lower_is_better: bool) -> dict:
    """Competition ranking（同分同名次）：按 extract_value 排名。

    返回 {student_id: rank}。value 为 None 的不参与排名。
    """
    valid = [(s.student_id, extract_value(s)) for s in scores if extract_value(s) is not None]
    if not valid:
        return {}
    valid.sort(key=lambda x: x[1], reverse=not lower_is_better)
    rank_map: dict[str, int] = {}
    prev_val = None
    prev_rank = 0
    for idx, (sid, val) in enumerate(valid, 1):
        if prev_val is not None and val == prev_val:
            rank_map[sid] = prev_rank
        else:
            rank_map[sid] = idx
            prev_rank = idx
            prev_val = val
    return rank_map


@router.get("/rank-metrics")
async def get_rank_metrics(grade: int, mode: str = "frequency"):
    """返回当前任教学科在排名区间筛选/排名频次统计中可选的指标（单学科化）。

    只返回当前任教学科唯一选项和 teaching_subject，不再列出其他学科或
    total:* 。高二/三选考 frequency 基础为 exact grade_score；其他为
    subject_percentile/subject_rank。mode 非法 400。
    """
    from app.db.models import SessionLocal
    from app.teaching.subject import (
        resolve_teaching_subject,
        SubjectNotConfiguredError,
        SubjectConflictError,
    )

    if mode not in {"range", "frequency"}:
        raise HTTPException(400, "mode 只能是 range 或 frequency")

    db = SessionLocal()
    try:
        try:
            subject = resolve_teaching_subject(db)
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))

        _ELECTIVE = ["物理", "化学", "生物", "政治", "历史", "地理"]
        is_elective = subject in _ELECTIVE
        is_high_grade = grade in (2, 3)

        metrics = []
        if mode == "frequency" and is_elective and is_high_grade:
            metrics.append({
                "value": f"subject_grade:{subject}",
                "label": f"{subject}等级分",
                "kind": "subject_grade_score",
            })
        else:
            metrics.append({
                "value": f"subject:{subject}",
                "label": subject,
                "kind": "subject_percentile",
            })
        return {
            "grade": grade,
            "mode": mode,
            "teaching_subject": subject,
            "metrics": metrics,
        }
    finally:
        db.close()


@router.get("/rank-range")
async def get_rank_range(
    exam_id: int,
    metric: str,
    rank_min: int = 1,
    rank_max: int = 100,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
):
    """按单次考试、当前学科 subject_rank 筛选学生（单学科化）。

    仅按当前学科 subject_rank 筛选；输出 teaching_subject、metric_basis、exam、
    合法范围 rows。每行仅含单科字段，禁止 total/year-total 字段。
    """
    from app.db.models import SessionLocal, Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
    )
    from app.teaching.subject import (
        SubjectNotConfiguredError,
        SubjectConflictError,
    )
    from app.analysis.exam_context import NoTeachingScopeError

    if class_num is not None:
        raise HTTPException(400, "请使用 teaching_class_id 参数，不再支持 class_num")

    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise HTTPException(404, "考试不存在")

        try:
            ctx = resolve_single_subject_context(
                db,
                teaching_class_id=teaching_class_id,
                grade=exam.grade,
            )
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))

        subject = ctx.subject

        # Only the metric advertised by rank-metrics for range mode is valid.
        try:
            _validate_metric_matches_subject(
                metric,
                subject,
                grade=exam.grade,
                mode="range",
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        rank_min = max(1, int(rank_min))
        rank_max = int(rank_max)
        if rank_max < rank_min:
            raise HTTPException(400, "排名区间上界不能小于下界")

        rank_map, rows_by_sid = compute_subject_rank_contextual(
            db, ctx, exam_id, exam_grade=exam.grade,
        )

        rows = []
        for sid, r in rows_by_sid.items():
            sr = rank_map.get(sid)
            if sr is None or not (rank_min <= sr <= rank_max):
                continue
            label = label_for_student(ctx, sid)
            rows.append({
                "student_id": sid,
                "name": r.name or sid,
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


@router.get("/rank-frequency")
async def get_rank_frequency(
    grade: int,
    metric: str,
    exam_ids: Optional[str] = None,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
    recent_count: int = 5,
):
    """按多场考试统计学生落入各排名/百分位/等级分区间的频次（单学科化）。

    只选当前学科在合法范围内确有真实分数的考试。高二/三选考按精确等级分
    70/67/.../40 频次；其他按当前学科百分位或 subject_rank 区间。
    仅返回 member scope 学生；其他学科/空分残留考试不能进入 selected_exams 或计数。
    """
    from app.db.models import SessionLocal, Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
        normalize_percentile,
        valid_exam_ids_for_subject,
        group_members_by_class,
        _ELECTIVE_SUBJECTS,
    )
    from app.analysis.rank_metrics import (
        PERCENTILE_BINS, GRADE_SCORE_VALUES, GRADE_SCORE_BINS,
        _grade_score_bin, _parse_exam_ids,
    )
    from app.teaching.subject import (
        SubjectNotConfiguredError,
        SubjectConflictError,
    )
    from app.analysis.exam_context import NoTeachingScopeError

    if class_num is not None:
        raise HTTPException(400, "请使用 teaching_class_id 参数，不再支持 class_num")

    db = SessionLocal()
    try:
        try:
            ctx = resolve_single_subject_context(
                db, teaching_class_id=teaching_class_id, grade=grade,
            )
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))

        subject = ctx.subject
        member_ids = ctx.member_ids

        try:
            _validate_metric_matches_subject(
                metric,
                subject,
                grade=grade,
                mode="frequency",
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        is_grade_score_mode = metric.startswith("subject_grade:")

        # 只选当前学科有真实分数的考试
        valid_ids = valid_exam_ids_for_subject(db, subject, member_ids, grade=grade)

        parsed = _parse_exam_ids(exam_ids)
        if parsed:
            selected_ids = sorted(set(parsed) & valid_ids)
        else:
            # 按 recent_count 取最近 N 场
            all_valid = (
                db.query(Exam)
                .filter(Exam.id.in_(valid_ids), Exam.grade == grade)
                .order_by(Exam.exam_date, Exam.id)
                .all()
            )
            n = max(1, min(int(recent_count or 5), 12))
            selected_ids = [e.id for e in all_valid[-n:]]

        exams = (
            db.query(Exam)
            .filter(Exam.id.in_(selected_ids), Exam.grade == grade)
            .order_by(Exam.exam_date, Exam.id)
            .all()
        ) if selected_ids else []

        # 构建 bins
        if is_grade_score_mode:
            bins = [
                {"key": b[0], "label": b[1], "separator_after": b[3]}
                for b in GRADE_SCORE_BINS
            ]
        else:
            bins = [
                {"key": b[0], "label": b[1]}
                for b in PERCENTILE_BINS
            ]

        # 逐考试统计
        student_rows: dict[str, dict[str, Any]] = {}
        for exam in exams:
            rank_map, rows_by_sid = compute_subject_rank_contextual(
                db, ctx, exam.id, exam_grade=exam.grade,
            )
            groups = group_members_by_class(ctx)
            group_for_sid = {
                sid: tc_id for tc_id, members in groups.items() for sid in members
            }
            ranked_size_by_group = {
                tc_id: sum(1 for sid in members if sid in rank_map)
                for tc_id, members in groups.items()
            }
            all_pct_by_group = {
                tc_id: bool(ranked_size_by_group[tc_id]) and all(
                    normalize_percentile(rows_by_sid[sid].grade_percentile) is not None
                    for sid in members
                    if sid in rank_map and sid in rows_by_sid
                )
                for tc_id, members in groups.items()
            }
            for sid, r in rows_by_sid.items():
                label = label_for_student(ctx, sid)
                entry = student_rows.setdefault(
                    sid,
                    {
                        "student_id": sid,
                        "name": r.name or sid,
                        "class_label": label,
                        "total_count": 0,
                    },
                )
                if r.name:
                    entry["name"] = r.name

                if is_grade_score_mode:
                    bin_key = _grade_score_bin(r.grade_score)
                else:
                    tc_id = group_for_sid.get(sid)
                    if tc_id is not None and all_pct_by_group.get(tc_id, False):
                        bin_key = _percentile_bin(
                            normalize_percentile(r.grade_percentile)
                        )
                    else:
                        sr = rank_map.get(sid)
                        if tc_id is None:
                            group_size = 0
                        else:
                            group_size = ranked_size_by_group.get(tc_id, 0)
                        bin_key = (
                            _percentile_bin_from_rank(sr, group_size)
                            if sr is not None and group_size > 0
                            else None
                        )

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
            "metric_kind": "subject_grade_score" if is_grade_score_mode else "subject_percentile",
            "teaching_class_id": teaching_class_id,
            "exams": [{"id": e.id, "name": e.name, "exam_date": e.exam_date} for e in exams],
            "bins": bins,
            "rows": rows_out,
        }
    finally:
        db.close()


@router.get("/analysis-config")
async def get_analysis_config():
    """返回当前重点关注段位阈值（供前端展示/编辑）。"""
    from app.analysis.config import get_band_config
    return get_band_config()


@router.put("/analysis-config")
async def update_analysis_config(payload: BandConfigPayload):
    """保存用户自定义的段位阈值（全局单行）。"""
    from app.db.models import SessionLocal, AnalysisConfig
    from datetime import datetime

    # 基本合法性校验：边界须为正、区间下界不大于上界
    if payload.high_score_max < 1 or payload.critical_min < 1 or payload.weak_min < 1:
        raise HTTPException(400, "排名阈值必须为正整数")
    if payload.critical_min > payload.critical_max:
        raise HTTPException(400, "临界段下界不能大于上界")

    db = SessionLocal()
    try:
        cfg = db.query(AnalysisConfig).filter(AnalysisConfig.id == 1).first()
        if not cfg:
            cfg = AnalysisConfig(id=1)
            db.add(cfg)
        cfg.high_score_max = payload.high_score_max
        cfg.critical_min = payload.critical_min
        cfg.critical_max = payload.critical_max
        cfg.weak_min = payload.weak_min
        cfg.updated_at = datetime.utcnow()
        db.commit()
        return {
            "high_score_max": cfg.high_score_max,
            "critical_min": cfg.critical_min,
            "critical_max": cfg.critical_max,
            "weak_min": cfg.weak_min,
        }
    finally:
        db.close()


@router.get("/band-trend")
async def get_band_trend(
    grade: int,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
):
    """某年级历次考试的三段（高分/临界/薄弱）人数趋势（单学科化）。

    仅统计当前学科确有真实分数的考试和合法成员，按每场 subject_rank + band config
    统计 high_score/critical/weak。全部模式仅为所教班成员并集。
    """
    from app.db.models import SessionLocal, Exam, TeachingClass
    from app.analysis.config import get_band_config
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import (
        SubjectNotConfiguredError,
        SubjectConflictError,
    )
    from app.analysis.exam_context import NoTeachingScopeError

    if class_num is not None:
        raise HTTPException(400, "请使用 teaching_class_id 参数，不再支持 class_num")

    db = SessionLocal()
    try:
        try:
            ctx = resolve_single_subject_context(
                db, teaching_class_id=teaching_class_id, grade=grade,
            )
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))

        subject = ctx.subject
        member_ids = ctx.member_ids
        cfg = get_band_config(db)

        # 只选当前学科有真实分数的考试
        valid_ids = valid_exam_ids_for_subject(db, subject, member_ids, grade=grade)
        exams = (
            db.query(Exam)
            .filter(Exam.id.in_(valid_ids), Exam.grade == grade)
            .order_by(Exam.exam_date, Exam.id)
            .all()
        )

        series = []
        for exam in exams:
            rank_map, _rows = compute_subject_rank_contextual(
                db, ctx, exam.id, exam_grade=exam.grade,
            )
            high = crit = weak = 0
            for sid, rank in rank_map.items():
                if 1 <= rank <= cfg["high_score_max"]:
                    high += 1
                if cfg["critical_min"] <= rank <= cfg["critical_max"]:
                    crit += 1
                if rank >= cfg["weak_min"]:
                    weak += 1
            series.append({
                "exam_id": exam.id,
                "exam_name": exam.name,
                "exam_date": exam.exam_date,
                "high_score": high,
                "critical": crit,
                "weak": weak,
            })

        # available_classes is restricted to the current teaching subject and
        # requested grade.  Legacy classes of another subject must not leak.
        class_ids = list(ctx.class_labels)
        classes = (
            db.query(TeachingClass)
            .filter(TeachingClass.id.in_(class_ids), TeachingClass.grade == grade)
            .order_by(TeachingClass.sort_order, TeachingClass.id)
            .all()
        ) if class_ids else []
        my_classes = [
            {"label": tc.label, "teaching_class_id": tc.id, "mine": True, "kind": tc.kind}
            for tc in classes
        ]
        return {
            "teaching_subject": subject,
            "series": series,
            "band_config": cfg,
            "grade": grade,
            "teaching_class_id": teaching_class_id,
            "available_classes": my_classes,
        }
    finally:
        db.close()

@router.get("/exams")
async def list_exams(
    grade: Optional[int] = None,
    teaching_class_id: Optional[int] = None,
):
    """列出已建档考试（单学科化）。

    只返回当前任教学科在允许的教学班成员范围内确有成绩的考试。
    其他学科有成绩但当前学科无成绩的考试不会出现。学科由后端教师上下文
    解析，前端无需也不可传入。teaching_class_id 限定为该教学班成员集合
    （不传=全部教学班成员并集）。
    """
    from app.db.models import SessionLocal, Exam, SubjectScore
    from app.analysis.exam_context import (
        resolve_exam_context,
        SubjectNotConfiguredError,
        NoTeachingScopeError,
    )
    from app.teaching.subject import SubjectConflictError
    db = SessionLocal()
    try:
        try:
            ctx = resolve_exam_context(db, teaching_class_id=teaching_class_id)
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            # teaching_class_id 不存在
            raise HTTPException(404, str(e))

        # 找出在允许成员范围内、当前任教学科确有真实分数（raw_score 或 grade_score
        # 至少一个非空）的考试 id。只有 grade_percentile 或全空残留行不算成绩。
        valid_exam_ids = set(
            row[0]
            for row in (
                db.query(SubjectScore.exam_id)
                .filter(
                    SubjectScore.subject == ctx.subject,
                    SubjectScore.student_id.in_(ctx.member_ids),
                )
                .filter(
                    SubjectScore.raw_score.isnot(None)
                    | SubjectScore.grade_score.isnot(None)
                )
                .distinct()
                .all()
            )
        )

        query = db.query(Exam).filter(Exam.id.in_(valid_exam_ids)).order_by(Exam.exam_date.desc())
        if grade:
            query = query.filter(Exam.grade == grade)
        exams = query.all()
        return {
            "subject": ctx.subject,
            "exams": [{
                "id": e.id,
                "name": e.name,
                "grade": e.grade,
                "semester": e.semester,
                "exam_date": e.exam_date,
                "exam_type": e.exam_type,
            } for e in exams]
        }
    finally:
        db.close()

@router.delete("/exams/{exam_id}")
async def delete_exam(exam_id: int):
    """删除考试及其全部关联数据（学生分数、总分、班均分、上传记录）"""
    from app.db.models import (
        SessionLocal,
        Exam,
        Upload,
        SubjectScore,
        TotalScore,
        ClassAverage,
    )

    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise HTTPException(404, "考试不存在")

        exam_name = exam.name
        subject_deleted = db.query(SubjectScore).filter(SubjectScore.exam_id == exam_id).delete(synchronize_session=False)
        total_deleted = db.query(TotalScore).filter(TotalScore.exam_id == exam_id).delete(synchronize_session=False)
        class_avg_deleted = db.query(ClassAverage).filter(ClassAverage.exam_id == exam_id).delete(synchronize_session=False)
        upload_deleted = db.query(Upload).filter(Upload.exam_id == exam_id).delete(synchronize_session=False)
        db.delete(exam)
        db.commit()
        return {
            "ok": True,
            "exam_id": exam_id,
            "exam_name": exam_name,
            "deleted": {
                "subject_score": subject_deleted,
                "total_score": total_deleted,
                "class_average": class_avg_deleted,
                "upload": upload_deleted,
            },
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"删除失败: {e}")
    finally:
        db.close()


@router.get("/exams/{exam_id}")
async def get_exam(exam_id: int, teaching_class_id: Optional[int] = None):
    """获取考试详情（单学科化）。

    学生明细、汇总统计、分布图、排名/百分位展示全部基于当前任教学科的
    SubjectScore；同一学生同一考试的其他学科与 TotalScore 完全隔离，不再出现。
    teaching_class_id 限定为当前教学班成员集合（不传=全部教学班成员并集）。
    学科由后端教师上下文解析。
    """
    from collections import Counter, defaultdict

    from app.db.models import SessionLocal, Exam, SubjectScore
    from app.analysis.exam_context import (
        resolve_exam_context,
        SubjectNotConfiguredError,
        NoTeachingScopeError,
    )
    from app.teaching.subject import SubjectConflictError
    from app.analysis.scope import student_class_map, my_class_labels

    db = SessionLocal()
    try:
        # ── 解析学科 + 成员范围 ──
        try:
            ctx = resolve_exam_context(db, teaching_class_id=teaching_class_id)
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            # 教学班不存在或无成员 → 明确 4xx，不退化为全年级
            if teaching_class_id is not None:
                raise HTTPException(404, str(e))
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            # teaching_class_id 不存在
            raise HTTPException(404, str(e))

        member_ids = ctx.member_ids
        subject = ctx.subject

        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise HTTPException(404, "考试不存在")

        # ── 只取当前任教学科 + 允许成员范围内的 SubjectScore ──
        # 排除 raw_score 与 grade_score 均为空的残留行（只有百分位/全空）。
        subject_rows = (
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

        # ── 单科排名基准：高二/高三选考优先用 grade_score，否则用 raw_score ──
        # 高一 grade_score 为 None，自动回落 raw_score。
        def _rank_value(row):
            return row.grade_score if row.grade_score is not None else row.raw_score

        # 计算每个学生在当前学科范围内的名次（值越大名次越靠前，1=最高）
        rows_with_rank = sorted(
            (r for r in subject_rows if _rank_value(r) is not None),
            key=lambda r: _rank_value(r),
            reverse=True,
        )
        rank_by_student: dict[str, int] = {}
        for idx, r in enumerate(rows_with_rank, 1):
            # 同分同名：与上一名同分则同名次
            if idx > 1 and _rank_value(r) == _rank_value(rows_with_rank[idx - 2]):
                rank_by_student[r.student_id] = rank_by_student[rows_with_rank[idx - 2].student_id]
            else:
                rank_by_student[r.student_id] = idx

        # ── 教学班 label 映射（供学生明细标注 class_label + class_averages 现算）──
        label_map = student_class_map(db, exam.grade)
        mine_labels_map = my_class_labels(db, exam.grade)
        mine_labels = set(mine_labels_map.keys())

        # ── 构造学生明细（单学科，不再携带 total_scores / total_score / grade_rank）──
        class_counter_by_student: dict[str, Counter] = defaultdict(Counter)
        students_by_id: dict[str, dict] = {}
        for row in subject_rows:
            student = students_by_id.setdefault(
                row.student_id,
                {
                    "student_id": row.student_id,
                    "name": row.name or row.student_id,
                    "class_num": row.class_num,
                    "class_label": label_map[row.student_id][0]
                    if row.student_id in label_map
                    else None,
                    "xueji": row.xueji,
                    "raw_score": row.raw_score,
                    "grade_score": row.grade_score,
                    "grade_percentile": row.grade_percentile,
                    "rank": rank_by_student.get(row.student_id),
                },
            )
            if row.name:
                student["name"] = row.name
            if row.class_num is not None:
                class_counter_by_student[row.student_id][row.class_num] += 1
            if row.xueji is not None:
                student["xueji"] = row.xueji
            # raw/grade/percentile 始终用行内值（单科只有一行，直接覆盖即可）
            student["raw_score"] = row.raw_score
            student["grade_score"] = row.grade_score
            student["grade_percentile"] = row.grade_percentile
            student["rank"] = rank_by_student.get(row.student_id)

        for student_id, counter in class_counter_by_student.items():
            if counter:
                students_by_id[student_id]["class_num"] = counter.most_common(1)[0][0]

        all_students = list(students_by_id.values())
        students = sorted(
            all_students,
            key=lambda s: (
                s["rank"] is None,
                s["rank"] if s["rank"] is not None else 10**9,
                s["student_id"],
            ),
        )

        # ── 单科统计（基于 grade_score 优先，否则 raw_score）──
        scored = [s for s in all_students if _rank_value_for_student(s) is not None]
        score_values = [_rank_value_for_student(s) for s in scored]
        rank_values = [s["rank"] for s in scored if s["rank"] is not None]
        avg_score = sum(score_values) / len(score_values) if score_values else None

        stats = {
            "total_students": len(all_students),
            "avg": round(avg_score, 1) if avg_score is not None else None,
            "max": max(score_values) if score_values else None,
            "min": min(score_values) if score_values else None,
            "rank_min": min(rank_values) if rank_values else None,
            "rank_max": max(rank_values) if rank_values else None,
            "score_basis": "grade_score" if any(s.get("grade_score") is not None for s in scored) else "raw_score",
        }

        # ── class_averages：范围隔离的当前学科现算均分 ──
        # 不再依赖官方 ClassAverage 行（它们可能包含其他老师/其他班的均分，
        # 会跨范围泄漏）。直接按本次 subject_rows + 当前 member_ids，对每个
        # 选中教学班的成员集合现算当前学科均分。响应只含 subject_averages
        # 的当前学科键，不含 total_averages 或其他学科。
        # （label_map / mine_labels_map 已在学生明细构造前计算）

        # 成员按教学班 label 分组（teaching_class_id 限定模式只覆盖该班成员）
        members_by_label: dict[str, set[str]] = defaultdict(set)
        for sid in member_ids:
            if sid in label_map:
                members_by_label[label_map[sid][0]].add(sid)

        def _subject_avg_for(candidate_ids):
            vals = [
                _rank_value(r)
                for r in subject_rows
                if r.student_id in candidate_ids and _rank_value(r) is not None
            ]
            return round(sum(vals) / len(vals), 1) if vals else None

        # 只输出在当前 member_ids 范围内、确有当前学科数据的教学班行。
        # 顺序：mine 教学班优先（与 my_class_labels 的 sort_order 一致）。
        class_averages_out = []
        for label in mine_labels_map:  # dict 保序（list_classes 已按 sort_order）
            cand = members_by_label.get(label, set())
            if not cand:
                continue
            subj_avg = _subject_avg_for(cand)
            if subj_avg is None:
                continue
            class_averages_out.append({
                "class_num": None,
                "class_label": label,
                "class_type": "教学",
                "teacher_name": None,
                "subject_averages": {subject: subj_avg},
            })

        # ── rank_bands：单科名次分段（按 class_label 分组，标 mine）──
        from app.analysis.config import get_band_config
        band_cfg = get_band_config(db)
        rank_bands_by_class = defaultdict(lambda: {"high_score": 0, "critical": 0, "weak": 0})
        for s in all_students:
            rank = s["rank"]
            if rank is None:
                continue
            sid = s["student_id"]
            if sid in label_map:
                label = label_map[sid][0]
            elif s.get("class_num") is not None:
                label = str(s["class_num"])
            else:
                continue
            bands = rank_bands_by_class[label]
            if 1 <= rank <= band_cfg["high_score_max"]:
                bands["high_score"] += 1
            if band_cfg["critical_min"] <= rank <= band_cfg["critical_max"]:
                bands["critical"] += 1
            if rank >= band_cfg["weak_min"]:
                bands["weak"] += 1

        rank_bands = [
            {"class_label": label, "mine": label in mine_labels, **bands}
            for label, bands in sorted(rank_bands_by_class.items())
        ]

        # ── rank_distribution：单科名次分布（只有当前学科一列）──
        max_rank = max(rank_values, default=0)
        max_bucket = max(40, ((max_rank + 39) // 40) * 40)
        rank_distribution = [
            {"band": f"{start}-{start + 39}名", subject: 0}
            for start in range(1, max_bucket + 1, 40)
        ]
        distribution_index = {item["band"]: item for item in rank_distribution}
        for s in all_students:
            rank = s["rank"]
            if rank is None or rank < 1:
                continue
            start = ((rank - 1) // 40) * 40 + 1
            band = f"{start}-{start + 39}名"
            if band not in distribution_index:
                distribution_index[band] = {"band": band, subject: 0}
                rank_distribution.append(distribution_index[band])
            distribution_index[band][subject] = distribution_index[band].get(subject, 0) + 1

        return {
            "subject": subject,
            "teaching_class_id": teaching_class_id,
            "exam": {
                "id": exam.id,
                "name": exam.name,
                "grade": exam.grade,
                "semester": exam.semester,
                "exam_date": exam.exam_date,
                "exam_type": exam.exam_type,
            },
            "class_averages": class_averages_out,
            "stats": stats,
            "students": students,
            "rank_bands": rank_bands,
            "band_config": band_cfg,
            "rank_distribution": rank_distribution,
        }
    finally:
        db.close()


def _rank_value_for_student(s: dict):
    """学生明细里的单科排序值：grade_score 优先，否则 raw_score。"""
    return s.get("grade_score") if s.get("grade_score") is not None else s.get("raw_score")

@router.get("/focus-list/{exam_id}")
async def get_focus_list(exam_id: int, teaching_class_id: Optional[int] = None, class_num: Optional[int] = None):
    """获取重点关注名单（单学科化）。

    只查询当前学科；根据 subject_rank + get_band_config 生成「临界段/薄弱段」问题，
    不再做跨学科比较。响应顶层 teaching_subject，每行仅含单科
    成绩、subject_rank、class_label、issues；删除学籍排名和总分字段、其他学科。
    """
    from app.db.models import SessionLocal, Exam
    from app.analysis.config import get_band_config
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
        band_classify,
    )
    from app.teaching.subject import (
        SubjectNotConfiguredError,
        SubjectConflictError,
    )
    from app.analysis.exam_context import NoTeachingScopeError

    if class_num is not None:
        raise HTTPException(400, "请使用 teaching_class_id 参数，不再支持 class_num")

    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise HTTPException(404, "考试不存在")

        try:
            ctx = resolve_single_subject_context(
                db,
                teaching_class_id=teaching_class_id,
                grade=exam.grade,
            )
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))

        subject = ctx.subject

        band_cfg = get_band_config(db)
        rank_map, rows_by_sid = compute_subject_rank_contextual(
            db, ctx, exam_id, exam_grade=exam.grade,
        )

        focus_list = []
        for sid, r in rows_by_sid.items():
            sr = rank_map.get(sid)
            issues = band_classify(sr, band_cfg)
            if not issues:
                continue
            label = label_for_student(ctx, sid)
            focus_list.append({
                "student_id": sid,
                "name": r.name or sid,
                "class_label": label,
                "raw_score": r.raw_score,
                "grade_score": r.grade_score,
                "subject_rank": sr,
                "issues": issues,
            })

        focus_list.sort(key=lambda x: (x["subject_rank"] or 10**9, x["student_id"]))
        return {
            "teaching_subject": subject,
            "focus_list": focus_list[:50],
        }
    finally:
        db.close()

@router.get("/students/{student_id}")
async def get_student(student_id: str, teaching_class_id: Optional[int] = None):
    """获取学生画像（单学科化）。

    学科由后端教师上下文解析（resolve_exam_context），前端不传也不可信。
    请求人/其身份别名必须与合法成员范围有交集，否则 404/403。

    可保留跨学年 identity 合并，但历史只查询当前任教学科 SubjectScore 且
    raw_score 或 grade_score 至少一个非空；考试集合由这些行决定，不依赖 TotalScore。
    返回顶层 teaching_subject 和单一 score_trend；每点至少含 exam_id/name/date/grade、
    raw_score、grade_score、grade_percentile、class_label、教学班内 scope_rank/rank_basis。

    完全删除 main_total_trend、five_trend、plus3_trend、san3_trend、多科 subject_trend、
    class_rank_basis 和全部总分字段。

    scope_rank 只能按对应教学班成员集合和当前学科有效分数计算；无可靠教学班范围时
    为 null，不得回退行政班或全年级。
    """
    from app.db.models import SessionLocal, SubjectScore, Exam
    from app.analysis.exam_context import (
        resolve_exam_context,
        SubjectNotConfiguredError,
        NoTeachingScopeError,
    )
    from app.teaching.subject import SubjectConflictError
    from app.analysis.scope import (
        student_ids_of_person, identity_of, student_class_map, members_of,
    )

    db = SessionLocal()
    try:
        try:
            ctx = resolve_exam_context(db, teaching_class_id=teaching_class_id)
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))

        subject = ctx.subject
        allowed_ids = set(ctx.member_ids)

        # 跨学年 identity 合并
        ids = student_ids_of_person(db, student_id)
        identity_id = identity_of(db, student_id)

        # 范围校验：请求人/其身份别名必须与合法成员范围有交集
        if not (ids & allowed_ids):
            raise HTTPException(404, "该学生不在当前教学范围内")

        # 只查询当前任教学科 SubjectScore 且 raw_score 或 grade_score 至少一个非空
        subject_scores = (
            db.query(SubjectScore)
            .filter(
                SubjectScore.student_id.in_(ids),
                SubjectScore.subject == subject,
                SubjectScore.raw_score.isnot(None)
                | SubjectScore.grade_score.isnot(None),
            )
            .order_by(SubjectScore.exam_id)
            .all()
        )

        # 考试集合由这些行决定（不依赖 TotalScore）
        exam_ids = {s.exam_id for s in subject_scores}
        exams = (
            db.query(Exam)
            .filter(Exam.id.in_(exam_ids))
            .order_by(Exam.grade, Exam.exam_date)
            .all()
        ) if exam_ids else []
        exam_map = {e.id: e for e in exams}

        # grades 来源：有效成绩考试的年级 + 教学班成员元数据年级（补全无成绩成员）
        from app.analysis.scope import student_class_map_multi
        tc_grade_map = student_class_map_multi(db, None)
        member_grades: set[int] = set()
        for sid in ids:
            for info in tc_grade_map.get(sid, []):
                if info["grade"] is not None:
                    member_grades.add(info["grade"])
        exam_grades = set(e.grade for e in exams if e.grade is not None)
        grades = exam_grades | member_grades
        has_cross_year = len(exam_grades) > 1

        name_row = db.query(SubjectScore).filter(
            SubjectScore.student_id.in_(ids), SubjectScore.name.isnot(None)
        ).first()
        name = name_row.name if name_row and name_row.name else student_id

        # 显式 teaching_class_id：当前年级的 label/tc/rank 强制使用该班
        explicit_tc_obj = None
        if teaching_class_id is not None:
            from app.db.models import TeachingClass
            explicit_tc_obj = db.query(TeachingClass).filter(
                TeachingClass.id == teaching_class_id
            ).first()

        # scope_rank：按对应教学班成员集合和当前学科有效分数计算
        label_map_cache: dict[int, dict] = {}
        scope_rank_by_exam: dict[int, int | None] = {}
        rank_basis_by_exam: dict[int, str] = {}

        for s in subject_scores:
            exam = exam_map.get(s.exam_id)
            if not exam:
                continue
            grade = exam.grade
            if grade not in label_map_cache:
                label_map_cache[grade] = student_class_map(db, grade)
            lm = label_map_cache[grade]

            # 显式班级优先：若该考试年级与显式班级年级匹配，强制用该班
            if explicit_tc_obj and explicit_tc_obj.grade == grade:
                peer_ids = members_of(db, explicit_tc_obj.id)
                if not peer_ids:
                    scope_rank_by_exam[s.exam_id] = None
                    rank_basis_by_exam[s.exam_id] = "none"
                    continue
            else:
                tc_info = lm.get(s.student_id)
                if not tc_info:
                    for sid in ids:
                        info = lm.get(sid)
                        if info:
                            tc_info = info
                            break
                if not tc_info:
                    scope_rank_by_exam[s.exam_id] = None
                    rank_basis_by_exam[s.exam_id] = "none"
                    continue
                peer_ids = members_of(db, tc_info[1])
                if not peer_ids:
                    scope_rank_by_exam[s.exam_id] = None
                    rank_basis_by_exam[s.exam_id] = "none"
                    continue

            peer_score_rows = (
                db.query(SubjectScore)
                .filter(
                    SubjectScore.exam_id == s.exam_id,
                    SubjectScore.subject == subject,
                    SubjectScore.student_id.in_(peer_ids),
                    SubjectScore.raw_score.isnot(None)
                    | SubjectScore.grade_score.isnot(None),
                )
                .all()
            )
            extract_value, lower_is_better = _rank_key_for_subject(subject, grade)
            rank_map = _competition_rank(peer_score_rows, extract_value, lower_is_better)
            scope_rank_by_exam[s.exam_id] = rank_map.get(s.student_id)
            rank_basis_by_exam[s.exam_id] = "teaching"

        # 头部展示：当前（最新）年级的教学班标签
        latest_grade = max(exam_grades) if exam_grades else (
            explicit_tc_obj.grade if explicit_tc_obj else (
                max(member_grades) if member_grades else None
            )
        )
        current_label = None
        current_tc_id = None
        if explicit_tc_obj and explicit_tc_obj.grade == latest_grade:
            current_label = explicit_tc_obj.label
            current_tc_id = explicit_tc_obj.id
        elif latest_grade is not None:
            if latest_grade not in label_map_cache:
                label_map_cache[latest_grade] = student_class_map(db, latest_grade)
            sids_latest = {
                s.student_id for s in subject_scores
                if exam_map.get(s.exam_id) and exam_map[s.exam_id].grade == latest_grade
            }
            for sid in sids_latest:
                info = label_map_cache[latest_grade].get(sid)
                if info:
                    current_label, current_tc_id = info
                    break

        class_counter = Counter(s.class_num for s in subject_scores if s.class_num is not None)
        class_num_value = class_counter.most_common(1)[0][0] if class_counter else None
        xueji_counter = Counter(s.xueji for s in subject_scores if s.xueji is not None)
        xueji_code_value = xueji_counter.most_common(1)[0][0] if xueji_counter else None

        def exam_sort_key(exam_id):
            e = exam_map.get(exam_id)
            return (e.grade if e else 0, e.exam_date if e else "")

        subject_scores_sorted = sorted(
            subject_scores, key=lambda s: exam_sort_key(s.exam_id)
        )

        # 每点的 class_label：显式班级年级匹配时优先该班，否则该考试该学号在教学班映射
        def _class_label_for_point(s):
            exam = exam_map.get(s.exam_id)
            if not exam:
                return None
            grade = exam.grade
            if explicit_tc_obj and explicit_tc_obj.grade == grade:
                return explicit_tc_obj.label
            if grade not in label_map_cache:
                label_map_cache[grade] = student_class_map(db, grade)
            lm = label_map_cache[grade]
            info = lm.get(s.student_id)
            if info:
                return info[0]
            for sid in ids:
                info2 = lm.get(sid)
                if info2:
                    return info2[0]
            return None

        return {
            "student_id": student_id,
            "identity_id": identity_id,
            "all_student_ids": sorted(ids),
            "name": name,
            "teaching_subject": subject,
            "has_cross_year": has_cross_year,
            "grades": sorted(list(grades)),
            "class_num": class_num_value,
            "class_label": current_label,
            "teaching_class_id": current_tc_id,
            "xueji_code": xueji_code_value,
            "score_trend": [
                {
                    "exam_id": s.exam_id,
                    "exam_name": exam_map[s.exam_id].name if s.exam_id in exam_map else str(s.exam_id),
                    "exam_date": exam_map[s.exam_id].exam_date if s.exam_id in exam_map else None,
                    "grade": exam_map[s.exam_id].grade if s.exam_id in exam_map else None,
                    "subject": s.subject,
                    "raw_score": s.raw_score,
                    "grade_score": s.grade_score,
                    "grade_percentile": s.grade_percentile,
                    "class_label": _class_label_for_point(s),
                    "scope_rank": scope_rank_by_exam.get(s.exam_id),
                    "rank_basis": rank_basis_by_exam.get(s.exam_id),
                }
                for s in subject_scores_sorted
            ],
        }
    finally:
        db.close()

@router.get("/class/compare")
async def compare_classes(exam_id: Optional[int] = None):
    """班级横向对比（单学科化）：只返回当前任教学科的教学班。

    重定义：不再返回全年级行政班、ClassAverage.total_averages 或其他学科数据。
    删除所有总分字段。每班至少返回 teaching_class_id/class_label/member_count/
    subject_avg/score_basis/source。同分采用 competition ranking（跳号）。

    - 考试集合只含当前学科在合法成员范围内有真实分数的考试。
    - 显式 exam_id 必须落在合法范围内（不扩大范围）。
    - 每场考试按成员去重后的总体均分供前端计算差值。
    - 无成绩班保留 subject_avg=null，不得用其他班官方均分补值。
    """
    from app.db.models import SessionLocal, Exam, TeachingClass
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        _ELECTIVE_SUBJECTS,
        compute_subject_rank_contextual,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import (
        SubjectNotConfiguredError,
        SubjectConflictError,
    )
    from app.analysis.exam_context import NoTeachingScopeError
    from app.analysis.scope import count_members

    db = SessionLocal()
    try:
        try:
            ctx = resolve_single_subject_context(db)
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))

        subject = ctx.subject

        # 合法考试集合：当前学科在合法成员范围内有真实分数的考试
        valid_ids = valid_exam_ids_for_subject(db, subject, ctx.member_ids)

        # 显式 exam_id 必须落在合法范围内
        if exam_id is not None and exam_id not in valid_ids:
            return {"teaching_subject": subject, "exams": []}

        if exam_id is not None:
            selected_ids = [exam_id]
        else:
            exams_q = (
                db.query(Exam)
                .filter(Exam.id.in_(valid_ids))
                .order_by(Exam.exam_date.desc(), Exam.id.desc())
            )
            selected_ids = [e.id for e in exams_q.limit(10).all()]

        exams = (
            db.query(Exam)
            .filter(Exam.id.in_(selected_ids))
            .order_by(Exam.exam_date.desc(), Exam.id.desc())
            .all()
        ) if selected_ids else []

        # 列出当前学科的所有教学班（逐班计算均分/成员）
        tc_rows = (
            db.query(TeachingClass)
            .filter(TeachingClass.subject == subject)
            .order_by(TeachingClass.sort_order, TeachingClass.id)
            .all()
        )

        result = []
        for e in exams:
            score_basis = (
                "grade_score"
                if (e.grade in (2, 3) and subject in _ELECTIVE_SUBJECTS)
                else "raw_score"
            )
            classes = []
            overall_sum = 0.0
            overall_count = 0
            for tc in tc_rows:
                if tc.grade != e.grade:
                    continue
                # 该教学班成员（限当前学科成员范围）
                members = _members_for_class(db, tc.id) & ctx.member_ids
                entry = {
                    "teaching_class_id": tc.id,
                    "class_label": tc.label,
                    "member_count": count_members(db, tc.id),
                    "subject_avg": None,
                    "score_basis": score_basis,
                    "source": "computed",
                }
                if members:
                    # 按班排名（competition ranking），顺便取均分
                    try:
                        sub_ctx = resolve_single_subject_context(
                            db, teaching_class_id=tc.id, grade=e.grade,
                        )
                    except (SubjectNotConfiguredError, NoTeachingScopeError,
                            SubjectConflictError, ValueError):
                        sub_ctx = None
                    if sub_ctx is not None:
                        _rank_map, rows_by_sid = compute_subject_rank_contextual(
                            db, sub_ctx, e.id, exam_grade=e.grade,
                        )
                        vals = []
                        for _sid, r in rows_by_sid.items():
                            v = r.grade_score if score_basis == "grade_score" else r.raw_score
                            if v is not None:
                                vals.append(float(v))
                        if vals:
                            entry["subject_avg"] = round(sum(vals) / len(vals), 1)
                entry["rank"] = None
                classes.append(entry)
                if entry["subject_avg"] is not None:
                    overall_sum += entry["subject_avg"]
                    overall_count += 1

            # competition ranking 按 subject_avg 降序
            scored = [(idx, c["subject_avg"]) for idx, c in enumerate(classes)
                      if c["subject_avg"] is not None]
            scored.sort(key=lambda x: x[1], reverse=True)
            prev_val = None
            prev_rank = 0
            for i, (idx, val) in enumerate(scored, 1):
                if prev_val is not None and val == prev_val:
                    classes[idx]["rank"] = prev_rank
                else:
                    classes[idx]["rank"] = i
                    prev_rank = i
                    prev_val = val

            overall_avg = round(overall_sum / overall_count, 1) if overall_count else None

            classes.sort(key=lambda c: (
                c["rank"] if c["rank"] is not None else 10**9,
                c["class_label"],
            ))
            result.append({
                "exam_id": e.id,
                "exam_name": e.name,
                "grade": e.grade,
                "teaching_subject": subject,
                "score_basis": score_basis,
                "overall_subject_avg": overall_avg,
                "classes": classes,
            })

        return {"teaching_subject": subject, "exams": result}
    finally:
        db.close()

@router.get("/subject-weakness/{exam_id}")
async def subject_weakness(exam_id: int, teaching_class_id: Optional[int] = None, class_num: Optional[int] = None):
    """当前任教学科薄弱名单（单学科化重定义）。

    保留路径兼容，但重定义为「当前任教学科薄弱名单」，复用 focus/band 逻辑中的
    weak 学生。返回 teaching_subject 与 subject_weakness，不含 main percentile diff、
    其他 subject 或总分表。
    """
    from app.db.models import SessionLocal, Exam
    from app.analysis.config import get_band_config
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
    )
    from app.teaching.subject import (
        SubjectNotConfiguredError,
        SubjectConflictError,
    )
    from app.analysis.exam_context import NoTeachingScopeError

    if class_num is not None:
        raise HTTPException(400, "请使用 teaching_class_id 参数，不再支持 class_num")

    db = SessionLocal()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise HTTPException(404, "考试不存在")

        try:
            ctx = resolve_single_subject_context(
                db,
                teaching_class_id=teaching_class_id,
                grade=exam.grade,
            )
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))

        subject = ctx.subject

        band_cfg = get_band_config(db)
        rank_map, rows_by_sid = compute_subject_rank_contextual(
            db, ctx, exam_id, exam_grade=exam.grade,
        )

        weakness_list = []
        for sid, r in rows_by_sid.items():
            sr = rank_map.get(sid)
            if sr is None or sr < band_cfg["weak_min"]:
                continue
            label = label_for_student(ctx, sid)
            weakness_list.append({
                "student_id": sid,
                "name": r.name or sid,
                "class_label": label,
                "raw_score": r.raw_score,
                "grade_score": r.grade_score,
                "grade_percentile": r.grade_percentile,
                "subject_rank": sr,
            })

        weakness_list.sort(key=lambda x: (x["subject_rank"] or 10**9, x["student_id"]))
        return {
            "teaching_subject": subject,
            "subject_weakness": weakness_list[:50],
        }
    finally:
        db.close()


@router.get("/students")
async def list_students(
    teaching_class_id: Optional[int] = None,
    grade: Optional[int] = None,
    q: Optional[str] = None,
):
    """学生检索数据源（单学科化）。

    学科由后端教师上下文解析（resolve_exam_context），前端不传也不可信。
    成绩摘要只用当前任教学科 SubjectScore，不查询 TotalScore。
    teaching_class_id 为空=我教所有班的成员并集。按「人」去重（同一人多学号
    合并一行，取最新年级学号为代表）。

    每行返回 student_id/name/class_label/teaching_class_id/grades，以及当前
    学科摘要：latest_exam、raw_score、grade_score、grade_percentile、scope_rank。
    没有当前学科分数的合法班级成员留在花名册，但成绩字段为 null。

    latest_exam 是当前学科在合法成员范围内有真实分数（raw_score 或 grade_score
    非空）的最新考试；只有百分位或空分残留不能成为最新考试。

    scope_rank 按教学班成员集合和当前学科有效分数计算；无可靠教学班范围时为 null。
    """
    from app.db.models import SessionLocal, Exam, SubjectScore
    from app.analysis.exam_context import (
        resolve_exam_context,
        SubjectNotConfiguredError,
        NoTeachingScopeError,
    )
    from app.teaching.subject import SubjectConflictError
    from app.analysis.scope import (
        student_class_map, student_ids_of_person, identity_of,
    )

    db = SessionLocal()
    try:
        try:
            ctx = resolve_exam_context(db, teaching_class_id=teaching_class_id)
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))

        subject = ctx.subject
        scope_ids = set(ctx.member_ids)
        # 教学班成员映射：student_id → (label, teaching_class_id, grade)
        # 用于 grade 过滤和 per-class 排名
        from app.analysis.scope import student_class_map_multi
        member_class_map = student_class_map_multi(db, grade)
        if grade is not None:
            # 限定年级：只保留该年级教学班的成员（按教学班 grade 元数据，不按是否有成绩）
            scope_ids = {
                sid for sid in scope_ids
                if any(
                    info["grade"] == grade
                    for info in member_class_map.get(sid, [])
                )
            }

        if not scope_ids:
            return {"students": [], "count": 0, "teaching_subject": subject}

        # 姓名过滤
        if q:
            q = q.strip()
            name_rows = (
                db.query(SubjectScore.student_id, SubjectScore.name)
                .filter(SubjectScore.student_id.in_(scope_ids))
                .distinct().all()
            )
            scope_ids = {
                sid for sid, nm in name_rows
                if (nm and q in nm) or q in sid
            }
            if not scope_ids:
                return {"students": [], "count": 0, "teaching_subject": subject}

        # 按身份去重：identity → 学号集合；无 alias 的学号自成一组
        groups: dict = {}
        seen: set[str] = set()
        for sid in scope_ids:
            if sid in seen:
                continue
            iid = identity_of(db, sid)
            if iid is None:
                groups[sid] = {sid}
                seen.add(sid)
            else:
                ids = student_ids_of_person(db, sid) & scope_ids | {sid}
                key = f"p{iid}"
                if key not in groups:
                    groups[key] = set()
                groups[key] |= ids
                seen |= ids

        # 当前学科在合法范围内有真实分数的考试集合（用于 latest_exam）
        valid_exam_ids = set(
            row[0]
            for row in (
                db.query(SubjectScore.exam_id)
                .filter(
                    SubjectScore.subject == subject,
                    SubjectScore.student_id.in_(scope_ids),
                    SubjectScore.raw_score.isnot(None)
                    | SubjectScore.grade_score.isnot(None),
                )
                .distinct().all()
            )
        )
        # 最新考试：按年级/日期/id（只在有真实分数的考试中选）
        latest_exam = None
        if valid_exam_ids:
            latest_exam = (
                db.query(Exam)
                .filter(Exam.id.in_(valid_exam_ids))
                .order_by(Exam.grade.desc(), Exam.exam_date.desc(), Exam.id.desc())
                .first()
            )

        # 每组取最新年级学号作代表。sid_grade 只取当前学科有真实分数（raw 或
        # grade_score 非空）的记录，空分残留不得影响 grades；无成绩成员的 grade
        # 由教学班元数据补全。
        sid_grade: dict[str, int] = {
            row[0]: row[1]
            for row in (
                db.query(SubjectScore.student_id, Exam.grade)
                .join(Exam, Exam.id == SubjectScore.exam_id)
                .filter(
                    SubjectScore.student_id.in_(scope_ids),
                    SubjectScore.subject == subject,
                    SubjectScore.raw_score.isnot(None)
                    | SubjectScore.grade_score.isnot(None),
                )
                .distinct().all()
            )
        }
        # 用教学班成员元数据补全无成绩成员的 grade（保证花名册有 grade 维度）
        for sid in scope_ids:
            if sid not in sid_grade:
                infos = member_class_map.get(sid, [])
                for info in infos:
                    if grade is None or info["grade"] == grade:
                        sid_grade[sid] = info["grade"]
                        break

        # label_map：显式 teaching_class_id 时优先该班，否则取第一个匹配年级的
        label_map = student_class_map(db, grade)
        # 构建显式班级时的 (label, tc_id) 供学生行优先使用
        explicit_tc_info: tuple[str, int] | None = None
        if teaching_class_id is not None:
            from app.db.models import TeachingClass
            tc_obj = db.query(TeachingClass).filter(TeachingClass.id == teaching_class_id).first()
            if tc_obj:
                explicit_tc_info = (tc_obj.label, tc_obj.id)

        # 最新考试当前学科成绩（按代表学号或同组任一学号）
        latest_scores: dict[str, SubjectScore] = {}
        if latest_exam:
            for s in db.query(SubjectScore).filter(
                SubjectScore.exam_id == latest_exam.id,
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(scope_ids),
                SubjectScore.raw_score.isnot(None)
                | SubjectScore.grade_score.isnot(None),
            ).all():
                latest_scores[s.student_id] = s

        # scope_rank：按每个学生所属教学班独立计算（不混排全年级）
        # 显式 teaching_class_id 时，强制所有成员归属该班
        scope_rank_map: dict[str, int] = {}
        if latest_exam:
            exam_grade_val = latest_exam.grade
            sid_to_tc: dict[str, int] = {}
            for sid in scope_ids:
                if teaching_class_id is not None:
                    sid_to_tc[sid] = teaching_class_id
                    continue
                infos = member_class_map.get(sid, [])
                matched = None
                for info in infos:
                    if grade is None or info["grade"] == grade:
                        matched = info["teaching_class_id"]
                        break
                if matched is None and infos:
                    matched = infos[0]["teaching_class_id"]
                if matched is not None:
                    sid_to_tc[sid] = matched

            tc_to_member_ids: dict[int, set[str]] = {}
            for sid, tc_id in sid_to_tc.items():
                tc_to_member_ids.setdefault(tc_id, set()).add(sid)

            extract_value, lower_is_better = _rank_key_for_subject(subject, exam_grade_val)
            for tc_id, member_ids in tc_to_member_ids.items():
                tc_scores = [
                    latest_scores[sid] for sid in member_ids
                    if sid in latest_scores
                ]
                rank_map = _competition_rank(tc_scores, extract_value, lower_is_better)
                scope_rank_map.update(rank_map)

        students = []
        for ids in groups.values():
            rep = max(ids, key=lambda s: (sid_grade.get(s, 0), s))
            name_row = db.query(SubjectScore.name).filter(
                SubjectScore.student_id.in_(ids), SubjectScore.name.isnot(None)
            ).first()
            name = name_row[0] if name_row and name_row[0] else rep
            # 显式班级优先；否则用 label_map（按 sort_order 取第一个）
            if explicit_tc_info:
                label, tc_id = explicit_tc_info
            else:
                label, tc_id = label_map.get(rep, (None, None))
            s = latest_scores.get(rep) or next(
                (latest_scores.get(sid) for sid in ids if latest_scores.get(sid)), None
            )
            students.append({
                "student_id": rep,
                "name": name,
                "class_label": label,
                "teaching_class_id": tc_id,
                "grades": sorted({sid_grade.get(s) for s in ids if sid_grade.get(s)}),
                "latest_exam_id": latest_exam.id if latest_exam else None,
                "latest_exam": (
                    {"id": latest_exam.id, "name": latest_exam.name}
                    if latest_exam else None
                ),
                "raw_score": s.raw_score if s else None,
                "grade_score": s.grade_score if s else None,
                "grade_percentile": s.grade_percentile if s else None,
                "scope_rank": scope_rank_map.get(s.student_id) if s else None,
            })
        # 排序：有 scope_rank 的优先（越小越好），无成绩的排末尾
        students.sort(
            key=lambda st: (
                st["scope_rank"] if st["scope_rank"] is not None else 10 ** 9,
                st["student_id"],
            )
        )
        return {
            "students": students,
            "count": len(students),
            "teaching_subject": subject,
            "latest_exam": (
                {"id": latest_exam.id, "name": latest_exam.name}
                if latest_exam else None
            ),
        }
    finally:
        db.close()


@router.get("/dashboard/overview")
async def dashboard_overview(grade: Optional[int] = None):
    """总览仪表盘聚合（单学科化）：只列当前任教学科的教学班，每班一行。

    每班最近考试必须是：该班成员在当前学科至少有一条 raw_score/grade_score 有值
    的最近考试（不得使用全局最近考试）。均分：高二/高三选考用 grade_score，其他
    用 raw_score，不混合量纲。focus_count 使用阶段4按班 subject rank +
    get_band_config，不年级混排。

    删除 main_total_avg；返回 teaching_subject、subject_avg、score_basis、focus_count。
    overall 学生数为当前学科教学班成员去重并集（不含遗留他科班）。
    """
    from app.db.models import SessionLocal, Exam
    from app.analysis.config import get_band_config
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        _ELECTIVE_SUBJECTS,
        band_classify,
        compute_subject_rank_contextual,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import (
        SubjectNotConfiguredError,
        SubjectConflictError,
    )
    from app.analysis.exam_context import NoTeachingScopeError

    db = SessionLocal()
    try:
        try:
            ctx_all = resolve_single_subject_context(db, grade=grade)
        except SubjectNotConfiguredError as e:
            raise HTTPException(409, str(e))
        except NoTeachingScopeError as e:
            raise HTTPException(409, str(e))
        except SubjectConflictError as e:
            raise HTTPException(409, str(e))

        subject = ctx_all.subject
        cfg = get_band_config(db)
        # score_basis 按每个班级的实际 grade 决定（避免年级混判）。

        from app.db.models import TeachingClass
        # 重新列出当前学科的教学班（resolve_single_subject_context 已限定成员范围，
        # 这里按同样的 subject/grade 列出班级用于逐班展示）。
        tc_q = db.query(TeachingClass).filter(TeachingClass.subject == subject)
        if grade is not None:
            tc_q = tc_q.filter(TeachingClass.grade == grade)
        classes = tc_q.order_by(TeachingClass.sort_order, TeachingClass.id).all()

        from app.analysis.scope import count_members
        rows = []
        union_ids: set[str] = set(ctx_all.member_ids)
        for tc in classes:
            # 逐班解析成员：必须是该教学班实际成员且属于当前学科成员范围
            members = _members_for_class(db, tc.id) & ctx_all.member_ids
            if not members:
                members = _members_for_class(db, tc.id)
            # 该班的 score_basis：高二/三选考用 grade_score，否则 raw_score
            score_basis = (
                "grade_score"
                if (tc.grade in (2, 3) and subject in _ELECTIVE_SUBJECTS)
                else "raw_score"
            )
            # 该班在当前学科有真实分数的最近考试
            valid_ids = valid_exam_ids_for_subject(db, subject, members, grade=tc.grade)
            latest_ex = None
            if valid_ids:
                latest_ex = (
                    db.query(Exam)
                    .filter(Exam.id.in_(valid_ids), Exam.grade == tc.grade)
                    .order_by(Exam.exam_date.desc(), Exam.id.desc())
                    .first()
                )
            entry = {
                "id": tc.id,
                "grade": tc.grade,
                "label": tc.label,
                "teaching_class_id": tc.id,
                "subject": tc.subject,
                "kind": tc.kind,
                "member_count": count_members(db, tc.id),
                "latest_exam": (
                    {"id": latest_ex.id, "name": latest_ex.name, "exam_date": latest_ex.exam_date}
                    if latest_ex else None
                ),
                "subject_avg": None,
                "score_basis": score_basis,
                "focus_count": 0,
            }
            if latest_ex and members:
                # 按班 subject rank + band config 计算 focus_count（阶段4口径）
                try:
                    sub_ctx = resolve_single_subject_context(
                        db, teaching_class_id=tc.id, grade=tc.grade,
                    )
                except (SubjectNotConfiguredError, NoTeachingScopeError, SubjectConflictError, ValueError):
                    sub_ctx = None
                rank_map, rows_by_sid = (None, None)
                if sub_ctx is not None:
                    rank_map, rows_by_sid = compute_subject_rank_contextual(
                        db, sub_ctx, latest_ex.id, exam_grade=latest_ex.grade,
                    )
                # 均分：按 score_basis 选列
                if rows_by_sid:
                    vals = []
                    for _sid, r in rows_by_sid.items():
                        v = r.grade_score if score_basis == "grade_score" else r.raw_score
                        if v is not None:
                            vals.append(float(v))
                    if vals:
                        entry["subject_avg"] = round(sum(vals) / len(vals), 1)
                    # focus_count
                    if rank_map:
                        for _sid, sr in rank_map.items():
                            issues = band_classify(sr, cfg)
                            if issues:
                                entry["focus_count"] += 1
            rows.append(entry)

        rows.sort(key=lambda r: (r["grade"], r["label"]))
        return {
            "grade": grade,
            "teaching_subject": subject,
            "classes": rows,
            "overall": {
                "class_count": len(classes),
                "total_students": len(union_ids),
            },
        }
    finally:
        db.close()


def _members_for_class(db, teaching_class_id: int) -> set[str]:
    """某教学班的成员学号集合（复用 scope.members_of，避免循环导入问题）。"""
    from app.analysis.scope import members_of
    return members_of(db, teaching_class_id)
