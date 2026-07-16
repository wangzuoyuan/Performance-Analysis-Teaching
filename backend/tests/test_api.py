"""成绩分析WebApp测试套件

测试策略：
- API测试：验证端点可访问且返回正确JSON结构（使用真实~/.exam-tracker/db.sqlite）
- DB测试：验证ORM模型可写入和查询（使用真实数据库）

注意：考试端点在阶段2单学科化后要求教师已配置 subject 且有有成员的教学班。
考试相关测试通过 _seed_minimal_exam_scope 自建自删最小教学范围，
保证在全新临时 EXAM_TRACKER_DIR 下也能确定性通过（不依赖共享库状态、不 skip）。
其他端点（health/teacher/uploads 等）不依赖教学范围。
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)


from tests.conftest import seed_minimal_exam_scope as _seed_minimal_exam_scope


# === API 测试 ===

def test_health(client):
    """Step 6: 健康检查端点"""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "成绩追踪" in response.json()["message"]

def test_teacher_get(client):
    """Step 6: 获取班主任信息"""
    response = client.get("/api/teacher")
    assert response.status_code == 200
    data = response.json()
    assert "target_class_high1" in data or "id" in data

def test_bind_class(client):
    """Step 6: 绑定班级"""
    response = client.post("/api/teacher/bind-class", json={"class_num": 6, "grade": 1})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_list_exams(client, request):
    """Step 6: 列出考试（单学科化后需要教师 subject + 教学班成员）。

    自建最小教学范围（教师学科 + 教学班 + 考试 + 数学成绩），request.addfinalizer 测后清理，
    保证在全新临时 EXAM_TRACKER_DIR 下也能确定性通过。
    """
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    response = client.get("/api/exams")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "exams" in body
    assert body.get("subject") is not None


def test_chat_config_endpoint(client):
    response = client.get("/api/chat/config")
    assert response.status_code == 200
    data = response.json()
    assert {"provider", "model", "configured", "base_url_configured"} <= set(data)
    assert "api_key" not in data


def test_exam_not_found(client, request):
    """Step 6: 考试不存在返回404（单学科化后需先有教学范围）。"""
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1"])
    request.addfinalizer(cleanup)
    response = client.get("/api/exams/99999")
    assert response.status_code == 404


def test_exam_detail_includes_dashboard_payload(client, request):
    """考试详情返回单学科化后的统计、学生明细和分数段字段。

    学生对象携带 raw_score / grade_score / grade_percentile / rank，
    不再携带 total_scores / total_score / grade_rank / subject_scores 多科字典。
    """
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    exams_response = client.get("/api/exams")
    assert exams_response.status_code == 200
    exams = exams_response.json()["exams"]
    assert exams, "seeding 后应有至少一场考试"

    response = client.get(f"/api/exams/{exams[0]['id']}")
    assert response.status_code == 200
    data = response.json()

    # 单学科统计：avg/max/min/rank_min/rank_max（不再有 by_total_type / avg_main_total）
    assert {"total_students", "avg", "max", "min", "rank_min", "rank_max"} <= set(data["stats"])
    assert "by_total_type" not in data["stats"]
    assert "avg_main_total" not in data["stats"]
    assert isinstance(data["students"], list)
    assert isinstance(data["rank_bands"], list)
    if data["students"]:
        student = data["students"][0]
        assert {
            "student_id",
            "name",
            "xueji",
            "raw_score",
            "grade_score",
            "grade_percentile",
            "rank",
        } <= set(student)
        # 单学科化：不再有这些多科/总分字段
        assert "subject_scores" not in student
        assert "total_scores" not in student
        assert "total_score" not in student
        assert "grade_rank" not in student


def test_focus_list(client, request):
    """重点关注名单（单学科化后需教师 subject + 教学班成员，自建自删隔离范围）。"""
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    exams_response = client.get("/api/exams")
    assert exams_response.status_code == 200
    exams = exams_response.json()["exams"]
    assert exams, "seeding 后应有至少一场考试"
    response = client.get(f"/api/focus-list/{exams[0]['id']}")
    assert response.status_code == 200
    assert "focus_list" in response.json()

def test_class_compare(client, request):
    """Step 6: 班级对比（单学科化后需教师 subject + 教学班成员，自建自删隔离范围）。"""
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    response = client.get("/api/class/compare")
    assert response.status_code == 200
    assert "exams" in response.json()

def test_student_not_found(tmp_path):
    """学生不在教学范围内返回 404（隔离临时 DB，不依赖共享库）。"""
    import json, os, subprocess, sys, textwrap

    setup = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import Teacher, TeachingClass, TeachingClassMember
        t = Teacher(subject="数学", name="数学老师")
        db.add(t)
        db.flush()
        tc = TeachingClass(grade=2, label="api班", subject="数学", kind="教学")
        db.add(tc)
        db.flush()
        db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="tapi-s1", source="manual"))
        db.commit()
        db.close()
    """)
    assert_code = textwrap.dedent("""\
        r = client.get("/api/students/NOTEXIST123")
        print(json.dumps({"status_code": r.status_code}))
    """)
    _api_script = textwrap.dedent("""\
        import json, os, sys
        from fastapi.testclient import TestClient
        from app.main import app
        from app.db.models import SessionLocal
        client = TestClient(app)
        with open(sys.argv[1]) as f:
            exec(f.read())
        with open(sys.argv[2]) as f:
            exec(f.read())
        sys.stdout.flush()
        os._exit(0)
    """)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sf, af = tmp_path / "s.py", tmp_path / "a.py"
    sf.write_text(setup)
    af.write_text(assert_code)
    env = os.environ.copy()
    env["EXAM_TRACKER_DIR"] = str(data_dir)
    env["EXAM_TRACKER_BACKUP_DIR"] = str(tmp_path / "bk")
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(os.path.dirname(sys.executable), "python")
    if not os.path.exists(venv_python):
        venv_python = sys.executable
    proc = subprocess.run(
        [venv_python, "-c", _api_script, str(sf), str(af)],
        cwd=backend_dir, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False,
    )
    assert proc.returncode == 0, f"子进程失败:\n{proc.stdout}"
    result = json.loads(proc.stdout.strip().split("\n")[-1])
    assert result["status_code"] == 404

