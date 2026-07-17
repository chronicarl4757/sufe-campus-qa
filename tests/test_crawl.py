import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sufe_qa.crawler.crawl import Seed, crawl_seed, extract_links, load_seeds


def _seed() -> Seed:
    return Seed(
        name="t",
        list_url="https://www.sufe.edu.cn/notice/list.htm",
        link_selector="ul.news_list li a",
        url_prefix="https://www.sufe.edu.cn/",
        category="学工事务",
        publisher="上海财经大学",
        max_pages=2,
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
    y.write_text(
        """seeds:
  - name: a
    list_url: "https://www.sufe.edu.cn/x/list.htm"
    link_selector: "li a"
    url_prefix: "https://www.sufe.edu.cn/"
    category: "学工事务"
    publisher: "上海财经大学"
    max_pages: 5
""",
        encoding="utf-8",
    )
    seeds = load_seeds(y)
    assert len(seeds) == 1 and seeds[0].max_pages == 5 and seeds[0].category == "学工事务"


def test_load_seeds_empty(tmp_path):
    y = tmp_path / "seeds.yaml"
    y.write_text("seeds: []\n", encoding="utf-8")
    assert load_seeds(y) == []


# ---- crawl_seed 离线测试：本地 http.server，禁止外网 ----

_LIST_HTML = """<ul class="news_list">
  <li><a href="/a1">文章一</a></li>
  <li><a href="/a2">文章二</a></li>
  <li><a href="http://127.0.0.1:1/offsite">站外链接</a></li>
  <li><a href="#top">纯锚点</a></li>
  <li><a href="/boom">会 500 的页</a></li>
</ul>"""


class _Handler(BaseHTTPRequestHandler):
    """测试站点：/list 列表页、/a1 /a2 正常页、/boom 恒 500、/robots.txt 可配置。"""

    robots: tuple[int, str] | None = None  # None 表示 /robots.txt 返回 404

    def do_GET(self) -> None:
        if self.path == "/robots.txt":
            if self.robots is None:
                self.send_error(404)
            else:
                self._respond(*self.robots)
        elif self.path == "/list":
            self._respond(200, _LIST_HTML)
        elif self.path in ("/a1", "/a2"):
            self._respond(200, f"<p>{self.path}</p>")
        elif self.path == "/boom":
            self._respond(500, "boom")
        else:
            self.send_error(404)

    def _respond(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # 静默测试服务器日志
        pass


@pytest.fixture
def make_server():
    """本地站点工厂：robots=None → 404；否则 (status, body) 原样返回。yield base_url。"""
    servers: list[HTTPServer] = []

    def _make(robots: tuple[int, str] | None = None) -> str:
        handler = type("_BoundHandler", (_Handler,), {"robots": robots})
        srv = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield _make
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _live_seed(base: str) -> Seed:
    return Seed(
        name="t",
        list_url=f"{base}/list",
        link_selector="ul.news_list li a",
        url_prefix=f"{base}/",
        category="学工事务",
        publisher="测试",
    )


def test_crawl_seed_robots_404_allows_crawl(make_server):
    base = make_server()  # robots.txt 404 → 全放行
    pages = crawl_seed(_live_seed(base), delay=0)
    # a1/a2 入库；站外链接与纯锚点被滤；/boom 500 告警跳过、不中断
    assert [u for u, _ in pages] == [f"{base}/a1", f"{base}/a2"]


def test_crawl_seed_respects_robots_disallow(make_server):
    base = make_server((200, "User-agent: *\nDisallow: /a1\n"))
    pages = crawl_seed(_live_seed(base), delay=0)
    assert [u for u, _ in pages] == [f"{base}/a2"]


@pytest.mark.parametrize("status", [401, 403])
def test_crawl_seed_robots_unauthorized_forbids(make_server, status):
    base = make_server((status, ""))
    with pytest.raises(RuntimeError, match="robots"):
        crawl_seed(_live_seed(base), delay=0)


def test_crawl_seed_respects_crawl_delay(make_server, monkeypatch):
    base = make_server((200, "User-agent: *\nCrawl-delay: 1\n"))
    sleeps: list[float] = []
    monkeypatch.setattr("sufe_qa.crawler.crawl.time.sleep", sleeps.append)
    pages = crawl_seed(_live_seed(base), delay=0)
    assert len(pages) == 2
    assert sleeps == [1, 1]  # delay=0 被 robots 的 Crawl-delay: 1 覆盖
