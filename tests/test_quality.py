"""
文档质量评估测试：附件依赖页、无效标题、导航污染、正文过短、doc_type 分类与 boost。

Run: .venv/bin/python -m pytest tests/test_quality.py -v
"""

import pytest

from sufe_qa.ingest.quality import assess_document, default_boost

VALID_TITLE = "上海财经大学研究生学籍管理办法"

# 中性长正文（去空白 >120 字符，不含任何分类/页脚/附件关键词）
NEUTRAL_BODY = (
    "春日的校园里绿树成荫，同学们在图书馆里安静地自习，偶尔抬头望向窗外。"
    "操场上传来阵阵欢笑声，整个校园充满了生机与活力，处处洋溢着青春气息。"
    "傍晚时分，夕阳洒在教学楼的外墙上，给校园镀上了一层温暖的金色。"
    "夜幕降临后，自习室的灯光依然明亮，走廊里回荡着轻快的脚步声。"
    "新的一天又从清晨的琅琅书声中开始，湖畔的晨读身影络绎不绝。"
)


# ---------- 附件依赖页 ----------


def test_attachment_dependent_page_incomplete():
    r = assess_document(VALID_TITLE, "详见附件。", has_valid_attachment=False)
    assert r.status == "incomplete_document"
    assert not r.accepted
    assert "正文依赖附件但附件缺失或解析失败" in r.reasons


def test_attachment_dependent_page_with_valid_attachment_accepted():
    # 有有效附件兜底：短正文引导下载不算残缺，也不过短
    r = assess_document(VALID_TITLE, "详见附件。", has_valid_attachment=True)
    assert r.status == "accepted"
    assert r.accepted
    assert r.score == 1.0


def test_attachment_keywords_but_long_body_not_incomplete():
    body = NEUTRAL_BODY + "具体材料清单详见附件。"  # 去空白 >120 字符
    r = assess_document(VALID_TITLE, body, has_valid_attachment=False)
    assert r.status == "accepted"


# ---------- 无效标题 ----------


@pytest.mark.parametrize(
    "title",
    [
        "",
        "   ",
        "03a91ba5c9a8",
        "deadbeef1234",
        "首页",
        "通知公告",
        "欢迎访问",
        "无标题",
        "untitled",
        "Untitled",
        "公示专栏",
        "硕士生招生",
    ],
)
def test_invalid_title_rejected(title):
    r = assess_document(title, NEUTRAL_BODY, has_valid_attachment=False)
    assert r.status == "low_quality"
    assert not r.accepted
    assert any("标题" in reason for reason in r.reasons)


def test_short_hash_like_title_under_8_chars_is_valid():
    r = assess_document("03a91ba", NEUTRAL_BODY, has_valid_attachment=False)
    assert r.accepted


# ---------- 导航污染 ----------


def test_nav_pollution_short_lines():
    lines = [
        "首页",
        "学院概况",
        "师资队伍",
        "科学研究",
        "本科生教育",
        "研究生教育",
        "招生就业",
        "人才招聘",
        "校友会",
        "基金会",
        "图书馆",
        "信息门户",
        "这是一条正常的正文句子，包含标点，长度也超过十五个字。",
    ]
    # 13 行中 12 行短无标点（92% > 60%）→ 污染
    r = assess_document(VALID_TITLE, "\n".join(lines), has_valid_attachment=False)
    assert r.status == "low_quality"
    assert any("导航" in reason for reason in r.reasons)


def test_explicit_service_guide_hint_accepts_structured_short_line_table():
    body = "\n".join(
        [
            "快递邮寄服务一览",
            "单位",
            "服务时间",
            "地址",
            "联系电话",
            "菜鸟驿站",
            "9:00-19:00",
            "国定路校区",
            "15800371877",
            "三门路园区",
            "9:00-20:00",
            "13311833846",
            "中山北一路校区",
            "9:00-18:00",
            "19921797883",
            "国定路校区收发室",
            "07:45-11:45",
            "国定路777号前门卫对面",
            "65903864",
            "中山北一路校区收发室",
        ]
    )
    result = assess_document(
        "快递邮寄",
        body,
        has_valid_attachment=False,
        trusted_document_kind="service_guide",
    )

    assert result.status == "accepted"


