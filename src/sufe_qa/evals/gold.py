"""gold.v1 人工金标评测集：校验器 + 标注候选推荐。

与 150 题覆盖探针（sufe_question_bank）、冻结措辞集（holdout.v1）分工：
gold 由人工精标 expected_doc_ids / required_answer_points / evidence / gold_answer，
evidence_text 必须与原文逐字吻合（校验器强制），用于判断"检索对没对、答案对没对、
引用支不支撑"。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sufe_qa.schema import load_manifest

SCENES = {
    "本科教务",
    "奖助学金",
    "研究生培养与学位",
    "就业手续",
    "宿舍后勤",
    "信息化与校园卡",
    "图书馆",
    "医疗医保",
    "国际交流",
    "新生与安全",
    "推免与招生",
}
INTENTS = {"条件", "材料", "流程", "时间", "地点", "金额", "资格"}
VALIDITY = {"current", "historical", "superseded", "unknown_validity"}
# 泛词不算要点：要点必须是可检查的事实
# 泛词不算要点：整句仅由泛词组成（如"申请""申请流程"）即拒绝
GENERIC_POINT = re.compile(
    r"^(申请|流程|办理|部门|材料|条件|时间|地点|联系方式|注意事项|规定|办法)+$"
)


@dataclass
class GoldIssue:
    id: str
    level: str  # error | warn
    message: str


@dataclass
class GoldReport:
    total: int
    issues: list[GoldIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[GoldIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[GoldIssue]:
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def validate_gold(path: Path, manifest_path: Path, corpus_dir: Path | None = None) -> GoldReport:
    """逐条校验 gold 集：schema、词表、来源文档现行性、evidence 逐字存在。"""
    corpus_dir = corpus_dir or manifest_path.parent
    manifest = load_manifest(manifest_path)
    issues: list[GoldIssue] = []
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            issues.append(GoldIssue(f"第{lineno}行", "error", f"不是合法 JSON: {exc}"))
    report = GoldReport(total=len(rows), issues=issues)
    seen_ids: set[str] = set()

    for row in rows:
        rid = str(row.get("id", "?"))

        def err(msg: str) -> None:
            issues.append(GoldIssue(rid, "error", msg))

        def warn(msg: str) -> None:
            issues.append(GoldIssue(rid, "warn", msg))

        if rid in seen_ids:
            err(f"重复 id: {rid}")
        seen_ids.add(rid)

        # ---- 1. 基本属性与词表 ----
        for f in ("question", "scene", "topic_key", "question_intent", "student_type"):
            if not row.get(f):
                err(f"缺字段: {f}")
        if row.get("scene") and row["scene"] not in SCENES:
            err(f"scene 不在词表: {row['scene']}")
        if row.get("question_intent") and row["question_intent"] not in INTENTS:
            warn(f"question_intent 建议用词表 {sorted(INTENTS)}: {row['question_intent']}")
        for f in ("should_answer", "should_refuse", "needs_clarification", "needs_current_version"):
            if not isinstance(row.get(f), bool):
                err(f"{f} 必须是 true/false")
        if row.get("should_answer") and row.get("should_refuse"):
            err("should_answer 与 should_refuse 不能同时 true")

        # ---- 2. 权威来源 ----
        doc_ids = [str(x) for x in row.get("expected_doc_ids") or []]
        if row.get("should_answer") and not doc_ids:
            err("应答题必须有 expected_doc_ids（至少一份人工确认的正确原文）")
        if row.get("should_refuse") and doc_ids:
            warn("拒答题一般不留 expected_doc_ids")
        for doc_id in doc_ids:
            meta = manifest.get(doc_id)
            if meta is None:
                err(f"expected_doc_id 不存在于 manifest: {doc_id}")
                continue
            if meta.quality_status != "accepted" or meta.retention_status != "active":
                err(
                    f"gold 来源不是现行文档: {doc_id}（{meta.quality_status}/{meta.retention_status}）"
                )
            if meta.index_collection == "none":
                err(f"gold 来源不在检索索引: {doc_id}")
            if meta.validity_status in {"superseded", "historical"}:
                warn(f"gold 来源已是旧版（{meta.validity_status}），确认是否应换现行版: {doc_id}")
        publishers = {manifest[d].publisher for d in doc_ids if d in manifest}
        for pub in row.get("expected_publishers") or []:
            if publishers and pub not in publishers:
                warn(f"expected_publisher 与来源文档发布单位不符: {pub}")

        # ---- 3. 要点必须是可以检查的事实 ----
        points = [str(p) for p in row.get("required_answer_points") or []]
        if row.get("should_answer") and not points:
            err("应答题必须有 required_answer_points")
        for p in points:
            if GENERIC_POINT.match(_squash(p)):
                err(f"要点太泛，需写成可检查的事实句: {p}")
            elif len(_squash(p)) < 6:
                warn(f"要点偏短，可能难以区分对错: {p}")

        # ---- 4. evidence 逐字核对（防标注者脑补）----
        for ev in row.get("evidence") or []:
            ev_doc = str(ev.get("doc_id", ""))
            ev_text = str(ev.get("evidence_text", ""))
            meta = manifest.get(ev_doc)
            if meta is None or not meta.file_path:
                err(f"evidence 文档不存在或无正文: {ev_doc}")
                continue
            body_path = corpus_dir / meta.file_path
            if not body_path.is_file():
                err(f"evidence 正文文件缺失: {meta.file_path}")
                continue
            body = body_path.read_text(encoding="utf-8", errors="replace")
            if _squash(ev_text) not in _squash(body):
                err(f"evidence_text 在原文中逐字找不到（{ev_doc}）: {ev_text[:40]}…")

        # ---- 5. gold_answer 长度 ----
        gold_answer = str(row.get("gold_answer") or "")
        if row.get("should_answer"):
            n = len(gold_answer)
            if not (30 <= n <= 300):
                warn(f"gold_answer 建议 50~150 字（当前 {n} 字）")

        # ---- 6. 版本有效性人工确认 ----
        vs = str(row.get("validity_status") or "")
        if vs and vs not in VALIDITY:
            err(f"validity_status 词表外: {vs}")
        if row.get("needs_current_version") and vs == "unknown_validity":
            warn("needs_current_version=true 但版本有效性标了 unknown，请尽量确认")

    return report


def suggest_candidates(question: str, retriever, n: int = 8) -> list[dict]:
    """对给定问题跑真实检索，返回候选官方文档供人工勾选 gold 来源。"""
    out = []
    for hit in retriever.search_routed(question)[:n]:
        out.append(
            {
                "doc_id": hit.doc_id,
                "title": hit.title,
                "publisher": hit.publisher,
                "publish_date": hit.publish_date,
                "validity_status": hit.validity_status,
                "similarity": round(hit.vector_similarity or 0.0, 3),
                "snippet": hit.text[:160].replace("\n", " "),
            }
        )
    return out
