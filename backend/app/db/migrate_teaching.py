"""教学版一次性数据迁移（幂等，可反复执行）。

把班主任版（单班）旧库平滑升级为教学版（多教学班）：
1. `Base.metadata.create_all()` 建新表：teaching_class / teaching_class_member /
   student_identity / student_alias（create_all 本身幂等）。
2. 给既有表补列：subject_score / class_average / class_roster 的 class_label，
   teacher 的 current_teaching_class_id（先 PRAGMA table_info 判存在，再 ADD COLUMN）。
3. 数据回填（仅首次升级、且老师尚未配置任何教学班时）：
   - 旧 teacher.target_class_highN → teaching_class(行政) + source=class_num 成员；
   - class_average.class_label 缺省回填为 str(class_num)。
4. 用 homework_setting.schema_version 标记，便于排查。

参考既有 homework/migrate.py 的幂等风格。
"""
from __future__ import annotations

from sqlalchemy import text

from app.db.models import (
    Base,
    ClassAverage,
    HomeworkSetting,
    SubjectScore,
    Teacher,
    TeachingClass,
    TeachingClassMember,
    engine,
    SessionLocal,
)

SCHEMA_VERSION = "teaching_v1"


def _existing_columns(db, table_name: str) -> set[str]:
    rows = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def _add_column(db, table_name: str, column: str, ddl: str) -> bool:
    """给已有表加列，已存在则跳过。返回是否新增。"""
    if column in _existing_columns(db, table_name):
        return False
    db.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {ddl}"))
    return True


def _backfill_from_old_target_class(db) -> int:
    """把旧单班配置升级为一个行政教学班 + class_num 来源成员。仅当老师尚无任何
    教学班时执行一次（首次升级）。返回新建教学班数。"""
    if db.query(TeachingClass).count() > 0:
        return 0
    teacher = db.query(Teacher).first()
    if not teacher:
        return 0

    created = 0
    for grade, col in ((1, "target_class_high1"), (2, "target_class_high2"), (3, "target_class_high3")):
        class_num_value = getattr(teacher, col, None)
        if class_num_value is None:
            continue
        label = str(int(class_num_value))
        tc = TeachingClass(grade=grade, label=label, kind="行政", sort_order=created)
        db.add(tc)
        db.flush()
        # 该年级该 class_num 的全部学号作为成员（source=class_num）
        sids = {
            row[0]
            for row in db.query(SubjectScore.student_id)
            .filter(SubjectScore.class_num == int(class_num_value))
            .distinct()
            .all()
        }
        for sid in sids:
            db.add(
                TeachingClassMember(
                    teaching_class_id=tc.id,
                    student_id=sid,
                    source="class_num",
                )
            )
        created += 1
    return created


def _backfill_class_average_labels(db) -> int:
    """class_average.class_label 为空时回填 str(class_num)。只动 NULL 行，幂等。"""
    rows = db.query(ClassAverage).filter(ClassAverage.class_label.is_(None)).all()
    updated = 0
    for row in rows:
        if row.class_num is not None:
            row.class_label = str(int(row.class_num))
            updated += 1
    return updated


def _backfill_member_names(db) -> int:
    """teaching_class_member.name 为空时，按学号反查姓名回填（仅 NULL 行，幂等）。
    新增 name 列后让旧成员也能直接展示姓名，与「仅姓名录入」的新成员一致。"""
    # 延迟导入：service 依赖 analysis.scope（函数内 import），此处安全
    from app.teaching.service import student_name, ANON_PREFIX

    rows = db.query(TeachingClassMember).filter(TeachingClassMember.name.is_(None)).all()
    updated = 0
    for row in rows:
        if row.student_id and row.student_id.startswith(ANON_PREFIX):
            # 仅姓名占位学号：姓名即后缀
            row.name = row.student_id[len(ANON_PREFIX):]
            updated += 1
            continue
        nm = student_name(db, row.student_id)
        if nm:
            row.name = nm
            updated += 1
    return updated


def migrate_teaching(db=None) -> dict:
    """执行教学版迁移。db 为空时自建 session。返回各步骤计数，便于日志/排查。"""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        # 1) 建新表（幂等）
        Base.metadata.create_all(bind=engine)

        # 2) 补列
        added_columns = []
        added_columns.append(("subject_score", "class_label", _add_column(db, "subject_score", "class_label", "TEXT")))
        added_columns.append(("class_average", "class_label", _add_column(db, "class_average", "class_label", "TEXT")))
        added_columns.append(("class_roster", "class_label", _add_column(db, "class_roster", "class_label", "TEXT")))
        added_columns.append(("teacher", "current_teaching_class_id", _add_column(db, "teacher", "current_teaching_class_id", "INTEGER")))
        added_columns.append(("teaching_class_member", "name", _add_column(db, "teaching_class_member", "name", "TEXT")))

        # 3) 回填
        new_classes = _backfill_from_old_target_class(db)
        relabeled = _backfill_class_average_labels(db)
        named_members = _backfill_member_names(db)

        # 4) 版本标记
        marker = db.query(HomeworkSetting).filter(HomeworkSetting.key == "schema_version").first()
        if not marker:
            db.add(HomeworkSetting(key="schema_version", value=SCHEMA_VERSION))
        else:
            marker.value = SCHEMA_VERSION

        db.commit()
        return {
            "added_columns": [name for name, _, added in added_columns if added],
            "new_teaching_classes": new_classes,
            "relabelled_class_averages": relabeled,
            "named_members": named_members,
            "schema_version": SCHEMA_VERSION,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    result = migrate_teaching()
    print("教学版迁移完成：", result)
