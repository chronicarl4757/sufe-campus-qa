"""命令行入口：crawl / ingest / index / ask / eval 五个子命令串起全流程。

    sufe-qa crawl                      # 按 seeds.yaml 抓种子站 → 解析入库
    sufe-qa ingest --category 学工事务  # data/inbox/ 手动投放文件入库
    sufe-qa index                      # 增量索引（--full 全量重建）
    sufe-qa ask "推免申请条件是什么"     # 问答（流式回答 + 来源卡片）
    sufe-qa eval                       # 跑评测集并过门禁（不达标退出码 1）

--fake-embed 用确定性假向量替代 BGE-M3，供离线开发/测试（跨进程确定性，索引与问答需同用）。
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sys
from pathlib import Path

from sufe_qa.config import PROJECT_ROOT, Settings, load_settings
from sufe_qa.crawler.crawl import crawl_seed, load_seeds
from sufe_qa.evals.scorer import load_evalset, score_retrieval
from sufe_qa.generate.answer import answer_question
from sufe_qa.generate.client import LLMClient
from sufe_qa.indexing.indexer import BgeEmbedder, Embedder, FakeEmbedder, update_index
from sufe_qa.ingest.inbox import ingest_inbox, slugify
from sufe_qa.retrieve.retriever import HybridRetriever

logger = logging.getLogger(__name__)

DEFAULT_SEEDS = PROJECT_ROOT / "seeds.yaml"
DEFAULT_EVALSET = PROJECT_ROOT / "data" / "eval" / "evalset.v1.jsonl"


def _make_embedder(settings: Settings, fake: bool) -> Embedder:
    if fake:
        print("警告：使用 FakeEmbedder，仅用于离线开发/测试", file=sys.stderr)
        return FakeEmbedder()
    return BgeEmbedder(settings.embedding_model)


def _make_llm(settings: Settings) -> LLMClient | None:
    """返回 None 让 answer_question 自建 DeepSeekClient；测试可 monkeypatch 本函数。"""
    return None


def _cmd_crawl(args: argparse.Namespace) -> int:
    settings = load_settings()
    seeds = load_seeds(Path(args.seeds))
    if not seeds:
        print(f"种子清单为空: {args.seeds}", file=sys.stderr)
        return 2
    staging = settings.data_dir / "crawl_staging"
    for seed in seeds:
        pages = crawl_seed(seed, delay=args.delay)  # robots/限速/出站防护已内置
        seed_dir = staging / slugify(seed.name)
        shutil.rmtree(seed_dir, ignore_errors=True)
        seed_dir.mkdir(parents=True, exist_ok=True)
        source_urls = {}
        for url, html in pages:
            # 文件名锚定 URL：重爬同 URL 覆盖同名文件，配合 ingest 判重幂等
            fname = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12] + ".html"
            (seed_dir / fname).write_text(html, encoding="utf-8")
            source_urls[fname] = url
        report = ingest_inbox(
            seed_dir,
            settings.corpus_dir,
            settings.manifest_path,
            category=seed.category,
            publisher=seed.publisher,
            source_urls=source_urls,
        )
        print(
            f"[{seed.name}] 抓取 {len(pages)} 页 → 新增 {report.added}，"
            f"重复 {report.skipped_dup}，空 {report.skipped_empty}，"
            f"错误 {report.skipped_error}，隔离 {len(report.quarantined)}"
        )
    shutil.rmtree(staging, ignore_errors=True)
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    settings = load_settings()
    report = ingest_inbox(
        settings.inbox_dir,
        settings.corpus_dir,
        settings.manifest_path,
        category=args.category,
        publisher=args.publisher,
    )
    print(
        f"新增 {report.added}，重复 {report.skipped_dup}，空 {report.skipped_empty}，"
        f"错误 {report.skipped_error}，隔离 {len(report.quarantined)}"
    )
    for name in report.quarantined:
        print(f"  隔离（疑似敏感信息）: {name}", file=sys.stderr)
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    settings = load_settings()
    report = update_index(settings, _make_embedder(settings, args.fake_embed), full=args.full)
    print(
        f"新增 {report.added_docs} 篇，更新 {report.updated_docs} 篇，"
        f"删除 {report.deleted_docs} 篇，共 {report.total_chunks} chunks"
    )
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    settings = load_settings()
    retriever = HybridRetriever(settings, _make_embedder(settings, args.fake_embed))
    ans = answer_question(args.question, settings, retriever, llm=_make_llm(settings))
    for token in ans.stream:
        print(token, end="", flush=True)
    print()
    if not ans.refused:
        print("\n来源：")
        for card in ans.sources():
            date = f"，{card.publish_date}" if card.publish_date != "unknown" else ""
            print(f"  [{card.index}] {card.title}（{card.publisher}{date}）{card.source_url}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    evalset = Path(args.evalset)
    if not evalset.exists():
        print(
            f"评测集不存在: {evalset}（参考 data/eval/evalset.example.jsonl 编写）", file=sys.stderr
        )
        return 2
    settings = load_settings()
    retriever = HybridRetriever(settings, _make_embedder(settings, args.fake_embed))
    report = score_retrieval(retriever, settings, load_evalset(evalset))
    for row in report.rows:
        mark = "PASS" if row.correct else "FAIL"
        kind = "拒答" if row.hit is None else ("命中" if row.hit else "未命中")
        print(f"  [{mark}] {row.id} {kind} | {row.question}")
    if report.hit_rate is not None:
        print(f"检索命中率: {report.hit_rate:.1%}（达标线 {args.min_hit:.0%}）")
    if report.refusal_rate is not None:
        print(f"拒答正确率: {report.refusal_rate:.1%}（达标线 {args.min_refusal:.0%}）")
    failures = report.gate_failures(args.min_hit, args.min_refusal)
    for f in failures:
        print(f"门禁未过: {f}", file=sys.stderr)
    return 1 if failures else 0


def _cmd_serve(args: argparse.Namespace) -> int:
    settings = load_settings()
    import uvicorn

    if args.fake_embed:
        from sufe_qa.app.server import create_app

        app = create_app(settings, retriever=HybridRetriever(settings, FakeEmbedder()))
    else:
        from sufe_qa.app.server import app  # BGE-M3 延迟到 startup 加载

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sufe-qa", description="上财校园问答智能体")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="抓种子站并入库")
    c.add_argument("--seeds", default=str(DEFAULT_SEEDS))
    c.add_argument("--delay", type=float, default=1.0, help="每页最小间隔秒数")
    c.set_defaults(func=_cmd_crawl)

    i = sub.add_parser("ingest", help="data/inbox/ 手动投放文件入库")
    i.add_argument("--category", required=True)
    i.add_argument("--publisher", default="手动投放")
    i.set_defaults(func=_cmd_ingest)

    x = sub.add_parser("index", help="增量索引")
    x.add_argument("--full", action="store_true", help="全量重建")
    x.add_argument("--fake-embed", action="store_true", help=argparse.SUPPRESS)
    x.set_defaults(func=_cmd_index)

    a = sub.add_parser("ask", help="提问")
    a.add_argument("question")
    a.add_argument("--fake-embed", action="store_true", help=argparse.SUPPRESS)
    a.set_defaults(func=_cmd_ask)

    e = sub.add_parser("eval", help="评测集打分 + 门禁")
    e.add_argument("--evalset", default=str(DEFAULT_EVALSET))
    e.add_argument("--min-hit", type=float, default=0.9, help="检索命中率达标线")
    e.add_argument("--min-refusal", type=float, default=1.0, help="拒答正确率达标线")
    e.add_argument("--fake-embed", action="store_true", help=argparse.SUPPRESS)
    e.set_defaults(func=_cmd_eval)

    s = sub.add_parser("serve", help="启动 Web 问答界面")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7860)
    s.add_argument("--fake-embed", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=_cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
