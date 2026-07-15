"""作业缺交统计服务层。

集中缺交看板/排行/预警/学生汇总/相关性等查询，供 homework/router.py 的
REST 端点和 chat/tools.py 的对话工具共同复用，避免逻辑重复。口径与原
Flask 应用一致：缺交有效记录 = remark 为空 且 subject != '全科'；默认排除
excluded=1 的学生（指定具体学生查询时不排除）。数据库字段名 subject 为旧名，
当前业务含义是“作业种类”。
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from app.db.models import (
    ClassRoster,
    HomeworkSemester,
    HomeworkRecord,
    SpecialRecord,
    HomeworkSetting,
    TeachingClass,
)
from app.analysis.scope import all_my_member_ids, members_of, student_class_map_multi
from app.homework.parser import (
    ACADEMIC_SUBJECT_HINTS,
    DEFAULT_HOMEWORK_TYPE,
    NEGATIVE_EVALUATIONS,
    POSITIVE_EVALUATIONS,
    SUBJECT_GROUPS,
    normalize_subject,
)

DEFAULT_SEMESTER = {
    "semester_start": "2026-02-17",
    "semester_end": "2026-07-04",
    "semester_name": "",
}


def get_semester(db):
    current = (
        db.query(HomeworkSemester)
        .filter(HomeworkSemester.is_current == 1)
        .order_by(HomeworkSemester.id.desc())
        .first()
    )
    if current:
        return {
            "semester_id": current.id,
            "semester_start": current.start_date,
            "semester_end": current.end_date,
            "semester_name": current.name,
        }
    rows = db.query(HomeworkSetting).filter(
        HomeworkSetting.key.in_(["semester_start", "semester_end", "semester_name"])
    ).all()
    cfg = dict(DEFAULT_SEMESTER)
    for row in rows:
        if row.value is not None:
            cfg[row.key] = row.value
    return cfg


def set_semester(db, data):
    current = (
        db.query(HomeworkSemester)
        .filter(HomeworkSemester.is_current == 1)
        .order_by(HomeworkSemester.id.desc())
        .first()
    )
    start = str(data.get("semester_start") or (current.start_date if current else DEFAULT_SEMESTER["semester_start"]))
    end = str(data.get("semester_end") or (current.end_date if current else DEFAULT_SEMESTER["semester_end"]))
    name = str(data.get("semester_name") or (current.name if current else "") or f"{start} 至 {end}")
    if current:
        current.start_date, current.end_date, current.name = start, end, name
    else:
        current = HomeworkSemester(name=name, start_date=start, end_date=end, is_current=1)
        db.add(current)
    for key in ("semester_start", "semester_end", "semester_name"):
        if key in data and data[key] is not None:
            db.merge(HomeworkSetting(key=key, value=str(data[key])))
    db.commit()
    return get_semester(db)


def excluded_names(db):
    rows = db.query(ClassRoster.name).filter(ClassRoster.excluded == 1).all()
    return {r[0] for r in rows}


def _subject_keywords(subject):
    if subject == DEFAULT_HOMEWORK_TYPE:
        return [DEFAULT_HOMEWORK_TYPE, *ACADEMIC_SUBJECT_HINTS]
    for canonical_name, keywords in SUBJECT_GROUPS:
        if canonical_name == subject:
            return keywords
    return None


def _miss_filters():
    """有效缺交的统一 SQL 谓词：状态=缺交、非全科、remark 为空、当天无请假。
    所有缺交口径（KPI/排行/预警/学期对比）必须复用这一份，避免各处漂移。"""
    from sqlalchemy import and_, exists

    has_leave = exists().where(and_(
        SpecialRecord.student_id == HomeworkRecord.student_id,
        SpecialRecord.date == HomeworkRecord.date,
        SpecialRecord.type.like("%请假%"),
    ))
    return [
        (HomeworkRecord.remark.is_(None)) | (HomeworkRecord.remark == ""),
        HomeworkRecord.subject != "全科",
        HomeworkRecord.submission_status == "缺交",
        ~has_leave,
    ]


def _base_miss_query(db, start, end, student=None, subject=None,
                     respect_excluded=True, teaching_class_id=None, scoped=True,
                     scope_ids=None):
    """缺交有效记录基础查询（join 花名册），返回 (HomeworkRecord, ClassRoster)。

    scope_ids: 显式成员集合（含 anon），优先于 teaching_class_id 的自动解析。
    供 weekly_focus 等需要「当前学科范围」语义的调用方传递，避免
    _scope_student_ids(None) 混入他科教学班成员。
    """
    q = (
        db.query(HomeworkRecord, ClassRoster)
        .join(ClassRoster, ClassRoster.student_id == HomeworkRecord.student_id)
        .filter(*_miss_filters())
    )
    if scoped:
        # excluded 的剔除交给下方 roster 层，保留「指定学生查询时不排除」的口径
        if scope_ids is not None:
            ids = scope_ids
        else:
            ids = _scope_student_ids(db, teaching_class_id, include_excluded=True)
        q = q.filter(HomeworkRecord.student_id.in_(ids))
    if start and end:
        q = q.filter(HomeworkRecord.date >= start, HomeworkRecord.date <= end)
    if student:
        q = q.filter(ClassRoster.name.like(f"%{student}%"))
    elif respect_excluded:
        q = q.filter(ClassRoster.excluded == 0)
    if subject:
        keywords = _subject_keywords(subject)
        if keywords:
            from sqlalchemy import or_
            q = q.filter(or_(*[HomeworkRecord.subject.like(f"%{k}%") for k in keywords]))
        else:
            q = q.filter(HomeworkRecord.subject == subject)
    return q


def _scope_student_ids(db, teaching_class_id=None, include_excluded=False):
    """作业范围：指定教学班＝该班成员；None＝我教的全部班成员并集。
    尚未配置任何教学班时回落到全花名册（旧版口径），避免看板/录入整体失明。

    注意：本函数的 None 路径取所有学科教学班成员并集（all_my_member_ids），
    单学科化后仅供已明确传入 teaching_class_id 的调用使用。需要「默认＝当前
    学科」语义的调用方（如 weekly_focus）应改用 _current_subject_hw_member_ids，
    禁止把 None 当默认旁路。"""
    if teaching_class_id is not None:
        ids = members_of(db, int(teaching_class_id), include_anon=True)
    else:
        ids = all_my_member_ids(db, include_anon=True)
        if not ids:
            ids = {r[0] for r in db.query(ClassRoster.student_id).all()}
    if include_excluded or not ids:
        return set(ids)
    excluded = {
        r[0] for r in db.query(ClassRoster.student_id)
        .filter(ClassRoster.student_id.in_(ids), ClassRoster.excluded == 1).all()
    }
    return set(ids) - excluded


def _current_subject_hw_member_ids(db, teaching_class_id=None) -> set[str]:
    """当前任教学科教学班成员并集（含 _anon: 占位成员），供作业缺交跟踪使用。

    与 _scope_student_ids(None) 的区别：后者取所有学科教学班成员并集，会混入
    教师遗留的他科教学班成员；本函数严格限定到教师唯一 subject 匹配的教学班。

    - 解析教师唯一 subject（resolve_teaching_subject）。
    - 只查询 TeachingClass.subject == subject 的班级；显式 teaching_class_id
      时进一步限定到该班，且校验其 subject/归属。
    - 成员集合含 _anon:（仅姓名占位成员），因为作业缺交跟踪正是「先有名单、
      后有成绩」的场景。
    """
    from app.analysis.scope import members_of
    from app.teaching.subject import resolve_teaching_subject
    from app.db.models import TeachingClassMember

    subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)

    if teaching_class_id is not None:
        # 显式班：直接取该班成员（含 anon）；subject 一致性已由
        # resolve_teaching_subject 校验（冲突会抛 SubjectConflictError）。
        return members_of(db, int(teaching_class_id), include_anon=True)

    # 默认：当前学科所有教学班成员并集（含 anon）
    rows = (
        db.query(TeachingClassMember.student_id)
        .join(TeachingClass, TeachingClass.id == TeachingClassMember.teaching_class_id)
        .filter(TeachingClass.subject == subject)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _labels_for(labels, student_id):
    """labels 为 student_class_map_multi(db) 的结果；调用方每次请求只建一次。"""
    return [row["label"] for row in labels.get(student_id, [])]


def kpi(db, start, end, student=None, subject=None, teaching_class_id=None):
    rows = _base_miss_query(db, start, end, student, subject,
                            teaching_class_id=teaching_class_id).all()
    total = len(rows)

    subj_counts = defaultdict(int)
    stu_counts = defaultdict(int)
    for rec, roster in rows:
        subj_counts[normalize_subject(rec.subject)] += 1
        stu_counts[(roster.student_id, roster.name)] += 1

    if subj_counts:
        worst_name, worst_count = max(subj_counts.items(), key=lambda x: x[1])
        worst_subject = {"name": worst_name, "count": worst_count}
    else:
        worst_subject = {"name": "无", "count": 0}

    labels = student_class_map_multi(db)
    top_students = [
        {"student_id": sid, "name": name, "class_labels": _labels_for(labels, sid), "count": c}
        for (sid, name), c in sorted(stu_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    return {
        "total_misses": total,
        "worst_subject": worst_subject,
        "top_students": top_students,
    }


def trend(db, start, end, student=None, subject=None, teaching_class_id=None):
    rows = _base_miss_query(db, start, end, student, subject,
                            teaching_class_id=teaching_class_id).all()
    by_date = defaultdict(int)
    for rec, _ in rows:
        by_date[rec.date] += 1
    dates = sorted(by_date)
    return {"dates": dates, "counts": [by_date[d] for d in dates]}


def subjects(db, start, end, student=None, subject=None, teaching_class_id=None):
    rows = _base_miss_query(db, start, end, student, subject,
                            teaching_class_id=teaching_class_id).all()
    totals = defaultdict(int)
    detail = defaultdict(lambda: defaultdict(int))
    for rec, roster in rows:
        canonical = normalize_subject(rec.subject)
        totals[canonical] += 1
        detail[canonical][(roster.student_id, roster.name)] += 1
    labels = student_class_map_multi(db)
    out = []
    for name, count in sorted(totals.items(), key=lambda x: x[1], reverse=True):
        students = sorted(detail[name].items(), key=lambda x: x[1], reverse=True)
        out.append({
            "name": name,
            "value": count,
            "students": [
                {"student_id": sid, "name": name, "class_labels": _labels_for(labels, sid), "count": c}
                for (sid, name), c in students
            ],
        })
    return out


def rankings(db, start, end, student=None, subject=None, limit=10,
             teaching_class_id=None):
    rows = _base_miss_query(db, start, end, student, subject,
                            teaching_class_id=teaching_class_id).all()
    counts = defaultdict(int)
    for _, roster in rows:
        counts[(roster.student_id, roster.name)] += 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    labels = student_class_map_multi(db)
    return {
        "names": [name for (_, name), _ in ranked],
        "counts": [c for _, c in ranked],
        "students": [
            {"student_id": sid, "name": name, "class_labels": _labels_for(labels, sid), "count": count}
            for (sid, name), count in ranked
        ],
    }


def warnings(db, start, end, teaching_class_id=None, scope_ids=None):
    """同一种作业「当前正在进行」的连续缺交预警。

    时间轴 = 该种作业全班有人缺交的去重日期 ∪ 该生自身有记录的日期；从最近
    一次向前回溯，统计某学生连续缺交了最近几次（必须含最后一次，否则视为
    已结束）。本人一条「已交」会终结自己的连击，但其他学生的「已交」记录
    不影响本人。连续 2 次 → warning（黄），≥3 次 → serious（红）。
    排除 excluded 学生。

    scope_ids: 显式成员集合（含 anon），优先于 teaching_class_id 的自动解析。
    供 weekly_focus 传递当前学科范围，避免 _scope_student_ids(None) 混入他科成员。
    """
    if scope_ids is not None:
        ids = scope_ids
    else:
        ids = _scope_student_ids(db, teaching_class_id)
    all_rows = (
        db.query(HomeworkRecord, ClassRoster)
        .join(ClassRoster, ClassRoster.student_id == HomeworkRecord.student_id)
        .filter(
            HomeworkRecord.student_id.in_(ids),
            HomeworkRecord.date >= start,
            HomeworkRecord.date <= end,
            HomeworkRecord.subject != "全科",
        ).all()
    )
    leave_pairs = {
        (sid, day)
        for sid, day in db.query(SpecialRecord.student_id, SpecialRecord.date).filter(
            SpecialRecord.student_id.in_(ids),
            SpecialRecord.date >= start,
            SpecialRecord.date <= end,
            SpecialRecord.type.like("%请假%"),
        ).all()
    }

    timeline = defaultdict(set)           # subject -> 有人缺交的日期
    own_dates = defaultdict(set)          # (subject, sid) -> 该生自身有记录的日期
    missed = defaultdict(set)
    identities = {}
    for rec, roster in all_rows:
        subj = normalize_subject(rec.subject)
        identities[(subj, roster.student_id)] = roster
        own_dates[(subj, roster.student_id)].add(rec.date)
        if (
            rec.submission_status == "缺交"
            and not (rec.remark or "").strip()
            and (rec.student_id, rec.date) not in leave_pairs
        ):
            missed[(subj, roster.student_id)].add(rec.date)
            timeline[subj].add(rec.date)

    labels = student_class_map_multi(db)
    serious, warning = [], []
    for (subj, sid), miss_dates in missed.items():
        roster = identities[(subj, sid)]
        axis = sorted(timeline[subj] | own_dates[(subj, sid)])
        streak = []
        for d in reversed(axis):
            if (sid, d) in leave_pairs:
                continue
            if d in miss_dates:
                streak.append(d)
            else:
                break
        if len(streak) < 2:
            continue
        streak.reverse()
        item = {
            "name": roster.name,
            "student_id": sid,
            "class_labels": _labels_for(labels, sid),
            "subject": subj,
            "streak": len(streak),
            "dates": streak,
        }
        (serious if item["streak"] >= 3 else warning).append(item)

    sort_key = lambda x: (-x["streak"], x["name"])
    serious.sort(key=sort_key)
    warning.sort(key=sort_key)
    students = {i["student_id"] for i in serious + warning}
    return {
        "serious": serious,
        "warning": warning,
        "counts": {
            "serious": len(serious),
            "warning": len(warning),
            "students": len(students),
        },
    }


# 评价词表唯一来源在 parser.py（录入解析与看板口径必须一致）
POSITIVE_WORDS = POSITIVE_EVALUATIONS
NEGATIVE_WORDS = NEGATIVE_EVALUATIONS


def evaluation_tone(value):
    text = (value or "").strip()
    if any(word in text for word in NEGATIVE_WORDS):
        return "negative"
    if any(word in text for word in POSITIVE_WORDS):
        return "positive"
    return "neutral"


def list_semesters(db):
    return [
        {
            "id": row.id,
            "name": row.name,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "is_current": bool(row.is_current),
        }
        for row in db.query(HomeworkSemester)
        .order_by(HomeworkSemester.start_date.desc(), HomeworkSemester.id.desc()).all()
    ]


def add_semester(db, name, start_date, end_date, make_current=False):
    if start_date > end_date:
        raise ValueError("学期开始日期不能晚于结束日期")
    final_name = name.strip() or f"{start_date} 至 {end_date}"
    duplicate = db.query(HomeworkSemester).filter(
        HomeworkSemester.name == final_name,
        HomeworkSemester.start_date == start_date,
        HomeworkSemester.end_date == end_date,
    ).first()
    if duplicate:
        raise ValueError("同名同起止日期的学期已存在")
    if make_current:
        db.query(HomeworkSemester).update({HomeworkSemester.is_current: 0})
    row = HomeworkSemester(
        name=final_name,
        start_date=start_date,
        end_date=end_date,
        is_current=1 if make_current else 0,
    )
    db.add(row)
    db.commit()
    return list_semesters(db)


def set_current_semester(db, semester_id):
    row = db.query(HomeworkSemester).filter(HomeworkSemester.id == semester_id).first()
    if not row:
        return False
    db.query(HomeworkSemester).update({HomeworkSemester.is_current: 0})
    row.is_current = 1
    for key, value in (
        ("semester_start", row.start_date),
        ("semester_end", row.end_date),
        ("semester_name", row.name),
    ):
        db.merge(HomeworkSetting(key=key, value=value))
    db.commit()
    return True


def _period_label(raw_date, group_by):
    parsed = datetime.strptime(raw_date, "%Y-%m-%d").date()
    if group_by == "month":
        return parsed.strftime("%Y-%m")
    monday = parsed - timedelta(days=parsed.weekday())
    return monday.isoformat()


def _scope_meta(db, teaching_class_id, ids):
    if teaching_class_id is not None:
        tc = db.query(TeachingClass).filter(TeachingClass.id == teaching_class_id).first()
        return {
            "type": "teaching_class",
            "teaching_class_id": teaching_class_id,
            "label": tc.label if tc else "未知教学班",
            "member_count": len(ids),
        }
    return {
        "type": "all",
        "teaching_class_id": None,
        "label": "全部（我教的班）",
        "member_count": len(ids),
    }


def dashboard(db, start, end, student=None, teaching_class_id=None,
              group_by="week", limit=10):
    """作业页单次请求所需的完整聚合数据。

    姓名筛选只作用于按学生的榜单/预警/荣誉/趋势；教学班提交率与学期对比
    始终按完整范围计算，避免筛一个人时把班级指标算成单人指标。
    """
    scope_ids = _scope_student_ids(db, teaching_class_id)
    roster_rows = (
        db.query(ClassRoster).filter(
            ClassRoster.student_id.in_(scope_ids), ClassRoster.excluded == 0
        ).all()
    )
    roster_all = {r.student_id: r for r in roster_rows}
    ids_all = set(roster_all)
    roster = (
        {sid: r for sid, r in roster_all.items() if student in r.name}
        if student else roster_all
    )
    ids = set(roster)
    labels = student_class_map_multi(db)

    records = (
        db.query(HomeworkRecord)
        .filter(
            HomeworkRecord.student_id.in_(ids_all),
            HomeworkRecord.date >= start,
            HomeworkRecord.date <= end,
        ).order_by(HomeworkRecord.date, HomeworkRecord.id).all()
    )
    specials = (
        db.query(SpecialRecord)
        .filter(
            SpecialRecord.student_id.in_(ids_all),
            SpecialRecord.date >= start,
            SpecialRecord.date <= end,
        ).all()
    )
    leave_pairs = {
        (s.student_id, s.date) for s in specials if "请假" in (s.type or "")
    }

    def is_valid_miss(rec):
        # 与 _miss_filters() 同一口径的内存版
        return (
            rec.submission_status == "缺交"
            and rec.subject != "全科"
            and not (rec.remark or "").strip()
            and (rec.student_id, rec.date) not in leave_pairs
        )

    misses_all = [r for r in records if is_valid_miss(r)]
    misses = [r for r in misses_all if r.student_id in ids]
    submitted = [
        r for r in records
        if r.student_id in ids
        and r.submission_status == "已交"
        and (r.student_id, r.date) not in leave_pairs
    ]

    def student_item(sid, count=0):
        row = roster_all[sid]
        return {
            "student_id": sid,
            "name": row.name,
            "class_labels": _labels_for(labels, sid),
            "count": count,
        }

    miss_counts, excellent_counts = defaultdict(int), defaultdict(int)
    evaluation_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for rec in misses:
        miss_counts[rec.student_id] += 1
    # 优秀统计跟随所选区间（不锚定「今天」，历史区间同样有效）
    for rec in submitted:
        tone = evaluation_tone(rec.evaluation)
        evaluation_counts[tone] += 1
        if tone == "positive":
            excellent_counts[rec.student_id] += 1

    missing_ranking = [
        student_item(sid, count)
        for sid, count in sorted(miss_counts.items(), key=lambda x: (-x[1], roster[x[0]].name))[:limit]
    ]
    excellent_ranking = [
        student_item(sid, count)
        for sid, count in sorted(excellent_counts.items(), key=lambda x: (-x[1], roster[x[0]].name))[:limit]
    ]

    streaks = warnings(db, start, end, teaching_class_id)
    if student:
        for key in ("serious", "warning"):
            streaks[key] = [x for x in streaks[key] if x["student_id"] in ids]
        streaks["counts"] = {
            "serious": len(streaks["serious"]),
            "warning": len(streaks["warning"]),
            "students": len({x["student_id"] for x in streaks["serious"] + streaks["warning"]}),
        }

    forgot = defaultdict(int)
    for sp in specials:
        if sp.student_id in ids and "忘带" in (sp.type or ""):
            forgot[sp.student_id] += 1
    forgot_warnings = [
        student_item(sid, count)
        for sid, count in sorted(forgot.items(), key=lambda x: -x[1])
        if count >= 3
    ]

    negative_streaks = []
    by_student_evals = defaultdict(list)
    for rec in submitted:
        if rec.evaluation:
            by_student_evals[rec.student_id].append(rec)
    for sid, rows in by_student_evals.items():
        streak = []
        for rec in reversed(rows):
            if evaluation_tone(rec.evaluation) == "negative":
                streak.append(rec)
            else:
                break
        if len(streak) >= 2:
            item = student_item(sid, len(streak))
            item["dates"] = sorted(r.date for r in streak)
            item["evaluations"] = [r.evaluation for r in reversed(streak)]
            negative_streaks.append(item)

    excellent_stars = [
        student_item(sid, count)
        for sid, count in sorted(excellent_counts.items(), key=lambda x: -x[1])
        if count >= 3
    ]

    heatmap_counts = defaultdict(int)
    trend_counts = defaultdict(int)
    subject_totals = defaultdict(int)
    for rec in misses:
        heatmap_counts[rec.date] += 1
        trend_counts[_period_label(rec.date, group_by)] += 1
        subject_totals[normalize_subject(rec.subject)] += 1

    # 教学班提交率：按完整范围（ids_all）计算，不受姓名筛选影响。
    # 口径假设：某班任一成员有记录的日期即视为该班一次收交、全员应交；
    # 区间内无任何记录的班无法估计，rate 返回 None（前端显示「—」）。
    members_by_class = defaultdict(set)
    for sid, rows in labels.items():
        for row in rows:
            members_by_class[row["teaching_class_id"]].add(sid)

    classes_q = db.query(TeachingClass)
    if teaching_class_id is not None:
        classes_q = classes_q.filter(TeachingClass.id == teaching_class_id)
    classes = classes_q.order_by(TeachingClass.sort_order, TeachingClass.id).all()

    rates = []
    eligible_full_attendance = set()
    for tc in classes:
        class_ids = members_by_class.get(tc.id, set()) & ids_all
        dates = {r.date for r in records if r.student_id in class_ids}
        if class_ids and dates:
            eligible_full_attendance |= class_ids
            leave_count = len({
                (sid, day) for sid, day in leave_pairs
                if sid in class_ids and day in dates
            })
            denominator = len(class_ids) * len(dates) - leave_count
            class_misses = sum(1 for r in misses_all if r.student_id in class_ids)
            submitted_slots = max(0, denominator - class_misses)
            rate = round(submitted_slots / denominator * 100, 1) if denominator > 0 else None
        else:
            denominator, submitted_slots, rate = 0, 0, None
        rates.append({
            "teaching_class_id": tc.id,
            "label": tc.label,
            "member_count": len(class_ids),
            "assignment_dates": len(dates),
            "submitted": submitted_slots,
            "expected": max(0, denominator),
            "rate": rate,
        })

    if not classes:
        # 未配置教学班（回落全花名册）：区间内有过任何记录即视为有作业安排
        eligible_full_attendance = ids_all if records else set()
    # 全勤之星只发给「所在班在区间内确实有收交记录」的学生，
    # 避免零数据班/空区间把全班都评成星。
    full_attendance = [
        student_item(sid) for sid in roster
        if sid in eligible_full_attendance and miss_counts.get(sid, 0) == 0
    ]

    semester_compare = []
    for sem in db.query(HomeworkSemester).order_by(HomeworkSemester.start_date).all():
        sem_misses = (
            db.query(HomeworkRecord)
            .filter(
                HomeworkRecord.student_id.in_(ids_all),
                HomeworkRecord.date >= sem.start_date,
                HomeworkRecord.date <= sem.end_date,
                *_miss_filters(),
            ).count()
        )
        semester_compare.append({
            "semester_id": sem.id, "name": sem.name, "misses": sem_misses,
            "is_current": bool(sem.is_current),
        })

    return {
        "scope": _scope_meta(db, teaching_class_id, ids_all),
        "date_range": {"start": start, "end": end},
        "kpi": kpi(db, start, end, student, teaching_class_id=teaching_class_id),
        "subjects": [
            {"name": key, "value": value}
            for key, value in sorted(subject_totals.items(), key=lambda x: -x[1])
        ],
        "warnings": {
            "streak": streaks,
            "quality": negative_streaks,
            "forgot": forgot_warnings,
        },
        "honors": {"excellent": excellent_stars, "full_attendance": full_attendance},
        "rankings": {"missing": missing_ranking, "excellent": excellent_ranking},
        "submission_rates": rates,
        "trend": [
            {"period": period, "count": count}
            for period, count in sorted(trend_counts.items())
        ],
        "evaluation_distribution": [
            {"tone": key, "label": {"positive": "正面", "neutral": "一般", "negative": "负面"}[key], "count": value}
            for key, value in evaluation_counts.items()
        ],
        "heatmap": [
            {"date": day, "count": count}
            for day, count in sorted(heatmap_counts.items())
        ],
        "semester_compare": semester_compare,
    }


def student_summary(db, student_id=None, name=None):
    """单个学生本学期作业概况：缺交总数、按作业种类分布、迟到/请假次数、
    当前连续缺交预警。姓名多义时返回候选。"""
    roster_q = db.query(ClassRoster)
    if student_id:
        roster_q = roster_q.filter(ClassRoster.student_id == student_id)
    elif name:
        roster_q = roster_q.filter(ClassRoster.name.like(f"%{name}%"))
    else:
        return {"error": "需提供 student_id 或 name"}
    matches = roster_q.limit(10).all()
    if not matches:
        return {"error": "未在作业花名册中找到该学生", "student_id": student_id, "name": name}
    if len(matches) > 1 and not student_id:
        return {
            "error": "匹配到多个学生，请指定学号",
            "candidates": [{"student_id": m.student_id, "name": m.name} for m in matches],
        }
    roster = matches[0]
    sem = get_semester(db)
    start, end = sem["semester_start"], sem["semester_end"]

    # 指定学生查询：不走教学班 scope、不排除 excluded（口径见模块 docstring）
    miss_rows = [
        rec for rec, _ in _base_miss_query(
            db, start, end, respect_excluded=False, scoped=False
        ).filter(HomeworkRecord.student_id == roster.student_id).all()
    ]
    by_subject = defaultdict(int)
    for r in miss_rows:
        by_subject[normalize_subject(r.subject)] += 1

    special_rows = (
        db.query(SpecialRecord)
        .filter(
            SpecialRecord.student_id == roster.student_id,
            SpecialRecord.date >= start,
            SpecialRecord.date <= end,
        )
        .all()
    )
    special_counts = defaultdict(int)
    for s in special_rows:
        special_counts[s.type] += 1

    # 该生当前连续缺交预警
    all_warn = warnings(db, start, end)
    student_warnings = [
        w for w in (all_warn["serious"] + all_warn["warning"])
        if w["student_id"] == roster.student_id
    ]

    recent_records = [
        {"date": r.date, "subject": normalize_subject(r.subject), "content": r.content or ""}
        for r in sorted(miss_rows, key=lambda r: r.date, reverse=True)[:10]
    ]

    return {
        "student": {
            "student_id": roster.student_id,
            "name": roster.name,
            "class_num": roster.class_num,
            "excluded": bool(roster.excluded),
        },
        "semester": sem,
        "total_misses": len(miss_rows),
        "miss_by_subject": dict(sorted(by_subject.items(), key=lambda x: x[1], reverse=True)),
        "special_counts": dict(special_counts),
        "active_warnings": student_warnings,
        "recent_records": recent_records,
        "note": "作业数据仅含缺交、请假、迟到等负面信号，不代表作业完成质量。",
    }


def _pearson(xs, ys):
    """皮尔逊相关系数；样本<3 或任一方差为 0 返回 None。"""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(sxy / (sxx ** 0.5 * syy ** 0.5), 4)


def _resolve_latest_exam(db, valid_ids, exam_id, request_param_name="exam_id"):
    """在合法考试集合中解析最终使用的考试，返回 (exam_id, exam_grade)。

    - 显式 exam_id 必须落在 valid_ids 内；否则 400（不静默替换）。
    - 默认（exam_id is None）按 Exam.exam_date DESC, Exam.id DESC 选最近一场。
    - 返回 exam_grade（Exam.grade），供 compute_subject_rank_contextual 使用，
      禁止 None（高二/三选考必须按 grade_score 排名）。
    """
    from app.db.models import Exam
    from fastapi import HTTPException

    if exam_id is not None:
        if exam_id not in valid_ids:
            raise HTTPException(
                400,
                f"{request_param_name} 不在当前教学班/学科/范围内，请勿指定他班考试",
            )
        ex = db.query(Exam).filter(Exam.id == exam_id).first()
        return exam_id, (ex.grade if ex else None)

    if valid_ids:
        latest = (
            db.query(Exam)
            .filter(Exam.id.in_(valid_ids))
            .order_by(Exam.exam_date.desc(), Exam.id.desc())
            .first()
        )
        if latest:
            return latest.id, latest.grade

    return None, None


def grade_correlation(db, teaching_class_id=None, exam_id=None,
                      start=None, end=None, subject=None):
    """作业缺交 × 当前学科成绩相关性（单学科化）。

    - 后端自行解析唯一任教学科；subject 兼容但只允许等于当前学科，否则 ValueError。
    - 范围必须是当前学科教学班成员（显式班或默认去重并集）。
    - X 为所有作业种类的缺交次数（HomeworkRecord.subject 是作业种类，不得误当学科
      过滤）；Y 统一使用最近合法考试的当前学科 subject_rank（按班排名，越小越好），
      高二/三选考自然由 grade_score 排名。
    - 无当前学科成绩的合法成员保留，subject_rank=null。
    """
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject
    from fastapi import HTTPException

    teaching_subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)
    # subject 兼容：只允许等于当前学科
    if subject is not None and subject != teaching_subject:
        raise HTTPException(400, f"subject 只允许当前任教学科「{teaching_subject}」")

    if not start or not end:
        sem = get_semester(db)
        start, end = sem["semester_start"], sem["semester_end"]

    # 解析当前学科成员范围（显式班或默认并集）
    try:
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id,
        )
    except Exception as e:
        # 让领域错误冒泡为 4xx
        raise HTTPException(409, str(e))

    member_ids = set(ctx.member_ids)

    # 合法考试：当前学科在该范围内有真实分数的考试
    valid_ids = valid_exam_ids_for_subject(db, teaching_subject, member_ids)
    exam_id, exam_grade = _resolve_latest_exam(db, valid_ids, exam_id)

    # subject_rank（按班 competition ranking，越小越好）
    rank_map: dict[str, int] = {}
    if exam_id is not None:
        try:
            rm, _rows = compute_subject_rank_contextual(
                db, ctx, exam_id, exam_grade=exam_grade,
            )
            rank_map = rm
        except Exception:
            rank_map = {}

    # 学期内缺交次数（所有作业种类，不得按学科过滤——HomeworkRecord.subject 是作业种类）
    miss_rows = _base_miss_query(
        db, start, end,
        teaching_class_id=teaching_class_id,
        respect_excluded=True,
    ).all()
    miss_by_sid = defaultdict(int)
    for rec, _roster in miss_rows:
        miss_by_sid[rec.student_id] += 1

    # 花名册（限合法成员范围，排除 excluded）
    roster_rows = (
        db.query(ClassRoster)
        .filter(ClassRoster.student_id.in_(member_ids))
        .all()
    )
    rows = []
    for r in roster_rows:
        if r.excluded:
            continue
        rows.append({
            "student_id": r.student_id,
            "name": r.name,
            "miss_count": miss_by_sid.get(r.student_id, 0),
            "subject_rank": rank_map.get(r.student_id),
        })
    rows.sort(key=lambda x: x["miss_count"], reverse=True)
    return {
        "teaching_subject": teaching_subject,
        "teaching_class_id": teaching_class_id,
        "exam_id": exam_id,
        "subject": teaching_subject,
        "y_field": "subject_rank",
        "y_label": f"{teaching_subject}班内名次",
        "semester": {"start": start, "end": end},
        "rows": rows,
        "note": (
            f"miss_count 为学期内所有作业种类的缺交次数；subject_rank 为当前{teaching_subject}"
            "按班排名（越小越好）。缺交多且名次靠后即落在重点关注象限。"
            "作业数据仅反映缺交，不代表完成质量。"
        ),
    }



def subject_correlation_ranking(db, teaching_class_id=None, exam_id=None, start=None, end=None):
    """「缺交 × 当前学科成绩」皮尔逊相关（单学科化重定义）。

    不再多学科扫描：重定义为仅当前任教学科一项，并返回 teaching_subject。
    r>0 表示缺交越多、当前学科排名越靠后（rank 越大）。
    仅纳入有当前学科 subject_rank、非 excluded 的合法成员（缺交为 0 也计入）。
    """
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        valid_exam_ids_for_subject,
    )
    from app.teaching.subject import resolve_teaching_subject
    from fastapi import HTTPException

    teaching_subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)

    if not start or not end:
        sem = get_semester(db)
        start, end = sem["semester_start"], sem["semester_end"]

    try:
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id,
        )
    except Exception as e:
        raise HTTPException(409, str(e))

    member_ids = set(ctx.member_ids)
    valid_ids = valid_exam_ids_for_subject(db, teaching_subject, member_ids)
    exam_id, exam_grade = _resolve_latest_exam(db, valid_ids, exam_id)

    rank_map: dict[str, int] = {}
    if exam_id is not None:
        try:
            rm, _rows = compute_subject_rank_contextual(
                db, ctx, exam_id, exam_grade=exam_grade,
            )
            rank_map = rm
        except Exception:
            rank_map = {}

    # 学期内缺交次数（所有作业种类）
    miss_rows = _base_miss_query(
        db, start, end,
        teaching_class_id=teaching_class_id,
        respect_excluded=True,
    ).all()
    miss_by_sid = defaultdict(int)
    for rec, _roster in miss_rows:
        miss_by_sid[rec.student_id] += 1

    roster_rows = (
        db.query(ClassRoster)
        .filter(ClassRoster.student_id.in_(member_ids))
        .all()
    )
    excluded = {r.student_id for r in roster_rows if r.excluded}
    xs, ys = [], []
    for r in roster_rows:
        if r.student_id in excluded:
            continue
        sr = rank_map.get(r.student_id)
        if sr is None:
            continue
        xs.append(miss_by_sid.get(r.student_id, 0))
        ys.append(sr)  # rank 越小越好
    r_val = _pearson(xs, ys)
    results = [{"subject": teaching_subject, "r": r_val, "n": len(xs)}]
    return {
        "teaching_subject": teaching_subject,
        "teaching_class_id": teaching_class_id,
        "exam_id": exam_id,
        "semester": {"start": start, "end": end},
        "rankings": results,
        "note": (
            f"r 为皮尔逊相关系数，正值越大表示缺交越多、{teaching_subject}班内名次越靠后"
            "（成绩越差）；n 为样本数，n<3 记 r=null。作业数据仅反映缺交，不代表完成质量。"
        ),
    }


def weekly_focus(db, teaching_class_id=None, today=None):
    """本周关注名单（单学科化）：合并连续缺交预警、本周缺交激增、最近一次考试
    临界/薄弱、谈话跟进待办。主要由缺交信号驱动，不依赖新考试。

    - 接受 teaching_class_id；默认范围为当前任教学科教学班成员并集。
    - 作业缺交、特殊记录、谈话跟进仍保留，但只能落在合法成员范围内。
    - 最近考试信号不得导入/调用 chat.tools.focus_list，不得查询 TotalScore。
      直接复用阶段4当前学科上下文、合法考试、按班 subject rank 和 band config；
      理由仅「临界段/薄弱段」，不再「偏科」。
    - 返回 teaching_subject、teaching_class_id。
    """
    from datetime import date, timedelta

    from app.db.models import StudentNote, Exam
    from app.analysis.config import get_band_config
    from app.analysis.single_subject_metrics import (
        resolve_single_subject_context,
        compute_subject_rank_contextual,
        valid_exam_ids_for_subject,
        band_classify,
    )
    from app.teaching.subject import resolve_teaching_subject
    from fastapi import HTTPException

    teaching_subject = resolve_teaching_subject(db, teaching_class_id=teaching_class_id)

    try:
        ctx = resolve_single_subject_context(
            db, teaching_class_id=teaching_class_id,
        )
    except Exception as e:
        raise HTTPException(409, str(e))

    member_ids = set(ctx.member_ids)

    sem = get_semester(db)
    start, end = sem["semester_start"], sem["semester_end"]
    today = today or date.today().isoformat()
    week_start = (date.fromisoformat(today) - timedelta(days=6)).isoformat()

    # 花名册：限当前学科教学班成员范围、非 excluded。
    # member_ids（ctx）不含 _anon: 占位成员，但作业缺交跟踪需要保留仅姓名
    # 教学班成员（先有名单、后有成绩）。这里用当前学科作业范围（含 anon）构建
    # 花名册，保证匿名成员的缺交信号能进入 Weekly；成绩排名信号仍只用 ctx.member_ids。
    # 禁止 _scope_student_ids(None) 或 all_my_member_ids() 成为默认旁路（会混入
    # 教师遗留的他科教学班成员）。
    hw_scope_ids = _current_subject_hw_member_ids(db, teaching_class_id)
    roster = {
        r.student_id: r
        for r in db.query(ClassRoster)
        .filter(ClassRoster.student_id.in_(hw_scope_ids), ClassRoster.excluded == 0)
        .all()
    }
    reasons: dict[str, list] = defaultdict(list)

    def add(sid, tag, weight):
        if sid in roster:
            reasons[sid].append({"tag": tag, "weight": weight})

    # ① 连续缺交预警（限当前学科范围）
    w = warnings(db, start, end, scope_ids=hw_scope_ids)
    best = {}
    for item in w["serious"] + w["warning"]:
        sid = item.get("student_id")
        if sid and (sid not in best or item["streak"] > best[sid]["streak"]):
            best[sid] = item
    for sid, item in best.items():
        sev = 3 if item["streak"] >= 3 else 2
        add(sid, f"连续缺交{item['streak']}次（{item['subject']}）", sev)

    # ② 本周缺交激增（限当前学科范围）
    miss_rows = _base_miss_query(
        db, start, end,
        scope_ids=hw_scope_ids,
        respect_excluded=True,
    ).all()
    total_by_sid = defaultdict(int)
    week_by_sid = defaultdict(int)
    for rec, _roster in miss_rows:
        total_by_sid[rec.student_id] += 1
        if week_start <= rec.date <= today:
            week_by_sid[rec.student_id] += 1
    weeks_elapsed = max(1, (date.fromisoformat(min(today, end)) - date.fromisoformat(start)).days / 7)
    for sid, wk in week_by_sid.items():
        avg = total_by_sid[sid] / weeks_elapsed
        if wk >= 3 and wk >= 2 * max(avg, 0.5):
            add(sid, f"本周缺交激增（{wk}次）", 2)

    # ③ 最近一次当前学科合法考试的临界/薄弱（复用阶段4口径，不调用 focus_list、
    #    不查询 TotalScore；理由仅临界段/薄弱段）
    valid_ids = valid_exam_ids_for_subject(db, teaching_subject, member_ids)
    latest = None
    if valid_ids:
        latest = (
            db.query(Exam)
            .filter(Exam.id.in_(valid_ids))
            .order_by(Exam.exam_date.desc(), Exam.id.desc())
            .first()
        )
    if latest:
        cfg = get_band_config(db)
        rank_map, _rows = compute_subject_rank_contextual(
            db, ctx, latest.id, exam_grade=latest.grade,
        )
        for sid, sr in rank_map.items():
            issues = band_classify(sr, cfg)
            if issues:
                add(sid, "、".join(issues), 1)

    # ④ 谈话跟进待办（限合法成员范围）
    note_rows = (
        db.query(StudentNote)
        .filter(StudentNote.follow_up.isnot(None), StudentNote.follow_up_done == 0)
        .all()
    )
    for n in note_rows:
        if n.student_id in roster:
            add(n.student_id, f"谈话跟进待办：{n.follow_up}", 2)

    out = []
    for sid, items in reasons.items():
        out.append({
            "student_id": sid,
            "name": roster[sid].name,
            "score": sum(i["weight"] for i in items),
            "reasons": [i["tag"] for i in sorted(items, key=lambda x: -x["weight"])],
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return {
        "teaching_subject": teaching_subject,
        "teaching_class_id": teaching_class_id,
        "week": {"start": week_start, "end": today},
        "students": out,
        "note": (
            "合并连续缺交预警、本周缺交激增、最近考试临界/薄弱（仅当前学科）、谈话跟进待办。"
            "主要由缺交信号驱动，无新考试也每天更新。作业数据仅反映缺交，不代表完成质量。"
        ),
    }
