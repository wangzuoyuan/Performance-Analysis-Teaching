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
#
# 阶段6A：chat 工具全部单学科化。范围解析不再有全年级/行政班回退：
# - 默认 scope = 当前教师唯一任教学科的全部教学班成员去重并集；
# - 显式 teaching_class_id 必须属于当前教师、当前 subject 和请求年级；
# - 越权（他科班）/跨年级 拒绝，不回退。

_FORBIDDEN_CLASS_PARAMS_MSG = "单学科化后不再支持 class_num / class_label，请使用 teaching_class_id"


def _reject_legacy_class_params(class_label=None, class_num=None):
    """禁止遗留跨口径入参（非空必须明确拒绝，不能旁路）。"""
    if class_label is not None or class_num is not None:
        raise ValueError(_FORBIDDEN_CLASS_PARAMS_MSG)


def _resolve_class_scope(
    teaching_class_id: Optional[int] = None,
    class_label: Optional[str] = None,
    class_num: Optional[int] = None,
    grade: Optional[int] = None,
    exam_id: Optional[int] = None,
):
    """把教学班参数解析成 (SingleSubjectContext, grade)。

    始终基于 resolve_single_subject_context（当前教师唯一任教学科 + 合法教学班成员）。
    class_label/class_num 非空 → ValueError（不再旁路）。
    grade 为 None 且给了 exam_id 时用该考试年级解析。
    """
    from app.analysis.single_subject_metrics import resolve_single_subject_context
    from app.db.models import Exam

    _reject_legacy_class_params(class_label=class_label, class_num=class_num)

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
        ctx = resolve_single_subject_context(db, teaching_class_id=teaching_class_id, grade=g)
        return ctx, g
    finally:
        db.close()


def _resolve_class_scope_by_grade(
    teaching_class_id: Optional[int],
    grade: Optional[int],
):
    """范围解析（按 grade，不依赖 exam_id）。返回 SingleSubjectContext。"""
    from app.analysis.single_subject_metrics import resolve_single_subject_context

    db = _db()
    try:
        return resolve_single_subject_context(db, teaching_class_id=teaching_class_id, grade=grade)
    finally:
        db.close()


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
    """列出当前任教学科在合法成员中有真实分数的考试。

    单学科化：只返回当前教师任教学科在教学班成员范围内有 raw_score 或
    grade_score 的考试；最近考试按 exam_date desc, id desc。
    """
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject
    from app.db.models import Exam

    db = _db()
    try:
        subject = resolve_teaching_subject(db)
        ctx = resolve_single_subject_context(db, grade=grade)
        valid_ids = valid_exam_ids_for_subject(db, subject, ctx.member_ids, grade=grade)
        if not valid_ids:
            return []
        q = (
            db.query(Exam)
            .filter(Exam.id.in_(valid_ids))
            .order_by(Exam.exam_date.desc(), Exam.id.desc())
        )
        if grade:
            q = q.filter(Exam.grade == grade)
        exams = q.all()
        return [
            {"id": e.id, "name": e.name, "grade": e.grade,
             "exam_date": e.exam_date, "teaching_subject": subject}
            for e in exams
        ]
    finally:
        db.close()

def student_lookup(name: Optional[str] = None, student_id: Optional[str] = None) -> list:
    """按姓名/学号定位学生（限当前任教学科教学班成员范围）。"""
    from app.db.models import SubjectScore
    from app.analysis.scope import all_my_member_ids
    from app.teaching.subject import resolve_teaching_subject

    db = _db()
    try:
        subject = resolve_teaching_subject(db)
        member_ids = all_my_member_ids(db)
        query = (
            db.query(SubjectScore.student_id, SubjectScore.name)
            .filter(
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(member_ids),
            )
            .distinct()
        )
        if student_id:
            query = query.filter(SubjectScore.student_id == student_id)
        if name:
            query = query.filter(SubjectScore.name.like(f"%{name}%"))
        results = query.all()
        return [
            {"student_id": r[0], "name": r[1]}
            for r in results
        ]
    finally:
        db.close()

