from __future__ import annotations

from types import SimpleNamespace

from sufe_qa.config import Settings
from sufe_qa.crawler.adapters import GraduateSchoolAdapter, SectionSpec
from sufe_qa.crawler.authority import AuthoritySource
from sufe_qa.crawler.authority_runner import AuthorityRunOptions, crawl_authority_sources
from sufe_qa.crawler.authority_runner import retry_attachments_from_raw
from sufe_qa.crawler.fetcher import FetchResult
from sufe_qa.schema import load_manifest


class StubFetcher:
    def __init__(self, *args, **kwargs):
        self.routes = {
            "https://gs.sufe.edu.cn/Home/List/49": FetchResult(
                requested_url="https://gs.sufe.edu.cn/Home/List/49",
                final_url="https://gs.sufe.edu.cn/Home/List/49",
                content='<div class="single-blog-item"><div class="blog-content"><a href="/Home/Detail/8001">研究生选课通知</a></div></div>'.encode("utf-8"),
                mime_type="text/html",
                status_code=200,
            ),
            "https://gs.sufe.edu.cn/Home/Detail/8001": FetchResult(
                requested_url="https://gs.sufe.edu.cn/Home/Detail/8001",
                final_url="https://gs.sufe.edu.cn/Home/Detail/8001",
                content="<html><head><title>研究生选课通知|培养工作</title></head><body><h1>研究生选课通知</h1><div class=content>研究生选课条件、材料和办理流程说明，适用于在校研究生。</div></body></html>".encode("utf-8"),
                mime_type="text/html",
                status_code=200,
            ),
        }

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def fetch(self, url, kind="html", headers=None):
        return self.routes.get(
            url,
            FetchResult(
                requested_url=url,
                final_url=url,
                status="http_error",
                status_code=404,
                error="404",
            ),
        )


def test_authority_runner_wires_adapter_to_ingest_and_source_metadata(tmp_path, monkeypatch):
    data = tmp_path / "data"
    settings = Settings(
        data_dir=data,
        corpus_dir=data / "corpus",
        inbox_dir=data / "inbox",
        chroma_dir=data / "chroma",
        manifest_path=data / "corpus" / "manifest.jsonl",
    )
    section = SectionSpec(
        section_id="gs-49",
        name="培养工作",
        list_url="https://gs.sufe.edu.cn/Home/List/49",
        category="学工事务",
        publisher="上海财经大学研究生院",
        source_type="official_department",
        scope_unit="研究生",
    )
    source = AuthoritySource(
        source_id="gs",
        adapter_name="graduate_school",
        homepage="https://gs.sufe.edu.cn/",
        publisher="上海财经大学研究生院",
        source_type="official_department",
        scope_unit="研究生",
        sections=(section,),
    )
    monkeypatch.setattr("sufe_qa.crawler.authority_runner.SafeFetcher", StubFetcher)
    monkeypatch.setattr(
        "sufe_qa.crawler.authority_runner.adapter_for_source", lambda _: GraduateSchoolAdapter()
    )
    reports = crawl_authority_sources(
        settings,
        [source],
        options=AuthorityRunOptions(max_list_pages=3, max_articles=3),
        parse_attachment=lambda filename, content: SimpleNamespace(parse_status="ok", text=""),
    )
    manifest = load_manifest(settings.manifest_path)
    assert len(reports) == 1
    assert len(manifest) == 1
    meta = next(iter(manifest.values()))
    assert meta.source_type == "official_department"
    assert meta.source_section == "培养工作"
    assert meta.scope_unit == "研究生"


def test_retry_attachments_replays_saved_raw_articles_without_refetching_html(tmp_path, monkeypatch):
    data = tmp_path / "data"
    settings = Settings(
        data_dir=data,
        corpus_dir=data / "corpus",
        inbox_dir=data / "inbox",
        chroma_dir=data / "chroma",
        manifest_path=data / "corpus" / "manifest.jsonl",
    )
    from sufe_qa.schema import DocMeta, append_manifest, doc_id_from

    source_url = "https://gs.sufe.edu.cn/Home/Detail/8001"
    doc_id = doc_id_from(source_url)
    raw = settings.data_dir / "raw" / "gs.sufe.edu.cn" / "articles" / f"{doc_id}.html"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(
        """<html><head><title>研究生选课通知|培养工作</title></head><body>
        <h1>研究生选课通知</h1><div class="content">研究生选课条件、材料和办理流程。</div>
        <a href="https://ssd.sufe.edu.cn/index.php?mod=pdf&path=abc">选课指南</a></body></html>""",
        encoding="utf-8",
    )
    append_manifest(
        settings.manifest_path,
        [
            DocMeta(
                doc_id=doc_id,
                title="研究生选课通知",
                source_url=source_url,
                publisher="上海财经大学研究生院",
                publish_date="2026-06-01",
                category="学工事务",
                fetched_at="2026-08-01",
                content_hash="sha256:old",
                file_path="学工事务/old.md",
                source_type="official_department",
                source_section="培养工作",
                scope_unit="研究生",
            )
        ],
    )
    (settings.corpus_dir / "学工事务").mkdir(parents=True, exist_ok=True)
    (settings.corpus_dir / "学工事务/old.md").write_text("旧正文", encoding="utf-8")

    class AttachmentFetcher(StubFetcher):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.routes["https://ssd.sufe.edu.cn/index.php?mod=pdf&path=abc"] = FetchResult(
                requested_url="https://ssd.sufe.edu.cn/index.php?mod=pdf&path=abc",
                final_url="https://ssd.sufe.edu.cn/index.php?mod=pdf&path=abc",
                content=b"pdf bytes",
                mime_type="application/pdf",
                status_code=200,
            )

    monkeypatch.setattr("sufe_qa.crawler.authority_runner.SafeFetcher", AttachmentFetcher)
    source = AuthoritySource(
        source_id="gs",
        adapter_name="graduate_school",
        homepage="https://gs.sufe.edu.cn/",
        publisher="上海财经大学研究生院",
        source_type="official_department",
        scope_unit="研究生",
        sections=(),
        allowed_hosts=("ssd.sufe.edu.cn",),
    )
    reports = retry_attachments_from_raw(
        settings,
        source,
        parse_attachment=lambda filename, content: SimpleNamespace(
            parse_status="ok", text="选课申请条件、材料和办理流程。"
        ),
    )
    assert reports[0].attachments_downloaded == 1
    assert any(meta.document_type == "attachment" for meta in load_manifest(settings.manifest_path).values())
