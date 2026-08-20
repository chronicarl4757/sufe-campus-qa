"""公众号抓取编排：discovery → 白名单/时间/相关性门 → fetch → 质量门 → manifest。

复用现有 ingest.pipeline（质量门/生命周期/三级 hash 去重/manifest/relations），
本模块只做公众号特有的前置门与计数。绝不自动索引（规格 §二十五）：
crawl-wechat 只写 corpus/manifest，索引仍由 `sufe-qa index` 完成。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sufe_qa.crawler.engine import CrawledArticle, CrawlReport
from sufe_qa.ingest.pipeline import ingest_crawled_articles
from sufe_qa.schema import (
    DocRelation,
    append_relations,
    default_relations_path,
    doc_id_from,
    load_manifest,
    sha256_text,
)
from sufe_qa.wechat.article import WechatArticle, WechatArticleFetcher, parse_wechat_content
from sufe_qa.wechat.discovery import (
    ArticleDiscovery,
    DiscoveredArticle,
    DiscoveryResult,
)
from sufe_qa.wechat.filters import (
    MIN_PUBLISH_DATE,
    WechatAccount,
    classify_topic,
    classify_wechat_kind,
    date_gate,
    match_account,
    relevance_check,
)

logger = logging.getLogger(__name__)

# 空壳正文阈值（去空白字符数）：低于此值记入 empty_body，由质量门最终裁决
_EMPTY_BODY_CHARS = 80
# 自动 explains 关系：公众号文档与官网政策 topic_key 唯一匹配时建立（规格 §十六）
_OFFICIAL_SOURCE_TYPES = {"official_department", "information_disclosure", "service_platform"}


@dataclass
class WechatCrawlReport:
    """公众号抓取报告（规格 §二十六）：各门计数 + 拒绝原因分布 + 逐篇决策。"""

    mode: str  # seed | werss
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    discovery_status: str = "ok"
    discovered: int = 0
    whitelist_passed: int = 0
    date_passed: int = 0
    relevance_passed: int = 0
    direct_content: int = 0  # 使用 WeRSS 已存正文、未回源微信的篇数（规格 §八）
    fetch_ok: int = 0
    fetch_failed: int = 0
    empty_body: int = 0
    quality_accepted: int = 0
    quality_rejected: int = 0
    duplicate: int = 0
    indexed_candidate: int = 0  # 最终写入 manifest 的 accepted 文档数（new+updated+unchanged）
    reject_reasons: dict[str, int] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1

    def decide(self, url: str, title: str, decision: str, reason: str = "", **extra) -> None:
        row = {"url": url, "title": title, "decision": decision, "reason": reason}
        row.update(extra)
        self.decisions.append(row)

    def topic_stats(self) -> dict[str, dict[str, int]]:
        """按招生/选拔话题统计（规格 §三十八）：topic × decision 计数。"""
        stats: dict[str, dict[str, int]] = {}
        for row in self.decisions:
            topic = row.get("topic") or "其他"
            bucket = stats.setdefault(
                topic,
                {
                    "discovered": 0,
                    "accepted": 0,
                    "historical": 0,
                    "news_rejected": 0,
                    "duplicate": 0,
                    "other_rejected": 0,
                },
            )
            bucket["discovered"] += 1
            if row["decision"] == "accept":
                bucket["accepted"] += 1
                if row.get("retention") == "historical":
                    bucket["historical"] += 1
            elif row["reason"] in {"news_noise", "strong_exclude", "no_facts"}:
                bucket["news_rejected"] += 1
            elif row["reason"] in {"duplicate", "duplicate_text_hash"}:
                bucket["duplicate"] += 1
            else:
                bucket["other_rejected"] += 1
        return stats

    def summary(self) -> str:
        lines = [
            f"公众号抓取报告（{self.mode}）@ {self.started_at}",
            f"  发现文章: {self.discovered}",
            f"  白名单通过: {self.whitelist_passed}",
            f"  时间窗通过: {self.date_passed}",
            f"  相关性通过: {self.relevance_passed}",
            f"  WeRSS正文直入: {self.direct_content}，回源抓取成功: {self.fetch_ok}，"
            f"失败: {self.fetch_failed}，空壳: {self.empty_body}",
            f"  质量门通过: {self.quality_accepted}，拒绝: {self.quality_rejected}",
            f"  重复: {self.duplicate}",
            f"  最终入库候选: {self.indexed_candidate}",
        ]
        if self.reject_reasons:
            lines.append(
                "  拒绝分布: " + ", ".join(f"{k}={v}" for k, v in self.reject_reasons.items())
            )
        stats = self.topic_stats()
        if stats:
            lines.append("  话题分布:")
            for topic, bucket in stats.items():
                lines.append(
                    f"    {topic}: 发现 {bucket['discovered']}，入库 {bucket['accepted']}"
                    f"（历史 {bucket['historical']}），新闻拒 {bucket['news_rejected']}，"
                    f"重复 {bucket['duplicate']}，其他拒 {bucket['other_rejected']}"
                )
        for w in self.warnings:
            lines.append(f"  警告: {w}")
        return "\n".join(lines)

    def save(self, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = re.sub(r"[:+]", "", self.started_at.replace("T", "-"))[:15]
        path = reports_dir / f"{ts}-wechat-{self.mode}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        return path


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _to_crawled(
    article: WechatArticle,
    discovered: DiscoveredArticle,
    *,
    document_kind: str,
    publisher: str,
) -> CrawledArticle:
    """WechatArticle → 现有 ingest 管线的 CrawledArticle。

    final_url 置为 canonical 身份 URL：doc_id 锚定 biz+mid+idx（规格 §十八），
    同一文章的 /s/ 短链与长链自然归并为一个文档。
    """
    return CrawledArticle(
        requested_url=discovered.url,
        final_url=article.canonical_url,
        title=article.title,
        publish_date=article.publish_date,
        publisher=publisher,
        html="",
        body_text=article.body_markdown,
        attachments=[],
        status="ok",
        errors=[],
        document_kind_hint=document_kind,
        publish_date_evidence=("wechat createTime" if article.publish_date != "unknown" else ""),
        publish_date_confidence=0.9 if article.publish_date != "unknown" else 0.0,
    )


def _explains_relations(
    articles: list[tuple[WechatArticle, DiscoveredArticle, str]],
    manifest_path: Path,
) -> list[DocRelation]:
    """官网正式文档与公众号解读的 canonical 关联（规格 §十六）。

    两种证据：
    - 种子显式 related_official_url（confidence 1.0）；
    - topic_key 与唯一一篇 active 官网 policy 精确匹配（confidence 0.7）。
    关系方向：child(公众号) explains parent(官网正式文档)。
    """
    existing = load_manifest(manifest_path)
    by_topic: dict[str, list[str]] = {}
    for meta in existing.values():
        if (
            meta.source_type in _OFFICIAL_SOURCE_TYPES
            and meta.document_kind == "policy"
            and meta.quality_status == "accepted"
            and meta.retention_status == "active"
            and meta.topic_key
            and meta.topic_key != "unknown.topic"
        ):
            by_topic.setdefault(meta.topic_key, []).append(meta.doc_id)
    relations: list[DocRelation] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for article, discovered, wechat_doc_id in articles:
        if discovered.related_official_url:
            official_id = doc_id_from(discovered.related_official_url.strip())
            relations.append(
                DocRelation(
                    parent_doc_id=official_id,
                    child_doc_id=wechat_doc_id,
                    relation="explains",
                    evidence="seed related_official_url",
                    confidence=1.0,
                    created_at=now,
                )
            )
            continue
        # 自动匹配需要 manifest 行：取该 doc_id 对应的 topic_key
        meta = existing.get(wechat_doc_id)
        topic_key = meta.topic_key if meta else ""
        candidates = by_topic.get(topic_key or "", [])
        if len(candidates) == 1 and candidates[0] != wechat_doc_id:
            relations.append(
                DocRelation(
                    parent_doc_id=candidates[0],
                    child_doc_id=wechat_doc_id,
                    relation="explains",
                    evidence=f"topic_key 唯一匹配: {topic_key}",
                    confidence=0.7,
                    created_at=now,
                )
            )
    return relations


def crawl_wechat(
    *,
    accounts: list[WechatAccount],
    discovery: ArticleDiscovery,
    fetcher: WechatArticleFetcher,
    corpus_dir: Path,
    manifest_path: Path,
    mode: str,
    limit: int = 20,
    min_date: str = MIN_PUBLISH_DATE,
    dry_run: bool = False,
    raw_dir: Path | None = None,
    report_dir: Path | None = None,
    relations_path: Path | None = None,
    now: datetime | None = None,
) -> WechatCrawlReport:
    """公众号抓取主流程。任何单篇失败只记报告，不影响其他文章与其他 crawler。"""
    report = WechatCrawlReport(mode=mode)
    relations_path = relations_path or default_relations_path(manifest_path)
    evaluated_at = (now or datetime.now(timezone.utc)).date()

    result: DiscoveryResult = discovery.discover(
        accounts=[a.account_name for a in accounts], limit=limit
    )
    report.discovery_status = result.status
    if result.message:
        report.warnings.append(result.message)
    report.warnings.extend(result.warnings)
    report.discovered = len(result.articles)
    if result.status != "ok" and not result.articles:
        # WeRSS 不可用/种子缺失：报告后干净退出，绝不拖垮其他 crawler（规格 §二十三）
        if report_dir is not None and not dry_run:
            report.save(report_dir)
        return report

    existing = load_manifest(manifest_path)
    # 只与公众号自己的历史文档做 exact text_hash 去重（§三十一）：
    # 官网政策/解读类文档即使文本相近也不参与，避免跨来源误删（§十七）。
    wechat_text_hashes = {
        m.text_hash: m.doc_id
        for m in existing.values()
        if m.source_type == "official_wechat" and m.text_hash
    }

    # 逐篇过门；accepted 的按账号分组后批量走现有 ingest 管线
    accepted: dict[str, list[tuple[WechatArticle, DiscoveredArticle, WechatAccount, str]]] = {}
    seen_keys: set[str] = set()
    for item in result.articles:
        url = item.url
        # 1) 白名单预检（发现层带了账号名时）；不带账号名的种子留到抓取后按页面账号复检
        account = match_account(item.account, accounts) if item.account else None
        if item.account and account is None:
            report.reject("not_whitelisted")
            report.decide(
                url,
                item.title,
                "reject",
                "not_whitelisted",
                account=item.account,
                topic=classify_topic(item.title),
            )
            continue
        # 2) 时间窗预检（发现层带了日期时）
        if item.publish_date:
            ok, reason = date_gate(
                item.publish_date, force_include=item.force_include, min_date=min_date
            )
            if not ok:
                report.reject("too_old")
                report.decide(
                    url,
                    item.title,
                    "reject",
                    "too_old",
                    date=item.publish_date,
                    topic=classify_topic(item.title),
                )
                continue
        # 3) 标题强排除预检（省一次正文获取）；排除词与招生信号同现的标题延后到正文判定
        if item.title:
            pre = relevance_check(item.title)
            if not pre.keep and pre.reason == "strong_exclude":
                report.reject("news_noise")
                report.decide(
                    url,
                    item.title,
                    "reject",
                    "news_noise",
                    keyword=pre.matched_keyword,
                    topic=classify_topic(item.title),
                )
                continue

        # 4) 正文来源（规格 §十/§十一）：WeRSS 已存正文优先 normalize；
        #    无正文或 normalize 失败才回源 mp.weixin.qq.com
        article: WechatArticle | None = None
        if item.has_content:
            candidate = parse_wechat_content(
                item.content_html,
                item.url,
                title=item.title,
                account=item.account,
                publish_date=item.publish_date,
                content_text=item.content_text,
            )
            if candidate.status == "ok":
                article = candidate
                report.direct_content += 1
        if article is None:
            article = fetcher.fetch(url)
            if article.status != "ok":
                report.fetch_failed += 1
                report.reject("fetch_failed")
                report.decide(
                    url,
                    item.title,
                    "reject",
                    "fetch_failed",
                    status=article.status,
                    error=article.error,
                    topic=classify_topic(item.title),
                )
                continue
            report.fetch_ok += 1

        # 5) 白名单复检：以页面内 account_name 为准（规格 §九，防止种子标注造假）
        account = match_account(article.account_name, accounts)
        if account is None:
            report.reject("not_whitelisted")
            report.decide(
                article.source_url,
                article.title,
                "reject",
                "not_whitelisted",
                account=article.account_name,
                topic=classify_topic(article.title, article.body_markdown),
            )
            continue
        report.whitelist_passed += 1

        # 6) 时间窗复检（以页面 createTime 为准）
        ok, reason = date_gate(
            article.publish_date, force_include=item.force_include, min_date=min_date
        )
        if not ok:
            report.reject("too_old")
            report.decide(
                article.source_url,
                article.title,
                "reject",
                "too_old",
                date=article.publish_date,
                topic=classify_topic(article.title, article.body_markdown),
            )
            continue
        report.date_passed += 1

        # 7) 相关性复判：标题 + 正文事实 + 账号（规格 §七：只看事实，不看图片）
        decision = relevance_check(article.title, article.body_markdown)
        if not decision.keep:
            report.reject(decision.reason if decision.reason != "strong_exclude" else "news_noise")
            report.decide(
                article.source_url,
                article.title,
                "reject",
                decision.reason if decision.reason != "strong_exclude" else "news_noise",
                keyword=decision.matched_keyword,
                topic=classify_topic(article.title, article.body_markdown),
            )
            continue
        report.relevance_passed += 1

        if len(_squash(article.body_markdown)) < _EMPTY_BODY_CHARS:
            report.empty_body += 1

        # 8) 去重：canonical 身份 + exact text_hash（规格 §十七/§三十一：只按精确
        #    哈希去重，不做语义去重；官网政策与公众号解读即使相近也都保留）
        topic = classify_topic(article.title, article.body_markdown)
        if article.doc_key in seen_keys:
            report.duplicate += 1
            report.reject("duplicate")
            report.decide(article.source_url, article.title, "reject", "duplicate", topic=topic)
            continue
        seen_keys.add(article.doc_key)
        doc_id = doc_id_from(article.canonical_url)
        text_hash = sha256_text(_squash(article.body_markdown))
        # text_hash 命中同一 doc_id 是“原地更新/未变化”，交给 ingest 管线判 unchanged；
        # 只有命中不同 doc_id（另一 URL 同文）才算重复。
        if text_hash and wechat_text_hashes.get(text_hash) not in (None, doc_id):
            report.duplicate += 1
            report.reject("duplicate")
            report.decide(
                article.source_url, article.title, "reject", "duplicate_text_hash", topic=topic
            )
            continue
        if text_hash:
            wechat_text_hashes[text_hash] = doc_id

        kind = classify_wechat_kind(article.title, article.body_markdown)
        accepted.setdefault(account.account_id, []).append((article, item, account, kind))

    # 9) 按账号分组走现有质量门/生命周期/入库管线
    accepted_pairs: list[tuple[WechatArticle, DiscoveredArticle, str]] = []
    for account_id, rows in accepted.items():
        account = rows[0][2]
        crawled_batch: list[CrawledArticle] = []
        for article, item, _, kind in rows:
            crawled_batch.append(
                _to_crawled(article, item, document_kind=kind, publisher=account.publisher)
            )
        ingest_report = CrawlReport(host=f"wechat:{account.account_name}")
        stats = ingest_crawled_articles(
            crawled_batch,
            category=account.category,
            corpus_dir=corpus_dir,
            manifest_path=manifest_path,
            relations_path=relations_path,
            raw_dir=None if dry_run else raw_dir,
            report=ingest_report,
            dry_run=dry_run,
            source_type="official_wechat",
            source_section=account.account_name,
            scope_unit=account.scope_unit,
            time_policy="all_history",
            evaluated_at=evaluated_at,
        )
        report.quality_accepted += (
            stats.count("new") + stats.count("updated") + stats.count("unchanged")
        )
        report.quality_rejected += stats.count("rejected") + stats.count("quarantined")
        row_by_doc = {doc_id_from(a.canonical_url): (a, i, k) for a, i, _, k in rows}
        for d in stats.decisions:
            row = row_by_doc.get(d.doc_id)
            if row is None:
                continue
            article, item, kind = row
            topic = classify_topic(article.title, article.body_markdown)
            if d.action in {"new", "updated", "unchanged"}:
                report.decide(
                    article.source_url,
                    article.title,
                    "accept",
                    d.action,
                    date=article.publish_date,
                    account=article.account_name,
                    document_kind=kind,
                    body_chars=len(_squash(article.body_markdown)),
                    topic=topic,
                    doc_id=d.doc_id,
                )
                accepted_pairs.append((article, item, d.doc_id))
            else:
                report.reject("quality_" + d.action)
                report.decide(
                    article.source_url,
                    article.title,
                    "reject",
                    d.action,
                    detail=d.reason,
                    topic=topic,
                )
    report.indexed_candidate = report.quality_accepted

    # 回填 accepted 文档的 retention（供 topic_stats 的 historical 计数）
    if not dry_run:
        final_manifest = load_manifest(manifest_path)
        for row in report.decisions:
            if row["decision"] == "accept" and row.get("doc_id"):
                meta = final_manifest.get(row["doc_id"])
                if meta is not None:
                    row["retention"] = meta.retention_status

    # 10) canonical 关联：公众号解读 explains 官网正式文档（规格 §十六）
    if accepted_pairs and not dry_run:
        relations = _explains_relations(accepted_pairs, manifest_path)
        if relations:
            append_relations(relations_path, relations)
            report.notes.append(f"建立 explains 关系 {len(relations)} 条")

    if report_dir is not None and not dry_run:
        path = report.save(report_dir)
        report.notes.append(f"报告: {path}")
    return report
