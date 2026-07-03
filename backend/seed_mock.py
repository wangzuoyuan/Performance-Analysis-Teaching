"""生成虚拟测试数据：教学班 / 花名册 / 两次考试成绩 / 作业缺交 / 特殊记录 / 谈话档案。

设计目标：让「作业模块」与其它模块（仪表盘本周关注、缺交×成绩相关性、
学生画像作业卡、教学班过滤）之间的数据流通都有真实可验证的数据。

口径要点：
- 年级共 120 人（4 个行政班，班号 1..4），我教其中 1 班、2 班（共 60 人）。
- 作业花名册 = 我教的 60 人；缺交次数与学生「能力」负相关（越弱缺交越多）。
- 学期 2026-02-17 ~ 2026-07-04，今天 2026-07-03；作业日期落在 6 月~7 月初，
  本周（06-27~07-03）留一簇以触发「本周缺交激增」。
- 段位阈值按 120 人调小，让部分学生落入临界/薄弱段，喂给本周关注的考试信号。
"""
import random
from datetime import date, timedelta

from app.db.models import (
    SessionLocal, engine, Base,
    Teacher, Exam, SubjectScore, TotalScore, ClassAverage, AnalysisConfig,
    ClassRoster, HomeworkRecord, SpecialRecord, HomeworkSemester, HomeworkSetting,
    StudentNote, TeachingClass, TeachingClassMember,
)

random.seed(20260703)
Base.metadata.create_all(bind=engine)
db = SessionLocal()

# ---------- 清库（只清本脚本涉及的表，保持幂等可重跑） ----------
for model in (TeachingClassMember, TeachingClass, StudentNote, SpecialRecord,
              HomeworkRecord, ClassRoster, HomeworkSemester, HomeworkSetting,
              ClassAverage, TotalScore, SubjectScore, Exam, AnalysisConfig, Teacher):
    db.query(model).delete()
db.commit()

SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]
SURNAMES = list("王李张刘陈杨黄赵周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢")
GIVEN = list("伟芳娜秀英敏静丽强磊军洋勇艳杰娟涛明超秀霞平刚桂香俊智浩宇轩晨欣怡博文瑞泽睿嘉宁诗璐骏行知远航")

def make_name(rng):
    return rng.choice(SURNAMES) + "".join(rng.choice(GIVEN) for _ in range(rng.choice([1, 2])))

# ---------- 学生：120 人，班号 1..4，每班 30 人 ----------
students = []  # dict: student_id, name, class_num, ability, gender
sid_counter = {}
name_rng = random.Random(1)
for cls in range(1, 5):
    for seat in range(1, 31):
        sid = f"725{cls:02d}{seat:02d}"  # 如 7250101
        ability = random.random()  # 0(弱)~1(强)
        students.append({
            "student_id": sid,
            "name": make_name(name_rng),
            "class_num": cls,
            "seat_no": seat,
            "ability": ability,
            "gender": random.choice(["男", "女"]),
        })

by_sid = {s["student_id"]: s for s in students}
my_classes = {1, 2}
my_students = [s for s in students if s["class_num"] in my_classes]

# ---------- 老师 + 教学班（行政，任教数学，1 班 / 2 班） ----------
teacher = Teacher(name="张老师", school="示例中学")
db.add(teacher)
db.flush()

tc_ids = {}
for order, cls in enumerate([1, 2]):
    tc = TeachingClass(grade=1, label=str(cls), subject="数学", kind="行政",
                       note=f"高一{cls}班（数学）", sort_order=order)
    db.add(tc)
    db.flush()
    tc_ids[cls] = tc.id
    for s in students:
        if s["class_num"] == cls:
            db.add(TeachingClassMember(teaching_class_id=tc.id, student_id=s["student_id"],
                                       source="class_num"))
teacher.current_teaching_class_id = tc_ids[1]
db.commit()

# ---------- 段位阈值（按 120 人调小，让临界/薄弱段有人） ----------
db.add(AnalysisConfig(id=1, high_score_max=20, critical_min=61, critical_max=90, weak_min=91))
db.commit()

# ---------- 两次考试 ----------
exams = [
    dict(name="高一第二学期4月月考", grade=1, semester="下", exam_type="月考", exam_date="2026-04-15"),
    dict(name="高一第二学期期中考试", grade=1, semester="下", exam_type="期中", exam_date="2026-05-20"),
]
exam_ids = []
for e in exams:
    row = Exam(**e, source_files=["mock.xlsx"])
    db.add(row)
    db.flush()
    exam_ids.append(row.id)
