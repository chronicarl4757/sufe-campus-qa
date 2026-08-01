"""栏目分页：识别“下一页”/数字分页/listN.htm/?page=N，驱动多页抓取。

规格 §五要点：
- 支持 下一页锚文本、数字分页、list.htm→list2.htm→list3.htm、?page=2、页内分页 URL；
- 停止条件：max_list_pages、连续两页无新文章、页面 hash 重复、连续两空页、
  连续请求失败、max_articles（文章日期截止由 engine 在文章级判定）；
- 无法识别的 AJAX/JS 分页标记 requires_adapter，不得把只抓到第一页报告为完整成功。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from sufe_qa.crawler.fetcher import FetchResult

_NEXT_TEXT_RE = re.compile(r"^(下一页|下页|下一张|next|next\s*page|»|›|>)$", re.I)
_JS_PAGER_RE = re.compile(
    r"createPageHTML|_showDynClickBatch|onclick\s*=\s*[\"'][^\"']*goPage|data-page|loadPage\s*\(",
    re.I,
)
_TOTAL_PAGES_RE = re.compile(r"共\s*(\d+)\s*页")
_LISTN_RE = re.compile(r"^(?P<stem>list|index|default)(?P<num>\d*)\.(?P<ext>htm|html|shtml)$", re.I)
_PAGE_QUERY_RE = re.compile(r"^(page|p|pageNo|pageIndex|currentPage)$", re.I)
_CURRENT_PAGE_SEL = (
    ".current, .this-page, .thispage, .on, .active, span.p_pages .cur, .wp_paging .cur"
)


@dataclass
class ListPageResult:
    requested_url: str
    final_url: str
    page_index: int  # 1-based
    article_urls: list[str]
    html_hash: str
    status: str = "ok"
    error: str = ""


@dataclass
class PaginationReport:
    pages: list[ListPageResult] = field(default_factory=list)
    article_urls: list[str] = field(default_factory=list)  # 去重保序
    complete: bool = False  # True = 正常收尾；False = 失败或需要 adapter
    requires_adapter: bool = False
    stop_reason: str = ""

    @property
    def pages_fetched(self) -> int:
        return len([p for p in self.pages if p.status == "ok"])


def page_hash(html: str) -> str:
    """页面指纹：压缩空白后取 sha256，用于重复页检测。"""
    return hashlib.sha256(re.sub(r"\s+", "", html).encode("utf-8")).hexdigest()


def has_js_pagination(html: str) -> bool:
    return bool(_JS_PAGER_RE.search(html or ""))


def _pagination_signal(soup: BeautifulSoup, html: str) -> bool:
    """页面是否存在分页迹象（决定 listN.htm / ?page=N 递增试探是否有依据）。"""
    if has_js_pagination(html) or _TOTAL_PAGES_RE.search(html or ""):
        return True
    if soup.select_one(_CURRENT_PAGE_SEL):
        return True
    for a in soup.find_all("a"):
        t = a.get_text(strip=True)
        if _NEXT_TEXT_RE.match(t) or (t.isdigit() and a.get("href")):
            return True
    return False


def _abs(base: str, href: str) -> str | None:
    from urllib.parse import urljoin

    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    full = urljoin(base, href)
    return full if full.startswith(("http://", "https://")) else None


def _increment_listn(url: str) -> str | None:
    """list.htm → list2.htm；list3.htm → list4.htm。匹配不上返回 None。"""
    from urllib.parse import urlparse, urlunparse

    p = urlparse(url)
    seg = p.path.rstrip("/").rsplit("/", 1)[-1] if p.path.strip("/") else ""
    m = _LISTN_RE.match(seg or "list.htm" if not seg else seg)
    if not m:
        return None
    num = int(m.group("num")) + 1 if m.group("num") else 2
    new_seg = f"{m.group('stem')}{num}.{m.group('ext')}"
    new_path = (
        p.path[: len(p.path) - len(seg)] + new_seg if seg else p.path.rstrip("/") + "/" + new_seg
    )
    return urlunparse(p._replace(path=new_path))


def _increment_page_query(url: str) -> str | None:
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    p = urlparse(url)
    pairs = parse_qsl(p.query)
    for i, (k, v) in enumerate(pairs):
        if _PAGE_QUERY_RE.match(k) and v.isdigit():
            pairs[i] = (k, str(int(v) + 1))
            return urlunparse(p._replace(query=urlencode(pairs)))
    return None


def find_next_page_url(html: str, current_url: str) -> tuple[str | None, bool]:
    """返回 (下一页 URL 或 None, 是否疑似 JS 分页)。

    顺序：①“下一页”锚文本；②数字分页（当前页标记 +1）；
    ③有分页迹象时按 listN.htm 递增；④有分页迹象时按 ?page=N 递增。
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        if _NEXT_TEXT_RE.match(a.get_text(strip=True)):
            if u := _abs(current_url, str(a["href"])):
                return u, False

    cur_el = soup.select_one(_CURRENT_PAGE_SEL)
    if cur_el and cur_el.get_text(strip=True).isdigit():
        want = str(int(cur_el.get_text(strip=True)) + 1)
        for a in soup.find_all("a", href=True):
            if a.get_text(strip=True) == want:
                if u := _abs(current_url, str(a["href"])):
                    return u, False

    signal = _pagination_signal(soup, html)
    if signal:
        # 当前 URL 已带 page 类查询参数时，优先递增参数（比 listN 模式更忠实于原分页）
        from urllib.parse import parse_qsl, urlparse

        has_page_query = any(
            _PAGE_QUERY_RE.match(k) for k, _ in parse_qsl(urlparse(current_url).query)
        )
        if has_page_query:
            if u := _increment_page_query(current_url):
                return u, False
        if u := _increment_listn(current_url):
            return u, False
        if u := _increment_page_query(current_url):
            return u, False
    return None, has_js_pagination(html)


