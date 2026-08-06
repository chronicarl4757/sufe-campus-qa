"""对已入库文档做带证据的制度版本关系回溯。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from sufe_qa.ingest.versioning import VersionCandidate, infer_version_relations
from sufe_qa.schema import (
    DocMeta,
    DocRelation,
    append_manifest,
    append_relations,
    load_manifest,
    load_relations,
    save_relations,
)

_VERSION_DERIVED_DEFAULTS = {
    "validity_status": "unknown_validity",
    "validity_confidence": 0.0,
    "validity_evidence": "",
    "relation_confidence": 0.0,
    "relation_evidence": "",
    "supersedes": (),
    "superseded_by": (),
}


def _reset_version_fields(manifest_path: Path, relations_path: Path) -> None:
    """清空全部版本派生字段并删除既有 supersedes 关系，供确定性重算。"""
    manifest = load_manifest(manifest_path)
    resets = []
    for meta in manifest.values():

        def _dirty(field: str, default: object) -> bool:
            value = getattr(meta, field)
            if isinstance(default, tuple):
                return tuple(value) != default
            return value != default

        if any(_dirty(field, default) for field, default in _VERSION_DERIVED_DEFAULTS.items()):
            resets.append(replace(meta, **_VERSION_DERIVED_DEFAULTS))
    if resets:
        append_manifest(manifest_path, resets)
    relations = load_relations(relations_path)
    kept = {r for r in relations if r.relation != "supersedes"}
    if len(kept) != len(relations):
        save_relations(relations_path, kept)


@dataclass(frozen=True)
class VersionReconcileReport:
    candidate_groups: int
    relation_count: int
    unknown_validity_count: int
    updated_document_count: int


def reconcile_versions(
    manifest_path: Path,
    corpus_dir: Path,
    relations_path: Path,
    *,
    rebuild: bool = False,
) -> VersionReconcileReport:
    """仅凭正文明确证据升级 current/superseded；年份相似保持 unknown_validity。

    rebuild=True 时先清空全部版本派生字段并删除既有 supersedes 关系，
    再从零确定性重算——用于修正历史误判，保证结果只取决于当前推断规则。
    """
    if rebuild:
        _reset_version_fields(manifest_path, relations_path)
    manifest = load_manifest(manifest_path)
    candidates: list[VersionCandidate] = []
    for meta in manifest.values():
        if (meta.quality_status or "accepted") != "accepted" or not meta.file_path:
            continue
        path = corpus_dir / meta.file_path
        if not path.is_file():
            continue
        candidates.append(
            VersionCandidate(
                doc_id=meta.doc_id,
                title=meta.title,
                body=path.read_text(encoding="utf-8", errors="replace"),
                publish_date=meta.publish_date,
                policy_name=meta.policy_name,
                topic_key=meta.topic_key,
                document_type=meta.document_type,
                parent_doc_id=meta.parent_doc_id or None,
            )
        )
    groups = {}
    for candidate in candidates:
        key = candidate.topic_key or candidate.normalized_policy_name
        groups.setdefault(key, []).append(candidate)
    multi_groups = [group for group in groups.values() if len(group) >= 2]
    inferred = infer_version_relations(candidates)
    relation_rows: list[DocRelation] = []
    updates: dict[str, DocMeta] = {}
    relation_count = 0
    unknown_count = 0
    for relation in inferred:
        if relation.relation == "version_unknown":
            unknown_count += 1
            if relation.source_doc_id in manifest:
                updates[relation.source_doc_id] = replace(
                    updates.get(relation.source_doc_id, manifest[relation.source_doc_id]),
                    validity_status="unknown_validity",
                    validity_confidence=relation.confidence,
                    validity_evidence=relation.evidence,
                    relation_confidence=relation.confidence,
                    relation_evidence=relation.evidence,
                )
            continue
        if relation.relation != "supersedes" or relation.target_doc_id not in manifest:
            continue
        relation_count += 1
        relation_rows.append(
            DocRelation(
                parent_doc_id=relation.source_doc_id,
                child_doc_id=relation.target_doc_id,
                relation="supersedes",
                evidence=relation.evidence,
                confidence=relation.confidence,
            )
        )
        source = updates.get(relation.source_doc_id, manifest[relation.source_doc_id])
        target = updates.get(relation.target_doc_id, manifest[relation.target_doc_id])
        updates[relation.source_doc_id] = replace(
            source,
            validity_status="current",
            validity_confidence=relation.confidence,
            validity_evidence=relation.evidence,
            relation_confidence=relation.confidence,
            relation_evidence=relation.evidence,
            supersedes=tuple(sorted(set(source.supersedes) | {relation.target_doc_id})),
        )
        updates[relation.target_doc_id] = replace(
            target,
            validity_status="superseded",
            validity_confidence=relation.confidence,
            validity_evidence=relation.evidence,
            relation_confidence=relation.confidence,
            relation_evidence=relation.evidence,
            superseded_by=tuple(sorted(set(target.superseded_by) | {relation.source_doc_id})),
        )
    if updates:
        append_manifest(manifest_path, list(updates.values()))
    append_relations(relations_path, relation_rows)
    return VersionReconcileReport(
        candidate_groups=len(multi_groups),
        relation_count=relation_count,
        unknown_validity_count=unknown_count,
        updated_document_count=len(updates),
    )