db.commit()

def gen_exam_scores(exam_id, drift):
    """按能力生成一次考试的分数、总分、排名、班均分。drift 让两次考试排名略有变化。"""
    # 每个学生一个「本次表现」= 能力 + 噪声 + drift
    perf = {}
    for s in students:
        perf[s["student_id"]] = s["ability"] + random.gauss(0, 0.05) + drift.get(s["student_id"], 0)
    # 主三门总分（语数英）用于学籍排名
    order = sorted(students, key=lambda s: perf[s["student_id"]], reverse=True)
    rank_of = {s["student_id"]: i + 1 for i, s in enumerate(order)}
    n = len(students)

    class_subj_sum = {c: {sub: 0.0 for sub in SUBJECTS} for c in range(1, 5)}
    class_total_sum = {c: {"主三门": 0.0, "五门": 0.0, "九门": 0.0} for c in range(1, 5)}
    class_cnt = {c: 0 for c in range(1, 5)}

    for s in students:
        sid = s["student_id"]
        p = max(0.0, min(1.0, perf[sid]))
        cls = s["class_num"]
        class_cnt[cls] += 1
        # 偏科：给个别学生某一科拉低（制造严重偏科）
        weak_subj = None
        if s["ability"] < 0.5 and random.random() < 0.25:
            weak_subj = random.choice(SUBJECTS)
        main_total = 0.0
        five_total = 0.0
        nine_total = 0.0
        for sub in SUBJECTS:
            base = 60 + p * 80  # 60~140
            score = round(base + random.gauss(0, 6), 1)
            if sub == weak_subj:
                score = round(score * 0.6, 1)
            score = max(0, min(150, score))
            # 年级百分位：按该科排名估算（这里用整体表现近似，偏科科目更差）
            pct = 1 - p
            if sub == weak_subj:
                pct = min(1.0, pct + 0.35)
            pct = round(max(0.01, min(0.99, pct + random.gauss(0, 0.03))), 4)
            db.add(SubjectScore(exam_id=exam_id, student_id=sid, class_num=cls,
                                class_label=str(cls), name=s["name"], subject=sub,
                                raw_score=score, grade_score=None, grade_percentile=pct))
            class_subj_sum[cls][sub] += score
            nine_total += score
            if sub in ("语文", "数学", "英语"):
                main_total += score
                five_total += score
            if sub in ("物理", "化学"):
                five_total += score
        rank = rank_of[sid]
        main_pct = round(rank / n, 4)
        db.add(TotalScore(exam_id=exam_id, student_id=sid, total_type="主三门",
                          total_score=round(main_total, 1), grade_percentile=main_pct,
                          xueji_rank=rank, grade_rank=rank))
        db.add(TotalScore(exam_id=exam_id, student_id=sid, total_type="五门",
                          total_score=round(five_total, 1), grade_percentile=main_pct,
                          xueji_rank=rank, grade_rank=rank))
        db.add(TotalScore(exam_id=exam_id, student_id=sid, total_type="九门",
                          total_score=round(nine_total, 1), grade_percentile=main_pct,
                          xueji_rank=rank, grade_rank=rank))
        class_total_sum[cls]["主三门"] += main_total
        class_total_sum[cls]["五门"] += five_total
        class_total_sum[cls]["九门"] += nine_total

    for c in range(1, 5):
        cnt = class_cnt[c] or 1
        db.add(ClassAverage(
            exam_id=exam_id, class_type="平行", class_num=c, class_label=str(c),
            teacher_name="张老师" if c in my_classes else f"李老师{c}",
            subject_averages={sub: round(class_subj_sum[c][sub] / cnt, 1) for sub in SUBJECTS},
            total_averages={tt: round(class_total_sum[c][tt] / cnt, 1) for tt in ("主三门", "五门", "九门")},
        ))
    db.commit()

# 第二次考试给部分学生一点漂移，制造进步/退步
drift2 = {s["student_id"]: random.gauss(0, 0.08) for s in students}
gen_exam_scores(exam_ids[0], drift={})
gen_exam_scores(exam_ids[1], drift=drift2)

# ---------- 作业花名册（我教的 60 人） ----------
excluded_sids = {my_students[5]["student_id"], my_students[35]["student_id"]}  # 2 人排除统计
for s in my_students:
    db.add(ClassRoster(
        student_id=s["student_id"], name=s["name"], class_num=s["class_num"],
        class_label=str(s["class_num"]), seat_no=s["seat_no"], gender=s["gender"],
        excluded=1 if s["student_id"] in excluded_sids else 0,
    ))
