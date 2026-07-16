from app.analysis.config import (
    PROGRESS_RANK_THRESHOLD,
    VOLATILITY_RANK_THRESHOLD,
    SUBJECT_PCT_THRESHOLD,
    SUBJECT_WEAKNESS_PCT_DIFF,
    HIGH_SCORE_RANGE,
    CRITICAL_RANGE,
    WEAK_RANGE,
    TREND_LABELS,
)

# ⚠ 集成冲突项（阶段7 明确保留，待阶段6 chat 合并后删除）：
# chat/tools.py（本卡禁止修改）仍调用 compute_student_trend，该函数读取 TotalScore
# （主三门/3+3 学籍名次时间序列）。TotalScore 已退役——新上传不再写入该表——故本
# 函数对新数据始终返回「无数据」。生产单学科趋势由 analysis/router.py（学科成绩表
# + 教师任教学科）实时计算，不经过本模块。阶段6 chat 切换到单学科口径后，删除本文件
# 及 chat/tools.py 的 compute_student_trend 调用。


def compute_student_trend(student_id: str, total_type: str, exam_ids: list, db) -> dict:
    """计算学生趋势（基于名次时间序列）"""
    # 从数据库获取该生的各次考试名次
    # 必须按考试时间（grade, exam_date）排序——exam_id 是上传顺序，与时间顺序无关，
    # 否则下方 ranks[0]/ranks[-1] 取的"最早/最新"会错位，进退步判断随之出错。
    from app.db.models import TotalScore, Exam

    scores = db.query(TotalScore).join(Exam, Exam.id == TotalScore.exam_id).filter(
        TotalScore.student_id == student_id,
        TotalScore.total_type == total_type,
        TotalScore.exam_id.in_(exam_ids)
    ).order_by(Exam.grade, Exam.exam_date, Exam.id).all()

    if not scores:
        return {"trend_label": "无数据", "ranks": [], "volatility": None}

    ranks = [(s.exam_id, s.xueji_rank or s.grade_rank) for s in scores if s.xueji_rank or s.grade_rank]
    if len(ranks) < 2:
        return {"trend_label": "数据不足", "ranks": ranks, "volatility": None}

    # 计算进退步
    first_rank = ranks[0][1]
    last_rank = ranks[-1][1]
    rank_change = first_rank - last_rank  # 正数=进步

    # 波动性
    rank_values = [r[1] for r in ranks]
    avg_rank = sum(rank_values) / len(rank_values)
    variance = sum((r - avg_rank) ** 2 for r in rank_values) / len(rank_values)
    volatility = variance ** 0.5

    # 判断趋势标签
    if volatility > VOLATILITY_RANK_THRESHOLD:
        trend_label = TREND_LABELS["volatile"]
    elif rank_change >= PROGRESS_RANK_THRESHOLD:
        trend_label = TREND_LABELS["significant_progress"]
    elif rank_change <= -PROGRESS_RANK_THRESHOLD:
        trend_label = TREND_LABELS["significant_regression"]
    else:
        trend_label = TREND_LABELS["normal"]

    return {
        "trend_label": trend_label,
        "ranks": ranks,
        "rank_change": rank_change,
        "volatility": volatility,
    }