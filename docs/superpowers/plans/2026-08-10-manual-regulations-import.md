# Manual SUFE Regulations Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely import an explicit allowlist of user-provided SUFE regulation files, route accepted documents through the existing lifecycle collections, rebuild the real BGE-M3 index, and continue question-gap-driven crawling.

**Architecture:** A dedicated manual-authority importer recursively inventories a source tree but imports only exact configured relative paths. It reuses the attachment parser for binary formats, emits deterministic candidates and a per-file audit report, and persists only after `--apply`; existing versioning and index collection routing remain authoritative.

**Tech Stack:** Python 3.13, dataclasses, PyYAML, PyMuPDF, python-docx, openpyxl, LibreOffice, pytest, ChromaDB, sentence-transformers BGE-M3.

---

### Task 1: Manual authority import contract

**Files:**
- Create: `src/sufe_qa/ingest/manual_authority.py`
- Modify: `src/sufe_qa/cli.py`
- Test: `tests/test_manual_authority.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing policy and dry-run tests**

Create fixtures containing one exact allowlisted PDF/DOCX, one unlisted file, one `征求意见稿`, one duplicate body and one parse failure. Assert that dry-run returns deterministic decisions without changing corpus or manifest, and that only the accepted exact path becomes a candidate.

- [ ] **Step 2: Verify the tests fail for the missing importer**

Run: `uv run pytest tests/test_manual_authority.py -q`

Expected: collection fails because `sufe_qa.ingest.manual_authority` does not exist.

- [ ] **Step 3: Implement configuration and decision types**

Add frozen `ManualAuthorityEntry`, `ManualImportDecision`, `ManualImportCandidate`, and `ManualImportReport` dataclasses. Load a YAML `entries` list keyed by normalized POSIX relative path; reject duplicate paths, invalid categories, invalid document kinds, absolute paths and `..` traversal.

- [ ] **Step 4: Implement recursive audit without writes**

For each regular file under the source root, compute a binary hash, apply hard exclusions, look up the exact allowlist entry, call `parse_attachment(path.name, path.read_bytes())`, reject non-`ok`/empty results, scan sensitive values, normalize text and compare hashes against the last-wins manifest. Produce stable `manual://sufe-regulations/<quoted-path>` source URLs and retain explicit metadata from the entry.

- [ ] **Step 5: Implement apply persistence**

Write accepted candidates to category corpus paths with normalized Markdown, append `DocMeta` rows with `source_type=manual_upload`, `document_type=attachment`, parse/hash/version evidence, and explicit lifecycle fields. Existing content hashes are reported as duplicates and never materialized twice.

- [ ] **Step 6: Add the CLI command**

Add:

```text
sufe-qa ingest-authority-files --source PATH --rules YAML --report JSON [--apply]
```

The command prints imported/duplicate/excluded/incomplete/quarantined counts and refuses all writes without `--apply`.

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest tests/test_manual_authority.py tests/test_cli.py -q`

```bash
git add src/sufe_qa/ingest/manual_authority.py src/sufe_qa/cli.py \
  tests/test_manual_authority.py tests/test_cli.py
git commit -m "feat: add audited manual authority import"
```

### Task 2: Curate and import the regulation bundle

**Files:**
- Create: `data/sources/sufe_manual_regulations.yaml`
- Generate: `data/crawl_reports/sufe_manual_regulations.json`
- Modify: `data/corpus/manifest.jsonl`
- Generate: accepted corpus Markdown under `data/corpus/`

- [ ] **Step 1: Build the exact allowlist**

List only student-facing policies and procedures. Give every entry an exact relative path, category, publisher, scope unit, source section, document kind and retention status. Mark old 2005/2013/2016 rules historical; do not list drafts, internal performance, teacher administration, party finance, general staff finance or journal catalogues.

- [ ] **Step 2: Run dry-run and reconcile every source file**

Run:

```bash
uv run sufe-qa ingest-authority-files \
  --source /home/chronicarl/Github/sufe-campus-qa/data/raw/规章制度 \
  --rules data/sources/sufe_manual_regulations.yaml \
  --report data/crawl_reports/sufe_manual_regulations.json
```

Expected: all 81 source files appear exactly once in the report; writes remain zero.

- [ ] **Step 3: Inspect representative extraction quality**

Render and inspect at least one university policy PDF and one college implementation-rule PDF with `pdftoppm`; compare visible headings/tables with extracted text. Inspect one DOCX and one spreadsheet extraction. Any mismatch becomes `incomplete` rather than accepted.

- [ ] **Step 4: Apply the reviewed import**

Repeat the command with `--apply`. Verify every imported manifest row has a materialized Markdown file whose `content_hash` matches, and every excluded item has a non-empty reason.

- [ ] **Step 5: Reconcile versions and commit source evidence**

Run: `uv run sufe-qa reconcile-versions`

```bash
git add data/sources/sufe_manual_regulations.yaml \
  data/crawl_reports/sufe_manual_regulations.json data/corpus
git commit -m "data: import curated SUFE regulations"
```

### Task 3: Reindex and verify data quality

**Files:**
- Modify: `data/chroma_db/`
- Modify: `data/chroma_db/index_metadata.json`
- Modify: `data/quality/sufe_data_quality_after.json`
- Modify: `data/quality/sufe_data_quality_after.md`
- Modify: `data/coverage/sufe_coverage_after.json`
- Modify: `data/coverage/sufe_coverage_after.md`

- [ ] **Step 1: Build a real incremental BGE-M3 index**

Run: `uv run sufe-qa index`

Expected: metadata records `BAAI/bge-m3`, `embedding_device=cuda`, `embedding_precision=float16`, and `test_only=false`.

- [ ] **Step 2: Refresh fixed-bank reports without changing the bank**

Run the existing quality audit, coverage audit and quality gates with their committed configuration. Assert the question-bank hash and similarity threshold equal the pre-import report.

- [ ] **Step 3: Verify collection and corpus invariants**

Assert no isolated kind is present in main, no public list is present in main, no active annual series has more than one canonical document, all accepted attachments have parsed text, and the index manifest fingerprint matches the current manifest.

- [ ] **Step 4: Commit generated index and reports**

```bash
git add data/chroma_db data/quality data/coverage data/crawl_reports/sufe_full_report.json
git commit -m "data: index curated SUFE regulations"
```

### Task 4: Continue gap-driven authoritative crawling

**Files:**
- Modify: `data/sources/sufe_authoritative.yaml` only if a verified public section is missing
- Modify: `data/corpus/manifest.jsonl`
- Modify: accepted corpus Markdown and `data/corpus/relations.jsonl`
- Modify: `data/crawl_reports/`

- [ ] **Step 1: Rank current missing-document probes**

Read the committed benchmark needs-docs report and group gaps by expected department and required answer points. Select the smallest JWC, career and NIC sections that can answer the largest number of unresolved questions.

- [ ] **Step 2: Smoke-test public sections**

Use existing adapters and SafeFetcher against the selected public sections. Confirm listing pagination, article body, attachments and source department before permitting writes; do not add broad selectors or scrape recruitment/news feeds.

- [ ] **Step 3: Crawl selected sections and rerun the probe**

Run `crawl-authoritative` only for selected sources, then run version reconciliation, incremental indexing and the unchanged benchmark probe. Record authoritative hit delta, wrong-department hit rate, attachment success and isolated-content rate.

- [ ] **Step 4: Run full verification and commit**

Run:

```bash
uv run pytest -q
uv run ruff check .
git diff --check
```

Commit only verified source configuration, corpus, index and reports. Keep raw download caches and local recovery backups ignored.
