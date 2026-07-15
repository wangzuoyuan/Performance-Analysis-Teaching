"""阶段6 最终集成：chat/tools.py 单学科范围硬化（严格 TDD）。

合并默认助手审查发现的 6A 范围 Blocker：
- 数学教师有遗留物理班 s6，给 s6 数学诱饵分后 student_lookup(s6) 不应泄露。
- list_my_classes 只列当前任教学科班。
- student_lookup / student_exam_detail / student_trend / student_learning_profile /
  student_homework_summary / class_homework_ranking / student_notes 需接受
  teaching_class_id 并做合法 scope 校验。
- 具体班 A 不能查 B；全部模式仅当前学科班并集；作业/档案可含当前学科合法 anon，
  不能含他科班。
- class_homework_ranking 移除 class_num，调用 service.rankings(teaching_class_id=...)。
- 移除未使用的 _resolve_tc_id / class_label 旁路。

所有测试在全新临时数据目录下用子进程执行，不依赖共享库。
先 RED 后 GREEN，无 skip/autouse/宽泛异常。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest


# ════════════════════════════════════════════════════════════════
#  隔离子进程测试基础设施（与 test_chat_tools_single_subject 同构）
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
    lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"无法从子进程输出解析 JSON\n{proc.stdout}")


# ════════════════════════════════════════════════════════════════
#  测试数据：数学教师 + A/B 班 + 遗留物理班（s6 有数学诱饵分）+ 作业/档案
# ════════════════════════════════════════════════════════════════

_SETUP_FULL = textwrap.dedent("""\
    from app.db.models import SessionLocal
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord, HomeworkSemester, StudentNote,
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
    db.commit()

    # 考试1 期中 (grade2): 数学 + s6 也有数学诱饵分
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11-15")
    db.add(exam1); db.flush()
    for i, sid in enumerate(["s1","s2","s3","s4","s5"], 1):
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=90-i*5, grade_percentile=0.9-i*0.1,
            name=f"学生{i}", class_num=1))
    # s6 数学诱饵分（物理班成员但有数学分 — 不得泄露）
    db.add(SubjectScore(exam_id=exam1.id, student_id="s6", subject="数学",
        raw_score=88, grade_percentile=0.2, name="物理生6", class_num=2))
    db.commit()

    # 作业花名册：当前学科成员 + 物理班成员（诱饵）
    for sid, name in [("s1","学生1"),("s2","学生2"),("s3","学生3"),
                       ("s4","学生4"),("s5","学生5"),("s6","物理生6")]:
        db.add(ClassRoster(student_id=sid, name=name, class_num=1, excluded=0))
    db.commit()

    # 作业记录：s1 缺交多，s6(物理班) 也缺交
    sem = HomeworkSemester(name="2025春", start_date="2025-02-17", end_date="2025-07-04", is_current=1)
    db.add(sem); db.flush()
    for day in ["2025-03-01","2025-03-02","2025-03-03"]:
        db.add(HomeworkRecord(student_id="s1", date=day, subject="校本",
            submission_status="缺交", content=""))
        db.add(HomeworkRecord(student_id="s6", date=day, subject="校本",
            submission_status="缺交", content=""))
    db.commit()

    # 档案：s1 有谈话记录，s6(物理班) 也有
    db.add(StudentNote(student_id="s1", date="2025-03-10",
        category="谈话", content="s1谈话记录"))
    db.add(StudentNote(student_id="s6", date="2025-03-10",
        category="谈话", content="s6物理班档案"))
    db.commit()
    db.close()
