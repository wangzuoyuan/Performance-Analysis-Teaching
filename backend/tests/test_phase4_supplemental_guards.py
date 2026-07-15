"""Supplemental phase-4 guards discovered by independent review."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

_SCRIPT = r'''
import json, sys
from fastapi.testclient import TestClient
from app.main import app
from app.db.models import SessionLocal
ns = {"SessionLocal": SessionLocal, "json": json}
exec(open(sys.argv[1]).read(), ns)
client = TestClient(app)
ns["client"] = client
exec(open(sys.argv[2]).read(), ns)
'''


def _run(tmp_path, setup: str, assertion: str) -> dict:
    setup_file = tmp_path / "setup.py"
    assertion_file = tmp_path / "assert.py"
    setup_file.write_text(setup)
    assertion_file.write_text(assertion)
    env = os.environ.copy()
    env["EXAM_TRACKER_DIR"] = str(tmp_path / "data")
    env["EXAM_TRACKER_BACKUP_DIR"] = str(tmp_path / "backups")
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(setup_file), str(assertion_file)],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT:")]
    assert lines, proc.stdout
    return json.loads(lines[-1].removeprefix("RESULT:"))


def test_all_mode_excludes_other_subject_class_members(tmp_path):
    setup = textwrap.dedent("""\
        from app.db.models import Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore
        db=SessionLocal(); db.add(Teacher(subject="数学", name="数学老师")); db.flush()
        math=TeachingClass(grade=2,label="数学A",subject="数学",kind="教学",sort_order=0)
        phy=TeachingClass(grade=2,label="物理遗留班",subject="物理",kind="教学",sort_order=1)
        db.add_all([math,phy]); db.flush()
        db.add(TeachingClassMember(teaching_class_id=math.id,student_id="m1",source="manual"))
        db.add(TeachingClassMember(teaching_class_id=phy.id,student_id="p1",source="manual"))
        exam=Exam(name="期中",grade=2,semester="上",exam_type="期中",exam_date="2025-11")
        db.add(exam); db.flush()
        db.add_all([
          SubjectScore(exam_id=exam.id,student_id="m1",subject="数学",raw_score=90,name="M"),
          SubjectScore(exam_id=exam.id,student_id="p1",subject="数学",raw_score=80,name="P"),
        ])
        db.commit(); exam_id=exam.id; db.close()
    """)
    assertion = textwrap.dedent("""\
        r=client.get(f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&rank_min=1&rank_max=9")
        assert r.status_code==200, r.text
        b=client.get("/api/band-trend?grade=2")
        assert b.status_code==200, b.text
        print("RESULT:"+json.dumps({
          "ids":[row["student_id"] for row in r.json()["rows"]],
          "classes":[row["label"] for row in b.json()["available_classes"]],
        },ensure_ascii=False))
    """)
    data = _run(tmp_path, setup, assertion)
    assert data == {"ids": ["m1"], "classes": ["数学A"]}


def test_rank_frequency_explicit_exam_ids_cannot_cross_grade(tmp_path):
    setup = textwrap.dedent("""\
        from app.db.models import Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore
        db=SessionLocal(); db.add(Teacher(subject="数学",name="老师")); db.flush()
        tc=TeachingClass(grade=2,label="数学A",subject="数学",kind="教学")
        db.add(tc); db.flush(); db.add(TeachingClassMember(teaching_class_id=tc.id,student_id="s1",source="manual"))
        e1=Exam(name="高一旧考",grade=1,semester="上",exam_type="月考",exam_date="2024-11")
        e2=Exam(name="高二月考",grade=2,semester="上",exam_type="月考",exam_date="2025-11")
        db.add_all([e1,e2]); db.flush()
        db.add_all([
          SubjectScore(exam_id=e1.id,student_id="s1",subject="数学",raw_score=80,grade_percentile=.2),
          SubjectScore(exam_id=e2.id,student_id="s1",subject="数学",raw_score=90,grade_percentile=.1),
        ])
        db.commit(); old_id=e1.id; db.close()
    """)
    assertion = textwrap.dedent("""\
        r=client.get(f"/api/rank-frequency?grade=2&metric=subject:数学&exam_ids={old_id}")
        assert r.status_code==200, r.text
        print("RESULT:"+json.dumps({"exams":r.json()["exams"]},ensure_ascii=False))
    """)
    assert _run(tmp_path, setup, assertion)["exams"] == []


def test_exam_endpoints_reject_cross_grade_teaching_class(tmp_path):
    setup = textwrap.dedent("""\
        from app.db.models import Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore
        db=SessionLocal(); db.add(Teacher(subject="数学",name="老师")); db.flush()
        tc=TeachingClass(grade=3,label="高三数学班",subject="数学",kind="教学")
        db.add(tc); db.flush(); db.add(TeachingClassMember(teaching_class_id=tc.id,student_id="s1",source="manual"))
        exam=Exam(name="高二月考",grade=2,semester="上",exam_type="月考",exam_date="2025-11")
        db.add(exam); db.flush(); db.add(SubjectScore(exam_id=exam.id,student_id="s1",subject="数学",raw_score=90))
        db.commit(); exam_id=exam.id; tc_id=tc.id; db.close()
    """)
    assertion = textwrap.dedent("""\
        urls=[
          f"/api/rank-range?exam_id={exam_id}&metric=subject:数学&teaching_class_id={tc_id}",
          f"/api/focus-list/{exam_id}?teaching_class_id={tc_id}",
          f"/api/subject-weakness/{exam_id}?teaching_class_id={tc_id}",
        ]
        statuses=[client.get(url).status_code for url in urls]
        print("RESULT:"+json.dumps({"statuses":statuses},ensure_ascii=False))
    """)
    statuses = _run(tmp_path, setup, assertion)["statuses"]
    assert all(status in (400, 404, 409) for status in statuses), statuses


def test_metric_is_strict_for_grade_and_mode():
    from app.analysis.single_subject_metrics import expected_metric, validate_metric

    assert expected_metric("数学", 2, "range") == "subject:数学"
    assert expected_metric("数学", 2, "frequency") == "subject:数学"
    assert expected_metric("物理", 2, "frequency") == "subject_grade:物理"
    with pytest.raises(ValueError):
        validate_metric("subject_grade:数学", "数学", 2, "range")
    with pytest.raises(ValueError):
        validate_metric("subject_grade:数学", "数学", 2, "frequency")
    with pytest.raises(ValueError):
        validate_metric("subject:物理", "物理", 2, "frequency")
