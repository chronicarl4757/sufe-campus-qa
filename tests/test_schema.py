import pytest

from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text


def _meta(content_hash: str = "sha256:a", title: str = "细则") -> DocMeta:
    return DocMeta(
        doc_id=doc_id_from("https://x.sufe.edu.cn/1", title),
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
        DocMeta(**{**_meta().__dict__, "category": "不存在类"})


def test_hash_and_doc_id_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")
    assert doc_id_from("u", "t") == doc_id_from("u", "t")
    assert doc_id_from("u", "t") != doc_id_from("u", "t2")


def test_manifest_roundtrip_and_last_wins(tmp_path):
    p = tmp_path / "manifest.jsonl"
    m1, m2 = _meta("sha256:1"), _meta("sha256:2")
    append_manifest(p, [m1])
    append_manifest(p, [m2])  # 同 doc_id 新版本
    loaded = load_manifest(p)
    assert len(loaded) == 1
    assert loaded[m1.doc_id].content_hash == "sha256:2"
    assert loaded[m1.doc_id].file_path == "奖助学金/xi-ze.md"
