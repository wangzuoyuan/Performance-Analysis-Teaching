from app.homework.parser import (
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
