import anthropic
from typing import Any
from typing import Optional

from app.chat.config import ChatConfig, get_chat_config

BASE_SUBJECTS = ("语文", "数学", "英语")
ELECTIVE_SUBJECTS = ("物理", "化学", "生物", "政治", "历史", "地理")
ALL_SUBJECTS = BASE_SUBJECTS + ELECTIVE_SUBJECTS


def create_anthropic_client(config: ChatConfig | None = None):
    config = config or get_chat_config()
    kwargs = {"api_key": config.api_key}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return anthropic.Anthropic(**kwargs)


def create_openai_client(config: ChatConfig | None = None):
    from openai import OpenAI

    config = config or get_chat_config()
    kwargs: dict[str, Any] = {"api_key": config.api_key}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return OpenAI(**kwargs)


def get_client():
    config = get_chat_config()
    if not config.is_configured:
        return None
    if config.provider == "openai":
        return create_openai_client(config)
    return create_anthropic_client(config)


# ────────────────────────────── 教学班范围解析 ──────────────────────────────

def _resolve_class_scope(
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
    grade: Optional[int] = None,
    exam_id: Optional[int] = None,
):
    """把教学班参数解析成成员学号集合（None=全年级）。优先 teaching_class_id，
    其次 class_label（按我的教学班名匹配成 tc_id），最后 class_num（行政班号回退）。"""
    from app.analysis.scope import resolve_scope_compat, my_class_labels, members_of

    if teaching_class_id is not None:
        return members_of(_db(), teaching_class_id)
    if class_label:
        labels = my_class_labels(_db(), grade)
        tc_id = labels.get(class_label.strip()) or labels.get(class_label)
        if tc_id is not None:
            return members_of(_db(), tc_id)
    return resolve_scope_compat(_db(), class_num=class_num, exam_id=exam_id, grade=grade)


def _db():
    from app.db.models import SessionLocal
    return SessionLocal()


def _resolve_tc_id(
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    grade: Optional[int] = None,
    exam_id: Optional[int] = None,
) -> Optional[int]:
    """把 class_label（教学班名）解析成 teaching_class_id；已给 id 直接返回。
    需要年级时优先用传入 grade，其次按 exam_id 反查。匹配不到返回 None。"""
    if teaching_class_id is not None:
        return teaching_class_id
    if not class_label:
        return None
    from app.analysis.scope import my_class_labels
    from app.db.models import Exam

    g = grade
    if g is None and exam_id is not None:
        db = _db()
        try:
            ex = db.query(Exam).filter(Exam.id == exam_id).first()
            g = ex.grade if ex else None
        finally:
            db.close()
    db = _db()
    try:
        labels = my_class_labels(db, g) if g is not None else {}
    finally:
        db.close()
    key = class_label.strip()
    return labels.get(key) or labels.get(class_label)


def list_my_classes(grade: Optional[int] = None) -> list[dict[str, Any]]:
    """列出我配置的教学班（可限年级），供把『物A1班/1班』等名字解析成 teaching_class_id。"""
    from app.analysis.scope import list_classes, members_of

    db = _db()
    try:
        out = []
        for tc in list_classes(db, grade):
            out.append({
                "teaching_class_id": tc.id,
                "grade": tc.grade,
                "label": tc.label,
                "subject": tc.subject,
                "kind": tc.kind,
                "member_count": len(members_of(db, tc.id)),
            })
        return out
    finally:
        db.close()


def _has_subject_score(score) -> bool:
    return score.raw_score is not None or score.grade_score is not None


def _subject_score_payload(score, exam=None) -> dict[str, Any]:
    available = _has_subject_score(score)
    payload = {
        "subject": score.subject,
        "raw_score": score.raw_score if available else None,
        "grade_score": score.grade_score if available else None,
        "grade_percentile": score.grade_percentile if available else None,
        "available": available,
    }
    if exam is not None:
        payload["exam"] = {
            "id": exam.id,
            "name": exam.name,
            "grade": exam.grade,
            "exam_date": exam.exam_date,
        }
    return payload


def _missing_subject_payload(subject: str) -> dict[str, Any]:
    return {
        "subject": subject,
        "raw_score": None,
        "grade_score": None,
        "grade_percentile": None,
        "available": False,
    }

def list_exams(grade: Optional[int] = None, year_range: Optional[tuple] = None) -> list:
    """列出已建档考试"""
    from app.db.models import Exam
    from app.db.models import get_db

    db = next(get_db())
    query = db.query(Exam).order_by(Exam.exam_date.desc())
    if grade:
        query = query.filter(Exam.grade == grade)
    exams = query.all()
    db.close()
    return [{"id": e.id, "name": e.name, "grade": e.grade, "exam_date": e.exam_date} for e in exams]

def student_lookup(name: Optional[str] = None, student_id: Optional[str] = None) -> list:
    """按姓名/学号定位学生"""
    from app.db.models import SubjectScore
    from app.db.models import get_db

    db = next(get_db())
    query = db.query(SubjectScore.student_id, SubjectScore.name).distinct()
    if student_id:
        query = query.filter(SubjectScore.student_id == student_id)
    if name:
        query = query.filter(SubjectScore.name.like(f"%{name}%"))
    results = query.all()
    db.close()
    return [{"student_id": r[0], "name": r[1]} for r in results]

def student_exam_detail(student_id: str, exam_id: int) -> dict:
    """某生某次考试的完整成绩"""
    from app.db.models import SubjectScore, TotalScore
    from app.db.models import get_db

    db = next(get_db())
    subjects = db.query(SubjectScore).filter(
        SubjectScore.student_id == student_id,
        SubjectScore.exam_id == exam_id
    ).all()
    totals = db.query(TotalScore).filter(
        TotalScore.student_id == student_id,
        TotalScore.exam_id == exam_id
    ).all()
    db.close()

    return {
        "student_id": student_id,
        "exam_id": exam_id,
        "subjects": [_subject_score_payload(s) for s in subjects],
        "totals": [{"total_type": t.total_type, "total_score": t.total_score, "xueji_rank": t.xueji_rank} for t in totals],
    }


def student_trend(student_id: str, total_type: str = "主三门", exam_ids: Optional[list[int]] = None) -> dict:
    """跨次趋势。跨学年调用方应使用主三门。"""
    from app.analysis.trends import compute_student_trend
    from app.db.models import Exam, TotalScore
    from app.db.models import get_db

    db = next(get_db())
    if exam_ids is None:
        exam_ids = [
            row[0]
            for row in db.query(TotalScore.exam_id)
            .join(Exam, Exam.id == TotalScore.exam_id)
            .filter(TotalScore.student_id == student_id, TotalScore.total_type == total_type)
            .order_by(Exam.grade, Exam.exam_date)
            .distinct()
            .all()
        ]
    result = compute_student_trend(student_id, total_type, exam_ids, db)
    db.close()
    return result


