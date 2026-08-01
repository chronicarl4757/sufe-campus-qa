"""站点画像：discover-site 勘探生成，crawl-site 消费；YAML 持久化，确定性抓取。

profile 只承载站点结构知识（栏目 URL、选择器、限额），不含每次抓取时才确定的动态信息；
日常 crawl-site 不允许依赖 LLM 判断页面类型。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CategoryProfile:
    name: str  # 栏目名（通知公告/本科生培养/...）
    list_url: str
    category: str  # 入库分类（config.CATEGORIES 之一）
    article_selector: str = "a"  # 列表页文章链接选择器
    url_prefix: str = ""  # 文章链接前缀过滤，空为不限
    max_list_pages: int = 5
    max_articles: int = 100


@dataclass(frozen=True)
class ArticleProfile:
    title_selectors: list[str] = field(default_factory=list)
    date_selectors: list[str] = field(default_factory=list)
    content_selectors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SiteLimits:
    max_html_bytes: int = 5_000_000
    max_attachment_bytes: int = 30_000_000
    max_attachments_per_article: int = 20


@dataclass(frozen=True)
class SiteProfile:
    site_name: str
    root_url: str
    allowed_hosts: list[str]
    cms_type: str = "generic"  # wp3 | gs_home | generic
    categories: list[CategoryProfile] = field(default_factory=list)
    article: ArticleProfile = field(default_factory=ArticleProfile)
    limits: SiteLimits = field(default_factory=SiteLimits)

    @property
    def host(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.root_url).netloc


def profile_to_yaml(profile: SiteProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(asdict(profile), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _coerce(cls, d: dict):
    return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


def profile_from_yaml(path: Path) -> SiteProfile:
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SiteProfile(
        site_name=d.get("site_name", ""),
        root_url=d.get("root_url", ""),
        allowed_hosts=list(d.get("allowed_hosts") or []),
        cms_type=d.get("cms_type", "generic"),
        categories=[_coerce(CategoryProfile, c) for c in d.get("categories") or []],
        article=_coerce(ArticleProfile, d.get("article")),
        limits=_coerce(SiteLimits, d.get("limits")),
    )
