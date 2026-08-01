from sufe_qa.config import Settings
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
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
