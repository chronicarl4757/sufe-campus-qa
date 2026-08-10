from __future__ import annotations

import json
from dataclasses import replace

import pytest

from sufe_qa.config import load_settings
from sufe_qa.coverage.answer_benchmark import (
    ResumeMismatchError,
    generate_real_answer,
    run_answer_benchmark,
)
from sufe_qa.coverage.question_bank import QuestionBank, QuestionProbe
from sufe_qa.retrieve.retriever import Hit


def _probe(qid: str = "jwc-leave-001", question: str = "如何申请缓考？") -> QuestionProbe:
    return QuestionProbe(
        id=qid,
        question=question,
        scene="本科教务",
        required_source_type="official_procedure",
        expected_domains=("jwc.sufe.edu.cn",),
        expected_doc_ids=(),
        required_answer_points=("申请条件", "办理流程"),
        needs_current_version=True,
    )


def _hit(similarity: float = 0.91) -> Hit:
    return Hit(
        chunk_id="doc-1::0000",
        doc_id="doc-1",
        title="缓考办理办法",
        category="本科教务",
        source_url="https://jwc.sufe.edu.cn/page.htm",
        publisher="上海财经大学教务处",
        heading_path="第二章 缓考",
        text="学生因病不能参加考试，应在考试前提交申请表和医院证明，报教务处审批。",
        rrf_score=0.032,
        vector_similarity=similarity,
        publish_date="2026-04-01",
        document_kind="procedure",
        source_type="official_department",
        validity_status="current",
        index_collection="sufe_qa_main_v2",
    )


class _Retriever:
    def __init__(self, hits: list[Hit]):
        self.hits = hits
        self.questions: list[str] = []

    def search_routed(self, question: str) -> list[Hit]:
        self.questions.append(question)
        return self.hits


class _TextLLM:
    def __init__(self, text: str):
        self.text = text

    def stream_chat(self, messages):
        yield self.text


class _BoomLLM:
    def stream_chat(self, messages):
        raise RuntimeError("provider unavailable")
        yield  # pragma: no cover


def test_generate_real_answer_saves_answer_citation_and_actual_chunk(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    settings = load_settings()
    result = generate_real_answer(
        _probe(),
        settings,
        _Retriever([_hit()]),
        lambda: _TextLLM("申请人须在考试前提交申请表和医院证明，并报教务处审批[1]。"),
    )

    assert result.status == "answered"
    assert result.refused is False
    assert result.citation_check == {
        "ok": True,
        "has_citation": True,
        "invalid_refs": [],
    }
    assert result.hits[0].prompt_index == 1
    assert result.hits[0].chunk_id == "doc-1::0000"
    assert "医院证明" in result.hits[0].text
    assert result.matched_domains == ("jwc.sufe.edu.cn",)
    assert result.domain_match is True


def test_generate_real_answer_marks_missing_citations(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    settings = load_settings()
    result = generate_real_answer(
        _probe(),
        settings,
        _Retriever([_hit()]),
        lambda: _TextLLM("请在考试前提交申请。"),
    )
    assert result.status == "answered_with_citation_issue"
    assert result.citation_check["ok"] is False


def test_generate_real_answer_preserves_gate_refusal_without_calling_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    settings = load_settings()

    def forbidden_llm():
        raise AssertionError("门控拒答不应调用 LLM")

    result = generate_real_answer(
        _probe(), settings, _Retriever([_hit(similarity=0.2)]), forbidden_llm
    )
    assert result.status == "refused"
    assert result.refused is True
    assert "未在已收录" in result.answer_text
    assert result.citation_check is None


def test_generate_real_answer_captures_provider_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    settings = load_settings()
    result = generate_real_answer(
        _probe(), settings, _Retriever([_hit()]), lambda: _BoomLLM()
    )
    assert result.status == "error"
    assert result.answer_text == ""
    assert "provider unavailable" in result.error


def test_answer_benchmark_writes_counts_and_resumes_compatible_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    settings = replace(load_settings(), llm_model="test-real-model")
    bank = QuestionBank(
        (_probe("q-1", "问题一"), _probe("q-2", "问题二")),
        content_hash="sha256:bank",
    )
    retriever = _Retriever([_hit()])
    output = tmp_path / "real_answers.json"

    report = run_answer_benchmark(
        bank,
        settings,
        retriever,
        lambda: _TextLLM("真实回答[1]"),
        output_path=output,
        index_metadata={
            "index_fingerprint": "sha256:index-a",
            "embedding_model": "BAAI/bge-m3",
            "embedding_backend": "sentence-transformers",
            "test_only": False,
        },
        workers=2,
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert report.total == 2
    assert report.status_counts == {"answered": 2}
    assert persisted["status_counts"] == {"answered": 2}
    assert [row["id"] for row in persisted["results"]] == ["q-1", "q-2"]

    resumed = run_answer_benchmark(
        bank,
        settings,
        _Retriever([]),
        lambda: _TextLLM("不应再次生成"),
        output_path=output,
        index_metadata={
            "index_fingerprint": "sha256:index-a",
            "embedding_model": "BAAI/bge-m3",
            "embedding_backend": "sentence-transformers",
            "test_only": False,
        },
        workers=1,
        resume=True,
    )
    assert resumed.status_counts == {"answered": 2}


def test_answer_benchmark_rejects_resume_from_different_index(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    settings = replace(load_settings(), llm_model="test-real-model")
    bank = QuestionBank((_probe(),), content_hash="sha256:bank")
    output = tmp_path / "real_answers.json"
    first_meta = {
        "index_fingerprint": "sha256:index-a",
        "embedding_model": "BAAI/bge-m3",
        "embedding_backend": "sentence-transformers",
        "test_only": False,
    }
    run_answer_benchmark(
        bank,
        settings,
        _Retriever([_hit()]),
        lambda: _TextLLM("真实回答[1]"),
        output_path=output,
        index_metadata=first_meta,
    )
    with pytest.raises(ResumeMismatchError, match="index_fingerprint"):
        run_answer_benchmark(
            bank,
            settings,
            _Retriever([_hit()]),
            lambda: _TextLLM("真实回答[1]"),
            output_path=output,
            index_metadata={**first_meta, "index_fingerprint": "sha256:index-b"},
            resume=True,
        )
