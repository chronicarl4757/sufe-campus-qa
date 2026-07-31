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
    failures = report.gate_failures(0.9, 1.0)
    assert len(failures) == 1 and "命中率" in failures[0]
    assert report.gate_failures(0.5, 1.0) == []