def student_exam_detail(student_id: str, exam_id: int) -> dict:
    """某生某次考试的当前学科成绩（单学科化）。

    只返回当前任教学科一科，不含 totals/其他学科；附 subject_rank（按班
    competition ranking）。学生必须在合法 scope（否则 ValueError）。
    空分行（无 raw/grade_score）不当作有效成绩。
    """
    from app.db.models import Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
    )

    db = _db()
    try:
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise ValueError("考试不存在")
        ctx = resolve_single_subject_context(
            db, teaching_class_id=None, grade=exam.grade,
        )
        if student_id not in ctx.member_ids:
            raise ValueError(
                f"学生 {student_id} 不在当前任教学科教学班成员范围内"
            )
        subject = ctx.subject
        score = (
            db.query(SubjectScore)
            .filter(
                SubjectScore.exam_id == exam_id,
                SubjectScore.student_id == student_id,
                SubjectScore.subject == subject,
            )
            .first()
        )
        # subject_rank（按班 competition ranking）
        rank_map, _rows = compute_subject_rank_contextual(
            db, ctx, exam_id, exam_grade=exam.grade,
        )
        class_label, tc_id = label_for_student(ctx, student_id, return_tc_id=True)

        use_grade_score = exam.grade in (2, 3) and subject in ELECTIVE_SUBJECTS
        score_basis = "grade_score" if use_grade_score else "raw_score"

        if score is None or not _has_subject_score(score):
            return {
                "teaching_subject": subject,
                "teaching_class_id": tc_id,
                "scope": "teaching_class" if tc_id is not None else "all",
                "score_basis": score_basis,
                "student_id": student_id,
                "exam_id": exam_id,
                "exam": {
                    "id": exam.id, "name": exam.name,
                    "grade": exam.grade, "exam_date": exam.exam_date,
                },
                "subject_score": None,
                "subject_rank": rank_map.get(student_id),
                "class_label": class_label,
            }

        payload = _subject_score_payload(score, exam)
        return {
            "teaching_subject": subject,
            "teaching_class_id": tc_id,
            "scope": "teaching_class" if tc_id is not None else "all",
            "score_basis": score_basis,
            "student_id": student_id,
            "exam_id": exam_id,
            "subject_score": {
                "subject": score.subject,
                "raw_score": score.raw_score,
                "grade_score": score.grade_score,
                "grade_percentile": score.grade_percentile,
                "subject_rank": rank_map.get(student_id),
            },
            "subject_rank": rank_map.get(student_id),
            "class_label": class_label,
        }
    finally:
        db.close()


def student_trend(student_id: str, exam_ids: Optional[list[int]] = None) -> dict:
    """某生当前学科跨次趋势（单学科化）。

    只生成当前任教学科历史，删除 total_type / main_total_trend。
    每个 series 点含 raw_score / grade_score / grade_percentile / subject_rank。
    学生必须在合法 scope（否则 ValueError）。高二/三选考用 grade_score 判断趋势，
    其他单科用 percentile，沿用阶段3/4 既有规则。
    """
    from app.db.models import Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject

    db = _db()
    try:
        subject = resolve_teaching_subject(db)
        ctx = resolve_single_subject_context(db)
        if student_id not in ctx.member_ids:
            raise ValueError(
                f"学生 {student_id} 不在当前任教学科教学班成员范围内"
            )
        valid_ids = valid_exam_ids_for_subject(db, subject, ctx.member_ids)
        if exam_ids:
            selected = [eid for eid in exam_ids if eid in valid_ids]
        else:
            selected = sorted(valid_ids)
        if not selected:
            return {
                "teaching_subject": subject,
                "student_id": student_id,
                "series": [],
                "score_basis": "grade_score" if False else "raw_score",
            }
        exams = (
            db.query(Exam)
            .filter(Exam.id.in_(selected))
            .order_by(Exam.grade, Exam.exam_date, Exam.id)
            .all()
        )
        # 判断 score_basis：用最后一场考试的年级/学科
        last_exam = exams[-1]
        use_grade_score = last_exam.grade in (2, 3) and subject in ELECTIVE_SUBJECTS
        score_basis = "grade_score" if use_grade_score else "raw_score"

        series = []
        for exam in exams:
            score = (
                db.query(SubjectScore)
                .filter(
                    SubjectScore.exam_id == exam.id,
                    SubjectScore.student_id == student_id,
                    SubjectScore.subject == subject,
                )
                .first()
            )
            if score is None or not _has_subject_score(score):
                continue
            rank_map, _rows = compute_subject_rank_contextual(
                db, ctx, exam.id, exam_grade=exam.grade,
            )
            class_label, tc_id = label_for_student(ctx, student_id, return_tc_id=True)
            series.append({
                "exam_id": exam.id,
                "exam_name": exam.name,
                "exam_date": exam.exam_date,
                "grade": exam.grade,
                "raw_score": score.raw_score,
                "grade_score": score.grade_score,
                "grade_percentile": score.grade_percentile,
                "subject_rank": rank_map.get(student_id),
                "class_label": class_label,
            })
        return {
            "teaching_subject": subject,
            "teaching_class_id": label_for_student(ctx, student_id, return_tc_id=True)[1],
            "scope": "all",
            "score_basis": score_basis,
            "student_id": student_id,
            "series": series,
        }
    finally:
        db.close()


