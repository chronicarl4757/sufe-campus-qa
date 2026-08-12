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
    # 仅 metadata 变化、未重 embed 的文档数（含 chunk 布局变化回退重建的）
    meta_updated_docs: int = 0


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
        canonical_id = max(
            group,
            key=lambda item: (
                item.meta.validity_status == "current",
                item.meta.publish_date,
                len(item.text),
                item.meta.document_type == "attachment",
                item.meta.doc_id,
            ),
        ).meta.doc_id
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


def _metadata_signature(base_metadata: dict) -> str:
    """doc 级 chunk metadata 的签名：判断要不要刷新 Chroma metadata（不重 embed）。

    覆盖 _chunk_metadata 的全部字段（含 content_hash、title）；不含 fetched_at，
    抓取时间变化不会触发刷新。
    """
    payload = json.dumps(base_metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()[:16]


def _embedding_signature(settings: Settings, base_metadata: dict) -> str:
    """影响 embedding 输入/切分结果的因素签名：判断要不要重 embed。

    当前覆盖 content_hash（正文→切分与嵌入文本）、title（嵌入前缀
    "title\\nchunk"）、collection_schema_version（切分/索引 schema）。
    publisher、publish_date 等纯 metadata 不在内，由 metadata_sig 负责。
    """
    payload = json.dumps(
        {
            "content_hash": base_metadata["content_hash"],
            "title": base_metadata["title"],
            "schema_version": settings.collection_schema_version,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()[:16]


def _base_metadata_with_sig(settings: Settings, item: _Indexable, collection_name: str) -> dict:
    base = _chunk_metadata(item, collection_name)
    return {
        **base,
        "embedding_sig": _embedding_signature(settings, base),
        "metadata_sig": _metadata_signature(base),
    }


def _upsert_item(
    settings: Settings, col, item: _Indexable, embedder: Embedder, collection_name: str
) -> int:
    base_metadata = _base_metadata_with_sig(settings, item, collection_name)
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


def _refresh_item_metadata(
    settings: Settings, col, item: _Indexable, embedder: Embedder, collection_name: str
) -> int:
    """只刷新 Chroma metadata，不重 embed；返回整篇重建的 chunks 数（回退路径）。

    正文未变（embedding_sig 相同）时 chunk 布局应与库中一致，直接 col.update
    各 chunk 的 metadata；布局不一致（如 splitter 已升级）无法对齐，回退
    delete + re-upsert 整篇重建。
    """
    base_metadata = _base_metadata_with_sig(settings, item, collection_name)
    chunks = split_document(item.text, item.meta.doc_id, base_metadata)
    if not chunks:
        return 0
    existing_ids = set(col.get(where={"doc_id": item.meta.doc_id}).get("ids") or [])
    if existing_ids != {c.chunk_id for c in chunks}:
        col.delete(where={"doc_id": item.meta.doc_id})
        return _upsert_item(settings, col, item, embedder, collection_name)
    col.update(
        ids=[c.chunk_id for c in chunks],
        metadatas=[{**c.metadata, "heading_path": c.heading_path} for c in chunks],
    )
    return 0


def _existing_by_collection(client, settings: Settings) -> dict[str, dict[str, tuple[str, str]]]:
    """各 collection 已索引的 doc_id -> (embedding_sig, metadata_sig)。"""
    existing: dict[str, dict[str, tuple[str, str]]] = {}
    for key in (MAIN_QA_COLLECTION, PUBLIC_LIST_COLLECTION, HISTORICAL_COLLECTION):
        col = client.get_or_create_collection(
            collection_name_for(settings, key), metadata={"hnsw:space": "cosine"}
        )
        rows = col.get(include=["metadatas"]).get("metadatas") or []
        existing[key] = {
            # 旧索引无 embedding_sig 字段取 ""：首轮增量按 embedding 已失效处理，
            # 安全地整体重 embed 一次；之后签名齐全，恢复正常增量。
            str(row["doc_id"]): (
                str(row.get("embedding_sig", "")),
                str(row.get("metadata_sig", "")),
            )
            for row in rows
            if row and row.get("doc_id")
        }
    return existing


def _read_index_metadata(index_dir: Path) -> tuple[str, dict | None]:
    """读取 index_metadata.json，返回 (status, data)。

    status: "missing"（文件不存在）| "invalid"（损坏或结构非法）| "valid"。
    只有 "valid" 时 data 非 None。
    """
    path = index_dir / "index_metadata.json"
    if not path.is_file():
        return "missing", None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "invalid", None
    if not isinstance(data, dict):
        return "invalid", None
    return "valid", data


def _existing_chunk_count(client, settings: Settings) -> int:
    """三个业务 collection 中已有的 chunk 总数；collection 不存在计 0。"""
    total = 0
    for key in (MAIN_QA_COLLECTION, PUBLIC_LIST_COLLECTION, HISTORICAL_COLLECTION):
        try:
            total += client.get_collection(collection_name_for(settings, key)).count()
        except (ValueError, chromadb.errors.NotFoundError):
            continue
    return total


def _compatibility_problems(data: dict, settings: Settings, embedder: Embedder) -> list[str]:
    """索引元数据与当前 embedder/schema 的不一致项；空列表表示兼容。"""
    problems: list[str] = []
    schema = str(data.get("schema_version", ""))
    if schema != settings.collection_schema_version:
        problems.append(f"schema_version 索引={schema!r} 当前={settings.collection_schema_version!r}")
    model = str(data.get("embedding_model", ""))
    current_model = str(getattr(embedder, "model_name", ""))
    if model != current_model:
        problems.append(f"embedding_model 索引={model!r} 当前={current_model!r}")
    indexed_test_only = bool(data.get("test_only", False))
    if indexed_test_only != bool(getattr(embedder, "test_only", False)):
        problems.append(f"test_only 索引={indexed_test_only} 当前={not indexed_test_only}")
    return problems


def _check_incremental_compatible(
    settings: Settings, embedder: Embedder, index_dir: Path, client
) -> None:
    """增量索引守卫：索引必须出自当前 embedder 与 schema，否则拒绝并提示 --full。

    metadata 缺失/损坏且库中已有 chunk 时，无法证明已有 embedding 与当前
    模型/schema 兼容，必须拒绝——不能通过一次 incremental 给来源不明的
    旧索引重新盖上当前 metadata。真正首次构建（无 metadata 且无 chunk）放行。
    """
    status, data = _read_index_metadata(index_dir)
    if status != "valid":
        if _existing_chunk_count(client, settings) == 0:
            return
        reason = "缺失" if status == "missing" else "损坏"
        raise RuntimeError(
            f"索引目录已有数据，但 index_metadata.json {reason}，"
            "无法证明已有 embedding 与当前模型/schema 兼容；"
            "已拒绝增量索引，请先运行 index --full 重建"
        )
    problems = _compatibility_problems(data, settings, embedder)
    if problems:
        raise RuntimeError(
            "索引与当前 embedder/schema 不匹配（"
            + "；".join(problems)
            + "），已拒绝增量索引；请先运行 index --full 重建"
        )


def verify_index_compatibility(settings: Settings, embedder: Embedder) -> None:
    """serving 启动校验：索引必须存在且出自当前 embedder 与 schema。

    配错数据目录、忘了 --full 重建、或误用 test_only 索引启动服务时，
    在这里 fail-fast，而不是静默创建一个空 collection 一直拒答。
    """
    status, data = _read_index_metadata(settings.chroma_dir)
    if status != "valid":
        reason = "缺失" if status == "missing" else "损坏"
        raise RuntimeError(
            f"{settings.chroma_dir}/index_metadata.json {reason}：请先运行 index 构建索引"
        )
    problems = _compatibility_problems(data, settings, embedder)
    if problems:
        raise RuntimeError(
            "索引与当前 embedder/schema 不匹配（"
            + "；".join(problems)
            + "）；请运行 index --full 重建后再启动服务"
        )


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
    manifest_fingerprint = (
        "sha256:"
        + hashlib.sha256(
            settings.manifest_path.read_bytes() if settings.manifest_path.is_file() else b""
        ).hexdigest()
    )
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
                    {
                        "policy",
                        "procedure",
                        "faq",
                        "annual_notice",
                        "form",
                        "manual",
                        "service_guide",
                    }
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
    _check_incremental_compatible(settings, embedder, index_dir, client)
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
    meta_updated_global: set[str] = set()
    total_chunks = 0
    collection_counts: dict[str, int] = {}

    for key, col in cols.items():
        present = existing[key]
        wanted = desired[key]
        collection_name = collection_name_for(settings, key)
        deleted = set(present) - set(wanted)
        changed: set[str] = set()
        meta_only: set[str] = set()
        for doc_id, item in wanted.items():
            base = _chunk_metadata(item, collection_name)
            # embedding 输入相关因素（正文/标题/schema）变化：delete + re-upsert，重 embed
            if present.get(doc_id, ("", ""))[0] != _embedding_signature(settings, base):
                changed.add(doc_id)
            # 仅 metadata 变化（含旧索引首次补签名）：刷新 metadata，不重 embed
            elif doc_id in present and present[doc_id][1] != _metadata_signature(base):
                meta_only.add(doc_id)
        for doc_id in deleted | (changed & set(present)):
            col.delete(where={"doc_id": doc_id})
        deleted_global.update(deleted)
        changed_global.update(changed)
        added_global.update(changed - existing_global)
        updated_global.update(changed & existing_global)
        for doc_id in changed:
            total_chunks += _upsert_item(settings, col, wanted[doc_id], embedder, collection_name)
        for doc_id in meta_only:
            meta_updated_global.add(doc_id)
            total_chunks += _refresh_item_metadata(
                settings, col, wanted[doc_id], embedder, collection_name
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
        meta_updated_docs=len(meta_updated_global),
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
            chunks += _upsert_item(
                settings, col, item, embedder, collection_name_for(settings, key)
            )
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
