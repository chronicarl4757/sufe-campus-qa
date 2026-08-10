# 150-Question Coverage Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/coverage` audit dashboard that visualizes all 150 fixed SUFE coverage questions and exposes every question's retrieved documents and answer-point evidence.

**Architecture:** FastAPI serves a validated, read-only snapshot from `data/coverage/sufe_coverage_after.json` through `/api/coverage` and a dedicated static page through `/coverage`. A framework-free JavaScript client derives summary counts, renders the 150-cell evidence matrix, composes filters, and opens an accessible evidence drawer without changing evaluation data.

**Tech Stack:** Python 3.11, FastAPI, pytest, HTML5, CSS Grid, vanilla JavaScript

---

## File map

- Modify `src/sufe_qa/app/server.py`: add report loading/validation and the two coverage routes.
- Modify `src/sufe_qa/app/static/index.html`: add navigation from the Q&A page to the audit page.
- Create `src/sufe_qa/app/static/coverage.html`: semantic dashboard shell and accessible controls.
- Create `src/sufe_qa/app/static/coverage.css`: archive-quality audit layout, matrix, drawer, responsive states.
- Create `src/sufe_qa/app/static/coverage.js`: API loading, derived metrics, filters, matrix/list/detail rendering, URL state.
- Modify `tests/test_app.py`: API, error, shell, navigation, and static-contract tests.

### Task 1: Add the read-only coverage report API

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/sufe_qa/app/server.py`

- [ ] **Step 1: Write failing tests for successful report loading**

Add a compact report fixture and test to `tests/test_app.py`:

```python
COVERAGE_REPORT = {
    "question_bank_version": "sufe-question-bank.v1",
    "question_bank_hash": "sha256:bank",
    "index_fingerprint": "sha256:index",
    "evaluated_at": "2026-08-10T13:10:28+00:00",
    "retriever_config": {"similarity_threshold": 0.5},
    "scene_stats": {
        "本科教务": {
            "question_count": 1,
            "answerable_question_count": 1,
            "partially_answerable_question_count": 0,
            "unanswerable_question_count": 0,
        }
    },
    "question_results": [
        {
            "id": "jwc-leave-001",
            "question": "本科生如何申请缓考？",
            "scene": "本科教务",
            "status": "answerable",
            "retrieved_doc_ids": ["doc-1"],
            "titles": ["缓考办理办法"],
            "publishers": ["上海财经大学教务处"],
            "publish_dates": ["2026-01-01"],
            "document_kinds": ["procedure"],
            "validity_statuses": ["current"],
            "has_attachment": True,
            "matched_domains": ["jwc.sufe.edu.cn"],
            "point_evidence": [],
            "missing_reasons": [],
        }
    ],
}


def _write_coverage_report(tmp_path, report=COVERAGE_REPORT):
    path = tmp_path / "coverage" / "sufe_coverage_after.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def test_coverage_api_returns_current_report(client, tmp_path):
    _write_coverage_report(tmp_path)
    response = client.get("/api/coverage")
    assert response.status_code == 200
    assert response.json()["question_results"][0]["id"] == "jwc-leave-001"
    assert response.headers["cache-control"] == "no-store"
```

- [ ] **Step 2: Run the success test and verify RED**

Run: `uv run pytest tests/test_app.py::test_coverage_api_returns_current_report -v`

Expected: FAIL with `404 Not Found` because `/api/coverage` does not exist.

- [ ] **Step 3: Write failing tests for missing, malformed, and invalid reports**

Add:

```python
def test_coverage_api_reports_missing_file(client):
    response = client.get("/api/coverage")
    assert response.status_code == 404
    assert response.json()["detail"] == "覆盖评测报告不存在"


def test_coverage_api_rejects_malformed_json(client, tmp_path):
    path = tmp_path / "coverage" / "sufe_coverage_after.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    response = client.get("/api/coverage")
    assert response.status_code == 500
    assert response.json()["detail"] == "覆盖评测报告无法解析"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.pop("scene_stats"),
        lambda report: report["question_results"][0].pop("question"),
        lambda report: report["question_results"][0].update(status="invented"),
    ],
)
def test_coverage_api_rejects_invalid_schema(client, tmp_path, mutation):
    report = json.loads(json.dumps(COVERAGE_REPORT))
    mutation(report)
    _write_coverage_report(tmp_path, report)
    response = client.get("/api/coverage")
    assert response.status_code == 500
    assert response.json()["detail"] == "覆盖评测报告结构无效"
