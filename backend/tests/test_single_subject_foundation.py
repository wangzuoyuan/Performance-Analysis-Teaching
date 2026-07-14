"""单科教学领域边界（阶段1）隔离测试。

完全使用内存 SQLite，不依赖也不污染 ~/.exam-tracker/db.sqlite。
覆盖：
- Teacher.subject 字段 + 幂等迁移（补列）
- resolve_teaching_subject 领域函数（未配置/冲突/正常）
- 教师首次设置 subject 回填空班 + 冲突拒绝
- 新建教学班自动继承教师 subject / 未配置 409 / 兼容校验
- 修改教学班禁止改学科
- 全部教学班模式可从教师确定唯一学科
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Teacher, TeachingClass, TeachingClassMember


# ────────────────────────────── 隔离 DB 工具 ──────────────────────────────


def make_db():
    """内存 SQLite，建全部表，返回 session。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def make_legacy_db_without_teacher_subject():
    """模拟旧库：建 teacher 表但不含 subject 列，其余表正常。

    用于验证迁移补列的幂等性。
    """
    eng = create_engine("sqlite:///:memory:")
    # 先正常建表（含 subject 列），再用 SQL 删掉 subject 列模拟旧库。
    # SQLite 不支持 DROP COLUMN（老版本），改用手动重建 teacher 表。
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE teacher_old AS SELECT "
            "id, name, school, target_class_high1, target_class_high2, "
            "target_class_high3, current_teaching_class_id, created_at FROM teacher"
        ))
        conn.execute(text("DROP TABLE teacher"))
        conn.execute(text("ALTER TABLE teacher_old RENAME TO teacher"))
    return eng


# ────────────────────────────── 迁移补列 ──────────────────────────────


