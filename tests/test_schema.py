import dataclasses
import json

import pytest

from sufe_qa.schema import (
    DocMeta,
    DocRelation,
    append_manifest,
    append_relations,
    doc_id_from,
    load_manifest,
    load_relations,
    sha256_text,
)


def _meta(content_hash: str = "sha256:a", title: str = "细则") -> DocMeta:
    return DocMeta(
        doc_id=doc_id_from("https://x.sufe.edu.cn/1"),
        title=title,
        source_url="https://x.sufe.edu.cn/1",
        publisher="学生工作部",
        publish_date="2025-10-12",
        category="奖助学金",
        fetched_at="2026-07-17T00:00:00",
        content_hash=content_hash,
        file_path="奖助学金/xi-ze.md",
    )


def test_invalid_category_rejected():
    with pytest.raises(ValueError, match="非法分类"):
        dataclasses.replace(_meta(), category="不存在类")


def test_hash_and_doc_id_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")
    assert doc_id_from("u") == doc_id_from("u")
    assert doc_id_from("u") != doc_id_from("v")


def test_manifest_roundtrip_and_last_wins(tmp_path):
    p = tmp_path / "manifest.jsonl"
    m1, m2 = _meta("sha256:1"), _meta("sha256:2")
    append_manifest(p, [m1])
    append_manifest(p, [m2])  # 同 doc_id 新版本
    loaded = load_manifest(p)
    assert len(loaded) == 1
    assert loaded[m1.doc_id].content_hash == "sha256:2"
    assert loaded[m1.doc_id].file_path == "奖助学金/xi-ze.md"


def test_load_manifest_skips_corrupt_lines(tmp_path):
    p = tmp_path / "manifest.jsonl"
    m = _meta()
    append_manifest(p, [m])
    with p.open("a", encoding="utf-8") as f:
        f.write("{broken json\n")
    loaded = load_manifest(p)
    assert loaded[m.doc_id].title == "细则"


def test_load_manifest_missing_file(tmp_path):
    assert load_manifest(tmp_path / "nope.jsonl") == {}


def test_load_manifest_legacy_line_gets_defaults(tmp_path):
    # 旧版 10 字段行（无附件/质量字段）必须仍能加载，新字段取默认值
    p = tmp_path / "manifest.jsonl"
    legacy = {
        "doc_id": "ab12cd34ef56",
        "title": "旧记录",
        "source_url": "https://x.sufe.edu.cn/old",
        "publisher": "学生工作部",
        "publish_date": "2024-01-01",
        "category": "学工事务",
        "fetched_at": "2024-01-02T00:00:00",
        "content_hash": "sha256:9",
        "file_path": "学工事务/old.md",
    }
    p.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")
    m = load_manifest(p)["ab12cd34ef56"]
    assert m.document_type == "article" and m.parent_doc_id is None
    assert m.parse_status == "ok" and m.quality_status == "accepted" and m.text_hash == ""


def test_manifest_extended_fields_roundtrip(tmp_path):
    p = tmp_path / "manifest.jsonl"
    m = dataclasses.replace(
        _meta(),
        document_type="attachment",
        parent_doc_id="p1",
        download_url="https://x.sufe.edu.cn/f.pdf",
        parse_status="scanned_pdf",
        quality_status="accepted",
        binary_hash="sha256:bin",
        text_hash="sha256:txt",
        temporal_class="annual",
        series_key="研究生院|研究生|硕士复试录取办法",
        retention_status="historical",
        retention_reason="prior_annual_series_version",
        canonical_doc_id="canonical-2025",
    )
    append_manifest(p, [m])
    loaded = load_manifest(p)[m.doc_id]
    assert loaded.document_type == "attachment" and loaded.parent_doc_id == "p1"
    assert loaded.parse_status == "scanned_pdf" and loaded.text_hash == "sha256:txt"
    assert loaded.temporal_class == "annual"
    assert loaded.series_key.endswith("硕士复试录取办法")
    assert loaded.retention_status == "historical"
    assert loaded.retention_reason == "prior_annual_series_version"
    assert loaded.canonical_doc_id == "canonical-2025"


def test_relations_append_load_and_dedup(tmp_path):
    p = tmp_path / "relations.jsonl"
    r1, r2 = DocRelation("a1", "att1"), DocRelation("a2", "att1")  # 同附件多父
    append_relations(p, [r1, r2])
    append_relations(p, [r1])  # 重复追加不产生重复行
    rels = load_relations(p)
    assert rels == {r1, r2}
    assert len(p.read_text(encoding="utf-8").strip().splitlines()) == 2
