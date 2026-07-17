"""Teacher.subject 列迁移（幂等，可反复执行）。

给既有 teacher 表补 subject 列（TEXT, nullable）。旧库无此列时 ALTER TABLE
ADD COLUMN；已有则跳过。不破坏已有数据，补列后默认 NULL。

与 migrate_teaching.py 的 _add_column 同风格，但独立成模块以便单测覆盖。
"""
from __future__ import annotations

from sqlalchemy import inspect, text


SUPPORTED_SUBJECTS = frozenset(
    ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]
)


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
    inspector = inspect(eng)
    if "subject" not in _existing_columns(eng, "teacher"):
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE teacher ADD COLUMN subject TEXT"))
        added.append("teacher.subject")
        if db is not None:
            db.commit()

    inferred_subject = None
    backfilled_classes = 0
    if "teaching_class" in inspector.get_table_names():
        with eng.begin() as conn:
            teacher = conn.execute(
                text("SELECT id, subject FROM teacher ORDER BY id LIMIT 1")
            ).mappings().first()
            if teacher and not (teacher["subject"] or "").strip():
                subjects = {
                    row[0].strip()
                    for row in conn.execute(
                        text(
                            "SELECT DISTINCT subject FROM teaching_class "
                            "WHERE subject IS NOT NULL AND trim(subject) <> ''"
                        )
                    )
                    if row[0]
                }
                if len(subjects) == 1 and next(iter(subjects)) in SUPPORTED_SUBJECTS:
                    inferred_subject = next(iter(subjects))
                    conn.execute(
                        text("UPDATE teacher SET subject = :subject WHERE id = :teacher_id"),
                        {"subject": inferred_subject, "teacher_id": teacher["id"]},
                    )
                    result = conn.execute(
                        text(
                            "UPDATE teaching_class SET subject = :subject "
                            "WHERE subject IS NULL OR trim(subject) = ''"
                        ),
                        {"subject": inferred_subject},
                    )
                    backfilled_classes = result.rowcount or 0

    if db is not None:
        db.expire_all()
    return {
        "added_columns": added,
        "inferred_subject": inferred_subject,
        "backfilled_classes": backfilled_classes,
    }