def student_learning_profile(
    student_id: Optional[str] = None,
    name: Optional[str] = None,
    subject_limit: int = 5,
) -> dict[str, Any]:
    """学生整体学习画像：总分趋势、单科强弱项、进退步科目。"""
    from collections import defaultdict

    from app.db.models import Exam, SubjectScore, TotalScore
    from app.db.models import get_db

    db = next(get_db())
    students_query = db.query(SubjectScore.student_id, SubjectScore.name).distinct()
    if student_id:
        students_query = students_query.filter(SubjectScore.student_id == student_id)
    if name:
        students_query = students_query.filter(SubjectScore.name.like(f"%{name}%"))
    students = students_query.limit(10).all()

    if not students:
        db.close()
        return {"error": "未找到学生", "student_id": student_id, "name": name}
    if len(students) > 1 and not student_id:
        db.close()
        return {
            "error": "匹配到多个学生，请指定学号",
            "candidates": [{"student_id": row[0], "name": row[1]} for row in students],
        }

    resolved_student_id = students[0][0]
    resolved_name = students[0][1] or resolved_student_id

    exam_rows = (
        db.query(Exam)
        .join(TotalScore, Exam.id == TotalScore.exam_id)
        .filter(TotalScore.student_id == resolved_student_id)
        .order_by(Exam.grade, Exam.exam_date, Exam.id)
        .distinct()
        .all()
    )
    exam_map = {exam.id: exam for exam in exam_rows}

    totals = (
        db.query(TotalScore)
        .filter(TotalScore.student_id == resolved_student_id)
        .all()
    )
    totals_by_type: dict[str, list[TotalScore]] = defaultdict(list)
    for total in totals:
        totals_by_type[total.total_type].append(total)
    for rows in totals_by_type.values():
        rows.sort(key=lambda row: (exam_map.get(row.exam_id).grade if exam_map.get(row.exam_id) else 0,
                                   exam_map.get(row.exam_id).exam_date if exam_map.get(row.exam_id) else "",
                                   row.exam_id))

    subjects = (
        db.query(SubjectScore)
        .filter(SubjectScore.student_id == resolved_student_id)
        .all()
    )
    subjects_by_name: dict[str, list[SubjectScore]] = defaultdict(list)
    subjects_by_exam: dict[int, dict[str, SubjectScore]] = defaultdict(dict)
    for score in subjects:
        subjects_by_name[score.subject].append(score)
        subjects_by_exam[score.exam_id][score.subject] = score
    for rows in subjects_by_name.values():
        rows.sort(key=lambda row: (exam_map.get(row.exam_id).grade if exam_map.get(row.exam_id) else 0,
                                   exam_map.get(row.exam_id).exam_date if exam_map.get(row.exam_id) else "",
                                   row.exam_id))

    def exam_payload(exam_id: int) -> dict[str, Any]:
        exam = exam_map.get(exam_id)
        if not exam:
            return {"id": exam_id, "name": str(exam_id), "grade": None, "exam_date": None}
        return {"id": exam.id, "name": exam.name, "grade": exam.grade, "exam_date": exam.exam_date}

    def is_high23_elective(score: SubjectScore) -> bool:
        exam = exam_map.get(score.exam_id)
        return bool(exam and exam.grade in {2, 3} and score.subject in ELECTIVE_SUBJECTS)

    def analysis_metric(score: SubjectScore) -> dict[str, Any]:
        if not _has_subject_score(score):
            return {
                "metric_kind": "missing",
                "value": None,
                "lower_is_better": None,
                "note": "未参考或无有效成绩",
            }
        if is_high23_elective(score):
            return {
                "metric_kind": "grade_score",
                "value": score.grade_score,
                "lower_is_better": False,
                "note": "高二/高三加三选考单科用等级分判断趋势",
            }
        return {
            "metric_kind": "grade_percentile",
            "value": score.grade_percentile,
            "lower_is_better": True,
            "note": "高一单科和高二/高三语数英用年级百分位判断趋势，数值越小越靠前",
        }

    def subject_history_payload(score: SubjectScore) -> dict[str, Any]:
        payload = _subject_score_payload(score, exam_map.get(score.exam_id))
        payload["analysis_metric"] = analysis_metric(score)
        return payload

    def trend_change(first: SubjectScore, latest: SubjectScore) -> tuple[float | None, dict[str, Any]]:
        first_metric = analysis_metric(first)
        latest_metric = analysis_metric(latest)
        if first_metric["metric_kind"] != latest_metric["metric_kind"]:
            return None, {
                "metric_kind": latest_metric["metric_kind"],
                "value_field": latest_metric["metric_kind"],
                "reason": "起止考试指标口径不同，不能直接计算趋势变化",
            }
        first_value = first_metric["value"]
        latest_value = latest_metric["value"]
        if first_value is None or latest_value is None:
            return None, {
                "metric_kind": latest_metric["metric_kind"],
                "value_field": latest_metric["metric_kind"],
                "reason": "有效趋势点不足",
            }
        if latest_metric["lower_is_better"]:
            change = round(first_value - latest_value, 4)
        else:
            change = round(latest_value - first_value, 4)
        return change, {
            "metric_kind": latest_metric["metric_kind"],
            "value_field": latest_metric["metric_kind"],
            "lower_is_better": latest_metric["lower_is_better"],
            "positive_means": "进步",
        }

    main_total_trend = []
    for total in totals_by_type.get("主三门", []):
        main_total_trend.append(
            {
                "exam": exam_payload(total.exam_id),
                "total_score": total.total_score,
                "xueji_rank": total.xueji_rank,
                "grade_rank": total.grade_rank,
                "grade_percentile": total.grade_percentile,
            }
        )

    subject_summaries = []
    subject_history = {}
    for subject, rows in subjects_by_name.items():
        history = [subject_history_payload(score) for score in rows]
        subject_history[subject] = history
        valid_rows = [score for score in rows if _has_subject_score(score)]
        if not valid_rows:
            continue
        latest = valid_rows[-1]
        comparable_rows = [
            score
            for score in valid_rows
            if analysis_metric(score)["metric_kind"] == analysis_metric(latest)["metric_kind"]
        ]
        first = comparable_rows[0] if comparable_rows else latest
        raw_score_change = None
        if first.raw_score is not None and latest.raw_score is not None:
            raw_score_change = round(latest.raw_score - first.raw_score, 2)
        metric_change, metric_meta = trend_change(first, latest)
        subject_summaries.append(
            {
                "subject": subject,
                "latest_raw_score": latest.raw_score,
                "latest_grade_score": latest.grade_score,
                "latest_grade_percentile": latest.grade_percentile,
                "raw_score_change": raw_score_change,
                "percentile_change": metric_change if metric_meta["metric_kind"] == "grade_percentile" else None,
                "grade_score_change": metric_change if metric_meta["metric_kind"] == "grade_score" else None,
                "trend_change": metric_change,
                "trend_metric": metric_meta,
                "exam_count": len(valid_rows),
            }
        )

    latest_exam = exam_rows[-1] if exam_rows else None
    latest_subjects = []
    if latest_exam:
        latest_subjects = [subject_history_payload(score) for score in subjects if score.exam_id == latest_exam.id and _has_subject_score(score)]

    exam_history = []
    for exam in exam_rows:
        score_map = subjects_by_exam.get(exam.id, {})
        subject_payloads = {}
        included_subjects = []
        missing_subjects = []
        for subject in ALL_SUBJECTS:
            score = score_map.get(subject)
            payload = subject_history_payload(score) if score else _missing_subject_payload(subject)
            subject_payloads[subject] = payload
            if payload["available"]:
                included_subjects.append(subject)
            else:
                missing_subjects.append(subject)
        exam_history.append(
            {
                "exam": exam_payload(exam.id),
                "subjects": subject_payloads,
                "included_subjects": included_subjects,
                "missing_subjects": missing_subjects,
            }
        )

    def latest_sort_score(row: dict[str, Any]) -> float | None:
        metric = row.get("analysis_metric") or {}
        value = metric.get("value")
        if value is None:
            return None
        return value if metric.get("lower_is_better") else -value

    latest_rankable = [row for row in latest_subjects if latest_sort_score(row) is not None]
    strengths = sorted(latest_rankable, key=lambda row: latest_sort_score(row) or 0)[:subject_limit]
    weaknesses = sorted(latest_rankable, key=lambda row: latest_sort_score(row) or 0, reverse=True)[:subject_limit]
    progress_subjects = sorted(
        [row for row in subject_summaries if row["trend_change"] is not None],
        key=lambda row: row["trend_change"],
        reverse=True,
    )[:subject_limit]
    regression_subjects = sorted(
        [row for row in subject_summaries if row["trend_change"] is not None],
        key=lambda row: row["trend_change"],
    )[:subject_limit]

    db.close()
    return {
        "student": {
            "student_id": resolved_student_id,
            "name": resolved_name,
            "current_grade": latest_exam.grade if latest_exam else None,
            "latest_exam": exam_payload(latest_exam.id) if latest_exam else None,
        },
        "available_exams": [exam_payload(exam.id) for exam in exam_rows],
        "main_total_trend": main_total_trend,
        "latest_subjects": latest_subjects,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "progress_subjects": progress_subjects,
        "regression_subjects": regression_subjects,
        "subject_history": subject_history,
        "exam_history": exam_history,
        "subject_scope_note": "加三学科指物理、化学、生物、政治、历史、地理六科的统称；高二/高三学生通常只在六科中选择三科考试。",
        "metric_note": "available=false 表示未参考或无有效成绩，即使原始导入行里有百分位也不能当作成绩引用。grade_percentile 越小表示年级位置越靠前；高一单科和高二/高三语数英用 grade_percentile 判断趋势；高二/高三加三选考单科用 grade_score 判断趋势。trend_change 为正表示进步，为负表示退步；raw_score_change 只能作为辅助说明。",
        "analysis_boundary": "仅基于已导入考试成绩，不能推断课堂表现、作业习惯或家庭因素。",
    }


