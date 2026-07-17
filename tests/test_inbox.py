from sufe_qa.ingest.inbox import ingest_inbox, scan_sensitive
from sufe_qa.schema import load_manifest


def test_scan_sensitive_finds_id_and_phone():
    hits = scan_sensitive("张三 身份证号 310101199901011234 电话 13812345678")
    assert len(hits) == 2
    assert scan_sensitive("普通政策文本") == []


def test_ingest_writes_corpus_and_manifest(tmp_path):
    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    (inbox / "rule.md").write_text(
        "# 国家奖学金评审细则\n第一条 奖励标准为每生每年8000元。", encoding="utf-8"
    )
    report = ingest_inbox(inbox, corpus, manifest, category="奖助学金", publisher="学生工作部")
    assert report.added == 1 and report.skipped_dup == 0 and report.quarantined == []
    loaded = load_manifest(manifest)
    assert len(loaded) == 1
    meta = next(iter(loaded.values()))
    assert meta.category == "奖助学金" and "国家奖学金" in meta.title
    assert (corpus / meta.file_path).exists()


def test_ingest_dedup_by_content_hash(tmp_path):
    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    (inbox / "a.md").write_text("同一份文件内容", encoding="utf-8")
    (inbox / "b.md").write_text("同一份文件内容", encoding="utf-8")
    report = ingest_inbox(inbox, corpus, manifest, category="其他", publisher="手动投放")
    assert report.added == 1 and report.skipped_dup == 1


def test_ingest_quarantines_sensitive(tmp_path):
    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    (inbox / "leak.md").write_text("名单：李四 310101199901011234", encoding="utf-8")
    report = ingest_inbox(inbox, corpus, manifest, category="其他", publisher="手动投放")
    assert report.added == 0 and report.quarantined == ["leak.md"]
    assert load_manifest(manifest) == {}


def test_ingest_corrupt_file_counted_not_crash(tmp_path):
    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    (inbox / "bad.pdf").write_bytes(b"not a pdf")
    (inbox / "good.md").write_text("正常文件", encoding="utf-8")
    report = ingest_inbox(inbox, corpus, manifest, category="其他", publisher="手动投放")
    assert report.added == 1 and report.skipped_error == 1
