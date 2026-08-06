"""固定分母的问题覆盖探针格式。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

QUESTION_BANK_VERSION = "sufe-question-bank.v1"
SCENE_QUOTAS = {
    "本科教务": 20,
    "研究生培养与学位": 20,
    "奖助学金": 15,
    "推免与招生": 15,
    "就业手续": 15,
    "宿舍后勤": 10,
    "信息化与校园卡": 15,
    "图书馆": 10,
    "医疗医保": 10,
    "国际交流": 10,
    "新生与安全": 10,
}
VALID_STATUSES = frozenset({"unverified", "verified", "blocked"})


@dataclass(frozen=True)
class QuestionProbe:
    id: str
    question: str
    scene: str
    required_source_type: str
    expected_domains: tuple[str, ...]
    expected_doc_ids: tuple[str, ...]
    required_answer_points: tuple[str, ...]
    needs_current_version: bool
    status: str = "unverified"
    scope_unit: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "QuestionProbe":
        required = {
            "id",
            "question",
            "scene",
            "required_source_type",
            "expected_domains",
            "expected_doc_ids",
            "required_answer_points",
            "needs_current_version",
            "status",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(f"问题缺少字段: {', '.join(missing)}")
        probe = cls(
            id=str(data["id"]),
            question=str(data["question"]),
            scene=str(data["scene"]),
            required_source_type=str(data["required_source_type"]),
            expected_domains=tuple(str(x) for x in data["expected_domains"]),
            expected_doc_ids=tuple(str(x) for x in data["expected_doc_ids"]),
            required_answer_points=tuple(str(x) for x in data["required_answer_points"]),
            needs_current_version=bool(data["needs_current_version"]),
            status=str(data["status"]),
            scope_unit=str(data["scope_unit"]) if data.get("scope_unit") else None,
        )
        if not probe.id or not probe.question:
            raise ValueError("问题 id 和 question 不能为空")
        if probe.scene not in SCENE_QUOTAS:
            raise ValueError(f"未知问题场景: {probe.scene}")
        if not probe.required_source_type or not probe.expected_domains:
            raise ValueError(f"问题缺少权威来源: {probe.id}")
        if not probe.required_answer_points:
            raise ValueError(f"问题缺少回答要点: {probe.id}")
        if probe.status not in VALID_STATUSES:
            raise ValueError(f"非法问题状态: {probe.status}")
        return probe

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "scene": self.scene,
            "required_source_type": self.required_source_type,
            "expected_domains": list(self.expected_domains),
            "expected_doc_ids": list(self.expected_doc_ids),
            "required_answer_points": list(self.required_answer_points),
            "needs_current_version": self.needs_current_version,
            "status": self.status,
            **({"scope_unit": self.scope_unit} if self.scope_unit else {}),
        }


@dataclass(frozen=True)
class QuestionBank:
    items: tuple[QuestionProbe, ...]
    version: str = QUESTION_BANK_VERSION
    content_hash: str = ""

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[QuestionProbe]:
        return iter(self.items)

    def by_scene(self, scene: str) -> tuple[QuestionProbe, ...]:
        return tuple(item for item in self.items if item.scene == scene)


def _hash_rows(rows: list[dict]) -> str:
    canonical = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_question_bank(path: Path) -> QuestionBank:
    if not path.exists():
        raise FileNotFoundError(f"问题库不存在: {path}")
    rows: list[dict] = []
    items: list[QuestionProbe] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"问题库第 {lineno} 行不是 JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"问题库第 {lineno} 行必须是对象")
        item = QuestionProbe.from_dict(raw)
        rows.append(item.to_dict())
        items.append(item)
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("问题库存在重复 id")
    counts = {scene: len([item for item in items if item.scene == scene]) for scene in SCENE_QUOTAS}
    if counts != SCENE_QUOTAS:
        raise ValueError(f"问题场景配额不符: {counts}，期望 {SCENE_QUOTAS}")
    return QuestionBank(tuple(items), content_hash=_hash_rows(rows))
