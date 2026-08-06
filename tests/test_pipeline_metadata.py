from __future__ import annotations

from datetime import date

from sufe_qa.crawler.engine import CrawledArticle
from sufe_qa.ingest.pipeline import ingest_crawled_articles
from sufe_qa.schema import load_manifest


def test_ingest_persists_source_and_document_kind_metadata(tmp_path):
    url = "https://jwc.sufe.edu.cn/notice/leave"
    body = (
        "本科生课程考试缓考申请办法。申请条件包括因病或其他特殊原因无法参加考试。"
        "学生应在规定时间提交申请材料，由学院审核后报教务处审批。申请材料包括申请表、"
        "诊断证明或其他情况说明，具体办理时间以教务处通知为准。"
    )
    article = CrawledArticle(
        requested_url=url,
        final_url=url,
        title="课程考试缓考申请办法",
        publish_date="2025-09-01",
        publisher="上海财经大学教务处",
        html=f"<html><body>{body}</body></html>",
        body_text=body,
        attachments=[],
        status="ok",
        errors=[],
        publish_date_evidence="发布时间：2025-09-01",
        publish_date_confidence=1.0,
        date_conflict=False,
    )
    corpus = tmp_path / "corpus"
    ingest_crawled_articles(
        [article],
        category="学工事务",
        corpus_dir=corpus,
        manifest_path=corpus / "manifest.jsonl",
        relations_path=corpus / "relations.jsonl",
        source_type="official_department",
        source_section="办事流程",
        scope_unit="上海财经大学教务处",
    )
    meta = next(iter(load_manifest(corpus / "manifest.jsonl").values()))
    assert meta.document_kind == "policy"
    assert meta.source_type == "official_department"
    assert meta.source_section == "办事流程"
    assert meta.scope_unit == "上海财经大学教务处"
    assert meta.validity_status == "unknown_validity"
    assert meta.publish_date_evidence == "发布时间：2025-09-01"
    assert meta.publish_date_confidence == 1.0
    assert meta.date_conflict is False


def test_ingest_archives_old_annual_notice_without_materializing_corpus(tmp_path):
    url = "https://gs.sufe.edu.cn/Home/Detail/old-retest"
    body = (
        "本年度硕士研究生复试工作安排如下。考生应提交申请材料，参加资格审核、"
        "专业复试和综合考核，具体办理流程、时间地点和联系方式以本通知为准。"
    )
    article = CrawledArticle(
        requested_url=url,
        final_url=url,
        title="上海财经大学2018年硕士研究生复试通知",
        publish_date="2018-03-01",
        publisher="上海财经大学研究生院",
        html=f"<html><body><p>发布时间：2018-03-01</p>{body}</body></html>",
        body_text=body,
        attachments=[],
        status="ok",
        errors=[],
        publish_date_evidence="发布时间：2018-03-01",
        publish_date_confidence=1.0,
    )
    corpus = tmp_path / "corpus"
    raw = tmp_path / "raw"
    ingest_crawled_articles(
        [article],
        category="推免升学",
        corpus_dir=corpus,
        manifest_path=corpus / "manifest.jsonl",
        relations_path=corpus / "relations.jsonl",
        raw_dir=raw,
        source_type="official_department",
        source_section="招生通知",
        scope_unit="研究生",
        time_policy="recent_5_school_years",
        evaluated_at=date(2026, 8, 6),
    )
    meta = next(iter(load_manifest(corpus / "manifest.jsonl").values()))
    assert meta.document_kind == "annual_notice"
    assert meta.temporal_class == "annual"
    assert meta.retention_status == "archived"
    assert meta.retention_reason == "outside_recent_5_school_years"
    assert meta.file_path == ""
    assert list(corpus.glob("推免升学/*.md")) == []
    assert (raw / "articles" / f"{meta.doc_id}.html").is_file()
