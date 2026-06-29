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
    get_db,
)
from app.homework import service
from app.homework.export import export_daily_report
from app.homework.parser import (
    is_subject_item,
    parse_homework_item,
    split_colon,
    split_names,
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
                 student: str = "", subject: str = ""):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.kpi(db, s, e, stu, sub)
    finally:
        db.close()


@router.get("/homework/trend")
async def hw_trend(start_date: str = "", end_date: str = "",
                   student: str = "", subject: str = ""):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.trend(db, s, e, stu, sub)
    finally:
        db.close()


@router.get("/homework/subjects")
async def hw_subjects(start_date: str = "", end_date: str = "",
                      student: str = "", subject: str = ""):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.subjects(db, s, e, stu, sub)
    finally:
        db.close()


@router.get("/homework/rankings")
async def hw_rankings(start_date: str = "", end_date: str = "",
                      student: str = "", subject: str = "", limit: int = 10):
    db = next(get_db())
    try:
        s, e, stu, sub = _filters(start_date, end_date, student, subject, db)
        return service.rankings(db, s, e, stu, sub, limit)
    finally:
        db.close()


@router.get("/homework/warnings")
async def hw_warnings():
    db = next(get_db())
    try:
        sem = service.get_semester(db)
        return service.warnings(db, sem["semester_start"], sem["semester_end"])
    finally:
        db.close()


@router.get("/homework/correlation")
async def hw_correlation(class_num: int = 6, exam_id: Optional[int] = None,
                         total_type: str = "主三门", subject: str = ""):
    db = next(get_db())
    try:
        return service.grade_correlation(
            db, class_num, exam_id, total_type, subject=subject or None
        )
    finally:
        db.close()


@router.get("/homework/correlation/subjects")
async def hw_correlation_subjects(class_num: int = 6, exam_id: Optional[int] = None):
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
async def weekly_focus(class_num: int = 6):
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


def _find_student_id(db, name):
    row = db.query(ClassRoster).filter(ClassRoster.name == name).first()
    return row.student_id if row else None


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
                        sid = _find_student_id(db, name)
                        if not sid:
                            errors.append(f"找不到学生: {name}")
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
                        sid = _find_student_id(db, name)
                        if not sid:
                            errors.append(f"找不到学生: {name}")
                            continue
                        db.add(HomeworkRecord(student_id=sid, date=date, subject=subj,
                                              content=content, remark=remark))
                        added += 1
            else:
                # 学生：科目1、科目2 / 情况
                name = left
                sid = _find_student_id(db, name)
                if not sid:
                    errors.append(f"找不到学生: {name}")
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
                                              content=content, remark=remark))
                        added += 1
        db.commit()
        if added > 0:
            export_daily_report(date, db=db)
        return {"success": True, "added_count": added, "errors": errors}
    finally:
        db.close()


class SpecialPayload(BaseModel):
    raw_text: str
    date: Optional[str] = None
    mode: str = "by_student"  # by_student | by_type


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
                    sid = _find_student_id(db, name)
                    if not sid:
                        errors.append(f"找不到学生: {name}")
                        continue
                    db.add(SpecialRecord(student_id=sid, date=date, type=left, note=None))
                    added += 1
            else:
                sid = _find_student_id(db, left)
                if not sid:
                    errors.append(f"找不到学生: {left}")
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
                         start_date: str = "", end_date: str = ""):
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

        records = [
            {"id": r.id, "name": roster.name, "date": r.date, "subject": r.subject,
             "content": r.content or "", "remark": r.remark or "", "is_special": False}
            for r, roster in rec_q.order_by(HomeworkRecord.date.desc()).limit(200).all()
        ]
        specials = []
        if include_specials:
            specials = [
                {"id": sr.id, "name": roster.name, "date": sr.date, "subject": "",
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
