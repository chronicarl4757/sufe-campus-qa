"""公众号文章解析测试：离线 fixture，无真实网络（规格 §二十七）。"""

from __future__ import annotations

from pathlib import Path

import httpx

from sufe_qa.wechat.article import (
    WechatArticleFetcher,
    doc_key_for,
    normalize_wechat_url,
    parse_wechat_article,
)

FIXTURES = Path(__file__).parent / "fixtures" / "wechat"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_normal_article_metadata_and_body():
    article = parse_wechat_article(
        _fixture("normal_article.html"), "https://mp.weixin.qq.com/s/AbCdEfGh"
    )
    assert article.status == "ok"
    assert article.title == "关于2026年本科生转专业工作的通知"
    assert article.account_name == "上海财经大学教务处"
    assert article.publish_date == "2026-03-01"
    assert article.author == "教务处"
    assert article.wechat_biz == "MzI3Mjk2NTgwTEST=="
    assert article.wechat_mid == "2247500001"
    assert article.wechat_idx == "1"
    assert article.canonical_url == (
        "https://mp.weixin.qq.com/s?__biz=MzI3Mjk2NTgwTEST==&mid=2247500001&idx=1"
    )
    assert article.doc_key == "wechat:MzI3Mjk2NTgwTEST==:2247500001:1"
    body = article.body_markdown
    # 正文要点保留：段落、编号、列表、电话、网址、时间、材料清单
    assert "根据《上海财经大学本科生转专业工作实施细则》" in body
    assert "- 网上报名：2026年3月10日至3月20日" in body
    assert "021-6590XXXX" in body
    assert "https://jwc.sufe.edu.cn/" in body
    assert "材料清单：申请表、成绩单、个人陈述" in body
    # 微信 UI / 关注引导被清除
    for cruft in ("微信扫一扫", "关注公众号", "点赞", "在看", "阅读原文"):
        assert cruft not in body


def test_body_comes_from_js_content_only():
    article = parse_wechat_article(
        _fixture("normal_article.html"), "https://mp.weixin.qq.com/s/AbCdEfGh"
    )
    # 顶部公众号栏（js_name 在 js_content 之外）不应混入正文
    assert "var msg_title" not in article.body_markdown
    assert article.body_markdown.startswith("各学院、各位同学：")


def test_table_rows_not_stripped():
    article = parse_wechat_article(
        _fixture("normal_article.html"), "https://mp.weixin.qq.com/s/AbCdEfGh"
    )
    assert "学院 接收专业 计划数" in article.body_markdown
    assert "经济学院 经济学 10" in article.body_markdown
    assert "金融学院 金融学 8" in article.body_markdown


def test_image_only_article_has_tiny_body_and_image_count():
    article = parse_wechat_article(
        _fixture("image_only_article.html"), "https://mp.weixin.qq.com/s/ImgOnly"
    )
    assert article.status == "ok"  # 页面有效，但正文几乎为空 → 由质量门判低质
    assert article.image_count == 3
    assert len(article.body_markdown.replace(" ", "").replace("\n", "")) < 80


def test_guide_article_strips_signature_and_components():
    article = parse_wechat_article(
        _fixture("guide_article.html"), "https://mp.weixin.qq.com/s/Guide"
    )
    assert article.status == "ok"
    body = article.body_markdown
    assert "挂失补办" in body and "工本费 20 元" in body
    assert "服务时间：工作日 8:30-17:00" in body
    for cruft in ("点击上方蓝字关注我们", "长按二维码关注", "分享，点赞，在看"):
        assert cruft not in body


def test_verify_page_classified():
    article = parse_wechat_article(
        _fixture("verify_page.html"), "https://mp.weixin.qq.com/s/Verify"
    )
    assert article.status == "verify_required"
    assert not article.body_markdown


def test_deleted_page_classified():
    article = parse_wechat_article(
        _fixture("deleted_page.html"), "https://mp.weixin.qq.com/s/Deleted"
    )
    assert article.status == "gone"


def test_missing_fields_do_not_fail():
    article = parse_wechat_article(
        "<html><head><title></title></head><body>"
        '<div id="js_content"><p>只有正文，没有任何 JS 变量。这是一段足够长的正文内容，'
        "用于验证字段缺失不会让解析失败。</p></div></body></html>",
        "https://mp.weixin.qq.com/s/Minimal",
    )
    assert article.status == "ok"
    assert article.publish_date == "unknown"
    assert article.account_name == ""
    # 无 biz/mid/idx 时身份退化为规范化 URL
    assert article.doc_key.startswith("url:")
    assert article.canonical_url == "https://mp.weixin.qq.com/s/Minimal"


def test_no_content_container_is_invalid_response():
    article = parse_wechat_article(
        "<html><head><title></title></head><body><div>空白页</div></body></html>",
        "https://mp.weixin.qq.com/s/Empty",
    )
    assert article.status == "invalid_response"


def test_normalize_wechat_url_strips_tracking_params():
    url = "https://mp.weixin.qq.com/s/AbCd?scene=21&nwr_flag=1#wechat_redirect"
    assert normalize_wechat_url(url) == "https://mp.weixin.qq.com/s/AbCd"
    long_url = "https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1&sn=xx&scene=21&chksm=abc"
    normalized = normalize_wechat_url(long_url)
    assert "scene" not in normalized and "chksm" not in normalized
    assert "__biz=MzA" in normalized and "sn=xx" in normalized


def test_doc_key_prefers_biz_mid_idx():
    key = doc_key_for("https://mp.weixin.qq.com/s/AbCd", "MzA=", "123", "2")
    assert key == "wechat:MzA=:123:2"


def _mock_fetcher(handler) -> WechatArticleFetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WechatArticleFetcher.create(delay=0, client=client)


def test_fetcher_fetches_and_parses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_fixture("normal_article.html"))

    article = _mock_fetcher(handler).fetch("https://mp.weixin.qq.com/s/AbCdEfGh")
    assert article.status == "ok"
    assert article.title == "关于2026年本科生转专业工作的通知"


def test_fetcher_blocks_non_wechat_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>evil</p>")

    article = _mock_fetcher(handler).fetch("https://evil.example.com/x")
    assert article.status == "redirect_blocked"
