"""Adapter 驱动的通用抓取编排。

这里集中调用 SafeFetcher、条件请求、附件下载与限速；adapter 本身只解析 PageContent。
返回的仍是现有 ingest.pipeline 接受的 CrawledArticle，因而不会绕过既有质量门和父子关系。
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable, Protocol
from urllib.parse import urlencode, urlparse, urlunparse

from sufe_qa.crawler.adapters import (
    ArticleSpec,
    ListingResult,
    PageContent,
    PageSpec,
    SectionSpec,
    SiteAdapter,
)
from sufe_qa.crawler.article import AttachmentCandidate
from sufe_qa.crawler.engine import (
    CrawlReport,
    CrawledArticle,
    DownloadedAttachment,
    _download_attachment,
)
from sufe_qa.crawler.fetcher import FetchResult
from sufe_qa.crawler.state import CrawlState


class FetcherLike(Protocol):
    def fetch(self, url: str, kind: str = "html", headers: dict | None = None) -> FetchResult: ...


@dataclass(frozen=True)
class AdapterCrawlOptions:
    max_list_pages: int = 1000
    max_articles: int | None = None
    max_attachments_per_article: int = 20
    since: str | None = None
    download_attachments: bool = True
    use_conditional_requests: bool = True


def _page_content(result: FetchResult) -> PageContent:
    return PageContent(
        requested_url=result.requested_url,
        final_url=result.final_url or result.requested_url,
        status=result.status,
        content=result.content,
        mime_type=result.mime_type,
        status_code=result.status_code,
        error=result.error,
    )


def _synthetic_parent_url(section: SectionSpec, attachment_url: str) -> str:
    token = hashlib.sha256(attachment_url.encode("utf-8")).hexdigest()[:16]
    parsed = urlparse(section.list_url)
    query = dict(
        parsed.query
        and [pair.split("=", 1) for pair in parsed.query.split("&") if "=" in pair]
        or []
    )
    query["source_attachment"] = token
    return urlunparse(parsed._replace(query=urlencode(query)))


def _filter_listing_titles(listing: ListingResult, section: SectionSpec) -> ListingResult:
    """按栏目 metadata 的 title_include/title_exclude 正则收窄文章入口（如财务处宽栏目）。"""
    include = section.metadata.get("title_include")
    exclude = section.metadata.get("title_exclude")
    if not include and not exclude:
        return listing
    inc = re.compile(include) if include else None
    exc = re.compile(exclude) if exclude else None
    kept = [
        spec
        for spec in listing.article_pages
        if (inc is None or inc.search(spec.title_hint or ""))
        and (exc is None or not exc.search(spec.title_hint or ""))
    ]
    return replace(listing, article_pages=kept)


def _failed_article(url: str, publisher: str, status: str, error: str) -> CrawledArticle:
    return CrawledArticle(
        requested_url=url,
        final_url=url,
        title="",
        publish_date="unknown",
        publisher=publisher,
        html="",
        body_text="",
        attachments=[],
        status=status,
        errors=[error] if error else [],
    )


def _direct_attachment_article(
    spec: PageSpec,
    section: SectionSpec,
    attachment: DownloadedAttachment,
) -> CrawledArticle:
    title = spec.title_hint or attachment.filename or "栏目附件"
    parent_url = _synthetic_parent_url(section, spec.url)
    body = (
        f"栏目“{section.name}”公开发布材料“{title}”。"
        f"该材料的具体条件、材料和办理要求见附件正文。"
        f"原始发布栏目：{section.list_url}。"
    )
    candidate = attachment.candidate or AttachmentCandidate(
        source_page_url=section.list_url,
        requested_url=spec.url,
        anchor_text=title,
        candidate_score=1.0,
        discovery_reason=["listing_attachment"],
    )
    return CrawledArticle(
        requested_url=parent_url,
        final_url=parent_url,
        title=title,
        publish_date="unknown",
        publisher=section.publisher,
        html="",
        body_text=body,
        attachments=[candidate],
        status="ok",
        errors=[] if attachment.status in {"ok", "duplicate"} else [attachment.error],
        downloaded=[attachment],
    )


def _article_to_crawled(
    article: ArticleSpec,
    *,
    fetcher: FetcherLike,
    options: AdapterCrawlOptions,
    seen_attachments: dict[str, DownloadedAttachment],
    parse_attachment: Callable[[str, bytes], object] | None,
    report: CrawlReport | None,
) -> CrawledArticle:
    downloaded: list[DownloadedAttachment] = []
    errors: list[str] = []
    if report:
        report.attachments_found += len(article.attachments)
    if options.download_attachments:
        for index, candidate in enumerate(
            article.attachments[: options.max_attachments_per_article], start=1
        ):
            attachment = _download_attachment(
                candidate,
                index,
                fetcher,
                parse_attachment,
                seen_attachments,
                report,
                parent_title=article.title,
            )
            downloaded.append(attachment)
            if attachment.status not in {"ok", "duplicate"}:
                errors.append(
                    f"附件 {candidate.requested_url}: {attachment.status} {attachment.error}"
                )
    return CrawledArticle(
        requested_url=article.page.url,
        final_url=article.page.url,
        title=article.title,
        publish_date=article.publish_date,
        publisher=article.publisher,
        html=article.html,
        body_text=article.body_text,
        attachments=article.attachments,
        status="ok",
        errors=errors,
        downloaded=downloaded,
        breadcrumbs=article.breadcrumbs,
        low_quality_title=False,
        html_hash=hashlib.sha256(article.body_text.encode("utf-8")).hexdigest(),
        publish_date_evidence=article.publish_date_evidence,
        publish_date_confidence=article.publish_date_confidence,
        date_conflict=article.date_conflict,
    )


def crawl_adapter_section(
    adapter: SiteAdapter,
    section: SectionSpec,
    fetcher: FetcherLike,
    *,
    options: AdapterCrawlOptions | None = None,
    state: CrawlState | None = None,
    parse_attachment: Callable[[str, bytes], object] | None = None,
    report: CrawlReport | None = None,
) -> list[CrawledArticle]:
    """按 adapter 解析栏目直到分页终点、重复页或连续无新链接。"""
    options = options or AdapterCrawlOptions(max_list_pages=section.max_pages or 1000)
    max_pages = min(options.max_list_pages, section.max_pages or options.max_list_pages)
    pending: deque[PageSpec] = deque(adapter.iter_list_pages(section))
    seen_list_urls: set[str] = set()
    seen_hashes: set[str] = set()
    seen_article_urls: set[str] = set()
    article_specs: list[PageSpec] = []
    list_contents: dict[str, PageContent] = {}
    stale_pages = 0
    report_article_base = report.articles_found if report else 0

    while pending and len(seen_list_urls) < max_pages:
        list_spec = pending.popleft()
        if list_spec.url in seen_list_urls:
            continue
        seen_list_urls.add(list_spec.url)
        result = fetcher.fetch(list_spec.url, "html")
        page = _page_content(result)
        if not page.ok:
            if report:
                report.fail(list_spec.url, "list_page", page.status, page.error)
            continue
        if report:
            report.list_pages_fetched += 1
        if page.final_url in list_contents:
            break
        list_contents[page.final_url] = page
        listing = adapter.parse_listing(page, section)
        listing = _filter_listing_titles(listing, section)
        if listing.page_hash in seen_hashes:
            break
        seen_hashes.add(listing.page_hash)
        before = len(article_specs)
        for spec in listing.article_pages:
            if spec.url in seen_article_urls:
                continue
            seen_article_urls.add(spec.url)
            article_specs.append(spec)
            if options.max_articles is not None and len(article_specs) >= options.max_articles:
                break
        stale_pages = stale_pages + 1 if len(article_specs) == before else 0
        if report:
            report.articles_found = report_article_base + len(article_specs)
        if options.max_articles is not None and len(article_specs) >= options.max_articles:
            break
        if stale_pages >= 2:
            break
        if listing.next_page and listing.next_page.url not in seen_list_urls:
            pending.append(listing.next_page)

    articles: list[CrawledArticle] = []
    seen_attachments: dict[str, DownloadedAttachment] = {}
    for spec in article_specs:
        if spec.page_kind == "attachment":
            candidate = AttachmentCandidate(
                source_page_url=spec.source_page_url or section.list_url,
                requested_url=spec.url,
                anchor_text=spec.title_hint,
                candidate_score=1.0,
                discovery_reason=["listing_attachment"],
            )
            attachment = _download_attachment(
                candidate,
                1,
                fetcher,
                parse_attachment,
                seen_attachments,
                report,
                parent_title=spec.title_hint,
            )
            articles.append(_direct_attachment_article(spec, section, attachment))
            continue

        page = list_contents.get(spec.url)
        if page is None:
            cond = (
                state.conditional_headers(spec.url)
                if state and options.use_conditional_requests
                else {}
            )
            result = fetcher.fetch(spec.url, "html", headers=cond or None)
            page = _page_content(result)
        if page.status == "not_modified":
            if state:
                state.mark_seen(spec.url)
            articles.append(_failed_article(spec.url, section.publisher, "not_modified", ""))
            articles[-1].status = "not_modified"
            continue
        if not page.ok:
            if report:
                report.fail(spec.url, "article", page.status, page.error)
            articles.append(_failed_article(spec.url, section.publisher, page.status, page.error))
            continue
        article = adapter.parse_article(page, spec)
        if (
            options.since
            and article.publish_date != "unknown"
            and article.publish_date < options.since
        ):
            continue
        if state:
            state.update(
                spec.url,
                final_url=page.final_url,
                content_hash=hashlib.sha256(article.body_text.encode("utf-8")).hexdigest(),
            )
        if report:
            report.articles_downloaded += 1
        articles.append(
            _article_to_crawled(
                article,
                fetcher=fetcher,
                options=options,
                seen_attachments=seen_attachments,
                parse_attachment=parse_attachment,
                report=report,
            )
        )
    return articles
