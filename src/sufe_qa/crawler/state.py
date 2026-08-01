"""抓取状态：data/crawl_state/<host>.json，支撑增量抓取与 not_seen 标记。

记录粒度为 requested_url，字段覆盖规格 §十一：
requested_url / final_url / etag / last_modified / last_seen_at / fetched_at /
content_hash / binary_hash / text_hash / parse_status / status(active|not_seen)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CrawlState:
    path: Path
    records: dict[str, dict] = field(default_factory=dict)
    _seen: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> CrawlState:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls(path=path, records=dict(data.get("records") or {}))
            except (json.JSONDecodeError, OSError):
                pass  # 状态损坏不致命，重来一轮全量
        return cls(path=path)

    def get(self, url: str) -> dict | None:
        return self.records.get(url)

    def mark_seen(self, url: str) -> None:
        self._seen.add(url)
        if url in self.records:
            self.records[url]["last_seen_at"] = _now()
            self.records[url]["status"] = "active"

    def update(self, url: str, **fields) -> None:
        rec = self.records.setdefault(url, {"requested_url": url})
        rec.update({k: v for k, v in fields.items() if v is not None})
        rec["fetched_at"] = _now()
        self.mark_seen(url)

    def conditional_headers(self, url: str) -> dict:
        """由历史 etag/last_modified 生成条件请求头。"""
        rec = self.records.get(url) or {}
        headers = {}
        if rec.get("etag"):
            headers["If-None-Match"] = rec["etag"]
        if rec.get("last_modified"):
            headers["If-Modified-Since"] = rec["last_modified"]
        return headers

    def finalize(self) -> list[str]:
        """本轮未出现的记录标记 not_seen（不删除，规格 §十一）；返回其 URL。"""
        missing = []
        for url, rec in self.records.items():
            if url not in self._seen and rec.get("status") != "not_seen":
                rec["status"] = "not_seen"
                missing.append(url)
        return missing

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"records": self.records}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