def class_trend(
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
    metric: str = "主三门",
    exam_ids: Optional[list[int]] = None,
) -> list[dict[str, Any]]:
    """某教学班/行政班的均分时间序列。优先 teaching_class_id/class_label（教学班标签），
    否则 class_num（行政班号）。metric 可以是总分类型或学科名。"""
    from app.db.models import ClassAverage, Exam, TeachingClass, TotalScore
    from sqlalchemy import or_

    db = _db()
    try:
        # 解析目标标签（教学班）或行政班号
        label = class_label.strip() if class_label else None
        cn = int(class_num) if class_num is not None else None
        if teaching_class_id is not None:
            tc = db.query(TeachingClass).filter(TeachingClass.id == teaching_class_id).first()
            if tc:
                label = tc.label
        # 若给的是教学班 label，尝试转成行政班号（数字 label）
        if label is not None and cn is None and label.isdigit():
            cn = int(label)

        query = db.query(Exam).order_by(Exam.grade, Exam.exam_date)
        if exam_ids:
            query = query.filter(Exam.id.in_(exam_ids))
        exams = query.all()

        series = []
        for exam in exams:
            avg = None
            if label is not None:
                avg = (
                    db.query(ClassAverage)
                    .filter(
                        ClassAverage.exam_id == exam.id,
                        or_(
                            ClassAverage.class_label == label,
                            (ClassAverage.class_label.is_(None)) & (ClassAverage.class_num == cn),
                        ),
                    )
                    .first()
                )
            elif cn is not None:
                avg = db.query(ClassAverage).filter(
                    ClassAverage.exam_id == exam.id, ClassAverage.class_num == cn
                ).first()
            value = None
            if avg:
                if avg.total_averages:
                    value = avg.total_averages.get(metric)
                if value is None and avg.subject_averages:
                    value = avg.subject_averages.get(metric)
            elif teaching_class_id is not None:
                # 无官方班均分时，用成员现算
                from app.analysis.scope import members_of
                members = members_of(db, teaching_class_id)
                if members:
                    rows = (
                        db.query(TotalScore.total_score)
                        .filter(
                            TotalScore.exam_id == exam.id,
                            TotalScore.student_id.in_(members),
                            TotalScore.total_type == metric,
                            TotalScore.total_score.isnot(None),
                        ).all()
                    )
                    vs = [r[0] for r in rows]
                    value = round(sum(vs) / len(vs), 1) if vs else None
            series.append({"exam_id": exam.id, "exam_name": exam.name, "metric": metric, "value": value})
        return series
    finally:
        db.close()


def compare_classes(
    teaching_class_ids: Optional[list[int]] = None,
    class_labels: Optional[list[str]] = None,
    class_nums: Optional[list[int]] = None,
    exam_id: int = None,
    metric: str = "主三门",
) -> list[dict[str, Any]]:
    """多班同次对比。优先 teaching_class_ids/class_labels（教学班标签），否则 class_nums。"""
    from app.db.models import ClassAverage
    from sqlalchemy import or_

    db = _db()
    try:
        labels = [s.strip() for s in (class_labels or []) if s and s.strip()]
        if teaching_class_ids:
            from app.db.models import TeachingClass
            for tc in db.query(TeachingClass).filter(TeachingClass.id.in_(teaching_class_ids)).all():
                if tc.label not in labels:
                    labels.append(tc.label)
        nums = [int(n) for n in (class_nums or []) if n is not None]

        q = db.query(ClassAverage).filter(ClassAverage.exam_id == exam_id)
        rows = []
        if labels:
            avgs = q.filter(or_(ClassAverage.class_label.in_(labels), ClassAverage.class_num.in_(nums) if nums else ClassAverage.class_label.in_(labels))).all()
        else:
            avgs = q.filter(ClassAverage.class_num.in_(nums)).all() if nums else []
        for avg in avgs:
            value = None
            if avg.total_averages:
                value = avg.total_averages.get(metric)
            if value is None and avg.subject_averages:
                value = avg.subject_averages.get(metric)
            rows.append({"class_label": avg.class_label or str(avg.class_num), "class_num": avg.class_num, "metric": metric, "value": value})
        return rows
    finally:
        db.close()


def focus_list(exam_id: int, category: Optional[str] = None) -> list[dict[str, Any]]:
    """重点关注名单。"""
    from app.analysis.config import SUBJECT_WEAKNESS_PCT_DIFF, get_band_config
    from app.db.models import SubjectScore, TotalScore
    from app.db.models import get_db

    db = next(get_db())
    band_cfg = get_band_config(db)
    totals = db.query(TotalScore).filter(
        TotalScore.exam_id == exam_id,
        TotalScore.total_type == "主三门",
    ).all()
    rows = []
    for total in totals:
        rank = total.xueji_rank or total.grade_rank or 999999
        subjects = db.query(SubjectScore).filter(
            SubjectScore.exam_id == exam_id,
            SubjectScore.student_id == total.student_id,
        ).all()
        name = next((s.name for s in subjects if s.name), total.student_id)
        issues = []
        if band_cfg["critical_min"] <= rank <= band_cfg["critical_max"]:
            issues.append("临界段")
        if rank >= band_cfg["weak_min"]:
            issues.append("薄弱段")
        if total.grade_percentile is not None:
            for subject in subjects:
                if subject.grade_percentile is not None and subject.grade_percentile - total.grade_percentile >= SUBJECT_WEAKNESS_PCT_DIFF:
                    issues.append(f"严重偏科({subject.subject})")
        if category:
            issues = [issue for issue in issues if category in issue]
        if issues:
            rows.append({"student_id": total.student_id, "name": name, "xueji_rank": rank, "issues": issues})
    db.close()
    return sorted(rows, key=lambda row: row["xueji_rank"])[:50]


