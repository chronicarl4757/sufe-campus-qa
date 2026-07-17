# 上财校园问答智能体 M1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 M1——语料采集/解析、增量索引、混合检索、CLI 问答闭环，产出本地可用的 `sufe-qa ask` 命令。

**Architecture:** 见 `docs/superpowers/specs/2026-07-17-sufe-campus-qa-design.md`。离线侧：inbox/crawler → 解析 → corpus+manifest → 结构切分 → BGE-M3 → Chroma（增量 upsert）。在线侧：向量 top-20 + BM25 top-20 → RRF → DeepSeek 严格引用生成 → 来源卡片。低置信直接拒答，不走 LLM。

**Tech Stack:** Python 3.11, uv, ChromaDB, sentence-transformers(BGE-M3), rank_bm25+jieba, trafilatura/pymupdf/python-docx, openai(DeepSeek 兼容协议), pytest, ruff。

**Scope:** 仅 M1。M2（Gradio UI/评测集/拒答标定）、M3（HF Spaces）、M4（提交材料）另行立项。

**设计澄清（相对 spec 的一处细化）:** 拒答判定 = 向量路先按 `vector_min_similarity` 过滤 + BM25 路要求分数 > 0；融合后为空 → 拒答。比 spec 的"纯 RRF 阈值"更稳健（Chroma 无论相关与否都会返回 top-k，单靠 RRF 分无法区分"弱相关"与"完全无关"）。

---

## File Map

- `pyproject.toml`, `.env.example`, `src/sufe_qa/__init__.py` — 工程骨架
- `src/sufe_qa/config.py` — Settings（路径/阈值/模型名），`.env` 加载
- `src/sufe_qa/schema.py` — DocMeta/Chunk dataclass，manifest.jsonl 读写，content_hash
- `src/sufe_qa/ingest/parsers.py` — html/pdf/docx/md → ParsedDoc
- `src/sufe_qa/ingest/inbox.py` — 扫描 inbox → corpus + manifest，敏感信息拦截
- `src/sufe_qa/crawler/crawl.py` + `src/sufe_qa/crawler/seeds.yaml` — 种子站抓取（robots + 限速）
- `src/sufe_qa/ingest/splitter.py` — 结构感知切分
- `src/sufe_qa/indexing/indexer.py` — 增量索引（Embedder 协议 + BgeEmbedder）
- `src/sufe_qa/retrieve/hybrid.py` — 混合检索 RRF
- `src/sufe_qa/generate/prompts.py` / `llm.py` / `answer.py` — 生成与引用组装
- `src/sufe_qa/cli.py` — `sufe-qa ingest|index|ask|crawl`
- `tests/` — 每个模块一个测试文件

**铁律：除 `BgeEmbedder.__init__` 内部外，任何模块不得 import `sentence_transformers`/`torch`**（测试与 CLI 的轻量路径都不应拖着 2GB 依赖）。

---

## Task 1: 工程骨架

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/sufe_qa/__init__.py`
- Create: `src/sufe_qa/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
from sufe_qa.config import CATEGORIES, load_settings


def test_categories_cover_competition_scope():
    assert CATEGORIES == ("评奖评优", "奖助学金", "推免升学", "实习就业", "学工事务", "校园生活", "其他")


def test_load_settings_creates_data_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path / "data"))
    s = load_settings()
    assert s.corpus_dir.exists()
    assert s.inbox_dir.exists()
    assert s.vector_top_k == 20 and s.fusion_top_n == 8
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_config.py -q`
Expected: 收集失败，`ModuleNotFoundError: No module named 'sufe_qa'`

- [ ] **Step 3: 实现**

```toml
# pyproject.toml
[project]
name = "sufe-campus-qa"
version = "0.1.0"
description = "上财校园问答智能体（SCAI 大赛作品）"
requires-python = ">=3.11"
dependencies = [
    "chromadb>=0.6",
    "sentence-transformers>=3.0",
    "rank-bm25>=0.2.2",
    "jieba>=0.42.1",
    "trafilatura>=1.9",
    "pymupdf>=1.24",
    "python-docx>=1.1",
    "openai>=1.40",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.6"]

[project.scripts]
sufe-qa = "sufe_qa.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/sufe_qa"]

[tool.ruff]
line-length = 100
```

```
# .env.example
DEEPSEEK_API_KEY=sk-your-key-here
```

```python
# src/sufe_qa/__init__.py
"""上财校园问答智能体。"""
__version__ = "0.1.0"
```

```python
# src/sufe_qa/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CATEGORIES = ("评奖评优", "奖助学金", "推免升学", "实习就业", "学工事务", "校园生活", "其他")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    corpus_dir: Path
    inbox_dir: Path
    chroma_dir: Path
    manifest_path: Path
    embedding_model: str = "BAAI/bge-m3"
    collection_name: str = "sufe_campus_qa"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    vector_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    fusion_top_n: int = 8
    vector_min_similarity: float = 0.45


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.getenv("SUFE_QA_DATA_DIR", str(PROJECT_ROOT / "data")))
    s = Settings(
        data_dir=data_dir,
        corpus_dir=data_dir / "corpus",
        inbox_dir=data_dir / "inbox",
        chroma_dir=data_dir / "chroma_db",
        manifest_path=data_dir / "corpus" / "manifest.jsonl",
    )
    s.corpus_dir.mkdir(parents=True, exist_ok=True)
    s.inbox_dir.mkdir(parents=True, exist_ok=True)
    return s


def get_api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY：复制 .env.example 为 .env 并填写")
    return key
