from __future__ import annotations

import pytest

from sufe_qa.evals.scorer import EvalItem, load_evalset, score_retrieval
from sufe_qa.retrieve.retriever import Hit


def _hit(doc_id: str, sim: float = 0.9) -> Hit:
    return Hit(
        chunk_id=f"{doc_id}:0",
        doc_id=doc_id,
        title="t",
        category="c",
        source_url="u",
        publisher="p",
        heading_path="",
        text="x",
        rrf_score=0.01,
        vector_similarity=sim,
    )


class _StubRetriever:
    """按问题返回预设命中。"""

    def __init__(self, mapping: dict[str, list[Hit]]):
        self._m = mapping

    def search(self, question: str) -> list[Hit]:
        return self._m.get(question, [])

    def search_routed(self, question: str) -> list[Hit]:
        return self.search(question)


def _settings():
    from sufe_qa.config import Settings
    from pathlib import Path

    return Settings(
        data_dir=Path("/tmp/x"),
        corpus_dir=Path("/tmp/x/corpus"),
        inbox_dir=Path("/tmp/x/inbox"),
        chroma_dir=Path("/tmp/x/chroma"),
        manifest_path=Path("/tmp/x/manifest.jsonl"),
    )


def test_load_evalset_parses_and_validates(tmp_path):
    p = tmp_path / "evalset.jsonl"
    p.write_text(
        "# 模板注释行：复制后按真实语料填写\n"
        '{"id": "q1", "question": "a", "expected_doc_ids": ["d1"], "should_refuse": false}\n'
        "\n"
        '{"id": "q2", "question": "b", "should_refuse": true}\n',
        encoding="utf-8",
    )
    items = load_evalset(p)
    assert items == [
        EvalItem(id="q1", question="a", expected_doc_ids=["d1"]),
        EvalItem(id="q2", question="b", should_refuse=True),
    ]
    p.write_text('{"id": "q3", "bad_key": 1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="评测集格式错误"):
        load_evalset(p)
    p.write_text('{"id": "q3", broken json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 解析失败"):
        load_evalset(p)


def test_score_and_gate():
    mapping = {
        "命中题": [_hit("d1")],
        "未命中题": [_hit("d2")],
        "拒答题": [_hit("d3", sim=0.1)],  # 低置信 → 被门控拦下 → 拒答正确
    }
    items = [
        EvalItem(id="1", question="命中题", expected_doc_ids=["d1"]),
        EvalItem(id="2", question="未命中题", expected_doc_ids=["d1"]),
        EvalItem(id="3", question="拒答题", should_refuse=True),
    ]
    report = score_retrieval(_StubRetriever(mapping), _settings(), items)
    assert report.hit_rate == pytest.approx(0.5)
    assert report.refusal_rate == pytest.approx(1.0)
    assert report.answer_rate == pytest.approx(1.0)
    failures = report.gate_failures(0.9, 1.0)
    assert len(failures) == 1 and "命中率" in failures[0]
    assert report.gate_failures(0.5, 1.0) == []


def test_gate_fails_on_empty_evalset():
    report = score_retrieval(_StubRetriever({}), _settings(), [])
    failures = report.gate_failures(0.9, 1.0)
    assert any("为空" in f for f in failures)


def test_gate_fails_when_missing_sample_kinds():
    only_answerable = score_retrieval(
        _StubRetriever({"命中题": [_hit("d1")]}),
        _settings(),
        [EvalItem(id="1", question="命中题", expected_doc_ids=["d1"])],
    )
    assert any("拒答题样本" in f for f in only_answerable.gate_failures(0.9, 1.0))
    only_refusable = score_retrieval(
        _StubRetriever({"拒答题": [_hit("d3", sim=0.1)]}),
        _settings(),
        [EvalItem(id="2", question="拒答题", should_refuse=True)],
    )
    assert any("应答题样本" in f for f in only_refusable.gate_failures(0.9, 1.0))


def test_answerable_refusal_counts_as_failure():
    # 系统全拒答时旧门禁会满分通过：命中只看检索、拒答题全对。
    # 新逻辑：应答题被拒答 → correct=False 且回答率 0 → 门禁必须拦下。
    mapping = {"应答题": [_hit("d1", sim=0.1)], "拒答题": [_hit("d2", sim=0.1)]}
    items = [
        EvalItem(id="1", question="应答题", expected_doc_ids=["d1"]),
        EvalItem(id="2", question="拒答题", should_refuse=True),
    ]
    report = score_retrieval(_StubRetriever(mapping), _settings(), items)
    assert report.rows[0].hit is True and report.rows[0].correct is False
    assert report.answer_rate == pytest.approx(0.0)
    assert any("回答率" in f for f in report.gate_failures(0.9, 1.0))
