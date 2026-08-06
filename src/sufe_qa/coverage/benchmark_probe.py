"""用户真实问题 benchmark 的检索级探针。

与 coverage/audit.py 的语料字面匹配不同，这里走真实检索链路
（HybridRetriever.search_routed + 置信门控），判断每道题在**当前索引**下
是否能命中正确职能部门的资料、要点是否齐备。

判级规则（普通题）：
- not_answerable：未过置信门（语料缺口）；
- answerable：过门且全部回答要点有证据，且命中域名符合期望（若声明）；
- partially_answerable：其余过门情形（要点不全或域名偏离）。

特殊题型：
- should_refuse：检索级只能判定「门控是否已拦下」。过门的标记为
  generation_check_required —— 拒答责任在生成层，需生成级抽查确认。
- needs_clarification：判 clarification_check_required，不计入可答率分母。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sufe_qa.config import Settings
from sufe_qa.coverage.audit import _point_supported
from sufe_qa.retrieve.retriever import Hit, HybridRetriever, is_confident

ANSWERABLE_KINDS = {
    "policy",
    "procedure",
    "faq",
    "annual_notice",
    "form",
    "manual",
    "service_guide",
}
TOP_EVIDENCE_N = 5


@dataclass(frozen=True)
class BenchmarkItem:
    id: str
    question: str
    scene: str
    question_type: str = "direct_fact"
    expected_domains: tuple[str, ...] = ()
    expected_answer_points: tuple[str, ...] = ()
    should_refuse: bool = False
    needs_clarification: bool = False
    valid_for_year: int = 0


@dataclass(frozen=True)
class HitEvidence:
    doc_id: str
    title: str
    publisher: str
    publish_date: str
    document_kind: str
    validity_status: str
    similarity: float | None
    domain: str
    via_attachment: bool


@dataclass(frozen=True)
class BenchmarkResult:
    id: str
    question: str
    scene: str
    question_type: str
    status: str
    refused_by_gate: bool
    supported_points: tuple[str, ...] = ()
    unsupported_points: tuple[str, ...] = ()
    matched_domains: tuple[str, ...] = ()
    missing_reasons: tuple[str, ...] = ()
    top_hits: tuple[HitEvidence, ...] = ()


@dataclass(frozen=True)
class BenchmarkReport:
    bank_path: str
    bank_hash: str
    evaluated_at: str
    similarity_threshold: float
    total: int
    scored: int  # 计入可答率的普通题数
    answerable: int
    answerable_offdomain: int
    partially_answerable: int
    not_answerable: int
    refusal_gate_refused: int
    refusal_generation_required: int
    clarification_required: int
    by_scene: dict[str, dict[str, int]]
    results: tuple[BenchmarkResult, ...]
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def load_benchmark(path: Path) -> list[BenchmarkItem]:
    items: list[BenchmarkItem] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - 配置错误
            raise ValueError(f"{path}:{lineno} 不是合法 JSON：{exc}") from exc
        items.append(
            BenchmarkItem(
                id=str(d["id"]),
                question=str(d["question"]),
                scene=str(d.get("scene", "")),
                question_type=str(d.get("question_type", "direct_fact")),
                expected_domains=tuple(d.get("expected_domains") or ()),
                expected_answer_points=tuple(d.get("expected_answer_points") or ()),
                should_refuse=bool(d.get("should_refuse", False)),
                needs_clarification=bool(d.get("needs_clarification", False)),
                valid_for_year=int(d.get("valid_for_year", 0) or 0),
            )
        )
    return items


def _domain_of(hit: Hit) -> str:
    return urlparse(hit.source_url).netloc.lower()


def _evidence(hits: list[Hit]) -> tuple[HitEvidence, ...]:
    seen: set[str] = set()
    out: list[HitEvidence] = []
    for h in hits:
        key = h.doc_id
        if key in seen:
            continue
        seen.add(key)
        out.append(
            HitEvidence(
                doc_id=h.doc_id,
                title=h.parent_title or h.title,
                publisher=h.publisher,
                publish_date=h.publish_date,
                document_kind=h.document_kind,
                validity_status=h.validity_status,
                similarity=h.vector_similarity,
                domain=_domain_of(h),
                via_attachment=bool(h.parent_doc_id),
            )
        )
        if len(out) >= 3:
            break
    return tuple(out)


def evaluate_item(item: BenchmarkItem, hits: list[Hit], min_similarity: float) -> BenchmarkResult:
    confident = is_confident(hits, min_similarity)
    base = dict(
        id=item.id,
        question=item.question,
        scene=item.scene,
        question_type=item.question_type,
        refused_by_gate=not confident,
        top_hits=_evidence(hits),
    )
    if item.should_refuse:
        return BenchmarkResult(
            status="gate_refused" if not confident else "generation_check_required",
            missing_reasons=() if not confident else ("通过门控，拒答需生成层确认",),
            **base,
        )
    if item.needs_clarification:
        return BenchmarkResult(
            status="clarification_check_required",
            missing_reasons=("信息不足题型，需生成层确认追问行为",),
            **base,
        )

    expected_domains = {d.lower() for d in item.expected_domains}
    hit_domains = {_domain_of(h) for h in hits[:TOP_EVIDENCE_N] if h.source_url}
    matched = tuple(sorted(expected_domains & hit_domains))
    corpus_text = re.sub(r"\s+", "", "\n".join(h.text for h in hits[:TOP_EVIDENCE_N])).lower()
    supported = tuple(p for p in item.expected_answer_points if _point_supported(corpus_text, p))
    unsupported = tuple(p for p in item.expected_answer_points if p not in supported)

    reasons: list[str] = []
    if not confident:
        reasons.append("无高置信检索结果（语料缺口）")
        status = "not_answerable"
    else:
        if unsupported:
            reasons.append("缺回答要点：" + "、".join(unsupported))
        if expected_domains and not matched:
            reasons.append(
                "命中域名偏离期望职能部门：命中 "
                + "、".join(sorted(hit_domains)[:3] or ["（无）"])
                + "，期望 "
                + "、".join(sorted(expected_domains))
            )
        if not unsupported and (not expected_domains or matched):
            status = "answerable"
        elif not unsupported:
            # 要点齐备但域名偏离：多为题库期望域名过窄或跨部门转载，
            # 单独成桶便于人工复核，不与「缺要点」混为一谈。
            status = "answerable_offdomain"
        else:
            status = "partially_answerable"
    return BenchmarkResult(
        status=status,
        supported_points=supported,
        unsupported_points=unsupported,
        matched_domains=matched,
        missing_reasons=tuple(reasons),
        **base,
    )


def run_benchmark(
    settings: Settings, retriever: HybridRetriever, bank_path: Path
) -> BenchmarkReport:
    import hashlib

    items = load_benchmark(bank_path)
    results: list[BenchmarkResult] = []
    for item in items:
        hits = retriever.search_routed(item.question)
        results.append(evaluate_item(item, hits, settings.vector_min_similarity))

    normal = [
        r
        for r in results
        if r.status
        in {"answerable", "answerable_offdomain", "partially_answerable", "not_answerable"}
    ]
    by_scene: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        by_scene[r.scene]["total"] += 1
        by_scene[r.scene][r.status] += 1
    return BenchmarkReport(
        bank_path=str(bank_path),
        bank_hash=hashlib.sha256(bank_path.read_bytes()).hexdigest()[:16],
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        similarity_threshold=settings.vector_min_similarity,
        total=len(results),
        scored=len(normal),
        answerable=sum(1 for r in normal if r.status == "answerable"),
        answerable_offdomain=sum(1 for r in normal if r.status == "answerable_offdomain"),
        partially_answerable=sum(1 for r in normal if r.status == "partially_answerable"),
        not_answerable=sum(1 for r in normal if r.status == "not_answerable"),
        refusal_gate_refused=sum(1 for r in results if r.status == "gate_refused"),
        refusal_generation_required=sum(
            1 for r in results if r.status == "generation_check_required"
        ),
        clarification_required=sum(
            1 for r in results if r.status == "clarification_check_required"
        ),
        by_scene={k: dict(v) for k, v in sorted(by_scene.items())},
        results=tuple(results),
    )
