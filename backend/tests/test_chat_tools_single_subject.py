"""阶段6A：chat/tools.py 成绩工具单学科化（严格 TDD 测试）。

覆盖 chat/tools.py 所有成绩类工具从「班主任多学科/总分」模型改为
「当前教师唯一任教学科 + 合法教学班成员范围」的隔离。

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
#  隔离子进程测试基础设施
# ════════════════════════════════════════════════════════════════

_TOOL_TEST_SCRIPT = textwrap.dedent("""\
    import json, sys
    setup_script = sys.argv[1]
    assert_script = sys.argv[2]
    ns = {"json": json}
    with open(setup_script) as f:
        exec(f.read(), ns)
    with open(assert_script) as f:
        exec(f.read(), ns)
""")


def _run_tool_test(tmp_path, setup_code: str, assert_code: str):
    """在子进程中用全新临时 DB 直接调用 chat tool 函数。"""
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
        [venv_python, "-c", _TOOL_TEST_SCRIPT, str(setup_file), str(assert_file)],
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
#  测试数据 fixture（数学教师 + A/B 班 + 遗留物理班 + 跨年级班 + 诱饵数据）
# ════════════════════════════════════════════════════════════════

_SETUP_MATH_TEACHER = textwrap.dedent("""\
    from app.db.models import SessionLocal
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, TotalScore, ClassAverage,
    )
    t = Teacher(subject="数学", name="数学老师")
    db.add(t); db.flush()
    # 数学 A班 / B班（合法当前学科教学班）
    for label, sids in [("A班", ["s1","s2","s3"]), ("B班", ["s4","s5"])]:
        tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
        db.add(tc); db.flush()
        for sid in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    # 遗留物理班（不同学科 — 诱饵，不可越权）
    tc_phy = TeachingClass(grade=2, label="物C班", subject="物理", kind="教学")
    db.add(tc_phy); db.flush()
    for sid in ["s6","s7"]:
        db.add(TeachingClassMember(teaching_class_id=tc_phy.id, student_id=sid, source="manual"))
    # 跨年级数学班（高三 — 跨年级拒绝测试）
    tc_g3 = TeachingClass(grade=3, label="数A3", subject="数学", kind="教学")
    db.add(tc_g3); db.flush()
    for sid in ["s8","s9"]:
        db.add(TeachingClassMember(teaching_class_id=tc_g3.id, student_id=sid, source="manual"))
    db.commit()

    # 考试1 期中 (grade2): 数学 + 物理诱饵 + TotalScore诱饵 + ClassAverage诱饵
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11-15")
    db.add(exam1); db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=90-i*5, grade_percentile=0.9-i*0.1,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    # 物理诱饵分数（s6,s7 物理班成员 + s1-s3 也有物理分）
    for i, sid in enumerate(["s6","s7"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="物理",
            raw_score=50+i, name=f"物生{i}", class_num=2))
    for sid in ["s1","s2","s3"]:
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="物理",
            raw_score=60, grade_percentile=0.5, name="x", class_num=1))
    # TotalScore 诱饵
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(TotalScore(exam_id=exam1.id, student_id=sid, total_type="主三门",
            total_score=280+i, xueji_rank=10+i, grade_percentile=0.8))
    # ClassAverage 诱饵
    db.add(ClassAverage(exam_id=exam1.id, class_label="A班", class_num=1,
        total_averages={"主三门": 282}, subject_averages={"数学": 85, "物理": 60}))
    db.commit()

    # 考试2 月考 (grade2, 更早): 数学分数不同（供 trend）
    exam2 = Exam(name="月考", grade=2, semester="上", exam_type="月考", exam_date="2025-10-15")
    db.add(exam2); db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="数学",
            raw_score=95-i*5, grade_percentile=0.8-i*0.05,
            name=f"学生{i}", class_num=1, xueji=252000+i))
    db.commit()

    # 考试3 物理专考 (grade2): 只有物理（数学教师不应看到）
    exam3 = Exam(name="物理专考", grade=2, semester="上", exam_type="月考", exam_date="2025-09-15")
    db.add(exam3); db.flush()
    for sid in ["s1","s2","s3"]:
        db.add(SubjectScore(exam_id=exam3.id, student_id=sid, subject="物理",
            raw_score=70, name="x", class_num=1))
    db.commit()

    # 考试4 残留考试 (grade2): 数学只有百分位无真实分（诱饵，无效）
    exam4 = Exam(name="残留考试", grade=2, semester="上", exam_type="月考", exam_date="2025-08-15")
    db.add(exam4); db.flush()
    for i, sid in enumerate(["s1","s2","s3"], 1):
        db.add(SubjectScore(exam_id=exam4.id, student_id=sid, subject="数学",
            raw_score=None, grade_score=None, grade_percentile=0.8-i*0.1,
            name=f"学生{i}", class_num=1))
    db.commit()

    # 考试5 高三期中 (grade3): 数学 s8,s9（跨年级）
    exam5 = Exam(name="高三期中", grade=3, semester="上", exam_type="期中", exam_date="2026-11-15")
    db.add(exam5); db.flush()
    for i, sid in enumerate(["s8","s9"], 1):
        db.add(SubjectScore(exam_id=exam5.id, student_id=sid, subject="数学",
            raw_score=85-i*5, grade_percentile=0.7, name=f"高三{i}", class_num=1))
    db.commit()
    db.close()
