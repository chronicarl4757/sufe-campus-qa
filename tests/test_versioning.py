from __future__ import annotations

from sufe_qa.ingest.classification import (
    classify_document_kind,
    normalize_policy_name,
    standardize_topic_key,
)
from sufe_qa.ingest.versioning import VersionCandidate, infer_version_relations
from sufe_qa.schema import DocMeta


def test_document_kind_and_policy_name_are_explicit_and_normalized():
    assert classify_document_kind("2026年度奖学金评审工作的通知", "请按要求申请") == "annual_notice"
    assert classify_document_kind("上海财经大学学生奖学金评选办法", "第一条 评选对象") == "policy"
    assert classify_document_kind("关于获奖名单的公示", "1. 张三\n2. 李四") == "public_list"
    assert normalize_policy_name("关于修订《上海财经大学学生奖学金评选办法》的通知") == (
        "上海财经大学学生奖学金评选办法"
    )
    assert standardize_topic_key("上海财经大学本科生奖学金评选管理办法") == (
        "undergraduate.scholarship.merit"
    )


def test_doc_meta_accepts_source_topic_and_validity_evidence_fields():
    meta = DocMeta(
        doc_id="abc123def456",
        title="学生奖学金评选办法",
        source_url="https://xsc.sufe.edu.cn/policy/1",
        publisher="上海财经大学学生工作处",
        publish_date="2025-09-01",
        category="奖助学金",
        fetched_at="2026-08-01T00:00:00+00:00",
        content_hash="sha256:abc",
        file_path="奖助学金/办法.md",
        document_kind="policy",
        source_type="official_department",
        policy_name="学生奖学金评选办法",
        topic_key="undergraduate.scholarship.merit",
        validity_status="current",
        validity_confidence=0.95,
        validity_evidence="自2025年9月1日起施行",
        relation_confidence=0.9,
        relation_evidence="修订原办法",
        index_collection="main_qa",
    )
    assert meta.document_kind == "policy"
    assert meta.source_type == "official_department"
    assert meta.validity_confidence == 0.95
    assert meta.index_collection == "main_qa"


def test_year_only_does_not_supersede_previous_policy():
    relations = infer_version_relations(
        [
            VersionCandidate("new", "2025年学生奖学金办法", "管理办法正文"),
            VersionCandidate("old", "2024年学生奖学金办法", "管理办法正文"),
        ]
    )
    assert all(relation.status == "unknown_validity" for relation in relations)
    assert not any(relation.relation == "supersedes" for relation in relations)


def test_explicit_effective_and_repeal_words_produce_evidence():
    relations = infer_version_relations(
        [
            VersionCandidate(
                "new",
                "学生奖学金办法（修订）",
                "自2025年9月1日起施行，同时废止原办法。",
            ),
            VersionCandidate("old", "学生奖学金办法", "原办法正文"),
        ]
    )
    result = next(relation for relation in relations if relation.relation == "supersedes")
    assert result.source_doc_id == "new"
    assert result.target_doc_id == "old"
    assert result.confidence >= 0.9
    assert "同时废止" in result.evidence


def test_version_reconciliation_persists_relations_and_evidence(tmp_path):
    from sufe_qa.ingest.version_reconcile import reconcile_versions
    from sufe_qa.schema import append_manifest, load_manifest, load_relations

    corpus = tmp_path / "corpus"
    rows = []
    for doc_id, title, body, year in (
        (
            "old",
            "学生奖学金评选办法",
            "本办法自2024年9月1日起施行，同时废止原办法。",
            "2024-08-01",
        ),
        (
            "new",
            "关于修订学生奖学金评选办法的通知",
            "现修订学生奖学金评选办法，具体申请条件和材料如下。",
            "2025-08-01",
        ),
    ):
        path = corpus / f"{doc_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        rows.append(
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url=f"https://xsc.sufe.edu.cn/{doc_id}",
                publisher="学生处",
                publish_date=year,
                category="奖助学金",
                fetched_at=year,
                content_hash=f"sha256:{doc_id}",
                file_path=f"{doc_id}.md",
                document_kind="policy",
                policy_name="学生奖学金评选办法",
                topic_key="undergraduate.scholarship.merit",
            )
        )
    manifest = corpus / "manifest.jsonl"
    relations = corpus / "relations.jsonl"
    append_manifest(manifest, rows)
    report = reconcile_versions(manifest, corpus, relations)
    current = load_manifest(manifest)
    rels = load_relations(relations)
    assert report.relation_count == 1
    assert any(r.relation == "supersedes" and r.parent_doc_id == "new" for r in rels)
    assert current["new"].validity_status == "current"
    assert current["new"].validity_evidence
