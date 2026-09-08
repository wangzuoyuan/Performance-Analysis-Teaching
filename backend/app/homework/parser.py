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


def is_special_item(item):
    """item 是否为「情况」而非作业种类（记特殊记录，不计缺交）。

    三档判定，顺序有意如此：
    1. 情况词/情况句式（请假、迟到、忘带、漏题、补交…）优先于作业种类——
       「校本漏题」是交了但没做全，不能记成缺交。
    2. 命中作业种类或学科名 → 不是情况，交回 is_subject_item。
    3. 剩下的才看评价词（优秀、潦草…）。放在种类之后，是因为「培优练习」
       「查漏补缺」这类作业名会撞上评价词的单字，让种类先兜住。
    """
    item = item.strip()
    if not item:
        return False
    if any(word in item for word in SPECIAL_STATUS_WORDS):
        return True
    if SPECIAL_STATUS_RE.search(item):
        return True
    for _, keywords in SUBJECT_GROUPS:
        if any(keyword in item for keyword in keywords):
            return False
    if any(keyword in item for keyword in ACADEMIC_SUBJECT_HINTS):
        return False
    return any(word in item for word in ITEM_EVALUATION_WORDS)


def is_subject_item(item):
    """item 是否当作作业种类（用于区分缺交 vs 特殊情况）。

    只排除 is_special_item 认定的情况词，其余一律当作老师自定义的作业种类
    （如「专题二」「限时训练」）——否则自定义作业名会被误记成特殊记录，
    不计入缺交统计和连续缺交预警。
    """
    item = item.strip()
    if not item:
        return False
    return not is_special_item(item)


def split_names(raw):
    """把「卜一轩、张曦 吴辰轩」这类列表拆成姓名数组。"""
    return [n.strip() for n in NAME_SPLIT_RE.split(raw) if n.strip()]


def split_colon(line):
    """按中英文冒号切一次，返回 (左, 右) 或 None（格式错误）。"""
    parts = COLON_SPLIT_RE.split(line, maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[0].strip(), parts[1].strip()


# 「全班都交了」的表达：右侧整体匹配才算（如「校本作业：全交」「周末作业：齐了」）
_FULL_SUBMIT_TOKENS = {"全交", "齐", "全齐", "交齐", "都交", "全交齐", "都交齐"}


def is_full_submission(text):
    """右侧列表是否为「全交/齐」类表达（忽略 了/嘛/吗/标点/空白）。

    命中时由路由展开为范围内每人一条「已交」记录：只有缺交记录时「全交日」
    不可见，连续缺交预警会把 缺-交-缺 误判为连续。"""
    normalized = re.sub(r"[了嘛吗！!。，,、\s]", "", str(text or ""))
    return normalized in _FULL_SUBMIT_TOKENS


POSITIVE_EVALUATIONS = ("优秀", "认真", "良好", "工整", "整洁", "进步", "棒", "优")
NEGATIVE_EVALUATIONS = ("不合格", "不认真", "马虎", "潦草", "敷衍", "不工整", "退步", "差")
LEAVE_WORDS = ("请假", "病假", "事假")
FORGOT_WORDS = ("忘带", "没带", "未带")
MISSING_WORDS = ("缺交", "未交", "没交", "欠交")

# ── 特殊记录（「情况」）的识别词表，见 is_special_item ──
ATTENDANCE_WORDS = ("迟到", "早退", "旷课", "缺课", "缺席")
# 交了但没做全：漏题、少做几题、留白，都不该记成缺交
INCOMPLETE_WORDS = ("漏题", "漏做", "漏写", "漏答", "少做", "少写", "未完成", "没做完", "没写完", "空白")
MAKEUP_WORDS = ("补交", "已补", "补做", "重做", "免做", "免交", "免修")
CONDUCT_WORDS = ("表扬", "批评", "违纪", "值日", "抄袭", "代写")
SPECIAL_STATUS_WORDS = (
    LEAVE_WORDS + FORGOT_WORDS + ATTENDANCE_WORDS
    + INCOMPLETE_WORDS + MAKEUP_WORDS + CONDUCT_WORDS
)
# 词表列不全的口语写法：「漏了两题」「少答一问」「没写完」「空了三题」。
# 「漏交」是缺交的同义词，明确排除，别被 漏X 规则吞掉。
_COUNT = r"\d一二两三四五六七八九十几半"
SPECIAL_STATUS_RE = re.compile(
    rf"漏(?!交)[了做写答题{_COUNT}]"
    rf"|少[了做写答][{_COUNT}]?"
    r"|没[写做答]完"
    rf"|空[了]?[{_COUNT}]*[题空处]"
)
# 评价词只在没有作业种类时才判为特殊记录，单字的「优」「差」不参与，
# 否则「培优练习」「查漏补差」这类作业名会被误判。
ITEM_EVALUATION_WORDS = tuple(
    word for word in NEGATIVE_EVALUATIONS + POSITIVE_EVALUATIONS if len(word) > 1
)


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
    incomplete = next((word for word in INCOMPLETE_WORDS if word in action), None)
    if incomplete or SPECIAL_STATUS_RE.search(action):
        # 交了但没做全：记一条特殊记录，作业本身算已交，不进缺交统计
        return {
            "subject": subject,
            "submission_status": "已交",
            "evaluation": "",
            "content": action,
            "special_type": incomplete or "漏做",
        }
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