db.commit()

# ---------- 学期配置 ----------
db.add(HomeworkSemester(name="2025学年第二学期", start_date="2026-02-17",
                        end_date="2026-07-04", is_current=1))
for k, v in (("semester_start", "2026-02-17"), ("semester_end", "2026-07-04"),
             ("semester_name", "2025学年第二学期")):
    db.add(HomeworkSetting(key=k, value=v))
db.commit()

# ---------- 作业缺交记录 ----------
# 作业布置日：6/1 起每周一三五，直到 7/3；本周(6/29,7/1,7/3)是重点。
assign_dates = []
d = date(2026, 6, 1)
end = date(2026, 7, 3)
while d <= end:
    if d.weekday() in (0, 2, 4):  # 周一三五
        assign_dates.append(d.isoformat())
    d += timedelta(days=1)

hw_subjects = ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]
hw_rng = random.Random(7)

# 每个学生的缺交概率与能力负相关
for s in my_students:
    if s["student_id"] in excluded_sids:
        continue
    miss_p = 0.05 + (1 - s["ability"]) * 0.35  # 弱生缺交概率高
    for day in assign_dates:
        # 本周加权，制造激增
        boost = 1.6 if day >= "2026-06-27" else 1.0
        for sub in hw_subjects:
            if hw_rng.random() < miss_p * boost / 3:
                db.add(HomeworkRecord(student_id=s["student_id"], date=day, subject=sub,
                                      content=f"{sub}作业", submission_status="缺交"))

# 指定几个学生制造「连续缺交」预警：最近几次同一科目连续缺交
recent = [dd for dd in assign_dates if dd >= "2026-06-15"]
warn_students = my_students[10:14]  # 4 个学生
for i, s in enumerate(warn_students):
    if s["student_id"] in excluded_sids:
        continue
    subj = "数学"
    streak_len = 3 + (i % 2)  # 3 或 4 连续
    for day in recent[-streak_len:]:
        # 先删掉可能已随机生成的同日同科记录，避免重复
        db.query(HomeworkRecord).filter(
            HomeworkRecord.student_id == s["student_id"],
            HomeworkRecord.date == day, HomeworkRecord.subject == subj).delete()
        db.add(HomeworkRecord(student_id=s["student_id"], date=day, subject=subj,
                              content="数学作业", submission_status="缺交"))
db.commit()

# ---------- 特殊记录：请假 / 忘带 ----------
db.add(SpecialRecord(student_id=my_students[20]["student_id"], date="2026-07-01",
                     type="请假", note="病假"))
for day in ["2026-06-22", "2026-06-24", "2026-06-29"]:
    db.add(SpecialRecord(student_id=my_students[8]["student_id"], date=day,
                         type="忘带", note="忘带作业"))
db.commit()

# ---------- 谈话/成长档案（含未完成跟进，喂给本周关注④） ----------
note_targets = [my_students[10], my_students[2], my_students[25]]
cats = ["谈话", "家长沟通", "观察"]
for s, cat in zip(note_targets, cats):
    db.add(StudentNote(student_id=s["student_id"], date="2026-06-28", category=cat,
                       content=f"与{s['name']}就近期作业与成绩情况沟通。",
                       follow_up=f"一周后复盘{s['name']}的数学缺交情况", follow_up_done=0))
db.add(StudentNote(student_id=my_students[2]["student_id"], date="2026-05-10", category="奖惩",
                   content="月考进步表扬", follow_up=None, follow_up_done=0))
db.commit()

# ---------- 汇总输出 ----------
print("=== 虚拟数据生成完成 ===")
print(f"年级学生: {len(students)} 人（班号 1-4）")
print(f"我的教学班: 高一1班(id={tc_ids[1]}) / 高一2班(id={tc_ids[2]})，成员共 {len(my_students)} 人")
print(f"作业花名册: {len(my_students)} 人（排除统计 {len(excluded_sids)} 人）")
print(f"考试: {exam_ids}")
print(f"作业布置日: {len(assign_dates)} 天，缺交记录 {db.query(HomeworkRecord).count()} 条")
print(f"连续缺交预警对象学号: {[s['student_id']+'/'+s['name'] for s in warn_students]}")
print(f"谈话档案(未完成跟进): {[s['name'] for s in note_targets]}")
db.close()
