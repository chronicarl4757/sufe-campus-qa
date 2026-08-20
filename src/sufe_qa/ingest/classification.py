"""文档用途和政策主题的确定性标准化。"""

from __future__ import annotations

import re

_POLICY_KWS = ("办法", "规定", "条例", "章程", "实施细则", "管理办法")
_PROCEDURE_KWS = ("流程", "指南", "办理", "须知")
_FAQ_KWS = ("常见问题", "常见问答", "FAQ", "问答")
_MANUAL_KWS = ("操作手册", "使用手册", "用户手册")
_SERVICE_KWS = ("服务说明", "服务指南", "服务介绍", "服务流程")
_FORM_KWS = ("申请表", "登记表", "审批表", "表格", "模板")
_PUBLIC_LIST_KWS = ("名单", "公示")
_NEWS_KWS = ("新闻", "动态", "召开", "走访", "调研", "活动")
_PROMOTION_KWS = ("宣讲会", "招生宣传", "开放日", "分享团", "活动回顾")
_EVENT_KWS = ("讲座", "论坛", "会议预告", "比赛", "竞赛")
_ANNUAL_BUSINESS_KWS = (
    "通知",
    "公告",
    "报名",
    "评选",
    "评审",
    "招生",
    "推免",
    "复试",
    "调剂",
    "录取",
    "申请",
    "选拔",
    "考核",
    "报到",
    "安排",
    "奖学金",
    "助学金",
    "资助",
    "夏令营",
)
_TEMPORAL_TITLE_RE = re.compile(
    r"(?:19|20)\d{2}(?:\s*[-—至/]\s*(?:19|20)\d{2})?\s*(?:年|年度|学年)?"
)
_FORMAL_POLICY_WRAPPER_RE = re.compile(
    r"关于印发《[^》]*(?:办法|规定|细则|条例|章程)[^》]*》(?:的)?通知"
)

_TOPIC_RULES = (
    (("本科生", "奖学金"), "undergraduate.scholarship.merit"),
    (("国家奖学金",), "undergraduate.scholarship.national"),
    (("国家励志奖学金",), "undergraduate.scholarship.incentive"),
    (("助学金", "资助"), "undergraduate.financial_aid"),
    (("困难认定", "家庭经济困难"), "undergraduate.financial_aid.need_assessment"),
    (("勤工助学",), "undergraduate.work_study"),
    (("推免", "推荐免试"), "undergraduate.recommendation_exemption"),
    (("选课", "退课", "重修"), "undergraduate.course_selection"),
    (("休学", "复学", "退学"), "undergraduate.enrollment_status"),
    (("转专业", "转院系"), "undergraduate.major_transfer"),
    (("校外学习学分", "成绩转换"), "undergraduate.external_credit_transfer"),
    (("研究生", "选课"), "graduate.course_selection"),
    (("学分认定",), "graduate.credit_recognition"),
    (("学位论文", "答辩", "学位授予"), "graduate.degree_thesis"),
    (("博士", "申请考核"), "graduate.doctoral_application_assessment"),
    (("硕博连读",), "graduate.integrated_master_doctor"),
    (("国际交流", "公派留学", "短期交流"), "student.international_exchange"),
)

# ---------------- 招生语义层级（本轮 §二-§九） ----------------
# 少量高精度规则；判定优先级：正文明确学历层次 > 标题明确学历层次 > 弱关键词。
# 证据不足归 other_admission，不硬塞 master_admission；非招生文档返回 ""。

ADMISSION_LEVELS = (
    "undergraduate_admission",
    "master_admission",
    "doctoral_admission",
    "recommendation_admission",
    "reexamination",
    "adjustment",
    "non_degree_program",
    "other_admission",
)

