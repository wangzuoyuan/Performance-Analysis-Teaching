"""作业跟踪 REST 路由（/api/homework 前缀）。

由原「作业跟踪」Flask app.py 全部端点迁移而来，数据访问改为 SQLAlchemy、
学生关联键改为真实学号。聚合查询委托给 service.py。
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.db.models import (
    ClassRoster,
    HomeworkRecord,
    SpecialRecord,
    TeachingClass,
    TeachingClassMember,
    get_db,
)
from app.analysis.scope import student_class_map_multi
from app.homework import service
from app.homework.export import export_daily_report
from app.homework.parser import (
    is_subject_item,
    parse_homework_item,
    split_colon,
    split_names,
    parse_name_action,
)

router = APIRouter(tags=["homework"])


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _filters(start_date, end_date, student, subject, db):
    """缺看板筛选：未给日期时回落到学期区间。"""
    sem = service.get_semester(db)
    return (
        start_date or sem["semester_start"],
        end_date or sem["semester_end"],
        student or None,
        subject or None,
    )


# ─────────────────────────── 看板统计 ───────────────────────────

@router.get("/homework/kpi")
async def hw_kpi(start_date: str = "", end_date: str = "",
                 student: str = "", subject: str = "",
                 teaching_class_id: Optional[int] = None):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.kpi(db, s, e, stu, sub, teaching_class_id)
    finally:
        db.close()


@router.get("/homework/trend")
async def hw_trend(start_date: str = "", end_date: str = "",
                   student: str = "", subject: str = "",
                   teaching_class_id: Optional[int] = None):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.trend(db, s, e, stu, sub, teaching_class_id)
    finally:
        db.close()


@router.get("/homework/subjects")
async def hw_subjects(start_date: str = "", end_date: str = "",
                      student: str = "", subject: str = "",
                      teaching_class_id: Optional[int] = None):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.subjects(db, s, e, stu, sub, teaching_class_id)
    finally:
        db.close()


@router.get("/homework/rankings")
async def hw_rankings(start_date: str = "", end_date: str = "",
                      student: str = "", subject: str = "", limit: int = 10,
                      teaching_class_id: Optional[int] = None):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.rankings(db, s, e, stu, sub, limit, teaching_class_id)
    finally:
        db.close()


@router.get("/homework/warnings")
async def hw_warnings(start_date: str = "", end_date: str = "",
                      teaching_class_id: Optional[int] = None):
    db = next(get_db())
    try:
        sem = service.get_semester(db)
        return service.warnings(
            db,
            start_date or sem["semester_start"],
            end_date or sem["semester_end"],
            teaching_class_id,
        )
    finally:
        db.close()


@router.get("/homework/dashboard")
async def hw_dashboard(start_date: str = "", end_date: str = "", student: str = "",
                       teaching_class_id: Optional[int] = None,
                       group_by: str = Query("week", pattern="^(week|month)$")):
    db = next(get_db())
    try:
        if teaching_class_id is not None and not db.query(TeachingClass).filter(
            TeachingClass.id == teaching_class_id
        ).first():
            raise HTTPException(404, "教学班不存在")
        s, e, stu, _ = _filters(start_date, end_date, student, "", db)
        return service.dashboard(db, s, e, stu, teaching_class_id, group_by)
    finally:
        db.close()


@router.get("/homework/correlation")
async def hw_correlation(class_num: Optional[int] = None, exam_id: Optional[int] = None,
                         total_type: str = "主三门", subject: str = ""):
    db = next(get_db())
    try:
        return service.grade_correlation(
            db, class_num, exam_id, total_type, subject=subject or None
        )
    finally:
        db.close()


@router.get("/homework/correlation/subjects")
async def hw_correlation_subjects(class_num: Optional[int] = None, exam_id: Optional[int] = None):
    db = next(get_db())
    try:
        return service.subject_correlation_ranking(db, class_num, exam_id)
    finally:
        db.close()


@router.get("/homework/student/{student_id}")
async def hw_student_summary(student_id: str):
    """单个学生作业概况（供学生画像页作业卡片）。"""
    db = next(get_db())
    try:
        return service.student_summary(db, student_id=student_id)
    finally:
        db.close()


@router.get("/weekly-focus")
async def weekly_focus(class_num: Optional[int] = None):
    """本周关注名单（仪表盘主动提醒）。"""
    db = next(get_db())
    try:
        return service.weekly_focus(db, class_num)
    finally:
        db.close()


# ─────────────────────────── 录入 ───────────────────────────

class RecordsPayload(BaseModel):
    raw_text: str
    date: Optional[str] = None
    mode: str = "by_student"  # by_student | by_subject
    teaching_class_id: Optional[int] = None


def _student_matches(db, name, teaching_class_id=None):
    q = db.query(ClassRoster)
    if teaching_class_id is not None:
        q = q.join(
            TeachingClassMember,
            TeachingClassMember.student_id == ClassRoster.student_id,
        ).filter(TeachingClassMember.teaching_class_id == teaching_class_id)
    else:
        q = q.filter(ClassRoster.student_id.in_(service._scope_student_ids(db)))
    return q.filter(ClassRoster.name == name).all()


def _resolve_student(db, name, teaching_class_id=None):
    """按姓名解析学号，返回 (student_id, error)。同名时给出明确提示而非「找不到」。"""
    matches = _student_matches(db, name, teaching_class_id)
    if not matches:
        return None, f"找不到学生: {name}"
    if len(matches) > 1:
        return None, f"同名学生: {name}（请改用智能录入，以「学号 姓名+动作」消歧）"
    return matches[0].student_id, None


@router.post("/homework/records")
async def hw_add_records(payload: RecordsPayload):
    if not payload.raw_text.strip():
        raise HTTPException(400, "请输入记录内容")
    date = payload.date or _today()
    db = next(get_db())
    added = 0
    errors = []
    try:
        lines = [l.strip() for l in payload.raw_text.split("\n") if l.strip()]
        for line in lines:
            parts = split_colon(line)
            if not parts:
                errors.append(f"格式错误: {line}")
                continue
            left, right = parts

            if payload.mode == "by_subject":
                # 学科/情况：学生1、学生2
                names = split_names(right)
                if not is_subject_item(left):
                    for name in names:
                        sid, err = _resolve_student(db, name, payload.teaching_class_id)
                        if not sid:
                            errors.append(err)
                            continue
                        db.add(SpecialRecord(student_id=sid, date=date, type=left, note=None))
                        added += 1
                else:
                    parsed = parse_homework_item(left)
                    if not parsed:
                        errors.append(f"无法识别科目: {left}")
                        continue
                    subj, content, remark = parsed
                    for name in names:
                        sid, err = _resolve_student(db, name, payload.teaching_class_id)
                        if not sid:
                            errors.append(err)
                            continue
                        db.add(HomeworkRecord(student_id=sid, date=date, subject=subj,
                                              content=content, remark=remark,
                                              submission_status="缺交"))
                        added += 1
            else:
                # 学生：科目1、科目2 / 情况
                name = left
                sid, err = _resolve_student(db, name, payload.teaching_class_id)
                if not sid:
                    errors.append(err)
                    continue
                for item in split_names(right):
                    if not is_subject_item(item):
                        db.add(SpecialRecord(student_id=sid, date=date, type=item, note=None))
                        added += 1
                    else:
                        parsed = parse_homework_item(item)
                        if not parsed:
                            continue
                        subj, content, remark = parsed
                        db.add(HomeworkRecord(student_id=sid, date=date, subject=subj,
                                              content=content, remark=remark,
                                              submission_status="缺交"))
                        added += 1
        db.commit()
        if added > 0:
            export_daily_report(date, db=db)
        return {"success": True, "added_count": added, "errors": errors}
    finally:
        db.close()


class SmartInputPayload(BaseModel):
    raw_text: str
    date: Optional[str] = None
    teaching_class_id: int
    confirm: bool = False


@router.post("/homework/smart-input")
async def hw_smart_input(payload: SmartInputPayload):
    if not payload.raw_text.strip():
        raise HTTPException(400, "请输入记录内容")
    db = next(get_db())
    try:
        if not db.query(TeachingClass).filter(
            TeachingClass.id == payload.teaching_class_id
        ).first():
            raise HTTPException(404, "教学班不存在")
        members = (
            db.query(ClassRoster)
            .join(TeachingClassMember, TeachingClassMember.student_id == ClassRoster.student_id)
            .filter(TeachingClassMember.teaching_class_id == payload.teaching_class_id)
            .all()
        )
        by_name = {}
        for member in members:
            by_name.setdefault(member.name, []).append(member)
        by_id = {member.student_id: member for member in members}
        parsed = []
        for line in payload.raw_text.splitlines():
            if not line.strip():
                continue
            stripped = line.strip()
            explicit = next(
                (sid for sid in sorted(by_id, key=len, reverse=True)
                 if stripped.startswith(sid)),
                None,
            )
            parse_text = stripped[len(explicit):].strip() if explicit else stripped
            item = parse_name_action(parse_text, by_name.keys())
            if explicit and not item.get("error"):
                item["explicit_student_id"] = explicit
            parsed.append(item)
        errors = []
        preview = []
        for item in parsed:
            if item.get("error"):
                errors.append({"raw": item["raw"], "message": item["error"]})
                continue
            matches = by_name[item["name"]]
            explicit_sid = item.pop("explicit_student_id", None)
            if explicit_sid:
                if by_id[explicit_sid].name != item["name"]:
                    errors.append({
                        "raw": item["raw"],
                        "message": "学号与姓名不匹配",
                    })
                    continue
                matches = [by_id[explicit_sid]]
            if len(matches) > 1:
                errors.append({
                    "raw": item["raw"],
                    "message": "当前教学班有同名学生，请改用“学号 姓名+动作”",
                    "candidates": [
                        {"student_id": r.student_id, "name": r.name} for r in matches
                    ],
                })
                continue
            item["student_id"] = matches[0].student_id
            preview.append(item)
        if not payload.confirm:
            return {"success": not errors, "preview": preview, "errors": errors}
        if errors:
            raise HTTPException(422, {"message": "存在未匹配或同名记录", "errors": errors})
        target_date = payload.date or _today()
        try:
            for item in preview:
                if item["special_type"]:
                    db.add(SpecialRecord(
                        student_id=item["student_id"], date=target_date,
                        type=item["special_type"], note=item["content"] or None,
                    ))
                    if item["special_type"] == "请假":
                        continue
                db.add(HomeworkRecord(
                    student_id=item["student_id"], date=target_date,
                    subject=item["subject"] or "综合",
                    content=item["content"] or None,
                    submission_status=item["submission_status"],
                    evaluation=item["evaluation"] or None,
                ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        if preview:
            export_daily_report(target_date, db=db)
        return {"success": True, "added_count": len(preview), "errors": []}
    finally:
        db.close()


class SpecialPayload(BaseModel):
    raw_text: str
    date: Optional[str] = None
    mode: str = "by_student"  # by_student | by_type
    teaching_class_id: Optional[int] = None


@router.post("/homework/special-records")
async def hw_add_special(payload: SpecialPayload):
    if not payload.raw_text.strip():
        raise HTTPException(400, "请输入记录内容")
    date = payload.date or _today()
    db = next(get_db())
    added = 0
    errors = []
    try:
        for line in [l.strip() for l in payload.raw_text.split("\n") if l.strip()]:
            parts = split_colon(line)
            if not parts:
                errors.append(f"格式错误: {line}")
                continue
            left, right = parts
            if payload.mode == "by_type":
                for name in split_names(right):
                    sid, err = _resolve_student(db, name, payload.teaching_class_id)
                    if not sid:
                        errors.append(err)
                        continue
                    db.add(SpecialRecord(student_id=sid, date=date, type=left, note=None))
                    added += 1
            else:
                sid, err = _resolve_student(db, left, payload.teaching_class_id)
                if not sid:
                    errors.append(err)
                    continue
                for rec_type in split_names(right):
                    db.add(SpecialRecord(student_id=sid, date=date, type=rec_type, note=None))
                    added += 1
        db.commit()
        return {"success": True, "added_count": added, "errors": errors}
    finally:
        db.close()


@router.get("/homework/special-records")
async def hw_get_special(date: str = ""):
    target = date or _today()
    db = next(get_db())
    try:
        rows = (
            db.query(SpecialRecord, ClassRoster)
            .join(ClassRoster, ClassRoster.student_id == SpecialRecord.student_id)
            .filter(SpecialRecord.date == target)
            .order_by(SpecialRecord.type, ClassRoster.name)
            .all()
        )
        return [
            {"id": sr.id, "name": roster.name, "date": sr.date, "type": sr.type, "note": sr.note}
            for sr, roster in rows
        ]
    finally:
        db.close()


@router.delete("/homework/special-records/{record_id}")
async def hw_delete_special(record_id: int):
    db = next(get_db())
    try:
        db.query(SpecialRecord).filter(SpecialRecord.id == record_id).delete()
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ─────────────────────────── 记录管理 ───────────────────────────

@router.get("/homework/manage/records")
async def hw_manage_list(date: str = "", student: str = "", subject: str = "",
                         start_date: str = "", end_date: str = "",
                         teaching_class_id: Optional[int] = None):
    from sqlalchemy import or_
    from app.homework.service import _subject_keywords

    db = next(get_db())
    try:
        rec_q = (
            db.query(HomeworkRecord, ClassRoster)
            .join(ClassRoster, ClassRoster.student_id == HomeworkRecord.student_id)
        )
        sp_q = (
            db.query(SpecialRecord, ClassRoster)
            .join(ClassRoster, ClassRoster.student_id == SpecialRecord.student_id)
        )
        # 记录管理是运维视角：excluded 学生的历史记录也要能查到、能改能删
        scope_ids = service._scope_student_ids(db, teaching_class_id, include_excluded=True)
        rec_q = rec_q.filter(HomeworkRecord.student_id.in_(scope_ids))
        sp_q = sp_q.filter(SpecialRecord.student_id.in_(scope_ids))
        if start_date and end_date:
            rec_q = rec_q.filter(HomeworkRecord.date >= start_date, HomeworkRecord.date <= end_date)
            sp_q = sp_q.filter(SpecialRecord.date >= start_date, SpecialRecord.date <= end_date)
        elif date:
            rec_q = rec_q.filter(HomeworkRecord.date == date)
            sp_q = sp_q.filter(SpecialRecord.date == date)
        if student:
            rec_q = rec_q.filter(ClassRoster.name.like(f"%{student}%"))
            sp_q = sp_q.filter(ClassRoster.name.like(f"%{student}%"))

        # 按学科过滤：只看该科缺交记录，不含无学科的特殊记录
        include_specials = True
        if subject:
            include_specials = False
            keywords = _subject_keywords(subject)
            if keywords:
                rec_q = rec_q.filter(or_(*[HomeworkRecord.subject.like(f"%{k}%") for k in keywords]))
            else:
                rec_q = rec_q.filter(HomeworkRecord.subject == subject)

        labels = student_class_map_multi(db)
        records = [
            {"id": r.id, "student_id": roster.student_id, "name": roster.name,
             "class_labels": service._labels_for(labels, roster.student_id),
             "date": r.date, "subject": r.subject,
             "content": r.content or "", "remark": r.remark or "",
             "submission_status": r.submission_status, "evaluation": r.evaluation or "",
             "created_at": r.created_at, "updated_at": r.updated_at,
             "is_special": False}
            for r, roster in rec_q.order_by(HomeworkRecord.date.desc()).limit(200).all()
        ]
        specials = []
        if include_specials:
            specials = [
                {"id": sr.id, "student_id": roster.student_id, "name": roster.name,
                 "class_labels": service._labels_for(labels, roster.student_id),
                 "date": sr.date, "subject": "",
                 "content": sr.note or "", "remark": sr.type, "is_special": True}
                for sr, roster in sp_q.order_by(SpecialRecord.date.desc()).limit(200).all()
            ]
        allr = sorted(records + specials, key=lambda x: (x["date"], x["name"]), reverse=True)
        return allr
    finally:
        db.close()


class UpdateRecordPayload(BaseModel):
    subject: str = ""
    content: str = ""
    remark: str = ""
    submission_status: str = "缺交"
    evaluation: str = ""


@router.put("/homework/manage/records/{record_id}")
async def hw_manage_update(record_id: int, payload: UpdateRecordPayload):
    db = next(get_db())
    try:
        rec = db.query(HomeworkRecord).filter(HomeworkRecord.id == record_id).first()
        if not rec:
            raise HTTPException(404, "记录不存在")
        rec.subject = payload.subject
        rec.content = payload.content
        rec.remark = payload.remark
        rec.submission_status = payload.submission_status
        rec.evaluation = payload.evaluation or None
        db.commit()
        export_daily_report(rec.date, db=db)
        return {"success": True}
    finally:
        db.close()


@router.delete("/homework/manage/records/{record_id}")
async def hw_manage_delete(record_id: int):
    db = next(get_db())
    try:
        rec = db.query(HomeworkRecord).filter(HomeworkRecord.id == record_id).first()
        rec_date = rec.date if rec else None
        if rec:
            db.delete(rec)
            db.commit()
        if rec_date:
            export_daily_report(rec_date, db=db)
        return {"success": True}
    finally:
        db.close()


# ─────────────────────────── 花名册 ───────────────────────────

@router.get("/homework/roster")
async def hw_roster():
    db = next(get_db())
    try:
        rows = db.query(ClassRoster).order_by(
            ClassRoster.excluded.asc(), ClassRoster.seat_no.asc()
        ).all()
        out = []
        for r in rows:
            count = db.query(HomeworkRecord).filter(
                HomeworkRecord.student_id == r.student_id
            ).count()
            out.append({
                "student_id": r.student_id, "name": r.name, "seat_no": r.seat_no,
                "gender": r.gender, "excluded": r.excluded, "class_num": r.class_num,
                "record_count": count,
            })
        return out
    finally:
        db.close()


class AddStudentPayload(BaseModel):
    name: str
    student_id: Optional[str] = None
    seat_no: Optional[int] = None
    gender: Optional[str] = None
    class_num: int = 6


@router.post("/homework/roster")
async def hw_add_student(payload: AddStudentPayload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    db = next(get_db())
    try:
        if db.query(ClassRoster).filter(ClassRoster.name == name).first():
            raise HTTPException(400, f"学生 {name} 已存在")
        sid = payload.student_id or f"HW-{payload.seat_no or name}"
        db.add(ClassRoster(student_id=sid, name=name, class_num=payload.class_num,
                           seat_no=payload.seat_no, gender=payload.gender, excluded=0))
        db.commit()
        return {"success": True, "student_id": sid}
    finally:
        db.close()


@router.delete("/homework/roster/{student_id}")
async def hw_delete_student(student_id: str):
    db = next(get_db())
    try:
        dates = [
            r[0] for r in db.query(HomeworkRecord.date)
            .filter(HomeworkRecord.student_id == student_id).distinct().all()
        ]
        db.query(HomeworkRecord).filter(HomeworkRecord.student_id == student_id).delete()
        db.query(SpecialRecord).filter(SpecialRecord.student_id == student_id).delete()
        db.query(ClassRoster).filter(ClassRoster.student_id == student_id).delete()
        db.commit()
        for d in dates:
            export_daily_report(d, db=db)
        return {"success": True, "affected_dates": len(dates)}
    finally:
        db.close()


@router.put("/homework/roster/{student_id}/toggle-excluded")
async def hw_toggle_excluded(student_id: str):
    db = next(get_db())
    try:
        r = db.query(ClassRoster).filter(ClassRoster.student_id == student_id).first()
        if not r:
            raise HTTPException(404, "学生不存在")
        r.excluded = 0 if r.excluded else 1
        db.commit()
        return {"success": True, "excluded": r.excluded}
    finally:
        db.close()


# ─────────────────────────── 学期配置 ───────────────────────────

class SemesterPayload(BaseModel):
    semester_start: Optional[str] = None
    semester_end: Optional[str] = None
    semester_name: Optional[str] = None


class NewSemesterPayload(BaseModel):
    name: str
    start_date: str
    end_date: str
    make_current: bool = False


@router.get("/homework/semester")
async def hw_get_semester():
    db = next(get_db())
    try:
        return service.get_semester(db)
    finally:
        db.close()


@router.put("/homework/semester")
async def hw_set_semester(payload: SemesterPayload):
    db = next(get_db())
    try:
        return service.set_semester(db, payload.model_dump(exclude_none=True))
    finally:
        db.close()


@router.get("/homework/semesters")
async def hw_list_semesters():
    db = next(get_db())
    try:
        return service.list_semesters(db)
    finally:
        db.close()


@router.post("/homework/semesters")
async def hw_add_semester(payload: NewSemesterPayload):
    db = next(get_db())
    try:
        try:
            return service.add_semester(
                db, payload.name, payload.start_date, payload.end_date, payload.make_current
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        db.close()


@router.put("/homework/semesters/{semester_id}/current")
async def hw_set_current_semester(semester_id: int):
    db = next(get_db())
    try:
        if not service.set_current_semester(db, semester_id):
            raise HTTPException(404, "学期不存在")
        return service.get_semester(db)
    finally:
        db.close()
