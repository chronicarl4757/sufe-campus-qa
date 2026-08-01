from __future__ import annotations

import chromadb
import pytest

from sufe_qa.config import Settings
from sufe_qa.indexing.collections import (
    MAIN_QA_COLLECTION,
    PUBLIC_LIST_COLLECTION,
    collection_for_kind,
    collection_name_for,
)
from sufe_qa.indexing.indexer import FakeEmbedder, migrate_legacy_collection, update_index
from sufe_qa.retrieve.retriever import HybridRetriever
from sufe_qa.schema import DocMeta, append_manifest, doc_id_from


def _settings(tmp_path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        data_dir=data,
        corpus_dir=data / "corpus",
        inbox_dir=data / "inbox",
        chroma_dir=data / "chroma",
        manifest_path=data / "corpus" / "manifest.jsonl",
    )


def _add_doc(settings: Settings, source: str, title: str, kind: str, text: str) -> str:
    doc_id = doc_id_from(source)
    rel = f"材料/{doc_id}.md"
    path = settings.corpus_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
    append_manifest(
        settings.manifest_path,
        [
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url=source,
                publisher="测试职能部门",
                publish_date="2026-01-01",
                category="学工事务",
                fetched_at="2026-08-01T00:00:00+08:00",
                content_hash=f"sha256:{doc_id}",
                file_path=rel,
                document_kind=kind,
                quality_status="accepted",
            )
        ],
    )
    return doc_id


def test_collection_routing_uses_explicit_kind_allowlists():
    assert collection_for_kind("policy") == MAIN_QA_COLLECTION
    assert collection_for_kind("service_guide") == MAIN_QA_COLLECTION
    assert collection_for_kind("public_list") == PUBLIC_LIST_COLLECTION
    assert collection_for_kind("news") is None
    assert collection_for_kind("incomplete") is None


def test_collection_names_are_versioned_and_legacy_is_not_default(tmp_path):
    settings = _settings(tmp_path)
    assert collection_name_for(settings, MAIN_QA_COLLECTION) == "sufe_qa_main_v2"
    assert collection_name_for(settings, PUBLIC_LIST_COLLECTION) == "sufe_qa_public_list_v2"
    assert settings.collection_name == "sufe_qa_main_v2"
    assert settings.legacy_collection_name == "sufe_campus_qa"


def test_indexer_separates_main_public_and_archived_documents(tmp_path):
    settings = _settings(tmp_path)
    main_id = _add_doc(
        settings,
        "https://jwc.sufe.edu.cn/policy",
        "缓考办理办法",
        "policy",
        "本科生因病不能参加考试，可以按照条件、材料和流程申请缓考。",
    )
    public_id = _add_doc(
        settings,
        "https://xsc.sufe.edu.cn/list",
        "奖学金获奖名单公示",
        "public_list",
        "2026年度本科生奖学金获奖名单如下，公示期为五个工作日。",
    )
    _add_doc(
        settings,
        "https://xsc.sufe.edu.cn/news",
        "学生工作新闻",
        "news",
        "学校举行学生工作交流活动，介绍相关情况。",
    )

    report = update_index(settings, FakeEmbedder())
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    main = client.get_collection(settings.collection_name)
    public = client.get_collection(settings.public_list_collection_name)

    assert report.added_docs == 2
    assert {m["doc_id"] for m in main.get(include=["metadatas"])["metadatas"]} == {main_id}
    assert {m["doc_id"] for m in public.get(include=["metadatas"])["metadatas"]} == {public_id}
    assert all(
        m["index_collection"] == settings.collection_name
        for m in main.get(include=["metadatas"])["metadatas"]
    )


def test_retriever_defaults_to_main_and_public_is_explicit(tmp_path):
    settings = _settings(tmp_path)
    main_id = _add_doc(
        settings,
        "https://jwc.sufe.edu.cn/policy",
        "缓考办理办法",
        "policy",
        "缓考申请条件、材料和办理流程。",
    )
    public_id = _add_doc(
        settings,
        "https://xsc.sufe.edu.cn/list",
        "奖学金获奖名单公示",
        "public_list",
        "获奖名单公示信息。",
    )
    update_index(settings, FakeEmbedder())

    default_hits = HybridRetriever(settings, FakeEmbedder()).search("缓考申请流程")
    public_hits = HybridRetriever(
        settings, FakeEmbedder(), collection=PUBLIC_LIST_COLLECTION
    ).search("获奖名单")

    assert default_hits and {h.doc_id for h in default_hits} == {main_id}
    assert public_hits and {h.doc_id for h in public_hits} == {public_id}


def test_retriever_can_route_collection_per_query(tmp_path):
    settings = _settings(tmp_path)
    _add_doc(
        settings,
        "https://jwc.sufe.edu.cn/policy",
        "缓考办理办法",
        "policy",
        "缓考申请条件、材料和办理流程。",
    )
    _add_doc(
        settings,
        "https://xsc.sufe.edu.cn/list",
        "奖学金获奖名单公示",
        "public_list",
        "获奖名单公示信息。",
    )
    update_index(settings, FakeEmbedder())
    retriever = HybridRetriever(settings, FakeEmbedder())

    hits = retriever.search("获奖名单", collection=PUBLIC_LIST_COLLECTION)
    assert hits and hits[0].title == "奖学金获奖名单公示"


def test_legacy_collection_is_read_only_migration_input(tmp_path):
    settings = _settings(tmp_path)
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    legacy = client.get_or_create_collection(settings.legacy_collection_name)
    legacy.upsert(
        ids=["legacy-policy", "legacy-news"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=[
            "缓考办理办法 第一条 申请条件和材料。",
            "学院新闻 举行交流活动。",
        ],
        metadatas=[
            {"doc_id": "legacy-policy", "title": "缓考办理办法", "content_hash": "h1"},
            {"doc_id": "legacy-news", "title": "学院新闻", "content_hash": "h2"},
        ],
    )

    report = migrate_legacy_collection(settings)
    main = client.get_collection(settings.collection_name)
    assert report.source_collection == settings.legacy_collection_name
    assert report.migrated_chunks == 1
    assert main.get()["ids"] == ["legacy-policy"]
    assert client.get_collection(settings.legacy_collection_name).count() == 2


def test_full_rebuild_is_atomic_on_failure(tmp_path, monkeypatch):
    import sufe_qa.indexing.indexer as indexer

    settings = _settings(tmp_path)
    _add_doc(
        settings,
        "https://jwc.sufe.edu.cn/policy",
        "缓考办理办法",
        "policy",
        "缓考申请条件、材料和办理流程。",
    )
    update_index(settings, FakeEmbedder())

    def fail(*args, **kwargs):
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(indexer, "_build_full", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        update_index(settings, FakeEmbedder(), full=True)

    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    assert client.get_collection(settings.collection_name).count() > 0
