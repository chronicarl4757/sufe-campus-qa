from sufe_qa.ingest.inbox import ingest_inbox, scan_sensitive
from sufe_qa.schema import load_manifest


def test_scan_sensitive_finds_id_and_phone():
    hits = scan_sensitive("张三 身份证号 310101199901011234 电话 13812345678")
    assert len(hits) == 2
    assert scan_sensitive("普通政策文本") == []


def test_scan_sensitive_can_allow_public_service_phone_but_never_id():
    text = "服务电话 13812345678；身份证号 310101199901011234"
    assert scan_sensitive(text, allow_phone=True) == ["310101199901011234"]


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
    # 内容完全相同的两个文件（同 H1 标题 + 同正文），仅文件名不同
    (inbox / "a.md").write_text("# 同一标题\n同一份文件内容", encoding="utf-8")
    (inbox / "b.md").write_text("# 同一标题\n同一份文件内容", encoding="utf-8")
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


def test_ingest_unsupported_suffix_counted_not_crash(tmp_path):
    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    (inbox / "x.exe").write_bytes(b"MZ")
    (inbox / "good.md").write_text("正常文件", encoding="utf-8")
    report = ingest_inbox(inbox, corpus, manifest, category="其他", publisher="手动投放")
    assert report.added == 1 and report.skipped_error == 1


def test_ingest_update_same_file_overwrites_in_place(tmp_path):
    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    f = inbox / "rule.md"
    f.write_text("# 旧标题\n旧内容", encoding="utf-8")
    ingest_inbox(inbox, corpus, manifest, category="奖助学金", publisher="学生工作部")
    f.write_text("# 新标题\n新内容", encoding="utf-8")  # 同文件名更新
    report = ingest_inbox(inbox, corpus, manifest, category="奖助学金", publisher="学生工作部")
    assert report.added == 1
    files = list((corpus / "奖助学金").glob("*.md"))
    assert len(files) == 1  # 无孤儿副本
    assert "新内容" in files[0].read_text(encoding="utf-8")
    from sufe_qa.schema import load_manifest as lm

    assert lm(manifest)[next(iter(lm(manifest)))].title == "新标题"


def test_ingest_invalid_category_raises_before_write(tmp_path):
    import pytest

    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    (inbox / "a.md").write_text("内容", encoding="utf-8")
    with pytest.raises(ValueError, match="非法分类"):
        ingest_inbox(inbox, corpus, manifest, category="../escape", publisher="x")
    assert not corpus.exists() or list(corpus.rglob("*.md")) == []


def test_md_h1_not_duplicated_and_hash_matches_file(tmp_path):
    inbox, corpus, manifest = (
        tmp_path / "inbox",
        tmp_path / "corpus",
        tmp_path / "corpus/manifest.jsonl",
    )
    inbox.mkdir()
    (inbox / "rule.md").write_text("# 评审办法\n第一条 标准。", encoding="utf-8")
    ingest_inbox(inbox, corpus, manifest, category="奖助学金", publisher="学生工作部")
    from sufe_qa.schema import load_manifest as lm, sha256_text

    meta = next(iter(lm(manifest).values()))
    content = (corpus / meta.file_path).read_text(encoding="utf-8")
    assert content.count("# 评审办法") == 1  # 单 H1
    assert meta.content_hash == sha256_text(content)