def student_learning_profile(
    student_id: Optional[str] = None,
    name: Optional[str] = None,
    subject_limit: int = 5,
) -> dict[str, Any]:
    """学生当前学科学习画像（单学科化）。

    只生成当前任教学科历史，删除 total_type / main_total_trend /
    latest_subjects / strengths / weaknesses / progress_subjects /
    regression_subjects（多学科强弱项）。
    保留 series（当前学科跨次趋势，含 subject_rank）。
    学生必须在合法 scope。
    """
    from app.db.models import Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject

    db = _db()
    try:
        subject = resolve_teaching_subject(db)
        ctx = resolve_single_subject_context(db)
        # 学生定位（限合法成员范围内、当前学科）
        q = (
            db.query(SubjectScore.student_id, SubjectScore.name)
            .filter(
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(ctx.member_ids),
            )
            .distinct()
        )
        if student_id:
            q = q.filter(SubjectScore.student_id == student_id)
        if name:
            q = q.filter(SubjectScore.name.like(f"%{name}%"))
        students = q.limit(10).all()
        if not students:
            return {"error": "未在当前任教学科范围内找到该学生",
                    "student_id": student_id, "name": name,
                    "teaching_subject": subject}
        if len(students) > 1 and not student_id:
            return {
                "error": "匹配到多个学生，请指定学号",
                "teaching_subject": subject,
                "candidates": [{"student_id": r[0], "name": r[1]} for r in students],
            }
        resolved_student_id = students[0][0]
        resolved_name = students[0][1] or resolved_student_id

        valid_ids = valid_exam_ids_for_subject(db, subject, ctx.member_ids)
        exams = (
            db.query(Exam)
            .filter(Exam.id.in_(valid_ids))
            .order_by(Exam.grade, Exam.exam_date, Exam.id)
            .all()
        )
        last_exam = exams[-1] if exams else None
        use_grade_score = bool(last_exam and last_exam.grade in (2, 3)
                               and subject in ELECTIVE_SUBJECTS)
        score_basis = "grade_score" if use_grade_score else "raw_score"

        series = []
        for exam in exams:
            score = (
                db.query(SubjectScore)
                .filter(
                    SubjectScore.exam_id == exam.id,
                    SubjectScore.student_id == resolved_student_id,
                    SubjectScore.subject == subject,
                )
                .first()
            )
            if score is None or not _has_subject_score(score):
                continue
            rank_map, _rows = compute_subject_rank_contextual(
                db, ctx, exam.id, exam_grade=exam.grade,
            )
            class_label, tc_id = label_for_student(
                ctx, resolved_student_id, return_tc_id=True,
            )
            series.append({
                "exam_id": exam.id,
                "exam_name": exam.name,
                "exam_date": exam.exam_date,
                "grade": exam.grade,
                "raw_score": score.raw_score,
                "grade_score": score.grade_score,
                "grade_percentile": score.grade_percentile,
                "subject_rank": rank_map.get(resolved_student_id),
                "class_label": class_label,
            })

        # 趋势变化（首末点）
        trend_change = None
        if len(series) >= 2:
            first, latest = series[0], series[-1]
            if use_grade_score:
                if first["grade_score"] is not None and latest["grade_score"] is not None:
                    trend_change = round(latest["grade_score"] - first["grade_score"], 2)
            else:
                if first["grade_percentile"] is not None and latest["grade_percentile"] is not None:
                    # 百分位降低=进步
                    trend_change = round(first["grade_percentile"] - latest["grade_percentile"], 4)

        return {
            "teaching_subject": subject,
            "teaching_class_id": label_for_student(
                ctx, resolved_student_id, return_tc_id=True,
            )[1],
            "scope": "all",
            "score_basis": score_basis,
            "student": {
                "student_id": resolved_student_id,
                "name": resolved_name,
                "current_grade": last_exam.grade if last_exam else None,
                "latest_exam": {
                    "id": last_exam.id, "name": last_exam.name,
                    "grade": last_exam.grade, "exam_date": last_exam.exam_date,
                } if last_exam else None,
            },
            "series": series,
            "trend_change": trend_change,
            "metric_note": (
                f"score_basis={score_basis}；高二/三选考学科用 grade_score 判断趋势，"
                "其他单科用 grade_percentile（越小越靠前）。subject_rank 为按班 "
                "competition ranking（同分同名次）。trend_change 为正表示进步。"
            ),
            "analysis_boundary": "仅基于已导入考试成绩，不能推断课堂表现、作业习惯或家庭因素。",
        }
    finally:
        db.close()


def class_trend(
    teaching_class_id: Optional[int] = None,
    exam_ids: Optional[list[int]] = None,
) -> dict[str, Any]:
    """教学班当前学科均分/排名时间序列（单学科化）。

    不再读 ClassAverage.total_averages；按当前学科 subject_rank 均值或
    raw_score 均值现算。teaching_class_id 可选（默认全部当前学科教学班）。
    """
    from app.db.models import Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        group_members_by_class,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject

    _reject_legacy_class_params()

    db = _db()
    try:
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(db, teaching_class_id=teaching_class_id)
        valid_ids = valid_exam_ids_for_subject(db, subject, ctx.member_ids)
        q = db.query(Exam).filter(Exam.id.in_(valid_ids)).order_by(Exam.grade, Exam.exam_date, Exam.id)
        if exam_ids:
            q = q.filter(Exam.id.in_(exam_ids))
        exams = q.all()

        last_exam = exams[-1] if exams else None
        use_grade_score = bool(last_exam and last_exam.grade in (2, 3)
                               and subject in ELECTIVE_SUBJECTS)
        score_basis = "grade_score" if use_grade_score else "raw_score"

        series = []
        for exam in exams:
            rank_map, rows_by_sid = compute_subject_rank_contextual(
                db, ctx, exam.id, exam_grade=exam.grade,
            )
            groups = group_members_by_class(ctx)
            # 计算各班均分（score_basis）和均排名
            class_values = {}
            for tc_id, member_set in groups.items():
                member_rows = [rows_by_sid[sid] for sid in member_set if sid in rows_by_sid]
                if not member_rows:
                    continue
                ranks = [rank_map.get(sid) for sid in member_set if sid in rank_map]
                if use_grade_score:
                    vals = [r.grade_score for r in member_rows if r.grade_score is not None]
                else:
                    vals = [r.raw_score for r in member_rows if r.raw_score is not None]
                avg_score = round(sum(vals) / len(vals), 1) if vals else None
                avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else None
                class_values[ctx.class_labels.get(tc_id)] = {
                    "avg_score": avg_score,
                    "avg_rank": avg_rank,
                    "count": len(member_rows),
                }
            series.append({
                "exam_id": exam.id,
                "exam_name": exam.name,
                "exam_date": exam.exam_date,
                "class_values": class_values,
            })
        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "score_basis": score_basis,
            "series": series,
        }
    finally:
        db.close()


