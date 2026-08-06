# Clean SUFE Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a non-destructive data lifecycle pipeline that corrects source dates, identifies annual series, enforces time retention, and keeps yearly duplicates out of the default SUFE QA index.

**Architecture:** Add deterministic date evidence and lifecycle classification before persistence, then route documents by `retention_status` and explicit collection allowlists. Existing data is normalized through a dry-run audit followed by an atomic clean-corpus rebuild; raw HTML, binaries, and relations remain authoritative and untouched.

**Tech Stack:** Python 3.13, dataclasses, BeautifulSoup, pytest, PyYAML, ChromaDB, existing JSONL manifest/relations pipeline.

---

### Task 1: Source-backed publish dates

**Files:**
- Modify: `src/sufe_qa/crawler/article.py`
- Modify: `src/sufe_qa/crawler/adapters.py`
- Modify: `src/sufe_qa/crawler/engine.py`
- Modify: `src/sufe_qa/schema.py`
- Modify: `src/sufe_qa/ingest/pipeline.py`
- Test: `tests/test_article.py`
- Test: `tests/test_adapters.py`
- Test: `tests/test_engine_pipeline.py`

- [ ] **Step 1: Write failing GS date tests**

Add a fixture containing an unrelated sidebar `.info` date and `<p>发布时间：2017-05-09</p>`. Assert `GraduateSchoolAdapter.parse_article()` returns `publish_date == "2017-05-09"`, evidence containing `发布时间`, confidence at least `0.95`, and no conflict.

- [ ] **Step 2: Verify the date test fails**

Run: `uv run pytest tests/test_adapters.py -k publish_date_evidence -q`

Expected: FAIL because the current adapter selects the sidebar date and the model has no evidence fields.

- [ ] **Step 3: Implement date evidence without broad selectors**

Introduce a `DateEvidence` value with `value`, `evidence`, `confidence`, and `conflict`. Make labeled dates outrank selectors and metadata. Remove `.info` and `.time` from `GraduateSchoolAdapter.article_profile.date_selectors`; use `.key-feature p` as the site-specific selector.

- [ ] **Step 4: Persist date evidence through all boundaries**

Add evidence fields to `ArticleMeta`, `ArticleSpec`, `CrawledArticle`, and backward-compatible `DocMeta` defaults. Copy them in article, audit, attachment, and metadata-refresh paths.

- [ ] **Step 5: Run focused and regression tests**

Run: `uv run pytest tests/test_article.py tests/test_adapters.py tests/test_engine_pipeline.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/sufe_qa/crawler/article.py src/sufe_qa/crawler/adapters.py \
  src/sufe_qa/crawler/engine.py src/sufe_qa/schema.py src/sufe_qa/ingest/pipeline.py \
  tests/test_article.py tests/test_adapters.py tests/test_engine_pipeline.py
git commit -m "fix: extract evidence-backed SUFE publish dates"
```

### Task 2: Temporal classification and annual series keys

**Files:**
- Create: `src/sufe_qa/ingest/lifecycle.py`
- Modify: `src/sufe_qa/ingest/classification.py`
- Modify: `src/sufe_qa/schema.py`
- Test: `tests/test_lifecycle.py`
- Test: `tests/test_classification.py`

- [ ] **Step 1: Write failing classification tests**

Cover these cases:

```python
assert classify_document_kind("上海财经大学2025年硕士研究生复试录取办法", body) == "annual_notice"
assert classify_document_kind("上海财经大学研究生学籍管理规定", body) == "policy"
assert classify_document_kind("2024-2025学年第一学期1-4周研究生课程调停课情况公示", body) == "public_list"
assert classify_document_kind("2025年研究生招生宣讲会", body) == "promotion"
```

Assert 2024/2025 editions of the same复试办法 have equal `series_key`, while different学院 or different业务 retain distinct keys.

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest tests/test_lifecycle.py tests/test_classification.py -q`

Expected: FAIL because lifecycle and title-first annual rules do not exist.

- [ ] **Step 3: Implement focused lifecycle types**

Create frozen `LifecycleDecision` with `temporal_class`, `series_key`, `retention_status`, `retention_reason`, and `canonical_doc_id`. Implement title normalization for year, school year, batch, and week ranges without dropping scope-unit names.

- [ ] **Step 4: Fix classification precedence**

Use title-first precedence: public list → promotion/event/news → annual notice → FAQ/form/manual/service/procedure → formal policy. Body keywords may support a decision but cannot promote a year-specific notice to policy.

- [ ] **Step 5: Add backward-compatible schema fields**

Add defaults for all lifecycle fields to `DocMeta` and round-trip tests in `tests/test_schema.py`.

- [ ] **Step 6: Run tests and commit**

Run: `uv run pytest tests/test_lifecycle.py tests/test_classification.py tests/test_schema.py -q`

```bash
git add src/sufe_qa/ingest/lifecycle.py src/sufe_qa/ingest/classification.py \
  src/sufe_qa/schema.py tests/test_lifecycle.py tests/test_classification.py tests/test_schema.py
