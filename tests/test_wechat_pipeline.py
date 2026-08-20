"""公众号端到端测试：seed 发现 → 白名单/时间/相关性门 → MockTransport 抓取 → 入库。

覆盖规格 §三十一（去重）、§十六（explains 关系）、§二十五（不自动索引，只写 manifest）、
本轮 WeRSS 正文直入/回源 fallback（§十/§十一）与图片无关质量判定（§五-§七）。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from sufe_qa.schema import (
    DocMeta,
    append_manifest,
    doc_id_from,
    load_manifest,
    load_relations,
    sha256_text,
)
from sufe_qa.wechat.article import WechatArticleFetcher
from sufe_qa.wechat.discovery import DiscoveredArticle, DiscoveryResult, SeedURLDiscovery
from sufe_qa.wechat.filters import load_wechat_accounts
from sufe_qa.wechat.runner import crawl_wechat

FIXTURES = Path(__file__).parent / "fixtures" / "wechat"
NORMAL_URL = "https://mp.weixin.qq.com/s/AbCdEfGh"
GUIDE_URL = "https://mp.weixin.qq.com/s/Guide"
IMAGE_URL = "https://mp.weixin.qq.com/s/ImgOnly"
OLD_URL = "https://mp.weixin.qq.com/s/Old2022"
OTHER_ACCOUNT_URL = "https://mp.weixin.qq.com/s/OtherAcc"
NEWS_URL = "https://mp.weixin.qq.com/s/NewsFlash"
VERIFY_URL = "https://mp.weixin.qq.com/s/Verify"
FACTS_IMG_URL = "https://mp.weixin.qq.com/s/FactsImgs"
SHORT_FACT_URL = "https://mp.weixin.qq.com/s/ShortFacts"
PROMO_URL = "https://mp.weixin.qq.com/s/LongPromo"
PHONE_URL = "https://mp.weixin.qq.com/s/PhoneCtx"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _old_article() -> str:
    return (
        _fixture("normal_article.html")
        .replace("2026-03-01 09:30", "2022-03-01 09:30")
        .replace("关于2026年本科生转专业工作的通知", "关于2022年本科生转专业工作的通知")
        # 正文也要与新版不同，否则 exact text_hash 去重会把旧年度判成重复
        .replace("2026年本科生转专业工作安排通知如下", "2022年本科生转专业工作安排通知如下")
        .replace('var mid = "2247500001"', 'var mid = "2247500099"')
    )


def _other_account_article() -> str:
    return (
        _fixture("normal_article.html")
        .replace("上海财经大学教务处", "上财校园资讯")
        .replace('var mid = "2247500001"', 'var mid = "2247500098"')
    )


def _page(
    title: str, body_html: str, *, date: str = "2026-03-01 09:30", mid: str = "2247500999"
) -> str:
    """最小公众号页面生成器：JS 元数据变量 + #js_content。"""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title></title></head><body>"
        f'<div class="rich_media_content" id="js_content">{body_html}</div>'
        "<script>"
        f"var msg_title = '{title}';"
        'var nickname = htmlDecode("上海财经大学教务处");'
        f"var createTime = '{date}';"
        'var biz = "MzI3Mjk2NTgwTEST==";'
        f'var mid = "{mid}";'
        'var idx = "1";'
        'var author = "";'
        'var user_name = "gh_testjwc";'
        "</script></body></html>"
    )


def _short_facts_article() -> str:
    """120 字左右但含明确招生事实（年份/新增专业/选拔变化）→ 应保留（§六/§七）。"""
    body = (
        "<p>2026年我校本科招生新增“数字经济”专业和“人工智能”实验班，"
        "招生范围覆盖全国31个省（区、市），实验班进校后二次选拔。</p>"
        "<p>详见本科招生网 zs.sufe.edu.cn，咨询电话：021-6590XXXX。</p>"
    )
    return _page("权威发布丨2026年本科招生亮点", body, mid="2247500888")


