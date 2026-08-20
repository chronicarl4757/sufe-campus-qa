"""unit registry 与归一化测试（§三十八：alias normalization / unit matching / unknown preservation）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from sufe_qa.coverage.units import (
    Unit,
    attribute_document,
    load_units,
    normalize_unit_name,
)

REGISTRY = Path(__file__).parent.parent / "data" / "coverage" / "sufe_units.yaml"


@pytest.fixture(scope="module")
def units():
    return load_units(REGISTRY)


def _mini_units():
    return [
        Unit("sime", "信息管理与工程学院", ("上财信息", "信管学院"), "college", True, True, True),
        Unit(
            "scai",
            "计算机与人工智能学院",
            ("上财计算机与人工智能学院", "计算机学院", "SCAI"),
            "college",
            True,
            True,
            True,
        ),
        Unit("ssds", "统计与数据科学学院", ("统计与管理学院",), "college", True, True, True),
        Unit("djh", "滴水湖高级金融学院", ("滴水湖高金",), "academy", False, True, True),
    ]


def test_registry_loads_all_units(units):
    assert len(units) >= 30
    by_id = {u.unit_id for u in units}
    for required in (
        "marxism",
        "accounting",
        "finance",
        "scai",
        "aiclg",
        "kuangshi",
        "siif",
        "djh_thinktank",
        "zj",
    ):
        assert required in by_id


def test_alias_normalization(units):
    assert normalize_unit_name("上财信息", units).canonical_name == "信息管理与工程学院"
    assert normalize_unit_name("信管学院", units).canonical_name == "信息管理与工程学院"
    assert normalize_unit_name("SCAI", units).canonical_name == "计算机与人工智能学院"
    assert normalize_unit_name("上财会计学院", units).canonical_name == "会计学院"
    assert normalize_unit_name("统计与管理学院", units).canonical_name == "统计与数据科学学院"
    assert normalize_unit_name("国际工商管理学院", units).canonical_name == "商学院"
    assert normalize_unit_name("公共经济与管理学院", units).canonical_name == "财税投资学院"


def test_longest_match_wins():
    units = _mini_units()
    # “上海财经大学计算机与人工智能学院”比“计算机学院”更长更具体
    assert (
        normalize_unit_name(
            "上海财经大学计算机与人工智能学院2027年接收推免生预报名的通知", units
        ).unit_id
        == "scai"
    )


def test_unknown_unit_preserved(units):
    assert normalize_unit_name("复旦大学", units) is None
    assert (
        normalize_unit_name("上海财经大学浙江学院教务处", units).canonical_name
        == "上海财经大学浙江学院"
    )
    assert normalize_unit_name("", units) is None
    assert normalize_unit_name("某不知名研究院", units) is None


def test_attribute_document_prefers_publisher(units):
    unit, via = attribute_document(
        "2026年硕士研究生招生考试复试办法", "上海财经大学高级会计审计学院", units
    )
    assert via == "publisher"
    assert unit.canonical_name == "高级会计审计学院"


def test_attribute_document_falls_back_to_title(units):
    unit, via = attribute_document(
        "上海财经大学金融学院2026年接收推荐免试研究生预推免报名通知",
        "上海财经大学研究生院招生办公室",
        units,
    )
    assert via == "title"
    assert unit.canonical_name == "金融学院"


def test_attribute_document_unknown(units):
    unit, via = attribute_document("关于寒假放假的通知", "上海财经大学后勤实业发展中心", units)
    assert unit is None and via == "none"