```

- [ ] **Step 4: 运行确认通过 + 环境落锁**

Run: `uv sync && uv run pytest tests/test_config.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example src/sufe_qa/__init__.py src/sufe_qa/config.py tests/test_config.py uv.lock
git commit -m "feat: 工程骨架与配置加载"
```

---

## Task 2: 语料 schema 与 manifest

**Files:**
- Create: `src/sufe_qa/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_schema.py
import pytest

from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text


def _meta(content_hash: str = "sha256:a", title: str = "细则") -> DocMeta:
    return DocMeta(
        doc_id=doc_id_from("https://x.sufe.edu.cn/1", title),
        title=title,
        source_url="https://x.sufe.edu.cn/1",
        publisher="学生工作部",
        publish_date="2025-10-12",
        category="奖助学金",
        fetched_at="2026-07-17T00:00:00",
        content_hash=content_hash,
        file_path="奖助学金/xi-ze.md",
    )


def test_invalid_category_rejected():
    with pytest.raises(ValueError, match="非法分类"):
        DocMeta(**{**_meta().__dict__, "category": "不存在类"})


def test_hash_and_doc_id_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")
    assert doc_id_from("u", "t") == doc_id_from("u", "t")
    assert doc_id_from("u", "t") != doc_id_from("u", "t2")


def test_manifest_roundtrip_and_last_wins(tmp_path):
    p = tmp_path / "manifest.jsonl"
    m1, m2 = _meta("sha256:1"), _meta("sha256:2")
    append_manifest(p, [m1])
    append_manifest(p, [m2])  # 同 doc_id 新版本
    loaded = load_manifest(p)
    assert len(loaded) == 1
    assert loaded[m1.doc_id].content_hash == "sha256:2"
    assert loaded[m1.doc_id].file_path == "奖助学金/xi-ze.md"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_schema.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.schema`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/schema.py
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
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def doc_id_from(source_url: str, title: str) -> str:
    return hashlib.sha256(f"{source_url}|{title}".encode("utf-8")).hexdigest()[:12]


def append_manifest(manifest_path: Path, metas: list[DocMeta]) -> None:
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
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_schema.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/schema.py tests/test_schema.py
git commit -m "feat: 语料 schema 与 manifest 读写"
```

---

## Task 3: 文档解析器

**Files:**
- Create: `src/sufe_qa/ingest/__init__.py`
- Create: `src/sufe_qa/ingest/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_parsers.py
from pathlib import Path

import pytest

from sufe_qa.ingest.parsers import parse_file, parse_html


def test_parse_html_extracts_text_and_title():
    html = """<html><head><title>关于开展2025年奖学金评审的通知</title></head>
    <body><article><p>各学院：现将评审安排通知如下。</p><p>申请条件如下。</p></article></body></html>"""
    doc = parse_html(html, "fallback")
    assert "申请条件" in doc.text
    assert "奖学金" in doc.title


def test_parse_pdf(tmp_path):
    import fitz

    p = tmp_path / "rule.pdf"
    d = fitz.open()
    page = d.new_page()
    page.insert_text((72, 72), "第一条 本办法适用于全日制在校生。")
    d.save(str(p))
    d.close()
    doc = parse_file(p)
    assert "第一条" in doc.text
    assert doc.title == "rule"


def test_parse_docx(tmp_path):
    from docx import Document

    p = tmp_path / "notice.docx"
    d = Document()
    d.add_paragraph("推免工作将于九月启动。")
    d.save(str(p))
    doc = parse_file(p)
    assert "推免" in doc.text


def test_parse_md_passthrough(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("# 学工指南\n内容正文。", encoding="utf-8")
    doc = parse_file(p)
    assert "学工指南" in doc.text


def test_unsupported_suffix(tmp_path):
    p = tmp_path / "a.exe"
    p.write_bytes(b"x")
    with pytest.raises(ValueError, match="不支持"):
        parse_file(p)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_parsers.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.ingest`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/ingest/__init__.py
```

```python
# src/sufe_qa/ingest/parsers.py
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
    date = meta.date if meta and meta.date else "unknown"
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
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_parsers.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/ingest/ tests/test_parsers.py
git commit -m "feat: html/pdf/docx/md 统一解析器"
```

---

## Task 4: inbox 收集器（手动投放入口）

**Files:**
- Create: `src/sufe_qa/ingest/inbox.py`
- Test: `tests/test_inbox.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_inbox.py
from sufe_qa.ingest.inbox import ingest_inbox, scan_sensitive
from sufe_qa.schema import load_manifest


def test_scan_sensitive_finds_id_and_phone():
    hits = scan_sensitive("张三 身份证号 310101199901011234 电话 13812345678")
    assert len(hits) == 2
    assert scan_sensitive("普通政策文本") == []


def test_ingest_writes_corpus_and_manifest(tmp_path):
    inbox, corpus, manifest = tmp_path / "inbox", tmp_path / "corpus", tmp_path / "corpus/manifest.jsonl"
    inbox.mkdir()
    (inbox / "rule.md").write_text("# 国家奖学金评审细则\n第一条 奖励标准为每生每年8000元。", encoding="utf-8")
    report = ingest_inbox(inbox, corpus, manifest, category="奖助学金", publisher="学生工作部")
    assert report.added == 1 and report.skipped_dup == 0 and report.quarantined == []
    loaded = load_manifest(manifest)
    assert len(loaded) == 1
    meta = next(iter(loaded.values()))
    assert meta.category == "奖助学金" and "国家奖学金" in meta.title
    assert (corpus / meta.file_path).exists()


