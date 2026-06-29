"""作业缺交统计服务层。

集中缺交看板/排行/预警/学生汇总/相关性等查询，供 homework/router.py 的
REST 端点和 chat/tools.py 的对话工具共同复用，避免逻辑重复。口径与原
Flask 应用一致：缺交有效记录 = remark 为空 且 subject != '全科'；默认排除
excluded=1 的学生（指定具体学生查询时不排除）。
"""

from collections import defaultdict

from app.db.models import (
    ClassRoster,
    HomeworkRecord,
    SpecialRecord,
    HomeworkSetting,
)
from app.homework.parser import SUBJECT_GROUPS, normalize_subject

DEFAULT_SEMESTER = {
    "semester_start": "2026-02-17",
    "semester_end": "2026-07-04",
    "semester_name": "",
}


def get_semester(db):
    rows = db.query(HomeworkSetting).filter(
        HomeworkSetting.key.in_(["semester_start", "semester_end", "semester_name"])
    ).all()
    cfg = dict(DEFAULT_SEMESTER)
    for row in rows:
        if row.value is not None:
            cfg[row.key] = row.value
    return cfg


def set_semester(db, data):
    for key in ("semester_start", "semester_end", "semester_name"):
        if key in data and data[key] is not None:
            db.merge(HomeworkSetting(key=key, value=str(data[key])))
    db.commit()
    return get_semester(db)


def excluded_names(db):
    rows = db.query(ClassRoster.name).filter(ClassRoster.excluded == 1).all()
    return {r[0] for r in rows}


def _subject_keywords(subject):
    for canonical_name, keywords in SUBJECT_GROUPS:
        if canonical_name == subject:
            return keywords
    return None


def _base_miss_query(db, start, end, student=None, subject=None,
                     respect_excluded=True):
    """缺交有效记录基础查询（join 花名册），返回 (HomeworkRecord, ClassRoster)。"""
    q = (
        db.query(HomeworkRecord, ClassRoster)
        .join(ClassRoster, ClassRoster.student_id == HomeworkRecord.student_id)
        .filter(
            (HomeworkRecord.remark.is_(None)) | (HomeworkRecord.remark == ""),
            HomeworkRecord.subject != "全科",
        )
    )
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


