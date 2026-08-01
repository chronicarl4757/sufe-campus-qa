"""混合检索：Chroma 向量路 + jieba/BM25 词面路，RRF 融合。

- BM25 语料直接取自 Chroma 全量文档（同一数据源，不产生第二份索引漂移）；
  语料规模变化时懒重建。
- 拒答门控：向量路最高余弦相似度 >= vector_min_similarity 才算"有可靠来源"。
  RRF 分数量纲随语料漂移，不适合做阈值；阈值用评测集标定。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

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
    publish_date: str = "unknown"


def is_confident(hits: list[Hit], min_similarity: float) -> bool:
    """融合结果中任意 chunk 的向量相似度过阈值即视为有可靠来源。"""
    return any(
        h.vector_similarity is not None and h.vector_similarity >= min_similarity for h in hits
    )


def recency_weight(publish_date: str, today: date | None = None) -> float:
    """时效权重：当年 1.0，每早一年 ×0.85，下限 0.4；日期未知取 0.7。

    政策类信息年年更新（招生/推免/评审办法），作为相关性之上的乘性调节，
    避免旧版文件凭词面命中压过新版。相关性仍是主导：旧文档要胜出，
    RRF 得分需高出 1/weight 倍。
    """
    today = today or date.today()
    m = re.match(r"(\d{4})", publish_date or "")
    if not m:
        return 0.7
    years_old = max(0, today.year - int(m.group(1)))
    return max(0.4, 0.85**years_old)


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
        # 时效重排：先按 RRF 超取 3 倍（为多样性截留留出余量），再乘时效权重。
        # 相关性主导、新度决胜：同主题新旧文件并存时新版优先进入生成上下文。
        candidates = sorted(fused, key=lambda cid: fused[cid], reverse=True)[: s.fusion_top_n * 3]
        ranked = sorted(
            candidates,
            key=lambda cid: (
                fused[cid]
                * recency_weight(str(self._store.get(cid, ("", {}))[1].get("publish_date", "")))
                # 文档类型权重（§十二）：政策/规程 1.1、新闻/活动 0.85，只调排序不过门控
                * float(self._store.get(cid, ("", {}))[1].get("boost", 1.0) or 1.0)
            ),
            reverse=True,
        )
        # 多样性截留：同一文档最多占 max_chunks_per_doc 个槽位，
        # 避免长文档多 chunk 或同模板兄弟文档挤掉其他有效来源
        top_ids: list[str] = []
        per_doc: dict[str, int] = {}
        for cid in ranked:
            doc = str(self._store.get(cid, ("", {}))[1].get("doc_id", ""))
            if per_doc.get(doc, 0) >= s.max_chunks_per_doc:
                continue
            per_doc[doc] = per_doc.get(doc, 0) + 1
            top_ids.append(cid)
            if len(top_ids) >= s.fusion_top_n:
                break

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
                    publish_date=str(meta.get("publish_date", "unknown")),
                )
            )
        return hits