def subject_weakness(
    exam_id: int,
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
) -> list[dict[str, Any]]:
    """本班/教学班单科薄弱清单。teaching_class_id/class_label 限定教学班成员，
    class_num 限定行政班，都空=全年级。"""
    from app.analysis.config import SUBJECT_WEAKNESS_PCT_DIFF
    from app.db.models import SubjectScore, TotalScore
    from app.db.models import get_db

    db = next(get_db())
    allowed = _resolve_class_scope(
        teaching_class_id=teaching_class_id, class_label=class_label,
        class_num=class_num, exam_id=exam_id,
    )
    main_totals = db.query(TotalScore).filter(
        TotalScore.exam_id == exam_id,
        TotalScore.total_type == "主三门",
    ).all()
    main_pct = {row.student_id: row.grade_percentile for row in main_totals if row.grade_percentile is not None}
    subjects = db.query(SubjectScore).filter(
        SubjectScore.exam_id == exam_id,
    ).all()
    rows = []
    for subject in subjects:
        if allowed is not None and subject.student_id not in allowed:
            continue
        base = main_pct.get(subject.student_id)
        if base is None or subject.grade_percentile is None:
            continue
        diff = subject.grade_percentile - base
        if diff >= SUBJECT_WEAKNESS_PCT_DIFF:
            rows.append(
                {
                    "student_id": subject.student_id,
                    "name": subject.name,
                    "subject": subject.subject,
                    "raw_score": subject.raw_score,
                    "grade_percentile": subject.grade_percentile,
                    "diff": round(diff, 3),
                }
            )
    db.close()
    return sorted(rows, key=lambda row: row["grade_percentile"])[:50]


def subject_progress_ranking(
    grade: int,
    subject: str,
    start_exam_id: Optional[int] = None,
    end_exam_id: Optional[int] = None,
    limit: int = 10,
    direction: str = "progress",
) -> dict[str, Any]:
    """按年级/学科查询跨考试进步最大的学生。"""
    from app.db.models import Exam, SubjectScore
    from app.db.models import get_db

    db = next(get_db())
    exams_query = db.query(Exam).filter(Exam.grade == grade).order_by(Exam.exam_date, Exam.id)
    exams = exams_query.all()
    if len(exams) < 2 and not (start_exam_id and end_exam_id):
        db.close()
        return {"error": "该年级可比较的考试少于2次", "grade": grade, "subject": subject, "rows": []}

    exam_by_id = {exam.id: exam for exam in exams}
    if start_exam_id is None:
        start_exam = exams[0]
    else:
        start_exam = exam_by_id.get(start_exam_id) or db.query(Exam).filter(Exam.id == start_exam_id).first()
    if end_exam_id is None:
        end_exam = exams[-1]
    else:
        end_exam = exam_by_id.get(end_exam_id) or db.query(Exam).filter(Exam.id == end_exam_id).first()

    if not start_exam or not end_exam:
        db.close()
        return {"error": "起止考试不存在", "grade": grade, "subject": subject, "rows": []}
    if start_exam.id == end_exam.id:
        db.close()
        return {"error": "起止考试不能相同", "grade": grade, "subject": subject, "rows": []}

    start_scores = db.query(SubjectScore).filter(
        SubjectScore.exam_id == start_exam.id,
        SubjectScore.subject == subject,
    ).all()
    end_scores = db.query(SubjectScore).filter(
        SubjectScore.exam_id == end_exam.id,
        SubjectScore.subject == subject,
    ).all()

    use_grade_score = start_exam.grade in {2, 3} and end_exam.grade in {2, 3} and subject in ELECTIVE_SUBJECTS
    start_by_student = {score.student_id: score for score in start_scores}
    rows = []
    for end_score in end_scores:
        start_score = start_by_student.get(end_score.student_id)
        if not start_score:
            continue

        if not _has_subject_score(start_score) or not _has_subject_score(end_score):
            continue

        percentile_change = None
        if start_score.grade_percentile is not None and end_score.grade_percentile is not None:
            percentile_change = round(start_score.grade_percentile - end_score.grade_percentile, 4)

        grade_score_change = None
        if start_score.grade_score is not None and end_score.grade_score is not None:
            grade_score_change = round(end_score.grade_score - start_score.grade_score, 2)

        raw_score_change = None
        if start_score.raw_score is not None and end_score.raw_score is not None:
            raw_score_change = round(end_score.raw_score - start_score.raw_score, 2)

        trend_change = grade_score_change if use_grade_score else percentile_change
        if trend_change is None and raw_score_change is None:
            continue

        rows.append(
            {
                "student_id": end_score.student_id,
                "name": end_score.name or start_score.name,
                "class_num": end_score.class_num or start_score.class_num,
                "start_raw_score": start_score.raw_score,
                "end_raw_score": end_score.raw_score,
                "raw_score_change": raw_score_change,
                "start_grade_score": start_score.grade_score,
                "end_grade_score": end_score.grade_score,
                "grade_score_change": grade_score_change,
                "start_grade_percentile": start_score.grade_percentile,
                "end_grade_percentile": end_score.grade_percentile,
                "percentile_change": percentile_change,
                "trend_change": trend_change,
            }
        )

    reverse = direction != "regression"
    none_value = float("-inf") if reverse else float("inf")
    rows.sort(
        key=lambda row: (
            row["trend_change"] if row["trend_change"] is not None else none_value,
            row["raw_score_change"] if row["raw_score_change"] is not None else none_value,
        ),
        reverse=reverse,
    )
    db.close()

    return {
        "grade": grade,
        "subject": subject,
        "start_exam": {"id": start_exam.id, "name": start_exam.name, "exam_date": start_exam.exam_date},
        "end_exam": {"id": end_exam.id, "name": end_exam.name, "exam_date": end_exam.exam_date},
        "direction": direction,
        "metric": (
            "高二/高三加三学科用 grade_score_change/trend_change 判断进退步；"
            "其他单科用 percentile_change/trend_change 判断进退步，正数表示进步，负数表示退步；"
            "raw_score_change 为原始分变化，只作单点辅助。"
        ),
        "rows": rows[: max(1, min(limit, 50))],
    }