def compare_classes(
    teaching_class_id: Optional[int] = None,
    exam_id: int = None,
) -> dict[str, Any]:
    """多班同次对比（单学科化）。

    不再读 ClassAverage.total_averages；按当前学科按班均分/均排名现算。
    teaching_class_id 可选；默认对比当前学科所有教学班。
    """
    from app.db.models import Exam
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        group_members_by_class,
    )
    from app.teaching.subject import resolve_teaching_subject

    _reject_legacy_class_params()

    db = _db()
    try:
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(db, teaching_class_id=teaching_class_id)
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise ValueError("考试不存在")
        use_grade_score = exam.grade in (2, 3) and subject in ELECTIVE_SUBJECTS
        score_basis = "grade_score" if use_grade_score else "raw_score"

        rank_map, rows_by_sid = compute_subject_rank_contextual(
            db, ctx, exam.id, exam_grade=exam.grade,
        )
        groups = group_members_by_class(ctx)
        rows = []
        for tc_id, member_set in groups.items():
            member_rows = [rows_by_sid[sid] for sid in member_set if sid in rows_by_sid]
            if not member_rows:
                continue
            ranks = [rank_map.get(sid) for sid in member_set if sid in rank_map]
            if use_grade_score:
                vals = [r.grade_score for r in member_rows if r.grade_score is not None]
            else:
                vals = [r.raw_score for r in member_rows if r.raw_score is not None]
            avg_score = round(sum(vals) / len(vals), 1) if vals else None
            avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else None
            rows.append({
                "teaching_class_id": tc_id,
                "class_label": ctx.class_labels.get(tc_id),
                "avg_score": avg_score,
                "avg_rank": avg_rank,
                "count": len(member_rows),
            })
        rows.sort(key=lambda r: (r["avg_rank"] is None, r["avg_rank"] or 0))
        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "score_basis": score_basis,
            "exam": {
                "id": exam.id, "name": exam.name,
                "grade": exam.grade, "exam_date": exam.exam_date,
            },
            "rows": rows,
        }
    finally:
        db.close()


def focus_list(
    exam_id: int,
    teaching_class_id: Optional[int] = None,
    category: Optional[str] = None,
) -> dict[str, Any]:
    """重点关注名单（单学科化）。

    基于 subject_rank + band_config（临界段/薄弱段），不查 TotalScore、不偏科。
    学生必须在合法 scope。
    """
    from app.db.models import Exam
    from app.analysis.config import get_band_config
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
        band_classify,
    )
    from app.teaching.subject import resolve_teaching_subject

    _reject_legacy_class_params()

    db = _db()
    try:
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id,
        )
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise ValueError("考试不存在")
        band_cfg = get_band_config(db)
        rank_map, rows_by_sid = compute_subject_rank_contextual(
            db, ctx, exam.id, exam_grade=exam.grade,
        )
        rows = []
        for sid, sr in rank_map.items():
            issues = band_classify(sr, band_cfg)
            if category:
                issues = [i for i in issues if category in i]
            if not issues:
                continue
            r = rows_by_sid.get(sid)
            class_label, tc_id = label_for_student(ctx, sid, return_tc_id=True)
            rows.append({
                "student_id": sid,
                "name": r.name if r else sid,
                "subject_rank": sr,
                "issues": issues,
                "class_label": class_label,
                "teaching_class_id": tc_id,
            })
        rows.sort(key=lambda row: (row["subject_rank"], row["student_id"]))
        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "exam_id": exam_id,
            "focus_list": rows[:50],
            "band_config": band_cfg,
        }
    finally:
        db.close()


