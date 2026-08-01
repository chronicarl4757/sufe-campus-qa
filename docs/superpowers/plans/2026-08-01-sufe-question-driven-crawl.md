# 上财问题覆盖驱动采集系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以固定学生问题为分母，完成教务处、学生处、研究生院的适配式采集、附件/版本/关系管理、主问答与公示双 collection、30 条垂直切片评测，并为后续 P0/P1 站点提供可复用框架。

**Architecture:** Adapter 只发现栏目和解析页面语义；通用 orchestrator 负责 SafeFetcher、分页调度、附件下载/解析、质量门和入库。`DocMeta` 保存来源、用途、版本和证据，`relations.jsonl` 保存多父关系。Indexer 按显式 allowlist 写入 `sufe_qa_main_v2` 与 `sufe_qa_public_list_v2`，retriever/BM25 按 collection 隔离。覆盖审计使用固定 150 条探针，正式 `evalset.v2` 只有人工确认条目才进入门禁。

**Tech Stack:** Python 3.13/3.11, uv, pytest, ruff, BeautifulSoup, httpx, PyMuPDF/python-docx, ChromaDB, rank-bm25/jieba, YAML/JSONL。

---

## File map

- Create `src/sufe_qa/crawler/adapters/models.py`: `SectionSpec`、`PageSpec`、`PageContent`、`ListingResult`、`ArticleSpec`、`DocumentCandidate`。
- Create `src/sufe_qa/crawler/adapters/protocol.py`: `SiteAdapter` protocol 与 adapter 错误。
- Create `src/sufe_qa/crawler/adapters/base.py`: `BaseAdapter` 的 URL、导航、日期和分类辅助。
- Create `src/sufe_qa/crawler/adapters/wp3.py`: 通用 `_wp3` adapter。
- Create `src/sufe_qa/crawler/adapters/jwc.py`: 教务处特殊 adapter。
- Create `src/sufe_qa/crawler/adapters/graduate_school.py`: 研究生院自建站 adapter。
- Create `src/sufe_qa/crawler/adapters/business_school.py`: 商学院自建站 adapter，供后续扩展。
- Create `src/sufe_qa/crawler/adapters/career.py`: 就业平台手续页 adapter，供后续扩展。
- Create `src/sufe_qa/crawler/adapters/nic_service.py`: 网络中心服务卡片 adapter，供后续扩展。
- Create `src/sufe_qa/crawler/adapters/registry.py`: adapter 注册和 seed 配置解析。
- Create `src/sufe_qa/crawler/orchestrator.py`: adapter → 通用请求/附件/入库的流水线。
- Modify `src/sufe_qa/schema.py`, `src/sufe_qa/ingest/pipeline.py`, `src/sufe_qa/ingest/quality.py`: 元数据、关系、类型和版本字段。
- Create `src/sufe_qa/ingest/classification.py`, `src/sufe_qa/ingest/versioning.py`: `document_kind`、`topic_key` 和带证据的版本关系。
- Create `src/sufe_qa/indexing/collections.py`; modify `src/sufe_qa/indexing/indexer.py`, `src/sufe_qa/config.py`: 双 collection、迁移、fingerprint、原子 full rebuild。
- Modify `src/sufe_qa/retrieve/retriever.py`, `src/sufe_qa/cli.py`: collection 路由和独立 BM25。
- Create `src/sufe_qa/coverage/question_bank.py`, `src/sufe_qa/coverage/audit.py`, `src/sufe_qa/coverage/evidence.py`, `src/sufe_qa/coverage/reports.py`: 固定题库、确定性检查、证据化结果和覆盖报告。
- Create `data/sources/sufe_authoritative_sources.yaml`、`data/eval/sufe_question_bank.jsonl`、`data/eval/evalset.v2.jsonl`；modify `seeds.yaml`。
- Generate `data/coverage/sufe_coverage_before.{json,md}`、`data/coverage/sufe_coverage_after.{json,md}`、`data/crawl_reports/sufe_full_report.json`、`data/crawl_reports/sufe_missing_sources.json`。
- Add tests under `tests/test_adapters_*.py`, `tests/test_coverage_*.py`, `tests/test_collections.py`, `tests/test_versioning.py`, `tests/test_question_bank.py`; extend existing schema/index/retriever/CLI/pipeline tests.

## Task 1: 固定题库数据契约与 150 条覆盖探针

**Files:**
- Create: `src/sufe_qa/coverage/__init__.py`, `src/sufe_qa/coverage/question_bank.py`
- Create: `tests/test_question_bank.py`
- Create: `data/eval/sufe_question_bank.jsonl`

