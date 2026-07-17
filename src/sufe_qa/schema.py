"""语料数据模型：文档元数据、切块结构，以及 manifest 的读写。

manifest 是一份 JSONL 文件，每行一条 DocMeta 记录；同一 doc_id 可能因内容更新
出现多次，加载时以文件中最后一条为准（last wins）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sufe_qa.config import CATEGORIES


@dataclass(frozen=True)
class DocMeta:
    doc_id: str
    title: str
    source_url: str
    publisher: str
    publish_date: str  # ISO 日期或 "unknown"
    category: str
    fetched_at: str
    content_hash: str
    file_path: str  # 相对 corpus_dir 的路径

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"非法分类: {self.category}")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # f"{doc_id}:{chunk_index}"
    doc_id: str
    chunk_index: int
    heading_path: str
    text: str
    metadata: dict = field(default_factory=dict)


def sha256_text(text: str) -> str:
    """正文内容哈希，用于判断文档是否变化。"""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def doc_id_from(source_url: str, title: str) -> str:
    """由来源 URL 与标题生成稳定 doc_id。"""
    return hashlib.sha256(f"{source_url}|{title}".encode("utf-8")).hexdigest()[:12]


def append_manifest(manifest_path: Path, metas: list[DocMeta]) -> None:
    """以 JSONL 形式追加写入 manifest（每行一条 DocMeta）。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as f:
        for m in metas:
            f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")


def load_manifest(manifest_path: Path) -> dict[str, DocMeta]:
    """doc_id -> DocMeta；同 doc_id 以文件中最后一条为准。"""
    if not manifest_path.exists():
        return {}
    out: dict[str, DocMeta] = {}
    with manifest_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                out[d["doc_id"]] = DocMeta(**d)
    return out
