"""Teacher.subject 列迁移（幂等，可反复执行）。

给既有 teacher 表补 subject 列（TEXT, nullable）。旧库无此列时 ALTER TABLE
ADD COLUMN；已有则跳过。不破坏已有数据，补列后默认 NULL。

与 migrate_teaching.py 的 _add_column 同风格，但独立成模块以便单测覆盖。
"""
from __future__ import annotations

from sqlalchemy import inspect, text


def _existing_columns(eng, table_name: str) -> set[str]:
    inspector = inspect(eng)
    return {c["name"] for c in inspector.get_columns(table_name)}


def migrate_teacher_subject(eng, db=None) -> dict:
    """给 teacher 表补 subject 列（幂等）。

    Args:
        eng: SQLAlchemy engine（用于 inspect 列是否存在）。
        db: 可选 session；补列后若有待提交事务会一并提交。

    Returns:
        {"added_columns": [...]} — 本次实际新增的列名列表（空列表表示无需迁移）。
    """
    added: list[str] = []
    if "subject" not in _existing_columns(eng, "teacher"):
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE teacher ADD COLUMN subject TEXT"))
        added.append("teacher.subject")
        if db is not None:
            db.commit()
    return {"added_columns": added}
