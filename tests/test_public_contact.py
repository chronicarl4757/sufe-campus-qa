"""official_public_contact：官方公开联系方式上下文放行，私人/无上下文 PII 继续隔离（§十五-§二十）。"""

from __future__ import annotations


from sufe_qa.crawler.engine import CrawledArticle
from sufe_qa.ingest.inbox import scan_sensitive
from sufe_qa.ingest.pipeline import ingest_crawled_articles
from sufe_qa.schema import default_relations_path

# ---------------- scan_sensitive 单元级（§二十） ----------------


def test_public_contact_context_allows_phone():
    assert scan_sensitive("咨询电话：13812345678（招生办公室）", allow_public_contact=True) == []
    assert scan_sensitive("联系电话 13812345678", allow_public_contact=True) == []
    assert scan_sensitive("报名咨询：13812345678", allow_public_contact=True) == []
    assert scan_sensitive("项目咨询老师 13812345678", allow_public_contact=True) == []
    # 真实排版变体：标签与号码之间夹换行/座机、标签带空格（“电 话：”）
    text = "十一、联系我们\n上海财经大学高级会计审计学院\n电话：\n021-65365276；19946257062"
    assert scan_sensitive(text, allow_public_contact=True) == []
    text = "招生微信：SUFE-MPAcc369\n电 话：\n021-65365276 / 19946257062"
    assert scan_sensitive(text, allow_public_contact=True) == []


def test_private_contact_context_still_quarantined():
    hits = scan_sensitive("个人紧急联系人：13812345678", allow_public_contact=True)
    assert hits == ["13812345678"]
    hits = scan_sensitive("家庭电话：13812345678", allow_public_contact=True)
    assert hits == ["13812345678"]


def test_phone_without_context_still_quarantined():
    assert scan_sensitive("他的手机号是13812345678，可以联系", allow_public_contact=True) == [
        "13812345678"
    ]


def test_id_number_never_allowed():
    text = "咨询电话：13812345678，本人身份证号310101199901011234"
    hits = scan_sensitive(text, allow_public_contact=True)
    assert "310101199901011234" in hits
    assert "13812345678" not in hits


def test_allow_public_contact_defaults_off():
    assert scan_sensitive("咨询电话：13812345678") == ["13812345678"]


# ---------------- pipeline 级：官网官方电话也放行（§十九/§二十） ----------------


def _article(body: str, *, title: str = "2026年硕士招生复试办法") -> CrawledArticle:
    return CrawledArticle(
        requested_url="https://jwc.sufe.edu.cn/x.htm",
        final_url="https://jwc.sufe.edu.cn/x.htm",
        title=title,
        publish_date="2026-03-01",
        publisher="上海财经大学教务处",
        html="",
        body_text=body,
        attachments=[],
        status="ok",
        errors=[],
        document_kind_hint="annual_notice",
    )


def test_official_department_public_phone_accepted(tmp_path):
    body = (
        "复试时间为3月20日，考生须携带身份证与准考证。"
        "招生办公室联系电话：13812345678，监督邮箱：jwc@mail.shufe.edu.cn。" * 3
    )
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "corpus" / "manifest.jsonl"
    stats = ingest_crawled_articles(
        [_article(body)],
        category="学工事务",
        corpus_dir=corpus,
        manifest_path=manifest,
        relations_path=default_relations_path(manifest),
        source_type="official_department",
        source_section="测试栏目",
        scope_unit="研究生",
    )
    assert stats.count("new") == 1
    assert stats.count("quarantined") == 0


def test_non_official_source_public_phone_quarantined(tmp_path):
    """manual_upload 等非官方来源不享受 public contact 放行。"""
    body = "复试时间为3月20日。招生办公室联系电话：13812345678。" * 4
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "corpus" / "manifest.jsonl"
    stats = ingest_crawled_articles(
        [_article(body)],
        category="学工事务",
        corpus_dir=corpus,
        manifest_path=manifest,
        relations_path=default_relations_path(manifest),
        source_type="manual_upload",
        source_section="测试",
        scope_unit="",
    )
    assert stats.count("quarantined") == 1


def test_official_department_private_phone_quarantined(tmp_path):
    """官方来源中的私人手机号（无公开语境）继续隔离。"""
    body = "兹有我院教师张三，个人手机号13812345678，因私出国。" * 4
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "corpus" / "manifest.jsonl"
    stats = ingest_crawled_articles(
        [_article(body)],
        category="学工事务",
        corpus_dir=corpus,
        manifest_path=manifest,
        relations_path=default_relations_path(manifest),
        source_type="official_department",
        source_section="测试栏目",
        scope_unit="研究生",
    )
    assert stats.count("quarantined") == 1