def test_ingest_dedup_by_content_hash(tmp_path):
    inbox, corpus, manifest = tmp_path / "inbox", tmp_path / "corpus", tmp_path / "corpus/manifest.jsonl"
    inbox.mkdir()
    (inbox / "a.md").write_text("同一份文件内容", encoding="utf-8")
    (inbox / "b.md").write_text("同一份文件内容", encoding="utf-8")  # 不同文件名, 相同内容
    report = ingest_inbox(inbox, corpus, manifest, category="其他", publisher="手动投放")
    assert report.added == 1 and report.skipped_dup == 1


def test_ingest_quarantines_sensitive(tmp_path):
    inbox, corpus, manifest = tmp_path / "inbox", tmp_path / "corpus", tmp_path / "corpus/manifest.jsonl"
    inbox.mkdir()
    (inbox / "leak.md").write_text("名单：李四 310101199901011234", encoding="utf-8")
    report = ingest_inbox(inbox, corpus, manifest, category="其他", publisher="手动投放")
    assert report.added == 0 and report.quarantined == ["leak.md"]
    assert load_manifest(manifest) == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_inbox.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.ingest.inbox`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/ingest/inbox.py
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sufe_qa.ingest.parsers import parse_file
from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text

SENSITIVE_PATTERNS = [
    re.compile(r"\d{17}[\dXx]"),        # 身份证
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
    quarantined: list[str] = field(default_factory=list)


def ingest_inbox(inbox_dir: Path, corpus_dir: Path, manifest_path: Path,
                 category: str, publisher: str) -> InboxReport:
    existing_hashes = {m.content_hash for m in load_manifest(manifest_path).values()}
    added, dup, empty, quarantined = 0, 0, 0, []
    new_metas: list[DocMeta] = []

    for path in sorted(inbox_dir.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        doc = parse_file(path)
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
        title = doc.title
        slug = slugify(title)
        rel_path = Path(category) / f"{slug}.md"
        out_path = corpus_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(f"# {doc.title}\n\n{doc.text}\n", encoding="utf-8")
        new_metas.append(DocMeta(
            doc_id=doc_id_from(f"inbox/{path.name}", doc.title),
            title=doc.title,
            source_url=f"inbox/{path.name}",
            publisher=publisher,
            publish_date=doc.publish_date,
            category=category,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            content_hash=content_hash,
            file_path=rel_path.as_posix(),
        ))
        existing_hashes.add(content_hash)
        added += 1

    append_manifest(manifest_path, new_metas)
    return InboxReport(added=added, skipped_dup=dup, skipped_empty=empty, quarantined=quarantined)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_inbox.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/ingest/inbox.py tests/test_inbox.py
git commit -m "feat: inbox 收集器（去重+敏感信息拦截）"
```

---

## Task 5: 种子站爬虫

**Files:**
- Create: `src/sufe_qa/crawler/__init__.py`
- Create: `src/sufe_qa/crawler/crawl.py`
- Create: `src/sufe_qa/crawler/seeds.yaml`
- Test: `tests/test_crawl.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_crawl.py
from pathlib import Path

from sufe_qa.crawler.crawl import Seed, extract_links, load_seeds


def _seed() -> Seed:
    return Seed(
        name="t", list_url="https://www.sufe.edu.cn/notice/list.htm",
        link_selector="ul.news_list li a", url_prefix="https://www.sufe.edu.cn/",
        category="学工事务", publisher="上海财经大学", max_pages=2,
    )


def test_extract_links_filters_prefix_and_dedups():
    html = """<ul class="news_list">
      <li><a href="/notice/1.htm">通知一</a></li>
      <li><a href="/notice/1.htm">通知一(重复)</a></li>
      <li><a href="https://evil.com/x">外部</a></li>
      <li><a href="/notice/2.htm">通知二</a></li>
      <li><a href="/notice/3.htm">通知三(超max_pages)</a></li>
    </ul>"""
    links = extract_links(html, _seed())
    assert links == ["https://www.sufe.edu.cn/notice/1.htm", "https://www.sufe.edu.cn/notice/2.htm"]


def test_load_seeds(tmp_path):
    y = tmp_path / "seeds.yaml"
    y.write_text("""seeds:
  - name: a
    list_url: "https://www.sufe.edu.cn/x/list.htm"
    link_selector: "li a"
    url_prefix: "https://www.sufe.edu.cn/"
    category: "学工事务"
    publisher: "上海财经大学"
    max_pages: 5
""", encoding="utf-8")
    seeds = load_seeds(y)
    assert len(seeds) == 1 and seeds[0].max_pages == 5 and seeds[0].category == "学工事务"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_crawl.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.crawler`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/crawler/__init__.py
```

```python
# src/sufe_qa/crawler/crawl.py
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup

UA = "sufe-qa-bot (student research project)"


@dataclass(frozen=True)
class Seed:
    name: str
    list_url: str
    link_selector: str  # 列表页上文章链接的 CSS 选择器
    url_prefix: str     # 只跟进此前缀的链接
    category: str
    publisher: str
    max_pages: int = 20


def load_seeds(path: Path) -> list[Seed]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Seed(**s) for s in data["seeds"]]


def allowed_by_robots(url: str, ua: str = UA) -> bool:
    parsed = urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return False  # robots 不可达时保守放行前的拒绝策略: 不抓
    return rp.can_fetch(ua, url)


def extract_links(html: str, seed: Seed) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for a in soup.select(seed.link_selector):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(seed.list_url, str(href))
        if full.startswith(seed.url_prefix):
            out.append(full)
    return list(dict.fromkeys(out))[: seed.max_pages]


