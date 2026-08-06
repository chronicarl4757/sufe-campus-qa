"""engine.py（抓取引擎）+ pipeline.py（入库管线）+ state.py 离线测试。

全部通过 stub fetcher 注入响应，无网络；覆盖规格 §十六 相关项：
20/21 详见附件与附件失败、22 父子同库、24/25 binary/text hash 去重、
26 同附件多父、27 增量 no-op、28 更新失败不删旧档、31 报告统计。

Run: python -m pytest tests/test_engine_pipeline.py -v
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import fitz
import pytest

from sufe_qa.crawler.engine import (
    CrawlOptions,
    CrawlReport,
    attachment_filename,
    crawl_category,
    filename_from_disposition,
)
from sufe_qa.crawler.fetcher import FetchResult
from sufe_qa.crawler.state import CrawlState
from sufe_qa.ingest.attachment_parsers import parse_attachment
from sufe_qa.ingest.pipeline import ingest_crawled_articles
from sufe_qa.schema import DocMeta, doc_id_from, load_manifest, load_relations

BASE = "https://gs.sufe.edu.cn"


def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 500, 700), text, fontsize=11, fontname="china-s")
    return doc.tobytes()


LIST_HTML = '<html><body><a href="/Home/Detail/6946">推免办法</a><a href="/Home/Detail/7000">纯正文通知</a></body></html>'

ART_ATTACH = """
<html><head><title>关于印发《推免工作实施办法》的通知|研究生院</title></head>
<body><h1>关于印发《推免工作实施办法》的通知</h1>
<div class="info">发布时间：2025-09-01 来源：研究生院</div>
<div class="content"><p>各学院：现将《推免工作实施办法》印发给你们，请遵照执行。详见附件。</p>
<p><a href="/_upload/files/impl2025.pdf">附件：推免工作实施办法.pdf</a></p>
</div></body></html>
"""

ART_PLAIN = """
<html><head><title>关于开学报到的通知|研究生院</title></head>
<body><h1>关于开学报到的通知</h1>
<div class="info">发布时间：2025-09-02</div>
<div class="content"><p>请各位研究生新生于规定时间携带录取通知书、身份证件到校报到。
报到流程包括资格审查、缴费确认、宿舍分配与校园卡办理四个环节，具体安排请见各学院通知。
逾期未报到且未请假者，按放弃入学资格处理。</p></div></body></html>
"""

PDF_TEXT = (
    "推免工作实施办法全文：申请条件包括学业成绩排名前百分之三十，无不及格课程记录。"
    "申请人须为纳入国家普通本科招生计划录取的应届毕业生，思想政治素质合格，身心健康。"
    "需提交申请表、成绩单、专家推荐信与科研成果证明材料，于规定日期前报送研究生院。"
)


class StubFetcher:
    """按 URL 表返回响应的伪 SafeFetcher；记录请求以验证条件头。"""

    def __init__(self, routes: dict[str, FetchResult]):
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def fetch(self, url: str, kind: str = "html", headers: dict | None = None) -> FetchResult:
        self.calls.append((url, kind, headers))
        res = self.routes.get(url)
        if res is None:
            return FetchResult(
                requested_url=url, final_url=url, status="http_error", status_code=404, error="404"
            )
        res.requested_url = url
        return res


def _html_res(url: str, html: str, etag: str | None = None) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        content=html.encode("utf-8"),
        etag=etag,
        mime_type="text/html",
        status_code=200,
    )


def _att_res(url: str, content: bytes, cd: str = "") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        content=content,
        mime_type="application/pdf",
        status_code=200,
        content_disposition=cd,
    )


@pytest.fixture()
def routes() -> dict[str, FetchResult]:
    return {
        f"{BASE}/Home/List/25": _html_res(f"{BASE}/Home/List/25", LIST_HTML),
        f"{BASE}/Home/Detail/6946": _html_res(f"{BASE}/Home/Detail/6946", ART_ATTACH, etag='"e1"'),
        f"{BASE}/Home/Detail/7000": _html_res(f"{BASE}/Home/Detail/7000", ART_PLAIN),
        f"{BASE}/_upload/files/impl2025.pdf": _att_res(
            f"{BASE}/_upload/files/impl2025.pdf", _pdf_bytes(PDF_TEXT)
        ),
    }


def _crawl(routes, **kw):
    fetcher = StubFetcher(routes)
    report = CrawlReport(host="gs.sufe.edu.cn")
    arts = crawl_category(
        f"{BASE}/Home/List/25",
        "a",
        f"{BASE}/Home/Detail",
        fetcher,
        report=report,
        parse_attachment=parse_attachment,
        **kw,
    )
    return arts, report, fetcher


# ---------------- 文件名 ----------------


def test_filename_from_disposition_rfc5987():
    cd = "attachment; filename*=UTF-8''%E6%8E%A8%E5%85%8D%E5%8A%9E%E6%B3%95.pdf"
    assert filename_from_disposition(cd) == "推免办法.pdf"


def test_filename_from_disposition_gbk():
    cd = 'attachment; filename="' + "推免名单.xlsx".encode("gb18030").decode("latin-1") + '"'
    assert filename_from_disposition(cd) == "推免名单.xlsx"


def test_attachment_filename_fallback():
    assert attachment_filename("", f"{BASE}/_upload/a.pdf", f"{BASE}/x", 1) == "a.pdf"
    # 无附件扩展名的下载脚本：依次回退到锚文本、父标题（按 mime 补扩展名）、序号
    assert (
        attachment_filename(
            "", f"{BASE}/download.jsp?fileId=1", f"{BASE}/x", 2, anchor_text="材料汇总"
        )
        == "材料汇总"
    )
    assert (
        attachment_filename(
            "",
            f"{BASE}/index.php?mod=io",
            f"{BASE}/x",
            3,
            parent_title="推免办法",
            mime_type="application/pdf",
        )
        == "推免办法.pdf"
    )
    assert attachment_filename("", f"{BASE}/download.jsp", f"{BASE}/x", 4) == "attachment-4"


def test_attachment_filename_prefers_anchor_over_opaque_uuid():
    """jwc 附件服务器的 UUID 文件名没有语义，应回退到锚文本。"""
    uuid_url = f"{BASE}/_upload/article/files/ab/cd/e470cdc5-5780-4d49-ad18-f265ea4c5887.pdf"
    assert (
        attachment_filename("", uuid_url, uuid_url, 1, anchor_text="本科生缓考申请表")
        == "本科生缓考申请表.pdf"
    )
    # 无语义锚文本时才保留 UUID 段（可辨识的唯一名）
    assert attachment_filename("", uuid_url, uuid_url, 2) == (
        "e470cdc5-5780-4d49-ad18-f265ea4c5887.pdf"
    )


def test_iframe_pdfjs_viewer_resolved(tmp_path):
    """gs 站真实链路：iframe mod=pdf 查看器 → _fileurl → getStream 真 PDF。"""
    viewer_url = "https://ssd.sufe.edu.cn/index.php?mod=pdf&path=TOK"
    stream_url = "https://ssd.sufe.edu.cn/index.php?mod=io&op=getStream&path=TOK&filename="
    art_html = """
    <html><head><title>关于印发推免办法的通知|研究生院</title></head>
    <body><h1>关于印发推免办法的通知</h1>
    <div class="info">发布时间：2025-07-28</div>
    <iframe src="https://ssd.sufe.edu.cn/index.php?mod=pdf&path=TOK" width="600" height="800"></iframe>
    </body></html>
    """
    viewer_html = "<html><body><script>var _fileurl='" + stream_url + "';</script></body></html>"
    routes = {
        f"{BASE}/Home/List/25": _html_res(
            f"{BASE}/Home/List/25", '<a href="/Home/Detail/6946">推免办法</a>'
        ),
        f"{BASE}/Home/Detail/6946": _html_res(f"{BASE}/Home/Detail/6946", art_html),
        viewer_url: FetchResult(
            requested_url=viewer_url,
            final_url=viewer_url,
            status="unsupported_mime",
            mime_type="text/html",
            status_code=200,
            content=viewer_html.encode(),
            error="附件请求返回 text/html（疑似错误页或查看器）",
        ),
        stream_url: _att_res(stream_url, _pdf_bytes(PDF_TEXT)),
    }
    arts, report, _ = _crawl(routes)
    art = next(a for a in arts if "6946" in a.requested_url)
    assert art.status == "ok"
    assert len(art.downloaded) == 1
    att = art.downloaded[0]
    assert att.status == "ok"
    assert att.final_url == stream_url  # doc_id 锚定真实文件地址
    assert att.filename == "关于印发推免办法的通知.pdf"  # 回退到父标题 + mime 扩展名
    assert att.parse.parse_status == "ok"
    _ingest(tmp_path, arts)
    manifest = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    att_meta = next(m for m in manifest.values() if m.document_type == "attachment")
    assert att_meta.quality_status == "accepted"
    assert "申请条件" in (tmp_path / "corpus" / att_meta.file_path).read_text(encoding="utf-8")


# ---------------- engine ----------------


def test_crawl_category_full_flow(routes):
    arts, report, _ = _crawl(routes)
    ok = [a for a in arts if a.status == "ok"]
    assert len(ok) == 2
    attach_art = next(a for a in ok if a.title.startswith("关于印发"))
    assert attach_art.publish_date == "2025-09-01"
    assert len(attach_art.downloaded) == 1
    att = attach_art.downloaded[0]
    assert att.status == "ok"
    assert att.filename == "impl2025.pdf"
    assert att.parse.parse_status == "ok"
    assert "申请条件" in att.parse.text
    assert report.articles_downloaded == 2
    assert report.attachments_found == 1
    assert report.attachments_downloaded == 1
    assert report.attachments_parsed == 1


def test_crawl_category_not_modified(routes):
    state = CrawlState(path=SimpleNamespace())  # 不落盘，仅用内存逻辑
    state.update(f"{BASE}/Home/Detail/6946", etag='"e1"')
    routes[f"{BASE}/Home/Detail/6946"] = FetchResult(
        requested_url="",
        final_url=f"{BASE}/Home/Detail/6946",
        status="not_modified",
        status_code=304,
    )
    arts, _, fetcher = _crawl(routes, state=state)
    art = next(a for a in arts if "6946" in a.requested_url)
    assert art.status == "not_modified"
    cond = next(h for u, _, h in fetcher.calls if "6946" in u)
    assert cond == {"If-None-Match": '"e1"'}


def test_crawl_category_article_failure(routes):
    del routes[f"{BASE}/Home/Detail/7000"]
    arts, report, _ = _crawl(routes)
    failed = next(a for a in arts if "7000" in a.requested_url)
    assert failed.status == "http_error"
    assert any(f["stage"] == "article" for f in report.failures)


def test_crawl_category_since(routes):
    arts, _, _ = _crawl(routes, options=CrawlOptions(since="2025-09-02"))
    skipped = next(a for a in arts if "6946" in a.requested_url)
    assert skipped.status == "skipped_since"
    kept = next(a for a in arts if "7000" in a.requested_url)
    assert kept.status == "ok"


def test_duplicate_attachment_same_run(routes):
    routes[f"{BASE}/_upload/files/copy.pdf"] = _att_res(
        f"{BASE}/_upload/files/copy.pdf",
        routes[f"{BASE}/_upload/files/impl2025.pdf"].content,
    )
    html2 = ART_ATTACH.replace("impl2025.pdf", "copy.pdf").replace("6946", "6950")
    routes[f"{BASE}/Home/Detail/6950"] = _html_res(f"{BASE}/Home/Detail/6950", html2)
    routes[f"{BASE}/Home/List/25"] = _html_res(
        f"{BASE}/Home/List/25",
        LIST_HTML + '<a href="/Home/Detail/6950">第二个引用</a>',
    )
    arts, report, _ = _crawl(routes)
    dup = arts[-1].downloaded[0]
    assert dup.status == "duplicate"
    assert report.duplicate_attachments == 1


# ---------------- state ----------------


def test_state_roundtrip_and_not_seen(tmp_path):
    p = tmp_path / "state.json"
    st = CrawlState.load(p)
    st.update("https://x/a", etag='"e"', binary_hash="b1")
    st.update("https://x/b", etag='"e2"')
    st.records["https://x/b"]["status"] = "active"
    st._seen.discard("https://x/b")
    missing = st.finalize()
    st.save()
    assert missing == ["https://x/b"]
    st2 = CrawlState.load(p)
    assert st2.get("https://x/a")["etag"] == '"e"'
    assert st2.get("https://x/b")["status"] == "not_seen"
    assert st2.conditional_headers("https://x/a") == {"If-None-Match": '"e"'}


# ---------------- pipeline ----------------


def _ingest(tmp_path, arts, report=None, dry_run=False, state=None):
    corpus = tmp_path / "corpus"
    return ingest_crawled_articles(
        arts,
        category="学工事务",
        corpus_dir=corpus,
        manifest_path=corpus / "manifest.jsonl",
        relations_path=corpus / "relations.jsonl",
        raw_dir=tmp_path / "raw" / "gs.sufe.edu.cn",
        state=state,
        report=report,
        dry_run=dry_run,
    )


def test_parent_child_ingested_together(routes, tmp_path):
    arts, report, _ = _crawl(routes)
    stats = _ingest(tmp_path, arts, report=report)
    manifest = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    rels = load_relations(tmp_path / "corpus" / "relations.jsonl")
    articles = [m for m in manifest.values() if m.document_type == "article"]
    atts = [m for m in manifest.values() if m.document_type == "attachment"]
    assert len(articles) == 2 and len(atts) == 1
    att = atts[0]
    assert att.quality_status == "accepted"
    assert att.parent_doc_id in {a.doc_id for a in articles}
    assert att.binary_hash and att.text_hash
    assert any(r.child_doc_id == att.doc_id and r.parent_doc_id == att.parent_doc_id for r in rels)
    text = (tmp_path / "corpus" / att.file_path).read_text(encoding="utf-8")
    assert "所属通知：关于印发《推免工作实施办法》的通知" in text
    assert "申请条件" in text  # 附件正文随父级上下文入库
    assert (
        tmp_path
        / "raw"
        / "gs.sufe.edu.cn"
        / "attachments"
        / att.binary_hash[:2]
        / att.attachment_name
    ).is_file()
    assert stats.count("new") == 3  # 2 文章 + 1 附件
    assert report.final_indexed == 3


def test_incomplete_document_when_attachment_fails(routes, tmp_path):
    del routes[f"{BASE}/_upload/files/impl2025.pdf"]  # 附件 404
    arts, report, _ = _crawl(routes)
    _ingest(tmp_path, arts, report=report)
    manifest = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    art = next(m for m in manifest.values() if m.title.startswith("关于印发"))
    assert art.quality_status == "incomplete_document"
    assert art.file_path == ""  # 不完整文档不生成 corpus 文件
    assert report.incomplete_documents == 1


def test_attachment_dependent_page_complete_with_attachment(routes, tmp_path):
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    manifest = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    art = next(m for m in manifest.values() if m.title.startswith("关于印发"))
    assert art.quality_status == "accepted"  # 有有效附件，详见附件页不算残缺


def test_incremental_noop_second_run(routes, tmp_path):
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    arts2, _, _ = _crawl(routes)
    stats2 = _ingest(tmp_path, arts2)
    assert stats2.count("new") == 0 and stats2.count("updated") == 0
    assert stats2.count("unchanged") == 3


def test_parse_failure_keeps_previous_valid_doc(routes, tmp_path):
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    manifest1 = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    old = next(m for m in manifest1.values() if m.document_type == "attachment")
    old_file = tmp_path / "corpus" / old.file_path
    assert old_file.is_file()
    # 第二轮：同一附件 binary 变了（伪装损坏），解析失败
    routes[f"{BASE}/_upload/files/impl2025.pdf"] = _att_res(
        f"{BASE}/_upload/files/impl2025.pdf", b"\x00\x01corrupted"
    )
    arts2, _, _ = _crawl(routes)
    stats2 = _ingest(tmp_path, arts2)
    manifest2 = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    now = manifest2[old.doc_id]
    assert now.quality_status == "accepted"  # 旧有效行仍是最后一行
    assert old_file.is_file()  # 旧文件未被删除
    assert any(d.action == "kept_previous" for d in stats2.decisions)


def test_previously_accepted_article_low_quality_kept_previous(routes, tmp_path):
    """旧有效文章本轮重抓后质量门不通过：保留旧版本，不写审计行覆盖（规格 §十一）。"""
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    manifest1 = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    old = next(m for m in manifest1.values() if m.title.startswith("关于开学报到"))
    old_file = tmp_path / "corpus" / old.file_path
    assert old.quality_status == "accepted" and old_file.is_file()
    # 第二轮：同一 URL 变成薄页（栏目名标题 + 极短正文无日期）→ low_quality
    thin = """
    <html><head><title>公示专栏</title></head>
    <body><h1>公示专栏</h1>
    <div class="content"><p>本页内容未经许可，禁止一切形式的转载。</p></div></body></html>
    """
    routes[f"{BASE}/Home/Detail/7000"] = _html_res(f"{BASE}/Home/Detail/7000", thin)
    arts2, _, _ = _crawl(routes)
    stats2 = _ingest(tmp_path, arts2)
    manifest2 = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    now = manifest2[old.doc_id]
    assert now.quality_status == "accepted"  # 旧有效行仍是最后一行
    assert now.content_hash == old.content_hash
    assert old_file.is_file()  # 旧文件未被删除
    assert any(d.action == "kept_previous" for d in stats2.decisions)


def test_binary_dedup_multi_parent(routes, tmp_path):
    routes[f"{BASE}/_upload/files/copy.pdf"] = _att_res(
        f"{BASE}/_upload/files/copy.pdf",
        routes[f"{BASE}/_upload/files/impl2025.pdf"].content,
    )
    html2 = ART_ATTACH.replace("impl2025.pdf", "copy.pdf").replace("6946", "6950")
    routes[f"{BASE}/Home/Detail/6950"] = _html_res(f"{BASE}/Home/Detail/6950", html2)
    routes[f"{BASE}/Home/List/25"] = _html_res(
        f"{BASE}/Home/List/25", LIST_HTML + '<a href="/Home/Detail/6950">第二篇</a>'
    )
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    manifest = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    rels = load_relations(tmp_path / "corpus" / "relations.jsonl")
    atts = [
        m
        for m in manifest.values()
        if m.document_type == "attachment" and m.quality_status == "accepted"
    ]
    assert len(atts) == 1  # 同 binary 只嵌入一份正文
    parents = {r.parent_doc_id for r in rels if r.child_doc_id == atts[0].doc_id}
    assert len(parents) == 2  # 两个父文章的关系都保留


def test_same_url_multi_parent_relation(routes, tmp_path):
    html2 = ART_ATTACH.replace("6946", "6951")
    routes[f"{BASE}/Home/Detail/6951"] = _html_res(f"{BASE}/Home/Detail/6951", html2)
    routes[f"{BASE}/Home/List/25"] = _html_res(
        f"{BASE}/Home/List/25", LIST_HTML + '<a href="/Home/Detail/6951">第二篇</a>'
    )
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    rels = load_relations(tmp_path / "corpus" / "relations.jsonl")
    att_id = doc_id_from(f"{BASE}/_upload/files/impl2025.pdf")
    parents = {r.parent_doc_id for r in rels if r.child_doc_id == att_id}
    assert len(parents) == 2


def test_text_hash_dedup_reuse(routes, tmp_path):
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    manifest = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    old = next(m for m in manifest.values() if m.document_type == "attachment")
    # 第二轮：binary 变化（PDF 元数据差异），但解析出的文本完全相同
    routes[f"{BASE}/_upload/files/impl2025.pdf"] = _att_res(
        f"{BASE}/_upload/files/impl2025.pdf", _pdf_bytes(PDF_TEXT) + b"% trailing-comment\n"
    )
    arts2, _, _ = _crawl(routes)
    stats2 = _ingest(tmp_path, arts2)
    rows = [
        json.loads(line)
        for line in (tmp_path / "corpus" / "manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and old.doc_id in line
    ]
    assert stats2.count("updated") == 0
    assert rows[-1]["content_hash"] == old.content_hash  # content_hash 不变 → 不重嵌入
    assert rows[-1]["binary_hash"] != old.binary_hash  # binary_hash 已刷新


def test_dry_run_writes_nothing(routes, tmp_path):
    arts, _, _ = _crawl(routes)
    stats = _ingest(tmp_path, arts, dry_run=True)
    assert stats.count("new") == 3
    assert not (tmp_path / "corpus" / "manifest.jsonl").exists()
    assert not list((tmp_path / "corpus").rglob("*.md")) if (tmp_path / "corpus").exists() else True
    assert not (tmp_path / "raw").exists()


def test_old_manifest_rows_still_load(routes, tmp_path):
    # 旧格式 manifest 行（无新增字段）与新旧混合读取
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "学工事务").mkdir()
    old_row = DocMeta(
        doc_id="abc123def456",
        title="旧文档",
        source_url="https://x/old",
        publisher="研究生院",
        publish_date="2020-01-01",
        category="学工事务",
        fetched_at="2024-01-01T00:00:00+00:00",
        content_hash="sha256:old",
        file_path="学工事务/旧文档.md",
    )
    line = json.dumps(
        {
            k: v
            for k, v in old_row.__dict__.items()
            if k
            in {
                "doc_id",
                "title",
                "source_url",
                "publisher",
                "publish_date",
                "category",
                "fetched_at",
                "content_hash",
                "file_path",
            }
        }
    )
    (corpus / "manifest.jsonl").write_text(line + "\n", encoding="utf-8")
    arts, _, _ = _crawl(routes)
    _ingest(tmp_path, arts)
    manifest = load_manifest(corpus / "manifest.jsonl")
    assert manifest["abc123def456"].quality_status == "accepted"
    assert manifest["abc123def456"].document_type == "article"


def test_previously_rejected_doc_reaccepted_no_crash(routes, tmp_path):
    """回归：曾被拒（审计行 file_path=""）的文档转为 accepted 时必须分配新路径而不是崩溃。"""
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True)
    doc_url = f"{BASE}/Home/Detail/7000"
    audit = DocMeta(
        doc_id=doc_id_from(doc_url),
        title="曾被拒文档",
        source_url=doc_url,
        publisher="研究生院",
        publish_date="2025-09-02",
        category="学工事务",
        fetched_at="2026-01-01T00:00:00+00:00",
        content_hash="",
        file_path="",
        document_type="article",
        quality_status="low_quality",
    )
    (corpus / "manifest.jsonl").write_text(
        json.dumps(audit.__dict__, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    arts, _, _ = _crawl(routes)
    stats = _ingest(tmp_path, arts)  # 不崩溃即核心断言
    manifest = load_manifest(corpus / "manifest.jsonl")
    meta = manifest[doc_id_from(doc_url)]
    assert meta.quality_status == "accepted"
    assert meta.file_path and (corpus / meta.file_path).is_file()
    assert any(d.action == "updated" for d in stats.decisions)
