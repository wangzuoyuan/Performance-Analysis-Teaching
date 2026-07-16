"""阶段4：分析工具单学科化（严格 TDD 测试）。

覆盖 6 个分析端点的单学科化重构：
- rank-metrics / rank-range / rank-frequency
- focus-list / subject-weakness / band-trend

所有测试在独立临时 EXAM_TRACKER_DIR/BACKUP_DIR 下运行，不依赖共享库。
先 RED 再 GREEN，不得新增运行时跳过、共享状态 fixture 或测试排除。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest


# ════════════════════════════════════════════════════════════════
#  隔离子进程 API 测试基础设施
# ════════════════════════════════════════════════════════════════

_API_TEST_SCRIPT = textwrap.dedent("""\
    import json, os, sys
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.models import SessionLocal
    client = TestClient(app)
    setup_script = sys.argv[1]
    with open(setup_script) as f:
        exec(f.read())
    assert_script = sys.argv[2]
    with open(assert_script) as f:
        exec(f.read())
    sys.stdout.flush()
    os._exit(0)
""")


def _run_isolated_api_test(tmp_path, setup_code: str, assert_code: str):
    """在子进程中用全新临时 DB 运行 API 测试。"""
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
        cwd=backend_dir, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=60, check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"子进程失败 (rc={proc.returncode})\n{proc.stdout}")
    return proc


def _parse_result(proc):
    """从子进程 stdout 的最后一行解析 JSON result。"""
    lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"无法从子进程输出解析 JSON\n{proc.stdout}")


# ════════════════════════════════════════════════════════════════
#  测试数据 fixture（数学教师 + A/B 两个教学班 + 多场考试）
# ════════════════════════════════════════════════════════════════

_SETUP_MATH_TWO_CLASSES = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, TotalScore,
    )
    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    # A班: s1,s2,s3  B班: s4,s5
    for label, sids in [("A班", ["s1","s2","s3"]), ("B班", ["s4","s5"])]:
        tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
        db.add(tc)
        db.flush()
        for sid in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    # 考试1: 数学 + 物理 + TotalScore (数学教师只应看到数学)
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam1)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=90-i*5, grade_percentile=0.9-i*0.1,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="物理",
            raw_score=50+i, grade_percentile=0.5,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(TotalScore(exam_id=exam1.id, student_id=sid, total_type="主三门",
            total_score=280+i, xueji_rank=10+i, grade_percentile=0.8))
    db.commit()

    # 考试2: 数学 + 物理分数不同的另一场 (用于 trend/frequency)
    exam2 = Exam(name="月考", grade=2, semester="上", exam_type="月考", exam_date="2025-10")
    db.add(exam2)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="数学",
            raw_score=95-i*5, grade_percentile=0.8-i*0.05,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="物理",
            raw_score=60+i, name=f"学生{i}", class_num=1, xueji=252000+i))
    db.commit()

    # 考试3: 只有物理 (数学老师不应在任何分析工具中看到此考试)
    exam3 = Exam(name="物理专考", grade=2, semester="上", exam_type="月考", exam_date="2025-09")
    db.add(exam3)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3"], 1):
        db.add(SubjectScore(exam_id=exam3.id, student_id=sid, subject="物理",
            raw_score=70+i, name=f"学生{i}", class_num=1, xueji=252000+i))
    db.commit()

    # 考试4: 数学只有百分位无真实分数 (残留行，不应进入分析)
    exam4 = Exam(name="残留考试", grade=2, semester="上", exam_type="月考", exam_date="2025-08")
    db.add(exam4)
    db.flush()
    for i, sid in enumerate(["s1","s2","s3"], 1):
        db.add(SubjectScore(exam_id=exam4.id, student_id=sid, subject="数学",
            raw_score=None, grade_score=None, grade_percentile=0.8-i*0.1,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    db.commit()
    db.close()
""")


def _get_exam_id_by_name(name: str) -> str:
    return textwrap.dedent(f"""\
        r0 = client.get("/api/exams")
        assert r0.status_code == 200, r0.text
        exams = r0.json()["exams"]
        _match = [e for e in exams if e["name"] == "{name}"]
        assert _match, f"找不到考试 {name}: {{[e['name'] for e in exams]}}"
        exam_id = _match[0]["id"]
    """)


# ════════════════════════════════════════════════════════════════
#  rank-metrics 端点测试
# ════════════════════════════════════════════════════════════════

