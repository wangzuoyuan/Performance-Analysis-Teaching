"""教学班配置 API 回归测试（/api/teaching/*）。

测试自建自删（fixture 清理），不污染共享库。对应 03·§2 班级配置 API。
"""
import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_teacher_subject():
    """单科教学领域边界：创建教学班前需教师已配置 subject。

    旧测试通过 make_class 创建班时提交 subject（如 "物理"），现在后端要求
    教师先配置同一学科。本 fixture 在模块级设置教师 subject="物理" 并在结束后
    恢复，保证旧测试不改业务参数即可继续运行。
    """
    original = client.get("/api/teacher").json().get("subject")
    client.patch("/api/teacher", json={"subject": "物理"})
    yield
    # 恢复原状：清除 subject（避免影响其他测试模块对共享库的假设）
    from app.db.models import SessionLocal, Teacher
    db = SessionLocal()
    t = db.query(Teacher).first()
    if t:
        t.subject = original
        db.commit()
    db.close()


def _unique_label(prefix: str = "tc") -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


@pytest.fixture
def make_class():
    created: list[int] = []

    def _make(grade: int = 2, label: str | None = None, kind: str = "教学", subject: str | None = None):
        label = label or _unique_label()
        # subject 兼容：旧测试可能传 "物理"（与教师一致则通过）；None 则继承教师学科
        payload = {"grade": grade, "label": label, "kind": kind}
        if subject is not None:
            payload["subject"] = subject
        r = client.post(
            "/api/teaching/classes",
            json=payload,
        )
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
        return r.json()

    yield _make

    for tcid in created:
        client.delete(f"/api/teaching/classes/{tcid}")


def test_create_list_delete_class(make_class):
    tc = make_class(grade=2, kind="教学", subject="物理")
    assert tc["label"] and tc["id"]
    r = client.get("/api/teaching/classes?grade=2")
    ids = [c["id"] for c in r.json()["classes"]]
    assert tc["id"] in ids
    # 同年级同名应拒绝（409）
    dup = client.post("/api/teaching/classes", json={"grade": 2, "label": tc["label"], "kind": "教学"})
    assert dup.status_code == 409


def test_member_crud(make_class):
    tc = make_class()
    r = client.post(f"/api/teaching/classes/{tc['id']}/members", json={"student_ids": ["100", "101", "102"]})
    assert r.json()["added"] == 3
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert {m["student_id"] for m in members} == {"100", "101", "102"}
    # 移除单个
    client.delete(f"/api/teaching/classes/{tc['id']}/members/101")
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert {m["student_id"] for m in members} == {"100", "102"}


def test_import_states(make_class):
    tc = make_class()
    # 真实学号（≥5 位数字）→ matched；未知姓名 → name_only（仅姓名占位成员）
    r = client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100001\n7100002\n不存在姓名"},
    )
    rep = r.json()
    matched_ids = {m["student_id"] for m in rep["matched"]}
    assert "7100001" in matched_ids and "7100002" in matched_ids
    no_ids = {n["name"] for n in rep["name_only"]}
    assert "不存在姓名" in no_ids
    # 成员表里能看到这条仅姓名成员，且标记为未设学号
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    anon = [m for m in members if m["name"] == "不存在姓名"]
    assert len(anon) == 1 and anon[0]["has_student_id"] is False
    assert anon[0]["student_id"].startswith("_anon:")


def test_import_id_name_pair(make_class):
    tc = make_class()
    # 「学号 姓名」一行应成对识别，而非拆成两个 token
    r = client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100001 张三\n7100002 李四"},
    )
    rep = r.json()
    by_id = {m["student_id"]: m["name"] for m in rep["matched"]}
    assert by_id == {"7100001": "张三", "7100002": "李四"}
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert {m["student_id"]: m["name"] for m in members} == {
        "7100001": "张三",
        "7100002": "李四",
    }


def test_add_name_only(make_class):
    tc = make_class()
    # 添加成员 tab 的「按姓名」：零命中也应落为仅姓名占位
    r = client.post(
        f"/api/teaching/classes/{tc['id']}/members",
        json={"names": ["某新人"]},
    )
    assert r.json()["added"] == 1
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert any(m["name"] == "某新人" and not m["has_student_id"] for m in members)


def test_reassign_member_and_upgrade(make_class):
    tc = make_class()
    # 先按姓名导入占位成员，再补学号
    client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "王小明"},
    )
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    anon_sid = [m["student_id"] for m in members if m["name"] == "王小明"][0]
    # PATCH 改学号（URL 含冒号需编码）
    r = client.patch(
        f"/api/teaching/classes/{tc['id']}/members/{quote(anon_sid, safe='')}",
        json={"new_student_id": "7100099", "name": "王小明"},
    )
    assert r.status_code == 200, r.text
    members = r.json()["members"]
    assert any(m["student_id"] == "7100099" and m["has_student_id"] for m in members)
    assert all(not m["student_id"].startswith("_anon:") for m in members)


def test_reassign_cascades_note(make_class):
    tc = make_class()
    sid_old, sid_new = "7100088", "7100077"
    client.post(f"/api/teaching/classes/{tc['id']}/members", json={"student_ids": [sid_old]})
    # 在旧学号下写一条档案
    note = client.post(
        "/api/notes",
        json={"student_id": sid_old, "category": "谈话", "content": "旧学号下的谈话"},
    ).json()
    # 改学号
    r = client.patch(
        f"/api/teaching/classes/{tc['id']}/members/{sid_old}",
        json={"new_student_id": sid_new, "name": "测试生"},
    )
    assert r.status_code == 200, r.text
    # 档案应随学号迁移到新学号
    new_notes = client.get(f"/api/notes/{sid_new}").json()
    assert any(n["id"] == note["id"] for n in new_notes)
    old_notes = client.get(f"/api/notes/{sid_old}").json()
    assert all(n["id"] != note["id"] for n in old_notes)
    # 清理
    client.delete(f"/api/notes/{note['id']}")


