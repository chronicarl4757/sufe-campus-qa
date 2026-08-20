"""数据源扩建 Phase 1：学院/书院/招生网 source 配置与过滤行为回归测试。

覆盖任务要求的四类行为：
- source filtering：本科培养标题进入，学院新闻/研究生招生/讲座/名单公示排除；
- scope：publisher / scope_unit / source_section 正确；
- attachment：学院文章/栏目直链附件（如 ksc 培养方案 docx）识别为附件页；
- version：同系列 2025/2026 年度方案只保留一个 active canonical。
"""

from __future__ import annotations

from datetime import date

import pytest

from sufe_qa.crawler.adapter_engine import _filter_listing_titles
from sufe_qa.crawler.adapters import (
    BusinessSchoolAdapter,
    CobUndergradAdapter,
    ListingResult,
    PageContent,
    PageSpec,
    SectionSpec,
)
from sufe_qa.crawler.authority import adapter_for_source, load_authority_sources
from sufe_qa.ingest.lifecycle import LifecycleCandidate, resolve_lifecycle

SOURCE_FILE = "data/sources/sufe_authoritative.yaml"

_PHASE1_SOURCES = {
    "zs": ("wp3", "official_department", "本科生"),
    "sof": ("business_school", "official_college", "金融学院本科生"),
    "cob": ("cob_undergrad", "official_college", "商学院本科生"),
    "econ": ("business_school", "official_college", "经济学院本科生"),
    "cpi": ("business_school", "official_college", "财税投资学院本科生"),
    "ssds": ("business_school", "official_college", "统计与数据科学学院本科生"),
    "sime": ("business_school", "official_college", "信息管理与工程学院本科生"),
    "scai": ("business_school", "official_college", "计算机与人工智能学院本科生"),
    "de": ("business_school", "official_college", "数字经济学院本科生"),
    "law": ("business_school", "official_college", "法学院本科生"),
    "sfs": ("business_school", "official_college", "外国语学院本科生"),
    "ksc": ("business_school", "official_college", "匡时书院学生"),
    "aiclg": ("business_school", "official_college", "前沿交叉书院学生"),
}


def _sources():
    return {s.source_id: s for s in load_authority_sources(SOURCE_FILE)}


def test_phase1_sources_present_with_college_scope():
    sources = _sources()
    assert set(_PHASE1_SOURCES) <= sources.keys()
    for source_id, (adapter_name, source_type, scope_unit) in _PHASE1_SOURCES.items():
        source = sources[source_id]
        assert source.adapter_name == adapter_name, source_id
        assert source.source_type == source_type, source_id
        assert source.scope_unit == scope_unit, source_id
        assert source.sections, source_id
        # adapter 工厂必须能实例化每个新 source
        adapter_for_source(source)


def test_phase1_gongkai_expansion_sections():
    gongkai = _sources()["gongkai"]
    urls = {section.list_url for section in gongkai.sections}
    assert {
        "https://gongkai.sufe.edu.cn/xkzysz/list.htm",
        "https://gongkai.sufe.edu.cn/kcyjxjh/list.htm",
        "https://gongkai.sufe.edu.cn/xjxwgl/list.htm",
        "https://gongkai.sufe.edu.cn/jysfqk/list.htm",
        "https://gongkai.sufe.edu.cn/jlcfbf/list.htm",
        "https://gongkai.sufe.edu.cn/sstjyclcx/list.htm",
    } <= urls


def test_aiclg_inline_section_and_sfs_scope_override():
    sources = _sources()
    aiclg = {s.name: s for s in sources["aiclg"].sections}
    assert aiclg["招生专业"].metadata["inline_article"] == "true"
    sfs = {s.name: s for s in sources["sfs"].sections}
    assert sfs["大学外语教学"].scope_unit == "全体本科生"
    assert sfs["本科生教育"].scope_unit == "外国语学院本科生"


# ---- source filtering：真实探测样本标题，宽栏目必须收规则、排噪声 ----

