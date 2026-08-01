from __future__ import annotations

from pathlib import Path

from sufe_qa.config import Settings
from sufe_qa.generate.answer import REFUSAL_TEMPLATE, answer_question, validate_citations
from sufe_qa.generate.client import FakeLLM
from sufe_qa.generate.prompt import build_messages
from sufe_qa.retrieve.retriever import Hit


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        inbox_dir=tmp_path / "inbox",
        chroma_dir=tmp_path / "chroma",
        manifest_path=tmp_path / "corpus" / "manifest.jsonl",
    )


def _hit(doc_id: str, sim: float = 0.9, title: str = "办法") -> Hit:
    return Hit(
        chunk_id=f"{doc_id}:0",
        doc_id=doc_id,
        title=title,
        category="学工事务",
        source_url=f"https://example.com/{doc_id}",
        publisher="测试单位",
        heading_path="第一条",
        text="正文内容",
        rrf_score=0.03,
        vector_similarity=sim,
    )


class _StubRetriever:
    def __init__(self, hits: list[Hit]):
        self._hits = hits

    def search(self, question: str) -> list[Hit]:
        return self._hits


class _BoomLLM:
    def stream_chat(self, messages):
        raise AssertionError("拒答路径不应调用 LLM")


def test_build_messages_numbers_sources():
    msgs = build_messages("推免条件？", [_hit("d1", title="推免办法"), _hit("d2", title="细则")])
    assert "严禁编造" in msgs[0]["content"]
    assert "以发布日期最新者为准" in msgs[0]["content"]  # 时效冲突规则
    user = msgs[1]["content"]
    assert "[1] 《推免办法》 第一条（测试单位，发布于 unknown）" in user
    assert "[2] 《细则》 第一条" in user
    assert "推免条件？" in user


def test_refusal_when_no_confident_hit(tmp_path):
    # 低置信命中同样拒答，且不消耗 LLM
    ans = answer_question(
        "问题", _settings(tmp_path), _StubRetriever([_hit("d1", sim=0.1)]), llm=_BoomLLM()
    )
    assert ans.refused
    assert list(ans.stream) == [REFUSAL_TEMPLATE]
    assert ans.sources() == []


def test_answer_streams_and_dedupes_source_cards(tmp_path):
    hits = [_hit("d1", title="推免办法"), _hit("d1", title="推免办法"), _hit("d2", title="细则")]
    ans = answer_question("推免条件？", _settings(tmp_path), _StubRetriever(hits), llm=FakeLLM(2))
    assert not ans.refused
    text = "".join(ans.stream)
    assert "[1][2]" in text
    cards, cite_map = ans.sources_and_map()
    assert [c.title for c in cards] == ["推免办法", "细则"]
    assert [c.index for c in cards] == [1, 2]  # 展示序号连续
    assert cite_map == {1: 1, 2: 1, 3: 2}  # prompt 引文编号 → 卡片序号


def test_validate_citations():
    ok = validate_citations("申请须为应届毕业生[1]，并获推荐资格[2]。", 2)
    assert ok.ok and ok.has_citation and ok.invalid_refs == []
    # 编号越界（模型幻觉出 [99]）判不通过
    bad = validate_citations("依据资料[1]与[99]可得。", 2)
    assert not bad.ok and bad.invalid_refs == [99]
    # 全文无引用判不通过；[ 3 ] 空白变体可识别
    none = validate_citations("没有任何引用的回答。", 2)
    assert not none.ok and not none.has_citation
    spaced = validate_citations("见资料[ 2 ]。", 2)
    assert spaced.ok
