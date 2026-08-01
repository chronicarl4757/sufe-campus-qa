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


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["doc_count"] == 1
    assert m["categories"] == ["学工事务"]
    assert m["updated_at"]
    assert len(m["examples"]) >= 4


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