def _long_promo_article() -> str:
    """1000 字招生宣传软文，无报名/资格/时间等事实 → 拒绝（§七/§二十七）。"""
    paragraph = (
        "<p>为什么选择上海财经大学金融学院？这里有百年积淀的学术传统、"
        "国际化的师资队伍和温暖的校园氛围，是莘莘学子圆梦的理想之地。</p>"
    ) * 10
    return _page("为什么选择上财金融学院？", paragraph, mid="2247500777")


def _public_phone_article() -> str:
    """官方招生通知带公开联系方式上下文 → 不隔离（§十五-§十八）。"""
    body = (
        "<p>我院2026年接收推免生预报名于7月10日开始，申请材料通过系统提交。</p>"
        "<p>咨询电话：13812345678（学院招生办公室），邮箱：zs@mail.shufe.edu.cn。</p>"
    )
    return _page("关于2026年接收推荐免试研究生预报名的通知", body, mid="2247500666")


_ROUTES = {
    NORMAL_URL: "normal_article.html",
    GUIDE_URL: "guide_article.html",
    IMAGE_URL: "image_only_article.html",
    OLD_URL: None,  # 动态生成
    OTHER_ACCOUNT_URL: None,
    NEWS_URL: "image_only_article.html",  # 标题即喜报，预检即拒不应抓取
    VERIFY_URL: "verify_page.html",
    FACTS_IMG_URL: "facts_with_images_article.html",
    SHORT_FACT_URL: None,
    PROMO_URL: None,
    PHONE_URL: None,
}


def _handler(request: httpx.Request) -> httpx.Response:
    # 按 host+path 匹配（忽略 query/fragment）：带跟踪参数的变体 URL 也应命中同一篇
    url = f"https://{request.url.host}{request.url.path}"
    if url == OLD_URL:
        return httpx.Response(200, text=_old_article())
    if url == OTHER_ACCOUNT_URL:
        return httpx.Response(200, text=_other_account_article())
    if url == SHORT_FACT_URL:
        return httpx.Response(200, text=_short_facts_article())
    if url == PROMO_URL:
        return httpx.Response(200, text=_long_promo_article())
    if url == PHONE_URL:
        return httpx.Response(200, text=_public_phone_article())
    fixture = _ROUTES.get(url)
    if fixture:
        return httpx.Response(200, text=_fixture(fixture))
    return httpx.Response(404, text="not found")