""")


def _math_a_class_id() -> str:
    return textwrap.dedent("""\
        from app.db.models import SessionLocal, TeachingClass
        _db = SessionLocal()
        _a = _db.query(TeachingClass).filter(TeachingClass.label == "A班", TeachingClass.subject == "数学").first()
        a_id = _a.id
        _phy = _db.query(TeachingClass).filter(TeachingClass.subject == "物理").first()
        phy_id = _phy.id
        _g3 = _db.query(TeachingClass).filter(TeachingClass.grade == 3).first()
        g3_id = _g3.id
        _db.close()
    """)


# ════════════════════════════════════════════════════════════════
#  list_exams
# ════════════════════════════════════════════════════════════════

class TestListExamsSingleSubject:
    """list_exams 只列当前学科在合法成员中有真实分数的考试。"""

    def test_only_current_subject_exams(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import list_exams
            result = {
                "teaching_subject": "数学",
                "exam_names": [e["name"] for e in list_exams()],
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert "物理专考" not in data["exam_names"], f"不应含物理专考: {data}"
        assert "残留考试" not in data["exam_names"], f"不应含残留考试: {data}"
        # 期中、月考应有数学真实分
        assert "期中" in data["exam_names"]
        assert "月考" in data["exam_names"]

    def test_sorted_desc_and_carries_subject(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import list_exams
            exams = list_exams()
            names = [e["name"] for e in exams]
            result = {"names": names, "keys": sorted(exams[0].keys()) if exams else []}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        names = data["names"]
        # 期中(2025-11) 应在 月考(2025-10) 之前（desc）
        assert names.index("期中") < names.index("月考"), f"应按日期 desc: {names}"


# ════════════════════════════════════════════════════════════════
#  student_lookup
# ════════════════════════════════════════════════════════════════

class TestStudentLookupScoped:
    """student_lookup 只返回合法成员范围内的学生。"""

    def test_excludes_out_of_scope_students(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_lookup
            all_results = student_lookup()
            sids = {r["student_id"] for r in all_results}
            result = {"sids": sorted(sids)}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        # s6,s7 是物理班成员，不在数学教学班范围
        assert "s6" not in data["sids"], f"不应含物理班学生 s6: {data}"
        assert "s7" not in data["sids"], f"不应含物理班学生 s7: {data}"
        # s1-s5 是合法数学教学班成员
        for sid in ["s1", "s2", "s3", "s4", "s5"]:
            assert sid in data["sids"]


# ════════════════════════════════════════════════════════════════
#  student_exam_detail
# ════════════════════════════════════════════════════════════════

class TestStudentExamDetailSingleSubject:
    """student_exam_detail 只返回当前学科一科，不含 totals/其他学科。"""

    def test_only_current_subject_no_totals(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_exam_detail
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            data = student_exam_detail(student_id="s1", exam_id=eid)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_total_score": '"total_score"' in raw,
                "has_totals_key": "totals" in data,
                "has_physics": "物理" in raw,
                "has_xueji_rank": '"xueji_rank"' in raw,
                "subject_score_subject": (data.get("subject_score") or {}).get("subject"),
                "has_subject_rank": "subject_rank" in (data.get("subject_score") or {}),
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total_score"]
        assert not data["has_totals_key"]
        assert not data["has_physics"], f"不应含物理: {data}"
        assert not data["has_xueji_rank"]
        assert data["subject_score_subject"] == "数学"
        assert data["has_subject_rank"], f"应有 subject_rank: {data}"

    def test_out_of_scope_student_rejected(self, tmp_path):
        """s6 是物理班成员，不在数学合法 scope → 应拒绝或返回空。"""
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_exam_detail
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            try:
                data = student_exam_detail(student_id="s6", exam_id=eid)
                result = {"error": data.get("error"), "has_data": "subject_score" in data}
            except ValueError as e:
                result = {"error": str(e), "has_data": False}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["error"] or not data["has_data"], \
            f"s6 不在合法 scope，应被拒绝: {data}"


# ════════════════════════════════════════════════════════════════
#  student_trend
# ════════════════════════════════════════════════════════════════

class TestStudentTrendSingleSubject:
    """student_trend 只生成当前学科历史，删除 total_type/main_total_trend。"""

    def test_only_current_subject_trend(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_trend
            data = student_trend(student_id="s1")
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_main_total_trend": "main_total_trend" in data,
                "has_total_type": '"total_type"' in raw,
                "has_total_score": '"total_score"' in raw,
                "series_len": len(data.get("series", [])),
                "series_has_subject_rank": bool(data.get("series")) and "subject_rank" in data["series"][0],
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_main_total_trend"]
        assert not data["has_total_type"]
        assert not data["has_total_score"]
        assert data["series_len"] >= 2, f"应有多场考试趋势: {data}"
        assert data["series_has_subject_rank"]


# ════════════════════════════════════════════════════════════════
#  student_learning_profile
# ════════════════════════════════════════════════════════════════

class TestStudentLearningProfileSingleSubject:
    """student_learning_profile 只生成当前学科，删除多学科项。"""

    def test_no_multi_subject_fields(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_learning_profile
            data = student_learning_profile(student_id="s1")
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_main_total_trend": "main_total_trend" in data,
                "has_latest_subjects": "latest_subjects" in data,
                "has_strengths": "strengths" in data,
                "has_weaknesses": "weaknesses" in data,
                "has_total_score": '"total_score"' in raw,
                "has_physics": "物理" in raw,
                "has_series": "series" in data,
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_main_total_trend"]
        assert not data["has_latest_subjects"]
        assert not data["has_strengths"]
        assert not data["has_weaknesses"]
        assert not data["has_total_score"]
        assert not data["has_physics"], f"不应含物理: {data}"
        assert data["has_series"]


# ════════════════════════════════════════════════════════════════
#  class_trend
# ════════════════════════════════════════════════════════════════

class TestClassTrendSingleSubject:
    """class_trend 单学科化，不读 ClassAverage.total_averages。"""

    def test_current_subject_only(self, tmp_path):
        assert_code = _math_a_class_id() + textwrap.dedent("""\
            from app.chat.tools import class_trend
            data = class_trend(teaching_class_id=a_id)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_total_score": '"total_score"' in raw,
                "has_ClassAverage": "ClassAverage" in raw,
                "series_len": len(data.get("series", [])),
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total_score"]
        assert not data["has_ClassAverage"]
        assert data["series_len"] >= 2

    def test_class_num_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import class_trend
            try:
                data = class_trend(class_num=1)
                result = {"raised": False}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"class_num 应被拒绝: {data}"


