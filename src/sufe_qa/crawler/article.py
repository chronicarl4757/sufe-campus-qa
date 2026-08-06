"""文章页结构化解析：元数据提取、正文清洗与附件候选发现。

职责拆分（规格 §六/§七）：
- 文章元数据解析：标题回退链、发布日期规范化、面包屑、发布单位；
- 正文清洗与标准化：trafilatura 抽取 + 复用 ingest.parsers 的导航剥离；
- 附件候选发现：综合 URL 后缀/链接文字/download 属性/路径特征/嵌入元素打分，
  支持无后缀下载链接，不只看 .pdf/.docx。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from sufe_qa.crawler.profile import ArticleProfile
from sufe_qa.ingest.parsers import _breadcrumb_title, _strip_nav_soup

# ---------------- 附件识别 ----------------

ATTACH_EXTS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
    ".7z",
}
ATTACH_TEXT_RE = re.compile(r"附件|下载|点击下载|申请表|材料|名单|细则|办法|通知|表格|文件|指南")
ATTACH_PATH_RE = re.compile(
    r"/_upload/|/upload/|/files/|/download/|/system/resource/|download\.jsp|fileId="
    r"|mod=pdf|op=getstream|viewer\.html",
    re.I,
)
ATTACH_SCORE_THRESHOLD = 0.5

_DATE_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
# 阅读计数行每次访问都变，剥掉避免 content_hash 抖动导致伪更新
_VIEW_COUNT_RE = re.compile(
    r"^\s*(阅读量|浏览量|阅读数|浏览次数|点击数|访问量)\s*[:：]?\s*\d+\s*$", re.M
)
_DATE_LABEL_RE = re.compile(
    r"(?:发布日期|发布时间|发稿时间)\s*[:：]?\s*"
    r"(20\d{2}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2})"
)
_PUBLISHER_RE = re.compile(r"(?:来源|发布单位|发布机构)\s*[:：]\s*([一-龥A-Za-z0-9（）()·]{2,30})")

_BREADCRUMB_SELECTORS = [
    ".wp_breadcrumb",
    ".breadcrumb",
    ".crumbs",
    "[class*=crumb]",
    "[class*=position]",
    "[class*=location]",
]
# 面包屑里常见的当前位置/首页前缀，非文章主题
_BREADCRUMB_DROP = {"首页", "当前位置", "网站首页", "home", "index"}

# 站点通用栏目名作为文章标题即无语义（gs 站 h1 常是栏目名而非文章名）
_GENERIC_TITLES = {
    "首页",
    "通知公告",
    "欢迎访问",
    "无标题",
    "untitled",
    "index",
    "default",
    "管理规定",
    "规章制度",
    "新闻动态",
    "学院新闻",
    "图片新闻",
    "最新动态",
    "综合新闻",
    "招生信息",
    "信息公开",
    "下载专区",
    "办事指南",
    "机构设置",
    "联系我们",
    "公示公告",
    "公告公示",
    "公示专栏",
    "硕士生招生",
}
_HASH_TITLE_RE = re.compile(r"^[0-9a-f]{8,}$", re.I)


@dataclass
class AttachmentCandidate:
    source_page_url: str
    requested_url: str  # 相对链接已按文章页 URL 绝对化
    anchor_text: str
    candidate_score: float
    discovery_reason: list[str]


@dataclass(frozen=True)
class DateEvidence:
    value: str
    evidence: str = ""
    confidence: float = 0.0
    conflict: bool = False


@dataclass
class ArticleMeta:
    title: str
    publish_date: str  # YYYY-MM-DD 或 "unknown"；绝不回填抓取时间
    publisher: str
    breadcrumbs: list[str]
    body_text: str
    attachments: list[AttachmentCandidate]
    title_source: str  # profile_selector|og|h1|trafilatura|html_title|url_filename|none
    low_quality_title: bool
    publish_date_evidence: str = ""
    publish_date_confidence: float = 0.0
    date_conflict: bool = False


def _normalize_date(text: str) -> str:
    """把各种中文/符号日期统一为 YYYY-MM-DD；识别不了返回 "unknown"。"""
    m = _DATE_RE.search(text or "")
    if not m:
        return "unknown"
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return "unknown"
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


_SUDYFILE_TITLE_RE = re.compile(r"'title'\s*:\s*'([^']+)'")


def _sudyfile_title(attr: str) -> str:
    """wp3 sudyfile-attr="{'title':'xxx.pdf'}" 中的真实文件名。"""
    match = _SUDYFILE_TITLE_RE.search(attr or "")
    return _clean_title(match.group(1)) if match else ""


def _strip_view_counts(text: str) -> str:
    """剥阅读计数行（每次访问都变，会让 content_hash 抖动出伪更新）。"""
    lines = [ln for ln in _VIEW_COUNT_RE.sub("", text).split("\n")]
    return "\n".join(ln for ln in lines if ln.strip())


def _url_filename_title(url: str) -> str:
    seg = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", seg).strip()


def _title_tag_segments(raw: str) -> list[str]:
    """<title> 面包屑分段（"文章名|栏目|… - 站名"），用于识别栏目名冒充的 h1。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    if not m:
        return []
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    if "|" not in t and "｜" not in t:
        return []
    segs = [s.strip() for s in re.split(r"[|｜]", t) if s.strip()]
    # 末段常带 " - 站名" 后缀，比较时剥掉
    return [re.split(r"\s+[-—–]\s+", s)[0].strip() for s in segs]


