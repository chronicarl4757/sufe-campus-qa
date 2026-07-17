"""种子站爬虫：从栏目列表页提取文章链接并抓取正文页。

合规约束：
- robots.txt 用带超时、带 UA 的 httpx 拉取并按 netloc 缓存
  （不用 robotparser.read()：它无超时可能永久阻塞，且每 URL 重复拉取、UA 不受控）；
- 遵守 Crawl-delay：实际限速取 max(调用方 delay, Crawl-delay)；
- 出站防护：只抓与列表页同 netloc 的页面，重定向到出站页面同样跳过；
- 单篇文章抓取失败只告警跳过，不中断整站抓取；列表页失败则直接抛错；
- 自定义 User-Agent 表明身份。

离线可测：extract_links / load_seeds 为纯函数；crawl_seed 支持注入 httpx.Client，
测试可用本地 http.server 替代真实站点。
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup

from sufe_qa.config import CATEGORIES

logger = logging.getLogger(__name__)

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

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"非法分类: {self.category}")


def load_seeds(path: Path) -> list[Seed]:
    """读取种子清单 YAML；seeds 键缺失或为 null/空列表时返回空列表。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Seed(**s) for s in data.get("seeds") or []]


class _RobotsCache:
    """按 netloc 缓存 robots 规则；用带超时的 httpx 拉取，替代 robotparser.read()。

    状态语义（依据 RFC 9309）：
    - 404：站点无 robots.txt，全站放行；
    - 401/403：robots.txt 访问被拒，视为全站禁止抓取；
    - 其他 4xx/5xx、网络异常（含超时）：保守策略，视为禁止抓取（can_fetch=False）。
    """

    def __init__(self, client: httpx.Client, ua: str = UA):
        self._client = client
        self._ua = ua
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _load(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parsed = urlparse(url)
        netloc = parsed.netloc
        if netloc in self._cache:
            return self._cache[netloc]
        rp = urllib.robotparser.RobotFileParser()
        try:
            # 用目标页面自己的 scheme 拼 robots URL（被测站点可能是 http）
            r = self._client.get(f"{parsed.scheme}://{netloc}/robots.txt")
        except httpx.HTTPError:
            self._cache[netloc] = None  # 网络异常/超时：保守不抓
            return None
        if r.status_code == 404:
            rp.parse([])  # 无 robots = 全放行（RFC 9309）
        elif r.status_code in (401, 403):
            rp.parse(["User-agent: *", "Disallow: /"])  # 401/403 = 全站禁止
        elif r.status_code >= 400:
            self._cache[netloc] = None  # 其他 4xx/5xx：保守不抓
            return None
        else:
            rp.parse(r.text.splitlines())
        self._cache[netloc] = rp
        return rp

    def can_fetch(self, url: str) -> bool:
        rp = self._load(url)
        return rp is not None and rp.can_fetch(self._ua, url)

    def crawl_delay(self, url: str) -> float | None:
        rp = self._load(url)
        return rp.crawl_delay(self._ua) if rp else None


def extract_links(html: str, seed: Seed) -> list[str]:
    """从列表页 HTML 提取文章链接。

    相对 URL 按 list_url 补全；跳过空 href 与纯锚点（#...）；按 url_prefix 过滤、
    保序去重、截断到 max_pages。
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for a in soup.select(seed.link_selector):
        href = a.get("href")
        if not href or str(href).startswith("#"):
            continue
        full = urljoin(seed.list_url, str(href))
        if full.startswith(seed.url_prefix):
            out.append(full)
    return list(dict.fromkeys(out))[: seed.max_pages]


def crawl_seed(
    seed: Seed, delay: float = 1.0, client: httpx.Client | None = None
) -> list[tuple[str, str]]:
    """抓取种子站列表页及其文章页，返回 [(url, html)]。

    - 逐 URL 检查 robots（_RobotsCache 按 netloc 缓存）：被禁页面跳过，
      列表页被禁则抛 RuntimeError；
    - 实际限速为 max(delay, robots 的 Crawl-delay) 秒/页；
    - 只抓与列表页同 netloc 的页面，重定向出站的页面跳过并告警；
    - 单篇文章抓取失败（HTTP 错误/超时）告警跳过、已抓页面保留；列表页失败直接抛错；
    - 注入的 client 由调用方管理；本函数自建的 client 退出前关闭。
    """
    own_client = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA})
    robots = _RobotsCache(client)
    site_netloc = urlparse(seed.list_url).netloc
    try:
        if not robots.can_fetch(seed.list_url):
            raise RuntimeError(f"robots.txt 禁止抓取: {seed.list_url}")
        list_resp = client.get(seed.list_url)
        list_resp.raise_for_status()  # 列表页失败直接抛错
        urls = extract_links(list_resp.text, seed)
        # 候选页与列表页同 netloc（下方循环保证），Crawl-delay 取一次即可
        actual_delay = max(delay, robots.crawl_delay(seed.list_url) or 0)
        pages: list[tuple[str, str]] = []
        for u in urls:
            if urlparse(u).netloc != site_netloc:
                continue  # 出站防护：url_prefix 过滤之外的二次保险
            if not robots.can_fetch(u):
                continue
            try:
                r = client.get(u)
                r.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("抓取失败，跳过 %s: %s", u, e)
                continue
            if urlparse(str(r.url)).netloc != site_netloc:
                logger.warning("重定向到出站页面，跳过 %s -> %s", u, r.url)
                continue
            pages.append((u, r.text))
            time.sleep(actual_delay)
        return pages
    finally:
        if own_client:
            client.close()
