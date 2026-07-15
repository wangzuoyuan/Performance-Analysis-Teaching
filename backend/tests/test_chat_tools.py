import pytest

from app.chat.tools import (
    TOOL_FUNCTIONS,
    custom_rank_band_trend,
    multi_exam_progress_ranking,
    rank_frequency_stat_tool,
    rank_range_filter_tool,
    student_learning_profile,
    subject_progress_ranking,
)


def test_subject_progress_ranking_registered():
    assert TOOL_FUNCTIONS["subject_progress_ranking"] is subject_progress_ranking
    assert TOOL_FUNCTIONS["student_learning_profile"] is student_learning_profile
    assert TOOL_FUNCTIONS["multi_exam_progress_ranking"] is multi_exam_progress_ranking
    assert TOOL_FUNCTIONS["custom_rank_band_trend"] is custom_rank_band_trend
    assert TOOL_FUNCTIONS["rank_range_filter"] is rank_range_filter_tool
    assert TOOL_FUNCTIONS["rank_frequency_stat"] is rank_frequency_stat_tool


def test_subject_progress_ranking_no_subject_param():
    """阶段6A：subject_progress_ranking 不再接受 subject 参数（固定当前任教学科）。"""
    import inspect
    sig = inspect.signature(subject_progress_ranking)
    assert "subject" not in sig.parameters, \
        "subject_progress_ranking 不应有 subject 参数"


def test_multi_exam_progress_ranking_no_metrics_param():
    """阶段6A：multi_exam_progress_ranking 不再接受 metrics 参数。"""
    import inspect
    sig = inspect.signature(multi_exam_progress_ranking)
    assert "metrics" not in sig.parameters, \
        "multi_exam_progress_ranking 不应有 metrics 参数"
