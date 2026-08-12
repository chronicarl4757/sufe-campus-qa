"""SafeFetcher 离线测试：httpx.MockTransport，无真实网络。"""

from __future__ import annotations

import httpx
import pytest

from sufe_qa.crawler.fetcher import SafeFetcher

HOST = "example.sufe.edu.cn"


def _fetcher(handler, **kw) -> SafeFetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "t"})
    kw.setdefault("delay", 0)
    kw.setdefault("allow_private", True)  # 默认放行私网便于本地 mock；拦截用例显式关
    return SafeFetcher(client, **kw)


def _ok_handler(body: str = "<p>ok</p>", content_type: str = "text/html"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=body, headers={"Content-Type": content_type})

    return handler


def test_rejects_non_http_scheme():
    f = _fetcher(_ok_handler())
    res = f.fetch("ftp://example.com/x.pdf")
    assert res.status == "unsupported_scheme" and not res.ok


def test_rejects_userinfo_url():
    f = _fetcher(_ok_handler())
    res = f.fetch(f"http://user:pass@{HOST}/x")
    assert res.status == "userinfo_blocked"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://[::1]/x",
        "http://10.0.0.5/x",
        "http://192.168.1.10/x",
        "http://169.254.169.254/latest/meta-data",  # 云元数据
    ],
)
def test_blocks_private_addresses(url):
    f = _fetcher(_ok_handler(), allow_private=False)
    assert f.fetch(url).status == "private_address_blocked"


def test_same_host_redirect_followed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, text="<p>落地页</p>")

    f = _fetcher(handler)
    res = f.fetch(f"http://{HOST}/start")
    assert res.ok and res.final_url == f"http://{HOST}/final" and res.redirects


def test_cross_host_redirect_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == HOST and request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == HOST:
            return httpx.Response(302, headers={"Location": "http://evil.example.com/x"})
        return httpx.Response(200, text="evil")

    f = _fetcher(handler, allowed_hosts={HOST})
    res = f.fetch(f"http://{HOST}/start")
    assert res.status == "redirect_blocked"


def test_redirect_loop_detected():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/a":
            return httpx.Response(302, headers={"Location": "/b"})
        return httpx.Response(302, headers={"Location": "/a"})

    f = _fetcher(handler)
    assert f.fetch(f"http://{HOST}/a").status == "redirect_loop"


def test_robots_rechecked_after_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /final\n")
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, text="<p>不应抓到</p>")

    f = _fetcher(handler)
    res = f.fetch(f"http://{HOST}/start")
    assert res.status == "robots_denied"


def test_robots_denied_on_initial_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text="x")

    f = _fetcher(handler)
    assert f.fetch(f"http://{HOST}/any").status == "robots_denied"


def test_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(500, text="boom")

    f = _fetcher(handler)
    res = f.fetch(f"http://{HOST}/x")
    assert res.status == "http_error" and res.status_code == 500


def test_network_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ConnectError("refused", request=request)

    f = _fetcher(handler)
    assert f.fetch(f"http://{HOST}/x").status == "network_error"


def test_oversized_html_blocked():
    big = "x" * (1024 * 1024)  # 1MB，上限设 1KB

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        # 故意谎报 Content-Length，验证只信实际读取字节
        return httpx.Response(
            200,
            content=big.encode(),
            headers={"Content-Type": "text/html", "Content-Length": "100"},
        )

    f = _fetcher(handler, max_html_bytes=1024)
    assert f.fetch(f"http://{HOST}/big").status == "oversized"


def test_attachment_html_response_is_unsupported_mime():
    f = _fetcher(_ok_handler(body="<html>错误页</html>", content_type="text/html"))
    res = f.fetch(f"http://{HOST}/download?fileId=1", kind="attachment")
    assert res.status == "unsupported_mime"


