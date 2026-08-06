"""固定问题分母的语料覆盖审计。

审计默认不依赖 Chroma：它直接读取有效 manifest 和 corpus 正文，因而可以在首次
采集前生成可比较的 baseline。之后可以把同一份题库与索引命中结果注入更严格的
evidence checker；这里的确定性检查始终保留，避免把模型判断当成唯一证据。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sufe_qa.coverage.question_bank import QuestionProbe, load_question_bank
from sufe_qa.ingest.quality import classify_document
from sufe_qa.schema import DocMeta, load_manifest

SCENES = (
    "本科教务",
    "研究生培养与学位",
    "奖助学金",
    "推免与招生",
    "就业手续",
    "宿舍后勤",
    "信息化与校园卡",
    "图书馆",
    "医疗医保",
    "国际交流",
    "新生与安全",
)

_DOMAIN_SCENES = {
    "jwc.sufe.edu.cn": "本科教务",
    "gs.sufe.edu.cn": "研究生培养与学位",
    "career.sufe.edu.cn": "就业手续",
    "nic.sufe.edu.cn": "信息化与校园卡",
    "lib.sufe.edu.cn": "图书馆",
    "yljk.sufe.edu.cn": "医疗医保",
    "ieco.sufe.edu.cn": "国际交流",
    "baoweichu.sufe.edu.cn": "新生与安全",
    "hq.sufe.edu.cn": "宿舍后勤",
    "gongkai.sufe.edu.cn": "宿舍后勤",
}
_XSC_SCHOLARSHIP_TERMS = ("奖学金", "助学金", "困难", "勤工助学", "资助", "学费减免", "贷款")
_XSC_NEW_TERMS = ("入学", "新生", "安全", "违纪", "综合素质", "申诉")
_GS_ADMISSION_TERMS = ("招生", "推免", "硕士", "博士", "直博", "硕博连读", "复试")
_GS_EXCHANGE_TERMS = ("国际", "交流", "留学", "出国", "公派")
_TITLE_ONLY_MAX = 80
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class PointEvidence:
    point: str
    status: str
    evidence_doc_id: str | None = None
    evidence_excerpt: str = ""
    reason: str = ""
    confidence: float = 0.0
    checker: str = "deterministic"


@dataclass(frozen=True)
class QuestionResult:
    id: str
    question: str
    scene: str
    status: str
    retrieved_doc_ids: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()
    publishers: tuple[str, ...] = ()
    publish_dates: tuple[str, ...] = ()
    document_kinds: tuple[str, ...] = ()
    validity_statuses: tuple[str, ...] = ()
    has_attachment: bool = False
    matched_domains: tuple[str, ...] = ()
    point_evidence: tuple[PointEvidence, ...] = ()
    missing_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneStats:
    scene: str
    document_count: int = 0
    valid_policy_documents: int = 0
    valid_procedure_documents: int = 0
    title_only_or_incomplete_documents: int = 0
    news_promotion_documents: int = 0
    latest_valid_version_count: int = 0
    question_count: int = 0
    answerable_question_count: int = 0
    partially_answerable_question_count: int = 0
    unanswerable_question_count: int = 0
    missing_authoritative_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageReport:
    question_bank_version: str
    question_bank_hash: str
    retriever_config: dict
    embedding_model: str
    similarity_threshold: float
    index_fingerprint: str
    evaluated_at: str
    scene_stats: dict[str, SceneStats]
    question_results: tuple[QuestionResult, ...]
    corpus_document_count: int

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


@dataclass(frozen=True)
class _CorpusDoc:
    meta: DocMeta
    body: str
    scene: str
    document_kind: str
    validity_status: str

    @property
    def domain(self) -> str:
        return urlparse(self.meta.source_url).netloc.lower()

    @property
    def accepted(self) -> bool:
        return (self.meta.quality_status or "accepted") == "accepted" and bool(
            self.meta.content_hash and self.meta.file_path
        )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _scene_for(meta: DocMeta, text: str) -> str | None:
    domain = urlparse(meta.source_url).netloc.lower()
    title_body = f"{meta.title}\n{text}"
    if domain == "xsc.sufe.edu.cn":
        if any(term in title_body for term in _XSC_SCHOLARSHIP_TERMS):
            return "奖助学金"
        if any(term in title_body for term in _XSC_NEW_TERMS):
            return "新生与安全"
        return "奖助学金"
    if domain == "gs.sufe.edu.cn":
        if any(term in title_body for term in _GS_ADMISSION_TERMS):
            return "推免与招生"
        if any(term in title_body for term in _GS_EXCHANGE_TERMS):
            return "国际交流"
    if "学生工作部" in meta.publisher or "学生处" in meta.publisher:
        if any(term in title_body for term in _XSC_SCHOLARSHIP_TERMS):
            return "奖助学金"
    return _DOMAIN_SCENES.get(domain)


def _document_kind(meta: DocMeta, text: str) -> str:
    explicit = getattr(meta, "document_kind", None)
    if explicit:
        return explicit
    quality = meta.quality_status or "accepted"
    if quality in {"incomplete_document", "low_quality", "quarantined"}:
        return "incomplete"
    classified = classify_document(meta.title, text)
    if classified == "policy":
        return "policy"
    if classified == "procedure":
        return "procedure"
    if classified == "public_list":
        return "public_list"
    if classified in {"news", "event"}:
        return classified
    if classified in {"announcement", "download_template"}:
        if re.search(r"20\d{2}年|年度", meta.title):
            return "annual_notice"
        return "procedure"
    return "news" if any(k in f"{meta.title}{text}" for k in ("新闻", "动态", "召开")) else "incomplete"


def _load_docs(manifest_path: Path, corpus_dir: Path) -> list[_CorpusDoc]:
    docs: list[_CorpusDoc] = []
    for meta in load_manifest(manifest_path).values():
        if not meta.file_path:
            continue
        path = corpus_dir / meta.file_path
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        scene = _scene_for(meta, body)
        if scene is None:
            continue
        docs.append(
            _CorpusDoc(
                meta=meta,
                body=body,
                scene=scene,
                document_kind=_document_kind(meta, body),
                validity_status=getattr(meta, "validity_status", None) or "unknown_validity",
            )
        )
    return docs


def _question_terms(question: str) -> set[str]:
    terms: set[str] = set()
    for token in _TOKEN_RE.findall(question):
        if len(token) <= 4:
            terms.add(token)
        else:
            terms.update(token[i : i + 2] for i in range(len(token) - 1))
    return terms


def _excerpt(body: str, point: str) -> str:
    compact = re.sub(r"\s+", " ", body).strip()
    index = compact.find(point)
    if index < 0:
        return compact[:160]
    return compact[max(0, index - 50) : index + len(point) + 110]


def _evaluate_question(probe: QuestionProbe, docs: list[_CorpusDoc]) -> QuestionResult:
    expected_domains = {domain.lower() for domain in probe.expected_domains}
    terms = _question_terms(probe.question)
    candidates: list[tuple[int, _CorpusDoc]] = []
    for doc in docs:
        if not doc.accepted:
            continue
        text = _normalize(f"{doc.meta.title}\n{doc.body}")
        domain_score = 2 if doc.domain in expected_domains else 0
        term_score = sum(1 for term in terms if _normalize(term) in text)
        point_score = sum(1 for point in probe.required_answer_points if _normalize(point) in text)
        if domain_score and term_score + point_score >= 2:
            candidates.append((domain_score + term_score + point_score, doc))
    candidates.sort(key=lambda item: (item[0], item[1].meta.publish_date), reverse=True)
    selected = [doc for _, doc in candidates[:5]]
    evidence: list[PointEvidence] = []
    for point in probe.required_answer_points:
        match = next((doc for doc in selected if _normalize(point) in _normalize(doc.body)), None)
        if match:
            evidence.append(
                PointEvidence(
                    point=point,
                    status="supported",
                    evidence_doc_id=match.meta.doc_id,
                    evidence_excerpt=_excerpt(match.body, point),
                    reason="正文包含回答要点",
                    confidence=0.75,
                )
            )
        else:
            evidence.append(
                PointEvidence(point=point, status="unsupported", reason="未找到正文证据")
            )
    supported = sum(point.status == "supported" for point in evidence)
    if selected and supported == len(evidence):
        status = "answerable"
    elif selected and supported:
        status = "partially_answerable"
    else:
        status = "not_answerable"
    missing = [f"缺少回答要点：{point.point}" for point in evidence if point.status != "supported"]
    if not selected:
        missing.insert(0, f"未命中权威来源：{', '.join(probe.expected_domains)}")
    return QuestionResult(
        id=probe.id,
        question=probe.question,
        scene=probe.scene,
        status=status,
        retrieved_doc_ids=tuple(doc.meta.doc_id for doc in selected),
        titles=tuple(doc.meta.title for doc in selected),
        publishers=tuple(doc.meta.publisher for doc in selected),
        publish_dates=tuple(doc.meta.publish_date for doc in selected),
        document_kinds=tuple(doc.document_kind for doc in selected),
        validity_statuses=tuple(doc.validity_status for doc in selected),
        has_attachment=any(doc.meta.document_type == "attachment" for doc in selected),
        matched_domains=tuple(sorted({doc.domain for doc in selected})),
        point_evidence=tuple(evidence),
        missing_reasons=tuple(missing),
    )


def _latest_valid_count(docs: list[_CorpusDoc]) -> int:
    grouped: dict[str, list[_CorpusDoc]] = defaultdict(list)
    for doc in docs:
        if not doc.accepted or doc.document_kind not in {"policy", "procedure", "annual_notice"}:
            continue
        topic = getattr(doc.meta, "topic_key", None) or getattr(doc.meta, "policy_name", None)
        grouped[topic or doc.meta.title].append(doc)
    return sum(1 for group in grouped.values() if group)


def audit_manifest(
    *,
    manifest_path: Path,
    corpus_dir: Path,
    question_bank_path: Path,
    retriever_config: dict | None = None,
    index_fingerprint: str = "not_indexed",
    embedding_model: str = "not_indexed",
) -> CoverageReport:
    bank = load_question_bank(question_bank_path)
    docs = _load_docs(manifest_path, corpus_dir)
    results = tuple(_evaluate_question(probe, docs) for probe in bank)
    scene_stats: dict[str, SceneStats] = {}
    for scene in SCENES:
        scene_docs = [doc for doc in docs if doc.scene == scene]
        scene_results = [result for result in results if result.scene == scene]
        valid = [doc for doc in scene_docs if doc.accepted]
        missing_domains = sorted(
            {
                domain
                for result, probe in zip(results, bank, strict=True)
                if result.scene == scene and result.status == "not_answerable"
                for domain in probe.expected_domains
            }
        )
        scene_stats[scene] = SceneStats(
            scene=scene,
            document_count=len(scene_docs),
            valid_policy_documents=sum(doc.document_kind == "policy" for doc in valid),
            valid_procedure_documents=sum(doc.document_kind == "procedure" for doc in valid),
            title_only_or_incomplete_documents=sum(
                (not doc.body or len(_normalize(doc.body)) <= _TITLE_ONLY_MAX)
                or doc.document_kind == "incomplete"
                for doc in scene_docs
            ),
            news_promotion_documents=sum(
                doc.document_kind in {"news", "event", "promotion"} for doc in scene_docs
            ),
            latest_valid_version_count=_latest_valid_count(scene_docs),
            question_count=len(scene_results),
            answerable_question_count=sum(r.status == "answerable" for r in scene_results),
            partially_answerable_question_count=sum(
                r.status == "partially_answerable" for r in scene_results
            ),
            unanswerable_question_count=sum(r.status == "not_answerable" for r in scene_results),
            missing_authoritative_sources=tuple(missing_domains),
        )
    config = dict(retriever_config or {})
    threshold = float(config.get("similarity_threshold", 0.0))
    return CoverageReport(
        question_bank_version=bank.version,
        question_bank_hash=bank.content_hash,
        retriever_config=config,
        embedding_model=embedding_model,
        similarity_threshold=threshold,
        index_fingerprint=index_fingerprint,
        evaluated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        scene_stats=scene_stats,
        question_results=results,
        corpus_document_count=len(docs),
    )


def render_markdown(report: CoverageReport) -> str:
    lines = [
        "# 上财知识库覆盖审计",
        "",
        f"- question_bank_version: `{report.question_bank_version}`",
        f"- question_bank_hash: `{report.question_bank_hash}`",
        f"- embedding_model: `{report.embedding_model}`",
        f"- similarity_threshold: `{report.similarity_threshold}`",
        f"- index_fingerprint: `{report.index_fingerprint}`",
        f"- evaluated_at: `{report.evaluated_at}`",
        "",
        "## 场景统计",
        "",
        "| 场景 | 文档数 | 有效 policy | 有效 procedure | 标题/不完整 | 新闻/宣传 | 最新有效版本 | 可回答 | 部分 | 不可回答 | 缺失权威来源 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for scene in SCENES:
        stats = report.scene_stats[scene]
        lines.append(
            f"| {scene} | {stats.document_count} | {stats.valid_policy_documents} | "
            f"{stats.valid_procedure_documents} | {stats.title_only_or_incomplete_documents} | "
            f"{stats.news_promotion_documents} | {stats.latest_valid_version_count} | "
            f"{stats.answerable_question_count} | {stats.partially_answerable_question_count} | "
            f"{stats.unanswerable_question_count} | {', '.join(stats.missing_authoritative_sources) or '—'} |"
        )
    lines.extend(
        [
            "",
            "## 逐题结果",
            "",
            "| ID | 问题 | 场景 | 状态 | doc_id | 标题 | 缺口 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for result in report.question_results:
        lines.append(
            f"| {result.id} | {result.question} | {result.scene} | {result.status} | "
            f"{', '.join(result.retrieved_doc_ids) or '—'} | "
            f"{result.titles[0] if result.titles else '—'} | "
            f"{'; '.join(result.missing_reasons) or '—'} |"
        )
    return "\n".join(lines) + "\n"
