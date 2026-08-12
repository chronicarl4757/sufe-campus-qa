"""安全 HTTP 抓取客户端：统一出站防护、手动重定向检查、流式大小限制、全请求限速。

规则（对应失败状态）：
- 只允许 http/https（unsupported_scheme）；URL 不得带用户名密码（userinfo_blocked）；
- 自动发现模式禁止 localhost/环回/链路本地/私网/云元数据（private_address_blocked），
  主机名经 DNS 解析后任一地址命中私网同样拦截（解析在 robots 拉取之前完成）；
- 重定向逐跳手动检查：协议、userinfo、私网、host allowlist、robots 全部重检，
  跨 allowlist 跳转与出站跳转记 redirect_blocked，环路/超限记 redirect_loop；
- 流式读取、按 HTML/附件分别限制最大字节（oversized），不只信 Content-Length；
- robots 拒绝记 robots_denied，HTTP 4xx/5xx 记 http_error，网络异常记 network_error；
- 附件请求拿到 text/html（多为错误页）记 unsupported_mime；
- 所有请求（含失败与重定向跳）都按 max(delay, robots Crawl-delay) 限速。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# 不使用含 "bot" 的 UA：部分高校 WAF（如 ssd.sufe.edu.cn）按关键词 403；
# 项目名+仓库地址已足够标识身份与联系方式
UA = "sufe-qa/1.0 (campus knowledge assistant; +https://github.com/chronicarl4757/sufe-campus-qa)"

# 附件类响应允许的 MIME 前缀/具体类型；text/html 一般是错误页，判 unsupported_mime
_DOCUMENT_MIMES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
    "application/vnd.ms-",
    "application/octet-stream",
    "application/zip",
    "binary/octet-stream",
)

_PRIVATE_HOSTNAMES = {"localhost", "ip6-localhost", "broadcasthost"}
_METADATA_IPS = {"169.254.169.254", "100.100.2.136"}  # 云元数据（AWS/阿里）


def _ip_is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _is_private_host(host: str) -> bool:
    """字面 IP 与 localhost 系主机名的快速判定（不解析 DNS）。"""
    h = host.strip().lower().rstrip(".")
    if h in _PRIVATE_HOSTNAMES or h.endswith(".localhost"):
        return True
    if h in _METADATA_IPS:
        return True
    try:
        ip = ipaddress.ip_address(h.strip("[]"))  # 兼容 IPv6 字面量 [::1]
    except ValueError:
        return False
    return _ip_is_private(ip)


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """解析主机名的全部 A/AAAA 地址；解析失败返回空（连接阶段会自然报 network_error）。"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return []
    ips = []
    for info in infos:
        try:
            ips.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return ips


