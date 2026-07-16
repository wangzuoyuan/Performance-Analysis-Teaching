from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import hashlib

router = APIRouter(tags=["ingest"])

from app.paths import RAW_DIR

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


def _teacher_subject(db) -> str | None:
    """读取教师唯一任教学科（单科教学领域边界）。未配置时返回 None。"""
    from app.db.models import Teacher

    teacher = db.query(Teacher).first()
    return teacher.subject if teacher else None


def parse_and_store(file_path: str, filename: str, parsed: dict, grade: int) -> dict:
    """解析单个 Excel 文件并写库。parsed 提供 semester/exam_type/sort_key/canonical_name。
    返回 {result, detected_class, detected_grade}；调用方负责汇总。

    单学科存储（阶段7）：新上传只持久化教师唯一任教学科的 SubjectScore；混合
    多学科 Excel 中的其他学科与 TotalScore 不得入库。ClassAverage 只保留当前
    subject 的 subject_averages 键，total_averages 不再写。

    领域约束（§3–§9）：
    - detected_class / detected_classes 只从 filtered SubjectScore rows（教师学科
      且 raw_score/grade_score 至少一个非空）推导，不把他科班标签回传前端。
    - raw_score 和 grade_score 均空的 percentile-only 残留行不得入库（§4）。
    - ClassAverage 只写教师学科值真实存在的合法行；total_averages 恒 {}（§5）。
    - Teacher.subject 未设置 或 文件无任教学科真实成绩 → 域错误拒绝 + rollback，
      不创建空 Exam/Upload 业务数据（§6）。
    - sync_members_after_upload 异常不静默吞错（§9）。
    """
    from app.db.models import SessionLocal, Upload, SubjectScore, ClassAverage

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

        # 单学科领域边界：先读教师任教学科，据此过滤。
        teacher_subj = _teacher_subject(db)

        if kind == "student_scores":
            subject_scores = result.get("subject_scores", [])

            # §3+§4：按教师学科过滤，并丢弃 raw_score/grade_score 均空的残留行。
            if teacher_subj:
                subject_scores = [
                    ss for ss in subject_scores
                    if ss.get("subject") == teacher_subj
                    and (ss.get("raw_score") is not None or ss.get("grade_score") is not None)
                ]
            else:
                subject_scores = []

            # §6：教师学科未设置 或 文件无该学科真实成绩 → 域错误拒绝。
            if not teacher_subj:
                raise ValueError("未配置教师任教学科（Teacher.subject），无法确定单学科存储边界")
            if not subject_scores:
                raise ValueError(
                    f"文件未包含任教学科「{teacher_subj}」的真实成绩"
                    f"（raw_score / grade_score 至少需要一个非空）"
                )

            parsed_ok = True
            upload_record = Upload(
                file_path=file_path,
                file_hash=compute_hash(open(file_path, "rb").read()),
                kind=kind,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                parsed_ok=1,
            )
            db.add(upload_record)

            # §3：detected_class / detected_classes 从 filtered rows 推导，
            # 不把他科班标签（如物理科的教学班标签）回传前端。
            out["detected_class"] = detect_class_from_students(subject_scores)
            out["detected_grade"] = grade
            class_nums = sorted({ss.get("class_num") for ss in subject_scores if ss.get("class_num") is not None})
            class_labels = sorted({ss.get("class_label") for ss in subject_scores if ss.get("class_label")})
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
            # §1/§9：写库后只 flush（分配 id、暴露约束错误），不 commit。
            # sync_members_after_upload 成功后才做唯一一次 commit。任何异常
            # rollback 后 Exam/Upload/SubjectScore/TeachingClassMember 全部不留。
            db.flush()
            from app.teaching.service import sync_members_after_upload
            sync_members_after_upload(db, exam)
            db.commit()
            out["result"] = {
                "filename": filename,
                "parsed_ok": True,
                "message": f"解析成功，检测到{len(subject_scores)}条{teacher_subj}成绩 · 归入「{parsed['canonical_name']}」",
                "kind": "student_scores",
                "grade": grade,
                "exam_name": parsed["canonical_name"],
                "subject": teacher_subj,
                "stored_count": len(subject_scores),
            }

        elif kind == "class_averages":
            class_avgs = result.get("class_averages", [])

            # §5：ClassAverage 只保留教师学科值真实存在的合法行；
            # total_averages 恒 {}。
            if teacher_subj:
                filtered_avgs = []
                for ca in class_avgs:
                    raw_subj_avgs = ca.get("subject_averages", {})
                    subj_val = raw_subj_avgs.get(teacher_subj)
                    if subj_val is None:
                        continue  # 该班无教师学科真实均分 → 不写空壳行
                    clabel = ca.get("class_label")
                    if clabel is None and ca.get("class_num") is not None:
                        clabel = str(ca["class_num"])
                    filtered_avgs.append((ca, clabel, {teacher_subj: subj_val}))
            else:
                filtered_avgs = []

            # §6：教师学科未设置 → 域错误拒绝。
            if not teacher_subj:
                raise ValueError("未配置教师任教学科（Teacher.subject），无法确定单学科存储边界")
            if not filtered_avgs:
                raise ValueError(
                    f"均分表未包含任教学科「{teacher_subj}」的真实班级均分"
                )

            parsed_ok = True
            upload_record = Upload(
                file_path=file_path,
                file_hash=compute_hash(open(file_path, "rb").read()),
                kind=kind,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                parsed_ok=1,
            )
            db.add(upload_record)

            exam = get_or_create_exam(db, parsed, grade, file_path)
            upload_record.exam_id = exam.id

            for ca, clabel, subj_avgs in filtered_avgs:
                db.add(ClassAverage(
                    exam_id=exam.id,
                    class_type=ca.get("class_type"),
                    class_num=ca.get("class_num"),
                    class_label=clabel,
                    teacher_name=ca.get("teacher_name"),
                    subject_averages=subj_avgs,
                    total_averages={},
                ))
            # §1：写库后单一 commit；class_averages 路径无 sync 钩子，异常
            # rollback 后 Exam/Upload/ClassAverage 全部不留（含 source_files 改动）。
            db.commit()
            out["result"] = {
                "filename": filename,
                "parsed_ok": True,
                "message": f"解析成功，检测到{len(filtered_avgs)}个班级{teacher_subj}均分 · 归入「{parsed['canonical_name']}」",
                "kind": "class_averages",
                "grade": grade,
                "exam_name": parsed["canonical_name"],
                "subject": teacher_subj,
            }

        else:
            parsed_ok = False
            upload_record = Upload(
                file_path=file_path,
                file_hash=compute_hash(open(file_path, "rb").read()),
                kind=kind or "unknown",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                parsed_ok=0,
                parse_log=result,
            )
            db.add(upload_record)
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
