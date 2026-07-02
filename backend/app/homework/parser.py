"""作业录入文本解析与学科归类。

移植自原「作业跟踪」Flask 应用 app.py 的 SUBJECT_GROUPS /
normalize_subject / parse_homework_item / is_subject_item，逻辑保持不变，
仅独立成模块供 router 与对话工具复用。
"""

import re

# 学科归类表：原始文本含任一关键词即归到对应规范学科名。
SUBJECT_GROUPS = [
    ("语文", ["语文"]),
    ("数学", ["数学"]),
    ("英语", ["英语"]),
    ("物理", ["物理"]),
    ("化学", ["化学"]),
    ("生物", ["生物"]),
    ("历史", ["历史"]),
    ("地理", ["地理"]),
    ("政治", ["政治", "道法", "道德与法治"]),
    ("全科", ["全科"]),
]

# 录入文本里「学生/学科 : 列表」的分隔符
NAME_SPLIT_RE = re.compile(r"[，,；;、\s]+")
COLON_SPLIT_RE = re.compile(r"[:：]")


def normalize_subject(subject):
    """把原始学科文本归一化到规范学科名；识别不到则原样返回。"""
    if not subject:
        return "未分类"

    normalized = str(subject).strip().replace(" ", "")
    if not normalized:
        return "未分类"

    for canonical_name, keywords in SUBJECT_GROUPS:
        if any(keyword in normalized for keyword in keywords):
            return canonical_name

    return normalized


def parse_homework_item(item):
    """解析单个作业项，返回 (subject, content, remark)。

    - '请假'     → ('全科', None, '请假')
    - '英语粉书' → ('英语', '英语粉书', None)
    - '数学'     → ('数学', None, None)
    无法识别学科时，原样作为学科名返回。
    """
    item = item.strip()
    if not item:
        return None

    if item == "请假":
        return ("全科", None, "请假")

    for canonical_name, keywords in SUBJECT_GROUPS:
        for keyword in keywords:
            if keyword in item:
                content = item if item != keyword else None
                return (canonical_name, content, None)

    return (item, None, None)


def is_subject_item(item):
    """item 是否包含可识别的学科关键词（用于区分缺交 vs 特殊情况）。"""
    item = item.strip()
    for _, keywords in SUBJECT_GROUPS:
        for keyword in keywords:
            if keyword in item:
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
    if not action:
        return {
            "raw": raw, "name": name, "subject": "综合",
            "submission_status": "缺交", "evaluation": "", "content": "",
            "special_type": "",
        }
    if any(word in action for word in LEAVE_WORDS):
        return {
            "raw": raw, "name": name, "subject": "综合",
            "submission_status": "已交", "evaluation": "", "content": "",
            "special_type": "请假",
        }
    if any(word in action for word in FORGOT_WORDS):
        return {
            "raw": raw, "name": name, "subject": normalize_subject(action),
            "submission_status": "缺交", "evaluation": "", "content": action,
            "special_type": "忘带",
        }
    subject = next(
        (canonical for canonical, words in SUBJECT_GROUPS
         if any(word in action for word in words)),
        "综合",
    )
    if any(word in action for word in MISSING_WORDS):
        content = action
        for word in MISSING_WORDS:
            content = content.replace(word, "")
        return {
            "raw": raw, "name": name, "subject": subject,
            "submission_status": "缺交", "evaluation": "", "content": content.strip(),
            "special_type": "",
        }
    tone_words = POSITIVE_EVALUATIONS + NEGATIVE_EVALUATIONS + ("合格", "一般")
    evaluation = next((word for word in tone_words if word in action), action)
    return {
        "raw": raw, "name": name, "subject": subject,
        "submission_status": "已交", "evaluation": evaluation, "content": "",
        "special_type": "",
    }