def test_attachment_ok_and_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=b"%PDF-1.4 fake",
            headers={
                "Content-Type": "application/pdf",
                "ETag": '"abc"',
                "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
            },
        )

    f = _fetcher(handler)
    res = f.fetch(f"http://{HOST}/f.pdf", kind="attachment")
    assert res.ok and res.content.startswith(b"%PDF") and res.etag == '"abc"'
    assert res.last_modified and res.mime_type == "application/pdf"


def test_throttle_applies_to_failed_requests_too():
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(500, text="boom")

    f = _fetcher(handler, delay=1.0, sleep=sleeps.append)
    f.fetch(f"http://{HOST}/x")
    f.fetch(f"http://{HOST}/y")
    assert len(sleeps) == 1 and sleeps[0] > 0  # 第二次请求前被限速（即使是失败请求）


def test_gbk_text_decoding():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, content="推免办法".encode("gb18030"), headers={"Content-Type": "text/html"}
        )

    f = _fetcher(handler)
    res = f.fetch(f"http://{HOST}/gbk")
    assert res.ok and res.text() == "推免办法"


def test_post_marker_sends_post_with_xhr_header():
    """post+https:// 前缀：转为 POST 并带 X-Requested-With，安全检查链不变。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        seen["method"] = request.method
        seen["xhr"] = request.headers.get("x-requested-with")
        return httpx.Response(
            200, text='{"code":200}', headers={"Content-Type": "application/json"}
        )

    f = _fetcher(handler)
    res = f.fetch(f"post+https://{HOST}/career/news/search/tzgg/1/20")
    assert res.ok
    assert seen["method"] == "POST"
    assert seen["xhr"] == "XMLHttpRequest"
    assert res.requested_url == f"https://{HOST}/career/news/search/tzgg/1/20"


def test_blocks_hostname_resolving_to_private_ip(monkeypatch):
    """DNS 解析到私网地址的主机名同样拦截（SSRF 防御不止字面 IP）。"""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    f = _fetcher(_ok_handler(), allow_private=False)
    assert f.fetch(f"http://{HOST}/x").status == "private_address_blocked"


def test_allows_hostname_resolving_to_public_ip(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    f = _fetcher(_ok_handler(), allow_private=False)
    r = f.fetch(f"http://{HOST}/x")
    assert r.status == "ok"


def test_dns_resolution_failure_falls_through_to_network_error(monkeypatch):
    """DNS 解析失败不在 precheck 拦截，由连接阶段报 network_error。"""
    import socket

    def boom(*a, **k):
        raise socket.gaierror("mocked dns failure")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    f = _fetcher(_ok_handler(), allow_private=False)
    # MockTransport 不经过真实连接，precheck 放行后由 mock 正常应答
    assert f.fetch(f"http://{HOST}/x").status == "ok"


def test_dns_rebinding_rechecked_for_public_hostname(monkeypatch):
    """公网解析结果不缓存：同一实例内域名 rebinding 到私网后必须拦截。"""
    import socket

    answers = [
        [(2, 1, 6, "", ("93.184.216.34", 80))],
        [(2, 1, 6, "", ("127.0.0.1", 80))],
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: answers.pop(0))
    f = _fetcher(_ok_handler(), allow_private=False)
    assert f.fetch(f"http://{HOST}/x").status == "ok"
    assert f.fetch(f"http://{HOST}/x").status == "private_address_blocked"


def test_private_dns_result_sticks(monkeypatch):
    """私网解析结果持续阻断，后续请求不再解析（缓存只记私网）。"""
    import socket

    calls = []

    def fake_getaddrinfo(*a, **k):
        calls.append(1)
        return [(2, 1, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    f = _fetcher(_ok_handler(), allow_private=False)
    assert f.fetch(f"http://{HOST}/x").status == "private_address_blocked"
    assert f.fetch(f"http://{HOST}/x").status == "private_address_blocked"
    assert len(calls) == 1  # 第二次命中私网缓存，未重新解析
