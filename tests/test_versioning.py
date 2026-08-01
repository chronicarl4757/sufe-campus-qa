from __future__ import annotations

from sufe_qa.ingest.classification import classify_document_kind, normalize_policy_name
from sufe_qa.ingest.versioning import VersionCandidate, infer_version_relations
from sufe_qa.schema import DocMeta


def test_document_kind_and_policy_name_are_explicit_and_normalized():
    assert classify_document_kind("2026年度奖学金评审工作的通知", "请按要求申请") == "annual_notice"
    assert classify_document_kind("上海财经大学学生奖学金评选办法", "第一条 评选对象") == "policy"
    assert classify_document_kind("关于获奖名单的公示", "1. 张三\n2. 李四") == "public_list"
    assert normalize_policy_name("关于修订《上海财经大学学生奖学金评选办法》的通知") == (
        "上海财经大学学生奖学金评选办法"
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
