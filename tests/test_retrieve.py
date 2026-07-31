from __future__ import annotations

import pytest

from sufe_qa.config import load_settings
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
from sufe_qa.ingest.inbox import ingest_inbox
from sufe_qa.retrieve.retriever import (
    Hit,
    HybridRetriever,
    is_confident,
    rrf_fuse,
    tokenize,
)
from sufe_qa.schema import doc_id_from


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    return load_settings()


def _seed(settings, files: dict[str, str], category: str = "学工事务"):
    for name, text in files.items():
        (settings.inbox_dir / name).write_text(text, encoding="utf-8")
    ingest_inbox(
        settings.inbox_dir, settings.corpus_dir, settings.manifest_path, category, "测试单位"
    )
    update_index(settings, FakeEmbedder())


def _hit(doc_id: str, sim: float | None) -> Hit:
    return Hit(
        chunk_id=f"{doc_id}:0",
        doc_id=doc_id,
        title="t",
        category="学工事务",
        source_url="u",
        publisher="p",
        heading_path="",
        text="x",
        rrf_score=0.01,
        vector_similarity=sim,
    )


def test_tokenize_drops_punctuation_and_keeps_words():
    toks = tokenize("推免申请，条件：GPA≥3.5！")
    assert toks
    assert all(t.strip("，。：！≥") == t for t in toks)
    assert any("gpa" in t or "3.5" in t for t in toks)


def test_rrf_fuse_scores_and_order():
    scores = rrf_fuse([["a", "b"], ["c"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62)
    assert scores["c"] == pytest.approx(1 / 61)
    # 双路都命中的 chunk 排在单路命中之前
    scores2 = rrf_fuse([["x", "y"], ["x"]], k=60)
    assert scores2["x"] > scores2["y"]


def test_search_empty_index_returns_nothing(settings):
    r = HybridRetriever(settings, FakeEmbedder())
    assert r.search("推免条件") == []


def test_search_bm25_recovers_exact_terms(settings):
    tuimian = (
        "推免工作实施办法 第一条 申请推免的学生应为应届本科毕业生，"
        "拥护党的领导，品德良好，遵纪守法，身心健康。"
    ) * 3
    zhuxue = "助学金管理办法 第一条 家庭经济困难学生可申请助学金，按学年评审。" * 3
    _seed(settings, {"tuimian.md": tuimian, "zhuxue.md": zhuxue})
    r = HybridRetriever(settings, FakeEmbedder())
    hits = r.search("推免 申请 条件")
    assert hits, "应有检索结果"
    assert hits[0].doc_id == doc_id_from("inbox/tuimian.md")
    assert all(h.title and h.publisher and h.text for h in hits)


def test_is_confident_threshold():
    hits = [_hit("a", 0.3), _hit("b", 0.5)]
    assert is_confident(hits, 0.45)
    assert not is_confident(hits, 0.6)
    assert not is_confident([_hit("c", None)], 0.45)
