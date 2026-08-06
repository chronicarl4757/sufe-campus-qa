"""article.py（文章元数据解析 + 附件发现）与 pagination.py（栏目分页）离线测试。

Run: python -m pytest tests/test_article_pagination.py -v
"""

from __future__ import annotations

from sufe_qa.crawler.article import (
    _normalize_date,
    discover_attachments,
    is_low_quality_title,
    parse_article,
)
from sufe_qa.crawler.fetcher import FetchResult
from sufe_qa.crawler.pagination import crawl_list_pages, find_next_page_url
from sufe_qa.crawler.profile import ArticleProfile

from bs4 import BeautifulSoup

BASE = "https://scai.sufe.edu.cn/bkspy/"

ARTICLE_HTML = """
<html><head>
<title>关于做好2025年推免工作的通知|本科生培养 - 计算机与人工智能学院</title>
<meta property="og:title" content="关于做好2025年推免工作的通知">
</head><body>
<div class="wp_breadcrumb">首页 &gt; 本科生培养 &gt; 正文</div>
<h1 class="arti_title">关于做好2025年推免工作的通知</h1>
<div class="arti_update">发布时间：2025-09-01</div>
<div class="wp_articlecontent">
<p>各学院、各位同学：</p>
<p>现将我校2025年推荐优秀应届本科毕业生免试攻读研究生工作有关安排通知如下。</p>
<p>具体申请条件、材料清单与时间安排详见附件。</p>
<p><a href="/_upload/article/files/ab/cd/ef001.pdf">附件1：2025年推免工作实施办法.pdf</a></p>
<p><a href="../files/list2025">附件2：推荐名单表格</a></p>
<p><a href="download.jsp?fileId=abc123" download>点击下载材料汇总</a></p>
</div>
</body></html>
"""


def _soup(html: str):
    return BeautifulSoup(html, "html.parser")


# ---------------- 日期规范化 ----------------


def test_normalize_date_variants():
    assert _normalize_date("2025年3月5日") == "2025-03-05"
    assert _normalize_date("2025/3/5") == "2025-03-05"
    assert _normalize_date("2025-3-5") == "2025-03-05"
    assert _normalize_date("2025.03.05") == "2025-03-05"
    assert _normalize_date("发布时间：2025-13-45") == "unknown"
    assert _normalize_date("没有日期") == "unknown"
    assert _normalize_date("") == "unknown"


def test_date_never_falls_back_to_fetch_time():
    html = "<html><body><h1>某通知</h1><p>正文内容，没有任何日期信息。</p></body></html>"
    meta = parse_article(html, "https://scai.sufe.edu.cn/info/1001.htm")
    assert meta.publish_date == "unknown"


def test_labeled_date_outranks_conflicting_generic_selector_with_evidence():
    html = """
    <html><body>
      <div class="sidebar-date">历史推荐：2015-06-20</div>
      <article><h1>研究生复试通知</h1><p>发布时间：2025-05-09</p>
      <p>本通知包含申请条件、材料清单、办理流程和咨询方式。</p></article>
    </body></html>
    """
    profile = ArticleProfile(date_selectors=[".sidebar-date"], content_selectors=["article"])
    meta = parse_article(html, "https://gs.sufe.edu.cn/Home/Detail/5850", profile)
    assert meta.publish_date == "2025-05-09"
    assert meta.publish_date_evidence == "发布时间：2025-05-09"
    assert meta.publish_date_confidence == 1.0
    assert meta.date_conflict is True


# ---------------- 标题回退链 ----------------


def test_title_profile_selector_first():
    profile = ArticleProfile(title_selectors=[".arti_title"])
    meta = parse_article(ARTICLE_HTML, f"{BASE}info/1001.htm", profile)
    assert meta.title == "关于做好2025年推免工作的通知"
    assert meta.title_source == "profile_selector"
    assert not meta.low_quality_title


def test_title_og_then_h1():
    html = """
    <html><head><meta property="og:title" content="OG 标题"></head>
    <body><h1>H1 标题</h1><p>这是一段足够长的正文内容，用来通过正文抽取的最小长度门槛。</p></body></html>
    """
    meta = parse_article(html, f"{BASE}info/1002.htm")
    assert meta.title == "OG 标题"
    assert meta.title_source == "og"
    html_no_og = html.replace('<meta property="og:title" content="OG 标题">', "")
    meta2 = parse_article(html_no_og, f"{BASE}info/1002.htm")
    assert meta2.title == "H1 标题"
    assert meta2.title_source == "h1"


