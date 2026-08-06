"""知识库 collection 路由。

collection 的归属由显式 document-kind allowlist 决定，不能依赖类型枚举的顺序。
隔离类型没有默认向量 collection，避免新闻、公示和不完整页面污染主问答库。
"""

from __future__ import annotations

from typing import Final

from sufe_qa.config import Settings

MAIN_QA_COLLECTION: Final = "main_qa"
PUBLIC_LIST_COLLECTION: Final = "public_list"
HISTORICAL_COLLECTION: Final = "historical"

MAIN_QA_KINDS: Final = frozenset(
    {"policy", "procedure", "faq", "annual_notice", "form", "manual", "service_guide"}
)
PUBLIC_LIST_KINDS: Final = frozenset({"public_list"})
HISTORICAL_KINDS: Final = frozenset(
    {"policy", "procedure", "annual_notice", "form", "manual", "service_guide"}
)
ISOLATED_KINDS: Final = frozenset({"news", "event", "promotion", "incomplete"})


def collection_for_kind(
    document_kind: str | None, retention_status: str = "active"
) -> str | None:
    """返回逻辑 collection key；隔离文档返回 ``None``。"""
    kind = (document_kind or "incomplete").strip().lower()
    retention = (retention_status or "archived").strip().lower()
    if retention == "historical":
        return HISTORICAL_COLLECTION if kind in HISTORICAL_KINDS else None
    if retention != "active":
        return None
    if kind in MAIN_QA_KINDS:
        return MAIN_QA_COLLECTION
    if kind in PUBLIC_LIST_KINDS:
        return PUBLIC_LIST_COLLECTION
    if kind in ISOLATED_KINDS or not kind:
        return None
    # 未知类型必须安全隔离，避免新类型意外进入问答索引。
    return None


def collection_name_for(settings: Settings, collection_key: str) -> str:
    """将逻辑 collection key 映射为带 schema 版本的实际 Chroma 名称。"""
    if collection_key == MAIN_QA_COLLECTION:
        return settings.collection_name
    if collection_key == PUBLIC_LIST_COLLECTION:
        return settings.public_list_collection_name
    if collection_key == HISTORICAL_COLLECTION:
        return settings.historical_collection_name
    raise ValueError(f"未知 collection key: {collection_key}")


def collection_key_for_name(settings: Settings, name: str) -> str:
    """接受逻辑 key 或实际 collection 名，统一为逻辑 key。"""
    if name in {MAIN_QA_COLLECTION, settings.collection_name}:
        return MAIN_QA_COLLECTION
    if name in {PUBLIC_LIST_COLLECTION, settings.public_list_collection_name}:
        return PUBLIC_LIST_COLLECTION
    if name in {HISTORICAL_COLLECTION, settings.historical_collection_name}:
        return HISTORICAL_COLLECTION
    raise ValueError(f"未知 collection: {name}")