git commit -m "feat: classify temporal documents into stable series"
```

### Task 3: Enforce section retention policies during ingestion

**Files:**
- Modify: `src/sufe_qa/crawler/adapters.py`
- Modify: `src/sufe_qa/crawler/authority.py`
- Modify: `src/sufe_qa/crawler/authority_runner.py`
- Modify: `src/sufe_qa/ingest/lifecycle.py`
- Modify: `src/sufe_qa/ingest/pipeline.py`
- Modify: `data/sources/sufe_authoritative.yaml`
- Test: `tests/test_authority_sources.py`
- Test: `tests/test_engine_pipeline.py`
- Test: `tests/test_lifecycle.py`

- [ ] **Step 1: Write failing policy-window tests**

Use a fixed evaluation date and assert:

- enduring policy remains active regardless of publication year;
- annual notice older than five school years becomes archived;
- latest annual document in a series becomes active and prior in-window versions become historical;
- public list older than two school years becomes archived;
- recurring timetable public list outside current school year becomes archived.

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest tests/test_lifecycle.py -k retention -q`

Expected: FAIL because `time_policy` is currently parsed but ignored.

- [ ] **Step 3: Implement deterministic retention evaluation**

Consume `SectionSpec.time_policy` and a fixed `evaluated_at` date. Never use wall-clock time inside pure lifecycle functions. Return explicit reasons such as `annual_notice_outside_5_school_year_window`.

- [ ] **Step 4: Wire lifecycle decisions into persistence**

Pass `time_policy` from authority runner to `ingest_crawled_articles`. Future archived documents keep raw and audit metadata but do not create corpus Markdown. Active/historical documents preserve attachments and relations.

- [ ] **Step 5: Configure vertical-slice sections**

Set policy/guide sections to `all_history`, notice sections to `recent_5_school_years`, public-list sections to `recent_2_school_years`, timetable/答辩日程 sections to `current_school_year`, and excluded promotional content to `archive_only` via title rules.

- [ ] **Step 6: Run tests and commit**

Run: `uv run pytest tests/test_authority_sources.py tests/test_lifecycle.py tests/test_engine_pipeline.py -q`

```bash
git add src/sufe_qa/crawler src/sufe_qa/ingest/lifecycle.py src/sufe_qa/ingest/pipeline.py \
  data/sources/sufe_authoritative.yaml tests/test_authority_sources.py \
  tests/test_lifecycle.py tests/test_engine_pipeline.py
git commit -m "feat: enforce source-specific document retention"
```

### Task 4: Clean collection routing and annual canonical selection

**Files:**
- Modify: `src/sufe_qa/config.py`
- Modify: `src/sufe_qa/indexing/collections.py`
- Modify: `src/sufe_qa/indexing/indexer.py`
- Modify: `src/sufe_qa/retrieve/retriever.py`
- Test: `tests/test_collections.py`
- Test: `tests/test_indexer.py`
- Test: `tests/test_retrieve.py`

- [ ] **Step 1: Write failing routing tests**

Assert active accepted main kinds enter `main_qa`, active public lists enter `public_list`, historical valid content enters `historical`, and archived/isolated content enters none. Assert legacy unclassified content is skipped rather than coerced to manual.

- [ ] **Step 2: Write failing canonical-series test**

Create three annual notices with one `series_key`; assert only the canonical active document appears in main while prior in-window versions appear in historical.

- [ ] **Step 3: Verify tests fail**

Run: `uv run pytest tests/test_collections.py tests/test_indexer.py -q`

Expected: FAIL because historical routing and retention gates are absent.

- [ ] **Step 4: Implement explicit three-collection routing**

Add versioned historical collection configuration and route by both `document_kind` and `retention_status`. Remove the incomplete-to-manual compatibility fallback.

- [ ] **Step 5: Isolate BM25 and query routing**

Give historical its own Chroma/BM25 view. Keep default retrieval on main; expose historical only via explicit collection selection or year-intent routing.

- [ ] **Step 6: Run tests and commit**

Run: `uv run pytest tests/test_collections.py tests/test_indexer.py tests/test_retrieve.py -q`

```bash
git add src/sufe_qa/config.py src/sufe_qa/indexing src/sufe_qa/retrieve \
  tests/test_collections.py tests/test_indexer.py tests/test_retrieve.py
git commit -m "feat: isolate historical and annual-series documents"
```

### Task 5: Dry-run quality audit and atomic clean-corpus migration

