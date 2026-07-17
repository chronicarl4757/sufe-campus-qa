"""种子站爬虫：从栏目列表页提取文章链接并抓取正文页。

合规约束：
- 逐 URL 检查 robots.txt，robots 不可达时保守不抓；
- 默认 1 秒/页限速，自定义 User-Agent 表明身份；
- 只跟进 url_prefix 限定的站内链接，去重并限制每个列表页的最大跟进数。

离线可测：extract_links / load_seeds 为纯函数；crawl_seed 支持注入 httpx.Client。
"""

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
    url_prefix: str  # 只跟进此前缀的链接
    category: str
    publisher: str
    max_pages: int = 20


def load_seeds(path: Path) -> list[Seed]:
    """读取种子清单 YAML；seeds 键缺失或为 null/空列表时返回空列表。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Seed(**s) for s in data.get("seeds") or []]


def allowed_by_robots(url: str, ua: str = UA) -> bool:
    """检查 robots.txt 是否允许抓取 url；robots 不可达时保守返回 False。"""
    parsed = urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return False  # robots 不可达时保守策略：不抓
    return rp.can_fetch(ua, url)


def extract_links(html: str, seed: Seed) -> list[str]:
    """从列表页 HTML 提取文章链接：相对 URL 补全、按前缀过滤、保序去重、截断到 max_pages。"""
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


def crawl_seed(
    seed: Seed, delay: float = 1.0, client: httpx.Client | None = None
) -> list[tuple[str, str]]:
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
