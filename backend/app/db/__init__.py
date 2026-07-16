# TotalScore 为 LEGACY 兼容导出（阶段7退役）：仅旧库启动、备份/恢复与
# 删除考试级联清理使用。生产业务不得新增依赖。
from app.db.models import get_db, Teacher, Exam, Upload, SubjectScore, TotalScore, ClassAverage, Base, engine  # noqa