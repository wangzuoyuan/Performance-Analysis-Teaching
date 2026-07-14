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


@router.get("/rank-metrics")
async def get_rank_metrics(grade: int, mode: str = "frequency"):
    """返回指定年级在排名区间筛选/排名频次统计中可选的指标。"""
    from app.analysis.rank_metrics import rank_metric_options

    if mode not in {"range", "frequency"}:
        raise HTTPException(400, "mode 只能是 range 或 frequency")
    return {"grade": grade, "mode": mode, "metrics": rank_metric_options(grade, mode)}


@router.get("/rank-range")
async def get_rank_range(
    exam_id: int,
    metric: str,
    rank_min: int = 1,
    rank_max: int = 100,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
):
    """按单次考试、指标和年级排名区间筛选学生。"""
    from app.analysis.rank_metrics import rank_range_filter

    try:
        return rank_range_filter(
            exam_id=exam_id,
            metric=metric,
            rank_min=rank_min,
            rank_max=rank_max,
            teaching_class_id=teaching_class_id,
            class_num=class_num,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/rank-frequency")
async def get_rank_frequency(
    grade: int,
    metric: str,
    exam_ids: Optional[str] = None,
    teaching_class_id: Optional[int] = None,
    class_num: Optional[int] = None,
    recent_count: int = 5,
):
    """按多场考试统计学生落入各排名/百分位/等级分区间的频次。"""
    from app.analysis.rank_metrics import rank_frequency_stats

    try:
        return rank_frequency_stats(
            grade=grade,
            metric=metric,
            exam_ids=exam_ids,
            teaching_class_id=teaching_class_id,
            class_num=class_num,
            recent_count=recent_count,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


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
    """某年级历次考试的三段（高分/临界/薄弱）人数趋势。
    teaching_class_id 为空时统计全年级；按当前 band_config 分段，改阈值后趋势同步变化。"""
    from app.db.models import SessionLocal, Exam, TotalScore
    from app.analysis.config import get_band_config
    from app.analysis.scope import resolve_scope_compat, list_classes

    db = SessionLocal()
    try:
        cfg = get_band_config(db)
        exams = (
            db.query(Exam)
            .filter(Exam.grade == grade)
            .order_by(Exam.grade, Exam.exam_date, Exam.id)
            .all()
        )

        series = []
        for exam in exams:
            allowed = resolve_scope_compat(
                db, teaching_class_id=teaching_class_id, class_num=class_num, exam_id=exam.id, grade=grade
            )
            totals = (
                db.query(TotalScore)
                .filter(TotalScore.exam_id == exam.id, TotalScore.total_type == "主三门")
                .all()
            )
            high = crit = weak = 0
            for t in totals:
                if allowed is not None and t.student_id not in allowed:
                    continue
                rank = t.xueji_rank or t.grade_rank
                if rank is None:
                    continue
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

        # available_classes：我的教学班（该年级）+ 全年级选项
        my_classes = [
            {"label": tc.label, "teaching_class_id": tc.id, "mine": True, "kind": tc.kind}
            for tc in list_classes(db, grade)
        ]
        return {
            "series": series,
            "band_config": cfg,
            "grade": grade,
            "teaching_class_id": teaching_class_id,
            "class_num": class_num,
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
    """获取重点关注名单。teaching_class_id 限定教学班成员集合，空=全年级。
    每项附带 class_label（学生所属教学班标签）。"""
    from app.db.models import SessionLocal, Exam, TotalScore, SubjectScore
    from app.analysis.config import SUBJECT_WEAKNESS_PCT_DIFF, get_band_config
    from app.analysis.scope import resolve_scope_compat, student_class_map

    db = SessionLocal()
    band_cfg = get_band_config(db)
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    grade = exam.grade if exam else None
    allowed = resolve_scope_compat(
        db, teaching_class_id=teaching_class_id, class_num=class_num, exam_id=exam_id, grade=grade
    )
    label_map = student_class_map(db, grade) if grade is not None else {}

    query = db.query(TotalScore).filter(
        TotalScore.exam_id == exam_id,
        TotalScore.total_type == "主三门"
    )
    if allowed is not None:
        query = query.filter(TotalScore.student_id.in_(allowed))

    all_totals = query.all()
    focus_list = []

    for t in all_totals:
        student_id = t.student_id
        rank = t.xueji_rank or t.grade_rank or 9999

        subject_scores = db.query(SubjectScore).filter(
            SubjectScore.exam_id == exam_id,
            SubjectScore.student_id == student_id
        ).all()

        name = student_id
        class_num_value = None
        for s in subject_scores:
            if s.name:
                name = s.name
            if class_num_value is None and s.class_num is not None:
                class_num_value = s.class_num
            if name != student_id and class_num_value is not None:
                break

        issues = []
        if band_cfg["critical_min"] <= rank <= band_cfg["critical_max"]:
            issues.append("临界段")
        if rank >= band_cfg["weak_min"]:
            issues.append("薄弱段")
        if t.grade_percentile is not None:
            main_pct = t.grade_percentile
            for ss in subject_scores:
                if ss.grade_percentile is not None:
                    diff = ss.grade_percentile - main_pct
                    if diff >= SUBJECT_WEAKNESS_PCT_DIFF:
                        issues.append(f"严重偏科({ss.subject})")

        if issues:
            label, _tc_id = label_map.get(student_id, (None, None))
            focus_list.append({
                "student_id": student_id,
                "name": name,
                "class_num": class_num_value,
                "class_label": label,
                "xueji_rank": rank,
                "total_score": t.total_score,
                "issues": issues,
            })

    focus_list.sort(key=lambda x: x["xueji_rank"])
    db.close()
    return {"focus_list": focus_list[:50]}

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

        if not subject_scores:
            raise HTTPException(404, "该学生无当前学科成绩记录")

        # 考试集合由这些行决定（不依赖 TotalScore）
        exam_ids = {s.exam_id for s in subject_scores}
        exams = (
            db.query(Exam)
            .filter(Exam.id.in_(exam_ids))
            .order_by(Exam.grade, Exam.exam_date)
            .all()
        )
        exam_map = {e.id: e for e in exams}

        grades = set(e.grade for e in exams)
        has_cross_year = len(grades) > 1

        name_row = db.query(SubjectScore).filter(
            SubjectScore.student_id.in_(ids), SubjectScore.name.isnot(None)
        ).first()
        name = name_row.name if name_row and name_row.name else student_id

        # scope_rank：按对应教学班成员集合和当前学科有效分数计算
        # 确定该学生每场考试对应的教学班成员集合（按年级）
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

            # 该考试该学生使用的学号 → 教学班
            tc_info = lm.get(s.student_id)
            if not tc_info:
                # 该学号未在教学班成员中，尝试同组其他学号
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

            # 当前学科该考试 peer_ids 中的有效分数（raw_score 非空）
            peer_scores = {
                row[0]: row[1]
                for row in (
                    db.query(SubjectScore.student_id, SubjectScore.raw_score)
                    .filter(
                        SubjectScore.exam_id == s.exam_id,
                        SubjectScore.subject == subject,
                        SubjectScore.student_id.in_(peer_ids),
                        SubjectScore.raw_score.isnot(None),
                    )
                    .all()
                )
            }
            my_score = s.raw_score
            if my_score is None or s.student_id not in peer_scores:
                scope_rank_by_exam[s.exam_id] = None
                rank_basis_by_exam[s.exam_id] = "teaching"
                continue
            # 排名：比我高的 + 1
            scope_rank_by_exam[s.exam_id] = (
                sum(1 for v in peer_scores.values() if v > my_score) + 1
            )
            rank_basis_by_exam[s.exam_id] = "teaching"

        # 头部展示：当前（最新）年级的教学班标签
        latest_grade = max(grades) if grades else None
        current_label = None
        current_tc_id = None
        if latest_grade is not None:
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

        # 每点的 class_label：该考试该学号在教学班映射中的 label
        def _class_label_for_point(s):
            exam = exam_map.get(s.exam_id)
            if not exam:
                return None
            grade = exam.grade
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
    """班级对比（D2：全年级所有班，高亮我的教学班）。
    - 按 class_label 组织横轴（空则 str(class_num)）；mine=我的教学班集合。
    - 官方 ClassAverage 优先（source=class_average）；我的教学班若无官方行，用成员
      总分现算（source=computed）。
    - dimension：高一=行政班；高二/三 数据含 class_label 或已配教学班=教学班，否则行政班。"""
    from collections import defaultdict
    from app.db.models import SessionLocal, Exam, ClassAverage, TotalScore
    from app.analysis.scope import my_class_labels, members_of

    db = SessionLocal()

    def _avg_over(members, exam_id):
        rows = (
            db.query(TotalScore.total_type, TotalScore.total_score)
            .filter(
                TotalScore.exam_id == exam_id,
                TotalScore.student_id.in_(members),
                TotalScore.total_type.in_(["主三门", "五门", "九门", "+3", "3+3"]),
                TotalScore.total_score.isnot(None),
            )
            .all()
        )
        sums = defaultdict(list)
        for tt, sc in rows:
            sums[tt].append(sc)

        def avg(tt):
            v = sums.get(tt)
            return round(sum(v) / len(v), 1) if v else None

        return {
            "main_total_avg": avg("主三门"),
            "five_total_avg": avg("五门"),
            "nine_total_avg": avg("九门"),
            "plus3_avg": avg("+3"),
            "total_avg": avg("3+3"),
        }

    exams_query = db.query(Exam).order_by(Exam.exam_date.desc())
    if exam_id:
        exams_query = exams_query.filter(Exam.id == exam_id)
    exams = exams_query.limit(10).all()

    result = []
    for e in exams:
        my_labels = my_class_labels(db, e.grade)
        mine_set = set(my_labels.keys())
        avgs = db.query(ClassAverage).filter(ClassAverage.exam_id == e.id).all()
        by_label: dict[str, dict] = {}

        for a in avgs:
            label = a.class_label or (str(a.class_num) if a.class_num is not None else None)
            if label is None:
                continue
            ta = a.total_averages or {}
            by_label[label] = {
                "class_label": label,
                "class_num": a.class_num,
                "class_type": a.class_type,
                "teacher_name": a.teacher_name,
                "main_total_avg": ta.get("主三门"),
                "five_total_avg": ta.get("五门") or ta.get("五门总分"),
                "nine_total_avg": ta.get("九门") or ta.get("九门总分"),
                "plus3_avg": ta.get("+3"),
                "total_avg": ta.get("3+3总分") or ta.get("3+3"),
                "mine": label in mine_set,
                "source": "class_average",
            }

        # 我的教学班若无官方均分，用成员现算补一根柱
        for label, tc_id in my_labels.items():
            if label in by_label:
                continue
            members = members_of(db, tc_id)
            if not members:
                continue
            entry = {"class_label": label, "class_num": None, "class_type": None,
                     "teacher_name": None, "mine": True, "source": "computed"}
            entry.update(_avg_over(members, e.id))
            by_label[label] = entry

        has_label_data = any(a.class_label for a in avgs) or bool(my_labels)
        dimension = "行政班" if e.grade == 1 else ("教学班" if has_label_data else "行政班")

        classes = sorted(
            by_label.values(),
            key=lambda c: (
                not c["mine"],
                c["main_total_avg"] is None,
                -(c["main_total_avg"] or 0),
                c["class_label"],
            ),
        )
        result.append({
            "exam_id": e.id,
            "exam_name": e.name,
            "grade": e.grade,
            "dimension": dimension,
            "mine_labels": sorted(mine_set),
            "classes": classes,
        })

    db.close()
    return {"exams": result}

@router.get("/subject-weakness/{exam_id}")
async def subject_weakness(exam_id: int, teaching_class_id: Optional[int] = None, class_num: Optional[int] = None):
    """单科薄弱名单。teaching_class_id 限定教学班成员集合，空=全年级。"""
    from app.db.models import SessionLocal, SubjectScore, TotalScore
    from app.analysis.config import SUBJECT_WEAKNESS_PCT_DIFF
    from app.analysis.scope import resolve_scope_compat

    db = SessionLocal()

    main_totals = db.query(TotalScore).filter(
        TotalScore.exam_id == exam_id,
        TotalScore.total_type == "主三门"
    ).all()
    main_pct_map = {t.student_id: t.grade_percentile for t in main_totals if t.grade_percentile is not None}

    allowed = resolve_scope_compat(
        db, teaching_class_id=teaching_class_id, class_num=class_num, exam_id=exam_id
    )
    query = db.query(SubjectScore).filter(SubjectScore.exam_id == exam_id)
    if allowed is not None:
        query = query.filter(SubjectScore.student_id.in_(allowed))
    all_subjects = query.all()

    student_subjects = {}
    for s in all_subjects:
        student_subjects.setdefault(s.student_id, []).append(s)

    weakness_list = []
    for student_id, subjects in student_subjects.items():
        main_pct = main_pct_map.get(student_id)
        if main_pct is None:
            continue
        for s in subjects:
            if s.grade_percentile is not None:
                diff = s.grade_percentile - main_pct
                if diff >= SUBJECT_WEAKNESS_PCT_DIFF:
                    name = student_id
                    for sub in subjects:
                        if sub.name:
                            name = sub.name
                            break
                    weakness_list.append({
                        "student_id": student_id,
                        "name": name,
                        "subject": s.subject,
                        "raw_score": s.raw_score,
                        "grade_percentile": s.grade_percentile,
                        "diff": round(diff, 3),
                    })

    weakness_list.sort(key=lambda x: x["grade_percentile"])
    db.close()
    return {"subject_weakness": weakness_list[:50]}


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
        if grade is not None:
            # 限定年级：只保留该年级教学班的成员
            scope_ids = {
                sid for sid in scope_ids
                if _student_has_grade(db, sid, grade, subject)
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

        # 每组取最新年级学号作代表
        sid_grade = {
            row[0]: row[1]
            for row in (
                db.query(SubjectScore.student_id, Exam.grade)
                .join(Exam, Exam.id == SubjectScore.exam_id)
                .filter(SubjectScore.student_id.in_(scope_ids))
                .distinct().all()
            )
        }
        label_map = student_class_map(db, grade)

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

        # scope_rank 基数：当前教学班范围内、最新考试当前学科有效分数
        scope_rank_map: dict[str, int] = {}
        if latest_exam:
            scores_for_rank = [
                s for s in latest_scores.values()
                if s.student_id in scope_ids
            ]
            # 用 raw_score 排名（单科趋势的基准之一）
            valid = [s for s in scores_for_rank if s.raw_score is not None]
            valid.sort(key=lambda s: s.raw_score, reverse=True)
            for rank, s in enumerate(valid, 1):
                scope_rank_map[s.student_id] = rank

        students = []
        for ids in groups.values():
            rep = max(ids, key=lambda s: (sid_grade.get(s, 0), s))
            name_row = db.query(SubjectScore.name).filter(
                SubjectScore.student_id.in_(ids), SubjectScore.name.isnot(None)
            ).first()
            name = name_row[0] if name_row and name_row[0] else rep
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
                "scope_rank": scope_rank_map.get(rep) if s else None,
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


def _student_has_grade(db, student_id: str, grade: int, subject: str) -> bool:
    """该学号在指定年级是否有过当前学科成绩记录。"""
    from app.db.models import Exam, SubjectScore

    return bool(
        db.query(SubjectScore.id)
        .join(Exam, Exam.id == SubjectScore.exam_id)
        .filter(
            SubjectScore.student_id == student_id,
            SubjectScore.subject == subject,
            Exam.grade == grade,
        )
        .first()
    )


@router.get("/dashboard/overview")
async def dashboard_overview(grade: Optional[int] = None):
    """总览仪表盘聚合：我教的所有班（可限年级）。每个教学班一行（人数、最近考试
    主三门班均、关注数）；并附跨班并集的总体统计。避免前端 N 次 fetch。"""
    from collections import defaultdict
    from app.db.models import SessionLocal, Exam, TotalScore
    from app.analysis.config import get_band_config
    from app.analysis.scope import list_classes, members_of, count_members

    db = SessionLocal()
    try:
        cfg = get_band_config(db)
        classes = list_classes(db, grade)
        # 最新考试（按年级分别取）
        latest_by_grade: dict[int, Exam] = {}
        for g in {c.grade for c in classes}:
            ex = (
                db.query(Exam).filter(Exam.grade == g)
                .order_by(Exam.exam_date.desc(), Exam.id.desc()).first()
            )
            if ex:
                latest_by_grade[g] = ex

        rows = []
        union_ids: set[str] = set()
        for tc in classes:
            members = members_of(db, tc.id)
            union_ids |= members
            ex = latest_by_grade.get(tc.grade)
            entry = {
                "id": tc.id, "grade": tc.grade, "label": tc.label,
                "subject": tc.subject, "kind": tc.kind, "member_count": count_members(db, tc.id),
                "latest_exam": {"id": ex.id, "name": ex.name, "exam_date": ex.exam_date} if ex else None,
                "main_total_avg": None, "focus_count": 0,
            }
            if ex and members:
                totals = (
                    db.query(TotalScore).filter(
                        TotalScore.exam_id == ex.id, TotalScore.total_type == "主三门",
                        TotalScore.student_id.in_(members),
                    ).all()
                )
                scores = [t.total_score for t in totals if t.total_score is not None]
                if scores:
                    entry["main_total_avg"] = round(sum(scores) / len(scores), 1)
                focus = 0
                for t in totals:
                    rank = t.xueji_rank or t.grade_rank
                    if rank is None:
                        continue
                    if cfg["critical_min"] <= rank <= cfg["critical_max"] or rank >= cfg["weak_min"]:
                        focus += 1
                entry["focus_count"] = focus
            rows.append(entry)

        rows.sort(key=lambda r: (r["grade"], r["label"]))
        return {
            "grade": grade,
            "classes": rows,
            "overall": {
                "class_count": len(classes),
                "total_students": len(union_ids),
            },
        }
    finally:
        db.close()
