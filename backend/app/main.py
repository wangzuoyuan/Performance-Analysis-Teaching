from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import os

from starlette.responses import JSONResponse as _JSONResponse  # noqa: E402

app = FastAPI(title="成绩追踪 API", version="0.1.0")

# 生产同源（经反代）时无需 CORS；本地 dev 前端 3000 → 后端 8000 跨源需放行。
# 额外可用 CORS_ORIGINS（逗号分隔）显式追加来源。
_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"http://[\w.\-]+:3000",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 登录鉴权：内网免登录、外网（命中 PUBLIC_HOST）才要求会话。
from app.auth import COOKIE_NAME, auth_required_for, verify_token  # noqa: E402

_AUTH_ALLOWLIST = {"/api/login", "/api/logout", "/api/auth/status", "/api/health"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if (
        request.method != "OPTIONS"
        and path.startswith("/api")
        and path not in _AUTH_ALLOWLIST
        and auth_required_for(request)
        and not verify_token(request.cookies.get(COOKIE_NAME, ""))
    ):
        return _JSONResponse({"detail": "需要登录"}, status_code=401)
    return await call_next(request)

from app.paths import DATA_DIR as EXAM_TRACKER_DIR
os.makedirs(EXAM_TRACKER_DIR, exist_ok=True)
os.makedirs(f"{EXAM_TRACKER_DIR}/raw", exist_ok=True)

@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.1.0"}

@app.get("/")
def root():
    return {"message": "成绩追踪 API", "docs": "/docs"}

@app.get("/api/teacher")
def get_teacher():
    """获取老师信息（延迟初始化）。教学版：返回当前教学班 + 已配置班级数；
    保留 target_class_highN 字段以兼容旧库（不再读写）。"""
    from app.db.models import SessionLocal, Teacher, TeachingClass
    db = SessionLocal()
    teacher = db.query(Teacher).first()
    if not teacher:
        teacher = Teacher()
        db.add(teacher)
        db.commit()
        db.refresh(teacher)
    class_count = db.query(TeachingClass).count()
    db.close()
    return {
        "id": teacher.id,
        "name": teacher.name,
        "current_teaching_class_id": teacher.current_teaching_class_id,
        "class_count": class_count,
        # 兼容旧字段（教学版不再使用）
        "target_class_high1": teacher.target_class_high1,
        "target_class_high2": teacher.target_class_high2,
        "target_class_high3": teacher.target_class_high3,
    }

@app.patch("/api/teacher")
async def update_teacher(request: Request):
    """更新老师姓名"""
    from app.db.models import SessionLocal, Teacher
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid json")
    name = body.get("name", "").strip()
    db = SessionLocal()
    teacher = db.query(Teacher).first()
    if not teacher:
        teacher = Teacher()
        db.add(teacher)
    teacher.name = name or None
    db.commit()
    db.close()
    return {"ok": True, "name": name or None}

@app.post("/api/teacher/bind-class")
async def bind_class(request: Request, class_num: Optional[int] = None, grade: int = 1):
    """[已弃用] 班主任版单班绑定。教学版改用 /api/teaching/* 配置教学班。
    保留端点返回 ok，避免旧前端流程硬中断；不再写入任何字段。"""
    return {"ok": True, "deprecated": True, "message": "教学版请改用 /api/teaching 配置教学班"}

# 路由模块导入
from app.db.models import Base, engine  # noqa
Base.metadata.create_all(bind=engine)

# 教学版迁移：建新表 + 补列 + 旧单班配置回填（幂等）
from app.db.migrate_teaching import migrate_teaching  # noqa
migrate_teaching()

# 作业仪表盘迁移：旧缺交记录原样保留并补齐状态/时间戳，学期配置迁入历史表。
from app.db.migrate_homework_dashboard import migrate_homework_dashboard  # noqa
migrate_homework_dashboard()

from app.ingest.router import router as ingest_router  # noqa
from app.analysis.router import router as analysis_router  # noqa
from app.chat.session import router as chat_router  # noqa
from app.homework.router import router as homework_router  # noqa
from app.notes.router import router as notes_router  # noqa
from app.backup.router import router as backup_router  # noqa
from app.teaching.router import router as teaching_router  # noqa
from app.auth_router import router as auth_router  # noqa

app.include_router(auth_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(homework_router, prefix="/api")
app.include_router(notes_router, prefix="/api")
app.include_router(backup_router, prefix="/api")
app.include_router(teaching_router, prefix="/api")