def test_title_breadcrumb_html_title():
    html = "<html><head><title>某管理办法|研究生院 - 上海财经大学</title></head><body><p>正文。</p></body></html>"
    meta = parse_article(html, "https://gs.sufe.edu.cn/Home/Detail/6946")
    assert meta.title == "某管理办法"
    assert meta.title_source == "html_title"


def test_title_url_filename_and_low_quality():
    html = "<html><body><p>只有正文没有标题。</p></body></html>"
    meta = parse_article(html, f"{BASE}03a91ba5c9a8.htm")
    assert meta.title_source == "url_filename"
    assert meta.low_quality_title


def test_low_quality_title_patterns():
    assert is_low_quality_title("03a91ba5c9a8")
    assert is_low_quality_title("首页")
    assert is_low_quality_title("通知公告")
    assert is_low_quality_title("欢迎访问")
    assert is_low_quality_title("公示专栏")
    assert is_low_quality_title("硕士生招生")
    assert is_low_quality_title("")
    assert not is_low_quality_title("关于做好2025年推免工作的通知")


def test_h1_column_name_falls_back_to_breadcrumb_title():
    """gs 站详情页 h1 是栏目名：命中 <title> 面包屑非首段时跳过 h1 继续回退。"""
    html = """
    <html><head><title>上海财经大学2026年硕士研究生招生考试调剂复试考生名单|公示专栏|招生信息 - 上海财经大学研究生院</title></head>
    <body><h1>公示专栏</h1><p>本页内容未经许可，禁止一切形式的转载。发布时间：2026-05-07。</p></body></html>
    """
    meta = parse_article(html, "https://gs.sufe.edu.cn/Home/Detail/8008")
    assert meta.title == "上海财经大学2026年硕士研究生招生考试调剂复试考生名单"
    assert meta.title_source == "html_title"


def test_h1_matching_breadcrumb_first_segment_kept():
    """h1 与面包屑首段一致时是真正的文章名，h1 正常胜出。"""
    html = """
    <html><head><title>关于开学报到的通知|通知公告 - 某学院</title></head>
    <body><h1>关于开学报到的通知</h1><p>请各位新生按时报到，携带录取通知书与身份证件。</p></body></html>
    """
    meta = parse_article(html, "https://gs.sufe.edu.cn/Home/Detail/7000")
    assert meta.title == "关于开学报到的通知"
    assert meta.title_source == "h1"


# ---------------- 附件发现 ----------------


def test_discover_attachments_full_article():
    cands = discover_attachments(_soup(ARTICLE_HTML), f"{BASE}info/1001.htm")
    urls = {c.requested_url for c in cands}
    assert "https://scai.sufe.edu.cn/_upload/article/files/ab/cd/ef001.pdf" in urls
    assert "https://scai.sufe.edu.cn/bkspy/files/list2025" in urls  # 相对链接绝对化
    assert (
        "https://scai.sufe.edu.cn/bkspy/info/download.jsp?fileId=abc123" in urls
    )  # 同目录相对链接


def test_attachment_scoring_reasons():
    cands = {
        c.requested_url: c
        for c in discover_attachments(_soup(ARTICLE_HTML), f"{BASE}info/1001.htm")
    }
    pdf = cands["https://scai.sufe.edu.cn/_upload/article/files/ab/cd/ef001.pdf"]
    assert "extension" in pdf.discovery_reason
    assert "url_path" in pdf.discovery_reason
    assert "anchor_text" in pdf.discovery_reason
    assert pdf.candidate_score >= 0.8
    noext = cands["https://scai.sufe.edu.cn/bkspy/files/list2025"]
    assert "extension" not in noext.discovery_reason  # 无后缀也靠路径+锚文本入选


def test_nav_download_link_filtered():
    html = f"""
    <html><body>
    <ul class="nav"><li><a href="{BASE}download.htm">下载专区</a></li></ul>
    <p>正文内容。</p>
    </body></html>
    """
    cands = discover_attachments(_soup(html), f"{BASE}info/1003.htm")
    # 仅锚文本一个信号（0.3）不达阈值
    assert all("download.htm" not in c.requested_url for c in cands)


def test_embedded_attachment_elements():
    html = """
    <html><body>
    <iframe src="/_upload/viewer/doc123.pdf"></iframe>
    <embed src="/files/slides.pptx">
    <object data="/system/resource/file789"></object>
    </body></html>
    """
    cands = discover_attachments(_soup(html), f"{BASE}info/1004.htm")
    urls = {c.requested_url for c in cands}
    assert "https://scai.sufe.edu.cn/_upload/viewer/doc123.pdf" in urls
    assert "https://scai.sufe.edu.cn/files/slides.pptx" in urls
    obj = next(c for c in cands if c.requested_url.endswith("file789"))
    assert "embedded" in obj.discovery_reason
    assert "url_path" in obj.discovery_reason


