from __future__ import annotations

import pytest

from sufe_qa.config import load_settings
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
from sufe_qa.ingest.inbox import ingest_inbox
from sufe_qa.retrieve.retriever import (
    Hit,
    HybridRetriever,
    expand_query,
    is_confident,
    recency_weight,
    retrieval_time_weight,
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


def test_expand_query_adds_stable_campus_service_aliases():
    assert expand_query("校医院在哪里，如何联系？") == (
        "校医院在哪里，如何联系？ 门诊部 医疗健康服务中心 就诊导航 地理位置"
    )
    assert expand_query("毕业去向如何登记？") == (
        "毕业去向如何登记？ 毕业去向管理 我的毕业去向 就业综合管理服务平台"
    )
    assert expand_query("如何申请缓考？") == "如何申请缓考？"


def test_expand_query_maps_student_wording_to_official_terms():
    assert "课程不及格 参评学年" in expand_query("有挂科记录还能申请奖学金吗？")
    assert "家庭经济困难学生认定 认定程序" in expand_query(
        "家庭经济困难学生如何认定？"
    )
    assert "毕业去向管理 我的毕业去向" in expand_query("灵活就业如何登记？")
    assert "升学 交回协议书 违约改签" in expand_query("考上研究生后已签三方怎么办？")
    assert "期末成绩 成绩发布后7日 成绩复核" in expand_query(
        "本科生对课程成绩有异议如何申请复核？"
    )


def test_rrf_fuse_scores_and_order():
    scores = rrf_fuse([["a", "b"], ["c"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62)
    assert scores["c"] == pytest.approx(1 / 61)
    # 双路都命中的 chunk 排在单路命中之前
    scores2 = rrf_fuse([["x", "y"], ["x"]], k=60)
    assert scores2["x"] > scores2["y"]


def test_search_empty_index_returns_nothing(settings):
    update_index(settings, FakeEmbedder())  # 空 manifest：索引存在但无文档
    r = HybridRetriever(settings, FakeEmbedder())
    assert r.search("推免条件") == []


def test_retriever_fails_fast_without_index(settings):
    """serving 不得静默创建空 collection：索引缺失时启动即报错。"""
    with pytest.raises(RuntimeError, match="index_metadata"):
        HybridRetriever(settings, FakeEmbedder())


def test_retriever_fails_fast_on_embedder_mismatch(settings):
    _seed(settings, {"tuimian.md": "推免工作实施办法 第一条 申请条件。"})

    class OtherEmbedder(FakeEmbedder):
        model_name = "other-model-v9"

    with pytest.raises(RuntimeError, match="embedding_model"):
        HybridRetriever(settings, OtherEmbedder())


def test_hot_index_update_invalidates_corpus_cache(settings):
    """chunk 数不变的热更新后，同一 retriever 必须读到新正文（按索引指纹失效）。"""
    from sufe_qa.schema import DocMeta, append_manifest

    doc_id = doc_id_from("test/tuimian.md")

    def write(body: str, content_hash: str) -> None:
        (settings.corpus_dir / "tuimian.md").write_text(
            f"# 推免办法\n\n{body}\n", encoding="utf-8"
        )
        append_manifest(
            settings.manifest_path,
            [
                DocMeta(
                    doc_id=doc_id,
                    title="推免办法",
                    source_url="test/tuimian.md",
                    publisher="测试单位",
                    publish_date="2026-01-01",
                    category="学工事务",
                    fetched_at="t",
                    content_hash=content_hash,
                    file_path="tuimian.md",
                    retention_status="active",
                    retention_reason="test_fixture",
                )
            ],
        )
        update_index(settings, FakeEmbedder())

    write("推免申请条件：应届本科毕业生，品德良好，遵纪守法。", "sha256:v1")
    r = HybridRetriever(settings, FakeEmbedder())
    hits = r.search("推免 申请 条件")
    assert hits and "遵纪守法" in hits[0].text

    # 等长改文（chunk 数不变）：旧实现按 count 判缓存，这里会读到旧正文
    write("推免申请条件：应届本科毕业生，品德良好，学风端正。", "sha256:v2")
    hits = r.search("推免 申请 条件")
    assert hits and "学风端正" in hits[0].text


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


def test_recency_weight_decay():
    from datetime import date

    today = date(2026, 7, 31)
    assert recency_weight("2026-03-01", today) == 1.0
    assert recency_weight("2025-06-01", today) == pytest.approx(0.85)
    assert recency_weight("2024-01-01", today) == pytest.approx(0.85**2)
    assert recency_weight("2010-01-01", today) == 0.4  # 下限
    assert recency_weight("unknown", today) == 0.7
    assert recency_weight("", today) == 0.7
    assert recency_weight("2030-01-01", today) == 1.0  # 未来日期按当年


def test_retrieval_time_weight_only_decays_time_bound_document_kinds():
    from datetime import date

    today = date(2026, 7, 31)
    assert retrieval_time_weight("faq", "2013-01-01", today) == 1.0
    assert retrieval_time_weight("policy", "2013-01-01", today) == 1.0
    assert retrieval_time_weight("service_guide", "2013-01-01", today) == 1.0
    assert retrieval_time_weight("annual_notice", "2013-01-01", today) == 0.4
    assert retrieval_time_weight("public_list", "2025-01-01", today) == pytest.approx(0.85)


def test_search_recency_reranks_identical_relevance(settings):
    """相关性相同时新版文档排在旧版之前（年度通知场景）。"""
    from sufe_qa.schema import DocMeta, append_manifest

    body = "推免申请的学生应为应届本科毕业生，品德良好，遵纪守法，身心健康，成绩优秀。"
    for fname, date in (("old.md", "2015-01-01"), ("new.md", "2026-01-01")):
        (settings.corpus_dir / fname).parent.mkdir(parents=True, exist_ok=True)
        (settings.corpus_dir / fname).write_text(f"# 推免办法\n\n{body}\n", encoding="utf-8")
    metas = [
        DocMeta(
            doc_id=doc_id_from(f"test/{fname}"),
            title="推免办法",
            source_url=f"test/{fname}",
            publisher="测试单位",
            publish_date=date,
            category="学工事务",
            fetched_at="2026-07-31T00:00:00+00:00",
            content_hash=f"sha256:{fname}",
            file_path=fname,
            document_kind="annual_notice",
            retention_status="active",
            retention_reason="test_fixture",
        )
        for fname, date in (("old.md", "2015-01-01"), ("new.md", "2026-01-01"))
    ]
    append_manifest(settings.manifest_path, metas)
    update_index(settings, FakeEmbedder())

    hits = HybridRetriever(settings, FakeEmbedder()).search("推免申请 条件")
    assert hits[0].doc_id == doc_id_from("test/new.md")
    assert hits[0].publish_date == "2026-01-01"


def test_search_doc_type_boost(settings):
    """相关性相同时政策类文档排在新闻类之前（§十二 类型权重）。"""
    from sufe_qa.schema import DocMeta, append_manifest

    body = "推免申请的学生应为应届本科毕业生，品德良好，遵纪守法，身心健康，成绩优秀。"
    docs = (
        ("news.md", "学院推免工作新闻", f"学院举行推免工作宣讲会，调研情况如下。{body}"),
        ("policy.md", "推免工作管理办法", body),
    )
    for fname, title, text in docs:
        (settings.corpus_dir / fname).parent.mkdir(parents=True, exist_ok=True)
        (settings.corpus_dir / fname).write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
    append_manifest(
        settings.manifest_path,
        [
            DocMeta(
                doc_id=doc_id_from(f"test/{fname}"),
                title=title,
                source_url=f"test/{fname}",
                publisher="测试单位",
                publish_date="2026-01-01",
                category="学工事务",
                fetched_at="2026-07-31T00:00:00+00:00",
                content_hash=f"sha256:{fname}",
                file_path=fname,
                retention_status="active",
                retention_reason="test_fixture",
            )
            for fname, title, _ in docs
        ],
    )
    update_index(settings, FakeEmbedder())

    hits = HybridRetriever(settings, FakeEmbedder()).search("推免申请 条件")
    assert hits[0].doc_id == doc_id_from("test/policy.md")


def test_search_per_doc_chunk_cap(settings):
    """单文档最多占 max_chunks_per_doc 个槽位，其余来源得以进入 top-N（多样性截留）。"""
    big = "推免申请条件：应届本科毕业生，品德良好，遵纪守法，身心健康，成绩优秀。\n" * 150
    other = "助学金申请条件：家庭经济困难学生可提出推免申请以外的资助申请，按学年评审。\n" * 5
    _seed(settings, {"big.md": big, "other.md": other})
    r = HybridRetriever(settings, FakeEmbedder())
    hits = r.search("推免 申请 条件 助学金")
    big_id = doc_id_from("inbox/big.md")
    other_id = doc_id_from("inbox/other.md")
    big_hits = [h for h in hits if h.doc_id == big_id]
    assert 0 < len(big_hits) <= settings.max_chunks_per_doc
    assert other_id in {h.doc_id for h in hits}


def test_route_collections_intent():
    from sufe_qa.retrieve.retriever import route_collections

    assert route_collections("会计学院转专业拟录取名单公示了吗？") == ("main_qa", "public_list")
    assert route_collections("推免申请条件是什么？") == ("main_qa",)
    assert route_collections("这份办法的上一版规定了什么？") == ("main_qa", "historical")
    assert route_collections("该文件是否已被废止？") == ("main_qa", "historical")


def test_search_routed_finds_public_list_only_with_intent(settings):
    _seed(
        settings,
        {
            "gongshi.md": "# 会计学院转专业拟录取名单公示\n\n现将 2026 年会计学院转专业拟录取名单予以公示，公示期三天，如有异议请联系教务办。\n"
            * 3,
            "banfa.md": "# 转专业管理办法\n\n第一条 学生申请转专业应符合下列条件：品行良好，无违纪记录。\n"
            * 3,
        },
    )
    r = HybridRetriever(settings, FakeEmbedder())
    routed = r.search_routed("会计学院转专业拟录取名单公示了吗？")
    assert any("公示" in h.title for h in routed)
    # 无意图时只查主问答库，公示文档不出现
    plain = r.search("转专业申请条件")
    assert plain
    assert all("公示" not in h.title for h in plain)
