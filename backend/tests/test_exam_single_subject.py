"""阶段2：考试列表与详情单学科化（严格 TDD 测试）。

覆盖范围（评审人要求）：
- resolve_exam_context 领域函数（学科 + 成员范围解析）
- /api/exams 只返回当前任教学科在允许成员范围内确有成绩的考试
- /api/exams/{id} 学生明细/统计/分布/排名全部基于当前任教学科 SubjectScore
- A/B 两个教学班「当前班」与「全部」成员范围正确，全部模式去重
- 只有其他学科成绩的考试不出现在考试列表
- 测试数据**包含 TotalScore 与其他学科 SubjectScore**，断言 API 响应
  不再暴露 total_scores / by_total_type / 主三门 / total_averages
- 无有效教学范围或越权教学班时返回 4xx，不退化为全年级
- /api/exams 支持 teaching_class_id 参数（当前班 vs 全部班切换）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

# ════════════════════════════════════════════════════════════════
#  领域函数测试（内存 SQLite，完全隔离）
# ════════════════════════════════════════════════════════════════

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    Teacher,
    TeachingClass,
    TeachingClassMember,
)


def _mem_db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _setup_teacher_with_classes(db, subject="数学", classes=None):
    """创建教师 + 学科 + 教学班 + 成员。classes: [(label, [student_ids], grade)]"""
    t = Teacher(subject=subject)
    db.add(t)
    db.flush()
    tc_ids = []
    for label, sids, grade in (classes or []):
        tc = TeachingClass(grade=grade, label=label, subject=subject, kind="教学")
        db.add(tc)
        db.flush()
        tc_ids.append(tc.id)
        for sid in sids:
            db.add(TeachingClassMember(
                teaching_class_id=tc.id, student_id=sid, source="manual"
            ))
    db.commit()
    return tc_ids


class TestResolveExamContext:
    """resolve_exam_context：学科解析 + 成员范围解析。"""

    def test_current_class_returns_that_class_members(self):
        db = _mem_db()
        tc_ids = _setup_teacher_with_classes(db, "数学", [
            ("A班", ["s1", "s2", "s3"], 2),
            ("B班", ["s4", "s5"], 2),
        ])
        from app.analysis.exam_context import resolve_exam_context

        ctx = resolve_exam_context(db, teaching_class_id=tc_ids[0])
        assert ctx.subject == "数学"
        assert ctx.member_ids == {"s1", "s2", "s3"}
        db.close()

    def test_all_classes_returns_union_dedup(self):
        db = _mem_db()
        _setup_teacher_with_classes(db, "数学", [
            ("A班", ["s1", "s2", "s3"], 2),
            ("B班", ["s3", "s4", "s5"], 2),  # s3 跨班
        ])
        from app.analysis.exam_context import resolve_exam_context

        ctx = resolve_exam_context(db, teaching_class_id=None)
        assert ctx.subject == "数学"
        assert ctx.member_ids == {"s1", "s2", "s3", "s4", "s5"}  # 去重
        db.close()

    def test_no_subject_raises_not_configured(self):
        db = _mem_db()
        t = Teacher(subject=None)
        db.add(t)
        db.commit()
        from app.analysis.exam_context import resolve_exam_context
        from app.teaching.subject import SubjectNotConfiguredError

        with pytest.raises(SubjectNotConfiguredError):
            resolve_exam_context(db)
        db.close()

    def test_no_teaching_classes_raises_no_scope(self):
        db = _mem_db()
        t = Teacher(subject="数学")
        db.add(t)
        db.commit()
        from app.analysis.exam_context import resolve_exam_context, NoTeachingScopeError

        with pytest.raises(NoTeachingScopeError):
            resolve_exam_context(db)
        db.close()

    def test_classes_without_members_raises_no_scope(self):
        db = _mem_db()
        _setup_teacher_with_classes(db, "数学", [("A班", [], 2)])
        from app.analysis.exam_context import resolve_exam_context, NoTeachingScopeError

        with pytest.raises(NoTeachingScopeError):
            resolve_exam_context(db)
        db.close()

    def test_invalid_teaching_class_id_raises(self):
        """不存在的 teaching_class_id 必须抛 ValueError，不能静默退化为全年级。"""
        db = _mem_db()
        _setup_teacher_with_classes(db, "数学", [("A班", ["s1"], 2)])
        from app.analysis.exam_context import resolve_exam_context

        with pytest.raises(ValueError):
            resolve_exam_context(db, teaching_class_id=99999)
        db.close()


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
    """在子进程中用全新临时 DB 运行 API 测试，返回 stdout。

    setup_code 在 app 导入后执行（可操作 SessionLocal 填数据）。
    assert_code 在 setup 后执行（client 已可用），其末行应 print(json.dumps(result))。
    """
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
    # 确保用同一 venv
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


# 测试数据：数学教师，两个高二教学班；考试1 含数学+物理+TotalScore，考试2 只含物理
_SETUWITH_TOTALS = textwrap.dedent("""\
    # 教师=数学，两个高二教学班
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, TotalScore, ClassAverage,
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

    # 考试1: 有数学和物理成绩 + TotalScore（主三门/3+3）+ ClassAverage
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam1)
    db.flush()
    # 数学成绩（任教学科）：含 raw_score、grade_score、grade_percentile
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=80+i, grade_score=70+i*0.5, grade_percentile=0.9-i*0.05,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    # 物理成绩（非任教学科）——必须被完全隔离
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="物理",
            raw_score=50+i, grade_score=60+i*0.5, grade_percentile=0.5,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    # TotalScore（主三门 + 3+3）——单学科化后不应再出现在考试详情
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(TotalScore(exam_id=exam1.id, student_id=sid, total_type="主三门",
            total_score=280+i, xueji_rank=10+i, grade_percentile=0.8))
        db.add(TotalScore(exam_id=exam1.id, student_id=sid, total_type="3+3",
            total_score=480+i, xueji_rank=5+i, grade_percentile=0.7))
    # ClassAverage（含多学科与 total_averages）
    db.add(ClassAverage(exam_id=exam1.id, class_num=1, class_label="A班",
        class_type="平行", teacher_name="某老师",
        subject_averages={"语文": 100, "数学": 85, "物理": 60},
        total_averages={"主三门": 280, "3+3": 480}))
    db.commit()

    # 考试2: 只有物理成绩（数学老师不应看到这场）
    exam2 = Exam(name="物理月考", grade=2, semester="上", exam_type="月考", exam_date="2025-10")
    db.add(exam2)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="物理",
            raw_score=60+i, name=f"学生{i}", class_num=1))
    db.commit()

    db.close()
