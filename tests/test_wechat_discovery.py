"""发现层测试：SeedURLDiscovery 离线解析；WeRSSDiscovery 用 MockTransport（规格 §二十-§二十三）。"""

from __future__ import annotations

import json

import httpx

from sufe_qa.wechat.discovery import (
    SeedURLDiscovery,
    WeRSSDiscovery,
    is_wechat_article_url,
)


def test_seed_discovery_reads_jsonl(tmp_path):
    seed = tmp_path / "seeds.jsonl"
    seed.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "account": "上财本科招生",
                        "url": "https://mp.weixin.qq.com/s/AAA",
                        "title": "2026年招生章程",
                        "publish_date": "2026-06-01",
                    }
                ),
                json.dumps({"account": "上财本科招生", "url": "https://mp.weixin.qq.com/s/BBB"}),
                json.dumps({"account": "上财本科招生", "url": "https://mp.weixin.qq.com/s/AAA"}),
                "not-json",
                json.dumps({"account": "x", "url": "https://example.com/not-wechat"}),
            ]
        ),
        encoding="utf-8",
    )
    result = SeedURLDiscovery(seed).discover(accounts=["上财本科招生"], limit=20)
    assert result.status == "ok"
    assert len(result.articles) == 2  # 重复 URL 与非微信 URL 被剔除
    assert result.articles[0].title == "2026年招生章程"
    assert len(result.warnings) == 2


def test_seed_discovery_missing_file(tmp_path):
    result = SeedURLDiscovery(tmp_path / "missing.jsonl").discover(accounts=[], limit=20)
    assert result.status == "temporary_unavailable"
    assert not result.articles


def test_seed_discovery_limit(tmp_path):
    seed = tmp_path / "seeds.jsonl"
    seed.write_text(
        "\n".join(
            json.dumps({"account": "a", "url": f"https://mp.weixin.qq.com/s/U{i}"})
            for i in range(10)
        ),
        encoding="utf-8",
    )
    result = SeedURLDiscovery(seed).discover(accounts=[], limit=3)
    assert len(result.articles) == 3


def test_seed_force_include_flag(tmp_path):
    seed = tmp_path / "seeds.jsonl"
    seed.write_text(
        json.dumps(
            {
                "account": "a",
                "url": "https://mp.weixin.qq.com/s/OLD",
                "publish_date": "2022-01-01",
                "force_include": True,
                "related_official_url": "https://jwc.sufe.edu.cn/x.pdf",
            }
        ),
        encoding="utf-8",
    )
    result = SeedURLDiscovery(seed).discover(accounts=[], limit=20)
    assert result.articles[0].force_include is True
    assert result.articles[0].related_official_url == "https://jwc.sufe.edu.cn/x.pdf"


def test_url_validation():
    assert is_wechat_article_url("https://mp.weixin.qq.com/s/AAA")
    assert is_wechat_article_url("https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1&sn=x")
    assert not is_wechat_article_url("https://mp.weixin.qq.com/")
    assert not is_wechat_article_url("https://evil.com/s/AAA")
    assert not is_wechat_article_url("ftp://mp.weixin.qq.com/s/AAA")


def _werss_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_werss_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/mps"):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"list": [{"id": "MP_ID_1", "mp_name": "上财本科招生"}], "total": 1},
            },
        )
    if request.url.path.endswith("/articles"):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "title": "2026年本科招生章程",
                            "url": "https://mp.weixin.qq.com/s/AAA",
                            "publish_time": 1780300800,
                            "mp_name": "上财本科招生",
                        },
                        {
                            "title": "招生亮点",
                            "url": "https://mp.weixin.qq.com/s/BBB",
                            "publish_time": 1780214400,
                            "mp_name": "上财本科招生",
                        },
                    ],
                    "total": 2,
                },
            },
        )
    return httpx.Response(404, json={"code": 404, "message": "not found"})


def _werss_content_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/mps"):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"list": [{"id": "MP_ID_1", "mp_name": "上财本科招生"}], "total": 1},
            },
        )
    if request.url.path.endswith("/articles/A1"):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "id": "A1",
                    "title": "2026年本科招生章程",
                    "content_html": '<div id="js_content"><p>第一条 招生范围面向全国。</p>'
                    "<p>报名时间：2026年6月1日至6月20日。</p></div>",
                    "content": "",
                },
            },
        )
    if request.url.path.endswith("/articles"):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": "A1",
                            "title": "2026年本科招生章程",
                            "url": "https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1&sn=x",
                            "publish_time": 1780300800,
                            "mp_name": "上财本科招生",
                            "has_content": 1,
                        },
                        {
                            "id": "A2",
                            "title": "无正文文章",
                            "url": "https://mp.weixin.qq.com/s/BBB",
                            "publish_time": 1780214400,
                            "mp_name": "上财本科招生",
                            "has_content": 0,
                        },
                    ],
                    "total": 2,
                },
            },
        )
    return httpx.Response(404, json={"code": 404, "message": "not found"})


def test_werss_discovery_fetches_detail_content():
    """list 只给元数据（has_content），正文走 detail 端点（规格 §十三）。"""
    d = WeRSSDiscovery(
        "http://werss.local", "ak", "sk", client=_werss_client(_werss_content_handler)
    )
    result = d.discover(accounts=["上财本科招生"], limit=10)
    assert result.status == "ok"
    assert len(result.articles) == 2
    with_content = result.articles[0]
    assert with_content.has_content
    assert "招生范围面向全国" in with_content.content_html
    no_content = result.articles[1]
    assert not no_content.has_content  # has_content=0：不请求详情，留给 runner 回源


def test_werss_discovery_happy_path():
    d = WeRSSDiscovery("http://werss.local", "ak", "sk", client=_werss_client(_ok_werss_handler))
    result = d.discover(accounts=["上财本科招生"], limit=10)
    assert result.status == "ok"
    assert len(result.articles) == 2
    assert result.articles[0].title == "2026年本科招生章程"
    assert result.articles[0].publish_date == "2026-06-01"
    assert result.articles[0].source == "werss"


def test_werss_sends_ak_sk_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return _ok_werss_handler(request)

    d = WeRSSDiscovery("http://werss.local", "my-ak", "my-sk", client=_werss_client(handler))
    d.discover(accounts=["上财本科招生"], limit=5)
    assert seen["auth"] == "AK-SK my-ak:my-sk"


def test_werss_error_classification():
    def make(status_code):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"code": status_code, "message": "x"})

        return handler

    for code, expected in (
        (401, "auth_required"),
        (403, "auth_required"),
        (429, "rate_limited"),
        (500, "temporary_unavailable"),
    ):
        d = WeRSSDiscovery("http://werss.local", client=_werss_client(make(code)))
        result = d.discover(accounts=["上财本科招生"], limit=5)
        assert result.status == expected
        assert not result.articles


def test_werss_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    d = WeRSSDiscovery("http://werss.local", client=_werss_client(handler))
    result = d.discover(accounts=["上财本科招生"], limit=5)
    assert result.status == "invalid_response"


def test_werss_network_error_is_temporary():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    d = WeRSSDiscovery("http://werss.local", client=_werss_client(handler))
    result = d.discover(accounts=["上财本科招生"], limit=5)
    assert result.status == "temporary_unavailable"


def test_werss_from_env_not_configured(monkeypatch):
    monkeypatch.delenv("WERSS_BASE_URL", raising=False)
    assert WeRSSDiscovery.from_env() is None
