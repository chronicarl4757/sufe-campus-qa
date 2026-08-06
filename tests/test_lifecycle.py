from __future__ import annotations

from datetime import date

from sufe_qa.ingest.lifecycle import (
    LifecycleCandidate,
    resolve_lifecycle,
    series_key_for,
    temporal_class_for,
)


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
    assert temporal_class_for("annual_notice", "上海财经大学2025年硕士研究生复试通知") == "annual"
    assert (
        temporal_class_for("public_list", "2025-2026学年第一学期研究生课程调停课情况公示")
        == "recurring_public"
    )
    assert temporal_class_for("promotion", "2025年研究生招生宣讲会") == "ephemeral"


def _candidate(doc_id: str, title: str, kind: str, publish_date: str) -> LifecycleCandidate:
    return LifecycleCandidate(
        doc_id=doc_id,
        title=title,
        publisher="上海财经大学研究生院",
        scope_unit="研究生",
        document_kind=kind,
        publish_date=publish_date,
    )


def test_retention_keeps_enduring_policy_regardless_of_age():
    decisions = resolve_lifecycle(
        [_candidate("policy", "上海财经大学研究生学籍管理规定", "policy", "2013-01-10")],
        time_policy="all_history",
        evaluated_at=date(2026, 8, 6),
    )
    assert decisions["policy"].retention_status == "active"
    assert decisions["policy"].retention_reason == "all_history"


def test_enduring_policy_is_not_archived_by_annual_section_window():
    decisions = resolve_lifecycle(
        [_candidate("policy", "上海财经大学研究生学籍管理规定", "policy", "2013-01-10")],
        time_policy="recent_5_school_years",
        evaluated_at=date(2026, 8, 6),
    )
    assert decisions["policy"].retention_status == "active"
    assert decisions["policy"].retention_reason == "enduring_document"


def test_annual_window_archives_old_and_selects_one_active_series_version():
    records = [
        _candidate(
            "old", "上海财经大学2019年硕士研究生复试录取办法", "annual_notice", "2019-03-01"
        ),
        _candidate(
            "prior", "上海财经大学2024年硕士研究生复试录取办法", "annual_notice", "2024-03-01"
        ),
        _candidate(
            "latest", "上海财经大学2025年硕士研究生复试录取办法", "annual_notice", "2025-03-01"
        ),
    ]
    decisions = resolve_lifecycle(
        records,
        time_policy="recent_5_school_years",
        evaluated_at=date(2026, 8, 6),
    )
    assert decisions["old"].retention_status == "archived"
    assert decisions["prior"].retention_status == "historical"
    assert decisions["latest"].retention_status == "active"
    assert decisions["latest"].canonical_doc_id == "latest"
    assert decisions["prior"].canonical_doc_id == "latest"


def test_public_and_operational_windows_are_distinct():
    public = resolve_lifecycle(
        [
            _candidate("old", "2022年研究生拟录取名单公示", "public_list", "2022-05-01"),
            _candidate("new", "2025年研究生拟录取名单公示", "public_list", "2025-05-01"),
        ],
        time_policy="recent_2_school_years",
        evaluated_at=date(2026, 8, 6),
    )
    assert public["old"].retention_status == "archived"
    assert public["new"].retention_status == "active"

    operational = resolve_lifecycle(
        [
            _candidate(
                "old-term",
                "2024-2025学年第一学期1-4周研究生课程调停课情况公示",
                "public_list",
                "2024-10-01",
            ),
            _candidate(
                "current-term",
                "2025-2026学年第一学期1-4周研究生课程调停课情况公示",
                "public_list",
                "2025-10-01",
            ),
        ],
        time_policy="current_school_year",
        evaluated_at=date(2026, 8, 6),
    )
    assert operational["old-term"].retention_status == "archived"
    assert operational["current-term"].retention_status == "active"


def test_time_bounded_policy_without_publish_date_is_safely_archived():
    decisions = resolve_lifecycle(
        [_candidate("unknown", "硕士研究生复试通知", "annual_notice", "unknown")],
        time_policy="recent_5_school_years",
        evaluated_at=date(2026, 8, 6),
    )
    assert decisions["unknown"].retention_status == "archived"
    assert decisions["unknown"].retention_reason == "missing_publish_date_for_time_policy"
