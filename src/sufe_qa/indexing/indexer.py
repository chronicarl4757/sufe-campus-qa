"""按文档用途分 collection 的增量/全量索引。

索引器只读取 manifest 和 corpus，不让 adapter 直接写向量库。主问答、公示名单
分别维护自己的 Chroma 与 BM25 语料；新闻、活动、宣传和不完整文档没有默认索引。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import chromadb

from sufe_qa.config import Settings
from sufe_qa.indexing.collections import (
    HISTORICAL_COLLECTION,
    MAIN_QA_COLLECTION,
    PUBLIC_LIST_COLLECTION,
    collection_for_kind,
    collection_name_for,
)
from sufe_qa.ingest.classification import classify_document_kind
from sufe_qa.ingest.quality import default_boost
from sufe_qa.ingest.splitter import split_document
from sufe_qa.schema import DocMeta, load_manifest


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """确定性假向量：字符 3-gram 哈希到 64 维，仅用于测试。"""

    model_name = "fake-hash-3gram-v1"
    backend = "fake"
    test_only = True
    device = "cpu"
    precision = "float32"

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
        import torch
        from sentence_transformers import SentenceTransformer  # 仅此处置允许 import

        self.model_name = model_name
        self.backend = "sentence-transformers"
        self.test_only = False
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.precision = "float16" if self.device == "cuda" else "float32"
        self.batch_size = 32
        model_kwargs = None
        if self.device == "cuda":
            model_kwargs = {"torch_dtype": torch.float16}
            total_vram = torch.cuda.get_device_properties(0).total_memory
            if total_vram <= 4 * 1024**3:
                self.batch_size = 2
        self._m = SentenceTransformer(
            model_name,
            device=self.device,
            model_kwargs=model_kwargs,
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._m.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
        )
        return [[float(x) for x in v] for v in vectors]


@dataclass(frozen=True)
class IndexReport:
    added_docs: int
    updated_docs: int
    deleted_docs: int
    total_chunks: int
    collection_counts: dict[str, int] = field(default_factory=dict)
    skipped_docs: int = 0
    backup_path: str | None = None


@dataclass(frozen=True)
class LegacyMigrationReport:
    source_collection: str
    migrated_chunks: int
    skipped_chunks: int
    target_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Indexable:
    meta: DocMeta
    text: str
    document_kind: str
    collection_key: str


def _document_kind(meta: DocMeta, text: str) -> str:
    """兼容旧 manifest：旧行没有新 kind 时按正文补推断；显式隔离值不提升。"""
    kind = (getattr(meta, "document_kind", "") or "").strip().lower()
    if kind and kind != "incomplete":
        return kind
    inferred = classify_document_kind(
        meta.title,
        text,
        quality_status=str(meta.quality_status or "accepted"),
        has_valid_attachment=meta.document_type == "attachment",
    )
    return inferred


def _load_indexable(settings: Settings) -> tuple[dict[str, _Indexable], int]:
    out: dict[str, _Indexable] = {}
    skipped = 0
    for doc_id, meta in load_manifest(settings.manifest_path).items():
        if str(meta.quality_status or "accepted") != "accepted" or not meta.file_path:
            skipped += 1
            continue
        path = settings.corpus_dir / meta.file_path
        if not path.is_file():
            skipped += 1
            continue
        text = path.read_text(encoding="utf-8")
        kind = _document_kind(meta, text)
        retention_status = meta.retention_status
        if meta.validity_status in {"historical", "superseded"}:
            retention_status = "historical"
        collection_key = collection_for_kind(kind, retention_status)
        if collection_key is None:
            skipped += 1
            continue
        effective_meta = (
            meta
            if retention_status == meta.retention_status
            else replace(meta, retention_status=retention_status)
        )
        out[doc_id] = _Indexable(effective_meta, text, kind, collection_key)

    # 防御性折叠：重试分批或旧迁移可能留下同一年度系列的多个 active 文档。
    # 只改变索引视图，不据此改变 validity_status。
    active_series: dict[str, list[_Indexable]] = {}
    for item in out.values():
        if (
            item.document_kind == "annual_notice"
            and item.meta.retention_status == "active"
            and item.meta.series_key
        ):
            active_series.setdefault(item.meta.series_key, []).append(item)
    for group in active_series.values():
        if len(group) < 2:
            continue
        group_ids = {item.meta.doc_id for item in group}
        declared = {
            item.meta.canonical_doc_id
            for item in group
            if item.meta.canonical_doc_id in group_ids
        }
        canonical_id = (
            next(iter(declared))
            if len(declared) == 1
            else max(group, key=lambda item: (item.meta.publish_date, item.meta.doc_id)).meta.doc_id
        )
        for item in group:
            if item.meta.doc_id == canonical_id:
                out[item.meta.doc_id] = replace(
                    item,
                    meta=replace(item.meta, canonical_doc_id=canonical_id),
                )
                continue
            historical_key = collection_for_kind(item.document_kind, "historical")
            if historical_key is None:
                del out[item.meta.doc_id]
                skipped += 1
                continue
            out[item.meta.doc_id] = replace(
                item,
                meta=replace(
                    item.meta,
                    retention_status="historical",
                    retention_reason="index_canonical_fold",
                    canonical_doc_id=canonical_id,
                ),
                collection_key=historical_key,
            )
    return out, skipped


def _chunk_metadata(item: _Indexable, collection_name: str) -> dict[str, str | int | float | bool]:
    meta = item.meta
    return {
        "doc_id": meta.doc_id,
        "content_hash": meta.content_hash,
        "title": meta.title,
        "category": meta.category,
        "source_url": meta.source_url,
        "publisher": meta.publisher,
        "publish_date": meta.publish_date,
        "document_type": meta.document_type,
        "document_kind": item.document_kind,
        "source_type": meta.source_type or "unknown",
        "source_section": meta.source_section or "",
        "scope_unit": meta.scope_unit or "",
        "policy_name": meta.policy_name or "",
        "topic_key": meta.topic_key or "",
        "validity_status": meta.validity_status or "unknown_validity",
        "validity_confidence": float(meta.validity_confidence or 0.0),
        "effective_date": meta.effective_date or "unknown",
        "valid_until": meta.valid_until or "unknown",
        "revision_year": int(meta.revision_year or 0),
        "parent_doc_id": meta.parent_doc_id or "",
        "index_collection": collection_name,
        "temporal_class": meta.temporal_class or "undated",
        "series_key": meta.series_key or "",
        "retention_status": meta.retention_status or "archived",
        "retention_reason": meta.retention_reason or "",
        "canonical_doc_id": meta.canonical_doc_id or "",
        # 只影响门控后的排序，不参与 vector_min_similarity 判定。
        "boost": default_boost(item.document_kind),
    }


def _upsert_item(col, item: _Indexable, embedder: Embedder, collection_name: str) -> int:
    base_metadata = _chunk_metadata(item, collection_name)
    chunks = split_document(item.text, item.meta.doc_id, base_metadata)
    if not chunks:
        return 0
    embeddings = embedder.encode([f"{item.meta.title}\n{c.text}" for c in chunks])
    col.upsert(
        ids=[c.chunk_id for c in chunks],
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=[{**c.metadata, "heading_path": c.heading_path} for c in chunks],
    )
    return len(chunks)


def _existing_by_collection(client, settings: Settings) -> dict[str, dict[str, str]]:
    existing: dict[str, dict[str, str]] = {}
    for key in (MAIN_QA_COLLECTION, PUBLIC_LIST_COLLECTION, HISTORICAL_COLLECTION):
        col = client.get_or_create_collection(
            collection_name_for(settings, key), metadata={"hnsw:space": "cosine"}
        )
        rows = col.get(include=["metadatas"]).get("metadatas") or []
        existing[key] = {
            str(row["doc_id"]): str(row.get("content_hash", ""))
            for row in rows
            if row and row.get("doc_id")
        }
    return existing


def _write_index_metadata(
    settings: Settings,
    index_dir: Path,
    embedder: Embedder | None,
) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    embedding_model = str(getattr(embedder, "model_name", "legacy-unknown"))
    embedding_backend = str(getattr(embedder, "backend", "legacy-unknown"))
    embedding_device = str(getattr(embedder, "device", "legacy-unknown"))
    embedding_precision = str(getattr(embedder, "precision", "legacy-unknown"))
    test_only = bool(getattr(embedder, "test_only", False))
    manifest_fingerprint = "sha256:" + hashlib.sha256(
        settings.manifest_path.read_bytes() if settings.manifest_path.is_file() else b""
    ).hexdigest()
    fingerprint_payload = json.dumps(
        {
            "collection_schema_version": settings.collection_schema_version,
            "embedding_model": embedding_model,
            "manifest_fingerprint": manifest_fingerprint,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    data = {
        "schema_version": settings.collection_schema_version,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embedding_model": embedding_model,
        "embedding_backend": embedding_backend,
        "embedding_device": embedding_device,
        "embedding_precision": embedding_precision,
        "test_only": test_only,
        "manifest_fingerprint": manifest_fingerprint,
        "index_fingerprint": "sha256:" + hashlib.sha256(fingerprint_payload).hexdigest(),
        "legacy_collection": settings.legacy_collection_name,
        "collections": {
            MAIN_QA_COLLECTION: {
                "name": settings.collection_name,
                "document_kinds": sorted(
                    {"policy", "procedure", "faq", "annual_notice", "form", "manual", "service_guide"}
                ),
            },
            PUBLIC_LIST_COLLECTION: {
                "name": settings.public_list_collection_name,
                "document_kinds": ["public_list"],
            },
            HISTORICAL_COLLECTION: {
                "name": settings.historical_collection_name,
                "document_kinds": sorted(
                    {"policy", "procedure", "annual_notice", "form", "manual", "service_guide"}
                ),
            },
        },
    }
    (index_dir / "index_metadata.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _build_incremental(settings: Settings, embedder: Embedder, index_dir: Path) -> IndexReport:
    client = chromadb.PersistentClient(path=str(index_dir))
    cols = {
        key: client.get_or_create_collection(
            collection_name_for(settings, key), metadata={"hnsw:space": "cosine"}
        )
        for key in (MAIN_QA_COLLECTION, PUBLIC_LIST_COLLECTION, HISTORICAL_COLLECTION)
    }
    manifest, skipped = _load_indexable(settings)
    desired = {
        key: {doc_id: item for doc_id, item in manifest.items() if item.collection_key == key}
        for key in cols
    }
    existing = _existing_by_collection(client, settings)
    existing_global = {doc_id for rows in existing.values() for doc_id in rows}
    desired_global = set(manifest)
    deleted_global: set[str] = set()
    changed_global: set[str] = set()
    added_global: set[str] = set()
    updated_global: set[str] = set()
    total_chunks = 0
    collection_counts: dict[str, int] = {}

    for key, col in cols.items():
        present = existing[key]
        wanted = desired[key]
        deleted = set(present) - set(wanted)
        changed = {
            doc_id for doc_id, item in wanted.items() if present.get(doc_id) != item.meta.content_hash
        }
        for doc_id in deleted | (changed & set(present)):
            col.delete(where={"doc_id": doc_id})
        deleted_global.update(deleted)
        changed_global.update(changed)
        added_global.update(changed - existing_global)
        updated_global.update(changed & existing_global)
        for doc_id in changed:
            total_chunks += _upsert_item(
                col,
                wanted[doc_id],
                embedder,
                collection_name_for(settings, key),
            )
        collection_counts[key] = col.count()

    # doc_id 从主库迁移到公示库（或反向）时，旧 collection 已删除，新增也计为更新。
    deleted_global -= desired_global
    _write_index_metadata(settings, index_dir, embedder)
    return IndexReport(
        added_docs=len(added_global),
        updated_docs=len(updated_global),
        deleted_docs=len(deleted_global),
        total_chunks=total_chunks,
        collection_counts=collection_counts,
        skipped_docs=skipped,
    )


def _build_full(settings: Settings, embedder: Embedder, index_dir: Path) -> IndexReport:
    client = chromadb.PersistentClient(path=str(index_dir))
    cols = {
        key: client.get_or_create_collection(
            collection_name_for(settings, key), metadata={"hnsw:space": "cosine"}
        )
        for key in (MAIN_QA_COLLECTION, PUBLIC_LIST_COLLECTION, HISTORICAL_COLLECTION)
    }
    manifest, skipped = _load_indexable(settings)
    chunks = 0
    counts: dict[str, int] = {}
    for key, col in cols.items():
        items = [item for item in manifest.values() if item.collection_key == key]
        for item in items:
            chunks += _upsert_item(col, item, embedder, collection_name_for(settings, key))
        counts[key] = col.count()
    _write_index_metadata(settings, index_dir, embedder)
    return IndexReport(
        added_docs=len(manifest),
        updated_docs=0,
        deleted_docs=0,
        total_chunks=chunks,
        collection_counts=counts,
        skipped_docs=skipped,
    )


def _cleanup_staging(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def update_index(settings: Settings, embedder: Embedder, full: bool = False) -> IndexReport:
    """增量更新或原子全量重建两个业务 collection。"""
    if not full:
        return _build_incremental(settings, embedder, settings.chroma_dir)

    settings.chroma_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = settings.chroma_dir.parent / f".{settings.chroma_dir.name}.staging-{uuid.uuid4().hex}"
    backup: Path | None = None
    try:
        report = _build_full(settings, embedder, staging)
        if settings.chroma_dir.exists():
            backup = settings.chroma_dir.parent / (
                f".{settings.chroma_dir.name}.previous-{uuid.uuid4().hex}"
            )
            settings.chroma_dir.rename(backup)
        staging.rename(settings.chroma_dir)
    except Exception:
        _cleanup_staging(staging)
        if backup is not None and not settings.chroma_dir.exists() and backup.exists():
            backup.rename(settings.chroma_dir)
        raise
    return replace(report, backup_path=str(backup) if backup else None)


def migrate_legacy_collection(settings: Settings) -> LegacyMigrationReport:
    """把旧单 collection 中可判定的文档复制到新 collection。

    旧 collection 永不删除、永不改写；无法判定用途的 chunk 进入 skipped，等待
    重新从 manifest/corpus 建库，而不是冒险把它放进主问答索引。
    """
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    try:
        legacy = client.get_collection(settings.legacy_collection_name)
    except ValueError:
        return LegacyMigrationReport(settings.legacy_collection_name, 0, 0, {})

    data = legacy.get(include=["documents", "metadatas", "embeddings"])
    ids = data.get("ids") or []
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []
    embeddings = data.get("embeddings")
    if embeddings is None:
        embeddings = []
    target_rows: dict[str, list[tuple[str, list[float], str, dict]]] = {
        MAIN_QA_COLLECTION: [],
        PUBLIC_LIST_COLLECTION: [],
        HISTORICAL_COLLECTION: [],
    }
    skipped = 0
    for chunk_id, text, metadata, embedding in zip(
        ids, documents, metadatas, embeddings, strict=True
    ):
        meta = metadata or {}
        kind = (meta.get("document_kind") or "").strip().lower()
        if not kind:
            kind = classify_document_kind(str(meta.get("title", "")), text or "")
        key = collection_for_kind(kind)
        if key is None:
            skipped += 1
            continue
        target_meta = {
            **meta,
            "document_kind": kind,
            "index_collection": collection_name_for(settings, key),
        }
        target_rows[key].append((chunk_id, embedding, text, target_meta))

    counts: dict[str, int] = {}
    migrated = 0
    for key, rows in target_rows.items():
        if not rows:
            counts[key] = 0
            continue
        col = client.get_or_create_collection(
            collection_name_for(settings, key), metadata={"hnsw:space": "cosine"}
        )
        col.upsert(
            ids=[row[0] for row in rows],
            embeddings=[row[1] for row in rows],
            documents=[row[2] for row in rows],
            metadatas=[row[3] for row in rows],
        )
        migrated += len(rows)
        counts[key] = col.count()
    _write_index_metadata(settings, settings.chroma_dir, None)
    return LegacyMigrationReport(settings.legacy_collection_name, migrated, skipped, counts)