class RobotsCache:
    """按 netloc 缓存 robots 规则；用带超时的 httpx 拉取，替代 robotparser.read()。

    状态语义（依据 RFC 9309）：404 全放行；401/403 全站禁止；其他 4xx/5xx 与
    网络异常保守视为禁止。缓存键为 netloc，can_fetch 可对任意 URL（含重定向目标）调用。
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
            r = self._client.get(f"{parsed.scheme}://{netloc}/robots.txt")
        except httpx.HTTPError:
            self._cache[netloc] = None
            return None
        if r.status_code == 404:
            rp.parse([])
        elif r.status_code in (401, 403):
            rp.parse(["User-agent: *", "Disallow: /"])
        elif r.status_code >= 400:
            self._cache[netloc] = None
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


@dataclass
class FetchResult:
    requested_url: str
    final_url: str = ""
    status: str = "ok"  # ok | 上述各失败状态
    content: bytes = b""
    mime_type: str = ""
    status_code: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_disposition: str = ""  # 原始 Content-Disposition 头（附件中文文件名用）
    redirects: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def text(self) -> str:
        """按响应头 charset 解码，缺失时回退 utf-8/gb18030（高校老站常见 GBK）。"""
        for enc in ("utf-8", "gb18030"):
            try:
                return self.content.decode(enc)
            except UnicodeDecodeError:
                continue
        return self.content.decode("utf-8", errors="replace")


class SafeFetcher:
    """统一安全抓取入口；注入 httpx.Client 与 sleep 以便 MockTransport 离线测试。"""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        ua: str = UA,
        delay: float = 1.0,
        allowed_hosts: set[str] | None = None,
        allow_private: bool = False,
        max_html_bytes: int = 5_000_000,
        max_attachment_bytes: int = 30_000_000,
        max_redirects: int = 5,
        timeout: float = 15.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._own = client is None
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=False, headers={"User-Agent": ua}
        )
        self._ua = ua
        self._delay = delay
        self._allowed = allowed_hosts
        self._allow_private = allow_private
        self._max_html = max_html_bytes
        self._max_att = max_attachment_bytes
        self._max_redirects = max_redirects
        self._sleep = sleep
        self._robots = RobotsCache(self._client, ua)
        self._last_req: dict[str, float] = {}
        self._dns_private: dict[str, bool] = {}  # 主机名 -> DNS 解析后是否私网（按实例缓存）

    def close(self) -> None:
        if self._own:
            self._client.close()

    def __enter__(self) -> SafeFetcher:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- 检查链 ----

    def _host_is_private(self, host: str) -> bool:
        """完整私网判定：字面检查 + DNS 解析全部地址（任一私网即拦截）。

        残余边界：解析与连接分两次进行，存在 DNS rebinding TOCTOU 窗口；
        部署上应配合 host allowlist 收敛出站目标。
        """
        h = host.strip().lower().rstrip(".")
        if _is_private_host(h):
            return True
        try:
            ipaddress.ip_address(h.strip("[]"))
            return False  # 字面公网 IP，无需解析
        except ValueError:
            pass
        if h not in self._dns_private:
            self._dns_private[h] = any(_ip_is_private(ip) for ip in _resolve_host_ips(h))
        return self._dns_private[h]

    def _precheck(self, url: str, via_redirect: bool) -> str | None:
        """返回失败状态或 None（放行）。每一步重定向都要完整重跑。"""
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return "unsupported_scheme"
        if p.username or p.password:
            return "userinfo_blocked"
        if not p.netloc:
            return "unsupported_scheme"
        if not self._allow_private and self._host_is_private(p.hostname or ""):
            return "private_address_blocked"
        if self._allowed is not None and p.netloc not in self._allowed:
            return "redirect_blocked"
        if not self._robots.can_fetch(url):
            return "robots_denied"
        return None

    def _throttle(self, url: str) -> None:
        """成功与失败请求一律限速：间隔取 max(delay, robots Crawl-delay)。"""
        host = urlparse(url).netloc
        wait = max(self._delay, self._robots.crawl_delay(url) or 0.0)
        last = self._last_req.get(host)
        if last is not None:
            remain = wait - (time.monotonic() - last)
            if remain > 0:
                self._sleep(remain)
        self._last_req[host] = time.monotonic()

    # ---- 主入口 ----

    def fetch(self, url: str, kind: str = "html", headers: dict | None = None) -> FetchResult:
        """抓取 url；kind 为 "html" 或 "attachment"（不同大小上限与 MIME 判定）。

        headers 可传 If-None-Match / If-Modified-Since 做条件请求；304 返回
        status="not_modified"（ok=False，由调用方按“未变化”处理，不计失败）。

        ``post+https://`` 前缀表示该地址只能通过 POST JSON 接口获取（如就业平台
        的 XHR API）；此时以 POST + X-Requested-With 请求，安全检查链不变。
        """
        method = "GET"
        if url.startswith("post+"):
            method, url = "POST", url[5:]
            headers = {**(headers or {}), "X-Requested-With": "XMLHttpRequest"}
        res = FetchResult(requested_url=url)
        limit = self._max_html if kind == "html" else self._max_att
        current, seen = url, {url}
        for _hop in range(self._max_redirects + 1):
            if (bad := self._precheck(current, via_redirect=(current != url))) is not None:
                res.status, res.final_url, res.error = bad, current, f"blocked: {current}"
                return res
            self._throttle(current)
            try:
                # 流式响应：先拿状态/头决定重定向，再限量读体
                with self._client.stream(
                    method, current, follow_redirects=False, headers=headers
                ) as r:
                    if r.is_redirect:
                        loc = r.headers.get("location")
                        if not loc:
                            res.status, res.error = "redirect_blocked", "302 无 Location"
                            return res
                        nxt = urljoin(current, loc)
                        if nxt in seen or len(res.redirects) >= self._max_redirects:
                            res.status, res.error = "redirect_loop", nxt
                            return res
                        seen.add(nxt)
                        res.redirects.append(nxt)
                        current = nxt
                        continue
                    res.final_url = current
                    res.status_code = r.status_code
                    res.mime_type = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    res.etag = r.headers.get("etag")
                    res.last_modified = r.headers.get("last-modified")
                    res.content_disposition = r.headers.get("content-disposition", "")
                    if r.status_code == 304:
                        res.status = "not_modified"
                        return res
                    if r.status_code >= 400:
                        res.status = "http_error"
                        res.error = f"HTTP {r.status_code}"
                        return res
                    if kind == "attachment" and res.mime_type.startswith("text/html"):
                        res.status = "unsupported_mime"
                        res.error = "附件请求返回 text/html（疑似错误页或查看器）"
                        # 保留部分响应体：pdf.js 等查看器页内含真实文件地址，供 engine 解析
                        chunks, total = [], 0
                        for chunk in r.iter_bytes(65536):
                            total += len(chunk)
                            if total > 262144:
                                break
                            chunks.append(chunk)
                        res.content = b"".join(chunks)
                        return res
                    chunks, total = [], 0
                    for chunk in r.iter_bytes(65536):
                        total += len(chunk)
                        if total > limit:
                            res.status = "oversized"
                            res.error = f"超过 {limit} 字节上限"
                            return res
                        chunks.append(chunk)
                    res.content = b"".join(chunks)
                    return res
            except httpx.HTTPError as e:
                res.status, res.final_url = "network_error", current
                res.error = f"{type(e).__name__}: {e}"
                return res
        res.status, res.error = "redirect_loop", "重定向次数超限"
        return res
