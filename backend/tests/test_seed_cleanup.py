"""seed_minimal_exam_scope 完全回滚测试。

验证 helper 的 cleanup 仅删除自己创建的行，cleanup 后数据库状态与调用前等价：
不删除预存数据，也不残留新数据。覆盖三条路径：
1. 新 teacher 路径 cleanup 后 Teacher=0
2. 复用已有班路径 cleanup 后预存班保留但新增 member 为 0
3. 重复两次幂等

所有执行使用临时 EXAM_TRACKER_DIR / EXAM_TRACKER_BACKUP_DIR。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest


def _run_in_temp_env(tmp_path, body_code: str):
    """在子进程中用全新临时 DB 运行 body_code。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    script = tmp_path / "body.py"
    script.write_text(textwrap.dedent(body_code))

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = os.environ.copy()
    env["EXAM_TRACKER_DIR"] = str(data_dir)
    env["EXAM_TRACKER_BACKUP_DIR"] = str(tmp_path / "backups")
    venv_python = os.path.join(os.path.dirname(sys.executable), "python")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    proc = subprocess.run(
        [venv_python, str(script)],
        cwd=backend_dir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    return proc


_COUNTS = textwrap.dedent("""\
    from app.db.models import (
        SessionLocal, Teacher, TeachingClass, TeachingClassMember,
        Exam, SubjectScore,
    )
    db = SessionLocal()
    counts = {
        "teacher": db.query(Teacher).count(),
        "tc": db.query(TeachingClass).count(),
        "member": db.query(TeachingClassMember).count(),
        "exam": db.query(Exam).count(),
        "score": db.query(SubjectScore).count(),
    }
    db.close()
""")


def _parse_counts(proc):
    assert proc.returncode == 0, "子进程失败:\n" + proc.stdout
    lines = [ln for ln in proc.stdout.strip().split("\n") if ln.strip()]
    return json.loads(lines[-1])


class TestSeedCleanupNewTeacher:
    """新 teacher 路径：cleanup 后所有新建行清零（Teacher=0）。"""

    def test_cleanup_new_teacher(self, tmp_path):
        body = (
            "import sys, os\n"
            "sys.path.insert(0, os.path.join(os.getcwd(), 'tests'))\n"
            "from conftest import seed_minimal_exam_scope\n"
            + _COUNTS.replace("counts = {", "before = {")
            + "\ncleanup = seed_minimal_exam_scope(member_ids=['s1', 's2'])\n"
            "cleanup()\n"
            + _COUNTS.replace("counts = {", "after = {")
            + "\nimport json\n"
            "print(json.dumps({'before': before, 'after': after}))\n"
        )
        proc = _run_in_temp_env(tmp_path, body)
        data = _parse_counts(proc)
        # 全新临时 DB，cleanup 后应全部归零
        assert data["after"] == {"teacher": 0, "tc": 0, "member": 0, "exam": 0, "score": 0}, \
            "新 teacher cleanup 后应全部清零: " + str(data)


class TestSeedCleanupReuseExistingClass:
    """复用已有班路径：预存班保留，但新增 member/score/exam 必须 cleanup。"""

    def test_cleanup_preserves_existing_deletes_new(self, tmp_path):
        body = (
            "from app.db.models import (\n"
            "    SessionLocal, Teacher, TeachingClass, TeachingClassMember,\n"
            "    Exam, SubjectScore,\n"
            ")\n"
            "import sys, os\n"
            "sys.path.insert(0, os.path.join(os.getcwd(), 'tests'))\n"
            "from conftest import seed_minimal_exam_scope\n"
            "\n"
            "db = SessionLocal()\n"
            "t = Teacher(subject='数学', name='预存老师')\n"
            "db.add(t)\n"
            "db.flush()\n"
            "tc = TeachingClass(grade=2, label='tapi-scope', subject='数学', kind='教学')\n"
            "db.add(tc)\n"
            "db.flush()\n"
            "db.add(TeachingClassMember(teaching_class_id=tc.id, student_id='s_pre', source='manual'))\n"
            "db.commit()\n"
            "db.close()\n"
            + _COUNTS.replace("counts = {", "before = {")
            + "\ncleanup = seed_minimal_exam_scope(member_ids=['s1', 's2'])\n"
            "cleanup()\n"
            + _COUNTS.replace("counts = {", "after = {")
            + "\nimport json\n"
            "print(json.dumps({'before': before, 'after': after}))\n"
        )
        proc = _run_in_temp_env(tmp_path, body)
        data = _parse_counts(proc)
        # 预存: teacher=1, tc=1, member=1(s_pre), exam=0, score=0
        # cleanup 后: teacher=1(保留), tc=1(保留), member=1(s_pre保留, s1/s2删除),
        #             exam=0(新建的删除), score=0(新建的删除)
        assert data["after"]["teacher"] == 1, "预存 teacher 应保留: " + str(data)
        assert data["after"]["tc"] == 1, "预存班应保留: " + str(data)
        assert data["after"]["member"] == 1, "预存 member 应保留、新增 member 应删除: " + str(data)
        assert data["after"]["exam"] == 0, "新建 exam 应删除: " + str(data)
        assert data["after"]["score"] == 0, "新建 score 应删除: " + str(data)


class TestSeedCleanupIdempotentTwice:
    """重复两次调用幂等：每次 cleanup 后状态等价。"""

    def test_double_seed_cleanup(self, tmp_path):
        body = (
            "import sys, os\n"
            "sys.path.insert(0, os.path.join(os.getcwd(), 'tests'))\n"
            "from conftest import seed_minimal_exam_scope\n"
            + _COUNTS.replace("counts = {", "before = {")
            + "\ncleanup1 = seed_minimal_exam_scope(member_ids=['s1', 's2'])\n"
            "cleanup1()\n"
            + _COUNTS.replace("counts = {", "mid = {")
            + "\ncleanup2 = seed_minimal_exam_scope(member_ids=['s3', 's4'])\n"
            "cleanup2()\n"
            + _COUNTS.replace("counts = {", "after = {")
            + "\nimport json\n"
            "print(json.dumps({'before': before, 'mid': mid, 'after': after}))\n"
        )
        proc = _run_in_temp_env(tmp_path, body)
        data = _parse_counts(proc)
        zero = {"teacher": 0, "tc": 0, "member": 0, "exam": 0, "score": 0}
        assert data["before"] == zero, "初始应为空: " + str(data)
        assert data["mid"] == zero, "第一次 cleanup 后应为空: " + str(data)
        assert data["after"] == zero, "第二次 cleanup 后应为空: " + str(data)