- [ ] **Step 1: Write the failing test**

```python
def test_question_bank_has_fixed_scene_quota_and_required_fields():
    items = load_question_bank(Path("data/eval/sufe_question_bank.jsonl"))
    assert len(items) == 150
    assert Counter(x.scene for x in items) == Counter({
        "本科教务": 20, "研究生培养与学位": 20, "奖助学金": 15,
        "推免与招生": 15, "就业手续": 15, "宿舍后勤": 10,
        "信息化与校园卡": 15, "图书馆": 10, "医疗医保": 10,
        "国际交流": 10, "新生与安全": 10,
    })
    assert all(x.status == "unverified" for x in items)
    assert all(x.required_answer_points and x.expected_domains for x in items)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_question_bank.py::test_question_bank_has_fixed_scene_quota_and_required_fields -q`

Expected: FAIL because `sufe_qa.coverage.question_bank` and the new JSONL do not exist.

- [ ] **Step 3: Write minimal implementation**

Implement a frozen `QuestionProbe` dataclass and `load_question_bank(path)` that validates unique IDs, exact scene quotas, non-empty `required_answer_points`, `expected_domains`, and one of `unverified/verified/blocked`. Add the 150 fixed questions from the user’s scenario list; use `status: unverified`, `expected_doc_ids: []` until source-backed curation.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_question_bank.py -q`

Expected: PASS with the exact 150-row quota.

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/coverage tests/test_question_bank.py data/eval/sufe_question_bank.jsonl
git commit -m "feat: add fixed SUFE coverage question bank"
```

## Task 2: 基线覆盖审计（必须在任何新站点抓取前完成）

**Files:**
- Create: `tests/test_coverage_audit.py`
- Create: `src/sufe_qa/coverage/audit.py`, `src/sufe_qa/coverage/reports.py`
- Modify: `src/sufe_qa/cli.py`
- Generate: `data/coverage/sufe_coverage_before.json`, `data/coverage/sufe_coverage_before.md`

- [ ] **Step 1: Write the failing test**

```python
def test_audit_uses_question_bank_hash_as_fixed_denominator(tmp_path):
    report = audit_manifest(
        manifest_path=tmp_path / "manifest.jsonl",
        corpus_dir=tmp_path / "corpus",
        question_bank_path=Path("data/eval/sufe_question_bank.jsonl"),
        retriever_config={"similarity_threshold": 0.5},
        index_fingerprint="legacy-test",
    )
    assert report.question_bank_version == "sufe-question-bank.v1"
    assert report.question_bank_hash
    assert report.scene_stats["本科教务"].question_count == 20
    assert report.evaluated_at
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_coverage_audit.py::test_audit_uses_question_bank_hash_as_fixed_denominator -q`

Expected: FAIL with missing `audit_manifest`.

- [ ] **Step 3: Write minimal implementation**

Implement `audit_manifest()` to load last-wins manifest rows, classify accepted policy/procedure/guide, incomplete, news/promotion and version status, then evaluate every fixed probe through a deterministic corpus evidence provider. Store `question_bank_version`, SHA-256 hash, retriever config, embedding model, threshold, index fingerprint, `evaluated_at`, per-scene counts and every question result. Render the same structure to Markdown, including missing authoritative domains.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_coverage_audit.py -q`

Expected: PASS and stable hash assertions.

- [ ] **Step 5: Generate the required baseline before changing seeds or crawling**

Run:

```bash
uv run sufe-qa coverage-audit --question-bank data/eval/sufe_question_bank.jsonl \
  --manifest data/corpus/manifest.jsonl --corpus data/corpus \
  --output-json data/coverage/sufe_coverage_before.json \
  --output-md data/coverage/sufe_coverage_before.md
```

Expected: both files exist and contain all 150 question rows, fixed scene denominators, current manifest statistics, missing domains and the legacy index fingerprint. Do not invoke any crawl command before this step completes.

- [ ] **Step 6: Commit**

```bash
git add src/sufe_qa/coverage src/sufe_qa/cli.py tests/test_coverage_audit.py data/coverage/sufe_coverage_before.json data/coverage/sufe_coverage_before.md
git commit -m "feat: generate fixed-denominator SUFE baseline coverage audit"
```

## Task 3: 类型、来源、版本证据和多父关系模型

**Files:**
- Create: `tests/test_versioning.py`, `src/sufe_qa/ingest/classification.py`, `src/sufe_qa/ingest/versioning.py`
- Modify: `src/sufe_qa/schema.py`, `src/sufe_qa/ingest/quality.py`, `src/sufe_qa/ingest/pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_year_only_does_not_supersede_previous_policy():
    relations = infer_version_relations([
        Candidate(title="2024年学生奖学金办法", body="管理办法正文"),
        Candidate(title="2025年学生奖学金办法", body="年度安排正文"),
    ])
    assert all(r.status == "unknown_validity" for r in relations)
    assert not any(r.relation == "supersedes" for r in relations)

