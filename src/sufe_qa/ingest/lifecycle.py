"""文档时间属性与年度系列的确定性标准化。

本模块不判断制度是否有效，也不读写 manifest。它只提供纯函数，把文档用途映射为
时间类别，并把不同年份的同一业务通知归并到稳定 series key。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date

_SCHOOL_YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*[-—至到/]\s*(?:19|20)\d{2}\s*学年")
_CALENDAR_YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*(?:年度|年)")
_BATCH_RE = re.compile(r"第\s*[一二三四五六七八九十百0-9]+\s*批")
_WEEK_RE = re.compile(r"第?\s*\d+\s*(?:[-—至到]\s*\d+)?\s*周")
_SPACE_PUNCT_RE = re.compile(r"[\s_·•]+")
_WRAPPER_PREFIX_RE = re.compile(r"^(?:关于|上海财经大学关于)")
_WRAPPER_SUFFIX_RE = re.compile(r"(?:的通知|通知|公告)$")


@dataclass(frozen=True)
class LifecycleCandidate:
    doc_id: str
    title: str
    publisher: str
    scope_unit: str
    document_kind: str
    publish_date: str


@dataclass(frozen=True)
class LifecycleDecision:
    temporal_class: str
    series_key: str
    retention_status: str
    retention_reason: str
    canonical_doc_id: str = ""


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


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _school_year_start(value: date) -> int:
    return value.year if value.month >= 9 else value.year - 1


def _base_retention(
    candidate: LifecycleCandidate, *, time_policy: str, evaluated_at: date
) -> LifecycleDecision:
    temporal_class = temporal_class_for(candidate.document_kind, candidate.title)
    series_key = series_key_for(
        candidate.title,
        publisher=candidate.publisher,
        scope_unit=candidate.scope_unit,
    )
    if temporal_class == "ephemeral" or candidate.document_kind in {
        "news",
        "event",
        "promotion",
        "incomplete",
    }:
        return LifecycleDecision(
            temporal_class, series_key, "archived", "isolated_document_kind"
        )
    if time_policy == "archive_only":
        return LifecycleDecision(temporal_class, series_key, "archived", "archive_only")
    if time_policy == "all_history":
        return LifecycleDecision(temporal_class, series_key, "active", "all_history")
    # 正式制度、办事指南等长期文档不能因为它恰好出现在年度通知栏目中而被时间窗淘汰。
    # 时间窗只约束年度通知、公示和其他有明确时效的内容。
    if temporal_class == "enduring":
        return LifecycleDecision(
            temporal_class, series_key, "active", "enduring_document"
        )

    published = _parse_date(candidate.publish_date)
    if published is None:
        return LifecycleDecision(
            temporal_class,
            series_key,
            "archived",
            "missing_publish_date_for_time_policy",
        )
    age = _school_year_start(evaluated_at) - _school_year_start(published)
    if age < 0:
        return LifecycleDecision(
            temporal_class, series_key, "archived", "future_publish_date"
        )
    windows = {
        "recent_5_school_years": (4, "outside_recent_5_school_years"),
        "recent_2_school_years": (1, "outside_recent_2_school_years"),
        "current_school_year": (0, "outside_current_school_year"),
    }
    try:
        max_age, outside_reason = windows[time_policy]
    except KeyError as exc:
        raise ValueError(f"未知 time_policy: {time_policy}") from exc
    if age > max_age:
        return LifecycleDecision(temporal_class, series_key, "archived", outside_reason)
    return LifecycleDecision(temporal_class, series_key, "active", time_policy)


def resolve_lifecycle(
    candidates: list[LifecycleCandidate], *, time_policy: str, evaluated_at: date
) -> dict[str, LifecycleDecision]:
    """计算一批文档的生命周期，并为年度系列只选择一个 active canonical。"""
    decisions = {
        candidate.doc_id: _base_retention(
            candidate, time_policy=time_policy, evaluated_at=evaluated_at
        )
        for candidate in candidates
    }
    annual_groups: dict[str, list[LifecycleCandidate]] = {}
    for candidate in candidates:
        decision = decisions[candidate.doc_id]
        if decision.temporal_class == "annual" and decision.retention_status == "active":
            annual_groups.setdefault(decision.series_key, []).append(candidate)
    for group in annual_groups.values():
        canonical = max(group, key=lambda candidate: (candidate.publish_date, candidate.doc_id))
        for candidate in group:
            decision = decisions[candidate.doc_id]
            decisions[candidate.doc_id] = replace(
                decision,
                retention_status=("active" if candidate.doc_id == canonical.doc_id else "historical"),
                retention_reason=(
                    decision.retention_reason
                    if candidate.doc_id == canonical.doc_id
                    else "prior_annual_series_version"
                ),
                canonical_doc_id=canonical.doc_id,
            )
    return decisions
