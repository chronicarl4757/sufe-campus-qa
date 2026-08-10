"""显式 allowlist 驱动的本地权威资料导入。"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import yaml

from sufe_qa.config import CATEGORIES
from sufe_qa.indexing.collections import collection_for_kind
from sufe_qa.ingest.attachment_parsers import parse_attachment
from sufe_qa.ingest.classification import normalize_policy_name, standardize_topic_key
from sufe_qa.ingest.inbox import scan_sensitive, slugify
from sufe_qa.ingest.lifecycle import series_key_for, temporal_class_for
from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text

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
    existing_by_content = {meta.content_hash: meta.doc_id for meta in existing.values() if meta.content_hash}
    existing_by_text = {meta.text_hash: meta.doc_id for meta in existing.values() if meta.text_hash}
    candidates: list[ManualImportCandidate] = []
    decisions: list[ManualImportDecision] = []

    paths = sorted(path for path in source_root.rglob("*") if path.is_file())
    for path in paths:
        relative_path = path.relative_to(source_root).as_posix()
        entry = entries.get(relative_path)
        if entry is None:
            decisions.append(ManualImportDecision(relative_path, "excluded", "not_allowlisted"))
            continue
        if _DRAFT_RE.search(path.name):
            decisions.append(ManualImportDecision(relative_path, "excluded", "draft_filename"))
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
        final = f"# {title}\n\n{text}\n"
        content_hash = sha256_text(final)
        text_hash = sha256_text(text)
        duplicate_doc_id = existing_by_content.get(content_hash) or existing_by_text.get(text_hash)
        source_url = f"manual://{namespace}/{quote(relative_path, safe='/')}"
        doc_id = doc_id_from(source_url)
        old = existing.get(doc_id)
        if duplicate_doc_id or (old and old.content_hash == content_hash):
            decisions.append(
                ManualImportDecision(
                    relative_path,
                    "duplicate",
                    "duplicate_content",
                    doc_id=doc_id,
                    duplicate_doc_id=duplicate_doc_id or doc_id,
                    parse_status=parsed.parse_status,
                    char_count=len(text),
                    binary_hash=binary_hash,
                    text_hash=text_hash,
                )
            )
            continue

        publish_date, date_evidence, date_confidence = _publish_date_from_filename(title)
        collection = collection_for_kind(entry.document_kind, entry.retention_status) or "none"
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
        candidates.append(ManualImportCandidate(meta=meta, content=final))
        decisions.append(
            ManualImportDecision(
                relative_path,
                "accepted",
                "allowlisted_student_material",
                doc_id=doc_id,
                parse_status=parsed.parse_status,
                char_count=len(text),
                binary_hash=binary_hash,
                text_hash=text_hash,
            )
        )
        existing_by_content[content_hash] = doc_id
        existing_by_text[text_hash] = doc_id

    if apply:
        for candidate in candidates:
            output = corpus_dir / candidate.meta.file_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(candidate.content, encoding="utf-8")
        append_manifest(manifest_path, [candidate.meta for candidate in candidates])

    counts = {status: 0 for status in ("accepted", "duplicate", "excluded", "incomplete", "quarantined")}
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
        persisted=len(candidates) if apply else 0,
        duplicates=counts["duplicate"],
        excluded=counts["excluded"],
        incomplete=counts["incomplete"],
        quarantined=counts["quarantined"],
        decisions=tuple(decisions),
    )
    if report_path is not None:
        _write_report(report_path, report)
    return report