""")


def _class_ids() -> str:
    return textwrap.dedent("""\
        from app.db.models import SessionLocal, TeachingClass
        _db = SessionLocal()
        _a = _db.query(TeachingClass).filter(TeachingClass.label == "A班", TeachingClass.subject == "数学").first()
        a_id = _a.id
        _b = _db.query(TeachingClass).filter(TeachingClass.label == "B班", TeachingClass.subject == "数学").first()
        b_id = _b.id
        _phy = _db.query(TeachingClass).filter(TeachingClass.subject == "物理").first()
        phy_id = _phy.id
        _db.close()
    """)


# ════════════════════════════════════════════════════════════════
#  student_lookup 不泄露他科班学生（6A Blocker 核心）
# ════════════════════════════════════════════════════════════════

class TestStudentLookupNoLeak:
    """数学教师有遗留物理班 s6，s6 有数学诱饵分 → student_lookup 不得返回 s6。"""

    def test_s6_not_in_lookup(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_lookup
            all_results = student_lookup()
            sids = {r["student_id"] for r in all_results}
            print(json.dumps({"sids": sorted(sids)}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert "s6" not in data["sids"], f"物理班 s6 不应泄露: {data}"
        assert "s7" not in data["sids"], f"物理班 s7 不应泄露: {data}"

    def test_lookup_by_name_scoped(self, tmp_path):
        """按姓名搜"物理生6" → 不应命中（属于物理班）。"""
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_lookup
            results = student_lookup(name="物理生6")
            sids = {r["student_id"] for r in results}
            print(json.dumps({"sids": sorted(sids)}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert "s6" not in data["sids"], f"按名搜物理生不应泄露 s6: {data}"


# ════════════════════════════════════════════════════════════════
#  list_my_classes 只列当前学科班
# ════════════════════════════════════════════════════════════════

class TestListMyClassesCurrentSubjectOnly:
    """list_my_classes 只返回当前任教学科班，不含遗留他科班。"""

    def test_excludes_other_subject(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import list_my_classes
            classes = list_my_classes()
            labels = [c["label"] for c in classes]
            subjects = {c["subject"] for c in classes}
            print(json.dumps({"labels": labels, "subjects": sorted(subjects)}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert "物C班" not in data["labels"], f"不应含物理班: {data}"
        assert data["subjects"] == ["数学"], f"应只有数学: {data}"


# ════════════════════════════════════════════════════════════════
#  student_exam_detail / student_trend / student_learning_profile 拒绝越权
# ════════════════════════════════════════════════════════════════

class TestGradeToolsRejectOutOfScopeStudent:
    """s6 是物理班成员（有数学诱饵分），成绩类工具不得返回其数据。"""

    def test_exam_detail_rejects_s6(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_exam_detail
            from app.db.models import SessionLocal, Exam
            _db = SessionLocal()
            exam1 = _db.query(Exam).filter(Exam.name == "期中").first()
            eid = exam1.id
            _db.close()
            try:
                data = student_exam_detail(student_id="s6", exam_id=eid)
                result = {"raised": False, "has_score": data.get("subject_score") is not None}
            except ValueError as exc:
                result = {"raised": True, "has_score": False, "msg": str(exc)}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["raised"] or not data["has_score"], f"s6 应被拒绝: {data}"

    def test_trend_rejects_s6(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_trend
            try:
                data = student_trend(student_id="s6")
                result = {"raised": False, "series_len": len(data.get("series", []))}
            except ValueError as exc:
                result = {"raised": True, "series_len": 0, "msg": str(exc)}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["raised"] or data["series_len"] == 0, f"s6 趋势应空/拒绝: {data}"

    def test_profile_rejects_s6(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_learning_profile
            data = student_learning_profile(student_id="s6")
            has_error = bool(data.get("error"))
            print(json.dumps({"has_error": has_error, "series_len": len(data.get("series", []))}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["has_error"] or data["series_len"] == 0, f"s6 画像应空/拒绝: {data}"


# ════════════════════════════════════════════════════════════════
#  student_homework_summary 拒绝他科班学生
# ════════════════════════════════════════════════════════════════

class TestHomeworkSummaryScoped:
    """s6 是物理班成员，作业概况不得返回其数据。"""

    def test_rejects_s6(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_homework_summary
            data = student_homework_summary(student_id="s6")
            has_error = bool(data.get("error"))
            has_misses = "total_misses" in data
            print(json.dumps({"has_error": has_error, "has_misses": has_misses}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["has_error"] or not data["has_misses"], f"s6 作业不应返回: {data}"


# ════════════════════════════════════════════════════════════════
#  class_homework_ranking 移除 class_num、按 teaching_class_id 过滤
# ════════════════════════════════════════════════════════════════

class TestClassHomeworkRankingScope:
    """class_homework_ranking 不接受 class_num，按 teaching_class_id 限定范围。"""

    def test_class_num_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import class_homework_ranking
            try:
                data = class_homework_ranking(class_num=1)
                result = {"raised": False}
            except (ValueError, TypeError):
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"class_num 应被拒绝: {data}"

    def test_scoped_to_a_excludes_s6(self, tmp_path):
        """指定 A班 teaching_class_id 时，缺交排行不含物理班 s6。"""
        assert_code = _class_ids() + textwrap.dedent("""\
            from app.chat.tools import class_homework_ranking
            data = class_homework_ranking(teaching_class_id=a_id)
            names = [r["name"] for r in data.get("rankings", [])]
            has_s6 = "物理生6" in names
            print(json.dumps({"names": names, "has_s6": has_s6}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert not data["has_s6"], f"A班排行不应含物理班 s6: {data}"

    def test_all_scope_excludes_other_subject(self, tmp_path):
        """不指定班（全部当前学科）时，排行也不含物理班 s6。"""
        assert_code = textwrap.dedent("""\
            from app.chat.tools import class_homework_ranking
            data = class_homework_ranking()
            names = [r["name"] for r in data.get("rankings", [])]
            has_s6 = "物理生6" in names
            print(json.dumps({"names": names, "has_s6": has_s6}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert not data["has_s6"], f"全部模式不应含物理班 s6: {data}"

    def test_cross_subject_class_rejected(self, tmp_path):
        """数学教师用物理班 teaching_class_id → 拒绝。"""
        assert_code = _class_ids() + textwrap.dedent("""\
            from app.chat.tools import class_homework_ranking
            from app.teaching.subject import SubjectConflictError
            try:
                data = class_homework_ranking(teaching_class_id=phy_id)
                result = {"raised": False}
            except (ValueError, SubjectConflictError) as exc:
                result = {"raised": True, "msg": str(exc)}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["raised"], f"物理班应被拒绝: {data}"


# ════════════════════════════════════════════════════════════════
#  student_notes 拒绝他科班学生
# ════════════════════════════════════════════════════════════════

class TestStudentNotesScoped:
    """s6 是物理班成员，档案工具不得返回其记录。"""

    def test_rejects_s6(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_notes
            data = student_notes(student_id="s6")
            has_error = bool(data.get("error"))
            notes_content = " ".join(n.get("content","") for n in data.get("notes", []))
            leaked = "s6物理班档案" in notes_content
            print(json.dumps({"has_error": has_error, "leaked": leaked}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["has_error"] or not data["leaked"], f"s6 档案不应泄露: {data}"

    def test_s1_returns_notes(self, tmp_path):
        """s1 是合法数学班成员，应返回其档案。"""
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_notes
            data = student_notes(student_id="s1")
            notes_content = " ".join(n.get("content","") for n in data.get("notes", []))
            print(json.dumps({"has_s1_note": "s1谈话记录" in notes_content}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["has_s1_note"], f"s1 档案应返回: {data}"


# ════════════════════════════════════════════════════════════════
#  A/B 同名 + 具体班不能查他班
# ════════════════════════════════════════════════════════════════

class TestSameNameDisambiguation:
    """A班和 B班各有一个同名学生"小明"，具体班查询只返回本班成员。"""

    def test_class_scoped_lookup(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            for label, sids in [("A班", ["xa","a1"]), ("B班", ["xb","b1"])]:
                tc = TeachingClass(grade=2, label=label, subject="数学", kind="教学")
                db.add(tc); db.flush()
                for sid in sids:
                    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
            db.commit()
            exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
            db.add(exam); db.flush()
            # 两个"小明"分别属 A/B
            db.add(SubjectScore(exam_id=exam.id, student_id="xa", subject="数学", raw_score=90, name="小明", class_num=1))
            db.add(SubjectScore(exam_id=exam.id, student_id="xb", subject="数学", raw_score=50, name="小明", class_num=2))
            db.add(SubjectScore(exam_id=exam.id, student_id="a1", subject="数学", raw_score=80, name="甲", class_num=1))
            db.add(SubjectScore(exam_id=exam.id, student_id="b1", subject="数学", raw_score=70, name="乙", class_num=2))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            from app.chat.tools import student_lookup
            _db = SessionLocal()
            a = _db.query(TeachingClass).filter(TeachingClass.label=="A班", TeachingClass.subject=="数学").first()
            a_id = a.id
            _db.close()
            # 指定 A班查"小明" → 只应返回 xa
            results = student_lookup(name="小明", teaching_class_id=a_id)
            sids = sorted(r["student_id"] for r in results)
            print(json.dumps({"sids": sids}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["sids"] == ["xa"], f"A班查小明应只返回 xa: {data}"


# ════════════════════════════════════════════════════════════════
#  anon 占位成员保护：当前学科合法 anon 可见，他科 anon 不可见
# ════════════════════════════════════════════════════════════════

class TestAnonGuard:
    """_anon: 仅姓名占位成员只在当前学科范围内可见（作业场景），他科 anon 不泄露。"""

    def test_other_subject_anon_excluded(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc_m = TeachingClass(grade=2, label="数A", subject="数学", kind="教学")
            db.add(tc_m); db.flush()
            db.add(TeachingClassMember(teaching_class_id=tc_m.id, student_id="_anon:m1", source="manual"))
            tc_p = TeachingClass(grade=2, label="物B", subject="物理", kind="教学")
            db.add(tc_p); db.flush()
            db.add(TeachingClassMember(teaching_class_id=tc_p.id, student_id="_anon:p1", source="manual"))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import list_my_classes
            classes = list_my_classes()
            # 数学教师只应看到数A班，物B班不含
            labels = [c["label"] for c in classes]
            print(json.dumps({"labels": labels}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert "物B" not in data["labels"], f"物理班不应出现: {data}"
        assert "数A" in data["labels"]


# ════════════════════════════════════════════════════════════════
#  schema 签名检查：关键工具含 teaching_class_id，class_homework_ranking 无 class_num
# ════════════════════════════════════════════════════════════════

class TestSchemaSignatures:
    """TOOLS schema 签名一致性。"""

    def test_student_lookup_has_teaching_class_id(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "student_lookup")
        props = tool["input_schema"].get("properties", {})
        assert "teaching_class_id" in props, "student_lookup 应含 teaching_class_id"

    def test_class_homework_ranking_no_class_num(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "class_homework_ranking")
        props = tool["input_schema"].get("properties", {})
        assert "class_num" not in props, "class_homework_ranking 不应含 class_num"
        assert "teaching_class_id" in props, "class_homework_ranking 应含 teaching_class_id"

    def test_homework_summary_has_teaching_class_id(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "student_homework_summary")
        props = tool["input_schema"].get("properties", {})
        assert "teaching_class_id" in props, "student_homework_summary 应含 teaching_class_id"

    def test_student_notes_has_teaching_class_id(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "student_notes")
        props = tool["input_schema"].get("properties", {})
        assert "teaching_class_id" in props, "student_notes 应含 teaching_class_id"


# ════════════════════════════════════════════════════════════════
#  死代码移除：_resolve_tc_id / _resolve_class_scope_by_grade 不再存在
# ════════════════════════════════════════════════════════════════

class TestDeadCodeRemoved:
    """未使用的旁路辅助函数应已移除。"""

    def test_no_resolve_tc_id(self):
        import app.chat.tools as tools
        assert not hasattr(tools, "_resolve_tc_id"), "_resolve_tc_id 应已移除"

    def test_no_resolve_class_scope_by_grade(self):
        import app.chat.tools as tools
        assert not hasattr(tools, "_resolve_class_scope_by_grade"), \
            "_resolve_class_scope_by_grade 应已移除"

    def test_no_year_range_in_list_exams(self):
        """list_exams 的 year_range 若保留必须生效，否则应移除。这里验证已移除。"""
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "list_exams")
        props = tool["input_schema"].get("properties", {})
        assert "year_range" not in props, "year_range 应已移除（未使用）"


# ════════════════════════════════════════════════════════════════
#  阶段6最终返工：4 个成绩工具含 teaching_class_id + _SCOPE_TOOLS
# ════════════════════════════════════════════════════════════════

class TestFourGradeToolsTeachingClassId:
    """list_exams / student_exam_detail / student_trend / student_learning_profile
    必须支持 teaching_class_id 参数和 schema，并进入 _SCOPE_TOOLS。"""

    def test_list_exams_schema_has_teaching_class_id(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "list_exams")
        props = tool["input_schema"].get("properties", {})
        assert "teaching_class_id" in props, "list_exams 应含 teaching_class_id"

    def test_student_exam_detail_schema_has_teaching_class_id(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "student_exam_detail")
        props = tool["input_schema"].get("properties", {})
        assert "teaching_class_id" in props, "student_exam_detail 应含 teaching_class_id"

    def test_student_trend_schema_has_teaching_class_id(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "student_trend")
        props = tool["input_schema"].get("properties", {})
        assert "teaching_class_id" in props, "student_trend 应含 teaching_class_id"

    def test_student_learning_profile_schema_has_teaching_class_id(self):
        from app.chat.tools import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "student_learning_profile")
        props = tool["input_schema"].get("properties", {})
        assert "teaching_class_id" in props, "student_learning_profile 应含 teaching_class_id"

    def test_four_tools_in_scope_tools(self):
        """这 4 个工具必须在 _SCOPE_TOOLS 中，否则 session 不会注入页面 scope。"""
        from app.chat.session import _SCOPE_TOOLS
        for name in ("list_exams", "student_exam_detail", "student_trend", "student_learning_profile"):
            assert name in _SCOPE_TOOLS, f"{name} 应在 _SCOPE_TOOLS 中"

    def test_list_exams_function_accepts_teaching_class_id(self):
        import inspect
        from app.chat.tools import list_exams
        sig = inspect.signature(list_exams)
        assert "teaching_class_id" in sig.parameters

    def test_student_exam_detail_function_accepts_teaching_class_id(self):
        import inspect
        from app.chat.tools import student_exam_detail
        sig = inspect.signature(student_exam_detail)
        assert "teaching_class_id" in sig.parameters

    def test_student_trend_function_accepts_teaching_class_id(self):
        import inspect
        from app.chat.tools import student_trend
        sig = inspect.signature(student_trend)
        assert "teaching_class_id" in sig.parameters

    def test_student_learning_profile_function_accepts_teaching_class_id(self):
        import inspect
        from app.chat.tools import student_learning_profile
        sig = inspect.signature(student_learning_profile)
        assert "teaching_class_id" in sig.parameters


# ════════════════════════════════════════════════════════════════
#  list_exams 具体班 scope：A 班不能列 B 班独有考试
# ════════════════════════════════════════════════════════════════

class TestListExamsClassScoped:
    """list_exams(teaching_class_id=A) 只返回 A 班成员有真实分数的考试，
    B 班独有考试（A 班成员无分）不应出现。"""

    def test_class_scoped_excludes_other_class_exam(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc_a = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            tc_b = TeachingClass(grade=2, label="B班", subject="数学", kind="教学")
            db.add(tc_a); db.add(tc_b); db.flush()
            for sid in ["a1", "a2"]:
                db.add(TeachingClassMember(teaching_class_id=tc_a.id, student_id=sid, source="manual"))
            for sid in ["b1", "b2"]:
                db.add(TeachingClassMember(teaching_class_id=tc_b.id, student_id=sid, source="manual"))
            db.commit()
            # exam_common: A 和 B 都有分
            ex1 = Exam(name="共同考", grade=2, semester="上", exam_type="月考", exam_date="2025-10-01")
            db.add(ex1); db.flush()
            for sid in ["a1","a2","b1","b2"]:
                db.add(SubjectScore(exam_id=ex1.id, student_id=sid, subject="数学",
                    raw_score=80, name=sid, class_num=1))
            # exam_b_only: 只有 B 班有分
            ex2 = Exam(name="B班独有", grade=2, semester="上", exam_type="月考", exam_date="2025-11-01")
            db.add(ex2); db.flush()
            for sid in ["b1","b2"]:
                db.add(SubjectScore(exam_id=ex2.id, student_id=sid, subject="数学",
                    raw_score=70, name=sid, class_num=2))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            from app.chat.tools import list_exams
            _db = SessionLocal()
            a = _db.query(TeachingClass).filter(TeachingClass.label=="A班", TeachingClass.subject=="数学").first()
            a_id = a.id
            _db.close()
            exams = list_exams(teaching_class_id=a_id)
            names = [e["name"] for e in exams]
            print(json.dumps({"names": names}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert "B班独有" not in data["names"], f"A班 scope 不应含 B班独有考试: {data}"
        assert "共同考" in data["names"], f"A班 scope 应含共同考: {data}"


# ════════════════════════════════════════════════════════════════
#  build_system_prompt / _inject_page_scope bool & 负数 tid 拒绝
# ════════════════════════════════════════════════════════════════

class TestBoolNegativeTcIdRejected:
    """bool teaching_class_id（True/False 是 int 子类）和负数必须被拒绝。"""

    def test_build_prompt_rejects_bool_tc_id(self):
        """build_system_prompt 中 type(True) is int == False，不得进入 prompt。"""
        from app.chat.session import build_system_prompt
        prompt = build_system_prompt({"scope_mode": "teaching_class", "teaching_class_id": True})
        ctx_part = prompt.split("上下文")[-1] if "上下文" in prompt else ""
        # bool True 不应作为 teaching_class_id 出现在 JSON 中
        assert '"teaching_class_id": true' not in ctx_part, \
            f"bool teaching_class_id 不应进入 prompt: {ctx_part}"

    def test_build_prompt_rejects_false_tc_id(self):
        from app.chat.session import build_system_prompt
        prompt = build_system_prompt({"scope_mode": "teaching_class", "teaching_class_id": False})
        ctx_part = prompt.split("上下文")[-1] if "上下文" in prompt else ""
        assert '"teaching_class_id": false' not in ctx_part

    def test_build_prompt_rejects_negative_tc_id(self):
        from app.chat.session import build_system_prompt
        prompt = build_system_prompt({"scope_mode": "teaching_class", "teaching_class_id": -5})
        ctx_part = prompt.split("上下文")[-1] if "上下文" in prompt else ""
        assert "-5" not in ctx_part, f"负数 teaching_class_id 不应进入 prompt: {ctx_part}"

    def test_inject_page_scope_rejects_bool_tc_id(self):
        """_inject_page_scope 不应把 True 当作有效 teaching_class_id。"""
        from app.chat.session import _inject_page_scope
        result = _inject_page_scope({"scope_mode": "teaching_class", "teaching_class_id": True})
        # bool True 不应通过 type(x) is int 校验
        assert result is None or result.get("teaching_class_id") is not True, \
            f"bool tc_id 不应被注入: {result}"

    def test_inject_page_scope_rejects_negative_tc_id(self):
        from app.chat.session import _inject_page_scope
        result = _inject_page_scope({"scope_mode": "teaching_class", "teaching_class_id": -1})
        assert result is None, f"负数 tc_id 应被丢弃: {result}"


# ════════════════════════════════════════════════════════════════
#  student_homework_summary / student_learning_profile 按 name 唯一他科诱饵
# ════════════════════════════════════════════════════════════════

class TestByNameResolutionScoped:
    """按 name 查询时，他科班同名学生不得作为候选返回。"""

    def test_homework_summary_name_excludes_other_subject(self, tmp_path):
        """数学教师按 name 查"物理生6"（s6 在物理班），不应返回其作业。"""
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_homework_summary
            data = student_homework_summary(name="物理生6")
            has_error = bool(data.get("error"))
            candidates = data.get("candidates", [])
            sids = [c.get("student_id") for c in candidates]
            leaked = "s6" in sids
            print(json.dumps({"has_error": has_error, "leaked": leaked}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["has_error"] or not data["leaked"], \
            f"按名查物理生6 不应泄露 s6: {data}"

    def test_learning_profile_name_excludes_other_subject(self, tmp_path):
        """数学教师按 name 查"物理生6"（s6 在物理班），不应返回其画像。"""
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_learning_profile
            data = student_learning_profile(name="物理生6")
            has_error = bool(data.get("error"))
            candidates = data.get("candidates", [])
            sids = [c.get("student_id") for c in candidates]
            leaked = "s6" in sids
            series_len = len(data.get("series", []))
            print(json.dumps({"has_error": has_error, "leaked": leaked, "series_len": series_len}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_FULL, assert_code)
        data = _parse_result(proc)
        assert data["has_error"] or not data["leaked"], \
            f"按名查物理生6 画像不应泄露 s6: {data}"


# ════════════════════════════════════════════════════════════════
#  student_exam_detail 具体班 rank pool：A 班学生用 A 班 rank pool
# ════════════════════════════════════════════════════════════════

class TestExamDetailClassScopedRank:
    """student_exam_detail(teaching_class_id=A) 对重叠学生应返回 A 班的 rank 和 label。"""

    def test_overlapping_student_gets_explicit_class_label(self, tmp_path):
        """学生 x 同属 A/B 班，指定 teaching_class_id=B 时应返回 B 的 label。"""
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc_a = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            tc_b = TeachingClass(grade=2, label="B班", subject="数学", kind="教学")
            db.add(tc_a); db.add(tc_b); db.flush()
            # x 同属 A 和 B（重叠学生）
            for tc in [tc_a, tc_b]:
                db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="x", source="manual"))
            db.add(TeachingClassMember(teaching_class_id=tc_a.id, student_id="a1", source="manual"))
            db.add(TeachingClassMember(teaching_class_id=tc_b.id, student_id="b1", source="manual"))
            db.commit()
            ex = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11-15")
            db.add(ex); db.flush()
            for sid, score in [("x",85),("a1",90),("b1",70)]:
                db.add(SubjectScore(exam_id=ex.id, student_id=sid, subject="数学",
                    raw_score=score, name=sid, class_num=1))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass, Exam
            from app.chat.tools import student_exam_detail
            _db = SessionLocal()
            b = _db.query(TeachingClass).filter(TeachingClass.label=="B班", TeachingClass.subject=="数学").first()
            b_id = b.id
            exam = _db.query(Exam).filter(Exam.name=="期中").first()
            eid = exam.id
            _db.close()
            data = student_exam_detail(student_id="x", exam_id=eid, teaching_class_id=b_id)
            print(json.dumps({"class_label": data.get("class_label"), "tc_id": data.get("teaching_class_id")}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        data = _parse_result(proc)
        assert data["class_label"] == "B班", \
            f"指定 B班 tid 时重叠学生 x 应返回 B班 label: {data}"