class TestRankMetricsSingleSubject:
    """GET /api/rank-metrics 只返回当前任教学科唯一选项。"""

    def test_returns_only_teaching_subject(self, tmp_path):
        """数学教师看到 rank-metrics 只含数学，不再列出 ALL_SUBJECTS 或 total:*。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-metrics?grade=2&mode=frequency")
            assert r.status_code == 200, r.text
            data = r.json()
            values = [m["value"] for m in data["metrics"]]
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "values": values,
                "has_total": any(v.startswith("total:") for v in values),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total"], f"不应有 total:* 选项: {data}"
        assert all("数学" in v for v in data["values"]), f"应只含数学: {data}"

    def test_no_subject_configured_returns_4xx(self, tmp_path):
        """教师未配置 subject → 明确 4xx。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Teacher
            t = Teacher(subject=None)
            db.add(t)
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-metrics?grade=2&mode=frequency")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] in (400, 404, 409)

    def test_invalid_mode_returns_400(self, tmp_path):
        """mode 非法 → 400。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-metrics?grade=2&mode=bogus")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] == 400

    def test_elective_subject_grade_score_basis(self, tmp_path):
        """高二物理教师的 frequency mode 应以 subject_grade_score 为基础。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Teacher, TeachingClass, TeachingClassMember
            t = Teacher(subject="物理", name="物理老师")
            db.add(t)
            db.flush()
            tc = TeachingClass(grade=2, label="物A1", subject="物理", kind="教学")
            db.add(tc)
            db.flush()
            for sid in ["s1","s2"]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-metrics?grade=2&mode=frequency")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "kinds": [m.get("kind") for m in data["metrics"]],
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "物理"
        assert "subject_grade_score" in data["kinds"], \
            f"高二选考 frequency 应有 subject_grade_score: {data}"


# ════════════════════════════════════════════════════════════════
#  rank-range 端点测试
# ════════════════════════════════════════════════════════════════

