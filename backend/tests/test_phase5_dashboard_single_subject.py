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
