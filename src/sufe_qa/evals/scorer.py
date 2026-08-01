"""评测：检索命中率 / 应答题回答率 / 拒答正确率，离线可跑（无需 LLM）；合并前过门禁。

评测集为 JSONL，每行：
  {"id": "q1", "question": "...", "expected_doc_ids": ["ab12cd34ef56"],
   "should_refuse": false, "answer_points": ["要点1", "要点2"]}
空行与 # 开头的注释行跳过（模板文件内嵌说明用）。

- 应答题：expected_doc_ids 任一出现在融合 top-N 即命中；命中率对齐 M2 达标线 >= 90%。
  应答题被低置信门控拦下（拒答）视同作答失败，计入回答率门禁。
- 拒答题：should_refuse=true，检索低置信（被门控拦下）才算拒答正确；达标线 = 100%。
- 空评测集、缺少应答题/拒答题样本一律判门禁失败，杜绝"空集过门禁"。
- 引用正确率需 LLM 判分，v1 门禁只卡检索、回答率与拒答三项离线指标。
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
        if not line or line.startswith("#"):
            continue  # 空行与模板说明注释行
        try:
            d = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"评测集 JSON 解析失败 {path}:{lineno}: {e}") from e
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
    answer_rate: float | None  # 应答题中未被拒答的比例；无应答题时为 None

    def gate_failures(
        self, min_hit_rate: float, min_refusal_rate: float, min_answer_rate: float = 1.0
    ) -> list[str]:
        """返回未达标项描述列表；空列表表示过门禁。

        空评测集、缺少应答题/拒答题样本直接判失败：None 不视为达标，
        防止"全部拒答"或"空集"系统混过门禁。
        """
        failures: list[str] = []
        if not self.rows:
            failures.append("评测集为空，无法证明系统可用")
            return failures
        if self.hit_rate is None:
            failures.append("缺少应答题样本（should_refuse=false）")
        elif self.hit_rate < min_hit_rate:
            failures.append(f"检索命中率 {self.hit_rate:.1%} < 达标线 {min_hit_rate:.1%}")
        if self.refusal_rate is None:
            failures.append("缺少拒答题样本（should_refuse=true）")
        elif self.refusal_rate < min_refusal_rate:
            failures.append(f"拒答正确率 {self.refusal_rate:.1%} < 达标线 {min_refusal_rate:.1%}")
        if self.answer_rate is not None and self.answer_rate < min_answer_rate:
            failures.append(
                f"应答题回答率 {self.answer_rate:.1%} < 达标线 {min_answer_rate:.1%}"
                "（应答题被拒答视同失败）"
            )
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
            # 应答题被低置信门控拦下视同作答失败：检索命中但被拒答不计正确
            rows.append(
                EvalRow(
                    item.id, item.question, hit=hit, refused=refused, correct=hit and not refused
                )
            )

    answerable = [r for r in rows if r.hit is not None]
    refusable = [r for r in rows if r.hit is None]
    return EvalReport(
        rows=rows,
        hit_rate=(sum(1 for r in answerable if r.hit) / len(answerable)) if answerable else None,
        refusal_rate=(sum(1 for r in refusable if r.correct) / len(refusable))
        if refusable
        else None,
        answer_rate=(sum(1 for r in answerable if not r.refused) / len(answerable))
        if answerable
        else None,
    )