def crawl_list_pages(
    first_url: str,
    fetch_page: Callable[[str], FetchResult],
    extract_links: Callable[[str, str], list[str]],
    *,
    max_list_pages: int = 5,
    max_articles: int = 100,
    max_consecutive_failures: int = 2,
) -> PaginationReport:
    """从第一页起驱动分页抓取。fetch_page/extract_links 注入，测试可完全离线。"""
    report = PaginationReport()
    seen_hashes: set[str] = set()
    url = first_url
    fails = 0
    empty_run = 0
    stale_run = 0

    while url and len(report.pages) < max_list_pages:
        res = fetch_page(url)
        if not res.ok:
            fails += 1
            report.pages.append(
                ListPageResult(
                    requested_url=url,
                    final_url=res.final_url,
                    page_index=len(report.pages) + 1,
                    article_urls=[],
                    html_hash="",
                    status=res.status,
                    error=res.error,
                )
            )
            if fails >= max_consecutive_failures or not report.article_urls:
                report.stop_reason = "fetch_failed"
                return report
            url, js = find_next_page_url("", url)
            if not url:
                report.stop_reason = "fetch_failed"
                return report
            continue

        fails = 0
        html = res.text()
        h = page_hash(html)
        if h in seen_hashes:
            report.stop_reason = "duplicate_page"
            report.complete = True
            return report
        seen_hashes.add(h)

        links = [u for u in extract_links(html, res.final_url) if u]
        new_links = [u for u in links if u not in report.article_urls]
        report.article_urls.extend(new_links)
        report.pages.append(
            ListPageResult(
                requested_url=url,
                final_url=res.final_url,
                page_index=len(report.pages) + 1,
                article_urls=links,
                html_hash=h,
            )
        )

        empty_run = empty_run + 1 if not links else 0
        stale_run = stale_run + 1 if not new_links else 0
        if empty_run >= 2:
            report.stop_reason = "empty_pages"
            report.complete = bool(report.article_urls)
            return report
        if stale_run >= 2:
            report.stop_reason = "no_new_articles"
            report.complete = True
            return report
        if len(report.article_urls) >= max_articles:
            report.article_urls = report.article_urls[:max_articles]
            report.stop_reason = "max_articles"
            report.complete = True
            return report
        if len(report.pages) >= max_list_pages:
            report.stop_reason = "max_list_pages"
            report.complete = True
            return report

        next_url, js = find_next_page_url(html, res.final_url)
        if not next_url:
            if js:
                report.requires_adapter = True
                report.stop_reason = "requires_adapter"
                report.complete = False
            else:
                report.stop_reason = "no_next_page"
                report.complete = True
            return report
        url = next_url

    report.stop_reason = "max_list_pages"
    report.complete = True
    return report