def test_student_detail_returns_single_subject_trend(tmp_path):
    """学生画像返回 teaching_subject 和单一 score_trend（隔离临时 DB）。"""
    import json, os, subprocess, sys, textwrap

    setup = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import (
            Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
        )
        t = Teacher(subject="数学", name="数学老师")
        db.add(t)
        db.flush()
        tc = TeachingClass(grade=2, label="api班", subject="数学", kind="教学")
        db.add(tc)
        db.flush()
        for sid in ["tapi-s1", "tapi-s2"]:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=sid, source="manual"))
        db.commit()
        exam = Exam(name="tapi考试", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
        db.add(exam)
        db.flush()
        db.add(SubjectScore(exam_id=exam.id, student_id="tapi-s1", subject="数学",
            raw_score=85, name="测试1", class_num=1))
        db.add(SubjectScore(exam_id=exam.id, student_id="tapi-s2", subject="数学",
            raw_score=90, name="测试2", class_num=1))
        db.commit()
        db.close()
    """)
    assert_code = textwrap.dedent("""\
        r = client.get("/api/students/tapi-s1")
        assert r.status_code == 200, r.text
        data = r.json()
        subjects = {p["subject"] for p in data["score_trend"]} if data["score_trend"] else set()
        result = {
            "teaching_subject": data["teaching_subject"],
            "has_score_trend": "score_trend" in data,
            "has_subject_trend": "subject_trend" in data,
            "has_five_trend": "five_trend" in data,
            "has_main_total_trend": "main_total_trend" in data,
            "subjects": sorted(subjects),
        }
        print(json.dumps(result))
    """)
    _api_script = textwrap.dedent("""\
        import json, os, sys
        from fastapi.testclient import TestClient
        from app.main import app
        from app.db.models import SessionLocal
        client = TestClient(app)
        with open(sys.argv[1]) as f:
            exec(f.read())
        with open(sys.argv[2]) as f:
            exec(f.read())
        sys.stdout.flush()
        os._exit(0)
    """)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sf, af = tmp_path / "s.py", tmp_path / "a.py"
    sf.write_text(setup)
    af.write_text(assert_code)
    env = os.environ.copy()
    env["EXAM_TRACKER_DIR"] = str(data_dir)
    env["EXAM_TRACKER_BACKUP_DIR"] = str(tmp_path / "bk")
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(os.path.dirname(sys.executable), "python")
    if not os.path.exists(venv_python):
        venv_python = sys.executable
    proc = subprocess.run(
        [venv_python, "-c", _api_script, str(sf), str(af)],
        cwd=backend_dir, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False,
    )
    assert proc.returncode == 0, f"子进程失败:\n{proc.stdout}"
    result = json.loads(proc.stdout.strip().split("\n")[-1])
    assert result["teaching_subject"] == "数学"
    assert result["has_score_trend"] is True
    assert result["has_subject_trend"] is False
    assert result["has_five_trend"] is False
    assert result["has_main_total_trend"] is False
    if result["subjects"]:
        assert result["subjects"] == ["数学"]

def test_student_detail_excludes_empty_score_rows(tmp_path):
    """空分行不进入 score_trend（隔离临时 DB）。"""
    import json, os, subprocess, sys, textwrap

    setup = textwrap.dedent("""\
        db = SessionLocal()
        from app.db.models import (
            Teacher, TeachingClass, TeachingClassMember, Exam, SubjectScore,
        )
        t = Teacher(subject="数学", name="数学老师")
        db.add(t)
        db.flush()
        tc = TeachingClass(grade=2, label="api班", subject="数学", kind="教学")
        db.add(tc)
        db.flush()
        db.add(TeachingClassMember(teaching_class_id=tc.id, student_id="tapi-s1", source="manual"))
        db.commit()
        exam = Exam(name="tapi考试", grade=2, semester="上", exam_type="月考", exam_date="2025-11")
        db.add(exam)
        db.flush()
        db.add(SubjectScore(exam_id=exam.id, student_id="tapi-s1", subject="数学",
            raw_score=85, name="测试1", class_num=1))
        exam2 = Exam(name="残留考试", grade=2, semester="上", exam_type="月考", exam_date="2025-08")
        db.add(exam2)
        db.flush()
        db.add(SubjectScore(exam_id=exam2.id, student_id="tapi-s1", subject="数学",
            raw_score=None, grade_score=None, grade_percentile=0.5,
            name="测试1", class_num=1))
        db.commit()
        db.close()
    """)
    assert_code = textwrap.dedent("""\
        r = client.get("/api/students/tapi-s1")
        assert r.status_code == 200, r.text
        trend = r.json()["score_trend"]
        exam_names = [p["exam_name"] for p in trend]
        print(json.dumps({"exam_names": exam_names}))
    """)
    _api_script = textwrap.dedent("""\
        import json, os, sys
        from fastapi.testclient import TestClient
        from app.main import app
        from app.db.models import SessionLocal
        client = TestClient(app)
        with open(sys.argv[1]) as f:
            exec(f.read())
        with open(sys.argv[2]) as f:
            exec(f.read())
        sys.stdout.flush()
        os._exit(0)
    """)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sf, af = tmp_path / "s.py", tmp_path / "a.py"
    sf.write_text(setup)
    af.write_text(assert_code)
    env = os.environ.copy()
    env["EXAM_TRACKER_DIR"] = str(data_dir)
    env["EXAM_TRACKER_BACKUP_DIR"] = str(tmp_path / "bk")
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(os.path.dirname(sys.executable), "python")
    if not os.path.exists(venv_python):
        venv_python = sys.executable
    proc = subprocess.run(
        [venv_python, "-c", _api_script, str(sf), str(af)],
        cwd=backend_dir, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False,
    )
    assert proc.returncode == 0, f"子进程失败:\n{proc.stdout}"
    result = json.loads(proc.stdout.strip().split("\n")[-1])
    assert "残留考试" not in result["exam_names"], "空分行不应进入 score_trend"

def test_subject_weakness(client, request):
    """单科薄弱（单学科化后需教师 subject + 教学班成员，自建自删隔离范围）。"""
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    exams_response = client.get("/api/exams")
    assert exams_response.status_code == 200
    exams = exams_response.json()["exams"]
    assert exams
    response = client.get(f"/api/subject-weakness/{exams[0]['id']}")
    assert response.status_code == 200
    assert "subject_weakness" in response.json()


def test_rank_metrics_options(client, request):
    """rank-metrics 单学科化后只返回当前任教学科（自建自删隔离范围）。"""
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    response = client.get("/api/rank-metrics?grade=2&mode=frequency")
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    subject = data.get("teaching_subject")
    assert subject is not None
    values = [item["value"] for item in data["metrics"]]
    assert all(subject in v for v in values)
    assert not any(v.startswith("total:") for v in values)


def test_rank_range_endpoint(client, request):
    """rank-range 单学科化后只返回当前学科行（自建自删隔离范围）。"""
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    # 从 rank-metrics 获取实际学科
    metrics_resp = client.get("/api/rank-metrics?grade=2&mode=range")
    assert metrics_resp.status_code == 200
    subject = metrics_resp.json()["teaching_subject"]
    exams_response = client.get("/api/exams")
    assert exams_response.status_code == 200
    exams = exams_response.json()["exams"]
    assert exams
    exam_id = exams[0]["id"]
    response = client.get(
        f"/api/rank-range?exam_id={exam_id}&metric=subject:{subject}&rank_min=1&rank_max=9999"
    )
    assert response.status_code == 200
    data = response.json()
    assert {"teaching_subject", "metric_basis", "rows"} <= set(data)
    assert data["teaching_subject"] == subject


def test_rank_frequency_endpoint(client, request):
    """rank-frequency 单学科化后只统计当前学科（自建自删隔离范围）。"""
    cleanup = _seed_minimal_exam_scope(member_ids=["tapi-s1", "tapi-s2"])
    request.addfinalizer(cleanup)
    # 从 rank-metrics 获取实际学科
    metrics_resp = client.get("/api/rank-metrics?grade=2&mode=frequency")
    assert metrics_resp.status_code == 200
    subject = metrics_resp.json()["teaching_subject"]
    metric = metrics_resp.json()["metrics"][0]["value"]
    response = client.get(f"/api/rank-frequency?grade=2&metric={metric}&recent_count=2")
    assert response.status_code == 200
    data = response.json()
    assert {"bins", "rows", "exams"} <= set(data)
    assert data.get("teaching_subject") == subject


def test_grade_score_frequency_bins_are_exact_scores():
    """高二/高三+3等级分频次按精确等级分统计，不按分数段归并。"""
    from app.analysis.rank_metrics import GRADE_SCORE_BINS, _grade_score_bin

    assert [label for _key, label, _score, _separator in GRADE_SCORE_BINS] == [
        "70分",
        "67分",
        "64分",
        "61分",
        "58分",
        "55分",
        "52分",
        "49分",
        "46分",
        "43分",
        "40分",
    ]
    assert [score for _key, _label, score, separator in GRADE_SCORE_BINS if separator] == [67, 58, 49, 43]
    assert _grade_score_bin(67) == "g67"
    assert _grade_score_bin(66) is None


def test_ingest_uploads_get(client):
    """Step 6: 上传列表"""
    response = client.get("/api/uploads")
    assert response.status_code == 200
    assert "uploads" in response.json()