def test_explicit_effective_and_repeal_words_produce_evidence():
    result = infer_version_relations([
        Candidate(title="学生奖学金办法（修订）", body="自2025年9月1日起施行，同时废止原办法。"),
        Candidate(title="学生奖学金办法", body="原办法正文"),
    ])[0]
    assert result.relation == "supersedes"
    assert result.confidence >= 0.9
    assert "同时废止" in result.evidence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_versioning.py -q`

Expected: FAIL because version evidence and relation inference do not exist.

- [ ] **Step 3: Implement the minimal model changes**

Add backward-compatible default fields to `DocMeta`, explicit `MAIN_QA_KINDS`/`PUBLIC_LIST_KINDS`/`ARCHIVED_KINDS`, `source_type`, `document_kind`, `topic_key`, `policy_name`, `scope_unit`, `validity_status`, confidence/evidence fields and `index_collection`. Add relation evidence fields while retaining `parent_doc_id` as a display shortcut. Implement title normalization and explicit-evidence version inference; year-only candidates remain `unknown_validity`.

- [ ] **Step 4: Run the focused and regression tests**

Run: `uv run pytest tests/test_schema.py tests/test_quality.py tests/test_versioning.py -q`

Expected: all existing schema/quality tests and the new version tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/schema.py src/sufe_qa/ingest/classification.py src/sufe_qa/ingest/versioning.py src/sufe_qa/ingest/quality.py src/sufe_qa/ingest/pipeline.py tests/test_versioning.py
git commit -m "feat: add explicit document types and evidence-backed version metadata"
```

## Task 4: 双 collection、迁移和独立 BM25

**Files:**
- Create: `tests/test_collections.py`, `src/sufe_qa/indexing/collections.py`
- Modify: `src/sufe_qa/config.py`, `src/sufe_qa/indexing/indexer.py`, `src/sufe_qa/retrieve/retriever.py`, `src/sufe_qa/cli.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_document_kind_routes_to_explicit_collection():
    assert collection_for_kind("policy") == "main_qa"
    assert collection_for_kind("public_list") == "public_list"
    assert collection_for_kind("news") == "none"
    assert collection_for_kind("incomplete") == "none"

def test_retriever_defaults_to_main_and_public_is_opt_in(tmp_path):
    settings = test_settings(tmp_path)
    write_manifest_with_policy_and_public_list(settings)
    update_index(settings, FakeEmbedder(), full=True)
    main = HybridRetriever(settings, FakeEmbedder())
    assert all(hit.metadata["index_collection"] == "main_qa" for hit in main.search("名单"))
    public = HybridRetriever(settings, FakeEmbedder(), collection="public_list")
    assert all(hit.metadata["index_collection"] == "public_list" for hit in public.search("名单"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_collections.py -q`

Expected: FAIL because the collection router and collection-aware retriever do not exist.

- [ ] **Step 3: Implement minimal collection routing**

Create `CollectionNames`, `collection_for_kind`, manifest fingerprinting and `IndexMetadata`. Update indexer to group accepted documents by `index_collection`, write separate Chroma collections and store `index_collection` in chunk metadata. Update retriever to load one BM25 corpus per collection and accept `collection="main_qa"` by default. Add explicit CLI/API route for `public_list`; preserve legacy collection as read-only migration input.

- [ ] **Step 4: Implement atomic full rebuild and migration report**

Build in a sibling temporary directory, write both collections plus `index_metadata.json`, close the client, rename the old directory to a timestamped backup, then rename the temporary directory into place; on any exception restore the old directory. Save migrated/isolated counts and old/new fingerprints in the crawl/index report. Never delete the old collection before the new build is complete.

- [ ] **Step 5: Run focused and regression tests**

Run: `uv run pytest tests/test_collections.py tests/test_indexer.py tests/test_retrieve.py tests/test_cli.py -q`