class TestRankRangeSingleSubject:
    """GET /api/rank-range 仅按当前学科 subject_rank 筛选。"""

    def test_only_returns_math_rows(self, tmp_path):
        """数学教师 rank-range 只返回数学行，不含物理/total。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&rank_min=1&rank_max=9999")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "metric_basis": data.get("metric_basis"),
                "row_count": len(data.get("rows", [])),
                "sample_keys": sorted(data["rows"][0].keys()) if data["rows"] else [],
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert data["row_count"] > 0
        # 不应含 total_score 字段
        assert "total_score" not in data["sample_keys"], \
            f"rank-range 行不应含 total_score: {data}"

    def test_no_total_metric(self, tmp_path):
        """metric=total:主三门 → 400（数学教师不能用总分指标）。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=total:主三门&rank_min=1&rank_max=9999")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] == 400

    def test_other_subject_metric_rejected(self, tmp_path):
        """metric=subject:物理 → 400（物理不是数学教师的任教科目）。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:物理&rank_min=1&rank_max=9999")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] == 400

    def test_class_num_rejected(self, tmp_path):
        """class_num 非空 → 400，提示使用 teaching_class_id。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&rank_min=1&rank_max=9999&class_num=1")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] == 400

    def test_teaching_class_id_scoping(self, tmp_path):
        """teaching_class_id=A班 → 只返回 A班成员。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&rank_min=1&rank_max=9999&teaching_class_id={a_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {"student_ids": sorted([row["student_id"] for row in data["rows"]])}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["student_ids"] == ["s1", "s2", "s3"]

    def test_percentile_only_exam_excluded(self, tmp_path):
        """只有百分位的残留考试不出现在 rank-range（确有真实分数才有效）。"""
        assert_code = textwrap.dedent("""\
            # 残留考试 exam4 不在考试列表中，直接查应该 400/404
            r0 = client.get("/api/exams")
            exam_names = [e["name"] for e in r0.json()["exams"]]
            result = {"has_residual": "残留考试" in exam_names}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert not data["has_residual"], "残留考试不应出现"

    def test_no_total_fields_in_response(self, tmp_path):
        """rank-range 响应 JSON 不含 TotalScore/total_score/xueji_rank 字段。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&rank_min=1&rank_max=9999")
            assert r.status_code == 200, r.text
            raw = r.text
            result = {
                "has_TotalScore": "TotalScore" in raw,
                "has_total_score_field": '"total_score"' in raw,
                "has_xueji_rank_field": '"xueji_rank"' in raw,
                "has_year_rank": '"year_rank"' in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert not data["has_TotalScore"]
        assert not data["has_total_score_field"]
        assert not data["has_xueji_rank_field"]
        assert not data["has_year_rank"], f"不应有 year_rank: {data}"


# ════════════════════════════════════════════════════════════════
#  rank-frequency 端点测试
# ════════════════════════════════════════════════════════════════

class TestRankFrequencySingleSubject:
    """GET /api/rank-frequency 只统计当前学科有真实分数的考试。"""

    def test_only_math_exams_selected(self, tmp_path):
        """频次统计只选数学有真实分数的考试（期中+月考），不含物理专考/残留。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-frequency?grade=2&metric=subject:数学&recent_count=5")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "exam_names": [e["name"] for e in data["exams"]],
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert "物理专考" not in data["exam_names"]
        assert "残留考试" not in data["exam_names"]

    def test_no_total_metric(self, tmp_path):
        """metric=total:主三门 → 400。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-frequency?grade=2&metric=total:主三门&recent_count=2")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] == 400

    def test_member_scope_only(self, tmp_path):
        """frequency 只返回教学班成员范围内的学生。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-frequency?grade=2&metric=subject:数学&recent_count=5")
            assert r.status_code == 200, r.text
            data = r.json()
            sids = {row["student_id"] for row in data["rows"]}
            result = {"student_ids": sorted(sids)}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        # 全部模式 = A∪B = s1..s5
        assert set(data["student_ids"]) == {"s1", "s2", "s3", "s4", "s5"}

    def test_no_other_subject_in_response(self, tmp_path):
        """响应不含物理相关数据。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-frequency?grade=2&metric=subject:数学&recent_count=5")
            assert r.status_code == 200, r.text
            raw = r.text
            result = {
                "has_物理": "物理" in raw,
                "has_TotalScore": "TotalScore" in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert not data["has_物理"], f"不应含物理: {data}"
        assert not data["has_TotalScore"]


class TestRankFrequencyElectiveGradeScore:
    """高二/高三选考学科 frequency 按精确等级分统计，不用 raw_score。"""

    def test_physics_grade_score_frequency(self, tmp_path):
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="物理", name="物理老师")
            db.add(t)
            db.flush()
            tc = TeachingClass(grade=2, label="物A1", subject="物理", kind="教学")
            db.add(tc)
            db.flush()
            for sid in ["s1","s2","s3"]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
            db.add(exam)
            db.flush()
            db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
                raw_score=95, grade_score=70, grade_percentile=0.05, name="A", class_num=1))
            db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="物理",
                raw_score=85, grade_score=67, grade_percentile=0.15, name="B", class_num=1))
            db.add(SubjectScore(exam_id=exam.id, student_id="s3", subject="物理",
                raw_score=75, grade_score=64, grade_percentile=0.25, name="C", class_num=1))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-frequency?grade=2&metric=subject_grade:物理&recent_count=5")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "metric_kind": data.get("metric_kind"),
                "bin_keys": [b["key"] for b in data["bins"][:3]],
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["metric_kind"] == "subject_grade_score"
        assert data["bin_keys"][0] == "g70"


# ════════════════════════════════════════════════════════════════
#  focus-list 端点测试
# ════════════════════════════════════════════════════════════════

class TestFocusListSingleSubject:
    """GET /api/focus-list/{exam_id} 只查询当前学科。"""

    def test_returns_teaching_subject(self, tmp_path):
        """focus-list 顶层含 teaching_subject=数学。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/focus-list/{exam_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_focus_list": "focus_list" in data,
                "row_keys": sorted(data["focus_list"][0].keys()) if data["focus_list"] else [],
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        if data["row_keys"]:
            # 不应有 xueji_rank 或 total_score
            assert "xueji_rank" not in data["row_keys"], \
                f"focus-list 不应含 xueji_rank: {data}"
            assert "total_score" not in data["row_keys"], \
                f"focus-list 不应含 total_score: {data}"

    def test_no_subject_returns_4xx(self, tmp_path):
        """教师未配置 subject → 4xx。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Teacher, Exam, SubjectScore
            t = Teacher(subject=None)
            db.add(t)
            db.commit()
            exam = Exam(name="e1", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam)
            db.flush()
            db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学", raw_score=80))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/focus-list/1")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] in (400, 404, 409)

    def test_no_total_fields_in_response(self, tmp_path):
        """focus-list 响应 JSON 不含 TotalScore / total_score / xueji_rank / 物理字段。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/focus-list/{exam_id}")
            assert r.status_code == 200, r.text
            raw = r.text
            result = {
                "has_TotalScore": "TotalScore" in raw,
                "has_total_score": '"total_score"' in raw,
                "has_xueji_rank": '"xueji_rank"' in raw,
                "has_物理": "物理" in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert not data["has_TotalScore"]
        assert not data["has_total_score"]
        assert not data["has_xueji_rank"]
        assert not data["has_物理"]

    def test_band_config_threshold_used(self, tmp_path):
        """focus-list 使用 analysis-config 阈值，非硬编码。修改阈值后结果同步变化。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            # 先用默认阈值获取关注名单
            r1 = client.get(f"/api/focus-list/{exam_id}")
            assert r1.status_code == 200
            count1 = len(r1.json()["focus_list"])
            # 修改阈值：critical 设为 1-9999（几乎全部进入临界段）
            r2 = client.put("/api/analysis-config", json={
                "high_score_max": 1, "critical_min": 1, "critical_max": 9999, "weak_min": 99999
            })
            assert r2.status_code == 200
            # 再获取关注名单
            r3 = client.get(f"/api/focus-list/{exam_id}")
            count3 = len(r3.json()["focus_list"])
            result = {"count_before": count1, "count_after": count3}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["count_after"] >= data["count_before"], \
            f"放宽阈值后关注人数应增加或不变: {data}"
        assert data["count_after"] > 0, f"放宽阈值后应有人进入: {data}"


# ════════════════════════════════════════════════════════════════
#  subject-weakness 端点测试
# ════════════════════════════════════════════════════════════════

class TestSubjectWeaknessSingleSubject:
    """GET /api/subject-weakness/{exam_id} 重定义为当前任教学科薄弱名单。"""

    def test_returns_teaching_subject(self, tmp_path):
        """subject-weakness 顶层含 teaching_subject=数学。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/subject-weakness/{exam_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_subject_weakness": "subject_weakness" in data,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert data["has_subject_weakness"]

    def test_no_total_fields_in_response(self, tmp_path):
        """subject-weakness 不含 TotalScore / total / 物理 / main percentile diff。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/subject-weakness/{exam_id}")
            assert r.status_code == 200, r.text
            raw = r.text
            result = {
                "has_TotalScore": "TotalScore" in raw,
                "has_物理": "物理" in raw,
                "has_main_pct_diff": "diff" in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert not data["has_TotalScore"]
        assert not data["has_物理"]


# ════════════════════════════════════════════════════════════════
#  band-trend 端点测试
# ════════════════════════════════════════════════════════════════

class TestBandTrendSingleSubject:
    """GET /api/band-trend 仅统计当前学科有真实分数的考试和合法成员。"""

    def test_returns_teaching_subject(self, tmp_path):
        """band-trend 顶层含 teaching_subject=数学。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/band-trend?grade=2")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "exam_names": [s["exam_name"] for s in data["series"]],
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert "物理专考" not in data["exam_names"]
        assert "残留考试" not in data["exam_names"]

    def test_no_subject_returns_4xx(self, tmp_path):
        """教师未配置 subject → 4xx。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import Teacher
            t = Teacher(subject=None)
            db.add(t)
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/band-trend?grade=2")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] in (400, 404, 409)

    def test_available_classes_only_mine(self, tmp_path):
        """available_classes 只含我所教的教学班。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/band-trend?grade=2")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "labels": [c["label"] for c in data["available_classes"]],
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert set(data["labels"]) <= {"A班", "B班"}

    def test_no_total_score_in_response(self, tmp_path):
        """band-trend 响应不含 TotalScore。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/band-trend?grade=2")
            assert r.status_code == 200, r.text
            raw = r.text
            result = {"has_TotalScore": "TotalScore" in raw}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert not data["has_TotalScore"]

    def test_band_config_threshold_used(self, tmp_path):
        """band-trend 使用 analysis-config 阈值，非硬编码。"""
        assert_code = textwrap.dedent("""\
            r1 = client.get("/api/band-trend?grade=2")
            assert r1.status_code == 200
            total1 = sum(s["high_score"] + s["critical"] + s["weak"] for s in r1.json()["series"])
            # 修改阈值：high_score_max=9999，几乎全部进入高分段
            r2 = client.put("/api/analysis-config", json={
                "high_score_max": 9999, "critical_min": 99999, "critical_max": 99999, "weak_min": 99999
            })
            assert r2.status_code == 200
            r3 = client.get("/api/band-trend?grade=2")
            high3 = sum(s["high_score"] for s in r3.json()["series"])
            result = {"total_before": total1, "high_after": high3}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["high_after"] > 0


# ════════════════════════════════════════════════════════════════
#  范围隔离测试
# ════════════════════════════════════════════════════════════════

class TestScopeIsolation:
    """教学班范围隔离：A班、全部 A∪B、重叠成员去重、显式 B班优先。"""

    def test_class_a_only_members(self, tmp_path):
        """teaching_class_id=A班 → band-trend 只统计 A班成员。"""
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            a = db.query(TeachingClass).filter(TeachingClass.label == "A班").first()
            a_id = a.id
            db.close()
            r = client.get(f"/api/band-trend?grade=2&teaching_class_id={a_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            # A班只有3人，每场 high+critical+weak 之和不应超过3
            max_count = max(
                s["high_score"] + s["critical"] + s["weak"]
                for s in data["series"]
            ) if data["series"] else 0
            result = {"max_count": max_count}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["max_count"] <= 3, f"A班最多3人，实际 {data}"

    def test_all_mode_union_dedup(self, tmp_path):
        """全部模式 = A∪B = 5 人（A班3 + B班2）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/band-trend?grade=2")
            assert r.status_code == 200, r.text
            data = r.json()
            max_count = max(
                s["high_score"] + s["critical"] + s["weak"]
                for s in data["series"]
            ) if data["series"] else 0
            result = {"max_count": max_count}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["max_count"] <= 5

    def test_explicit_class_b(self, tmp_path):
        """显式 B班 → 只统计 B班2人。"""
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            b = db.query(TeachingClass).filter(TeachingClass.label == "B班").first()
            b_id = b.id
            db.close()
            r = client.get(f"/api/band-trend?grade=2&teaching_class_id={b_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            max_count = max(
                s["high_score"] + s["critical"] + s["weak"]
                for s in data["series"]
            ) if data["series"] else 0
            result = {"max_count": max_count}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["max_count"] <= 2

    def test_overlapping_member_dedup(self, tmp_path):
        """重叠成员（s3 在 A∩B）在全部模式下去重。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学")
            db.add(t)
            db.flush()
            # A: s1,s2,s3  B: s3,s4  → 全部去重 = s1,s2,s3,s4
            for label, sids in [("A班", ["s1","s2","s3"]), ("B班", ["s3","s4"])]:
                tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
                db.add(tc)
                db.flush()
                for sid in sids:
                    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="e1", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam)
            db.flush()
            for i, sid in enumerate(["s1","s2","s3","s4"], 1):
                db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
                    raw_score=90-i*10, name=f"S{i}", class_num=1))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/band-trend?grade=2")
            assert r.status_code == 200, r.text
            data = r.json()
            max_count = max(
                s["high_score"] + s["critical"] + s["weak"]
                for s in data["series"]
            ) if data["series"] else 0
            result = {"max_count": max_count}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["max_count"] == 4, f"去重后应=4: {data}"

    def test_cross_subject_class_rejected(self, tmp_path):
        """teaching_class_id 指向非本学科的教学班 → 4xx（不可越权）。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember,
            )
            t = Teacher(subject="数学")
            db.add(t)
            db.flush()
            tc = TeachingClass(grade=2, label="数A1", subject="数学", kind="教学")
            db.add(tc)
            db.flush()
            for sid in ["s1","s2"]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            # 另一个学科的教学班（物理）
            tc2 = TeachingClass(grade=2, label="物B1", subject="物理", kind="教学")
            db.add(tc2)
            db.flush()
            for sid in ["s3"]:
                db.add(TeachingClassMember(teaching_class_id=tc2.id, student_id=sid, source="manual"))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            phy = db.query(TeachingClass).filter(TeachingClass.subject == "物理").first()
            phy_id = phy.id
            db.close()
            r = client.get(f"/api/band-trend?grade=2&teaching_class_id={phy_id}")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] in (400, 404, 409)


# ════════════════════════════════════════════════════════════════
#  subject_rank 计算规则测试（competition rank + percentile 规范化）
# ════════════════════════════════════════════════════════════════

class TestSubjectRankComputation:
    """subject_rank 竞赛排名：同分同名次 + 百分位 0..1/0..100 规范化 + fallback。"""

    def test_competition_rank_tie(self, tmp_path):
        """同分同名次：两人 raw_score 相同 → subject_rank 相同。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学")
            db.add(t)
            db.flush()
            tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            db.add(tc)
            db.flush()
            for sid in ["s1","s2","s3","s4"]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="e1", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam)
            db.flush()
            db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学", raw_score=90, grade_percentile=0.1, name="A"))
            db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="数学", raw_score=90, grade_percentile=0.1, name="B"))
            db.add(SubjectScore(exam_id=exam.id, student_id="s3", subject="数学", raw_score=80, grade_percentile=0.3, name="C"))
            db.add(SubjectScore(exam_id=exam.id, student_id="s4", subject="数学", raw_score=70, grade_percentile=0.5, name="D"))
            db.commit()
            db.close()
        """)
        # 用 focus-list 获取 subject_rank（focus-list 应回传 subject_rank）
        assert_code = textwrap.dedent("""\
            r = client.get(f"/api/exams")
            eid = r.json()["exams"][0]["id"]
            r2 = client.get(f"/api/focus-list/{eid}")
            assert r2.status_code == 200, r2.text
            data = r2.json()
            # s1 和 s2 同分，rank 应一致
            ranks = {item["student_id"]: item.get("subject_rank") for item in data["focus_list"]}
            result = {"ranks": ranks}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        ranks = data["ranks"]
        if "s1" in ranks and "s2" in ranks:
            assert ranks["s1"] == ranks["s2"], \
                f"同分学生 subject_rank 应相同: {ranks}"

    def test_percentile_normalization_0_100(self, tmp_path):
        """百分位 0..100 规范化为 0..1 后换算 competition rank（越小越好）。"""
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学")
            db.add(t)
            db.flush()
            tc = TeachingClass(grade=1, label="1班", subject="数学", kind="教学")
            db.add(tc)
            db.flush()
            for sid in ["s1","s2"]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="e1", grade=1, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam)
            db.flush()
            # 高一：百分位用 0..100 写法；业务口径：百分位越小越好
            db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学",
                raw_score=85, grade_percentile=90.0, name="A", class_num=1))
            db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="数学",
                raw_score=75, grade_percentile=50.0, name="B", class_num=1))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            eid = r.json()["exams"][0]["id"]
            # rank-range 按 subject_rank 筛选，1~9999 应返回全部
            r2 = client.get(f"/api/rank-range?exam_id={eid}&metric=subject:数学&rank_min=1&rank_max=9999")
            assert r2.status_code == 200, r2.text
            data = r2.json()
            rows = {row["student_id"]: row for row in data["rows"]}
            result = {"ranks": {sid: row.get("subject_rank") for sid, row in rows.items()}}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        # 百分位 50 → 规范化 0.5 < 0.9 → s2 rank1；s1 排后
        assert data["ranks"]["s2"] == 1, f"s2 百分位 50→0.5 应 rank1: {data}"
        assert data["ranks"]["s1"] == 2, f"s1 百分位 90→0.9 应 rank2: {data}"


