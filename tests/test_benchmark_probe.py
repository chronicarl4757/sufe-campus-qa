from __future__ import annotations

from pathlib import Path

import pytest

from sufe_qa.config import Settings
from sufe_qa.coverage.benchmark_probe import (
    BenchmarkItem,
    evaluate_item,
    load_benchmark,
    run_benchmark,
)
from sufe_qa.retrieve.retriever import Hit


def _hit(
    doc_id: str, sim: float = 0.9, url: str = "https://jwc.sufe.edu.cn/x.htm", text: str = "x"
) -> Hit:
    return Hit(
        chunk_id=f"{doc_id}:0",
        doc_id=doc_id,
        title="t",
        category="c",
        source_url=url,
        publisher="p",
        heading_path="",
        text=text,
        rrf_score=0.01,
        vector_similarity=sim,
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        inbox_dir=tmp_path / "inbox",
        chroma_dir=tmp_path / "chroma",
        manifest_path=tmp_path / "manifest.jsonl",
    )


class _StubRetriever:
    def __init__(self, mapping: dict[str, list[Hit]]):
        self._m = mapping

    def search_routed(self, question: str) -> list[Hit]:
        return self._m.get(question, [])


def test_load_benchmark_parses_schema(tmp_path):
    p = tmp_path / "bank.jsonl"
    p.write_text(
        "# 注释\n"
        '{"id": "a-001", "question": "q", "scene": "本科教务", "question_type": "procedure",'
        ' "expected_domains": ["jwc.sufe.edu.cn"], "expected_answer_points": ["办理流程"],'
        ' "should_refuse": false, "needs_clarification": false, "valid_for_year": 2026}\n'
        "\n"
        '{"id": "r-001", "question": "r", "scene": "拒答", "should_refuse": true}\n',
        encoding="utf-8",
    )
    items = load_benchmark(p)
    assert items == [
        BenchmarkItem(
            id="a-001",
            question="q",
            scene="本科教务",
            question_type="procedure",
            expected_domains=("jwc.sufe.edu.cn",),
            expected_answer_points=("办理流程",),
            valid_for_year=2026,
        ),
        BenchmarkItem(id="r-001", question="r", scene="拒答", should_refuse=True),
    ]
    p.write_text('{"id": "bad"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="不是合法 JSON"):
        load_benchmark(p)


def test_evaluate_answerable_with_domain_and_points():
    item = BenchmarkItem(
        id="q1",
        question="如何申请缓考？",
        scene="本科教务",
        expected_domains=("jwc.sufe.edu.cn",),
        expected_answer_points=("申请条件", "办理流程"),
    )
    hits = [_hit("d1", text="缓考申请条件：因病；办理流程：教务系统提交")]
    r = evaluate_item(item, hits, 0.5)
    assert r.status == "answerable"
    assert r.supported_points == ("申请条件", "办理流程")
    assert r.matched_domains == ("jwc.sufe.edu.cn",)


def test_evaluate_not_answerable_when_below_gate():
    item = BenchmarkItem(id="q2", question="q", scene="s", expected_answer_points=("申请条件",))
    r = evaluate_item(item, [_hit("d1", sim=0.2)], 0.5)
    assert r.status == "not_answerable"
    assert r.refused_by_gate
    assert "语料缺口" in r.missing_reasons[0]


def test_evaluate_partial_on_missing_point_or_domain():
    item = BenchmarkItem(
        id="q3",
        question="q",
        scene="s",
        expected_domains=("jwc.sufe.edu.cn",),
        expected_answer_points=("申请条件", "办理流程"),
    )
    hits = [_hit("d1", url="https://news.example.cn/x", text="申请条件：应届")]
    r = evaluate_item(item, hits, 0.5)
    assert r.status == "partially_answerable"
    assert r.unsupported_points == ("办理流程",)
    assert any("域名偏离" in reason for reason in r.missing_reasons)


def test_evaluate_refusal_and_clarification_status():
    refusal = BenchmarkItem(id="r1", question="r", scene="s", should_refuse=True)
    assert evaluate_item(refusal, [_hit("d1", sim=0.1)], 0.5).status == "gate_refused"
    assert evaluate_item(refusal, [_hit("d1", sim=0.9)], 0.5).status == "generation_check_required"
    clarify = BenchmarkItem(id="c1", question="c", scene="s", needs_clarification=True)
    assert evaluate_item(clarify, [_hit("d1")], 0.5).status == "clarification_check_required"


def test_run_benchmark_aggregates(tmp_path):
    bank = tmp_path / "bank.jsonl"
    bank.write_text(
        '{"id": "1", "question": "可答", "scene": "A",'
        ' "expected_answer_points": ["申请条件"]}\n'
        '{"id": "2", "question": "不可答", "scene": "A"}\n'
        '{"id": "3", "question": "拒答", "scene": "B", "should_refuse": true}\n',
        encoding="utf-8",
    )
    retriever = _StubRetriever(
        {
            "可答": [_hit("d1", text="申请条件：应届")],
            "不可答": [_hit("d2", sim=0.1)],
            "拒答": [_hit("d3", sim=0.1)],
        }
    )
    report = run_benchmark(_settings(tmp_path), retriever, bank)
    assert report.total == 3
    assert report.scored == 2
    assert report.answerable == 1
    assert report.not_answerable == 1
    assert report.refusal_gate_refused == 1
    assert report.by_scene["A"]["answerable"] == 1
    assert report.by_scene["B"]["gate_refused"] == 1