class TestTeacherSubjectMigration:
    """Teacher.subject 列迁移：补列幂等，不破坏已有数据。"""

    def test_migration_adds_subject_column_to_legacy_db(self):
        eng = make_legacy_db_without_teacher_subject()
        cols = {c["name"] for c in inspect(eng).get_columns("teacher")}
        assert "subject" not in cols  # 旧库无此列

        # 运行迁移
        from app.teaching.migrate_subject import migrate_teacher_subject

        Session = sessionmaker(bind=eng)
        db = Session()
        result = migrate_teacher_subject(eng, db)
        db.close()

        # 迁移后重新 inspect（inspector 有缓存，必须新建）
        cols = {c["name"] for c in inspect(eng).get_columns("teacher")}
        assert "subject" in cols
        assert result["added_columns"] == ["teacher.subject"]

    def test_migration_is_idempotent(self):
        eng = make_legacy_db_without_teacher_subject()
        from app.teaching.migrate_subject import migrate_teacher_subject

        Session = sessionmaker(bind=eng)
        db = Session()
        migrate_teacher_subject(eng, db)  # 首次
        result2 = migrate_teacher_subject(eng, db)  # 再次
        db.close()

        assert result2["added_columns"] == []  # 第二次无新增

    def test_migration_preserves_existing_teacher_data(self):
        eng = make_legacy_db_without_teacher_subject()
        Session = sessionmaker(bind=eng)
        db = Session()
        # 插入一条旧 teacher（无 subject）
        db.execute(text(
            "INSERT INTO teacher (id, name, school, current_teaching_class_id) "
            "VALUES (1, '张老师', '一中', NULL)"
        ))
        db.commit()

        from app.teaching.migrate_subject import migrate_teacher_subject
        migrate_teacher_subject(eng, db)

        t = db.query(Teacher).first()
        assert t.name == "张老师"
        assert t.school == "一中"
        assert t.subject is None  # 补列后默认 None
        db.close()

    def test_real_app_startup_migrates_subject_before_teacher_query(self, tmp_path):
        """旧库真实启动顺序：补 subject 后才能让后续迁移查询 Teacher ORM。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = data_dir / "db.sqlite"

        # 模拟教学版迁移之前的旧 teacher 表：有旧教师数据，但没有
        # current_teaching_class_id 和 subject 两列。
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """CREATE TABLE teacher (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR,
                    school VARCHAR,
                    target_class_high1 INTEGER,
                    target_class_high2 INTEGER,
                    target_class_high3 INTEGER,
                    created_at DATETIME
                )"""
            )
            conn.execute(
                "INSERT INTO teacher "
                "(id, name, school, target_class_high2) "
                "VALUES (1, '旧教师', '一中', 7)"
            )
            conn.commit()

        env = os.environ.copy()
        env["EXAM_TRACKER_DIR"] = str(data_dir)
        env["EXAM_TRACKER_BACKUP_DIR"] = str(tmp_path / "backups")
        backend_dir = os.path.dirname(os.path.dirname(__file__))
        proc = subprocess.run(
            [sys.executable, "-c", "import app.main; print('startup-ok')"],
            cwd=backend_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )

        assert proc.returncode == 0, proc.stdout
        assert "startup-ok" in proc.stdout
        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(teacher)")}
            teacher = conn.execute(
                "SELECT name, school, subject FROM teacher WHERE id = 1"
            ).fetchone()
        assert {"current_teaching_class_id", "subject"} <= columns
        assert teacher == ("旧教师", "一中", None)


# ────────────────────────────── 学科校验 ──────────────────────────────

SUPPORTED_SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]


class TestSubjectValidation:
    """学科值统一 trim，拒绝空白或不支持的学科。"""

    def test_valid_subject_passes(self):
        from app.teaching.subject import validate_subject
        for s in SUPPORTED_SUBJECTS:
            assert validate_subject(s) == s

    def test_subject_is_trimmed(self):
        from app.teaching.subject import validate_subject
        assert validate_subject("  物理  ") == "物理"
        assert validate_subject("\t数学\n") == "数学"

    def test_empty_subject_rejected(self):
        from app.teaching.subject import validate_subject, InvalidSubjectError
        for bad in ["", "   ", "\t\n"]:
            with pytest.raises(InvalidSubjectError):
                validate_subject(bad)

    def test_unsupported_subject_rejected(self):
        from app.teaching.subject import validate_subject, InvalidSubjectError
        with pytest.raises(InvalidSubjectError):
            validate_subject("体育")
        with pytest.raises(InvalidSubjectError):
            validate_subject("science")


# ────────────────────────────── 教师资料（subject 读写） ──────────────────────────────


class TestTeacherProfileSubject:
    """教师资料读写：GET 返回 subject + subject_configured；PATCH 更新 subject。"""

    def test_get_teacher_returns_subject_fields(self):
        from app.teaching.subject import get_teacher_profile
        db = make_db()
        db.add(Teacher(name="王老师", subject="物理"))
        db.commit()

        profile = get_teacher_profile(db)
        assert profile["name"] == "王老师"
        assert profile["subject"] == "物理"
        assert profile["subject_configured"] is True
        db.close()

    def test_get_teacher_subject_configured_false_when_unset(self):
        from app.teaching.subject import get_teacher_profile
        db = make_db()
        db.add(Teacher(name=None, subject=None))
        db.commit()

        profile = get_teacher_profile(db)
        assert profile["subject"] is None
        assert profile["subject_configured"] is False
        db.close()

    def test_update_teacher_subject(self):
        from app.teaching.subject import update_teacher_profile
        db = make_db()
        db.add(Teacher(name=None, subject=None))
        db.commit()

        update_teacher_profile(db, subject="化学")
        t = db.query(Teacher).first()
        assert t.subject == "化学"
        db.close()

    def test_update_teacher_subject_trimmed(self):
        from app.teaching.subject import update_teacher_profile
        db = make_db()
        db.add(Teacher(subject=None))
        db.commit()

        update_teacher_profile(db, subject="  英语  ")
        t = db.query(Teacher).first()
        assert t.subject == "英语"
        db.close()

    def test_update_teacher_subject_invalid_raises(self):
        from app.teaching.subject import update_teacher_profile, InvalidSubjectError
        db = make_db()
        db.add(Teacher(subject=None))
        db.commit()

        with pytest.raises(InvalidSubjectError):
            update_teacher_profile(db, subject="")
        with pytest.raises(InvalidSubjectError):
            update_teacher_profile(db, subject="体育")
        # 不修改数据
        assert db.query(Teacher).first().subject is None
        db.close()

    def test_update_teacher_name_only(self):
        from app.teaching.subject import update_teacher_profile
        db = make_db()
        db.add(Teacher(name=None, subject=None))
        db.commit()

        update_teacher_profile(db, name="李老师")
        t = db.query(Teacher).first()
        assert t.name == "李老师"
        assert t.subject is None  # subject 不受影响
        db.close()

    def test_update_teacher_name_none_clears_name(self):
        from app.teaching.subject import update_teacher_profile
        db = make_db()
        db.add(Teacher(name="旧名", subject="物理"))
        db.commit()

        update_teacher_profile(db, name="")
        t = db.query(Teacher).first()
        assert t.name is None
        assert t.subject == "物理"
        db.close()


# ────────────────────────────── resolve_teaching_subject ──────────────────────────────


class TestResolveTeachingSubject:
    """统一领域函数：教师 subject 为唯一来源。

    - 未配置 → SubjectNotConfiguredError
    - 给定 teaching_class_id 且旧 subject 与教师 subject 冲突 → SubjectConflictError
    - 正常 → 返回教师 subject
    """

    def test_returns_teacher_subject_when_configured(self):
        from app.teaching.subject import resolve_teaching_subject
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.commit()

        assert resolve_teaching_subject(db) == "物理"
        db.close()

    def test_raises_when_not_configured(self):
        from app.teaching.subject import resolve_teaching_subject, SubjectNotConfiguredError
        db = make_db()
        db.add(Teacher(subject=None))
        db.commit()

        with pytest.raises(SubjectNotConfiguredError):
            resolve_teaching_subject(db)
        db.close()

    def test_raises_when_no_teacher_at_all(self):
        from app.teaching.subject import resolve_teaching_subject, SubjectNotConfiguredError
        db = make_db()
        with pytest.raises(SubjectNotConfiguredError):
            resolve_teaching_subject(db)
        db.close()

    def test_with_class_id_consistent_subject(self):
        from app.teaching.subject import resolve_teaching_subject
        db = make_db()
        db.add(Teacher(subject="化学"))
        db.commit()
        tc = TeachingClass(grade=2, label="化A1", subject="化学", kind="教学")
        db.add(tc)
        db.commit()

        assert resolve_teaching_subject(db, teaching_class_id=tc.id) == "化学"
        db.close()

    def test_with_class_id_empty_subject_ok(self):
        """教学班 subject 为空时不冲突（回填后的预期状态）。"""
        from app.teaching.subject import resolve_teaching_subject
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.commit()
        tc = TeachingClass(grade=2, label="物A1", subject=None, kind="教学")
        db.add(tc)
        db.commit()

        assert resolve_teaching_subject(db, teaching_class_id=tc.id) == "物理"
        db.close()

    def test_with_class_id_conflict_raises(self):
        """教学班旧 subject 与教师 subject 不同 → 明确冲突。"""
        from app.teaching.subject import (
            resolve_teaching_subject, SubjectConflictError,
        )
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.commit()
        tc = TeachingClass(grade=2, label="史B3", subject="历史", kind="教学")
        db.add(tc)
        db.commit()

        with pytest.raises(SubjectConflictError):
            resolve_teaching_subject(db, teaching_class_id=tc.id)
        db.close()

    def test_with_nonexistent_class_id_raises_404(self):
        from app.teaching.subject import resolve_teaching_subject
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.commit()

        with pytest.raises(ValueError, match="不存在"):
            resolve_teaching_subject(db, teaching_class_id=99999)
        db.close()


# ────────────────────────────── 首次设置 subject：回填 + 冲突 ──────────────────────────────


class TestFirstSubjectSettingBackfill:
    """教师首次设置 subject 时：
    - 对 subject 为空的既有教学班回填该学科；
    - 已有多个非空学科或与请求值冲突 → 409，不修改数据。
    """

    def test_backfills_empty_classes(self):
        from app.teaching.subject import update_teacher_profile
        db = make_db()
        db.add(Teacher(subject=None))
        db.add(TeachingClass(grade=2, label="物A1", subject=None, kind="教学"))
        db.add(TeachingClass(grade=2, label="物A2", subject=None, kind="教学"))
        db.commit()

        update_teacher_profile(db, subject="物理")
        classes = db.query(TeachingClass).order_by(TeachingClass.label).all()
        assert all(tc.subject == "物理" for tc in classes)
        db.close()

    def test_conflict_when_multiple_non_empty_subjects(self):
        from app.teaching.subject import (
            update_teacher_profile, SubjectConflictError,
        )
        db = make_db()
        db.add(Teacher(subject=None))
        db.add(TeachingClass(grade=2, label="物A1", subject="物理", kind="教学"))
        db.add(TeachingClass(grade=2, label="史B3", subject="历史", kind="教学"))
        db.commit()

        with pytest.raises(SubjectConflictError) as exc_info:
            update_teacher_profile(db, subject="物理")
        # 列出冲突班
        conflict_ids = {c["id"] for c in exc_info.value.conflicting_classes}
        assert len(conflict_ids) == 2
        # 不修改数据
        assert db.query(Teacher).first().subject is None
        db.close()

    def test_conflict_when_existing_subject_differs_from_request(self):
        from app.teaching.subject import (
            update_teacher_profile, SubjectConflictError,
        )
        db = make_db()
        db.add(Teacher(subject=None))
        db.add(TeachingClass(grade=2, label="物A1", subject="物理", kind="教学"))
        db.commit()

        with pytest.raises(SubjectConflictError):
            update_teacher_profile(db, subject="化学")
        # 不修改数据
        assert db.query(Teacher).first().subject is None
        assert db.query(TeachingClass).first().subject == "物理"
        db.close()

    def test_backfill_skips_when_teacher_already_has_subject(self):
        """教师已有 subject 时，再次更新不触发回填（只改教师 subject）。"""
        from app.teaching.subject import update_teacher_profile
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.add(TeachingClass(grade=2, label="物A1", subject="物理", kind="教学"))
        db.add(TeachingClass(grade=2, label="空班", subject=None, kind="教学"))
        db.commit()

        # 教师已有 subject=物理，改成化学：空班不应被回填（变更逻辑后续阶段处理）
        update_teacher_profile(db, subject="化学")
        empty_tc = db.query(TeachingClass).filter(TeachingClass.label == "空班").first()
        assert empty_tc.subject is None  # 不回填
        db.close()


# ────────────────────────────── 教学班 CRUD 学科继承/校验 ──────────────────────────────


class TestClassCreateInheritsSubject:
    """新建教学班：自动继承教师 subject；未配置 409；兼容请求携带 subject 必须一致。"""

    def test_create_inherits_teacher_subject(self):
        from app.teaching.subject import create_class_with_subject
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.commit()

        tc = create_class_with_subject(db, grade=2, label="物A1", kind="教学")
        assert tc["subject"] == "物理"
        db.close()

    def test_create_raises_when_teacher_subject_unset(self):
        from app.teaching.subject import (
            create_class_with_subject, SubjectNotConfiguredError,
        )
        db = make_db()
        db.add(Teacher(subject=None))
        db.commit()

        with pytest.raises(SubjectNotConfiguredError):
            create_class_with_subject(db, grade=2, label="物A1", kind="教学")
        # 不创建班
        assert db.query(TeachingClass).count() == 0
        db.close()

    def test_create_raises_when_no_teacher(self):
        from app.teaching.subject import (
            create_class_with_subject, SubjectNotConfiguredError,
        )
        db = make_db()
        with pytest.raises(SubjectNotConfiguredError):
            create_class_with_subject(db, grade=2, label="物A1", kind="教学")
        db.close()

    def test_create_with_compatible_subject_ok(self):
        """兼容请求携带 subject：与教师一致则通过。"""
        from app.teaching.subject import create_class_with_subject
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.commit()

        tc = create_class_with_subject(
            db, grade=2, label="物A1", kind="教学", subject="物理"
        )
        assert tc["subject"] == "物理"
        db.close()

    def test_create_with_conflicting_subject_raises(self):
        """兼容请求携带 subject：与教师不同 → 409 冲突。"""
        from app.teaching.subject import (
            create_class_with_subject, SubjectConflictError,
        )
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.commit()

        with pytest.raises(SubjectConflictError):
            create_class_with_subject(
                db, grade=2, label="史B3", kind="教学", subject="历史"
            )
        # 不创建班
        assert db.query(TeachingClass).count() == 0
        db.close()


class TestClassUpdateSubjectLock:
    """修改教学班：禁止改成与教师 subject 不同的值；保持旧客户端兼容。"""

    def test_update_label_ok(self):
        from app.teaching.subject import update_class_subject_aware
        db = make_db()
        db.add(Teacher(subject="物理"))
        tc = TeachingClass(grade=2, label="物A1", subject="物理", kind="教学")
        db.add(tc)
        db.commit()

        result = update_class_subject_aware(db, tc.id, label="物理一班")
        assert result["label"] == "物理一班"
        assert result["subject"] == "物理"
        db.close()

    def test_update_subject_to_same_value_ok(self):
        from app.teaching.subject import update_class_subject_aware
        db = make_db()
        db.add(Teacher(subject="物理"))
        tc = TeachingClass(grade=2, label="物A1", subject="物理", kind="教学")
        db.add(tc)
        db.commit()

        result = update_class_subject_aware(db, tc.id, subject="物理")
        assert result["subject"] == "物理"
        db.close()

    def test_update_subject_to_different_value_rejected(self):
        from app.teaching.subject import (
            update_class_subject_aware, SubjectConflictError,
        )
        db = make_db()
        db.add(Teacher(subject="物理"))
        tc = TeachingClass(grade=2, label="物A1", subject="物理", kind="教学")
        db.add(tc)
        db.commit()

        with pytest.raises(SubjectConflictError):
            update_class_subject_aware(db, tc.id, subject="化学")
        # 不修改
        assert db.query(TeachingClass).first().subject == "物理"
        db.close()

    def test_update_other_fields_keeps_subject(self):
        """更新 note/kind 等不影响 subject。"""
        from app.teaching.subject import update_class_subject_aware
        db = make_db()
        db.add(Teacher(subject="物理"))
        tc = TeachingClass(grade=2, label="物A1", subject="物理", kind="教学")
        db.add(tc)
        db.commit()

        result = update_class_subject_aware(db, tc.id, note="重点班")
        assert result["subject"] == "物理"
        assert result["note"] == "重点班"
        db.close()


# ────────────────────────────── 全部教学班模式 ──────────────────────────────


class TestAllClassesModeSubject:
    """「全部教学班」模式必须可从教师配置确定唯一学科。"""

    def test_resolve_without_class_id_works_with_multiple_classes(self):
        """教师有多个教学班，但 resolve_teaching_subject 不传 class_id 也能确定学科。"""
        from app.teaching.subject import resolve_teaching_subject
        db = make_db()
        db.add(Teacher(subject="物理"))
        db.add(TeachingClass(grade=2, label="物A1", subject="物理", kind="教学"))
        db.add(TeachingClass(grade=2, label="物A2", subject="物理", kind="教学"))
        db.commit()

        assert resolve_teaching_subject(db) == "物理"
        db.close()

    def test_all_classes_share_teacher_subject_after_backfill(self):
        """教师首次设置 subject 后，所有空班的 subject 都回填一致。"""
        from app.teaching.subject import update_teacher_profile
        db = make_db()
        db.add(Teacher(subject=None))
        db.add(TeachingClass(grade=1, label="1", subject=None, kind="行政"))
        db.add(TeachingClass(grade=2, label="物A1", subject=None, kind="教学"))
        db.add(TeachingClass(grade=3, label="物B3", subject=None, kind="教学"))
        db.commit()

        update_teacher_profile(db, subject="物理")
        subjects = {tc.subject for tc in db.query(TeachingClass).all()}
        assert subjects == {"物理"}
        db.close()

    def test_current_class_subject_reflects_teacher_subject(self):
        """classes/current 响应中的 subject 反映教师任教科目（回填后一致）。"""
        from app.teaching.subject import update_teacher_profile, get_current_class_payload
        db = make_db()
        db.add(Teacher(subject=None, current_teaching_class_id=None))
        tc = TeachingClass(grade=2, label="物A1", subject=None, kind="教学")
        db.add(tc)
        db.commit()

        # 设置当前班
        teacher = db.query(Teacher).first()
        teacher.current_teaching_class_id = tc.id
        db.commit()

        # 首次设置 subject → 回填
        update_teacher_profile(db, subject="物理")

        # current payload 的 subject 应反映回填后的值
        payload = get_current_class_payload(db)
        assert payload["class"]["subject"] == "物理"
        db.close()

    def test_current_payload_none_when_no_current_class(self):
        from app.teaching.subject import get_current_class_payload
        db = make_db()
        db.add(Teacher(subject="物理", current_teaching_class_id=None))
        db.commit()

        payload = get_current_class_payload(db)
        assert payload["teaching_class_id"] is None
        assert payload["class"] is None
        db.close()
