"""Web 服务：FastAPI + SSE 流式问答 + 静态前端，无构建步骤。

- GET  /               静态单页（app/static/）
- GET  /api/meta       馆藏档数 / 分类 / 知识库更新时间 / 示例问题
- POST /api/ask        SSE 流：meta(文号/检索耗时) → token* → sources|refused → done
- POST /api/feedback   批注（👍/👎）追加 data/feedback.jsonl（提交材料 #9）

create_app 支持注入 retriever/llm（测试与离线演示用 Fake 替代）；
模块级 app 延迟到 startup 才加载 BGE-M3，import 本模块无重活。
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sufe_qa.config import Settings, load_settings
from sufe_qa.generate.answer import answer_question, validate_citations
from sufe_qa.generate.client import LLMClient
from sufe_qa.retrieve.retriever import HybridRetriever
from sufe_qa.schema import load_manifest

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
_COVERAGE_STATUSES = {"answerable", "partially_answerable", "not_answerable"}
_REAL_ANSWER_STATUSES = {
    "answered",
    "answered_with_citation_issue",
    "refused",
    "error",
}

EXAMPLE_QUESTIONS = [
    "推免预报名的申请条件是什么？",
    "博士研究生「申请考核」制的流程是怎样的？",
    "研究生新生党团组织关系怎么转接？",
    "国家教育考试作弊会受什么处理？",
    "硕士研究生调剂拟录取名单公示了吗？",
    "学校门口哪家火锅最好吃？",
]


class AskReq(BaseModel):
    question: str = Field(max_length=2000)  # 传输层硬上限；业务上限由 settings 收口


class FeedbackReq(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=8000)
    rating: str  # "up" | "down"


def _load_coverage_report(path: Path) -> dict:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="覆盖评测报告不存在")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="覆盖评测报告无法解析") from exc
    if not isinstance(report, dict):
        raise HTTPException(status_code=500, detail="覆盖评测报告结构无效")
    questions = report.get("question_results")
    scenes = report.get("scene_stats")
    if not isinstance(questions, list) or not isinstance(scenes, dict):
        raise HTTPException(status_code=500, detail="覆盖评测报告结构无效")
    for question in questions:
        required = ("id", "question", "scene", "status")
        if not isinstance(question, dict) or any(
            not isinstance(question.get(key), str) or not question[key] for key in required
        ):
            raise HTTPException(status_code=500, detail="覆盖评测报告结构无效")
        if question["status"] not in _COVERAGE_STATUSES:
            raise HTTPException(status_code=500, detail="覆盖评测报告结构无效")
    return report


def _load_real_answer_report(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="真实答案报告无法解析") from exc
    if not isinstance(report, dict) or report.get("schema_version") != "1":
        raise HTTPException(status_code=500, detail="真实答案报告结构无效")
    results = report.get("results")
    if not isinstance(results, list) or not isinstance(report.get("total"), int):
        raise HTTPException(status_code=500, detail="真实答案报告结构无效")
    seen: set[str] = set()
    for result in results:
        required = ("id", "question", "scene", "status")
        if not isinstance(result, dict) or any(
            not isinstance(result.get(key), str) or not result[key] for key in required
        ):
            raise HTTPException(status_code=500, detail="真实答案报告结构无效")
        if result["status"] not in _REAL_ANSWER_STATUSES or result["id"] in seen:
            raise HTTPException(status_code=500, detail="真实答案报告结构无效")
        if not isinstance(result.get("answer_text", ""), str) or not isinstance(
            result.get("hits", []), list
        ):
            raise HTTPException(status_code=500, detail="真实答案报告结构无效")
        seen.add(result["id"])
    return report


def _merge_real_answers(coverage: dict, answers: dict | None) -> dict:
    questions = coverage["question_results"]
    if answers is None:
        coverage["answer_run"] = {"available": False}
        for question in questions:
            question["real_answer"] = None
        return coverage
    compatible = (
        answers.get("question_bank_version") == coverage.get("question_bank_version")
        and answers.get("question_bank_hash") == coverage.get("question_bank_hash")
        and answers.get("index_fingerprint") == coverage.get("index_fingerprint")
        and answers.get("total") == len(questions)
    )
    if not compatible:
        raise HTTPException(status_code=409, detail="真实答案报告与覆盖题库或索引不兼容")
    question_by_id = {question["id"]: question for question in questions}
    answer_by_id: dict[str, dict] = {}
    for answer in answers["results"]:
        question = question_by_id.get(answer["id"])
        if (
            question is None
            or question["question"] != answer["question"]
            or question["scene"] != answer["scene"]
        ):
            raise HTTPException(status_code=409, detail="真实答案报告与覆盖题库或索引不兼容")
        answer_by_id[answer["id"]] = answer
    for question in questions:
        question["real_answer"] = answer_by_id.get(question["id"])
    coverage["answer_run"] = {
        **{key: value for key, value in answers.items() if key != "results"},
        "available": True,
    }
    return coverage


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_error(message: str) -> StreamingResponse:
    return StreamingResponse(
        iter([_sse("error", {"message": message})]), media_type="text/event-stream"
    )


class _RateLimiter:
    """单实例内存滑动窗口限流，按客户端 IP 计数。"""

    def __init__(self, per_minute: int):
        self._per = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            while dq and now - dq[0] > 60.0:
                dq.popleft()
            if len(dq) >= self._per:
                return False
            dq.append(now)
            return True


def _client_key(request: Request) -> str:
    """取客户端标识：反向代理（如 HF Spaces）后取 X-Forwarded-For 首跳。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app(
    settings: Settings | None = None,
    retriever: HybridRetriever | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    from contextlib import asynccontextmanager

    settings = settings or load_settings()
    state: dict = {"retriever": retriever, "llm": llm, "counter": itertools.count(1)}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if state["retriever"] is None:
            from sufe_qa.indexing.indexer import BgeEmbedder

            state["retriever"] = HybridRetriever(settings, BgeEmbedder(settings.embedding_model))
        yield

    app = FastAPI(title="上财校务问答", docs_url=None, redoc_url=None, lifespan=lifespan)
    # 防滥用：IP 滑动窗口限流 + 全局 LLM 并发闸（挂在 app.state 便于测试注入与观测）
    app.state.rate_limiter = _RateLimiter(settings.rate_limit_per_minute)
    app.state.llm_sem = threading.BoundedSemaphore(settings.max_concurrent_llm)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/coverage")
    def coverage_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "coverage.html")

    @app.get("/api/meta")
    def meta() -> dict:
        manifest = load_manifest(settings.manifest_path)
        updated = max((m.fetched_at for m in manifest.values()), default=None)
        return {
            "doc_count": len(manifest),
            "updated_at": updated,
            "categories": sorted({m.category for m in manifest.values()}),
            "examples": EXAMPLE_QUESTIONS,
        }

    @app.get("/api/coverage")
    def coverage_report() -> JSONResponse:
        coverage_dir = settings.data_dir / "coverage"
        report = _merge_real_answers(
            _load_coverage_report(coverage_dir / "sufe_coverage_after.json"),
            _load_real_answer_report(coverage_dir / "sufe_real_answers.json"),
        )
        return JSONResponse(report, headers={"Cache-Control": "no-store"})

    @app.post("/api/ask")
    def ask(req: AskReq, request: Request) -> StreamingResponse:
        question = req.question.strip()
        if not question:
            return _sse_error("问题为空")
        if len(question) > settings.max_question_chars:
            return _sse_error(f"问题过长（上限 {settings.max_question_chars} 字）")
        if not app.state.rate_limiter.allow(_client_key(request)):
            return _sse_error("请求过于频繁，请稍后再试")
        if not app.state.llm_sem.acquire(blocking=False):
            return _sse_error("当前咨询人数较多，请稍后重试")
        if state["retriever"] is None:
            # 测试经 TestClient 注入组件时不走此分支；直接调用 create_app 未起 lifespan 时兜底
            from sufe_qa.indexing.indexer import BgeEmbedder

            state["retriever"] = HybridRetriever(settings, BgeEmbedder(settings.embedding_model))

        def gen() -> Iterator[str]:
            # 整个生成过程（含 LLM token 流迭代）都在兜底内：
            # 流中途断网/超时也要发出 error 事件，并让 finally 释放并发闸
            try:
                doc_no = f"校务答字〔{datetime.now().year}〕第{next(state['counter']):03d}号"
                t0 = time.perf_counter()
                ans = answer_question(question, settings, state["retriever"], llm=state["llm"])
                retrieval_ms = (time.perf_counter() - t0) * 1000
                yield _sse(
                    "meta",
                    {
                        "doc_no": doc_no,
                        "retrieval_ms": round(retrieval_ms, 1),
                        "refused": ans.refused,
                    },
                )
                answer_text = ""
                for token in ans.stream:
                    answer_text += token
                    yield _sse("token", {"text": token})
                cards, cite_map = ans.sources_and_map()
                # 拒答走固定模板、本就无引用，不参与校验
                citation_check = (
                    validate_citations(answer_text, len(ans.hits)) if not ans.refused else None
                )
                if citation_check is not None and not citation_check.ok:
                    logger.warning("引用校验未通过: %s", citation_check.invalid_refs)
                yield _sse(
                    "sources",
                    {
                        "cards": [
                            {
                                "index": c.index,
                                "title": c.title,
                                "publisher": c.publisher,
                                "source_url": c.source_url,
                                "publish_date": c.publish_date,
                            }
                            for c in cards
                        ],
                        "cite_map": cite_map,
                        "citation_check": (
                            None
                            if citation_check is None
                            else {
                                "ok": citation_check.ok,
                                "invalid_refs": citation_check.invalid_refs,
                            }
                        ),
                    },
                )
                yield _sse("done", {"total_ms": round((time.perf_counter() - t0) * 1000, 1)})
            except Exception as e:  # LLM 未配置/检索异常/流中断等，统一退为 error 事件
                logger.exception("问答失败")
                yield _sse("error", {"message": f"答复生成失败：{e}"})
            finally:
                app.state.llm_sem.release()

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/feedback")
    def feedback(req: FeedbackReq, request: Request) -> dict:
        if req.rating not in ("up", "down"):
            return {"ok": False, "message": "rating 须为 up/down"}
        if not app.state.rate_limiter.allow(_client_key(request)):
            return {"ok": False, "message": "请求过于频繁，请稍后再试"}
        path = settings.data_dir / "feedback.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "question": req.question[:500],
                        "answer": req.answer[:500],
                        "rating": req.rating,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
