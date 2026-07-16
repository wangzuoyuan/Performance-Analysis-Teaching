"""阶段6第三轮独立审查修复（TDD RED→GREEN）。

覆盖审查发现的 10 个 Blocker，全部用全新临时数据目录 + 子进程隔离执行，
不依赖共享库状态。禁止 skip / autouse / 宽泛 except / pytest.raises(Exception) /
deselect。

Blocker 分组：
  1-3  合法 anon / 无分成员被排除（include_anon、画像无分成员返回、anon 真实数据）
  4-5  identity 跨学段（student_ids_of_person 读历史；不串人、不丢数据）
  6-9  参数与显式测试硬校验（int>0、grade enum、exam_id 正整数、exam_ids 属当前 scope、
       scope 字段一致）
  10   prompt 安全（_safe_page / _safe_student_id 拒绝控制字符与 query/hash 注入）
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
    import json, os, sys
    setup_script = sys.argv[1]
    assert_script = sys.argv[2]
    ns = {"json": json}
    with open(setup_script) as f:
        exec(f.read(), ns)
    with open(assert_script) as f:
        exec(f.read(), ns)
    sys.stdout.flush()
    os._exit(0)
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
#  共享数据：数学教师 + A班（含合法 anon 无分成员）+ 遗留物理班
# ════════════════════════════════════════════════════════════════

_SETUP_ANON = textwrap.dedent("""\
    from app.db.models import SessionLocal
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord, HomeworkSemester, StudentNote,
    )
    t = Teacher(subject="数学", name="数学老师")
    db.add(t); db.flush()
    tc_a = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
    db.add(tc_a); db.flush()
    a_id = tc_a.id
    # A班合法成员：s1（有分）、合法 anon 无分学生
    db.add(TeachingClassMember(teaching_class_id=tc_a.id, student_id="s1", source="manual"))
    anon_sid = f"_anon:{a_id}:无分学生"
    db.add(TeachingClassMember(teaching_class_id=tc_a.id, student_id=anon_sid,
                               source="manual", name="无分学生"))
    db.commit()
    # 考试：s1 有数学分，anon 无分
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11-15")
    db.add(exam1); db.flush()
    db.add(SubjectScore(exam_id=exam1.id, student_id="s1", subject="数学",
        raw_score=85, grade_percentile=0.15, name="学生1", class_num=1))
    db.commit()
    # 作业花名册 + 作业记录：anon 有缺交
    db.add(ClassRoster(student_id=anon_sid, name="无分学生", class_num=1, excluded=0))
    db.add(ClassRoster(student_id="s1", name="学生1", class_num=1, excluded=0))
    db.commit()
    sem = HomeworkSemester(name="2025春", start_date="2025-02-17", end_date="2025-07-04", is_current=1)
    db.add(sem); db.flush()
    db.add(HomeworkRecord(student_id=anon_sid, date="2025-03-01", subject="校本",
        submission_status="缺交", content=""))
    db.add(HomeworkRecord(student_id="s1", date="2025-03-02", subject="校本",
        submission_status="缺交", content=""))
    # 档案：anon 有谈话记录
    db.add(StudentNote(student_id=anon_sid, date="2025-03-10",
        category="谈话", content="anon谈话记录"))
    db.add(StudentNote(student_id="s1", date="2025-03-10",
        category="谈话", content="s1谈话记录"))
    db.commit(); db.close()
