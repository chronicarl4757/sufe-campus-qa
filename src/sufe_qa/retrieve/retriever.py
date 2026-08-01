"""按业务 collection 隔离的混合检索：Chroma 向量路 + BM25 词面路。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import chromadb

from sufe_qa.config import Settings
from sufe_qa.indexing.collections import (
    MAIN_QA_COLLECTION,
    collection_key_for_name,
    collection_name_for,
)
from sufe_qa.indexing.indexer import Embedder

_WORD_RE = re.compile(r"\w+")


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


@dataclass
class _CollectionView:
    key: str
    name: str
    col: object
    store: dict[str, tuple[str, dict]] = field(default_factory=dict)
    bm25: object | None = None
    bm25_ids: list[str] = field(default_factory=list)


class HybridRetriever:
    """默认检索主问答 collection；公示名单必须显式路由。"""

    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        collection: str = MAIN_QA_COLLECTION,
    ):
        self._settings = settings
        self._embedder = embedder
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
            col = self._client.get_or_create_collection(
                name, metadata={"hnsw:space": "cosine"}
            )
            view = _CollectionView(key=key, name=name, col=col)
            self._views[key] = view
        return view

    @staticmethod
    def _ensure_corpus(view: _CollectionView) -> None:
        """从当前 collection 拉全量文档构建独立 BM25；规模变化时重建。"""
        from rank_bm25 import BM25Okapi

        data = view.col.get(include=["documents", "metadatas"])
        ids: list[str] = data.get("ids") or []
        if len(ids) == len(view.store) and view.bm25 is not None:
            return
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        view.store = {cid: (d, m or {}) for cid, d, m in zip(ids, docs, metas, strict=True)}
        view.bm25_ids = ids
        view.bm25 = BM25Okapi([tokenize(d) for d in docs]) if docs else None

    def search(self, question: str, collection: str | None = None) -> list[Hit]:
        s = self._settings
        view = self._view(collection or self._default_collection_key)
        total = view.col.count()
        if total == 0:
            return []
        self._ensure_corpus(view)

        # 向量路：cosine space，similarity = 1 - distance
        res = view.col.query(
            query_embeddings=self._embedder.encode([question]),
            n_results=min(s.vector_top_k, total),
            include=["distances"],
        )
        vec_ids = res["ids"][0]
        vec_sim = {cid: 1.0 - d for cid, d in zip(vec_ids, res["distances"][0], strict=True)}

        # 词面路：每个 collection 有自己的 BM25 语料，不跨库混合。
        bm_ids: list[str] = []
        if view.bm25 is not None:
            scores = view.bm25.get_scores(tokenize(question))
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            bm_ids = [view.bm25_ids[i] for i in ranked[: s.bm25_top_k] if scores[i] > 0]

        fused = rrf_fuse([vec_ids, bm_ids], s.rrf_k)
        candidates = sorted(fused, key=lambda cid: fused[cid], reverse=True)[: s.fusion_top_n * 3]
        ranked = sorted(
            candidates,
            key=lambda cid: (
                fused[cid]
                * recency_weight(str(view.store.get(cid, ("", {}))[1].get("publish_date", "")))
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
                )
            )
        return hits
