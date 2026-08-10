"""入库管线：CrawledArticle → raw 缓存 → 质量门 → corpus/manifest/relations。

规格落点：
- §九 父子文档（attachment md 模板带父级上下文、doc_id 锚定规范化下载 URL、多父关系入 relations.jsonl）；
- §十 原始文件缓存放 data/raw/<host>/{articles,attachments}/，不进 inbox；
- §十一 去重增量（content_hash / binary_hash / text_hash 三级；解析失败不删旧有效语料）；
- §十二 质量门（quality_status != "accepted" 的文档只入 manifest 审计，不进索引）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urlparse, urlunparse

from sufe_qa.crawler.engine import CrawledArticle, CrawlReport, DownloadedAttachment
from sufe_qa.crawler.state import CrawlState
from sufe_qa.ingest.inbox import scan_sensitive, slugify
from sufe_qa.ingest.classification import (
    classify_document_kind,
    normalize_policy_name,
    standardize_topic_key,
)
from sufe_qa.ingest.lifecycle import (
    LifecycleCandidate,
    LifecycleDecision,
    resolve_lifecycle,
)
from sufe_qa.ingest.quality import assess_document
from sufe_qa.schema import (
    DocMeta,
    DocRelation,
    append_manifest,
    append_relations,
    doc_id_from,
    load_manifest,
    sha256_text,
)

# quality_status 取值（仅 "accepted" 会被 indexer 收入向量库）：
#   accepted | incomplete_document | low_quality | quarantined | duplicate |
#   scanned_pdf | legacy_doc_unparsed | unsupported_format | parse_failed | unparsed

_DOCUMENT_KIND_HINTS = frozenset(
    {
        "policy",
        "procedure",
        "faq",
        "annual_notice",
        "form",
        "manual",
        "service_guide",
        "public_list",
        "news",
        "event",
        "promotion",
        "incomplete",
    }
)


@dataclass
class IngestDecision:
    doc_id: str
    action: (
        str  # new | updated | unchanged | rejected | quarantined | relation_only | kept_previous
    )
    reason: str = ""
    title: str = ""


@dataclass
class IngestStats:
    decisions: list[IngestDecision] = field(default_factory=list)

    def add(self, doc_id: str, action: str, reason: str = "", title: str = "") -> None:
        self.decisions.append(
            IngestDecision(doc_id=doc_id, action=action, reason=reason, title=title)
        )

    def count(self, action: str) -> int:
        return sum(1 for d in self.decisions if d.action == action)


def _normalize_doc_url(url: str) -> str:
    """doc_id 锚定用的 URL 规范化：去 fragment、去尾斜杠、scheme/host 小写。"""
    p = urlparse(urldefrag(url.strip())[0])
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _doc_relpath(
    corpus_dir: Path, old: DocMeta | None, category: str, title: str, content_hash: str
) -> Path:
    """更新沿用旧路径；新文档 slug 撞车时追加哈希尾 6 位（与 inbox 逻辑一致）。

    审计行（曾被拒文档）file_path 为空，必须按新文档分配路径，
    否则会把 corpus_dir 本身当文件写。
    """
    if old is not None and old.file_path:
        return Path(old.file_path)
    rel = Path(category) / f"{slugify(title)}.md"
    if (corpus_dir / rel).exists():
        rel = Path(category) / f"{slugify(title)}-{content_hash[-6:]}.md"
    return rel


def _attachment_md(att: DownloadedAttachment, parent: CrawledArticle, text: str) -> str:
    """规格 §九模板：附件正文必须带可检索的父级上下文。"""
    return (
        f"# {att.filename}\n\n"
        f"所属通知：{parent.title}\n"
        f"发布日期：{parent.publish_date}\n"
        f"发布单位：{parent.publisher}\n"
        f"原发布页：{parent.final_url or parent.requested_url}\n"
        f"附件下载地址：{att.final_url or att.requested_url}\n\n"
        f"## 附件正文\n\n{text}\n"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _article_meta(
    *,
    doc_id: str,
    art: CrawledArticle,
    category: str,
    src: str,
    content_hash: str,
    file_path: str,
    document_kind: str,
    lifecycle: LifecycleDecision,
    source_type: str,
    source_section: str,
    scope_unit: str,
) -> DocMeta:
    return DocMeta(
        doc_id=doc_id,
        title=art.title,
        source_url=src,
        publisher=art.publisher,
        publish_date=art.publish_date,
        category=category,
        fetched_at=_now(),
        content_hash=content_hash,
        file_path=file_path,
        document_type="article",
        source_page_url=src,
        parse_status="ok",
        quality_status="accepted",
        text_hash=sha256_text(_squash(art.body_text)),
        document_kind=document_kind,
        policy_name=normalize_policy_name(art.title),
        topic_key=standardize_topic_key(art.title, normalize_policy_name(art.title), scope_unit),
        source_type=source_type,
        source_section=source_section,
        scope_unit=scope_unit,
        validity_status="unknown_validity",
        publish_date_evidence=art.publish_date_evidence,
        publish_date_confidence=art.publish_date_confidence,
        date_conflict=art.date_conflict,
        temporal_class=lifecycle.temporal_class,
        series_key=lifecycle.series_key,
        retention_status=lifecycle.retention_status,
        retention_reason=lifecycle.retention_reason,
        canonical_doc_id=lifecycle.canonical_doc_id,
    )


def ingest_crawled_articles(
    articles: list[CrawledArticle],
    *,
    category: str,
    corpus_dir: Path,
    manifest_path: Path,
    relations_path: Path,
    raw_dir: Path | None = None,
    state: CrawlState | None = None,
    report: CrawlReport | None = None,
    dry_run: bool = False,
    source_type: str = "unknown",
    source_section: str = "",
    scope_unit: str = "",
    time_policy: str = "all_history",
    evaluated_at: date | None = None,
) -> IngestStats:
    """把一批抓取结果落库。dry_run=True 时只评估与计数，不写任何文件。"""
    stats = IngestStats()
    existing = load_manifest(manifest_path)
    metas: list[DocMeta] = []
    relations: list[DocRelation] = []
    binary_seen: dict[str, str] = {}  # binary_hash -> 首个附件 doc_id（本轮）
    processed_atts: set[str] = set()
    lifecycle_date = evaluated_at or datetime.now(timezone.utc).date()

    article_kinds: dict[str, str] = {}
    article_candidates: dict[str, LifecycleCandidate] = {}
    attachment_kinds: dict[str, str] = {}
    attachment_candidates: dict[str, LifecycleCandidate] = {}
    for art in articles:
        if art.status != "ok":
            continue
        src = _normalize_doc_url(art.final_url or art.requested_url)
        doc_id = doc_id_from(src)
        hint = (art.document_kind_hint or "").strip().lower()
        document_kind = (
            hint if hint in _DOCUMENT_KIND_HINTS else classify_document_kind(art.title, art.body_text)
        )
        article_kinds[doc_id] = document_kind
        article_candidates[doc_id] = LifecycleCandidate(
            doc_id=doc_id,
            title=art.title,
            publisher=art.publisher,
            scope_unit=scope_unit,
            document_kind=document_kind,
            publish_date=art.publish_date,
        )
        for att in art.downloaded:
            if att.status != "ok" or att.parse is None:
                continue
            text = getattr(att.parse, "text", "") or ""
            if getattr(att.parse, "parse_status", "") != "ok" or not text:
                continue
            att_src = _normalize_doc_url(att.final_url or att.requested_url)
            att_doc_id = doc_id_from(att_src)
            att_kind = classify_document_kind(att.filename, text, has_valid_attachment=True)
            attachment_kinds[att_doc_id] = att_kind
            candidate = LifecycleCandidate(
                doc_id=att_doc_id,
                title=att.filename,
                publisher=art.publisher,
                scope_unit=scope_unit,
                document_kind=att_kind,
                publish_date=art.publish_date,
            )
            previous = attachment_candidates.get(att_doc_id)
            if previous is None or candidate.publish_date > previous.publish_date:
                attachment_candidates[att_doc_id] = candidate

    article_lifecycle = resolve_lifecycle(
        list(article_candidates.values()),
        time_policy=time_policy,
        evaluated_at=lifecycle_date,
    )
    attachment_lifecycle = resolve_lifecycle(
        list(attachment_candidates.values()),
        time_policy=time_policy,
        evaluated_at=lifecycle_date,
    )

    for art in articles:
        if art.status == "not_modified":
            src = _normalize_doc_url(art.final_url or art.requested_url)
            stats.add(doc_id_from(src), "unchanged", "not_modified")
            continue
        if art.status != "ok":
            continue  # 抓取失败已在 engine 报告，旧语料保持不动

        src = _normalize_doc_url(art.final_url or art.requested_url)
        doc_id = doc_id_from(src)
        document_kind = article_kinds[doc_id]
        lifecycle = article_lifecycle[doc_id]
        if raw_dir is not None and not dry_run:
            _save_raw_article(raw_dir, doc_id, art)
        has_valid_att = any(
            a.status in ("ok", "duplicate")
            and a.parse is not None
            and getattr(a.parse, "parse_status", "") == "ok"
            and getattr(a.parse, "text", "")
            for a in art.downloaded
        )
        quality = assess_document(art.title, art.body_text, has_valid_att, art.publish_date)
        if report:
            if quality.status == "incomplete_document":
                report.incomplete_documents += 1
            elif quality.status == "low_quality":
                report.low_quality_documents += 1
        if state:
            state.update(
                art.requested_url,
                parse_status=quality.status,
                text_hash=sha256_text(_squash(art.body_text)),
            )

        if scan_sensitive(art.body_text):
            if report:
                report.sensitive_quarantined += 1
            stats.add(doc_id, "quarantined", "正文命中敏感信息", art.title)
            if not dry_run:
                metas.append(
                    _audit_meta(
                        doc_id,
                        art,
                        category,
                        src,
                        "quarantined",
                        source_type=source_type,
                        source_section=source_section,
                        scope_unit=scope_unit,
                    )
                )
                _drop_old_file(corpus_dir, existing.get(doc_id))
            continue

        if quality.status != "accepted":
            old = existing.get(doc_id)
            # 重新解析被拒（附件暂时失败、质量门对旧文档的规则回归等）不是删除旧有效语料的
            # 理由（规格 §十一）：旧版本已被证明可用，保留旧行、不写审计行覆盖、不删文件
            if old and old.quality_status == "accepted" and old.content_hash:
                stats.add(doc_id, "kept_previous", f"本轮 {quality.status}，保留旧版本", art.title)
                continue
            stats.add(doc_id, "rejected", ";".join(quality.reasons) or quality.status, art.title)
            if not dry_run:
                metas.append(
                    _audit_meta(
                        doc_id,
                        art,
                        category,
                        src,
                        quality.status,
                        source_type=source_type,
                        source_section=source_section,
                        scope_unit=scope_unit,
                    )
                )
                _drop_old_file(corpus_dir, old)
            continue

        # 时间窗外文档保留 raw 与 manifest 审计，但不物化到 corpus。
        if lifecycle.retention_status == "archived":
            stats.add(doc_id, "archived", lifecycle.retention_reason, art.title)
            if not dry_run:
                metas.append(
                    _article_meta(
                        doc_id=doc_id,
                        art=art,
                        category=category,
                        src=src,
                        content_hash="",
                        file_path="",
                        document_kind=document_kind,
                        lifecycle=lifecycle,
                        source_type=source_type,
                        source_section=source_section,
                        scope_unit=scope_unit,
                    )
                )

        # active/historical 文档物化正文；历史年度版本随后进入 historical collection。
        final = f"# {art.title}\n\n{art.body_text}\n"
        ch = sha256_text(final)
        old = existing.get(doc_id)
        if lifecycle.retention_status == "archived":
            pass
        elif (
            old
            and old.content_hash == ch
            and old.file_path
            and (corpus_dir / old.file_path).exists()
        ):
            stats.add(doc_id, "unchanged", "", art.title)
            if report:
                report.unchanged_documents += 1
            metadata_updates = {
                "publisher": art.publisher,
                "publish_date": art.publish_date,
                "document_kind": document_kind,
                "policy_name": normalize_policy_name(art.title),
                "topic_key": standardize_topic_key(
                    art.title, normalize_policy_name(art.title), scope_unit
                ),
                "source_type": source_type,
                "source_section": source_section,
                "scope_unit": scope_unit,
                "publish_date_evidence": art.publish_date_evidence,
                "publish_date_confidence": art.publish_date_confidence,
                "date_conflict": art.date_conflict,
                "temporal_class": lifecycle.temporal_class,
                "series_key": lifecycle.series_key,
                "retention_status": lifecycle.retention_status,
                "retention_reason": lifecycle.retention_reason,
                "canonical_doc_id": lifecycle.canonical_doc_id,
            }
            if not dry_run and any(
                getattr(old, key) != value for key, value in metadata_updates.items()
            ):
                metas.append(replace(old, fetched_at=_now(), **metadata_updates))
        else:
            rel = _doc_relpath(corpus_dir, old, category, art.title, ch)
            if not dry_run:
                out = corpus_dir / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(final, encoding="utf-8")
                metas.append(
                    _article_meta(
                        doc_id=doc_id,
                        art=art,
                        category=category,
                        src=src,
                        content_hash=ch,
                        file_path=rel.as_posix(),
                        document_kind=document_kind,
                        lifecycle=lifecycle,
                        source_type=source_type,
                        source_section=source_section,
                        scope_unit=scope_unit,
                    )
                )
            action = "updated" if old else "new"
            stats.add(doc_id, action, "", art.title)
            if report:
                if old:
                    report.updated_documents += 1
                else:
                    report.new_documents += 1

        # 附件入库（与父文章是否被拒解耦：附件本身可能仍有独立价值）
        for att in art.downloaded:
            _ingest_attachment(
                att,
                art,
                doc_id,
                category=category,
                corpus_dir=corpus_dir,
                existing=existing,
                metas=metas,
                relations=relations,
                binary_seen=binary_seen,
                processed_atts=processed_atts,
                stats=stats,
                report=report,
                state=state,
                raw_dir=raw_dir,
                dry_run=dry_run,
                source_section=source_section,
                scope_unit=scope_unit,
                document_kinds=attachment_kinds,
                lifecycle_by_doc=attachment_lifecycle,
            )

    if not dry_run:
        append_manifest(manifest_path, metas)
        append_relations(relations_path, relations)
    if report:
        report.final_indexed += (
            stats.count("new") + stats.count("updated") + stats.count("unchanged")
        )
    return stats


def _audit_meta(
    doc_id: str,
    art: CrawledArticle,
    category: str,
    src: str,
    quality_status: str,
    *,
    source_type: str,
    source_section: str,
    scope_unit: str,
) -> DocMeta:
    """被拒/隔离文档的审计行：content_hash 置空使其不会也无法被索引。"""
    return DocMeta(
        doc_id=doc_id,
        title=art.title,
        source_url=src,
        publisher=art.publisher,
        publish_date=art.publish_date,
        category=category,
        fetched_at=_now(),
        content_hash="",
        file_path="",
        document_type="article",
        source_page_url=src,
        parse_status="ok",
        quality_status=quality_status,
        text_hash=sha256_text(_squash(art.body_text)),
        document_kind="incomplete",
        source_type=source_type,
        source_section=source_section,
        scope_unit=scope_unit,
        validity_status="unknown_validity",
        publish_date_evidence=art.publish_date_evidence,
        publish_date_confidence=art.publish_date_confidence,
        date_conflict=art.date_conflict,
    )


def _drop_old_file(corpus_dir: Path, old: DocMeta | None) -> None:
    """旧版本曾入库、本轮被拒：删除旧 corpus 文件（indexer 依 manifest 同步删向量）。"""
    if old and old.file_path:
        p = corpus_dir / old.file_path
        if p.is_file():
            p.unlink()


def _save_raw_article(raw_dir: Path, doc_id: str, art: CrawledArticle) -> None:
    d = raw_dir / "articles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{doc_id}.html").write_text(art.html, encoding="utf-8")


def _safe_raw_filename(att: DownloadedAttachment) -> str:
    """原始附件落盘文件名：安全名原样保留；百分号编码/超长的先解码再按字节截断。

    高校下载接口常把中文文件名整段百分号编码后塞进 URL 或
    Content-Disposition，直接当文件名会超过 255 字节上限
    （OSError: File name too long）。截断名追加哈希尾防撞。
    """
    from urllib.parse import unquote

    name = att.filename or ""
    if name and "/" not in name and len(name.encode("utf-8", errors="ignore")) <= 120:
        if not (name.isascii() and re.search(r"%[0-9A-Fa-f]{2}", name)):
            return name
    name = unquote(name, errors="replace").replace("/", "_").strip()
    if not name:
        return att.binary_hash[:16]
    suffix = Path(name).suffix[:16]
    stem_bytes = Path(name).stem.encode("utf-8")[:120]
    stem = stem_bytes.decode("utf-8", errors="ignore")
    return f"{stem}-{att.binary_hash[:8]}{suffix}"


def _save_raw_attachment(raw_dir: Path, att: DownloadedAttachment) -> Path:
    d = raw_dir / "attachments" / att.binary_hash[:2]
    d.mkdir(parents=True, exist_ok=True)
    path = d / _safe_raw_filename(att)
    if not path.exists() or path.stat().st_size != len(att.content):
        path.write_bytes(att.content)
    return path


def _attachment_meta(
    *,
    att_doc_id: str,
    att: DownloadedAttachment,
    parent: CrawledArticle,
    parent_doc_id: str,
    category: str,
    src: str,
    content_hash: str,
    file_path: str,
    text_hash: str,
    document_kind: str,
    lifecycle: LifecycleDecision,
    source_section: str,
    scope_unit: str,
) -> DocMeta:
    return DocMeta(
        doc_id=att_doc_id,
        title=att.filename,
        source_url=src,
        publisher=parent.publisher,
        publish_date=parent.publish_date,
        category=category,
        fetched_at=_now(),
        content_hash=content_hash,
        file_path=file_path,
        document_type="attachment",
        parent_doc_id=parent_doc_id,
        source_page_url=_normalize_doc_url(parent.final_url or parent.requested_url),
        download_url=src,
        attachment_name=att.filename,
        mime_type=att.mime_type,
        parse_status="ok",
        quality_status="accepted",
        binary_hash=att.binary_hash,
        text_hash=text_hash,
        document_kind=document_kind,
        policy_name=normalize_policy_name(att.filename or parent.title),
        topic_key=standardize_topic_key(
            att.filename or parent.title,
            normalize_policy_name(att.filename or parent.title),
            scope_unit,
        ),
        source_type="attachment",
        source_section=source_section,
        scope_unit=scope_unit,
        validity_status="unknown_validity",
        publish_date_evidence=parent.publish_date_evidence,
        publish_date_confidence=parent.publish_date_confidence,
        date_conflict=parent.date_conflict,
        temporal_class=lifecycle.temporal_class,
        series_key=lifecycle.series_key,
        retention_status=lifecycle.retention_status,
        retention_reason=lifecycle.retention_reason,
        canonical_doc_id=lifecycle.canonical_doc_id,
    )


def _ingest_attachment(
    att: DownloadedAttachment,
    parent: CrawledArticle,
    parent_doc_id: str,
    *,
    category: str,
    corpus_dir: Path,
    existing: dict[str, DocMeta],
    metas: list[DocMeta],
    relations: list[DocRelation],
    binary_seen: dict[str, str],
    processed_atts: set[str],
    stats: IngestStats,
    report: CrawlReport | None,
    state: CrawlState | None,
    raw_dir: Path | None,
    dry_run: bool,
    source_section: str,
    scope_unit: str,
    document_kinds: dict[str, str],
    lifecycle_by_doc: dict[str, LifecycleDecision],
) -> None:
    if att.status == "duplicate":
        # 本轮内同 binary 的另一 URL：关系挂到首个 canonical 文档，不重复嵌入
        canonical = binary_seen.get(att.binary_hash)
        if canonical:
            relations.append(DocRelation(parent_doc_id=parent_doc_id, child_doc_id=canonical))
            stats.add(canonical, "relation_only", f"duplicate of {canonical}", att.filename)
        return
    if att.status != "ok":
        return  # 下载失败 engine 已报告

    src = _normalize_doc_url(att.final_url or att.requested_url)
    att_doc_id = doc_id_from(src)
    binary_seen.setdefault(att.binary_hash, att_doc_id)
    if state:
        state.update(
            att.requested_url,
            final_url=att.final_url,
            binary_hash=att.binary_hash,
        )
    if raw_dir is not None and not dry_run:
        _save_raw_attachment(raw_dir, att)

    if att_doc_id in processed_atts:
        relations.append(DocRelation(parent_doc_id=parent_doc_id, child_doc_id=att_doc_id))
        stats.add(att_doc_id, "relation_only", "同附件多父引用", att.filename)
        return
    processed_atts.add(att_doc_id)

    parse_status = getattr(att.parse, "parse_status", "unparsed") if att.parse else "unparsed"
    text = (getattr(att.parse, "text", "") or "") if att.parse else ""
    text_hash = sha256_text(_squash(text)) if text else ""
    if state:
        state.update(att.requested_url, text_hash=text_hash or None, parse_status=parse_status)
    old = existing.get(att_doc_id)

    if parse_status != "ok" or not text:
        # 解析不可用：旧有有效语料必须保留（规格 §十一），否则只写审计行
        if old and old.quality_status == "accepted":
            stats.add(att_doc_id, "kept_previous", f"本轮 {parse_status}，保留旧版本", att.filename)
            relations.append(DocRelation(parent_doc_id=parent_doc_id, child_doc_id=att_doc_id))
            return
        stats.add(att_doc_id, "rejected", parse_status, att.filename)
        if not dry_run:
            metas.append(
                DocMeta(
                    doc_id=att_doc_id,
                    title=att.filename,
                    source_url=src,
                    publisher=parent.publisher,
                    publish_date=parent.publish_date,
                    category=category,
                    fetched_at=_now(),
                    content_hash="",
                    file_path="",
                    document_type="attachment",
                    parent_doc_id=parent_doc_id,
                    source_page_url=_normalize_doc_url(parent.final_url or parent.requested_url),
                    download_url=src,
                    attachment_name=att.filename,
                    mime_type=att.mime_type,
                    parse_status=parse_status,
                    quality_status=parse_status,
                    binary_hash=att.binary_hash,
                    text_hash=text_hash,
                    document_kind="incomplete",
                    source_type="attachment",
                    source_section=source_section,
                    scope_unit=scope_unit,
                    validity_status="unknown_validity",
                    publish_date_evidence=parent.publish_date_evidence,
                    publish_date_confidence=parent.publish_date_confidence,
                    date_conflict=parent.date_conflict,
                )
            )
        relations.append(DocRelation(parent_doc_id=parent_doc_id, child_doc_id=att_doc_id))
        return

    if scan_sensitive(text):
        if report:
            report.sensitive_quarantined += 1
        stats.add(att_doc_id, "quarantined", "附件命中敏感信息", att.filename)
        if not dry_run:
            metas.append(
                DocMeta(
                    doc_id=att_doc_id,
                    title=att.filename,
                    source_url=src,
                    publisher=parent.publisher,
                    publish_date=parent.publish_date,
                    category=category,
                    fetched_at=_now(),
                    content_hash="",
                    file_path="",
                    document_type="attachment",
                    parent_doc_id=parent_doc_id,
                    source_page_url=_normalize_doc_url(parent.final_url or parent.requested_url),
                    download_url=src,
                    attachment_name=att.filename,
                    mime_type=att.mime_type,
                    parse_status="ok",
                    quality_status="quarantined",
                    binary_hash=att.binary_hash,
                    text_hash=text_hash,
                    document_kind="incomplete",
                    source_type="attachment",
                    source_section=source_section,
                    scope_unit=scope_unit,
                    validity_status="unknown_validity",
                    publish_date_evidence=parent.publish_date_evidence,
                    publish_date_confidence=parent.publish_date_confidence,
                    date_conflict=parent.date_conflict,
                )
            )
        return

    document_kind = document_kinds[att_doc_id]
    lifecycle = lifecycle_by_doc[att_doc_id]
    if lifecycle.retention_status == "archived":
        stats.add(att_doc_id, "archived", lifecycle.retention_reason, att.filename)
        if not dry_run:
            metas.append(
                _attachment_meta(
                    att_doc_id=att_doc_id,
                    att=att,
                    parent=parent,
                    parent_doc_id=parent_doc_id,
                    category=category,
                    src=src,
                    content_hash="",
                    file_path="",
                    text_hash=text_hash,
                    document_kind=document_kind,
                    lifecycle=lifecycle,
                    source_section=source_section,
                    scope_unit=scope_unit,
                )
            )
        relations.append(DocRelation(parent_doc_id=parent_doc_id, child_doc_id=att_doc_id))
        return

    md = _attachment_md(att, parent, text)
    ch = sha256_text(md)
    if (
        old
        and old.binary_hash == att.binary_hash
        and old.content_hash == ch
        and old.file_path
        and (corpus_dir / old.file_path).exists()
    ):
        stats.add(att_doc_id, "unchanged", "", att.filename)
        if report:
            report.unchanged_documents += 1
    elif (
        old
        and old.quality_status == "accepted"
        and old.text_hash == text_hash
        and old.file_path
        and (corpus_dir / old.file_path).exists()
    ):
        # binary 变化但标准化文本相同：复用文本与向量，仅刷新 binary_hash 审计
        stats.add(att_doc_id, "unchanged", "binary 变化 text 相同，复用", att.filename)
        if report:
            report.unchanged_documents += 1
        if not dry_run:
            metas.append(
                _refresh_att_meta(
                    old,
                    att,
                    src,
                    parent_doc_id,
                    parent,
                    document_kind=document_kind,
                    lifecycle=lifecycle,
                )
            )
    else:
        rel = _doc_relpath(corpus_dir, old, category, att.filename, ch)
        if not dry_run:
            out = corpus_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8")
            metas.append(
                _attachment_meta(
                    att_doc_id=att_doc_id,
                    att=att,
                    parent=parent,
                    parent_doc_id=parent_doc_id,
                    category=category,
                    src=src,
                    content_hash=ch,
                    file_path=rel.as_posix(),
                    text_hash=text_hash,
                    document_kind=document_kind,
                    lifecycle=lifecycle,
                    source_section=source_section,
                    scope_unit=scope_unit,
                )
            )
        action = "updated" if old else "new"
        stats.add(att_doc_id, action, "", att.filename)
        if report:
            if old:
                report.updated_documents += 1
            else:
                report.new_documents += 1
    relations.append(DocRelation(parent_doc_id=parent_doc_id, child_doc_id=att_doc_id))


def _refresh_att_meta(
    old: DocMeta,
    att: DownloadedAttachment,
    src: str,
    parent_doc_id: str,
    parent: CrawledArticle,
    *,
    document_kind: str,
    lifecycle: LifecycleDecision,
) -> DocMeta:
    """binary 变 text 不变的元数据刷新：content_hash 保持旧值，indexer 不会重嵌入。"""
    return DocMeta(
        doc_id=old.doc_id,
        title=old.title,
        source_url=old.source_url,
        publisher=old.publisher,
        publish_date=old.publish_date,
        category=old.category,
        fetched_at=_now(),
        content_hash=old.content_hash,
        file_path=old.file_path,
        document_type="attachment",
        parent_doc_id=parent_doc_id,
        source_page_url=old.source_page_url
        or _normalize_doc_url(parent.final_url or parent.requested_url),
        download_url=src,
        attachment_name=att.filename or old.attachment_name,
        mime_type=att.mime_type or old.mime_type,
        parse_status="ok",
        quality_status="accepted",
        binary_hash=att.binary_hash,
        text_hash=old.text_hash,
        document_kind=document_kind,
        policy_name=old.policy_name,
        document_number=old.document_number,
        effective_date=old.effective_date,
        valid_until=old.valid_until,
        revision_year=old.revision_year,
        supersedes=old.supersedes,
        superseded_by=old.superseded_by,
        applicable_student_type=old.applicable_student_type,
        applicable_school_year=old.applicable_school_year,
        source_type=old.source_type or "attachment",
        source_section=old.source_section,
        scope_unit=old.scope_unit,
        topic_key=old.topic_key,
        validity_status=old.validity_status,
        validity_confidence=old.validity_confidence,
        validity_evidence=old.validity_evidence,
        relation_confidence=old.relation_confidence,
        relation_evidence=old.relation_evidence,
        index_collection=old.index_collection,
        publish_date_evidence=old.publish_date_evidence or parent.publish_date_evidence,
        publish_date_confidence=max(old.publish_date_confidence, parent.publish_date_confidence),
        date_conflict=old.date_conflict or parent.date_conflict,
        temporal_class=lifecycle.temporal_class,
        series_key=lifecycle.series_key,
        retention_status=lifecycle.retention_status,
        retention_reason=lifecycle.retention_reason,
        canonical_doc_id=lifecycle.canonical_doc_id,
    )
