"""公众号文章发现层：只负责输出 (account, title, publish_date, url) 最小元组。

- SeedURLDiscovery：人工/外部收集的 JSONL 种子，完全离线可用，是 fallback 与测试基础；
- WeRSSDiscovery：可选的 We-MP-RSS HTTP API 客户端（AK-SK 认证），只读其公开 API，
  不耦合它的 SQLite/内部表结构；不可用时报 warning，绝不让整个 crawl 失败。

两种实现都输出 DiscoveredArticle，下游 fetcher/filter/ingest 不需要知道来源。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

WECHAT_HOST = "mp.weixin.qq.com"

# WeRSS 故障分类（规格 §三十五）：区分授权过期/频控/暂时不可用/响应异常，不做无限 retry。
WERSS_STATUSES = (
    "ok",
    "not_configured",
    "temporary_unavailable",
    "auth_required",
    "rate_limited",
    "invalid_response",
)


@dataclass(frozen=True)
class DiscoveredArticle:
    """发现层的最小输出：公众号名 + 文章 URL；title/date 可空，由 fetcher 补齐。

    content_html/content_text 是 WeRSS 已存正文（规格 §八-§十）：非空时 runner
    直接 normalize，不再二次请求 mp.weixin.qq.com。
    """

    account: str
    url: str
    title: str = ""
    publish_date: str = ""  # YYYY-MM-DD 或空
    force_include: bool = False  # 显式豁免时间窗（规格 §十四）
    related_official_url: str = ""  # 对应的官网正式文档 URL（建立 explains 关系用）
    source: str = "seed"  # seed | werss
    content_html: str = ""
    content_text: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.content_html.strip() or self.content_text.strip())


@dataclass
class DiscoveryResult:
    articles: list[DiscoveredArticle] = field(default_factory=list)
    status: str = "ok"  # ok | WERSS_STATUSES 的非 ok 值
    message: str = ""
    warnings: list[str] = field(default_factory=list)


class ArticleDiscovery(Protocol):
    """发现层接口：任何来源（种子文件/WeRSS/未来搜索引擎）只需实现 discover。"""

    name: str

    def discover(self, *, accounts: list[str], limit: int) -> DiscoveryResult:
        """accounts 为白名单公众号名（空列表表示不过滤）；limit 为总上限。"""
        ...


def is_wechat_article_url(url: str) -> bool:
    """只接受 mp.weixin.qq.com 文章地址（/s/<token> 或 /s?__biz=... 长链）。"""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    return (
        p.scheme in ("http", "https")
        and p.netloc.lower() == WECHAT_HOST
        and (p.path.startswith("/s"))
    )


class SeedURLDiscovery:
    """从 JSONL 种子文件读取文章 URL；每行 {account, url, title?, publish_date?, force_include?}。"""

    name = "seed"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def discover(self, *, accounts: list[str], limit: int) -> DiscoveryResult:
        result = DiscoveryResult()
        if not self.path.is_file():
            result.status = "temporary_unavailable"
            result.message = f"种子文件不存在: {self.path}"
            return result
        seen: set[str] = set()
        for lineno, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                result.warnings.append(f"种子第 {lineno} 行 JSON 解析失败，已跳过")
                continue
            url = str(raw.get("url") or "").strip()
            if not is_wechat_article_url(url):
                result.warnings.append(
                    f"种子第 {lineno} 行非 mp.weixin.qq.com 文章地址，已跳过: {url}"
                )
                continue
            if url in seen:
                continue
            seen.add(url)
            account = str(raw.get("account") or "").strip()
            result.articles.append(
                DiscoveredArticle(
                    account=account,
                    url=url,
                    title=str(raw.get("title") or "").strip(),
                    publish_date=str(raw.get("publish_date") or "").strip(),
                    force_include=bool(raw.get("force_include") or False),
                    related_official_url=str(raw.get("related_official_url") or "").strip(),
                    source="seed",
                )
            )
            if limit and len(result.articles) >= limit:
                break
        return result


class WeRSSDiscovery:
    """We-MP-RSS（WeRSS）文章发现客户端：AK-SK 认证，只读公开 HTTP API。

    端点（we-mp-rss ≥1.4，经 upstream 源码核对 apis/article.py）：
    - GET {api_prefix}/mps?kw=                订阅公众号列表（按名称匹配 mp_id）
    - GET {api_prefix}/articles?mp_id=…       文章列表（ArticleBase，**不含正文**），
      返回 title / url / publish_time / mp_name / id / has_content
    - GET {api_prefix}/articles/{id}          文章详情，返回完整 Article，
      含 content_html / content —— 有正文时直接消费，不再回源微信（规格 §八）
    api_prefix 默认 /api/v1/wx，404 时回退 /api（不同版本挂载点不同）。
    """

    name = "werss"
    DEFAULT_API_PREFIXES = ("/api/v1/wx", "/api")

    def __init__(
        self,
        base_url: str,
        access_key: str = "",
        secret_key: str = "",
        *,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self._timeout = timeout
        self._own = client is None
        self._client = client or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, *, client: httpx.Client | None = None) -> WeRSSDiscovery | None:
        """WERSS_BASE_URL 未配置返回 None（调用方按 disabled/skip 处理）。"""
        base_url = os.getenv("WERSS_BASE_URL", "").strip()
        if not base_url:
            return None
        return cls(
            base_url,
            os.getenv("WERSS_ACCESS_KEY", "").strip(),
            os.getenv("WERSS_SECRET_KEY", "").strip(),
            client=client,
        )

    def close(self) -> None:
        if self._own:
            self._client.close()

    def __enter__(self) -> WeRSSDiscovery:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        if self.access_key and self.secret_key:
            return {"Authorization": f"AK-SK {self.access_key}:{self.secret_key}"}
        return {}

    def _get(self, path: str, params: dict) -> tuple[str, dict | None]:
        """返回 (status, payload)；payload 为解包后的 data 字段。"""
        last_status = "temporary_unavailable"
        for prefix in self.DEFAULT_API_PREFIXES:
            url = f"{self.base_url}{prefix}{path}"
            try:
                r = self._client.get(url, params=params, headers=self._headers())
            except httpx.HTTPError as e:
                logger.warning("WeRSS 请求失败 %s: %s", url, e)
                continue
            if r.status_code == 404 and prefix != self.DEFAULT_API_PREFIXES[-1]:
                continue  # 老/新版本挂载点差异，尝试下一个候选前缀
            if r.status_code in (401, 403):
                return "auth_required", None
            if r.status_code == 429:
                return "rate_limited", None
            if r.status_code >= 500:
                return "temporary_unavailable", None
            if r.status_code >= 400:
                last_status = "invalid_response"
                continue
            try:
                body = r.json()
            except (json.JSONDecodeError, ValueError):
                return "invalid_response", None
            if not isinstance(body, dict) or body.get("code") != 0:
                message = str((body or {}).get("message", "")) if isinstance(body, dict) else ""
                if any(k in message.lower() for k in ("auth", "token", "授权", "登录")):
                    return "auth_required", None
                return "invalid_response", None
            return "ok", body.get("data")
        return last_status, None

    def _find_mp_id(self, account: str) -> tuple[str, str | None]:
        """按公众号名查 mp_id；返回 (status, mp_id)。"""
        status, data = self._get("/mps", {"kw": account})
        if status != "ok":
            return status, None
        items = (data or {}).get("list") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return "invalid_response", None
        for item in items:
            if isinstance(item, dict) and str(item.get("mp_name") or "").strip() == account:
                return "ok", str(item.get("id") or "")
        return "ok", None  # 未订阅该公众号不是故障

    def _article_detail(self, article_id: str) -> tuple[str, str, str]:
        """拉文章详情取已存正文；返回 (status, content_html, content_text)。

        详情失败不视为发现失败：返回空正文，由 runner 回源微信抓取（规格 §十）。
        """
        status, data = self._get(f"/articles/{article_id}", {})
        if status != "ok" or not isinstance(data, dict):
            return status, "", ""
        content_html = str(data.get("content_html") or "")
        content_text = str(data.get("content") or "")
        return "ok", content_html, content_text

    def discover(self, *, accounts: list[str], limit: int) -> DiscoveryResult:
        result = DiscoveryResult()
        if not accounts:
            result.message = "WeRSS 模式需要白名单提供公众号名"
            return result
        for account in accounts:
            if limit and len(result.articles) >= limit:
                break
            status, mp_id = self._find_mp_id(account)
            if status != "ok":
                result.status = status
                result.message = f"查询公众号 {account} 失败: {status}"
                result.warnings.append(result.message)
                return result  # 故障即停：不做无限 retry，也不拖垮其他 crawler
            if not mp_id:
                result.warnings.append(f"WeRSS 未订阅公众号: {account}")
                continue
            remaining = limit - len(result.articles) if limit else 50
            status, data = self._get(
                "/articles", {"mp_id": mp_id, "offset": 0, "limit": max(1, min(remaining, 100))}
            )
            if status != "ok":
                result.status = status
                result.message = f"获取 {account} 文章列表失败: {status}"
                result.warnings.append(result.message)
                return result
            items = (data or {}).get("list") if isinstance(data, dict) else None
            if not isinstance(items, list):
                result.status = "invalid_response"
                result.message = f"{account} 文章列表响应结构异常"
                result.warnings.append(result.message)
                return result
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not is_wechat_article_url(url):
                    continue
                publish_date = ""
                try:
                    publish_date = datetime.fromtimestamp(
                        int(item.get("publish_time") or 0), tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                except (TypeError, ValueError, OSError):
                    publish_date = ""
                # 列表只给元数据；正文走详情端点（has_content=0 时跳过详情请求）
                content_html, content_text = "", ""
                article_id = str(item.get("id") or "").strip()
                try:
                    has_content = int(item.get("has_content") or 0) != 0
                except (TypeError, ValueError):
                    has_content = True  # 无法判断时仍尝试详情
                if article_id and has_content:
                    _, content_html, content_text = self._article_detail(article_id)
                result.articles.append(
                    DiscoveredArticle(
                        account=str(item.get("mp_name") or account).strip(),
                        url=url,
                        title=str(item.get("title") or "").strip(),
                        publish_date=publish_date,
                        source="werss",
                        content_html=content_html,
                        content_text=content_text,
                    )
                )
                if limit and len(result.articles) >= limit:
                    break
        return result