def test_nav_pollution_ratio_boundary_not_triggered():
    lines = [
        "首页",
        "师资队伍",
        "科学研究",
        "招生就业",
        "校友会",
        "图书馆",
        "这是一条正常正文句子，带有标点。",
        "第二条 管理规定的内容应当具体明确。",
        "第三条 各单位应当遵照执行本规定。",
        "第四条 本办法自发布之日起施行。",
    ]
    # 10 行中 6 短行 = 60%，未超过阈值 → 不判污染
    r = assess_document(VALID_TITLE, "\n".join(lines), has_valid_attachment=False)
    assert not any("导航" in reason for reason in r.reasons)
    assert r.accepted


def test_nav_pollution_footer_words():
    body = (
        NEUTRAL_BODY
        + "\n版权所有 上海财经大学 地址：上海市国定路777号 电话：021-65900000 邮编：200433"
    )
    r = assess_document(VALID_TITLE, body, has_valid_attachment=False)
    assert r.status == "low_quality"
    assert any("页脚" in reason for reason in r.reasons)


def test_footer_two_words_not_pollution():
    body = NEUTRAL_BODY + "\n地址：上海市国定路777号 电话：021-65900000"
    r = assess_document(VALID_TITLE, body, has_valid_attachment=False)
    assert not any("页脚" in reason for reason in r.reasons)
    assert r.accepted


def test_fullwidth_dot_numbered_list_not_pollution():
    """全角句点编号列表（"1．…"）是正文内容，不是无标点短行导航（gs 公告真实形态）。"""
    body = (
        "2027年硕士研究生招生考试（初试）中，我校部分学院的学科专业将调整考试科目，"
        "具体信息可查看以下链接：\n"
        "1．经济学院\n2．财税投资学院\n3．金融学院（金融硕士、保险硕士）\n"
        "4．首席经济学家中心\n5．数字经济学院\n6．滴水湖高级金融学院\n"
        "我校2027年硕士研究生招生学科专业与考试科目最终以招生简章为准。\n"
        "上海财经大学研究生院招生办公室\n2026年4月13日\n发布时间：2026-04-13"
    )
    r = assess_document(
        "我校关于调整2027年硕士研究生招生考试（初试）部分学院学科专业考试科目的公告",
        body,
        has_valid_attachment=False,
        publish_date="2026-04-13",
    )
    assert not any("导航" in reason for reason in r.reasons)
    assert r.accepted


# ---------- 正文过短 ----------


def test_short_body_rejected():
    r = assess_document(VALID_TITLE, "本页面正在维护中。", has_valid_attachment=False)
    assert r.status == "low_quality"
    assert any("正文过短" in reason for reason in r.reasons)


def test_short_body_with_valid_attachment_accepted():
    r = assess_document(VALID_TITLE, "本页面正在维护中，内容搬迁。", has_valid_attachment=True)
    assert r.accepted


def test_body_length_boundary_80_chars_accepted():
    r = assess_document(VALID_TITLE, "一" * 80, has_valid_attachment=False)
    assert r.accepted


# ---------- 指针型公示页豁免 ----------

# gs 公示专栏的真实页面形态：标题即完整信息，正文受源站转载保护而极薄
POINTER_TITLE = "上海财经大学2026年硕士研究生招生考试调剂复试考生名单"
POINTER_BODY = (
    "/ 公示专栏\n上海财经大学2026年硕士研究生招生考试调剂复试考生名单\n"
    "本页内容未经许可，禁止一切形式的转载。\n发布时间：2026-05-07"
)


def test_pointer_page_informative_title_and_date_accepted():
    r = assess_document(
        POINTER_TITLE, POINTER_BODY, has_valid_attachment=False, publish_date="2026-05-07"
    )
    assert r.status == "accepted"
    assert r.score == 1.0


