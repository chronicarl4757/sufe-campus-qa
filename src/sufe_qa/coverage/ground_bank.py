"""把 benchmark 探针结果固化为「有文可依」题库。

判级规则（在 benchmark_probe 结果之上）：
- grounded：answerable 且 top 命中是权威文档（高相似、有效文档类型），
  自动回填 expected_doc_ids（附件命中归一化为父通知 doc_id），状态置 grounded；
- needs_docs：not_answerable、要点长期缺失、或仅命中新闻/名单的题，
  连同缺口原因与建议补文档部门写入另算清单，不硬凑答案。

grounded 题库不是正式门禁（门禁仍是人工核验的 evalset.v1），而是
「高频问题 × 真实文档」的覆盖产物：每条都可回溯到具体权威文档。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# grounded 回填的最低相似度：明显高于门控 0.50，避免踩线命中凑数
GROUND_MIN_SIMILARITY = 0.55
# 可作为答案依据的文档类型
GROUNDABLE_KINDS = {
    "policy",
    "procedure",
    "faq",
    "annual_notice",
    "form",
    "manual",
    "service_guide",
}
# 年度通知只接受近三学年（高频问题的答案不能来自过期通知）
_ANNUAL_NOTICE_MAX_AGE_YEARS = 3


@dataclass(frozen=True)
class GroundDecision:
    status: str  # grounded | needs_docs
    expected_doc_ids: tuple[str, ...] = ()
    reason: str = ""


def _year_of(date_str: str) -> int | None:
    m = re.match(r"(20\d{2})", date_str or "")
    return int(m.group(1)) if m else None


def decide_grounding(result: dict, *, current_year: int) -> GroundDecision:
    """对单条 probe result 判级。result 为 BenchmarkResult.to_dict() 的 dict。"""
    if result["status"] == "not_answerable":
        reason = next(iter(result.get("missing_reasons") or ()), "无高置信检索结果")
        return GroundDecision("needs_docs", reason=reason)
    if result["status"] != "answerable":
        # partially/offdomain 由人工复核后另行处理，不自动固化
        return GroundDecision("needs_docs", reason=f"probe 状态 {result['status']}，待复核")

    hits = [h for h in result.get("top_hits") or () if h.get("similarity") is not None]
    if not hits or hits[0]["similarity"] < GROUND_MIN_SIMILARITY:
        return GroundDecision(
            "needs_docs",
            reason=f"top 相似度 {hits[0]['similarity'] if hits else 0:.2f} 低于固化线 {GROUND_MIN_SIMILARITY}",
        )

    doc_ids: list[str] = []
    for h in hits:
        kind = h.get("document_kind", "")
        if kind not in GROUNDABLE_KINDS:
            continue
        if kind == "annual_notice":
            year = _year_of(h.get("publish_date", ""))
            if year is None or year < current_year - _ANNUAL_NOTICE_MAX_AGE_YEARS:
                continue
        if h["doc_id"] not in doc_ids:
            doc_ids.append(h["doc_id"])
        if len(doc_ids) >= 2:
            break
    if not doc_ids:
        kinds = "、".join(sorted({h.get("document_kind", "?") for h in hits}))
        return GroundDecision("needs_docs", reason=f"命中文档类型不足以作为依据（{kinds}）")
    return GroundDecision("grounded", expected_doc_ids=tuple(doc_ids))


def ground_bank(
    bank_path: Path,
    probe_report_path: Path,
    *,
    grounded_out: Path,
    needs_docs_out: Path,
    current_year: int,
) -> tuple[int, int]:
    """输出 grounded 题库与 needs_docs 清单，返回各自条数。"""
    results = {
        r["id"]: r for r in json.loads(probe_report_path.read_text(encoding="utf-8"))["results"]
    }
    n_grounded = n_needs = 0
    with (
        open(bank_path, encoding="utf-8") as fin,
        open(grounded_out, "w", encoding="utf-8") as fg,
        open(needs_docs_out, "w", encoding="utf-8") as fn,
    ):
        for raw in fin:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            item = json.loads(line)
            result = results.get(item["id"])
            if result is None:
                continue
            if item.get("should_refuse") or item.get("needs_clarification"):
                # 拒答/追问题不依赖具体文档，保留原样进入 grounded 集合
                item["status"] = "grounded"
                fg.write(json.dumps(item, ensure_ascii=False) + "\n")
                n_grounded += 1
                continue
            decision = decide_grounding(result, current_year=current_year)
            if decision.status == "grounded":
                item["expected_doc_ids"] = list(decision.expected_doc_ids)
                item["status"] = "grounded"
                fg.write(json.dumps(item, ensure_ascii=False) + "\n")
                n_grounded += 1
            else:
                item["status"] = "needs_docs"
                item["missing_reason"] = decision.reason
                item["suggested_departments"] = item.get("expected_domains") or []
                fn.write(json.dumps(item, ensure_ascii=False) + "\n")
                n_needs += 1
    return n_grounded, n_needs
