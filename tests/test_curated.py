"""data/curated/ 人工精编指南入库测试：front matter 解析、子目录分类映射、幂等增量。

Run: python -m pytest tests/test_curated.py -v
"""

from __future__ import annotations

from sufe_qa.ingest.curated import _split_front_matter, ingest_curated
from sufe_qa.schema import doc_id_from, load_manifest

GUIDE = """---
title: 如何连上校园网
topic_key: room.connect.connect_to_campus_network
document_kind: curated_guide
applicable_student_type: freshman
scope_unit: 上海财经大学
validity_status: current
verified_at: 2026-08-01
editor: chronicarl
source_doc_ids:
  -
---

# 一句话结论

上财微门户app -> 应用 -> 服务保障 -> 学生网络自助服务。

# TIPS

- 有线网络与无线网络均可申请
"""


def _write(curated_dir, rel: str, text: str):
    p = curated_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_split_front_matter():
    fm, body = _split_front_matter(GUIDE)
    assert fm["title"] == "如何连上校园网"
    assert fm["document_kind"] == "curated_guide"
    assert "topic_key" not in body
    assert body.startswith("# 一句话结论")


def test_split_front_matter_absent_or_broken():
    fm, body = _split_front_matter("# 普通文档\n\n正文。")
    assert fm == {} and body.startswith("# 普通文档")
    fm2, body2 = _split_front_matter("---\n: 非法: yaml: [{\n---\n正文")
    assert fm2 == {} and "正文" in body2


def test_ingest_maps_front_matter_and_subdir(tmp_path):
    curated = tmp_path / "curated"
    _write(curated, "freshman_knowhow/如何连上校园网.md", GUIDE)
    _write(curated, "students_affairs/办事指南.md", "---\ntitle: 办事指南\n---\n\n正文内容。\n")
    _write(curated, "unknown_dir/某文档.md", "无头文档正文，标题取文件名。\n")
    _write(curated, "template.md", "")  # 空模板跳过

    report = ingest_curated(curated, tmp_path / "corpus", tmp_path / "corpus" / "manifest.jsonl")
    assert (report.added, report.updated, report.unchanged) == (3, 0, 0)
    assert report.skipped == ["template.md"]

    manifest = load_manifest(tmp_path / "corpus" / "manifest.jsonl")
    d1 = manifest[doc_id_from("curated/freshman_knowhow/如何连上校园网.md")]
    assert d1.title == "如何连上校园网"
    assert d1.category == "校园生活"
    assert d1.publish_date == "2026-08-01"  # yaml date 对象转字符串
    assert d1.publisher == "上海财经大学"
    assert d1.document_type == "article"
    assert d1.document_kind == "service_guide"
    assert d1.source_type == "manual_upload"
    assert d1.source_section == "人工精编指南"
    assert d1.topic_key == "room.connect.connect_to_campus_network"
    assert d1.applicable_student_type == "freshman"
    assert d1.scope_unit == "上海财经大学"
    assert d1.validity_status == "current"
    assert d1.validity_confidence == 1.0
    assert d1.index_collection == "main_qa"
    assert d1.retention_status == "active"
    assert d1.text_hash
    assert d1.quality_status == "accepted"

    d2 = manifest[doc_id_from("curated/students_affairs/办事指南.md")]
    assert d2.category == "学工事务"
    d3 = manifest[doc_id_from("curated/unknown_dir/某文档.md")]
    assert d3.category == "其他"
    assert d3.title == "某文档"  # 无 front matter 时取文件名
    assert d3.publish_date == "unknown"

    # front matter 不进入 corpus 正文
    text1 = (tmp_path / "corpus" / d1.file_path).read_text(encoding="utf-8")
    assert "topic_key" not in text1 and "verified_at" not in text1
    assert text1.startswith("# 如何连上校园网")


def test_ingest_incremental_update_and_noop(tmp_path):
    curated = tmp_path / "curated"
    p = _write(curated, "campus_services/校园卡.md", "---\ntitle: 校园卡\n---\n\n第一版正文。\n")
    manifest_path = tmp_path / "corpus" / "manifest.jsonl"
    r1 = ingest_curated(curated, tmp_path / "corpus", manifest_path)
    assert r1.added == 1

    r2 = ingest_curated(curated, tmp_path / "corpus", manifest_path)
    assert (r2.added, r2.updated, r2.unchanged) == (0, 0, 1)  # 幂等 no-op

    p.write_text("---\ntitle: 校园卡\n---\n\n第二版正文，内容已更新。\n", encoding="utf-8")
    r3 = ingest_curated(curated, tmp_path / "corpus", manifest_path)
    assert r3.updated == 1
    d = load_manifest(manifest_path)[doc_id_from("curated/campus_services/校园卡.md")]
    assert "第二版" in (tmp_path / "corpus" / d.file_path).read_text(encoding="utf-8")
    # 更新沿用旧路径，不产生第二个 corpus 文件
    assert len(list((tmp_path / "corpus" / "校园生活").glob("*.md"))) == 1


def test_ingest_missing_dir_is_noop(tmp_path):
    report = ingest_curated(tmp_path / "nope", tmp_path / "corpus", tmp_path / "m.jsonl")
    assert report.added == 0
