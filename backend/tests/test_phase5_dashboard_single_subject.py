"""阶段5：Dashboard / Compare / Weekly-Focus / Correlation 单学科化测试。

TDD RED 阶段：先写断言失败的真实测试，再由实现转 GREEN。

覆盖范围（对应 task §1–§7 的隔离反例）：
1. /api/dashboard/overview 只列当前任教学科教学班；返回 subject_avg / score_basis /
   focus_count；删除 main_total_avg；最近考试按班成员真实成绩选取；无总分组。
2. /api/class/compare 重定义为当前任教学科教学班横向对比；删除总分字段；同分采
   competition ranking；显式 exam_id 不越界；无其他学科。
3. /api/weekly-focus 接受 teaching_class_id；非空 class_num → 400；返回
   teaching_subject/teaching_class_id；最近成绩来自当前学科按班 rank，禁止
   TotalScore 诱惑。
4. /api/homework/correlation 单学科化：X 为所有作业种类缺交次数，Y 为当前学科按班
   subject_rank；class_num 非空 → 400；total_type 不再允许；subject 兼容但必须等于
   当前学科；无成绩者 subject_rank=null。
5. /api/homework/correlation/subjects 重定义为仅当前任教学科一项并返回
   teaching_subject。
6. 隔离反例：数学教师有数学 A/B 班 + 遗留物理班；物理班成员及诱惑 TotalScore /
   ClassAverage 不得进入 overview/compare/weekly/correlation。
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

    setup_script = sys.argv[1]
    with open(setup_script) as f:
        exec(f.read())

    assert_script = sys.argv[2]
    with open(assert_script) as f:
        exec(f.read())
""")


def _run_isolated_api_test(tmp_path, setup_code: str, assert_code: str):
    """在子进程中用全新临时 DB 运行 API 测试，返回 proc。"""
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
        timeout=90,
        check=False,
    )
    return proc


def _parse_stdout(proc):
    """Return the last JSON line of proc.stdout (or raise with full output)."""
    if proc.returncode != 0:
        raise AssertionError(f"子进程失败 (rc={proc.returncode}):\n{proc.stdout}")
    lines = [ln for ln in proc.stdout.strip().split("\n") if ln.strip()]
    return json.loads(lines[-1])


# ──────────────────────────────────────────────────────────────
#  共享 fixture：数学教师，A/B 两个数学教学班 + 一个遗留物理教学班
# ──────────────────────────────────────────────────────────────

_SETUP_MATH_WITH_LEGACY_PHYSICS = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, TotalScore, ClassAverage,
        ClassRoster, HomeworkRecord,
    )
    from datetime import datetime

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()

    # A班: s1, s2, s3 ; B班: s4, s5 ; 遗留物理班 P: s6, s7
    for label, sids, subj in [
        ("A班", ["s1","s2","s3"], "数学"),
        ("B班", ["s4","s5"], "数学"),
        ("P班", ["s6","s7"], "物理"),  # 遗留：他科教学班
    ]:
        tc = TeachingClass(grade=2, label=label, subject=subj, kind="教学")
        db.add(tc)
        db.flush()
        for sid in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    # 考试1（期中）: 数学 + 物理 + TotalScore
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam1)
    db.flush()
    # 数学成绩（A/B 成员）
    math_scores = {"s1": (81, 70), "s2": (82, 69), "s3": (83, 68),
                   "s4": (84, 67), "s5": (85, 66)}
    for sid, (raw, gs) in math_scores.items():
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=raw, grade_score=gs, grade_percentile=0.5,
            name=f"学生{sid}", class_num=1, xueji=252000))
    # 物理成绩（P 班成员 + A/B 成员也有，但物理不是任教学科）
    for sid in ["s1","s2","s3","s4","s5","s6","s7"]:
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="物理",
            raw_score=50, grade_score=40, grade_percentile=0.5,
            name=f"物理{sid}", class_num=2, xueji=252999))
    # 数学成绩（P 班成员也有——用来验证遗留班成员不得进入 overview/compare）
    for sid in ["s6","s7"]:
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=99, grade_score=99, grade_percentile=0.01,
            name=f"遗留{sid}", class_num=2, xueji=252999))
    # TotalScore——诱惑，不得影响单学科化端点
    for sid in ["s1","s2","s3","s4","s5","s6","s7"]:
        db.add(TotalScore(exam_id=exam1.id, student_id=sid, total_type="主三门",
            total_score=280, xueji_rank=1, grade_percentile=0.1))
    # ClassAverage——诱惑，compare 不得读取
    db.add(ClassAverage(exam_id=exam1.id, class_num=1, class_label="A班",
        subject_averages={"物理": 50}, total_averages={"主三门": 280}))
    db.commit()

    # 考试2（月考，更早）: 只有数学成绩（A/B 班成员）
    exam2 = Exam(name="月考", grade=2, semester="上", exam_type="月考", exam_date="2025-09")
    db.add(exam2)
    db.flush()
    for sid, (raw, gs) in math_scores.items():
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="数学",
            raw_score=raw-10, grade_score=gs-5, grade_percentile=0.6,
            name=f"学生{sid}", class_num=1, xueji=252000))
    db.commit()

    # 作业花名册 + 缺交记录（供 correlation/weekly 使用）
    for sid in ["s1","s2","s3","s4","s5","s6","s7"]:
        db.add(ClassRoster(student_id=sid, name=f"学生{sid}", class_num=1, excluded=0))
    db.commit()
    # s1 缺交 3 次，s2 缺交 1 次
    for sid in ["s1","s1","s1","s2"]:
        db.add(HomeworkRecord(student_id=sid, date="2025-11-01",
            subject="校本", submission_status="缺交"))
    db.commit()

    db.close()
