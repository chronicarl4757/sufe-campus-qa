from __future__ import annotations

import re

from sufe_qa.schema import Chunk

ARTICLE_RE = re.compile(r"(?m)^(第[一二三四五六七八九十百千零\d]+条)")
SECTION_RE = re.compile(r"(?m)^([一二三四五六七八九十]+[、．.])")


def _structural_units(text: str) -> list[tuple[str, str]]:
    """优先按'第X条'切，其次'一、'级标题；无结构返回单单元。heading 取标记词。"""
    for pattern in (ARTICLE_RE, SECTION_RE):
        parts = pattern.split(text)
        if len(parts) >= 3:
            units: list[tuple[str, str]] = []
            head, body = parts[0].strip(), parts[1:]
            if head:
                units.append(("", head))
            for i in range(0, len(body) - 1, 2):
                marker, content = body[i], body[i + 1]
                units.append((marker.strip(), (marker + content).strip()))
            return units
    return [("", text.strip())]


def _pack(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text else []
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        pieces.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return pieces


def split_document(
    text: str, doc_id: str, metadata: dict, max_chars: int = 480, overlap: int = 50
) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for heading, unit in _structural_units(text):
        for piece in _pack(unit, max_chars, overlap):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}:{idx}",
                    doc_id=doc_id,
                    chunk_index=idx,
                    heading_path=heading,
                    text=piece,
                    metadata=dict(metadata),
                )
            )
            idx += 1
    return chunks
