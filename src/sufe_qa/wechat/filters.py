"""公众号过滤层：官方账号白名单、时间窗、deterministic 相关性过滤（规格 §九-§十四）。

判定顺序：strong_exclude > strong_include > 文档类型启发。
- 标题命中强排除词（喜报/风采/讲座回顾…）直接拒绝，不浪费抓取；
- 标题命中高价值词（指南/办理/通知/转专业…）保留；
- 中性标题先抓正文，再按 标题+正文前若干段+账号 用现有 classify_document_kind 分型，
  news/event/promotion 一律拒绝（规格 §十一：news 默认不得进入 main QA）。

不引入 LLM 分类器；所有规则确定性、可回归测试。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from sufe_qa.config import CATEGORIES
from sufe_qa.ingest.classification import classify_admission_level, classify_document_kind

# 公众号采集时间窗（规格 §十四）：默认只接受 2024-01-01 至今，force_include 除外
MIN_PUBLISH_DATE = "2024-01-01"

# 高价值标题关键词（规格 §十二/§二十五）：围绕招生/推免/选拔，不做校园服务覆盖
STRONG_INCLUDE = (
    "推免",
    "预推免",
    "推荐免试",
    "直博",
    "硕博连读",
    "优秀大学生",
    "夏令营",
    "申请考核",
    "博士招生",
    "硕士招生",
    "复试",
    "调剂",
    "招生简章",
    "招生",
    "报考",
    "报名",
    "申请",
    "实验班",
    "拔尖班",
    "卓越班",
    "创新班",
    "转专业",
    "专业分流",
    "双学位",
    "辅修",
    "选拔",
    "国际项目",
    "联合培养",
    "指南",
    "办理",
    "流程",
    "办法",
    "细则",
    "通知",
    "常见问题",
    "faq",
    "FAQ",
    "选课",
    "奖学金",
    "助学金",
    "新生",
    "报到",
    "须知",
    "安排",
    "公示",
)

# 强排除标题关键词（规格 §十二）：这些是真实正文但对校园 QA 没价值
STRONG_EXCLUDE = (
    "喜报",
    "喜讯",
    "精彩回顾",
    "活动回顾",
    "风采",
    "讲座",
    "论坛",
    "党建",
    "主题党日",
    "校友",
    "人物专访",
    "专访",
    "学术活动",
    "学术讲座",
    "比赛",
    "获奖",
    "赛事",
    "精彩瞬间",
    "节日",
    "教师招聘",
    "学院新闻",
    "晚会",
    "典礼",
    "剪影",
    "纪实",
    "打卡",
    "投票",
    "摄影",
    "征集令",
    "招募令",
    "军训",
    "运动会",
    "文艺",
    "演出",
    "展览",
    "参访",
    "研讨会",
    "成功举办",
    "圆满举办",
    "顺利举行",
    "圆满落幕",
    "落幕",
    "收官",
    "一等奖",
    "二等奖",
    "国赛",
    "夺冠",
    "金奖",
    "论文入选",
    "论文发表",
    "成果速递",
    "顶会",
    "诚邀全球英才",
    "诚邀海内外英才",
    "英才加盟",
    "招聘公告",
    "结项",
    "党课",
    "党支部",
    "党委",
)

# 软排除词（规格 §二十六）：仅当标题同时具有招生/选拔信号时延后到正文判定
# （“推免政策讲座通知”可能有 QA 价值）；喜报/风采/回顾等硬噪声词仍即拒。
_SOFT_EXCLUDE = {"讲座", "论坛"}

# 招生/选拔动作信号（规格 §二十六）：标题同时命中强排除词与这些信号时，
# 不预检拒绝，抓取后结合正文事实再判（如“推免政策解读会通知”仍有 QA 价值）
_ADMISSION_SIGNAL = (
    "推免",
    "预推免",
    "夏令营",
    "招生",
    "报名",
    "申请",
    "复试",
    "调剂",
    "选拔",
    "转专业",
    "实验班",
    "报考",
    "录取",
    "简章",
    "通知",
)

# 政策解读类标题：正文有价值但不是正式政策本身，类型映射为 procedure（规格 §十一：
# 公众号 document_kind 映射到现有枚举的最近语义，不新增枚举）
_POLICY_EXPLANATION_RE = re.compile(r"(一图读懂|图解|解读|释义|问答|热点问答)")
_FORMAL_POLICY_RE = re.compile(r"《[^》]*(?:办法|规定|细则|条例|章程)[^》]*》")

_NOISE_KINDS = frozenset({"news", "event", "promotion"})

# 中性标题的正文新闻性证据：命中 >=2 个不同词判 news_noise。
# 只在标题既未命中强排除也未命中高价值词时启用，正常通知/指南不会走到这里。
_BODY_NEWS_MARKERS = (
    "召开",
    "举行",
    "出席",
    "致辞",
    "走访",
    "调研",
    "座谈",
    "合影",
    "开幕式",
    "闭幕式",
)

# 党建/思政活动报道的正文证据：标题无排除词时（如“追寻红色记忆”），
# 正文命中 >=2 个不同词判 news_noise；同样只在标题未命中高价值词时启用。
_BODY_PARTY_MARKERS = (
    "党支部",
    "党员",
    "党课",
    "党委",
    "主题党日",
    "八项规定",
    "廉洁",
    "红色记忆",
    "党纪",
    "入党",
)

# 事实型元素（规格 §七）：质量判断只看可提取正文有没有可引用事实，不看图片（§五）
_FACT_RES = {
    "date": re.compile(r"20\d{2}\s*年|20\d{2}-\d{2}-\d{2}|\d{1,2}\s*月\s*\d{1,2}\s*日"),
    "number": re.compile(r"\d{2,}"),
    "contact": re.compile(
        r"1[3-9]\d{9}|0\d{2,3}-?\d{7,8}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
        r"|QQ|https?://"
    ),
    "action": re.compile(
        r"报名|申请|条件|材料|对象|方式|考核|复试|调剂|录取|资格|选拔|学费|学制"
        r"|名单|咨询|联系|提交|审核|计划|专业|招生|推免|报考|时间|地点"
    ),
}


def fact_signals(text: str) -> set[str]:
    """正文中命中的事实元素组（date/number/contact/action），用于 meaningful-facts 判定。"""
    return {name for name, pattern in _FACT_RES.items() if pattern.search(text or "")}


def has_meaningful_facts(text: str, min_signals: int = 2) -> bool:
    """正文是否含 >=min_signals 组事实元素；不含事实的宣传/口号类文本应拒绝（§七）。"""
    return len(fact_signals(text)) >= min_signals


# 话题分类（规格 §三十八报告口径）：招生语义层级优先（degree/non-degree 严格区分，
# 在职课程培训班等非学历项目不再混入硕士招生），其余主题走关键词规则。
_ADMISSION_TOPIC = {
    "recommendation_admission": "推免/预推免",
    "reexamination": "复试/调剂",
    "adjustment": "复试/调剂",
    "doctoral_admission": "博士招生",
    "master_admission": "硕士招生",
    "undergraduate_admission": "本科招生",
    "non_degree_program": "非学历项目",
    "other_admission": "其他招生",
}

_TOPIC_RULES = (
    ("推免/预推免", ("推免", "预推免", "推荐免试", "直博", "硕博连读")),
    ("夏令营", ("夏令营", "优秀大学生")),
    ("复试/调剂", ("复试", "调剂")),
    ("博士招生", ("博士", "申请考核")),
    ("硕士招生", ("硕士", "MPAcc", "MAud", "MBA", "研究生招生")),
    ("转专业", ("转专业", "专业分流", "专业选择")),
    (
        "实验班/选拔",
        ("实验班", "拔尖班", "卓越班", "创新班", "校内选拔", "二次选拔", "双学位", "辅修", "选拔"),
    ),
    ("国际项目", ("国际项目", "联合培养", "交换", "暑校", "3+1", "2+2", "海外", "国际组织")),
    ("招生宣传", ("亮点", "宣传", "开放日", "宣讲", "招生季")),
)


def classify_topic(title: str, body: str = "") -> str:
    """文章话题归类：招生/推免/选拔口径（§三十八）。无法归类返回“其他”。"""
    level = classify_admission_level(title, body)
    if level:
        return _ADMISSION_TOPIC[level]
    for topic, keywords in _TOPIC_RULES:
        if any(k in (title or "") for k in keywords):
            return topic
    preview = (body or "")[:_BODY_PREVIEW_FOR_TOPIC]
    for topic, keywords in _TOPIC_RULES:
        if any(k in preview for k in keywords):
            return topic
    return "其他"


_BODY_PREVIEW_FOR_TOPIC = 400


@dataclass(frozen=True)
class WechatAccount:
    """白名单公众号：article.account_name 必须精确等于 account_name 或 alias 才放行。"""

    account_id: str
    account_name: str
    publisher: str
    scope_unit: str = ""
    category: str = "学工事务"
    aliases: tuple[str, ...] = ()
    enabled: bool = True

    def matches(self, account_name: str) -> bool:
        name = (account_name or "").strip()
        return bool(name) and (name == self.account_name or name in self.aliases)


def load_wechat_accounts(path: str | Path) -> list[WechatAccount]:
    """加载公众号白名单 yaml；enabled=false 的条目直接忽略。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    accounts: list[WechatAccount] = []
    for raw in data.get("sources") or []:
        if not raw.get("enabled", True):
            continue
        category = str(raw.get("category") or "学工事务")
        if category not in CATEGORIES:
            raise ValueError(f"公众号 {raw.get('id')}: 非法分类 {category}")
        accounts.append(
            WechatAccount(
                account_id=str(raw["id"]),
                account_name=str(raw["account_name"]),
                publisher=str(raw.get("publisher") or raw["account_name"]),
                scope_unit=str(raw.get("scope_unit") or ""),
                category=category,
                aliases=tuple(str(a) for a in raw.get("aliases") or ()),
                enabled=True,
            )
        )
    return accounts


