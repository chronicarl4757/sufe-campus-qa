"""Web 接口测试：TestClient + Fake 组件，全程离线。"""

from __future__ import annotations

import json

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
