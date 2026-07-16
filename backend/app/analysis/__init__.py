# 阶段7：focus_list / cross_year / class_compare 三个空壳遗留模块已彻底删除
# （无生产调用方，仅早期抽象）。生产口径由 router.py / chat/tools.py 实时计算。
# trends.py 暂留：chat/tools.py 仍调用 compute_student_trend（旧 chat baseline，
# 本卡不改 chat），待阶段6 chat 合并后一并清理。
from app.analysis.trends import compute_student_trend
from app.analysis.router import router as analysis_router