def multi_exam_progress_ranking(
    grade: int,
    metrics: Optional[list[str]] = None,
    exam_ids: Optional[list[int]] = None,
    recent_count: int = 5,
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
    limit: int = 10,
    direction: str = "progress",
    min_points: int = 2,
) -> dict[str, Any]:
    """多场考试合并判断进退步/趋势排行。"""
    from app.db.models import Exam, SubjectScore, TotalScore
    from app.db.models import get_db

    total_types = {"主三门", "五门", "九门", "+3", "3+3"}
    base_subjects = {"语文", "数学", "英语"}
    elective_subjects = {"物理", "化学", "生物", "政治", "历史", "地理"}
    all_subjects = base_subjects | elective_subjects

    def default_metrics_for_grade() -> list[str]:
        if grade == 1:
            return ["主三门", "五门", "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]
        return ["主三门", "3+3", "+3", "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]

    def clean_metrics(values: Optional[list[str]]) -> list[str]:
        seen = set()
        cleaned = []
        for value in values or default_metrics_for_grade():
            metric = str(value).strip()
            if not metric or metric in seen:
                continue
            if metric not in total_types and metric not in all_subjects:
                continue
            seen.add(metric)
            cleaned.append(metric)
        return cleaned

    def line_fit_change(values: list[float], lower_is_better: bool) -> float:
        n = len(values)
        if n < 2:
            return 0.0
        x_avg = (n - 1) / 2
        y_avg = sum(values) / n
        denom = sum((i - x_avg) ** 2 for i in range(n))
        if denom == 0:
            return 0.0
        slope = sum((i - x_avg) * (value - y_avg) for i, value in enumerate(values)) / denom
        change = slope * (n - 1)
        return -change if lower_is_better else change

    def classify_trend(overall_change: float, step_changes: list[float]) -> str:
        eps = 1e-9
        progress_steps = sum(1 for value in step_changes if value > eps)
        regression_steps = sum(1 for value in step_changes if value < -eps)
        if abs(overall_change) <= eps:
            if progress_steps and regression_steps:
                return "波动持平"
            return "基本稳定"
        if overall_change > 0:
            return "持续进步" if progress_steps == len(step_changes) else "总体进步"
        return "持续退步" if regression_steps == len(step_changes) else "总体退步"

    def build_row(
        student_id: str,
        metric: str,
        metric_kind: str,
        value_field: str,
        lower_is_better: bool,
        points: list[dict[str, Any]],
        profile: dict[str, Any],
    ) -> dict[str, Any] | None:
        if len(points) < max(2, min_points):
            return None
        values = [point["value"] for point in points if isinstance(point["value"], (int, float))]
        if len(values) < max(2, min_points):
            return None

        if lower_is_better:
            step_changes = [values[i] - values[i + 1] for i in range(len(values) - 1)]
            overall_change = values[0] - values[-1]
        else:
            step_changes = [values[i + 1] - values[i] for i in range(len(values) - 1)]
            overall_change = values[-1] - values[0]

        slope_change = line_fit_change(values, lower_is_better)
        trend_score = round(0.7 * overall_change + 0.3 * slope_change, 4)
        progress_steps = sum(1 for value in step_changes if value > 0)
        regression_steps = sum(1 for value in step_changes if value < 0)
        return {
            "student_id": student_id,
            "name": profile.get("name") or student_id,
            "class_num": profile.get("class_num"),
            "metric": metric,
            "metric_kind": metric_kind,
            "value_field": value_field,
            "lower_is_better": lower_is_better,
            "point_count": len(values),
            "trend_label": classify_trend(overall_change, step_changes),
            "trend_score": trend_score,
            "overall_change": round(overall_change, 4),
            "slope_change": round(slope_change, 4),
            "improvement_steps": progress_steps,
            "regression_steps": regression_steps,
            "series": points,
        }

    db = next(get_db())
    try:
        selected_metrics = clean_metrics(metrics)
        if not selected_metrics:
            return {"error": "没有可分析的指标", "grade": grade, "metrics": []}

        if exam_ids:
            exams = (
                db.query(Exam)
                .filter(Exam.id.in_(exam_ids), Exam.grade == grade)
                .order_by(Exam.exam_date, Exam.id)
                .all()
            )
        else:
            all_exams = db.query(Exam).filter(Exam.grade == grade).order_by(Exam.exam_date, Exam.id).all()
            count = max(2, min(recent_count or 5, 12))
            exams = all_exams[-count:]

        if len(exams) < 2:
            return {"error": "该年级可比较的考试少于2次", "grade": grade, "metrics": selected_metrics, "rows": []}

        exam_ids_selected = [exam.id for exam in exams]
        exam_payload = [
            {"id": exam.id, "name": exam.name, "exam_date": exam.exam_date}
            for exam in exams
        ]
        exam_name_by_id = {exam.id: exam.name for exam in exams}

        subject_rows = db.query(SubjectScore).filter(SubjectScore.exam_id.in_(exam_ids_selected)).all()
        allowed = _resolve_class_scope(
            teaching_class_id=teaching_class_id, class_label=class_label,
            class_num=class_num, grade=grade,
        )
        profiles: dict[str, dict[str, Any]] = {}
        for row in subject_rows:
            profile = profiles.setdefault(row.student_id, {"name": row.name, "class_num": row.class_num})
            if row.name:
                profile["name"] = row.name
            if row.class_num is not None:
                profile["class_num"] = row.class_num

        results = []
        for metric in selected_metrics:
            is_total = metric in total_types
            metric_kind = "total" if is_total else "subject"
            if is_total:
                rows = (
                    db.query(TotalScore)
                    .filter(TotalScore.exam_id.in_(exam_ids_selected), TotalScore.total_type == metric)
                    .all()
                )
                grouped: dict[str, list[dict[str, Any]]] = {}
                value_field = "total_score" if metric == "+3" else "rank_or_percentile"
                lower_is_better = metric != "+3"
                for row in rows:
                    if allowed is not None and row.student_id not in allowed:
                        continue
                    if metric == "+3":
                        value = row.total_score
                        current_field = "total_score"
                    else:
                        value = row.xueji_rank or row.grade_rank
                        current_field = "rank"
                        if value is None and row.grade_percentile is not None:
                            value = row.grade_percentile
                            current_field = "grade_percentile"
                    if value is None:
                        continue
                    value_field = current_field if value_field == "rank_or_percentile" else value_field
                    grouped.setdefault(row.student_id, []).append(
                        {
                            "exam_id": row.exam_id,
                            "exam_name": exam_name_by_id.get(row.exam_id, str(row.exam_id)),
                            "value": value,
                            "value_field": current_field,
                            "total_score": row.total_score,
                            "xueji_rank": row.xueji_rank,
                            "grade_rank": row.grade_rank,
                            "grade_percentile": row.grade_percentile,
                        }
                    )
            else:
                rows = [row for row in subject_rows if row.subject == metric]
                grouped = {}
                lower_is_better = not (grade in {2, 3} and metric not in base_subjects)
                value_field = "grade_score" if not lower_is_better else "grade_percentile"
                for row in rows:
                    if allowed is not None and row.student_id not in allowed:
                        continue
                    value = row.grade_score if value_field == "grade_score" else row.grade_percentile
                    if value is None:
                        continue
                    grouped.setdefault(row.student_id, []).append(
                        {
                            "exam_id": row.exam_id,
                            "exam_name": exam_name_by_id.get(row.exam_id, str(row.exam_id)),
                            "value": value,
                            "value_field": value_field,
                            "raw_score": row.raw_score,
                            "grade_score": row.grade_score,
                            "grade_percentile": row.grade_percentile,
                        }
                    )

            metric_rows = []
            for student_id, points in grouped.items():
                ordered_points = sorted(points, key=lambda point: exam_ids_selected.index(point["exam_id"]))
                profile = profiles.get(student_id, {})
                row = build_row(student_id, metric, metric_kind, value_field, lower_is_better, ordered_points, profile)
                if row:
                    metric_rows.append(row)

            reverse = direction != "regression"
            metric_rows.sort(
                key=lambda row: (
                    row["trend_score"],
                    row["overall_change"],
                    row["improvement_steps"] - row["regression_steps"],
                ),
                reverse=reverse,
            )
            results.append(
                {
                    "metric": metric,
                    "metric_kind": metric_kind,
                    "value_field": value_field,
                    "lower_is_better": lower_is_better,
                    "rows": metric_rows[: max(1, min(limit, 50))],
                }
            )

        return {
            "grade": grade,
            "direction": direction,
            "teaching_class_id": teaching_class_id,
            "class_num": class_num,
            "exams": exam_payload,
            "recent_count": len(exams),
            "metrics": results,
            "metric_note": (
                "trend_score 综合首末变化和多点线性趋势；正数表示进步，负数表示退步。"
                "总分优先使用学籍/年级排名，其次年级百分位；高一单科和高二/三语数英用年级百分位；"
                "高二/三选考单科用等级分。"
            ),
        }
    finally:
        db.close()


def band_trend(
    grade: int,
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
) -> dict[str, Any]:
    """某年级历次考试的高分段/临界段/薄弱段人数趋势。teaching_class_id/class_label
    限定教学班成员；class_num 限定行政班；都空=全年级。分段口径用当前 band_config。"""
    from app.analysis.config import get_band_config
    from app.db.models import Exam, TotalScore
    from app.analysis.scope import members_of, my_class_labels, members_by_class_num

    db = _db()
    try:
        cfg = get_band_config(db)
        allowed = _resolve_class_scope(
            teaching_class_id=teaching_class_id, class_label=class_label,
            class_num=class_num, grade=grade,
        )
        exams = (
            db.query(Exam).filter(Exam.grade == grade)
            .order_by(Exam.grade, Exam.exam_date, Exam.id).all()
        )
        series = []
        for exam in exams:
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
                "exam_name": exam.name, "exam_date": exam.exam_date,
                "high_score": high, "critical": crit, "weak": weak,
            })
        return {"band_config": cfg, "teaching_class_id": teaching_class_id,
                "class_num": class_num, "series": series}
    finally:
        db.close()


