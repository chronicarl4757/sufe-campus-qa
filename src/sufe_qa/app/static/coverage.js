/* 上财 150 问覆盖质检：只读展示固定评测报告，不在浏览器重算评测结论。 */
"use strict";

const PROBE_STATUS = {
  answerable: { label: "规则探针完整", short: "规整", symbol: "●", className: "is-answerable" },
  partially_answerable: { label: "规则探针部分", short: "规部", symbol: "◐", className: "is-partial" },
  not_answerable: { label: "规则探针未命中", short: "规缺", symbol: "×", className: "is-failed" },
};

const ANSWER_STATUS = {
  answered: { label: "已回答 · 引用通过", short: "已答", symbol: "✓", className: "is-real-answered" },
  answered_with_citation_issue: { label: "已回答 · 引用异常", short: "引异", symbol: "!", className: "is-real-citation" },
  refused: { label: "真实拒答", short: "拒答", symbol: "—", className: "is-real-refused" },
  error: { label: "生成错误", short: "错误", symbol: "×", className: "is-real-error" },
  not_run: { label: "尚未运行", short: "未跑", symbol: "·", className: "is-real-pending" },
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
  const run = report.answer_run || {};
  const generated = Object.values(run.status_counts || {}).reduce((sum, value) => sum + Number(value || 0), 0);
  setMeta(
    "meta-answer-run",
    run.available ? `${run.llm_model || "模型未知"} · ${generated}/${run.total || state.questions.length}` : "尚未运行",
    run.prompt_hash,
  );
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
  const count = (status) => state.questions.filter((q) => answerStatusOf(q) === status).length;
  const answered = count("answered");
  const citation = count("answered_with_citation_issue");
  const refused = count("refused");
  const errors = count("error");
  const pending = count("not_run");
  const probeComplete = state.questions.filter((q) => q.status === "answerable").length;

  byId("summary-metrics").replaceChildren(
    metric("固定问题", total, "题库分母", "total"),
    metric("真实回答", answered, "引用编号校验通过", "pass"),
    metric("引用异常", citation, "无引用或引用越界", "partial"),
    metric("真实拒答", refused, "未过检索置信门", "failed"),
    metric("生成错误", errors, "模型或网络错误", "failed"),
    metric("尚未运行", pending, "未产生真实快照"),
    metric("规则探针完整", probeComplete, "仅为关键词规则结果", "probe"),
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
    const answered = rows.filter((q) => answerStatusOf(q) === "answered").length;
    const citation = rows.filter((q) => answerStatusOf(q) === "answered_with_citation_issue").length;
    const refused = rows.filter((q) => answerStatusOf(q) === "refused").length;
    const errors = rows.filter((q) => ["error", "not_run"].includes(answerStatusOf(q))).length;
    const button = element("button", `scene-bar${selected === scene ? " is-selected" : ""}`);
    button.type = "button";
    button.dataset.scene = scene;
    button.setAttribute("aria-pressed", String(selected === scene));
    button.setAttribute("aria-label", `${scene}：已回答 ${answered}，引用异常 ${citation}，拒答 ${refused}，错误或未运行 ${errors}`);

    const head = element("span", "scene-bar__head");
    head.append(
      element("strong", "scene-bar__name", scene),
      element("span", "scene-bar__count", `${answered} / ${rows.length} 引用通过`),
    );
    const track = element("span", "scene-bar__track");
    for (const [name, value] of [["answered", answered], ["citation", citation], ["refused", refused], ["error", errors]]) {
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
  const answer = question.real_answer || {};
  const hits = array(answer.hits);
  return [
    question.id,
    question.question,
    question.scene,
    ...array(question.titles),
    ...array(question.publishers),
    ...array(question.matched_domains),
    ...array(question.retrieved_doc_ids),
    answer.answer_text || "",
    ...hits.flatMap((hit) => [hit.doc_id, hit.chunk_id, hit.title, hit.publisher, hit.text]),
  ].join(" ").toLocaleLowerCase("zh-CN");
}

function applyFilters() {
  const query = byId("search-filter").value.trim().toLocaleLowerCase("zh-CN");
  const scene = byId("scene-filter").value;
  const answerStatus = byId("answer-status-filter").value;
  const probeStatus = byId("probe-status-filter").value;
  const attachment = byId("attachment-filter").value;

  state.filtered = state.questions.filter((question) => {
    if (query && !searchableText(question).includes(query)) return false;
    if (scene && question.scene !== scene) return false;
    if (answerStatus && answerStatusOf(question) !== answerStatus) return false;
    if (probeStatus && question.status !== probeStatus) return false;
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

function probeStatusMeta(status) {
  return PROBE_STATUS[status] || PROBE_STATUS.not_answerable;
}

function answerStatusOf(question) {
  return question.real_answer ? question.real_answer.status : "not_run";
}

function answerStatusMeta(question) {
  return ANSWER_STATUS[answerStatusOf(question)] || ANSWER_STATUS.error;
}

function renderMatrix() {
  const container = byId("evidence-matrix");
  const fragment = document.createDocumentFragment();
  for (const question of state.filtered) {
    const meta = answerStatusMeta(question);
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
    const probe = probeStatusMeta(question.status);
    flags.appendChild(element("i", `flag flag--probe ${probe.className}`, probe.symbol));
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
    const meta = answerStatusMeta(question);
    const probe = probeStatusMeta(question.status);
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
      element("span", `probe-pill ${probe.className}`, `${probe.symbol} ${probe.label}`),
      element("span", `gap-count${gaps.length ? " has-gaps" : ""}`, gaps.length ? `${gaps.length} 项规则缺口` : "规则要点齐"),
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

function renderAnswerText(answerText, hits) {
  const container = element("div", "real-answer__content");
  const hitIndexes = new Set(hits.map((hit) => Number(hit.prompt_index)));
  const pattern = /\[(\d{1,2})\]|\*\*([^*\n]+)\*\*/g;
  let cursor = 0;
  let match;
  while ((match = pattern.exec(answerText)) !== null) {
    container.appendChild(document.createTextNode(answerText.slice(cursor, match.index)));
    if (match[2] !== undefined) {
      container.appendChild(element("strong", "answer-strong", match[2]));
      cursor = pattern.lastIndex;
      continue;
    }
    const index = Number(match[1]);
    const cite = element("button", "answer-citation", `[${index}]`);
    cite.type = "button";
    cite.disabled = !hitIndexes.has(index);
    cite.setAttribute("aria-label", hitIndexes.has(index) ? `定位到资料 ${index}` : `无效引用 ${index}`);
    if (hitIndexes.has(index)) {
      cite.addEventListener("click", () => {
        const target = byId(`answer-hit-${index}`);
        if (!target) return;
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.remove("flash");
        void target.offsetWidth;
        target.classList.add("flash");
      });
    }
    container.appendChild(cite);
    cursor = pattern.lastIndex;
  }
  container.appendChild(document.createTextNode(answerText.slice(cursor)));
  return container;
}

function renderRealAnswer(question) {
  const box = byId("real-answer");
  const metaBox = byId("real-answer-meta");
  const textBox = byId("real-answer-text");
  const answer = question.real_answer;
  const meta = answerStatusMeta(question);
  box.className = `real-answer ${meta.className}`;
  metaBox.replaceChildren();
  textBox.replaceChildren();

  const run = state.report.answer_run || {};
  const tags = [
    `${meta.symbol} ${meta.label}`,
    answer ? `模型 ${run.llm_model || "报告未提供"}` : "无真实答案快照",
  ];
  if (answer) {
    tags.push(`生成 ${formatEvaluatedAt(answer.generated_at)}`);
    tags.push(`耗时 ${Math.round(Number(answer.latency_ms || 0))} ms`);
    tags.push(answer.domain_match ? "命中预期域名" : "未命中预期域名");
    tags.push("人工审核：未完成");
  }
  for (const tag of tags) metaBox.appendChild(element("span", "real-answer__tag", tag));

  if (!answer) {
    textBox.appendChild(element("p", "real-answer__notice", "尚未运行真实问答。本题只有规则探针结果，不能视为答案。"));
    return;
  }
  if (answer.status === "error") {
    textBox.appendChild(element("p", "real-answer__notice is-error", `生成失败：${answer.error || "报告未提供错误原因"}`));
    return;
  }
  textBox.appendChild(renderAnswerText(answer.answer_text || "报告未提供答案正文", array(answer.hits)));
  const check = answer.citation_check;
  if (answer.status === "refused") {
    textBox.appendChild(element("p", "citation-audit is-refused", "本题未通过真实检索置信门，因此没有调用模型补写答案。"));
  } else if (check && check.ok) {
    textBox.appendChild(element("p", "citation-audit is-valid", "✓ 引用编号存在，且均指向本次 prompt 中的真实 chunk。"));
  } else {
    const invalid = check && array(check.invalid_refs).length
      ? `越界编号：${check.invalid_refs.join("、")}`
      : "回答缺少可校验引用";
    textBox.appendChild(element("p", "citation-audit is-invalid", `! 引用校验未通过：${invalid}`));
  }
}

function renderAnswerHits(question) {
  const body = byId("answer-hit-rows");
  const hits = array(question.real_answer && question.real_answer.hits);
  if (!hits.length) {
    const row = element("tr", "answer-hit");
    const cell = element("td", "document-empty", "本题没有用于真实回答的 chunk。" );
    cell.colSpan = 5;
    row.appendChild(cell);
    body.replaceChildren(row);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const hit of hits) {
    const index = Number(hit.prompt_index);
    const row = element("tr", "answer-hit");
    row.id = `answer-hit-${index}`;
    const indexCell = element("td", "answer-hit__index", `[${index}]`);
    const idCell = document.createElement("td");
    idCell.append(
      element("strong", "document-id", hit.doc_id || "报告未提供"),
      element("small", "answer-hit__chunk-id", hit.chunk_id || "报告未提供"),
    );
    const titleCell = document.createElement("td");
    const title = hit.parent_title || hit.title || "报告未提供";
    if (/^https?:\/\//.test(hit.source_url || "")) {
      const link = element("a", "document-title", title);
      link.href = hit.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      titleCell.appendChild(link);
    } else {
      titleCell.appendChild(element("strong", "document-title", title));
    }
    titleCell.appendChild(element("small", "document-publisher", hit.publisher || "报告未提供"));
    const similarity = typeof hit.vector_similarity === "number"
      ? hit.vector_similarity.toFixed(3)
      : "—";
    row.append(
      indexCell,
      idCell,
      titleCell,
      element("td", "answer-hit__similarity", similarity),
      element("td", `document-validity is-${hit.validity_status || "unknown_validity"}`, hit.validity_status || "报告未提供"),
    );
    const chunkRow = element("tr", "answer-hit__chunk");
    const chunkCell = document.createElement("td");
    chunkCell.colSpan = 5;
    const details = document.createElement("details");
    details.append(
      element("summary", "", `查看 [${index}] 实际 chunk · ${hit.heading_path || "无小节标题"}`),
      element("pre", "", hit.text || "报告未提供 chunk 正文"),
    );
    chunkCell.appendChild(details);
    chunkRow.appendChild(chunkCell);
    fragment.append(row, chunkRow);
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
  const meta = answerStatusMeta(question);
  const probe = probeStatusMeta(question.status);
  const answer = question.real_answer;
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
    ["真实回答 chunks", `${array(answer && answer.hits).length} 个`],
    ["真实命中域名", array(answer && answer.matched_domains).join("、") || "报告未提供"],
    ["规则探针", probe.label],
    ["人工审核", "未完成"],
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
  renderRealAnswer(question);
  renderAnswerHits(question);
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
  for (const id of [
    "search-filter",
    "scene-filter",
    "answer-status-filter",
    "probe-status-filter",
    "attachment-filter",
  ]) {
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