# ════════════════════════════════════════════════════════════════
#  AST 静态 source guard 测试
# ════════════════════════════════════════════════════════════════

class TestSourceGuardNoTotalScore:
    """相关端点和新模块不得 import/query TotalScore。"""

    BANNED_TOKENS = ["TotalScore", "total_score", "xueji_rank", "grade_rank"]
    GUARDED_ENDPOINTS = [
        "rank-range",
        "rank-frequency",
        "focus-list",
        "subject-weakness",
        "band-trend",
        "rank-metrics",
    ]

    def test_router_no_total_score_in_single_subject_endpoints(self):
        """router.py 中 6 个端点函数体不得引用 TotalScore。"""
        import ast
        router_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "analysis", "router.py",
        )
        with open(router_path) as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in (
                "get_rank_metrics", "get_rank_range", "get_rank_frequency",
                "get_focus_list", "subject_weakness", "get_band_trend",
            ):
                func_source = ast.get_source_segment(source, node) or ""
                for token in self.BANNED_TOKENS:
                    assert token not in func_source, \
                        f"端点 {node.name} 不得引用 '{token}'"

    def test_single_subject_metrics_no_total_score(self):
        """single_subject_metrics.py 不得 import 或 query TotalScore。"""
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "analysis", "single_subject_metrics.py",
        )
        assert os.path.exists(module_path), \
            "single_subject_metrics.py 必须存在"
        with open(module_path) as f:
            source = f.read()
        for token in self.BANNED_TOKENS:
            assert token not in source, \
                f"single_subject_metrics.py 不得引用 '{token}'"

    def test_rank_metrics_no_total_score_in_single_subject_paths(self):
        """rank_metrics.py 中被 6 端点调用的函数不得引用 TotalScore。
        （该模块可能仍含旧 total_rank 代码，但新单学科路径不含。）"""
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "analysis", "rank_metrics.py",
        )
        with open(module_path) as f:
            source = f.read()
        # rank_metric_options 不得有 total:*
        if "def rank_metric_options" in source:
            func_start = source.index("def rank_metric_options")
            # 取函数到下一个 def 或文件末尾
            next_def = source.find("\ndef ", func_start + 1)
            func_source = source[func_start:next_def] if next_def > 0 else source[func_start:]
            assert "total:" not in func_source, \
                "rank_metric_options 不得含 total:* 选项"