def crawl_seed(seed: Seed, delay: float = 1.0, client: httpx.Client | None = None) -> list[tuple[str, str]]:
    """返回 [(url, html)]；限速 delay 秒/页，逐 URL 检查 robots。"""
    client = client or httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA})
    if not allowed_by_robots(seed.list_url):
        raise RuntimeError(f"robots.txt 禁止抓取: {seed.list_url}")
    list_html = client.get(seed.list_url).text
    urls = extract_links(list_html, seed)
    pages: list[tuple[str, str]] = []
    for u in urls:
        if not allowed_by_robots(u):
            continue
        r = client.get(u)
        r.raise_for_status()
        pages.append((u, r.text))
        time.sleep(delay)
    return pages
```

```yaml
# src/sufe_qa/crawler/seeds.yaml
# 种子清单。执行时先验证各站栏目页 URL 与 CSS 选择器再启用（见 Task 10 smoke）。
seeds: []
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_crawl.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/crawler/ tests/test_crawl.py
git commit -m "feat: 种子站爬虫（robots 合规+限速）"
```

---

## Task 6: 结构感知切分器

**Files:**
- Create: `src/sufe_qa/ingest/splitter.py`
- Test: `tests/test_splitter.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_splitter.py
from sufe_qa.ingest.splitter import split_document

POLICY = """国家奖学金评审办法

第一条 为规范评审，制定本办法。奖励标准为每生每年8000元。
第二条 申请条件为热爱祖国、遵纪守法、成绩优异。
第三条 评审程序包括个人申请、学院初审、学校终审。
"""


def test_policy_splits_by_article():
    chunks = split_document(POLICY, "doc1", {"title": "国家奖学金评审办法"})
    assert len(chunks) == 4  # 前言(标题行) + 三条
    assert chunks[0].heading_path == ""
    assert chunks[1].heading_path == "第一条"
    assert "8000元" in chunks[1].text
    assert chunks[2].heading_path == "第二条"
    assert all(c.doc_id == "doc1" for c in chunks)
    assert [c.chunk_id for c in chunks] == ["doc1:0", "doc1:1", "doc1:2", "doc1:3"]


def test_plain_text_respects_max_chars():
    text = "这是一段没有结构的正文。" * 200  # ~2400 字
    chunks = split_document(text, "doc2", {}, max_chars=480, overlap=50)
    assert len(chunks) >= 5
    assert all(len(c.text) <= 480 + 50 for c in chunks)
    # 重叠: 相邻块共享尾部/首部片段
    assert chunks[0].text[-20:] in chunks[1].text


def test_metadata_propagated():
    chunks = split_document(POLICY, "doc3", {"title": "t", "category": "奖助学金"})
    assert all(c.metadata["category"] == "奖助学金" for c in chunks)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_splitter.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.ingest.splitter`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/ingest/splitter.py
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


def split_document(text: str, doc_id: str, metadata: dict,
                   max_chars: int = 480, overlap: int = 50) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for heading, unit in _structural_units(text):
        for piece in _pack(unit, max_chars, overlap):
            chunks.append(Chunk(
                chunk_id=f"{doc_id}:{idx}", doc_id=doc_id, chunk_index=idx,
                heading_path=heading, text=piece, metadata=dict(metadata),
            ))
            idx += 1
    return chunks
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_splitter.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/ingest/splitter.py tests/test_splitter.py
git commit -m "feat: 结构感知切分器（条款级+重叠回填）"
```

---

## Task 7: 增量索引

**Files:**
- Create: `src/sufe_qa/indexing/__init__.py`
- Create: `src/sufe_qa/indexing/indexer.py`
- Test: `tests/test_indexer.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_indexer.py
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
from sufe_qa.schema import DocMeta, append_manifest
from sufe_qa.config import Settings


def _settings(tmp_path) -> Settings:
    data = tmp_path / "data"
    return Settings(data_dir=data, corpus_dir=data / "corpus",
                    inbox_dir=data / "inbox", chroma_dir=data / "chroma",
                    manifest_path=data / "corpus" / "manifest.jsonl")


def _write_doc(s, doc_id, category, fname, text, title, content_hash):
    p = s.corpus_dir / category / fname
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    append_manifest(s.manifest_path, [DocMeta(
        doc_id=doc_id, title=title, source_url="inbox/x",
        publisher="学生工作部", publish_date="unknown", category=category,
        fetched_at="t", content_hash=content_hash,
        file_path=f"{category}/{fname}",
    )])


def test_first_build_indexes_all(tmp_path):
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    _write_doc(s, "docB", "推免升学", "b.md", "第一条 推免条件。", "推免办法", "sha256:bbbb")
    r = update_index(s, FakeEmbedder())
    assert (r.added_docs, r.updated_docs, r.deleted_docs) == (2, 0, 0)
    assert r.total_chunks >= 2


def test_second_run_noop(tmp_path):
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 奖学金标准。", "奖学金办法", "sha256:aaaa")
    update_index(s, FakeEmbedder())
    r = update_index(s, FakeEmbedder())
    assert (r.added_docs, r.updated_docs, r.deleted_docs) == (0, 0, 0)


def test_update_and_delete(tmp_path):
    s = _settings(tmp_path)
    _write_doc(s, "docA", "奖助学金", "a.md", "第一条 旧标准。", "奖学金办法", "sha256:aaaa")
    _write_doc(s, "docB", "推免升学", "b.md", "第一条 推免条件。", "推免办法", "sha256:bbbb")
    update_index(s, FakeEmbedder())
    # docA 改内容（同 doc_id 新 hash）；docB 从 manifest 移除
    p = s.corpus_dir / "奖助学金" / "a.md"
    p.write_text("第一条 新标准。增加条款。", encoding="utf-8")
    append_manifest(s.manifest_path, [DocMeta(
        doc_id="docA", title="奖学金办法", source_url="inbox/x", publisher="学生工作部",
        publish_date="unknown", category="奖助学金", fetched_at="t2",
        content_hash="sha256:cccc", file_path="奖助学金/a.md",
    )])
    lines = s.manifest_path.read_text(encoding="utf-8").splitlines()
    keep = [l for l in lines if '"docB"' not in l]
    s.manifest_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    r = update_index(s, FakeEmbedder())
    assert r.updated_docs == 1 and r.deleted_docs == 1 and r.added_docs == 0
```

