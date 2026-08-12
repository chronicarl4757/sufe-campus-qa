import json
import sys
from types import SimpleNamespace

import chromadb
import pytest

from sufe_qa.config import Settings
from sufe_qa.indexing.indexer import BgeEmbedder, FakeEmbedder, update_index
from sufe_qa.schema import DocMeta, append_manifest


def _settings(tmp_path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        data_dir=data,
        corpus_dir=data / "corpus",
        inbox_dir=data / "inbox",
        chroma_dir=data / "chroma",
        manifest_path=data / "corpus" / "manifest.jsonl",
    )


def _write_doc(s, doc_id, category, fname, text, title, content_hash):
    p = s.corpus_dir / category / fname
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    append_manifest(
        s.manifest_path,
        [
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url="inbox/x",
                publisher="学生工作部",
                publish_date="unknown",
                category=category,
                fetched_at="t",
                content_hash=content_hash,
                file_path=f"{category}/{fname}",
                retention_status="active",
                retention_reason="test_fixture",
            )
        ],
    )


def test_first_build_indexes_all(tmp_path):
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    _write_doc(s, "docB", "推免升学", "b.md", "第一条 推免条件。", "推免办法", "sha256:bbbb")
    r = update_index(s, FakeEmbedder())
    assert (r.added_docs, r.updated_docs, r.deleted_docs) == (2, 0, 0)
    assert r.total_chunks >= 2


def test_index_metadata_records_actual_embedder_and_manifest_fingerprint(tmp_path):
    s = _settings(tmp_path)
    _write_doc(
        s,
        "docA",
        "奖助学金",
        "a.md",
        "第一条 奖学金标准。",
        "奖学金办法",
        "sha256:aaaa",
    )

    update_index(s, FakeEmbedder(), full=True)

    metadata = json.loads((s.chroma_dir / "index_metadata.json").read_text(encoding="utf-8"))
    assert metadata["embedding_model"] == "fake-hash-3gram-v1"
    assert metadata["embedding_backend"] == "fake"
    assert metadata["test_only"] is True
    assert metadata["manifest_fingerprint"].startswith("sha256:")
    assert metadata["index_fingerprint"].startswith("sha256:")


