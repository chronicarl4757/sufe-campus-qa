"""权威来源清单的端到端抓取：adapter → SafeFetcher → ingest.pipeline。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sufe_qa.config import Settings
from sufe_qa.crawler.adapter_engine import (
    AdapterCrawlOptions,
    _article_to_crawled,
    crawl_adapter_section,
)
from sufe_qa.crawler.adapters import ArticleSpec, PageContent, PageSpec, SectionSpec
from sufe_qa.crawler.authority import AuthoritySource, adapter_for_source
from sufe_qa.crawler.engine import CrawlReport
from sufe_qa.crawler.fetcher import SafeFetcher
from sufe_qa.crawler.state import CrawlState
from sufe_qa.ingest.attachment_parsers import parse_attachment as _parse_attachment
from sufe_qa.ingest.pipeline import ingest_crawled_articles
from sufe_qa.schema import default_relations_path, load_manifest


@dataclass(frozen=True)
class AuthorityRunOptions:
    delay: float = 1.0
    max_list_pages: int = 1000
    max_articles: int | None = None
    max_attachment_bytes: int = 30_000_000
    max_attachments_per_article: int = 20
    since: str | None = None
    download_attachments: bool = True
    dry_run: bool = False
    report_dir: Path | None = None
    refresh_articles: bool = False
    retry_batch_size: int = 25


def crawl_authority_sources(
    settings: Settings,
    sources: list[AuthoritySource],
    *,
    options: AuthorityRunOptions | None = None,
    parse_attachment=_parse_attachment,
) -> list[CrawlReport]:
    """执行显式权威来源清单；每个站点共用 SafeFetcher、state 和报告。"""
    options = options or AuthorityRunOptions()
    reports: list[CrawlReport] = []
    for source in sources:
        host = urlparse(source.homepage or source.sections[0].list_url).netloc
        report = CrawlReport(host=host)
        report.categories_found += len(source.sections)
        state = CrawlState.load(settings.data_dir / "crawl_state" / f"{host}.json")
        adapter = adapter_for_source(source)
        with SafeFetcher(
            delay=options.delay,
            allowed_hosts={host, *source.allowed_hosts},
            max_attachment_bytes=options.max_attachment_bytes,
        ) as fetcher:
            for section in source.sections:
                articles = crawl_adapter_section(
                    adapter,
                    section,
                    fetcher,
                    options=AdapterCrawlOptions(
                        max_list_pages=options.max_list_pages,
                        max_articles=options.max_articles,
                        max_attachments_per_article=options.max_attachments_per_article,
                        since=options.since,
                        download_attachments=options.download_attachments,
                        use_conditional_requests=not options.refresh_articles,
                    ),
                    state=state,
                    parse_attachment=parse_attachment,
                    report=report,
                )
                ingest_crawled_articles(
                    articles,
                    category=section.category,
                    corpus_dir=settings.corpus_dir,
                    manifest_path=settings.manifest_path,
                    relations_path=default_relations_path(settings.manifest_path),
                    raw_dir=None if options.dry_run else settings.data_dir / "raw" / host,
                    state=state,
                    report=report,
                    dry_run=options.dry_run,
                    source_type=section.source_type,
                    source_section=section.name,
                    scope_unit=section.scope_unit,
                    time_policy=section.time_policy,
                )
        report.not_seen_documents += len(state.finalize())
        if not options.dry_run:
            state.save()
        if options.report_dir is not None and not options.dry_run:
            report.save(options.report_dir)
        reports.append(report)
    return reports


def retry_attachments_from_raw(
    settings: Settings,
    source: AuthoritySource,
    *,
    options: AuthorityRunOptions | None = None,
    parse_attachment=_parse_attachment,
) -> list[CrawlReport]:
    """从已保存文章 HTML 重放附件候选，不重复抓列表页和文章正文。"""
    options = options or AuthorityRunOptions()
    host = urlparse(source.homepage).netloc
    adapter = adapter_for_source(source)
    configured = {section.name: section for section in source.sections}
    jobs: list[tuple[ArticleSpec, str, str, str]] = []
    manifest = load_manifest(settings.manifest_path)
    for meta in manifest.values():
        if meta.publisher != source.publisher or meta.document_type != "article":
            continue
        raw = settings.data_dir / "raw" / host / "articles" / f"{meta.doc_id}.html"
        if not raw.is_file():
            continue
        section = configured.get(meta.source_section) or SectionSpec(
            section_id=f"{source.source_id}-{meta.source_section or 'raw'}",
            name=meta.source_section or "原始文章",
            list_url=meta.source_url,
            category=meta.category,
            publisher=meta.publisher,
            source_type=meta.source_type or source.source_type,
            scope_unit=meta.scope_unit or source.scope_unit,
        )
        page_spec = PageSpec(
            url=meta.source_url,
            section_id=section.section_id,
            page_kind="article",
            title_hint=meta.title,
            publisher_hint=meta.publisher,
            category=meta.category,
            source_type=meta.source_type or source.source_type,
            scope_unit=meta.scope_unit or source.scope_unit,
        )
        raw_content = raw.read_bytes()
        page = PageContent(
            requested_url=meta.source_url,
            final_url=meta.source_url,
            status="ok",
            content=raw_content,
            mime_type="text/html",
        )
        # 重放只补附件候选，不重复运行 trafilatura 正文抽取。父文档正文沿用
        # 当前 corpus，避免一次附件重放把原有正文质量降级。
        body_text = ""
        if meta.file_path:
            body_path = settings.corpus_dir / meta.file_path
            if body_path.is_file():
                body_text = body_path.read_text(encoding="utf-8")
                if body_text.startswith("# "):
                    body_text = body_text.split("\n", 1)[1].lstrip("\n")
        article = ArticleSpec(
            page=page_spec,
            title=meta.title,
            publish_date=meta.publish_date,
            publisher=meta.publisher or source.publisher,
            body_text=body_text,
            html=page.text(),
            attachments=adapter.discover_attachments(page, page_spec),
            breadcrumbs=[],
            source_type=meta.source_type or source.source_type,
            category=meta.category,
            scope_unit=meta.scope_unit or source.scope_unit,
            document_kind_hint=meta.document_kind,
            publish_date_evidence=meta.publish_date_evidence,
            publish_date_confidence=meta.publish_date_confidence,
            date_conflict=meta.date_conflict,
        )
        if article.attachments:
            jobs.append((article, meta.category, meta.source_section, meta.scope_unit))
            if options.max_articles is not None and len(jobs) >= options.max_articles:
                break

    report = CrawlReport(host=host)
    report.categories_found = len({job[2] for job in jobs})
    report.articles_found = len(jobs)
    report.articles_downloaded = len(jobs)
    if not jobs:
        if options.report_dir is not None:
            report.save(options.report_dir)
        return [report]
    with SafeFetcher(
        delay=options.delay,
        allowed_hosts={host, *source.allowed_hosts},
        max_attachment_bytes=options.max_attachment_bytes,
    ) as fetcher:
        seen_attachments = {}
        batch_size = max(1, options.retry_batch_size)
        for start in range(0, len(jobs), batch_size):
            grouped: dict[tuple[str, str, str], list] = {}
            for article, category, source_section, scope_unit in jobs[start : start + batch_size]:
                crawled = _article_to_crawled(
                    article,
                    fetcher=fetcher,
                    options=AdapterCrawlOptions(
                        max_attachments_per_article=options.max_attachments_per_article,
                        download_attachments=options.download_attachments,
                    ),
                    seen_attachments=seen_attachments,
                    parse_attachment=parse_attachment,
                    report=report,
                )
                grouped.setdefault((category, source_section, scope_unit), []).append(crawled)
            for (category, source_section, scope_unit), articles in grouped.items():
                ingest_crawled_articles(
                    articles,
                    category=category,
                    corpus_dir=settings.corpus_dir,
                    manifest_path=settings.manifest_path,
                    relations_path=default_relations_path(settings.manifest_path),
                    raw_dir=(None if options.dry_run else settings.data_dir / "raw" / host),
                    report=report,
                    dry_run=options.dry_run,
                    source_type=source.source_type,
                    source_section=source_section,
                    scope_unit=scope_unit or source.scope_unit,
                    time_policy=(
                        configured[source_section].time_policy
                        if source_section in configured
                        else "all_history"
                    ),
                )
    if options.report_dir is not None:
        report.save(options.report_dir)
    return [report]