""")


class TestExamsListSingleSubject:
    """/api/exams 只返回当前任教学科在允许范围内有成绩的考试。"""

    def test_exam_with_only_other_subject_excluded(self, tmp_path):
        """只有物理成绩的考试不出现在数学老师的考试列表。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            assert r.status_code == 200, r.text
            data = r.json()
            exam_names = [e["name"] for e in data["exams"]]
            assert "期中" in exam_names          # 有数学成绩 → 出现
            assert "物理月考" not in exam_names   # 只有物理 → 隐藏
            result = {"status": "ok", "exam_names": exam_names}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"

    def test_no_subject_configured_returns_error(self, tmp_path):
        """教师未配置 subject 时 /api/exams 返回明确错误（不退化为全年级）。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Teacher
            t = Teacher(subject=None)
            db.add(t)
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            result = {"status_code": r.status_code, "body": r.json()}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status_code"] in (400, 409), f"期望4xx, 得到 {data['status_code']}"

    def test_no_teaching_scope_returns_error(self, tmp_path):
        """有 subject 但无教学班成员时 /api/exams 返回明确错误。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Teacher
            t = Teacher(subject="数学")
            db.add(t)
            db.commit()
            # 添加一场考试和成绩
            from app.db.models import Exam, SubjectScore
            exam = Exam(name="考试", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam)
            db.flush()
            db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学", raw_score=80))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            result = {"status_code": r.status_code, "body": r.json()}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status_code"] in (400, 409), f"期望4xx, 得到 {data['status_code']}"

    def test_list_current_class_only_subject_scoped_exams(self, tmp_path):
        """teaching_class_id 参数：只返回该班成员有当前任教学科成绩的考试。"""
        assert_code = textwrap.dedent("""\
            # 先取 A 班 id
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/exams?teaching_class_id={a_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            exam_names = [e["name"] for e in data["exams"]]
            assert "期中" in exam_names
            assert "物理月考" not in exam_names
            result = {"status": "ok", "exam_names": exam_names}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"

    def test_exam_with_only_percentile_excluded(self, tmp_path):
        """当前学科只有 grade_percentile、raw_score 和 grade_score 均为空的考试不出现在列表。"""
        setup = _SETUWITH_TOTALS + textwrap.dedent("""\
            # 考试3: 数学只有百分位、无原始分和等级分（残留行）
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore
            exam3 = Exam(name="百分位残留", grade=2, semester="上", exam_type="月考", exam_date="2025-09")
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
            r = client.get("/api/exams")
            assert r.status_code == 200, r.text
            data = r.json()
            exam_names = [e["name"] for e in data["exams"]]
            assert "期中" in exam_names              # 有真实分数 → 出现
            assert "百分位残留" not in exam_names     # 只有百分位 → 隐藏
            result = {"status": "ok", "exam_names": exam_names}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert "百分位残留" not in data["exam_names"], \
            f"只有百分位的考试不应出现: {data}"


class TestExamDetailSingleSubject:
    """/api/exams/{id} 全部基于当前任教学科 SubjectScore，完全隔离其他学科与总分。"""

    @staticmethod
    def _get_qizhong_id():
        return textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
        """)

    def test_student_detail_only_has_teaching_subject(self, tmp_path):
        """同一学生同一考试的物理成绩必须完全隔离；学生对象携带当前学科
        原始分/等级分/百分位字段，不再有 subject_scores 多科字典。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            students = detail.get("students", [])
            assert len(students) > 0, "无学生数据"
            s1 = [s for s in students if s["student_id"] == "s1"][0]
            # 单学科化：学生对象不再有 subject_scores 字典；改用扁平 raw_score 字段
            has_subject_scores_dict = "subject_scores" in s1
            has_raw_score = "raw_score" in s1 and s1["raw_score"] is not None
            result = {
                "status": "ok",
                "has_subject_scores_dict": has_subject_scores_dict,
                "has_raw_score": has_raw_score,
                "raw_score": s1.get("raw_score"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["has_raw_score"], f"s1 应有当前学科 raw_score: {data}"
        assert not data["has_subject_scores_dict"], \
            f"单学科化后不应再有 subject_scores 多科字典: {data}"

    def test_student_detail_no_total_scores_field(self, tmp_path):
        """考试详情学生对象不再携带 total_scores / total_score / grade_rank 字段。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            students = detail.get("students", [])
            assert len(students) > 0
            sample_keys = set(students[0].keys())
            result = {
                "has_total_scores": "total_scores" in sample_keys,
                "has_total_score": "total_score" in sample_keys,
                "has_grade_rank": "grade_rank" in sample_keys,
                "sample_keys": sorted(sample_keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert not data["has_total_scores"], f"学生不应有 total_scores: {data}"
        assert not data["has_total_score"], f"学生不应有 total_score: {data}"
        assert not data["has_grade_rank"], f"学生不应有 grade_rank: {data}"

    def test_stats_no_by_total_type_or_main_total(self, tmp_path):
        """stats 不再包含 by_total_type / avg_main_total / main_total 等总分维度。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            stats_keys = set(detail.get("stats", {}).keys())
            result = {
                "has_by_total_type": "by_total_type" in stats_keys,
                "has_avg_main_total": "avg_main_total" in stats_keys,
                "has_main_total": "main_total" in stats_keys,
                "stats_keys": sorted(stats_keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert not data["has_by_total_type"], f"stats 不应有 by_total_type: {data}"
        assert not data["has_avg_main_total"], f"stats 不应有 avg_main_total: {data}"
        assert not data["has_main_total"], f"stats 不应有 main_total: {data}"

    def test_rank_distribution_is_single_subject(self, tmp_path):
        """rank_distribution 不再按 主三门/+3/3+3 等总分类型分列。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            rd = detail.get("rank_distribution", [])
            # 收集每个 bucket 除 band 外的所有 key
            total_type_keys = set()
            for bucket in rd:
                for k in bucket:
                    if k != "band":
                        total_type_keys.add(k)
            result = {
                "total_type_keys": sorted(total_type_keys),
                "has_main_total": "主三门" in total_type_keys,
                "has_3plus3": "3+3" in total_type_keys,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert not data["has_main_total"], f"rank_distribution 不应有 主三门 列: {data}"
        assert not data["has_3plus3"], f"rank_distribution 不应有 3+3 列: {data}"

    def test_class_averages_only_current_subject(self, tmp_path):
        """class_averages 只返回当前任教学科，不泄漏其他学科与 total_averages。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            cas = detail.get("class_averages", [])
            result = {
                "subject_avg_keys": set(),
                "has_total_averages_key": False,
                "has_physics_in_subject": False,
            }
            for ca in cas:
                sa = ca.get("subject_averages") or {}
                result["subject_avg_keys"] |= set(sa.keys())
                if ca.get("total_averages") is not None:
                    result["has_total_averages_key"] = True
                if "物理" in sa:
                    result["has_physics_in_subject"] = True
            result["subject_avg_keys"] = sorted(result["subject_avg_keys"])
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert not data["has_total_averages_key"], \
            f"class_averages 不应有 total_averages: {data}"
        assert not data["has_physics_in_subject"], \
            f"class_averages 不应含物理: {data}"
        # 应只含当前任教学科 数学
        assert "数学" in data["subject_avg_keys"], \
            f"class_averages 应含数学: {data}"

    def test_current_class_only_includes_that_class_members(self, tmp_path):
        """当前班模式只包含该班成员（A班 s1-s3），不含 B班 s4-s5。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r2 = client.get(f"/api/exams/{exam_id}?teaching_class_id={a_id}")
            assert r2.status_code == 200, r2.text
            students = r2.json().get("students", [])
            student_ids = sorted(s["student_id"] for s in students)
            result = {"status": "ok", "student_ids": student_ids}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["student_ids"] == ["s1", "s2", "s3"], f"A班应只有 s1-s3: {data}"

    def test_all_classes_mode_includes_union(self, tmp_path):
        """全部教学班模式包含所有教学班成员并集（s1-s5）。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            students = r2.json().get("students", [])
            student_ids = sorted(s["student_id"] for s in students)
            result = {"status": "ok", "student_ids": student_ids}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["student_ids"] == ["s1", "s2", "s3", "s4", "s5"], \
            f"全部模式应包含 s1-s5: {data}"

    def test_invalid_class_does_not_degrade_to_full_grade(self, tmp_path):
        """越权或不存在的教学班 id 不退化为全年级数据。"""
        assert_code = self._get_qizhong_id() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}?teaching_class_id=99999")
            result = {"status_code": r2.status_code}
            if r2.status_code == 200:
                result["student_count"] = len(r2.json().get("students", []))
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status_code"] in (400, 403, 404), \
            f"越权教学班应返回4xx, 得到 {data['status_code']}"

    def test_student_without_current_subject_excluded(self, tmp_path):
        """只有 TotalScore、没有当前任教学科 SubjectScore 的学生不应出现在详情。"""
        setup = _SETUWITH_TOTALS + textwrap.dedent("""\
            # 额外：加一个只有 TotalScore、没有数学 SubjectScore 的学生
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore, TotalScore, TeachingClass, TeachingClassMember
            exam1 = db.query(Exam).filter(Exam.name == "期中").first()
            a_tc = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            db.add(TeachingClassMember(teaching_class_id=a_tc.id, student_id="ghost", source="manual"))
            db.add(SubjectScore(exam_id=exam1.id, student_id="ghost", subject="物理",
                raw_score=99, name="幽灵", class_num=1))
            db.add(TotalScore(exam_id=exam1.id, student_id="ghost", total_type="主三门",
                total_score=300, xueji_rank=1))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            students = r2.json().get("students", [])
            student_ids = [s["student_id"] for s in students]
            result = {"status": "ok", "student_ids": student_ids, "has_ghost": "ghost" in student_ids}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert not data["has_ghost"], f"幽灵学生不应出现: {data}"
        assert "ghost" not in data["student_ids"], \
            f"幽灵学生不应在 students 列表: {data}"

    def test_empty_score_rows_excluded_from_detail(self, tmp_path):
        """当前学科 raw_score 与 grade_score 均为空的残留行（学生在教学班范围内）
        不进入 students / total_students / 分布。"""
        setup = _SETUWITH_TOTALS + textwrap.dedent("""\
            # empty1 是 A 班成员，但期中数学只有百分位、无原始分/等级分（残留行）
            db = SessionLocal()
            from app.db.models import Exam, SubjectScore, TeachingClass, TeachingClassMember
            exam1 = db.query(Exam).filter(Exam.name == "期中").first()
            a_tc = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            db.add(TeachingClassMember(teaching_class_id=a_tc.id, student_id="empty1", source="manual"))
            db.add(SubjectScore(exam_id=exam1.id, student_id="empty1", subject="数学",
                raw_score=None, grade_score=None, grade_percentile=0.5,
                name="空分学生", class_num=1, xueji=252099))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            student_ids = [s["student_id"] for s in detail.get("students", [])]
            total = detail.get("stats", {}).get("total_students")
            result = {
                "status": "ok",
                "student_ids": sorted(student_ids),
                "total_students": total,
                "has_empty1": "empty1" in student_ids,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert not data["has_empty1"], f"空分行学生不应出现在 students: {data}"
        assert "empty1" not in data["student_ids"], \
            f"空分行学生不应在 students 列表: {data}"
        # 期中原始 5 人（s1-s5），空分行不应使 total_students 变成 6
        assert data["total_students"] == 5, \
            f"total_students 应为 5（不含空分行）, 得到 {data['total_students']}"


# ════════════════════════════════════════════════════════════════
#  补充覆盖（任务要求中未覆盖的视角）
# ════════════════════════════════════════════════════════════════

# 物理教师 fixture：同样的考试数据，但教师=物理
_SETUP_PHYSICS_TEACHER = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore,
    )

    t = Teacher(subject="物理", name="物理老师")
    db.add(t)
    db.flush()

    for label, sids in [("A班", ["s1","s2","s3"]), ("B班", ["s4","s5"])]:
        tc = TeachingClass(grade=2, label=label, subject="物理", kind="教学")
        db.add(tc)
        db.flush()
        for sid in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    # 考试1: 有物理和数学成绩
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam1)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="物理",
            raw_score=50+i, name=f"学生{i}", class_num=1))
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=80+i, name=f"学生{i}", class_num=1))
    db.commit()

    # 考试2: 只有数学成绩（物理老师不应看到）
    exam2 = Exam(name="数学月考", grade=2, semester="上", exam_type="月考", exam_date="2025-10")
    db.add(exam2)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="数学",
            raw_score=70+i, name=f"学生{i}", class_num=1))
    db.commit()

    db.close()
