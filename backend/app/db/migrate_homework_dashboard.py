"""作业仪表盘结构迁移（幂等、保留旧记录）。"""

from datetime import datetime

from sqlalchemy import inspect, text

from app.db.models import (
    Base,
    HomeworkSemester,
    HomeworkSetting,
    SessionLocal,
    engine,
)


def migrate_homework_dashboard():
    Base.metadata.create_all(bind=engine)
    columns = {c["name"] for c in inspect(engine).get_columns("homework_record")}
    additions = {
        "submission_status": "VARCHAR NOT NULL DEFAULT '缺交'",
        "evaluation": "VARCHAR",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE homework_record ADD COLUMN {name} {ddl}"))
        now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        conn.execute(text(
            "UPDATE homework_record SET submission_status='缺交' "
            "WHERE submission_status IS NULL OR submission_status=''"
        ))
        conn.execute(text(
            "UPDATE homework_record SET created_at=:now WHERE created_at IS NULL"
        ), {"now": now})
        conn.execute(text(
            "UPDATE homework_record SET updated_at=:now WHERE updated_at IS NULL"
        ), {"now": now})

    db = SessionLocal()
    try:
        if db.query(HomeworkSemester).count() == 0:
            settings = {
                row.key: row.value
                for row in db.query(HomeworkSetting).filter(
                    HomeworkSetting.key.in_(
                        ["semester_start", "semester_end", "semester_name"]
                    )
                ).all()
            }
            start = settings.get("semester_start") or "2026-02-17"
            end = settings.get("semester_end") or "2026-07-04"
            name = settings.get("semester_name") or f"{start} 至 {end}"
            db.add(HomeworkSemester(
                name=name, start_date=start, end_date=end, is_current=1
            ))
        db.merge(HomeworkSetting(key="homework_dashboard_schema", value="1"))
        db.commit()
    finally:
        db.close()
