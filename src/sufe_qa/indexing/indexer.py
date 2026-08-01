"""增量索引：以 manifest 的 content_hash 为准，与 Chroma 中已索引内容做 diff。

- manifest 有、Chroma 没有（或 hash 不同）→ 切分、嵌入、upsert
- Chroma 有、manifest 没有 → delete
- 两侧 hash 一致 → 不动（幂等，重复运行是 no-op）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import chromadb

from sufe_qa.config import Settings
from sufe_qa.ingest.quality import classify_document, default_boost
from sufe_qa.ingest.splitter import split_document
from sufe_qa.schema import load_manifest


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """确定性假向量：字符 3-gram 哈希到 64 维，仅用于测试。"""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for i in range(max(1, len(t) - 2)):
                g = t[i : i + 3]
                v[int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % self.dim] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


class BgeEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        from sentence_transformers import SentenceTransformer  # 仅此处置允许 import

        self._m = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._m.encode(texts, normalize_embeddings=True)]


@dataclass(frozen=True)
class IndexReport:
    added_docs: int
    updated_docs: int
    deleted_docs: int
    total_chunks: int


def update_index(settings: Settings, embedder: Embedder, full: bool = False) -> IndexReport:
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    if full:
        try:
            client.delete_collection(settings.collection_name)
        except ValueError:
            pass  # collection 尚不存在，忽略
    col = client.get_or_create_collection(
        settings.collection_name, metadata={"hnsw:space": "cosine"}
    )

    # 质量门：仅 quality_status == "accepted" 的文档进入索引；
    # 被拒/隔离文档视同不在 manifest，已从索引存在的会被同步删除
    manifest = {
        d: m
        for d, m in load_manifest(settings.manifest_path).items()
        if m.quality_status == "accepted"
    }
    existing = col.get(include=["metadatas"]).get("metadatas") or []
    existing_hash = {m["doc_id"]: m["content_hash"] for m in existing if m}

    deleted = [d for d in existing_hash if d not in manifest]
    changed = [d for d, meta in manifest.items() if existing_hash.get(d) != meta.content_hash]
    added = [d for d in changed if d not in existing_hash]
    updated = [d for d in changed if d in existing_hash]

    for doc_id in set(deleted) | set(updated):
        col.delete(where={"doc_id": doc_id})

    total = 0
    for doc_id in changed:
        meta = manifest[doc_id]
        text = (settings.corpus_dir / meta.file_path).read_text(encoding="utf-8")
        chunk_meta = {
            "doc_id": meta.doc_id,
            "content_hash": meta.content_hash,
            "title": meta.title,
            "category": meta.category,
            "source_url": meta.source_url,
            "publisher": meta.publisher,
            "publish_date": meta.publish_date,
            "document_type": meta.document_type,
            # 检索排序权重（§十二）：policy/procedure 等 1.1，news/event 0.85；
            # 只影响门控后的排序，不参与 vector_min_similarity 门控判定
            "boost": default_boost(classify_document(meta.title, text)),
        }
        chunks = split_document(text, doc_id, chunk_meta)
        if not chunks:
            continue
        # 嵌入时给 chunk 加标题前缀（contextual header）：PDF 附件正文多以"我院"
        # 自称，裸 chunk 不含机构名，向量路无法区分各学院同名模板文件；
        # 库存文档仍是原文，前缀只用于向量计算
        embeddings = embedder.encode([f"{meta.title}\n{c.text}" for c in chunks])
        col.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[{**c.metadata, "heading_path": c.heading_path} for c in chunks],
        )
        total += len(chunks)

    return IndexReport(
        added_docs=len(added),
        updated_docs=len(updated),
        deleted_docs=len(deleted),
        total_chunks=total,
    )