Expected: all collection isolation tests and existing index/retrieval/CLI tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/sufe_qa/config.py src/sufe_qa/indexing src/sufe_qa/retrieve/retriever.py src/sufe_qa/cli.py tests/test_collections.py
git commit -m "feat: separate main QA and public-list indexes"
```
## Task 5: Adapter 数据契约与通用 `_wp3`

**Files:**
- Create: `src/sufe_qa/crawler/adapters/__init__.py`, `models.py`, `protocol.py`, `base.py`, `wp3.py`
- Create: `tests/test_adapters_wp3.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_wp3_listing_reads_total_pages_and_article_links():
    adapter = Wp3Adapter(site_name="教务处", publisher="上海财经大学教务处")
    result = adapter.parse_listing(PageContent.from_text(WP3_PAGE_1), section)
    assert result.total_pages == 5
    assert result.total_records == 61
    assert result.next_url.endswith("/5127/list2.htm")
    assert result.article_specs[0].url.endswith("c5127a267652/page.htm")

def test_adapter_never_downloads_or_writes_documents():
    assert not any(name in Wp3Adapter.__dict__ for name in ("fetch", "write_manifest", "download_attachment"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_adapters_wp3.py -q`

Expected: FAIL because the adapter package and page models are absent.

- [ ] **Step 3: Implement minimal models and Wp3 behavior**

Define frozen/dataclass models with explicit fields and a `SiteAdapter` protocol matching the design. `BaseAdapter` provides same-host URL normalization, date normalization, section/category mapping and safe title helpers. `Wp3Adapter` discovers navigation `list.htm` URLs from the homepage, parses `listN.htm`, current/total page markers, total record markers and article links from the content container only. It emits `ArticleSpec` and attachment candidates; no network or filesystem side effects.

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest tests/test_adapters_wp3.py -q && uv run ruff check src/sufe_qa/crawler/adapters tests/test_adapters_wp3.py`

Expected: PASS and no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/crawler/adapters tests/test_adapters_wp3.py
git commit -m "feat: add side-effect-free adapter contract and wp3 parser"
```

## Task 6: 教务处 `JwcAdapter`

**Files:**
- Create: `src/sufe_qa/crawler/adapters/jwc.py`, `tests/test_adapters_jwc.py`
- Add fixtures: `tests/fixtures/jwc_main.html`, `jwc_5124.html`, `jwc_5127_page1.html`, `jwc_5127_page2.html`, `jwc_5145.html`
- Modify: `src/sufe_qa/crawler/adapters/registry.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_jwc_discovers_real_sections_and_data_source_evidence():
    sections = JwcAdapter().discover_sections(PageContent.from_file("tests/fixtures/jwc_main.html"))
    ids = {s.section_id for s in sections}
    assert {"5123", "5124", "5126", "5127"} <= ids
    assert any(e.kind == "navigation_static" for e in adapter.discovery_evidence)

def test_jwc_5124_emits_direct_pdf_doc_xls_attachment_specs():
    article = JwcAdapter().parse_article(PageContent.from_file("tests/fixtures/jwc_5124.html"), page_spec)
    names = {a.anchor_text for a in article.attachments}
    assert {"选课", "重修", "休学申请表", "课程考试缓考申请", "上海财经大学学生证补发申请表"} <= names
    assert all(a.url.startswith("https://jwc.sufe.edu.cn/") for a in article.attachments)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_adapters_jwc.py -q`

Expected: FAIL because JwcAdapter and its section discovery do not exist.

- [ ] **Step 3: Implement minimal JWC adapter**

Subclass `Wp3Adapter`. Discover `/main.htm` navigation and retain student-facing sections (`5123`, `5124`, `5126`, `5127`, plus their actual child sections). Record evidence for embedded JSON/generalQuery, `_wp3` static list, sitemap probe, search endpoint and navigation links. For `5124` treat the page as an attachment index, preserving the business subsection text; for `5123/5145/5126` parse direct attachment links and normal article links. Support list pages with `listN.htm`, total records/pages and no fixed 20-article cap. If a public `generalQuery` payload is present, parse it; otherwise report `data_source=wp3_static_navigation` rather than claiming JS failure.

- [ ] **Step 4: Run fixtures and regression tests**

Run: `uv run pytest tests/test_adapters_jwc.py tests/test_article_pagination.py tests/test_attachment_parsers.py -q`

Expected: PASS, including direct legacy DOC/XLS candidates and the existing iframe/download parser tests.

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/crawler/adapters/jwc.py src/sufe_qa/crawler/adapters/registry.py tests/test_adapters_jwc.py tests/fixtures/jwc_*.html
git commit -m "feat: add JWC navigation and procedure adapter"
```

## Task 7: 学生处全部制度/通知分页

**Files:**
- Add fixtures: `tests/fixtures/xsc_5436_page1.html`, `xsc_5437_page1.html`, `xsc_5437_page2.html`, `xsc_5450_page1.html`
- Create: `tests/test_xsc_vertical_slice.py`
- Modify: `seeds.yaml`, `data/sources/sufe_authoritative_sources.yaml`

- [ ] **Step 1: Write the failing test**

```python
def test_xsc_vertical_sections_include_all_pages_and_policy_kind():
    sections = load_seed_sections("xsc")
    assert {"5436", "5437", "5450"} <= {s.section_id for s in sections}
    pages = list(iter_fixture_pages("xsc_5437_page1.html"))
    assert pages[-1].url.endswith("/5437/list2.htm")
    docs = classify_listing_fixture("xsc_5437_page1.html")
    assert all(d.document_kind in {"policy", "procedure", "annual_notice", "public_list"} for d in docs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_xsc_vertical_slice.py -q`

Expected: FAIL because the new source manifest and full-page seed configuration do not exist.

- [ ] **Step 3: Implement configuration and classification**

Add the students-office source with `official_department`, `all_history` for policy/institution sections, `recent_5_academic_years` for annual notices and `recent_2_academic_years` for public lists. Configure `/5436/list.htm`, `/5437/list.htm`, `/5450/list.htm` and allow the adapter to follow `list2.htm` until the reported last page. Preserve policy rows and annual notices as separate document kinds; public lists route only to `public_list`.

- [ ] **Step 4: Run data-contract tests**

Run: `uv run pytest tests/test_xsc_vertical_slice.py tests/test_config.py tests/test_crawl.py -q`

Expected: PASS without changing the old seed loader API for legacy tests.

- [ ] **Step 5: Commit**

```bash
git add seeds.yaml data/sources/sufe_authoritative_sources.yaml tests/test_xsc_vertical_slice.py tests/fixtures/xsc_*.html
git commit -m "feat: configure complete student-affairs policy sources"
```

## Task 8: 研究生院全导航与附件集合页

**Files:**
- Create: `src/sufe_qa/crawler/adapters/graduate_school.py`, `tests/test_adapters_graduate_school.py`
- Add fixtures: `tests/fixtures/gs_home.html`, `gs_list_35_page1.html`, `gs_list_35_page2.html`, `gs_detail_policy.html`, `gs_detail_attachment_set.html`
- Modify: `src/sufe_qa/crawler/adapters/registry.py`, `seeds.yaml`

- [ ] **Step 1: Write the failing tests**

```python
def test_graduate_school_discovers_all_student_business_sections():
    sections = GraduateSchoolAdapter().discover_sections(homepage)
    names = {s.name for s in sections}
    assert {"招生简章", "培养管理制度", "学籍管理", "办事程序", "学位管理规定", "短期交流", "常见问答", "下载专区"} <= names

def test_attachment_set_inherits_parent_metadata_and_keeps_each_child():
    article = adapter.parse_article(attachment_set_page, spec)
    assert len(article.attachments) >= 2
    assert all(a.parent_title == article.title for a in article.attachments)
    assert all(a.parent_url == article.url for a in article.attachments)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_adapters_graduate_school.py -q`

Expected: FAIL because the custom `/Home/List/<id>` adapter is absent.

- [ ] **Step 3: Implement the graduate-school adapter**

Parse the homepage navbar into all required section IDs, not only the existing three seeds. Parse custom list pagination and article links. For empty-body articles with attachment links, iframe/embed/object or attachment collections, emit each attachment candidate with parent title, section, publish date, publisher, parent URL and attachment name. Let the generic engine download and parse the child; the adapter does not write relations itself.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_adapters_graduate_school.py tests/test_engine_pipeline.py -q`

Expected: PASS, including the pre-existing iframe viewer and parent/child ingestion tests.

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/crawler/adapters/graduate_school.py src/sufe_qa/crawler/adapters/registry.py seeds.yaml tests/test_adapters_graduate_school.py tests/fixtures/gs_*.html
git commit -m "feat: crawl all graduate-school business sections and attachment sets"
```

## Task 9: 通用 orchestrator、报告和 vertical seed

**Files:**
- Create: `src/sufe_qa/crawler/orchestrator.py`, `tests/test_orchestrator.py`
- Modify: `src/sufe_qa/crawler/engine.py`, `src/sufe_qa/crawler/state.py`, `src/sufe_qa/crawler/registry.py`, `src/sufe_qa/cli.py`, `seeds.yaml`

- [ ] **Step 1: Write the failing test**

```python
def test_orchestrator_uses_adapter_for_pages_and_generic_engine_for_attachments(tmp_path):
    report = crawl_adapter_sections(
        adapter=FixtureAdapter(), fetcher=StubFetcher(routes), output=tmp_path,
        write=False,
    )
    assert report.adapter == "fixture"
    assert report.list_pages_fetched == 2
    assert report.attachments_found == 1
    assert report.manifest_writes == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -q`

Expected: FAIL because adapter orchestration and adapter-aware report fields do not exist.

- [ ] **Step 3: Implement the orchestrator**

Schedule homepage/section/list/article PageSpecs through the existing `SafeFetcher`; call adapter methods only on `PageContent`; pass `ArticleSpec` to the existing attachment engine and `ingest_crawled_articles`. Add stop reasons, adapter discovery evidence, blocked URLs, per-section pages, article/attachment/parser counts, quality counts, and source metadata to `CrawlReport`. Add `--adapter`, `--scope vertical`, `--dry-run`, `--since`, `--report-json` without removing legacy `crawl` flags.

- [ ] **Step 4: Run the complete crawler test slice**

Run: `uv run pytest tests/test_orchestrator.py tests/test_engine_pipeline.py tests/test_crawl.py tests/test_fetcher.py -q`

Expected: PASS with no writes in dry-run.

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/crawler src/sufe_qa/cli.py seeds.yaml tests/test_orchestrator.py
git commit -m "feat: orchestrate adapter-driven crawl with complete reports"
```
## Task 10: 证据化问题评测与候选 `evalset.v2`

**Files:**
- Create: `src/sufe_qa/coverage/evidence.py`, `tests/test_coverage_evidence.py`
- Modify: `src/sufe_qa/coverage/audit.py`, `src/sufe_qa/evals/scorer.py`, `src/sufe_qa/cli.py`
- Create: `data/eval/evalset.v2.jsonl` with `curation_status: agent_candidate`

- [ ] **Step 1: Write the failing test**

```python
def test_question_result_preserves_point_evidence_and_does_not_mutate_probe():
    probe = QuestionProbe.from_dict(SAMPLE_PROBE)
    result = evaluate_probe(probe, hits=[policy_hit, attachment_hit])
    assert result.status == "partially_answerable"
    assert result.point_evidence[0].evidence_doc_id == attachment_hit.doc_id
    assert result.point_evidence[0].checker == "deterministic"
    assert probe.expected_doc_ids == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_coverage_evidence.py -q`

Expected: FAIL because evidence-bearing probe evaluation is absent.

- [ ] **Step 3: Implement two-layer evaluation**

Implement deterministic checks for expected domains, source type, document kind, collection, validity, attachment relation and doc IDs. For each answer point, store `supported/unsupported/uncertain`, evidence chunk/doc ID, a short evidence excerpt, reason, confidence and checker name. Add an optional model checker interface that can only add evidence; it cannot mutate the question bank or expected docs. Emit 30 vertical-slice candidate rows into `evalset.v2.jsonl` with `curation_status=agent_candidate`, `status=unverified` and source evidence for later human review.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_coverage_evidence.py tests/test_evals.py -q`

Expected: PASS; existing formal v1 behavior remains unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/sufe_qa/coverage src/sufe_qa/evals src/sufe_qa/cli.py tests/test_coverage_evidence.py data/eval/evalset.v2.jsonl
git commit -m "feat: add evidence-backed question coverage evaluation"
```

## Task 11: 首个垂直切片的公开 dry-run 与 baseline/after 数据

**Files:**
- Generate: `data/crawl_reports/vertical-dry-run.json`
- Generate: `data/coverage/sufe_coverage_before.json`, `sufe_coverage_before.md`
- Modify only through generated ingestion outputs: `data/corpus`, `data/crawl_reports`

- [ ] **Step 1: Validate seed and source contracts before network writes**

Run:

```bash
uv run sufe-qa crawl --scope vertical --dry-run --report-json --delay 1.0
```

Expected: JWC/XSC/GS sections are discovered; JWC reports navigation/static-list or public-interface evidence; XSC reports all pages of `5437`; GS reports all discovered business sections; no corpus, manifest or index files change.

- [ ] **Step 2: Run the vertical crawl with attachments**

Run:

```bash
uv run sufe-qa crawl --scope vertical --report-json --delay 1.0 --max-attachment-bytes 30000000
```

Expected: only public sources are requested; failures are structured; direct PDF/DOC/XLS and iframe/download endpoints are counted; `incomplete` parents are not accepted into main QA.

- [ ] **Step 3: Build the v2 collections**

Run:

```bash
uv run sufe-qa index --full
```

Expected: `sufe_qa_main_v2` and `sufe_qa_public_list_v2` are built in an atomic snapshot; `index_metadata.json` contains a fingerprint; no news/event/promotion/incomplete document is present in either queryable collection.

- [ ] **Step 4: Run the fixed 30-question vertical evaluation**

Run:

```bash
uv run sufe-qa coverage-eval --question-bank data/eval/sufe_question_bank.jsonl \
  --limit-scenes "本科教务,研究生培养与学位,奖助学金" \
  --limit-per-scene 10 --collection main_qa \
  --output-json data/coverage/sufe_coverage_after.json \
  --output-md data/coverage/sufe_coverage_after.md
```

Expected: report contains the same metadata fields as before, 30 rows, point evidence, collection/domain checks, missing reasons and quality-gate metrics. If a source is blocked, report it; do not lower the threshold.

- [ ] **Step 5: Run the vertical quality gate**

Run: `uv run sufe-qa coverage-gate --report data/coverage/sufe_coverage_after.json --profile vertical`

Expected: command exits non-zero if正文比例、附件成功率、incomplete、污染率、重复率、unknown_validity、wrong-domain hits or collection cross-contamination exceed configured thresholds; it prints each failing metric and source.

- [ ] **Step 6: Commit generated vertical outputs**

```bash
git add data/corpus data/coverage data/crawl_reports data/eval/evalset.v2.jsonl
git commit -m "data: crawl and evaluate JWC XSC GS vertical slice"
```

## Task 12: 定向补抓与三站点人工抽查清单

**Files:**
- Create: `data/crawl_reports/sufe_missing_sources.json`
- Create: `data/coverage/vertical_manual_review.md`
- Modify: `src/sufe_qa/coverage/reports.py` only if a missing reason is not evidence-backed

- [ ] **Step 1: Generate the missing-source report**

Run: `uv run sufe-qa missing-sources --coverage data/coverage/sufe_coverage_after.json --output data/crawl_reports/sufe_missing_sources.json`

Expected: every partial/not-answerable question includes the missing answer point, expected authoritative domain, attempted doc IDs, source status, attachment failure or version ambiguity.

- [ ] **Step 2: Run only source-directed retries**

For each missing source, add or refine the exact section/endpoint in the adapter configuration, then run the corresponding adapter with `--dry-run` before the narrow crawl. Do not add broad homepage selectors or unrelated学院 seeds. Every retry must have a changed URL/selector/adapter path from the prior failure.

- [ ] **Step 3: Produce the 30-question manual review sheet**

Include for each required question: retrieved doc IDs, title, publisher, publish date, document kind, validity status, attachment flag, point evidence, completeness and human-review checkbox. Keep expected docs and question text immutable.

- [ ] **Step 4: Re-run the vertical gate**

Run: `uv run sufe-qa coverage-eval --question-bank data/eval/sufe_question_bank.jsonl --limit-per-scene 10 --collection main_qa` and then `uv run sufe-qa coverage-gate --report data/coverage/sufe_coverage_after.json --profile vertical`.

Expected: only evidence-supported improvement is accepted; a threshold change or unrelated document does not count as a fix.

## Task 13: 扩展 P0/P1 职能部门和学院细则

**Files:**
- Modify: `src/sufe_qa/crawler/adapters/career.py`, `src/sufe_qa/crawler/adapters/nic_service.py`, `src/sufe_qa/crawler/adapters/business_school.py`, `seeds.yaml`, `data/sources/sufe_authoritative_sources.yaml`
- Add: `tests/test_adapters_career.py`, `tests/test_adapters_nic.py`, `tests/test_p1_wp3_sources.py` and their HTML fixtures.

- [ ] **Step 1: Write failing site-shape tests for each distinct CMS**

```python
def test_career_adapter_keeps_procedure_pages_and_excludes_job_posts():
    items = CareerAdapter().parse_listing(PageContent.from_file("tests/fixtures/career_index.html"), career_section).article_specs
    assert any("就业推荐表" in item.title for item in items)
    assert all("招聘岗位" not in item.title and "宣讲会" not in item.title for item in items)

def test_nic_service_adapter_discovers_student_tabs_and_faq():
    sections = NicServiceAdapter().discover_sections(PageContent.from_file("tests/fixtures/nic_home.html"))
    assert {"统一认证", "校园卡", "无线联网", "VPN"} <= {s.name for s in sections}
    service = NicServiceAdapter().parse_article(PageContent.from_file("tests/fixtures/nic_service.html"), nic_page)
    assert {"操作流程", "常见问题", "客户端下载"} <= {x.label for x in service.service_items}

def test_p1_wp3_source_maps_authority_and_student_scene():
    spec = Wp3Adapter().discover_sections(PageContent.from_file("tests/fixtures/lib_home.html"))[0]
    assert spec.source_type == "official_department"
    assert spec.scene == "图书馆"
```

Run these targeted tests before implementation and confirm they fail because the site-specific parsing is absent.

- [ ] **Step 2: Implement only the site-specific parser layer**

Use `CareerAdapter` for employment procedures and student manuals only; use `NicServiceAdapter(Wp3Adapter)` for “学生服务” cards and tabs; use configured `Wp3Adapter` for library/HQ/disclosure/medical/finance/IECO/security standard pages. Keep recruitment, news, safety publicity and unrelated procurement/teacher content out of the main index.

- [ ] **Step 3: Run each site dry-run and quality gate**

Run each scope explicitly:

```bash
uv run sufe-qa crawl --scope career --dry-run --report-json --delay 1.0
uv run sufe-qa crawl --scope nic --dry-run --report-json --delay 1.0
uv run sufe-qa crawl --scope p1-wp3 --dry-run --report-json --delay 1.0
```

Inspect source discovery evidence and attachment statistics before the corresponding write run. Record inaccessible or login-gated sites in `sufe_missing_sources.json`.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q && uv run ruff check src tests`

Expected: all unit/integration tests pass; any pre-existing warning is documented and no new failure is ignored.

## Task 14: 全量 150 探针、最终报告和交付检查

**Files:**
- Generate: `data/coverage/sufe_coverage_after.json`, `sufe_coverage_after.md`
- Generate: `data/crawl_reports/sufe_full_report.json`, `sufe_missing_sources.json`
- Create: `data/coverage/sufe_version_conflicts.json`, `sufe_low_quality_isolation.json`
- Modify: `README.md` with reproducible crawl/audit/eval commands.

- [ ] **Step 1: Run full crawl in the specified order**

Run the P0/P1 scopes in order, with the configured time boundaries and attachments enabled:

```bash
for scope in vertical career nic library hq-disclosure p1-wp3 colleges; do
  uv run sufe-qa crawl --scope "$scope" --report-json --delay 1.0 --max-attachment-bytes 30000000
done
```

The command must save per-site pages, attachment counts, stop reasons, failures and quality metrics; if a scope is blocked, continue with the next independent public scope and preserve its missing-source record.

- [ ] **Step 2: Rebuild both collections atomically**

Run `uv run sufe-qa index --full` and verify `index_metadata.json`, collection counts, manifest fingerprint and BM25 collection manifests.

- [ ] **Step 3: Evaluate all 150 probes with the same question-bank hash**

Run `uv run sufe-qa coverage-eval --question-bank data/eval/sufe_question_bank.jsonl --collection main_qa --output-json data/coverage/sufe_coverage_after.json --output-md data/coverage/sufe_coverage_after.md`.

Expected: 150 rows with explicit `answerable/partially_answerable/not_answerable`, evidence chunks, domain/type/version/attachment checks and missing reasons. Formal hard-gate statistics use only `evalset.v2` rows whose `curation_status=verified`; the probe result is not silently promoted to formal evaluation.

- [ ] **Step 4: Generate version and low-quality reports**

List every conflicting `topic_key/policy_name`, status, confidence, evidence and documents; list every isolated news/event/promotion/incomplete document with reason and source URL.

- [ ] **Step 5: Run final verification**

Run:

```bash
uv run pytest -q
uv run ruff check src tests
uv run sufe-qa coverage-gate --report data/coverage/sufe_coverage_after.json --profile full
git diff --check
git status --short
```

Expected: tests and lint exit 0; the gate reports actual pass/fail metrics; final status contains only intentional generated/data changes. Do not claim the 120/150 or per-scene thresholds unless the fresh report proves them.

- [ ] **Step 6: Commit final deliverables**

```bash
git add README.md src tests seeds.yaml data
git commit -m "feat: complete question-driven SUFE collection pipeline"
```
