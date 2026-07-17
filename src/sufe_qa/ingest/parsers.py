from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParsedDoc:
    title: str
    text: str
    publish_date: str = "unknown"
    publisher: str = ""


def parse_html(raw: str, fallback_title: str) -> ParsedDoc:
    import trafilatura

    text = trafilatura.extract(raw, include_comments=False, include_tables=True) or ""
    meta = trafilatura.extract_metadata(raw)
    title = fallback_title
    if meta and meta.title:
        title = meta.title.strip()
    # trafilatura 不同版本的 metadata 可能没有 date 属性或为 None，统一兜底
    date = getattr(meta, "date", None) or "unknown"
    return ParsedDoc(title=title, text=text.strip(), publish_date=date)


def parse_pdf(path: Path) -> ParsedDoc:
    import fitz  # pymupdf

    doc = fitz.open(str(path))
    try:
        text = "\n".join(page.get_text().strip() for page in doc)
    finally:
        doc.close()
    return ParsedDoc(title=path.stem, text=text.strip())


def parse_docx(path: Path) -> ParsedDoc:
    from docx import Document

    d = Document(str(path))
    text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
    return ParsedDoc(title=path.stem, text=text.strip())


def parse_file(path: Path) -> ParsedDoc:
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        return parse_html(path.read_text(encoding="utf-8", errors="ignore"), path.stem)
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".md":
        return ParsedDoc(title=path.stem, text=path.read_text(encoding="utf-8").strip())
    raise ValueError(f"不支持的文件类型: {path.name}")
