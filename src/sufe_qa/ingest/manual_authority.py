"""显式 allowlist 驱动的本地权威资料导入。"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import yaml

from sufe_qa.config import CATEGORIES
from sufe_qa.indexing.collections import collection_for_kind
from sufe_qa.ingest.attachment_parsers import parse_attachment
from sufe_qa.ingest.classification import (
    classify_document_kind,
    normalize_policy_name,
    standardize_topic_key,
)
from sufe_qa.ingest.inbox import scan_sensitive, slugify
from sufe_qa.ingest.lifecycle import series_key_for, temporal_class_for
from sufe_qa.schema import (
    DocMeta,
    DocRelation,
    append_manifest,
    append_relations,
    default_relations_path,
    doc_id_from,
    load_manifest,
    sha256_text,
)

_DOCUMENT_KINDS = frozenset(
    {
        "policy",
        "procedure",
        "faq",
        "annual_notice",
        "form",
        "manual",
        "service_guide",
        "public_list",
    }
)
_RETENTION_STATUSES = frozenset({"active", "historical"})
_DRAFT_RE = re.compile(r"征求意见稿|征求意见|草案")
_LEADING_DATE_RE = re.compile(r"^(?P<raw>(?:19|20)\d{6})")
_REVISION_YEAR_RE = re.compile(r"((?:19|20)\d{2})\s*年[^）\n]{0,12}修订")
_HARD_EXCLUDE_RE = re.compile(
    r"党务|党建|党支部|党员|党委|纪委|巡察|工会|人事|"
    r"教职工(?:绩效|考核|薪酬)|教师(?:绩效|薪酬)|科研保密|保密管理|"
    r"差旅费|普通报销|财务报销"
)
_DECLARED_KIND_CONFLICTS = frozenset({"news", "event", "promotion", "public_list"})
_MIN_TEXT_CHARS = 80


@dataclass(frozen=True)
class ManualAuthorityEntry:
    path: str
    category: str
    publisher: str
    scope_unit: str
    source_section: str
    document_kind: str
    retention_status: str


@dataclass(frozen=True)
class ManualImportDecision:
    relative_path: str
    status: str
    reason: str
    doc_id: str = ""
    duplicate_doc_id: str = ""
    parse_status: str = ""
    char_count: int = 0
    binary_hash: str = ""
    text_hash: str = ""


@dataclass(frozen=True)
class ManualImportCandidate:
    meta: DocMeta
    content: str


@dataclass(frozen=True)
class ManualImportReport:
    source_root: str
    rules_path: str
    namespace: str
    evaluated_at: str
    apply: bool
    total_files: int
    accepted: int
    persisted: int
    duplicates: int
    excluded: int
    incomplete: int
    quarantined: int
    revoked: int
    missing: int
    decisions: tuple[ManualImportDecision, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalized_rule_path(value: object) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"非法规则路径: {raw}")
    normalized = path.as_posix()
    if normalized.startswith("/"):
        raise ValueError(f"非法规则路径: {raw}")
    return normalized


def _required_text(raw: dict[str, object], name: str, path: str) -> str:
    value = str(raw.get(name) or "").strip()
    if not value:
        raise ValueError(f"规则 {path} 缺少 {name}")
    return value


def load_manual_authority_rules(path: Path) -> tuple[str, dict[str, ManualAuthorityEntry]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if str(data.get("schema_version")) != "1":
        raise ValueError("不支持的人工资料规则 schema_version")
    namespace = str(data.get("namespace") or "").strip()
    if not namespace or "/" in namespace or ".." in namespace:
        raise ValueError("非法 namespace")
    entries: dict[str, ManualAuthorityEntry] = {}
    for raw in data.get("entries") or []:
        if not isinstance(raw, dict):
            raise ValueError("entries 必须是对象列表")
        relative_path = _normalized_rule_path(raw.get("path"))
        if relative_path in entries:
            raise ValueError(f"重复规则路径: {relative_path}")
        category = _required_text(raw, "category", relative_path)
        document_kind = _required_text(raw, "document_kind", relative_path)
        retention_status = _required_text(raw, "retention_status", relative_path)
        if category not in CATEGORIES:
            raise ValueError(f"规则 {relative_path} 非法分类: {category}")
        if document_kind not in _DOCUMENT_KINDS:
            raise ValueError(f"规则 {relative_path} 非法 document_kind: {document_kind}")
        if retention_status not in _RETENTION_STATUSES:
            raise ValueError(f"规则 {relative_path} 非法 retention_status: {retention_status}")
        entries[relative_path] = ManualAuthorityEntry(
            path=relative_path,
            category=category,
            publisher=_required_text(raw, "publisher", relative_path),
            scope_unit=_required_text(raw, "scope_unit", relative_path),
            source_section=_required_text(raw, "source_section", relative_path),
            document_kind=document_kind,
            retention_status=retention_status,
        )
    return namespace, entries


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+$", "", line) for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _binary_hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _publish_date_from_filename(title: str) -> tuple[str, str, float]:
    match = _LEADING_DATE_RE.match(title)
    if not match:
        return "unknown", "", 0.0
    raw = match.group("raw")
    try:
        value = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()
    except ValueError:
        return "unknown", "", 0.0
    return value, f"文件名前缀：{raw}", 0.9


def _revision_year(title: str) -> int | None:
    match = _REVISION_YEAR_RE.search(title)
    return int(match.group(1)) if match else None


def _write_report(path: Path, report: ManualImportReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _metadata_matches_entry(
    meta: DocMeta,
    entry: ManualAuthorityEntry,
    index_collection: str,
    binary_hash: str,
) -> bool:
    return (
        meta.category == entry.category
        and meta.publisher == entry.publisher
        and meta.scope_unit == entry.scope_unit
        and meta.source_section == entry.source_section
        and meta.document_kind == entry.document_kind
        and meta.retention_status == entry.retention_status
        and meta.index_collection == index_collection
        and meta.binary_hash == binary_hash
    )


def _safe_corpus_path(corpus_dir: Path, relative_path: str) -> Path | None:
    """把 manifest 相对路径收敛在 corpus 内，并拒绝现有符号链接逃逸。"""
    path = Path(relative_path)
    if not relative_path or path.is_absolute() or ".." in path.parts:
        return None
    root = corpus_dir.resolve()
    resolved = (root / path).resolve(strict=False)
    if not resolved.is_relative_to(root):
        return None
    return resolved


def _reusable_for_dedup(meta: DocMeta, corpus_dir: Path) -> bool:
    """只有实际存在、通过质量门且仍属于有效 collection 的正文才可参与去重。"""
    materialized = _safe_corpus_path(corpus_dir, meta.file_path)
    return bool(
        materialized
        and materialized.is_file()
        and meta.parse_status == "ok"
        and meta.quality_status == "accepted"
        and meta.content_hash
        and meta.text_hash
        and collection_for_kind(meta.document_kind, meta.retention_status)
    )


def _manual_relative_path(source_url: str, prefix: str) -> str:
    if not source_url.startswith(prefix):
        return ""
    try:
        return _normalized_rule_path(unquote(source_url.removeprefix(prefix)))
    except ValueError:
        return ""


def _duplicate_alias_matches(old: DocMeta | None, alias: DocMeta) -> bool:
    return bool(
        old
        and old.quality_status == "duplicate"
        and old.parse_status == "duplicate"
        and old.text_hash == alias.text_hash
        and old.binary_hash == alias.binary_hash
        and old.canonical_doc_id == alias.canonical_doc_id
        and old.retention_status == "archived"
        and old.index_collection == "none"
        and not old.file_path
        and not old.content_hash
    )


def import_manual_authority_files(
    source_root: Path,
    rules_path: Path,
    corpus_dir: Path,
    manifest_path: Path,
    *,
    report_path: Path | None = None,
    apply: bool = False,
    evaluated_at: str | None = None,
) -> ManualImportReport:
    """审计并可选持久化一棵本地资料目录；未列入 allowlist 的文件永不入库。"""
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ValueError(f"资料目录不存在: {source_root}")
    namespace, entries = load_manual_authority_rules(rules_path)
    evaluated = evaluated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = load_manifest(manifest_path)
    reusable = {
        doc_id: meta for doc_id, meta in existing.items() if _reusable_for_dedup(meta, corpus_dir)
    }
    existing_by_content = {
        meta.content_hash: meta.doc_id for meta in reusable.values() if meta.content_hash
    }
    existing_by_text = {meta.text_hash: meta.doc_id for meta in reusable.values() if meta.text_hash}
    candidates: list[ManualImportCandidate] = []
    duplicate_aliases: list[DocMeta] = []
    duplicate_relations: list[DocRelation] = []
    revocations: list[tuple[DocMeta, DocMeta]] = []
    decisions: list[ManualImportDecision] = []

    manual_prefix = f"manual://{namespace}/"
    expected_urls = {
        f"{manual_prefix}{quote(relative_path, safe='/')}" for relative_path in entries
    }
    stale_by_path = {
        relative_path: meta
        for meta in existing.values()
        if meta.source_type == "manual_upload"
        and meta.source_url.startswith(manual_prefix)
        and meta.source_url not in expected_urls
        and (relative_path := _manual_relative_path(meta.source_url, manual_prefix))
    }

    paths = sorted(path for path in source_root.rglob("*") if path.is_file())
    discovered_paths: set[str] = set()
    for path in paths:
        relative_path = path.relative_to(source_root).as_posix()
        discovered_paths.add(relative_path)
        entry = entries.get(relative_path)
        if entry is None:
            if relative_path not in stale_by_path:
                decisions.append(ManualImportDecision(relative_path, "excluded", "not_allowlisted"))
            continue
        if path.is_symlink():
            decisions.append(
                ManualImportDecision(relative_path, "excluded", "unsafe_source_symlink")
            )
            continue
        if _DRAFT_RE.search(path.name):
            decisions.append(ManualImportDecision(relative_path, "excluded", "draft_filename"))
            continue
        source_url = f"{manual_prefix}{quote(relative_path, safe='/')}"
        doc_id = doc_id_from(source_url)
        old = existing.get(doc_id)
        if old and old.file_path and _safe_corpus_path(corpus_dir, old.file_path) is None:
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "quarantined",
                    "unsafe_existing_file_path",
                    doc_id=doc_id,
                )
            )
            continue
        binary = path.read_bytes()
        binary_hash = _binary_hash(binary)
        parsed = parse_attachment(path.name, binary)
        text = _normalize_text(parsed.text)
        if parsed.parse_status != "ok" or len(text) < _MIN_TEXT_CHARS:
            reason = f"parse_{parsed.parse_status}"
            if parsed.parse_status == "ok":
                reason = "parse_text_too_short"
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "incomplete",
                    reason,
                    parse_status=parsed.parse_status,
                    char_count=len(text),
                    binary_hash=binary_hash,
                )
            )
            continue
        if scan_sensitive(text):
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "quarantined",
                    "sensitive_content",
                    parse_status=parsed.parse_status,
                    char_count=len(text),
                    binary_hash=binary_hash,
                )
            )
            continue

        title = path.stem.strip()
        # 硬排除只判断资料所属路径和标题。学生制度正文可能合法引用党委审议、
        # 人事认定或财务报销标准，不能据此把整份学生政策误判为内部制度。
        subject_probe = f"{relative_path}\n{title}"
        if _HARD_EXCLUDE_RE.search(subject_probe):
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "excluded",
                    "hard_excluded_subject",
                    doc_id=doc_id,
                    parse_status=parsed.parse_status,
                    char_count=len(text),
                    binary_hash=binary_hash,
                )
            )
            continue
        inferred_kind = classify_document_kind(title, text)
        if inferred_kind in _DECLARED_KIND_CONFLICTS and inferred_kind != entry.document_kind:
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "excluded",
                    f"declared_kind_conflict:{inferred_kind}",
                    doc_id=doc_id,
                    parse_status=parsed.parse_status,
                    char_count=len(text),
                    binary_hash=binary_hash,
                )
            )
            continue
        final = f"# {title}\n\n{text}\n"
        content_hash = sha256_text(final)
        text_hash = sha256_text(text)
        same_source_content = bool(
            old and (old.content_hash == content_hash or old.text_hash == text_hash)
        )
        duplicate_doc_id = existing_by_content.get(content_hash) or existing_by_text.get(text_hash)
        if duplicate_doc_id == doc_id:
            duplicate_doc_id = doc_id if same_source_content else None
        if (
            old
            and old.quality_status == "duplicate"
            and old.canonical_doc_id in reusable
            and same_source_content
        ):
            duplicate_doc_id = old.canonical_doc_id
        collection = collection_for_kind(entry.document_kind, entry.retention_status) or "none"
        publish_date, date_evidence, date_confidence = _publish_date_from_filename(title)
        rel_path = (
            Path(old.file_path)
            if old and old.file_path
            else Path(entry.category) / f"{slugify(title)}-{doc_id}.md"
        )
        meta = DocMeta(
            doc_id=doc_id,
            title=title,
            source_url=source_url,
            publisher=entry.publisher,
            publish_date=publish_date,
            category=entry.category,
            fetched_at=evaluated,
            content_hash=content_hash,
            file_path=rel_path.as_posix(),
            document_type="attachment",
            attachment_name=path.name,
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            parse_status=parsed.parse_status,
            quality_status="accepted",
            binary_hash=binary_hash,
            text_hash=text_hash,
            document_kind=entry.document_kind,
            policy_name=normalize_policy_name(title),
            revision_year=_revision_year(title),
            source_type="manual_upload",
            source_section=entry.source_section,
            scope_unit=entry.scope_unit,
            topic_key=standardize_topic_key(title, normalize_policy_name(title), entry.scope_unit),
            validity_status="unknown_validity",
            index_collection=collection,
            publish_date_evidence=date_evidence,
            publish_date_confidence=date_confidence,
            temporal_class=temporal_class_for(entry.document_kind, title),
            series_key=series_key_for(
                title, publisher=entry.publisher, scope_unit=entry.scope_unit
            ),
            retention_status=entry.retention_status,
            retention_reason="manual_allowlist",
            canonical_doc_id=doc_id if entry.retention_status == "active" else "",
        )
        if old is not None and same_source_content:
            meta = replace(
                meta,
                document_number=old.document_number,
                effective_date=old.effective_date,
                valid_until=old.valid_until,
                supersedes=old.supersedes,
                superseded_by=old.superseded_by,
                applicable_student_type=old.applicable_student_type,
                applicable_school_year=old.applicable_school_year,
                validity_status=old.validity_status,
                validity_confidence=old.validity_confidence,
                validity_evidence=old.validity_evidence,
                relation_confidence=old.relation_confidence,
                relation_evidence=old.relation_evidence,
            )
        if duplicate_doc_id and duplicate_doc_id != doc_id:
            alias = replace(
                meta,
                content_hash="",
                file_path="",
                parse_status="duplicate",
                quality_status="duplicate",
                retention_status="archived",
                retention_reason="duplicate_content",
                index_collection="none",
                canonical_doc_id=duplicate_doc_id,
            )
            if not _duplicate_alias_matches(old, alias):
                duplicate_aliases.append(alias)
            duplicate_relations.append(
                DocRelation(
                    parent_doc_id=doc_id,
                    child_doc_id=duplicate_doc_id,
                    relation="same_content_as",
                    evidence=f"text_hash:{text_hash}",
                    confidence=1.0,
                    created_at=evaluated,
                )
            )
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "duplicate",
                    "duplicate_content",
                    doc_id=doc_id,
                    duplicate_doc_id=duplicate_doc_id,
                    parse_status=parsed.parse_status,
                    char_count=len(text),
                    binary_hash=binary_hash,
                    text_hash=text_hash,
                )
            )
            continue
        if (
            duplicate_doc_id == doc_id
            and old is not None
            and _metadata_matches_entry(old, entry, collection, binary_hash)
        ):
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "duplicate",
                    "duplicate_content",
                    doc_id=doc_id,
                    duplicate_doc_id=doc_id,
                    parse_status=parsed.parse_status,
                    char_count=len(text),
                    binary_hash=binary_hash,
                    text_hash=text_hash,
                )
            )
            continue
        candidates.append(ManualImportCandidate(meta=meta, content=final))
        decisions.append(
            ManualImportDecision(
                relative_path,
                "accepted",
                "metadata_refresh" if same_source_content else "allowlisted_student_material",
                doc_id=doc_id,
                parse_status=parsed.parse_status,
                char_count=len(text),
                binary_hash=binary_hash,
                text_hash=text_hash,
            )
        )
        existing_by_content[content_hash] = doc_id
        existing_by_text[text_hash] = doc_id

    for relative_path in sorted(set(entries) - discovered_paths):
        decisions.append(
            ManualImportDecision(relative_path, "missing", "allowlisted_file_missing")
        )

    for relative_path, old in sorted(stale_by_path.items()):
        if (
            old.retention_status == "archived"
            and old.retention_reason == "manual_allowlist_revoked"
            and not old.file_path
            and not old.content_hash
        ):
            continue
        tombstone = replace(
            old,
            fetched_at=evaluated,
            content_hash="",
            file_path="",
            retention_status="archived",
            retention_reason="manual_allowlist_revoked",
            index_collection="none",
            canonical_doc_id="",
        )
        revocations.append((old, tombstone))
        decisions.append(
            ManualImportDecision(
                relative_path,
                "revoked",
                "manual_allowlist_revoked",
                doc_id=old.doc_id,
            )
        )

    if apply:
        for candidate in candidates:
            output = _safe_corpus_path(corpus_dir, candidate.meta.file_path)
            if output is None:
                raise ValueError(f"拒绝写入 corpus 外路径: {candidate.meta.file_path}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(candidate.content, encoding="utf-8")
        for old, _tombstone in revocations:
            old_path = _safe_corpus_path(corpus_dir, old.file_path)
            if old_path is not None and old_path.is_file():
                old_path.unlink()
        append_manifest(
            manifest_path,
            [candidate.meta for candidate in candidates]
            + duplicate_aliases
            + [tombstone for _old, tombstone in revocations],
        )
        append_relations(default_relations_path(manifest_path), duplicate_relations)

    counts = {
        status: 0
        for status in (
            "accepted",
            "duplicate",
            "excluded",
            "incomplete",
            "quarantined",
            "revoked",
            "missing",
        )
    }
    for decision in decisions:
        counts[decision.status] += 1
    report = ManualImportReport(
        source_root=str(source_root),
        rules_path=str(rules_path.resolve()),
        namespace=namespace,
        evaluated_at=evaluated,
        apply=apply,
        total_files=len(paths),
        accepted=counts["accepted"],
        persisted=(len(candidates) + len(duplicate_aliases) + len(revocations)) if apply else 0,
        duplicates=counts["duplicate"],
        excluded=counts["excluded"],
        incomplete=counts["incomplete"],
        quarantined=counts["quarantined"],
        revoked=counts["revoked"],
        missing=counts["missing"],
        decisions=tuple(decisions),
    )
    if report_path is not None:
        _write_report(report_path, report)
    return report
