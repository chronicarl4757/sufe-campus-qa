"""带原文证据的制度主题和版本关系推断。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sufe_qa.ingest.classification import normalize_policy_name

_EVIDENCE_PATTERNS = (
    re.compile(r"自[^。；\n]{2,30}(?:起)?(?:施行|实施|生效)"),
    re.compile(r"同时废止[^。；\n]{0,30}"),
    re.compile(r"原(?:办法|规定|制度)[^。；\n]{0,20}废止"),
    re.compile(r"(?:修订|修订版|修订稿|替代|取代)[^。；\n]{0,30}"),
    re.compile(r"以本(?:办法|规定|通知)为准"),
)


@dataclass(frozen=True)
class VersionCandidate:
    doc_id: str
    title: str
    body: str
    publish_date: str = "unknown"
    policy_name: str = ""
    topic_key: str = ""

    @property
    def normalized_policy_name(self) -> str:
        return self.policy_name or normalize_policy_name(self.title)


@dataclass(frozen=True)
class VersionRelation:
    source_doc_id: str
    target_doc_id: str
    relation: str
    status: str
    confidence: float
    evidence: str


def _evidence(candidate: VersionCandidate) -> str:
    text = f"{candidate.title}\n{candidate.body}"
    matches = [match.group(0) for pattern in _EVIDENCE_PATTERNS if (match := pattern.search(text))]
    return "；".join(matches)


def _topic(candidate: VersionCandidate) -> str:
    if candidate.topic_key:
        return candidate.topic_key
    name = re.sub(
        r"20\d{2}年|（[^）]*(?:修订|试行|暂行)[^）]*）",
        "",
        candidate.normalized_policy_name,
    )
    return name or candidate.doc_id


def infer_version_relations(candidates: list[VersionCandidate]) -> list[VersionRelation]:
    groups: dict[str, list[VersionCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(_topic(candidate), []).append(candidate)
    relations: list[VersionRelation] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda candidate: candidate.publish_date or "", reverse=True)
        source = next((candidate for candidate in ordered if _evidence(candidate)), None)
        if source is None:
            relations.extend(
                VersionRelation(
                    source_doc_id=candidate.doc_id,
                    target_doc_id="",
                    relation="version_unknown",
                    status="unknown_validity",
                    confidence=0.0,
                    evidence="仅发现年份/标题相似，缺少明确施行、修订或废止证据",
                )
                for candidate in ordered
            )
            continue
        target = next((candidate for candidate in ordered if candidate.doc_id != source.doc_id), None)
        if target is None:
            continue
        relations.append(
            VersionRelation(
                source_doc_id=source.doc_id,
                target_doc_id=target.doc_id,
                relation="supersedes",
                status="current",
                confidence=0.95,
                evidence=_evidence(source),
            )
        )
    return relations