```

- [ ] **Step 4: Implement the report loader and API route**

In `src/sufe_qa/app/server.py`, import `HTTPException` and `JSONResponse`, define the explicit status allowlist, and add:

```python
_COVERAGE_STATUSES = {"answerable", "partially_answerable", "not_answerable"}


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
```

Inside `create_app`, add:

```python
    @app.get("/api/coverage")
    def coverage_report() -> JSONResponse:
        report = _load_coverage_report(
            settings.data_dir / "coverage" / "sufe_coverage_after.json"
        )
        return JSONResponse(report, headers={"Cache-Control": "no-store"})
```

- [ ] **Step 5: Run API tests and verify GREEN**

Run: `uv run pytest tests/test_app.py -k coverage_api -v`

Expected: all coverage API tests PASS.

- [ ] **Step 6: Commit the API slice**

```bash
git add src/sufe_qa/app/server.py tests/test_app.py
git commit -m "feat: expose validated coverage report API"
```

### Task 2: Add the coverage page shell and navigation

**Files:**
- Modify: `tests/test_app.py`
- Modify: `src/sufe_qa/app/server.py`
- Modify: `src/sufe_qa/app/static/index.html`
- Create: `src/sufe_qa/app/static/coverage.html`

- [ ] **Step 1: Write failing route and static-contract tests**

Add:

```python
def test_coverage_page_served(client):
    response = client.get("/coverage")
    assert response.status_code == 200
    assert "150 问覆盖质检" in response.text
    assert 'id="evidence-matrix"' in response.text
    assert 'id="question-drawer"' in response.text
    assert 'src="/static/coverage.js"' in response.text


def test_index_links_to_coverage_dashboard(client):
    response = client.get("/")
    assert 'href="/coverage"' in response.text
    assert "覆盖质检" in response.text
```

- [ ] **Step 2: Run page tests and verify RED**

Run: `uv run pytest tests/test_app.py -k 'coverage_page or index_links' -v`

Expected: FAIL because `/coverage` returns 404 and the existing header has no audit link.

- [ ] **Step 3: Add the route and semantic page shell**

Add this route immediately after the index route:

```python
    @app.get("/coverage")
    def coverage_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "coverage.html")
```

Create `coverage.html` with these exact regions (copy can be refined without renaming IDs):

- a masthead containing “150 问覆盖质检”, report metadata, and a `/` return link;
- loading and explicit error states;
- `summary-metrics`, `scene-bars`, `evidence-matrix`, and `question-list` result regions;
- accessible `search`, `scene`, `status`, and `attachment` controls;
- a modal-style `aside` with `id="question-drawer"`, a close button, document table, evidence list, and missing-reasons region;
- links to `/static/coverage.css` and `/static/coverage.js`.

In `index.html`, add a visible `<a href="/coverage">覆盖质检</a>` next to the masthead subtitle without changing the Q&A form.

- [ ] **Step 4: Run page tests and verify GREEN**

Run: `uv run pytest tests/test_app.py -k 'coverage_page or index_links' -v`

Expected: both tests PASS.

- [ ] **Step 5: Commit the page shell**

```bash
git add src/sufe_qa/app/server.py src/sufe_qa/app/static/index.html \
  src/sufe_qa/app/static/coverage.html tests/test_app.py