def test_pointer_page_unknown_date_rejected():
    # 日期不明则无法证明时效，仍按正文过短判低质
    r = assess_document(POINTER_TITLE, POINTER_BODY, has_valid_attachment=False)
    assert r.status == "low_quality"
    assert any("正文过短" in reason for reason in r.reasons)


def test_pointer_page_generic_title_still_rejected():
    # 通用栏目名标题 + 薄正文：即使日期明确也判低质（标题规则与豁免同时不兜）
    r = assess_document(
        "公示专栏", POINTER_BODY, has_valid_attachment=False, publish_date="2026-05-07"
    )
    assert r.status == "low_quality"


# ---------- doc_type 分类 ----------


def _list_body(n: int = 25) -> str:
    return "\n".join(f"同学{i:02d} 某专业 学号2025{i:04d}" for i in range(n))


@pytest.mark.parametrize(
    "title,body,expected",
    [
        ("上海财经大学研究生学籍管理办法", NEUTRAL_BODY, "policy"),
        ("校园卡补办流程指南", NEUTRAL_BODY, "procedure"),
        ("2025年奖学金拟获奖名单公示", _list_body(), "public_list"),
        # 名单/公示但行数不足 20 → 不满足 public_list，顺落到 unknown
        ("2025年奖学金拟获奖名单公示", NEUTRAL_BODY, "unknown"),
        ("关于开展2025年工作的通知", NEUTRAL_BODY, "announcement"),
        ("实习备案表模板下载", NEUTRAL_BODY, "download_template"),
        ("创新创业比赛报名开始", NEUTRAL_BODY, "event"),
        ("校领导走访调研经济学院", NEUTRAL_BODY, "news"),
        ("春暖花开校园随手拍", NEUTRAL_BODY, "unknown"),
        # 优先级：policy 高于 announcement；procedure 高于 announcement
        ("关于印发《研究生学籍管理办法》的通知", NEUTRAL_BODY, "policy"),
        ("奖助学金办理流程的通知", NEUTRAL_BODY, "procedure"),
    ],
)
def test_doc_type_classification(title, body, expected):
    assert assess_document(title, body, has_valid_attachment=False).doc_type == expected


@pytest.mark.parametrize(
    "doc_type,expected",
    [
        ("policy", 1.1),
        ("notice", 1.1),
        ("procedure", 1.1),
        ("announcement", 1.1),
        ("download_template", 1.1),
        ("news", 0.85),
        ("event", 0.85),
        ("public_list", 1.0),
        ("unknown", 1.0),
        ("其他未登记类型", 1.0),
    ],
)
def test_default_boost(doc_type, expected):
    assert default_boost(doc_type) == pytest.approx(expected)


# ---------- score / accepted 边界 ----------


def test_clean_document_full_score():
    r = assess_document(VALID_TITLE, NEUTRAL_BODY, has_valid_attachment=False)
    assert r.status == "accepted"
    assert r.accepted
    assert r.score == 1.0
    assert r.reasons == []
    assert r.doc_type == "policy"


def test_single_reason_score_075():
    r = assess_document("03a91ba5c9a8", NEUTRAL_BODY, has_valid_attachment=False)
    assert len(r.reasons) == 1
    assert r.score == pytest.approx(0.75)
    assert not r.accepted


def test_score_floor_zero_with_five_reasons():
    # 同时命中 5 条：附件缺失 + 哈希标题 + 短行污染 + 页脚词 + 正文过短
    short_nav = "\n".join(
        [
            "首页",
            "师资队伍",
            "科学研究",
            "招生就业",
            "校友会",
            "图书馆",
            "基金会",
            "人才招聘",
            "信息门户",
            "English",
        ]
    )
    body = f"详见附件\n{short_nav}\n版权所有 地址：某路 电话：021"
    r = assess_document("03a91ba5c9a8", body, has_valid_attachment=False)
    assert len(r.reasons) == 5
    assert r.score == 0.0  # 1.0 - 5*0.25 = -0.25 → 下限 0
    assert not r.accepted
    # incomplete_document 优先于 low_quality
    assert r.status == "incomplete_document"
