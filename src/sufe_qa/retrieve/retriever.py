"""按业务 collection 隔离的混合检索：Chroma 向量路 + BM25 词面路。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

import chromadb

from sufe_qa.config import Settings
from sufe_qa.indexing.collections import (
    HISTORICAL_COLLECTION,
    MAIN_QA_COLLECTION,
    PUBLIC_LIST_COLLECTION,
    collection_key_for_name,
    collection_name_for,
)
from sufe_qa.indexing.indexer import Embedder, verify_index_compatibility

_WORD_RE = re.compile(r"\w+")

# 命中这些意图时才把对应 collection 合入检索；默认只查主问答库。
_PUBLIC_LIST_INTENT_RE = re.compile(r"公示|名单|拟录取|录取结果|获评|获奖名单")
_HISTORICAL_INTENT_RE = re.compile(
    r"旧版|历史版本|上一版|修订前|废止|失效|曾经规定|原来的规定|往年|哪一版"
)
# 次级 collection 合入的命中上限，避免公示/历史内容挤占主问答证据位
SECONDARY_COLLECTION_TOP_N = 3

_TIME_BOUND_DOCUMENT_KINDS = frozenset(
    {"annual_notice", "public_list", "news", "event", "promotion"}
)

_QUERY_EXPANSIONS = (
    (re.compile(r"校医院"), "门诊部 医疗健康服务中心 就诊导航 地理位置"),
    (re.compile(r"毕业去向"), "毕业去向管理 我的毕业去向 就业综合管理服务平台"),
    (re.compile(r"挂科"), "课程不及格 参评学年 不具有申请资格"),
    (
        re.compile(r"家庭经济困难.*认定|困难学生.*认定"),
        "家庭经济困难学生认定 认定程序 认定对象 申请材料",
    ),
    (
        re.compile(r"灵活就业"),
        "自由职业 其他录用形式 自主创业 毕业去向管理 我的毕业去向 毕业去向登记",
    ),
    (
        re.compile(r"考上研究生.*三方|升学.*三方"),
        "升学 交回协议书 违约改签 就业指导办公室",
    ),
    (
        re.compile(r"成绩.*异议|成绩.*复核"),
        "期末成绩 成绩发布后7日 成绩复核",
    ),
)


def expand_query(question: str) -> str:
    """补充校内稳定同义称谓；保留原问题，不改变门控阈值。"""
    additions = [terms for pattern, terms in _QUERY_EXPANSIONS if pattern.search(question)]
    return " ".join((question, *additions)) if additions else question


def route_collections(question: str) -> tuple[str, ...]:
    """按问题意图选择检索的 collection；主问答库始终在首位。"""
    collections = [MAIN_QA_COLLECTION]
    if _PUBLIC_LIST_INTENT_RE.search(question):
        collections.append(PUBLIC_LIST_COLLECTION)
    if _HISTORICAL_INTENT_RE.search(question):
        collections.append(HISTORICAL_COLLECTION)
    return tuple(collections)


def tokenize(text: str) -> list[str]:
    """jieba 分词并过滤纯标点/空白 token，保留中英文词与数字。"""
    import jieba  # 延迟 import：仅检索路径需要

    return [t for t in (tok.strip() for tok in jieba.lcut(text.lower())) if _WORD_RE.fullmatch(t)]


def rrf_fuse(rankings: list[list[str]], k: int) -> dict[str, float]:
    """Reciprocal Rank Fusion：chunk_id -> sum(1/(k+rank))，rank 从 1 起。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    category: str
    source_url: str
    publisher: str
    heading_path: str
    text: str
    rrf_score: float
    vector_similarity: float | None  # 未进入向量路 top-k 时为 None
    publish_date: str = "unknown"
    document_kind: str = "incomplete"
    source_type: str = "unknown"
    validity_status: str = "unknown_validity"
    index_collection: str = ""
    parent_doc_id: str = ""  # 附件命中的所属文章；无父级时为空
    parent_title: str = ""