def subject_weakness(
    exam_id: int,
    teaching_class_id: Optional[int] = None,
) -> dict[str, Any]:
    """当前学科薄弱名单（单学科化重定义）。

    不再「单科百分位 vs 主三门百分位」差；改为当前学科 subject_rank 靠后
    的学生（薄弱段，用 band_config.weak_min）。不查 TotalScore。
    """
    from app.db.models import Exam
    from app.analysis.config import get_band_config
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
    )
    from app.teaching.subject import resolve_teaching_subject

    _reject_legacy_class_params()

    db = _db()
    try:
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id,
        )
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise ValueError("考试不存在")
        band_cfg = get_band_config(db)
        rank_map, rows_by_sid = compute_subject_rank_contextual(
            db, ctx, exam.id, exam_grade=exam.grade,
        )
        rows = []
        for sid, sr in rank_map.items():
            if sr < band_cfg["weak_min"]:
                continue
            r = rows_by_sid.get(sid)
            class_label, tc_id = label_for_student(ctx, sid, return_tc_id=True)
            rows.append({
                "student_id": sid,
                "name": r.name if r else sid,
                "subject_rank": sr,
                "raw_score": r.raw_score if r else None,
                "grade_score": r.grade_score if r else None,
                "grade_percentile": r.grade_percentile if r else None,
                "class_label": class_label,
                "teaching_class_id": tc_id,
            })
        rows.sort(key=lambda row: (-row["subject_rank"], row["student_id"]))
        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "exam_id": exam_id,
            "subject_weakness": rows[:50],
            "band_config": band_cfg,
        }
    finally:
        db.close()


def subject_progress_ranking(
    grade: int,
    start_exam_id: Optional[int] = None,
    end_exam_id: Optional[int] = None,
    limit: int = 10,
    direction: str = "progress",
    teaching_class_id: Optional[int] = None,
) -> dict[str, Any]:
    """当前学科跨考试进步/退步排行（单学科化）。

    学科固定为当前任教学科，不接受 subject 参数。
    学生限合法成员范围。高二/三选考用 grade_score，其他单科用 percentile，
    沿用阶段3/4 既有规则。
    """
    from app.db.models import Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        label_for_student,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject

    db = _db()
    try:
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id, grade=grade,
        )
        valid_ids = valid_exam_ids_for_subject(
            db, subject, ctx.member_ids, grade=grade,
        )
        exams_query = (
            db.query(Exam)
            .filter(Exam.grade == grade, Exam.id.in_(valid_ids))
            .order_by(Exam.exam_date, Exam.id)
        )
        exams = exams_query.all()
        if len(exams) < 2 and not (start_exam_id and end_exam_id):
            return {"error": "该年级可比较的考试少于2次",
                    "grade": grade, "teaching_subject": subject, "rows": []}

        exam_by_id = {exam.id: exam for exam in exams}
        if start_exam_id is None:
            start_exam = exams[0]
        else:
            start_exam = exam_by_id.get(start_exam_id)
        if end_exam_id is None:
            end_exam = exams[-1]
        else:
            end_exam = exam_by_id.get(end_exam_id)

        if not start_exam or not end_exam:
            return {"error": "起止考试不存在",
                    "grade": grade, "teaching_subject": subject, "rows": []}
        if start_exam.id == end_exam.id:
            return {"error": "起止考试不能相同",
                    "grade": grade, "teaching_subject": subject, "rows": []}

        start_scores = (
            db.query(SubjectScore)
            .filter(
                SubjectScore.exam_id == start_exam.id,
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(ctx.member_ids),
            )
            .all()
        )
        end_scores = (
            db.query(SubjectScore)
            .filter(
                SubjectScore.exam_id == end_exam.id,
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(ctx.member_ids),
            )
            .all()
        )

        use_grade_score = start_exam.grade in {2, 3} and end_exam.grade in {2, 3} and subject in ELECTIVE_SUBJECTS
        score_basis = "grade_score" if use_grade_score else "raw_score"
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

            class_label, tc_id = label_for_student(ctx, end_score.student_id, return_tc_id=True)
            rows.append({
                "student_id": end_score.student_id,
                "name": end_score.name or start_score.name,
                "class_label": class_label,
                "teaching_class_id": tc_id,
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
            })

        reverse = direction != "regression"
        none_value = float("-inf") if reverse else float("inf")
        rows.sort(
            key=lambda row: (
                row["trend_change"] if row["trend_change"] is not None else none_value,
                row["raw_score_change"] if row["raw_score_change"] is not None else none_value,
            ),
            reverse=reverse,
        )
        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "score_basis": score_basis,
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
    finally:
        db.close()