def test_no_duplicate_name_only(make_class):
    tc = make_class()
    # 先「学号 姓名」导入一个有姓名的真实学号成员
    client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100001 赵六"},
    )
    # 再单独导入同名 → 不应产生 _anon:赵六 重复成员
    client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "赵六"},
    )
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert len(members) == 1
    assert members[0]["student_id"] == "7100001"
    assert members[0]["name"] == "赵六"


def test_upsert_overwrites_by_name(make_class):
    tc = make_class()
    # 先按姓名占位
    client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "李小华"},
    )
    # 覆盖模式重导「学号 姓名」→ 姓名命中占位成员，学号被改写
    r = client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100055 李小华", "upsert": True},
    )
    assert r.json()["reassigned_count"] == 1
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert len(members) == 1
    assert members[0]["student_id"] == "7100055"
    assert members[0]["name"] == "李小华"


def test_reassign_conflict_409(make_class):
    tc = make_class()
    # 两个不同姓名的学生占住两个学号
    client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100011 甲同学\n7100012 乙同学"},
    )
    # 把「甲同学」的学号改成已被「乙同学」占用的 7100012 → 409（不可并成一人）
    r = client.patch(
        f"/api/teaching/classes/{tc['id']}/members/7100011",
        json={"new_student_id": "7100012", "name": "甲同学"},
    )
    assert r.status_code == 409


def test_reassign_conflict_null_name_409(make_class):
    tc = make_class()
    # 按学号加入两个成员（尚无成绩，姓名缓存为空）
    client.post(
        f"/api/teaching/classes/{tc['id']}/members",
        json={"student_ids": ["7100021", "7100022"]},
    )
    # 即便不带 name，把 7100021 改成已占用的 7100022 也必须 409，不得静默合并
    r = client.patch(
        f"/api/teaching/classes/{tc['id']}/members/7100021",
        json={"new_student_id": "7100022"},
    )
    assert r.status_code == 409


def test_anon_reassign_does_not_leak_across_classes(make_class):
    a = make_class()
    b = make_class()
    # 两个班各有一个同名「仅姓名」成员（实际是不同的学生）
    client.post(f"/api/teaching/classes/{a['id']}/members/import", json={"text": "王某"})
    client.post(f"/api/teaching/classes/{b['id']}/members/import", json={"text": "王某"})
    # 占位学号按教学班隔离：两个同名成员是不同的占位学号，绝不共用
    anon_a = f"_anon:{a['id']}:王某"
    anon_b = f"_anon:{b['id']}:王某"
    assert anon_a != anon_b
    am = client.get(f"/api/teaching/classes/{a['id']}/members").json()["members"]
    assert am[0]["student_id"] == anon_a
    # 给 A 班的王某补学号
    r = client.patch(
        f"/api/teaching/classes/{a['id']}/members/{quote(anon_a, safe='')}",
        json={"new_student_id": "7100066", "name": "王某"},
    )
    assert r.status_code == 200, r.text
    # B 班的「仅姓名」王某必须原样保留，不能被级联污染
    bm = client.get(f"/api/teaching/classes/{b['id']}/members").json()["members"]
    assert len(bm) == 1
    assert bm[0]["student_id"] == anon_b
    assert bm[0]["has_student_id"] is False


def test_import_comma_ids_not_pair(make_class):
    tc = make_class()
    # 一行逗号分隔的多个学号：不应被误判为「学号 姓名」把第二个学号当姓名
    r = client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100001,7100002,7100003"},
    )
    matched_ids = {m["student_id"] for m in r.json()["matched"]}
    assert matched_ids == {"7100001", "7100002", "7100003"}
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert len(members) == 3
    assert {m["student_id"] for m in members} == {"7100001", "7100002", "7100003"}


def test_upsert_intra_import_same_name_conflict(make_class):
    tc = make_class()
    # 同一次导入里同名两个不同学号 → 判歧义、都不落（而不是静默覆盖丢学号）
    r = client.post(
        f"/api/teaching/classes/{tc['id']}/members/import",
        json={"text": "7100001 张三\n7100002 张三", "upsert": True},
    )
    rep = r.json()
    assert len(rep["ambiguous"]) == 1
    assert rep["ambiguous"][0]["name"] == "张三"
    members = client.get(f"/api/teaching/classes/{tc['id']}/members").json()["members"]
    assert members == []


def test_current_set_get_clear(make_class):
    tc = make_class()
    client.patch("/api/teaching/current", json={"teaching_class_id": tc["id"]})
    cur = client.get("/api/teaching/current").json()
    assert cur["teaching_class_id"] == tc["id"]
    assert cur["class"]["label"] == tc["label"]
    client.patch("/api/teaching/current", json={"teaching_class_id": None})
    assert client.get("/api/teaching/current").json()["teaching_class_id"] is None


def test_candidate_classes_ok():
    r = client.get("/api/teaching/candidate-classes?grade=2")
    assert r.status_code == 200
    body = r.json()
    assert "class_nums" in body and "class_labels" in body


def test_sync_by_class_num_requires_admin(make_class):
    # 教学班（非行政）按行政班号同步应 400
    tc = make_class(grade=2, kind="教学")
    r = client.post(f"/api/teaching/classes/{tc['id']}/sync-by-class-num")
    assert r.status_code == 400