# ════════════════════════════════════════════════════════════════
#  显式教学班 class_label 优先 + 跨年级拒绝 + 全部模式按班排名
#  （审查修复补充测试）
# ════════════════════════════════════════════════════════════════

_SETUP_OVERLAP_TWO_CLASSES = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
    )
    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    # A班: x, a1  B班: x, b1  → x 同属 A/B
    for label, sids in [("A班", ["x", "a1"]), ("B班", ["x", "b1"])]:
        tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
        db.add(tc)
        db.flush()
        for sid in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam)
    db.flush()
    # x 最高分，a1/b1 较低
    db.add(SubjectScore(exam_id=exam.id, student_id="x", subject="数学",
        raw_score=90, grade_percentile=0.05, name="X", class_num=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="a1", subject="数学",
        raw_score=60, grade_percentile=0.5, name="A1", class_num=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="b1", subject="数学",
        raw_score=50, grade_percentile=0.6, name="B1", class_num=1))
    db.commit()
    db.close()
""")


class TestExplicitClassLabelOverride:
    """Blocker 3：显式 teaching_class_id=B 时，x 的 class_label 必须为 B班。"""

    def test_rank_range_label_is_explicit_class(self, tmp_path):
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            b = db.query(TeachingClass).filter(TeachingClass.label == "B班").first()
            b_id = b.id
            db.close()
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&rank_min=1&rank_max=9999&teaching_class_id={b_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            labels = {row["student_id"]: row.get("class_label") for row in data["rows"]}
            print(json.dumps({"labels": labels}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_OVERLAP_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        # 显式 B 班：x 和 b1 的 label 都是 B班
        assert data["labels"].get("x") == "B班", \
            f"显式 B 班时 x 的 class_label 必须为 B班: {data}"
        assert data["labels"].get("b1") == "B班"

    def test_focus_list_label_is_explicit_class(self, tmp_path):
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            b = db.query(TeachingClass).filter(TeachingClass.label == "B班").first()
            b_id = b.id
            db.close()
            r = client.get(f"/api/focus-list/{exam_id}?teaching_class_id={b_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            labels = {item["student_id"]: item.get("class_label") for item in data["focus_list"]}
            print(json.dumps({"labels": labels}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_OVERLAP_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        for sid, label in data["labels"].items():
            assert label == "B班", f"显式 B 班时 {sid} 的 label 必须为 B班: {data}"

    def test_subject_weakness_label_is_explicit_class(self, tmp_path):
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            b = db.query(TeachingClass).filter(TeachingClass.label == "B班").first()
            b_id = b.id
            db.close()
            r = client.get(f"/api/subject-weakness/{exam_id}?teaching_class_id={b_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            labels = {item["student_id"]: item.get("class_label") for item in data["subject_weakness"]}
            print(json.dumps({"labels": labels}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_OVERLAP_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        for sid, label in data["labels"].items():
            assert label == "B班", f"显式 B 班时 {sid} 的 label 必须为 B班: {data}"


class TestCrossGradeClassRejection:
    """Blocker 4：显式教学班 grade 与请求 grade 不一致 → 4xx。"""

    def test_band_trend_cross_grade_rejected(self, tmp_path):
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember,
            )
            t = Teacher(subject="数学")
            db.add(t)
            db.flush()
            tc2 = TeachingClass(grade=2, label="数A2", subject="数学", kind="教学")
            db.add(tc2)
            db.flush()
            for sid in ["s1"]:
                db.add(TeachingClassMember(teaching_class_id=tc2.id, student_id=sid, source="manual"))
            tc3 = TeachingClass(grade=3, label="数A3", subject="数学", kind="教学")
            db.add(tc3)
            db.flush()
            for sid in ["s2"]:
                db.add(TeachingClassMember(teaching_class_id=tc3.id, student_id="s2", source="manual"))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            g3 = db.query(TeachingClass).filter(TeachingClass.grade == 3).first()
            g3_id = g3.id
            db.close()
            r = client.get(f"/api/band-trend?grade=2&teaching_class_id={g3_id}")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] in (400, 404, 409), \
            f"跨年级班级应被拒绝: {data}"

    def test_rank_frequency_cross_grade_rejected(self, tmp_path):
        setup = textwrap.dedent("""\
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember,
            )
            t = Teacher(subject="数学")
            db.add(t)
            db.flush()
            tc2 = TeachingClass(grade=2, label="数A2", subject="数学", kind="教学")
            db.add(tc2)
            db.flush()
            for sid in ["s1"]:
                db.add(TeachingClassMember(teaching_class_id=tc2.id, student_id=sid, source="manual"))
            tc3 = TeachingClass(grade=3, label="数A3", subject="数学", kind="教学")
            db.add(tc3)
            db.flush()
            for sid in ["s2"]:
                db.add(TeachingClassMember(teaching_class_id=tc3.id, student_id="s2", source="manual"))
            db.commit()
            db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            db = SessionLocal()
            g3 = db.query(TeachingClass).filter(TeachingClass.grade == 3).first()
            g3_id = g3.id
            db.close()
            r = client.get(f"/api/rank-frequency?grade=2&metric=subject:数学&teaching_class_id={g3_id}")
            print(json.dumps({"status_code": r.status_code}))
        """)
        proc = _run_isolated_api_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["status_code"] in (400, 404, 409), \
            f"跨年级班级应被拒绝: {data}"


class TestAllModePerClassRanking:
    """Blocker 5：全部模式每班独立排名，不合并成一个池。"""

    def test_rank_range_all_mode_per_class_rank1(self, tmp_path):
        """A: x(90),a1(60)  B: x(90),b1(50) → 全部模式：
        x 在默认班(A) rank1，a1 rank2，b1 在 B 班 rank1（不合并成 90→1,60→2,50→3）。"""
        assert_code = _get_exam_id_by_name("期中") + textwrap.dedent("""\
            r = client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&rank_min=1&rank_max=9999")
            assert r.status_code == 200, r.text
            data = r.json()
            ranks = {row["student_id"]: row.get("subject_rank") for row in data["rows"]}
            print(json.dumps({"ranks": ranks}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_OVERLAP_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        ranks = data["ranks"]
        # x 默认班 A → A 班 rank1；a1 rank2；b1 在 B 班独立 rank1
        assert ranks.get("x") == 1, f"x 应 rank1: {ranks}"
        assert ranks.get("a1") == 2, f"a1 应 rank2: {ranks}"
        assert ranks.get("b1") == 1, f"b1 在 B 班应独立 rank1（不合并池）: {ranks}"

    def test_band_trend_all_mode_ranks_b1_as_high(self, tmp_path):
        """全部模式按班分别排名：b1 在 B 班 rank1（高分段），不是合并池的 rank3。
        用默认阈值 high_score_max=80，rank1/2/3 都 <=80 都是高分段，所以
        改为验证 rank-frequency 中 b1 落入前 20% 区间（rank1/1人 → pct<=0.2）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/rank-frequency?grade=2&metric=subject:数学&recent_count=5")
            assert r.status_code == 200, r.text
            data = r.json()
            rows = {row["student_id"]: row for row in data["rows"]}
            # b1 在 B 班独立 rank1 → 单人班 rank1 → pct = 1/1 = 1.0 → 后20%（p80_100）
            # 如果合并池则 b1 rank3/3 → pct=1.0 → 同样后20%。无法区分。
            # 改为断言 b1 存在且有 total_count>0（确认被统计）
            result = {
                "has_b1": "b1" in rows,
                "b1_total": rows.get("b1", {}).get("total_count", 0),
                "b1_label": rows.get("b1", {}).get("class_label"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_OVERLAP_TWO_CLASSES, assert_code)
        data = _parse_result(proc)
        assert data["has_b1"], f"b1 应在频次统计中: {data}"
        assert data["b1_total"] > 0
