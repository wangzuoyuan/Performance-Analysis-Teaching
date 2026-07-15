"""_competition_rank_from_rows 单元测试（不依赖 DB，快速直接调用）。

覆盖 6 个 blocker 中正确名次算法的核心逻辑：
- 百分位方向（越小越好 → rank 越小）
- 统一量纲（同一池禁止混用 percentile/raw/grade_score）
- 高二选考用 grade_score 降序
- competition tie + 跳号
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.analysis.single_subject_metrics import (
    _competition_rank_from_rows,
    percentile_to_rank,
)


def _row(student_id, *, raw_score=None, grade_score=None, grade_percentile=None):
    """构造一个最小 mock 行，模拟 SubjectScore 的必要属性。"""
    return SimpleNamespace(
        student_id=student_id,
        raw_score=raw_score,
        grade_score=grade_score,
        grade_percentile=grade_percentile,
    )


class TestPercentileDirection:
    """Blocker 1：百分位越小越好，rank 越小。"""

    def test_low_percentile_ranks_first_01_vs_09(self):
        rows = [
            _row("a", raw_score=90, grade_percentile=0.1),
            _row("b", raw_score=10, grade_percentile=0.9),
        ]
        ranks = _competition_rank_from_rows(rows, "数学", exam_grade=1)
        assert ranks["a"] == 1, f"百分位 0.1 应排第1: {ranks}"
        assert ranks["b"] == 2, f"百分位 0.9 应排第2: {ranks}"

    def test_low_percentile_ranks_first_10_vs_90(self):
        """0..100 刻度：10 应优于 90。"""
        rows = [
            _row("a", raw_score=90, grade_percentile=10.0),
            _row("b", raw_score=10, grade_percentile=90.0),
        ]
        ranks = _competition_rank_from_rows(rows, "数学", exam_grade=1)
        assert ranks["a"] == 1, f"百分位 10 应排第1: {ranks}"
        assert ranks["b"] == 2, f"百分位 90 应排第2: {ranks}"


class TestMixedBasisForbidden:
    """Blocker 2：同一排名池严禁混用 percentile/raw_score/grade_score。

    当池中存在缺 percentile 的行时，整个池统一用 raw_score 降序，
    不能让有 percentile 的行走 percentile、缺的行走 raw。
    """

    def test_pool_falls_back_to_raw_when_any_missing_percentile(self):
        """pct学生(percentile=0.1, raw=90) 与 fallback学生(percentile=None, raw=80)
        混在同一池时，必须统一用 raw_score 降序 → 90 rank1, 80 rank2。
        绝不能把 0.1 当成排序值与 80 比较。"""
        rows = [
            _row("pct", raw_score=90, grade_percentile=0.1),
            _row("fallback", raw_score=80, grade_percentile=None),
        ]
        ranks = _competition_rank_from_rows(rows, "数学", exam_grade=1)
        assert ranks["pct"] == 1, f"raw=90 应 rank1: {ranks}"
        assert ranks["fallback"] == 2, f"raw=80 应 rank2: {ranks}"

    def test_all_percentile_present_uses_percentile_ascending(self):
        """全部行都有 percentile 时按 percentile 升序（越小越好）。"""
        rows = [
            _row("a", raw_score=90, grade_percentile=0.3),
            _row("b", raw_score=80, grade_percentile=0.1),
        ]
        ranks = _competition_rank_from_rows(rows, "数学", exam_grade=1)
        assert ranks["b"] == 1, f"百分位 0.1 应 rank1: {ranks}"
        assert ranks["a"] == 2, f"百分位 0.3 应 rank2: {ranks}"


class TestElectiveGradeScore:
    """Blocker：高二/高三选考学科统一用 grade_score 降序。"""

    def test_grade_score_descending(self):
        rows = [
            _row("a", raw_score=95, grade_score=70, grade_percentile=0.05),
            _row("b", raw_score=85, grade_score=67, grade_percentile=0.15),
        ]
        ranks = _competition_rank_from_rows(rows, "物理", exam_grade=2)
        assert ranks["a"] == 1, f"grade_score 70 应 rank1: {ranks}"
        assert ranks["b"] == 2, f"grade_score 67 应 rank2: {ranks}"

    def test_raw_score_reversed_does_not_affect(self):
        """raw_score 反向设置也不影响 grade_score 排名。"""
        rows = [
            _row("a", raw_score=50, grade_score=70),
            _row("b", raw_score=99, grade_score=67),
        ]
        ranks = _competition_rank_from_rows(rows, "物理", exam_grade=2)
        assert ranks["a"] == 1, f"grade_score 70 应 rank1: {ranks}"
        assert ranks["b"] == 2, f"grade_score 67 应 rank2: {ranks}"

    def test_grade_score_only_can_rank(self):
        """仅 grade_score 有值也可排名（raw 为 None）。"""
        rows = [
            _row("a", grade_score=70),
            _row("b", grade_score=64),
        ]
        ranks = _competition_rank_from_rows(rows, "化学", exam_grade=3)
        assert ranks["a"] == 1
        assert ranks["b"] == 2


class TestCompetitionTie:
    """同分同名次 + 后续跳号。"""

    def test_tie_then_skip(self):
        rows = [
            _row("a", raw_score=90),
            _row("b", raw_score=90),
            _row("c", raw_score=80),
        ]
        ranks = _competition_rank_from_rows(rows, "数学", exam_grade=1)
        assert ranks["a"] == 1
        assert ranks["b"] == 1
        assert ranks["c"] == 3, f"同分2人后应跳到 rank3: {ranks}"

    def test_all_same_score(self):
        rows = [
            _row("a", raw_score=90),
            _row("b", raw_score=90),
            _row("c", raw_score=90),
        ]
        ranks = _competition_rank_from_rows(rows, "数学", exam_grade=1)
        assert ranks["a"] == 1
        assert ranks["b"] == 1
        assert ranks["c"] == 1


class TestPercentileToRank:
    def test_lower_percentile_maps_to_better_rank(self):
        assert percentile_to_rank(0.1, 100) == 10
        assert percentile_to_rank(0.9, 100) == 90
        assert percentile_to_rank(10, 100) == 10


class TestRawMissingGetsNullRank:
    """缺 raw_score 的行在统一 raw 池中 rank=null（不参与排名）。"""

    def test_none_raw_excluded_from_raw_pool(self):
        rows = [
            _row("a", raw_score=90),
            _row("b", raw_score=None),
        ]
        ranks = _competition_rank_from_rows(rows, "数学", exam_grade=1)
        assert ranks["a"] == 1
        assert "b" not in ranks, f"raw=None 不应参与排名: {ranks}"
