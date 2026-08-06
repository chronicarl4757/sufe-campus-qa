"""带原文证据的制度版本关系推断。

设计原则（宁可 unknown，不可错判）：

1. 版本分组只按归一化政策名（去年份/修订版标记/附件扩展名），不用 topic_key——
   topic_key 是业务主题，会把不同制度（如"创新计划管理制度"与"学术之星评选办法"）
   错误归并。
2. supersedes 关系必须同时满足：
   - source 发布日期严格晚于 target（任一日期未知则不得建立）；
   - source 正文/标题含强证据（"同时废止/自…起施行/以本办法为准"等），
     且证据语境中提及 target 的政策名，防止把正文里任意"替代/修订"字样
     （例如论文文本"替代经典牛顿法"）当作版本证据；
   - 或：source 标题含明确"（…修订/修订稿）"版本标记，且与 target 归一化名称一致。
3. 父子（文章-附件）与同父兄弟之间绝不建立版本关系——它们是同一逻辑文档的
   不同载体，不是新旧版本。
4. 同组其余成员保持 version_unknown，交由生命周期按系列/时效规则处理。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sufe_qa.ingest.classification import normalize_policy_name

_STRONG_EVIDENCE_PATTERNS = (
    re.compile(r"同时废止[^。；\n]{0,30}"),
    re.compile(r"原《[^》]+》[^。；\n]{0,12}废止"),
    re.compile(r"自[^。；\n]{2,30}(?:起)?(?:施行|实施|生效)"),
    re.compile(r"以本(?:办法|规定|细则|通知|章程)为准"),
)
_EDITION_MARK_RE = re.compile(r"（[^）]*(?:修订|修订稿|修订版)[^）]*）")
_GROUP_NOISE_RE = re.compile(r"（[^）]*(?:修订|试行|暂行)[^）]*）|(?:19|20)\d{2}\s*年(?:度)?")
_EXT_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?)$", re.IGNORECASE)
# 政策名短于该长度时，"正文中提及名称"不足以证明版本指向（如"人才培养"是栏目名）
_MIN_CORE_LEN = 6


@dataclass(frozen=True)
class VersionCandidate:
    doc_id: str
    title: str
    body: str
    publish_date: str = "unknown"
    policy_name: str = ""
    topic_key: str = ""
    document_type: str = "article"
    parent_doc_id: str | None = None

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


def _group_key(candidate: VersionCandidate) -> str:
    name = _EXT_RE.sub("", candidate.normalized_policy_name)
    name = _GROUP_NOISE_RE.sub("", name)
    return name.strip(" ：:，,。") or candidate.doc_id


_REVISION_RE = re.compile(r"修订")


def _strong_evidence(source: VersionCandidate, target: VersionCandidate) -> str:
    """source 文本中的强版本证据。

    必须提及 target 政策名（长度 >= _MIN_CORE_LEN，避免"人才培养"这类栏目名），
    且出现强证据词或"修订"字样，防止把正文任意"替代/修订"文本当作版本证据。
    """
    text = f"{source.title}\n{source.body}"
    core = _EXT_RE.sub("", target.normalized_policy_name)
    if len(core) < _MIN_CORE_LEN or core not in text:
        return ""
    matches = [m.group(0) for p in _STRONG_EVIDENCE_PATTERNS if (m := p.search(text))]
    if _REVISION_RE.search(text):
        matches.append(f"修订{core}")
    return "；".join(matches)


def _title_edition_evidence(source: VersionCandidate, target: VersionCandidate) -> str:
    """标题修订版标记路径：source 与 target 同名且 source 标题带（…修订）标记。"""
    if _group_key(source) != _group_key(target):
        return ""
    mark = _EDITION_MARK_RE.search(source.title)
    if not mark:
        return ""
    return f"标题版本标记：{mark.group(0)}"


def _strictly_newer(source: VersionCandidate, target: VersionCandidate) -> bool:
    s_date, t_date = source.publish_date or "", target.publish_date or ""
    if not re.match(r"\d{4}-\d{2}-\d{2}", s_date) or not re.match(r"\d{4}-\d{2}-\d{2}", t_date):
        return False
    return s_date > t_date


def _is_family(source: VersionCandidate, target: VersionCandidate) -> bool:
    """父子或同父兄弟是同一逻辑文档的不同载体，不构成版本关系。"""
    if source.doc_id == target.parent_doc_id or target.doc_id == source.parent_doc_id:
        return True
    return bool(
        source.parent_doc_id
        and target.parent_doc_id
        and source.parent_doc_id == target.parent_doc_id
    )


def _unknown(candidate: VersionCandidate) -> VersionRelation:
    return VersionRelation(
        source_doc_id=candidate.doc_id,
        target_doc_id="",
        relation="version_unknown",
        status="unknown_validity",
        confidence=0.0,
        evidence="仅发现年份/标题相似，缺少明确施行、修订或废止证据",
    )


def infer_version_relations(candidates: list[VersionCandidate]) -> list[VersionRelation]:
    groups: dict[str, list[VersionCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(_group_key(candidate), []).append(candidate)
    relations: list[VersionRelation] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda c: c.publish_date or "", reverse=True)
        related: set[str] = set()
        for i, source in enumerate(ordered):
            if source.doc_id in related:
                continue
            for target in ordered[i + 1 :]:
                if target.doc_id in related or _is_family(source, target):
                    continue
                if not _strictly_newer(source, target):
                    continue
                evidence = _strong_evidence(source, target) or _title_edition_evidence(
                    source, target
                )
                if not evidence:
                    continue
                relations.append(
                    VersionRelation(
                        source_doc_id=source.doc_id,
                        target_doc_id=target.doc_id,
                        relation="supersedes",
                        status="current",
                        confidence=0.95,
                        evidence=evidence,
                    )
                )
                related.update({source.doc_id, target.doc_id})
                break
        relations.extend(
            _unknown(candidate) for candidate in ordered if candidate.doc_id not in related
        )
    return relations
