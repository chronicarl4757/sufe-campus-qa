"""抓取引擎：栏目分页 → 文章结构化解析 → 附件下载/解析 → CrawledArticle + CrawlReport。

只做抓取与解析，不写 corpus/manifest（入库由 ingest.pipeline 负责）。
CrawledArticle / DownloadedAttachment 字段按规格 §三/§七，另带工程扩展字段。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from sufe_qa.crawler.article import ATTACH_EXTS, ArticleMeta, AttachmentCandidate, parse_article
from sufe_qa.crawler.fetcher import SafeFetcher
from sufe_qa.crawler.pagination import crawl_list_pages
from sufe_qa.crawler.profile import ArticleProfile
from sufe_qa.crawler.state import CrawlState

# ---------------- 数据结构（规格 §三/§七） ----------------


@dataclass
class DownloadedAttachment:
    requested_url: str
    final_url: str
    filename: str
    mime_type: str
    content: bytes
    binary_hash: str
    status: str  # ok | fetch 失败状态 | duplicate
    candidate: AttachmentCandidate | None = None
    parse: object | None = None  # AttachmentParseResult（提供解析器时填充）
    error: str = ""


@dataclass
class CrawledArticle:
    requested_url: str
    final_url: str
    title: str
    publish_date: str
    publisher: str
    html: str
    body_text: str
    attachments: list[AttachmentCandidate]
    status: str  # ok | not_modified | skipped_since | fetch 失败状态
    errors: list[str]
    downloaded: list[DownloadedAttachment] = field(default_factory=list)
    breadcrumbs: list[str] = field(default_factory=list)
    low_quality_title: bool = False
    etag: str | None = None
    last_modified: str | None = None
    html_hash: str = ""


@dataclass
class CrawlOptions:
    max_list_pages: int = 5
    max_articles: int = 20
    max_attachment_bytes: int = 30_000_000
    max_attachments_per_article: int = 20
    since: str | None = None  # YYYY-MM-DD；早于此日期的文章跳过
    download_attachments: bool = True


@dataclass
class CrawlReport:
    """站点级抓取报告（规格 §十五）；crawl 侧与 ingest 侧计数共用此结构。"""

    host: str
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    categories_found: int = 0
    list_pages_fetched: int = 0
    categories_requires_adapter: int = 0
    articles_found: int = 0
    articles_downloaded: int = 0
    attachments_found: int = 0
    attachments_downloaded: int = 0
    attachments_parsed: int = 0
    scanned_pdfs: int = 0
    legacy_docs_unparsed: int = 0
    incomplete_documents: int = 0
    low_quality_documents: int = 0
    sensitive_quarantined: int = 0
    duplicate_attachments: int = 0
    new_documents: int = 0
    updated_documents: int = 0
    unchanged_documents: int = 0
    not_seen_documents: int = 0
    final_indexed: int = 0
    failures: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fail(self, url: str, stage: str, status: str, reason: str) -> None:
        self.failures.append({"url": url, "stage": stage, "status": status, "reason": reason[:200]})

    def summary(self) -> str:
        rows = [
            ("发现栏目数", self.categories_found),
            ("已抓栏目页数", self.list_pages_fetched),
            ("需要 adapter 的栏目数", self.categories_requires_adapter),
            ("发现文章数", self.articles_found),
            ("文章下载成功数", self.articles_downloaded),
            ("发现附件数", self.attachments_found),
            ("附件下载成功数", self.attachments_downloaded),
            ("附件解析成功数", self.attachments_parsed),
            ("扫描 PDF 数量", self.scanned_pdfs),
            ("旧 DOC 未解析数", self.legacy_docs_unparsed),
            ("不完整文档数", self.incomplete_documents),
            ("低质量文档数", self.low_quality_documents),
            ("敏感信息隔离数", self.sensitive_quarantined),
            ("重复附件数", self.duplicate_attachments),
            ("新增文档数", self.new_documents),
            ("更新文档数", self.updated_documents),
            ("未变化文档数", self.unchanged_documents),
            ("本轮未出现文档数", self.not_seen_documents),
            ("最终有效入库数", self.final_indexed),
        ]
        lines = [f"抓取报告 {self.host} @ {self.started_at}"]
        lines += [f"  {k}: {v}" for k, v in rows]
        if self.failures:
            lines.append(f"  失败对象: {len(self.failures)} 个（详见 JSON 报告）")
        return "\n".join(lines)

    def save(self, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = re.sub(r"[:+]", "", self.started_at.replace("T", "-"))[:15]
        path = reports_dir / f"{ts}-{self.host}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        return path


# ---------------- 附件文件名 ----------------

_RFC5987_RE = re.compile(r"filename\*\s*=\s*([^']+)'[^']*'([^;\s]+)", re.I)
_FILENAME_RE = re.compile(r'filename\s*=\s*"?([^";]+)"?', re.I)
_MIME_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/zip": ".zip",
}


def filename_from_disposition(cd: str) -> str | None:
    """从 Content-Disposition 提取文件名；支持 RFC5987 与 GBK 伪装 latin-1 的中文名。"""
    if not cd:
        return None
    m = _RFC5987_RE.search(cd)
    if m:
        try:
            return unquote(m.group(2), encoding=m.group(1) or "utf-8", errors="replace")
        except (LookupError, ValueError):
            pass
    m = _FILENAME_RE.search(cd)
    if not m:
        return None
    raw = m.group(1).strip()
    try:  # httpx 头按 latin-1 解码，中文名需还原字节再猜编码
        raw.encode("latin-1")
    except UnicodeEncodeError:
        return raw
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.encode("latin-1").decode(enc)
        except UnicodeDecodeError:
            continue
    return raw


def attachment_filename(
    content_disposition: str,
    final_url: str,
    requested_url: str,
    index: int,
    anchor_text: str = "",
    parent_title: str = "",
    mime_type: str = "",
) -> str:
    """文件名回退链：Content-Disposition → 带附件扩展名的 URL 段 → 锚文本 → 父标题 → 序号。"""
    if name := filename_from_disposition(content_disposition):
        return name
    for url in (final_url, requested_url):
        seg = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]).strip()
        if any(seg.lower().endswith(ext) for ext in ATTACH_EXTS):
            return seg
    ext = _MIME_EXT.get(mime_type, "")
    if anchor_text:
        name = re.sub(r"[\\/:*?\"<>|\s]+", "_", anchor_text).strip("_")[:80]
        if name:
            return name if Path(name).suffix else name + ext
    if parent_title:
        name = re.sub(r"[\\/:*?\"<>|\s]+", "_", parent_title).strip("_")[:80]
        return name + ext
    return f"attachment-{index}{ext}"


# pdf.js 等查看器页中的真实文件地址模式（gs.sufe 的 iframe 附件走此链路）
_VIEWER_TARGET_RES = [
    re.compile(r"_fileurl\s*=\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"DEFAULT_URL\s*[=:]\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"viewer(?:\.html)?\?file=([^'\"\s&]+)", re.I),
]


def viewer_target(html: str, base_url: str) -> str | None:
    """从查看器页 HTML 提取真实文件 URL；识别不了返回 None。"""
    for pat in _VIEWER_TARGET_RES:
        m = pat.search(html or "")
        if m:
            return urljoin(base_url, unquote(m.group(1)))
    return None


# ---------------- 列表链接提取 ----------------


def make_link_extractor(
    selector: str, url_prefix: str, limit: int
) -> Callable[[str, str], list[str]]:
    """按 CSS selector + URL 前缀过滤提取文章链接（去重保序，上限 limit）。"""

    def extract(html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html or "", "html.parser")
        urls: list[str] = []
        for a in soup.select(selector):
            href = a.get("href")
            if not href or str(href).startswith(("#", "javascript:", "mailto:")):
                continue
            full = urldefrag(urljoin(base_url, str(href)))[0]
            if url_prefix and not full.startswith(url_prefix):
                continue
            if full not in urls:
                urls.append(full)
            if len(urls) >= limit:
                break
        return urls

    return extract


# ---------------- 主流程 ----------------


def crawl_category(
    list_url: str,
    link_selector: str,
    url_prefix: str,
    fetcher: SafeFetcher,
    *,
    options: CrawlOptions | None = None,
    article_profile: ArticleProfile | None = None,
    publisher: str = "",
    state: CrawlState | None = None,
    parse_attachment: Callable[[str, bytes], object] | None = None,
    report: CrawlReport | None = None,
) -> list[CrawledArticle]:
    """抓取一个栏目：分页列表 → 逐文章 → 逐附件。失败全部结构化，不抛出。"""
    options = options or CrawlOptions()
    profile = article_profile or ArticleProfile()
    articles: list[CrawledArticle] = []
    seen_att: dict[str, DownloadedAttachment] = {}  # binary_hash -> 首个下载结果

    extractor = make_link_extractor(link_selector, url_prefix, options.max_articles)
    page = crawl_list_pages(
        list_url,
        fetcher.fetch,
        extractor,
        max_list_pages=options.max_list_pages,
        max_articles=options.max_articles,
    )
    if report:
        report.list_pages_fetched += page.pages_fetched
        report.articles_found += len(page.article_urls)
        if page.requires_adapter:
            report.categories_requires_adapter += 1
            report.notes.append(f"{list_url}: requires_adapter（{page.stop_reason}）")
        for p in page.pages:
            if p.status != "ok":
                report.fail(p.requested_url, "list_page", p.status, p.error)

    for url in page.article_urls:
        cond = state.conditional_headers(url) if state else {}
        res = fetcher.fetch(url, "html", headers=cond or None)
        if res.status == "not_modified":
            if state:
                state.mark_seen(url)
            articles.append(
                CrawledArticle(
                    requested_url=url,
                    final_url=url,
                    title="",
                    publish_date="unknown",
                    publisher=publisher,
                    html="",
                    body_text="",
                    attachments=[],
                    status="not_modified",
                    errors=[],
                )
            )
            continue
        if not res.ok:
            if report:
                report.fail(url, "article", res.status, res.error)
            articles.append(
                CrawledArticle(
                    requested_url=url,
                    final_url=res.final_url or url,
                    title="",
                    publish_date="unknown",
                    publisher=publisher,
                    html="",
                    body_text="",
                    attachments=[],
                    status=res.status,
                    errors=[res.error],
                )
            )
            continue

        html = res.text()
        meta: ArticleMeta = parse_article(html, res.final_url, profile, publisher)
        html_hash = hashlib.sha256(meta.body_text.encode("utf-8")).hexdigest()
        art = CrawledArticle(
            requested_url=url,
            final_url=res.final_url,
            title=meta.title,
            publish_date=meta.publish_date,
            publisher=meta.publisher,
            html=html,
            body_text=meta.body_text,
            attachments=meta.attachments,
            status="ok",
            errors=[],
            breadcrumbs=meta.breadcrumbs,
            low_quality_title=meta.low_quality_title,
            etag=res.etag,
            last_modified=res.last_modified,
            html_hash=html_hash,
        )
        if state:
            state.update(
                url,
                final_url=res.final_url,
                etag=res.etag,
                last_modified=res.last_modified,
                content_hash=html_hash,
            )

        if options.since and meta.publish_date != "unknown" and meta.publish_date < options.since:
            art.status = "skipped_since"
            articles.append(art)
            continue
        if report:
            report.articles_downloaded += 1
            report.attachments_found += len(meta.attachments)
            if len(meta.attachments) > options.max_attachments_per_article:
                report.notes.append(
                    f"{res.final_url}: 附件 {len(meta.attachments)} 个，"
                    f"截断到 {options.max_attachments_per_article} 个"
                )

        if options.download_attachments:
            for i, cand in enumerate(meta.attachments[: options.max_attachments_per_article], 1):
                att = _download_attachment(
                    cand,
                    i,
                    fetcher,
                    parse_attachment,
                    seen_att,
                    report,
                    parent_title=meta.title,
                )
                art.downloaded.append(att)
                if att.status != "ok" and report:
                    art.errors.append(f"附件 {cand.requested_url}: {att.status} {att.error}")
        articles.append(art)
    return articles


def _download_attachment(
    cand: AttachmentCandidate,
    index: int,
    fetcher: SafeFetcher,
    parse_attachment: Callable[[str, bytes], object] | None,
    seen_att: dict[str, DownloadedAttachment],
    report: CrawlReport | None,
    parent_title: str = "",
) -> DownloadedAttachment:
    res = fetcher.fetch(cand.requested_url, "attachment")
    if res.status == "unsupported_mime" and res.content:
        # pdf.js 类查看器页：解析真实文件地址后重取（gs.sufe 的 iframe 附件）
        target = viewer_target(res.text(), res.final_url or cand.requested_url)
        if target:
            res2 = fetcher.fetch(target, "attachment")
            if res2.ok:
                res = res2
            else:
                res.error = f"查看器目标抓取失败: {res2.status}"
    if not res.ok:
        if report:
            report.fail(cand.requested_url, "attachment", res.status, res.error)
        return DownloadedAttachment(
            requested_url=cand.requested_url,
            final_url=res.final_url or cand.requested_url,
            filename="",
            mime_type=res.mime_type,
            content=b"",
            binary_hash="",
            status=res.status,
            candidate=cand,
            error=res.error,
        )
    bhash = hashlib.sha256(res.content).hexdigest()
    filename = attachment_filename(
        res.content_disposition,
        res.final_url,
        cand.requested_url,
        index,
        anchor_text=cand.anchor_text,
        parent_title=parent_title,
        mime_type=res.mime_type,
    )
    att = DownloadedAttachment(
        requested_url=cand.requested_url,
        final_url=res.final_url,
        filename=filename,
        mime_type=res.mime_type,
        content=res.content,
        binary_hash=bhash,
        status="ok",
        candidate=cand,
    )
    first = seen_att.get(bhash)
    if first is not None:
        # 同 binary 重复引用：共享首个解析结果（父文章质量门据此判断附件有效），
        # status 标 duplicate，入库时只挂关系不重复嵌入
        att.status = "duplicate"
        att.parse = first.parse
        if report:
            report.duplicate_attachments += 1
        return att
    seen_att[bhash] = att
    if report:
        report.attachments_downloaded += 1
    if parse_attachment is not None:
        att.parse = parse_attachment(filename, res.content)
        status = getattr(att.parse, "parse_status", "")
        if status == "ok" and report:
            report.attachments_parsed += 1
        elif status == "scanned_pdf" and report:
            report.scanned_pdfs += 1
        elif status == "legacy_doc_unparsed" and report:
            report.legacy_docs_unparsed += 1
    return att
