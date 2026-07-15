"""兼容 wrapper 校验对齐测试（Blocker 6）。

rank_range_filter / rank_frequency_stats 必须与 HTTP 端点契约一致：
- class_num 非空报错
- total:* / 其他学科 / 不匹配模式 报错
不依赖真实数据库（monkeypatch 掉 SessionLocal / resolver）。
"""
from __future__ import annotations

import pytest

from app.analysis import rank_metrics


@pytest.fixture
def patched_no_db(monkeypatch):
    """避免 wrapper 触达真实数据库：SessionLocal 与 resolver 均 mock。"""
    from types import SimpleNamespace
    from app.analysis.single_subject_metrics import SingleSubjectContext

    fake_ctx = SingleSubjectContext(
        subject="数学",
        member_ids=frozenset(),
        explicit_class_id=None,
        member_to_default_class={},
        class_labels={},
    )

    class _FakeDB:
        def query(self, *a, **kw):
            class _Q:
                def filter(self, *a, **kw): return self
                def order_by(self, *a, **kw): return self
                def all(self): return []
                def first(self): return None
            return _Q()
        def close(self): pass

    def _fake_session():
        return _FakeDB()

    import app.db.models as models
    monkeypatch.setattr(models, "SessionLocal", _fake_session, raising=False)
    import app.analysis.single_subject_metrics as ssm
    monkeypatch.setattr(
        ssm, "resolve_single_subject_context",
        lambda *a, **kw: fake_ctx,
        raising=False,
    )


class TestRankRangeFilterValidation:
    def test_class_num_rejected(self, patched_no_db):
        with pytest.raises(ValueError, match="class_num"):
            rank_metrics.rank_range_filter(
                exam_id=1, metric="subject:数学",
                class_num=1,
            )

    def test_total_metric_rejected(self, patched_no_db):
        with pytest.raises(ValueError, match="总分指标"):
            rank_metrics.rank_range_filter(
                exam_id=1, metric="total:主三门",
            )

    def test_other_subject_metric_rejected(self, patched_no_db):
        with pytest.raises(ValueError, match="不一致"):
            rank_metrics.rank_range_filter(
                exam_id=1, metric="subject:物理",
                teaching_class_id=1,
            )

    def test_bad_format_metric_rejected(self, patched_no_db):
        with pytest.raises(ValueError, match="不支持的指标格式"):
            rank_metrics.rank_range_filter(
                exam_id=1, metric="bogus",
            )


class TestRankFrequencyStatsValidation:
    def test_class_num_rejected(self, patched_no_db):
        with pytest.raises(ValueError, match="class_num"):
            rank_metrics.rank_frequency_stats(
                grade=2, metric="subject:数学",
                class_num=1,
            )

    def test_total_metric_rejected(self, patched_no_db):
        with pytest.raises(ValueError, match="总分指标"):
            rank_metrics.rank_frequency_stats(
                grade=2, metric="total:主三门",
            )

    def test_grade_score_wrong_subject_rejected(self, patched_no_db):
        with pytest.raises(ValueError, match="不一致"):
            rank_metrics.rank_frequency_stats(
                grade=2, metric="subject_grade:化学",
                teaching_class_id=1,
            )
