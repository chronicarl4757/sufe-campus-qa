from __future__ import annotations

import json

from sufe_qa.config import Settings
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
from sufe_qa.quality.gates import verify_clean_pipeline, write_gate_report
from sufe_qa.schema import DocMeta, append_manifest, sha256_text


def _settings(tmp_path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        data_dir=data,
        corpus_dir=data / "corpus",
        inbox_dir=data / "inbox",
        chroma_dir=data / "chroma",
        manifest_path=data / "corpus" / "manifest.jsonl",
    )


def _add(settings, doc_id, title, kind, status, text=""):
    rel = ""
    content_hash = ""
    if text:
        rel = f"学工事务/{doc_id}.md"
        path = settings.corpus_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        content_hash = sha256_text(text)
    append_manifest(
        settings.manifest_path,
        [
            DocMeta(
                doc_id=doc_id,
                title=title,
                source_url=f"https://jwc.sufe.edu.cn/{doc_id}",
                publisher="上海财经大学教务处",
                publish_date="2025-01-01",
                category="学工事务",
                fetched_at="2026-08-01T00:00:00+00:00",
                content_hash=content_hash,
                file_path=rel,
                document_kind=kind,
                retention_status=status,
                retention_reason="test_fixture",
                index_collection={
                    "active": "main_qa",
                    "historical": "historical",
                    "archived": "none",
                }[status],
            )
        ],
    )


def test_quality_gates_check_files_collections_and_fixed_question_results(tmp_path):
    settings = _settings(tmp_path)
    _add(
        settings,
        "main",
        "缓考办理办法",
        "policy",
        "active",
        "# 缓考办理办法\n\n申请条件、材料和办理流程。\n",
    )
    _add(
        settings,
        "historical",
        "2024年缓考通知",
        "annual_notice",
        "historical",
        "# 2024年缓考通知\n\n2024年办理时间。\n",
    )
    _add(settings, "news", "学院新闻", "news", "archived")
    update_index(settings, FakeEmbedder())
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "question_bank_version": "test.v1",
                "question_bank_hash": "sha256:test",
                "question_results": [
                    {"id": "q1", "status": "answerable", "matched_domains": ["jwc.sufe.edu.cn"]},
                    {"id": "q2", "status": "not_answerable", "matched_domains": []},
                ],
                "scene_stats": {},
            }
        ),
        encoding="utf-8",
    )

    report = verify_clean_pipeline(settings, coverage_path=coverage)
    assert report["corpus"]["materialized_documents"] == 2
    assert report["corpus"]["file_hash_errors"] == []
    assert report["collections"]["main_qa"]["document_count"] == 1
    assert report["collections"]["historical"]["document_count"] == 1
    assert report["collections"]["main_qa"]["invalid_documents"] == []
    assert report["coverage"]["answerable"] == 1
    assert report["coverage"]["not_answerable"] == 1
    assert report["gates"]["corpus_integrity"] is True
    assert report["gates"]["question_answerability"] is False
    assert report["passed"] is False

    output = tmp_path / "full-report.json"
    write_gate_report(report, output)
    assert output.is_file()


def test_quality_gates_use_real_answers_for_answerability_when_supplied(tmp_path):
    settings = _settings(tmp_path)
    _add(
        settings,
        "main",
        "缓考办理办法",
        "policy",
        "active",
        "# 缓考办理办法\n\n申请条件、材料和办理流程。\n",
    )
    update_index(settings, FakeEmbedder())
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "question_bank_version": "test.v1",
                "question_bank_hash": "sha256:test",
                "index_fingerprint": "sha256:index",
                "question_results": [
                    {"id": f"q{i}", "status": "partially_answerable", "matched_domains": []}
                    for i in range(150)
                ],
            }
        ),
        encoding="utf-8",
    )
    answers = tmp_path / "answers.json"
    answer_rows = []
    scenes = ["本科教务", "研究生培养与学位", "奖助学金", "就业手续", "信息化与校园卡"]
    for i in range(150):
        answer_rows.append(
            {
                "id": f"q{i}",
                "scene": scenes[i % len(scenes)],
                "status": "answered" if i < 140 else "refused",
                "domain_match": i < 130,
            }
        )
    answers.write_text(
        json.dumps(
            {
                "question_bank_version": "test.v1",
                "question_bank_hash": "sha256:test",
                "index_fingerprint": "sha256:index",
                "total": 150,
                "results": answer_rows,
            }
        ),
        encoding="utf-8",
    )

    report = verify_clean_pipeline(
        settings,
        coverage_path=coverage,
        answer_report_path=answers,
    )

    assert report["real_answers"]["answered"] == 140
    assert report["real_answers"]["authoritative_answered"] == 130
    assert report["real_answers"]["refused"] == 10
    assert report["gates"]["question_answerability"] is True
    assert report["gates"]["question_authoritative_hits"] is True
    assert report["gates"]["core_scene_answerability"] is True
    assert report["gates"]["coverage_matches_index"] is False
    assert report["gates"]["real_answers_match_index"] is False


def test_quality_gates_reject_reports_from_an_old_index(tmp_path):
    settings = _settings(tmp_path)
    _add(
        settings,
        "main",
        "缓考办理办法",
        "policy",
        "active",
        "# 缓考办理办法\n\n申请条件、材料和办理流程。\n",
    )
    update_index(settings, FakeEmbedder())
    metadata = json.loads((settings.chroma_dir / "index_metadata.json").read_text(encoding="utf-8"))
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "question_bank_version": "test.v1",
                "question_bank_hash": "sha256:test",
                "index_fingerprint": "sha256:old",
                "question_results": [],
            }
        ),
        encoding="utf-8",
    )

    report = verify_clean_pipeline(settings, coverage_path=coverage)

    assert report["fingerprints"]["manifest"] == metadata["manifest_fingerprint"]
    assert report["gates"]["index_matches_manifest"] is True
    assert report["gates"]["coverage_matches_index"] is False
