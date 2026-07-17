from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParsedDoc:
    title: str
    text: str
    publish_date: str = "unknown"
    publisher: str = ""


class ParseError(Exception):
    """解析失败的统一异常，携带文件路径与原始原因。"""


def _read_html_text(path: Path) -> str:
    """读取 html 文件，兼容高校老网站的 GBK/GB2312 编码（gb18030 是其超集）。"""
    raw = path.read_bytes()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_html(raw: str, fallback_title: str) -> ParsedDoc:
    import trafilatura

    text = trafilatura.extract(raw, include_comments=False, include_tables=True) or ""
    meta = trafilatura.extract_metadata(raw)
    title = fallback_title
    if meta and meta.title:
        # 空白标题不覆盖 fallback
        title = meta.title.strip() or fallback_title
    # trafilatura 不同版本的 metadata 可能没有 date 属性或为 None，统一兜底
    date = getattr(meta, "date", None) or "unknown"
    return ParsedDoc(title=title, text=text.strip(), publish_date=date)


def parse_pdf(path: Path) -> ParsedDoc:
    """解析 PDF。契约：扫描件/加密 PDF 返回空 text，由下游按空文档处理，不视为解析错误。"""
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
    text_parts = [p.text for p in d.paragraphs if p.text.strip()]
    # 政策文件常用表格承载关键信息（金额、条件），需一并抽取
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                text_parts.append(" | ".join(cells))
    return ParsedDoc(title=path.stem, text="\n".join(text_parts).strip())


def parse_file(path: Path) -> ParsedDoc:
    """按后缀分发解析。

    不支持的后缀抛 ValueError；文件损坏等脏数据统一包装为 ParseError。
    下游 inbox 对两者都按错误计数跳过。
    """
    suffix = path.suffix.lower()
    if suffix not in (".html", ".htm", ".pdf", ".docx", ".md"):
        raise ValueError(f"不支持的文件类型: {path.name}")
    try:
        if suffix in (".html", ".htm"):
            return parse_html(_read_html_text(path), path.stem)
        if suffix == ".pdf":
            return parse_pdf(path)
        if suffix == ".docx":
            return parse_docx(path)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        # md 以首个一级标题为文档标题，无则回退文件名
        title = path.stem
        m = re.search(r"(?m)^#\s+(.+)$", text)
        if m:
            title = m.group(1).strip()
        return ParsedDoc(title=title, text=text)
    except Exception as e:
        raise ParseError(f"解析失败: {path.name}: {e}") from e
