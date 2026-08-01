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
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sufe_qa.config import Settings, load_settings
from sufe_qa.generate.answer import answer_question
from sufe_qa.generate.client import LLMClient
from sufe_qa.retrieve.retriever import HybridRetriever
from sufe_qa.schema import load_manifest

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

EXAMPLE_QUESTIONS = [
    "推免预报名的申请条件是什么？",
    "博士研究生「申请考核」制的流程是怎样的？",
    "研究生新生党团组织关系怎么转接？",
    "国家教育考试作弊会受什么处理？",
    "硕士研究生调剂拟录取名单公示了吗？",
    "学校门口哪家火锅最好吃？",
]


class AskReq(BaseModel):
    question: str


class FeedbackReq(BaseModel):
    question: str
    answer: str
    rating: str  # "up" | "down"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

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

    @app.post("/api/ask")
    def ask(req: AskReq) -> StreamingResponse:
        question = req.question.strip()
        if not question:
            return StreamingResponse(
                iter([_sse("error", {"message": "问题为空"})]),
                media_type="text/event-stream",
            )
        if state["retriever"] is None:
            # 测试经 TestClient 注入组件时不走此分支；直接调用 create_app 未起 lifespan 时兜底
            from sufe_qa.indexing.indexer import BgeEmbedder

            state["retriever"] = HybridRetriever(settings, BgeEmbedder(settings.embedding_model))

        def gen() -> Iterator[str]:
            doc_no = f"校务答字〔{datetime.now().year}〕第{next(state['counter']):03d}号"
            t0 = time.perf_counter()
            try:
                ans = answer_question(question, settings, state["retriever"], llm=state["llm"])
            except Exception as e:  # LLM 未配置/检索异常等，统一退为 error 事件
                logger.exception("问答失败")
                yield _sse("error", {"message": f"答复生成失败：{e}"})
                return
            retrieval_ms = (time.perf_counter() - t0) * 1000
            yield _sse(
                "meta",
                {"doc_no": doc_no, "retrieval_ms": round(retrieval_ms, 1), "refused": ans.refused},
            )
            for token in ans.stream:
                yield _sse("token", {"text": token})
            cards, cite_map = ans.sources_and_map()
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
                },
            )
            yield _sse("done", {"total_ms": round((time.perf_counter() - t0) * 1000, 1)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/feedback")
    def feedback(req: FeedbackReq) -> dict:
        if req.rating not in ("up", "down"):
            return {"ok": False, "message": "rating 须为 up/down"}
        path = settings.data_dir / "feedback.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "question": req.question,
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
