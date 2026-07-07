"""作业录入文本解析与作业种类归类。

从原「按学科」作业跟踪演进为任课老师单学科场景：不再要求记录学科，
而是归类校本作业、周末作业、试卷订正等作业种类。
"""

import re

# 作业种类归类表：原始文本含任一关键词即归到对应规范种类名。
# 数据库仍沿用旧列名 subject，存入的业务含义改为“作业种类”。
SUBJECT_GROUPS = [
    ("校本作业", ["校本", "校本作业"]),
    ("周末作业", ["周末", "双休", "假期作业"]),
    ("试卷订正", ["试卷订正", "订正", "错题", "纠错"]),
    ("练习册", ["练习册", "作业本"]),
    ("课堂练习", ["课堂练习", "随堂", "当堂"]),
    ("预习作业", ["预习"]),
    ("背诵默写", ["背诵", "默写"]),
    ("全科", ["全科"]),
]

ACADEMIC_SUBJECT_HINTS = (
    "语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理",
    "政治", "道法", "道德与法治",
)
DEFAULT_HOMEWORK_TYPE = "日常作业"

# 录入文本里「学生/作业种类 : 列表」的分隔符
NAME_SPLIT_RE = re.compile(r"[，,；;、\s]+")
COLON_SPLIT_RE = re.compile(r"[:：]")


def normalize_subject(value):
    """把原始作业种类文本归一化到规范种类名；识别不到则原样返回。"""
    if not value:
        return "未分类"

    normalized = str(value).strip().replace(" ", "")
    if not normalized:
        return "未分类"

    for canonical_name, keywords in SUBJECT_GROUPS:
        if any(keyword in normalized for keyword in keywords):
            return canonical_name

    if any(keyword in normalized for keyword in ACADEMIC_SUBJECT_HINTS):
        return DEFAULT_HOMEWORK_TYPE

    return normalized


def parse_homework_item(item):
    """解析单个作业项，返回 (assignment_type, content, remark)。

    - '请假'     → ('全科', None, '请假')
    - '校本作业' → ('校本作业', None, None)
    - '数学订正' → ('试卷订正', '数学订正', None)
    - '数学'     → ('日常作业', '数学', None)
    无法识别种类时，原样作为种类名返回。
    """
    item = item.strip()
    if not item:
        return None

    if item == "请假":
        return ("全科", None, "请假")

    for canonical_name, keywords in SUBJECT_GROUPS:
        for keyword in keywords:
            if keyword in item:
                content = item if item not in (canonical_name, keyword) else None
                return (canonical_name, content, None)

    if any(keyword in item for keyword in ACADEMIC_SUBJECT_HINTS):
        return (DEFAULT_HOMEWORK_TYPE, item, None)

    return (item, None, None)


def is_subject_item(item):
    """item 是否包含可识别的作业种类关键词（用于区分缺交 vs 特殊情况）。"""
    item = item.strip()
    for _, keywords in SUBJECT_GROUPS:
        for keyword in keywords:
            if keyword in item:
                return True
    if any(keyword in item for keyword in ACADEMIC_SUBJECT_HINTS):
        return True
    return False


def split_names(raw):
    """把「卜一轩、张曦 吴辰轩」这类列表拆成姓名数组。"""
    return [n.strip() for n in NAME_SPLIT_RE.split(raw) if n.strip()]


def split_colon(line):
    """按中英文冒号切一次，返回 (左, 右) 或 None（格式错误）。"""
    parts = COLON_SPLIT_RE.split(line, maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[0].strip(), parts[1].strip()


POSITIVE_EVALUATIONS = ("优秀", "认真", "良好", "工整", "整洁", "进步", "棒", "优")
NEGATIVE_EVALUATIONS = ("不合格", "不认真", "马虎", "潦草", "敷衍", "不工整", "退步", "差")
LEAVE_WORDS = ("请假", "病假", "事假")
FORGOT_WORDS = ("忘带", "没带", "未带")
MISSING_WORDS = ("缺交", "未交", "没交", "欠交")


def parse_action(action):
    """解析动作/作业种类文本，不处理姓名匹配。"""
    action = action.strip(" ：:,，、")
    if not action:
        return {
            "subject": DEFAULT_HOMEWORK_TYPE,
            "submission_status": "缺交",
            "evaluation": "",
            "content": "",
            "special_type": "",
        }
    if any(word in action for word in LEAVE_WORDS):
        return {
            "subject": "全科",
            "submission_status": "已交",
            "evaluation": "",
            "content": "",
            "special_type": "请假",
        }
    if any(word in action for word in FORGOT_WORDS):
        return {
            "subject": normalize_subject(action),
            "submission_status": "缺交",
            "evaluation": "",
            "content": action,
            "special_type": "忘带",
        }
    subject = next(
        (canonical for canonical, words in SUBJECT_GROUPS
         if any(word in action for word in words)),
        DEFAULT_HOMEWORK_TYPE,
    )
    if any(word in action for word in MISSING_WORDS):
        content = action
        for word in MISSING_WORDS:
            content = content.replace(word, "")
        return {
            "subject": subject,
            "submission_status": "缺交",
            "evaluation": "",
            "content": content.strip(),
            "special_type": "",
        }
    # 负面词优先匹配：像「不认真」「不工整」内含正面子串「认真」「工整」，
    # 若正面在前会被误判为正面，进而让质量预警/评价分布反转，故负面在前。
    tone_words = NEGATIVE_EVALUATIONS + POSITIVE_EVALUATIONS + ("合格", "一般")
    evaluation = next((word for word in tone_words if word in action), action)
    return {
        "subject": subject,
        "submission_status": "已交",
        "evaluation": evaluation,
        "content": "",
        "special_type": "",
    }


def parse_name_action(line, known_names):
    """解析参考项目的「姓名+动作」语法，姓名按当前教学班最长前缀匹配。"""
    raw = line.strip()
    name = next(
        (candidate for candidate in sorted(known_names, key=len, reverse=True)
         if raw.startswith(candidate)),
        None,
    )
    if not name:
        return {"raw": raw, "error": "未匹配到当前教学班学生"}
    action = raw[len(name):].strip(" ：:,，、")
    return {"raw": raw, "name": name, **parse_action(action)}
