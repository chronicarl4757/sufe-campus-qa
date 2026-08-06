"""基于质量审计结果原子重建干净 corpus。"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sufe_qa.quality.audit import DataQualityAudit
from sufe_qa.schema import DocMeta, append_manifest, load_manifest, sha256_text


@dataclass(frozen=True)
class CleanRebuildResult:
    applied: bool
    total_documents: int
    retained_files: int
    archived_documents: int
    backup_path: Path | None = None


def _fingerprint(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(staging: Path, expected_count: int) -> None:
    manifest_path = staging / "manifest.jsonl"
    manifest = load_manifest(manifest_path)
    if len(manifest) != expected_count:
        raise ValueError(
            f"staging manifest 文档数不一致: {len(manifest)} != {expected_count}"
        )
    for meta in manifest.values():
        if not meta.file_path:
            if meta.content_hash:
                raise ValueError(f"归档文档仍有 content_hash: {meta.doc_id}")
            continue
        path = staging / meta.file_path
        if not path.is_file():
            raise ValueError(f"manifest 引用文件不存在: {meta.doc_id} {meta.file_path}")
        actual = sha256_text(path.read_text(encoding="utf-8", errors="replace"))
        if actual != meta.content_hash:
            raise ValueError(f"正文 hash 不一致: {meta.doc_id}")


def rebuild_clean_corpus(
    audit: DataQualityAudit,
    corpus_dir: Path,
    *,
    apply: bool,
    validation_hook: Callable[[Path], None] | None = None,
) -> CleanRebuildResult:
    """在 sibling staging 中重建并原子切换；``apply=False`` 仅返回预览。"""
    manifest_path = corpus_dir / "manifest.jsonl"
    if _fingerprint(manifest_path) != audit.manifest_fingerprint:
        raise ValueError("manifest 已在审计后变化，请重新运行 quality-audit")
    decisions = {item.doc_id: item for item in audit.decisions}
    manifest = load_manifest(manifest_path)
    if set(decisions) != set(manifest):
        raise ValueError("审计决策与当前 last-wins manifest 不一致")
    retained = sum(item.retention_status in {"active", "historical"} for item in decisions.values())
    archived = len(decisions) - retained
    preview = CleanRebuildResult(False, len(manifest), retained, archived)
    if not apply:
        return preview

    staging = corpus_dir.parent / f".{corpus_dir.name}.staging-{uuid.uuid4().hex}"
    backup: Path | None = None
    try:
        staging.mkdir(parents=True)
        migrated: list[DocMeta] = []
        for doc_id in sorted(manifest):
            meta = manifest[doc_id]
            decision = decisions[doc_id]
            updates = {
                "publish_date": decision.after_publish_date,
                "publish_date_evidence": decision.date_evidence,
                "publish_date_confidence": decision.date_confidence,
                "date_conflict": decision.date_conflict,
                "document_kind": decision.document_kind,
                "temporal_class": decision.temporal_class,
                "series_key": decision.series_key,
                "retention_status": decision.retention_status,
                "retention_reason": decision.retention_reason,
                "canonical_doc_id": decision.canonical_doc_id,
                "index_collection": decision.index_collection,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if decision.retention_status == "archived":
                migrated.append(replace(meta, content_hash="", file_path="", **updates))
                continue
            if not meta.file_path:
                raise ValueError(f"应保留文档缺少 file_path: {doc_id}")
            source = corpus_dir / meta.file_path
            if not source.is_file():
                raise ValueError(f"应保留文档正文不存在: {doc_id} {meta.file_path}")
            target = staging / meta.file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            source_text = source.read_text(encoding="utf-8", errors="replace")
            text = "\n".join(line.rstrip() for line in source_text.splitlines()).rstrip("\n") + "\n"
            target.write_text(text, encoding="utf-8")
            content_hash = sha256_text(text)
            migrated.append(replace(meta, content_hash=content_hash, **updates))
        append_manifest(staging / "manifest.jsonl", migrated)
        relations = corpus_dir / "relations.jsonl"
        if relations.is_file():
            shutil.copy2(relations, staging / "relations.jsonl")
        _validate(staging, len(manifest))
        if validation_hook is not None:
            validation_hook(staging)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = corpus_dir.parent / f".{corpus_dir.name}.previous-{stamp}-{uuid.uuid4().hex[:8]}"
        corpus_dir.rename(backup)
        try:
            staging.rename(corpus_dir)
        except Exception:
            backup.rename(corpus_dir)
            backup = None
            raise
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return CleanRebuildResult(True, len(manifest), retained, archived, backup)