def multi_exam_progress_ranking(
    grade: int,
    exam_ids: Optional[list[int]] = None,
    recent_count: int = 5,
    teaching_class_id: Optional[int] = None,
    limit: int = 10,
    direction: str = "progress",
    min_points: int = 2,
) -> dict[str, Any]:
    """当前学科多场考试进退步/趋势排行（单学科化）。

    固定当前任教学科单一指标，不接受 metrics / total。学生限合法成员范围。
    高二/三选考用 grade_score，其他单科用 percentile（沿用阶段3/4规则）。
    """
    from app.db.models import Exam, SubjectScore
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        label_for_student,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject

    _reject_legacy_class_params()

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
            "class_label": profile.get("class_label"),
            "teaching_class_id": profile.get("teaching_class_id"),
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

    db = _db()
    try:
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id, grade=grade,
        )
        valid_ids = valid_exam_ids_for_subject(
            db, subject, ctx.member_ids, grade=grade,
        )
        if exam_ids:
            exams = (
                db.query(Exam)
                .filter(Exam.id.in_(exam_ids), Exam.grade == grade, Exam.id.in_(valid_ids))
                .order_by(Exam.exam_date, Exam.id)
                .all()
            )
        else:
            all_valid = (
                db.query(Exam)
                .filter(Exam.id.in_(valid_ids), Exam.grade == grade)
                .order_by(Exam.exam_date, Exam.id)
                .all()
            )
            count = max(2, min(recent_count or 5, 12))
            exams = all_valid[-count:]

        if len(exams) < 2:
            return {"error": "该年级可比较的考试少于2次",
                    "grade": grade, "teaching_subject": subject, "rows": []}

        exam_ids_selected = [exam.id for exam in exams]
        exam_payload = [
            {"id": exam.id, "name": exam.name, "exam_date": exam.exam_date}
            for exam in exams
        ]
        exam_name_by_id = {exam.id: exam.name for exam in exams}

        use_grade_score = grade in (2, 3) and subject in ELECTIVE_SUBJECTS
        score_basis = "grade_score" if use_grade_score else "raw_score"
        value_field = "grade_score" if use_grade_score else "grade_percentile"
        lower_is_better = not use_grade_score

        subject_rows = (
            db.query(SubjectScore)
            .filter(
                SubjectScore.exam_id.in_(exam_ids_selected),
                SubjectScore.subject == subject,
                SubjectScore.student_id.in_(ctx.member_ids),
            )
            .all()
        )
        # 按学生 + 考试构建趋势点
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in subject_rows:
            value = row.grade_score if use_grade_score else row.grade_percentile
            if value is None:
                continue
            grouped.setdefault(row.student_id, []).append({
                "exam_id": row.exam_id,
                "exam_name": exam_name_by_id.get(row.exam_id, str(row.exam_id)),
                "value": value,
                "value_field": value_field,
                "raw_score": row.raw_score,
                "grade_score": row.grade_score,
                "grade_percentile": row.grade_percentile,
            })

        metric_rows = []
        for student_id, points in grouped.items():
            ordered_points = sorted(points, key=lambda point: exam_ids_selected.index(point["exam_id"]))
            class_label, tc_id = label_for_student(ctx, student_id, return_tc_id=True)
            # name 取自行
            name = next((r.name for r in subject_rows if r.student_id == student_id), None)
            profile = {
                "name": name or student_id,
                "class_label": class_label,
                "teaching_class_id": tc_id,
            }
            row = build_row(student_id, subject, "subject", value_field, lower_is_better, ordered_points, profile)
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

        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "score_basis": score_basis,
            "grade": grade,
            "direction": direction,
            "exams": exam_payload,
            "recent_count": len(exams),
            "metric": subject,
            "metric_kind": "subject",
            "value_field": value_field,
            "lower_is_better": lower_is_better,
            "rows": metric_rows[: max(1, min(limit, 50))],
            "metric_note": (
                "trend_score 综合首末变化和多点线性趋势；正数表示进步，负数表示退步。"
                "高二/三选考单科用等级分（grade_score），其他单科用年级百分位"
                "（grade_percentile，越小越靠前）。"
            ),
        }
    finally:
        db.close()


def band_trend(
    grade: int,
    teaching_class_id: Optional[int] = None,
) -> dict[str, Any]:
    """某年级历次考试当前学科高分段/临界段/薄弱段人数趋势（单学科化）。

    基于 subject_rank + band_config（按班 competition ranking），不查 TotalScore。
    分段口径用当前 band_config。
    """
    from app.analysis.config import get_band_config
    from app.db.models import Exam
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        group_members_by_class,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject

    _reject_legacy_class_params()

    db = _db()
    try:
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id, grade=grade,
        )
        cfg = get_band_config(db)
        valid_ids = valid_exam_ids_for_subject(
            db, subject, ctx.member_ids, grade=grade,
        )
        exams = (
            db.query(Exam)
            .filter(Exam.grade == grade, Exam.id.in_(valid_ids))
            .order_by(Exam.grade, Exam.exam_date, Exam.id).all()
        )
        series = []
        for exam in exams:
            rank_map, _rows = compute_subject_rank_contextual(
                db, ctx, exam.id, exam_grade=exam.grade,
            )
            groups = group_members_by_class(ctx)
            high = crit = weak = 0
            per_class = {}
            for tc_id, member_set in groups.items():
                ph = pc = pw = 0
                for sid in member_set:
                    sr = rank_map.get(sid)
                    if sr is None:
                        continue
                    if 1 <= sr <= cfg["high_score_max"]:
                        high += 1
                        ph += 1
                    if cfg["critical_min"] <= sr <= cfg["critical_max"]:
                        crit += 1
                        pc += 1
                    if sr >= cfg["weak_min"]:
                        weak += 1
                        pw += 1
                per_class[ctx.class_labels.get(tc_id)] = {
                    "high_score": ph, "critical": pc, "weak": pw,
                }
            series.append({
                "exam_name": exam.name, "exam_date": exam.exam_date,
                "high_score": high, "critical": crit, "weak": weak,
                "per_class": per_class,
            })
        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "band_config": cfg,
            "series": series,
            "available_classes": [
                {"teaching_class_id": tc_id, "label": ctx.class_labels.get(tc_id)}
                for tc_id in group_members_by_class(ctx)
            ],
        }
    finally:
        db.close()


