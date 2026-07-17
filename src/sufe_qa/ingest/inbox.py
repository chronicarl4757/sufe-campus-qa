from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sufe_qa.ingest.parsers import ParseError, parse_file
from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text

SENSITIVE_PATTERNS = [
    re.compile(r"\d{17}[\dXx]"),  # 身份证
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),  # 手机号
]


def scan_sensitive(text: str) -> list[str]:
    """返回命中的敏感串；空列表表示安全。"""
    return [m.group() for pat in SENSITIVE_PATTERNS for m in pat.finditer(text)]


def slugify(title: str, max_len: int = 40) -> str:
    s = unicodedata.normalize("NFKC", title)
    s = re.sub(r"[^\w一-鿿-]+", "-", s).strip("-").lower()
    return (s[:max_len] or "untitled").strip("-")


@dataclass(frozen=True)
class InboxReport:
    added: int = 0
    skipped_dup: int = 0
    skipped_empty: int = 0
    skipped_error: int = 0
    quarantined: list[str] = field(default_factory=list)


def ingest_inbox(
    inbox_dir: Path, corpus_dir: Path, manifest_path: Path, category: str, publisher: str
) -> InboxReport:
    existing_hashes = {m.content_hash for m in load_manifest(manifest_path).values()}
    added, dup, empty, error, quarantined = 0, 0, 0, 0, []
    new_metas: list[DocMeta] = []

    for path in sorted(inbox_dir.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        try:
            doc = parse_file(path)
        except ParseError:
            # 脏文件（如损坏的 pdf）计数跳过，不中断整批收集
            error += 1
            continue
        if not doc.text:
            empty += 1
            continue
        if scan_sensitive(doc.text):
            quarantined.append(path.name)
            continue
        content_hash = sha256_text(doc.text)
        if content_hash in existing_hashes:
            dup += 1
            continue
        slug = slugify(doc.title)
        rel_path = Path(category) / f"{slug}.md"
        out_path = corpus_dir / rel_path
        if out_path.exists():
            # slug 撞车防御：走到这里 content_hash 必为新（相同则上面已判重），
            # 即目标文件属于另一份内容不同的文档，追加哈希尾 6 位区分
            rel_path = Path(category) / f"{slug}-{content_hash[-6:]}.md"
            out_path = corpus_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(f"# {doc.title}\n\n{doc.text}\n", encoding="utf-8")
        new_metas.append(
            DocMeta(
                doc_id=doc_id_from(f"inbox/{path.name}"),
                title=doc.title,
                source_url=f"inbox/{path.name}",
                publisher=publisher,
                publish_date=doc.publish_date,
                category=category,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                content_hash=content_hash,
                file_path=rel_path.as_posix(),
            )
        )
        existing_hashes.add(content_hash)
        added += 1

    append_manifest(manifest_path, new_metas)
    return InboxReport(
        added=added,
        skipped_dup=dup,
        skipped_empty=empty,
        skipped_error=error,
        quarantined=quarantined,
    )