def is_confident(hits: list[Hit], min_similarity: float) -> bool:
    """融合结果中任意 chunk 的向量相似度过阈值即视为有可靠来源。"""
    return any(
        h.vector_similarity is not None and h.vector_similarity >= min_similarity for h in hits
    )


def recency_weight(publish_date: str, today: date | None = None) -> float:
    """时效权重：当年 1.0，每早一年 ×0.85，下限 0.4；日期未知取 0.7。"""
    today = today or date.today()
    m = re.match(r"(\d{4})", publish_date or "")
    if not m:
        return 0.7
    years_old = max(0, today.year - int(m.group(1)))
    return max(0.4, 0.85**years_old)


def retrieval_time_weight(
    document_kind: str, publish_date: str, today: date | None = None
) -> float:
    """仅对年度性内容做时间衰减；长期制度和指南由版本证据决定权重。"""
    if document_kind not in _TIME_BOUND_DOCUMENT_KINDS:
        return 1.0
    return recency_weight(publish_date, today)


@dataclass
class _CollectionView:
    key: str
    name: str
    col: object
    store: dict[str, tuple[str, dict]] = field(default_factory=dict)
    doc_titles: dict[str, str] = field(default_factory=dict)
    bm25: object | None = None
    bm25_ids: list[str] = field(default_factory=list)
    # 构建 store/BM25 时的 index_fingerprint；索引重建（含 metadata-only 刷新）后失效
    fingerprint: str = ""


