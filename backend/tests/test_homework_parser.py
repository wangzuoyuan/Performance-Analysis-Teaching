from app.homework.parser import (
    is_subject_item,
    normalize_subject,
    parse_homework_item,
    split_colon,
    split_names,
)


def test_normalize_subject_groups():
    assert normalize_subject("英语粉书") == "英语"
    assert normalize_subject("道法") == "政治"
    assert normalize_subject("数学") == "数学"
    assert normalize_subject("") == "未分类"
    # 识别不到的原样返回
    assert normalize_subject("周记") == "周记"


def test_parse_homework_item():
    assert parse_homework_item("请假") == ("全科", None, "请假")
    assert parse_homework_item("英语粉书") == ("英语", "英语粉书", None)
    assert parse_homework_item("数学") == ("数学", None, None)
    assert parse_homework_item("") is None


def test_is_subject_item():
    assert is_subject_item("英语作文") is True
    assert is_subject_item("迟到") is False
    assert is_subject_item("请假") is False


def test_split_helpers():
    assert split_colon("卜一轩：英语、数学") == ("卜一轩", "英语、数学")
    assert split_colon("没有冒号") is None
    assert split_names("卜一轩、张曦 吴辰轩，徐晨") == ["卜一轩", "张曦", "吴辰轩", "徐晨"]
