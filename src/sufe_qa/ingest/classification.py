"""文档用途和政策主题的确定性标准化。"""

from __future__ import annotations

import re

_POLICY_KWS = ("办法", "规定", "条例", "章程", "实施细则", "管理办法")
_PROCEDURE_KWS = ("流程", "指南", "办理", "须知")
_FAQ_KWS = ("常见问题", "常见问答", "FAQ", "问答")
_MANUAL_KWS = ("操作手册", "使用手册", "用户手册")
_SERVICE_KWS = ("服务说明", "服务指南", "服务介绍", "服务流程")
_FORM_KWS = ("申请表", "登记表", "审批表", "表格", "模板")
_PUBLIC_LIST_KWS = ("名单", "公示")
_NEWS_KWS = ("新闻", "动态", "召开", "走访", "调研", "活动")
_PROMOTION_KWS = ("宣讲会", "招生宣传", "开放日", "分享团", "活动回顾")
_EVENT_KWS = ("讲座", "论坛", "会议预告", "比赛", "竞赛")
_ANNUAL_BUSINESS_KWS = (
    "通知",
    "公告",
    "报名",
    "评选",
    "评审",
    "招生",
    "推免",
    "复试",
    "调剂",
    "录取",
    "申请",
    "选拔",
    "考核",
    "报到",
    "安排",
    "奖学金",
    "助学金",
    "资助",
    "夏令营",
)
_TEMPORAL_TITLE_RE = re.compile(
    r"(?:19|20)\d{2}(?:\s*[-—至/]\s*(?:19|20)\d{2})?\s*(?:年|年度|学年)?"
)

_TOPIC_RULES = (
    (("本科生", "奖学金"), "undergraduate.scholarship.merit"),
    (("国家奖学金",), "undergraduate.scholarship.national"),
    (("国家励志奖学金",), "undergraduate.scholarship.incentive"),
    (("助学金", "资助"), "undergraduate.financial_aid"),
    (("困难认定", "家庭经济困难"), "undergraduate.financial_aid.need_assessment"),
    (("勤工助学",), "undergraduate.work_study"),
    (("推免", "推荐免试"), "undergraduate.recommendation_exemption"),
    (("选课", "退课", "重修"), "undergraduate.course_selection"),
    (("休学", "复学", "退学"), "undergraduate.enrollment_status"),
    (("转专业", "转院系"), "undergraduate.major_transfer"),
    (("校外学习学分", "成绩转换"), "undergraduate.external_credit_transfer"),
    (("研究生", "选课"), "graduate.course_selection"),
    (("学分认定",), "graduate.credit_recognition"),
    (("学位论文", "答辩", "学位授予"), "graduate.degree_thesis"),
    (("博士", "申请考核"), "graduate.doctoral_application_assessment"),
    (("硕博连读",), "graduate.integrated_master_doctor"),
    (("国际交流", "公派留学", "短期交流"), "student.international_exchange"),
)


def normalize_policy_name(title: str) -> str:
    text = re.sub(r"\s+", "", title or "").strip(" ：:，,。")
    quoted = re.search(r"《([^》]+)》", text)
    if quoted:
        text = quoted.group(1)
    text = re.sub(r"^关于(?:印发|修订|制定|出台|发布|实施)?", "", text)
    text = re.sub(r"(?:的通知|通知|公告)$", "", text)
    text = re.sub(r"^关于", "", text)
    text = re.sub(r"（(?:修订|试行|暂行|修订稿)[^）]*）$", "", text)
    return text.strip(" ：:，,。")


def standardize_topic_key(title: str, policy_name: str = "", scope_unit: str = "") -> str:
    """把长期制度、修订通知和年度通知归并到稳定业务主题。"""
    text = re.sub(r"\s+", "", f"{title}{policy_name}{scope_unit}")
    for terms, key in _TOPIC_RULES:
        if all(term in text for term in terms):
            return key
    normalized = normalize_policy_name(policy_name or title)
    normalized = re.sub(r"20\d{2}年|20\d{2}年度|（[^）]*(?:修订|试行|暂行)[^）]*）", "", normalized)
    return normalized or "unknown.topic"


def classify_document_kind(
    title: str,
    body_text: str,
    *,
    quality_status: str = "accepted",
    has_valid_attachment: bool = False,
) -> str:
    if quality_status in {"incomplete_document", "low_quality", "quarantined", "rejected"}:
        return "incomplete"
    text = f"{title}\n{body_text}"
    if any(keyword in title for keyword in _PUBLIC_LIST_KWS):
        return "public_list"
    if any(keyword in title for keyword in _PROMOTION_KWS):
        return "promotion"
    if any(keyword in title for keyword in _EVENT_KWS):
        return "event"
    if any(keyword in title for keyword in _NEWS_KWS):
        return "news"
    if _TEMPORAL_TITLE_RE.search(title) and any(
        keyword in title for keyword in _ANNUAL_BUSINESS_KWS
    ):
        return "annual_notice"
    if any(keyword in text for keyword in _FAQ_KWS):
        return "faq"
    if any(keyword in title for keyword in _POLICY_KWS) or (
        "第一条" in body_text[:500] and any(keyword in body_text[:500] for keyword in _POLICY_KWS)
    ):
        return "policy"
    if any(keyword in text for keyword in _FORM_KWS) and len(body_text.strip()) < 300:
        return "form"
    if any(keyword in text for keyword in _MANUAL_KWS):
        return "manual"
    if any(keyword in text for keyword in _SERVICE_KWS):
        return "service_guide"
    if any(keyword in text for keyword in _PROCEDURE_KWS):
        return "procedure"
    if "通知" in title or "公告" in title:
        return "annual_notice"
    if has_valid_attachment:
        return "manual"
    return "incomplete"
