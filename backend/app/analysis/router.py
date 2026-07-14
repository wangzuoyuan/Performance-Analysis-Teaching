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

        # 找出在允许成员范围内、当前任教学科确有成绩的考试 id
        valid_exam_ids = set(
            row[0]
            for row in (
                db.query(SubjectScore.exam_id)
                .filter(
                    SubjectScore.subject == ctx.subject,
                    SubjectScore.student_id.in_(ctx.member_ids),
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

    from app.db.models import SessionLocal, Exam, ClassAverage, SubjectScore
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
        subject_rows = (
            db.query(SubjectScore)
            .filter(
                SubjectScore.exam_id == exam_id,
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(member_ids),
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

        # ── class_averages：只返回当前任教学科，不泄漏其他学科与 total_averages ──
        # 优先用官方 ClassAverage 行的 subject_averages[subject]；官方无则现算。
        label_map = student_class_map(db, exam.grade)
        mine_labels = set(my_class_labels(db, exam.grade).keys())
        official_avgs = db.query(ClassAverage).filter(ClassAverage.exam_id == exam_id).all()
        # 成员按 label 分组（用教学班 label，无则按行政班号）
        members_by_label: dict[str, set[str]] = defaultdict(set)
        for sid in member_ids:
            if sid in label_map:
                members_by_label[label_map[sid][0]].add(sid)
        # 也收集每个学生的行政班号，用于官方行匹配
        admin_class_by_student = {s["student_id"]: s.get("class_num") for s in all_students}

        def _subject_avg_for(label_or_num, candidate_ids):
            vals = [
                _rank_value(r)
                for r in subject_rows
                if r.student_id in candidate_ids and _rank_value(r) is not None
            ]
            return round(sum(vals) / len(vals), 1) if vals else None

        class_averages_out = []
        seen_labels = set()
        for ca in official_avgs:
            label = ca.class_label or (str(ca.class_num) if ca.class_num is not None else None)
            if not label:
                continue
            sa = ca.subject_averages or {}
            subj_avg = sa.get(subject)
            # 若官方行无当前学科均分，尝试现算该 label 成员
            if subj_avg is None:
                cand = members_by_label.get(label, set())
                if not cand and ca.class_num is not None:
                    cand = {sid for sid, cn in admin_class_by_student.items() if cn == ca.class_num}
                subj_avg = _subject_avg_for(label, cand) if cand else None
            if subj_avg is None:
                continue  # 该班无当前学科数据，不展示
            class_averages_out.append({
                "class_num": ca.class_num,
                "class_label": label,
                "class_type": ca.class_type,
                "teacher_name": ca.teacher_name,
                "subject_averages": {subject: subj_avg},
                # 单学科化：不再返回 total_averages
            })
            seen_labels.add(label)

        # 我的教学班若官方无行，用成员现算补一行
        for label, tc_id in my_class_labels(db, exam.grade).items():
            if label in seen_labels:
                continue
            cand = members_by_label.get(label, set())
            if not cand:
                continue
            subj_avg = _subject_avg_for(label, cand)
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
async def get_student(student_id: str):
    """获取学生画像（跨学年）。学号会随分班变化，用身份层 student_ids_of_person
    把同一人的全部学号并起来查，使跨学年趋势/档案接续。班级排名按教学班成员集合
    （无配置时回退行政班）。"""
    from app.db.models import SessionLocal, TotalScore, SubjectScore, Exam
    from app.analysis.scope import (
        student_ids_of_person, identity_of, student_class_map, members_of,
    )

    db = SessionLocal()
    ids = student_ids_of_person(db, student_id)
    identity_id = identity_of(db, student_id)

    # 该人所有考试（跨学号并集）
    exams = db.query(Exam).join(TotalScore, Exam.id == TotalScore.exam_id).filter(
        TotalScore.student_id.in_(ids)
    ).order_by(Exam.grade, Exam.exam_date).all()

    if not exams:
        db.close()
        raise HTTPException(404, "该学生无成绩记录")

    grades = set(e.grade for e in exams)
    has_cross_year = len(grades) > 1

    main_totals = db.query(TotalScore).filter(
        TotalScore.student_id.in_(ids), TotalScore.total_type == "主三门"
    ).order_by(TotalScore.exam_id).all()
    five_totals = db.query(TotalScore).filter(
        TotalScore.student_id.in_(ids), TotalScore.total_type == "五门"
    ).order_by(TotalScore.exam_id).all()
    plus3_totals = db.query(TotalScore).filter(
        TotalScore.student_id.in_(ids), TotalScore.total_type == "+3"
    ).order_by(TotalScore.exam_id).all()
    san3_totals = db.query(TotalScore).filter(
        TotalScore.student_id.in_(ids), TotalScore.total_type == "3+3"
    ).order_by(TotalScore.exam_id).all()
    subject_scores = db.query(SubjectScore).filter(
        SubjectScore.student_id.in_(ids)
    ).order_by(SubjectScore.exam_id).all()

    name_row = db.query(SubjectScore).filter(
        SubjectScore.student_id.in_(ids), SubjectScore.name.isnot(None)
    ).first()
    name = name_row.name if name_row and name_row.name else student_id

    exam_map = {e.id: e for e in exams}

    # 班级排名：优先教学班成员集合，无则回退行政班号
    label_map_cache: dict[int, dict] = {}
    student_class_by_exam: dict[int, int] = {}
    for s in subject_scores:
        if s.class_num is not None and s.exam_id not in student_class_by_exam:
            student_class_by_exam[s.exam_id] = s.class_num

    class_rank_by_exam: dict[int, int | None] = {}
    class_rank_basis: dict[int, str] = {}  # 'teaching' | 'admin'
    for t in main_totals:
        if t.total_score is None:
            class_rank_by_exam[t.exam_id] = None
            continue
        exam = exam_map.get(t.exam_id)
        grade = exam.grade if exam else None
        peer_ids: list[str] = []
        basis = "admin"
        # 优先：该学号在该年级的教学班成员
        if grade is not None:
            if grade not in label_map_cache:
                label_map_cache[grade] = student_class_map(db, grade)
            lm = label_map_cache[grade]
            tc_info = lm.get(t.student_id)
            if tc_info:
                peer_ids = sorted(members_of(db, tc_info[1]))
                basis = "teaching"
        # 回退：行政班号
        if not peer_ids:
            cls = student_class_by_exam.get(t.exam_id)
            if cls is None:
                class_rank_by_exam[t.exam_id] = None
                continue
            peer_ids = [
                row[0]
                for row in db.query(SubjectScore.student_id)
                .filter(SubjectScore.exam_id == t.exam_id, SubjectScore.class_num == cls)
                .distinct().all()
            ]
        if not peer_ids:
            class_rank_by_exam[t.exam_id] = None
            continue
        peer_scores = [
            row[0]
            for row in db.query(TotalScore.total_score)
            .filter(
                TotalScore.exam_id == t.exam_id,
                TotalScore.total_type == "主三门",
                TotalScore.student_id.in_(peer_ids),
                TotalScore.total_score.isnot(None),
            ).all()
        ]
        class_rank_by_exam[t.exam_id] = sum(1 for s in peer_scores if s > t.total_score) + 1
        class_rank_basis[t.exam_id] = basis

    # 头部展示：当前（最新）年级的教学班标签
    latest_grade = max(grades) if grades else None
    current_label = None
    current_tc_id = None
    if latest_grade is not None:
        if latest_grade not in label_map_cache:
            label_map_cache[latest_grade] = student_class_map(db, latest_grade)
        # 该人在最新年级出现的任一学号
        sids_latest = {s.student_id for s in subject_scores if exam_map.get(s.exam_id) and exam_map[s.exam_id].grade == latest_grade}
        for sid in sids_latest:
            info = label_map_cache[latest_grade].get(sid)
            if info:
                current_label, current_tc_id = info
                break

    class_counter = Counter(s.class_num for s in subject_scores if s.class_num is not None)
    class_num_value = class_counter.most_common(1)[0][0] if class_counter else None
    xueji_counter = Counter(s.xueji for s in subject_scores if s.xueji is not None)
    xueji_code_value = xueji_counter.most_common(1)[0][0] if xueji_counter else None

    db.close()

    def exam_sort_key(exam_id):
        e = exam_map.get(exam_id)
        return (e.grade if e else 0, e.exam_date if e else "")

    main_totals_sorted = sorted(main_totals, key=lambda t: exam_sort_key(t.exam_id))
    five_totals_sorted = sorted(five_totals, key=lambda t: exam_sort_key(t.exam_id))
    plus3_totals_sorted = sorted(plus3_totals, key=lambda t: exam_sort_key(t.exam_id))
    san3_totals_sorted = sorted(san3_totals, key=lambda t: exam_sort_key(t.exam_id))
    subject_scores_sorted = sorted(subject_scores, key=lambda s: exam_sort_key(s.exam_id))
    subject_scores_with_score = [
        s for s in subject_scores_sorted if s.raw_score is not None or s.grade_score is not None
    ]

    return {
        "student_id": student_id,
        "identity_id": identity_id,
        "all_student_ids": sorted(ids),  # 学段履历
        "name": name,
        "has_cross_year": has_cross_year,
        "grades": sorted(list(grades)),
        "class_num": class_num_value,
        "class_label": current_label,
        "teaching_class_id": current_tc_id,
        "xueji_code": xueji_code_value,
        "class_rank_basis": class_rank_basis,
        "main_total_trend": [{
            "exam_id": t.exam_id,
            "exam_name": exam_map[t.exam_id].name if t.exam_id in exam_map else str(t.exam_id),
            "exam_date": exam_map[t.exam_id].exam_date if t.exam_id in exam_map else None,
            "grade": exam_map[t.exam_id].grade if t.exam_id in exam_map else None,
            "total_score": t.total_score,
            "xueji_rank": t.xueji_rank,
            "grade_percentile": t.grade_percentile,
            "class_rank": class_rank_by_exam.get(t.exam_id),
        } for t in main_totals_sorted],
        "five_trend": [{
            "exam_id": t.exam_id,
            "exam_name": exam_map[t.exam_id].name if t.exam_id in exam_map else str(t.exam_id),
            "exam_date": exam_map[t.exam_id].exam_date if t.exam_id in exam_map else None,
            "grade": exam_map[t.exam_id].grade if t.exam_id in exam_map else None,
            "total_score": t.total_score,
            "xueji_rank": t.xueji_rank,
            "grade_percentile": t.grade_percentile,
        } for t in five_totals_sorted],
        "subject_trend": [{
            "exam_id": s.exam_id,
            "exam_name": exam_map[s.exam_id].name if s.exam_id in exam_map else str(s.exam_id),
            "exam_date": exam_map[s.exam_id].exam_date if s.exam_id in exam_map else None,
            "subject": s.subject,
            "raw_score": s.raw_score,
            "grade_percentile": s.grade_percentile,
        } for s in subject_scores_with_score],
        "plus3_trend": [{
            "exam_id": t.exam_id,
            "exam_name": exam_map[t.exam_id].name if t.exam_id in exam_map else str(t.exam_id),
            "exam_date": exam_map[t.exam_id].exam_date if t.exam_id in exam_map else None,
            "grade": exam_map[t.exam_id].grade if t.exam_id in exam_map else None,
            "total_score": t.total_score,
            "xueji_rank": t.xueji_rank,
            "grade_percentile": t.grade_percentile,
        } for t in plus3_totals_sorted],
        "san3_trend": [{
            "exam_id": t.exam_id,
            "exam_name": exam_map[t.exam_id].name if t.exam_id in exam_map else str(t.exam_id),
            "exam_date": exam_map[t.exam_id].exam_date if t.exam_id in exam_map else None,
            "grade": exam_map[t.exam_id].grade if t.exam_id in exam_map else None,
            "total_score": t.total_score,
            "xueji_rank": t.xueji_rank,
            "grade_percentile": t.grade_percentile,
        } for t in san3_totals_sorted],
    }

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
    """学生检索数据源（替代前端逐场 fetch /api/exams/{id} 的低效做法）。
    teaching_class_id 为空=我教所有班的成员并集。按「人」去重（同一人多学号合并一行，
    取最新年级学号为代表）。返回每生所属教学班 label + 最新主三门摘要。"""
    from app.db.models import SessionLocal, Exam, SubjectScore, TotalScore
    from app.analysis.scope import (
        all_my_member_ids, members_of, student_class_map, student_ids_of_person, identity_of,
    )

    db = SessionLocal()
    try:
        if teaching_class_id is not None:
            scope_ids = members_of(db, teaching_class_id)
        else:
            scope_ids = all_my_member_ids(db, grade)

        if not scope_ids:
            return {"students": []}

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
                return {"students": []}

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

        # 最新考试（按年级/日期）
        latest_exam = (
            db.query(Exam).order_by(Exam.grade.desc(), Exam.exam_date.desc(), Exam.id.desc()).first()
        )
        latest_totals = {}
        if latest_exam:
            for t in db.query(TotalScore).filter(
                TotalScore.exam_id == latest_exam.id,
                TotalScore.total_type == "主三门",
                TotalScore.student_id.in_(scope_ids),
            ).all():
                latest_totals[t.student_id] = t

        students = []
        for ids in groups.values():
            rep = max(ids, key=lambda s: (sid_grade.get(s, 0), s))
            name_row = db.query(SubjectScore.name).filter(
                SubjectScore.student_id.in_(ids), SubjectScore.name.isnot(None)
            ).first()
            name = name_row[0] if name_row and name_row[0] else rep
            label, tc_id = label_map.get(rep, (None, None))
            lt = latest_totals.get(rep) or next(
                (latest_totals.get(s) for s in ids if latest_totals.get(s)), None
            )
            students.append({
                "student_id": rep,
                "name": name,
                "class_label": label,
                "teaching_class_id": tc_id,
                "grades": sorted({sid_grade.get(s) for s in ids if sid_grade.get(s)}),
                "latest_exam_id": latest_exam.id if latest_exam else None,
                "latest_total_score": lt.total_score if lt else None,
                "latest_xueji_rank": lt.xueji_rank if lt else None,
            })
        students.sort(key=lambda s: ((s["latest_xueji_rank"] or 10**9), s["student_id"]))
        return {"students": students, "count": len(students),
                "latest_exam": {"id": latest_exam.id, "name": latest_exam.name} if latest_exam else None}
    finally:
        db.close()


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
