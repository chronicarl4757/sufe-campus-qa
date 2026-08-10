from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from docx import Document

from sufe_qa.ingest.manual_authority import import_manual_authority_files
from sufe_qa.schema import load_manifest, sha256_text


def _write_docx(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(title, level=1)
    document.add_paragraph(body)
    document.save(path)


def _write_rules(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(
        yaml.safe_dump(
            {"schema_version": "1", "namespace": "sufe-regulations", "entries": entries},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _entry(relative_path: str, **overrides: str) -> dict[str, str]:
    entry = {
        "path": relative_path,
        "category": "学工事务",
        "publisher": "上海财经大学教务处",
        "scope_unit": "上海财经大学",
        "source_section": "本科教学",
        "document_kind": "policy",
        "retention_status": "active",
    }
    entry.update(overrides)
    return entry


def test_dry_run_is_recursive_and_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "规章制度"
    accepted = source / "本科教学/20250801关于印发《课程考核管理办法》的通知.docx"
    draft = source / "本科教学/课程考核管理办法（征求意见稿）.docx"
    unlisted = source / "党建/内部管理办法.docx"
    broken = source / "本科教学/损坏文件.pdf"
    body = "第一条 为规范本科学生课程考核，明确申请条件、办理流程和审批部门。" * 4
    _write_docx(accepted, "课程考核管理办法", body)
    _write_docx(draft, "课程考核管理办法征求意见稿", body)
    _write_docx(unlisted, "内部管理办法", body)
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"not-a-pdf")
    rules = tmp_path / "rules.yaml"
    _write_rules(
        rules,
        [
            _entry(accepted.relative_to(source).as_posix()),
            _entry(draft.relative_to(source).as_posix()),
            _entry(broken.relative_to(source).as_posix()),
        ],
    )
    corpus = tmp_path / "corpus"
    manifest = corpus / "manifest.jsonl"

    report = import_manual_authority_files(
        source, rules, corpus, manifest, apply=False, evaluated_at="2026-08-10T00:00:00Z"
    )

    assert report.total_files == 4
    assert report.accepted == 1
    assert report.persisted == 0
    assert report.excluded == 2
    assert report.incomplete == 1
    assert report.quarantined == 0
    assert {decision.relative_path for decision in report.decisions} == {
        accepted.relative_to(source).as_posix(),
        draft.relative_to(source).as_posix(),
        unlisted.relative_to(source).as_posix(),
        broken.relative_to(source).as_posix(),
    }
    reasons = {decision.relative_path: decision.reason for decision in report.decisions}
    assert reasons[draft.relative_to(source).as_posix()] == "draft_filename"
    assert reasons[unlisted.relative_to(source).as_posix()] == "not_allowlisted"
    assert reasons[broken.relative_to(source).as_posix()].startswith("parse_")
    assert not manifest.exists()
    assert list(corpus.rglob("*.md")) == []


def test_apply_persists_stable_manual_metadata_and_deduplicates(tmp_path: Path) -> None:
    source = tmp_path / "规章制度"
    relative = "本科教学/20250801关于印发《课程考核管理办法》的通知.docx"
    document_path = source / relative
    _write_docx(
        document_path,
        "课程考核管理办法",
        "第一条 本办法适用于本科学生。第二条 学生应按规定参加课程考核。" * 5,
    )
    rules = tmp_path / "rules.yaml"
    _write_rules(rules, [_entry(relative)])
    corpus = tmp_path / "corpus"
    manifest = corpus / "manifest.jsonl"

    first = import_manual_authority_files(
        source, rules, corpus, manifest, apply=True, evaluated_at="2026-08-10T00:00:00Z"
    )
    second = import_manual_authority_files(
        source, rules, corpus, manifest, apply=True, evaluated_at="2026-08-10T00:00:00Z"
    )

    assert first.accepted == first.persisted == 1
    assert second.accepted == 0
    assert second.duplicates == 1
    loaded = load_manifest(manifest)
    assert len(loaded) == 1
    meta = next(iter(loaded.values()))
    assert meta.source_url.startswith("manual://sufe-regulations/")
    assert "%E6%9C%AC%E7%A7%91%E6%95%99%E5%AD%A6" in meta.source_url
    assert meta.source_type == "manual_upload"
    assert meta.document_type == "attachment"
    assert meta.document_kind == "policy"
    assert meta.retention_status == "active"
    assert meta.index_collection == "main_qa"
    assert meta.validity_status == "unknown_validity"
    assert meta.publish_date == "2025-08-01"
    assert meta.publish_date_evidence == "文件名前缀：20250801"
    assert meta.binary_hash and meta.text_hash
    content = (corpus / meta.file_path).read_text(encoding="utf-8")
    assert meta.content_hash == sha256_text(content)


def test_rule_validation_rejects_duplicate_and_traversal_paths(tmp_path: Path) -> None:
    source = tmp_path / "规章制度"
    source.mkdir()
    rules = tmp_path / "rules.yaml"
    duplicate = _entry("本科教学/办法.pdf")
    _write_rules(rules, [duplicate, duplicate])

    with pytest.raises(ValueError, match="重复规则路径"):
        import_manual_authority_files(
            source, rules, tmp_path / "corpus", tmp_path / "corpus/manifest.jsonl"
        )

    _write_rules(rules, [_entry("../办法.pdf")])
    with pytest.raises(ValueError, match="非法规则路径"):
        import_manual_authority_files(
            source, rules, tmp_path / "corpus", tmp_path / "corpus/manifest.jsonl"
        )


def test_report_serializes_all_decisions(tmp_path: Path) -> None:
    source = tmp_path / "规章制度"
    _write_docx(source / "未收录.docx", "未收录", "第一条 普通正文。" * 10)
    rules = tmp_path / "rules.yaml"
    _write_rules(rules, [])
    report_path = tmp_path / "report.json"

    report = import_manual_authority_files(
        source,
        rules,
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
        report_path=report_path,
    )

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["total_files"] == 1
    assert data["decisions"][0]["status"] == "excluded"
    assert data["decisions"][0]["reason"] == "not_allowlisted"
    assert report.excluded == 1
