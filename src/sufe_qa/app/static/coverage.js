/* 上财 150 问覆盖质检：只读展示固定评测报告，不在浏览器重算评测结论。 */
"use strict";

const STATUS = {
  answerable: { label: "完整可回答", short: "完整", symbol: "●", className: "is-answerable" },
  partially_answerable: { label: "部分可回答", short: "部分", symbol: "◐", className: "is-partial" },
  not_answerable: { label: "不可回答", short: "缺失", symbol: "×", className: "is-failed" },
};

const state = {
  report: null,
  questions: [],
  filtered: [],
  activeQuestion: null,
  lastTrigger: null,
};

const byId = (id) => document.getElementById(id);
const array = (value) => (Array.isArray(value) ? value : []);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function setMeta(id, value, title) {
  const node = byId(id);
  node.textContent = value || "报告未提供";
  if (title) node.title = title;
}

function shortHash(value) {
  if (!value) return "报告未提供";
  const plain = String(value).replace(/^sha256:/, "");
  return plain.length > 18 ? `${plain.slice(0, 9)}…${plain.slice(-7)}` : plain;
}

function formatEvaluatedAt(value) {
  if (!value) return "报告未提供";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function retrieverLabel(config) {
  if (!config || typeof config !== "object") return "报告未提供";
  const parts = [];
  if (config.similarity_threshold !== undefined) parts.push(`阈值 ${config.similarity_threshold}`);
  if (config.vector_top_k !== undefined) parts.push(`Vector ${config.vector_top_k}`);
  if (config.bm25_top_k !== undefined) parts.push(`BM25 ${config.bm25_top_k}`);
  if (config.fusion_top_n !== undefined) parts.push(`Fusion ${config.fusion_top_n}`);
  return parts.length ? parts.join(" · ") : "报告未提供";
}

function renderReportMeta(report) {
  setMeta("meta-version", report.question_bank_version);
  setMeta("meta-time", formatEvaluatedAt(report.evaluated_at));
  setMeta("meta-bank-hash", shortHash(report.question_bank_hash), report.question_bank_hash);
  setMeta("meta-index-hash", shortHash(report.index_fingerprint), report.index_fingerprint);
  setMeta("meta-retriever", retrieverLabel(report.retriever_config));
  byId("stamp-count").textContent = String(state.questions.length);
  document.querySelector(".audit-stamp").setAttribute(
    "aria-label",
    `本次评测共 ${state.questions.length} 个问题`,
  );
}

function metric(label, value, note, tone) {
  const card = element("article", `metric${tone ? ` metric--${tone}` : ""}`);
  card.append(
    element("p", "metric__label", label),
    element("p", "metric__value", value),
    element("p", "metric__note", note),
  );
  return card;
}

function renderSummary() {
  const total = state.questions.length;
  const complete = state.questions.filter((q) => q.status === "answerable").length;
  const partial = state.questions.filter((q) => q.status === "partially_answerable").length;
  const failed = state.questions.filter((q) => q.status === "not_answerable").length;
  const authoritative = state.questions.filter((q) => array(q.matched_domains).length > 0).length;
  const attachments = state.questions.filter((q) => q.has_attachment === true).length;
  const rate = total ? `${((complete / total) * 100).toFixed(1)}%` : "0.0%";

  byId("summary-metrics").replaceChildren(
    metric("固定问题", total, "题库分母", "total"),
    metric("完整可回答", complete, `完整通过率 ${rate}`, "pass"),
    metric("部分可回答", partial, "仍有回答要点缺口", "partial"),
    metric("不可回答", failed, "无足够官方依据", "failed"),
    metric("权威域名命中", authoritative, `占全部问题 ${total ? Math.round((authoritative / total) * 100) : 0}%`),
    metric("含附件依据", attachments, "命中文档包含附件"),
  );
}

function sceneOrder() {
  const configured = Object.keys(state.report.scene_stats || {});
  for (const question of state.questions) {
    if (!configured.includes(question.scene)) configured.push(question.scene);
  }
  return configured;
}

function renderScenes() {
  const container = byId("scene-bars");
  const selected = byId("scene-filter").value;
  const fragment = document.createDocumentFragment();

  for (const scene of sceneOrder()) {
    const rows = state.questions.filter((q) => q.scene === scene);
    const total = rows.length || 1;
    const complete = rows.filter((q) => q.status === "answerable").length;
    const partial = rows.filter((q) => q.status === "partially_answerable").length;
    const failed = rows.filter((q) => q.status === "not_answerable").length;
    const button = element("button", `scene-bar${selected === scene ? " is-selected" : ""}`);
    button.type = "button";
    button.dataset.scene = scene;
    button.setAttribute("aria-pressed", String(selected === scene));
    button.setAttribute("aria-label", `${scene}：完整 ${complete}，部分 ${partial}，不可回答 ${failed}`);

    const head = element("span", "scene-bar__head");
    head.append(
      element("strong", "scene-bar__name", scene),
      element("span", "scene-bar__count", `${complete} / ${rows.length} 完整`),
    );
    const track = element("span", "scene-bar__track");
    for (const [name, value] of [["answerable", complete], ["partial", partial], ["failed", failed]]) {
      const segment = element("i", `scene-bar__segment is-${name}`);
      segment.style.width = `${(value / total) * 100}%`;
      track.appendChild(segment);
    }
    button.append(head, track);
    button.addEventListener("click", () => {
      byId("scene-filter").value = selected === scene ? "" : scene;
      applyFilters();
    });
    fragment.appendChild(button);
  }
  container.replaceChildren(fragment);
}

function searchableText(question) {
  return [
    question.id,
    question.question,
    question.scene,
    ...array(question.titles),
    ...array(question.publishers),
    ...array(question.matched_domains),
    ...array(question.retrieved_doc_ids),
  ].join(" ").toLocaleLowerCase("zh-CN");
}

function applyFilters() {
  const query = byId("search-filter").value.trim().toLocaleLowerCase("zh-CN");
  const scene = byId("scene-filter").value;
  const status = byId("status-filter").value;
  const attachment = byId("attachment-filter").value;

  state.filtered = state.questions.filter((question) => {
    if (query && !searchableText(question).includes(query)) return false;
    if (scene && question.scene !== scene) return false;
    if (status && question.status !== status) return false;
    if (attachment === "yes" && question.has_attachment !== true) return false;
    if (attachment === "no" && question.has_attachment === true) return false;
    return true;
  });

  byId("result-count").textContent = `当前 ${state.filtered.length} / ${state.questions.length}`;
  byId("empty-results").hidden = state.filtered.length > 0;
  renderScenes();
  renderMatrix();
  renderQuestionList();
}

function statusMeta(status) {
  return STATUS[status] || STATUS.not_answerable;
}

function renderMatrix() {
  const container = byId("evidence-matrix");
  const fragment = document.createDocumentFragment();
  for (const question of state.filtered) {
    const meta = statusMeta(question.status);
    const button = element("button", `matrix-cell ${meta.className}`);
    button.type = "button";
    button.dataset.questionId = question.id;
    button.title = `${String(question._ordinal).padStart(3, "0")} · ${question.question}`;
    button.setAttribute("aria-label", `${button.title} · ${meta.label}`);
    button.append(
      element("span", "matrix-cell__number", String(question._ordinal).padStart(3, "0")),
      element("span", "matrix-cell__symbol", meta.symbol),
    );
    const flags = element("span", "matrix-cell__flags");
    if (question.has_attachment === true) flags.appendChild(element("i", "flag flag--attachment", "附"));
    if (array(question.validity_statuses).includes("unknown_validity")) {
      flags.appendChild(element("i", "flag flag--unknown", "?"));
    }
    button.appendChild(flags);
    button.addEventListener("click", () => openQuestion(question.id, button));
    fragment.appendChild(button);
  }
  container.replaceChildren(fragment);
}

function firstDocumentLabel(question) {
  return array(question.titles)[0] || array(question.retrieved_doc_ids)[0] || "未命中文档";
}

function renderQuestionList() {
  const container = byId("question-list");
  const fragment = document.createDocumentFragment();
  for (const question of state.filtered) {
    const meta = statusMeta(question.status);
    const row = element("button", "question-row");
    row.type = "button";
    row.dataset.questionId = question.id;
    const number = element("span", `question-row__number ${meta.className}`);
    number.append(
      element("strong", "", String(question._ordinal).padStart(3, "0")),
      element("small", "", meta.short),
    );
    const main = element("span", "question-row__main");
    main.append(
      element("span", "question-row__id", `${question.scene} · ${question.id}`),
      element("strong", "question-row__question", question.question),
      element("span", "question-row__document", firstDocumentLabel(question)),
    );
    const gaps = array(question.missing_reasons);
    const tail = element("span", "question-row__tail");
    tail.append(
      element("span", `status-pill ${meta.className}`, `${meta.symbol} ${meta.label}`),
      element("span", `gap-count${gaps.length ? " has-gaps" : ""}`, gaps.length ? `${gaps.length} 项缺口` : "要点完整"),
    );
    row.append(number, main, tail);
    row.addEventListener("click", () => openQuestion(question.id, row));
    fragment.appendChild(row);
  }
  container.replaceChildren(fragment);
}

function documentsFor(question) {
  const ids = array(question.retrieved_doc_ids);
  const titles = array(question.titles);
  const publishers = array(question.publishers);
  const dates = array(question.publish_dates);
  const kinds = array(question.document_kinds);
  const validity = array(question.validity_statuses);
  return ids.map((id, index) => ({
    id,
    title: titles[index] || "报告未提供",
    publisher: publishers[index] || "报告未提供",
    date: dates[index] || "报告未提供",
    kind: kinds[index] || "报告未提供",
    validity: validity[index] || "报告未提供",
  }));
}

function renderDocuments(question) {
  const body = byId("document-rows");
  const rows = documentsFor(question);
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = element("td", "document-empty", "报告未提供命中文档");
    td.colSpan = 5;
    tr.appendChild(td);
    body.replaceChildren(tr);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const doc of rows) {
    const tr = document.createElement("tr");
    const idCell = element("td", "document-id", doc.id);
    const titleCell = document.createElement("td");
    titleCell.append(
      element("strong", "document-title", doc.title),
      element("small", "document-publisher", doc.publisher),
    );
    tr.append(
      idCell,
      titleCell,
      element("td", "document-date", doc.date),
      element("td", "document-kind", doc.kind),
      element("td", `document-validity is-${doc.validity}`, doc.validity),
    );
    fragment.appendChild(tr);
  }
  body.replaceChildren(fragment);
}