def test_javascript_and_mailto_ignored():
    html = """
    <html><body>
    <a href="javascript:download('x.pdf')">附件下载</a>
    <a href="mailto:admin@sufe.edu.cn">附件：联系我们</a>
    </body></html>
    """
    assert discover_attachments(_soup(html), f"{BASE}info/1005.htm") == []


# ---------------- 正文与面包屑 ----------------


def test_body_and_breadcrumbs():
    meta = parse_article(ARTICLE_HTML, f"{BASE}info/1001.htm")
    assert "推荐优秀应届本科毕业生" in meta.body_text
    assert "本科生培养" in meta.breadcrumbs
    assert "首页" not in meta.breadcrumbs  # 面包屑前缀被剔除
    assert meta.publish_date == "2025-09-01"


def test_content_selector_priority():
    html = """
    <html><body>
    <div class="sidebar"><p>侧边栏干扰文本，不应进入正文。</p></div>
    <div class="wp_articlecontent"><p>这是真正的正文内容，长度需要足够超过五十个字符的门槛要求，因此这里再补充一段说明文字以确保选择器路径被采用。</p></div>
    </body></html>
    """
    profile = ArticleProfile(content_selectors=[".wp_articlecontent"])
    meta = parse_article(html, f"{BASE}info/1006.htm", profile)
    assert "真正的正文内容" in meta.body_text
    assert "侧边栏干扰" not in meta.body_text


# ---------------- 分页 ----------------


def _fetcher_ok(pages: dict[str, str]):
    def fetch(url: str) -> FetchResult:
        if url in pages:
            return FetchResult(requested_url=url, final_url=url, content=pages[url].encode("utf-8"))
        return FetchResult(
            requested_url=url, final_url=url, status="http_error", status_code=404, error="404"
        )

    return fetch


def _extract(html: str, base: str) -> list[str]:
    return [
        a["href"]
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)
        if "info/" in a["href"]
    ]


def test_pagination_single_page_complete():
    page1 = '<html><body><a href="info/1.htm">文章1</a><a href="info/2.htm">文章2</a></body></html>'
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok({f"{BASE}list.htm": page1}), _extract)
    assert rep.complete and rep.stop_reason == "no_next_page"
    assert not rep.requires_adapter
    assert rep.article_urls == ["info/1.htm", "info/2.htm"]


def test_pagination_next_anchor_three_pages():
    p1 = '<a href="info/1.htm">a</a><a href="list2.htm">下一页</a>'
    p2 = '<a href="info/2.htm">a</a><a href="list3.htm">下一页</a>'
    p3 = '<a href="info/3.htm">a</a>'
    pages = {f"{BASE}list.htm": p1, f"{BASE}list2.htm": p2, f"{BASE}list3.htm": p3}
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok(pages), _extract)
    assert rep.complete
    assert rep.article_urls == ["info/1.htm", "info/2.htm", "info/3.htm"]
    assert rep.pages_fetched == 3


def test_pagination_listn_pattern_with_js_pager():
    # wp3 典型：分页器由 createPageHTML 生成，但 listN.htm 静态文件真实存在
    p1 = '<a href="info/1.htm">a</a><script>createPageHTML(3, 1, "list", "htm");</script>'
    p2 = '<a href="info/2.htm">a</a><script>createPageHTML(3, 2, "list", "htm");</script>'
    p3 = '<a href="info/3.htm">a</a>'
    pages = {f"{BASE}list.htm": p1, f"{BASE}list2.htm": p2, f"{BASE}list3.htm": p3}
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok(pages), _extract)
    assert rep.complete, rep.stop_reason
    assert len(rep.article_urls) == 3


def test_pagination_page_query():
    p1 = '<a href="info/1.htm">a</a><a href="?page=2">2</a>'
    p2 = '<a href="info/2.htm">a</a>'
    pages = {f"{BASE}list.htm?page=1": p1, f"{BASE}list.htm?page=2": p2}
    rep = crawl_list_pages(f"{BASE}list.htm?page=1", _fetcher_ok(pages), _extract)
    assert rep.article_urls == ["info/1.htm", "info/2.htm"]


