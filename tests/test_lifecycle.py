from __future__ import annotations

from sufe_qa.ingest.lifecycle import series_key_for, temporal_class_for


def test_yearly_editions_share_series_key_without_collapsing_scope_unit():
    publisher = "上海财经大学研究生院"
    first = series_key_for(
        "上海财经大学2024年硕士研究生招生考试复试录取办法",
        publisher=publisher,
        scope_unit="研究生",
    )
    second = series_key_for(
        "上海财经大学2025年硕士研究生招生考试复试录取办法",
        publisher=publisher,
        scope_unit="研究生",
    )
    college = series_key_for(
        "上海财经大学会计学院2025年硕士研究生招生考试复试录取办法",
        publisher=publisher,
        scope_unit="研究生",
    )
    assert first == second
    assert first != college


def test_series_key_normalizes_school_year_batch_and_week_ranges():
    first = series_key_for(
        "2024-2025学年第一学期1-4周研究生课程调停课情况公示",
        publisher="上海财经大学研究生院",
        scope_unit="研究生",
    )
    second = series_key_for(
        "2025-2026学年第一学期5-8周研究生课程调停课情况公示",
        publisher="上海财经大学研究生院",
        scope_unit="研究生",
    )
    assert first == second


def test_temporal_class_is_independent_from_document_kind_position():
    assert temporal_class_for("policy", "上海财经大学研究生学籍管理规定") == "enduring"
    assert (
        temporal_class_for("annual_notice", "上海财经大学2025年硕士研究生复试通知")
        == "annual"
    )
    assert (
        temporal_class_for(
            "public_list", "2025-2026学年第一学期研究生课程调停课情况公示"
        )
        == "recurring_public"
    )
    assert temporal_class_for("promotion", "2025年研究生招生宣讲会") == "ephemeral"

