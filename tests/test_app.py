"""Web 接口测试：TestClient + Fake 组件，全程离线。"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from sufe_qa.app.server import create_app
from sufe_qa.config import load_settings
from sufe_qa.generate.client import FakeLLM
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
from sufe_qa.ingest.inbox import ingest_inbox
from sufe_qa.retrieve.retriever import HybridRetriever

DOC = (
    "# 推免工作实施办法\n\n第一条 申请推免的学生应为纳入国家普通本科招生计划录取的应届毕业生，"
    "拥护中国共产党的领导，品德良好，遵纪守法，身心健康。"
) * 2
QUESTION = DOC[12:112]  # 正文子串提问，FakeEmbedder 下保证过置信门控

COVERAGE_REPORT = {
    "question_bank_version": "sufe-question-bank.v1",
    "question_bank_hash": "sha256:bank",
    "index_fingerprint": "sha256:index",
    "evaluated_at": "2026-08-10T13:10:28+00:00",
    "retriever_config": {"similarity_threshold": 0.5},
    "scene_stats": {
        "本科教务": {
            "question_count": 1,
            "answerable_question_count": 1,
            "partially_answerable_question_count": 0,
            "unanswerable_question_count": 0,
        }
    },
    "question_results": [
        {
            "id": "jwc-leave-001",
            "question": "本科生如何申请缓考？",
            "scene": "本科教务",
            "status": "answerable",
            "retrieved_doc_ids": ["doc-1"],
            "titles": ["缓考办理办法"],
            "publishers": ["上海财经大学教务处"],
            "publish_dates": ["2026-01-01"],
            "document_kinds": ["procedure"],
            "validity_statuses": ["current"],
            "has_attachment": True,
            "matched_domains": ["jwc.sufe.edu.cn"],
            "point_evidence": [],
            "missing_reasons": [],
        }
    ],
}

REAL_ANSWER_REPORT = {
    "schema_version": "1",
    "run_id": "run-test",
    "question_bank_version": "sufe-question-bank.v1",
    "question_bank_hash": "sha256:bank",
    "index_fingerprint": "sha256:index",
    "embedding_model": "BAAI/bge-m3",
    "embedding_backend": "sentence-transformers",
    "embedding_test_only": False,
    "llm_model": "deepseek-test",
    "prompt_hash": "sha256:prompt",
    "started_at": "2026-08-10T13:00:00+00:00",
    "completed_at": "2026-08-10T13:01:00+00:00",
    "total": 1,
    "status_counts": {"answered": 1},
    "results": [
        {
            "id": "jwc-leave-001",
            "question": "本科生如何申请缓考？",
            "scene": "本科教务",
            "status": "answered",
            "answer_text": "请在考试前提交申请和医院证明[1]。",
            "refused": False,
            "citation_check": {"ok": True, "has_citation": True, "invalid_refs": []},
            "expected_domains": ["jwc.sufe.edu.cn"],
            "required_answer_points": ["申请条件"],
            "matched_domains": ["jwc.sufe.edu.cn"],
            "domain_match": True,
            "hits": [
                {
                    "prompt_index": 1,
                    "chunk_id": "doc-1::0000",
                    "doc_id": "doc-1",
                    "title": "缓考办理办法",
                    "parent_title": "",
                    "publisher": "上海财经大学教务处",
                    "source_url": "https://jwc.sufe.edu.cn/page.htm",
                    "publish_date": "2026-04-01",
                    "document_kind": "procedure",
                    "source_type": "official_department",
                    "validity_status": "current",
                    "index_collection": "sufe_qa_main_v2",
                    "heading_path": "缓考",
                    "vector_similarity": 0.91,
                    "rrf_score": 0.032,
                    "text": "因病不能考试的学生应提交申请和医院证明。",
                }
            ],
            "generated_at": "2026-08-10T13:00:30+00:00",
            "latency_ms": 1234.5,
            "error": "",
        }
    ],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    settings = load_settings()
    (settings.inbox_dir / "tuimian.md").write_text(DOC, encoding="utf-8")
    ingest_inbox(
        settings.inbox_dir, settings.corpus_dir, settings.manifest_path, "学工事务", "研究生院"
    )
    update_index(settings, FakeEmbedder())
    app = create_app(
        settings,
        retriever=HybridRetriever(settings, FakeEmbedder()),
        llm=FakeLLM(1),
    )
    return TestClient(app)


def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "上财校务问答" in r.text


def test_coverage_page_served(client):
    response = client.get("/coverage")
    assert response.status_code == 200
    assert "150 问覆盖质检" in response.text
    assert 'id="evidence-matrix"' in response.text
    assert 'id="question-drawer"' in response.text
    assert 'src="/static/coverage.js"' in response.text


def test_index_links_to_coverage_dashboard(client):
    response = client.get("/")
    assert 'href="/coverage"' in response.text
    assert "覆盖质检" in response.text


def test_coverage_static_assets_define_audit_behaviors(client):
    script = client.get("/static/coverage.js")
    styles = client.get("/static/coverage.css")
    assert script.status_code == styles.status_code == 200
    for token in (
        "loadCoverage",
        "renderSummary",
        "renderScenes",
        "renderMatrix",
        "renderQuestionList",
        "openQuestion",
        "applyFilters",
        "point_evidence",
        "retrieved_doc_ids",
    ):
        assert token in script.text
    for selector in (
        ".evidence-matrix",
        ".matrix-cell",
        ".scene-bar",
        ".question-drawer",
        "@media (max-width: 720px)",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert selector in styles.text


def test_coverage_visual_contract_avoids_template_effects(client):
    coverage_styles = client.get("/static/coverage.css").text
    app_styles = client.get("/static/styles.css").text
    assert "linear-gradient" not in coverage_styles
    assert ".audit-link" in app_styles


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["doc_count"] == 1
    assert m["categories"] == ["学工事务"]
    assert m["updated_at"]
    assert len(m["examples"]) >= 4


def _write_coverage_report(tmp_path, report=COVERAGE_REPORT):
    path = tmp_path / "coverage" / "sufe_coverage_after.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _write_real_answer_report(tmp_path, report=REAL_ANSWER_REPORT):
    path = tmp_path / "coverage" / "sufe_real_answers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def test_coverage_api_returns_current_report(client, tmp_path):
    _write_coverage_report(tmp_path)
    response = client.get("/api/coverage")
    assert response.status_code == 200
    assert response.json()["question_results"][0]["id"] == "jwc-leave-001"
    assert response.json()["question_results"][0]["real_answer"] is None
    assert response.json()["answer_run"] == {"available": False}
    assert response.headers["cache-control"] == "no-store"


def test_coverage_api_merges_compatible_real_answers(client, tmp_path):
    _write_coverage_report(tmp_path)
    _write_real_answer_report(tmp_path)
    payload = client.get("/api/coverage").json()
    assert payload["answer_run"]["available"] is True
    assert payload["answer_run"]["llm_model"] == "deepseek-test"
    answer = payload["question_results"][0]["real_answer"]
    assert answer["status"] == "answered"
    assert "医院证明[1]" in answer["answer_text"]
    assert answer["hits"][0]["chunk_id"] == "doc-1::0000"


def test_coverage_api_rejects_malformed_real_answer_report(client, tmp_path):
    _write_coverage_report(tmp_path)
    path = tmp_path / "coverage" / "sufe_real_answers.json"
    path.write_text("{broken", encoding="utf-8")
    response = client.get("/api/coverage")
    assert response.status_code == 500
    assert response.json()["detail"] == "真实答案报告无法解析"


def test_coverage_api_rejects_duplicate_real_answer_ids(client, tmp_path):
    _write_coverage_report(tmp_path)
    report = json.loads(json.dumps(REAL_ANSWER_REPORT))
    report["results"].append(report["results"][0])
    _write_real_answer_report(tmp_path, report)
    response = client.get("/api/coverage")
    assert response.status_code == 500
    assert response.json()["detail"] == "真实答案报告结构无效"


def test_coverage_api_rejects_answer_snapshot_from_other_index(client, tmp_path):
    _write_coverage_report(tmp_path)
    report = {**REAL_ANSWER_REPORT, "index_fingerprint": "sha256:other"}
    _write_real_answer_report(tmp_path, report)
    response = client.get("/api/coverage")
    assert response.status_code == 409
    assert response.json()["detail"] == "真实答案报告与覆盖题库或索引不兼容"


def test_coverage_api_reports_missing_file(client):
    response = client.get("/api/coverage")
    assert response.status_code == 404
    assert response.json()["detail"] == "覆盖评测报告不存在"


def test_coverage_api_rejects_malformed_json(client, tmp_path):
    path = tmp_path / "coverage" / "sufe_coverage_after.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    response = client.get("/api/coverage")
    assert response.status_code == 500
    assert response.json()["detail"] == "覆盖评测报告无法解析"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.pop("scene_stats"),
        lambda report: report["question_results"][0].pop("question"),
        lambda report: report["question_results"][0].update(status="invented"),
    ],
)
def test_coverage_api_rejects_invalid_schema(client, tmp_path, mutation):
    report = json.loads(json.dumps(COVERAGE_REPORT))
    mutation(report)
    _write_coverage_report(tmp_path, report)
    response = client.get("/api/coverage")
    assert response.status_code == 500
    assert response.json()["detail"] == "覆盖评测报告结构无效"


def _events(text: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for block in text.strip().split("\n\n"):
        event = data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if event and data:
            out.setdefault(event, []).append(json.loads(data))
    return out


def test_ask_streams_answer_and_sources(client):
    r = client.post("/api/ask", json={"question": QUESTION})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    ev = _events(r.text)
    assert ev["meta"][0]["refused"] is False
    assert ev["meta"][0]["doc_no"].startswith("校务答字〔")
    assert ev["meta"][0]["retrieval_ms"] >= 0
    assert ev["token"], "应有流式 token"
    cards = ev["sources"][0]["cards"]
    assert cards and "推免工作实施办法" in cards[0]["title"]
    assert ev["done"][0]["total_ms"] >= 0


def test_ask_refusal_has_no_sources(client):
    r = client.post("/api/ask", json={"question": "qwerty asdfg zxcvb"})
    ev = _events(r.text)
    assert ev["meta"][0]["refused"] is True
    assert "未在已收录" in "".join(t["text"] for t in ev["token"])
    assert ev["sources"][0]["cards"] == []


def test_ask_empty_question_returns_error_event(client):
    r = client.post("/api/ask", json={"question": "  "})
    assert "event: error" in r.text


def test_feedback_appends_jsonl(client, tmp_path, monkeypatch):
    r = client.post(
        "/api/feedback",
        json={"question": "q", "answer": "a", "rating": "up"},
    )
    assert r.json() == {"ok": True}
    line = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["rating"] == "up" and rec["question"] == "q"
    assert (
        client.post("/api/feedback", json={"question": "q", "answer": "a", "rating": "meh"}).json()[
            "ok"
        ]
        is False
    )


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    """可定制 settings 与 LLM 的 app 工厂。"""

    def make(llm=None, **over):
        monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
        settings = replace(load_settings(), **over)
        (settings.inbox_dir / "tuimian.md").write_text(DOC, encoding="utf-8")
        ingest_inbox(
            settings.inbox_dir, settings.corpus_dir, settings.manifest_path, "学工事务", "研究生院"
        )
        update_index(settings, FakeEmbedder())
        app = create_app(
            settings,
            retriever=HybridRetriever(settings, FakeEmbedder()),
            llm=llm or FakeLLM(1),
        )
        return TestClient(app)

    return make


class _BoomStreamLLM:
    """流中途抛错，模拟 DeepSeek 连接中断。"""

    def stream_chat(self, messages):
        yield "前半段"
        raise RuntimeError("模拟断流")


def test_ask_overlong_question_rejected(client):
    r = client.post("/api/ask", json={"question": "长" * 600})
    assert "问题过长" in r.text  # 业务上限 500 字，走 SSE error
    r2 = client.post("/api/ask", json={"question": "长" * 2100})
    assert r2.status_code == 422  # 传输层硬上限，直接 422


def test_ask_rate_limited(client_factory):
    client = client_factory(rate_limit_per_minute=2)
    for _ in range(2):
        assert "event: meta" in client.post("/api/ask", json={"question": QUESTION}).text
    r = client.post("/api/ask", json={"question": QUESTION})
    assert "请求过于频繁" in r.text


def test_ask_concurrency_gate(client_factory):
    client = client_factory(max_concurrent_llm=1)
    assert client.app.state.llm_sem.acquire(blocking=False)  # 占住唯一的并发位
    try:
        r = client.post("/api/ask", json={"question": QUESTION})
        assert "当前咨询人数较多" in r.text
    finally:
        client.app.state.llm_sem.release()
    r = client.post("/api/ask", json={"question": QUESTION})
    assert "event: done" in r.text  # 释放后恢复


def test_ask_stream_break_emits_error_event(client_factory):
    client = client_factory(llm=_BoomStreamLLM())
    ev = _events(client.post("/api/ask", json={"question": QUESTION}).text)
    assert ev["token"][0]["text"] == "前半段"
    assert "模拟断流" in ev["error"][0]["message"]
    assert "done" not in ev
    # 并发闸在 finally 释放：后续请求不被卡死
    assert "event: meta" in client.post("/api/ask", json={"question": QUESTION}).text


def test_ask_sources_carry_citation_check(client):
    ev = _events(client.post("/api/ask", json={"question": QUESTION}).text)
    assert ev["sources"][0]["citation_check"]["ok"] is True


def test_ask_invalid_citation_flagged(client_factory):
    class BadCiteLLM:
        def stream_chat(self, messages):
            yield "依据资料[1]与[99]，结论成立。"

    client = client_factory(llm=BadCiteLLM())
    ev = _events(client.post("/api/ask", json={"question": QUESTION}).text)
    check = ev["sources"][0]["citation_check"]
    assert check["ok"] is False and check["invalid_refs"] == [99]


def test_ask_refusal_citation_check_skipped(client):
    ev = _events(client.post("/api/ask", json={"question": "qwerty asdfg zxcvb"}).text)
    assert ev["sources"][0]["citation_check"] is None


def test_feedback_question_truncated(client, tmp_path):
    r = client.post("/api/feedback", json={"question": "问" * 900, "answer": "a", "rating": "up"})
    assert r.json() == {"ok": True}
    line = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    assert len(json.loads(line)["question"]) == 500
