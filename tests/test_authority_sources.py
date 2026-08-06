from __future__ import annotations

from sufe_qa.crawler.authority import adapter_for_source, load_authority_sources


def test_load_authority_sources_builds_sections_and_preserves_scope(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        """
sources:
  - id: jwc
    adapter: jwc
    homepage: https://jwc.sufe.edu.cn/
    publisher: 上海财经大学教务处
    source_type: official_department
    scope_unit: 本科生
    sections:
      - name: 办事流程
        list_url: https://jwc.sufe.edu.cn/5124/list.htm
        category: 学工事务
        scene: 本科教务
""",
        encoding="utf-8",
    )
    sources = load_authority_sources(path)
    assert len(sources) == 1
    assert sources[0].sections[0].metadata["scene"] == "本科教务"
    assert adapter_for_source(sources[0]).__class__.__name__ == "JwcAdapter"


def test_authoritative_source_file_contains_vertical_slice_sites():
    sources = {source.source_id: source for source in load_authority_sources("data/sources/sufe_authoritative.yaml")}
    assert {"jwc", "xsc", "gs"} <= sources.keys()
    assert sources["jwc"].adapter_name == "jwc"
    assert sources["xsc"].adapter_name == "wp3"
    assert sources["gs"].adapter_name == "graduate_school"
    assert any(section.name == "办事流程" for section in sources["jwc"].sections)
    assert any(section.name == "部门制度" for section in sources["xsc"].sections)
    assert any(section.name == "培养管理制度" for section in sources["gs"].sections)
    policies = {
        source_id: {section.name: section.time_policy for section in source.sections}
        for source_id, source in sources.items()
    }
    assert policies["jwc"]["办事流程"] == "all_history"
    assert policies["xsc"]["通知公告"] == "recent_5_school_years"
    assert policies["gs"]["招生通知"] == "recent_5_school_years"
    assert policies["gs"]["招生公示"] == "recent_2_school_years"
    assert policies["gs"]["培养管理制度"] == "all_history"
    assert policies["gs"]["答辩公告"] == "current_school_year"
