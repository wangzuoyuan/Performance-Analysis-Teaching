from app.homework.parser import (
    is_special_item,
    is_subject_item,
    normalize_subject,
    parse_action,
    parse_homework_item,
    parse_name_action,
    split_colon,
    split_names,
)


def test_normalize_subject_groups():
    assert normalize_subject("校本优秀") == "校本作业"
    assert normalize_subject("试卷订正") == "试卷订正"
    assert normalize_subject("数学") == "日常作业"
    assert normalize_subject("") == "未分类"
    # 识别不到的原样返回
    assert normalize_subject("周记") == "周记"


def test_parse_homework_item():
    assert parse_homework_item("请假") == ("全科", None, "请假")
    assert parse_homework_item("校本作业") == ("校本作业", None, None)
    assert parse_homework_item("数学") == ("日常作业", "数学", None)
    assert parse_homework_item("") is None


def test_is_subject_item():
    assert is_subject_item("英语作文") is True
    assert is_subject_item("迟到") is False
    assert is_subject_item("请假") is False


def test_is_subject_item_unknown_defaults_to_homework():
    # 老师自定义的作业名不在关键词表里，也要当作业种类，否则会误记成特殊记录
    assert is_subject_item("专题二") is True
    assert is_subject_item("限时训练") is True
    assert is_subject_item("") is False
    # 考勤 / 评价类仍走特殊记录
    assert is_subject_item("忘带") is False
    assert is_subject_item("表扬") is False
    assert is_subject_item("不认真") is False


def test_is_special_item_status_words():
    # 交了但没做全，不是缺交
    for item in ("漏题", "漏做两题", "漏了三题", "少写一问", "没写完", "未完成", "空了两题"):
        assert is_special_item(item) is True, item
    # 情况词优先于作业种类：「校本漏题」不能记成校本缺交
    assert is_special_item("校本漏题") is True
    assert is_special_item("专题二漏题") is True
    # 补交 / 免做 / 考勤 / 品行
    for item in ("补交", "免做", "迟到", "抄袭"):
        assert is_special_item(item) is True, item
    # 「漏交」是缺交的同义词，不能被 漏X 规则吞掉
    assert is_special_item("漏交") is False
    # 作业种类先兜住，避免撞上评价词单字
    for item in ("培优练习", "查漏补缺", "校本作业", "专题二"):
        assert is_special_item(item) is False, item


def test_parse_action_incomplete_counts_as_special_not_missing():
    result = parse_action("校本漏题")
    assert result["special_type"] == "漏题"
    assert result["submission_status"] == "已交"
    assert result["subject"] == "校本作业"
    loose = parse_action("漏了两题")
    assert loose["special_type"] == "漏做"
    assert loose["submission_status"] == "已交"
    # 缺交语义不受影响
    assert parse_action("校本缺交")["submission_status"] == "缺交"


def test_split_helpers():
    assert split_colon("卜一轩：英语、数学") == ("卜一轩", "英语、数学")
    assert split_colon("没有冒号") is None
    assert split_names("卜一轩、张曦 吴辰轩，徐晨") == ["卜一轩", "张曦", "吴辰轩", "徐晨"]


def test_parse_action_homework_type_status_and_evaluation():
    excellent = parse_action("校本优秀")
    assert excellent["subject"] == "校本作业"
    assert excellent["submission_status"] == "已交"
    assert excellent["evaluation"] == "优秀"

    missing = parse_action("订正缺交")
    assert missing["subject"] == "试卷订正"
    assert missing["submission_status"] == "缺交"

    weak = parse_name_action("张三校本差", {"张三"})
    assert weak["subject"] == "校本作业"
    assert weak["submission_status"] == "已交"
    assert weak["evaluation"] == "差"
