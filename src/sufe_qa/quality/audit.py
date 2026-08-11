"""现有 SUFE 语料的只读生命周期审计。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sufe_qa.indexing.collections import collection_for_kind
from sufe_qa.ingest.classification import classify_document_kind
from sufe_qa.ingest.lifecycle import (
    LifecycleCandidate,
    canonicalize_active_annual,
    resolve_lifecycle,
)
from sufe_qa.schema import DocMeta, load_manifest, load_relations

_DATE_LABEL_RE = re.compile(
    r"(?:发布日期|发布时间|发稿时间)\s*[:：]?\s*"
    r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})"
)
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_ATTACHMENT_REFERENCES = ("详见附件", "见附件", "点击下载", "申请表见附件", "办法见附件")


@dataclass(frozen=True)
class QualityDecision:
    doc_id: str
    title: str
    source_url: str
    document_type: str
    before_publish_date: str
    after_publish_date: str
    date_evidence: str
    date_confidence: float
    date_conflict: bool
    before_document_kind: str
    document_kind: str
    temporal_class: str
    series_key: str
    retention_status: str
    retention_reason: str
    canonical_doc_id: str
    index_collection: str
    raw_available: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataQualityAudit:
    schema_version: str
    evaluated_at: str
    manifest_fingerprint: str
    total_documents: int
    accepted_documents: int
    materialized_documents: int
    active_documents: int
    historical_documents: int
    archived_documents: int
    year_title_count: int
    year_title_ratio: float
    annual_series_count: int
    duplicate_annual_series_count: int
    duplicate_active_annual_series_count: int
    date_correction_count: int
    date_conflict_count: int
    old_annual_count: int
    old_public_count: int
    collection_contamination_count: int
    unknown_type_count: int
    archived_without_raw_count: int
    main_qa_documents: int
    public_list_documents: int
    historical_collection_documents: int
    decisions: tuple[QualityDecision, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def _manifest_fingerprint(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _body_for(meta: DocMeta, corpus_dir: Path) -> str:
    if not meta.file_path:
        return ""
    path = corpus_dir / meta.file_path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _raw_article_path(meta: DocMeta, raw_root: Path) -> Path | None:
    host = urlparse(meta.source_page_url or meta.source_url).netloc.lower()
    if not host:
        return None
    path = raw_root / host / "articles" / f"{meta.parent_doc_id or meta.doc_id}.html"
    return path if path.is_file() else None


def _raw_attachment_exists(meta: DocMeta, raw_root: Path) -> bool:
    if not meta.binary_hash:
        return False
    host = urlparse(meta.source_page_url or meta.source_url).netloc.lower()
    if not host:
        return False
    root = raw_root / host / "attachments" / meta.binary_hash[:2]
    return root.is_dir() and any(path.is_file() for path in root.iterdir())


def _raw_available(meta: DocMeta, raw_root: Path) -> bool:
    if meta.document_type == "attachment":
        return _raw_attachment_exists(meta, raw_root)
    return _raw_article_path(meta, raw_root) is not None


def _labeled_date(meta: DocMeta, raw_root: Path) -> tuple[str, str, float, bool]:
    path = _raw_article_path(meta, raw_root)
    if path is None:
        return (
            meta.publish_date,
            meta.publish_date_evidence,
            meta.publish_date_confidence,
            meta.date_conflict,
        )
    raw = path.read_text(encoding="utf-8", errors="replace")
    matches = list(_DATE_LABEL_RE.finditer(raw))
    if not matches:
        return (
            meta.publish_date,
            meta.publish_date_evidence,
            meta.publish_date_confidence,
            meta.date_conflict,
        )
    values = [
        f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        for match in matches
    ]
    evidence = re.sub(r"\s+", "", matches[0].group(0))
    return values[0], evidence, 1.0, len(set(values)) > 1


def _default_time_policy(kind: str) -> str:
    if kind in {"policy", "procedure", "faq", "form", "manual", "service_guide"}:
        return "all_history"
    if kind == "annual_notice":
        return "recent_5_school_years"
    if kind == "public_list":
        return "recent_2_school_years"
    return "archive_only"


def _is_curated_manual(meta: DocMeta) -> bool:
    return meta.source_type == "manual_upload" and meta.source_url.startswith(
        "manual://sufe-regulations/"
    )


def _is_nic_service_guide(meta: DocMeta) -> bool:
    """只信任 NIC adapter 对学生服务目录给出的类型，不接受任意来源的同名字段。"""
    return (
        meta.document_kind == "service_guide"
        and meta.source_type == "official_department"
        and meta.source_section == "学生服务"
        and "网络信息中心" in meta.publisher
        and urlparse(meta.source_url).netloc.lower() == "nic.sufe.edu.cn"
    )


def _is_curated_service_guide(meta: DocMeta) -> bool:
    return (
        meta.document_kind == "service_guide"
        and meta.source_type == "manual_upload"
        and meta.source_section == "人工精编指南"
        and meta.source_url.startswith("curated/")
    )


def audit_corpus(
    manifest_path: Path,
    corpus_dir: Path,
    raw_root: Path,
    *,
    evaluated_at: date | None = None,
    time_policies: dict[tuple[str, str], str] | None = None,
    trusted_document_kinds: set[tuple[str, str, str]] | None = None,
    relations_path: Path | None = None,
) -> DataQualityAudit:
    """读取 last-wins manifest 并给出迁移决策；不写任何输入文件。"""
    evaluated_at = evaluated_at or datetime.now(timezone.utc).date()
    time_policies = time_policies or {}
    trusted_document_kinds = trusted_document_kinds or set()
    manifest = load_manifest(manifest_path)
    bodies = {doc_id: _body_for(meta, corpus_dir) for doc_id, meta in manifest.items()}
    relations_path = relations_path or manifest_path.with_name("relations.jsonl")
    relations = load_relations(relations_path)
    children_by_parent: dict[str, set[str]] = {}
    for relation in relations:
        if relation.relation == "attachment_of":
            children_by_parent.setdefault(relation.parent_doc_id, set()).add(relation.child_doc_id)
    valid_attachment_ids = {
        doc_id
        for doc_id, meta in manifest.items()
        if meta.document_type == "attachment"
        and meta.quality_status == "accepted"
        and bool(meta.file_path and bodies[doc_id])
    }
    missing_required_attachment = {
        doc_id
        for doc_id, meta in manifest.items()
        if meta.document_type == "article"
        and any(marker in bodies[doc_id] for marker in _ATTACHMENT_REFERENCES)
        and not (children_by_parent.get(doc_id, set()) & valid_attachment_ids)
    }
    dates: dict[str, tuple[str, str, float, bool]] = {}
    kinds: dict[str, str] = {}
    policies: dict[str, str] = {}
    candidates_by_policy: dict[str, list[LifecycleCandidate]] = {}

    for doc_id, meta in manifest.items():
        dates[doc_id] = _labeled_date(meta, raw_root)
        if doc_id in missing_required_attachment or meta.quality_status != "accepted":
            kind = "incomplete"
        elif not meta.file_path or not bodies[doc_id]:
            if (
                meta.retention_status == "archived"
                and meta.retention_reason != "legacy_unreviewed"
                and meta.document_kind
            ):
                kind = meta.document_kind
            else:
                kind = "incomplete"
        elif (
            _is_curated_manual(meta)
            or _is_nic_service_guide(meta)
            or _is_curated_service_guide(meta)
            or (
                meta.source_type in {"official_department", "information_disclosure"}
                and (meta.publisher, meta.source_section, meta.document_kind)
                in trusted_document_kinds
            )
        ):
            kind = meta.document_kind
        else:
            kind = classify_document_kind(
                meta.title,
                bodies[doc_id],
                quality_status=meta.quality_status,
                has_valid_attachment=meta.document_type == "attachment",
            )
        kinds[doc_id] = kind
        policy = time_policies.get(
            (meta.publisher, meta.source_section), _default_time_policy(kind)
        )
        policies[doc_id] = policy
        candidates_by_policy.setdefault(policy, []).append(
            LifecycleCandidate(
                doc_id=doc_id,
                title=meta.title,
                publisher=meta.publisher,
                scope_unit=meta.scope_unit,
                document_kind=kind,
                publish_date=dates[doc_id][0],
            )
        )

    lifecycle = {}
    for policy, candidates in candidates_by_policy.items():
        lifecycle.update(
            resolve_lifecycle(candidates, time_policy=policy, evaluated_at=evaluated_at)
        )

    for doc_id, meta in manifest.items():
        if not (
            _is_curated_manual(meta)
            and meta.retention_status in {"active", "historical"}
            and kinds[doc_id] not in {"news", "event", "promotion", "incomplete"}
        ):
            continue
        lifecycle[doc_id] = replace(
            lifecycle[doc_id],
            retention_status=meta.retention_status,
            retention_reason=f"manual_allowlist_{meta.retention_status}",
            canonical_doc_id=(
                doc_id
                if meta.retention_status == "active"
                and lifecycle[doc_id].temporal_class == "annual"
                else ""
            ),
        )

    for doc_id, meta in manifest.items():
        if meta.validity_status not in {"historical", "superseded"}:
            continue
        decision = lifecycle[doc_id]
        if decision.retention_status == "active":
            lifecycle[doc_id] = replace(
                decision,
                retention_status="historical",
                retention_reason="explicit_superseded_validity",
            )
    lifecycle = canonicalize_active_annual(
        [candidate for candidates in candidates_by_policy.values() for candidate in candidates],
        lifecycle,
    )

    parent_ids_by_child: dict[str, set[str]] = {}
    for relation in relations:
        parent_ids_by_child.setdefault(relation.child_doc_id, set()).add(relation.parent_doc_id)
    for doc_id, meta in manifest.items():
        if meta.document_type != "attachment":
            continue
        if kinds[doc_id] == "incomplete" or meta.quality_status != "accepted":
            continue
        parent_ids = parent_ids_by_child.get(doc_id, set())
        parent_candidates = [
            (manifest[parent_id], lifecycle[parent_id])
            for parent_id in parent_ids
            if parent_id in manifest and parent_id in lifecycle
        ]
        if not parent_candidates:
            continue
        parent_meta, parent_lifecycle = max(
            parent_candidates,
            key=lambda item: (
                {"archived": 0, "historical": 1, "active": 2}.get(item[1].retention_status, 0),
                item[0].publish_date,
                item[0].doc_id,
            ),
        )
        own = lifecycle[doc_id]
        if own.retention_status == "archived" and parent_lifecycle.retention_status in {
            "active",
            "historical",
        } and collection_for_kind(
            kinds[doc_id], parent_lifecycle.retention_status
        ) is not None:
            lifecycle[doc_id] = replace(
                own,
                series_key=parent_lifecycle.series_key,
                retention_status=parent_lifecycle.retention_status,
                retention_reason="retained_by_parent_relation",
                canonical_doc_id=parent_lifecycle.canonical_doc_id or parent_meta.doc_id,
            )

    decisions: list[QualityDecision] = []
    for doc_id, meta in manifest.items():
        publish_date, evidence, confidence, conflict = dates[doc_id]
        decision = lifecycle[doc_id]
        kind = kinds[doc_id]
        collection = collection_for_kind(kind, decision.retention_status) or "none"
        raw_available = _raw_available(meta, raw_root)
        reasons: list[str] = [decision.retention_reason]
        if publish_date != meta.publish_date:
            reasons.append("publish_date_corrected_from_raw_label")
        if kind != meta.document_kind:
            reasons.append("document_kind_reclassified")
        if doc_id in missing_required_attachment:
            reasons.append("missing_required_attachment")
        retained_parent = any(
            lifecycle[parent_id].retention_status in {"active", "historical"}
            for parent_id in parent_ids_by_child.get(doc_id, set())
            if parent_id in lifecycle
        )
        if decision.retention_status == "archived" and not raw_available and not retained_parent:
            reasons.append("archived_without_raw")
        decisions.append(
            QualityDecision(
                doc_id=doc_id,
                title=meta.title,
                source_url=meta.source_url,
                document_type=meta.document_type,
                before_publish_date=meta.publish_date,
                after_publish_date=publish_date,
                date_evidence=evidence,
                date_confidence=confidence,
                date_conflict=conflict,
                before_document_kind=meta.document_kind,
                document_kind=kind,
                temporal_class=decision.temporal_class,
                series_key=decision.series_key,
                retention_status=decision.retention_status,
                retention_reason=decision.retention_reason,
                canonical_doc_id=decision.canonical_doc_id,
                index_collection=collection,
                raw_available=raw_available,
                reasons=tuple(reasons),
            )
        )

    annual_groups: dict[str, int] = {}
    active_annual_groups: dict[str, int] = {}
    for item in decisions:
        if item.temporal_class == "annual":
            annual_groups[item.series_key] = annual_groups.get(item.series_key, 0) + 1
            if item.retention_status == "active":
                active_annual_groups[item.series_key] = (
                    active_annual_groups.get(item.series_key, 0) + 1
                )
    accepted = sum(meta.quality_status == "accepted" for meta in manifest.values())
    year_titles = sum(bool(_YEAR_RE.search(meta.title)) for meta in manifest.values())
    contamination = sum(
        bool(manifest[item.doc_id].file_path)
        and manifest[item.doc_id].quality_status == "accepted"
        and item.index_collection not in {"main_qa", "public_list", "historical"}
        for item in decisions
    )
    return DataQualityAudit(
        schema_version="1",
        evaluated_at=evaluated_at.isoformat(),
        manifest_fingerprint=_manifest_fingerprint(manifest_path),
        total_documents=len(manifest),
        accepted_documents=accepted,
        materialized_documents=sum(
            bool(meta.file_path and (corpus_dir / meta.file_path).is_file())
            for meta in manifest.values()
        ),
        active_documents=sum(item.retention_status == "active" for item in decisions),
        historical_documents=sum(item.retention_status == "historical" for item in decisions),
        archived_documents=sum(item.retention_status == "archived" for item in decisions),
        year_title_count=year_titles,
        year_title_ratio=(year_titles / len(manifest) if manifest else 0.0),
        annual_series_count=len(annual_groups),
        duplicate_annual_series_count=sum(count > 1 for count in annual_groups.values()),
        duplicate_active_annual_series_count=sum(
            count > 1 for count in active_annual_groups.values()
        ),
        date_correction_count=sum(
            item.before_publish_date != item.after_publish_date for item in decisions
        ),
        date_conflict_count=sum(item.date_conflict for item in decisions),
        old_annual_count=sum(
            item.temporal_class == "annual" and item.retention_status == "archived"
            for item in decisions
        ),
        old_public_count=sum(
            item.document_kind == "public_list" and item.retention_status == "archived"
            for item in decisions
        ),
        collection_contamination_count=contamination,
        unknown_type_count=sum(item.document_kind == "incomplete" for item in decisions),
        archived_without_raw_count=sum(
            "archived_without_raw" in item.reasons for item in decisions
        ),
        main_qa_documents=sum(item.index_collection == "main_qa" for item in decisions),
        public_list_documents=sum(item.index_collection == "public_list" for item in decisions),
        historical_collection_documents=sum(
            item.index_collection == "historical" for item in decisions
        ),
        decisions=tuple(decisions),
    )


def render_quality_markdown(report: DataQualityAudit) -> str:
    rows = [
        "# SUFE 语料质量与年度系列审计",
        "",
        f"- 审计时间：{report.evaluated_at}",
        f"- 文档总数：{report.total_documents}",
        f"- 有正文文件：{report.materialized_documents}",
        f"- 生命周期：active {report.active_documents} / historical {report.historical_documents} / archived {report.archived_documents}",
        f"- 标题含年份：{report.year_title_count}（{report.year_title_ratio:.1%}）",
        f"- 年度系列：{report.annual_series_count}，其中重复系列 {report.duplicate_annual_series_count}",
        f"- active 年度系列重复：{report.duplicate_active_annual_series_count}",
        f"- 日期修正：{report.date_correction_count}，日期冲突：{report.date_conflict_count}",
        f"- 旧年度通知归档：{report.old_annual_count}，旧公示归档：{report.old_public_count}",
        f"- 无法分类：{report.unknown_type_count}",
        f"- 归档但缺少 raw：{report.archived_without_raw_count}",
        f"- collection：main_qa {report.main_qa_documents} / public_list {report.public_list_documents} / historical {report.historical_collection_documents}",
        "",
        "## 年度系列与逐文档决策",
        "",
        "| doc_id | 标题 | 类型 | 日期 | 生命周期 | collection | 原因 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in report.decisions:
        title = item.title.replace("|", "\\|")
        rows.append(
            f"| {item.doc_id} | {title} | {item.document_kind} | "
            f"{item.after_publish_date} | {item.retention_status} | "
            f"{item.index_collection} | {'; '.join(item.reasons)} |"
        )
    return "\n".join(rows) + "\n"


def write_quality_audit(report: DataQualityAudit, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report.to_json(), encoding="utf-8")
    markdown_path.write_text(render_quality_markdown(report), encoding="utf-8")


def load_quality_audit(path: Path) -> DataQualityAudit:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["decisions"] = tuple(QualityDecision(**item) for item in data["decisions"])
    return DataQualityAudit(**data)
