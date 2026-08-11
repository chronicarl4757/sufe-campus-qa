"""抓取文档的质量评估与类型分类：入库前的轻量规则筛选，输出可解释的分数与原因。

规则全部基于标题 + 正文的确定性判定（无模型调用），score 按 reason 条数线性扣分，
保证结果可解释、可回归测试。status 优先级：incomplete_document > low_quality > accepted。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 附件依赖页关键词：正文过短且命中其一，说明实质内容在附件里
_ATTACHMENT_HINTS = ("详见附件", "附件如下", "点击下载", "请下载", "见附件", "附表", "附：")
# 附件依赖页的正文长度阈值（去空白后）
_ATTACHMENT_BODY_MAX = 120
# 正文过短阈值（去空白后）
_MIN_BODY_CHARS = 80
# 哈希样式无效标题（如 "03a91ba5c9a8"）
_HASH_TITLE_RE = re.compile(r"^[0-9a-f]{8,}$")
# 站点通用名无效标题（与 crawler/article.py 的 _GENERIC_TITLES 保持同步）
_INVALID_TITLES = {
    "首页",
    "通知公告",
    "欢迎访问",
    "无标题",
    "untitled",
    "index",
    "default",
    "管理规定",
    "规章制度",
    "新闻动态",
    "学院新闻",
    "图片新闻",
    "最新动态",
    "综合新闻",
    "招生信息",
    "信息公开",
    "下载专区",
    "办事指南",
    "机构设置",
    "联系我们",
    "公示公告",
    "公告公示",
    "公示专栏",
    "硕士生招生",
}
# 导航污染：短行（<=15 字无标点）占比阈值与最少行数
_SHORT_LINE_MAX = 15
_SHORT_LINE_RATIO = 0.6
_NAV_MIN_LINES = 10
# 站点页脚词：命中 >=3 个不同词视为页脚污染（"3 个以上"按法律惯例含本数）
_FOOTER_WORDS = ("备案号", "沪ICP备", "邮编", "地址：", "电话：", "版权所有")
_FOOTER_MIN_HITS = 3
# 标点判定含全角句点"．"（中文编号列表"1．"常用），否则编号列表会被误判为无标点短行
_PUNCT_RE = re.compile(r"[。，；：、！？.,;:!?()（）《》【】\[\]{}．]")
# 指针型公示页：具体标题（>=12 字、非通用词）+ 明确发布日期的短正文页，
# 其标题与日期本身即信息（如"名单公示了吗"类问题的答案），不按正文过短判低质
_INFORMATIVE_TITLE_MIN = 12

# doc_type 关键词（优先级从上到下，首条命中即返回）
_POLICY_KWS = ("办法", "规定", "条例", "章程", "实施细则", "管理办法")
_PROCEDURE_KWS = ("流程", "指南", "须知", "办理", "操作手册")
_PUBLIC_LIST_KWS = ("名单", "公示")
_PUBLIC_LIST_MIN_LINES = 20
_ANNOUNCEMENT_KWS = ("公告", "通知")
_DOWNLOAD_KWS = ("下载", "模板", "表格", "申请表")
_EVENT_KWS = ("讲座", "活动", "比赛", "竞赛", "报名开始")
_NEWS_KWS = ("新闻", "动态", "举行", "召开", "走访", "调研")

# 类型加权：政策/规程/公告类上调，新闻/活动类下调，其余不加权。
# 分类输出里没有 notice，但 boost 表保留 notice 档（announcement 视同 notice 档）。
_BOOSTS = {
    "policy": 1.1,
    "notice": 1.1,
    "procedure": 1.1,
    "announcement": 1.1,
    "download_template": 1.1,
    "news": 0.85,
    "event": 0.85,
}


@dataclass
class QualityResult:
    accepted: bool
    score: float  # 0..1
    status: str  # accepted | incomplete_document | low_quality
    reasons: list[str] = field(default_factory=list)
    doc_type: str = "unknown"
    # policy | notice | procedure | announcement | public_list
    # | download_template | news | event | unknown


def _squash(text: str) -> str:
    """去掉全部空白字符后的正文（长度判定统一口径）。"""
    return re.sub(r"\s+", "", text)


def _classify(title: str, body_text: str) -> str:
    """按 title+body 关键词分类，优先级从上到下，首条命中即返回。"""
    text = f"{title}\n{body_text}"
    if any(k in text for k in _POLICY_KWS):
        return "policy"
    if any(k in text for k in _PROCEDURE_KWS):
        return "procedure"
    body_lines = [ln for ln in body_text.splitlines() if ln.strip()]
    if any(k in text for k in _PUBLIC_LIST_KWS) and len(body_lines) >= _PUBLIC_LIST_MIN_LINES:
        return "public_list"
    if any(k in text for k in _ANNOUNCEMENT_KWS):
        return "announcement"
    if any(k in text for k in _DOWNLOAD_KWS):
        return "download_template"
    if any(k in text for k in _EVENT_KWS):
        return "event"
    if any(k in text for k in _NEWS_KWS):
        return "news"
    return "unknown"


def default_boost(doc_type: str) -> float:
    """类型加权系数：政策/规程/公告/下载模板 1.1，新闻/活动 0.85，其余 1.0。"""
    return _BOOSTS.get(doc_type, 1.0)


def classify_document(title: str, body_text: str) -> str:
    """公开的分类入口（indexer 写入 boost 用），规则同 _classify。"""
    return _classify(title, body_text)


def _is_informative_title(t: str) -> bool:
    """标题本身是否携带完整信息（长、具体、非通用词），用于指针型公示页豁免。"""
    return (
        len(t) >= _INFORMATIVE_TITLE_MIN
        and not _HASH_TITLE_RE.match(t)
        and t.lower() not in _INVALID_TITLES
    )


def assess_document(
    title: str,
    body_text: str,
    has_valid_attachment: bool,
    publish_date: str = "unknown",
    *,
    trusted_document_kind: str = "",
) -> QualityResult:
    """评估抓取文档是否值得入库。所有规则命中都会记录 reason，status 取最高优先级。"""
    reasons: list[str] = []
    incomplete = False
    t = title.strip()
    body = _squash(body_text)

    # 1) 附件依赖页：正文很短且引导读者看附件，但附件缺失/解析失败
    if (
        len(body) < _ATTACHMENT_BODY_MAX
        and any(k in body_text for k in _ATTACHMENT_HINTS)
        and not has_valid_attachment
    ):
        incomplete = True
        reasons.append("正文依赖附件但附件缺失或解析失败")

    # 2) 无效标题：空、纯哈希样式、站点通用名
    if not t:
        reasons.append("标题为空")
    elif _HASH_TITLE_RE.match(t):
        reasons.append(f"标题为哈希样式（无语义）: {t}")
    elif t.lower() in _INVALID_TITLES:
        reasons.append(f"标题为站点通用词: {t}")

    # 3) 导航污染：短无标点行占比过高，或命中多个站点页脚词
    lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
    if len(lines) >= _NAV_MIN_LINES and trusted_document_kind != "service_guide":
        short = sum(1 for ln in lines if len(ln) <= _SHORT_LINE_MAX and not _PUNCT_RE.search(ln))
        if short / len(lines) > _SHORT_LINE_RATIO:
            reasons.append(f"短无标点行占比 {short / len(lines):.0%}，疑似导航样板污染")
    footer_hits = sum(1 for w in _FOOTER_WORDS if w in body_text)
    if footer_hits >= _FOOTER_MIN_HITS:
        reasons.append(f"命中 {footer_hits} 个站点页脚词，疑似页脚污染")

    # 4) 正文过短且无有效附件兜底；指针型公示页（具体标题 + 明确日期）豁免：
    # 其标题与日期本身即答案，薄正文是源站保护所致而非模板污染
    if len(body) < _MIN_BODY_CHARS and not has_valid_attachment:
        if not (_is_informative_title(t) and publish_date != "unknown"):
            reasons.append(f"正文过短（去空白 {len(body)} 字符）且无有效附件")

    # status 优先级：附件缺失的 incomplete_document 高于 low_quality
    if incomplete:
        status = "incomplete_document"
    elif reasons:
        status = "low_quality"
    else:
        status = "accepted"
    # 初始 1.0，每条 reason 扣 0.25，下限 0
    score = max(0.0, 1.0 - 0.25 * len(reasons))
    return QualityResult(
        accepted=status == "accepted",
        score=score,
        status=status,
        reasons=reasons,
        doc_type=_classify(title, body_text),
    )
