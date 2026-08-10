# Real-Answer Coverage Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and visualize real, cited answers for the fixed 150-question SUFE bank while preserving the existing lexical coverage probe as a separately labeled diagnostic.

**Architecture:** A new `answer_benchmark` module runs the production retrieval/prompt/citation pipeline and atomically persists a resumable answer snapshot. FastAPI merges that snapshot with the existing coverage report by question ID, and the dashboard renders real answer status, text, prompt-indexed chunks, and citation checks ahead of the explicitly downgraded rule probe.

**Tech Stack:** Python 3.11, BGE-M3, Chroma, BM25, DeepSeek OpenAI-compatible API, FastAPI, pytest, vanilla JavaScript/CSS

---

### Task 1: Real-answer report domain model and generator

**Files:**
- Create: `src/sufe_qa/coverage/answer_benchmark.py`
- Create: `tests/test_answer_benchmark.py`

- [ ] Write failing tests for an answered item, confident refusal, citation issue, provider error, report counts, and atomic resume compatibility.
- [ ] Run `uv run pytest tests/test_answer_benchmark.py -v` and confirm failures are caused by the missing module.
- [ ] Implement immutable hit/result/report dataclasses, prompt/index hashes, real generation, citation validation, status derivation, deterministic ordering, atomic JSON writes, and strict resume metadata checks.
- [ ] Inject retriever and LLM factory in tests; production code must never fall back to `FakeLLM` or silently swallow errors.
- [ ] Run the focused tests and Ruff, then commit `feat: add real-answer benchmark runner`.

### Task 2: CLI batch command with resumable progress

**Files:**
- Modify: `src/sufe_qa/cli.py`
- Modify: `tests/test_cli.py`

- [ ] Write a failing CLI test that injects FakeEmbedder/FakeLLM, runs a one-item internal batch fixture, and asserts output, progress, and resume behavior.
- [ ] Add `answer-benchmark` arguments for bank, output, workers, resume, max-items, and retry-errors.
- [ ] Build one production BGE retriever, create DeepSeek clients per generation worker, print one progress line per completed question, and return nonzero only when terminal errors remain.
- [ ] Run focused CLI tests and commit `feat: add real-answer benchmark command`.

### Task 3: Merge answer snapshots into the coverage API

**Files:**
- Modify: `src/sufe_qa/app/server.py`
- Modify: `tests/test_app.py`

- [ ] Write failing tests for a valid answer snapshot merge, an absent optional snapshot, malformed JSON, duplicate answer IDs, and bank-hash mismatch.
- [ ] Load `data/coverage/sufe_real_answers.json`, validate its explicit status allowlist, reject incompatible snapshots, and attach each record as `real_answer`; expose run metadata as `answer_run`.
- [ ] Keep `/api/coverage` read-only and `no-store`; do not initialize retrieval or LLM components.
- [ ] Run focused API tests and commit `feat: expose real answers in coverage API`.

### Task 4: Render real answers and relabel the lexical probe

**Files:**
- Modify: `src/sufe_qa/app/static/coverage.html`
- Modify: `src/sufe_qa/app/static/coverage.js`
- Modify: `src/sufe_qa/app/static/coverage.css`
- Modify: `tests/test_app.py`

- [ ] Write failing static-contract tests for `renderRealAnswer`, `answer_text`, answer/probe filters, prompt-indexed hit rows, citation links, and the exact label “规则探针证据（非人工判分）”.
- [ ] Replace headline metrics, scene bars, matrix colors, and primary status pills with real generation status; retain rule-probe status as secondary text and filter.
- [ ] Render answer text safely with clickable `[n]` nodes, citation validation, model/time/domain metadata, refusal/error states, and actual hit chunks.
- [ ] Preserve mobile, keyboard, URL, and no-horizontal-overflow behavior; run Node syntax and static tests.
- [ ] Commit `feat: show real answers in coverage dashboard`.

### Task 5: Generate and verify all 150 real answers

**Files:**
- Create: `data/coverage/sufe_real_answers.json`
- Modify code/tests only for defects reproduced during the real run.

- [ ] Run the full test suite and Ruff before spending provider calls.
- [ ] Run `uv run sufe-qa answer-benchmark --workers 4 --resume` and monitor progress; retry only `error` results.
- [ ] Validate exactly 150 unique IDs, no missing terminal records, matching question-bank hash/index fingerprint/model/prompt hash, and citation status counts.
- [ ] Start the local dashboard and use a real browser at desktop and 360px to verify summary counts, combined filters, answer text, `[n]` navigation, source chunks, shared URLs, and overflow.
- [ ] Run `uv run pytest -q`, `uv run ruff check .`, and `node --check src/sufe_qa/app/static/coverage.js` fresh after all fixes.
- [ ] Commit the generated snapshot and any verified fixes as `data: add 150 real-answer evaluation snapshot`.