# ════════════════════════════════════════════════════════════════
#  compare_classes
# ════════════════════════════════════════════════════════════════

class TestCompareClassesSingleSubject:
    """compare_classes 单学科化，不读 ClassAverage.total_averages。"""

    def test_current_subject_only(self, tmp_path):
        assert_code = _math_a_class_id() + textwrap.dedent("""\
            from app.chat.tools import compare_classes
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            data = compare_classes(exam_id=eid)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_total_score": '"total_score"' in raw,
                "row_count": len(data.get("rows", [])),
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total_score"]
        assert data["row_count"] >= 2  # A班 + B班


# ════════════════════════════════════════════════════════════════
#  focus_list
# ════════════════════════════════════════════════════════════════

class TestFocusListSingleSubject:
    """focus_list 基于 subject_rank + band_config，不查 TotalScore。"""

    def test_no_total_fields(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import focus_list
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            data = focus_list(exam_id=eid)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_total_score": '"total_score"' in raw,
                "has_xueji_rank": '"xueji_rank"' in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total_score"]
        assert not data["has_xueji_rank"]


# ════════════════════════════════════════════════════════════════
#  subject_weakness
# ════════════════════════════════════════════════════════════════

class TestSubjectWeaknessSingleSubject:
    """subject_weakness 重定义为当前学科薄弱名单。"""

    def test_current_subject_only(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import subject_weakness
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            data = subject_weakness(exam_id=eid)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_total_score": '"total_score"' in raw,
                "has_physics": "物理" in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total_score"]
        assert not data["has_physics"]


# ════════════════════════════════════════════════════════════════
#  subject_progress_ranking
# ════════════════════════════════════════════════════════════════

class TestSubjectProgressRankingSingleSubject:
    """subject_progress_ranking 固定当前学科，不接受 subject 参数。"""

    def test_subject_param_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import subject_progress_ranking
            try:
                data = subject_progress_ranking(grade=2, subject="物理")
                result = {"raised": False, "subject": data.get("subject")}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"subject 参数应被拒绝: {data}"

    def test_returns_current_subject(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import subject_progress_ranking
            data = subject_progress_ranking(grade=2)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "subject": data.get("subject"),
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学" or data["subject"] == "数学"


# ════════════════════════════════════════════════════════════════
#  multi_exam_progress_ranking
# ════════════════════════════════════════════════════════════════

class TestMultiExamProgressRankingSingleSubject:
    """multi_exam_progress_ranking 固定当前学科，不接受 metrics/total。"""

    def test_metrics_with_total_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import multi_exam_progress_ranking
            try:
                data = multi_exam_progress_ranking(grade=2, metrics=["主三门"])
                result = {"raised": False}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"metrics=['主三门'] 应被拒绝: {data}"

    def test_no_total_in_response(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import multi_exam_progress_ranking
            data = multi_exam_progress_ranking(grade=2)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_total_score": '"total_score"' in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total_score"]


# ════════════════════════════════════════════════════════════════
#  band_trend
# ════════════════════════════════════════════════════════════════

class TestBandTrendSingleSubject:
    """band_trend 基于 subject_rank，不查 TotalScore。"""

    def test_current_subject_only(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import band_trend
            data = band_trend(grade=2)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_TotalScore": "TotalScore" in raw,
                "has_total_score": '"total_score"' in raw,
                "exam_names": [s.get("exam_name") for s in data.get("series", [])],
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_TotalScore"]
        assert not data["has_total_score"]
        assert "物理专考" not in data["exam_names"]
        assert "残留考试" not in data["exam_names"]

    def test_class_num_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import band_trend
            try:
                data = band_trend(grade=2, class_num=1)
                result = {"raised": False}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"]


# ════════════════════════════════════════════════════════════════
#  custom_rank_band_trend
# ════════════════════════════════════════════════════════════════

class TestCustomRankBandTrendSingleSubject:
    """custom_rank_band_trend 基于 subject_rank，total_type 被拒绝。"""

    def test_total_type_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import custom_rank_band_trend
            try:
                data = custom_rank_band_trend(grade=2, rank_max=100, total_type="主三门")
                result = {"raised": False}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"total_type 应被拒绝: {data}"

    def test_no_total_in_response(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import custom_rank_band_trend
            data = custom_rank_band_trend(grade=2, rank_max=9999)
            raw = json.dumps(data, ensure_ascii=False, default=str)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "has_total_score": '"total_score"' in raw,
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "数学"
        assert not data["has_total_score"]


# ════════════════════════════════════════════════════════════════
#  rank_range_filter / rank_frequency_stat
# ════════════════════════════════════════════════════════════════

class TestRankRangeFilterSingleSubject:
    """rank_range_filter 委托 phase4 单学科逻辑，class_num 被拒绝。"""

    def test_class_num_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import rank_range_filter_tool
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            try:
                data = rank_range_filter_tool(exam_id=eid, metric="subject:数学", class_num=1)
                result = {"raised": False}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"]

    def test_total_metric_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import rank_range_filter_tool
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            try:
                data = rank_range_filter_tool(exam_id=eid, metric="total:主三门")
                result = {"raised": False}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"]


class TestRankFrequencyStatSingleSubject:
    """rank_frequency_stat 委托 phase4 单学科逻辑，class_num 被拒绝。"""

    def test_class_num_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import rank_frequency_stat_tool
            try:
                data = rank_frequency_stat_tool(grade=2, metric="subject:数学", class_num=1)
                result = {"raised": False}
            except (ValueError, TypeError) as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"]


# ════════════════════════════════════════════════════════════════
#  越权 / 跨年级 / 跨学科拒绝
# ════════════════════════════════════════════════════════════════

class TestCrossScopeRejection:
    """显式 teaching_class_id 越权/跨学科/跨年级 → 拒绝。"""

    def test_cross_subject_class_rejected(self, tmp_path):
        """数学教师用物理班 teaching_class_id → 拒绝。"""
        assert_code = _math_a_class_id() + textwrap.dedent("""\
            from app.chat.tools import band_trend
            from app.teaching.subject import SubjectConflictError
            try:
                data = band_trend(grade=2, teaching_class_id=phy_id)
                result = {"raised": False}
            except SubjectConflictError as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"物理班应被拒绝: {data}"

    def test_cross_grade_class_rejected(self, tmp_path):
        """grade=2 但用高三班 teaching_class_id → 拒绝。"""
        assert_code = _math_a_class_id() + textwrap.dedent("""\
            from app.chat.tools import band_trend
            try:
                data = band_trend(grade=2, teaching_class_id=g3_id)
                result = {"raised": False}
            except ValueError as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"跨年级班应被拒绝: {data}"


# ════════════════════════════════════════════════════════════════
#  重叠成员去重
# ════════════════════════════════════════════════════════════════

class TestOverlappingMemberDedup:
    """重叠成员（同属 A/B）在全部模式下不重复计数。"""

    def test_union_dedup(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            for label, sids in [("A班", ["s1","s2","s3"]), ("B班", ["s3","s4","s5"])]:
                tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
                db.add(tc); db.flush()
                for sid in sids:
                    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="e1", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam); db.flush()
            for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
                db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
                    raw_score=90-i*5, name=f"S{i}", class_num=1))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_lookup
            results = student_lookup()
            sids = sorted({r["student_id"] for r in results})
            print(json.dumps({"sids": sids}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        # 去重后 s3 只出现一次，总成员 s1,s2,s3,s4,s5 = 5
        assert data["sids"] == ["s1", "s2", "s3", "s4", "s5"], f"去重应=5: {data}"


# ════════════════════════════════════════════════════════════════
#  选考 grade_score basis（物理教师高二）
# ════════════════════════════════════════════════════════════════

class TestElectiveGradeScoreBasis:
    """高二/高三选考学科用 grade_score 作为 score_basis。"""

    def test_physics_teacher_grade_score_basis(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="物理", name="物理老师"); db.add(t); db.flush()
            tc = TeachingClass(grade=2, label="物A1", subject="物理", kind="教学")
            db.add(tc); db.flush()
            for sid in ["s1","s2","s3"]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
            db.add(exam); db.flush()
            db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
                raw_score=95, grade_score=70, grade_percentile=0.05, name="A", class_num=1))
            db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="物理",
                raw_score=85, grade_score=67, grade_percentile=0.15, name="B", class_num=1))
            db.add(SubjectScore(exam_id=exam.id, student_id="s3", subject="物理",
                raw_score=75, grade_score=64, grade_percentile=0.25, name="C", class_num=1))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_exam_detail
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam.id
            _db.close()
            data = student_exam_detail(student_id="s1", exam_id=eid)
            result = {
                "teaching_subject": data.get("teaching_subject"),
                "score_basis": data.get("score_basis"),
            }
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["teaching_subject"] == "物理"
        assert data["score_basis"] == "grade_score", \
            f"高二物理应 grade_score: {data}"


# ════════════════════════════════════════════════════════════════
#  同分 competition ranking
# ════════════════════════════════════════════════════════════════

class TestCompetitionRanking:
    """同分同名次（competition ranking）。"""

    def test_tie_same_rank(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            db.add(tc); db.flush()
            for sid in ["s1","s2","s3","s4"]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="e1", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
            db.add(exam); db.flush()
            db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学", raw_score=90, grade_percentile=0.1, name="A"))
            db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="数学", raw_score=90, grade_percentile=0.1, name="B"))
            db.add(SubjectScore(exam_id=exam.id, student_id="s3", subject="数学", raw_score=80, grade_percentile=0.3, name="C"))
            db.add(SubjectScore(exam_id=exam.id, student_id="s4", subject="数学", raw_score=70, grade_percentile=0.5, name="D"))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import rank_range_filter_tool
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam = _db.query(Exam).filter(Exam.name == "e1").first()
            eid = exam.id
            _db.close()
            data = rank_range_filter_tool(exam_id=eid, metric="subject:数学", rank_min=1, rank_max=9999)
            ranks = {row["student_id"]: row.get("subject_rank") for row in data.get("rows", [])}
            print(json.dumps({"ranks": ranks}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        ranks = data["ranks"]
        assert ranks.get("s1") == ranks.get("s2"), f"同分应同名次: {ranks}"


# ════════════════════════════════════════════════════════════════
#  默认分班排名（不合并池）
# ════════════════════════════════════════════════════════════════

class TestDefaultPerClassRanking:
    """全部模式按班分别排名，不合并成一个池。"""

    def test_per_class_rank1(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            for label, sids in [("A班", ["x","a1"]), ("B班", ["x","b1"])]:
                tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
                db.add(tc); db.flush()
                for sid in sids:
                    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
            db.add(exam); db.flush()
            db.add(SubjectScore(exam_id=exam.id, student_id="x", subject="数学", raw_score=90, grade_percentile=0.05, name="X"))
            db.add(SubjectScore(exam_id=exam.id, student_id="a1", subject="数学", raw_score=60, grade_percentile=0.5, name="A1"))
            db.add(SubjectScore(exam_id=exam.id, student_id="b1", subject="数学", raw_score=50, grade_percentile=0.6, name="B1"))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import rank_range_filter_tool
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam.id
            _db.close()
            data = rank_range_filter_tool(exam_id=eid, metric="subject:数学", rank_min=1, rank_max=9999)
            ranks = {row["student_id"]: row.get("subject_rank") for row in data.get("rows", [])}
            print(json.dumps({"ranks": ranks}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        ranks = data["ranks"]
        assert ranks.get("b1") == 1, f"b1 在 B班应独立 rank1（不合并池）: {ranks}"


# ════════════════════════════════════════════════════════════════
#  homework_grade_correlation 不绕过 scope
# ════════════════════════════════════════════════════════════════

class TestHomeworkCorrelationScoped:
    """homework_grade_correlation 调用 phase5 单学科服务时不绕过 scope。"""

    def test_cross_subject_class_rejected(self, tmp_path):
        """数学教师用物理班 teaching_class_id 调 correlation → 拒绝。"""
        assert_code = _math_a_class_id() + textwrap.dedent("""\
            from app.chat.tools import homework_grade_correlation
            from app.teaching.subject import SubjectConflictError
            try:
                data = homework_grade_correlation(teaching_class_id=phy_id)
                result = {"raised": False}
            except SubjectConflictError as e:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_MATH_TEACHER, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"物理班应被拒绝: {data}"


# ════════════════════════════════════════════════════════════════
#  TOOLS schema 静态校验
# ════════════════════════════════════════════════════════════════

class TestToolSchemaNoCrossPath:
    """TOOLS schema 移除 total_type/metric=总分/subject 自由选择/class_num 跨口径输入。"""

    def test_no_total_type_in_schema(self):
        from app.chat.tools import TOOLS
        for tool in TOOLS:
            props = tool.get("input_schema", {}).get("properties", {})
            # student_trend / student_learning_profile 不应有 total_type
            if tool["name"] in ("student_trend",):
                assert "total_type" not in props, \
                    f"{tool['name']} 不应含 total_type"
            # subject_progress_ranking / multi_exam_progress_ranking 不应有 subject/metrics
            if tool["name"] == "subject_progress_ranking":
                assert "subject" not in props, \
                    f"{tool['name']} 不应含 subject 自由选择"
            if tool["name"] == "multi_exam_progress_ranking":
                assert "metrics" not in props, \
                    f"{tool['name']} 不应含 metrics 自由选择"

    def test_no_class_num_in_grade_tools(self):
        """成绩类工具 schema 不应含 class_num（homework 工具除外）。"""
        from app.chat.tools import TOOLS
        grade_tools = {
            "list_exams", "list_my_classes", "student_lookup",
            "student_exam_detail", "student_trend", "student_learning_profile",
            "class_trend", "compare_classes", "focus_list", "subject_weakness",
            "subject_progress_ranking", "multi_exam_progress_ranking",
            "band_trend", "custom_rank_band_trend",
            "rank_range_filter", "rank_frequency_stat",
        }
        for tool in TOOLS:
            if tool["name"] not in grade_tools:
                continue
            props = tool.get("input_schema", {}).get("properties", {})
            assert "class_num" not in props, \
                f"{tool['name']} 不应含 class_num"
            assert "class_label" not in props, \
                f"{tool['name']} 不应含 class_label"

    def test_no_total_type_in_tool_functions(self):
        """TOOL_FUNCTIONS 注册的 grade 工具不含 total_type 入口。"""
        from app.chat.tools import TOOL_FUNCTIONS
        # 确认成绩工具已注册
        for name in ["list_exams", "student_exam_detail", "student_trend",
                      "class_trend", "focus_list", "band_trend"]:
            assert name in TOOL_FUNCTIONS, f"{name} 应在 TOOL_FUNCTIONS"

    def test_homework_notes_preserved(self):
        """homework/notes 工具保留在 TOOL_FUNCTIONS。"""
        from app.chat.tools import TOOL_FUNCTIONS
        for name in ["student_homework_summary", "class_homework_ranking",
                      "homework_grade_correlation", "student_notes"]:
            assert name in TOOL_FUNCTIONS, f"{name} 应保留"


# ════════════════════════════════════════════════════════════════
#  静态跨学科泄漏扫描（source guard）
# ════════════════════════════════════════════════════════════════

class TestSourceGuardNoLeak:
    """tools.py 成绩工具不得 import/query TotalScore 或读 ClassAverage.total_averages。"""

    def _grade_tool_names(self):
        return {
            "list_exams", "student_lookup", "student_exam_detail",
            "student_trend", "student_learning_profile",
            "class_trend", "compare_classes", "focus_list", "subject_weakness",
            "subject_progress_ranking", "multi_exam_progress_ranking",
            "band_trend", "custom_rank_band_trend",
        }

    def test_no_total_score_import_or_query(self):
        """tools.py 不得 import TotalScore 或在其函数体查询它（docstring 注释除外）。"""
        import ast
        tools_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "chat", "tools.py",
        )
        with open(tools_path) as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in self._grade_tool_names():
                func_source = ast.get_source_segment(source, node) or ""
                # 剥离 docstring 后检查实际代码
                body = list(node.body)
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                    body = body[1:]
                code_only = "\n".join(ast.get_source_segment(source, stmt) or "" for stmt in body)
                assert "TotalScore" not in code_only, \
                    f"成绩工具 {node.name} 代码不得引用 TotalScore"
                assert "total_averages" not in code_only, \
                    f"成绩工具 {node.name} 代码不得读 ClassAverage.total_averages"

    def test_no_all_subjects_matrix_in_grade_tools(self):
        """成绩工具不得构建 ALL_SUBJECTS 多学科矩阵。"""
        import ast
        tools_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "chat", "tools.py",
        )
        with open(tools_path) as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in self._grade_tool_names():
                func_source = ast.get_source_segment(source, node) or ""
                # ALL_SUBJECTS 矩阵遍历是禁止的
                assert "ALL_SUBJECTS" not in func_source, \
                    f"成绩工具 {node.name} 不得遍历 ALL_SUBJECTS"