def test_pagination_duplicate_page_stops():
    # list2.htm 返回与 list.htm 完全相同内容 → 重复指纹停止
    p1 = '<a href="info/1.htm">a</a><span class="current">1</span><a href="list2.htm">2</a>'
    pages = {f"{BASE}list.htm": p1, f"{BASE}list2.htm": p1}
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok(pages), _extract)
    assert rep.stop_reason == "duplicate_page"
    assert rep.complete
    assert rep.article_urls == ["info/1.htm"]


def test_pagination_no_new_articles_stops():
    p1 = '<a href="info/1.htm">a</a><a href="list2.htm">下一页</a>'
    p2 = '<a href="info/1.htm">a</a><a href="list3.htm">下一页</a>'  # 无新文章但内容不同
    p3 = '<a href="info/1.htm">a</a>'
    pages = {f"{BASE}list.htm": p1, f"{BASE}list2.htm": p2, f"{BASE}list3.htm": p3 + "x"}
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok(pages), _extract)
    assert rep.stop_reason == "no_new_articles"
    assert rep.complete


def test_pagination_empty_pages_stop():
    p1 = '<a href="list2.htm">下一页</a>'
    p2 = '<div>无内容</div><a href="list3.htm">下一页</a>'
    pages = {f"{BASE}list.htm": p1, f"{BASE}list2.htm": p2, f"{BASE}list3.htm": "x"}
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok(pages), _extract)
    assert rep.stop_reason == "empty_pages"
    assert not rep.complete


def test_pagination_max_list_pages():
    pages = {}
    for i in range(1, 10):
        seg = "list.htm" if i == 1 else f"list{i}.htm"
        nxt = f"list{i + 1}.htm"
        pages[f"{BASE}{seg}"] = f'<a href="info/{i}.htm">a</a><a href="{nxt}">下一页</a>'
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok(pages), _extract, max_list_pages=3)
    assert rep.pages_fetched == 3
    assert rep.stop_reason == "max_list_pages"
    assert rep.complete


def test_pagination_max_articles():
    p1 = '<a href="info/1.htm">a</a><a href="info/2.htm">b</a><a href="info/3.htm">c</a><a href="list2.htm">下一页</a>'
    pages = {f"{BASE}list.htm": p1}
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok(pages), _extract, max_articles=2)
    assert rep.article_urls == ["info/1.htm", "info/2.htm"]
    assert rep.stop_reason == "max_articles"


def test_pagination_requires_adapter():
    # JS 分页且 URL 不是 listN.htm 模式 → 标记 requires_adapter，不得报完整
    p1 = '<a href="info/1.htm">a</a><div class="pager" data-page="2"></div>'
    rep = crawl_list_pages(
        "https://scai.sufe.edu.cn/api/news",
        _fetcher_ok({"https://scai.sufe.edu.cn/api/news": p1}),
        _extract,
    )
    assert rep.requires_adapter
    assert not rep.complete
    assert rep.stop_reason == "requires_adapter"


def test_pagination_first_page_failure_incomplete():
    rep = crawl_list_pages(f"{BASE}list.htm", _fetcher_ok({}), _extract)
    assert not rep.complete
    assert rep.stop_reason == "fetch_failed"


def test_find_next_page_url_none_on_plain_page():
    url, js = find_next_page_url("<html><body><p>hi</p></body></html>", f"{BASE}list.htm")
    assert url is None and not js


def test_discover_attachments_finds_pdfsrc_player_and_sudyfile_title():
    """gongkai/cwc 的内嵌 PDF：div/span[pdfsrc]，文件名在 sudyfile-attr。"""
    from bs4 import BeautifulSoup

    from sufe_qa.crawler.article import discover_attachments

    html = """
    <div class="wp_articlecontent">
      <div class="wp_pdf_player" pdfsrc="/_upload/article/files/ab/cd/policy.pdf"
           sudyfile-attr="{'title':'上海财经大学学生宿舍管理办法.pdf'}"></div>
      <span pdfsrc="/_upload/article/files/ef/gh/rules.docx"></span>
    </div>
    """
    cands = discover_attachments(
        BeautifulSoup(html, "html.parser"),
        "https://gongkai.sufe.edu.cn/a3/38/c13790a41784/page.htm",
    )
    urls = {c.requested_url: c for c in cands}
    assert "https://gongkai.sufe.edu.cn/_upload/article/files/ab/cd/policy.pdf" in urls
    assert "https://gongkai.sufe.edu.cn/_upload/article/files/ef/gh/rules.docx" in urls
    assert urls[
        "https://gongkai.sufe.edu.cn/_upload/article/files/ab/cd/policy.pdf"
    ].anchor_text == ("上海财经大学学生宿舍管理办法.pdf")