def custom_rank_band_trend(
    grade: int,
    rank_max: int,
    rank_min: int = 1,
    total_type: str = "主三门",
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    """按用户临时指定的排名区间统计历次考试人数变化。teaching_class_id/class_label 限定教学班。"""
    from datetime import date

    from app.db.models import Exam, TotalScore

    def normalize_date(value: Optional[str], *, end: bool = False) -> Optional[date]:
        if not value:
            return None
        text = str(value).strip()
        try:
            if len(text) == 4 and text.isdigit():
                return date(int(text), 12 if end else 1, 31 if end else 1)
            if len(text) == 7:
                year, month = [int(part) for part in text.split("-")]
                if end:
                    next_month = date(year + (month // 12), (month % 12) + 1, 1)
                    return date.fromordinal(next_month.toordinal() - 1)
                return date(year, month, 1)
            return date.fromisoformat(text[:10])
        except Exception:
            return None

    rank_min = max(1, int(rank_min or 1))
    rank_max = int(rank_max)
    if rank_max < rank_min:
        return {
            "error": "rank_max 不能小于 rank_min",
            "grade": grade, "rank_min": rank_min, "rank_max": rank_max, "series": [],
        }

    start = normalize_date(start_date)
    end = normalize_date(end_date, end=True)

    db = _db()
    try:
        allowed = _resolve_class_scope(
            teaching_class_id=teaching_class_id, class_label=class_label,
            class_num=class_num, grade=grade,
        )
        exams = (
            db.query(Exam).filter(Exam.grade == grade)
            .order_by(Exam.exam_date, Exam.id).all()
        )
        series = []
        for exam in exams:
            exam_date = normalize_date(exam.exam_date)
            if start and exam_date and exam_date < start:
                continue
            if end and exam_date and exam_date > end:
                continue
            totals = (
                db.query(TotalScore)
                .filter(TotalScore.exam_id == exam.id, TotalScore.total_type == total_type)
                .all()
            )
            ranks = []
            for total in totals:
                if allowed is not None and total.student_id not in allowed:
                    continue
                rank = total.xueji_rank or total.grade_rank
                if rank is not None:
                    ranks.append(rank)
            count = sum(1 for rank in ranks if rank_min <= rank <= rank_max)
            series.append({
                "exam_id": exam.id, "exam_name": exam.name, "exam_date": exam.exam_date,
                "count": count, "ranked_count": len(ranks),
                "rank_min_observed": min(ranks) if ranks else None,
                "rank_max_observed": max(ranks) if ranks else None,
            })
        return {
            "grade": grade, "teaching_class_id": teaching_class_id, "class_num": class_num,
            "total_type": total_type, "rank_min": rank_min, "rank_max": rank_max,
            "start_date": start_date, "end_date": end_date,
            "metric_note": "count 为该次考试中排名落在 rank_min 到 rank_max 内的人数；排名优先用 xueji_rank，无学籍排名时用 grade_rank。",
            "series": series,
        }
    finally:
        db.close()


def rank_range_filter_tool(
    exam_id: int,
    metric: str,
    rank_min: int = 1,
    rank_max: int = 100,
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
) -> dict[str, Any]:
    """单次考试按指标和年级排名区间筛选学生。teaching_class_id/class_label 限定教学班成员。"""
    from app.analysis.rank_metrics import rank_range_filter

    return rank_range_filter(
        exam_id=exam_id,
        metric=metric,
        rank_min=rank_min,
        rank_max=rank_max,
        teaching_class_id=_resolve_tc_id(teaching_class_id, class_label, exam_id=exam_id),
        class_num=class_num,
    )


def rank_frequency_stat_tool(
    grade: int,
    metric: str,
    exam_ids: Optional[list[int]] = None,
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
    recent_count: int = 5,
) -> dict[str, Any]:
    """多场考试按排名/百分位/精确等级分统计学生频次。teaching_class_id/class_label 限定教学班成员。"""
    from app.analysis.rank_metrics import rank_frequency_stats

    return rank_frequency_stats(
        grade=grade,
        metric=metric,
        exam_ids=exam_ids,
        teaching_class_id=_resolve_tc_id(teaching_class_id, class_label, grade=grade),
        class_num=class_num,
        recent_count=recent_count,
    )


def student_homework_summary(student_id: Optional[str] = None, name: Optional[str] = None) -> dict[str, Any]:
    """某生本学期作业概况：缺交总数、按科目分布、迟到/请假次数、当前连续缺交预警。"""
    from app.db.models import get_db
    from app.homework import service

    db = next(get_db())
    try:
        return service.student_summary(db, student_id=student_id, name=name)
    finally:
        db.close()


def student_notes(student_id: Optional[str] = None, name: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
    """读取某生的成长/谈话档案（谈话、观察、家访、家长沟通、奖惩等班主任记录），
    用于结合成绩与缺交起草谈话提纲或家长沟通稿。姓名多义时返回候选。"""
    from app.db.models import ClassRoster, StudentNote, get_db

    db = next(get_db())
    try:
        roster_q = db.query(ClassRoster)
        if student_id:
            roster_q = roster_q.filter(ClassRoster.student_id == student_id)
        elif name:
            roster_q = roster_q.filter(ClassRoster.name.like(f"%{name}%"))
        else:
            return {"error": "需提供 student_id 或 name"}
        matches = roster_q.limit(10).all()
        if not matches:
            return {"error": "未找到学生", "student_id": student_id, "name": name}
        if len(matches) > 1 and not student_id:
            return {
                "error": "匹配到多个学生，请指定学号",
                "candidates": [{"student_id": m.student_id, "name": m.name} for m in matches],
            }
        roster = matches[0]
        rows = (
            db.query(StudentNote)
            .filter(StudentNote.student_id == roster.student_id)
            .order_by(StudentNote.date.desc(), StudentNote.id.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return {
            "student": {"student_id": roster.student_id, "name": roster.name},
            "notes": [
                {
                    "date": n.date,
                    "category": n.category,
                    "content": n.content,
                    "follow_up": n.follow_up,
                    "follow_up_done": bool(n.follow_up_done),
                }
                for n in rows
            ],
            "note": "这些是班主任的私密档案，仅用于辅助本人工作，措辞需稳妥、尊重学生。",
        }
    finally:
        db.close()


def class_homework_ranking(
    class_num: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10,
) -> dict[str, Any]:
    """班级缺交排行（排除被标记为不统计的学生）。不传日期时用当前学期区间。"""
    from app.db.models import get_db
    from app.homework import service

    db = next(get_db())
    try:
        sem = service.get_semester(db)
        start = start_date or sem["semester_start"]
        end = end_date or sem["semester_end"]
        result = service.rankings(db, start, end, limit=limit)
        return {
            "class_num": class_num,
            "semester": {"start": start, "end": end},
            "rankings": [
                {"name": n, "miss_count": c}
                for n, c in zip(result["names"], result["counts"])
            ],
            "note": "miss_count 为该区间缺交次数；作业数据仅含缺交/请假/迟到，不代表完成质量。",
        }
    finally:
        db.close()


def homework_grade_correlation(
    teaching_class_id: Optional[int] = None,
    exam_id: Optional[int] = None,
    subject: Optional[str] = None,
) -> dict[str, Any]:
    """作业缺交 × 当前学科成绩联动（单学科化）。

    - 学科由后端教师上下文解析，前端/请求不可选择其他学科或总分类型。
    - X 为所有作业种类的缺交次数；Y 为当前学科最近合法考试的 subject_rank（按班
      排名，越小越好）。无当前学科成绩的合法成员 subject_rank=null。
    - 附带 subject_correlation（仅当前学科缺交 × 当前学科名次 皮尔逊相关）。
    exam_id 不填取最近一场。"""
    from app.db.models import get_db
    from app.homework import service

    db = next(get_db())
    try:
        result = service.grade_correlation(
            db, teaching_class_id=teaching_class_id, exam_id=exam_id,
            subject=subject,
        )
        result["subject_correlation"] = service.subject_correlation_ranking(
            db, teaching_class_id=teaching_class_id, exam_id=exam_id,
        )["rankings"]
        return result
    finally:
        db.close()


TOOL_FUNCTIONS = {
    "list_exams": list_exams,
    "list_my_classes": list_my_classes,
    "student_lookup": student_lookup,
    "student_exam_detail": student_exam_detail,
    "student_trend": student_trend,
    "student_learning_profile": student_learning_profile,
    "class_trend": class_trend,
    "compare_classes": compare_classes,
    "focus_list": focus_list,
    "subject_weakness": subject_weakness,
    "subject_progress_ranking": subject_progress_ranking,
    "multi_exam_progress_ranking": multi_exam_progress_ranking,
    "band_trend": band_trend,
    "custom_rank_band_trend": custom_rank_band_trend,
    "rank_range_filter": rank_range_filter_tool,
    "rank_frequency_stat": rank_frequency_stat_tool,
    "student_homework_summary": student_homework_summary,
    "class_homework_ranking": class_homework_ranking,
    "homework_grade_correlation": homework_grade_correlation,
    "student_notes": student_notes,
}


def execute_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "render_chart":
        return {"chart": args}
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return {"error": f"未知工具: {name}"}
    return func(**args)

def to_openai_tools(tools: list[dict]) -> list[dict]:
    """把 Anthropic 风格 tools 转成 OpenAI function-calling 格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


TOOLS = [
    {
        "name": "list_exams",
        "description": "罗列已建档考试",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "year_range": {"type": "array", "items": {"type": "string"}, "description": "年份范围如['2024','2025']"},
            },
        },
    },
    {
        "name": "list_my_classes",
        "description": "列出我任教的教学班（高一=行政班数字、高二/三可为走班名如『物A1』）。当用户提到具体班级名时，先调用本工具把名字解析成 teaching_class_id，再传给其他工具。返回每班的 teaching_class_id、grade、label、kind、member_count。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)；不填返回全部年级"},
            },
        },
    },
    {
        "name": "student_lookup",
        "description": "按姓名/学号定位学生",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "student_id": {"type": "string"},
            },
        },
    },
    {
        "name": "student_exam_detail",
        "description": "某生某次考试的完整成绩",
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string"},
                "exam_id": {"type": "integer"},
            },
            "required": ["student_id", "exam_id"],
        },
    },
    {
        "name": "student_trend",
        "description": "跨次趋势（自动判断是否跨学年）",
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string"},
                "total_type": {"type": "string"},
                "exam_ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["student_id"],
        },
    },
    {
        "name": "student_learning_profile",
        "description": "分析某个学生的整体学习情况，返回总分趋势、最新优势/薄弱科目、进步/退步科目、各科历史和按考试展开的完整成绩表。加三学科指物理、化学、生物、政治、历史、地理六科；available=false 表示未参考或无有效成绩。",
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "description": "学号；如果当前页面上下文有 student_id，应优先使用"},
                "name": {"type": "string", "description": "学生姓名；姓名不唯一时工具会返回候选学生"},
                "subject_limit": {"type": "integer", "description": "优势/薄弱/进退步科目返回数量，默认5"},
            },
        },
    },
    {
        "name": "class_trend",
        "description": "教学班/班级层的均分或排名时间序列。优先用 teaching_class_id/class_label 指定教学班；不填可用 class_num 指定行政班。",
        "input_schema": {
            "type": "object",
            "properties": {
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 解析班名）"},
                "class_label": {"type": "string", "description": "教学班名（如 1、物A1）"},
                "class_num": {"type": "integer"},
                "metric": {"type": "string"},
                "exam_ids": {"type": "array", "items": {"type": "integer"}},
            },
        },
    },
    {
        "name": "compare_classes",
        "description": "多班同次对比。优先用 teaching_class_ids/class_labels 指定教学班；class_nums 为行政班号回退。",
        "input_schema": {
            "type": "object",
            "properties": {
                "teaching_class_ids": {"type": "array", "items": {"type": "integer"}, "description": "教学班ID列表"},
                "class_labels": {"type": "array", "items": {"type": "string"}, "description": "教学班名列表（如 ['物A1','1']）"},
                "class_nums": {"type": "array", "items": {"type": "integer"}},
                "exam_id": {"type": "integer"},
                "metric": {"type": "string"},
            },
        },
    },
    {
        "name": "focus_list",
        "description": "拉某次考试的重点关注名单",
        "input_schema": {
            "type": "object",
            "properties": {
                "exam_id": {"type": "integer"},
                "category": {"type": "string"},
            },
        },
    },
    {
        "name": "subject_weakness",
        "description": "某次考试的单科薄弱清单（单科百分位比主三门百分位低较多）。teaching_class_id/class_label 限定教学班成员，class_num 限定行政班，都空=全年级。",
        "input_schema": {
            "type": "object",
            "properties": {
                "exam_id": {"type": "integer"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 解析班名）"},
                "class_label": {"type": "string", "description": "教学班名（如 1、物A1）"},
                "class_num": {"type": "integer"},
            },
            "required": ["exam_id"],
        },
    },
    {
        "name": "subject_progress_ranking",
        "description": "按年级和学科找跨考试进步或退步最大的学生，例如“高二语文进步最大的是谁”。默认比较该年级最早和最新考试。高一单科和高二/高三语数英按百分位，高二/高三加三学科（物理、化学、生物、政治、历史、地理）按等级分。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "subject": {"type": "string", "description": "学科名，如语文、数学、英语、物理、化学、生物、政治、历史、地理"},
                "start_exam_id": {"type": "integer", "description": "起始考试ID；不填则使用该年级最早考试"},
                "end_exam_id": {"type": "integer", "description": "结束考试ID；不填则使用该年级最新考试"},
                "limit": {"type": "integer", "description": "返回人数，默认10，最多50"},
                "direction": {"type": "string", "description": "progress=进步最大，regression=退步最大"},
            },
            "required": ["grade", "subject"],
        },
    },
    {
        "name": "multi_exam_progress_ranking",
        "description": "把最近N次或指定多场考试合起来，按单科/主三门/五门等指标分析全体学生进步、退步和趋势排行。适合回答“最近几次谁进步最大”“两次考试单科和总分进退步”“三门五门趋势最好的是谁”。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要分析的指标，如['语文','数学','英语','主三门','五门']；加三学科指物理、化学、生物、政治、历史、地理六科；不填时按年级返回常用总分和全部学科",
                },
                "exam_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "指定参与分析的考试ID；不填则使用最近 recent_count 次",
                },
                "recent_count": {"type": "integer", "description": "最近几次考试，默认5；用户说最近两次时传2"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 把『物A1班/1班』等名字解析成ID）；不填=全年级"},
                "class_label": {"type": "string", "description": "教学班名（如 1、物A1），与 teaching_class_id 二选一"},
                "class_num": {"type": "integer", "description": "只看某个班；不填表示全年级"},
                "limit": {"type": "integer", "description": "每个指标返回人数，默认10，最多50"},
                "direction": {"type": "string", "description": "progress=进步趋势最大，regression=退步趋势最大"},
                "min_points": {"type": "integer", "description": "每名学生至少需要几次有效记录，默认2；做多场趋势时可设3"},
            },
            "required": ["grade"],
        },
    },
    {
        "name": "band_trend",
        "description": "某年级历次考试的高分段/临界段/薄弱段人数随时间变化趋势。回答“本班高分段人数怎么变”“临界段最近几次趋势”“薄弱段有没有减少”等关于名次段位人数走势的问题。分段口径使用用户当前自定义的设置，返回值含 band_config 说明区间。class_num 不填表示全年级。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 把『物A1班/1班』等名字解析成ID）；不填=全年级"},
                "class_label": {"type": "string", "description": "教学班名（如 1、物A1），与 teaching_class_id 二选一"},
                "class_num": {"type": "integer", "description": "只看某个班；不填表示全年级"},
            },
            "required": ["grade"],
        },
    },
    {
        "name": "custom_rank_band_trend",
        "description": "按用户临时指定的排名阈值或排名区间统计历次考试人数变化。适合回答“350名以内人数如何变化”“前200名有多少人”“300-450名之间人数趋势”等，不受高分段/临界段/薄弱段固定配置限制。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "rank_min": {"type": "integer", "description": "排名区间下界，默认1；例如前350名传1"},
                "rank_max": {"type": "integer", "description": "排名区间上界；例如350名以内传350"},
                "total_type": {"type": "string", "description": "总分类型，默认主三门；可传主三门、五门、九门、3+3等"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 把『物A1班/1班』等名字解析成ID）；不填=全年级"},
                "class_label": {"type": "string", "description": "教学班名（如 1、物A1），与 teaching_class_id 二选一"},
                "class_num": {"type": "integer", "description": "只看某个班；不填表示全年级"},
                "start_date": {"type": "string", "description": "起始日期，可传YYYY、YYYY-MM或YYYY-MM-DD；例如2026年以来传2026"},
                "end_date": {"type": "string", "description": "结束日期，可传YYYY、YYYY-MM或YYYY-MM-DD"},
            },
            "required": ["grade", "rank_max"],
        },
    },
    {
        "name": "rank_range_filter",
        "description": "按单次考试、指标和年级排名区间筛选学生。适合回答“这次考试数学年级前100有哪些人”“主三门排名300到350有哪些学生”。高一可查9门单科、主三门、五门；高二/高三可查语数英单科、主三门、3+3。metric格式如 subject:数学 或 total:主三门。",
        "input_schema": {
            "type": "object",
            "properties": {
                "exam_id": {"type": "integer", "description": "考试ID"},
                "metric": {"type": "string", "description": "指标，格式如 subject:语文、total:主三门、total:五门、total:3+3"},
                "rank_min": {"type": "integer", "description": "年级排名下界，默认1"},
                "rank_max": {"type": "integer", "description": "年级排名上界，默认100"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 把『物A1班/1班』等名字解析成ID）；不填=全年级"},
                "class_label": {"type": "string", "description": "教学班名（如 1、物A1），与 teaching_class_id 二选一"},
                "class_num": {"type": "integer", "description": "只看某个班；不填表示全年级"},
            },
            "required": ["exam_id", "metric"],
        },
    },
    {
        "name": "rank_frequency_stat",
        "description": "统计多场考试里每名学生落入各排名区间/百分位区间/精确等级分的次数。适合回答“最近5次主三门排名频次”“语文前20%次数”“物理等级分频次”。高一9门单科按百分位，主三门/五门按40名一档；高二/高三语数英按百分位，+3选科用 subject_grade:物理 这类等级分指标，并按70、67、64、61、58、55、52、49、46、43、40精确等级分统计，主三门/3+3按40名一档。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "metric": {"type": "string", "description": "指标，格式如 subject:语文、subject_grade:物理、total:主三门、total:五门、total:3+3"},
                "exam_ids": {"type": "array", "items": {"type": "integer"}, "description": "参与统计的考试ID；不填则取最近 recent_count 次"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 把『物A1班/1班』等名字解析成ID）；不填=全年级"},
                "class_label": {"type": "string", "description": "教学班名（如 1、物A1），与 teaching_class_id 二选一"},
                "class_num": {"type": "integer", "description": "只看某个班；不填表示全年级"},
                "recent_count": {"type": "integer", "description": "未指定考试ID时取最近几次，默认5"},
            },
            "required": ["grade", "metric"],
        },
    },
    {
        "name": "student_homework_summary",
        "description": "某个学生本学期的作业（缺交）概况：缺交总次数、按科目分布、迟到/请假次数、当前连续缺交预警。回答“某某作业完成情况怎么样”“他缺交多吗”“作业和成绩有没有关系”时先用本工具拿作业侧数据，再结合 student_learning_profile 的成绩。作业数据仅含缺交/请假/迟到，不代表完成质量。",
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "description": "学号；页面上下文有 student_id 时优先使用"},
                "name": {"type": "string", "description": "学生姓名；姓名不唯一时返回候选"},
            },
        },
    },
    {
        "name": "class_homework_ranking",
        "description": "班级缺交排行榜，回答“这学期谁缺交最多”“缺交前几名是谁”。默认当前学期区间，已排除被标记为不统计的学生。",
        "input_schema": {
            "type": "object",
            "properties": {
                "class_num": {"type": "integer", "description": "行政班号；不填=我教的所有班并集（全花名册）"},
                "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD；不填用学期开始"},
                "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD；不填用学期结束"},
                "limit": {"type": "integer", "description": "返回人数，默认10"},
            },
        },
    },
    {
        "name": "homework_grade_correlation",
        "description": "把「缺交」和「当前学科成绩」放在一起，回答“作业缺交多的学生当前学科成绩是不是更差”“缺交和名次有没有关系”。X 为所有作业种类的缺交次数，Y 为当前学科最近合法考试的 subject_rank（按班排名，越小越好）。附带 subject_correlation（当前学科缺交 × 当前学科名次 皮尔逊相关，r 越大表示缺交越拖成绩）。学科由后端教师上下文解析，不可选择其他学科或总分。exam_id 不填取最近一场。作业数据仅反映缺交，不代表完成质量。",
        "input_schema": {
            "type": "object",
            "properties": {
                "teaching_class_id": {"type": "integer", "description": "教学班 id；不填=当前任教学科所有教学班成员并集"},
                "exam_id": {"type": "integer", "description": "考试ID；不填取最近一场"},
            },
        },
    },
    {
        "name": "student_notes",
        "description": "读取某个学生的成长/谈话档案（班主任记录的谈话、观察、家访、家长沟通、奖惩等）。当用户要『结合最近谈话/家访情况』『帮我准备和某某的谈话提纲』『写给某某家长的沟通稿』时调用，结合 student_learning_profile 与 student_homework_summary 一起用。内容为私密档案，措辞需稳妥尊重。",
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "description": "学号；页面上下文有 student_id 时优先使用"},
                "name": {"type": "string", "description": "学生姓名；姓名不唯一时返回候选"},
                "limit": {"type": "integer", "description": "返回最近几条，默认20"},
            },
        },
    },
]
