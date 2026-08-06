from __future__ import annotations

from sufe_qa.crawler.adapters import (
    BusinessSchoolAdapter,
    GraduateSchoolAdapter,
    JwcAdapter,
    NicServiceAdapter,
    PageContent,
    PageSpec,
    SectionSpec,
    Wp3Adapter,
)


def _page(url: str, html: str, mime: str = "text/html") -> PageContent:
    return PageContent(
        requested_url=url,
        final_url=url,
        status="ok",
        content=html.encode("utf-8"),
        mime_type=mime,
    )


def _section(url: str = "https://jwc.sufe.edu.cn/5127/list.htm") -> SectionSpec:
    return SectionSpec(
        section_id="jwc-5127",
        name="教学通知",
        list_url=url,
        category="学工事务",
        publisher="教务处",
        source_type="official_department",
        scope_unit="",
    )


WP3_LIST = """
<html><body>
<aside><a href="/bad/c1a9/page.htm">推荐新闻</a></aside>
<div id="wp_news_w6"><ul class="wp_article_list">
  <li><a href="/c1/a1/page.htm">缓考办理通知</a><span>2026-01-02</span></li>
  <li><a href="/c1/a2/page.htm">重修课程办理通知</a><span>2025-12-01</span></li>
  <li><a href="/_upload/article/files/guide.pdf">学生证补办指南</a><span>2025-11-01</span></li>
</ul></div>
<div id="wp_paging_w6"><span class="curr_page">1</span><span class="all_pages">3</span>
  <a class="next" href="/5127/list2.htm">下一页</a></div>
<footer><a href="/c1/c99/page.htm">友情链接</a></footer>
</body></html>
"""


def test_wp3_listing_uses_article_container_and_returns_pagination_metadata():
    adapter = Wp3Adapter(publisher="教务处")
    result = adapter.parse_listing(_page(_section().list_url, WP3_LIST), _section())

    assert [p.url for p in result.article_pages] == [
        "https://jwc.sufe.edu.cn/c1/a1/page.htm",
        "https://jwc.sufe.edu.cn/c1/a2/page.htm",
        "https://jwc.sufe.edu.cn/_upload/article/files/guide.pdf",
    ]
    assert result.article_pages[-1].page_kind == "attachment"
    assert result.next_page is not None
    assert result.next_page.url.endswith("/5127/list2.htm")
    assert result.total_pages == 3


def test_wp3_does_not_use_broad_page_htm_selector_as_primary_logic():
    html = """
    <html><body>
      <a href="/c1/a0/page.htm">页脚推荐</a>
      <div class="unrelated"><a href="/c1/a1/page.htm">侧边栏</a></div>
    </body></html>
    """
    result = Wp3Adapter(publisher="教务处").parse_listing(
        _page(_section().list_url, html), _section()
    )
    assert result.article_pages == []


def test_jwc_adapter_treats_static_process_page_as_article_with_attachments():
    section = SectionSpec(
        section_id="jwc-5124",
        name="办事流程",
        list_url="https://jwc.sufe.edu.cn/5124/list.htm",
        category="本科教务",
        publisher="教务处",
        source_type="official_department",
        scope_unit="本科生",
    )
    html = """
    <html><body><div class="col_news_head"><h2>办事流程</h2></div>
    <div class="wp_articlecontent">
      <p>本科生选课、重修、休学复学、缓考、转专业和学生证补办办理入口。</p>
      <a href="/_upload/article/files/leave.pdf">休学与复学</a>
      <a href="/_upload/article/files/leave.xls">休学申请表</a>
    </div></body></html>
    """
    adapter = JwcAdapter()
    listing = adapter.parse_listing(_page(section.list_url, html), section)
    assert len(listing.article_pages) == 1
    assert listing.article_pages[0].metadata["inline"] == "true"

    article = adapter.parse_article(
        _page(section.list_url, html), listing.article_pages[0]
    )
    assert article.title == "办事流程"
    assert len(article.attachments) == 2
    assert article.source_type == "official_department"