function renderPointEvidence(question) {
  const container = byId("point-evidence");
  const records = array(question.point_evidence);
  if (!records.length) {
    container.replaceChildren(element("p", "drawer-empty", "报告未提供回答要点证据。"));
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const record of records) {
    const supported = record.status === "supported";
    const card = element("article", `evidence-card ${supported ? "is-supported" : "is-unsupported"}`);
    const head = element("header", "evidence-card__head");
    head.append(
      element("strong", "evidence-card__point", record.point || "未命名要点"),
      element("span", "evidence-card__status", supported ? "✓ 已支持" : "! 未支持"),
    );
    const meta = element("p", "evidence-card__meta");
    const confidence = typeof record.confidence === "number"
      ? `${Math.round(record.confidence * 100)}%`
      : "报告未提供";
    meta.textContent = `证据 ${record.evidence_doc_id || "报告未提供"} · ${record.checker || "检查器未知"} · 置信度 ${confidence}`;
    const excerpt = element("blockquote", "evidence-card__excerpt", record.evidence_excerpt || "报告未提供证据片段");
    const reason = element("p", "evidence-card__reason", record.reason || "报告未提供判定理由");
    card.append(head, meta, excerpt, reason);
    fragment.appendChild(card);
  }
  container.replaceChildren(fragment);
}

