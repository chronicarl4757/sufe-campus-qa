"""受保护的知识库管理 API：看清、隔离、恢复、体检与发布。"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import urlsplit

import yaml
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from sufe_qa.config import CATEGORIES, PROJECT_ROOT, Settings
from sufe_qa.crawler.authority import load_authority_sources
from sufe_qa.generate.answer import (
    CitationGateError,
    answer_question,
    gated_citation_stream,
    validate_citations,
)
from sufe_qa.indexing.indexer import BgeEmbedder, update_index
from sufe_qa.ingest.curated import ingest_curated
from sufe_qa.ingest.inbox import ingest_inbox
from sufe_qa.quality.audit import audit_corpus, write_quality_audit
from sufe_qa.retrieve.retriever import HybridRetriever
from sufe_qa.schema import (
    DocMeta,
    DocRelation,
    append_manifest,
    append_relations,
    default_relations_path,
    doc_id_from,
    load_manifest,
    sha256_text,
)
from sufe_qa.wechat.article import WechatArticleFetcher
from sufe_qa.wechat.discovery import SeedURLDiscovery, is_wechat_article_url
from sufe_qa.wechat.filters import load_wechat_accounts
from sufe_qa.wechat.runner import crawl_wechat

logger = logging.getLogger(__name__)

# ponytail: 进程内单写锁适合当前单 worker 部署；多 worker 时改为数据库事务/任务队列。
_MUTATION_LOCK = threading.Lock()


class DocumentActionReq(BaseModel):
    action: Literal["quarantine", "restore", "rollback"]
    reason: str = Field(min_length=2, max_length=300)
    version_hash: str = Field(default="", max_length=80)


class DebugQuestionReq(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class CuratedAnswerReq(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    answer: str = Field(min_length=10, max_length=8000)
    category: str = Field(min_length=1, max_length=20)
    editor: str = Field(min_length=2, max_length=80)
    source_doc_ids: list[str] = Field(min_length=1, max_length=12)


class WechatImportReq(BaseModel):
    url: str = Field(min_length=20, max_length=2000)


def _fingerprint(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes() if path.is_file() else b"").hexdigest()


def _manifest_rows(path: Path) -> list[DocMeta]:
    rows: list[DocMeta] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(DocMeta(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            logger.warning("管理员时间线跳过 manifest 坏行")
    return rows


def _index_metadata(settings: Settings) -> dict:
    path = settings.chroma_dir / "index_metadata.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _quality_snapshot(settings: Settings, manifest_fingerprint: str) -> dict:
    path = settings.data_dir / "quality" / "sufe_data_quality_current.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"available": False, "fresh": False, "path": str(path)}
    if not isinstance(report, dict):
        return {"available": False, "fresh": False, "path": str(path)}
    missing_attachments = sum(
        "missing_required_attachment" in (item.get("reasons") or [])
        for item in report.get("decisions") or []
        if isinstance(item, dict)
    )
    return {
        "available": True,
        "fresh": report.get("manifest_fingerprint") == manifest_fingerprint,
        "path": str(path),
        "evaluated_at": report.get("evaluated_at"),
        "collection_contamination_count": int(report.get("collection_contamination_count", 0) or 0),
        "duplicate_active_annual_series_count": int(
            report.get("duplicate_active_annual_series_count", 0) or 0
        ),
        "date_conflict_count": int(report.get("date_conflict_count", 0) or 0),
        "missing_required_attachment_count": missing_attachments,
        "unknown_type_count": int(report.get("unknown_type_count", 0) or 0),
        "archived_without_raw_count": int(report.get("archived_without_raw_count", 0) or 0),
    }


def _gate_snapshot(settings: Settings, manifest_fingerprint: str) -> dict:
    path = settings.data_dir / "crawl_reports" / "sufe_full_report_current.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"available": False, "fresh": False, "failed": []}
    fingerprints = report.get("fingerprints") or {}
    gates = report.get("gates") or {}
    return {
        "available": True,
        "fresh": fingerprints.get("manifest") == manifest_fingerprint,
        "passed": bool(report.get("passed")),
        "evaluated_at": report.get("evaluated_at"),
        "failed": [name for name, passed in gates.items() if not passed],
    }


def _safe_body_path(settings: Settings, meta: DocMeta) -> Path | None:
    if not meta.file_path:
        return None
    root = settings.corpus_dir.resolve()
    path = (root / meta.file_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def _traceable_source_url(value: str) -> bool:
    parsed = urlsplit((value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _version_body_path(settings: Settings, meta: DocMeta) -> Path | None:
    path = _safe_body_path(settings, meta)
    if path is None or not meta.content_hash:
        return None
    body = path.read_text(encoding="utf-8", errors="replace")
    return path if sha256_text(body) == meta.content_hash else None


def _doc_payload(settings: Settings, meta: DocMeta) -> dict:
    path = _safe_body_path(settings, meta)
    return {
        "doc_id": meta.doc_id,
        "title": meta.title,
        "category": meta.category,
        "publisher": meta.publisher,
        "source_url": meta.source_url,
        "publish_date": meta.publish_date,
        "fetched_at": meta.fetched_at,
        "quality_status": meta.quality_status,
        "document_kind": meta.document_kind,
        "document_type": meta.document_type,
        "retention_status": meta.retention_status,
        "validity_status": meta.validity_status,
        "index_collection": meta.index_collection,
        "source_type": meta.source_type,
        "source_section": meta.source_section,
        "file_path": meta.file_path,
        "content_hash": meta.content_hash,
        "has_body": path is not None,
        "body_bytes": path.stat().st_size if path else 0,
        "is_searchable": bool(
            path
            and meta.quality_status == "accepted"
            and meta.retention_status in {"active", "historical"}
            and meta.index_collection != "none"
        ),
    }


def _timeline(documents: list[DocMeta]) -> tuple[list[dict], list[dict]]:
    daily: dict[str, Counter] = defaultdict(Counter)
    for meta in documents:
        day = meta.fetched_at[:10] if len(meta.fetched_at) >= 10 else "unknown"
        daily[day]["documents"] += 1
        daily[day]["searchable"] += int(
            meta.quality_status == "accepted" and meta.index_collection != "none"
        )
        daily[day]["isolated"] += int(meta.quality_status != "accepted")
    days = [{"date": day, **counts} for day, counts in sorted(daily.items(), reverse=True)]
    recent = [
        {
            "doc_id": meta.doc_id,
            "title": meta.title,
            "category": meta.category,
            "publisher": meta.publisher,
            "fetched_at": meta.fetched_at,
            "quality_status": meta.quality_status,
            "document_kind": meta.document_kind,
        }
        for meta in sorted(documents, key=lambda item: item.fetched_at, reverse=True)[:80]
    ]
    return days, recent


def _append_admin_action(settings: Settings, *, meta: DocMeta, action: str, reason: str) -> None:
    path = settings.data_dir / "admin_actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "doc_id": meta.doc_id,
                    "title": meta.title,
                    "action": action,
                    "reason": reason,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def _recent_admin_actions(settings: Settings) -> list[dict]:
    path = settings.data_dir / "admin_actions.jsonl"
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-30:][::-1]


def _run_quality_audit(settings: Settings) -> dict:
    sources = load_authority_sources(PROJECT_ROOT / "data" / "sources" / "sufe_authoritative.yaml")
    policies = {
        (source.publisher, section.name): section.time_policy
        for source in sources
        for section in source.sections
    }
    trusted = {
        (source.publisher, section.name, section.metadata["document_kind"])
        for source in sources
        for section in source.sections
        if section.metadata.get("inline_article") == "true"
        and section.metadata.get("document_kind")
    }
    report = audit_corpus(
        settings.manifest_path,
        settings.corpus_dir,
        settings.data_dir / "raw",
        time_policies=policies,
        trusted_document_kinds=trusted,
    )
    write_quality_audit(
        report,
        settings.data_dir / "quality" / "sufe_data_quality_current.json",
        settings.data_dir / "quality" / "sufe_data_quality_current.md",
    )
    return _quality_snapshot(settings, report.manifest_fingerprint)


def create_admin_router(settings: Settings, runtime: dict) -> APIRouter:
    router = APIRouter()

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        if not settings.admin_token:
            raise HTTPException(status_code=503, detail="管理员入口尚未配置")
        scheme, _, value = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(value, settings.admin_token):
            raise HTTPException(
                status_code=401,
                detail="管理员凭据无效",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def no_store(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store"

    def ensure_not_publishing() -> None:
        if runtime.get("publishing"):
            raise HTTPException(status_code=409, detail="知识库正在发布，请稍后操作")

    def refresh_runtime_index() -> dict:
        embedder = runtime.get("embedder") or BgeEmbedder(settings.embedding_model)
        runtime["embedder"] = embedder
        report = update_index(settings, embedder)
        runtime["retriever"] = HybridRetriever(settings, embedder)
        return asdict(report)

    def current_retriever() -> HybridRetriever:
        retriever = runtime.get("retriever")
        if retriever is None:
            embedder = runtime.get("embedder") or BgeEmbedder(settings.embedding_model)
            runtime["embedder"] = embedder
            retriever = HybridRetriever(settings, embedder)
            runtime["retriever"] = retriever
        return retriever

    @router.get("/api/admin/session")
    def session(response: Response, _: None = Depends(require_admin)) -> dict:
        no_store(response)
        return {"ok": True}

    @router.get("/api/admin/overview")
    def overview(response: Response, _: None = Depends(require_admin)) -> dict:
        no_store(response)
        manifest = load_manifest(settings.manifest_path)
        documents = list(manifest.values())
        manifest_fingerprint = _fingerprint(settings.manifest_path)
        index = _index_metadata(settings)
        days, recent = _timeline(documents)
        categories = []
        for category in CATEGORIES:
            rows = [meta for meta in documents if meta.category == category]
            categories.append(
                {
                    "category": category,
                    "documents": len(rows),
                    "searchable": sum(
                        meta.quality_status == "accepted"
                        and meta.index_collection != "none"
                        and bool(meta.file_path)
                        for meta in rows
                    ),
                    "attention": sum(meta.quality_status != "accepted" for meta in rows),
                }
            )
        searchable = sum(_doc_payload(settings, meta)["is_searchable"] for meta in documents)
        return {
            "counts": {
                "documents": len(documents),
                "searchable": searchable,
                "attention": sum(meta.quality_status != "accepted" for meta in documents),
                "sources": len({meta.publisher for meta in documents if meta.publisher}),
            },
            "freshness": {
                "manifest_fingerprint": manifest_fingerprint,
                "index_fingerprint": index.get("index_fingerprint", "missing"),
                "index_matches_manifest": index.get("manifest_fingerprint") == manifest_fingerprint,
                "indexed_at": index.get("created_at"),
            },
            "quality": _quality_snapshot(settings, manifest_fingerprint),
            "gates": _gate_snapshot(settings, manifest_fingerprint),
            "categories": categories,
            "quality_statuses": dict(Counter(meta.quality_status for meta in documents)),
            "source_types": dict(Counter(meta.source_type for meta in documents)),
            "timeline": days,
            "recent_documents": recent,
            "recent_actions": _recent_admin_actions(settings),
        }

    @router.get("/api/admin/documents")
    def documents(
        response: Response,
        _: None = Depends(require_admin),
        q: str = Query(default="", max_length=200),
        category: str = "",
        quality_status: str = "",
        retention_status: str = "",
        source_type: str = "",
        fetched_day: str = "",
        limit: int = Query(default=80, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        no_store(response)
        rows = list(load_manifest(settings.manifest_path).values())
        needle = q.strip().casefold()
        if needle:
            rows = [
                meta
                for meta in rows
                if needle
                in " ".join(
                    (meta.doc_id, meta.title, meta.publisher, meta.source_url, meta.category)
                ).casefold()
            ]
        if category:
            rows = [meta for meta in rows if meta.category == category]
        if quality_status:
            rows = [meta for meta in rows if meta.quality_status == quality_status]
        if retention_status:
            rows = [meta for meta in rows if meta.retention_status == retention_status]
        if source_type:
            rows = [meta for meta in rows if meta.source_type == source_type]
        if fetched_day:
            rows = [meta for meta in rows if meta.fetched_at.startswith(fetched_day)]
        rows.sort(key=lambda meta: (meta.fetched_at, meta.publish_date, meta.title), reverse=True)
        total = len(rows)
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": [_doc_payload(settings, meta) for meta in rows[offset : offset + limit]],
        }

    @router.get("/api/admin/documents/{doc_id}")
    def document_detail(
        doc_id: str,
        response: Response,
        _: None = Depends(require_admin),
    ) -> dict:
        no_store(response)
        history = [meta for meta in _manifest_rows(settings.manifest_path) if meta.doc_id == doc_id]
        if not history:
            raise HTTPException(status_code=404, detail="文档不存在")
        current = history[-1]
        body_meta = current
        if not _version_body_path(settings, body_meta):
            body_meta = next(
                (meta for meta in reversed(history[:-1]) if _version_body_path(settings, meta)),
                current,
            )
        body_path = _version_body_path(settings, body_meta)
        body = body_path.read_text(encoding="utf-8", errors="replace") if body_path else ""
        limit = 200_000
        return {
            "document": {**asdict(current), **_doc_payload(settings, current)},
            "content": body[:limit],
            "content_truncated": len(body) > limit,
            "history": [
                {
                    "fetched_at": meta.fetched_at,
                    "quality_status": meta.quality_status,
                    "retention_status": meta.retention_status,
                    "index_collection": meta.index_collection,
                    "content_hash": meta.content_hash,
                    "version_available": _version_body_path(settings, meta) is not None,
                    "is_current": meta is current,
                }
                for meta in history[-20:][::-1]
            ],
        }

    @router.get("/api/admin/documents/{doc_id}/versions/{content_hash}")
    def document_version(
        doc_id: str,
        content_hash: str,
        response: Response,
        _: None = Depends(require_admin),
    ) -> dict:
        no_store(response)
        version = next(
            (
                meta
                for meta in reversed(_manifest_rows(settings.manifest_path))
                if meta.doc_id == doc_id and meta.content_hash == content_hash
            ),
            None,
        )
        if version is None:
            raise HTTPException(status_code=404, detail="文档版本不存在")
        path = _version_body_path(settings, version)
        if path is None:
            raise HTTPException(status_code=410, detail="该历史记录没有可恢复的正文快照")
        body = path.read_text(encoding="utf-8", errors="replace")
        limit = 200_000
        return {
            "content_hash": version.content_hash,
            "fetched_at": version.fetched_at,
            "content": body[:limit],
            "content_truncated": len(body) > limit,
        }

    @router.post("/api/admin/debug")
    def debug_question(
        req: DebugQuestionReq,
        response: Response,
        _: None = Depends(require_admin),
    ) -> dict:
        no_store(response)
        ensure_not_publishing()
        question = req.question.strip()
        retriever = current_retriever()
        answer = answer_question(question, settings, retriever, llm=runtime.get("llm"))
        hits = answer.hits
        if answer.refused:
            text = "".join(answer.stream)
            candidates = retriever.search_routed(question)
            citation = None
            error = ""
        else:
            candidates = hits
            try:
                text = "".join(gated_citation_stream(answer.stream, len(hits)))
                citation = asdict(validate_citations(text, len(hits)))
                error = ""
            except CitationGateError as exc:
                text = ""
                citation = {
                    "ok": False,
                    "has_citation": True,
                    "invalid_refs": exc.invalid_refs,
                }
                error = "生成结果引用越界，已被门禁撤回"
        cards, citation_map = answer.sources_and_map()
        return {
            "question": question,
            "answer": text,
            "refused": answer.refused,
            "error": error,
            "citation_check": citation,
            "citation_map": citation_map,
            "source_cards": [asdict(card) for card in cards],
            "hits": [
                {
                    "chunk_id": hit.chunk_id,
                    "doc_id": hit.doc_id,
                    "title": hit.title,
                    "publisher": hit.publisher,
                    "source_url": hit.source_url,
                    "publish_date": hit.publish_date,
                    "category": hit.category,
                    "document_kind": hit.document_kind,
                    "validity_status": hit.validity_status,
                    "vector_similarity": hit.vector_similarity,
                    "heading_path": hit.heading_path,
                    "excerpt": hit.text[:1200],
                }
                for hit in candidates
            ],
        }

    @router.post("/api/admin/answers")
    def save_curated_answer(
        req: CuratedAnswerReq,
        response: Response,
        _: None = Depends(require_admin),
    ) -> dict:
        no_store(response)
        if req.category not in CATEGORIES:
            raise HTTPException(status_code=422, detail="知识分类不合法")
        question = req.question.strip()
        answer_text = req.answer.strip()
        editor = req.editor.strip()
        source_ids = list(
            dict.fromkeys(value.strip() for value in req.source_doc_ids if value.strip())
        )
        if not source_ids:
            raise HTTPException(status_code=422, detail="至少选择一份官方依据")

        with _MUTATION_LOCK:
            ensure_not_publishing()
            manifest_fingerprint = _fingerprint(settings.manifest_path)
            if _index_metadata(settings).get("manifest_fingerprint") != manifest_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="馆藏还有未发布变更；请先体检并发布，再增量写入标准答案",
                )
            manifest = load_manifest(settings.manifest_path)
            sources = [manifest.get(doc_id) for doc_id in source_ids]
            if any(source is None for source in sources):
                raise HTTPException(status_code=422, detail="所选依据中有文档已不存在")
            usable_sources = [source for source in sources if source is not None]
            if any(
                source.quality_status != "accepted"
                or source.retention_status != "active"
                or source.index_collection == "none"
                or _safe_body_path(settings, source) is None
                or not _traceable_source_url(source.source_url)
                for source in usable_sources
            ):
                raise HTTPException(
                    status_code=422, detail="标准答案只能引用现行、已发布的可追溯资料"
                )

            digest = hashlib.sha256(" ".join(question.split()).casefold().encode()).hexdigest()[:16]
            relative = Path("admin_answers") / f"{digest}.md"
            curated_path = settings.data_dir / "curated" / relative
            curated_path.parent.mkdir(parents=True, exist_ok=True)
            front_matter = {
                "title": f"标准答复｜{question[:80]}",
                "category": req.category,
                "topic_key": f"curated.answer.{digest}",
                "document_kind": "faq",
                "scope_unit": usable_sources[0].scope_unit or usable_sources[0].publisher,
                "publisher": usable_sources[0].publisher,
                "validity_status": "current",
                "verified_at": datetime.now(timezone.utc).date().isoformat(),
                "editor": editor,
                "source_doc_ids": source_ids,
            }
            raw = (
                "---\n"
                + yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False).strip()
                + "\n---\n\n# 适用问题\n\n"
                + question
                + "\n\n# 经核验答复\n\n"
                + answer_text
                + "\n"
            )
            temp_path = curated_path.with_suffix(".md.tmp")
            temp_path.write_text(raw, encoding="utf-8")
            temp_path.replace(curated_path)
            ingest_curated(
                settings.data_dir / "curated", settings.corpus_dir, settings.manifest_path
            )
            answer_doc_id = doc_id_from(f"curated/{relative.as_posix()}")
            answer_meta = load_manifest(settings.manifest_path).get(answer_doc_id)
            if answer_meta is None:
                raise HTTPException(status_code=500, detail="标准答案已保存，但未能写入馆藏")
            append_relations(
                default_relations_path(settings.manifest_path),
                [
                    DocRelation(
                        parent_doc_id=source.doc_id,
                        child_doc_id=answer_doc_id,
                        relation="derived_from",
                        evidence="管理员核验标准答案",
                        confidence=1.0,
                    )
                    for source in usable_sources
                ],
            )
            _append_admin_action(
                settings,
                meta=answer_meta,
                action="curate_answer",
                reason=f"{editor} 核验；依据 {len(usable_sources)} 份",
            )
            runtime["publishing"] = True
            runtime["admin_job"] = {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            try:
                index_report = refresh_runtime_index()
                runtime["admin_job"] = {
                    "status": "completed",
                    "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "result": index_report,
                }
            except Exception as exc:
                logger.exception("标准答案增量索引失败")
                runtime["admin_job"] = {
                    "status": "failed",
                    "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "error": str(exc),
                }
                raise HTTPException(
                    status_code=500,
                    detail=f"标准答案已保存，但增量索引失败：{exc}",
                ) from exc
            finally:
                runtime["publishing"] = False
        return {
            "ok": True,
            "document": _doc_payload(settings, answer_meta),
            "index": index_report,
        }

    @router.post("/api/admin/wechat/import")
    def import_wechat_article(
        req: WechatImportReq,
        response: Response,
        _: None = Depends(require_admin),
    ) -> dict:
        no_store(response)
        url = req.url.strip()
        if not is_wechat_article_url(url):
            raise HTTPException(status_code=422, detail="请输入 mp.weixin.qq.com 的文章链接")
        with _MUTATION_LOCK:
            ensure_not_publishing()
            with TemporaryDirectory(prefix=".admin-wechat-", dir=settings.data_dir) as temp_dir:
                seed = Path(temp_dir) / "seed.jsonl"
                seed.write_text(json.dumps({"account": "", "url": url}, ensure_ascii=False) + "\n")
                report = crawl_wechat(
                    accounts=load_wechat_accounts(
                        PROJECT_ROOT / "data" / "sources" / "sufe_wechat.yaml"
                    ),
                    discovery=SeedURLDiscovery(seed),
                    fetcher=WechatArticleFetcher.create(delay=0),
                    corpus_dir=settings.corpus_dir,
                    manifest_path=settings.manifest_path,
                    mode="admin-seed",
                    limit=1,
                    raw_dir=settings.data_dir / "raw" / "mp.weixin.qq.com",
                    report_dir=settings.data_dir / "crawl_reports",
                )
            accepted_ids = [
                row.get("doc_id")
                for row in report.decisions
                if row.get("decision") == "accept" and row.get("doc_id")
            ]
            if not accepted_ids:
                decision = report.decisions[0] if report.decisions else {}
                reason = decision.get("reason") or report.discovery_status or "unknown"
                status = decision.get("status") or ""
                error = decision.get("error") or ""
                detail = "；".join(part for part in (reason, status, error) if part)
                raise HTTPException(status_code=422, detail=f"公众号文章未入库：{detail}")
            manifest = load_manifest(settings.manifest_path)
            documents = [_doc_payload(settings, manifest[doc_id]) for doc_id in accepted_ids]
            for doc_id in accepted_ids:
                _append_admin_action(
                    settings,
                    meta=manifest[doc_id],
                    action="wechat_import",
                    reason="管理员提交公众号链接",
                )
        return {"ok": True, "report": asdict(report), "documents": documents}

    @router.post("/api/admin/import")
    def import_document(
        response: Response,
        _: None = Depends(require_admin),
        filename: str = Query(min_length=1, max_length=200),
        category: str = Query(min_length=1, max_length=20),
        publisher: str = Query(min_length=2, max_length=200),
        source_url: str = Query(min_length=8, max_length=2000),
        content: bytes = Body(max_length=25_000_000, media_type="application/octet-stream"),
    ) -> dict:
        no_store(response)
        clean_name = Path(filename).name
        if (
            clean_name != filename
            or "/" in filename
            or "\\" in filename
            or filename.startswith(".")
        ):
            raise HTTPException(status_code=422, detail="文件名不合法")
        if Path(clean_name).suffix.lower() not in {".md", ".html", ".htm", ".pdf", ".docx"}:
            raise HTTPException(status_code=422, detail="仅支持 Markdown、HTML、PDF 和 DOCX")
        if category not in CATEGORIES:
            raise HTTPException(status_code=422, detail="知识分类不合法")
        source = source_url.strip()
        if urlsplit(source).scheme not in {"http", "https"} or not urlsplit(source).netloc:
            raise HTTPException(status_code=422, detail="原始链接必须是完整的 http(s) 地址")
        if not content:
            raise HTTPException(status_code=422, detail="文件内容为空")

        with _MUTATION_LOCK:
            ensure_not_publishing()
            with TemporaryDirectory(prefix=".admin-upload-", dir=settings.data_dir) as temp_dir:
                upload = Path(temp_dir) / clean_name
                upload.write_bytes(content)
                report = ingest_inbox(
                    Path(temp_dir),
                    settings.corpus_dir,
                    settings.manifest_path,
                    category,
                    publisher.strip(),
                    {clean_name: source},
                )
            if report.quarantined:
                raise HTTPException(status_code=422, detail="文件含疑似个人敏感信息，未入库")
            if report.skipped_dup:
                raise HTTPException(status_code=409, detail="相同正文已经入库")
            if report.skipped_empty:
                raise HTTPException(status_code=422, detail="未解析到正文；扫描版 PDF 请先做 OCR")
            if report.skipped_error or not report.added:
                raise HTTPException(status_code=422, detail="文件无法解析或格式损坏")
            imported = load_manifest(settings.manifest_path)[doc_id_from(source)]
            _append_admin_action(
                settings, meta=imported, action="import", reason=f"管理员导入 {clean_name}"
            )
        return {"ok": True, "report": asdict(report), "document": _doc_payload(settings, imported)}

    @router.post("/api/admin/documents/{doc_id}/action")
    def document_action(
        doc_id: str,
        req: DocumentActionReq,
        response: Response,
        _: None = Depends(require_admin),
    ) -> dict:
        no_store(response)
        with _MUTATION_LOCK:
            ensure_not_publishing()
            history = [
                meta for meta in _manifest_rows(settings.manifest_path) if meta.doc_id == doc_id
            ]
            if not history:
                raise HTTPException(status_code=404, detail="文档不存在")
            current = history[-1]
            if req.action == "quarantine":
                if current.quality_status == "quarantined":
                    raise HTTPException(status_code=409, detail="文档已经隔离")
                updated = replace(
                    current,
                    content_hash="",
                    file_path="",
                    quality_status="quarantined",
                    document_kind="incomplete",
                    retention_status="archived",
                    retention_reason=f"admin_quarantine:{req.reason}",
                    index_collection="none",
                )
            elif req.action == "restore":
                if current.quality_status != "quarantined":
                    raise HTTPException(status_code=409, detail="只有已隔离文档可以恢复")
                previous = next(
                    (
                        meta
                        for meta in reversed(history[:-1])
                        if meta.quality_status != "quarantined" and meta.file_path
                    ),
                    None,
                )
                if previous is None:
                    raise HTTPException(status_code=409, detail="找不到可恢复版本")
                path = _safe_body_path(settings, previous)
                if path is None:
                    raise HTTPException(status_code=409, detail="原正文已不存在，无法恢复")
                if (
                    sha256_text(path.read_text(encoding="utf-8", errors="replace"))
                    != previous.content_hash
                ):
                    raise HTTPException(status_code=409, detail="原正文校验失败，无法恢复")
                updated = previous
            else:
                target = next(
                    (
                        meta
                        for meta in reversed(history[:-1])
                        if meta.content_hash == req.version_hash
                        and meta.quality_status == "accepted"
                    ),
                    None,
                )
                if target is None:
                    raise HTTPException(status_code=409, detail="找不到可回退版本")
                if _version_body_path(settings, target) is None:
                    raise HTTPException(status_code=409, detail="旧版正文快照已不存在，无法回退")
                updated = replace(
                    target,
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    retention_reason=f"admin_rollback:{req.reason}",
                )
            append_manifest(settings.manifest_path, [updated])
            _append_admin_action(
                settings, meta=updated, action=req.action, reason=req.reason.strip()
            )
        return {"ok": True, "document": _doc_payload(settings, updated)}

    @router.post("/api/admin/audit")
    def run_audit(response: Response, _: None = Depends(require_admin)) -> dict:
        no_store(response)
        with _MUTATION_LOCK:
            ensure_not_publishing()
            return {"ok": True, "quality": _run_quality_audit(settings)}

    def publish_worker() -> None:
        try:
            report = refresh_runtime_index()
            runtime["admin_job"] = {
                "status": "completed",
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "result": report,
            }
        except Exception as exc:  # 后台任务必须把可操作错误留给 Dashboard
            logger.exception("管理员发布索引失败")
            runtime["admin_job"] = {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "error": str(exc),
            }
        finally:
            runtime["publishing"] = False

    @router.post("/api/admin/publish")
    def publish(response: Response, _: None = Depends(require_admin)) -> dict:
        no_store(response)
        with _MUTATION_LOCK:
            if runtime.get("publishing"):
                raise HTTPException(status_code=409, detail="知识库正在发布")
            manifest_fingerprint = _fingerprint(settings.manifest_path)
            quality = _quality_snapshot(settings, manifest_fingerprint)
            if not quality.get("fresh"):
                raise HTTPException(status_code=409, detail="请先运行知识库体检")
            blockers = sum(
                int(quality.get(key, 0) or 0)
                for key in (
                    "collection_contamination_count",
                    "duplicate_active_annual_series_count",
                    "date_conflict_count",
                    "missing_required_attachment_count",
                )
            )
            if blockers:
                raise HTTPException(status_code=409, detail=f"仍有 {blockers} 个质量阻断项")
            if _index_metadata(settings).get("manifest_fingerprint") == manifest_fingerprint:
                raise HTTPException(status_code=409, detail="当前知识库已经发布")
            runtime["publishing"] = True
            runtime["admin_job"] = {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            threading.Thread(target=publish_worker, daemon=True).start()
        return {"ok": True, "job": runtime["admin_job"]}

    @router.get("/api/admin/job")
    def publish_job(response: Response, _: None = Depends(require_admin)) -> dict:
        no_store(response)
        return runtime.get("admin_job") or {"status": "idle"}

    return router
