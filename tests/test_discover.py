"""discover.py（站点勘探）离线测试：高价值栏目发现、页脚/新闻栏目忽略、CMS 识别。

Run: python -m pytest tests/test_discover.py -v
"""

from __future__ import annotations

from sufe_qa.crawler.discover import (
    analyze_column_page,
    detect_cms,
    discover_site,
    map_category,
)
from sufe_qa.crawler.fetcher import FetchResult
from sufe_qa.config import CATEGORIES

HOST = "scai.sufe.edu.cn"
ROOT = f"https://{HOST}/"

HOME_HTML = """
<html><head><title>计算机与人工智能学院</title></head>
<body>
<ul class="wp_listcolumn">
  <li><a href="/tzgg/list.htm">通知公告</a></li>
  <li><a href="/bkspy/list.htm">本科生培养</a></li>
  <li><a href="/jxgz/list.htm">奖学金</a></li>
  <li><a href="/xyxw/list.htm">学院新闻</a></li>
  <li><a href="/xyfc/list.htm">校友风采</a></li>
  <li><a href="/lxwm/list.htm">联系我们</a></li>
  <li><a href="/ztzl/list.htm">图片中心</a></li>
</ul>
<div class="footer">地址：上海市国定路777号 邮编：200433 沪ICP备000000号</div>
<script>createPageHTML(1, 0, "index", "htm");</script>
</body></html>
"""


def _list_page(prefix: str, n: int = 6) -> str:
    items = "".join(
        f'<li class="news_item"><a href="{prefix}{1000 + i}.htm">关于第{i}号工作通知</a>'
        f'<span class="date">2025-09-0{i}</span></li>'
        for i in range(1, n + 1)
    )
    return f"<html><body><ul class='news_list'>{items}</ul></body></html>"


class StubFetcher:
    def __init__(self, routes):
        self.routes = routes

    def fetch(self, url, kind="html", headers=None):
        res = self.routes.get(url)
        if res is None:
            return FetchResult(
                requested_url=url, final_url=url, status="http_error", status_code=404, error="404"
            )
        res.requested_url = url
        return res


def _routes(**extra):
    routes = {
        ROOT: FetchResult(requested_url=ROOT, final_url=ROOT, content=HOME_HTML.encode()),
        f"{ROOT}tzgg/list.htm": FetchResult(
            requested_url="",
            final_url=f"{ROOT}tzgg/list.htm",
            content=_list_page("/info/").encode(),
        ),
        f"{ROOT}bkspy/list.htm": FetchResult(
            requested_url="",
            final_url=f"{ROOT}bkspy/list.htm",
            content=_list_page("/bkspy/info/").encode(),
        ),
        f"{ROOT}jxgz/list.htm": FetchResult(
            requested_url="",
            final_url=f"{ROOT}jxgz/list.htm",
            content=_list_page("/jxgz/info/").encode(),
        ),
    }
    routes.update(extra)
    return routes


# ---------------- CMS 识别与分类映射 ----------------


def test_detect_cms():
    assert detect_cms('<div class="wp_articlecontent">x</div>', ROOT) == "wp3"
    assert detect_cms("<a href='/Home/List/31'>通知</a>", ROOT) == "gs_home"
    assert detect_cms("<html><body>plain</body></html>", ROOT) == "generic"


def test_map_category():
    assert map_category("奖学金") == "奖助学金"
    assert map_category("推免工作") == "推免升学"
    assert map_category("就业指导") == "实习就业"
    assert map_category("通知公告") == "学工事务"
    assert map_category("奇怪栏目") == "其他"


# ---------------- 栏目页分析 ----------------


def test_analyze_list_page():
    is_list, selector, prefix, samples, evidence = analyze_column_page(
        _list_page("/info/"), f"{ROOT}tzgg/list.htm", "wp3"
    )
    assert is_list
    assert selector == ".news_item a"
    assert prefix == f"{ROOT}info/"
    assert len(samples) == 5


def test_analyze_non_list_page():
    html = "<html><body><p>本学院成立于2024年，师资力量雄厚。</p></body></html>"
    is_list, *_ = analyze_column_page(html, f"{ROOT}gk/list.htm", "wp3")
    assert not is_list


# ---------------- 端到端勘探 ----------------


def test_discover_finds_high_value_columns():
    profile, report = discover_site(ROOT, StubFetcher(_routes()))
    assert report.cms_type == "wp3"
    names = {c.name for c in report.columns}
    assert {"通知公告", "本科生培养", "奖学金"} <= names
    col = next(c for c in report.columns if c.name == "通知公告")
    assert col.article_selector == ".news_item a"
    assert col.url_prefix == f"{ROOT}info/"
    assert len(col.sample_articles) == 5


def test_discover_ignores_footer_and_news():
    profile, report = discover_site(ROOT, StubFetcher(_routes()))
    skipped = {s["name"] for s in report.skipped}
    assert "学院新闻" in skipped
    assert "校友风采" in skipped
    assert "联系我们" in skipped
    assert "图片中心" in skipped  # 初筛零分，不进入勘探
    # 页脚链接不应进入栏目
    assert all("联系" not in c.name for c in report.columns)


def test_discover_profile_structure():
    profile, report = discover_site(ROOT, StubFetcher(_routes()))
    assert profile.allowed_hosts == [HOST]
    assert profile.cms_type == "wp3"
    assert profile.site_name == "计算机与人工智能学院"
    assert profile.article.title_selectors  # wp3 适配器默认选择器
    for cat in profile.categories:
        assert cat.category in CATEGORIES
        assert cat.max_list_pages == 10
        assert cat.max_articles == 200


def test_discover_homepage_failure():
    profile, report = discover_site(ROOT, StubFetcher({}))
    assert not profile.categories
    assert any("主页抓取失败" in w for w in report.warnings)


def test_discover_gs_home_site():
    gs = "gs.sufe.edu.cn"
    home = (
        "<html><head><title>研究生院</title></head><body>"
        '<div class="nav"><a href="/Home/List/31">招生工作</a>'
        '<a href="/Home/List/25">培养管理</a></div></body></html>'
    )
    list_page = "".join(
        f'<div class="item"><a href="/Home/Detail/{8000 + i}">通知{i}</a><span>2025-08-0{i}</span></div>'
        for i in range(1, 6)
    )
    routes = {
        f"https://{gs}/": FetchResult(
            requested_url="", final_url=f"https://{gs}/", content=home.encode()
        ),
        f"https://{gs}/Home/List/31": FetchResult(
            requested_url="",
            final_url="",
            content=f"<html><body>{list_page}</body></html>".encode(),
        ),
        f"https://{gs}/Home/List/25": FetchResult(
            requested_url="",
            final_url="",
            content=f"<html><body>{list_page}</body></html>".encode(),
        ),
    }
    profile, report = discover_site(f"https://{gs}/", StubFetcher(routes))
    assert report.cms_type == "gs_home"
    assert {c.name for c in report.columns} == {"招生工作", "培养管理"}
    assert profile.categories[0].url_prefix.startswith(f"https://{gs}/Home/Detail/")