function renderMissingReasons(question) {
  const container = byId("missing-reasons");
  const reasons = array(question.missing_reasons);
  if (!reasons.length) {
    container.replaceChildren(element("p", "missing-clear", "✓ 无缺失项"));
    return;
  }
  const list = element("ul", "missing-list");
  for (const reason of reasons) list.appendChild(element("li", "", reason));
  container.replaceChildren(list);
}

function renderVerdict(question) {
  const meta = statusMeta(question.status);
  const box = byId("drawer-verdict");
  const heading = element("div", "drawer-verdict__heading");
  heading.append(
    element("span", `status-pill status-pill--large ${meta.className}`, `${meta.symbol} ${meta.label}`),
    element("span", "drawer-verdict__scene", question.scene),
  );
  const title = element("p", "drawer-verdict__question", question.question);
  const facts = element("dl", "drawer-facts");
  const factData = [
    ["问题 ID", question.id],
    ["命中文档", `${array(question.retrieved_doc_ids).length} 份`],
    ["权威域名", array(question.matched_domains).join("、") || "报告未提供"],
    ["附件", question.has_attachment === true ? "是" : "否"],
  ];
  for (const [label, value] of factData) {
    const group = document.createElement("div");
    group.append(element("dt", "", label), element("dd", "", value));
    facts.appendChild(group);
  }
  box.replaceChildren(heading, title, facts);
}

