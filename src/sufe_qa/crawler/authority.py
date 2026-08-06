"""上财职能部门权威来源清单与 adapter 工厂。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sufe_qa.crawler.adapters import (
    BusinessSchoolAdapter,
    CareerAdapter,
    GraduateSchoolAdapter,
    JwcAdapter,
    NicServiceAdapter,
    SectionSpec,
    SiteAdapter,
    Wp3Adapter,
)


@dataclass(frozen=True)
class AuthoritySource:
    source_id: str
    adapter_name: str
    homepage: str
    publisher: str
    source_type: str
    scope_unit: str
    sections: tuple[SectionSpec, ...]
    allowed_hosts: tuple[str, ...] = ()


_ADAPTERS = {
    "wp3": Wp3Adapter,
    "jwc": JwcAdapter,
    "graduate_school": GraduateSchoolAdapter,
    "career": CareerAdapter,
    "nic_service": NicServiceAdapter,
    "business_school": BusinessSchoolAdapter,
}


def _section_from(source: dict[str, Any], raw: dict[str, Any]) -> SectionSpec:
    metadata = {
        str(key): str(value)
        for key, value in raw.items()
        if key not in {"name", "list_url", "category", "max_pages", "known_page_urls"}
        and value is not None
    }
    name = str(raw["name"])
    list_url = str(raw["list_url"])
    return SectionSpec(
        section_id=str(raw.get("section_id") or f"{source['id']}-{name}"),
        name=name,
        list_url=list_url,
        category=str(raw.get("category") or "学工事务"),
        publisher=str(source.get("publisher") or ""),
        source_type=str(source.get("source_type") or "official_department"),
        scope_unit=str(raw.get("scope_unit") or source.get("scope_unit") or ""),
        time_policy=str(raw.get("time_policy") or "all_history"),
        max_pages=int(raw["max_pages"]) if raw.get("max_pages") is not None else None,
        known_page_urls=tuple(str(url) for url in raw.get("known_page_urls") or ()),
        metadata=metadata,
    )


def load_authority_sources(path: str | Path) -> list[AuthoritySource]:
    source_path = Path(path)
    data = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    out: list[AuthoritySource] = []
    for raw in data.get("sources") or []:
        sections = tuple(_section_from(raw, section) for section in raw.get("sections") or [])
        out.append(
            AuthoritySource(
                source_id=str(raw["id"]),
                adapter_name=str(raw["adapter"]),
                homepage=str(raw.get("homepage") or ""),
                publisher=str(raw.get("publisher") or ""),
                source_type=str(raw.get("source_type") or "official_department"),
                scope_unit=str(raw.get("scope_unit") or ""),
                sections=sections,
                allowed_hosts=tuple(str(host) for host in raw.get("allowed_hosts") or ()),
            )
        )
    return out


def adapter_for_source(source: AuthoritySource) -> SiteAdapter:
    try:
        cls = _ADAPTERS[source.adapter_name]
    except KeyError as exc:
        raise ValueError(f"未知 SUFE adapter: {source.adapter_name}") from exc
    return cls(
        publisher=source.publisher,
        source_type=source.source_type,
        scope_unit=source.scope_unit,
    )