class HybridRetriever:
    """默认检索主问答；公示名单和历史版本必须显式路由。"""

    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        collection: str = MAIN_QA_COLLECTION,
    ):
        self._settings = settings
        self._embedder = embedder
        # 启动校验：索引缺失/与 embedder 不匹配时 fail-fast，不静默创建空库
        verify_index_compatibility(settings, embedder)
        self._client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self._default_collection_key = collection_key_for_name(settings, collection)
        self._views: dict[str, _CollectionView] = {}
        # 兼容旧代码读取默认 collection 的内部属性；搜索本身使用 _views。
        default = self._view(self._default_collection_key)
        self._col = default.col
        self._store = default.store
        self._bm25 = default.bm25
        self._bm25_ids = default.bm25_ids

    def _view(self, key_or_name: str) -> _CollectionView:
        key = collection_key_for_name(self._settings, key_or_name)
        view = self._views.get(key)
        if view is None:
            name = collection_name_for(self._settings, key)
            try:
                col = self._client.get_collection(name)
            except ValueError as e:
                raise RuntimeError(
                    f"索引 collection {name} 不存在；请先运行 index 构建索引"
                ) from e
            view = _CollectionView(key=key, name=name, col=col)
            self._views[key] = view
        return view

    def _index_fingerprint(self) -> str:
        """当前 index_metadata.json 的指纹；缺失/损坏返回 ""（退化为 count 语义）。"""
        try:
            data = json.loads(
                (self._settings.chroma_dir / "index_metadata.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError):
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("index_fingerprint", ""))

    def _ensure_corpus(self, view: _CollectionView) -> None:
        """从当前 collection 拉全量文档构建独立 BM25；索引指纹或规模变化时重建。"""
        from rank_bm25 import BM25Okapi

        fingerprint = self._index_fingerprint()
        if (
            view.bm25 is not None
            and fingerprint == view.fingerprint
            and view.col.count() == len(view.store)
        ):
            return
        data = view.col.get(include=["documents", "metadatas"])
        ids: list[str] = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        view.store = {cid: (d, m or {}) for cid, d, m in zip(ids, docs, metas, strict=True)}
        view.doc_titles = {}
        for _, meta in view.store.values():
            doc_id = str(meta.get("doc_id", ""))
            if doc_id and doc_id not in view.doc_titles:
                view.doc_titles[doc_id] = str(meta.get("title", ""))
        view.bm25_ids = ids
        view.bm25 = BM25Okapi([tokenize(d) for d in docs]) if docs else None
        view.fingerprint = fingerprint

    def search_routed(self, question: str) -> list[Hit]:
        """按问题意图检索多个 collection 并合并：主问答全量，次级 capped。"""
        collections = route_collections(question)
        if len(collections) == 1:
            return self.search(question)
        merged: list[Hit] = []
        seen: set[str] = set()
        for rank, key in enumerate(collections):
            hits = self.search(question, collection=key)
            if rank > 0:
                hits = hits[:SECONDARY_COLLECTION_TOP_N]
            for hit in hits:
                if hit.chunk_id in seen:
                    continue
                seen.add(hit.chunk_id)
                merged.append(hit)
        return merged

    def search(self, question: str, collection: str | None = None) -> list[Hit]:
        s = self._settings
        view = self._view(collection or self._default_collection_key)
        total = view.col.count()
        if total == 0:
            return []
        self._ensure_corpus(view)
        retrieval_query = expand_query(question)

        # 向量路：cosine space，similarity = 1 - distance
        res = view.col.query(
            query_embeddings=self._embedder.encode([retrieval_query]),
            n_results=min(s.vector_top_k, total),
            include=["distances"],
        )
        vec_ids = res["ids"][0]
        vec_sim = {cid: 1.0 - d for cid, d in zip(vec_ids, res["distances"][0], strict=True)}

        # 词面路：每个 collection 有自己的 BM25 语料，不跨库混合。
        bm_ids: list[str] = []
        if view.bm25 is not None:
            scores = view.bm25.get_scores(tokenize(retrieval_query))
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            bm_ids = [view.bm25_ids[i] for i in ranked[: s.bm25_top_k] if scores[i] > 0]

        fused = rrf_fuse([vec_ids, bm_ids], s.rrf_k)
        candidates = sorted(fused, key=lambda cid: fused[cid], reverse=True)[: s.fusion_top_n * 3]
        ranked = sorted(
            candidates,
            key=lambda cid: (
                fused[cid]
                * retrieval_time_weight(
                    str(
                        view.store.get(cid, ("", {}))[1].get(
                            "document_kind", "incomplete"
                        )
                    ),
                    str(view.store.get(cid, ("", {}))[1].get("publish_date", "")),
                )
                * float(view.store.get(cid, ("", {}))[1].get("boost", 1.0) or 1.0)
            ),
            reverse=True,
        )
        top_ids: list[str] = []
        per_doc: dict[str, int] = {}
        for cid in ranked:
            doc = str(view.store.get(cid, ("", {}))[1].get("doc_id", ""))
            if per_doc.get(doc, 0) >= s.max_chunks_per_doc:
                continue
            per_doc[doc] = per_doc.get(doc, 0) + 1
            top_ids.append(cid)
            if len(top_ids) >= s.fusion_top_n:
                break

        hits: list[Hit] = []
        for cid in top_ids:
            text, meta = view.store.get(cid, ("", {}))
            parent_doc_id = str(meta.get("parent_doc_id", "") or "")
            hits.append(
                Hit(
                    chunk_id=cid,
                    doc_id=str(meta.get("doc_id", "")),
                    title=str(meta.get("title", "")),
                    category=str(meta.get("category", "")),
                    source_url=str(meta.get("source_url", "")),
                    publisher=str(meta.get("publisher", "")),
                    heading_path=str(meta.get("heading_path", "")),
                    text=text,
                    rrf_score=fused[cid],
                    vector_similarity=vec_sim.get(cid),
                    publish_date=str(meta.get("publish_date", "unknown")),
                    document_kind=str(meta.get("document_kind", "incomplete")),
                    source_type=str(meta.get("source_type", "unknown")),
                    validity_status=str(meta.get("validity_status", "unknown_validity")),
                    index_collection=str(meta.get("index_collection", view.name)),
                    parent_doc_id=parent_doc_id,
                    parent_title=view.doc_titles.get(parent_doc_id, "") if parent_doc_id else "",
                )
            )
        return hits
