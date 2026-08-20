"""canonical unit registry 加载与单位名归一化（本轮 §四/§五/§十七）。

匹配原则：
- alias 只来自 registry（全部有真实使用证据），最长匹配优先（更具体的名称胜出）；
- 归属判定先看 publisher（精确别名匹配），再看 title（子串匹配）；
- 未匹配单位返回 None，由调用方原样保留（unknown unit preservation，不硬映射到相似学院）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

UNIT_TYPES = (
    "college",
    "academy",
    "institute",
    "teaching_department",
    "special_program_unit",
    "external",
)


@dataclass(frozen=True)
class Unit:
    unit_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    unit_type: str
    undergraduate: bool
    graduate: bool
    admission_relevant: bool
    website: str = ""
    wechat: str = ""
    notes: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        """所有可匹配名称：canonical_name 在 aliases 之前。"""
        return (self.canonical_name, *self.aliases)


def load_units(path: str | Path) -> list[Unit]:
    """加载 data/coverage/sufe_units.yaml。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    units: list[Unit] = []
    for raw in data.get("units") or []:
        unit_type = str(raw.get("unit_type") or "college")
        if unit_type not in UNIT_TYPES:
            raise ValueError(f"单位 {raw.get('unit_id')}: 非法 unit_type {unit_type}")
        canonical = str(raw["canonical_name"])
        aliases = tuple(str(a) for a in raw.get("aliases") or () if str(a) != canonical)
        units.append(
            Unit(
                unit_id=str(raw["unit_id"]),
                canonical_name=canonical,
                aliases=aliases,
                unit_type=unit_type,
                undergraduate=bool(raw.get("undergraduate") or False),
                graduate=bool(raw.get("graduate") or False),
                admission_relevant=bool(raw.get("admission_relevant") or False),
                website=str(raw.get("website") or ""),
                wechat=str(raw.get("wechat") or ""),
                notes=str(raw.get("notes") or ""),
            )
        )
    return units


def _best_match(text: str, units: list[Unit], *, exact: bool) -> Unit | None:
    """exact=True 要求名称与 text 完全相等；否则子串包含即命中。最长名称优先。"""
    best: Unit | None = None
    best_len = 0
    for unit in units:
        for name in unit.names:
            if not name:
                continue
            hit = text.strip() == name if exact else name in text
            if hit and len(name) > best_len:
                best, best_len = unit, len(name)
    return best


def normalize_unit_name(text: str, units: list[Unit]) -> Unit | None:
    """把任意写法（上财信息/SCAI/统计与管理学院…）归一到 canonical unit；未知返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    exact = _best_match(text, units, exact=True)
    if exact is not None:
        return exact
    return _best_match(text, units, exact=False)


def attribute_document(title: str, publisher: str, units: list[Unit]) -> tuple[Unit | None, str]:
    """文档 → canonical unit。返回 (unit, via)；via ∈ publisher|title|none。

    publisher 精确别名优先（发布者归属最可靠），其次 title 最长子串。
    """
    unit = _best_match((publisher or "").strip(), units, exact=True)
    if unit is not None:
        return unit, "publisher"
    unit = _best_match(title or "", units, exact=False)
    if unit is not None:
        return unit, "title"
    return None, "none"
