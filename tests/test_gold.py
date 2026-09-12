"""gold.v1 金标集校验器测试：schema、现行性、evidence 逐字核对。"""

from __future__ import annotations

import json
from pathlib import Path

from sufe_qa.evals.gold import validate_gold
from sufe_qa.schema import DocMeta, append_manifest, sha256_text


def _seed_manifest(tmp_path: Path, doc_id: str = "golddoc123456") -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    text = "# 缓考细则\n\n因病申请缓考的，须持医院出具的诊断证明，经审批后报教务处备案。\n"
    (corpus / "a.md").write_text(text, encoding="utf-8")
    append_manifest(
        corpus / "manifest.jsonl",
        [
            DocMeta(
                doc_id=doc_id,
                title="缓考细则",
                source_url="https://jwc.sufe.edu.cn/x.htm",
                publisher="上海财经大学教务处",
                publish_date="2026-01-01",
                category="学工事务",
                fetched_at="t",
                content_hash=sha256_text(text),
                file_path="a.md",
                retention_status="active",
                document_kind="procedure",
                index_collection="main_qa",
            )
        ],
    )
    return corpus / "manifest.jsonl"


def _row(**over):
    base = {
        "id": "gold-t-001",
        "question": "缓考怎么办？",
        "scene": "本科教务",
        "topic_key": "undergraduate.exam.deferment",
        "question_intent": "流程",
        "student_type": "本科",
        "should_answer": True,
        "should_refuse": False,
        "needs_clarification": False,
        "needs_current_version": True,
        "expected_domains": ["jwc.sufe.edu.cn"],
        "expected_doc_ids": ["golddoc123456"],
        "expected_publishers": ["上海财经大学教务处"],
        "required_answer_points": ["因病申请缓考须持医院诊断证明"],
        "evidence": [
            {"doc_id": "golddoc123456", "heading": "", "evidence_text": "须持医院出具的诊断证明"}
        ],
        "gold_answer": "因病不能参加考试应在考前申请缓考，须持医院诊断证明，经审批后报教务处备案。",
        "validity_status": "current",
        "reviewer": "human",
        "reviewed_at": "2026-09-12",
    }
    base.update(over)
    return base


def _check(tmp_path: Path, row: dict, manifest: Path):
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    return validate_gold(gold, manifest)


def test_valid_row_passes(tmp_path):
    manifest = _seed_manifest(tmp_path)
    report = _check(tmp_path, _row(), manifest)
    assert report.ok, [f"{i.level}:{i.message}" for i in report.issues]


def test_generic_point_rejected(tmp_path):
    manifest = _seed_manifest(tmp_path)
    report = _check(tmp_path, _row(required_answer_points=["申请流程"]), manifest)
    assert any("要点太泛" in i.message for i in report.errors)


def test_evidence_must_exist_verbatim(tmp_path):
    manifest = _seed_manifest(tmp_path)
    row = _row(evidence=[{"doc_id": "golddoc123456", "evidence_text": "须持身份证原件办理"}])
    report = _check(tmp_path, row, manifest)
    assert any("逐字找不到" in i.message for i in report.errors)


def test_unknown_doc_rejected(tmp_path):
    manifest = _seed_manifest(tmp_path)
    row = _row(expected_doc_ids=["notexistdoc99"])
    report = _check(tmp_path, row, manifest)
    assert any("不存在" in i.message for i in report.errors)


def test_answerable_requires_doc_ids(tmp_path):
    manifest = _seed_manifest(tmp_path)
    row = _row(expected_doc_ids=[])
    report = _check(tmp_path, row, manifest)
    assert any("expected_doc_ids" in i.message for i in report.errors)