git commit -m "feat: add coverage dashboard shell"
```

### Task 3: Build the evidence matrix and audit drawer

**Files:**
- Modify: `tests/test_app.py`
- Create: `src/sufe_qa/app/static/coverage.js`
- Create: `src/sufe_qa/app/static/coverage.css`

- [ ] **Step 1: Write failing static behavior-contract tests**

Add:

```python
def test_coverage_static_assets_define_audit_behaviors(client):
    script = client.get("/static/coverage.js")
    styles = client.get("/static/coverage.css")
    assert script.status_code == styles.status_code == 200
    for token in (
        "loadCoverage",
        "renderSummary",
        "renderScenes",
        "renderMatrix",
        "renderQuestionList",
        "openQuestion",
        "applyFilters",
        "point_evidence",
        "retrieved_doc_ids",
    ):
        assert token in script.text
    for selector in (
        ".evidence-matrix",
        ".matrix-cell",
        ".scene-bar",
        ".question-drawer",
        "@media (max-width: 720px)",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert selector in styles.text
```

- [ ] **Step 2: Run the static contract test and verify RED**

Run: `uv run pytest tests/test_app.py::test_coverage_static_assets_define_audit_behaviors -v`

Expected: FAIL because the two static assets do not exist.

- [ ] **Step 3: Implement JavaScript behaviors**

In `coverage.js`:

- fetch `/api/coverage` in `loadCoverage()` and show the API `detail` on failure;
- derive total, complete, partial, failed, authoritative-hit, and attachment counts from question rows;
- assign fixed `_ordinal` values from source order and map three explicit statuses to Chinese labels/symbols;
- render scene bars in report order;
- compose question ID/text, title, publisher, domain, doc ID, scene, status, and attachment filters;
- render one button per visible question in `renderMatrix()` and one row per result in `renderQuestionList()`;
- zip parallel document arrays by doc ID index and show absent fields as “报告未提供”;
- render all `point_evidence` fields and all `missing_reasons` without rewriting evidence;
- open from matrix/list, close by button/backdrop/Escape, restore focus, and synchronize `?question=<id>`;
- write report-controlled strings with `textContent`, not HTML interpolation.

- [ ] **Step 4: Implement the visual system**

In `coverage.css`, define:

```css
:root {
  --paper: #f1eee5;
  --paper-raised: #fbfaf5;
  --ink: #20201d;
  --muted: #6c6a62;
  --rule: #c9c3b4;
  --seal: #9e2420;
  --pass: #23624b;
  --partial: #a56417;
  --fail: #a22e2a;
}
```

Use Songti-family display type, system sans body text, monospace IDs, a 15-column desktop matrix, width-encoded scene bars, a right-side desktop drawer and full-width mobile sheet, visible focus rings, non-color status marks, 44px touch targets where practical, and a single reduced-motion-aware page reveal. Do not add external fonts, images, gradients, or ornamental charts.

- [ ] **Step 5: Verify JavaScript syntax and static tests**

```bash
node --check src/sufe_qa/app/static/coverage.js
uv run pytest tests/test_app.py::test_coverage_static_assets_define_audit_behaviors -v
```

Expected: Node exits 0 and pytest PASS.

- [ ] **Step 6: Commit the interactive dashboard**

```bash
git add src/sufe_qa/app/static/coverage.js src/sufe_qa/app/static/coverage.css tests/test_app.py
git commit -m "feat: visualize 150-question evidence matrix"
```

### Task 4: Verify real report rendering and regressions

**Files:**
- Modify static coverage files only for defects found during review.
- Modify `tests/test_app.py` before fixing any reproducible behavior defect.

- [ ] **Step 1: Run all automated checks**

```bash
uv run pytest tests/test_app.py -v
uv run pytest -q
uv run ruff check .
node --check src/sufe_qa/app/static/coverage.js
```

Expected: all tests PASS; Ruff and Node exit 0.

- [ ] **Step 2: Start the real application and inspect the report**

Run: `uv run uvicorn sufe_qa.app.server:app --host 127.0.0.1 --port 8000`

At `http://127.0.0.1:8000/coverage`, verify 150 total, 85 answerable, 65 partial, 0 failed, 11 scene rows, and `jwc-leave-001` with five document IDs and four evidence records.

- [ ] **Step 3: Review desktop and 360px behavior**

Verify no page overflow; all matrix cells are reachable; combined filters update both views; matrix/list open the same question; the URL restores a question after refresh; Escape closes and restores focus; long hashes, IDs, titles, and evidence wrap.

- [ ] **Step 4: Fix only observed defects with a RED/GREEN cycle**

For each defect, add or tighten an assertion, observe failure, patch the smallest relevant file, then run:

```bash
uv run pytest tests/test_app.py -v
uv run ruff check .
node --check src/sufe_qa/app/static/coverage.js
```

- [ ] **Step 5: Commit review fixes when present**

```bash
git add src/sufe_qa/app/static/coverage.html src/sufe_qa/app/static/coverage.css \
  src/sufe_qa/app/static/coverage.js tests/test_app.py
git diff --cached --quiet || git commit -m "fix: polish coverage audit experience"
```

- [ ] **Step 6: Record final repository state**

```bash
git status --short --branch
git log -5 --oneline
```

Expected: no unintended changes and recent commits show the API, page shell, matrix, and any review fix.