""")


class TestClassAverageScopeIsolation:
    """class_averages 范围隔离：选择 A 班时只返回 A 班当前学科均分，
    不返回 B 班或其他班的官方 ClassAverage 行；全部模式只返回教师所教教学班
    范围内的当前学科均分，不包含 total_averages 或其他学科键。"""

    # 双官方均分 fixture：A班/B班各有自己的 ClassAverage 行（不同数学均分）
    _SETUP_DUAL_OFFICIAL = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import (
            Teacher, TeachingClass, TeachingClassMember, Exam,
            SubjectScore, ClassAverage,
        )

        t = Teacher(subject="数学", name="数学老师")
        db.add(t)
        db.flush()

        for label, sids, cnum in [("A班", ["s1","s2","s3"], 1), ("B班", ["s4","s5"], 2)]:
            tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
            db.add(tc)
            db.flush()
            for sid in sids:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
        db.commit()

        exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
        db.add(exam)
        db.flush()
        # A班数学：81,82,83 → 均分 82；B班数学：84,85 → 均分 84.5
        for i, sid in enumerate(["s1","s2","s3"], 1):
            db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
                raw_score=80+i, grade_score=70+i*0.5, name=f"A学生{i}", class_num=1, xueji=252000+i))
        for i, sid in enumerate(["s4","s5"], 1):
            db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
                raw_score=83+i, grade_score=68+i*0.5, name=f"B学生{i}", class_num=2, xueji=252010+i))
        # 官方 ClassAverage：A班数学均分 82，B班数学均分 84.5（不同值便于辨认泄漏）
        db.add(ClassAverage(exam_id=exam.id, class_num=1, class_label="A班",
            class_type="平行", teacher_name="A老师",
            subject_averages={"数学": 82, "物理": 50},
            total_averages={"主三门": 280}))
        db.add(ClassAverage(exam_id=exam.id, class_num=2, class_label="B班",
            class_type="平行", teacher_name="B老师",
            subject_averages={"数学": 84.5, "物理": 55},
            total_averages={"主三门": 290}))
        db.commit()
        db.close()
    """)

    @staticmethod
    def _get_qizhong_id_and_a_class():
        return textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
        """)

    def test_select_class_a_returns_only_a_class_average(self, tmp_path):
        """选择 A 教学班时 class_averages 只返回 A 班行，不返回 B 班行。"""
        assert_code = self._get_qizhong_id_and_a_class() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}?teaching_class_id={a_id}")
            assert r2.status_code == 200, r2.text
            cas = r2.json().get("class_averages", [])
            labels = [c.get("class_label") for c in cas]
            result = {
                "status": "ok",
                "labels": labels,
                "has_B": "B班" in labels,
                "count": len(cas),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_DUAL_OFFICIAL, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert not data["has_B"], \
            f"选择 A 班时不应返回 B 班 class_average: {data}"
        assert data["count"] == 1, \
            f"选择 A 班时应只有 1 行 class_average, 得到 {data['count']}"

    def test_select_class_a_no_total_averages_or_other_subject(self, tmp_path):
        """选择 A 班时 class_averages 行只含当前学科键，无 total_averages/其他学科。"""
        assert_code = self._get_qizhong_id_and_a_class() + textwrap.dedent("""\
            r2 = client.get(f"/api/exams/{exam_id}?teaching_class_id={a_id}")
            assert r2.status_code == 200, r2.text
            cas = r2.json().get("class_averages", [])
            subj_keys = set()
            has_total = False
            for ca in cas:
                sa = ca.get("subject_averages") or {}
                subj_keys |= set(sa.keys())
                if ca.get("total_averages") is not None:
                    has_total = True
            result = {
                "subj_keys": sorted(subj_keys),
                "has_total_averages": has_total,
                "has_physics": "物理" in subj_keys,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_DUAL_OFFICIAL, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert not data["has_total_averages"], \
            f"不应有 total_averages: {data}"
        assert not data["has_physics"], \
            f"不应含物理学科: {data}"
        assert "数学" in data["subj_keys"], \
            f"应含数学: {data}"

    def test_all_mode_only_returns_my_teaching_classes(self, tmp_path):
        """全部模式只返回教师所教教学班范围内的当前学科均分，不泄漏外部班。"""
        setup = self._SETUP_DUAL_OFFICIAL + textwrap.dedent("""\
            # 加一个不在教师教学班范围内的「C班」官方均分行（模拟其他老师的班）
            db = SessionLocal()
            from app.db.models import Exam, ClassAverage, SubjectScore
            exam1 = db.query(Exam).filter(Exam.name == "期中").first()
            # C班学生 s6 不在任何教学班成员中
            db.add(SubjectScore(exam_id=exam1.id, student_id="s6", subject="数学",
                raw_score=90, name="C学生", class_num=3, xueji=252020))
            db.add(ClassAverage(exam_id=exam1.id, class_num=3, class_label="C班",
                class_type="平行", teacher_name="C老师",
                subject_averages={"数学": 90},
                total_averages={"主三门": 300}))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            cas = r2.json().get("class_averages", [])
            labels = [c.get("class_label") for c in cas]
            result = {
                "status": "ok",
                "labels": sorted(labels),
                "has_C": "C班" in labels,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert not data["has_C"], \
            f"全部模式不应返回非教师教学班的 C 班 class_average: {data}"


class TestBidirectionalSubjectFiltering:
    """学科过滤双向：数学老师只看数学考试，物理老师只看物理考试。"""

    def test_physics_teacher_sees_physics_exam_not_math_only(self, tmp_path):
        """物理老师能看到含物理成绩的考试，但看不到只有数学成绩的考试。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["subject"] == "物理"
            exam_names = [e["name"] for e in data["exams"]]
            assert "期中" in exam_names            # 有物理成绩 → 出现
            assert "数学月考" not in exam_names     # 只有数学 → 隐藏
            result = {"status": "ok", "subject": data["subject"], "exam_names": exam_names}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_PHYSICS_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["subject"] == "物理"
        assert "期中" in data["exam_names"]
        assert "数学月考" not in data["exam_names"]

    def test_physics_teacher_detail_has_physics_score_not_math(self, tmp_path):
        """物理老师查看考试详情时，学生分数是物理分数而非数学分数。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            assert detail["subject"] == "物理"
            s1 = [s for s in detail["students"] if s["student_id"] == "s1"][0]
            # s1 物理 raw_score=51, 数学 raw_score=81
            # 必须返回物理分数 51，不能是数学 81
            result = {
                "status": "ok",
                "raw_score": s1.get("raw_score"),
                "expected": 51,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_PHYSICS_TEACHER, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["raw_score"] == 51, \
            f"物理老师应看到 s1 物理分 51，得到 {data['raw_score']}"


class TestExplicitScoreValueIsolation:
    """考试详情中学生分数必须精确匹配当前学科，而非其他学科。"""

    def test_math_teacher_sees_math_score_value(self, tmp_path):
        """数学老师查看期中详情时，s1 的 raw_score 必须是数学分 81 而非物理分 51。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            detail = r2.json()
            s1 = [s for s in detail["students"] if s["student_id"] == "s1"][0]
            result = {
                "status": "ok",
                "raw_score": s1.get("raw_score"),
                "grade_percentile": s1.get("grade_percentile"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUWITH_TOTALS, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        # _SETUWITH_TOTALS: s1 数学 raw_score=81, 物理 raw_score=51
        assert data["raw_score"] == 81, \
            f"s1 数学 raw_score 应为 81，得到 {data['raw_score']}"
        # s1 数学 grade_percentile=0.85 (0.9-0.05*1), 物理为 0.5
        assert data["grade_percentile"] is not None


class TestOverlappingMembershipAPI:
    """API 层面重叠教学班成员：当前班模式只返回该班成员，全部模式返回并集去重。"""

    # 重叠成员 fixture：A班 s1,s2,s3 ; B班 s3,s4,s5（s3 跨班）
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

    def test_current_class_excludes_other_class_members(self, tmp_path):
        """当前班 A 只包含 s1,s2,s3——即使 s3 也在 B 班。"""
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = exams[0]["id"]
            r2 = client.get(f"/api/exams/{exam_id}?teaching_class_id={a_id}")
            assert r2.status_code == 200, r2.text
            students = r2.json().get("students", [])
            student_ids = sorted(s["student_id"] for s in students)
            result = {"status": "ok", "student_ids": student_ids}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_OVERLAP, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["student_ids"] == ["s1", "s2", "s3"], \
            f"A班应只有 s1-s3: {data}"

    def test_all_mode_union_dedup_overlapping(self, tmp_path):
        """全部模式返回 A∪B 并集去重：s1-s5（s3 只出现一次）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = exams[0]["id"]
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            students = r2.json().get("students", [])
            student_ids = sorted(s["student_id"] for s in students)
            # s3 跨班，全部模式应去重
            result = {"status": "ok", "student_ids": student_ids,
                      "has_dup": len(student_ids) != len(set(student_ids))}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, self._SETUP_OVERLAP, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["student_ids"] == ["s1", "s2", "s3", "s4", "s5"], \
            f"全部模式应包含 s1-s5 去重: {data}"
        assert not data["has_dup"], "s3 不应出现两次"


class TestStudentClassLabelInDetail:
    """/api/exams/{id} 每个学生行直接返回 class_label（教学范围标签），
    前端无需再调用学生汇总接口建立映射。"""

    def test_frontend_detail_has_no_student_summary_sidechannel(self):
        """考试详情源码不得重新引入会返回跨学科总分的学生汇总旁路。"""
        from pathlib import Path

        detail_page = (
            Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "app" / "exam" / "[id]" / "page.tsx"
        )
        source = detail_page.read_text(encoding="utf-8")
        forbidden = (
            "/api/students?grade",
            "latest_total_score",
            "latest_xueji_rank",
            "StudentListItem",
            "labelByStudentId",
        )
        leaked = [token for token in forbidden if token in source]
        assert not leaked, f"考试详情仍包含学生汇总数据旁路: {leaked}"

    def test_student_rows_include_class_label(self, tmp_path):
        """全部模式：A班学生 class_label='A班'，B班学生 class_label='B班'。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            r2 = client.get(f"/api/exams/{exam_id}")
            assert r2.status_code == 200, r2.text
            students = r2.json().get("students", [])
            label_by_id = {s["student_id"]: s.get("class_label") for s in students}
            result = {"status": "ok", "label_by_id": label_by_id}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(
            tmp_path, TestClassAverageScopeIsolation._SETUP_DUAL_OFFICIAL, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        labels = data["label_by_id"]
        # A班学生 s1,s2,s3
        for sid in ["s1", "s2", "s3"]:
            assert labels.get(sid) == "A班", \
                f"{sid} class_label 应为 A班, 得到 {labels.get(sid)}"
        # B班学生 s4,s5
        for sid in ["s4", "s5"]:
            assert labels.get(sid) == "B班", \
                f"{sid} class_label 应为 B班, 得到 {labels.get(sid)}"

    def test_current_class_mode_student_label(self, tmp_path):
        """当前班模式：选择 A班时学生行 class_label 仍为 'A班'。"""
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get("/api/exams")
            exams = r.json()["exams"]
            exam_id = [e["id"] for e in exams if e["name"] == "期中"][0]
            r2 = client.get(f"/api/exams/{exam_id}?teaching_class_id={a_id}")
            assert r2.status_code == 200, r2.text
            students = r2.json().get("students", [])
            labels = {s["student_id"]: s.get("class_label") for s in students}
            result = {"status": "ok", "labels": labels}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(
            tmp_path, TestClassAverageScopeIsolation._SETUP_DUAL_OFFICIAL, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status"] == "ok"
        for sid in ["s1", "s2", "s3"]:
            assert data["labels"].get(sid) == "A班", \
                f"{sid} 应标注 A班, 得到 {data['labels'].get(sid)}"


class TestSubjectConflictTeachingClass:
    """请求学科冲突的教学班必须返回 4xx，不退化为全年级。"""

    def test_conflicting_subject_class_returns_4xx(self, tmp_path):
        """数学教师请求一个 subject=物理 的教学班 → 必须返回 4xx。"""
        setup = _SETUWITH_TOTALS + textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import TeachingClass, TeachingClassMember
            # 新建一个 subject=物理 的教学班（与教师 subject=数学 冲突）
            tc = TeachingClass(grade=2, label="物理班", subject="物理", kind="教学")
            db.add(tc)
            db.flush()
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="s1", source="manual"))
            db.commit()
            conflict_id = tc.id
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            tc = db.query(TeachingClass).filter(TeachingClass.label == "物理班").first()
            conflict_id = tc.id
            db.close()
            r = client.get(f"/api/exams?teaching_class_id={conflict_id}")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = json.loads(proc.stdout.strip().split("\n")[-1])
        assert data["status_code"] in (400, 403, 404, 409), \
            f"学科冲突的教学班应返回4xx, 得到 {data['status_code']}"
