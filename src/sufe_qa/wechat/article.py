"""微信公众号单篇文章抓取与解析：WechatArticleFetcher。

只面向公开的 mp.weixin.qq.com 文章页（/s/<token> 与 /s?__biz=..&mid=..&idx=.. 长链），
不依赖任何微信私有接口。元数据取自页面内嵌 JS 变量（msg_title/nickname/createTime/
biz/mid/idx/author），正文限定在 #js_content 容器内清洗，平台 UI 天然被排除；
账号自行添加的关注引导/二维码签名等行内样板按短行规则过滤。

robots 说明：mp.weixin.qq.com 的 robots.txt 为 UA=* 全站 Disallow，但其文章页本身是
用户分享即可公开访问的页面。这里以 respect_robots=False + allowed_hosts 收敛 + 默认
2 秒限速抓取"已被显式给定的单篇 URL"，不做站内发现式爬取。
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urldefrag, urlparse, urlunparse

from bs4 import BeautifulSoup, NavigableString, Tag

from sufe_qa.crawler.fetcher import SafeFetcher
from sufe_qa.wechat.ocr import ocr_article_images

logger = logging.getLogger(__name__)

WECHAT_HOST = "mp.weixin.qq.com"
# 桌面浏览器 UA 即可稳定取到正文；项目 UA 会被微信 WAF 302 到错误页
WECHAT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ---------------- 页面级异常形态 ----------------
# 风控验证页（mmbizwap/secitptpage/verify.html）：频控或链接受限，任务规格 §三十五
# 归 temporary_unavailable 类，报告后跳过，不做绕过。
_VERIFY_MARKERS = ("secitptpage/verify.html", "环境异常", "访问过于频繁", "操作过于频繁")
# 内容不可用：被发布者删除 / 违规不可见 / 参数错误
_GONE_MARKERS = (
    "该内容已被发布者删除",
    "此内容因违规无法查看",
    "参数错误",
    "链接已过期",
    "未知错误",
)

# ---------------- 正文容器与组件清理 ----------------
_CONTENT_SELECTORS = ("#js_content", "div.rich_media_content", "#img-content")
# 平台组件/播放器/公众号名片：不是正文知识
_DROP_TAGS = (
    "script",
    "style",
    "svg",
    "iframe",
    "input",
    "mp-common-profile",
    "mpvoice",
    "mp-common-videosnap",
    "mp-common-mpaudio",
    "mp-common-miniprogram",
    "mp-common-product",
    "qqmusic",
)
# 账号签名/关注引导类短行（独立成行才删；正文中的表格、电话、步骤不受影响）
_SIGNATURE_LINE_RES = [
    re.compile(p)
    for p in (
        r"^微信?扫一扫",
        r"^(长按|扫描|扫码).{0,6}二维码",
        r"^识别二维码",
        r"^(点击|长按)?关注(我们|公众号|本平台)?$",
        r"^点击.{0,4}蓝字.?关注",
        r"^设为星标",
        r"^星标关注",
        r"^分享.{0,2}[，,、 ].{0,2}(点赞|在看)",
        r"^(点赞|在看|分享|收藏|喜欢){1}[，,、/ ]*(点赞|在看|分享|收藏)*$",
        r"^阅读原文$",
        r"^喜欢此内容的人还喜欢$",
        r"^预览时标签不可点$",
    )
]

_JS_VAR_RES = {
    "title": re.compile(r"var\s+msg_title\s*=\s*'((?:[^'\\]|\\.)*)'"),
    "account": re.compile(r'var\s+nickname\s*=\s*htmlDecode\("((?:[^"\\]|\\.)*)"\)'),
    "create_time": re.compile(r"var\s+createTime\s*=\s*'((?:[^'\\]|\\.)*)'"),
    "biz": re.compile(r'var\s+biz\s*=\s*"((?:[^"\\]|\\.)*)"'),
    "mid": re.compile(r'var\s+mid\s*=\s*"((?:[^"\\]|\\.)*)"'),
    "idx": re.compile(r'var\s+idx\s*=\s*"((?:[^"\\]|\\.)*)"'),
    "author": re.compile(r'var\s+author\s*=\s*"((?:[^"\\]|\\.)*)"'),
    "user_name": re.compile(r'var\s+user_name\s*=\s*"((?:[^"\\]|\\.)*)"'),
}

_DATE_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
# 长链 query 中的跟踪参数（scene/chksm/nwr_flag 等不影响文章身份）
_TRACKING_PARAMS = {"scene", "chksm", "nwr_flag", "xtrack", "subscene", "clicktime", "enterid"}


@dataclass(frozen=True)
class WechatArticle:
    """单篇公众号文章的结构化结果；status != ok 时字段可为空。"""

    source_url: str  # 请求 URL（规范化后）
    canonical_url: str  # biz+mid+idx 稳定身份 URL；取不到则为规范化 source_url
    doc_key: str  # wechat:{biz}:{mid}:{idx} 或 url:{canonical_url}
    title: str = ""
    account_name: str = ""
    publish_date: str = "unknown"
    author: str = ""
    wechat_biz: str = ""
    wechat_mid: str = ""
    wechat_idx: str = ""
    wechat_user_name: str = ""
    body_markdown: str = ""
    image_count: int = 0
    status: str = "ok"  # ok | verify_required | gone | invalid_response | fetch 失败状态
    error: str = ""
    warnings: list[str] = field(default_factory=list)


def _js_var(raw: str, name: str) -> str:
    m = _JS_VAR_RES[name].search(raw)
    if not m:
        return ""
    value = m.group(1).replace(r"\'", "'").replace(r"\"", '"').replace("\\\\", "\\")
    return html_lib.unescape(value).strip()


def _normalize_date(text: str) -> str:
    m = _DATE_RE.search(text or "")
    if not m:
        return "unknown"
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return "unknown"
    return f"{y:04d}-{mo:02d}-{d:02d}"


def normalize_wechat_url(url: str) -> str:
    """规范化文章 URL：去 fragment/跟踪参数，host 小写；不改变文章身份参数。"""
    p = urlparse(urldefrag((url or "").strip())[0])
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    return urlunparse(("https", WECHAT_HOST, p.path.rstrip("/") or "/", "", urlencode(query), ""))


def canonical_identity_url(source_url: str, biz: str = "", mid: str = "", idx: str = "") -> str:
    """公众号文章稳定身份（规格 §十八）：biz+mid+idx 优先，退化为规范化 URL。

    页面的 biz/mid/idx JS 变量比 URL query 更可信（/s/<token> 短链本身不带身份参数）。
    """
    biz = (biz or "").strip()
    mid = (mid or "").strip()
    idx = (idx or "").strip()
    if biz and mid and idx:
        return f"https://{WECHAT_HOST}/s?__biz={biz}&mid={mid}&idx={idx}"
    return normalize_wechat_url(source_url)


def doc_key_for(article_url: str, biz: str = "", mid: str = "", idx: str = "") -> str:
    canonical = canonical_identity_url(article_url, biz, mid, idx)
    if "__biz=" in canonical:
        p = urlparse(canonical)
        q = dict(parse_qsl(p.query))
        return f"wechat:{q.get('__biz', '')}:{q.get('mid', '')}:{q.get('idx', '')}"
    return f"url:{canonical}"


def _flatten_content(el: Tag) -> tuple[str, int, list[str]]:
    """把正文容器转成 markdown 风格纯文本；返回 (文本, 图片数, 图片 URL 列表)。

    - 表格按行合并（一行一格间空格分隔），名单/分数线不碎行；
    - 有序/无序列表项保留 "- " 前缀；
    - 图片不丢弃：替换为占位行 "{{WX_IMG_i}}"，URL 按序返回，供 OCR 回填；
      未启用 OCR 时占位行会在清洗阶段被移除，行为与旧版一致；
    - 平台组件标签整体删除。
    """
    clone = BeautifulSoup(str(el), "html.parser")
    for tag in clone.find_all(_DROP_TAGS):
        tag.decompose()
    image_urls: list[str] = []
    for img in clone.find_all("img"):
        url = (img.get("data-src") or img.get("src") or "").strip()
        if url.startswith("http"):
            image_urls.append(url)
            img.replace_with(NavigableString(f"\n{{{{WX_IMG_{len(image_urls) - 1}}}}}\n"))
        else:
            img.decompose()
    image_count = len(clone.find_all("img")) + len(image_urls)
    for br in clone.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for table in clone.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            row = " ".join(c for c in cells if c)
            if row.strip():
                rows.append(row.strip())
        table.replace_with(NavigableString("\n".join(rows)))
    for li in clone.find_all("li"):
        # 整体替换为单个文本节点：get_text("\n") 会把多节点拆行，破坏 "- " 前缀
        li.replace_with(NavigableString(f"- {li.get_text(' ', strip=True)}\n"))
    text = clone.get_text("\n", strip=True)
    return text, image_count, image_urls


def _resolve_image_placeholders(text: str, image_urls: list[str], *, ocr: bool) -> str:
    """把正文里的 {{WX_IMG_i}} 占位行替换为 OCR 文本；未启用 OCR 时移除占位行。"""
    if "{{WX_IMG_" not in text:
        return text
    ocr_texts: dict[int, str] = {}
    if ocr and image_urls:
        ocr_texts = ocr_article_images(image_urls, ua=WECHAT_UA)
    out: list[str] = []
    for line in text.split("\n"):
        m = re.fullmatch(r"\{\{WX_IMG_(\d+)\}\}", line.strip())
        if m is None:
            out.append(line)
            continue
        if not ocr:
            continue  # 未启用 OCR：移除占位行，与旧版"丢弃图片"行为一致
        content = ocr_texts.get(int(m.group(1)), "")
        if content:
            out.append(f"[图片识别] {content}")
    # 压缩可能产生的连续空行
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def _clean_lines(text: str) -> str:
    """行级清洗：删账号签名/关注引导短行，压缩空行与连续重复行。"""
    out: list[str] = []
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if len(line) <= 30 and any(p.search(line) for p in _SIGNATURE_LINE_RES):
            continue
        if out and out[-1] == line:
            continue  # 公众号正文常整块重复装饰性短行
        out.append(line)
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _extract_body(soup: BeautifulSoup, *, ocr: bool = False) -> tuple[str, int, list[str]]:
    """返回 (正文 markdown, 图片数, warnings)。只在正文容器内提取。"""
    warnings: list[str] = []
    for sel in _CONTENT_SELECTORS:
        try:
            el = soup.select_one(sel)
        except Exception:
            continue
        if el is None:
            continue
        text, image_count, image_urls = _flatten_content(el)
        cleaned = _resolve_image_placeholders(_clean_lines(text), image_urls, ocr=ocr)
        if cleaned:
            if sel != _CONTENT_SELECTORS[0]:
                warnings.append(f"正文容器回退到 {sel}")
            return cleaned, image_count, warnings
    return "", 0, warnings


def normalize_wechat_content(content_html: str, *, ocr: bool = False) -> tuple[str, int, list[str]]:
    """统一正文 normalize（规格 §十二）：输入完整文章页或 WeRSS 已存 content_html
    片段（片段可能自带 #js_content 容器，也可能就是正文内容本身），输出
    (cleaned markdown, 图片数, warnings)。清洗规则与页面解析完全一致。
    """
    warnings: list[str] = []
    soup = BeautifulSoup(content_html or "", "html.parser")
    root: Tag = soup
    for sel in _CONTENT_SELECTORS:
        try:
            el = soup.select_one(sel)
        except Exception:
            continue
        if el is not None:
            root = el
            break
    text, image_count, image_urls = _flatten_content(root)
    return (
        _resolve_image_placeholders(_clean_lines(text), image_urls, ocr=ocr),
        image_count,
        warnings,
    )


def _identity_from_url(url: str) -> tuple[str, str, str]:
    """长链 query 自带 __biz/mid/idx：WeRSS 永久链接的身份来源（JS 变量缺失时兜底）。"""
    q = dict(parse_qsl(urlparse(url or "").query))
    return q.get("__biz", ""), q.get("mid", ""), q.get("idx", "")


def parse_wechat_content(
    content_html: str,
    url: str,
    *,
    title: str = "",
    account: str = "",
    publish_date: str = "",
    content_text: str = "",
    ocr: bool = False,
) -> WechatArticle:
    """用 WeRSS 已存正文构建 WechatArticle（规格 §十）：content_html 优先，
    content（纯文本）兜底；元数据来自发现层，页面 JS 变量不可得时身份从长链 URL 解析。
    ocr=True 时对 content_html 中的正文图片做文字识别回填。
    """
    source_url = normalize_wechat_url(url)
    biz, mid, idx = _identity_from_url(source_url)
    body, image_count = "", 0
    warnings: list[str] = []
    if content_html and content_html.strip():
        body, image_count, warnings = normalize_wechat_content(content_html, ocr=ocr)
    elif content_text and content_text.strip():
        body = _clean_lines(content_text)
    canonical = canonical_identity_url(source_url, biz, mid, idx)
    status, error = "ok", ""
    if not body:
        status, error = "invalid_response", "WeRSS 已存正文为空"
    return WechatArticle(
        source_url=source_url,
        canonical_url=canonical,
        doc_key=doc_key_for(source_url, biz, mid, idx),
        title=title.strip(),
        account_name=account.strip(),
        publish_date=publish_date.strip() or "unknown",
        wechat_biz=biz,
        wechat_mid=mid,
        wechat_idx=idx,
        body_markdown=body,
        image_count=image_count,
        status=status,
        error=error,
        warnings=warnings,
    )


def parse_wechat_article(raw_html: str, url: str, *, ocr: bool = False) -> WechatArticle:
    """把文章页 HTML 解析为 WechatArticle；纯函数，供离线 fixture 测试。

    任何单个字段缺失都不导致整篇失败；只有页面级异常（验证页/删除页/无正文容器）
    才置非 ok status。ocr=True 时对正文内容图做文字识别并回填（引擎缺失时降级为丢弃）。
    """
    source_url = normalize_wechat_url(url)
    lowered = raw_html[:200000]
    if any(m in lowered for m in _VERIFY_MARKERS):
        return WechatArticle(
            source_url=source_url,
            canonical_url=source_url,
            doc_key=doc_key_for(source_url),
            status="verify_required",
            error="命中微信风控验证页（环境异常/访问频繁），未绕过",
        )
    soup = BeautifulSoup(raw_html, "html.parser")
    title_tag = (soup.find("title").get_text(strip=True) if soup.find("title") else "") or ""
    if title_tag in _GONE_MARKERS or any(m in title_tag for m in _GONE_MARKERS):
        return WechatArticle(
            source_url=source_url,
            canonical_url=source_url,
            doc_key=doc_key_for(source_url),
            status="gone",
            error=f"内容不可用: {title_tag}",
        )

    title = _js_var(raw_html, "title")
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og:
            title = html_lib.unescape(str(og.get("content", ""))).strip()
    if not title:
        h1 = soup.select_one("#activity-name, h1.rich_media_title")
        if h1:
            title = h1.get_text(" ", strip=True)

    account = _js_var(raw_html, "account")
    if not account:
        js_name = soup.select_one("#js_name")
        if js_name:
            account = js_name.get_text(" ", strip=True)

    publish_date = _normalize_date(_js_var(raw_html, "create_time"))
    if publish_date == "unknown":
        pt = soup.select_one("#publish_time")
        if pt:
            publish_date = _normalize_date(pt.get_text(" ", strip=True))

    biz, mid, idx = (
        _js_var(raw_html, "biz"),
        _js_var(raw_html, "mid"),
        _js_var(raw_html, "idx"),
    )
    # JS 变量缺失时从长链 URL 兜底身份（/s/<token> 短链无 query，自然落空）
    url_biz, url_mid, url_idx = _identity_from_url(source_url)
    biz, mid, idx = biz or url_biz, mid or url_mid, idx or url_idx
    author = _js_var(raw_html, "author")
    body, image_count, warnings = _extract_body(soup, ocr=ocr)
    canonical = canonical_identity_url(source_url, biz, mid, idx)
    status, error = "ok", ""
    if not body:
        status = "invalid_response"
        error = "未找到正文容器 #js_content 或正文为空"
    return WechatArticle(
        source_url=source_url,
        canonical_url=canonical,
        doc_key=doc_key_for(source_url, biz, mid, idx),
        title=title,
        account_name=account,
        publish_date=publish_date,
        author=author,
        wechat_biz=biz,
        wechat_mid=mid,
        wechat_idx=idx,
        wechat_user_name=_js_var(raw_html, "user_name"),
        body_markdown=body,
        image_count=image_count,
        status=status,
        error=error,
        warnings=warnings,
    )


class WechatArticleFetcher:
    """单篇公众号文章抓取器：SafeFetcher（host 白名单 + 限速 + 大小上限）+ 解析。"""

    def __init__(self, fetcher: SafeFetcher, *, ocr: bool = False):
        self._fetcher = fetcher
        self._ocr = ocr

    @classmethod
    def create(
        cls,
        *,
        delay: float = 2.0,
        timeout: float = 20.0,
        client=None,
        ocr: bool = False,
    ) -> WechatArticleFetcher:
        fetcher = SafeFetcher(
            client=client,
            ua=WECHAT_UA,
            delay=delay,
            timeout=timeout,
            allowed_hosts={WECHAT_HOST},
            # 见模块 docstring 的 robots 说明：只抓显式给定的单篇 URL
            respect_robots=False,
        )
        return cls(fetcher, ocr=ocr)

    def fetch(self, url: str) -> WechatArticle:
        res = self._fetcher.fetch(url, "html")
        if not res.ok:
            return WechatArticle(
                source_url=normalize_wechat_url(url),
                canonical_url=normalize_wechat_url(url),
                doc_key=doc_key_for(url),
                status=res.status,
                error=res.error,
            )
        return parse_wechat_article(res.text(), res.final_url or url, ocr=self._ocr)