def test_bge_embedder_uses_fp16_and_small_batches_on_low_vram(monkeypatch):
    calls = {}

    class StubModel:
        def __init__(self, model_name, **kwargs):
            calls["init"] = (model_name, kwargs)

        def encode(self, texts, **kwargs):
            calls["encode"] = (texts, kwargs)
            return [[1.0, 0.0] for _ in texts]

    stub_torch = SimpleNamespace(
        float16="float16",
        cuda=SimpleNamespace(
            is_available=lambda: True,
            get_device_properties=lambda _index: SimpleNamespace(total_memory=2 * 1024**3),
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", stub_torch)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=StubModel),
    )

    embedder = BgeEmbedder("BAAI/bge-m3")
    vectors = embedder.encode(["第一条 测试文本"])

    assert calls["init"] == (
        "BAAI/bge-m3",
        {"device": "cuda", "model_kwargs": {"torch_dtype": "float16"}},
    )
    assert calls["encode"][1]["batch_size"] == 2
    assert embedder.device == "cuda"
    assert embedder.precision == "float16"
    assert vectors == [[1.0, 0.0]]


def test_second_run_noop(tmp_path):
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    update_index(s, FakeEmbedder())
    r = update_index(s, FakeEmbedder())
    assert (r.added_docs, r.updated_docs, r.deleted_docs) == (0, 0, 0)


def test_update_and_delete(tmp_path):
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 旧标准。", "奖学金办法", "sha256:aaaa")
    _write_doc(s, "docB", "推免升学", "b.md", "第一条 推免条件。", "推免办法", "sha256:bbbb")
    update_index(s, FakeEmbedder())
    # docA 改内容（同 doc_id 新 hash）；docB 从 manifest 移除
    p = s.corpus_dir / "奖助学金" / "a.md"
    p.write_text("第一条 新标准。增加条款。", encoding="utf-8")
    append_manifest(
        s.manifest_path,
        [
            DocMeta(
                doc_id="docA",
                title="奖学金办法",
                source_url="inbox/x",
                publisher="学生工作部",
                publish_date="unknown",
                category="奖助学金",
                fetched_at="t2",
                content_hash="sha256:cccc",
                file_path="奖助学金/a.md",
                retention_status="active",
                retention_reason="test_fixture",
            )
        ],
    )
    lines = s.manifest_path.read_text(encoding="utf-8").splitlines()
    keep = [line for line in lines if '"docB"' not in line]
    s.manifest_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    r = update_index(s, FakeEmbedder())
    assert r.updated_docs == 1 and r.deleted_docs == 1 and r.added_docs == 0


def test_embeds_title_prefixed_chunk(tmp_path):
    """嵌入向量必须带标题前缀（contextual header），库存文档保持原文。"""
    import chromadb

    class RecordingEmbedder(FakeEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.seen: list[str] = []

        def encode(self, texts):
            self.seen.extend(texts)
            return super().encode(texts)

    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    emb = RecordingEmbedder()
    update_index(s, emb)
    assert emb.seen and all(t.startswith("奖学金办法\n") for t in emb.seen)
    # 库存文档保持原文（不带标题前缀）
    col = chromadb.PersistentClient(path=str(s.chroma_dir)).get_collection(s.collection_name)
    docs = col.get(include=["documents"])["documents"]
    assert docs and all(not d.startswith("奖学金办法\n") for d in docs)


def test_metadata_only_update_refreshes_chroma_without_reembedding(tmp_path):
    """正文不变、publish_date 变化时，增量索引只刷新 Chroma metadata，不重 embed。"""
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")

    class CountingEmbedder(FakeEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def encode(self, texts):
            self.calls += 1
            return super().encode(texts)

    emb = CountingEmbedder()
    update_index(s, emb)
    assert emb.calls > 0

    # ingest 的场景：content_hash 不变，metadata 变化，append 新 manifest 行
    append_manifest(
        s.manifest_path,
        [
            DocMeta(
                doc_id="docA",
                title="奖学金办法",
                source_url="inbox/x",
                publisher="学生工作部",
                publish_date="2026-08-01",
                category="奖助学金",
                fetched_at="t2",
                content_hash="sha256:aaaa",
                file_path="奖助学金/a.md",
                retention_status="active",
                retention_reason="test_fixture",
            )
        ],
    )
    emb.calls = 0
    r = update_index(s, emb)

    assert r.meta_updated_docs == 1
    assert (r.added_docs, r.updated_docs, r.deleted_docs) == (0, 0, 0)
    assert emb.calls == 0  # 未重跑 embedding
    col = chromadb.PersistentClient(path=str(s.chroma_dir)).get_collection(s.collection_name)
    metas = col.get(where={"doc_id": "docA"}, include=["metadatas"])["metadatas"]
    assert metas and all(m["publish_date"] == "2026-08-01" for m in metas)
    assert all(m["metadata_sig"].startswith("sha256:") for m in metas)


def test_incremental_rejects_embedder_mismatch(tmp_path):
    """换 embedding 模型后增量索引必须拒绝，强制走 --full。"""
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    update_index(s, FakeEmbedder())

    class OtherEmbedder(FakeEmbedder):
        model_name = "other-model-v9"

    with pytest.raises(RuntimeError, match="--full"):
        update_index(s, OtherEmbedder())
    # --full 显式重建不受守卫限制
    r = update_index(s, OtherEmbedder(), full=True)
    assert r.added_docs == 1
    # 重建后同模型增量恢复可用
    assert update_index(s, OtherEmbedder()).added_docs == 0


class _CountingEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return super().encode(texts)


class _RecordingEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def encode(self, texts):
        self.seen.extend(texts)
        return super().encode(texts)


def _append_doc_row(s, doc_id, category, fname, title, content_hash, publish_date="unknown"):
    append_manifest(
        s.manifest_path,
        [
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url="inbox/x",
                publisher="学生工作部",
                publish_date=publish_date,
                category=category,
                fetched_at="t2",
                content_hash=content_hash,
                file_path=f"{category}/{fname}",
                retention_status="active",
                retention_reason="test_fixture",
            )
        ],
    )


def test_title_change_triggers_reembedding_with_new_title(tmp_path):
    """title 是 embedding 输入前缀：正文/content_hash 不变、title 变 → 必须重 embed。"""
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    emb = _RecordingEmbedder()
    update_index(s, emb)
    assert emb.seen and all(t.startswith("奖学金办法\n") for t in emb.seen)

    emb.seen.clear()
    _append_doc_row(s, "docA", "奖助学金", "a.md", "国家奖学金实施细则", "sha256:aaaa")
    r = update_index(s, emb)

    assert r.updated_docs == 1 and r.meta_updated_docs == 0
    assert emb.seen, "title 变化必须重新 embedding"
    assert all(t.startswith("国家奖学金实施细则\n") for t in emb.seen)
    assert all("第一条 奖学金标准。" in t for t in emb.seen)


def test_second_run_is_true_noop_without_reembedding(tmp_path):
    """title/正文/metadata 全不变：第二次 index 不触发 embed，也无 metadata 刷新。"""
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    emb = _CountingEmbedder()
    update_index(s, emb)

    emb.calls = 0
    r = update_index(s, emb)
    assert (r.added_docs, r.updated_docs, r.deleted_docs, r.meta_updated_docs) == (0, 0, 0, 0)
    assert emb.calls == 0


def test_incremental_rejects_existing_index_with_missing_metadata(tmp_path):
    """已有 chunks 但 index_metadata.json 缺失：不得给旧索引重盖当前 metadata。"""
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    update_index(s, FakeEmbedder())
    (s.chroma_dir / "index_metadata.json").unlink()

    with pytest.raises(RuntimeError, match="--full"):
        update_index(s, FakeEmbedder())
    # --full 重建后恢复
    assert update_index(s, FakeEmbedder(), full=True).added_docs == 1
    assert update_index(s, FakeEmbedder()).added_docs == 0


def test_incremental_rejects_existing_index_with_corrupt_metadata(tmp_path):
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    update_index(s, FakeEmbedder())
    (s.chroma_dir / "index_metadata.json").write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="--full"):
        update_index(s, FakeEmbedder())
    assert update_index(s, FakeEmbedder(), full=True).added_docs == 1
    assert update_index(s, FakeEmbedder()).added_docs == 0


def test_missing_metadata_with_empty_index_allows_first_build(tmp_path):
    """无 metadata 且无 chunks 的首次构建放行（含空 manifest 场景）。"""
    s = _settings(tmp_path)
    assert not (s.chroma_dir / "index_metadata.json").exists()
    r = update_index(s, FakeEmbedder())
    assert r.added_docs == 0 and r.total_chunks == 0
    # 空索引写出的 metadata 有效：删掉后无 chunks，仍按首次构建放行
    (s.chroma_dir / "index_metadata.json").unlink()
    assert update_index(s, FakeEmbedder()).added_docs == 0
