"""scope 解析 + 跨学年身份层回归测试（analysis/scope.py）。

对应 03·§1 范围解析 与 06·§4 身份解析。自建自删。
"""
import pytest

from app.analysis import scope
from app.db.models import (
    SessionLocal,
    StudentAlias,
    StudentIdentity,
    TeachingClass,
    TeachingClassMember,
)


@pytest.fixture
def make_class_with_members():
    created: list[int] = []

    def _make(label: str, sids: list[str], grade: int = 2):
        db = SessionLocal()
        tc = TeachingClass(grade=grade, label=label, kind="教学")
        db.add(tc)
        db.flush()
        for s in sids:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=s, source="manual"))
        db.commit()
        tcid = tc.id
        db.close()
        created.append(tcid)
        return tcid

    yield _make

    db = SessionLocal()
    for tcid in created:
        db.query(TeachingClassMember).filter(TeachingClassMember.teaching_class_id == tcid).delete(
            synchronize_session=False
        )
        db.query(TeachingClass).filter(TeachingClass.id == tcid).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_members_of_and_resolve(make_class_with_members):
    tcid = make_class_with_members("scope-A", ["s1", "s2", "s3"])
    db = SessionLocal()
    try:
        assert scope.members_of(db, tcid) == {"s1", "s2", "s3"}
        assert scope.resolve_scope(db, teaching_class_id=tcid) == {"s1", "s2", "s3"}
        # None = 不限定（全年级）
        assert scope.resolve_scope(db, teaching_class_id=None) is None
    finally:
        db.close()


def test_student_class_map(make_class_with_members):
    tcid = make_class_with_members("scope-B", ["s9"])
    db = SessionLocal()
    try:
        m = scope.student_class_map(db, 2)
        assert m.get("s9") == ("scope-B", tcid)
    finally:
        db.close()


def test_identity_no_alias_returns_self():
    """无 alias 的学号视为独立单人，零配置可用。"""
    db = SessionLocal()
    try:
        assert scope.identity_of(db, "ghost-id-xyz") is None
        assert scope.student_ids_of_person(db, "ghost-id-xyz") == {"ghost-id-xyz"}
    finally:
        db.close()


def test_identity_link_and_union_then_unlink():
    """人工确认建链 → 跨学号并集 → 解除链接还原独立人。"""
    db = SessionLocal()
    ident_id = None
    try:
        ident = StudentIdentity(display_name="X")
        db.add(ident)
        db.flush()
        ident_id = ident.id
        scope.link_aliases(db, ident_id, ["la", "lb"], "name_confirmed")
        db.commit()
        assert scope.student_ids_of_person(db, "la") == {"la", "lb"}
        assert scope.identity_of(db, "lb") == ident_id
        # 解除 la 的链接
        assert scope.unlink_alias(db, "la") is True
        db.commit()
        assert scope.identity_of(db, "la") is None
        assert scope.student_ids_of_person(db, "la") == {"la"}
        # lb 仍属于该人
        assert scope.identity_of(db, "lb") == ident_id
    finally:
        db.query(StudentAlias).filter(StudentAlias.identity_id == ident_id).delete(
            synchronize_session=False
        )
        db.query(StudentIdentity).filter(StudentIdentity.id == ident_id).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()
