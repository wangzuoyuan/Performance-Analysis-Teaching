"""阶段3：学生列表与画像单学科化（严格 TDD 测试）。

覆盖范围（任务要求）：
- /api/students 返回顶层 teaching_subject，成绩摘要只用当前任教学科 SubjectScore
- 数学教师列表/画像只返回数学，生物/物理及主三门数据完全不泄漏
- A 当前班与 A∪B 全部模式成员范围、重叠去重、越权学号拒绝
- 只有其他学科/只有 percentile 空分残留不能成为最新考试或趋势点
- 学生无总分但有当前学科时仍可显示
- scope_rank 按教学班当前学科计算，且不回退全年级
- 高二选考学科趋势采用 grade_score，数学趋势采用 percentile
- 三个前端源码不含总分旁路、TotalScore、主三门/五门/九门/+3/3+3、
  main_total/five_trend/plus3/san3、ALL_SUBJECTS、latest_total_score/latest_xueji_rank
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

# ════════════════════════════════════════════════════════════════
#  API 端到端测试（子进程 + 全新临时 EXAM_TRACKER_DIR）
# ════════════════════════════════════════════════════════════════

_API_TEST_SCRIPT = textwrap.dedent("""\
    import json, sys
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.models import SessionLocal

    client = TestClient(app)

    # 读取 fixture 脚本路径，执行数据填充
    setup_script = sys.argv[1]
    with open(setup_script) as f:
        exec(f.read())

    # 读取要执行的断言脚本路径
    assert_script = sys.argv[2]
    with open(assert_script) as f:
        exec(f.read())
""")


def _run_isolated_api_test(tmp_path, setup_code: str, assert_code: str):
    """在子进程中用全新临时 DB 运行 API 测试，返回 stdout。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    setup_file = tmp_path / "setup.py"
    setup_file.write_text(setup_code)
    assert_file = tmp_path / "assert.py"
    assert_file.write_text(assert_code)

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = os.environ.copy()
    env["EXAM_TRACKER_DIR"] = str(data_dir)
    env["EXAM_TRACKER_BACKUP_DIR"] = str(tmp_path / "backups")
    venv_python = os.path.join(os.path.dirname(sys.executable), "python")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    proc = subprocess.run(
        [venv_python, "-c", _API_TEST_SCRIPT, str(setup_file), str(assert_file)],
        cwd=backend_dir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"子进程失败 (rc={proc.returncode}):\n{proc.stdout}")
    return proc


# ──────────────────────────────────────────────────────────────
#  共享 fixture：数学教师，两个高二教学班；考试含数学+物理+TotalScore
# ──────────────────────────────────────────────────────────────

_SETUP_MATH_TEACHER = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, TotalScore,
    )

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()

    # A班: s1, s2, s3 ; B班: s4, s5
    for label, sids in [("A班", ["s1","s2","s3"]), ("B班", ["s4","s5"])]:
        tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
        db.add(tc)
        db.flush()
        for sid in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    # 考试1（期中）: 数学+物理成绩 + TotalScore（主三门/3+3）
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam1)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=80+i, grade_score=70+i*0.5, grade_percentile=0.9-i*0.05,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    # 物理成绩（非任教学科）——必须被完全隔离
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="物理",
            raw_score=50+i, grade_score=60+i*0.5, grade_percentile=0.5,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    # TotalScore——单学科化后不应出现在学生列表/画像
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(TotalScore(exam_id=exam1.id, student_id=sid, total_type="主三门",
            total_score=280+i, xueji_rank=10+i, grade_percentile=0.8))
        db.add(TotalScore(exam_id=exam1.id, student_id=sid, total_type="3+3",
            total_score=480+i, xueji_rank=5+i, grade_percentile=0.7))
    db.commit()

    # 考试2（月考，更早）: 只有数学成绩
    exam2 = Exam(name="月考", grade=2, semester="上", exam_type="月考", exam_date="2025-09")
    db.add(exam2)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="数学",
            raw_score=70+i, grade_score=65+i*0.5, grade_percentile=0.85-i*0.05,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    db.commit()

    db.close()