def custom_rank_band_trend(
    grade: int,
    rank_max: int,
    rank_min: int = 1,
    teaching_class_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    """按用户临时指定的排名区间统计历次考试当前学科人数变化（单学科化）。

    基于 subject_rank（按班 competition ranking），不查 TotalScore。
    total_type 参数已移除（不再支持）。
    """
    from datetime import date

    from app.db.models import Exam
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject

    _reject_legacy_class_params()

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
        subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id, grade=grade,
        )
        valid_ids = valid_exam_ids_for_subject(
            db, subject, ctx.member_ids, grade=grade,
        )
        exams = (
            db.query(Exam)
            .filter(Exam.grade == grade, Exam.id.in_(valid_ids))
            .order_by(Exam.exam_date, Exam.id).all()
        )
        series = []
        for exam in exams:
            exam_date = normalize_date(exam.exam_date)
            if start and exam_date and exam_date < start:
                continue
            if end and exam_date and exam_date > end:
                continue
            rank_map, _rows = compute_subject_rank_contextual(
                db, ctx, exam.id, exam_grade=exam.grade,
            )
            ranks = [sr for sr in rank_map.values() if sr is not None]
            count = sum(1 for rank in ranks if rank_min <= rank <= rank_max)
            series.append({
                "exam_id": exam.id, "exam_name": exam.name, "exam_date": exam.exam_date,
                "count": count, "ranked_count": len(ranks),
                "rank_min_observed": min(ranks) if ranks else None,
                "rank_max_observed": max(ranks) if ranks else None,
            })
        return {
            "teaching_subject": subject,
            "teaching_class_id": teaching_class_id,
            "scope": "teaching_class" if teaching_class_id is not None else "all",
            "grade": grade,
            "rank_min": rank_min, "rank_max": rank_max,
            "start_date": start_date, "end_date": end_date,
            "metric_note": "count 为该次考试当前学科按班排名（competition ranking）落在 rank_min 到 rank_max 内的人数。",
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
) -> dict[str, Any]:
    """单次考试按指标和年级排名区间筛选学生（单学科化）。

    委托阶段4 rank_metrics.rank_range_filter。class_num/class_label 被拒绝。
    metric 必须与教师任教科目一致。
    """
    from app.analysis.rank_metrics import rank_range_filter

    _reject_legacy_class_params()
    return rank_range_filter(
        exam_id=exam_id,
        metric=metric,
        rank_min=rank_min,
        rank_max=rank_max,
        teaching_class_id=teaching_class_id,
    )


