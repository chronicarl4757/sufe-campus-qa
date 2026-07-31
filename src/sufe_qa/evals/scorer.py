"""评测：检索命中率 / 拒答正确率，离线可跑（无需 LLM）；合并前过门禁。

评测集为 JSONL，每行：
  {"id": "q1", "question": "...", "expected_doc_ids": ["ab12cd34ef56"],
   "should_refuse": false, "answer_points": ["要点1", "要点2"]}

- 应答题：expected_doc_ids 任一出现在融合 top-N 即命中；命中率对齐 M2 达标线 >= 90%。
- 拒答题：should_refuse=true，检索低置信（被门控拦下）才算拒答正确；达标线 = 100%。
- 引用正确率需 LLM 判分，v1 评测集只标定检索与拒答两项，门禁也只卡这两项。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sufe_qa.config import Settings
from sufe_qa.retrieve.retriever import HybridRetriever, is_confident


@dataclass(frozen=True)
class EvalItem:
    id: str
    question: str
    expected_doc_ids: list[str] = field(default_factory=list)
    should_refuse: bool = False
    answer_points: list[str] = field(default_factory=list)


def load_evalset(path: Path) -> list[EvalItem]:
    items: list[EvalItem] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        try:
            items.append(EvalItem(**d))
        except TypeError as e:
            raise ValueError(f"评测集格式错误 {path}:{lineno}: {e}") from e
    return items


@dataclass(frozen=True)
class EvalRow:
    id: str
    question: str
    hit: bool | None  # 拒答题不参与命中统计，置 None
    refused: bool
    correct: bool


@dataclass(frozen=True)
class EvalReport:
    rows: list[EvalRow]
    hit_rate: float | None  # 无应答题时为 None
    refusal_rate: float | None  # 无拒答题时为 None

    def gate_failures(self, min_hit_rate: float, min_refusal_rate: float) -> list[str]:
        """返回未达标项描述列表；空列表表示过门禁。"""
        failures: list[str] = []
        if self.hit_rate is not None and self.hit_rate < min_hit_rate:
            failures.append(f"检索命中率 {self.hit_rate:.1%} < 达标线 {min_hit_rate:.1%}")
        if self.refusal_rate is not None and self.refusal_rate < min_refusal_rate:
            failures.append(f"拒答正确率 {self.refusal_rate:.1%} < 达标线 {min_refusal_rate:.1%}")
        return failures


def score_retrieval(
    retriever: HybridRetriever, settings: Settings, items: list[EvalItem]
) -> EvalReport:
    rows: list[EvalRow] = []
    for item in items:
        hits = retriever.search(item.question)
        refused = not is_confident(hits, settings.vector_min_similarity)
        if item.should_refuse:
            rows.append(EvalRow(item.id, item.question, hit=None, refused=refused, correct=refused))
        else:
            hit = any(h.doc_id in item.expected_doc_ids for h in hits)
            rows.append(EvalRow(item.id, item.question, hit=hit, refused=refused, correct=hit))

    answerable = [r for r in rows if r.hit is not None]
    refusable = [r for r in rows if r.hit is None]
    return EvalReport(
        rows=rows,
        hit_rate=(sum(1 for r in answerable if r.hit) / len(answerable)) if answerable else None,
        refusal_rate=(sum(1 for r in refusable if r.correct) / len(refusable))
        if refusable
        else None,
    )
