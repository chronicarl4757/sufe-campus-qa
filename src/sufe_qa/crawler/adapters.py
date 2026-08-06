"""上财站点适配器协议与确定性页面解析。

Adapter 只负责把 HTTP 返回的 ``PageContent`` 转成栏目、分页和文章语义对象。
它不请求网络、不下载附件、不写 corpus/manifest，也不直接碰 Chroma；这些动作由
通用抓取/入库/索引引擎统一负责。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Iterator, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from sufe_qa.crawler.article import (
    AttachmentCandidate,
    discover_attachments,
    parse_article as parse_article_page,
)
from sufe_qa.crawler.profile import ArticleProfile


@dataclass(frozen=True)
class SectionSpec:
    section_id: str
    name: str
    list_url: str
    category: str
    publisher: str
    source_type: str
    scope_unit: str = ""
    time_policy: str = "all"
    max_pages: int | None = None
    known_page_urls: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageSpec:
    """待抓取任务：只描述目标和页面语义，不携带 HTTP 内容。"""

    url: str
    section_id: str
    page_kind: str = "listing"  # listing | article | attachment
    page_index: int = 1
    title_hint: str = ""
    publisher_hint: str = ""
    category: str = ""
    source_type: str = "unknown"
    scope_unit: str = ""
    source_page_url: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageContent:
    """HTTP 请求结果及原始内容；不包含解析后的文档关系或索引状态。"""

    requested_url: str
    final_url: str
    status: str
    content: bytes
    mime_type: str = ""
    status_code: int | None = None
    error: str = ""

    def text(self) -> str:
        for encoding in ("utf-8", "gb18030"):
            try:
                return self.content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class ListingResult:
    """栏目页语义：文章任务、分页元数据和停止线索。"""

    article_pages: list[PageSpec]
    current_page: int = 1
    total_pages: int | None = None
    total_records: int | None = None
    next_page: PageSpec | None = None
    page_hash: str = ""
    stop_reason: str = ""


@dataclass(frozen=True)
class ArticleSpec:
    """Adapter 对文章页的语义解析；附件仍只是候选，不在这里下载。"""

    page: PageSpec
    title: str
    publish_date: str
    publisher: str
    body_text: str
    html: str
    attachments: list[AttachmentCandidate]
    breadcrumbs: list[str]
    source_type: str
    category: str
    scope_unit: str
    document_kind_hint: str = ""
    publish_date_evidence: str = ""
    publish_date_confidence: float = 0.0
    date_conflict: bool = False


class SiteAdapter(Protocol):
    def discover_sections(self, homepage: PageContent) -> list[SectionSpec]: ...

    def iter_list_pages(self, section: SectionSpec) -> Iterator[PageSpec]: ...

    def parse_listing(self, page: PageContent, section: SectionSpec) -> ListingResult: ...

    def parse_article(self, page: PageContent, spec: PageSpec) -> ArticleSpec: ...


_HIGH_VALUE_SECTION_WORDS = (
    "通知",
    "公告",
    "制度",
    "规章",
    "办事",
    "培养",
    "教学",
    "学籍",
    "考试",
    "选课",
    "奖学金",
    "助学",
    "推免",
    "招生",
    "学位",
    "就业",
    "下载",
    "服务",
    "指南",
    "政策",
    "公示",
)
_DROP_SECTION_WORDS = ("新闻", "校友", "党建", "领导", "师资", "科研", "讲座", "活动")
_WP3_ARTICLE_RE = re.compile(
    r"/(?:[0-9a-z]{1,8}/){2,4}page\.htm$|/info/\d+\.htm$|/\d+\.htm$",
    re.I,
)
_GS_ARTICLE_RE = re.compile(r"/Home/Detail/\d+", re.I)
_ATTACH_RE = re.compile(
    r"(?:\.pdf|\.docx?|\.xlsx?|\.pptx?|/download(?:\.jsp)?|/_upload/|/files/|fileId=)",
    re.I,
)
_DATE_RE = re.compile(r"20\d{2}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}")
_TOTAL_RECORDS_RE = re.compile(r"(?:总共|共)\s*[：:]?\s*(\d+)\s*(?:条|记录|篇)")
_TOTAL_PAGES_RE = re.compile(r"(?:总共\s*)?(?:页码\s*)?(?:\d+\s*/\s*)?(\d+)\s*页")
_CURRENT_PAGE_RE = re.compile(r"(?:当前页|页码)\s*[：:]?\s*(\d+)")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _same_host(base: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    full = urljoin(base, href).split("#", 1)[0]
    if not full.startswith(("http://", "https://")):
        return None
    return full if urlparse(full).netloc == urlparse(base).netloc else None


def _section_id(url: str, name: str) -> str:
    return sha256(f"{url}\n{name}".encode("utf-8")).hexdigest()[:12]


def _is_attachment_url(url: str, text: str = "") -> bool:
    return bool(_ATTACH_RE.search(url) or re.search(r"下载|申请表|表格|材料|附件", text or ""))


def _page_number(url: str) -> int:
    for key, value in parse_qsl(urlparse(url).query):
        if key.lower() in {"page", "p", "pageno", "pageindex"} and value.isdigit():
            return int(value)
    name = urlparse(url).path.rsplit("/", 1)[-1]
    m = re.search(r"(?:list|index|default)(\d+)\.(?:htm|html|shtml)$", name, re.I)
    return int(m.group(1)) if m else 1


def _increment_page_url(url: str, page_number: int) -> str:
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for index, (key, value) in enumerate(pairs):
        if key.lower() in {"page", "p", "pageno", "pageindex"}:
            pairs[index] = (key, str(page_number))
            return urlunparse(parsed._replace(query=urlencode(pairs)))
    filename = parsed.path.rsplit("/", 1)[-1]
    match = re.match(r"(?P<stem>list|index|default)(?P<num>\d*)\.(?P<ext>htm|html|shtml)$", filename, re.I)
    if match:
        new_name = f"{match.group('stem')}{page_number}.{match.group('ext')}"
        return urlunparse(parsed._replace(path=parsed.path[: -len(filename)] + new_name))
    return url


def _pagination_value(soup: BeautifulSoup, pattern: re.Pattern[str], html: str) -> int | None:
    for text in (soup.get_text(" ", strip=True), html):
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


class BaseAdapter:
    """通用协议与安全的 DOM 提取；具体 CMS 只覆盖结构差异。"""

    listing_selectors: tuple[str, ...] = (
        "#wp_news_w6",
        ".wp_article_list",
        ".wp_news",
        ".news-list",
        ".article-list",
        ".list-box",
    )
    article_profile = ArticleProfile()
    article_url_pattern = _WP3_ARTICLE_RE

    def __init__(
        self,
        *,
        publisher: str = "",
        source_type: str = "official_department",
        scope_unit: str = "",
    ) -> None:
        self.publisher = publisher
        self.source_type = source_type
        self.scope_unit = scope_unit

    def discover_sections(self, homepage: PageContent) -> list[SectionSpec]:
        soup = BeautifulSoup(homepage.text(), "html.parser")
        containers = soup.select(
            "nav a, .nav a, .menu a, .navbar a, header a, .wp_listcolumn a, .column a"
        )
        seen: set[str] = set()
        sections: list[SectionSpec] = []
        for anchor in containers:
            if not isinstance(anchor, Tag):
                continue
            name = _clean(anchor.get_text(" ", strip=True))
            url = _same_host(homepage.final_url or homepage.requested_url, str(anchor.get("href", "")))
            if not url or not name or url in seen:
                continue
            if any(word in name for word in _DROP_SECTION_WORDS):
                continue
            if not any(word in name for word in _HIGH_VALUE_SECTION_WORDS):
                continue
            if not ("list" in url.lower() or "/home/" in url.lower() or "column" in url.lower()):
                continue
            seen.add(url)
            sections.append(
                SectionSpec(
                    section_id=_section_id(url, name),
                    name=name,
                    list_url=url,
                    category=name,
                    publisher=self.publisher,
                    source_type=self.source_type,
                    scope_unit=self.scope_unit,
                )
            )
        return sections

    def iter_list_pages(self, section: SectionSpec) -> Iterator[PageSpec]:
        urls = section.known_page_urls or (section.list_url,)
        for index, url in enumerate(urls, start=1):
            yield PageSpec(
                url=url,
                section_id=section.section_id,
                page_index=index,
                publisher_hint=section.publisher,
                category=section.category,
                source_type=section.source_type,
                scope_unit=section.scope_unit,
            )

    def _listing_containers(self, soup: BeautifulSoup) -> list[Tag]:
        containers: list[Tag] = []
        for selector in self.listing_selectors:
            containers.extend(node for node in soup.select(selector) if isinstance(node, Tag))
        return list(dict.fromkeys(containers))

    def _article_page_for_anchor(self, anchor: Tag, section: SectionSpec, base_url: str) -> PageSpec | None:
        url = _same_host(base_url, str(anchor.get("href", "")))
        if not url:
            return None
        title_hint = _clean(anchor.get("title", "") or anchor.get_text(" ", strip=True))
        if _is_attachment_url(url, title_hint):
            kind = "attachment"
        elif self.article_url_pattern.search(urlparse(url).path) or self._accept_article_url(url):
            kind = "article"
        else:
            return None
        return PageSpec(
            url=url,
            section_id=section.section_id,
            page_kind=kind,
            title_hint=title_hint,
            publisher_hint=section.publisher,
            category=section.category,
            source_type=section.source_type,
            scope_unit=section.scope_unit,
            source_page_url=base_url,
        )

    def _accept_article_url(self, url: str) -> bool:
        return False

    def parse_listing(self, page: PageContent, section: SectionSpec) -> ListingResult:
        soup = BeautifulSoup(page.text(), "html.parser")
        pages: list[PageSpec] = []
        seen: set[str] = set()
        for container in self._listing_containers(soup):
            for anchor in container.find_all("a", href=True):
                spec = self._article_page_for_anchor(anchor, section, page.final_url or page.requested_url)
                if spec and spec.url not in seen:
                    pages.append(spec)
                    seen.add(spec.url)
        current = _page_number(page.final_url or page.requested_url)
        total_pages = self._extract_total_pages(soup, page.text())
        total_records = _pagination_value(soup, _TOTAL_RECORDS_RE, page.text())
        next_url = self._find_next_url(soup, page.final_url or page.requested_url, current, total_pages)
        next_page = None
        if next_url and (total_pages is None or current < total_pages):
            next_page = PageSpec(
                url=next_url,
                section_id=section.section_id,
                page_index=current + 1,
                publisher_hint=section.publisher,
                category=section.category,
                source_type=section.source_type,
                scope_unit=section.scope_unit,
            )
        return ListingResult(
            article_pages=pages,
            current_page=current,
            total_pages=total_pages,
            total_records=total_records,
            next_page=next_page,
            page_hash=sha256(re.sub(r"\s+", "", page.text()).encode("utf-8")).hexdigest(),
            stop_reason="no_next_page" if next_page is None else "next_page",
        )

    def _extract_total_pages(self, soup: BeautifulSoup, html: str) -> int | None:
        el = soup.select_one(".all_pages, .all-pages, .pages-total, [class*=all_pages]")
        if el and (match := re.search(r"\d+", el.get_text(" ", strip=True))):
            return int(match.group())
        if value := _pagination_value(soup, _TOTAL_PAGES_RE, html):
            return value
        # GS 站常只提供“尾页?page=13”，没有“共 13 页”文字。
        page_values = []
        for anchor in soup.select(".pagination a[href], .pagination-block a[href]"):
            for key, value in parse_qsl(urlparse(str(anchor.get("href", ""))).query):
                if key.lower() in {"page", "p", "pageno", "pageindex"} and value.isdigit():
                    page_values.append(int(value))
        return max(page_values) if page_values else None

    def _find_next_url(
        self, soup: BeautifulSoup, current_url: str, current_page: int, total_pages: int | None
    ) -> str | None:
        for anchor in soup.find_all("a", href=True):
            if _clean(anchor.get_text(" ", strip=True)).lower() in {"下一页", "下页", "next", "next page", "›", "»"}:
                if url := _same_host(current_url, str(anchor.get("href", ""))):
                    return url
        if total_pages is not None and current_page < total_pages:
            return _increment_page_url(current_url, current_page + 1)
        return None

    def parse_article(self, page: PageContent, spec: PageSpec) -> ArticleSpec:
        meta = parse_article_page(
            page.text(),
            page.final_url or page.requested_url,
            self.article_profile,
            spec.publisher_hint or self.publisher,
        )
        title = spec.title_hint if meta.low_quality_title and spec.title_hint else meta.title
        return ArticleSpec(
            page=spec,
            title=title,
            publish_date=meta.publish_date,
            publisher=meta.publisher or spec.publisher_hint or self.publisher,
            body_text=meta.body_text,
            html=page.text(),
            attachments=meta.attachments,
            breadcrumbs=meta.breadcrumbs,
            source_type=spec.source_type or self.source_type,
            category=spec.category,
            scope_unit=spec.scope_unit or self.scope_unit,
            document_kind_hint=spec.metadata.get("document_kind", ""),
            publish_date_evidence=meta.publish_date_evidence,
            publish_date_confidence=meta.publish_date_confidence,
            date_conflict=meta.date_conflict,
        )

    def discover_attachments(self, page: PageContent, spec: PageSpec) -> list[AttachmentCandidate]:
        """只解析附件候选，不抽取正文。

        该轻量入口供 raw HTML 重放使用：重放的目标是补抓附件，不能为了重新发现
        附件而再次运行正文抽取器。网络请求、下载和持久化仍由通用引擎负责。
        """
        return discover_attachments(
            BeautifulSoup(page.text(), "html.parser"),
            page.final_url or page.requested_url or spec.url,
        )


class Wp3Adapter(BaseAdapter):
    """上财多数旧站的 wp3 CMS；只覆盖栏目/列表 DOM，不重复 HTTP 逻辑。"""

    listing_selectors = (
        "#wp_news_w6",
        "#wp_news_w72",
        ".wp_article_list",
        ".wp_column_article .wp_entry",
        ".col_news_list .wp_entry",
        ".col_news_list",
    )
    article_profile = ArticleProfile(
        title_selectors=[".arti_title", ".col_title h2", "h1"],
        date_selectors=[".arti_update", ".arti_metas", ".col_metas"],
        content_selectors=[".wp_articlecontent", ".wp_entry", ".article_content"],
    )


class JwcAdapter(Wp3Adapter):
    """教务处特殊点：办事流程是静态正文页，正文主要由附件链接组成。"""

    def __init__(self, *, publisher: str = "教务处", scope_unit: str = "本科生", **kwargs) -> None:
        super().__init__(publisher=publisher, scope_unit=scope_unit, **kwargs)

    def parse_listing(self, page: PageContent, section: SectionSpec) -> ListingResult:
        soup = BeautifulSoup(page.text(), "html.parser")
        content = soup.select_one("#wp_column_article .wp_articlecontent, .wp_articlecontent")
        if content and (
            section.name in {"办事流程", "常用下载", "学生类制度"}
            or len(_clean(content.get_text(" ", strip=True))) >= 20
        ):
            inline = PageSpec(
                url=page.final_url or page.requested_url,
                section_id=section.section_id,
                page_kind="article",
                title_hint=section.name,
                publisher_hint=section.publisher or self.publisher,
                category=section.category,
                source_type=section.source_type,
                scope_unit=section.scope_unit,
                metadata={"inline": "true"},
            )
            return ListingResult(
                article_pages=[inline],
                current_page=1,
                total_pages=1,
                total_records=1,
                page_hash=sha256(re.sub(r"\s+", "", page.text()).encode("utf-8")).hexdigest(),
                stop_reason="inline_article",
            )
        base = super().parse_listing(page, section)
        return base


class GraduateSchoolAdapter(BaseAdapter):
    """研究生院独立 Home/List/Detail CMS，完整保留 query 分页和附件正文。"""

    listing_selectors = (".single-blog-item", ".blog-content", ".pagination-block")
    article_url_pattern = _GS_ARTICLE_RE
    article_profile = ArticleProfile(
        title_selectors=[".detail-title", "h1"],
        date_selectors=[".key-feature p", ".blog-meta", ".detail-info"],
        content_selectors=[".content", ".detail", "article", ".v_news_content"],
    )

    def __init__(self, *, publisher: str = "研究生院", scope_unit: str = "研究生", **kwargs) -> None:
        super().__init__(publisher=publisher, scope_unit=scope_unit, **kwargs)

    def _accept_article_url(self, url: str) -> bool:
        return bool(self.article_url_pattern.search(url))

    def discover_sections(self, homepage: PageContent) -> list[SectionSpec]:
        soup = BeautifulSoup(homepage.text(), "html.parser")
        sections: list[SectionSpec] = []
        seen: set[str] = set()
        for anchor in soup.select("nav a, .navbar a, .programme-list a, header a"):
            url = _same_host(homepage.final_url or homepage.requested_url, str(anchor.get("href", "")))
            name = _clean(anchor.get_text(" ", strip=True))
            if not url or not name or not re.search(r"/Home/List/\d+", url) or url in seen:
                continue
            if any(word in name for word in _DROP_SECTION_WORDS):
                continue
            seen.add(url)
            sections.append(
                SectionSpec(
                    section_id=_section_id(url, name),
                    name=name,
                    list_url=url,
                    category=name,
                    publisher=self.publisher,
                    source_type=self.source_type,
                    scope_unit=self.scope_unit,
                )
            )
        return sections


class BusinessSchoolAdapter(Wp3Adapter):
    """学院站点默认复用 wp3；只携带学院级 scope，不重复解析逻辑。"""

    def __init__(self, *, publisher: str = "", scope_unit: str = "", **kwargs) -> None:
        super().__init__(
            publisher=publisher,
            scope_unit=scope_unit,
            source_type=kwargs.pop("source_type", "official_college"),
            **kwargs,
        )


class CareerAdapter(Wp3Adapter):
    """就业服务平台适配器：沿用 wp3 结构，栏目发现只保留手续/政策/下载。"""

    def __init__(self, *, publisher: str = "就业指导中心", scope_unit: str = "毕业生", **kwargs) -> None:
        super().__init__(publisher=publisher, scope_unit=scope_unit, **kwargs)

    def discover_sections(self, homepage: PageContent) -> list[SectionSpec]:
        sections = super().discover_sections(homepage)
        return [
            section
            for section in sections
            if any(word in section.name for word in ("就业", "手续", "下载", "政策", "指南", "公示"))
        ]


class NicServiceAdapter(Wp3Adapter):
    """网络信息中心服务目录：把服务卡片和显式 tab 内容当作文章入口。"""

    listing_selectors = (
        ".service-card",
        ".service-item",
        ".service-list",
        ".tab-pane",
        ".faq",
        ".wp_articlecontent",
    )
    article_profile = ArticleProfile(
        title_selectors=[".service-title", ".detail-title", "h1", "h2"],
        date_selectors=[".publish-date", ".date", ".time"],
        content_selectors=[".service-content", ".tab-pane", ".faq", ".wp_articlecontent", "article"],
    )

    def __init__(self, *, publisher: str = "网络信息中心", scope_unit: str = "学生", **kwargs) -> None:
        super().__init__(publisher=publisher, scope_unit=scope_unit, **kwargs)

    def _accept_article_url(self, url: str) -> bool:
        return "/service/" in url.lower() or "/services/" in url.lower()

    def parse_listing(self, page: PageContent, section: SectionSpec) -> ListingResult:
        soup = BeautifulSoup(page.text(), "html.parser")
        pages: list[PageSpec] = []
        seen: set[str] = set()
        selectors = ".service-card a, .service-item a, .service-list a, .tab-pane a[data-url]"
        for anchor in soup.select(selectors):
            spec = self._article_page_for_anchor(anchor, section, page.final_url or page.requested_url)
            if spec and spec.url not in seen:
                pages.append(spec)
                seen.add(spec.url)
        if pages:
            return ListingResult(
                article_pages=pages,
                total_pages=1,
                total_records=len(pages),
                page_hash=sha256(re.sub(r"\s+", "", page.text()).encode("utf-8")).hexdigest(),
                stop_reason="service_cards",
            )
        return super().parse_listing(page, section)