def kpi(db, start, end, student=None, subject=None):
    rows = _base_miss_query(db, start, end, student, subject).all()
    total = len(rows)

    subj_counts = defaultdict(int)
    stu_counts = defaultdict(int)
    for rec, roster in rows:
        subj_counts[normalize_subject(rec.subject)] += 1
        stu_counts[roster.name] += 1

    if subj_counts:
        worst_name, worst_count = max(subj_counts.items(), key=lambda x: x[1])
        worst_subject = {"name": worst_name, "count": worst_count}
    else:
        worst_subject = {"name": "无", "count": 0}

    top_students = [
        {"name": n, "count": c}
        for n, c in sorted(stu_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    return {
        "total_misses": total,
        "worst_subject": worst_subject,
        "top_students": top_students,
    }


def trend(db, start, end, student=None, subject=None):
    rows = _base_miss_query(db, start, end, student, subject).all()
    by_date = defaultdict(int)
    for rec, _ in rows:
        by_date[rec.date] += 1
    dates = sorted(by_date)
    return {"dates": dates, "counts": [by_date[d] for d in dates]}


def subjects(db, start, end, student=None, subject=None):
    rows = _base_miss_query(db, start, end, student, subject).all()
    totals = defaultdict(int)
    detail = defaultdict(lambda: defaultdict(int))
    for rec, roster in rows:
        canonical = normalize_subject(rec.subject)
        totals[canonical] += 1
        detail[canonical][roster.name] += 1
    out = []
    for name, count in sorted(totals.items(), key=lambda x: x[1], reverse=True):
        students = sorted(detail[name].items(), key=lambda x: x[1], reverse=True)
        out.append({
            "name": name,
            "value": count,
            "students": [{"name": s, "count": c} for s, c in students],
        })
    return out


def rankings(db, start, end, student=None, subject=None, limit=10):
    rows = _base_miss_query(db, start, end, student, subject).all()
    counts = defaultdict(int)
    for _, roster in rows:
        counts[roster.name] += 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "names": [n for n, _ in ranked],
        "counts": [c for _, c in ranked],
    }


def warnings(db, start, end):
    """同一学科「当前正在进行」的连续缺交预警。

    时间轴 = 该学科全班有人缺交的去重日期；从最近一次收交向前回溯，统计
    某学生连续缺交了最近几次（必须含最后一次收交，否则视为已结束）。
    连续 2 次 → warning（黄），≥3 次 → serious（红）。排除 excluded 学生。
    """
    rows = _base_miss_query(db, start, end, respect_excluded=True).all()

    timeline = defaultdict(set)            # subject -> {date}
    missed = defaultdict(set)             # (subject, name) -> {date}
    name_to_sid = {}                      # name -> student_id（供预警页链到学生画像）
    for rec, roster in rows:
        subj = normalize_subject(rec.subject)
        timeline[subj].add(rec.date)
        missed[(subj, roster.name)].add(rec.date)
        name_to_sid[roster.name] = roster.student_id

    serious, warning = [], []
    for (subj, name), miss_dates in missed.items():
        axis = sorted(timeline[subj])
        streak = []
        for d in reversed(axis):
            if d in miss_dates:
                streak.append(d)
            else:
                break
        if len(streak) < 2:
            continue
        streak.reverse()
        item = {
            "name": name,
            "student_id": name_to_sid.get(name),
            "subject": subj,
            "streak": len(streak),
            "dates": streak,
        }
        (serious if item["streak"] >= 3 else warning).append(item)

    sort_key = lambda x: (-x["streak"], x["name"])
    serious.sort(key=sort_key)
    warning.sort(key=sort_key)
    students = {i["name"] for i in serious + warning}
    return {
        "serious": serious,
        "warning": warning,
        "counts": {
            "serious": len(serious),
            "warning": len(warning),
            "students": len(students),
        },
    }


def student_summary(db, student_id=None, name=None):
    """单个学生本学期作业概况：缺交总数、按科目分布、迟到/请假次数、
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

    miss_rows = (
        db.query(HomeworkRecord)
        .filter(
            HomeworkRecord.student_id == roster.student_id,
            (HomeworkRecord.remark.is_(None)) | (HomeworkRecord.remark == ""),
            HomeworkRecord.subject != "全科",
            HomeworkRecord.date >= start,
            HomeworkRecord.date <= end,
        )
        .all()
    )
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
        w for w in (all_warn["serious"] + all_warn["warning"]) if w["name"] == roster.name
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


# 9 门学考学科（按学科相关性用，排除"全科"）
ACADEMIC_SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理")


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


def _latest_exam_id(db):
    from app.db.models import Exam, TotalScore
    exam = (
        db.query(Exam)
        .join(TotalScore, TotalScore.exam_id == Exam.id)
        .order_by(Exam.exam_date.desc(), Exam.id.desc())
        .first()
    )
    return exam.id if exam else None


def grade_correlation(db, class_num, exam_id=None, total_type="主三门",
                      start=None, end=None, subject=None):
    """班级「缺交 × 成绩」相关性数据。

    - 总分模式（subject 为空）：X=学期总缺交次数，Y=该次考试 total_type 学籍排名。
    - 单科模式（subject 非空）：X=该科学期缺交次数，Y=该科年级百分位（越小越靠前）。
    """
    from app.db.models import SubjectScore, TotalScore

    if not start or not end:
        sem = get_semester(db)
        start, end = sem["semester_start"], sem["semester_end"]
    if exam_id is None:
        exam_id = _latest_exam_id(db)

    roster = {
        r.student_id: r
        for r in db.query(ClassRoster).filter(ClassRoster.class_num == class_num).all()
    }

    # 学期内缺交次数（subject 非空时只算该科）
    miss_rows = _base_miss_query(db, start, end, subject=subject, respect_excluded=True).all()
    miss_by_sid = defaultdict(int)
    for rec, _ in miss_rows:
        miss_by_sid[rec.student_id] += 1

    if subject:
        scores = {}
        if exam_id is not None:
            for s in db.query(SubjectScore).filter(
                SubjectScore.exam_id == exam_id,
                SubjectScore.subject == subject,
            ).all():
                scores[s.student_id] = s
        rows = []
        for sid, roster_row in roster.items():
            if roster_row.excluded:
                continue
            s = scores.get(sid)
            rows.append({
                "student_id": sid,
                "name": roster_row.name,
                "miss_count": miss_by_sid.get(sid, 0),
                "grade_percentile": s.grade_percentile if s else None,
                "raw_score": s.raw_score if s else None,
            })
        rows.sort(key=lambda x: x["miss_count"], reverse=True)
        return {
            "class_num": class_num,
            "exam_id": exam_id,
            "subject": subject,
            "y_field": "grade_percentile",
            "y_label": "年级百分位",
            "semester": {"start": start, "end": end},
            "rows": rows,
            "note": f"miss_count 为学期内{subject}缺交次数；grade_percentile 越小越靠前。{subject}缺交多且百分位大（成绩差）即落在重点关注象限。作业数据仅反映缺交，不代表完成质量。",
        }

    # 总分模式
    totals = {}
    if exam_id is not None:
        for t in db.query(TotalScore).filter(
            TotalScore.exam_id == exam_id,
            TotalScore.total_type == total_type,
        ).all():
            totals[t.student_id] = t
    rows = []
    for sid, roster_row in roster.items():
        if roster_row.excluded:
            continue
        t = totals.get(sid)
        rows.append({
            "student_id": sid,
            "name": roster_row.name,
            "miss_count": miss_by_sid.get(sid, 0),
            "xueji_rank": t.xueji_rank if t else None,
            "grade_rank": t.grade_rank if t else None,
            "total_score": t.total_score if t else None,
        })
    rows.sort(key=lambda x: x["miss_count"], reverse=True)
    return {
        "class_num": class_num,
        "exam_id": exam_id,
        "total_type": total_type,
        "subject": None,
        "y_field": "xueji_rank",
        "y_label": "学籍排名",
        "semester": {"start": start, "end": end},
        "rows": rows,
        "note": "miss_count 为学期内缺交次数；xueji_rank 越小越靠前。缺交多且排名靠后即落在「高缺交+低排名」象限，值得重点关注。作业数据仅反映缺交，不代表完成质量。",
    }


def subject_correlation_ranking(db, class_num, exam_id=None, start=None, end=None):
    """各学科「缺交次数 × 该科年级百分位」皮尔逊相关排序。

    r>0 表示该科缺交越多、百分位越大（成绩越差），即"缺交越拖成绩"。
    仅纳入有该科百分位、非 excluded 的学生（缺交为 0 也计入）。按 r 降序。
    """
    from app.db.models import SubjectScore

    if not start or not end:
        sem = get_semester(db)
        start, end = sem["semester_start"], sem["semester_end"]
    if exam_id is None:
        exam_id = _latest_exam_id(db)

    excluded = {
        r.student_id
        for r in db.query(ClassRoster).filter(
            ClassRoster.class_num == class_num, ClassRoster.excluded == 1
        ).all()
    }

    # 一次取全学期缺交，按 (科目, 学生) 计数
    miss_rows = _base_miss_query(db, start, end, respect_excluded=True).all()
    miss_by_subj_sid = defaultdict(lambda: defaultdict(int))
    for rec, _ in miss_rows:
        miss_by_subj_sid[normalize_subject(rec.subject)][rec.student_id] += 1

    results = []
    for subject in ACADEMIC_SUBJECTS:
        score_rows = []
        if exam_id is not None:
            score_rows = db.query(SubjectScore).filter(
                SubjectScore.exam_id == exam_id,
                SubjectScore.subject == subject,
            ).all()
        miss_map = miss_by_subj_sid.get(subject, {})
        xs, ys = [], []
        for s in score_rows:
            if s.student_id in excluded or s.grade_percentile is None:
                continue
            xs.append(miss_map.get(s.student_id, 0))
            ys.append(s.grade_percentile)
        r = _pearson(xs, ys)
        results.append({"subject": subject, "r": r, "n": len(xs)})

    # r 降序；None（样本不足）排末尾
    results.sort(key=lambda x: (x["r"] is None, -(x["r"] or 0)))
    return {
        "class_num": class_num,
        "exam_id": exam_id,
        "semester": {"start": start, "end": end},
        "rankings": results,
        "note": "r 为皮尔逊相关系数，正值越大表示该科缺交越多、年级百分位越大（成绩越差），即缺交越拖该科成绩；n 为样本数，n<3 记 r=null。作业数据仅反映缺交，不代表完成质量。",
    }


def weekly_focus(db, class_num=6, today=None):
    """本周关注名单：合并连续缺交预警、本周缺交激增、最近一次考试临界/薄弱/
    偏科、谈话跟进待办。主要由缺交信号驱动，不依赖新考试。"""
    from datetime import date, timedelta

    from app.db.models import StudentNote

    sem = get_semester(db)
    start, end = sem["semester_start"], sem["semester_end"]
    today = today or date.today().isoformat()
    week_start = (date.fromisoformat(today) - timedelta(days=6)).isoformat()

    roster = {
        r.student_id: r
        for r in db.query(ClassRoster).filter(
            ClassRoster.class_num == class_num, ClassRoster.excluded == 0
        ).all()
    }
    reasons = defaultdict(list)  # student_id -> [理由标签]

    def add(sid, tag, weight):
        if sid in roster:
            reasons[sid].append({"tag": tag, "weight": weight})

    # ① 连续缺交预警（取每生最高连续次数）
    w = warnings(db, start, end)
    best = {}
    for item in w["serious"] + w["warning"]:
        sid = item.get("student_id")
        if sid and (sid not in best or item["streak"] > best[sid]["streak"]):
            best[sid] = item
    for sid, item in best.items():
        sev = 3 if item["streak"] >= 3 else 2
        add(sid, f"连续缺交{item['streak']}次（{item['subject']}）", sev)

    # ② 本周缺交激增
    miss_rows = _base_miss_query(db, start, end, respect_excluded=True).all()
    total_by_sid = defaultdict(int)
    week_by_sid = defaultdict(int)
    for rec, _ in miss_rows:
        total_by_sid[rec.student_id] += 1
        if week_start <= rec.date <= today:
            week_by_sid[rec.student_id] += 1
    weeks_elapsed = max(1, (date.fromisoformat(min(today, end)) - date.fromisoformat(start)).days / 7)
    for sid, wk in week_by_sid.items():
        avg = total_by_sid[sid] / weeks_elapsed
        if wk >= 3 and wk >= 2 * max(avg, 0.5):
            add(sid, f"本周缺交激增（{wk}次）", 2)

    # ③ 最近一次考试的临界/薄弱/偏科（复用 focus_list 口径，过滤到本班）
    try:
        from app.chat.tools import focus_list
        from app.db.models import Exam, TotalScore
        latest = (
            db.query(Exam).join(TotalScore, TotalScore.exam_id == Exam.id)
            .order_by(Exam.exam_date.desc(), Exam.id.desc()).first()
        )
        if latest:
            for row in focus_list(latest.id):
                sid = row.get("student_id")
                if sid in roster and row.get("issues"):
                    add(sid, "、".join(row["issues"]), 1)
    except Exception:
        pass

    # ④ 谈话跟进待办
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
        "class_num": class_num,
        "week": {"start": week_start, "end": today},
        "students": out,
        "note": "合并连续缺交预警、本周缺交激增、最近考试临界/薄弱/偏科、谈话跟进待办。主要由缺交信号驱动，无新考试也每天更新。",
    }