def _extract_title(
    soup: BeautifulSoup, raw: str, meta, profile: ArticleProfile, url: str
) -> tuple[str, str, bool]:
    """标题回退链：profile selector → og:title → h1 → 面包屑<title> → trafilatura → <title> → URL 文件名。

    每个阶段都先用 is_low_quality_title 校验候选：高校 CMS 常把栏目名塞进 h1
    （如 gs 站的“管理规定”），命中即视为本阶段无产出，继续向下回退。
    """
    for sel in profile.title_selectors:
        try:
            el = soup.select_one(sel)
        except Exception:
            continue
        if el and (t := _clean_title(el.get_text(" ", strip=True))) and not is_low_quality_title(t):
            return t, "profile_selector", False
    og = soup.find("meta", attrs={"property": "og:title"}) or soup.find(
        "meta", attrs={"name": "og:title"}
    )
    if og and (t := _clean_title(str(og.get("content", "")))) and not is_low_quality_title(t):
        return t, "og", False
    h1 = soup.find("h1")
    if h1 and (t := _clean_title(h1.get_text(" ", strip=True))) and not is_low_quality_title(t):
        # gs 等 CMS 详情页的 h1 常是栏目名：若它出现在 <title> 面包屑的非首段，
        # 说明面包屑首段才是文章名，跳过 h1 继续回退
        if t.lower() not in {s.lower() for s in _title_tag_segments(raw)[1:]}:
            return t, "h1", False
    # 面包屑式 <title>（"文章名|栏目 - 站名"）优先于 trafilatura 的半清洗标题
    if (t := _breadcrumb_title(raw)) and not is_low_quality_title(t):
        return t, "html_title", False
    if meta is not None and getattr(meta, "title", None):
        if (t := _clean_title(str(meta.title))) and not is_low_quality_title(t):
            return t, "trafilatura", False
    ttag = soup.find("title")
    if ttag and (t := _clean_title(ttag.get_text(strip=True))) and not is_low_quality_title(t):
        return t, "html_title", False
    if t := _url_filename_title(url):
        # URL 文件名兜底本身即视为低质量标题信号（常为哈希或编号）
        return t, "url_filename", True
    return _url_filename_title(url) or url, "none", True


def _extract_date(soup: BeautifulSoup, meta, profile: ArticleProfile, raw: str) -> DateEvidence:
    candidates: list[tuple[int, str, str, float]] = []
    # 页面明确标注的发布日期是最高置信来源。先解析它，同时继续收集其他来源，
    # 这样可以报告冲突而不是静默覆盖。
    for match in _DATE_LABEL_RE.finditer(raw):
        value = _normalize_date(match.group(1))
        if value != "unknown":
            candidates.append((0, value, re.sub(r"\s+", "", match.group(0)), 1.0))
    for sel in profile.date_selectors:
        try:
            el = soup.select_one(sel)
        except Exception:
            continue
        if el and (d := _normalize_date(el.get_text(" ", strip=True))) != "unknown":
            candidates.append((1, d, _clean_title(el.get_text(" ", strip=True)), 0.9))
    if meta is not None:
        d = _normalize_date(str(getattr(meta, "date", "") or ""))
        if d != "unknown":
            candidates.append((2, d, f"metadata.date={d}", 0.75))
    if not candidates:
        return DateEvidence("unknown")
    candidates.sort(key=lambda item: item[0])
    _, value, evidence, confidence = candidates[0]
    return DateEvidence(
        value=value,
        evidence=evidence,
        confidence=confidence,
        conflict=len({candidate[1] for candidate in candidates if candidate[3] >= 0.9}) > 1,
    )


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    for sel in _BREADCRUMB_SELECTORS:
        try:
            el = soup.select_one(sel)
        except Exception:
            continue
        if not el:
            continue
        raw = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        parts = [p.strip() for p in re.split(r"[>»→/›]|(?<=\S)\s{2,}(?=\S)", raw) if p.strip()]
        parts = [p for p in parts if p.lower() not in _BREADCRUMB_DROP]
        if parts:
            return parts
    return []


