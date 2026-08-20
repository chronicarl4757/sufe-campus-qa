"""微信公众号文章接入：URL 发现（discovery）与单篇抓取解析彻底解耦。

设计原则（任务规格 §一/§三）：
- 只接收公开的 mp.weixin.qq.com 文章 URL；不逆向微信历史消息接口，不碰 Cookie 池、
  代理池、验证码与风控绕过。
- We-MP-RSS 只是可选的 discovery service + 正文缓存；失效时可整体替换 discovery 层，
  正文抓取（WechatArticleFetcher）、过滤、入库不依赖它。
- 数据定位（本轮 §二-§四）：补充学院级、年度性的招生/推免/选拔信息
  （source_type=official_wechat），不追求校园生活服务覆盖；
  质量判断只看可提取正文中的事实，不看图片数量。
"""

from sufe_qa.wechat.article import (
    WechatArticle,
    WechatArticleFetcher,
    normalize_wechat_content,
    parse_wechat_article,
    parse_wechat_content,
)
from sufe_qa.wechat.discovery import (
    DiscoveredArticle,
    DiscoveryResult,
    SeedURLDiscovery,
    WeRSSDiscovery,
)
from sufe_qa.wechat.filters import (
    WechatAccount,
    classify_topic,
    classify_wechat_kind,
    has_meaningful_facts,
    load_wechat_accounts,
    match_account,
    relevance_check,
)
from sufe_qa.wechat.runner import WechatCrawlReport, crawl_wechat

__all__ = [
    "DiscoveredArticle",
    "DiscoveryResult",
    "SeedURLDiscovery",
    "WeRSSDiscovery",
    "WechatAccount",
    "WechatArticle",
    "WechatArticleFetcher",
    "WechatCrawlReport",
    "classify_topic",
    "classify_wechat_kind",
    "crawl_wechat",
    "has_meaningful_facts",
    "load_wechat_accounts",
    "match_account",
    "normalize_wechat_content",
    "parse_wechat_article",
    "parse_wechat_content",
    "relevance_check",
]