""")


# ════════════════════════════════════════════════════════════════
#  §1 /api/dashboard/overview
# ════════════════════════════════════════════════════════════════


class TestDashboardOverviewSingleSubject:
    def test_returns_teaching_subject(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/dashboard/overview")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {"teaching_subject": data.get("teaching_subject")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["teaching_subject"] == "数学"

    def test_only_lists_current_subject_classes(self, tmp_path):
        """只列数学 A/B 班，遗留物理 P 班不得出现。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/dashboard/overview")
            assert r.status_code == 200, r.text
            data = r.json()
            labels = {c["label"] for c in data.get("classes", [])}
            result = {"labels": sorted(labels)}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert "A班" in data["labels"], f"应包含 A班: {data}"
        assert "B班" in data["labels"], f"应包含 B班: {data}"
        assert "P班" not in data["labels"], f"不得包含遗留物理 P班: {data}"

    def test_no_main_total_avg_field(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/dashboard/overview")
            assert r.status_code == 200, r.text
            classes = r.json().get("classes", [])
            assert classes, "应至少一个班"
            keys = set(classes[0].keys())
            result = {
                "has_main_total_avg": "main_total_avg" in keys,
                "has_subject_avg": "subject_avg" in keys,
                "has_score_basis": "score_basis" in keys,
                "has_focus_count": "focus_count" in keys,
                "has_teaching_subject": "teaching_subject" in set(r.json().keys()),
                "keys": sorted(keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert not data["has_main_total_avg"], f"不应再有 main_total_avg: {data}"
        assert data["has_subject_avg"], f"应有 subject_avg: {data}"
        assert data["has_score_basis"], f"应有 score_basis: {data}"
        assert data["has_focus_count"], f"应有 focus_count: {data}"
        assert data["has_teaching_subject"], f"顶层应有 teaching_subject: {data}"

    def test_overall_excludes_legacy_class_members(self, tmp_path):
        """overall 学生数为当前数学教学班成员并集（5 人），不含 P 班 s6/s7。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/dashboard/overview")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {"total_students": data.get("overall", {}).get("total_students")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["total_students"] == 5, \
            f"overall 学生数应为 5（A∪B），得到 {data['total_students']}"


# ════════════════════════════════════════════════════════════════
#  §2 /api/class/compare
# ════════════════════════════════════════════════════════════════


class TestClassCompareSingleSubject:
    def test_returns_teaching_subject(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/class/compare")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {"teaching_subject": data.get("teaching_subject")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["teaching_subject"] == "数学"

    def test_only_my_classes_no_legacy(self, tmp_path):
        """只返回数学 A/B 班；不得有行政班或遗留物理 P 班。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/class/compare")
            assert r.status_code == 200, r.text
            exams = r.json().get("exams", [])
            assert exams, "应有考试"
            cls = exams[0].get("classes", [])
            labels = [c.get("class_label") or c.get("teaching_class_id") for c in cls]
            result = {"labels": sorted(str(l) for l in labels)}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        labels = set(data["labels"])
        assert "P班" not in labels, f"不得含遗留物理 P班: {data}"

    def test_no_total_fields(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/class/compare")
            assert r.status_code == 200, r.text
            exams = r.json().get("exams", [])
            assert exams, "应有考试"
            cls = exams[0].get("classes", [])
            assert cls, "应有班级行"
            keys = set(cls[0].keys())
            banned = {"main_total_avg", "five_total_avg", "nine_total_avg",
                      "plus3_avg", "total_avg"}
            result = {
                "banned_present": sorted(banned & keys),
                "has_subject_avg": "subject_avg" in keys,
                "has_teaching_class_id": "teaching_class_id" in keys,
                "has_member_count": "member_count" in keys,
                "has_score_basis": "score_basis" in keys,
                "keys": sorted(keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["banned_present"] == [], \
            f"不应再有总分字段: {data['banned_present']}"
        assert data["has_subject_avg"], f"应有 subject_avg: {data}"
        assert data["has_teaching_class_id"], f"应有 teaching_class_id: {data}"
        assert data["has_member_count"], f"应有 member_count: {data}"
        assert data["has_score_basis"], f"应有 score_basis: {data}"

    def test_explicit_exam_id_does_not_expand_scope(self, tmp_path):
        """显式 exam_id 必须是当前学科合法范围内的考试；不会拉入其他考试。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/class/compare?exam_id=999")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {"exam_count": len(data.get("exams", []))}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["exam_count"] == 0, \
            f"不存在的 exam_id 不应返回任何考试，得到 {data}"


# ════════════════════════════════════════════════════════════════
#  §3 /api/weekly-focus
# ════════════════════════════════════════════════════════════════


class TestWeeklyFocusSingleSubject:
    def test_class_num_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/weekly-focus?class_num=1")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["status_code"] == 400, \
            f"非空 class_num 应返回 400，得到 {data['status_code']}"

    def test_accepts_teaching_class_id(self, tmp_path):
        assert_code = textwrap.dedent("""\
            # 找到 A 班的 teaching_class_id
            r0 = client.get("/api/teaching/classes")
            classes = r0.json().get("classes", [])
            a_cls = [c for c in classes if c.get("label") == "A班"][0]
            tc_id = a_cls["id"]
            r = client.get(f"/api/weekly-focus?teaching_class_id={tc_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {
                "teaching_class_id": data.get("teaching_class_id"),
                "teaching_subject": data.get("teaching_subject"),
                "student_ids": sorted(s["student_id"] for s in data.get("students", [])),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["teaching_subject"] == "数学", \
            f"应返回 teaching_subject=数学: {data}"
        # 显式 A 班只含 A 班成员 s1/s2/s3
        for sid in data["student_ids"]:
            assert sid in {"s1", "s2", "s3"}, \
                f"显式 A 班不得含非 A 成员 {sid}: {data}"

    def test_default_scope_excludes_legacy(self, tmp_path):
        """默认范围（无 teaching_class_id）只含当前数学教学班成员并集 s1-s5，
        不含遗留 P 班 s6/s7。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/weekly-focus")
            assert r.status_code == 200, r.text
            data = r.json()
            student_ids = {s["student_id"] for s in data.get("students", [])}
            # 缺交只在 s1/s2 上，若 weekly 关注名单包含它们即足够
            has_legacy = {"s6", "s7"} & student_ids
            result = {
                "student_ids": sorted(student_ids),
                "has_legacy": bool(has_legacy),
                "teaching_subject": data.get("teaching_subject"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert not data["has_legacy"], \
            f"默认范围不得含遗留物理班 s6/s7: {data}"
        assert data["teaching_subject"] == "数学"


# ════════════════════════════════════════════════════════════════
#  §4 /api/homework/correlation
# ════════════════════════════════════════════════════════════════


class TestHomeworkCorrelationSingleSubject:
    def test_class_num_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation?class_num=1")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["status_code"] == 400, \
            f"非空 class_num 应返回 400: {data}"

    def test_total_type_rejected(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation?total_type=主三门")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["status_code"] == 400, \
            f"total_type 不再允许，应 400: {data}"

    def test_subject_must_match_current(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation?subject=物理")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["status_code"] == 400, \
            f"subject=物理 不等于当前数学，应 400: {data}"

    def test_returns_subject_rank_y_field(self, tmp_path):
        """Y 字段统一为 subject_rank（按班排名，越小越好）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation")
            assert r.status_code == 200, r.text
            data = r.json()
            rows = data.get("rows", [])
            keys = set(rows[0].keys()) if rows else set()
            result = {
                "y_field": data.get("y_field"),
                "teaching_subject": data.get("teaching_subject"),
                "has_xueji_rank": "xueji_rank" in keys,
                "has_total_score": "total_score" in keys,
                "has_subject_rank": "subject_rank" in keys,
                "keys": sorted(keys),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["y_field"] == "subject_rank", \
            f"y_field 应为 subject_rank: {data}"
        assert data["teaching_subject"] == "数学", \
            f"teaching_subject 应为 数学: {data}"
        assert not data["has_xueji_rank"], \
            f"不应再有 xueji_rank: {data}"
        assert not data["has_total_score"], \
            f"不应再有 total_score: {data}"
        assert data["has_subject_rank"], \
            f"应有 subject_rank: {data}"

    def test_accepts_teaching_class_id(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r0 = client.get("/api/teaching/classes")
            a_cls = [c for c in r0.json().get("classes", []) if c.get("label") == "A班"][0]
            tc_id = a_cls["id"]
            r = client.get(f"/api/homework/correlation?teaching_class_id={tc_id}")
            assert r.status_code == 200, r.text
            data = r.json()
            result = {"teaching_class_id": data.get("teaching_class_id")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["teaching_class_id"] is not None


# ════════════════════════════════════════════════════════════════
#  §5 /api/homework/correlation/subjects
# ════════════════════════════════════════════════════════════════


class TestHomeworkCorrelationSubjectsSingleSubject:
    def test_returns_only_current_subject(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation/subjects")
            assert r.status_code == 200, r.text
            data = r.json()
            rankings = data.get("rankings", [])
            subjects = {x["subject"] for x in rankings}
            result = {
                "subjects": sorted(subjects),
                "teaching_subject": data.get("teaching_subject"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["teaching_subject"] == "数学", \
            f"teaching_subject 应为 数学: {data}"
        assert "数学" in data["subjects"], f"应含当前学科: {data}"
        # 不应再扫描九门学科
        assert "物理" not in data["subjects"] or len(data["subjects"]) == 1, \
            f"不应多学科扫描: {data}"


# ════════════════════════════════════════════════════════════════
#  §6 选考 grade_score 反向用例（高二物理 raw 与 grade_score 反向）
# ════════════════════════════════════════════════════════════════


_SETUP_PHYSICS_TEACHER = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord,
    )

    t = Teacher(subject="物理", name="物理老师")
    db.add(t)
    db.flush()
    for label, sids in [("A班", ["s1","s2"]), ("B班", ["s3","s4"])]:
        tc = TeachingClass(grade=2, label=label, subject="物理", kind="教学")
        db.add(tc)
        db.flush()
        for sid in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam)
    db.flush()
    # raw_score 高 → grade_score 低（反向）
    db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
        raw_score=95, grade_score=40, grade_percentile=0.9, name="甲", class_num=1, xueji=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="物理",
        raw_score=90, grade_score=70, grade_percentile=0.5, name="乙", class_num=1, xueji=2))
    db.add(SubjectScore(exam_id=exam.id, student_id="s3", subject="物理",
        raw_score=88, grade_score=67, grade_percentile=0.6, name="丙", class_num=2, xueji=3))
    db.add(SubjectScore(exam_id=exam.id, student_id="s4", subject="物理",
        raw_score=85, grade_score=64, grade_percentile=0.7, name="丁", class_num=2, xueji=4))
    db.commit()

    for sid in ["s1","s2","s3","s4"]:
        db.add(ClassRoster(student_id=sid, name=f"学{sid}", class_num=1, excluded=0))
    db.commit()

    db.close()
""")


class TestElectiveGradeScoreBasis:
    def test_overview_uses_grade_score_for_elective(self, tmp_path):
        """高二物理（选考）overview/compare 用 grade_score，而非 raw_score。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/dashboard/overview")
            assert r.status_code == 200, r.text
            classes = r.json().get("classes", [])
            assert classes
            cls = classes[0]
            result = {"score_basis": cls.get("score_basis")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_PHYSICS_TEACHER, assert_code)
        data = _parse_stdout(proc)
        assert data["score_basis"] == "grade_score", \
            f"高二物理选考 score_basis 应为 grade_score: {data}"


# ════════════════════════════════════════════════════════════════
#  §7 阶段5独立审查返工 RED 测试（1 Blocker + 4 High）
# ════════════════════════════════════════════════════════════════


# ── §7.1 Dashboard exam-detail 契约（前端源码契约回归） ──

class TestExamDetailContract:
    """exam-detail 必须返回 stats.avg/max/min/total_students/score_basis
    + 顶层 subject（而非 stats.avg_subject/max_subject/min_subject/count
    或顶层 teaching_subject）。"""

    def test_stats_keys_stable(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r0 = client.get("/api/teaching/classes")
            classes = r0.json().get("classes", [])
            a_cls = [c for c in classes if c.get("label") == "A班"][0]
            tc_id = a_cls["id"]
            r = client.get("/api/exams?teaching_class_id=%s" % tc_id)
            exams = r.json().get("exams", [])
            assert exams, "应有考试"
            latest = exams[0]
            d = client.get("/api/exams/%s?teaching_class_id=%s" % (latest["id"], tc_id)).json()
            stats = d.get("stats", {})
            result = {
                "has_avg": "avg" in stats,
                "has_max": "max" in stats,
                "has_min": "min" in stats,
                "has_total_students": "total_students" in stats,
                "has_score_basis": "score_basis" in stats,
                "has_avg_subject": "avg_subject" in stats,
                "has_max_subject": "max_subject" in stats,
                "has_count": "count" in stats,
                "has_subject_top": "subject" in d,
                "has_teaching_subject_top": "teaching_subject" in d,
                "avg": stats.get("avg"),
                "max": stats.get("max"),
                "min": stats.get("min"),
                "total_students": stats.get("total_students"),
                "score_basis": stats.get("score_basis"),
                "subject_top": d.get("subject"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        # 稳定契约字段必须存在
        for k in ("has_avg", "has_max", "has_min", "has_total_students", "has_score_basis"):
            assert data[k], f"stats 应含 {k}: {data}"
        # 旧错误字段不得存在
        for k in ("has_avg_subject", "has_max_subject", "has_count"):
            assert not data[k], f"stats 不应再有 {k}: {data}"
        # 顶层 subject 必须存在
        assert data["has_subject_top"], f"顶层应有 subject: {data}"
        # 均分/最高/最低/有效人数 不得恒为空
        assert data["avg"] is not None, f"avg 不得为空: {data}"
        assert data["max"] is not None, f"max 不得为空: {data}"
        assert data["min"] is not None, f"min 不得为空: {data}"
        assert data["total_students"] is not None, f"total_students 不得为空: {data}"
        assert data["score_basis"] in ("raw_score", "grade_score"), \
            f"score_basis 必须有值: {data}"
        assert data["subject_top"] == "数学", f"顶层 subject 应为数学: {data}"

    def test_score_basis_label_raw(self, tmp_path):
        """高一数学 score_basis 应为 raw_score（非空）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json().get("exams", [])
            assert exams
            latest = exams[0]
            d = client.get("/api/exams/%s" % latest["id"]).json()
            print(json.dumps({"score_basis": d.get("stats", {}).get("score_basis")}))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert data["score_basis"] == "raw_score", \
            f"高二非选考数学 score_basis 应为 raw_score: {data}"


# ── §7.1b Dashboard 默认 exam-detail 范围隔离（遗留他科班成员不得返回）──

class TestExamDetailDefaultScopeIsolation:
    """默认 exam-detail（无 teaching_class_id）必须只返回当前学科教学班成员，
    不得混入教师遗留他科教学班成员（即使后者有当前学科的诱饵成绩）。"""

    def test_default_excludes_legacy_class_members(self, tmp_path):
        """_SETUP_MATH_WITH_LEGACY_PHYSICS: 数学 A/B 班 s1-s5 + 遗留物理 P 班 s6/s7。
        s6/s7 在 exam1 有数学诱饵成绩(raw=99)。默认详情只返回 s1-s5。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json().get("exams", [])
            assert exams, "应有考试"
            latest = exams[0]
            d = client.get("/api/exams/%s" % latest["id"]).json()
            student_ids = sorted(s["student_id"] for s in d.get("students", []))
            result = {"student_ids": student_ids,
                      "total_students": d.get("stats", {}).get("total_students")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        assert "s6" not in data["student_ids"], \
            f"默认详情不得返回遗留物理班 s6: {data}"
        assert "s7" not in data["student_ids"], \
            f"默认详情不得返回遗留物理班 s7: {data}"
        assert data["total_students"] == 5, \
            f"默认详情学生数应为 5（A∪B），得到 {data}"

    def test_explicit_class_still_subject_checked(self, tmp_path):
        """显式 teaching_class_id 仍必须校验 subject/grade；遗留他科班 id 不能返回。"""
        assert_code = textwrap.dedent("""\
            r0 = client.get("/api/teaching/classes")
            classes = r0.json().get("classes", [])
            # 找 P 班（遗留物理）
            p_cls = [c for c in classes if c.get("label") == "P班"]
            r = client.get("/api/exams")
            exams = r.json().get("exams", [])
            latest = exams[0]["id"] if exams else 1
            if p_cls:
                d = client.get("/api/exams/%s?teaching_class_id=%s" % (latest, p_cls[0]["id"]))
                result = {"status": d.status_code}
            else:
                result = {"status": "no_P_class"}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_MATH_WITH_LEGACY_PHYSICS, assert_code)
        data = _parse_stdout(proc)
        # P 班 subject=物理 ≠ 教师 subject=数学 → 应 4xx
        assert data["status"] in (400, 404, 409), \
            f"显式他科班应被拒绝（subject 冲突），得到 {data}"


# ── §7.1c Dashboard exam-detail 统一 basis（不得逐行混排）──

_SETUP_EXAM_DETAIL_BASIS_CONFLICT = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster,
    )

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
    db.add(tc)
    db.flush()
    for sid in ["s1", "s2"]:
        db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam)
    db.flush()
    # 数学（非选考）→ score_basis=raw_score
    # s1 raw95/grade40, s2 raw90/grade70
    # 若逐行 grade_score 优先: s1=40, s2=70 → s2 rank1（错误）
    # 统一 raw_score: s1=95 rank1, s2=90 rank2（正确），avg=92.5
    db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学",
        raw_score=95, grade_score=40, grade_percentile=0.1, name="甲", class_num=1, xueji=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="数学",
        raw_score=90, grade_score=70, grade_percentile=0.9, name="乙", class_num=1, xueji=2))
    db.commit()
    db.close()
""")


class TestExamDetailUniformBasis:
    """非选考学科 score_basis=raw_score，整个池统一用 raw_score 排名和统计，
    不得逐行 grade_score 优先。"""

    def test_raw_score_basis_rank_and_stats(self, tmp_path):
        """s1 raw95/grade40, s2 raw90/grade70（数学非选考）。
        score_basis=raw_score → s1 rank1, s2 rank2, avg=92.5, max=95, min=90。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json().get("exams", [])
            assert exams
            latest = exams[0]
            d = client.get("/api/exams/%s" % latest["id"]).json()
            students = {s["student_id"]: s for s in d.get("students", [])}
            stats = d.get("stats", {})
            result = {
                "score_basis": stats.get("score_basis"),
                "s1_rank": students.get("s1", {}).get("rank"),
                "s2_rank": students.get("s2", {}).get("rank"),
                "avg": stats.get("avg"),
                "max": stats.get("max"),
                "min": stats.get("min"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_EXAM_DETAIL_BASIS_CONFLICT, assert_code)
        data = _parse_stdout(proc)
        assert data["score_basis"] == "raw_score", \
            f"数学非选考 score_basis 应为 raw_score: {data}"
        assert data["s1_rank"] == 1, f"s1 raw=95 应 rank1: {data}"
        assert data["s2_rank"] == 2, f"s2 raw=90 应 rank2: {data}"
        assert abs(data["avg"] - 92.5) < 0.05, f"avg 应为 92.5: {data}"
        assert data["max"] == 95, f"max 应为 95: {data}"
        assert data["min"] == 90, f"min 应为 90: {data}"


# ── §7.1d Dashboard exam-detail 选考学科反向用 grade_score ──

_SETUP_EXAM_DETAIL_ELECTIVE_REVERSE = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster,
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
    # 高二物理（选考）→ score_basis=grade_score
    # s1 raw95/grade40, s2 raw90/grade70（raw 与 grade_score 反向）
    # 统一 grade_score: s1=40, s2=70 → s2 rank1, s1 rank2
    db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
        raw_score=95, grade_score=40, grade_percentile=0.1, name="甲", class_num=1, xueji=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="物理",
        raw_score=90, grade_score=70, grade_percentile=0.9, name="乙", class_num=1, xueji=2))
    db.commit()
    db.close()
""")


class TestExamDetailElectiveGradeScoreBasis:
    """高二/高三选考学科 exam-detail 必须统一用 grade_score 排名和统计。"""

    def test_grade_score_basis_rank_and_stats(self, tmp_path):
        """s1 raw95/grade40, s2 raw90/grade70（高二物理选考，raw 与 grade 反向）。
        score_basis=grade_score → s2 rank1(70), s1 rank2(40), avg=55.0。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/exams")
            exams = r.json().get("exams", [])
            assert exams
            latest = exams[0]
            d = client.get("/api/exams/%s" % latest["id"]).json()
            students = {s["student_id"]: s for s in d.get("students", [])}
            stats = d.get("stats", {})
            result = {
                "score_basis": stats.get("score_basis"),
                "s1_rank": students.get("s1", {}).get("rank"),
                "s2_rank": students.get("s2", {}).get("rank"),
                "avg": stats.get("avg"),
                "max": stats.get("max"),
                "min": stats.get("min"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_EXAM_DETAIL_ELECTIVE_REVERSE, assert_code)
        data = _parse_stdout(proc)
        assert data["score_basis"] == "grade_score", \
            f"高二物理选考 score_basis 应为 grade_score: {data}"
        assert data["s2_rank"] == 1, f"s2 grade=70 应 rank1: {data}"
        assert data["s1_rank"] == 2, f"s1 grade=40 应 rank2: {data}"
        assert abs(data["avg"] - 55.0) < 0.05, f"avg 应为 55.0: {data}"
        assert data["max"] == 70, f"max 应为 70: {data}"
        assert data["min"] == 40, f"min 应为 40: {data}"


# ── §7.2 Correlation 最近考试：按 exam_date DESC 而非 max(id) ──

_SETUP_CORRELATION_DATE_ORDER = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord,
    )

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    tc = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
    db.add(tc)
    db.flush()
    for sid in ["s1", "s2"]:
        db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
    db.commit()

    # exam id=1 日期 2025-11（较晚）；exam id=2 日期 2025-09（较早）
    exam1 = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam1)
    db.flush()
    exam2 = Exam(name="月考", grade=2, semester="上", exam_type="月考", exam_date="2025-09")
    db.add(exam2)
    db.flush()
    # exam2.id 可能 < exam1.id（取决于 flush 顺序），但关键是 exam1 日期更晚

    # exam1（id 较小但日期更晚）：s1=90, s2=80
    for sid, sc in [("s1", 90), ("s2", 80)]:
        db.add(SubjectScore(exam_id=exam1.id, student_id=sid, subject="数学",
            raw_score=sc, grade_score=None, grade_percentile=0.5,
            name=f"学{sid}", class_num=1, xueji=252000))
    # exam2（id 较大但日期更早）：s1=60, s2=50
    for sid, sc in [("s1", 60), ("s2", 50)]:
        db.add(SubjectScore(exam_id=exam2.id, student_id=sid, subject="数学",
            raw_score=sc, grade_score=None, grade_percentile=0.5,
            name=f"学{sid}", class_num=1, xueji=252000))
    db.commit()

    for sid in ["s1", "s2"]:
        db.add(ClassRoster(student_id=sid, name=f"学{sid}", class_num=1, excluded=0))
    # s1 缺交，s2 不缺交
    for _ in range(3):
        db.add(HomeworkRecord(student_id="s1", date="2025-11-01",
            subject="校本", submission_status="缺交"))
    db.commit()
    db.close()
""")


class TestCorrelationLatestExamByDate:
    def test_default_picks_latest_by_date_not_max_id(self, tmp_path):
        """默认必须选 exam_date 最晚的考试，而非 max(id)。
        反例：exam1(id小, 2025-11) vs exam2(id大, 2025-09) → 必须选 exam1。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation")
            assert r.status_code == 200, r.text
            data = r.json()
            # 找到两个 exam id
            r0 = client.get("/api/exams")
            exams = {e["id"]: e for e in r0.json().get("exams", [])}
            # exam_date 最晚的考试 id
            latest_id = max(exams, key=lambda i: (exams[i]["exam_date"], i))
            result = {"chosen_exam_id": data.get("exam_id"), "latest_by_date": latest_id}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_CORRELATION_DATE_ORDER, assert_code)
        data = _parse_stdout(proc)
        assert data["chosen_exam_id"] == data["latest_by_date"], \
            f"correlation 默认应选日期最晚的考试，得到 {data}"

    def test_explicit_out_of_scope_exam_id_returns_400(self, tmp_path):
        """显式提供不属于当前教学班/学科/范围的 exam_id 必须 400，不得静默替换。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation?exam_id=99999")
            result = {"status_code": r.status_code}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_CORRELATION_DATE_ORDER, assert_code)
        data = _parse_stdout(proc)
        assert data["status_code"] == 400, \
            f"不合法的 exam_id 应 400，得到 {data['status_code']}"

    def test_subjects_endpoint_also_latest_by_date(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation/subjects")
            assert r.status_code == 200, r.text
            data = r.json()
            r0 = client.get("/api/exams")
            exams = {e["id"]: e for e in r0.json().get("exams", [])}
            latest_id = max(exams, key=lambda i: (exams[i]["exam_date"], i))
            result = {"chosen_exam_id": data.get("exam_id"), "latest_by_date": latest_id}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_CORRELATION_DATE_ORDER, assert_code)
        data = _parse_stdout(proc)
        assert data["chosen_exam_id"] == data["latest_by_date"], \
            f"correlation/subjects 默认应选日期最晚的考试，得到 {data}"


# ── §7.3 高二/三选考 correlation 排名 basis 必须用 grade_score ──

_SETUP_ELECTIVE_BASIS_CONFLICT = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord,
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
    # s1: raw95/grade40/percentile=0.1（percentile 排名会得 rank1，但 grade_score 排名应得 rank2）
    # s2: raw90/grade70/percentile=0.9（percentile 排名会得 rank2，但 grade_score 排名应得 rank1）
    db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
        raw_score=95, grade_score=40, grade_percentile=0.1, name="甲", class_num=1, xueji=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="物理",
        raw_score=90, grade_score=70, grade_percentile=0.9, name="乙", class_num=1, xueji=2))
    db.commit()

    for sid in ["s1", "s2"]:
        db.add(ClassRoster(student_id=sid, name=f"学{sid}", class_num=1, excluded=0))
    db.commit()
    db.close()
""")


class TestCorrelationElectiveGradeScoreBasis:
    """高二物理 raw 与 grade_score 反向：必须按 grade_score 排名。
    s1 raw95/grade40/percentile=0.1, s2 raw90/grade70/percentile=0.9。
    percentile 模式会得 s1 rank1（错误）；grade_score 模式应得 s2 rank1。"""

    def test_rank_uses_grade_score_not_raw(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation")
            assert r.status_code == 200, r.text
            rows = {row["student_id"]: row for row in r.json().get("rows", [])}
            result = {
                "s1_rank": rows.get("s1", {}).get("subject_rank"),
                "s2_rank": rows.get("s2", {}).get("subject_rank"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_ELECTIVE_BASIS_CONFLICT, assert_code)
        data = _parse_stdout(proc)
        # s1 grade_score=40, s2 grade_score=70 → s2 rank1(small), s1 rank2
        assert data["s2_rank"] == 1, f"s2 grade_score=70 应 rank1: {data}"
        assert data["s1_rank"] == 2, f"s1 grade_score=40 应 rank2: {data}"

    def test_subjects_endpoint_also_uses_grade_score(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/homework/correlation/subjects")
            assert r.status_code == 200, r.text
            # subjects 端点的 rankings 只返回 r/n，不直接给 rank；
            # 但 exam_id 必须选中有 grade_score 的考试
            result = {"has_data": len(r.json().get("rankings", [])) > 0}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_ELECTIVE_BASIS_CONFLICT, assert_code)
        data = _parse_stdout(proc)
        assert data["has_data"], f"subjects 端点应有数据: {data}"


# ── §7.4 Compare overall_subject_avg 直接聚合 + competition ranking 精度 ──

_SETUP_COMPARE_OVERALL = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster,
    )

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    # A班: s1(40), s2(70) ; B班: s3..s10 各40
    tc_a = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
    tc_b = TeachingClass(grade=2, label="B班", subject="数学", kind="教学")
    db.add_all([tc_a, tc_b])
    db.flush()
    for sid in ["s1", "s2"]:
        db.add(TeachingClassMember(teaching_class_id=tc_a.id, student_id=sid, source="manual"))
    for sid in ["s3","s4","s5","s6","s7","s8","s9","s10"]:
        db.add(TeachingClassMember(teaching_class_id=tc_b.id, student_id=sid, source="manual"))
    db.commit()

    exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam)
    db.flush()
    # A班: s1=40, s2=70 → 班均 55.0
    db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学",
        raw_score=40, grade_score=None, grade_percentile=0.5, name="甲", class_num=1, xueji=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="数学",
        raw_score=70, grade_score=None, grade_percentile=0.5, name="乙", class_num=1, xueji=2))
    # B班: 8人各40 → 班均 40.0
    for i, sid in enumerate(["s3","s4","s5","s6","s7","s8","s9","s10"], 3):
        db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
            raw_score=40, grade_score=None, grade_percentile=0.5,
            name=f"生{i}", class_num=2, xueji=i))
    db.commit()
    db.close()
""")


class TestCompareOverallAggregate:
    def test_overall_is_student_aggregate_not_class_avg(self, tmp_path):
        """overall_subject_avg 必须直接对全部 10 名唯一学生的 score 求均，
        不得简单平均各班均分。
        反例：A班2人40/70, B班8人40 → overall=43.0, 不是(55+40)/2=47.5。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/class/compare")
            assert r.status_code == 200, r.text
            exams = r.json().get("exams", [])
            assert exams
            result = {"overall_subject_avg": exams[0].get("overall_subject_avg")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_COMPARE_OVERALL, assert_code)
        data = _parse_stdout(proc)
        # 10名学生：s1=40, s2=70, s3..s10=40×8 → 总和 40+70+320=430 / 10 = 43.0
        assert abs(data["overall_subject_avg"] - 43.0) < 0.05, \
            f"overall_subject_avg 应为 43.0（直接学生聚合），得到 {data}"


# ── §7.4b Compare competition ranking 使用未舍入真实班均 ──

_SETUP_COMPARE_RANKING_PRECISION = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster,
    )

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    tc_a = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
    tc_b = TeachingClass(grade=2, label="B班", subject="数学", kind="教学")
    db.add_all([tc_a, tc_b])
    db.flush()
    for sid in ["s1", "s2"]:
        db.add(TeachingClassMember(teaching_class_id=tc_a.id, student_id=sid, source="manual"))
    for sid in ["s3", "s4"]:
        db.add(TeachingClassMember(teaching_class_id=tc_b.id, student_id=sid, source="manual"))
    db.commit()

    exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam)
    db.flush()
    # A班真实均分 = (80.04+80.04)/2 = 80.04 → round(1)=80.0
    for sid in ["s1", "s2"]:
        db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
            raw_score=80.04, grade_score=None, grade_percentile=0.5,
            name=f"甲{sid}", class_num=1, xueji=1))
    # B班真实均分 = (79.96+79.96)/2 = 79.96 → round(1)=80.0
    for sid in ["s3", "s4"]:
        db.add(SubjectScore(exam_id=exam.id, student_id=sid, subject="数学",
            raw_score=79.96, grade_score=None, grade_percentile=0.5,
            name=f"乙{sid}", class_num=2, xueji=2))
    db.commit()
    db.close()
""")


class TestCompareRankingPrecision:
    def test_unrounded_class_avg_for_ranking(self, tmp_path):
        """competition ranking 必须使用未舍入真实班均；仅输出时 round(1)。
        反例：A班80.04, B班79.96 → A rank1, B rank2（不得因都显示80.0 并列）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/class/compare")
            assert r.status_code == 200, r.text
            exams = r.json().get("exams", [])
            assert exams
            classes = {c["class_label"]: c for c in exams[0].get("classes", [])}
            result = {
                "a_rank": classes.get("A班", {}).get("rank"),
                "b_rank": classes.get("B班", {}).get("rank"),
                "a_avg": classes.get("A班", {}).get("subject_avg"),
                "b_avg": classes.get("B班", {}).get("subject_avg"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_COMPARE_RANKING_PRECISION, assert_code)
        data = _parse_stdout(proc)
        assert data["a_rank"] == 1, f"A班真实均分更高应 rank1: {data}"
        assert data["b_rank"] == 2, f"B班真实均分更低应 rank2: {data}"


# ── §7.4c Compare 重叠成员 overall 去重 ──

_SETUP_COMPARE_OVERLAPPING_MEMBERS = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster,
    )

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    # A班: s1, s2 ; B班: s2, s3 （s2 重叠）
    tc_a = TeachingClass(grade=2, label="A班", subject="数学", kind="教学")
    tc_b = TeachingClass(grade=2, label="B班", subject="数学", kind="教学")
    db.add_all([tc_a, tc_b])
    db.flush()
    for sid in ["s1", "s2"]:
        db.add(TeachingClassMember(teaching_class_id=tc_a.id, student_id=sid, source="manual"))
    for sid in ["s2", "s3"]:
        db.add(TeachingClassMember(teaching_class_id=tc_b.id, student_id=sid, source="manual"))
    db.commit()

    exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam)
    db.flush()
    # s1=60, s2=80(重叠), s3=60
    db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="数学",
        raw_score=60, grade_score=None, grade_percentile=0.5, name="甲", class_num=1, xueji=1))
    db.add(SubjectScore(exam_id=exam.id, student_id="s2", subject="数学",
        raw_score=80, grade_score=None, grade_percentile=0.5, name="乙", class_num=1, xueji=2))
    db.add(SubjectScore(exam_id=exam.id, student_id="s3", subject="数学",
        raw_score=60, grade_score=None, grade_percentile=0.5, name="丙", class_num=2, xueji=3))
    db.commit()
    db.close()
""")


class TestCompareOverlappingMembers:
    """A={s1,s2}, B={s2,s3}（s2 重叠）。overall_subject_avg 必须只计 s2 一次。
    唯一学生 {s1=60, s2=80, s3=60} → overall=(60+80+60)/3=66.67→round=66.7。
    若不去重会得 (60+80+80+60)/4=70.0（错误）。"""

    def test_overall_dedup_overlapping(self, tmp_path):
        assert_code = textwrap.dedent("""\
            r = client.get("/api/class/compare")
            assert r.status_code == 200, r.text
            exams = r.json().get("exams", [])
            assert exams
            result = {"overall_subject_avg": exams[0].get("overall_subject_avg")}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_COMPARE_OVERLAPPING_MEMBERS, assert_code)
        data = _parse_stdout(proc)
        # 唯一学生 s1=60, s2=80, s3=60 → (60+80+60)/3 = 66.666... → round(1)=66.7
        assert abs(data["overall_subject_avg"] - 66.7) < 0.05, \
            f"overall 应去重重叠成员 s2（计一次），得到 {data}"


# ── §7.5 WeeklyFocus 默认范围与匿名成员 ──

_SETUP_WEEKLY_ANON = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord, HomeworkSemester,
    )

    # 设置当前学期覆盖 2025-11（默认学期是 2026 年，会导致缺交记录被时间轴过滤）
    db.add(HomeworkSemester(name="2025秋", start_date="2025-09-01",
        end_date="2026-02-28", is_current=1))
    db.commit()

    t = Teacher(subject="物理", name="物理老师")
    db.add(t)
    db.flush()
    tc = TeachingClass(grade=2, label="物理班", subject="物理", kind="教学")
    db.add(tc)
    db.flush()
    # s1 真实学号成员；_anon 成员（花名册中仅姓名）
    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="s1", source="manual"))
    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="_anon:%d:李某" % tc.id, source="manual"))
    db.commit()

    exam = Exam(name="期中", grade=2, semester="上", exam_type="期中", exam_date="2025-11")
    db.add(exam)
    db.flush()
    # s1 有物理成绩；_anon 无成绩
    db.add(SubjectScore(exam_id=exam.id, student_id="s1", subject="物理",
        raw_score=88, grade_score=67, grade_percentile=0.6, name="甲", class_num=1, xueji=1))
    db.commit()

    # 花名册：s1 和 _anon 都是合法仅姓名教学班成员
    for sid, name in [("s1", "学生s1"), ("_anon:%d:李某" % tc.id, "李某")]:
        db.add(ClassRoster(student_id=sid, name=name, class_num=1, excluded=0))
    # s1 连续缺交 2 次（不同日期）；_anon 也连续缺交 2 次（不同日期）
    anon_id = "_anon:%d:李某" % tc.id
    for day in ["2025-11-01", "2025-11-02"]:
        db.add(HomeworkRecord(student_id="s1", date=day,
            subject="校本", submission_status="缺交"))
        db.add(HomeworkRecord(student_id=anon_id, date=day,
            subject="校本", submission_status="缺交"))
    db.commit()
    db.close()
""")


class TestWeeklyAnonMember:
    def test_anon_homework_streak_retained(self, tmp_path):
        """匿名成员（花名册中合法仅姓名教学班成员）的作业缺交连续判定必须保留；
        匿名成员应进入 Weekly 的缺交信号。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/weekly-focus")
            assert r.status_code == 200, r.text
            data = r.json()
            students = {s["student_id"]: s for s in data.get("students", [])}
            anon_ids = [sid for sid in students if sid.startswith("_anon:")]
            s1_reasons = students.get("s1", {}).get("reasons", [])
            result = {
                "anon_in_weekly": len(anon_ids) > 0,
                "s1_has_streak": any("连续缺交" in r for r in s1_reasons),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_WEEKLY_ANON, assert_code)
        data = _parse_stdout(proc)
        assert data["anon_in_weekly"], \
            f"匿名成员连续缺交应进入 Weekly: {data}"
        assert data["s1_has_streak"], \
            f"s1 连续缺交应进入 Weekly: {data}"


# ── §7.5b WeeklyFocus 默认范围必须先按当前学科过滤 ──

_SETUP_WEEKLY_SUBJECT_FILTER = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord, HomeworkSemester,
    )

    # 设置当前学期覆盖 2025-11
    db.add(HomeworkSemester(name="2025秋", start_date="2025-09-01",
        end_date="2026-02-28", is_current=1))
    db.commit()

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    # 数学班 s1；遗留物理班 p1（他科教学班）
    tc_math = TeachingClass(grade=2, label="数学班", subject="数学", kind="教学")
    tc_phys = TeachingClass(grade=2, label="物理班", subject="物理", kind="教学")
    db.add_all([tc_math, tc_phys])
    db.flush()
    db.add(TeachingClassMember(teaching_class_id=tc_math.id, student_id="s1", source="manual"))
    db.add(TeachingClassMember(teaching_class_id=tc_phys.id, student_id="p1", source="manual"))
    db.commit()

    # 花名册：s1 和 p1 都是合法成员
    for sid, name in [("s1", "学生s1"), ("p1", "学生p1")]:
        db.add(ClassRoster(student_id=sid, name=name, class_num=1, excluded=0))
    db.commit()

    # s1 在数学班连续缺交 2 次
    for day in ["2025-11-01", "2025-11-02"]:
        db.add(HomeworkRecord(student_id="s1", date=day,
            subject="校本", submission_status="缺交"))
    # p1 在遗留物理班也连续缺交 2 次（不得进入数学老师的 Weekly）
    for day in ["2025-11-01", "2025-11-02"]:
        db.add(HomeworkRecord(student_id="p1", date=day,
            subject="校本", submission_status="缺交"))
    db.commit()
    db.close()
""")


class TestWeeklySubjectScopeFilter:
    """默认 Weekly 必须先按当前学科过滤；遗留他科教学班成员不得进入。"""

    def test_default_excludes_legacy_subject_member(self, tmp_path):
        """数学班 s1 连续缺交、遗留物理班 p1 也连续缺交。
        默认 Weekly 只返回 s1，不得返回 p1。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/weekly-focus")
            assert r.status_code == 200, r.text
            data = r.json()
            student_ids = {s["student_id"] for s in data.get("students", [])}
            result = {
                "student_ids": sorted(student_ids),
                "has_p1": "p1" in student_ids,
                "teaching_subject": data.get("teaching_subject"),
            }
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_WEEKLY_SUBJECT_FILTER, assert_code)
        data = _parse_stdout(proc)
        assert not data["has_p1"], \
            f"默认 Weekly 不得返回遗留物理班 p1: {data}"
        assert data["teaching_subject"] == "数学"

    def test_other_class_does_not_pollute_timeline(self, tmp_path):
        """他科班 p1 的缺交日期不得改变当前班 s1 的连续缺交日期轴。
        验证：s1 的连续缺交次数为 2（不被 p1 的记录干扰）。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/weekly-focus")
            assert r.status_code == 200, r.text
            students = {s["student_id"]: s for s in r.json().get("students", [])}
            s1 = students.get("s1", {})
            streak_reasons = [r for r in s1.get("reasons", []) if "连续缺交" in r]
            result = {"s1_has_streak_2": any("2次" in r for r in streak_reasons)}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_WEEKLY_SUBJECT_FILTER, assert_code)
        data = _parse_stdout(proc)
        assert data["s1_has_streak_2"], \
            f"s1 连续缺交应为 2 次（不被他科班 p1 干扰）: {data}"


# ── §7.5c WeeklyFocus 匿名成员在当前学科范围内仍保留 ──

_SETUP_WEEKLY_ANON_SUBJECT_FILTER = textwrap.dedent("""\
    db = SessionLocal()
    from app.db.models import (
        Teacher, TeachingClass, TeachingClassMember, Exam,
        SubjectScore, ClassRoster, HomeworkRecord, HomeworkSemester,
    )

    db.add(HomeworkSemester(name="2025秋", start_date="2025-09-01",
        end_date="2026-02-28", is_current=1))
    db.commit()

    t = Teacher(subject="数学", name="数学老师")
    db.add(t)
    db.flush()
    tc = TeachingClass(grade=2, label="数学班", subject="数学", kind="教学")
    db.add(tc)
    db.flush()
    # 真实学号成员 s1；匿名成员
    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="s1", source="manual"))
    anon_id = "_anon:%d:张某" % tc.id
    db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=anon_id, source="manual"))
    db.commit()

    for sid, name in [("s1", "学生s1"), (anon_id, "张某")]:
        db.add(ClassRoster(student_id=sid, name=name, class_num=1, excluded=0))
    # 匿名成员连续缺交 2 次
    for day in ["2025-11-01", "2025-11-02"]:
        db.add(HomeworkRecord(student_id=anon_id, date=day,
            subject="校本", submission_status="缺交"))
    db.commit()
    db.close()
""")


class TestWeeklyAnonInCurrentSubject:
    """匿名成员（当前学科教学班仅姓名占位）的缺交信号必须保留在 Weekly 中，
    且成绩排名信号不含 anon。"""

    def test_anon_retained_in_current_subject_scope(self, tmp_path):
        """当前数学教学班的匿名成员连续缺交 → 必须进入 Weekly。"""
        assert_code = textwrap.dedent("""\
            r = client.get("/api/weekly-focus")
            assert r.status_code == 200, r.text
            students = {s["student_id"]: s for s in r.json().get("students", [])}
            anon_ids = [sid for sid in students if sid.startswith("_anon:")]
            result = {"anon_count": len(anon_ids)}
            print(json.dumps(result))
        """)
        proc = _run_isolated_api_test(tmp_path, _SETUP_WEEKLY_ANON_SUBJECT_FILTER, assert_code)
        data = _parse_stdout(proc)
        assert data["anon_count"] >= 1, \
            f"当前学科匿名成员连续缺交应进入 Weekly: {data}"
