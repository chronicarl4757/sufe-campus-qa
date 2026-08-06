"""文档时间属性与年度系列的确定性标准化。

本模块不判断制度是否有效，也不读写 manifest。它只提供纯函数，把文档用途映射为
时间类别，并把不同年份的同一业务通知归并到稳定 series key。
"""

from __future__ import annotations

import re
import unicodedata

_SCHOOL_YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*[-—至到/]\s*(?:19|20)\d{2}\s*学年")
_CALENDAR_YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*(?:年度|年)")
_BATCH_RE = re.compile(r"第\s*[一二三四五六七八九十百0-9]+\s*批")
_WEEK_RE = re.compile(r"第?\s*\d+\s*(?:[-—至到]\s*\d+)?\s*周")
_SPACE_PUNCT_RE = re.compile(r"[\s_·•]+")
_WRAPPER_PREFIX_RE = re.compile(r"^(?:关于|上海财经大学关于)")
_WRAPPER_SUFFIX_RE = re.compile(r"(?:的通知|通知|公告)$")


def _clean_component(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = re.sub(r"\.(?:pdf|docx?|xlsx?|pptx?)$", "", value, flags=re.I)
    value = _SCHOOL_YEAR_RE.sub("", value)
    value = _CALENDAR_YEAR_RE.sub("", value)
    value = _BATCH_RE.sub("", value)
    value = _WEEK_RE.sub("", value)
    value = _WRAPPER_PREFIX_RE.sub("", value)
    value = _WRAPPER_SUFFIX_RE.sub("", value)
    value = _SPACE_PUNCT_RE.sub("", value)
    return value.strip("-—:：,，。()（）[]【】")


def series_key_for(title: str, *, publisher: str = "", scope_unit: str = "") -> str:
    """返回可审计、稳定的年度系列键；不删除学院和适用对象。"""
    normalized_title = _clean_component(title) or "unknown-series"
    normalized_publisher = _clean_component(publisher) or "unknown-publisher"
    normalized_scope = _clean_component(scope_unit) or "all"
    return f"{normalized_publisher}|{normalized_scope}|{normalized_title}"


def temporal_class_for(document_kind: str, title: str = "") -> str:
    kind = (document_kind or "").strip().lower()
    if kind in {"policy", "procedure", "faq", "form", "manual", "service_guide"}:
        return "enduring"
    if kind == "annual_notice":
        return "annual"
    if kind == "public_list":
        return "recurring_public"
    if kind in {"news", "event", "promotion"}:
        return "ephemeral"
    return "undated"

