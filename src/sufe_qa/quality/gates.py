"""清理后语料、collection 与固定题库的可重复质量门。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import chromadb

from sufe_qa.config import Settings
from sufe_qa.indexing.collections import (
    HISTORICAL_COLLECTION,
    HISTORICAL_KINDS,
    MAIN_QA_COLLECTION,
    MAIN_QA_KINDS,
    PUBLIC_LIST_COLLECTION,
    PUBLIC_LIST_KINDS,
    collection_name_for,
)
from sufe_qa.schema import load_manifest, load_relations, sha256_text

_ATTACHMENT_REFERENCES = ("详见附件", "见附件", "点击下载", "申请表见附件", "办法见附件")
_CORE_ANSWER_SCENES = frozenset(
    {"本科教务", "研究生培养与学位", "奖助学金", "就业手续", "信息化与校园卡"}
)


def _file_fingerprint(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes() if path.is_file() else b"").hexdigest()


def _index_fingerprints(settings: Settings) -> dict[str, str]:
    path = settings.chroma_dir / "index_metadata.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        data = {}
    return {
        "manifest_fingerprint": str(data.get("manifest_fingerprint", "missing")),
        "index_fingerprint": str(data.get("index_fingerprint", "missing")),
    }


def _collection_stats(settings: Settings) -> dict[str, dict]:
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    rules = {
        MAIN_QA_COLLECTION: (MAIN_QA_KINDS, "active"),
        PUBLIC_LIST_COLLECTION: (PUBLIC_LIST_KINDS, "active"),
        HISTORICAL_COLLECTION: (HISTORICAL_KINDS, "historical"),
    }
    output: dict[str, dict] = {}
    for key, (allowed_kinds, required_retention) in rules.items():
        name = collection_name_for(settings, key)
        try:
            collection = client.get_collection(name)
        except ValueError:
            output[key] = {
                "name": name,
                "chunk_count": 0,
                "document_count": 0,
                "invalid_documents": ["missing_collection"],
            }
            continue
        metadatas = collection.get(include=["metadatas"]).get("metadatas") or []
        doc_ids = {str(meta.get("doc_id", "")) for meta in metadatas if meta}
        invalid = sorted(
            {
                str(meta.get("doc_id", ""))
                for meta in metadatas
                if meta
                and (
                    str(meta.get("document_kind", "")) not in allowed_kinds
                    or str(meta.get("retention_status", "")) != required_retention
                )
            }
        )
        output[key] = {
            "name": name,
            "chunk_count": collection.count(),
            "document_count": len(doc_ids),
            "invalid_documents": invalid,
        }
    return output


def _coverage_stats(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {
            "question_bank_version": "missing",
            "question_bank_hash": "missing",
            "index_fingerprint": "missing",
            "total": 0,
            "answerable": 0,
            "partially_answerable": 0,
            "not_answerable": 0,
            "authoritative_hits": 0,
            "wrong_department_hits": 0,
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("question_results") or []
    counts = Counter(str(row.get("status", "not_answerable")) for row in results)
    wrong_department = sum(
        bool(row.get("retrieved_doc_ids")) and not bool(row.get("matched_domains"))
        for row in results
    )
    return {
        "question_bank_version": data.get("question_bank_version", "unknown"),
        "question_bank_hash": data.get("question_bank_hash", "unknown"),
        "index_fingerprint": data.get("index_fingerprint", "unknown"),
        "total": len(results),
        "answerable": counts["answerable"],
        "partially_answerable": counts["partially_answerable"],
        "not_answerable": counts["not_answerable"],
        "authoritative_hits": counts["answerable"] + counts["partially_answerable"],
        "wrong_department_hits": wrong_department,
    }


def _real_answer_stats(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {
            "available": False,
            "question_bank_version": "missing",
            "question_bank_hash": "missing",
            "index_fingerprint": "missing",
            "total": 0,
            "unique": 0,
            "answered": 0,
            "refused": 0,
            "citation_issues": 0,
            "errors": 0,
            "authoritative_answered": 0,
            "wrong_department_answered": 0,
            "wrong_department_ids": [],
            "scene_stats": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results") or []
    counts = Counter(str(row.get("status", "error")) for row in results)
    answered_rows = [row for row in results if row.get("status") == "answered"]
    wrong_department_ids = sorted(
        str(row.get("id", "")) for row in answered_rows if not bool(row.get("domain_match"))
    )
    by_scene: dict[str, Counter] = defaultdict(Counter)
    for row in results:
        scene = str(row.get("scene", "unknown"))
        by_scene[scene]["total"] += 1
        by_scene[scene][str(row.get("status", "error"))] += 1
    scene_stats = {
        scene: {
            "total": scene_counts["total"],
            "answered": scene_counts["answered"],
            "refused": scene_counts["refused"],
            "citation_issues": scene_counts["answered_with_citation_issue"],
            "errors": scene_counts["error"],
            "answer_rate": (
                scene_counts["answered"] / scene_counts["total"]
                if scene_counts["total"]
                else 0.0
            ),
        }
        for scene, scene_counts in sorted(by_scene.items())
    }
    return {
        "available": True,
        "question_bank_version": data.get("question_bank_version", "unknown"),
        "question_bank_hash": data.get("question_bank_hash", "unknown"),
        "index_fingerprint": data.get("index_fingerprint", "unknown"),
        "total": len(results),
        "unique": len({str(row.get("id", "")) for row in results}),
        "answered": counts["answered"],
        "refused": counts["refused"],
        "citation_issues": counts["answered_with_citation_issue"],
        "errors": counts["error"],
        "authoritative_answered": sum(bool(row.get("domain_match")) for row in answered_rows),
        "wrong_department_answered": len(wrong_department_ids),
        "wrong_department_ids": wrong_department_ids,
        "scene_stats": scene_stats,
    }


def _crawl_report_stats(settings: Settings) -> dict[str, dict]:
    reports_dir = settings.data_dir / "crawl_reports"
    latest: dict[str, tuple[str, dict]] = {}
    if not reports_dir.is_dir():
        return {}
    for path in reports_dir.glob("*.json"):
        if path.name in {"sufe_full_report.json", "sufe_missing_sources.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        host = str(data.get("host", ""))
        if not host:
            continue
        previous = latest.get(host)
        if previous is None or path.name > previous[0]:
            latest[host] = (path.name, data)
    fields = (
        "categories_found",
        "list_pages_fetched",
        "articles_found",
        "articles_downloaded",
        "attachments_found",
        "attachments_downloaded",
        "attachments_parsed",
        "incomplete_documents",
        "low_quality_documents",
        "final_indexed",
    )
    return {
        host: {
            "report_file": filename,
            **{field: int(data.get(field, 0) or 0) for field in fields},
        }
        for host, (filename, data) in sorted(latest.items())
    }


def verify_clean_pipeline(
    settings: Settings,
    *,
    coverage_path: Path | None = None,
    answer_report_path: Path | None = None,
) -> dict:
    manifest = load_manifest(settings.manifest_path)
    manifest_fingerprint = _file_fingerprint(settings.manifest_path)
    index_fingerprints = _index_fingerprints(settings)
    relations = load_relations(settings.manifest_path.with_name("relations.jsonl"))
    file_hash_errors: list[str] = []
    missing_files: list[str] = []
    materialized = []
    hashes: dict[str, list[str]] = defaultdict(list)
    for meta in manifest.values():
        if not meta.file_path:
            continue
        path = settings.corpus_dir / meta.file_path
        if not path.is_file():
            missing_files.append(meta.doc_id)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if sha256_text(text) != meta.content_hash:
            file_hash_errors.append(meta.doc_id)
        materialized.append(meta)
        hashes[meta.text_hash or meta.content_hash].append(meta.doc_id)

    retained = [
        meta
        for meta in manifest.values()
        if meta.retention_status in {"active", "historical"} and meta.quality_status == "accepted"
    ]
    materialized_ids = {meta.doc_id for meta in materialized}
    retained_materialized = sum(meta.doc_id in materialized_ids for meta in retained)
    isolated_materialized = sorted(
        meta.doc_id
        for meta in materialized
        if meta.document_kind in {"news", "event", "promotion", "incomplete"}
        or meta.retention_status == "archived"
    )
    active_annual: dict[str, list[str]] = defaultdict(list)
    for meta in manifest.values():
        if (
            meta.document_kind == "annual_notice"
            and meta.retention_status == "active"
            and meta.series_key
        ):
            active_annual[meta.series_key].append(meta.doc_id)
    duplicate_active_series = {key: ids for key, ids in active_annual.items() if len(ids) > 1}

    children_by_parent: dict[str, set[str]] = defaultdict(set)
    for relation in relations:
        if relation.relation == "attachment_of":
            children_by_parent[relation.parent_doc_id].add(relation.child_doc_id)
    attachment_reference_violations: list[str] = []
    for meta in materialized:
        if meta.document_type != "article":
            continue
        text = (settings.corpus_dir / meta.file_path).read_text(encoding="utf-8", errors="replace")
        if not any(marker in text for marker in _ATTACHMENT_REFERENCES):
            continue
        if not any(
            child in materialized_ids for child in children_by_parent.get(meta.doc_id, set())
        ):
            attachment_reference_violations.append(meta.doc_id)

    attachments = [meta for meta in manifest.values() if meta.document_type == "attachment"]
    parsed_attachments = [
        meta
        for meta in attachments
        if meta.parse_status == "ok" and meta.quality_status == "accepted" and meta.file_path
    ]
    duplicate_groups = [ids for ids in hashes.values() if len(ids) > 1]
    collections = _collection_stats(settings)
    coverage = _coverage_stats(coverage_path)
    real_answers = _real_answer_stats(answer_report_path)
    current_index_fingerprint = index_fingerprints["index_fingerprint"]
    index_matches_manifest = (
        index_fingerprints["manifest_fingerprint"] == manifest_fingerprint
    )
    coverage_matches_index = (
        coverage["total"] > 0
        and current_index_fingerprint != "missing"
        and coverage["index_fingerprint"] == current_index_fingerprint
    )
    real_answers_match_index = (
        not real_answers["available"]
        or (
            current_index_fingerprint != "missing"
            and real_answers["index_fingerprint"] == current_index_fingerprint
        )
    )
    real_answer_integrity = (
        not real_answers["available"]
        or (
            real_answers["total"] == 150
            and real_answers["unique"] == 150
            and real_answers["question_bank_hash"] == coverage["question_bank_hash"]
            and real_answers["index_fingerprint"] == coverage["index_fingerprint"]
        )
    )
    core_scene_answerability = not real_answers["available"] or all(
        scene in real_answers["scene_stats"]
        and real_answers["scene_stats"][scene]["answer_rate"] >= 0.9
        for scene in _CORE_ANSWER_SCENES
    )
    corpus = {
        "manifest_documents": len(manifest),
        "materialized_documents": len(materialized),
        "retained_documents": len(retained),
        "retained_materialized_documents": retained_materialized,
        "valid_body_ratio": (retained_materialized / len(retained) if retained else 1.0),
        "missing_files": missing_files,
        "file_hash_errors": file_hash_errors,
        "isolated_materialized": isolated_materialized,
        "duplicate_text_groups": duplicate_groups,
        "duplicate_document_rate": (
            sum(len(group) - 1 for group in duplicate_groups) / len(materialized)
            if materialized
            else 0.0
        ),
        "active_annual_series_duplicates": duplicate_active_series,
        "unknown_validity_main_documents": sum(
            meta.index_collection == "main_qa" and meta.validity_status == "unknown_validity"
            for meta in manifest.values()
        ),
    }
    attachment_stats = {
        "total": len(attachments),
        "parsed_and_materialized": len(parsed_attachments),
        "parse_success_rate": (len(parsed_attachments) / len(attachments) if attachments else 1.0),
        "article_reference_violations": attachment_reference_violations,
        "relation_count": sum(relation.relation == "attachment_of" for relation in relations),
    }
    gates = {
        "corpus_integrity": not missing_files and not file_hash_errors,
        "valid_body_ratio": corpus["valid_body_ratio"] >= 0.98,
        "isolated_content_removed": not isolated_materialized,
        "annual_series_canonical": not duplicate_active_series,
        "collection_isolation": all(not item["invalid_documents"] for item in collections.values()),
        "attachment_completeness": not attachment_reference_violations,
        "question_authoritative_hits": (
            real_answers["authoritative_answered"] >= 120
            if real_answers["available"]
            else coverage["authoritative_hits"] >= 120
        ),
        "question_answerability": (
            real_answers["answered"] >= 120
            if real_answers["available"]
            else coverage["answerable"] >= 120
        ),
        "real_answer_integrity": real_answer_integrity,
        "core_scene_answerability": core_scene_answerability,
        "wrong_department_hits": coverage["wrong_department_hits"] == 0,
        "index_matches_manifest": index_matches_manifest,
        "coverage_matches_index": coverage_matches_index,
        "real_answers_match_index": real_answers_match_index,
    }
    return {
        "schema_version": "1",
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprints": {
            "manifest": manifest_fingerprint,
            "indexed_manifest": index_fingerprints["manifest_fingerprint"],
            "index": current_index_fingerprint,
            "coverage_index": coverage["index_fingerprint"],
            "real_answers_index": real_answers["index_fingerprint"],
        },
        "corpus": corpus,
        "attachments": attachment_stats,
        "collections": collections,
        "crawl_sites": _crawl_report_stats(settings),
        "coverage": coverage,
        "real_answers": real_answers,
        "gates": gates,
        "passed": all(gates.values()),
    }


def write_gate_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
