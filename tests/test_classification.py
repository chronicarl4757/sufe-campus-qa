from __future__ import annotations

from sufe_qa.ingest.classification import classify_document_kind


BODY_WITH_POLICY_REFERENCE = (
    "本年度复试工作依据学校研究生招生管理办法组织实施。考生应按通知提交材料，"
    "参加资格审查和复试，具体时间、地点与联系方式见本页安排。"
)


def test_year_specific_admission_arrangement_outranks_policy_word_in_body():
    assert (
        classify_document_kind(
            "上海财经大学2025年硕士研究生招生考试复试录取办法",
            BODY_WITH_POLICY_REFERENCE,
        )
        == "annual_notice"
    )


def test_formal_timeless_regulation_remains_policy():
    assert (
        classify_document_kind(
            "上海财经大学研究生学籍管理规定",
            "第一条 为规范研究生学籍管理，根据国家有关规定，结合学校实际制定本规定。",
        )
        == "policy"
    )


def test_dated_printing_notice_for_quoted_policy_remains_policy():
    assert (
        classify_document_kind(
            "20250703关于印发《上海财经大学本科学生课程考核管理办法"
            "（2025年5月修订）》的通知",
            "《上海财经大学本科学生课程考核管理办法》已经审议通过，现印发给你们。"
            "第一条 为规范本科学生课程考核，制定本办法。",
        )
        == "policy"
    )


def test_formal_policy_wrapper_outranks_activity_word_inside_policy_name():
    assert (
        classify_document_kind(
            "关于印发《上海财经大学学生社团活动管理办法》的通知",
            "第一条 为规范学生社团活动，制定本办法。第二条 本办法适用于学生社团。",
        )
        == "policy"
    )


def test_public_list_and_promotion_precede_generic_notice_rules():
    assert (
        classify_document_kind(
            "2024-2025学年第一学期1-4周研究生课程调停课情况公示",
            "本期课程调整情况如下。\n具体课程、教师和时间见正文表格。",
        )
        == "public_list"
    )
    assert (
        classify_document_kind(
            "2025年研究生招生宣讲会通知",
            "欢迎同学参加招生宣讲活动，现场介绍培养特色并开展交流。",
        )
        == "promotion"
    )
