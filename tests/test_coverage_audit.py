from __future__ import annotations

import json
from pathlib import Path

from sufe_qa.coverage.audit import audit_manifest, render_markdown
from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, sha256_text


def _write_doc(tmp_path: Path, title: str, url: str, body: str, publisher: str) -> DocMeta:
    rel = Path("学工事务") / f"{title}.md"
    path = tmp_path / "corpus" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return DocMeta(
        doc_id=doc_id_from(url),
        title=title,
        source_url=url,
        publisher=publisher,
        publish_date="2025-09-01",
        category="学工事务",
        fetched_at="2026-08-01T00:00:00+00:00",
        content_hash=sha256_text(body),
        file_path=str(rel),
    )


def test_audit_uses_question_bank_hash_as_fixed_denominator(tmp_path):
    manifest = tmp_path / "corpus" / "manifest.jsonl"
    meta = _write_doc(
        tmp_path,
        "本科生奖学金评选办法",
        "https://xsc.sufe.edu.cn/policy/1",
        "本科生奖学金评选办法。申请条件、评审流程、材料和申诉部门见正文。",
        "上海财经大学学生工作处",
    )
    append_manifest(manifest, [meta])
    report = audit_manifest(
        manifest_path=manifest,
        corpus_dir=tmp_path / "corpus",
        question_bank_path=Path("data/eval/sufe_question_bank.jsonl"),
        retriever_config={"similarity_threshold": 0.5},
        index_fingerprint="legacy-test",
    )
    assert report.question_bank_version == "sufe-question-bank.v1"
    assert report.question_bank_hash.startswith("sha256:")
    assert report.scene_stats["本科教务"].question_count == 20
    assert report.scene_stats["奖助学金"].document_count == 1
    assert report.evaluated_at


def test_audit_markdown_contains_scene_stats_and_question_rows(tmp_path):
    manifest = tmp_path / "corpus" / "manifest.jsonl"
    append_manifest(
        manifest,
        [
            _write_doc(
                tmp_path,
                "关于开展2025年奖学金评审的通知",
                "https://xsc.sufe.edu.cn/notice/1",
                "申请条件、材料、截止时间和办理流程。",
                "上海财经大学学生工作处",
            )
        ],
    )
    report = audit_manifest(
        manifest_path=manifest,
        corpus_dir=tmp_path / "corpus",
        question_bank_path=Path("data/eval/sufe_question_bank.jsonl"),
        retriever_config={"similarity_threshold": 0.5},
        index_fingerprint="legacy-test",
    )
    markdown = render_markdown(report)
    assert "本科教务" in markdown
    assert "本科生国家奖学金申请条件是什么？" in markdown
    data = json.loads(report.to_json())
    assert data["question_bank_hash"] == report.question_bank_hash
