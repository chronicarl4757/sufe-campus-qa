from __future__ import annotations

from types import SimpleNamespace

from sufe_qa.crawler.adapters import GraduateSchoolAdapter, SectionSpec
from sufe_qa.crawler.adapter_engine import AdapterCrawlOptions, crawl_adapter_section
from sufe_qa.crawler.engine import CrawlReport
from sufe_qa.crawler.fetcher import FetchResult


BASE = "https://gs.sufe.edu.cn"


class StubFetcher:
    def __init__(self, routes: dict[str, FetchResult]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def fetch(self, url: str, kind: str = "html", headers: dict | None = None) -> FetchResult:
        self.calls.append((url, kind))
        result = self.routes.get(url)
        if result is None:
            return FetchResult(
                requested_url=url,
                final_url=url,
                status="http_error",
                status_code=404,
                error="404",
            )
        return result


def _html(url: str, body: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        content=body.encode("utf-8"),
        mime_type="text/html",
        status_code=200,
    )


def _pdf(url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        content=b"pdf bytes",
        mime_type="application/pdf",
        status_code=200,
    )


def test_adapter_engine_drives_pagination_article_and_attachment_without_adapter_io(tmp_path):
    list1 = f"{BASE}/Home/List/49"
    list2 = f"{BASE}/Home/List/49?page=2"
    article1 = f"{BASE}/Home/Detail/8001"
    article2 = f"{BASE}/Home/Detail/8002"
    attachment = f"{BASE}/_upload/files/guide.pdf"
    routes = {
        list1: _html(
            list1,
            f"""<div class="single-blog-item"><div class="blog-content">
            <a href="/Home/Detail/8001">研究生选课通知</a></div></div>
            <div class="pagination-block"><a href="{list2}">下一页</a>
            <a href="{BASE}/Home/List/49?page=2">尾页</a></div>""",
        ),
        list2: _html(
            list2,
            """<div class="single-blog-item"><div class="blog-content">
            <a href="/Home/Detail/8002">研究生学分认定办法</a></div></div>""",
        ),
        article1: _html(
            article1,
            """<html><head><title>研究生选课通知|培养工作</title></head>
            <body><h1>研究生选课通知</h1><div class="content">
            研究生选课时间和退选流程请按照培养工作要求办理，具体材料见附件。</div>
            <a href="/_upload/files/guide.pdf">选课指南</a></body></html>""",
        ),
        article2: _html(
            article2,
            """<html><head><title>研究生学分认定办法|培养工作</title></head>
            <body><h1>研究生学分认定办法</h1><div class="content">
            研究生学分认定的条件、材料和审批流程。</div></body></html>""",
        ),
        attachment: _pdf(attachment),
    }
    section = SectionSpec(
        section_id="gs-49",
        name="培养工作",
        list_url=list1,
        category="研究生培养与学位",
        publisher="研究生院",
        source_type="official_department",
        scope_unit="研究生",
    )
    fetcher = StubFetcher(routes)
    report = CrawlReport(host="gs.sufe.edu.cn")
    articles = crawl_adapter_section(
        GraduateSchoolAdapter(),
        section,
        fetcher,
        options=AdapterCrawlOptions(max_list_pages=10, max_articles=10),
        parse_attachment=lambda filename, content: SimpleNamespace(
            parse_status="ok", text="选课申请条件、材料和办理流程。"
        ),
        report=report,
    )

    assert [article.title for article in articles] == ["研究生选课通知", "研究生学分认定办法"]
    assert len(articles[0].downloaded) == 1
    assert articles[0].downloaded[0].parse.parse_status == "ok"
    assert report.list_pages_fetched == 2
    assert report.articles_found == 2
    assert report.attachments_downloaded == 1
    assert (list2, "html") in fetcher.calls


def test_adapter_engine_uses_inline_jwc_page_without_refetching():
    url = "https://jwc.sufe.edu.cn/5124/list.htm"
    html = """<div class="wp_articlecontent"><p>本科生办事流程和材料说明。</p>
    <a href="/_upload/article/files/leave.pdf">休学与复学</a></div>"""
    section = SectionSpec(
        section_id="jwc-5124",
        name="办事流程",
        list_url=url,
        category="本科教务",
        publisher="教务处",
        source_type="official_department",
        scope_unit="本科生",
    )
    attachment = "https://jwc.sufe.edu.cn/_upload/article/files/leave.pdf"
    fetcher = StubFetcher({url: _html(url, html), attachment: _pdf(attachment)})
    articles = crawl_adapter_section(
        __import__("sufe_qa.crawler.adapters", fromlist=["JwcAdapter"]).JwcAdapter(),
        section,
        fetcher,
        parse_attachment=lambda filename, content: SimpleNamespace(
            parse_status="ok", text="休学申请条件、材料和复学流程。"
        ),
    )
    assert len(articles) == 1
    assert articles[0].title == "办事流程"
    assert [call for call in fetcher.calls if call[0] == url] == [(url, "html")]


def test_title_include_filter_narrows_wide_section(tmp_path):
    """财务处宽栏目：title_include 只保留学生缴费相关文章。"""
    from sufe_qa.crawler.adapter_engine import _filter_listing_titles
    from sufe_qa.crawler.adapters import ListingResult, PageSpec, SectionSpec

    section = SectionSpec(
        section_id="cwc-xxgg",
        name="通知公告",
        list_url="https://cwc.sufe.edu.cn/xxgg_2982/list.htm",
        category="学工事务",
        publisher="财务处",
        source_type="official_department",
        metadata={"title_include": "缴费|学费|收费"},
    )
    specs = [
        PageSpec(url=f"https://cwc.sufe.edu.cn/a/{i}", section_id=section.section_id, title_hint=t)
        for i, t in enumerate(["2026级本科新设专业学费标准的公示", "科研经费报销培训通知"])
    ]
    listing = _filter_listing_titles(ListingResult(article_pages=specs), section)
    assert [s.title_hint for s in listing.article_pages] == ["2026级本科新设专业学费标准的公示"]


def test_is_attachment_url_rejects_htm_pages_with_material_anchor():
    """hq 办事指南列表把锚文本含「材料/下载」的 page.htm/list.htm 误判为附件。"""
    from sufe_qa.crawler.adapters import _is_attachment_url

    assert not _is_attachment_url("https://hq.sufe.edu.cn/f8/cf/c20020a260303/page.htm", "住宿申请材料")
    assert not _is_attachment_url("https://hq.sufe.edu.cn/19990/list.htm", "常用下载")
    assert _is_attachment_url("https://hq.sufe.edu.cn/_upload/files/a.pdf", "住宿申请材料")
    assert _is_attachment_url("https://hq.sufe.edu.cn/download.jsp?fileId=1", "表格")