def match_account(account_name: str, accounts: list[WechatAccount]) -> WechatAccount | None:
    """严格账号身份匹配（规格 §九）：仅按 account_name/alias，不看正文是否提到学校。"""
    for account in accounts:
        if account.matches(account_name):
            return account
    return None


@dataclass(frozen=True)
class RelevanceDecision:
    keep: bool
    reason: str  # strong_exclude | strong_include | news_noise | neutral_pass
    matched_keyword: str = ""


def _hit(text: str, keywords: tuple[str, ...]) -> str:
    for kw in keywords:
        if kw in text:
            return kw
    return ""


def relevance_check(title: str, body: str = "") -> RelevanceDecision:
    """标题优先的确定性相关性判定（本轮 §二十五-§二十八调优）。

    - 标题只命中强排除 → 直接拒绝（“转专业学生风采展示”不会被“转专业”救回）；
    - 软排除词（讲座/论坛）与招生信号同现 → 不预检拒绝，留待正文判定；
    - 标题命中高价值词 → 保留；
    - 有正文时统一校验 meaningful facts：无事实元素即宣传/口号，拒绝为 no_facts；
    - 中性标题结合正文前段做文档分型：news/event/promotion 拒绝，其余保留。
    """
    title = (title or "").strip()
    exclude_kw = _hit(title, STRONG_EXCLUDE)
    include_kw = _hit(title, STRONG_INCLUDE)
    if exclude_kw and (
        exclude_kw not in _SOFT_EXCLUDE or (not include_kw and not _hit(title, _ADMISSION_SIGNAL))
    ):
        return RelevanceDecision(False, "strong_exclude", exclude_kw)
    if body:
        preview = body[:600]
        kind = classify_document_kind(title, preview)
        if kind in _NOISE_KINDS and not include_kw:
            return RelevanceDecision(False, "news_noise", kind)
        if not include_kw:
            news_hits = {m for m in _BODY_NEWS_MARKERS if m in preview}
            if len(news_hits) >= 2:
                return RelevanceDecision(False, "news_noise", "+".join(sorted(news_hits)))
            party_hits = {m for m in _BODY_PARTY_MARKERS if m in preview}
            if len(party_hits) >= 2:
                return RelevanceDecision(
                    False, "news_noise", "党建:" + "+".join(sorted(party_hits))
                )
        if not has_meaningful_facts(body):
            return RelevanceDecision(False, "no_facts", ",".join(sorted(fact_signals(body))))
    if include_kw:
        return RelevanceDecision(True, "strong_include", include_kw)
    return RelevanceDecision(True, "neutral_pass")


def classify_wechat_kind(title: str, body_text: str) -> str:
    """公众号文章 → 现有 document_kind 枚举的最近语义映射。

    - “一图读懂/解读”类 → procedure（办事解读，不与正式政策同级）；
    - 书名号正式制度（《…办法》）→ policy；
    - 其余走现有 classify_document_kind（年度通知自动获得 annual 生命周期）。
    """
    title = (title or "").strip()
    if _POLICY_EXPLANATION_RE.search(title) and not _FORMAL_POLICY_RE.search(title):
        return "procedure"
    return classify_document_kind(title, body_text)


def date_gate(
    publish_date: str, *, force_include: bool = False, min_date: str = MIN_PUBLISH_DATE
) -> tuple[bool, str]:
    """时间窗（规格 §十四）：早于 min_date 且未 force_include → 拒绝。

    publish_date 为 unknown/空时不预拒绝（留待抓取后复检，复检仍 unknown 则由
    lifecycle 的 missing_publish_date 规则归档年度类，长期类可保留）。
    """
    if force_include:
        return True, "force_include"
    date = (publish_date or "").strip()
    if not date or date == "unknown":
        return True, "unknown_date"
    if date < min_date:
        return False, "too_old"
    return True, "in_window"
