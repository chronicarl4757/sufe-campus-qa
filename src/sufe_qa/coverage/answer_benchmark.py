"""固定问题库的真实问答快照：生产检索、生产 prompt、真实 LLM 与引用校验。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sufe_qa.config import Settings
from sufe_qa.coverage.question_bank import QuestionBank, QuestionProbe
from sufe_qa.generate.answer import REFUSAL_TEMPLATE, validate_citations
from sufe_qa.generate.client import LLMClient
from sufe_qa.generate.prompt import SYSTEM_PROMPT, build_messages
from sufe_qa.retrieve.retriever import Hit, HybridRetriever, is_confident

SCHEMA_VERSION = "1"
REAL_ANSWER_STATUSES = frozenset(
    {"answered", "answered_with_citation_issue", "refused", "error"}
)


class ResumeMismatchError(ValueError):
    """续跑快照和当前题库、索引、模型或 prompt 不兼容。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_prompt_hash() -> str:
    return "sha256:" + hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RealAnswerHit:
    prompt_index: int
    chunk_id: str
    doc_id: str
    title: str
    parent_title: str
    publisher: str
    source_url: str
    publish_date: str
    document_kind: str
    source_type: str
    validity_status: str
    index_collection: str
    heading_path: str
    vector_similarity: float | None
    rrf_score: float
    text: str

    @classmethod
    def from_hit(cls, hit: Hit, prompt_index: int) -> RealAnswerHit:
        return cls(
            prompt_index=prompt_index,
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            title=hit.title,
            parent_title=hit.parent_title,
            publisher=hit.publisher,
            source_url=hit.source_url,
            publish_date=hit.publish_date,
            document_kind=hit.document_kind,
            source_type=hit.source_type,
            validity_status=hit.validity_status,
            index_collection=hit.index_collection,
            heading_path=hit.heading_path,
            vector_similarity=hit.vector_similarity,
            rrf_score=hit.rrf_score,
            text=hit.text,
        )


@dataclass(frozen=True)
class RealAnswerResult:
    id: str
    question: str
    scene: str
    status: str
    answer_text: str
    refused: bool
    citation_check: dict | None
    expected_domains: tuple[str, ...]
    required_answer_points: tuple[str, ...]
    matched_domains: tuple[str, ...]
    domain_match: bool
    hits: tuple[RealAnswerHit, ...]
    generated_at: str
    latency_ms: float
    error: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> RealAnswerResult:
        return cls(
            id=str(data["id"]),
            question=str(data["question"]),
            scene=str(data["scene"]),
            status=str(data["status"]),
            answer_text=str(data.get("answer_text", "")),
            refused=bool(data.get("refused", False)),
            citation_check=data.get("citation_check"),
            expected_domains=tuple(data.get("expected_domains") or ()),
            required_answer_points=tuple(data.get("required_answer_points") or ()),
            matched_domains=tuple(data.get("matched_domains") or ()),
            domain_match=bool(data.get("domain_match", False)),
            hits=tuple(RealAnswerHit(**hit) for hit in data.get("hits") or ()),
            generated_at=str(data.get("generated_at", "")),
            latency_ms=float(data.get("latency_ms", 0.0)),
            error=str(data.get("error", "")),
        )