def rank_frequency_stat_tool(
    grade: int,
    metric: str,
    exam_ids: Optional[list[int]] = None,
    teaching_class_id: Optional[int] = None,
    recent_count: int = 5,
) -> dict[str, Any]:
    """多场考试按排名/百分位/精确等级分统计学生频次（单学科化）。

    委托阶段4 rank_metrics.rank_frequency_stats。class_num/class_label 被拒绝。
    metric 必须与教师任教科目一致。
    """
    from app.analysis.rank_metrics import rank_frequency_stats

    _reject_legacy_class_params()
    return rank_frequency_stats(
        grade=grade,
        metric=metric,
        exam_ids=exam_ids,
        teaching_class_id=teaching_class_id,
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
        "description": "罗列当前任教学科在教学班成员范围内有真实分数的考试（最近考试按日期倒序）。",
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
        "description": "按姓名/学号定位学生（限当前任教学科教学班成员范围）。",
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
        "description": "某生某次考试的当前学科成绩（含按班 subject_rank）。学科由后端教师上下文解析，只返回一科。",
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
        "description": "某生当前学科跨次趋势（含 subject_rank），高二/三选考用 grade_score 判断。",
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string"},
                "exam_ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["student_id"],
        },
    },
    {
        "name": "student_learning_profile",
        "description": "学生当前学科学习画像：跨次趋势序列（含 subject_rank）、首末趋势变化。学科由后端解析，不含总分或其他学科。",
        "input_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "description": "学号；如果当前页面上下文有 student_id，应优先使用"},
                "name": {"type": "string", "description": "学生姓名；姓名不唯一时工具会返回候选学生"},
                "subject_limit": {"type": "integer", "description": "兼容保留，不再使用"},
            },
        },
    },
    {
        "name": "class_trend",
        "description": "教学班当前学科均分/排名时间序列。teaching_class_id 指定单班；不填=全部当前学科教学班。",
        "input_schema": {
            "type": "object",
            "properties": {
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 解析班名）"},
                "exam_ids": {"type": "array", "items": {"type": "integer"}},
            },
        },
    },
    {
        "name": "compare_classes",
        "description": "多班同次当前学科对比（均分/均排名）。teaching_class_id 可选；默认对比当前学科所有教学班。",
        "input_schema": {
            "type": "object",
            "properties": {
                "teaching_class_id": {"type": "integer", "description": "教学班ID（可选）"},
                "exam_id": {"type": "integer"},
            },
            "required": ["exam_id"],
        },
    },
    {
        "name": "focus_list",
        "description": "某次考试的当前学科重点关注名单（基于 subject_rank + band_config 的临界段/薄弱段）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "exam_id": {"type": "integer"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（可选）"},
                "category": {"type": "string"},
            },
            "required": ["exam_id"],
        },
    },
    {
        "name": "subject_weakness",
        "description": "当前学科薄弱名单（subject_rank 落在薄弱段的学生）。teaching_class_id 可选。",
        "input_schema": {
            "type": "object",
            "properties": {
                "exam_id": {"type": "integer"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（可选）"},
            },
            "required": ["exam_id"],
        },
    },
    {
        "name": "subject_progress_ranking",
        "description": "当前学科跨考试进步或退步最大的学生排行。学科由后端解析，不接受 subject 参数。默认比较该年级最早和最新合法考试。高二/三选考按等级分，其他单科按百分位。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "start_exam_id": {"type": "integer", "description": "起始考试ID；不填则使用该年级最早合法考试"},
                "end_exam_id": {"type": "integer", "description": "结束考试ID；不填则使用该年级最新合法考试"},
                "limit": {"type": "integer", "description": "返回人数，默认10，最多50"},
                "direction": {"type": "string", "description": "progress=进步最大，regression=退步最大"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（可选）"},
            },
            "required": ["grade"],
        },
    },
    {
        "name": "multi_exam_progress_ranking",
        "description": "把最近N次或指定多场考试合起来，按当前学科分析全体学生进步、退步和趋势排行。学科固定为当前任教学科，不接受 metrics/总分。高二/三选考用等级分，其他单科用年级百分位。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "exam_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "指定参与分析的考试ID；不填则使用最近 recent_count 次",
                },
                "recent_count": {"type": "integer", "description": "最近几次考试，默认5；用户说最近两次时传2"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 把『物A1班/1班』等名字解析成ID）；不填=全部当前学科教学班"},
                "limit": {"type": "integer", "description": "返回人数，默认10，最多50"},
                "direction": {"type": "string", "description": "progress=进步趋势最大，regression=退步趋势最大"},
                "min_points": {"type": "integer", "description": "每名学生至少需要几次有效记录，默认2；做多场趋势时可设3"},
            },
            "required": ["grade"],
        },
    },
    {
        "name": "band_trend",
        "description": "某年级历次考试当前学科的高分段/临界段/薄弱段人数随时间变化趋势（基于 subject_rank）。分段口径使用用户当前自定义的设置，返回值含 band_config 说明区间。teaching_class_id 不填表示全部当前学科教学班。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（用 list_my_classes 把『物A1班/1班』等名字解析成ID）；不填=全部当前学科教学班"},
            },
            "required": ["grade"],
        },
    },
    {
        "name": "custom_rank_band_trend",
        "description": "按用户临时指定的排名区间统计历次考试当前学科人数变化（基于 subject_rank）。适合回答“班内前10名有多少人”“排名5-15名之间人数趋势”等，不受固定段位配置限制。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "rank_min": {"type": "integer", "description": "排名区间下界，默认1"},
                "rank_max": {"type": "integer", "description": "排名区间上界"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（可选）"},
                "start_date": {"type": "string", "description": "起始日期，可传YYYY、YYYY-MM或YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "结束日期，可传YYYY、YYYY-MM或YYYY-MM-DD"},
            },
            "required": ["grade", "rank_max"],
        },
    },
    {
        "name": "rank_range_filter",
        "description": "按单次考试和当前学科按班排名区间筛选学生。学科由后端解析，metric 格式如 subject:数学（必须与任教科目一致）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "exam_id": {"type": "integer", "description": "考试ID"},
                "metric": {"type": "string", "description": "指标，格式如 subject:数学（必须与教师任教科目一致）"},
                "rank_min": {"type": "integer", "description": "班内排名下界，默认1"},
                "rank_max": {"type": "integer", "description": "班内排名上界，默认100"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（可选）"},
            },
            "required": ["exam_id", "metric"],
        },
    },
    {
        "name": "rank_frequency_stat",
        "description": "统计多场考试里每名学生当前学科落入各排名/百分位/精确等级分区间的次数。高二/三选考用 subject_grade:学科 按精确等级分统计，其他单科用 subject:学科 按百分位区间统计。",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade": {"type": "integer", "description": "年级(1=高一,2=高二,3=高三)"},
                "metric": {"type": "string", "description": "指标，格式如 subject:数学 或 subject_grade:物理（必须与教师任教科目一致）"},
                "exam_ids": {"type": "array", "items": {"type": "integer"}, "description": "参与统计的考试ID；不填则取最近 recent_count 次"},
                "teaching_class_id": {"type": "integer", "description": "教学班ID（可选）"},
                "recent_count": {"type": "integer", "description": "未指定考试ID时取最近几次，默认5"},
            },
            "required": ["grade", "metric"],
        },
    },
    {
        "name": "student_homework_summary",
        "description": "某个学生本学期的作业（缺交）概况：缺交总次数、按作业种类分布、迟到/请假次数、当前连续缺交预警。回答“某某作业完成情况怎么样”“他缺交多吗”“作业和成绩有没有关系”时先用本工具拿作业侧数据，再结合 student_learning_profile 的成绩。作业数据仅含缺交/请假/迟到，不代表完成质量。",
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
