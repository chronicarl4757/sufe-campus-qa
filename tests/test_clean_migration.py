from __future__ import annotations

import hashlib
from datetime import date

import pytest

from sufe_qa.quality.audit import audit_corpus
from sufe_qa.quality.migrate import rebuild_clean_corpus
from sufe_qa.schema import DocMeta, append_manifest, load_manifest, sha256_text


def _tree_hash(root) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _fixture(tmp_path):
    data = tmp_path / "data"
    corpus = data / "corpus"
    raw = data / "raw"
    rows = []
    for doc_id, year, kind in (("active", 2025, "annual_notice"), ("old", 2018, "annual_notice")):
        title = f"上海财经大学{year}年硕士研究生复试通知"
        text = f"# {title}\n\n{year}年复试申请条件、材料和办理流程。\n"
        rel = f"推免升学/{doc_id}.md"
        path = corpus / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        rows.append(
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url=f"https://gs.sufe.edu.cn/Home/Detail/{doc_id}",
                publisher="上海财经大学研究生院",
                publish_date=f"{year}-03-01",
                category="推免升学",
                fetched_at="2026-08-01T00:00:00+00:00",
                content_hash=sha256_text(text),
                file_path=rel,
                document_kind=kind,
                source_type="official_department",
                source_section="招生通知",
                scope_unit="研究生",
            )
        )
    append_manifest(corpus / "manifest.jsonl", rows)
    raw_file = raw / "sentinel.bin"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_bytes(b"must-not-change")
    report = audit_corpus(
        corpus / "manifest.jsonl",
        corpus,
        raw,
        evaluated_at=date(2026, 8, 6),
        time_policies={
            ("上海财经大学研究生院", "招生通知"): "recent_5_school_years"
        },
    )
    return data, corpus, raw, report


def test_clean_rebuild_requires_apply_and_failure_preserves_active_corpus(tmp_path):
    _, corpus, raw, audit = _fixture(tmp_path)
    before_corpus = _tree_hash(corpus)
    before_raw = _tree_hash(raw)

    preview = rebuild_clean_corpus(audit, corpus, apply=False)
    assert preview.applied is False
    assert _tree_hash(corpus) == before_corpus

    def fail_validation(_staging):
        raise RuntimeError("injected validation failure")

    with pytest.raises(RuntimeError, match="injected"):
        rebuild_clean_corpus(audit, corpus, apply=True, validation_hook=fail_validation)
    assert _tree_hash(corpus) == before_corpus
    assert _tree_hash(raw) == before_raw


def test_clean_rebuild_atomically_swaps_and_keeps_archived_audit_row(tmp_path):
    _, corpus, raw, audit = _fixture(tmp_path)
    before_raw = _tree_hash(raw)

    result = rebuild_clean_corpus(audit, corpus, apply=True)

    assert result.applied is True
    assert result.backup_path.is_dir()
    assert result.retained_files == 1
    manifest = load_manifest(corpus / "manifest.jsonl")
    assert manifest["active"].retention_status == "active"
    assert manifest["active"].file_path
    assert manifest["old"].retention_status == "archived"
    assert manifest["old"].file_path == ""
    assert manifest["old"].content_hash == ""
    assert _tree_hash(raw) == before_raw