注意：`update_index` 的 doc_id 取 manifest 记录里的 `doc_id` 字段本身。删除判定 = Chroma 中存在但 manifest 已没有该 doc_id；更新判定 = 同 doc_id 但 content_hash 变化。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_indexer.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.indexing`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/indexing/__init__.py
```

```python
# src/sufe_qa/indexing/indexer.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import chromadb

from sufe_qa.config import Settings
from sufe_qa.ingest.splitter import split_document
from sufe_qa.schema import load_manifest


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """确定性假向量：字符 3-gram 哈希到 64 维，仅用于测试。"""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for i in range(max(1, len(t) - 2)):
                g = t[i:i + 3]
                v[int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % self.dim] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


class BgeEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        from sentence_transformers import SentenceTransformer  # 仅此处置允许 import

        self._m = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._m.encode(texts, normalize_embeddings=True)]


@dataclass(frozen=True)
class IndexReport:
    added_docs: int
    updated_docs: int
    deleted_docs: int
    total_chunks: int


def update_index(settings: Settings, embedder: Embedder, full: bool = False) -> IndexReport:
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    if full:
        client.delete_collection(settings.collection_name)
    col = client.get_or_create_collection(settings.collection_name, metadata={"hnsw:space": "cosine"})

    manifest = load_manifest(settings.manifest_path)
    existing = col.get(include=["metadatas"]).get("metadatas") or []
    existing_hash = {m["doc_id"]: m["content_hash"] for m in existing if m}

    deleted = [d for d in existing_hash if d not in manifest]
    changed = [d for d, meta in manifest.items() if existing_hash.get(d) != meta.content_hash]
    added = [d for d in changed if d not in existing_hash]
    updated = [d for d in changed if d in existing_hash]

    for doc_id in set(deleted) | set(updated):
        col.delete(where={"doc_id": doc_id})

    total = 0
    for doc_id in changed:
        meta = manifest[doc_id]
        text = (settings.corpus_dir / meta.file_path).read_text(encoding="utf-8")
        chunk_meta = {
            "doc_id": meta.doc_id, "content_hash": meta.content_hash,
            "title": meta.title, "category": meta.category,
            "source_url": meta.source_url, "publisher": meta.publisher,
        }
        chunks = split_document(text, doc_id, chunk_meta)
        if not chunks:
            continue
        embeddings = embedder.encode([c.text for c in chunks])
        col.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[{**c.metadata, "heading_path": c.heading_path} for c in chunks],
        )
        total += len(chunks)

    return IndexReport(added_docs=len(added), updated_docs=len(updated),
                       deleted_docs=len(deleted), total_chunks=total)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_indexer.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/indexing/ tests/test_indexer.py
git commit -m "feat: 增量索引（content_hash diff + upsert/delete）"
```

---

## Task 8: 混合检索（向量 + BM25 + RRF）

**Files:**
- Create: `src/sufe_qa/retrieve/__init__.py`
- Create: `src/sufe_qa/retrieve/hybrid.py`
- Test: `tests/test_hybrid.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_hybrid.py
from sufe_qa.config import Settings
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
from sufe_qa.retrieve.hybrid import HybridRetriever, rrf_fuse
from sufe_qa.schema import DocMeta, append_manifest


def _build_index(tmp_path):
    data = tmp_path / "data"
    s = Settings(data_dir=data, corpus_dir=data / "corpus", inbox_dir=data / "inbox",
                 chroma_dir=data / "chroma", manifest_path=data / "corpus" / "manifest.jsonl")
    docs = [
        ("a1", "奖学金办法", "奖助学金", "第一条 国家奖学金申请条件为成绩优异。第二条 奖励8000元。"),
        ("a2", "推免细则", "推免升学", "第一条 推免生须绩点排名专业前百分之二十。"),
        ("a3", "食堂指南", "校园生活", "食堂开放时间为早上七点至晚上九点。"),
    ]
    for doc_id, title, cat, text in docs:
        p = s.corpus_dir / cat / f"{doc_id}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        append_manifest(s.manifest_path, [DocMeta(
            doc_id=doc_id, title=title, source_url="inbox/x", publisher="学生工作部",
            publish_date="unknown", category=cat, fetched_at="t",
            content_hash=f"sha256:{doc_id}", file_path=f"{cat}/{doc_id}.md",
        )])
    update_index(s, FakeEmbedder())
    return s


def test_rrf_fuse_order():
    fused = rrf_fuse([["c1", "c2"], ["c2", "c3"]], k=60)
    assert fused[0][0] == "c2"  # 两路都命中且名次高者第一


def test_hybrid_retrieves_relevant(tmp_path):
    s = _build_index(tmp_path)
    r = HybridRetriever(s, FakeEmbedder())
    result = r.retrieve("奖学金申请条件是什么")
    assert not result.should_abstain
    assert result.chunks[0].metadata["doc_id"] == "a1"


def test_unrelated_query_abstains(tmp_path):
    s = _build_index(tmp_path)
    r = HybridRetriever(s, FakeEmbedder(), vector_min_similarity=0.5)
    result = r.retrieve("zxqwvkjhgf")  # 纯乱码：与语料无共享字符片段/词
    assert result.should_abstain
    assert result.chunks == []
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_hybrid.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.retrieve`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/retrieve/__init__.py
```

```python
# src/sufe_qa/retrieve/hybrid.py
from __future__ import annotations

