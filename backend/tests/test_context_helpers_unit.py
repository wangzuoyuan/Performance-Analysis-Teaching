"""SingleSubjectContext 扩展 + 统一 label/rank helper 单元测试（无 DB）。

覆盖 Blocker 3（显式班 class_label 优先）、Blocker 5（全部模式按班分别排名）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.analysis.single_subject_metrics import (
    SingleSubjectContext,
    label_for_student,
    group_members_by_class,
    compute_rank_multi_class,
    _competition_rank_from_rows,
)


def _row(student_id, *, raw_score=None, grade_score=None, grade_percentile=None):
    return SimpleNamespace(
        student_id=student_id,
        raw_score=raw_score,
        grade_score=grade_score,
        grade_percentile=grade_percentile,
    )


class TestLabelOverride:
    """Blocker 3：显式教学班强制 class_label 为该班。"""

    def test_explicit_class_overrides_default(self):
        """学生 x 同属 A/B，默认班(sort_order 最前)=A。
        显式 teaching_class_id=B 时，label_for_student 必须返回 B 的 label。"""
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["x", "y"]),
            explicit_class_id=20,
            member_to_default_class={"x": 10, "y": 10},  # 默认 A(id=10)
            class_labels={10: "A班", 20: "B班"},
        )
        assert label_for_student(ctx, "x") == "B班", \
            "显式 B 班时 x 的 label 必须为 B班"

    def test_no_explicit_class_uses_default(self):
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["x"]),
            explicit_class_id=None,
            member_to_default_class={"x": 10},
            class_labels={10: "A班", 20: "B班"},
        )
        assert label_for_student(ctx, "x") == "A班"

    def test_explicit_class_id_returned(self):
        """label_for_student 同时返回 teaching_class_id，供端点写回响应。"""
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["x"]),
            explicit_class_id=20,
            member_to_default_class={"x": 10},
            class_labels={10: "A班", 20: "B班"},
        )
        label, tc_id = label_for_student(ctx, "x", return_tc_id=True)
        assert label == "B班"
        assert tc_id == 20


class TestGroupByClass:
    """Blocker 5：全部模式按教学班分组。"""

    def test_group_members_by_class(self):
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["s1", "s2", "s3", "s4"]),
            explicit_class_id=None,
            member_to_default_class={"s1": 10, "s2": 10, "s3": 20, "s4": 20},
            class_labels={10: "A班", 20: "B班"},
        )
        groups = group_members_by_class(ctx)
        assert set(groups.keys()) == {10, 20}
        assert groups[10] == {"s1", "s2"}
        assert groups[20] == {"s3", "s4"}

    def test_explicit_class_single_group(self):
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["s1", "s2"]),
            explicit_class_id=10,
            member_to_default_class={"s1": 10, "s2": 10},
            class_labels={10: "A班"},
        )
        groups = group_members_by_class(ctx)
        assert set(groups.keys()) == {10}
        assert groups[10] == {"s1", "s2"}


class TestRankMultiClass:
    """Blocker 5：全部模式每班独立排名，不合并池。"""

    def test_each_class_starts_from_rank1(self):
        """A: s1(90),s2(80)  B: s3(70),s4(60) → A 内部 rank1/2，B 内部 rank1/2，
        不能合并成 90→1,80→2,70→3,60→4。"""
        rows_by_sid = {
            "s1": _row("s1", raw_score=90),
            "s2": _row("s2", raw_score=80),
            "s3": _row("s3", raw_score=70),
            "s4": _row("s4", raw_score=60),
        }
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["s1", "s2", "s3", "s4"]),
            explicit_class_id=None,
            member_to_default_class={"s1": 10, "s2": 10, "s3": 20, "s4": 20},
            class_labels={10: "A班", 20: "B班"},
        )
        ranks = compute_rank_multi_class(ctx, rows_by_sid, exam_grade=2)
        # A 班
        assert ranks["s1"] == 1
        assert ranks["s2"] == 2
        # B 班独立从 rank1 开始
        assert ranks["s3"] == 1, f"B班最高分应 rank1（不合并池）: {ranks}"
        assert ranks["s4"] == 2

    def test_explicit_class_ranks_only_that_class(self):
        """显式 A 班：member_ids 只含 A 班成员（resolver 已限定），B 班学生不在池中。
        实际 API 流程中 resolver 会把 member_ids 限定为显式班成员。"""
        rows_by_sid = {
            "s1": _row("s1", raw_score=90),
            "s2": _row("s2", raw_score=80),
        }
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["s1", "s2"]),  # 只有 A 班成员
            explicit_class_id=10,
            member_to_default_class={"s1": 10, "s2": 10, "s3": 20},
            class_labels={10: "A班", 20: "B班"},
        )
        ranks = compute_rank_multi_class(ctx, rows_by_sid, exam_grade=2)
        assert ranks["s1"] == 1
        assert ranks["s2"] == 2
        assert "s3" not in ranks, "B 班学生 s3 不在 member_ids 中，不应被排名"

    def test_overlapping_student_ranked_in_default_class(self):
        """重叠学生 s3 同属 A/B，默认班=A。全部模式下 s3 在 A 班内排名。"""
        rows_by_sid = {
            "s1": _row("s1", raw_score=90),
            "s2": _row("s2", raw_score=80),
            "s3": _row("s3", raw_score=70),
            "s4": _row("s4", raw_score=60),
        }
        ctx = SingleSubjectContext(
            subject="数学",
            member_ids=frozenset(["s1", "s2", "s3", "s4"]),
            explicit_class_id=None,
            member_to_default_class={"s1": 10, "s2": 10, "s3": 10, "s4": 20},
            class_labels={10: "A班", 20: "B班"},
        )
        ranks = compute_rank_multi_class(ctx, rows_by_sid, exam_grade=2)
        # s3 默认班 A → A: s1(90)=1,s2(80)=2,s3(70)=3；B: s4(60)=1
        assert ranks["s3"] == 3
        assert ranks["s4"] == 1
