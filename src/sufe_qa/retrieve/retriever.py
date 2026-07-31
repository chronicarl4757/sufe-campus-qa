"""混合检索：Chroma 向量路 + jieba/BM25 词面路，RRF 融合。

- BM25 语料直接取自 Chroma 全量文档（同一数据源，不产生第二份索引漂移）；
  语料规模变化时懒重建。
- 拒答门控：向量路最高余弦相似度 >= vector_min_similarity 才算"有可靠来源"。
  RRF 分数量纲随语料漂移，不适合做阈值；阈值用评测集标定。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chromadb

from sufe_qa.config import Settings
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


def is_confident(hits: list[Hit], min_similarity: float) -> bool:
    """融合结果中任意 chunk 的向量相似度过阈值即视为有可靠来源。"""
    return any(
        h.vector_similarity is not None and h.vector_similarity >= min_similarity for h in hits
    )


class HybridRetriever:
    def __init__(self, settings: Settings, embedder: Embedder):
        self._settings = settings
        self._embedder = embedder
        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self._col = client.get_or_create_collection(
            settings.collection_name, metadata={"hnsw:space": "cosine"}
        )
        self._store: dict[str, tuple[str, dict]] = {}  # chunk_id -> (text, metadata)
        self._bm25 = None
        self._bm25_ids: list[str] = []

    def _ensure_corpus(self) -> None:
        """从 Chroma 拉全量文档构建 BM25；规模变化时重建（CLI 单次运行只建一次）。"""
        from rank_bm25 import BM25Okapi

        data = self._col.get(include=["documents", "metadatas"])
        ids: list[str] = data.get("ids") or []
        if len(ids) == len(self._store) and self._bm25 is not None:
            return
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        self._store = {cid: (d, m or {}) for cid, d, m in zip(ids, docs, metas, strict=True)}
        self._bm25_ids = ids
        self._bm25 = BM25Okapi([tokenize(d) for d in docs]) if docs else None

    def search(self, question: str) -> list[Hit]:
        s = self._settings
        total = self._col.count()
        if total == 0:
            return []
        self._ensure_corpus()

        # 向量路：cosine space，similarity = 1 - distance
        res = self._col.query(
            query_embeddings=self._embedder.encode([question]),
            n_results=min(s.vector_top_k, total),
            include=["distances"],
        )
        vec_ids = res["ids"][0]
        vec_sim = {cid: 1.0 - d for cid, d in zip(vec_ids, res["distances"][0], strict=True)}

        # 词面路
        bm_ids: list[str] = []
        if self._bm25 is not None:
            scores = self._bm25.get_scores(tokenize(question))
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            bm_ids = [self._bm25_ids[i] for i in ranked[: s.bm25_top_k] if scores[i] > 0]

        fused = rrf_fuse([vec_ids, bm_ids], s.rrf_k)
        top_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[: s.fusion_top_n]

        hits: list[Hit] = []
        for cid in top_ids:
            text, meta = self._store.get(cid, ("", {}))
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
                )
            )
        return hits
