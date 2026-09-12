"""回补被拦的 .xls 附件：raw 缓存按 binary_hash 匹配，xlrd 纯 Python 解析后入库。

背景：早期爬取时 .xls 不支持解析（unsupported_format 归档）；attachment_parsers 现已支持
经 xlrd（部署环境无需 LibreOffice）。本脚本把 raw 缓存里的二进制重新解析写回 corpus。

用法：.venv/bin/python scripts/backfill_legacy_xls.py [--apply]
"""

import hashlib
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from sufe_qa.ingest.attachment_parsers import parse_attachment  # noqa: E402
from sufe_qa.ingest.classification import classify_document_kind  # noqa: E402
from sufe_qa.schema import append_manifest, load_manifest, sha256_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
MANIFEST = CORPUS / "manifest.jsonl"
RAW = ROOT / "data" / "raw"


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def main() -> None:
    apply = "--apply" in sys.argv
    latest = load_manifest(MANIFEST)
    blocked = {
        d.binary_hash: d
        for d in latest.values()
        if d.document_type == "attachment"
        and d.parse_status == "unsupported_format"
        and (d.attachment_name or "").lower().endswith(".xls")
        and d.binary_hash
    }
    print(f"待回补 .xls 附件: {len(blocked)}")

    # raw 缓存建 hash 索引（与管道同口径：截断 16 位）
    raw_by_hash: dict[str, Path] = {}
    for path in RAW.rglob("*.xls"):
        if path.suffix.lower() != ".xls":
            continue
        raw_by_hash[hashlib.sha256(path.read_bytes()).hexdigest()[:16]] = path

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = []
    matched = parsed = 0
    for bhash, meta in blocked.items():
        raw_path = raw_by_hash.get(bhash)
        if raw_path is None:
            continue
        matched += 1
        result = parse_attachment(meta.attachment_name or "attachment.xls", raw_path.read_bytes())
        if result.parse_status != "ok" or not result.text.strip():
            print(f"  解析失败: {meta.attachment_name} -> {result.parse_status} {result.notes[:1]}")
            continue
        parsed += 1
        title = meta.attachment_name or meta.title
        body = f"## 附件正文\n\n{result.text}\n"
        final = f"# {title}\n\n{body}"
        rel = Path(meta.category) / f"{meta.doc_id}.md"
        out = CORPUS / rel
        if apply:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(final, encoding="utf-8")
        kind = classify_document_kind(
            title, body, quality_status="accepted", has_valid_attachment=False
        )
        records.append(
            replace(
                meta,
                quality_status="accepted",
                retention_status="active",
                file_path=rel.as_posix(),
                content_hash=sha256_text(final),
                text_hash=sha256_text(_squash(body)),
                parse_status="ok",
                document_kind=kind,
                retention_reason="xls_backfill:xlrd 解析回补",
                index_collection="",
                fetched_at=now,
            )
        )
    print(f"raw 匹配 {matched}，解析成功 {parsed}，待写入 {len(records)}")
    if not apply:
        print("DRY-RUN，加 --apply 生效")
        return
    append_manifest(MANIFEST, records)
    with (ROOT / "data" / "admin_actions.jsonl").open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(
                json.dumps(
                    {
                        "ts": now,
                        "doc_id": r.doc_id,
                        "title": r.title,
                        "action": "xls_backfill",
                        "reason": r.retention_reason,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print("已应用")


if __name__ == "__main__":
    main()
