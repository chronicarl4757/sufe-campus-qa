from __future__ import annotations

import hashlib
from datetime import date

from sufe_qa.quality.audit import audit_corpus, write_quality_audit
from sufe_qa.schema import (
    DocMeta,
    DocRelation,
    append_manifest,
    append_relations,
    doc_id_from,
    sha256_text,
)


def _tree_hash(root) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _add(corpus, *, url, title, body, publish_date, kind="incomplete", section="招生通知"):
    doc_id = doc_id_from(url)
    rel = f"学工事务/{doc_id}.md"
    text = f"# {title}\n\n{body}\n"
    path = corpus / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    append_manifest(
        corpus / "manifest.jsonl",
        [
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url=url,
                publisher="上海财经大学研究生院",
                publish_date=publish_date,
                category="学工事务",
                fetched_at="2026-08-01T00:00:00+00:00",
                content_hash=sha256_text(text),
                file_path=rel,
                document_kind=kind,
                source_type="official_department",
                source_section=section,
                scope_unit="研究生",
                quality_status="accepted",
            )
        ],
    )
    return doc_id


def test_quality_audit_is_read_only_and_records_evidence_backed_decisions(tmp_path):
    data = tmp_path / "data"
    corpus = data / "corpus"
    raw = data / "raw"
    wrong_date_id = _add(
        corpus,
        url="https://gs.sufe.edu.cn/Home/Detail/date-wrong",
        title="上海财经大学2017年博士研究生招生通知",
        body="2017年博士研究生招生对象、申请材料、考核流程和联系方式。",
        publish_date="2015-06-20",
    )
    for year in (2023, 2024, 2025):
        _add(
            corpus,
            url=f"https://gs.sufe.edu.cn/Home/Detail/retest-{year}",
            title=f"上海财经大学{year}年硕士研究生复试通知",
            body=f"{year}年复试申请条件、材料、办理流程、时间和联系方式。",
            publish_date=f"{year}-03-01",
        )
    old_public_id = _add(
        corpus,
        url="https://gs.sufe.edu.cn/Home/Detail/public-2022",
        title="上海财经大学2022年硕士研究生拟录取名单公示",
        body="2022年硕士研究生拟录取名单及公示期限。",
        publish_date="2022-05-01",
        section="招生公示",
    )
    policy_id = _add(
        corpus,
        url="https://gs.sufe.edu.cn/Home/Detail/policy",
        title="上海财经大学研究生学籍管理规定",
        body="第一条 为规范研究生学籍管理制定本规定。第二条 本规定适用于在校研究生。",
        publish_date="2013-01-10",
        section="学籍管理规定",
    )
    unknown_id = _add(
        corpus,
        url="https://gs.sufe.edu.cn/Home/Detail/unknown",
        title="校务材料",
        body="一般性页面材料，仅用于展示概况。",
        publish_date="unknown",
    )
    raw_page = raw / "gs.sufe.edu.cn" / "articles" / f"{wrong_date_id}.html"
    raw_page.parent.mkdir(parents=True, exist_ok=True)
    raw_page.write_text(
        "<aside class='info'>2015-06-20</aside><p>发布时间：2017-05-09</p>",
        encoding="utf-8",
    )
    before = _tree_hash(data)

    report = audit_corpus(
        corpus / "manifest.jsonl",
        corpus,
        raw,
        evaluated_at=date(2026, 8, 6),
        time_policies={
            ("上海财经大学研究生院", "招生通知"): "recent_5_school_years",
            ("上海财经大学研究生院", "招生公示"): "recent_2_school_years",
            ("上海财经大学研究生院", "学籍管理规定"): "all_history",
        },
    )

    assert _tree_hash(data) == before
    assert report.total_documents == 7
    assert report.date_correction_count == 1
    decisions = {item.doc_id: item for item in report.decisions}
    assert decisions[wrong_date_id].after_publish_date == "2017-05-09"
    assert "发布时间：2017-05-09" in decisions[wrong_date_id].date_evidence
    assert decisions[old_public_id].retention_status == "archived"
    assert decisions[policy_id].retention_status == "active"
    assert decisions[unknown_id].document_kind == "incomplete"
    assert decisions[unknown_id].retention_status == "archived"
    series = [
        item for item in report.decisions if "硕士研究生复试通知" in item.title
    ]
    assert sum(item.retention_status == "active" for item in series) == 1
    assert sum(item.retention_status == "historical" for item in series) == 2
    assert {item.canonical_doc_id for item in series} == {
        next(item.doc_id for item in series if "2025年" in item.title)
    }

    json_path = data / "quality" / "audit.json"
    md_path = data / "quality" / "audit.md"
    write_quality_audit(report, json_path, md_path)
    assert '"date_correction_count": 1' in json_path.read_text(encoding="utf-8")
    assert "年度系列" in md_path.read_text(encoding="utf-8")


def test_shared_attachment_is_retained_when_any_parent_is_active(tmp_path):
    data = tmp_path / "data"
    corpus = data / "corpus"
    old_parent = _add(
        corpus,
        url="https://gs.sufe.edu.cn/Home/Detail/old-parent",
        title="上海财经大学2018年硕士研究生复试通知",
        body="2018年复试申请条件、材料和办理流程。",
        publish_date="2018-03-01",
    )
    active_parent = _add(
        corpus,
        url="https://gs.sufe.edu.cn/Home/Detail/active-parent",
        title="上海财经大学2025年硕士研究生复试通知",
        body="2025年复试申请条件、材料和办理流程。",
        publish_date="2025-03-01",
    )
    attachment_url = "https://gs.sufe.edu.cn/_upload/shared.pdf"
    attachment_id = doc_id_from(attachment_url)
    title = "2018年硕士研究生复试补充通知.pdf"
    body = "2018年复试补充申请条件、材料和办理流程。"
    text = f"# {title}\n\n{body}\n"
    rel = f"推免升学/{attachment_id}.md"
    path = corpus / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    append_manifest(
        corpus / "manifest.jsonl",
        [
            DocMeta(
                doc_id=attachment_id,
                title=title,
                source_url=attachment_url,
                publisher="上海财经大学研究生院",
                publish_date="2018-03-01",
                category="推免升学",
                fetched_at="2026-08-01T00:00:00+00:00",
                content_hash=sha256_text(text),
                file_path=rel,
                document_type="attachment",
                parent_doc_id=old_parent,
                source_page_url="https://gs.sufe.edu.cn/Home/Detail/old-parent",
                document_kind="annual_notice",
                source_type="attachment",
                source_section="招生通知",
                scope_unit="研究生",
            )
        ],
    )
    append_relations(
        corpus / "relations.jsonl",
        [
            DocRelation(parent_doc_id=old_parent, child_doc_id=attachment_id),
            DocRelation(parent_doc_id=active_parent, child_doc_id=attachment_id),
        ],
    )

    report = audit_corpus(
        corpus / "manifest.jsonl",
        corpus,
        data / "raw",
        evaluated_at=date(2026, 8, 6),
        time_policies={
            ("上海财经大学研究生院", "招生通知"): "recent_5_school_years"
        },
    )
    decision = next(item for item in report.decisions if item.doc_id == attachment_id)
    assert decision.retention_status == "active"
    assert decision.retention_reason == "retained_by_parent_relation"
    assert decision.canonical_doc_id == active_parent
