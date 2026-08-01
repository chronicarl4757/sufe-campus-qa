"""data/curated/ 人工精编指南入库：解析 YAML front matter，子目录映射知识库分类。

curated/ 与抓取的原始网页不同，是运营者手工撰写、带版本元数据的一等来源：
- front matter（title/document_kind/verified_at/scope_unit 等）只映射 manifest
  元数据，不进入正文与嵌入向量；
- 子目录名按 _SUBDIR_CATEGORY 映射到知识库分类，未列出的归入"其他"；
- publish_date 取 verified_at（人工验证日期即该指南的时效锚点）；
- 不做敏感信息隔离：服务电话等联系方式是人工编写的有效内容，
  scan_sensitive 隔离针对的是抓取的第三方页面（如公示名单）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sufe_qa.ingest.inbox import slugify
from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text

# curated 子目录 -> 知识库分类（须在 config.CATEGORIES 内；未列出的子目录归"其他"）
_SUBDIR_CATEGORY = {
    "campus_services": "校园生活",
    "freshman_knowhow": "校园生活",
    "students_affairs": "学工事务",
}

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


@dataclass(frozen=True)
class CuratedReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)  # 空文件或剥掉头后无正文


def _split_front_matter(text: str) -> tuple[dict, str]:
    """拆 YAML front matter；无头部或解析失败时返回空 dict 与原文。"""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, text[m.end() :].strip()


def ingest_curated(curated_dir: Path, corpus_dir: Path, manifest_path: Path) -> CuratedReport:
    """把 data/curated/**/*.md 解析入库；doc_id 锚定 curated 相对路径，重复运行幂等。"""
    existing = load_manifest(manifest_path)
    added = updated = unchanged = 0
    skipped: list[str] = []
    new_metas: list[DocMeta] = []
    if not curated_dir.is_dir():
        return CuratedReport()

    for path in sorted(curated_dir.rglob("*.md")):
        rel = path.relative_to(curated_dir)
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            skipped.append(rel.as_posix())  # template.md 等空模板
            continue
        fm, body = _split_front_matter(raw)
        if not body:
            skipped.append(rel.as_posix())
            continue
        title = str(fm.get("title") or "").strip() or path.stem
        subdir = rel.parts[0] if len(rel.parts) > 1 else ""
        category = _SUBDIR_CATEGORY.get(subdir, "其他")
        # yaml 会把 2026-08-01 解析成 date 对象，str() 后仍为 YYYY-MM-DD
        publish_date = str(fm.get("verified_at") or "unknown")
        publisher = str(fm.get("scope_unit") or fm.get("editor") or "人工整理")
        doc_id = doc_id_from(f"curated/{rel.as_posix()}")
        final = f"# {title}\n\n{body}\n"
        content_hash = sha256_text(final)

        old = existing.get(doc_id)
        if old and old.content_hash == content_hash:
            unchanged += 1
            continue
        if old and old.file_path:
            rel_path = Path(old.file_path)  # 同文档更新：沿用旧路径，不留孤儿文件
        else:
            rel_path = Path(category) / f"{slugify(title)}.md"
            if (corpus_dir / rel_path).exists():
                rel_path = Path(category) / f"{slugify(title)}-{content_hash[-6:]}.md"
        out_path = corpus_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final, encoding="utf-8")
        new_metas.append(
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url=f"curated/{rel.as_posix()}",
                publisher=publisher,
                publish_date=publish_date,
                category=category,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                content_hash=content_hash,
                file_path=rel_path.as_posix(),
                document_type=str(fm.get("document_kind") or "curated_guide"),
                parse_status="ok",
                quality_status="accepted",
            )
        )
        if old:
            updated += 1
        else:
            added += 1

    append_manifest(manifest_path, new_metas)
    return CuratedReport(added=added, updated=updated, unchanged=unchanged, skipped=skipped)
