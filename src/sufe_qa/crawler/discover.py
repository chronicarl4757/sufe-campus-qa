"""站点勘探：学院主页 → 高价值栏目发现 → CMS 识别 → 生成确定性 SiteProfile。

规格 §十三：只识别三类 CMS（wp3 / gs_home / 通用静态列表页）；勘探与日常抓取
都是确定性启发式，任何阶段不允许依赖 LLM 判断页面类型。
discover-site 只生成 profile 与报告；crawl-site 消费固定 profile。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from sufe_qa.crawler.fetcher import SafeFetcher
from sufe_qa.crawler.profile import (
    ArticleProfile,
    CategoryProfile,
    SiteLimits,
    SiteProfile,
)

# ---------------- 关键词与模式 ----------------

HIGH_VALUE_KEYWORDS = {
    "通知公告": 3.0,
    "规章制度": 3.0,
    "本科生培养": 3.0,
    "研究生培养": 3.0,
    "学生工作": 3.0,
    "教学管理": 3.0,
    "奖学金": 3.0,
    "助学金": 3.0,
    "评奖评优": 3.0,
    "推免": 3.0,
    "招生": 2.5,
    "就业": 2.5,
    "办事指南": 3.0,
    "常用下载": 3.0,
    "公示": 2.5,
    "下载专区": 2.5,
    "培养方案": 2.5,
    "教务": 2.5,
    "学生事务": 3.0,
    "政策文件": 3.0,
    "管理制度": 3.0,
    "文档下载": 2.5,
}
NEGATIVE_KEYWORDS = {
    "校友": -3.0,
    "新闻动态": -2.0,
    "学院新闻": -2.0,
    "图片新闻": -2.0,
    "媒体": -2.0,
    "讲座": -1.5,
    "学术报告": -1.5,
    "活动": -1.5,
    "师资队伍": -2.0,
    "教师": -1.5,
    "科研成果": -2.0,
    "联系我们": -4.0,
    " English": -2.0,
    "旧版": -3.0,
}
FOOTER_HINT_RE = re.compile(r"版权|Copyright|备案|沪ICP|地址：|邮编|联系我们|校长信箱", re.I)

# URL 形态：栏目列表页 / 文章页
_LIST_URL_RES = {
    "wp3": re.compile(r"/(?:[0-9a-z]{2}/){0,3}(?:list|index|default)\.htm", re.I),
    "gs_home": re.compile(r"/Home/List/\d+", re.I),
    "generic": re.compile(r"list|column|category|index", re.I),
}
_ARTICLE_URL_RES = {
    "wp3": re.compile(r"(?:/info/\d+\.htm|/[0-9a-z]{2,4}/c\d+a\d+/page\.htm|/\d+\.htm)$", re.I),
    "gs_home": re.compile(r"/Home/Detail/\d+", re.I),
    "generic": re.compile(r"/(?:detail|info|article|content|show|view)[/?=].*\d", re.I),
}
_DATE_IN_LIST_RE = re.compile(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}")
_WP3_MARK_RE = re.compile(
    r"wp_articlecontent|wp_paging|wp_listcolumn|createPageHTML|/_upload/", re.I
)

_CMS_ARTICLE_PROFILES = {
    "wp3": ArticleProfile(
        title_selectors=[".arti_title", "h1"],
        date_selectors=[".arti_update", ".arti_metas", ".arti_publisher"],
        content_selectors=[".wp_articlecontent", ".wp_entry", ".article_content"],
    ),
    "gs_home": ArticleProfile(
        title_selectors=["h1", ".detail-title", ".arti_title"],
        date_selectors=[".info", ".detail-info", ".time"],
        content_selectors=[".content", ".detail", "article", ".v_news_content"],
    ),
    "generic": ArticleProfile(),
}

_CATEGORY_MAP = [
    (re.compile(r"奖学金|助学金|奖助|勤工助学|助学贷款"), "奖助学金"),
    (re.compile(r"评奖评优|评优|表彰"), "评奖评优"),
    (re.compile(r"推免|保研|研究生推荐|免试"), "推免升学"),
    (re.compile(r"就业|实习|招聘|生涯|职业"), "实习就业"),
    (re.compile(r"招生|本科招生|研究生招生"), "学工事务"),
    (re.compile(r"通知|规章|制度|培养|教学|学生|办事|下载|公示|教务|政策"), "学工事务"),
]


@dataclass
class CandidateColumn:
    name: str
    list_url: str
    score: float
    reasons: list[str]
    article_selector: str = ""
    url_prefix: str = ""
    sample_articles: list[str] = field(default_factory=list)
    is_list_page: bool = False


@dataclass
class DiscoveryReport:
    root_url: str
    host: str
    cms_type: str = "generic"
    site_name: str = ""
    columns: list[CandidateColumn] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"站点勘探 {self.host}（CMS: {self.cms_type}）{self.site_name}",
            f"  入选栏目 {len(self.columns)} 个：",
        ]
        for c in self.columns:
            lines.append(f"    {c.name}  score={c.score:.1f}  {c.list_url}")
            lines.append(
                f"      依据: {', '.join(c.reasons)}；样例文章 {len(c.sample_articles)} 篇"
            )
        if self.skipped:
            lines.append(f"  忽略 {len(self.skipped)} 个：")
            for s in self.skipped:
                lines.append(f"    {s['name']}（{s['reason']}）")
        for w in self.warnings:
            lines.append(f"  警告: {w}")
        return "\n".join(lines)


# ---------------- CMS 识别 ----------------


def detect_cms(html: str, url: str) -> str:
    """wp3（wp_* class + list.htm + /_upload/）> gs_home（/Home/List|Detail）> generic。"""
    if _WP3_MARK_RE.search(html or ""):
        return "wp3"
    if re.search(r"/Home/(?:List|Detail)/\d+", html or "") or re.search(
        r"/Home/(?:List|Detail)/\d+", url
    ):
        return "gs_home"
    return "generic"


def map_category(column_name: str) -> str:
    for pat, cat in _CATEGORY_MAP:
        if pat.search(column_name):
            return cat
    return "其他"


# ---------------- 主页链接提取与初筛 ----------------


def _abs_same_host(base: str, href: str, host: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    full = urldefrag(urljoin(base, href))[0]
    if not full.startswith(("http://", "https://")):
        return None
    if urlparse(full).netloc != host:
        return None
    return full


def extract_nav_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """主页站内链接（去重保序，text, url）；导航区优先，其余锚文本兜底。"""
    host = urlparse(base_url).netloc
    soup = BeautifulSoup(html or "", "html.parser")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    nav_els = soup.select("nav, .nav, .menu, .navbar, header, .header, .wp_listcolumn, .column")
    containers = [e for e in nav_els if isinstance(e, Tag)] or [soup]
    for container in containers:
        for a in container.find_all("a", href=True):
            text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            full = _abs_same_host(base_url, str(a["href"]), host)
            if not full or not text or len(text) > 20:
                continue
            if full in seen:
                continue
            seen.add(full)
            out.append((text, full))
    return out


def prescore_link(text: str, url: str) -> tuple[float, list[str]]:
    """主页链接初筛：高价值关键词加分，页脚/新闻类减分。"""
    score, reasons = 0.0, []
    for kw, w in HIGH_VALUE_KEYWORDS.items():
        if kw in text:
            score += w
            reasons.append(f"关键词[{kw}]")
            break
    for kw, w in NEGATIVE_KEYWORDS.items():
        if kw in text:
            score += w
            reasons.append(f"负面词[{kw.strip()}]")
            break
    if _LIST_URL_RES["wp3"].search(url) or _LIST_URL_RES["gs_home"].search(url):
        score += 1.0
        reasons.append("列表页URL")
    if FOOTER_HINT_RE.search(text):
        score -= 4.0
        reasons.append("页脚特征")
    return score, reasons


# ---------------- 栏目页分析 ----------------


def _selector_signature(a: Tag) -> str:
    """锚点的容器签名：最近带 class 的父级（用于找重复 DOM 结构）。"""
    node: Tag | None = a
    for _ in range(4):
        if node is None:
            break
        cls = node.get("class") if isinstance(node, Tag) else None
        if cls:
            return f"{node.name}.{'.'.join(cls)}"
        node = node.parent if isinstance(node.parent, Tag) else None
    return a.name or "a"


def analyze_column_page(
    html: str, url: str, cms_type: str, sample_n: int = 5
) -> tuple[bool, str, str, list[str], list[str]]:
    """判断是否为栏目列表页；返回 (is_list, selector, url_prefix, samples, evidence)。"""
    soup = BeautifulSoup(html or "", "html.parser")
    host = urlparse(url).netloc
    article_re = _ARTICLE_URL_RES.get(cms_type, _ARTICLE_URL_RES["generic"])

    # 按容器签名分组统计文章形态链接：重复结构是列表页的核心证据
    groups: dict[str, list[str]] = {}
    for a in soup.find_all("a", href=True):
        full = _abs_same_host(url, str(a["href"]), host)
        if not full or not article_re.search(urlparse(full).path):
            continue
        groups.setdefault(_selector_signature(a), []).append(full)

    evidence: list[str] = []
    best_sig, best_links = "", []
    for sig, links in groups.items():
        uniq = list(dict.fromkeys(links))
        if len(uniq) > len(best_links):
            best_sig, best_links = sig, uniq
    dates = len(_DATE_IN_LIST_RE.findall(html or ""))
    if dates >= 3:
        evidence.append(f"日期密度[{dates}]")
    if len(best_links) >= 3:
        evidence.append(f"重复结构[{best_sig}]x{len(best_links)}")

    is_list = len(best_links) >= 3 and dates >= 1
    if not is_list:
        return False, "", "", [], evidence

    # selector：容器 class 下的 a；url_prefix：样例链接的最长公共前缀
    selector = f".{best_sig.split('.', 1)[1]} a" if "." in best_sig else "a"
    prefix = best_links[0]
    for link in best_links[1:]:
        while prefix and not link.startswith(prefix):
            prefix = prefix[:-1]
    prefix = prefix[: prefix.rfind("/") + 1] if "/" in prefix else prefix
    return True, selector, prefix, best_links[:sample_n], evidence


def score_column_page(text: str, is_list: bool, dates_evidence: list[str]) -> float:
    score = 0.0
    if is_list:
        score += 2.0
    for ev in dates_evidence:
        if ev.startswith("日期密度"):
            score += min(int(re.search(r"\d+", ev).group()), 10) * 0.2
        elif ev.startswith("重复结构"):
            score += min(int(ev.rsplit("x", 1)[1]), 15) * 0.2
    return score


# ---------------- 主流程 ----------------


def discover_site(
    root_url: str,
    fetcher: SafeFetcher,
    *,
    max_probe: int = 15,
    max_columns: int = 12,
    min_score: float = 3.0,
) -> tuple[SiteProfile, DiscoveryReport]:
    """勘探学院主页，生成确定性 SiteProfile + 发现报告。失败全部走 warnings，不抛出。"""
    root_url = root_url if root_url.endswith("/") else root_url + "/"
    host = urlparse(root_url).netloc
    report = DiscoveryReport(root_url=root_url, host=host)

    home = fetcher.fetch(root_url, "html")
    if not home.ok:
        report.warnings.append(f"主页抓取失败: {home.status} {home.error}")
        return SiteProfile(site_name=host, root_url=root_url, allowed_hosts=[host]), report

    html = home.text()
    soup = BeautifulSoup(html, "html.parser")
    ttag = soup.find("title")
    report.site_name = re.sub(r"\s+", " ", ttag.get_text(strip=True)) if ttag else host
    report.cms_type = detect_cms(html, home.final_url or root_url)

    links = extract_nav_links(html, home.final_url or root_url)
    if not links:
        report.warnings.append("主页未发现站内导航链接")

    # 初筛：高价值候选进入勘探；零分/负分栏目记入忽略清单（可审计）
    probes: list[tuple[str, str, float, list[str]]] = []
    for text, url in links:
        s, reasons = prescore_link(text, url)
        if s <= 0:
            report.skipped.append(
                {"name": text, "url": url, "reason": ",".join(reasons) or "无高价值特征"}
            )
            continue
        probes.append((text, url, s, reasons))
    probes.sort(key=lambda p: p[2], reverse=True)
    probes = probes[:max_probe]

    for text, url, pre, reasons in probes:
        res = fetcher.fetch(url, "html")
        if not res.ok:
            report.skipped.append({"name": text, "url": url, "reason": f"抓取失败:{res.status}"})
            continue
        is_list, selector, prefix, samples, evidence = analyze_column_page(
            res.text(), res.final_url or url, report.cms_type
        )
        if not is_list:
            report.skipped.append(
                {
                    "name": text,
                    "url": url,
                    "reason": f"非列表页（{';'.join(evidence) or '无重复结构'}）",
                }
            )
            continue
        total = pre + score_column_page(text, is_list, evidence)
        if total < min_score:
            report.skipped.append({"name": text, "url": url, "reason": f"总分不足({total:.1f})"})
            continue
        report.columns.append(
            CandidateColumn(
                name=text,
                list_url=res.final_url or url,
                score=total,
                reasons=reasons + evidence,
                article_selector=selector,
                url_prefix=prefix,
                sample_articles=samples,
                is_list_page=True,
            )
        )

    report.columns.sort(key=lambda c: c.score, reverse=True)
    report.columns = report.columns[:max_columns]
    profile = SiteProfile(
        site_name=report.site_name,
        root_url=root_url,
        allowed_hosts=[host],
        cms_type=report.cms_type,
        categories=[
            CategoryProfile(
                name=c.name,
                list_url=c.list_url,
                category=map_category(c.name),
                article_selector=c.article_selector or "a",
                url_prefix=c.url_prefix,
                max_list_pages=10,
                max_articles=200,
            )
            for c in report.columns
        ],
        article=_CMS_ARTICLE_PROFILES.get(report.cms_type, ArticleProfile()),
        limits=SiteLimits(),
    )
    if not report.columns:
        report.warnings.append("未发现高价值栏目（可能需要人工编写 profile）")
    return profile, report
