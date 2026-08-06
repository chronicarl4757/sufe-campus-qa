"""命令行入口：crawl / ingest / index / ask / eval / serve 串起全流程。

    sufe-qa crawl                      # 按 seeds.yaml 抓种子站（分页+附件+质量门）→ 入库
    sufe-qa discover-site <url>        # 学院主页勘探，生成 site profile
    sufe-qa crawl-site <host|profile>  # 按确定性 profile 整站抓取
    sufe-qa crawl-report [host]        # 查看最近一次抓取报告
    sufe-qa ingest --category 学工事务  # data/inbox/ 手动投放文件入库
    sufe-qa index                      # 增量索引（--full 全量重建）
    sufe-qa ask "推免申请条件是什么"     # 问答（流式回答 + 来源卡片）
    sufe-qa eval                       # 跑评测集并过门禁（不达标退出码 1）

--fake-embed 用确定性假向量替代 BGE-M3，供离线开发/测试（跨进程确定性，索引与问答需同用）。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from sufe_qa.config import PROJECT_ROOT, Settings, load_settings
from sufe_qa.coverage.audit import audit_manifest
from sufe_qa.coverage.reports import write_coverage_report
from sufe_qa.crawler.authority import load_authority_sources
from sufe_qa.crawler.authority_runner import (
    AuthorityRunOptions,
    crawl_authority_sources,
    retry_attachments_from_raw,
)
from sufe_qa.crawler.crawl import load_seeds
from sufe_qa.crawler.discover import discover_site
from sufe_qa.crawler.engine import CrawlOptions, CrawlReport, crawl_category
from sufe_qa.crawler.fetcher import SafeFetcher
from sufe_qa.crawler.profile import ArticleProfile, SiteProfile, profile_from_yaml, profile_to_yaml
from sufe_qa.crawler.state import CrawlState
from sufe_qa.evals.scorer import load_evalset, score_retrieval
from sufe_qa.generate.answer import answer_question
from sufe_qa.generate.client import LLMClient
from sufe_qa.indexing.indexer import (
    BgeEmbedder,
    Embedder,
    FakeEmbedder,
    migrate_legacy_collection,
    update_index,
)
from sufe_qa.indexing.collections import (
    HISTORICAL_COLLECTION,
    MAIN_QA_COLLECTION,
    PUBLIC_LIST_COLLECTION,
)
from sufe_qa.ingest.attachment_parsers import parse_attachment
from sufe_qa.ingest.inbox import ingest_inbox
from sufe_qa.ingest.pipeline import ingest_crawled_articles
from sufe_qa.ingest.version_reconcile import reconcile_versions
from sufe_qa.quality.audit import (
    audit_corpus,
    load_quality_audit,
    write_quality_audit,
)
from sufe_qa.quality.migrate import rebuild_clean_corpus
from sufe_qa.quality.gates import verify_clean_pipeline, write_gate_report
from sufe_qa.retrieve.retriever import HybridRetriever
from sufe_qa.schema import default_relations_path

logger = logging.getLogger(__name__)

DEFAULT_SEEDS = PROJECT_ROOT / "seeds.yaml"
DEFAULT_EVALSET = PROJECT_ROOT / "data" / "eval" / "evalset.v1.jsonl"
DEFAULT_AUTHORITY_SOURCES = PROJECT_ROOT / "data" / "sources" / "sufe_authoritative.yaml"


def _make_embedder(settings: Settings, fake: bool) -> Embedder:
    if fake:
        print("警告：使用 FakeEmbedder，仅用于离线开发/测试", file=sys.stderr)
        return FakeEmbedder()
    return BgeEmbedder(settings.embedding_model)


def _make_llm(settings: Settings) -> LLMClient | None:
    """返回 None 让 answer_question 自建 DeepSeekClient；测试可 monkeypatch 本函数。"""
    return None


def _crawl_one_category(
    settings: Settings,
    fetcher: SafeFetcher,
    *,
    name: str,
    list_url: str,
    selector: str,
    url_prefix: str,
    category: str,
    publisher: str,
    article_profile: ArticleProfile,
    options: CrawlOptions,
    dry_run: bool,
    report_json: bool,
    report: CrawlReport | None = None,  # 同 host 多栏目共享站点级报告
) -> CrawlReport:
    """抓取单个栏目并入库；返回报告（调用方负责打印与汇总）。"""
    host = urlparse(list_url).netloc
    state = CrawlState.load(settings.data_dir / "crawl_state" / f"{host}.json")
    own_report = report is None
    report = report or CrawlReport(host=host)
    report.categories_found += 1
    articles = crawl_category(
        list_url,
        selector,
        url_prefix,
        fetcher,
        options=options,
        article_profile=article_profile,
        publisher=publisher,
        state=state,
        parse_attachment=None if options.download_attachments is False else parse_attachment,
        report=report,
    )
    stats = ingest_crawled_articles(
        articles,
        category=category,
        corpus_dir=settings.corpus_dir,
        manifest_path=settings.manifest_path,
        relations_path=default_relations_path(settings.manifest_path),
        raw_dir=None if dry_run else settings.data_dir / "raw" / host,
        state=state,
        report=report,
        dry_run=dry_run,
    )
    report.not_seen_documents += len(state.finalize())
    if not dry_run:
        state.save()
    if report_json and own_report:
        path = report.save(settings.data_dir / "crawl_reports")
        print(f"  报告: {path}")
    rejected = stats.count("rejected")
    print(
        f"[{name}] 文章 {report.articles_downloaded}/{report.articles_found}，"
        f"附件 {report.attachments_downloaded}/{report.attachments_found} "
        f"解析 {report.attachments_parsed}，新增 {report.new_documents}，"
        f"更新 {report.updated_documents}，未变 {report.unchanged_documents}，"
        f"不完整 {report.incomplete_documents}，低质 {report.low_quality_documents}，"
        f"拒绝 {rejected}{'（dry-run）' if dry_run else ''}"
    )
    if report.categories_requires_adapter:
        print(f"  警告: {name} 存在无法识别的分页，需要 adapter", file=sys.stderr)
    return report


def _cmd_crawl(args: argparse.Namespace) -> int:
    settings = load_settings()
    seeds = load_seeds(Path(args.seeds))
    if not seeds:
        print(f"种子清单为空: {args.seeds}", file=sys.stderr)
        return 2
    # 同 host 的 seed 共享一份站点级报告（避免同秒文件名互相覆盖）
    by_host: dict[str, list] = {}
    for seed in seeds:
        by_host.setdefault(urlparse(seed.list_url).netloc, []).append(seed)
    with SafeFetcher(delay=args.delay, max_attachment_bytes=args.max_attachment_bytes) as fetcher:
        for host, host_seeds in by_host.items():
            report = CrawlReport(host=host)
            for seed in host_seeds:
                _crawl_one_category(
                    settings,
                    fetcher,
                    name=seed.name,
                    list_url=seed.list_url,
                    selector=seed.link_selector,
                    url_prefix=seed.url_prefix,
                    category=seed.category,
                    publisher=seed.publisher,
                    article_profile=ArticleProfile(),
                    options=CrawlOptions(
                        max_list_pages=args.max_list_pages or seed.max_list_pages,
                        max_articles=args.max_articles or seed.max_articles,
                        max_attachment_bytes=args.max_attachment_bytes,
                        since=args.since,
                        download_attachments=not args.no_attachments,
                    ),
                    dry_run=args.dry_run,
                    report_json=args.report_json,
                    report=report,
                )
            if args.report_json and not args.dry_run:
                print(f"  站点报告: {report.save(settings.data_dir / 'crawl_reports')}")
    return 0


def _cmd_discover_site(args: argparse.Namespace) -> int:
    settings = load_settings()
    # 自动发现模式：一律禁止私网地址（SafeFetcher 默认），限速从 --delay
    with SafeFetcher(delay=args.delay) as fetcher:
        profile, report = discover_site(args.homepage_url, fetcher, max_probe=args.max_probe)
    print(report.summary())
    out = settings.data_dir / "site_profiles" / f"{profile.host}.yaml"
    profile_to_yaml(profile, out)
    print(f"\nprofile 已写入: {out}")
    print(f"可用 `sufe-qa crawl-site {profile.host}` 执行确定性抓取")
    return 0 if report.columns else 1


def _resolve_profile(settings: Settings, host_or_path: str) -> SiteProfile | None:
    p = Path(host_or_path)
    if p.is_file():
        return profile_from_yaml(p)
    candidate = settings.data_dir / "site_profiles" / f"{host_or_path}.yaml"
    return profile_from_yaml(candidate) if candidate.is_file() else None


def _cmd_crawl_site(args: argparse.Namespace) -> int:
    settings = load_settings()
    profile = _resolve_profile(settings, args.host_or_profile)
    if profile is None or not profile.categories:
        print(
            f"profile 不存在或无栏目: {args.host_or_profile}（先运行 discover-site）",
            file=sys.stderr,
        )
        return 2
    # crawl-site 只用确定性 profile：host 白名单收敛到 profile.allowed_hosts
    report = CrawlReport(host=profile.host)
    with SafeFetcher(
        delay=args.delay,
        allowed_hosts=set(profile.allowed_hosts),
        max_html_bytes=profile.limits.max_html_bytes,
        max_attachment_bytes=args.max_attachment_bytes or profile.limits.max_attachment_bytes,
    ) as fetcher:
        for cat in profile.categories:
            _crawl_one_category(
                settings,
                fetcher,
                name=f"{profile.site_name}-{cat.name}",
                list_url=cat.list_url,
                selector=cat.article_selector,
                url_prefix=cat.url_prefix,
                category=cat.category,
                publisher=profile.site_name,
                article_profile=profile.article,
                options=CrawlOptions(
                    max_list_pages=args.max_list_pages or cat.max_list_pages,
                    max_articles=args.max_articles or cat.max_articles,
                    max_attachment_bytes=args.max_attachment_bytes
                    or profile.limits.max_attachment_bytes,
                    max_attachments_per_article=profile.limits.max_attachments_per_article,
                    since=args.since,
                    download_attachments=not args.no_attachments,
                ),
                dry_run=args.dry_run,
                report_json=args.report_json,
                report=report,
            )
    if args.report_json and not args.dry_run:
        print(f"  站点报告: {report.save(settings.data_dir / 'crawl_reports')}")
    return 0


def _cmd_crawl_authoritative(args: argparse.Namespace) -> int:
    settings = load_settings()
    sources = load_authority_sources(Path(args.sources))
    if args.source:
        sources = [source for source in sources if source.source_id in set(args.source)]
    if not sources:
        print("权威来源清单为空或未匹配 --source", file=sys.stderr)
        return 2
    reports = crawl_authority_sources(
        settings,
        sources,
        options=AuthorityRunOptions(
            delay=args.delay,
            max_list_pages=args.max_list_pages or 1000,
            max_articles=args.max_articles or None,
            max_attachment_bytes=args.max_attachment_bytes,
            max_attachments_per_article=args.max_attachments_per_article,
            since=args.since,
            download_attachments=not args.no_attachments,
            dry_run=args.dry_run,
            report_dir=settings.data_dir / "crawl_reports" if args.report_json else None,
            refresh_articles=args.refresh,
        ),
    )
    for report in reports:
        print(report.summary())
    if not args.dry_run:
        version_report = reconcile_versions(
            settings.manifest_path,
            settings.corpus_dir,
            default_relations_path(settings.manifest_path),
        )
        print(
            f"版本关系：候选主题组 {version_report.candidate_groups}，"
            f"明确关系 {version_report.relation_count}，"
            f"unknown_validity {version_report.unknown_validity_count}"
        )
    return 0


def _cmd_reconcile_versions(_args: argparse.Namespace) -> int:
    settings = load_settings()
    report = reconcile_versions(
        settings.manifest_path,
        settings.corpus_dir,
        default_relations_path(settings.manifest_path),
    )
    print(
        f"版本关系：候选主题组 {report.candidate_groups}，明确关系 {report.relation_count}，"
        f"unknown_validity {report.unknown_validity_count}，更新文档 {report.updated_document_count}"
    )
    return 0


def _cmd_retry_attachments(args: argparse.Namespace) -> int:
    settings = load_settings()
    sources = load_authority_sources(Path(args.sources))
    source = next((item for item in sources if item.source_id == args.source), None)
    if source is None:
        print(f"未找到 source id: {args.source}", file=sys.stderr)
        return 2
    reports = retry_attachments_from_raw(
        settings,
        source,
        options=AuthorityRunOptions(
            delay=args.delay,
            max_attachment_bytes=args.max_attachment_bytes,
            max_attachments_per_article=args.max_attachments_per_article,
            report_dir=settings.data_dir / "crawl_reports" if args.report_json else None,
        ),
    )
    for report in reports:
        print(report.summary())
    return 0


def _cmd_crawl_report(args: argparse.Namespace) -> int:
    settings = load_settings()
    reports_dir = settings.data_dir / "crawl_reports"
    files = sorted(reports_dir.glob(f"*-{args.host}.json" if args.host else "*.json"))
    if not files:
        print(f"暂无抓取报告: {reports_dir}", file=sys.stderr)
        return 2
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    report = CrawlReport(**{k: v for k, v in data.items() if k in CrawlReport.__dataclass_fields__})
    print(f"最新报告: {files[-1].name}")
    print(report.summary())
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
    if args.migrate_legacy:
        report = migrate_legacy_collection(settings)
        print(
            f"迁移源 {report.source_collection}：复制 {report.migrated_chunks} chunks，"
            f"隔离 {report.skipped_chunks} chunks；旧 collection 保留"
        )
        return 0
    report = update_index(settings, _make_embedder(settings, args.fake_embed), full=args.full)
    print(
        f"新增 {report.added_docs} 篇，更新 {report.updated_docs} 篇，"
        f"删除 {report.deleted_docs} 篇，共 {report.total_chunks} chunks，"
        f"主问答 {report.collection_counts.get(MAIN_QA_COLLECTION, 0)} chunks，"
        f"公示 {report.collection_counts.get(PUBLIC_LIST_COLLECTION, 0)} chunks，"
        f"历史 {report.collection_counts.get(HISTORICAL_COLLECTION, 0)} chunks"
    )
    if report.backup_path:
        print(f"旧索引备份: {report.backup_path}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    settings = load_settings()
    retriever = HybridRetriever(
        settings, _make_embedder(settings, args.fake_embed), collection=args.collection
    )
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
    if report.answer_rate is not None:
        print(f"应答题回答率: {report.answer_rate:.1%}（达标线 {args.min_answer:.0%}）")
    if report.refusal_rate is not None:
        print(f"拒答正确率: {report.refusal_rate:.1%}（达标线 {args.min_refusal:.0%}）")
    failures = report.gate_failures(args.min_hit, args.min_refusal, args.min_answer)
    for f in failures:
        print(f"门禁未过: {f}", file=sys.stderr)
    return 1 if failures else 0


def _cmd_coverage_audit(args: argparse.Namespace) -> int:
    settings = load_settings()
    manifest_path = Path(args.manifest) if args.manifest else settings.manifest_path
    corpus_dir = Path(args.corpus) if args.corpus else settings.corpus_dir
    report = audit_manifest(
        manifest_path=manifest_path,
        corpus_dir=corpus_dir,
        question_bank_path=Path(args.question_bank),
        retriever_config={
            "similarity_threshold": settings.vector_min_similarity,
            "vector_top_k": settings.vector_top_k,
            "bm25_top_k": settings.bm25_top_k,
            "fusion_top_n": settings.fusion_top_n,
        },
        index_fingerprint=args.index_fingerprint,
        embedding_model=settings.embedding_model,
    )
    write_coverage_report(report, Path(args.output_json), Path(args.output_md))
    print(f"覆盖审计 JSON: {args.output_json}")
    print(f"覆盖审计 Markdown: {args.output_md}")
    print(f"题目 {len(report.question_results)} 条，语料文档 {report.corpus_document_count} 篇")
    return 0


def _cmd_quality_audit(args: argparse.Namespace) -> int:
    settings = load_settings()
    manifest_path = Path(args.manifest) if args.manifest else settings.manifest_path
    corpus_dir = Path(args.corpus) if args.corpus else settings.corpus_dir
    raw_root = Path(args.raw) if args.raw else settings.data_dir / "raw"
    policies = {
        (source.publisher, section.name): section.time_policy
        for source in load_authority_sources(Path(args.sources))
        for section in source.sections
    }
    report = audit_corpus(
        manifest_path,
        corpus_dir,
        raw_root,
        time_policies=policies,
    )
    write_quality_audit(report, Path(args.output_json), Path(args.output_md))
    print(f"质量审计 JSON: {args.output_json}")
    print(f"质量审计 Markdown: {args.output_md}")
    print(
        f"文档 {report.total_documents}，标题含年份 {report.year_title_ratio:.1%}，"
        f"旧年度通知归档候选 {report.old_annual_count}，日期修正 {report.date_correction_count}"
    )
    return 0


def _cmd_rebuild_clean_corpus(args: argparse.Namespace) -> int:
    settings = load_settings()
    corpus_dir = Path(args.corpus) if args.corpus else settings.corpus_dir
    report = load_quality_audit(Path(args.audit))
    result = rebuild_clean_corpus(report, corpus_dir, apply=args.apply)
    if not result.applied:
        print(
            f"预览：保留正文 {result.retained_files}，归档 {result.archived_documents}；"
            "未传 --apply，未修改 corpus"
        )
        return 0
    print(
        f"干净 corpus 已切换：保留正文 {result.retained_files}，"
        f"归档 {result.archived_documents}"
    )
    print(f"旧 corpus 备份: {result.backup_path}")
    return 0


def _cmd_quality_gates(args: argparse.Namespace) -> int:
    settings = load_settings()
    coverage_path = Path(args.coverage) if args.coverage else None
    report = verify_clean_pipeline(settings, coverage_path=coverage_path)
    write_gate_report(report, Path(args.output))
    if args.missing_sources and coverage_path and coverage_path.is_file():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        probes = {}
        if args.question_bank:
            for line in Path(args.question_bank).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    probes[str(item["id"])] = item
        missing = []
        for result in coverage.get("question_results") or []:
            if result.get("status") == "answerable":
                continue
            probe = probes.get(str(result.get("id")), {})
            missing.append(
                {
                    "id": result.get("id"),
                    "question": result.get("question"),
                    "scene": result.get("scene"),
                    "status": result.get("status"),
                    "expected_domains": probe.get("expected_domains", []),
                    "missing_reasons": result.get("missing_reasons", []),
                }
            )
        missing_path = Path(args.missing_sources)
        missing_path.parent.mkdir(parents=True, exist_ok=True)
        missing_path.write_text(
            json.dumps(
                {
                    "question_bank_version": coverage.get("question_bank_version"),
                    "question_bank_hash": coverage.get("question_bank_hash"),
                    "missing_count": len(missing),
                    "items": missing,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(f"质量门报告: {args.output}")
    failed = [name for name, passed in report["gates"].items() if not passed]
    if failed:
        print(f"未通过质量门: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("全部质量门通过")
    return 0


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

    c = sub.add_parser("crawl", help="抓种子站并入库（分页+附件+质量门）")
    c.add_argument("--seeds", default=str(DEFAULT_SEEDS))
    c.add_argument("--delay", type=float, default=1.0, help="每请求最小间隔秒数")
    c.add_argument("--max-list-pages", type=int, default=0, help="覆盖 seeds 的分页上限")
    c.add_argument("--max-articles", type=int, default=0, help="覆盖 seeds 的文章上限")
    c.add_argument("--max-attachment-bytes", type=int, default=30_000_000)
    c.add_argument("--since", default=None, help="跳过早于此日期的文章（YYYY-MM-DD）")
    c.add_argument("--dry-run", action="store_true", help="只评估，不写 corpus/manifest/索引")
    c.add_argument("--no-attachments", action="store_true", help="不下载附件")
    c.add_argument("--report-json", action="store_true", help="保存机器可读抓取报告")
    c.set_defaults(func=_cmd_crawl)

    ds = sub.add_parser("discover-site", help="学院主页勘探，生成 site profile")
    ds.add_argument("homepage_url")
    ds.add_argument("--delay", type=float, default=1.0)
    ds.add_argument("--max-probe", type=int, default=15, help="最多勘探的候选栏目数")
    ds.set_defaults(func=_cmd_discover_site)

    cs = sub.add_parser("crawl-site", help="按 site profile 确定性整站抓取")
    cs.add_argument("host_or_profile", help="主机名（data/site_profiles/<host>.yaml）或 yaml 路径")
    cs.add_argument("--delay", type=float, default=1.0)
    cs.add_argument("--max-list-pages", type=int, default=0)
    cs.add_argument("--max-articles", type=int, default=0)
    cs.add_argument("--max-attachment-bytes", type=int, default=0)
    cs.add_argument("--since", default=None)
    cs.add_argument("--dry-run", action="store_true")
    cs.add_argument("--no-attachments", action="store_true")
    cs.add_argument("--report-json", action="store_true")
    cs.set_defaults(func=_cmd_crawl_site)

    ac = sub.add_parser("crawl-authoritative", help="按上财职能部门 adapter 清单抓取垂直切片")
    ac.add_argument("--sources", default=str(DEFAULT_AUTHORITY_SOURCES))
    ac.add_argument("--source", action="append", help="只抓指定 source id，可重复")
    ac.add_argument("--delay", type=float, default=1.0)
    ac.add_argument("--max-list-pages", type=int, default=0)
    ac.add_argument("--max-articles", type=int, default=0)
    ac.add_argument("--max-attachment-bytes", type=int, default=30_000_000)
    ac.add_argument("--max-attachments-per-article", type=int, default=20)
    ac.add_argument("--since", default=None)
    ac.add_argument("--dry-run", action="store_true")
    ac.add_argument("--no-attachments", action="store_true")
    ac.add_argument("--refresh", action="store_true", help="忽略文章条件请求，重抓正文与附件")
    ac.add_argument("--report-json", action="store_true")
    ac.set_defaults(func=_cmd_crawl_authoritative)

    vr = sub.add_parser("reconcile-versions", help="根据正文证据回溯制度版本关系")
    vr.set_defaults(func=_cmd_reconcile_versions)

    ra = sub.add_parser("retry-attachments", help="从原始文章缓存定向重放附件")
    ra.add_argument("--sources", default=str(DEFAULT_AUTHORITY_SOURCES))
    ra.add_argument("--source", required=True)
    ra.add_argument("--delay", type=float, default=1.0)
    ra.add_argument("--max-attachment-bytes", type=int, default=30_000_000)
    ra.add_argument("--max-attachments-per-article", type=int, default=20)
    ra.add_argument("--report-json", action="store_true")
    ra.set_defaults(func=_cmd_retry_attachments)

    cr = sub.add_parser("crawl-report", help="查看最近一次抓取报告")
    cr.add_argument("host", nargs="?", default=None)
    cr.set_defaults(func=_cmd_crawl_report)

    i = sub.add_parser("ingest", help="data/inbox/ 手动投放文件入库")
    i.add_argument("--category", required=True)
    i.add_argument("--publisher", default="手动投放")
    i.set_defaults(func=_cmd_ingest)

    x = sub.add_parser("index", help="增量索引")
    x.add_argument("--full", action="store_true", help="全量重建")
    x.add_argument("--migrate-legacy", action="store_true", help="从旧单 collection 复制可判定文档")
    x.add_argument("--fake-embed", action="store_true", help=argparse.SUPPRESS)
    x.set_defaults(func=_cmd_index)

    a = sub.add_parser("ask", help="提问")
    a.add_argument("question")
    a.add_argument(
        "--collection",
        choices=[MAIN_QA_COLLECTION, PUBLIC_LIST_COLLECTION, HISTORICAL_COLLECTION],
        default=MAIN_QA_COLLECTION,
        help="检索 collection；公示名单和历史版本必须显式选择对应 collection",
    )
    a.add_argument("--fake-embed", action="store_true", help=argparse.SUPPRESS)
    a.set_defaults(func=_cmd_ask)

    e = sub.add_parser("eval", help="评测集打分 + 门禁")
    e.add_argument("--evalset", default=str(DEFAULT_EVALSET))
    e.add_argument("--min-hit", type=float, default=0.9, help="检索命中率达标线")
    e.add_argument("--min-answer", type=float, default=1.0, help="应答题回答率达标线")
    e.add_argument("--min-refusal", type=float, default=1.0, help="拒答正确率达标线")
    e.add_argument("--fake-embed", action="store_true", help=argparse.SUPPRESS)
    e.set_defaults(func=_cmd_eval)

    ca = sub.add_parser("coverage-audit", help="生成固定题库分母的语料覆盖审计")
    ca.add_argument("--question-bank", required=True)
    ca.add_argument("--manifest", default="")
    ca.add_argument("--corpus", default="")
    ca.add_argument(
        "--output-json",
        default=str(PROJECT_ROOT / "data" / "coverage" / "sufe_coverage_before.json"),
    )
    ca.add_argument(
        "--output-md",
        default=str(PROJECT_ROOT / "data" / "coverage" / "sufe_coverage_before.md"),
    )
    ca.add_argument("--index-fingerprint", default="not_indexed")
    ca.set_defaults(func=_cmd_coverage_audit)

    qa = sub.add_parser("quality-audit", help="只读审计日期、类型、年度系列和生命周期")
    qa.add_argument("--sources", default=str(DEFAULT_AUTHORITY_SOURCES))
    qa.add_argument("--manifest", default="")
    qa.add_argument("--corpus", default="")
    qa.add_argument("--raw", default="")
    qa.add_argument(
        "--output-json",
        default=str(PROJECT_ROOT / "data" / "quality" / "sufe_data_quality_before.json"),
    )
    qa.add_argument(
        "--output-md",
        default=str(PROJECT_ROOT / "data" / "quality" / "sufe_data_quality_before.md"),
    )
    qa.set_defaults(func=_cmd_quality_audit)

    rc = sub.add_parser("rebuild-clean-corpus", help="按质量审计原子重建干净 corpus")
    rc.add_argument("--audit", required=True)
    rc.add_argument("--corpus", default="")
    rc.add_argument("--apply", action="store_true", help="确认执行原子切换；默认仅预览")
    rc.set_defaults(func=_cmd_rebuild_clean_corpus)

    qg = sub.add_parser("quality-gates", help="验证 corpus、collection、附件和固定题库质量门")
    qg.add_argument("--coverage", default="")
    qg.add_argument("--question-bank", default="")
    qg.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / "crawl_reports" / "sufe_full_report.json"),
    )
    qg.add_argument(
        "--missing-sources",
        default=str(
            PROJECT_ROOT / "data" / "crawl_reports" / "sufe_missing_sources.json"
        ),
    )
    qg.set_defaults(func=_cmd_quality_gates)

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