""")


# ════════════════════════════════════════════════════════════════
#  Blocker 1-2：合法 anon 在作业/档案工具中可见，且返回真实数据
# ════════════════════════════════════════════════════════════════

class TestLegalAnonHomeworkAndNotes:
    """合法 _anon:<tid>:姓名 成员在当前学科范围内，student_homework_summary /
    student_notes 必须返回其真实作业/档案数据，而非「未找到」。"""

    def test_homework_summary_anon_returns_real_misses(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_homework_summary
            data = student_homework_summary(name="无分学生")
            has_error = bool(data.get("error"))
            total = data.get("total_misses")
            print(json.dumps({"has_error": has_error, "total_misses": total}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert not d["has_error"], f"合法 anon 不应报错: {d}"
        assert d["total_misses"] == 1, f"anon 应有 1 次缺交: {d}"

    def test_notes_anon_returns_real_record(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_notes
            data = student_notes(name="无分学生")
            has_error = bool(data.get("error"))
            contents = " ".join(n.get("content","") for n in data.get("notes", []))
            has_record = "anon谈话记录" in contents
            print(json.dumps({"has_error": has_error, "has_record": has_record}))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert not d["has_error"], f"合法 anon 档案不应报错: {d}"
        assert d["has_record"], f"anon 谈话记录应返回: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 3：合法成员即使无当前学科成绩，student_learning_profile 仍返回
# ════════════════════════════════════════════════════════════════

class TestProfileReturnsMemberWithoutScore:
    """合法 TeachingClassMember/ClassRoster 即使无当前 SubjectScore，
    student_learning_profile 按学号/姓名查询时应返回学生与空 series/null 成绩，
    而非「未找到」。A/B 同名仍按 scope 限定。"""

    def test_profile_by_id_returns_empty_series(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            db.add(tc); db.flush()
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="nomark",
                                       source="manual", name="无分张三"))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_learning_profile
            data = student_learning_profile(student_id="nomark")
            has_error = bool(data.get("error"))
            series_len = len(data.get("series", []))
            has_student = "student" in data
            print(json.dumps({"has_error": has_error, "series_len": series_len, "has_student": has_student}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        d = _parse_result(proc)
        assert not d["has_error"], f"无分成员不应报错: {d}"
        assert d["has_student"], f"应返回 student 对象: {d}"
        assert d["series_len"] == 0, f"无分成员 series 应为空: {d}"

    def test_profile_by_name_returns_empty_series(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            db.add(tc); db.flush()
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="nomark",
                                       source="manual", name="无分张三"))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_learning_profile
            data = student_learning_profile(name="无分张三")
            has_error = bool(data.get("error"))
            series_len = len(data.get("series", []))
            has_student = "student" in data
            print(json.dumps({"has_error": has_error, "series_len": series_len, "has_student": has_student}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        d = _parse_result(proc)
        assert not d["has_error"], f"按名查无分成员不应报错: {d}"
        assert d["has_student"], f"按名查应返回 student: {d}"
        assert d["series_len"] == 0, f"无分成员 series 应为空: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 4：identity 跨学段读取历史学号成绩
# ════════════════════════════════════════════════════════════════

class TestIdentityCrossSegment:
    """student_trend 先验证请求 student_id 属于当前 scope，再用
    student_ids_of_person 读同一人的历史学号成绩；趋势点标实际 student_id。"""

    def test_trend_reads_history_alias(self, tmp_path):
        """s_new 是当前 scope 成员（高二数学班），s_old 是 s_new 的历史学号
        （高一），两者通过 StudentAlias 链接。student_trend(s_new) 应读到
        s_old 的高一历史点。"""
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
                StudentIdentity, StudentAlias,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            db.add(tc); db.flush()
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="s_new", source="manual"))
            db.commit()
            # 高一历史考试（当前 scope 成员不在高一班，但同一人有历史学号）
            ex_old = Exam(name="高一月考", grade=1, semester="上", exam_type="月考", exam_date="2024-09-15")
            db.add(ex_old); db.flush()
            db.add(SubjectScore(exam_id=ex_old.id, student_id="s_old", subject="数学",
                raw_score=70, grade_percentile=0.3, name="张三", class_num=1))
            # 高二当前考试
            ex_new = Exam(name="高二期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11-15")
            db.add(ex_new); db.flush()
            db.add(SubjectScore(exam_id=ex_new.id, student_id="s_new", subject="数学",
                raw_score=85, grade_percentile=0.1, name="张三", class_num=1))
            # 建立 alias：s_new 和 s_old 是同一人
            ident = StudentIdentity(display_name="张三"); db.add(ident); db.flush()
            db.add(StudentAlias(student_id="s_new", identity_id=ident.id, link_source="name_confirmed"))
            db.add(StudentAlias(student_id="s_old", identity_id=ident.id, link_source="name_confirmed"))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_trend
            data = student_trend(student_id="s_new")
            series = data.get("series", [])
            exam_ids = sorted(s["exam_id"] for s in series)
            point_sids = [s.get("student_id") for s in series]
            print(json.dumps({"series_len": len(series), "exam_ids": exam_ids}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        d = _parse_result(proc)
        assert d["series_len"] == 2, f"应读到高一+高二两个历史点: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 5：同名非 alias 不串人
# ════════════════════════════════════════════════════════════════

class TestSameNameNotAliasNoCrosstalk:
    """当前班新学号与历史同名学号未建 alias 时，student_trend 不得把历史学号
    成绩串进来。"""

    def test_no_alias_no_crosstalk(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            db.add(tc); db.flush()
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="s_new", source="manual"))
            db.commit()
            ex_old = Exam(name="高一月考", grade=1, semester="上", exam_type="月考", exam_date="2024-09-15")
            db.add(ex_old); db.flush()
            # 历史同名学号 s_old，但未建 alias（不同人，恰好同名）
            db.add(SubjectScore(exam_id=ex_old.id, student_id="s_old", subject="数学",
                raw_score=70, grade_percentile=0.3, name="张三", class_num=1))
            ex_new = Exam(name="高二期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11-15")
            db.add(ex_new); db.flush()
            db.add(SubjectScore(exam_id=ex_new.id, student_id="s_new", subject="数学",
                raw_score=85, grade_percentile=0.1, name="张三", class_num=1))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_trend
            data = student_trend(student_id="s_new")
            series = data.get("series", [])
            print(json.dumps({"series_len": len(series)}))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        d = _parse_result(proc)
        assert d["series_len"] == 1, f"无 alias 不应串入历史同名学号: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 6：resolve_single_subject_context 对 teaching_class_id int>0 校验
# ════════════════════════════════════════════════════════════════

class TestResolveContextIntValidation:
    """resolve_single_subject_context 对 teaching_class_id 做 type(x) is int and x>0，
    bool/字符串/0/负数明确 ValueError。"""

    _ASSERT_TEMPLATE = textwrap.dedent("""\
        from app.db.models import SessionLocal
        from app.analysis.single_subject_metrics import resolve_single_subject_context
        db = SessionLocal()
        try:
            resolve_single_subject_context(db, teaching_class_id={val!r})
            result = {{"raised": False}}
        except (ValueError, TypeError):
            result = {{"raised": True}}
        finally:
            db.close()
        print(json.dumps(result))
    """)

    def test_rejects_bool(self, tmp_path):
        proc = _run_tool_test(tmp_path, _SETUP_ANON, self._ASSERT_TEMPLATE.format(val=True))
        d = _parse_result(proc)
        assert d["raised"], f"bool teaching_class_id 应被拒绝: {d}"

    def test_rejects_string(self, tmp_path):
        proc = _run_tool_test(tmp_path, _SETUP_ANON, self._ASSERT_TEMPLATE.format(val="1"))
        d = _parse_result(proc)
        assert d["raised"], f"字符串 teaching_class_id 应被拒绝: {d}"

    def test_rejects_zero(self, tmp_path):
        proc = _run_tool_test(tmp_path, _SETUP_ANON, self._ASSERT_TEMPLATE.format(val=0))
        d = _parse_result(proc)
        assert d["raised"], f"0 应被拒绝: {d}"

    def test_rejects_negative(self, tmp_path):
        proc = _run_tool_test(tmp_path, _SETUP_ANON, self._ASSERT_TEMPLATE.format(val=-3))
        d = _parse_result(proc)
        assert d["raised"], f"负数应被拒绝: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 7：list_exams grade 仅允许 None/1/2/3 且拒绝 bool；
#            student_exam_detail exam_id 必须正整数非 bool
# ════════════════════════════════════════════════════════════════

class TestListExamsGradeValidation:
    """list_exams grade 仅允许 None/1/2/3，拒绝 bool 和其他整数。"""

    def test_rejects_bool_grade(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import list_exams
            try:
                list_exams(grade=True)
                result = {"raised": False}
            except (ValueError, TypeError):
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert d["raised"], f"bool grade 应被拒绝: {d}"

    def test_rejects_grade_4(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import list_exams
            try:
                list_exams(grade=4)
                result = {"raised": False}
            except ValueError:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert d["raised"], f"grade=4 应被拒绝: {d}"


class TestExamDetailExamIdValidation:
    """student_exam_detail exam_id 必须是正整数非 bool。"""

    def test_rejects_bool_exam_id(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_exam_detail
            try:
                student_exam_detail(student_id="s1", exam_id=True)
                result = {"raised": False}
            except (ValueError, TypeError):
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert d["raised"], f"bool exam_id 应被拒绝: {d}"

    def test_rejects_negative_exam_id(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_exam_detail
            try:
                student_exam_detail(student_id="s1", exam_id=-1)
                result = {"raised": False}
            except ValueError:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert d["raised"], f"负 exam_id 应被拒绝: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 8：student_trend 显式 exam_ids 必须正整数列表且全属当前 scope
# ════════════════════════════════════════════════════════════════

class TestStudentTrendExamIdsValidation:
    """student_trend exam_ids 必须是正整数列表，且每个考试均属于当前 subject/scope。
    任何非法/不存在/他班独有考试明确 ValueError，不能静默过滤后继续。"""

    def test_rejects_nonexistent_exam_id(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_trend
            try:
                student_trend(student_id="s1", exam_ids=[99999])
                result = {"raised": False}
            except ValueError:
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert d["raised"], f"不存在的 exam_id 应 ValueError: {d}"

    def test_rejects_bool_in_exam_ids(self, tmp_path):
        assert_code = textwrap.dedent("""\
            from app.chat.tools import student_trend
            try:
                student_trend(student_id="s1", exam_ids=[True])
                result = {"raised": False}
            except (ValueError, TypeError):
                result = {"raised": True}
            print(json.dumps(result))
        """)
        proc = _run_tool_test(tmp_path, _SETUP_ANON, assert_code)
        d = _parse_result(proc)
        assert d["raised"], f"exam_ids 含 bool 应被拒绝: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 9：student_trend/profile 返回 scope 与请求一致
# ════════════════════════════════════════════════════════════════

class TestScopeFieldConsistency:
    """student_trend/profile 返回 scope 字段：显式班为 teaching_class，
    全部为 all；teaching_class_id 字段一致。"""

    def test_explicit_class_scope(self, tmp_path):
        setup = textwrap.dedent("""\
            from app.db.models import SessionLocal
            db = SessionLocal()
            from app.db.models import (
                Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
            )
            t = Teacher(subject="数学"); db.add(t); db.flush()
            tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
            db.add(tc); db.flush()
            tc_id = tc.id
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="s1", source="manual"))
            ex = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
            db.add(ex); db.flush()
            db.add(SubjectScore(exam_id=ex.id, student_id="s1", subject="数学",
                raw_score=85, grade_percentile=0.1, name="甲", class_num=1))
            db.commit(); db.close()
        """)
        assert_code = textwrap.dedent("""\
            from app.db.models import SessionLocal, TeachingClass
            from app.chat.tools import student_trend, student_learning_profile
            _db = SessionLocal()
            tc = _db.query(TeachingClass).filter(TeachingClass.label=="A班").first()
            tc_id = tc.id
            _db.close()
            trend = student_trend(student_id="s1", teaching_class_id=tc_id)
            profile = student_learning_profile(student_id="s1", teaching_class_id=tc_id)
            print(json.dumps({
                "trend_scope": trend.get("scope"),
                "trend_tc_id": trend.get("teaching_class_id"),
                "profile_scope": profile.get("scope"),
                "profile_tc_id": profile.get("teaching_class_id"),
            }))
        """)
        proc = _run_tool_test(tmp_path, setup, assert_code)
        d = _parse_result(proc)
        assert d["trend_scope"] == "teaching_class", f"显式班 trend scope 应为 teaching_class: {d}"
        assert d["trend_tc_id"] is not None, f"显式班 trend tc_id 不应为 None: {d}"
        assert d["profile_scope"] == "teaching_class", f"显式班 profile scope 应为 teaching_class: {d}"


# ════════════════════════════════════════════════════════════════
#  Blocker 10：_safe_page / _safe_student_id 安全硬化
# ════════════════════════════════════════════════════════════════

class TestPromptSecurityHardening:
    """_safe_page 仅接受以 / 开头、≤200、无 CR/LF/TAB/NUL、无 ?/# 的 pathname。
    _safe_student_id 拒绝全部控制字符而非只 LF。"""

    def test_safe_page_rejects_no_leading_slash(self):
        from app.chat.session import _safe_page
        assert _safe_page("relative/path") is None

    def test_safe_page_rejects_carriage_return(self):
        from app.chat.session import _safe_page
        assert _safe_page("/ok\rINJECTED") is None

    def test_safe_page_rejects_tab(self):
        from app.chat.session import _safe_page
        assert _safe_page("/ok\tINJECTED") is None

    def test_safe_page_rejects_nul(self):
        from app.chat.session import _safe_page
        assert _safe_page("/ok\x00INJECTED") is None

    def test_safe_page_rejects_query(self):
        from app.chat.session import _safe_page
        assert _safe_page("/page?inject=1") is None

    def test_safe_page_rejects_hash(self):
        from app.chat.session import _safe_page
        assert _safe_page("/page#inject") is None

    def test_safe_page_accepts_valid(self):
        from app.chat.session import _safe_page
        assert _safe_page("/student/123") == "/student/123"

    def test_safe_page_dict_rejects_query_in_pathname(self):
        """page 为 dict 时 pathname 含 ? 也要拒绝。"""
        from app.chat.session import _safe_page
        assert _safe_page({"pathname": "/p?x=1"}) is None

    def test_safe_student_id_rejects_carriage_return(self):
        from app.chat.session import _safe_student_id
        assert _safe_student_id("123\rINJECT") is None

    def test_safe_student_id_rejects_tab(self):
        from app.chat.session import _safe_student_id
        assert _safe_student_id("123\tINJECT") is None

    def test_safe_student_id_rejects_nul(self):
        from app.chat.session import _safe_student_id
        assert _safe_student_id("123\x00INJECT") is None

    def test_safe_student_id_accepts_normal(self):
        from app.chat.session import _safe_student_id
        assert _safe_student_id("7250601") == "7250601"