_FILTER_CASES = [
    # (source_id, section_name, kept, dropped)
    (
        "zs",
        "招生动态",
        ["上海财经大学2026年第二学士学位招生简章"],
        ["上海财经大学2026年高水平运动队招生简章", "上海财经大学2026年第二学士学位拟录取名单公示"],
    ),
    (
        "sof",
        "本科生",
        ["2023级“金融科技拔尖班”校内新生选拔公告"],
        ["金融学院2026年春季学期本科开学教育系列活动", "2026年金融学院实验班拟录取名单公示"],
    ),
    (
        "cob",
        "重要通知",
        [
            "商学院2024级工商管理（商务分析实验班）面试通知",
            "2024-2025学年第三学期本科生国际课程网上选课通知",
        ],
        [
            "商学院2023级本科生导师制录取名单",
            "上海财经大学关于组织开展第二届全国教材建设奖评选工作的通知",
        ],
    ),
    (
        "cpi",
        "本科生工作动态",
        ["公共经济与管理学院2024年本科生自主选择专业（转专业）工作细则"],
        ["本科教学双月简报（第三期）", "公共经济与管理学院转专业录取名单"],
    ),
    (
        "ssds",
        "本科生",
        ["2024-2025学年本科毕业论文工作流程安排", "本科学位论文模板"],
        ["本科生拔尖型科研训练计划项目结项答辩会", "年级大会暨毕业论文动员会"],
    ),
    (
        "sime",
        "通知公告",
        ["2022年本科生自主转专业报名条件及选拔程序"],
        ["2026年博士研究生招生综合考核通知", "2026年自主转专业拟录取结果公示"],
    ),
    (
        "scai",
        "通知公告",
        ["计算机与人工智能学院2026年本科生转专业工作实施细则"],
        [
            "2026年博士研究生招生综合考核通知",
            "2026自主转专业拟录取结果公示",
            "暑期活动专家推荐信模板（2026）",
            "关于开展2025年计算机与人工智能学院学生会主席与分团委副书记候选人选拔工作的通知",
        ],
    ),
    (
        "de",
        "通知公告",
        ["数字经济学院2026年本科生转专业工作实施细则"],
        [
            "数字经济学院2025级本科转专业拟录取结果公示",
            "2027年接收推荐免试研究生报名通知",
            "2026双创项目立项名单公示",
        ],
    ),
    (
        "law",
        "相关制度",
        ["法学院本科生素质综合评价细则", "法学院法学专业本科毕业论文管理规定"],
        [
            "硕士研究生素质评价细则",
            "博士生综合评价细则",
            "普通高等学校学生管理规定",
            "上海财经大学奖学金评比实施条例",
            "校园地国家助学贷款政策解读",
            "学生申诉处理实施细则",
        ],
    ),
    (
        "sfs",
        "本科生教育",
        [
            "外国语学院本科生海外学习学分认定与课程转换管理办法",
            "上海财经大学外国语学院2026年商务英语专业“英法复语实验班”项目选拔公告",
        ],
        [
            "上海财经大学外国语学院2027年接收优秀应届本科毕业生免试攻读研究生预报名的通知",
            "研思践悟 硕果纷呈",
        ],
    ),
    (
        "sfs",
        "大学外语教学",
        ["2026级本科生大学英语课程分级考试与教学安排", "关于202X级学生大学英语升降级的申请表"],
        ["研究生学术英语论坛通知"],
    ),
    (
        "ksc",
        "通知公告",
        ["2025级匡时书院本科生自主转专业选拔通知", "关于开展2025级新生选拔工作的通知"],
        ["2025年新生选拔结果公告", "匡时讲堂第9期回顾", "学生科创项目立项名单公示"],
    ),
    (
        "gongkai",
        "课程与教学计划",
        [
            "上海财经大学本科各专业培养方案",
            "上海财经大学2024-2025学年第二学期本科课程开设总数及教学计划实施情况",
        ],
        ["上海财经大学2024-2025学年研究生课程开设总数等情况"],
    ),
    (
        "gongkai",
        "奖励处罚办法",
        ["上海财经大学本科生荣誉学士学位授予办法（试行）", "上海财经大学学生考试试场规则"],
        ["上海财经大学研究生“学术之星”评选办法"],
    ),
    (
        "gongkai",
        "学籍管理",
        ["上海财经大学本科学生学籍管理实施细则（2024年）"],
        ["上海财经大学成人高等学历教育学生学籍管理实施细则"],
    ),
]


@pytest.mark.parametrize("source_id,section_name,kept,dropped", _FILTER_CASES)
def test_mixed_sections_keep_rules_and_drop_noise(source_id, section_name, kept, dropped):
    section = next(s for s in _sources()[source_id].sections if s.name == section_name)
    specs = [
        PageSpec(
            url=f"https://example.sufe.edu.cn/a/{i}",
            section_id=section.section_id,
            title_hint=title,
        )
        for i, title in enumerate([*kept, *dropped])
    ]
    listing = _filter_listing_titles(ListingResult(article_pages=specs), section)
    kept_titles = [s.title_hint for s in listing.article_pages]
    assert kept_titles == kept


# ---- cob 自研结构 adapter ----


