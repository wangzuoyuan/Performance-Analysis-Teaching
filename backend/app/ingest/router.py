from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import hashlib

router = APIRouter(tags=["ingest"])

from app.paths import DATA_DIR as EXAM_TRACKER_DIR
RAW_DIR = f"{EXAM_TRACKER_DIR}/raw"

def save_upload_with_content(filename: str, content: bytes) -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    file_path = f"{RAW_DIR}/{filename}"
    with open(file_path, "wb") as f:
        f.write(content)
    return file_path

def resolve_token_path(token: str) -> str:
    """把前端回传的 token（文件名）还原为 raw/ 下的绝对路径，basename 防路径穿越。"""
    safe_name = os.path.basename(token or "")
    return os.path.join(RAW_DIR, safe_name)

def compute_hash(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()

def detect_class_from_students(students: list) -> int:
    """从学生列表众数统计检测班级号"""
    class_counts = {}
    for s in students:
        cls = s.get("class_num") or s.get("class")
        if cls:
            class_counts[cls] = class_counts.get(cls, 0) + 1
    if class_counts:
        return max(class_counts, key=class_counts.get)
    return 6  # 默认6班

def split_sort_key(sort_key: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """把 'YYYY-MM' 拆成 (year, month)，供前端预填年/月下拉。"""
    if not sort_key or "-" not in sort_key:
        return None, None
    try:
        y, m = sort_key.split("-", 1)
        return int(y), int(m)
    except (ValueError, TypeError):
        return None, None

def get_or_create_exam(db, parsed: dict, grade: int, file_path: str):
    from app.db.models import Exam

    exam = db.query(Exam).filter(
        Exam.grade == grade,
        Exam.semester == (parsed["semester"] or "下"),
        Exam.exam_date == parsed["sort_key"],
        Exam.exam_type == (parsed["exam_type"] or "月考"),
    ).first()
    if not exam:
        exam = Exam(
            name=parsed["canonical_name"],
            grade=grade,
            semester=parsed["semester"] or "下",
            exam_date=parsed["sort_key"],
            exam_type=parsed["exam_type"] or "月考",
            source_files=[file_path],
        )
        db.add(exam)
        db.flush()
    else:
        if exam.name != parsed["canonical_name"]:
            exam.name = parsed["canonical_name"]
        if file_path not in (exam.source_files or []):
            exam.source_files = (exam.source_files or []) + [file_path]
    return exam


def parse_and_store(file_path: str, filename: str, parsed: dict, grade: int) -> dict:
    """解析单个 Excel 文件并写库。parsed 提供 semester/exam_type/sort_key/canonical_name。
    返回 {result, detected_class, detected_grade}；调用方负责汇总。"""
    from app.db.models import SessionLocal, Upload, SubjectScore, TotalScore, ClassAverage

    out = {"result": None, "detected_class": None, "detected_grade": None}

    filename = filename or "upload"
    if not filename.lower().endswith('.xlsx'):
        out["result"] = {
            "filename": filename,
            "parsed_ok": False,
            "message": "暂不支持此文件类型，请上传学生成绩明细表或班级均分表 Excel（.xlsx）",
        }
        return out

    db = SessionLocal()
    try:
        # 根据年级选择解析器
        if grade == 1:
            from app.ingest.excel_parser import parse_excel_grade1
            result = parse_excel_grade1(file_path)
        else:
            from app.ingest.excel_parser import parse_excel_grade23
            result = parse_excel_grade23(file_path, grade)

        kind = result.get("kind")
        parsed_ok = kind in {"student_scores", "class_averages"}

        upload_record = Upload(
            file_path=file_path,
            file_hash=compute_hash(open(file_path, "rb").read()),
            kind=kind or "unknown",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            parsed_ok=1 if parsed_ok else 0,
            parse_log=result if not parsed_ok else None,
        )
        db.add(upload_record)

        if kind == "student_scores":
            students = result.get("students", [])
            subject_scores = result.get("subject_scores", [])
            total_scores = result.get("total_scores", [])

            out["detected_class"] = detect_class_from_students(students)
            out["detected_grade"] = grade
            # 候选班（行政班号 + 教学班标签），供班级配置向导预填
            class_nums = sorted({s.get("class_num") for s in students if s.get("class_num") is not None})
            class_labels = sorted({s.get("class_label") for s in students if s.get("class_label")})
            out["detected_classes"] = {"class_nums": class_nums, "class_labels": class_labels}

            exam = get_or_create_exam(db, parsed, grade, file_path)
            upload_record.exam_id = exam.id

            for ss in subject_scores:
                db.add(SubjectScore(
                    exam_id=exam.id,
                    student_id=ss["student_id"],
                    class_num=ss.get("class_num"),
                    class_label=ss.get("class_label"),
                    xueji=ss.get("xueji"),
                    name=ss.get("name"),
                    subject=ss["subject"],
                    raw_score=ss.get("raw_score"),
                    grade_score=ss.get("grade_score"),
                    grade_percentile=ss.get("grade_percentile"),
                ))

            for ts in total_scores:
                db.add(TotalScore(
                    exam_id=exam.id,
                    student_id=ts["student_id"],
                    total_type=ts["total_type"],
                    total_score=ts.get("total_score"),
                    grade_percentile=ts.get("grade_percentile"),
                    xueji_rank=ts.get("xueji_rank"),
                    grade_rank=ts.get("grade_rank"),
                ))

            db.commit()
            # 上传钩子：按 class_num / class_label 自动维护教学班成员
            try:
                from app.teaching.service import sync_members_after_upload
                sync_members_after_upload(db, exam)
            except Exception:
                pass
            out["result"] = {
                "filename": filename,
                "parsed_ok": True,
                "message": f"解析成功，检测到{len(students)}名学生 · 归入「{parsed['canonical_name']}」",
                "kind": "student_scores",
                "grade": grade,
                "exam_name": parsed["canonical_name"],
            }

        elif kind == "class_averages":
            class_avgs = result.get("class_averages", [])
            exam = get_or_create_exam(db, parsed, grade, file_path)
            upload_record.exam_id = exam.id

            for ca in class_avgs:
                clabel = ca.get("class_label")
                if clabel is None and ca.get("class_num") is not None:
                    clabel = str(ca["class_num"])
                db.add(ClassAverage(
                    exam_id=exam.id,
                    class_type=ca.get("class_type"),
                    class_num=ca.get("class_num"),
                    class_label=clabel,
                    teacher_name=ca.get("teacher_name"),
                    subject_averages=ca.get("subject_averages", {}),
                    total_averages=ca.get("total_averages", {}),
                ))

            db.commit()
            out["result"] = {
                "filename": filename,
                "parsed_ok": True,
                "message": f"解析成功，检测到{len(class_avgs)}个班级均分 · 归入「{parsed['canonical_name']}」",
                "kind": "class_averages",
                "grade": grade,
                "exam_name": parsed["canonical_name"],
            }

        else:
            db.commit()
            out["result"] = {
                "filename": filename,
                "parsed_ok": False,
                "message": f"未知文件类型: {kind}",
            }

    except Exception as e:
        db.rollback()
        out["result"] = {
            "filename": filename,
            "parsed_ok": False,
            "message": str(e),
        }
    finally:
        db.close()

    return out


@router.post("/uploads/preview")
async def preview_files(files: List[UploadFile] = File(...)):
    """阶段一：保存文件并按文件名给出可编辑的元数据建议，不入库。"""
    from app.ingest.filename_parser import parse_filename

    items = []
    for file in files:
        content = await file.read()
        filename = file.filename or "upload"
        save_upload_with_content(filename, content)

        parsed = parse_filename(filename)
        year, month = split_sort_key(parsed.get("sort_key"))
        items.append({
            "token": filename,
            "filename": filename,
            "grade": parsed.get("grade") or 1,
            "semester": parsed.get("semester") or "上",
            "exam_type": parsed.get("exam_type") or "月考",
            "year": year,
            "month": month,
            "canonical_name": parsed.get("canonical_name"),
            "is_xlsx": filename.lower().endswith(".xlsx"),
        })

    return JSONResponse({"files": items})


class CommitItem(BaseModel):
    token: str
    grade: int
    semester: str
    exam_type: str
    year: int
    month: int


class CommitRequest(BaseModel):
    items: List[CommitItem]


@router.post("/uploads/commit")
async def commit_files(payload: CommitRequest):
    """阶段二：按用户确认后的年级/学期/类型/年月正式解析入库。"""
    from app.ingest.filename_parser import build_exam_name

    results = []
    detected_class = None
    detected_grade = None
    all_class_nums: set = set()
    all_class_labels: set = set()

    for item in payload.items:
        file_path = resolve_token_path(item.token)
        if not os.path.exists(file_path):
            results.append({
                "filename": item.token,
                "parsed_ok": False,
                "message": "文件已失效，请重新选择并上传",
            })
            continue

        sort_key = f"{item.year}-{item.month:02d}"
        parsed = {
            "grade": item.grade,
            "semester": item.semester if item.semester in ("上", "下") else "上",
            "exam_type": item.exam_type,
            "sort_key": sort_key,
            "canonical_name": build_exam_name(item.grade, item.semester, item.exam_type, item.month),
        }
        out = parse_and_store(file_path, os.path.basename(item.token), parsed, item.grade)
        results.append(out["result"])
        if out["detected_class"]:
            detected_class = out["detected_class"]
            detected_grade = out["detected_grade"]
        dc = out.get("detected_classes") or {}
        all_class_nums.update(dc.get("class_nums") or [])
        all_class_labels.update(dc.get("class_labels") or [])

    response = {"results": results}
    if detected_class:
        response["detected_class"] = detected_class
        response["detected_grade"] = detected_grade or 1
    response["detected_classes"] = {
        "class_nums": sorted(all_class_nums),
        "class_labels": sorted(all_class_labels),
    }
    return JSONResponse(response)


@router.post("/uploads")
async def upload_files(files: List[UploadFile] = File(...)):
    """旧版一步式上传：完全按文件名自动识别后直接入库（保留向后兼容）。"""
    from app.ingest.filename_parser import parse_filename

    results = []
    detected_class = None
    detected_grade = None

    for file in files:
        content = await file.read()
        filename = file.filename or "upload"
        file_path = save_upload_with_content(filename, content)

        parsed = parse_filename(filename)
        grade = parsed.get("grade") or 1

        out = parse_and_store(file_path, filename, parsed, grade)
        results.append(out["result"])
        if out["detected_class"]:
            detected_class = out["detected_class"]
            detected_grade = out["detected_grade"]

    response = {"results": results}
    if detected_class:
        response["detected_class"] = detected_class
        response["detected_grade"] = detected_grade or 1
    return JSONResponse(response)


@router.get("/uploads")
async def list_uploads():
    """列出已上传文件"""
    from app.db.models import SessionLocal, Upload
    db = SessionLocal()
    uploads = db.query(Upload).order_by(Upload.uploaded_at.desc()).limit(50).all()
    db.close()
    return {
        "uploads": [{
            "id": u.id,
            "filename": u.file_path.split("/")[-1] if u.file_path else "",
            "kind": u.kind,
            "mime": u.mime,
            "parsed_ok": bool(u.parsed_ok),
            "exam_id": u.exam_id,
            "uploaded_at": u.uploaded_at.isoformat() if u.uploaded_at else None,
        } for u in uploads]
    }
