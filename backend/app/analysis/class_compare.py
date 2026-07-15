"""[遗留兼容] 班级横向对比计算（早期抽象，当前无生产调用方）。

单学科化（阶段7）：原实现查询班级均分表的总分字段 / 多学科均分并 join
总分表。总分表已退役，生产班级对比由 analysis/router.py 的单学科口径
（教师任教学科成绩表实时聚合）计算。本模块保留函数签名以兼容旧的测试
级联引用，但不再查询总分表。
"""
from sqlalchemy import func


def compute_class_compare(exam_id: int, class_num: int, db) -> dict:
    """[遗留] 计算本班 vs 平行班均分对比。

    原实现依赖总分表与多学科班级均分。总分表已退役，生产班级对比请使用
    analysis/router.py 的单学科成绩表实时聚合。本函数仅返回最小结构
    （不查总分表）。
    """
    from app.db.models import ClassAverage, SubjectScore

    subject_avgs = (
        db.query(
            SubjectScore.subject,
            func.avg(SubjectScore.raw_score).label("avg"),
        )
        .filter(
            SubjectScore.exam_id == exam_id,
            SubjectScore.class_num == class_num,
        )
        .group_by(SubjectScore.subject)
        .all()
    )

    parallel_avgs = (
        db.query(ClassAverage)
        .filter(
            ClassAverage.exam_id == exam_id,
            ClassAverage.class_num != class_num,
        )
        .all()
    )

    return {
        "class_num": class_num,
        "subject_avgs": {s.subject: s.avg for s in subject_avgs},
        "parallel_classes": [
            {"class_num": p.class_num, "subject_averages": p.subject_averages}
            for p in parallel_avgs
        ],
    }