def test_cob_adapter_parses_post_list_and_swiper():
    adapter = CobUndergradAdapter(publisher="上海财经大学商学院", scope_unit="商学院本科生")
    html = """
    <html><body>
    <div class="swiper-slide"><a href="/UnderGraduate/Detail/11987">国际经济与贸易 了解更多</a></div>
    <div class="post-list" id="news-list">
      <a href="/UnderGraduate/Detail/26605">商学院2024级工商管理（商务分析实验班）面试通知</a>
      <a href="/UnderGraduate">本科生</a>
      <a href="https://mp.weixin.qq.com/s/xyz">微信外链</a>
    </div>
    </body></html>
    """
    url = "https://cob.sufe.edu.cn/UnderGraduate/List/1081"
    page = PageContent(requested_url=url, final_url=url, status="ok", content=html.encode())
    section = SectionSpec(
        section_id="cob-zyjs",
        name="专业介绍",
        list_url=url,
        category="学工事务",
        publisher="上海财经大学商学院",
        source_type="official_college",
    )
    listing = adapter.parse_listing(page, section)
    urls = sorted(s.url for s in listing.article_pages)
    assert urls == [
        "https://cob.sufe.edu.cn/UnderGraduate/Detail/11987",
        "https://cob.sufe.edu.cn/UnderGraduate/Detail/26605",
    ]
    assert listing.next_page is None


def test_cob_adapter_strips_site_suffix_from_article_title():
    adapter = CobUndergradAdapter(publisher="上海财经大学商学院", scope_unit="商学院本科生")
    body = "面试主要考察学生的数据分析与商业理解能力，请携带学生证按时到场。" * 4
    html = f"""
    <html><head><title>商学院2024级工商管理（商务分析实验班）面试通知 - 上海财经大学商学院</title></head>
    <body><article><p>{body}</p></article></body></html>
    """
    url = "https://cob.sufe.edu.cn/UnderGraduate/Detail/26605"
    page = PageContent(requested_url=url, final_url=url, status="ok", content=html.encode())
    spec = PageSpec(url=url, section_id="cob-zyjs", page_kind="article")
    article = adapter.parse_article(page, spec)
    assert article.title == "商学院2024级工商管理（商务分析实验班）面试通知"


# ---- attachment：栏目直链附件（ksc 培养方案 docx 模式）----


def test_listing_direct_attachment_link_becomes_attachment_page():
    adapter = BusinessSchoolAdapter(publisher="上海财经大学匡时书院", scope_unit="匡时书院学生")
    html = """
    <div id="wp_news_w6"><ul>
      <li><a href="/_upload/article/files/ab/cd/plan.docx">匡时书院2023级孙冶方班培养方案</a></li>
      <li><a href="/f3/0f/c12220a258831/page.htm">关于开展2025级新生选拔工作的通知</a></li>
    </ul></div>
    """
    url = "https://ksc.sufe.edu.cn/pyfa/list.htm"
    page = PageContent(requested_url=url, final_url=url, status="ok", content=html.encode())
    section = SectionSpec(
        section_id="ksc-pyfa",
        name="培养方案",
        list_url=url,
        category="学工事务",
        publisher="上海财经大学匡时书院",
        source_type="official_college",
    )
    listing = adapter.parse_listing(page, section)
    kinds = {s.title_hint: s.page_kind for s in listing.article_pages}
    assert kinds["匡时书院2023级孙冶方班培养方案"] == "attachment"
    assert kinds["关于开展2025级新生选拔工作的通知"] == "article"


# ---- version：同系列年度文档只保留一个 active canonical ----


def test_annual_series_keeps_single_active_canonical():
    candidates = [
        LifecycleCandidate(
            doc_id="exp2025",
            title="2025年金融学院实验班选拔方案",
            publisher="上海财经大学金融学院",
            scope_unit="金融学院本科生",
            document_kind="annual_notice",
            publish_date="2025-06-01",
        ),
        LifecycleCandidate(
            doc_id="exp2026",
            title="2026年金融学院实验班选拔方案",
            publisher="上海财经大学金融学院",
            scope_unit="金融学院本科生",
            document_kind="annual_notice",
            publish_date="2026-06-01",
        ),
    ]
    decisions = resolve_lifecycle(
        candidates, time_policy="all_history", evaluated_at=date(2026, 8, 12)
    )
    assert decisions["exp2025"].series_key == decisions["exp2026"].series_key
    assert decisions["exp2026"].retention_status == "active"
    assert decisions["exp2025"].retention_status == "historical"
    assert decisions["exp2025"].canonical_doc_id == "exp2026"


# ---- 表格正文提取：单元格按行合并，数据表不再被误判为导航样板 ----


