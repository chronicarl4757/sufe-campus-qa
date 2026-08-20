from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sufe_qa.config import CATEGORIES
from sufe_qa.indexing.collections import collection_for_kind
from sufe_qa.ingest.classification import (
    classify_document_kind,
    normalize_policy_name,
    standardize_topic_key,
)
from sufe_qa.ingest.lifecycle import series_key_for, temporal_class_for
from sufe_qa.ingest.parsers import ParseError, parse_file
from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text

_ID_PATTERN = re.compile(r"\d{17}[\dXx]")
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
SENSITIVE_PATTERNS = [_ID_PATTERN, _PHONE_PATTERN]

# 官方公开联系方式上下文（规格 §十七）：号码前 N 字符内命中即 official_public_contact，
# 不使整篇 quarantine；私人语境（紧急联系人/家庭电话等）显式优先排除。
# 匹配前对窗口去空白：覆盖“电 话：”“电话：\n021-…/139…”等真实排版。
_PUBLIC_CONTACT_CONTEXT = (
    "联系电话",
    "咨询电话",
    "招生咨询",
    "报名咨询",
    "项目咨询",
    "咨询老师",
    "联系老师",
    "招生办公室",
    "招生办",
    "项目办公室",
    "学院办公室",
    "办公室电话",
    "联系方式",
    "联系我们",
    "咨询邮箱",
    "电子邮箱",
    "咨询：",
    "手机：",
    "电话：",
    "电话:",
)
_PRIVATE_CONTACT_CONTEXT = (
    "紧急联系人",
    "家庭电话",
    "家庭住址",
    "家长",
    "亲属",
    "本人身份证",
    "银行卡",
)
_PUBLIC_CONTACT_WINDOW = 60


def _is_public_contact(text: str, pos: int) -> bool:
    """号码前窗口内是否官方公开联系方式语境；私人语境优先判私。"""
    window = re.sub(r"\s+", "", text[max(0, pos - _PUBLIC_CONTACT_WINDOW) : pos])
    if any(k in window for k in _PRIVATE_CONTACT_CONTEXT):
        return False
    return any(k in window for k in _PUBLIC_CONTACT_CONTEXT)


def scan_sensitive(
    text: str, *, allow_phone: bool = False, allow_public_contact: bool = False
) -> list[str]:
    """返回命中的敏感串。

    - 身份证号一律隔离（任何来源都不放行）；
    - allow_phone：权威服务指南整体放行电话号码（既有行为）；
    - allow_public_contact（规格 §十五-§十九）：官方来源正文中带公开联系方式
      上下文（咨询电话/招生办公室/联系老师…）的手机号按 official_public_contact 放行，
      无上下文或私人语境的手机号继续隔离。
    """
    ids = [m.group() for m in _ID_PATTERN.finditer(text)]
    phones = []
    for m in _PHONE_PATTERN.finditer(text):
        if allow_phone:
            continue
        if allow_public_contact and _is_public_contact(text, m.start()):
            continue
        phones.append(m.group())
    return ids + phones


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
    inbox_dir: Path,
    corpus_dir: Path,
    manifest_path: Path,
    category: str,
    publisher: str,
    source_urls: dict[str, str] | None = None,
) -> InboxReport:
    """收集 inbox 文件入库。source_urls：文件名 -> 真实来源 URL（爬虫入口用）；
    提供后 doc_id 与 source_url 锚定真实 URL，重爬同 URL 视为同文档原地更新。"""
    # 入口先校验：非法 category（含 "../escape" 路径穿越）在写盘前拒绝
    if category not in CATEGORIES:
        raise ValueError(f"非法分类: {category}")
    existing_by_id = load_manifest(manifest_path)
    existing_hashes = {m.content_hash for m in existing_by_id.values()}
    added, dup, empty, error, quarantined = 0, 0, 0, 0, []
    new_metas: list[DocMeta] = []

    for path in sorted(inbox_dir.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        try:
            doc = parse_file(path)
        except (ParseError, ValueError):
            # 脏文件（如损坏的 pdf）或不支持后缀（用户误投，如 .exe/.zip）
            # 都按错误计数跳过，不中断整批收集
            error += 1
            continue
        if not doc.text:
            empty += 1
            continue
        if scan_sensitive(doc.text):
            quarantined.append(path.name)
            continue
        # hash 对齐最终落盘内容，保证 manifest 与磁盘文件一致
        final = f"# {doc.title}\n\n{doc.text}\n"
        content_hash = sha256_text(final)
        if content_hash in existing_hashes:
            dup += 1
            continue
        doc_id = doc_id_from((source_urls or {}).get(path.name, f"inbox/{path.name}"))
        slug = slugify(doc.title)
        rel_path = Path(category) / f"{slug}.md"
        if (corpus_dir / rel_path).exists():
            # slug 撞车或同一来源出现新正文时写不可变版本；旧 manifest 行仍可回看/回退。
            rel_path = Path(category) / f"{slug}-{content_hash[-6:]}.md"
        out_path = corpus_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final, encoding="utf-8")
        document_kind = classify_document_kind(doc.title, doc.text)
        if document_kind == "incomplete":
            document_kind = "manual"
        new_metas.append(
            DocMeta(
                doc_id=doc_id,
                title=doc.title,
                source_url=(source_urls or {}).get(path.name, f"inbox/{path.name}"),
                publisher=publisher,
                publish_date=doc.publish_date,
                category=category,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                content_hash=content_hash,
                file_path=rel_path.as_posix(),
                document_kind=document_kind,
                policy_name=normalize_policy_name(doc.title),
                topic_key=standardize_topic_key(doc.title, normalize_policy_name(doc.title)),
                source_type="manual_upload",
                index_collection=collection_for_kind(document_kind, "active") or "none",
                temporal_class=temporal_class_for(document_kind, doc.title),
                series_key=series_key_for(doc.title, publisher=publisher),
                retention_status="active",
                retention_reason="manual_upload",
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