def _extract_body(soup: BeautifulSoup, raw: str, profile: ArticleProfile) -> tuple[str, object]:
    """返回 (正文, trafilatura metadata)。content_selectors 优先，trafilatura 兜底。"""
    import trafilatura

    meta = trafilatura.extract_metadata(raw)
    for sel in profile.content_selectors:
        try:
            els = soup.select(sel)
        except Exception:
            continue
        text = "\n".join(el.get_text("\n", strip=True) for el in els if el.get_text(strip=True))
        if len(text) >= 50:
            return _strip_view_counts(_strip_nav_soup(text.strip())), meta
    text = trafilatura.extract(raw, include_comments=False, include_tables=True) or ""
    return _strip_view_counts(_strip_nav_soup(text.strip())), meta


def _score_candidate(
    url: str, anchor: str, embedded: bool, has_download_attr: bool
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    path = urlparse(url).path.lower()
    url_lower = url.lower()
    if any(path.endswith(ext) for ext in ATTACH_EXTS):
        score += 0.5
        reasons.append("extension")
    if has_download_attr:
        score += 0.3
        reasons.append("download_attr")
    if anchor and ATTACH_TEXT_RE.search(anchor):
        score += 0.3
        reasons.append("anchor_text")
    if ATTACH_PATH_RE.search(url_lower) or ATTACH_PATH_RE.search(path):
        score += 0.3
        reasons.append("url_path")
    if embedded:
        score += 0.4
        reasons.append("embedded")
    return score, reasons


def discover_attachments(soup: BeautifulSoup, page_url: str) -> list[AttachmentCandidate]:
    """从文章页发现附件候选：a[href] + iframe/embed/object 嵌入元素。"""
    cands: dict[str, AttachmentCandidate] = {}

    def add(raw_url: str, anchor: str, embedded: bool, has_download_attr: bool) -> None:
        raw_url = (raw_url or "").strip()
        if not raw_url or raw_url.startswith(("#", "javascript:", "mailto:", "tel:")):
            return
        full = urldefrag(urljoin(page_url, raw_url))[0]
        if not full.startswith(("http://", "https://")):
            return
        score, reasons = _score_candidate(full, anchor, embedded, has_download_attr)
        if score < ATTACH_SCORE_THRESHOLD:
            return
        if full in cands:
            c = cands[full]
            c.candidate_score = max(c.candidate_score, score)
            for r in reasons:
                if r not in c.discovery_reason:
                    c.discovery_reason.append(r)
            if anchor and not c.anchor_text:
                c.anchor_text = anchor
            return
        cands[full] = AttachmentCandidate(
            source_page_url=page_url,
            requested_url=full,
            anchor_text=anchor,
            candidate_score=score,
            discovery_reason=reasons,
        )

    for a in soup.find_all("a", href=True):
        anchor = _clean_title(a.get_text(" ", strip=True))
        if not anchor:
            anchor = _sudyfile_title(str(a.get("sudyfile-attr") or ""))
        add(
            str(a["href"]),
            anchor,
            embedded=False,
            has_download_attr=a.has_attr("download"),
        )
    for tag, attr in (("iframe", "src"), ("embed", "src"), ("object", "data")):
        for el in soup.find_all(tag):
            if el.get(attr):
                add(str(el[attr]), "", embedded=True, has_download_attr=False)
    # wp3 内嵌 PDF 播放器：正式制度常以 div/span[pdfsrc] 挂载，文件名在 sudyfile-attr
    for el in soup.select("[pdfsrc]"):
        add(
            str(el.get("pdfsrc") or ""),
            _sudyfile_title(str(el.get("sudyfile-attr") or "")),
            embedded=True,
            has_download_attr=False,
        )

    return sorted(cands.values(), key=lambda c: c.candidate_score, reverse=True)


def is_low_quality_title(title: str) -> bool:
    t = (title or "").strip()
    return not t or bool(_HASH_TITLE_RE.match(t)) or t.lower() in _GENERIC_TITLES


def parse_article(
    html: str,
    url: str,
    profile: ArticleProfile | None = None,
    default_publisher: str = "",
) -> ArticleMeta:
    """把文章页 HTML 解析为结构化元数据 + 清洗正文 + 附件候选。"""
    profile = profile or ArticleProfile()
    soup = BeautifulSoup(html, "html.parser")
    body, meta = _extract_body(soup, html, profile)
    title, title_source, url_low = _extract_title(soup, html, meta, profile, url)
    publish_date = _extract_date(soup, meta, profile, html)
    publisher = default_publisher
    m = _PUBLISHER_RE.search(html)
    if m:
        publisher = m.group(1).strip()
    return ArticleMeta(
        title=title,
        publish_date=publish_date.value,
        publisher=publisher,
        breadcrumbs=_extract_breadcrumbs(soup),
        body_text=body,
        attachments=discover_attachments(soup, url),
        title_source=title_source,
        low_quality_title=url_low or is_low_quality_title(title),
        publish_date_evidence=publish_date.evidence,
        publish_date_confidence=publish_date.confidence,
        date_conflict=publish_date.conflict,
    )
