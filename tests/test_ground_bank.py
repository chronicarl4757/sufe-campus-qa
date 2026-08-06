from __future__ import annotations

import json

from sufe_qa.coverage.ground_bank import decide_grounding, ground_bank


def _result(status: str, hits: list[dict] | None = None, reasons: list[str] | None = None) -> dict:
    return {
        "status": status,
        "top_hits": hits or [],
        "missing_reasons": reasons or [],
    }


def _hit(doc_id: str, sim: float = 0.8, kind: str = "procedure", date: str = "2026-01-01") -> dict:
    return {
        "doc_id": doc_id,
        "similarity": sim,
        "document_kind": kind,
        "publish_date": date,
    }


def test_grounded_when_high_sim_authoritative_doc():
    d = decide_grounding(_result("answerable", [_hit("a1")]), current_year=2026)
    assert d.status == "grounded"
    assert d.expected_doc_ids == ("a1",)


def test_needs_docs_when_below_ground_similarity_line():
    d = decide_grounding(_result("answerable", [_hit("a1", sim=0.52)]), current_year=2026)
    assert d.status == "needs_docs"
    assert "固化线" in d.reason


def test_needs_docs_when_only_news_or_list_hits():
    hits = [_hit("n1", kind="news"), _hit("p1", kind="public_list")]
    d = decide_grounding(_result("answerable", hits), current_year=2026)
    assert d.status == "needs_docs"
    assert "文档类型" in d.reason


def test_stale_annual_notice_not_groundable():
    d = decide_grounding(
        _result("answerable", [_hit("old", kind="annual_notice", date="2019-03-01")]),
        current_year=2026,
    )
    assert d.status == "needs_docs"


def test_partial_and_not_answerable_go_to_needs_docs():
    assert (
        decide_grounding(_result("partially_answerable"), current_year=2026).status == "needs_docs"
    )
    d = decide_grounding(
        _result("not_answerable", reasons=["无高置信检索结果（语料缺口）"]), current_year=2026
    )
    assert d.status == "needs_docs"
    assert "语料缺口" in d.reason


def test_ground_bank_writes_both_files(tmp_path):
    bank = tmp_path / "bank.jsonl"
    bank.write_text(
        '{"id": "1", "question": "可答", "scene": "A", "expected_domains": ["jwc.sufe.edu.cn"]}\n'
        '{"id": "2", "question": "缺口", "scene": "A", "expected_domains": ["nic.sufe.edu.cn"]}\n'
        '{"id": "3", "question": "拒答", "scene": "B", "should_refuse": true}\n',
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "results": [
                    {"id": "1", **_result("answerable", [_hit("a1"), _hit("a2", sim=0.7)])},
                    {
                        "id": "2",
                        **_result("not_answerable", reasons=["无高置信检索结果（语料缺口）"]),
                    },
                    {"id": "3", "status": "gate_refused", "top_hits": [], "missing_reasons": []},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    grounded = tmp_path / "grounded.jsonl"
    needs = tmp_path / "needs.jsonl"
    n_g, n_n = ground_bank(
        bank, report, grounded_out=grounded, needs_docs_out=needs, current_year=2026
    )
    assert (n_g, n_n) == (2, 1)  # 可答题 + 拒答题 grounded；缺口题另算
    g1, g3 = [json.loads(line) for line in grounded.read_text(encoding="utf-8").splitlines()]
    assert g1["expected_doc_ids"] == ["a1", "a2"]
    assert g1["status"] == g3["status"] == "grounded"
    (n2,) = [json.loads(line) for line in needs.read_text(encoding="utf-8").splitlines()]
    assert n2["status"] == "needs_docs"
    assert n2["suggested_departments"] == ["nic.sufe.edu.cn"]
    assert "语料缺口" in n2["missing_reason"]