@dataclass(frozen=True)
class RealAnswerReport:
    schema_version: str
    run_id: str
    question_bank_version: str
    question_bank_hash: str
    index_fingerprint: str
    embedding_model: str
    embedding_backend: str
    embedding_test_only: bool
    llm_model: str
    prompt_hash: str
    started_at: str
    completed_at: str | None
    total: int
    results: tuple[RealAnswerResult, ...]

    @property
    def status_counts(self) -> dict[str, int]:
        counts = Counter(result.status for result in self.results)
        return {status: counts[status] for status in sorted(counts) if counts[status]}

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status_counts"] = self.status_counts
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def load_index_metadata(settings: Settings) -> dict:
    path = settings.chroma_dir / "index_metadata.json"
    if not path.is_file():
        raise FileNotFoundError(f"索引元数据不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"索引元数据无法解析: {path}") from exc
    if not isinstance(data, dict) or not data.get("index_fingerprint"):
        raise ValueError(f"索引元数据结构无效: {path}")
    return data


def _domains(hits: list[Hit]) -> tuple[str, ...]:
    return tuple(sorted({urlparse(hit.source_url).netloc.lower() for hit in hits if hit.source_url}))


def _snapshots(hits: list[Hit]) -> tuple[RealAnswerHit, ...]:
    return tuple(RealAnswerHit.from_hit(hit, index) for index, hit in enumerate(hits, 1))


def _is_model_evidence_refusal(answer_text: str) -> bool:
    """识别模型基于证据不足作出的自然语言拒答，避免误报为引用异常。"""
    first_paragraph = re.split(r"\n\s*\n", answer_text.strip(), maxsplit=1)[0]
    first_sentence = first_paragraph.split("。", 1)[0]
    evidence_context = any(word in first_sentence for word in ("资料", "依据", "文档", "来源"))
    missing_evidence = any(
        phrase in first_sentence
        for phrase in ("未提及", "未明确提及", "未找到", "没有找到", "无法确定", "无法从")
    )
    return evidence_context and missing_evidence


def _base_result(
    probe: QuestionProbe,
    *,
    status: str,
    answer_text: str,
    refused: bool,
    citation_check: dict | None,
    hits: list[Hit],
    started: float,
    error: str = "",
) -> RealAnswerResult:
    matched_domains = _domains(hits)
    expected = {domain.lower() for domain in probe.expected_domains}
    return RealAnswerResult(
        id=probe.id,
        question=probe.question,
        scene=probe.scene,
        status=status,
        answer_text=answer_text,
        refused=refused,
        citation_check=citation_check,
        expected_domains=probe.expected_domains,
        required_answer_points=probe.required_answer_points,
        matched_domains=matched_domains,
        domain_match=bool(expected & set(matched_domains)),
        hits=_snapshots(hits),
        generated_at=_now(),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        error=error,
    )


def _generate_from_hits(
    probe: QuestionProbe,
    hits: list[Hit],
    llm_factory: Callable[[], LLMClient],
    started: float,
) -> RealAnswerResult:
    try:
        answer_text = "".join(llm_factory().stream_chat(build_messages(probe.question, hits))).strip()
        if not answer_text:
            return _base_result(
                probe,
                status="error",
                answer_text="",
                refused=False,
                citation_check=None,
                hits=hits,
                started=started,
                error="模型返回空答案",
            )
        check = validate_citations(answer_text, len(hits))
        check_dict = {
            "ok": check.ok,
            "has_citation": check.has_citation,
            "invalid_refs": check.invalid_refs,
        }
        if _is_model_evidence_refusal(answer_text):
            return _base_result(
                probe,
                status="refused",
                answer_text=answer_text,
                refused=True,
                citation_check=None,
                hits=hits,
                started=started,
            )
        return _base_result(
            probe,
            status="answered" if check.ok else "answered_with_citation_issue",
            answer_text=answer_text,
            refused=False,
            citation_check=check_dict,
            hits=hits,
            started=started,
        )
    except Exception as exc:  # provider/网络/流式中断都必须成为逐题显式结果
        return _base_result(
            probe,
            status="error",
            answer_text="",
            refused=False,
            citation_check=None,
            hits=hits,
            started=started,
            error=f"{type(exc).__name__}: {exc}",
        )


def generate_real_answer(
    probe: QuestionProbe,
    settings: Settings,
    retriever: HybridRetriever,
    llm_factory: Callable[[], LLMClient],
) -> RealAnswerResult:
    started = time.perf_counter()
    try:
        hits = retriever.search_routed(probe.question)
    except Exception as exc:
        return _base_result(
            probe,
            status="error",
            answer_text="",
            refused=False,
            citation_check=None,
            hits=[],
            started=started,
            error=f"{type(exc).__name__}: {exc}",
        )
    if not hits or not is_confident(hits, settings.vector_min_similarity):
        return _base_result(
            probe,
            status="refused",
            answer_text=REFUSAL_TEMPLATE,
            refused=True,
            citation_check=None,
            hits=hits,
            started=started,
        )
    return _generate_from_hits(probe, hits, llm_factory, started)


def _report(
    bank: QuestionBank,
    settings: Settings,
    index_metadata: dict,
    *,
    run_id: str,
    started_at: str,
    results: dict[str, RealAnswerResult],
) -> RealAnswerReport:
    ordered = tuple(results[item.id] for item in bank if item.id in results)
    complete = len(ordered) == len(bank)
    return RealAnswerReport(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        question_bank_version=bank.version,
        question_bank_hash=bank.content_hash,
        index_fingerprint=str(index_metadata.get("index_fingerprint", "")),
        embedding_model=str(index_metadata.get("embedding_model", settings.embedding_model)),
        embedding_backend=str(index_metadata.get("embedding_backend", "unknown")),
        embedding_test_only=bool(index_metadata.get("test_only", False)),
        llm_model=settings.llm_model,
        prompt_hash=current_prompt_hash(),
        started_at=started_at,
        completed_at=_now() if complete else None,
        total=len(bank),
        results=ordered,
    )


def _atomic_write(report: RealAnswerReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(report.to_json(), encoding="utf-8")
    os.replace(tmp, path)


def _load_resume(path: Path) -> tuple[dict, dict[str, RealAnswerResult]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResumeMismatchError("现有答案快照无法解析") from exc
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ResumeMismatchError("现有答案快照结构无效")
    results: dict[str, RealAnswerResult] = {}
    for row in rows:
        result = RealAnswerResult.from_dict(row)
        if result.status not in REAL_ANSWER_STATUSES or result.id in results:
            raise ResumeMismatchError("现有答案快照含非法状态或重复 id")
        results[result.id] = result
    return data, results


def _validate_resume(existing: dict, current: RealAnswerReport) -> None:
    fields = (
        "schema_version",
        "question_bank_version",
        "question_bank_hash",
        "index_fingerprint",
        "embedding_model",
        "llm_model",
        "prompt_hash",
        "total",
    )
    for field in fields:
        if existing.get(field) != getattr(current, field):
            raise ResumeMismatchError(f"续跑元数据不一致: {field}")


def run_answer_benchmark(
    bank: QuestionBank,
    settings: Settings,
    retriever: HybridRetriever,
    llm_factory: Callable[[], LLMClient],
    *,
    output_path: Path,
    index_metadata: dict,
    workers: int = 4,
    resume: bool = False,
    max_items: int = 0,
    retry_errors: bool = True,
    progress: Callable[[RealAnswerResult, int, int], None] | None = None,
) -> RealAnswerReport:
    if workers < 1:
        raise ValueError("workers 必须至少为 1")
    run_id = uuid.uuid4().hex
    started_at = _now()
    results: dict[str, RealAnswerResult] = {}
    if resume and output_path.is_file():
        existing, results = _load_resume(output_path)
        run_id = str(existing.get("run_id") or run_id)
        started_at = str(existing.get("started_at") or started_at)
        current = _report(
            bank,
            settings,
            index_metadata,
            run_id=run_id,
            started_at=started_at,
            results=results,
        )
        _validate_resume(existing, current)

    pending = [
        probe
        for probe in bank
        if probe.id not in results or (retry_errors and results[probe.id].status == "error")
    ]
    if max_items > 0:
        pending = pending[:max_items]

    def save(result: RealAnswerResult) -> None:
        results[result.id] = result
        report = _report(
            bank,
            settings,
            index_metadata,
            run_id=run_id,
            started_at=started_at,
            results=results,
        )
        _atomic_write(report, output_path)
        if progress is not None:
            progress(result, len(results), len(bank))

    futures: dict[Future[RealAnswerResult], QuestionProbe] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for probe in pending:
            started = time.perf_counter()
            try:
                hits = retriever.search_routed(probe.question)
            except Exception as exc:
                save(
                    _base_result(
                        probe,
                        status="error",
                        answer_text="",
                        refused=False,
                        citation_check=None,
                        hits=[],
                        started=started,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if not hits or not is_confident(hits, settings.vector_min_similarity):
                save(
                    _base_result(
                        probe,
                        status="refused",
                        answer_text=REFUSAL_TEMPLATE,
                        refused=True,
                        citation_check=None,
                        hits=hits,
                        started=started,
                    )
                )
                continue
            future = executor.submit(_generate_from_hits, probe, hits, llm_factory, started)
            futures[future] = probe
        for future in as_completed(futures):
            save(future.result())

    final = _report(
        bank,
        settings,
        index_metadata,
        run_id=run_id,
        started_at=started_at,
        results=results,
    )
    _atomic_write(final, output_path)
    return final