""")


class TestStudentsListSingleSubject:
    """/api/students 单学科化：返回 teaching_subject，成绩摘要只用当前学科。"""

    def test_returns_teaching_subject(self, tmp_path):
        """/api/students 顶层返回 teaching_subject='数学'。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {"status": "ok", "teaching_subject": data.get("teaching_subject")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["teaching_subject"] == "数学", \
            f"teaching_subject 应为 数学, 得到 {data['teaching_subject']}"

    def test_no_total_score_fields(self, tmp_path):
        """学生行不再有 latest_total_score / latest_xueji_rank 字段。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            data = r.json()
            students = data.get("students", [])
            assert len(students) > 0
            keys = set(students[0].keys())
            result = {
                "has_latest_total_score": "latest_total_score" in keys,
                "has_latest_xueji_rank": "latest_xueji_rank" in keys,
                "has_raw_score": "raw_score" in keys,
                "has_scope_rank": "scope_rank" in keys,
                "keys": sorted(keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert not data["has_latest_total_score"], \
            f"不应有 latest_total_score: {data}"
        assert not data["has_latest_xueji_rank"], \
            f"不应有 latest_xueji_rank: {data}"
        assert data["has_raw_score"], f"应有 raw_score: {data}"

    def test_math_teacher_only_returns_math_scores(self, tmp_path):
        """数学教师列表成绩是数学分而非物理分。s1 数学 raw_score=81, 物理 raw_score=51。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            result = {"status": "ok", "raw_score": s1.get("raw_score"), "expected": 81}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["raw_score"] == 81, \
            f"s1 数学 raw_score 应为 81（不是物理 51），得到 {data['raw_score']}"

    def test_latest_exam_is_most_recent_with_real_score(self, tmp_path):
        """latest_exam 是当前学科在合法范围内有真实分数的最新考试（期中 2025-11）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            data = r.json()
            students = data.get("students", [])
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            result = {
                "status": "ok",
                "latest_exam_name": s1.get("latest_exam", {}).get("name") if s1.get("latest_exam") else None,
                "raw_score": s1.get("raw_score"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["latest_exam_name"] == "期中", \
            f"最新考试应为 期中, 得到 {data['latest_exam_name']}"
        assert data["raw_score"] == 81

    def test_all_mode_union_dedup(self, tmp_path):
        """全部模式（无 teaching_class_id）返回 A∪B 全部 5 名学生。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            ids = sorted(s["student_id"] for s in students)
            result = {"status": "ok", "ids": ids}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["ids"] == ["s1", "s2", "s3", "s4", "s5"], \
            f"全部模式应返回 s1-s5: {data['ids']}"

    def test_current_class_only_that_class_members(self, tmp_path):
        """当前班模式只返回该教学班成员。"""
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/students?teaching_class_id={a_id}")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            ids = sorted(s["student_id"] for s in students)
            result = {"status": "ok", "ids": ids}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["ids"] == ["s1", "s2", "s3"], \
            f"A班应只有 s1-s3: {data['ids']}"

    def test_invalid_teaching_class_returns_4xx(self, tmp_path):
        """不存在的 teaching_class_id 返回 4xx，不退化为全年级。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students?teaching_class_id=99999")
            result = {"status_code": r.status_code}
            if r.status_code == 200:
                result["count"] = len(r.json().get("students", []))
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status_code"] in (400, 403, 404, 409), \
            f"越权教学班应返回4xx, 得到 {data['status_code']}"

    def test_student_without_current_subject_stays_with_null_scores(self, tmp_path):
        """无当前学科分数的合法班级成员留在花名册，但成绩字段为 null。"""
        setup = _SETUP_MATH_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore, TeachingClass, TeachingClassMember
            exam1 = db.query(Exam).filter(Exam.name == "期中").first()
            a_tc = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            db.add(TeachingClassMember(teaching_class_id=a_tc.id, student_id="nomath", source="manual"))
            # nomath 只有物理成绩，没有数学
            db.add(SubjectScore(exam_id=exam1.id, student_id="nomath", subject="物理",
                raw_score=99, name="无数学", class_num=1))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/students?teaching_class_id={a_id}")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            nomath = [s for s in students if s["student_id"] == "nomath"]
            result = {
                "status": "ok",
                "has_nomath": len(nomath) > 0,
                "raw_score": nomath[0].get("raw_score") if nomath else "N/A",
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["has_nomath"], f"nomath 应在花名册: {data}"
        assert data["raw_score"] is None, \
            f"nomath 成绩字段应为 null, 得到 {data['raw_score']}"

    def test_percentile_only_not_latest_exam(self, tmp_path):
        """只有百分位、无原始分/等级分的残留行不能成为最新考试。"""
        setup = _SETUP_MATH_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore
            # 考试3（最新，但数学只有百分位残留）
            exam3 = Exam(name="百分位残留", grade=2, semester="上", exam_type="月考", exam_date="2025-12")
            db.add(exam3)
            db.flush()
            for i, sid in enumerate(["s1","s2","s3"], 1):
                db.add(SubjectScore(exam_id=exam3.id, student_id=sid, subject="数学",
                    raw_score=None, grade_score=None, grade_percentile=0.8-i*0.1,
                    name=f"学生{i}", class_num=1, xueji=252000+i))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            latest = s1.get("latest_exam", {}) or {}
            result = {"status": "ok", "latest_exam_name": latest.get("name")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["latest_exam_name"] == "期中", \
            f"百分位残留不应成为最新考试, 应为期中: {data['latest_exam_name']}"

    def test_scope_rank_computed_within_teaching_class(self, tmp_path):
        """scope_rank 按教学班内当前学科有效分数计算。
        A班(s1,s2,s3) 期中数学：81,82,83 → s1 排名第3。"""
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/students?teaching_class_id={a_id}")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            # A班数学：s1=81, s2=82, s3=83 → s1排名第3
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            result = {"status": "ok", "scope_rank": s1.get("scope_rank"), "expected": 3}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["scope_rank"] == 3, \
            f"s1 在 A班(81,82,83) scope_rank 应为 3, 得到 {data['scope_rank']}"


class TestStudentsListOverlapDedup:
    """重叠教学班成员：当前班模式只返回该班成员，全部模式返回并集去重。"""

    _SETUP_OVERLAP = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import (
            Teacher, TeachingClass, TeachingClassMember, Exam,
            SubjectScore,
        )

        t = Teacher(subject="数学", name="数学老师")
        db.add(t)
        db.flush()

        # A班 s1,s2,s3 ; B班 s3,s4,s5（s3 同时在两个班）
        for label, sids in [("A班", ["s1","s2","s3"]), ("B班", ["s3","s4","s5"])]:
            tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
            db.add(tc)
            db.flush()
            for sid in sids:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
        db.commit()

        exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
        db.add(exam)
        db.flush()
        for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
            db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
                raw_score=80+i, name=f"学生{i}", class_num=1))
        db.commit()
        db.close()
    """)

    def test_all_mode_union_dedup_overlap(self, tmp_path):
        """全部模式返回 A∪B 并集去重：s1-s5（s3 只出现一次）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            ids = sorted(s["student_id"] for s in students)
            result = {"status": "ok", "ids": ids,
                      "has_dup": len(ids) != len(set(ids))}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_OVERLAP, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["ids"] == ["s1", "s2", "s3", "s4", "s5"], \
            f"全部模式应包含 s1-s5 去重: {data['ids']}"
        assert not data["has_dup"], "s3 不应出现两次"


class TestStudentProfileSingleSubject:
    """/api/students/{id} 单学科化。"""

    def test_returns_teaching_subject_and_score_trend(self, tmp_path):
        """画像返回顶层 teaching_subject 和单一 score_trend。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/s1")
            assert r.status_code == 200, r.text
            data = r.json()
            keys = set(data.keys())
            result = {
                "status": "ok",
                "teaching_subject": data.get("teaching_subject"),
                "has_score_trend": "score_trend" in keys,
                "has_main_total_trend": "main_total_trend" in keys,
                "has_five_trend": "five_trend" in keys,
                "has_plus3_trend": "plus3_trend" in keys,
                "has_san3_trend": "san3_trend" in keys,
                "has_subject_trend": "subject_trend" in keys,
                "has_class_rank_basis": "class_rank_basis" in keys,
                "keys": sorted(keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["teaching_subject"] == "数学"
        assert data["has_score_trend"], f"应有 score_trend: {data}"
        assert not data["has_main_total_trend"], f"不应有 main_total_trend: {data}"
        assert not data["has_five_trend"], f"不应有 five_trend: {data}"
        assert not data["has_plus3_trend"], f"不应有 plus3_trend: {data}"
        assert not data["has_san3_trend"], f"不应有 san3_trend: {data}"
        assert not data["has_subject_trend"], f"不应有 subject_trend: {data}"
        assert not data["has_class_rank_basis"], f"不应有 class_rank_basis: {data}"

    def test_score_trend_only_current_subject(self, tmp_path):
        """score_trend 只含当前任教学科记录，不含物理。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/s1")
            assert r.status_code == 200, r.text
            data = r.json()
            trend = data.get("score_trend", [])
            subjects = set(t.get("subject") for t in trend)
            result = {"status": "ok", "subjects": sorted(subjects)}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert "物理" not in data["subjects"], f"不应含物理: {data}"
        assert "数学" in data["subjects"], f"应含数学: {data}"

    def test_score_trend_excludes_empty_score_rows(self, tmp_path):
        """raw_score 和 grade_score 均为空的残留行不进入趋势。"""
        setup = _SETUP_MATH_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore
            exam3 = Exam(name="残留", grade=2, semester="上", exam_type="月考", exam_date="2025-08")
            db.add(exam3)
            db.flush()
            db.add(SubjectScore(exam_id=exam3.id, student_id="s1", subject="数学",
                raw_score=None, grade_score=None, grade_percentile=0.5,
                name="学生1", class_num=1))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/s1")
            assert r.status_code == 200, r.text
            trend = r.json().get("score_trend", [])
            exam_names = [t["exam_name"] for t in trend]
            result = {"status": "ok", "exam_names": exam_names}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert "残留" not in data["exam_names"], \
            f"空分行不应进入趋势: {data['exam_names']}"

    def test_out_of_scope_student_returns_404(self, tmp_path):
        """不在合法成员范围内的学号返回 404/403。"""
        setup = _SETUP_MATH_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore
            exam1 = db.query(Exam).filter(Exam.name == "期中").first()
            # outsider 不在任何教学班
            db.add(SubjectScore(exam_id=exam1.id, student_id="outsider", subject="数学",
                raw_score=99, name="外部", class_num=9))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/outsider")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status_code"] in (403, 404), \
            f"外部学号应返回403/404, 得到 {data['status_code']}"

    def test_score_trend_has_scope_rank(self, tmp_path):
        """score_trend 每点含 scope_rank 和 rank_basis。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/s1")
            assert r.status_code == 200, r.text
            trend = r.json().get("score_trend", [])
            assert len(trend) > 0
            point = trend[0]
            keys = set(point.keys())
            result = {
                "has_scope_rank": "scope_rank" in keys,
                "has_rank_basis": "rank_basis" in keys,
                "has_class_label": "class_label" in keys,
                "keys": sorted(keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["has_scope_rank"], f"应有 scope_rank: {data}"
        assert data["has_rank_basis"], f"应有 rank_basis: {data}"

    def test_scope_rank_not_fallback_to_full_grade(self, tmp_path):
        """scope_rank 按教学班成员集合计算，不回退全年级。
        A班(s1,s2,s3) 期中数学：81,82,83 → s1 班内第3。
        全年级含 s4=84,s5=85，若回退全年级 s1 会是第5。"""
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/students/s1?teaching_class_id={a_id}")
            assert r.status_code == 200, r.text
            trend = r.json().get("score_trend", [])
            qizhong = [t for t in trend if t["exam_name"] == "期中"][0]
            result = {"status": "ok", "scope_rank": qizhong.get("scope_rank"), "expected": 3}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["scope_rank"] == 3, \
            f"s1 期中 A班内 scope_rank 应为 3（不回退全年级=5）, 得到 {data['scope_rank']}"

    def test_student_without_total_but_has_subject_visible(self, tmp_path):
        """学生无总分但有当前学科成绩时仍可显示画像。"""
        setup = _SETUP_MATH_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore, TeachingClass, TeachingClassMember
            exam1 = db.query(Exam).filter(Exam.name == "期中").first()
            a_tc = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            db.add(TeachingClassMember(teaching_class_id=a_tc.id, student_id="onlymath", source="manual"))
            db.add(SubjectScore(exam_id=exam1.id, student_id="onlymath", subject="数学",
                raw_score=77, name="只有数学", class_num=1))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/onlymath")
            assert r.status_code == 200, r.text
            trend = r.json().get("score_trend", [])
            result = {"status": "ok", "trend_len": len(trend)}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["trend_len"] > 0, f"只有数学的学生应有趋势: {data}"

    def test_no_subject_configured_returns_4xx(self, tmp_path):
        """教师未配置 subject 时返回明确错误。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Teacher
            t = Teacher(subject=None)
            db.add(t)
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status_code"] in (400, 409), \
            f"未配置学科应返回4xx, 得到 {data['status_code']}"


class TestStudentProfileTrendMetric:
    """趋势字段：高二选考学科含 grade_score，数学含 grade_percentile。"""

    def test_score_trend_point_has_grade_score_and_percentile(self, tmp_path):
        """score_trend 每点含 raw_score, grade_score, grade_percentile。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/s1")
            assert r.status_code == 200, r.text
            trend = r.json().get("score_trend", [])
            qizhong = [t for t in trend if t["exam_name"] == "期中"][0]
            result = {
                "status": "ok",
                "raw_score": qizhong.get("raw_score"),
                "grade_score": qizhong.get("grade_score"),
                "grade_percentile": qizhong.get("grade_percentile"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["raw_score"] == 81
        assert data["grade_score"] is not None
        assert data["grade_percentile"] is not None


class TestFrontendSourceGuard:
    """前端三个源码不含总分旁路、TotalScore、多学科概念。"""

    @staticmethod
    def _read(rel_path):
        from pathlib import Path
        p = (
            Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "app" / "student" / rel_path
        )
        return p.read_text(encoding="utf-8")

    def test_student_list_page_no_forbidden_tokens(self):
        source = self._read("page.tsx")
        forbidden = (
            "latest_total_score",
            "latest_xueji_rank",
            "ALL_SUBJECTS",
            "main_total_trend",
            "five_trend",
            "plus3_trend",
            "san3_trend",
            "TotalScore",
        )
        leaked = [t for t in forbidden if t in source]
        assert not leaked, f"学生列表页含禁用 token: {leaked}"

    def test_student_detail_page_no_forbidden_tokens(self):
        source = self._read("[id]/page.tsx")
        forbidden = (
            "ALL_SUBJECTS",
            "main_total_trend",
            "five_trend",
            "plus3_trend",
            "san3_trend",
            "subject_trend",
            "class_rank_basis",
            "TotalScore",
            "主三门",
            "五门",
            "+3",
            "3+3",
        )
        leaked = [t for t in forbidden if t in source]
        assert not leaked, f"学生详情页含禁用 token: {leaked}"

    def test_student_report_page_no_forbidden_tokens(self):
        source = self._read("[id]/report/page.tsx")
        forbidden = (
            "ALL_SUBJECTS",
            "main_total_trend",
            "five_trend",
            "TotalScore",
            "主三门",
            "五门",
            "+3",
            "3+3",
        )
        leaked = [t for t in forbidden if t in source]
        assert not leaked, f"学生报告页含禁用 token: {leaked}"

    def test_student_detail_page_uses_class_scope(self):
        """详情页使用 ClassScopeProvider 并传 teaching_class_id。"""
        source = self._read("[id]/page.tsx")
        assert "useClassScope" in source or "ClassScopeProvider" in source, \
            "详情页应使用 useClassScope"


# ════════════════════════════════════════════════════════════════
#  审查修复测试：per-class 排名、选修 grade_score、同分 competition、
#  grade 筛选保留空分成员、其他学科不污染 grades
# ════════════════════════════════════════════════════════════════


class TestReviewerFixesScopeRank:
    """审查 REJECT 修复：scope_rank 按教学班独立排名、选修用 grade_score、
    同分 competition ranking、grade 筛选保留空分成员、其他学科不污染 grades。"""

    _SETUP_PHYSICS_TEACHER = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import (
            Teacher, TeachingClass, TeachingClassMember, Exam,
            SubjectScore,
        )
        t = Teacher(subject="物理", name="物理老师")
        db.add(t)
        db.flush()
        tc = TeachingClass(grade=2, label="A班", subject="物理", kind="教学")
        db.add(tc)
        db.flush()
        for sid in ["s1", "s2"]:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
        db.commit()
        exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
        db.add(exam)
        db.flush()
        db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
            raw_score=100, grade_score=40, grade_percentile=0.5,
            name="学生1", class_num=1))
        db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="物理",
            raw_score=50, grade_score=70, grade_percentile=0.3,
            name="学生2", class_num=1))
        db.commit()
        db.close()
    """)

    _SETUP_SAME_SCORE = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import (
            Teacher, TeachingClass, TeachingClassMember, Exam,
            SubjectScore,
        )
        t = Teacher(subject="数学", name="数学老师")
        db.add(t)
        db.flush()
        tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
        db.add(tc)
        db.flush()
        for sid in ["s1", "s2", "s3"]:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
        db.commit()
        exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
        db.add(exam)
        db.flush()
        db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学",
            raw_score=80, name="学生1", class_num=1))
        db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="数学",
            raw_score=80, name="学生2", class_num=1))
        db.add(SubjectScore(exam_id=exam.id, student_id="s3", subject="数学",
            raw_score=85, name="学生3", class_num=1))
        db.commit()
        db.close()
    """)

    def test_per_class_rank_in_all_mode(self, tmp_path):
        """全部模式下 scope_rank 按各自教学班独立计算。
        A班(s1=81,s2=82,s3=83) B班(s4=84,s5=85)。
        s1 在 A班内第3；s4 在 B班内第2。不混排为全年级。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            s4 = [s for s in students if s["student_id"] == "s4"][0]
            result = {
                "status": "ok",
                "s1_rank": s1.get("scope_rank"),
                "s4_rank": s4.get("scope_rank"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["s1_rank"] == 3, \
            f"s1 在 A班(81,82,83) 应为 3, 得到 {data['s1_rank']}"
        assert data["s4_rank"] == 2, \
            f"s4 在 B班(84,85) 应为 2, 得到 {data['s4_rank']}"

    def test_elective_uses_grade_score_for_rank(self, tmp_path):
        """物理（高二选考）scope_rank 用 grade_score 排名。
        s1 raw=100/grade=40, s2 raw=50/grade=70。
        按 grade_score：s2(70)>s1(40) → s2=1, s1=2。
        当前 raw_score 错误逻辑会得到 s1=1, s2=2。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            s2 = [s for s in students if s["student_id"] == "s2"][0]
            result = {
                "status": "ok",
                "s1_rank": s1.get("scope_rank"),
                "s2_rank": s2.get("scope_rank"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_PHYSICS_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["s1_rank"] == 2, \
            f"物理 s1 grade=40 应排第2, 得到 {data['s1_rank']}"
        assert data["s2_rank"] == 1, \
            f"物理 s2 grade=70 应排第1, 得到 {data['s2_rank']}"

    def test_grade_score_only_still_ranks(self, tmp_path):
        """raw_score=null 但 grade_score 有效时仍应有排名（选修学科）。
        s1 raw=null/grade=40, s2 raw=50/grade=70 → s1=2, s2=1。"""
        setup = self._SETUP_PHYSICS_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import SubjectScore, Exam
            exam = db.query(Exam).filter(Exam.name == "期中").first()
            s1_row = db.query(SubjectScore).filter(
                SubjectScore.exam_id == exam.id,
                SubjectScore.student_id == "s1",
                SubjectScore.subject == "物理",
            ).first()
            s1_row.raw_score = None
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            s2 = [s for s in students if s["student_id"] == "s2"][0]
            result = {
                "status": "ok",
                "s1_rank": s1.get("scope_rank"),
                "s2_rank": s2.get("scope_rank"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["s1_rank"] == 2, \
            f"raw=null/grade=40 应排第2, 得到 {data['s1_rank']}"
        assert data["s2_rank"] == 1, \
            f"grade=70 应排第1, 得到 {data['s2_rank']}"

    def test_competition_ranking_same_score(self, tmp_path):
        """同分应同名次（competition ranking）。
        s3=85(第1), s1=80, s2=80（同为第2）。enumerate 会给出 1,2,3。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            by_id = {s["student_id"]: s for s in students}
            result = {
                "status": "ok",
                "s1_rank": by_id.get("s1", {}).get("scope_rank"),
                "s2_rank": by_id.get("s2", {}).get("scope_rank"),
                "s3_rank": by_id.get("s3", {}).get("scope_rank"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_SAME_SCORE, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["s3_rank"] == 1, f"s3=85 应第1, 得到 {data['s3_rank']}"
        assert data["s1_rank"] == 2, f"s1=80 应第2, 得到 {data['s1_rank']}"
        assert data["s2_rank"] == 2, f"s2=80 同分应第2, 得到 {data['s2_rank']}"

    def test_grade_filter_preserves_members_without_scores(self, tmp_path):
        """grade 过滤按教学班年级保留成员，不按是否有当前学科成绩删除。
        nomath 是 A班(grade=2)合法成员但无数学成绩。"""
        setup = _SETUP_MATH_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import TeachingClass, TeachingClassMember
            a_tc = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            db.add(TeachingClassMember(teaching_class_id=a_tc.id, student_id="nomath", source="manual"))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/students?teaching_class_id={a_id}&grade=2")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            nomath = [s for s in students if s["student_id"] == "nomath"]
            result = {
                "status": "ok",
                "has_nomath": len(nomath) > 0,
                "total_count": len(students),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["has_nomath"], \
            f"nomath 是 A班合法成员应在花名册, 得到 {data}"

    def test_other_subject_does_not_contaminate_grades(self, tmp_path):
        """其他学科成绩不污染当前学科的 grades 元数据。
        s1 数学只在 grade 2，但物理在 grade 1 有成绩。
        作为数学教师查看时 grades 不应包含 grade 1。"""
        setup = _SETUP_MATH_TEACHER + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore
            exam_g1 = Exam(name="高一物理", grade=1, semester="下", exam_type="期末", exam_date="2025-06")
            db.add(exam_g1)
            db.flush()
            db.add(SubjectScore(exam_id=exam_g1.id, student_id="s1", subject="物理",
                raw_score=60, name="学生1", class_num=1, xueji=252001))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students")
            assert r.status_code == 200, r.text
            students = r.json().get("students", [])
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            result = {"status": "ok", "grades": s1.get("grades")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert 1 not in data["grades"], \
            f"grade 1 物理成绩不应出现在数学 grades 中, 得到 {data['grades']}"


class TestStudentProfileScopeRankFix:
    """get_student scope_rank 修复：选修学科用 grade_score。"""

    _SETUP_PHYSICS = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import (
            Teacher, TeachingClass, TeachingClassMember, Exam,
            SubjectScore,
        )
        t = Teacher(subject="物理", name="物理老师")
        db.add(t)
        db.flush()
        tc = TeachingClass(grade=2, label="A班", subject="物理", kind="教学")
        db.add(tc)
        db.flush()
        for sid in ["s1", "s2"]:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
        db.commit()
        exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
        db.add(exam)
        db.flush()
        db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
            raw_score=100, grade_score=40, grade_percentile=0.5,
            name="学生1", class_num=1))
        db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="物理",
            raw_score=50, grade_score=70, grade_percentile=0.3,
            name="学生2", class_num=1))
        db.commit()
        db.close()
    """)

    def test_profile_scope_rank_uses_grade_score_for_elective(self, tmp_path):
        """物理画像 scope_rank 用 grade_score 排名。
        s1 raw=100/grade=40, s2 raw=50/grade=70 → s1=2, s2=1。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/s1")
            assert r.status_code == 200, r.text
            trend = r.json().get("score_trend", [])
            qizhong = [t for t in trend if t["exam_name"] == "期中"][0]
            result = {"status": "ok", "scope_rank": qizhong.get("scope_rank")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_PHYSICS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["scope_rank"] == 2, \
            f"物理 s1 grade=40 应排第2, 得到 {data['scope_rank']}"

    def test_profile_scope_rank_competition_tie(self, tmp_path):
        """物理画像同分 competition ranking。
        s1 raw=100/grade=40, s2 raw=100/grade=40 → s1=1, s2=1。"""
        setup = self._SETUP_PHYSICS + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import SubjectScore, Exam
            exam = db.query(Exam).filter(Exam.name == "期中").first()
            s2_row = db.query(SubjectScore).filter(
                SubjectScore.exam_id == exam.id,
                SubjectScore.student_id == "s2",
                SubjectScore.subject == "物理",
            ).first()
            s2_row.raw_score = 100
            s2_row.grade_score = 40
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/students/s1")
            assert r.status_code == 200, r.text
            trend = r.json().get("score_trend", [])
            qizhong = [t for t in trend if t["exam_name"] == "期中"][0]
            result = {"status": "ok", "scope_rank": qizhong.get("scope_rank")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["scope_rank"] == 1, \
            f"物理 s1 grade=40 同 s2 应并列第1, 得到 {data['scope_rank']}"
