"""招生语义层级 classify_admission_level 回归测试（§三十）：degree/non-degree 严格区分。"""

from __future__ import annotations


from sufe_qa.crawler.engine import CrawledArticle
from sufe_qa.ingest.classification import classify_admission_level
from sufe_qa.ingest.pipeline import ingest_crawled_articles
from sufe_qa.schema import default_relations_path, load_manifest
from sufe_qa.wechat.filters import classify_topic

# ---------------- §三十 五个规定 case ----------------


def test_mpacc_part_time_is_master_admission():
    assert (
        classify_admission_level(
            "上海财经大学2026年会计硕士专业学位（MPAcc）会计与财务精英研究方向（非全日制）招生简章",
            "本项目为硕士专业学位研究生教育，非全日制学习，学制2.5年，毕业时颁发硕士毕业证书和硕士学位证书。",
        )
        == "master_admission"
    )


def test_training_program_is_non_degree():
    body = (
        "办班性质：非学历教育。报名条件：本科学历并获得学士学位后满三年。"
        "学习完全部课程后，可获得相应专业的结业证书（盖培训专用章）。"
    )
    assert (
        classify_admission_level("招生简章 | 2026年信息管理与工程学院在职课程培训班", body)
        == "non_degree_program"
    )


def test_executive_program_is_non_degree():
    assert classify_admission_level("2026年高级研修班招生简章", "结业后颁发结业证书。") == (
        "non_degree_program"
    )


def test_part_time_master_is_not_non_degree():
    """“在职/非全日制”不能自动等于 non-degree（§六）：明确硕士学历教育即 master。"""
    body = "非全日制硕士研究生招生，参加全国硕士研究生招生考试，录取后修满学分授予硕士学位。"
    assert (
        classify_admission_level("上海财经大学2026年非全日制硕士研究生招生简章", body)
        == "master_admission"
    )


def test_doctoral_application_assessment():
    assert classify_admission_level("关于做好2026年博士研究生“申请考核”制招生工作的通知") == (
        "doctoral_admission"
    )


# ---------------- 边界与优先级 ----------------


def test_recommendation_including_direct_phd_is_not_doctoral():
    assert (
        classify_admission_level("金融学院2026年接收推荐免试研究生（含直博生）预推免报名通知")
        == "recommendation_admission"
    )


def test_adjustment_and_reexamination_levels():
    assert classify_admission_level("上海财经大学2025年MPAcc（非全日制）调剂通知") == "adjustment"
    assert classify_admission_level("2026年硕士研究生招生复试录取办法") == "reexamination"


def test_summer_camp_needs_admission_context():
    """普通学术夏令营不算推免招生；与推免/研究生选拔相关才算（§四）。"""
    assert (
        classify_admission_level("2026年暑期学术夏令营活动通知", "本次夏令营安排名家讲座。") == ""
    )
    assert (
        classify_admission_level(
            "2026年优秀大学生夏令营通知", "夏令营优秀营员可获得推免生候选人资格。"
        )
        == "recommendation_admission"
    )


def test_weak_signals_give_other_admission():
    assert classify_admission_level(
        "关于启动2026年项目报名工作的通知", "欢迎广大同学踊跃报名。"
    ) == ("other_admission")


def test_non_admission_returns_empty():
    assert classify_admission_level("上海财经大学学生宿舍管理办法", "第一条 为加强宿舍管理。") == ""


def test_undergraduate_admission():
    body = "2026年本科招生计划面向全国31个省（区、市），按照高考成绩录取。"
    assert classify_admission_level("权威发布丨2026年本科招生亮点", body) == (
        "undergraduate_admission"
    )


# ---------------- topic 统计口径 ----------------


def test_classify_topic_degree_aware():
    assert classify_topic("上海财经大学2026年MPAcc（非全日制）招生简章") == "硕士招生"
    assert (
        classify_topic(
            "招生简章 | 2026年信管学院在职课程培训班",
            "办班性质：非学历教育，结业颁发结业证书。",
        )
        == "非学历项目"
    )
    assert classify_topic("财税投资学院2026年接收推荐免试研究生预报名通知") == "推免/预推免"


# ---------------- pipeline 落盘 ----------------


def test_pipeline_writes_admission_level(tmp_path):
    art = CrawledArticle(
        requested_url="https://mp.weixin.qq.com/s/x",
        final_url="https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1",
        title="招生简章 | 2026年信管学院在职课程培训班",
        publish_date="2026-06-23",
        publisher="上海财经大学信息管理与工程学院",
        html="",
        body_text=(
            "办班性质：非学历教育。报名条件：本科学历并获得学士学位后满三年。"
            "学习完全部课程后，可获得相应专业的结业证书（盖培训专用章）。"
            "学制1.5年，可选面授班或线上班。"
        ),
        attachments=[],
        status="ok",
        errors=[],
        document_kind_hint="annual_notice",
    )
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "corpus" / "manifest.jsonl"
    stats = ingest_crawled_articles(
        [art],
        category="学工事务",
        corpus_dir=corpus,
        manifest_path=manifest,
        relations_path=default_relations_path(manifest),
        source_type="official_wechat",
        source_section="上财信息",
        scope_unit="本研学生",
    )
    assert stats.count("new") == 1
    meta = next(iter(load_manifest(manifest).values()))
    assert meta.admission_level == "non_degree_program"
    # 非学历项目不隔离：仍进入 main QA（§十一）
    assert meta.quality_status == "accepted"
    assert meta.retention_status == "active"


def test_institute_name_with_xinwen_not_classified_as_news():
    """单位/专业名中的“新闻与”（新闻与社会高等研究院/新闻与传播硕士）不触发 news 隔离。"""
    from sufe_qa.ingest.classification import classify_document_kind

    kind = classify_document_kind(
        "上海财经大学新闻与社会高等研究院2027年接收优秀应届本科毕业生免试攻读研究生预报名的通知",
        "本次推免预报名面向2027届本科毕业生，申请材料通过系统提交。",
    )
    assert kind != "news"
    assert (
        classify_document_kind(
            "新闻与传播硕士专业学位2027年推免预报名通知", "报名截止时间为8月20日。"
        )
        != "news"
    )
    # 真正的新闻自称仍隔离
    assert (
        classify_document_kind("学院新闻｜我院召开年度总结大会", "我院于近日召开会议。") == "news"
    )