@pytest.fixture
def env(tmp_path):
    whitelist = tmp_path / "wechat.yaml"
    whitelist.write_text(
        "sources:\n"
        "  - id: sufe_jwc\n"
        "    account_name: 上海财经大学教务处\n"
        "    publisher: 上海财经大学教务处\n"
        "    scope_unit: 本科生\n"
        "    category: 学工事务\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    seed = tmp_path / "seeds.jsonl"
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    fetcher = WechatArticleFetcher.create(delay=0, client=client)
    return {
        "accounts": load_wechat_accounts(whitelist),
        "seed": seed,
        "fetcher": fetcher,
        "corpus_dir": tmp_path / "corpus",
        "manifest_path": tmp_path / "corpus" / "manifest.jsonl",
        "relations_path": tmp_path / "corpus" / "relations.jsonl",
    }


def _write_seed(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")


def _run(env, *, dry_run=False):
    return crawl_wechat(
        accounts=env["accounts"],
        discovery=SeedURLDiscovery(env["seed"]),
        fetcher=env["fetcher"],
        corpus_dir=env["corpus_dir"],
        manifest_path=env["manifest_path"],
        relations_path=env["relations_path"],
        mode="seed",
        limit=20,
        dry_run=dry_run,
    )


def test_end_to_end_accept_and_quality_gate(env):
    _write_seed(
        env["seed"],
        [
            {"account": "上海财经大学教务处", "url": NORMAL_URL},
            {"account": "上海财经大学教务处", "url": GUIDE_URL},
            {"account": "上海财经大学教务处", "url": IMAGE_URL},
        ],
    )
    report = _run(env)
    assert report.discovered == 3
    assert report.fetch_ok == 3
    assert report.whitelist_passed == 3
    # 转专业通知 + 校园卡指南入库；“详情见下图”空壳在相关性门按无事实拒绝（§七）
    assert report.quality_accepted == 2
    assert report.reject_reasons.get("no_facts") == 1
    manifest = load_manifest(env["manifest_path"])
    by_title = {m.title: m for m in manifest.values()}
    assert "2026级新生报到安排" not in by_title  # 无事实空壳不入库
    accepted = by_title["关于2026年本科生转专业工作的通知"]
    assert accepted.source_type == "official_wechat"
    assert accepted.source_section == "上海财经大学教务处"
    assert accepted.publisher == "上海财经大学教务处"
    assert accepted.scope_unit == "本科生"
    assert accepted.document_kind == "annual_notice"
    assert accepted.quality_status == "accepted"
    assert accepted.content_hash
    corpus_file = env["corpus_dir"] / accepted.file_path
    text = corpus_file.read_text(encoding="utf-8")
    assert "经济学院 经济学 10" in text
    guide = by_title["新生校园卡使用指南"]
    assert guide.document_kind in {"service_guide", "procedure"}


def test_report_counters(env):
    _write_seed(
        env["seed"],
        [
            {"account": "上财校园资讯", "url": OTHER_ACCOUNT_URL},  # 非白名单：预检拒
            {"account": "上海财经大学教务处", "url": OLD_URL, "publish_date": "2022-03-01"},
            {
                "account": "上海财经大学教务处",
                "url": NEWS_URL,
                "title": "喜报！我院学子荣获国家级奖项",
            },
            {"account": "上海财经大学教务处", "url": VERIFY_URL},
            {"account": "上海财经大学教务处", "url": NORMAL_URL},
        ],
    )
    report = _run(env)
    assert report.discovered == 5
    assert report.reject_reasons.get("not_whitelisted") == 1
    assert report.reject_reasons.get("too_old") == 1
    assert report.reject_reasons.get("news_noise") == 1
    assert report.reject_reasons.get("fetch_failed") == 1  # verify 页
    assert report.quality_accepted == 1
    kinds = {
        d["title"]: d.get("document_kind") for d in report.decisions if d["decision"] == "accept"
    }
    assert kinds["关于2026年本科生转专业工作的通知"] == "annual_notice"


def test_old_article_rejected_post_fetch_when_seed_date_missing(env):
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": OLD_URL}])
    report = _run(env)
    assert report.reject_reasons.get("too_old") == 1
    assert not load_manifest(env["manifest_path"])


def test_force_include_allows_old_article(env):
    _write_seed(
        env["seed"],
        [{"account": "上海财经大学教务处", "url": OLD_URL, "force_include": True}],
    )
    report = _run(env)
    assert report.quality_accepted == 1


def test_same_url_discovered_twice_writes_once(env):
    _write_seed(
        env["seed"],
        [
            {"account": "上海财经大学教务处", "url": NORMAL_URL},
            {"account": "上海财经大学教务处", "url": NORMAL_URL + "?scene=21#wechat_redirect"},
        ],
    )
    report = _run(env)
    assert report.quality_accepted == 1
    assert report.duplicate == 1
    manifest = load_manifest(env["manifest_path"])
    assert len(manifest) == 1


def test_rerun_is_unchanged(env):
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": NORMAL_URL}])
    first = _run(env)
    assert first.quality_accepted == 1
    second = _run(env)
    assert second.quality_accepted == 1  # unchanged 也计入 accepted
    manifest = load_manifest(env["manifest_path"])
    assert len(manifest) == 1
    unchanged = [d for d in second.decisions if d["decision"] == "accept"]
    assert unchanged[0]["reason"] == "unchanged"


def test_exact_text_hash_dedup_across_urls(env):
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": NORMAL_URL}])
    _run(env)
    # 另一 URL（不同 mid → 不同 doc_id）正文完全相同 → exact text_hash 去重
    dup_seed = tmp_seed = env["seed"]
    _write_seed(
        dup_seed,
        [{"account": "上海财经大学教务处", "url": "https://mp.weixin.qq.com/s/CopyCat"}],
    )

    def dup_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=_fixture("normal_article.html").replace(
                'var mid = "2247500001"', 'var mid = "2247500007"'
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(dup_handler))
    report = crawl_wechat(
        accounts=env["accounts"],
        discovery=SeedURLDiscovery(tmp_seed),
        fetcher=WechatArticleFetcher.create(delay=0, client=client),
        corpus_dir=env["corpus_dir"],
        manifest_path=env["manifest_path"],
        relations_path=env["relations_path"],
        mode="seed",
    )
    assert report.duplicate == 1
    assert report.quality_accepted == 0


def test_official_policy_and_wechat_explanation_coexist(env):
    """官网正式政策与公众号解读不互相去重，且建立 explains 关系（规格 §十六/§三十一）。"""
    official_url = "https://jwc.sufe.edu.cn/2026/zhuanzhuanye.pdf"
    official = DocMeta(
        doc_id=doc_id_from(official_url),
        title="上海财经大学本科生转专业工作实施细则",
        source_url=official_url,
        publisher="上海财经大学教务处",
        publish_date="2026-02-20",
        category="学工事务",
        fetched_at="2026-08-01T00:00:00+00:00",
        content_hash=sha256_text("正式政策 PDF 正文"),
        file_path="学工事务/转专业细则.md",
        document_kind="policy",
        source_type="official_department",
        topic_key="undergraduate.major_transfer",
        quality_status="accepted",
        retention_status="active",
    )
    append_manifest(env["manifest_path"], [official])
    _write_seed(
        env["seed"],
        [
            {
                "account": "上海财经大学教务处",
                "url": NORMAL_URL,
                "related_official_url": official_url,
            }
        ],
    )
    report = _run(env)
    assert report.quality_accepted == 1
    manifest = load_manifest(env["manifest_path"])
    assert len(manifest) == 2  # 官网 PDF 与公众号文章各自独立存在
    relations = load_relations(env["relations_path"])
    explains = [r for r in relations if r.relation == "explains"]
    assert len(explains) == 1
    assert explains[0].parent_doc_id == official.doc_id
    assert explains[0].confidence == 1.0


def test_topic_based_explains_relation(env):
    """无显式 related_official_url 时，topic_key 唯一匹配官网 policy 自动建立 explains。"""
    official_url = "https://jwc.sufe.edu.cn/2026/zhuanzhuanye.pdf"
    official = DocMeta(
        doc_id=doc_id_from(official_url),
        title="2026年本科生转专业工作实施细则",
        source_url=official_url,
        publisher="上海财经大学教务处",
        publish_date="2026-02-20",
        category="学工事务",
        fetched_at="2026-08-01T00:00:00+00:00",
        content_hash=sha256_text("正式政策 PDF 正文"),
        file_path="学工事务/转专业细则.md",
        document_kind="policy",
        source_type="official_department",
        # 与 ingest 管线为“关于2026年本科生转专业工作的通知”算出的 topic_key 一致
        topic_key="本科生转专业工作",
        quality_status="accepted",
        retention_status="active",
    )
    append_manifest(env["manifest_path"], [official])
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": NORMAL_URL}])
    _run(env)
    relations = load_relations(env["relations_path"])
    explains = [r for r in relations if r.relation == "explains"]
    assert len(explains) == 1
    assert explains[0].confidence == 0.7


def test_dry_run_writes_nothing(env):
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": NORMAL_URL}])
    report = _run(env, dry_run=True)
    assert report.quality_accepted == 1
    assert not env["manifest_path"].exists()
    assert not load_relations(env["relations_path"])


def test_annual_series_canonicalization(env):
    """同系列两年年度通知：最新年度为 current，旧年度转 historical（规格 §十五）。"""
    _write_seed(
        env["seed"],
        [
            {"account": "上海财经大学教务处", "url": NORMAL_URL},
            {"account": "上海财经大学教务处", "url": OLD_URL, "force_include": True},
        ],
    )
    report = _run(env)
    assert report.quality_accepted == 2
    manifest = load_manifest(env["manifest_path"])
    by_title = {m.title: m for m in manifest.values()}
    new = by_title["关于2026年本科生转专业工作的通知"]
    old = by_title["关于2022年本科生转专业工作的通知"]
    assert new.document_kind == old.document_kind == "annual_notice"
    assert new.retention_status == "active"
    assert old.retention_status == "historical"
    assert old.canonical_doc_id == new.doc_id


def test_werss_unavailable_does_not_crash(env):
    class BrokenDiscovery:
        name = "werss"

        def discover(self, *, accounts, limit):
            from sufe_qa.wechat.discovery import DiscoveryResult

            return DiscoveryResult(status="auth_required", message="授权过期")

    report = crawl_wechat(
        accounts=env["accounts"],
        discovery=BrokenDiscovery(),
        fetcher=env["fetcher"],
        corpus_dir=env["corpus_dir"],
        manifest_path=env["manifest_path"],
        mode="werss",
    )
    assert report.discovery_status == "auth_required"
    assert report.discovered == 0
    assert not env["manifest_path"].exists()


def _stub_discovery(articles: list[DiscoveredArticle]):
    class _Stub:
        name = "werss"

        def discover(self, *, accounts, limit):
            return DiscoveryResult(articles=articles)

    return _Stub()


class _NeverFetch:
    """direct content 链路不应触网；被调用即失败。"""

    def fetch(self, url):
        raise AssertionError(f"不应回源抓取: {url}")


class _CountingFetcher:
    def __init__(self, inner):
        self._inner = inner
        self.calls: list[str] = []

    def fetch(self, url):
        self.calls.append(url)
        return self._inner.fetch(url)


_WERSS_CONTENT = (
    '<div id="js_content">'
    "<p>我院2026年接收推荐免试研究生预报名于7月10日至7月25日进行，"
    "申请条件为2026届应届本科毕业生、绩点不低于3.2，材料经学院系统提交。</p>"
    "<p>咨询电话：021-6590XXXX（学院招生办公室）。</p></div>"
)

_WERSS_ITEM = DiscoveredArticle(
    account="上海财经大学教务处",
    url="https://mp.weixin.qq.com/s?__biz=MzI3Mjk2NTgwTEST==&mid=2247510001&idx=1&sn=abc",
    title="关于2026年接收推荐免试研究生预报名的通知",
    publish_date="2025-07-05",
    source="werss",
    content_html=_WERSS_CONTENT,
)


def test_werss_direct_content_skips_fetch(env):
    """WeRSS 已存正文 → 直接 normalize 入库，不调用 WechatArticleFetcher（§十/§四十二）。"""
    report = crawl_wechat(
        accounts=env["accounts"],
        discovery=_stub_discovery([_WERSS_ITEM]),
        fetcher=_NeverFetch(),
        corpus_dir=env["corpus_dir"],
        manifest_path=env["manifest_path"],
        relations_path=env["relations_path"],
        mode="werss",
    )
    assert report.direct_content == 1
    assert report.fetch_ok == 0
    assert report.quality_accepted == 1
    manifest = load_manifest(env["manifest_path"])
    meta = next(iter(manifest.values()))
    assert meta.title == "关于2026年接收推荐免试研究生预报名的通知"
    assert meta.publish_date == "2025-07-05"
    # 身份从长链 URL 解析（无页面 JS 变量）
    assert meta.source_url == (
        "https://mp.weixin.qq.com/s?__biz=MzI3Mjk2NTgwTEST==&mid=2247510001&idx=1"
    )
    text = (env["corpus_dir"] / meta.file_path).read_text(encoding="utf-8")
    assert "申请条件" in text and "咨询电话" in text


def test_werss_empty_content_falls_back_to_fetch(env):
    """WeRSS content_html/content 都为空 → 回源 mp.weixin.qq.com（§十/§四十二）。"""
    item = DiscoveredArticle(
        account="上海财经大学教务处",
        url=NORMAL_URL,
        title="",
        source="werss",
    )
    counting = _CountingFetcher(env["fetcher"])
    report = crawl_wechat(
        accounts=env["accounts"],
        discovery=_stub_discovery([item]),
        fetcher=counting,
        corpus_dir=env["corpus_dir"],
        manifest_path=env["manifest_path"],
        relations_path=env["relations_path"],
        mode="werss",
    )
    assert counting.calls == [NORMAL_URL]
    assert report.direct_content == 0
    assert report.fetch_ok == 1
    assert report.quality_accepted == 1


def test_seed_mode_always_fetches(env):
    """Seed URL 模式始终走 WechatArticleFetcher（§十一/§四十二）。"""
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": NORMAL_URL}])
    counting = _CountingFetcher(env["fetcher"])
    report = crawl_wechat(
        accounts=env["accounts"],
        discovery=SeedURLDiscovery(env["seed"]),
        fetcher=counting,
        corpus_dir=env["corpus_dir"],
        manifest_path=env["manifest_path"],
        relations_path=env["relations_path"],
        mode="seed",
    )
    assert counting.calls == [NORMAL_URL]
    assert report.quality_accepted == 1


def test_facts_with_many_images_accepted(env):
    """20 张图片 + 足够招生事实正文 → accepted（§五：禁止用图片数量判质量）。"""
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": FACTS_IMG_URL}])
    report = _run(env)
    assert report.quality_accepted == 1
    manifest = load_manifest(env["manifest_path"])
    meta = next(iter(manifest.values()))
    text = (env["corpus_dir"] / meta.file_path).read_text(encoding="utf-8")
    assert "报名时间：2025年7月10日至7月25日" in text
    assert "考核方式" in text


def test_short_body_with_facts_accepted(env):
    """120 字但含明确招生变化/年份/专业 → accepted（§六/§七）。"""
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": SHORT_FACT_URL}])
    report = _run(env)
    assert report.quality_accepted == 1
    manifest = load_manifest(env["manifest_path"])
    meta = next(iter(manifest.values()))
    text = (env["corpus_dir"] / meta.file_path).read_text(encoding="utf-8")
    assert "数字经济" in text and "人工智能" in text


def test_long_promo_without_facts_rejected(env):
    """1000 字招生宣传无事实 → rejected as no_facts（§七/§二十七）。"""
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": PROMO_URL}])
    report = _run(env)
    assert report.quality_accepted == 0
    assert report.reject_reasons.get("no_facts") == 1
    assert not env["manifest_path"].exists()


def test_official_public_contact_phone_accepted(env):
    """官方招生通知 + 咨询电话上下文 → accepted（§二十）。"""
    _write_seed(env["seed"], [{"account": "上海财经大学教务处", "url": PHONE_URL}])
    report = _run(env)
    assert report.quality_accepted == 1
    manifest = load_manifest(env["manifest_path"])
    meta = next(iter(manifest.values()))
    assert meta.quality_status == "accepted"
    text = (env["corpus_dir"] / meta.file_path).read_text(encoding="utf-8")
    assert "13812345678" in text  # 公开招生电话保留在正文中
