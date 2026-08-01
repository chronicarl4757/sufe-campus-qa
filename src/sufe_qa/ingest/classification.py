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
        lines = [line for line in body_text.splitlines() if line.strip()]
        if len(lines) >= 2 or "名单" in title:
            return "public_list"
    if re.search(r"20\d{2}年|年度", title) and any(k in title for k in ("通知", "公告", "评审", "报名")):
        return "annual_notice"
    if any(keyword in text for keyword in _FAQ_KWS):
        return "faq"
    if any(keyword in text for keyword in _POLICY_KWS):
        return "policy"
    if any(keyword in text for keyword in _FORM_KWS) and len(body_text.strip()) < 300:
        return "form"
    if any(keyword in text for keyword in _MANUAL_KWS):
        return "manual"
    if any(keyword in text for keyword in _SERVICE_KWS):
        return "service_guide"
    if any(keyword in text for keyword in _PROCEDURE_KWS):
        return "procedure"
    if "通知" in text or "公告" in text:
        return "annual_notice"
    if any(keyword in text for keyword in _NEWS_KWS):
        return "news"
    if has_valid_attachment:
        return "manual"
    return "incomplete"