def test_table_body_extracted_as_rows_passes_quality_gate(tmp_path):
    """招生专业目录式表格页：行级合并后正文应通过质量门（修复前 81% 短行被判 low_quality）。"""
    from sufe_qa.crawler.article import parse_article
    from sufe_qa.crawler.profile import ArticleProfile
    from sufe_qa.ingest.quality import assess_document

    rows = "".join(
        f"<tr><td>{college}</td><td>{major}</td><td>{note}</td></tr>"
        for college, major, note in [
            ("会计学院", "会计学", "不限"),
            ("金融学院", "金融学", "金融实验班 新生入校后1-2周面向全校新生选拔"),
            ("法学院", "法学", "涉外法治实验班 部分面向全校新生选拔"),
            ("统计与数据科学学院", "统计学", "统计学基地班 大二下学期分流"),
            ("计算机与人工智能学院", "计算机科学与技术", "物理+化学"),
            ("前沿交叉书院", "统计学（前沿交叉书院）", "数字前沿交叉实验班 入校后选拔"),
        ]
    )
    nav = "<ul>" + "".join(f"<li>栏目{i}</li>" for i in range(6)) + "</ul>"
    html = f"""<html><head><title>上海财经大学2026年本科招生专业（类）目录</title></head>
    <body>{nav}<div class="wp_articlecontent">
    <p>现将我校2026年本科招生专业（类）目录公布如下，各专业选考科目要求与备注见表。</p>
    <table><tr><th>学院</th><th>专业</th><th>备注</th></tr>{rows}</table>
    </div></body></html>"""
    meta = parse_article(
        html,
        "https://zs.sufe.edu.cn/08/c0/c3337a264384/page.htm",
        ArticleProfile(content_selectors=[".wp_articlecontent"]),
    )
    assert "金融学院 金融学 金融实验班" in meta.body_text.replace("  ", " ")
    # 行级合并后不再有大量单元格碎行
    q = assess_document(meta.title, meta.body_text, False, "2026-06-04")
    assert q.status == "accepted", q.reasons


# ---- 附件与父文章拒收解耦：壳页被拒，附件照常入库 ----


def test_rejected_parent_still_ingests_valid_attachment(tmp_path):
    """薄正文壳页（导航污染被判 low_quality）的有效 PDF 附件必须入库并保留父子关系。"""
    from sufe_qa.crawler.engine import CrawledArticle, DownloadedAttachment
    from sufe_qa.ingest.attachment_parsers import AttachmentParseResult
    from sufe_qa.ingest.pipeline import ingest_crawled_articles
    from sufe_qa.schema import doc_id_from, load_manifest

    nav_body = "\n".join(f"栏目导航{i}" for i in range(30))  # 短无标点行 -> low_quality
    att_text = "法学院法学专业2025级本科培养方案。一、培养目标：本专业培养复合型法律人才。" * 6
    att = DownloadedAttachment(
        requested_url="https://law.sufe.edu.cn/_upload/article/files/ab/cd/plan2025.pdf",
        final_url="https://law.sufe.edu.cn/_upload/article/files/ab/cd/plan2025.pdf",
        filename="法学院法学专业2025级本科培养方案.pdf",
        mime_type="application/pdf",
        content=b"%PDF-fake",
        binary_hash="cd" * 32,
        status="ok",
        parse=AttachmentParseResult(
            filename="法学院法学专业2025级本科培养方案.pdf",
            fmt="pdf",
            text=att_text,
            char_count=len(att_text),
            page_count=12,
            sheet_count=None,
            parse_status="ok",
        ),
    )
    url = "https://law.sufe.edu.cn/c2/70/c8529a246384/page.htm"
    article = CrawledArticle(
        requested_url=url,
        final_url=url,
        title="法学院法学专业2025级本科培养方案",
        publish_date="2025-09-01",
        publisher="上海财经大学法学院",
        html="",
        body_text=nav_body,
        attachments=[],
        status="ok",
        errors=[],
        downloaded=[att],
    )
    corpus = tmp_path / "corpus"
    stats = ingest_crawled_articles(
        [article],
        category="学工事务",
        corpus_dir=corpus,
        manifest_path=corpus / "manifest.jsonl",
        relations_path=corpus / "relations.jsonl",
        source_type="official_college",
        source_section="培养方案",
        scope_unit="法学院本科生",
    )
    manifest = load_manifest(corpus / "manifest.jsonl")
    parent_id = doc_id_from(url)
    parent = manifest[parent_id]
    assert parent.quality_status == "low_quality"  # 壳页本身仍被拒
    assert stats.count("rejected") == 1
    att_meta = next(m for m in manifest.values() if m.document_type == "attachment")
    assert att_meta.parent_doc_id == parent_id
    assert att_meta.quality_status == "accepted"
    assert att_meta.scope_unit == "法学院本科生"
    assert stats.count("new") == 1  # 附件作为新文档入库