function updateQuestionUrl(questionId) {
  const url = new URL(window.location.href);
  if (questionId) url.searchParams.set("question", questionId);
  else url.searchParams.delete("question");
  window.history.replaceState({}, "", url);
}

function openQuestion(questionId, trigger) {
  const question = state.questions.find((item) => item.id === questionId);
  if (!question) return;
  state.activeQuestion = question;
  state.lastTrigger = trigger || document.activeElement;
  byId("drawer-sequence").textContent = `问题 ${String(question._ordinal).padStart(3, "0")} / ${state.questions.length}`;
  byId("drawer-title").textContent = question.question;
  renderVerdict(question);
  renderDocuments(question);
  renderPointEvidence(question);
  renderMissingReasons(question);
  byId("drawer-backdrop").hidden = false;
  byId("question-drawer").hidden = false;
  document.body.classList.add("drawer-open");
  updateQuestionUrl(question.id);
  requestAnimationFrame(() => byId("drawer-title").focus());
}

function closeQuestion() {
  if (!state.activeQuestion) return;
  state.activeQuestion = null;
  byId("drawer-backdrop").hidden = true;
  byId("question-drawer").hidden = true;
  document.body.classList.remove("drawer-open");
  updateQuestionUrl(null);
  if (state.lastTrigger && document.contains(state.lastTrigger)) state.lastTrigger.focus();
}

function populateSceneFilter() {
  const select = byId("scene-filter");
  const existing = select.querySelector("option");
  const options = document.createDocumentFragment();
  options.appendChild(existing.cloneNode(true));
  for (const scene of sceneOrder()) {
    const option = document.createElement("option");
    option.value = scene;
    option.textContent = scene;
    options.appendChild(option);
  }
  select.replaceChildren(options);
}

function bindControls() {
  for (const id of ["search-filter", "scene-filter", "status-filter", "attachment-filter"]) {
    byId(id).addEventListener(id === "search-filter" ? "input" : "change", applyFilters);
  }
  byId("filter-bar").addEventListener("reset", () => window.setTimeout(applyFilters, 0));
  byId("drawer-close").addEventListener("click", closeQuestion);
  byId("drawer-backdrop").addEventListener("click", closeQuestion);
  byId("retry-button").addEventListener("click", loadCoverage);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.activeQuestion) closeQuestion();
  });
}

function showError(message) {
  byId("loading-state").hidden = true;
  byId("dashboard").hidden = true;
  byId("error-message").textContent = message;
  byId("error-state").hidden = false;
}

async function loadCoverage() {
  byId("error-state").hidden = true;
  byId("loading-state").hidden = false;
  try {
    const response = await fetch("/api/coverage", { cache: "no-store" });
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("服务器返回的覆盖报告不是有效 JSON");
    }
    if (!response.ok) throw new Error(payload.detail || "覆盖评测报告加载失败");
    if (!payload || !Array.isArray(payload.question_results)) {
      throw new Error("覆盖评测报告缺少逐题结果");
    }
    state.report = payload;
    state.questions = payload.question_results.map((question, index) => ({
      ...question,
      _ordinal: index + 1,
    }));
    state.filtered = [...state.questions];
    renderReportMeta(payload);
    renderSummary();
    populateSceneFilter();
    applyFilters();
    byId("loading-state").hidden = true;
    byId("dashboard").hidden = false;
    const requested = new URL(window.location.href).searchParams.get("question");
    if (requested) openQuestion(requested, null);
  } catch (error) {
    showError(error instanceof Error ? error.message : "覆盖评测报告加载失败");
  }
}

bindControls();
loadCoverage();