from dataclasses import dataclass, field

import chromadb
import jieba
from rank_bm25 import BM25Okapi

from sufe_qa.config import Settings
from sufe_qa.indexing.indexer import Embedder


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    text: str
    metadata: dict
    score: float
    channels: frozenset[str] = field(default_factory=frozenset)  # {"vector"} / {"bm25"}


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[Hit]
    should_abstain: bool


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """倒数排名融合：score = Σ 1/(k+rank)，rank 从 1 起。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class HybridRetriever:
    def __init__(self, settings: Settings, embedder: Embedder,
                 vector_min_similarity: float | None = None):
        self.settings = settings
        self.embedder = embedder
        self.min_sim = (vector_min_similarity if vector_min_similarity is not None
                        else settings.vector_min_similarity)
        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.col = client.get_or_create_collection(settings.collection_name,
                                                   metadata={"hnsw:space": "cosine"})
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: list[str] = []

    def _vector_ranking(self, question: str) -> list[str]:
        if self.col.count() == 0:
            return []
        qv = self.embedder.encode([question])[0]
        res = self.col.query(query_embeddings=[qv], n_results=min(self.settings.vector_top_k, self.col.count()),
                             include=["distances"])
        ids, dists = res["ids"][0], res["distances"][0]
        # cosine 空间 distance = 1 - similarity
        return [cid for cid, d in zip(ids, dists) if 1.0 - d >= self.min_sim]

    def _bm25_ranking(self, question: str) -> list[str]:
        if self._bm25 is None:
            got = self.col.get(include=["documents"])
            docs, self._bm25_ids = got.get("documents") or [], got.get("ids") or []
            self._bm25 = BM25Okapi([list(jieba.lcut(d)) for d in docs]) if docs else None
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(list(jieba.lcut(question)))
        ranked = sorted(zip(self._bm25_ids, scores), key=lambda kv: kv[1], reverse=True)
        return [cid for cid, s in ranked[: self.settings.bm25_top_k] if s > 0.0]

    def retrieve(self, question: str) -> RetrievalResult:
        vec = self._vector_ranking(question)
        bm = self._bm25_ranking(question)
        fused = rrf_fuse([vec, bm], k=self.settings.rrf_k)[: self.settings.fusion_top_n]
        if not fused:
            return RetrievalResult(chunks=[], should_abstain=True)
        got = self.col.get(ids=[cid for cid, _ in fused], include=["documents", "metadatas"])
        by_id = {cid: (doc, meta) for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"])}
        hits = []
        for cid, score in fused:
            doc, meta = by_id[cid]
            channels = frozenset((["vector"] if cid in vec else []) + (["bm25"] if cid in bm else []))
            hits.append(Hit(chunk_id=cid, text=doc, metadata=meta, score=score, channels=channels))
        return RetrievalResult(chunks=hits, should_abstain=False)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_hybrid.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/retrieve/ tests/test_hybrid.py
git commit -m "feat: 混合检索（向量+BM25+RRF，空集拒答）"
```

---

## Task 9: 生成层（DeepSeek + 严格引用 + 来源卡片）

**Files:**
- Create: `src/sufe_qa/generate/__init__.py`
- Create: `src/sufe_qa/generate/prompts.py`
- Create: `src/sufe_qa/generate/llm.py`
- Create: `src/sufe_qa/generate/answer.py`
- Test: `tests/test_answer.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_answer.py
from sufe_qa.config import Settings
from sufe_qa.generate.answer import (ABSTAIN_TEMPLATE, answer_question,
                                     build_source_cards, extract_citations)
from sufe_qa.retrieve.hybrid import Hit, RetrievalResult


class StubRetriever:
    def __init__(self, result): self._r = result
    def retrieve(self, q): return self._r


class SpyClient:
    def __init__(self): self.calls = []
    def stream(self, messages):
        self.calls.append(messages)
        yield "申请条件为成绩优异[1]，奖励8000元[1][2]。"


def _hits() -> list[Hit]:
    return [
        Hit("a:0", "第一条 国家奖学金申请条件为成绩优异。", {"title": "奖学金办法", "publisher": "学生工作部", "source_url": "https://x/1", "category": "奖助学金"}, 0.03),
        Hit("b:0", "第二条 奖励标准为每生每年8000元。", {"title": "资助管理规定", "publisher": "学生工作部", "source_url": "https://x/2", "category": "奖助学金"}, 0.02),
    ]


def test_extract_citations_ordered_dedup():
    assert extract_citations("甲[2]乙[1]丙[2]丁[9]") == [2, 1, 9]


def test_source_cards_map_and_ignore_out_of_range():
    cards = build_source_cards([1, 2, 9], _hits())
    assert len(cards) == 2
    assert cards[0].title == "奖学金办法" and cards[0].source_url == "https://x/1"
    assert cards[1].title == "资助管理规定" and cards[1].source_url == "https://x/2"


def test_abstain_short_circuits_llm(tmp_path):
    client = SpyClient()
    r = answer_question("无关", StubRetriever(RetrievalResult([], True)), client, Settings.__new__(Settings))
    assert r.abstained and r.text == ABSTAIN_TEMPLATE
    assert client.calls == []


def test_answer_assembles_cards(tmp_path):
    client = SpyClient()
    r = answer_question("条件", StubRetriever(RetrievalResult(_hits(), False)), client, Settings.__new__(Settings))
    assert not r.abstained
    assert "成绩优异" in r.text
    assert [c.title for c in r.sources] == ["奖学金办法", "资助管理规定"]
    # prompt 硬约束进入 messages
    user_msg = client.calls[0][1]["content"]
    assert "[1]" in user_msg and "奖学金办法" in user_msg and "问题：" in user_msg
```

注：`Settings.__new__(Settings)` 仅为绕过 dataclass 构造的测试技巧，answer_question 不读 Settings 字段（保留参数以便后续加温度等配置）。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_answer.py -q`
Expected: FAIL，`ModuleNotFoundError: sufe_qa.generate`

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/generate/__init__.py
```

```python
# src/sufe_qa/generate/prompts.py
from __future__ import annotations

from sufe_qa.retrieve.hybrid import Hit

SYSTEM_PROMPT = """你是上海财经大学校园问答助手。只允许依据"资料"部分的内容回答。
规则：
1. 每条关键论断后必须紧跟引用编号，如[1][2]；编号只能来自给定资料
2. 资料中没有的内容，明确说"知识库暂未收录"，并建议查阅学校/学院官网或咨询相关部门
3. 严禁编造文件名、日期、金额、比例、政策条款
4. 用简体中文，简洁分点
5. 不要在结尾自行罗列参考资料清单（由系统生成）"""


def build_user_prompt(question: str, chunks: list[Hit]) -> str:
    parts = ["资料："]
    for i, h in enumerate(chunks, 1):
        m = h.metadata
        parts.append(f"[{i}] 《{m.get('title','')}》（{m.get('publisher','')} / {m.get('category','')}）\n{h.text}")
    parts.append(f"问题：{question}")
    return "\n\n".join(parts)
```

```python
# src/sufe_qa/generate/llm.py
from __future__ import annotations

from typing import Iterator, Protocol


class ChatClient(Protocol):
    def stream(self, messages: list[dict]) -> Iterator[str]: ...


class DeepSeekClient:
    def __init__(self, api_key: str, model: str = "deepseek-chat",
                 base_url: str = "https://api.deepseek.com"):
        from openai import OpenAI

        self._c = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def stream(self, messages: list[dict]) -> Iterator[str]:
        resp = self._c.chat.completions.create(
            model=self._model, messages=messages, stream=True, temperature=0.2,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
```

```python
# src/sufe_qa/generate/answer.py
from __future__ import annotations

import re
from dataclasses import dataclass

from sufe_qa.config import Settings
from sufe_qa.generate.llm import ChatClient
from sufe_qa.generate.prompts import SYSTEM_PROMPT, build_user_prompt
from sufe_qa.retrieve.hybrid import Hit, HybridRetriever

ABSTAIN_TEMPLATE = (
    "知识库暂未收录与该问题相关的可靠资料。建议：\n"
    "1. 换个关键词再问一次；\n"
    "2. 直接查阅上海财经大学官网 / 计算机与人工智能学院官网的通知公告；\n"
    "3. 咨询相关部门（学生工作部、教务处、学院学生办公室）。"
)

CITATION_RE = re.compile(r"\[(\d{1,2})\]")


@dataclass(frozen=True)
class SourceCard:
    title: str
    publisher: str
    source_url: str
    category: str


@dataclass(frozen=True)
class AnswerResult:
    text: str
    sources: list[SourceCard]
    abstained: bool


def extract_citations(answer: str) -> list[int]:
    return list(dict.fromkeys(int(m.group(1)) for m in CITATION_RE.finditer(answer)))


def build_source_cards(citations: list[int], chunks: list[Hit]) -> list[SourceCard]:
    cards: list[SourceCard] = []
    for n in citations:
        if 1 <= n <= len(chunks):
            m = chunks[n - 1].metadata
            card = SourceCard(title=m.get("title", ""), publisher=m.get("publisher", ""),
                              source_url=m.get("source_url", ""), category=m.get("category", ""))
            if card not in cards:
                cards.append(card)
    return cards


def answer_question(question: str, retriever: HybridRetriever, client: ChatClient,
                    settings: Settings) -> AnswerResult:
    result = retriever.retrieve(question)
    if result.should_abstain:
        return AnswerResult(text=ABSTAIN_TEMPLATE, sources=[], abstained=True)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, result.chunks)},
    ]
    text = "".join(client.stream(messages))
    cards = build_source_cards(extract_citations(text), result.chunks)
    return AnswerResult(text=text, sources=cards, abstained=False)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_answer.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/generate/ tests/test_answer.py
git commit -m "feat: DeepSeek 生成层（严格引用+拒答短路+来源卡片）"
```

---

## Task 10: CLI 串联与真实 smoke

**Files:**
- Create: `src/sufe_qa/cli.py`
- Create: `data/inbox/sample_policy.md`（smoke 用样例，随后移入正式语料）
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli.py
import subprocess
import sys


def test_cli_help_exits_zero():
    r = subprocess.run([sys.executable, "-m", "sufe_qa.cli", "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "ingest" in r.stdout and "ask" in r.stdout and "index" in r.stdout
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL（模块不存在或 --help 无子命令）

- [ ] **Step 3: 实现**

```python
# src/sufe_qa/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sufe_qa.config import get_api_key, load_settings


def _cmd_ingest(args) -> int:
    from sufe_qa.ingest.inbox import ingest_inbox

    s = load_settings()
    r = ingest_inbox(s.inbox_dir, s.corpus_dir, s.manifest_path,
                     category=args.category, publisher=args.publisher)
    print(f"added={r.added} dup={r.skipped_dup} empty={r.skipped_empty} quarantined={r.quarantined}")
    return 0


def _cmd_crawl(args) -> int:
    from sufe_qa.crawler.crawl import crawl_seed, load_seeds
    from sufe_qa.ingest.parsers import parse_html
    from sufe_qa.ingest.inbox import scan_sensitive, slugify
    from sufe_qa.schema import DocMeta, append_manifest, doc_id_from, load_manifest, sha256_text
    from datetime import datetime, timezone

    s = load_settings()
    seeds = load_seeds(Path(__file__).parent / "crawler" / "seeds.yaml")
    seed = next((x for x in seeds if x.name == args.seed), None)
    if seed is None:
        print(f"未知 seed: {args.seed}，可选: {[x.name for x in seeds]}", file=sys.stderr)
        return 2
    known = {m.content_hash for m in load_manifest(s.manifest_path).values()}
    metas = []
    for url, html in crawl_seed(seed, delay=args.delay):
        doc = parse_html(html, fallback_title=url)
        if not doc.text or scan_sensitive(doc.text):
            continue
        h = sha256_text(doc.text)
        if h in known:
            continue
        rel = Path(seed.category) / f"{slugify(doc.title)}.md"
        out = s.corpus_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# {doc.title}\n\n{doc.text}\n", encoding="utf-8")
        metas.append(DocMeta(
            doc_id=doc_id_from(url, doc.title), title=doc.title, source_url=url,
            publisher=seed.publisher, publish_date=doc.publish_date, category=seed.category,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            content_hash=h, file_path=rel.as_posix(),
        ))
        known.add(h)
    append_manifest(s.manifest_path, metas)
    print(f"seed={seed.name} fetched_new={len(metas)}")
    return 0


def _cmd_index(args) -> int:
    from sufe_qa.indexing.indexer import BgeEmbedder, update_index

    s = load_settings()
    r = update_index(s, BgeEmbedder(s.embedding_model), full=args.full)
    print(f"added={r.added_docs} updated={r.updated_docs} deleted={r.deleted_docs} chunks={r.total_chunks}")
    return 0


def _cmd_ask(args) -> int:
    from sufe_qa.generate.answer import answer_question
    from sufe_qa.generate.llm import DeepSeekClient
    from sufe_qa.indexing.indexer import BgeEmbedder
    from sufe_qa.retrieve.hybrid import HybridRetriever

    s = load_settings()
    retriever = HybridRetriever(s, BgeEmbedder(s.embedding_model))
    client = DeepSeekClient(get_api_key(), model=s.llm_model, base_url=s.llm_base_url)
    r = answer_question(args.question, retriever, client, s)
    print(r.text)
    if r.sources:
        print("\n—— 资料来源 ——")
        for c in r.sources:
            print(f"· 《{c.title}》 {c.publisher} {c.source_url}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="sufe-qa", description="上财校园问答智能体")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="扫描 data/inbox 入库")
    pi.add_argument("--category", default="其他")
    pi.add_argument("--publisher", default="手动投放")
    pi.set_defaults(fn=_cmd_ingest)

    pc = sub.add_parser("crawl", help="按 seeds.yaml 抓取")
    pc.add_argument("--seed", required=True)
    pc.add_argument("--delay", type=float, default=1.0)
    pc.set_defaults(fn=_cmd_crawl)

    px = sub.add_parser("index", help="增量更新向量索引")
    px.add_argument("--full", action="store_true")
    px.set_defaults(fn=_cmd_index)

    pa = sub.add_parser("ask", help="提问")
    pa.add_argument("question")
    pa.set_defaults(fn=_cmd_ask)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

```markdown
# 上海财经大学学生奖学金评定办法（样例）

第一条 为激励学生勤奋学习，学校设立国家奖学金、国家励志奖学金与校内奖学金。
第二条 国家奖学金奖励标准为每生每年8000元，申请条件为学习成绩优异、社会实践与综合素质突出。
第三条 国家励志奖学金面向家庭经济困难且品学兼优的学生，奖励标准为每生每年5000元。
第四条 各类奖学金每学年评审一次，一般在九月至十月开展，由学生工作部组织实施。
第五条 学生对评审结果有异议的，可在公示期内向学生工作部提出书面申诉。
```

- [ ] **Step 4: 运行确认通过 + 全量测试**

Run: `uv run pytest -q`
Expected: 全部通过（含此前各 Task，累计约 20 项）

- [ ] **Step 5: 真实 smoke（需要 .env 里有真 key；约 2GB 模型下载）**

```bash
cp data/inbox/sample_policy.md data/inbox/_demo_policy.md
uv run sufe-qa ingest --category 奖助学金 --publisher 学生工作部
uv run sufe-qa index
uv run sufe-qa ask "国家奖学金申请条件是什么，奖励多少钱"
uv run sufe-qa ask "火星基地什么时候招生"   # 期望走拒答模板
```

Expected: 第一问引用《…奖学金评定办法》并带来源；第二问输出拒答模板且无 LLM 调用。

- [ ] **Step 6: Commit**

```bash
git add src/sufe_qa/cli.py tests/test_cli.py data/inbox/sample_policy.md
git commit -m "feat: CLI 串联 ingest/crawl/index/ask 与 smoke 样例"
```

---

## M1 完成审计

- [ ] `uv run pytest -q` 全绿，`uv run ruff check src tests` 无错
- [ ] 真实 smoke：ingest → index → ask（含拒答用例）全部符合预期
- [ ] 增量索引验证：重复执行 `index` 输出 `added=0 updated=0 deleted=0`
- [ ] `manifest.jsonl` 每条含 title/source_url/publisher/category/content_hash
- [ ] 无任何模块在 `BgeEmbedder` 外 import `sentence_transformers`（`rg "sentence_transformers" src -l` 只命中 `indexer.py`）
- [ ] `.env` 未入库；`data/inbox/` 被 gitignore（样例文件除外）
- [ ] seeds.yaml 保持空清单或仅含已验证种子；未对未验证站点发起抓取
