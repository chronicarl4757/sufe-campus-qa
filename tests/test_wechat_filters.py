"""公众号过滤测试：相关性（规格 §二十八）、白名单（§二十九）、时间窗（§三十）。"""

from __future__ import annotations

import pytest

from sufe_qa.wechat.filters import (
    WechatAccount,
    classify_wechat_kind,
    date_gate,
    load_wechat_accounts,
    match_account,
    relevance_check,
)

ACCOUNTS = [
    WechatAccount(
        account_id="sufe_jwc",
        account_name="上海财经大学教务处",
        publisher="上海财经大学教务处",
        scope_unit="本科生",
        aliases=("上财教务处",),
    ),
    WechatAccount(
        account_id="sufe_zs",
        account_name="上财本科招生",
        publisher="上海财经大学招生就业处",
    ),
]


@pytest.mark.parametrize(
    "title",
    [
        "2026年本科生转专业工作通知",
        "关于国家奖学金评选工作的通知",
        "新生校园卡使用指南",
        "2026级新生报到须知",
        "学生证补办流程",
    ],
)
def test_relevance_accepts_service_titles(title):
    assert relevance_check(title).keep


@pytest.mark.parametrize(
    "title",
    [
        "转专业经验分享｜优秀学生风采",
        "喜报！我院学子荣获国家级奖项",
        "迎新晚会精彩回顾",
        "我院举办学术讲座",
        "主题党日活动纪实",
        "校友返校日精彩瞬间",
        "具身智能时代的人机智慧协同研讨会成功举办",
        "72小时极限作战：SCAIers的国赛一等奖之路",
        "学院师生5篇论文入选KDD2026",
        "诚邀全球英才申报2026年国家优青项目（海外）",
        "信息管理与工程学院党委换届选举党员大会顺利召开",
    ],
)
def test_relevance_rejects_noise_titles(title):
    decision = relevance_check(title)
    assert not decision.keep
    assert decision.reason == "strong_exclude"


def test_soft_exclude_with_admission_signal_defers():
    """“推免政策讲座通知”：讲座（软排除）+ 推免信号 → 不预检拒绝，正文有事实则保留（§二十六）。"""
    assert relevance_check("2026推免政策解读讲座通知").keep
    body = "讲座定于3月20日举行，解读2026年推免政策报名条件与材料要求。"
    assert relevance_check("2026推免政策解读讲座通知", body).keep
    junk = "我院近日举办讲座，师生合影留念。"
    assert not relevance_check("2026推免政策解读讲座通知", junk).keep


def test_party_activity_body_rejected():
    body = "党员同志们走进国歌展示馆，党支部开展主题党日活动，重温入党誓词。" * 2
    decision = relevance_check("追寻红色记忆 传承廉洁精神", body)
    assert not decision.keep
    assert decision.reason == "news_noise"


def test_strong_exclude_beats_strong_include():
    # “转专业学生风采展示”同时命中 include（转专业）与 exclude（风采）→ 拒绝（规格 §十三）
    decision = relevance_check("转专业学生风采展示")
    assert not decision.keep


def test_relevance_neutral_title_uses_body_classification():
    body = "我院于近日召开学科建设研讨会，校领导出席并讲话。" * 3
    decision = relevance_check("我院举行学科建设研讨", body)
    assert not decision.keep
    assert decision.reason == "news_noise"


def test_relevance_neutral_title_with_service_body_passes():
    body = "第一步，登录教务系统；第二步，在“选课管理”模块提交申请，截止时间为3月20日。" * 3
    assert relevance_check("系统升级后的新操作说明", body).keep


def test_whitelist_exact_and_alias():
    assert match_account("上海财经大学教务处", ACCOUNTS) is ACCOUNTS[0]
    assert match_account("上财教务处", ACCOUNTS) is ACCOUNTS[0]
    assert match_account("上财本科招生", ACCOUNTS) is ACCOUNTS[1]


def test_whitelist_rejects_lookalike():
    # 标题像官方不算数；账号名必须精确匹配（规格 §二十九）
    assert match_account("上财校园资讯", ACCOUNTS) is None
    assert match_account("上海财经大学教务处学生会", ACCOUNTS) is None
    assert match_account("", ACCOUNTS) is None


def test_load_wechat_accounts_from_yaml(tmp_path):
    path = tmp_path / "wechat.yaml"
    path.write_text(
        "sources:\n"
        "  - id: a\n"
        "    account_name: 上海财经大学教务处\n"
        "    publisher: 上海财经大学教务处\n"
        "    scope_unit: 本科生\n"
        "    category: 学工事务\n"
        "    enabled: true\n"
        "  - id: b\n"
        "    account_name: 未确认账号\n"
        "    publisher: X\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    accounts = load_wechat_accounts(path)
    assert len(accounts) == 1
    assert accounts[0].account_id == "a"
    assert accounts[0].category == "学工事务"


def test_date_gate():
    assert date_gate("2026-03-01") == (True, "in_window")
    assert date_gate("2024-01-01") == (True, "in_window")
    assert date_gate("2022-06-01")[0] is False
    # 显式 force_include 的种子允许例外（规格 §十四）
    assert date_gate("2022-06-01", force_include=True) == (True, "force_include")
    # 未知日期不预拒绝，留待抓取后复检
    assert date_gate("unknown")[0] is True
    assert date_gate("")[0] is True


def test_classify_wechat_kind_maps_to_existing_enum():
    assert classify_wechat_kind("一图读懂｜2026年本科生转专业工作", "解读正文" * 10) == "procedure"
    assert (
        classify_wechat_kind(
            "关于印发《上海财经大学学生申诉处理实施细则》的通知", "第一条 总则" * 20
        )
        == "policy"
    )
    assert classify_wechat_kind("新生校园卡使用指南", "校园卡服务指南正文" * 20) in {
        "service_guide",
        "procedure",
    }
    kind = classify_wechat_kind(
        "关于2026年本科生转专业工作的通知", "各学院：现将有关事项通知如下" * 10
    )
    assert kind in {"annual_notice", "policy", "procedure"}