def test_graduate_school_adapter_parses_home_list_detail_and_query_pagination():
    section = SectionSpec(
        section_id="gs-49",
        name="培养工作通知公告",
        list_url="https://gs.sufe.edu.cn/Home/List/49",
        category="研究生培养与学位",
        publisher="研究生院",
        source_type="official_department",
        scope_unit="研究生",
    )
    html = """
    <html><body><div class="single-blog-item">
      <div class="blog-content"><a href="/Home/Detail/8001">研究生选课通知</a>
      <a class="read-more" href="/Home/Detail/8001">阅读</a></div>
      <p class="blog-meta">发布时间 | 2026-06-01</p>
    </div><div class="pagination-block"><a href="/Home/List/49?page=2">下一页</a>
      <a href="/Home/List/49?page=13">尾页</a></div></body></html>
    """
    adapter = GraduateSchoolAdapter()
    result = adapter.parse_listing(_page(section.list_url, html), section)
    assert [p.url for p in result.article_pages] == [
        "https://gs.sufe.edu.cn/Home/Detail/8001"
    ]
    assert result.next_page is not None
    assert result.next_page.url.endswith("?page=2")
    assert result.total_pages == 13

    article_html = """
    <html><head><title>研究生选课通知|培养工作 - 研究生院</title></head>
    <body><h1>研究生选课通知</h1><div class="content">
    <p>研究生选课时间、课程退选和培养方案要求见本通知正文。</p></div></body></html>
    """
    article = adapter.parse_article(
        _page(result.article_pages[0].url, article_html), result.article_pages[0]
    )
    assert article.title == "研究生选课通知"
    assert "选课时间" in article.body_text


def test_graduate_school_adapter_prefers_labeled_publish_date_over_sidebar_info():
    """GS 全局 .info 含旧文章日期时，必须采用详情正文旁的“发布时间”。"""
    spec = PageSpec(
        url="https://gs.sufe.edu.cn/Home/Detail/5850",
        section_id="gs-31",
        page_kind="article",
        title_hint="2025年硕士研究生复试通知",
        publisher_hint="上海财经大学研究生院",
        category="推免升学",
        source_type="official_department",
        scope_unit="研究生",
    )
    html = """
    <html><head><title>2025年硕士研究生复试通知|招生信息</title></head><body>
      <aside class="info"><a>历史文章</a><span>2015-06-20</span></aside>
      <div class="single-programme">
        <h5>2025年硕士研究生复试通知</h5>
        <div class="conn"><p>本通知说明复试申请条件、材料、办理流程和时间安排。</p></div>
        <div class="key-feature"><p>发布时间：2025-05-09</p></div>
      </div>
    </body></html>
    """
    article = GraduateSchoolAdapter().parse_article(_page(spec.url, html), spec)
    assert article.publish_date == "2025-05-09"
    assert "发布时间：2025-05-09" in article.publish_date_evidence
    assert article.publish_date_confidence >= 0.95
    assert article.date_conflict is False


def test_nic_service_adapter_discovers_service_cards_tabs_and_faq():
    section = SectionSpec(
        section_id="nic-student-services",
        name="学生服务",
        list_url="https://nic.sufe.edu.cn/services/student",
        category="校园生活",
        publisher="网络信息中心",
        source_type="official_department",
        scope_unit="学生",
    )
    html = """
    <html><body><div class="service-card"><a href="/service/identity">统一认证</a></div>
    <div class="service-card"><a href="/service/wifi">无线联网</a></div>
    <div class="tab-pane" id="faq"><h3>常见问题</h3>
      <p>密码忘记后可以通过统一认证页面找回。</p></div></body></html>
    """
    result = NicServiceAdapter().parse_listing(_page(section.list_url, html), section)
    assert [p.title_hint for p in result.article_pages] == ["统一认证", "无线联网"]
    assert all(p.page_kind == "article" for p in result.article_pages)


def test_business_school_adapter_reuses_wp3_contract():
    adapter = BusinessSchoolAdapter(publisher="会计学院", scope_unit="会计学院")
    assert isinstance(adapter, Wp3Adapter)
    pages = list(adapter.iter_list_pages(_section()))
    assert pages[0].page_kind == "listing"