# 非学历项目证据：培训班/研修班/证书项目等（§五）；“在职”本身不构成证据（§六）
_NON_DEGREE_RE = re.compile(
    r"非学历教育|非学历培训|课程培训班|高级研修班|研修班|专题培训|证书项目"
    r"|培训项目|继续教育学院|结业证书|课程班"
)
# 项目自明的非学历声明（“办班性质：非学历教育”）：最高强度证据，直接判定
_EXPLICIT_NON_DEGREE_RE = re.compile(r"非学历教育|非学历培训")
# 招生文档的标题意图：无招生意图的文档（奖学金办法/医保制度/查号表/毕业细则）
# 不进入招生层级判定，防止正文顺带提及“继续教育学院/结业证书/招生计划”误归
_ADMISSION_INTENT_RE = re.compile(
    r"招生|报名|录取|推免|预推免|推荐免试|调剂|复试|夏令营|申请考核|选拔|招录|选调|简章|申报"
)
# 明确授予学历学位的证据（§五）：必须锚定“授予/颁发/获得”动作——
# 学院简介里的“博士点/博士学位的教师占比”不构成项目授位证据
_DEGREE_GRANT_RE = re.compile(
    r"授予[^。]{0,8}(?:学士|硕士|博士)学位"
    r"|颁发[^。]{0,8}(?:硕士|博士|本科)[^。]{0,4}(?:毕业证书|学位证书)"
    r"|获得[^。]{0,8}学位证书"
)
_DOCTORAL_RE = re.compile(r"博士研究生|博士学位|博士招生|申请考核|直博")
_DOCTORAL_BODY_RE = re.compile(r"博士研究生招生|博士学位研究生|博士招生|申请考核制|直接攻读博士")
_MASTER_RE = re.compile(
    r"硕士研究生|硕士学位|专业学位硕士|研究生招生|全国硕士研究生"
    r"|MPAcc|MAud|MBA|EMBA|MF(?![A-Za-z])|金融硕士|会计硕士|审计硕士"
)
# 正文判定用严格形态：学院简介中的“博士点/博士学位的教师/硕士点”不构成项目层次证据
_MASTER_BODY_RE = re.compile(
    r"硕士研究生(?:招生|考试)|硕士学位研究生|硕士专业学位|专业学位硕士|全国硕士研究生"
    r"|MPAcc|MAud|MBA|EMBA|金融硕士|会计硕士|审计硕士"
)
_UG_RE = re.compile(r"本科招生|本科生招生|普通本科|高考|本科录取|本科新生|招生计划")
_RECOMMEND_RE = re.compile(r"推免|推荐免试|预推免|接收推免")
_SUMMER_CAMP_RE = re.compile(r"夏令营")
_SUMMER_CAMP_ADMISSION_RE = re.compile(r"推免|硕士|研究生|选拔|录取")
_REEXAM_RE = re.compile(r"复试")
_ADJUST_RE = re.compile(r"调剂")
_ADMISSION_WEAK_RE = re.compile(r"招生|报名|录取")


def classify_admission_level(title: str, body_text: str = "") -> str:
    """招生类文档的学历/非学历层级（本轮 §四-§八）。

    - 非学历暗示（培训班/研修班/结业证书/非学历教育）且无明确授予学位证据
      → non_degree_program；
    - 推免（含直博）→ recommendation_admission；夏令营须与推免/研究生选拔相关；
    - 复试/调剂先于层次判定（更具体的业务环节）；
    - 博士/硕士/本科：正文证据优先于标题，博士需无硕士证据才成立；
    - 仅“招生/报名”弱词无层次证据 → other_admission；非招生 → ""。
    """
    title = title or ""
    head = (body_text or "")[:1500]  # 层次证据多在开头（办班性质/报考条件/学制）

    if not _ADMISSION_INTENT_RE.search(title):
        return ""
    if _EXPLICIT_NON_DEGREE_RE.search(head):
        return "non_degree_program"
    # 非学历暗示只认标题命中：正文顺带提及其他项目（“课程培训班/研修班”
    # 出现在部门列表或项目清单里）不足以把学历招生简章翻转成 non-degree
    if _NON_DEGREE_RE.search(title) and not _DEGREE_GRANT_RE.search(head):
        return "non_degree_program"

    if _RECOMMEND_RE.search(title):
        return "recommendation_admission"
    if _SUMMER_CAMP_RE.search(title) and _SUMMER_CAMP_ADMISSION_RE.search(title + head[:400]):
        return "recommendation_admission"

    if _REEXAM_RE.search(title):
        return "reexamination"
    if _ADJUST_RE.search(title):
        return "adjustment"

    master = bool(_MASTER_BODY_RE.search(head) or _MASTER_RE.search(title))
    doctoral = bool(_DOCTORAL_BODY_RE.search(head) or _DOCTORAL_RE.search(title))
    if doctoral and not master:
        return "doctoral_admission"
    if master:
        return "master_admission"
    if _UG_RE.search(head) or _UG_RE.search(title):
        return "undergraduate_admission"

    if _ADMISSION_WEAK_RE.search(title):
        return "other_admission"
    return ""