**Files:**
- Create: `src/sufe_qa/quality/__init__.py`
- Create: `src/sufe_qa/quality/audit.py`
- Create: `src/sufe_qa/quality/migrate.py`
- Modify: `src/sufe_qa/cli.py`
- Test: `tests/test_quality_audit.py`
- Test: `tests/test_clean_migration.py`

- [ ] **Step 1: Write failing audit tests**

Build a small manifest with wrong GS date, three yearly notices, old public lists, active policy, and an unknown legacy document. Assert the report contains per-document before/after fields, reason, canonical ID, and aggregate pollution metrics without modifying source files.

- [ ] **Step 2: Verify audit tests fail**

Run: `uv run pytest tests/test_quality_audit.py -q`

Expected: FAIL because no quality audit module exists.

- [ ] **Step 3: Implement read-only audit**

Load last-wins manifest, re-read raw HTML where available, reclassify lifecycle, and emit JSON/Markdown. Include total/accepted, year-title ratio, duplicate annual series, date conflicts, old annual/public counts, collection contamination, unknown types, and per-document decisions.

- [ ] **Step 4: Write failing migration atomicity tests**

Assert a successful migration swaps a staging corpus and leaves a timestamped backup; injected validation failure leaves the active corpus byte-for-byte unchanged.

- [ ] **Step 5: Implement atomic migration**

Build clean manifest/corpus/relations in staging. Copy active and valid historical documents, keep archived documents as audit rows without corpus files, preserve relations, validate every referenced file/hash, then rename. Never touch `data/raw`.

- [ ] **Step 6: Add CLI commands**

```text
sufe-qa quality-audit --output-json ... --output-md ...
sufe-qa rebuild-clean-corpus --audit ... --apply
```

The rebuild command must refuse to mutate without `--apply`.

- [ ] **Step 7: Run tests and commit**

Run: `uv run pytest tests/test_quality_audit.py tests/test_clean_migration.py tests/test_cli.py -q`

```bash
git add src/sufe_qa/quality src/sufe_qa/cli.py \
  tests/test_quality_audit.py tests/test_clean_migration.py tests/test_cli.py
git commit -m "feat: audit and atomically rebuild clean corpus"
```

### Task 6: Migrate the captured vertical-slice data and verify gates

**Files:**
- Generate: `data/quality/sufe_data_quality_before.json`
- Generate: `data/quality/sufe_data_quality_before.md`
- Generate: `data/quality/sufe_data_quality_after.json`
- Generate: `data/quality/sufe_data_quality_after.md`
- Update: `data/corpus/manifest.jsonl`
- Update: `data/corpus/relations.jsonl`
- Update: `data/crawl_reports/sufe_full_report.json`

- [ ] **Step 1: Run the read-only audit**

Run:

```bash
uv run sufe-qa quality-audit \
  --output-json data/quality/sufe_data_quality_before.json \
  --output-md data/quality/sufe_data_quality_before.md
```

Expected: report reproduces the current yearly-series pollution and records every planned decision.

- [ ] **Step 2: Review safety invariants**

Verify report counts reconcile to last-wins manifest, no active enduring policy is archived solely because of age, every archived attachment remains reachable from raw or a retained relation, and all date corrections cite raw evidence.

- [ ] **Step 3: Apply atomic clean rebuild**

Run:

```bash
uv run sufe-qa rebuild-clean-corpus \
  --audit data/quality/sufe_data_quality_before.json --apply
```

Expected: active corpus switches only after validation and prints the backup path.

- [ ] **Step 4: Reconcile versions and rebuild all collections**

Run:

```bash
uv run sufe-qa reconcile-versions
uv run sufe-qa index --full --fake-embed
```

Expected: atomic index rebuild succeeds for main/public/historical.

- [ ] **Step 5: Generate after report and verify gates**

Run the audit again and assert:

```text
main duplicate annual series = 0
main annual notices older than 5 school years = 0
public lists older than 2 school years = 0
main isolated-kind contamination = 0
legacy unknown promoted to manual = 0
date conflicts without evidence = 0
```

- [ ] **Step 6: Run fixed-bank coverage comparison**

Generate `sufe_coverage_after.json/.md` with the unchanged question-bank hash and retriever threshold. Core answerable/partially-answerable totals must not decline solely because duplicates were removed.

- [ ] **Step 7: Run the full suite and commit generated evidence**

Run:

```bash
uv run pytest -q
uv run ruff check src tests
git diff --check
```

```bash
git add data/quality data/coverage data/crawl_reports/sufe_full_report.json \
  data/corpus/manifest.jsonl data/corpus/relations.jsonl
git commit -m "data: migrate SUFE corpus to clean lifecycle view"
```