def normalize_policy_name(title: str) -> str:
    text = re.sub(r"\s+", "", title or "").strip(" ：:，,。")
    quoted = re.search(r"《([^》]+)》", text)
    if quoted:
        text = quoted.group(1)
    text = re.sub(r"^关于(?:印发|修订|制定|出台|发布|实施)?", "", text)
    text = re.sub(r"(?:的通知|通知|公告)$", "", text)
    text = re.sub(r"^关于", "", text)
    text = re.sub(r"（(?:修订|试行|暂行|修订稿)[^）]*）$", "", text)
    return text.strip(" ：:，,。")


def standardize_topic_key(title: str, policy_name: str = "", scope_unit: str = "") -> str:
    """把长期制度、修订通知和年度通知归并到稳定业务主题。"""
    text = re.sub(r"\s+", "", f"{title}{policy_name}{scope_unit}")
    for terms, key in _TOPIC_RULES:
        if all(term in text for term in terms):
            return key
    normalized = normalize_policy_name(policy_name or title)
    normalized = re.sub(r"20\d{2}年|20\d{2}年度|（[^）]*(?:修订|试行|暂行)[^）]*）", "", normalized)
    return normalized or "unknown.topic"


def classify_document_kind(
    title: str,
    body_text: str,
    *,
    quality_status: str = "accepted",
    has_valid_attachment: bool = False,
) -> str:
    if quality_status in {"incomplete_document", "low_quality", "quarantined", "rejected"}:
        return "incomplete"
    text = f"{title}\n{body_text}"
    # 书名号中的正式制度名优先于“活动/管理动态”等通用隔离词。
    if _FORMAL_POLICY_WRAPPER_RE.search(title):
        return "policy"
    if any(keyword in title for keyword in _PUBLIC_LIST_KWS):
        return "public_list"
    # 标题明确自称“新闻/动态”时按新闻隔离；其余宣讲会、活动回顾再归 promotion。
    # “新闻与社会高等研究院/新闻与传播（硕士）”是单位/专业名而非新闻自称（blocking 误伤：
    # 该院 2027 推免通知曾因此被归档）。标题命中“新闻与”复合名称时跳过两条新闻规则。
    _xinwen_in_unit_name = "新闻与" in title
    if ("新闻" in title and not _xinwen_in_unit_name) or "动态" in title:
        return "news"
    if any(keyword in title for keyword in _PROMOTION_KWS):
        return "promotion"
    if any(keyword in title for keyword in _EVENT_KWS):
        return "event"
    if any(keyword in title for keyword in _NEWS_KWS) and not _xinwen_in_unit_name:
        return "news"
    # 文号/发布日期前缀不应把“关于印发《正式制度》”误判为年度业务通知。
    # 该规则只接受书名号内带制度词的明确包装标题，不影响“2025 年复试录取办法”
    # 等每年重新制定的招生安排。
    if _TEMPORAL_TITLE_RE.search(title) and any(
        keyword in title for keyword in _ANNUAL_BUSINESS_KWS
    ):
        return "annual_notice"
    if any(keyword in text for keyword in _FAQ_KWS):
        return "faq"
    if any(keyword in title for keyword in _POLICY_KWS) or (
        "第一条" in body_text[:500] and any(keyword in body_text[:500] for keyword in _POLICY_KWS)
    ):
        return "policy"
    if any(keyword in text for keyword in _FORM_KWS) and len(body_text.strip()) < 300:
        return "form"
    if any(keyword in text for keyword in _MANUAL_KWS):
        return "manual"
    if any(keyword in text for keyword in _SERVICE_KWS):
        return "service_guide"
    if any(keyword in text for keyword in _PROCEDURE_KWS):
        return "procedure"
    if "通知" in title or "公告" in title:
        return "annual_notice"
    if has_valid_attachment:
        return "manual"
    return "incomplete"
