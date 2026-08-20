"use strict";

const byId = (id) => document.getElementById(id);
const state = {
  token: sessionStorage.getItem("sufe-admin-token") || "",
  overview: null,
  offset: 0,
  limit: 80,
  fetchedDay: "",
  activeDocId: "",
  previewVersion: "",
  debugQuestion: "",
  lastFocus: null,
  pollTimer: null,
  view: "overview",
};

const labels = {
  accepted: "已通过",
  incomplete_document: "正文不完整",
  low_quality: "低质量",
  quarantined: "已隔离",
  active: "现行",
  archived: "归档",
  official_department: "校内职能部门",
  official_school: "学校官方",
  official_college: "学院官方",
  official_wechat: "官方公众号",
  manual_upload: "管理员导入",
  unknown: "来源待核验",
  main_qa: "主问答库",
  public_list: "公示名单",
  historical: "历史资料",
  sufe_qa_main_v2: "主问答库",
  sufe_qa_public_list_v2: "公示名单库",
  sufe_qa_historical_v2: "历史资料库",
  none: "不进入问答",
  policy: "政策制度",
  procedure: "办事流程",
  annual_notice: "年度通知",
  faq: "常见问答",
  form: "表格模板",
  manual: "操作手册",
  service_guide: "服务指南",
  news: "新闻动态",
  event: "活动",
  promotion: "宣传",
  incomplete: "不完整",
  current: "现行有效",
  superseded: "已被替代",
  unknown_validity: "有效性待确认",
};

const VIEWS = ["overview", "documents", "clinic", "import"];

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = String(text);
  return item;
}

function display(value) {
  return labels[value] || value || "未标注";
}

function formatDate(value) {
  return value && value !== "unknown" ? value.replace("T", " ").slice(0, 16) : "未知";
}

function shortFingerprint(value) {
  return value && value !== "missing" ? `${value.slice(7, 19)}` : "尚未生成";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${state.token}`);
  const response = await fetch(path, {...options, headers});
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  if (!response.ok) {
    const error = new Error(payload.detail || `请求失败（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

let toastTimer;
function toast(message, isError = false) {
  const box = byId("toast");
  box.textContent = message;
  box.classList.toggle("is-error", isError);
  box.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { box.hidden = true; }, 4200);
}

function handleError(error) {
  if (error.status === 401) {
    logout();
    byId("login-message").textContent = "管理员令牌已失效，请重新输入。";
    return;
  }
  toast(error.message || "操作失败", true);
}

/* ---------- 视图路由 ---------- */

function currentRoute() {
  const name = (location.hash || "").replace(/^#\/?/, "");
  return VIEWS.includes(name) ? name : "overview";
}

function showView(name, {updateHash = true} = {}) {
  state.view = name;
  VIEWS.forEach((view) => {
    const section = byId(`view-${view}`);
    if (section) section.hidden = view !== name;
  });
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === name);
  });
  const active = byId(`view-${name}`);
  byId("topbar-title").textContent = active ? active.dataset.title : "概览";
  if (updateHash && `#/${name}` !== location.hash) {
    history.replaceState(null, "", `#/${name}`);
  }
}

/* ---------- 概览 ---------- */

function setReadiness(id, tone, message) {
  const item = byId(id);
  item.className = `check-item is-${tone}`;
  item.querySelector("p").textContent = message;
}

function qualityBlockers(quality) {
  return [
    "collection_contamination_count",
    "duplicate_active_annual_series_count",
    "date_conflict_count",
    "missing_required_attachment_count",
  ].reduce((sum, key) => sum + Number(quality[key] || 0), 0);
}

function fillSelect(select, items, placeholder) {
  const selected = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  items.forEach(([value, label]) => select.add(new Option(label, value)));
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

function renderReleaseBanner(overview, qualityReady, blockers) {
  const banner = byId("release-banner");
  const title = byId("release-banner-title");
  const detail = byId("release-banner-detail");
  banner.hidden = false;
  banner.className = "banner";
  const indexReady = overview.freshness.index_matches_manifest;
  const quality = overview.quality;
  if (indexReady) {
    banner.classList.add("is-ready");
    title.textContent = "学生端已是最新版本";
    detail.textContent = "馆藏与问答索引一致，无需发布。";
  } else if (qualityReady) {
    banner.classList.add("is-ready");
    title.textContent = "可以发布";
    detail.textContent = "质量体检已通过，发布后学生端立即使用新资料。";
  } else if (!quality.available || !quality.fresh) {
    banner.classList.add("is-pending");
    title.textContent = "发布前需要体检";
    detail.textContent = "馆藏已变化或尚无体检报告，请先点击右上角“重新体检”。";
  } else {
    banner.classList.add("is-blocked");
    title.textContent = `暂不可发布：${blockers} 个阻断项`;
    detail.textContent = "请到“文档”视图处理被隔离或缺附件的文档，再重新体检。";
  }
}

function renderOverview(overview) {
  state.overview = overview;
  Object.entries(overview.counts).forEach(([key, value]) => {
    const target = byId(`count-${key}`);
    if (target) target.textContent = Number(value).toLocaleString("zh-CN");
  });

  const quality = overview.quality;
  const blockers = quality.available && quality.fresh ? qualityBlockers(quality) : 0;
  const qualityReady = quality.available && quality.fresh && blockers === 0;
  if (!quality.available) setReadiness("quality-readiness", "warning", "尚无体检报告，请点击“重新体检”");
  else if (!quality.fresh) setReadiness("quality-readiness", "warning", "馆藏已变化，需要重新体检");
  else if (blockers) setReadiness("quality-readiness", "error", `${blockers} 个阻断项需要处理`);
  else setReadiness("quality-readiness", "ok", `报告有效 · ${formatDate(quality.evaluated_at)}`);

  const indexReady = overview.freshness.index_matches_manifest;
  setReadiness(
    "index-readiness",
    indexReady ? "ok" : "warning",
    indexReady ? `已发布 · ${formatDate(overview.freshness.indexed_at)}` : "馆藏领先于学生端，等待发布",
  );

  const gates = overview.gates;
  if (!gates.available) setReadiness("gate-readiness", "warning", "尚无完整验收报告");
  else if (!gates.fresh) setReadiness("gate-readiness", "warning", "验收快照已过期");
  else if (!gates.passed) setReadiness("gate-readiness", "error", `${gates.failed.length} 项完整验收未通过`);
  else setReadiness("gate-readiness", "ok", "完整验收通过");

  renderReleaseBanner(overview, qualityReady, blockers);

  const release = byId("release-state");
  release.className = "release-pill";
  if (indexReady) {
    release.textContent = "学生端已是当前版本";
    release.classList.add("is-ready");
  } else if (qualityReady) {
    release.textContent = "可以发布";
  } else {
    release.textContent = "暂不可发布";
    release.classList.add("is-blocked");
  }
  byId("publish-button").disabled = indexReady || !qualityReady;
  byId("fingerprint-note").textContent =
    `语料 ${shortFingerprint(overview.freshness.manifest_fingerprint)} · 索引 ${shortFingerprint(overview.freshness.index_fingerprint)}`;

  fillSelect(
    byId("category-filter"),
    overview.categories.map((item) => [item.category, `${item.category}（${item.documents}）`]),
    "全部分类",
  );
  fillSelect(
    byId("import-category"),
    overview.categories.map((item) => [item.category, item.category]),
    "请选择",
  );
  fillSelect(
    byId("answer-category"),
    overview.categories.map((item) => [item.category, item.category]),
    "请选择",
  );
  fillSelect(
    byId("quality-filter"),
    Object.entries(overview.quality_statuses).map(([value, count]) => [value, `${display(value)}（${count}）`]),
    "全部状态",
  );
  fillSelect(
    byId("source-filter"),
    Object.entries(overview.source_types).map(([value, count]) => [value, `${display(value)}（${count}）`]),
    "全部来源",
  );
  renderTimeline(overview.timeline);
  renderCategories(overview.categories);
  renderRecent(overview.recent_documents || []);
}

function renderRecent(docs) {
  const list = byId("recent-documents");
  list.replaceChildren();
  docs.slice(0, 8).forEach((doc) => {
    const item = element("li");
    const title = element("span", "", doc.title);
    title.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    item.append(title, element("time", "", formatDate(doc.fetched_at)));
    item.style.cursor = "pointer";
    item.addEventListener("click", () => openDocument(doc.doc_id, item).catch(handleError));
    list.append(item);
  });
  if (!docs.length) list.append(element("li", "", "尚无入库记录"));
}

function renderTimeline(days) {
  const ruler = byId("timeline-ruler");
  ruler.replaceChildren();
  if (!days.length) {
    ruler.append(element("p", "timeline-empty", "尚无入库记录"));
    return;
  }
  const shown = days.slice(0, 45).reverse();
  const maximum = Math.max(...shown.map((day) => day.documents), 1);
  shown.forEach((day) => {
    const button = element("button", "timeline-day");
    button.type = "button";
    button.setAttribute("role", "listitem");
    button.classList.toggle("is-selected", state.fetchedDay === day.date);
    button.title = `${day.date}：${day.documents} 份，${day.isolated} 份待治理`;
    const bar = element("span", "timeline-day__bar");
    bar.style.height = `${Math.max(4, Math.round(day.documents / maximum * 104))}px`;
    const risk = element("span", "timeline-day__risk");
    risk.style.height = `${day.documents ? Math.round(day.isolated / day.documents * 100) : 0}%`;
    bar.append(risk);
    button.append(bar, element("span", "timeline-day__date", day.date.slice(5)));
    button.addEventListener("click", () => {
      state.fetchedDay = state.fetchedDay === day.date ? "" : day.date;
      state.offset = 0;
      byId("clear-day-filter").hidden = !state.fetchedDay;
      renderTimeline(days);
      showView("documents");
      loadDocuments().catch(handleError);
    });
    ruler.append(button);
  });
}

function renderCategories(categories) {
  const register = byId("category-register");
  register.replaceChildren();
  const maximum = Math.max(...categories.map((item) => item.documents), 1);
  categories.forEach((item) => {
    const button = element("button", "category-row");
    button.type = "button";
    button.classList.toggle("is-selected", byId("category-filter").value === item.category);
    const meter = element("span", "category-meter");
    const fill = element("i");
    fill.style.width = `${Math.round(item.documents / maximum * 100)}%`;
    meter.append(fill);
    const count = element("span", "category-count", `${item.searchable} 可检索`);
    count.append(element("small", "", `${item.attention} 待治理`));
    button.append(element("strong", "", item.category), meter, count);
    button.addEventListener("click", () => {
      const filter = byId("category-filter");
      filter.value = filter.value === item.category ? "" : item.category;
      state.offset = 0;
      renderCategories(categories);
      showView("documents");
      loadDocuments().catch(handleError);
    });
    register.append(button);
  });
}

/* ---------- 文档列表 ---------- */

function documentParams() {
  const params = new URLSearchParams({offset: state.offset, limit: state.limit});
  const filters = {
    q: byId("search-filter").value.trim(),
    category: byId("category-filter").value,
    quality_status: byId("quality-filter").value,
    source_type: byId("source-filter").value,
    fetched_day: state.fetchedDay,
  };
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params;
}

function statusClass(value) {
  if (value === "accepted") return "is-ok";
  if (value === "low_quality") return "is-warning";
  return "is-error";
}

function renderDocuments(result) {
  const rows = byId("document-rows");
  rows.replaceChildren();
  result.items.forEach((doc) => {
    const row = element("tr", "document-row");
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `查看 ${doc.title}`);
    const source = element("td");
    source.append(
      element("strong", "document-title", doc.title),
      element("span", "document-source", `${doc.publisher || "发布单位未知"} · ${doc.source_url}`),
    );
    const status = element("span", `status-tag ${statusClass(doc.quality_status)}`, display(doc.quality_status));
    row.append(
      element("td", "document-date", formatDate(doc.fetched_at)),
      source,
      element("td", "category-cell", doc.category),
      element("td"),
      element("td", "destination", display(doc.index_collection)),
    );
    row.children[3].append(status);
    const open = () => openDocument(doc.doc_id, row).catch(handleError);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
    rows.append(row);
  });
  byId("empty-state").hidden = result.total !== 0;
  byId("result-count").textContent = `${result.total.toLocaleString("zh-CN")} 份文档`;
  const pages = Math.ceil(result.total / result.limit);
  const page = result.total ? Math.floor(result.offset / result.limit) + 1 : 0;
  byId("page-label").textContent = `第 ${page} / ${pages} 页`;
  byId("previous-page").disabled = result.offset === 0;
  byId("next-page").disabled = result.offset + result.limit >= result.total;
}

async function loadOverview() {
  renderOverview(await api("/api/admin/overview"));
}

async function loadDocuments() {
  renderDocuments(await api(`/api/admin/documents?${documentParams()}`));
}

/* ---------- 问答诊室 ---------- */

function renderEvidence(hits) {
  const list = byId("evidence-list");
  list.replaceChildren();
  const seen = new Set();
  hits.forEach((hit) => {
    if (seen.has(hit.doc_id)) return;
    seen.add(hit.doc_id);
    const label = element("label", "evidence-option");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = hit.doc_id;
    input.name = "source-doc";
    const details = element("span");
    details.append(
      element("strong", "", hit.title),
      element("small", "", `${hit.publisher} · ${formatDate(hit.publish_date)} · 相似度 ${hit.vector_similarity === null ? "—" : hit.vector_similarity.toFixed(3)}`),
      element("small", "evidence-excerpt", hit.excerpt),
    );
    label.append(input, details);
    list.append(label);
  });
  if (!seen.size) list.append(element("p", "panel-note", "没有可选依据。请先到“导入资料”补充官方文件并发布。"));
}

function renderDebug(result) {
  state.debugQuestion = result.question;
  byId("debug-result").hidden = false;
  byId("debug-answer").textContent = result.error || result.answer;
  const status = byId("debug-status");
  status.className = "debug-status";
  if (result.error || (result.citation_check && !result.citation_check.ok)) {
    status.textContent = result.error || "回答已生成，但引用检查未通过";
    status.classList.add("is-error");
  } else if (result.refused) {
    status.textContent = "已安全拒答 · 下方显示最接近的候选资料";
    status.classList.add("is-error");
  } else {
    status.textContent = `回答成功 · ${result.source_cards.length} 个来源卡片 · 引用检查通过`;
    status.classList.add("is-ok");
  }
  renderEvidence(result.hits);
  byId("curated-answer").value = result.refused
    ? ""
    : result.answer.replace(/\s*\[\s*\d+\s*\]/g, "").trim();
  if (result.hits[0]) byId("answer-category").value = result.hits[0].category;
  byId("answer-note").textContent = "请逐项核对答复内容，并主动选择真正支撑它的资料。";
}

async function debugQuestion(question) {
  renderDebug(await api("/api/admin/debug", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({question}),
  }));
}

async function runDebug(event) {
  event.preventDefault();
  const question = byId("debug-question").value.trim();
  const button = byId("debug-button");
  button.disabled = true;
  button.textContent = "检索与生成中…";
  try {
    await debugQuestion(question);
    byId("debug-result").scrollIntoView({block: "start"});
  } finally {
    button.disabled = false;
    button.textContent = "运行真实问答";
  }
}

async function saveCuratedAnswer(event) {
  event.preventDefault();
  const sourceDocIds = [...document.querySelectorAll('input[name="source-doc"]:checked')]
    .map((input) => input.value);
  if (!sourceDocIds.length) {
    toast("至少勾选一份真正支撑答复的官方资料", true);
    return;
  }
  const button = byId("save-answer-button");
  button.disabled = true;
  button.textContent = "写入并索引中…";
  try {
    const result = await api("/api/admin/answers", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        question: state.debugQuestion,
        answer: byId("curated-answer").value.trim(),
        category: byId("answer-category").value,
        editor: byId("answer-editor").value.trim(),
        source_doc_ids: sourceDocIds,
      }),
    });
    byId("answer-note").textContent =
      `已生成版本 ${result.document.content_hash || "—"}；增量索引新增 ${result.index.added_docs}、更新 ${result.index.updated_docs}。`;
    toast("标准答复已增量发布，正在复测");
    await Promise.all([loadOverview(), loadDocuments()]);
    await debugQuestion(state.debugQuestion);
  } finally {
    button.disabled = false;
    button.textContent = "保存并增量索引";
  }
}

/* ---------- 文档抽屉 ---------- */

function safeSourceUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_error) {
    return "";
  }
}

async function openDocument(docId, trigger) {
  const result = await api(`/api/admin/documents/${encodeURIComponent(docId)}`);
  const doc = result.document;
  state.activeDocId = docId;
  state.previewVersion = "";
  state.lastFocus = trigger || document.activeElement;
  byId("drawer-id").textContent = `编号 ${doc.doc_id}`;
  byId("drawer-title").textContent = doc.title;
  byId("drawer-publisher").textContent = doc.publisher || "发布单位未知";
  const facts = byId("document-facts");
  facts.replaceChildren();
  [
    ["知识分类", doc.category],
    ["质量状态", display(doc.quality_status)],
    ["公开日期", formatDate(doc.publish_date)],
    ["最近入库", formatDate(doc.fetched_at)],
    ["资料类型", display(doc.document_kind)],
    ["有效性", display(doc.validity_status)],
    ["来源类型", display(doc.source_type)],
    ["问答去向", display(doc.index_collection)],
  ].forEach(([term, value]) => {
    const item = element("div");
    item.append(element("dt", "", term), element("dd", "", value));
    facts.append(item);
  });
  const source = byId("drawer-source");
  const href = safeSourceUrl(doc.source_url);
  source.hidden = !href;
  if (href) source.href = href;
  else source.removeAttribute("href");
  byId("document-content").textContent = result.content || "当前版本没有可显示的正文。";
  byId("content-note").textContent = result.content_truncated ? "正文过长，仅显示前 20 万字" : "完整正文";

  const action = byId("document-action");
  const restoring = doc.quality_status === "quarantined";
  action.dataset.action = restoring ? "restore" : "quarantine";
  action.textContent = restoring ? "恢复这份文档" : "隔离这份文档";
  action.classList.toggle("is-restore", restoring);
  byId("governance-note").textContent = restoring
    ? "恢复后仍需重新体检并发布，才会回到学生问答端。"
    : "隔离后不会进入下一次索引，原正文仍保留用于恢复。";
  byId("action-reason").value = "";

  const history = byId("document-history");
  history.replaceChildren();
  result.history.forEach((version) => {
    const item = element("li");
    const summary = element("span", "", `${display(version.quality_status)} · ${display(version.retention_status)} · ${display(version.index_collection)}`);
    item.append(element("time", "", formatDate(version.fetched_at)), summary);
    if (version.version_available && !version.is_current) {
      const view = element("button", "version-button", "查看此版");
      view.type = "button";
      view.addEventListener("click", () => previewDocumentVersion(version.content_hash).catch(handleError));
      item.append(view);
    }
    history.append(item);
  });
  byId("drawer-backdrop").hidden = false;
  byId("document-drawer").hidden = false;
  document.body.style.overflow = "hidden";
  byId("drawer-title").focus();
}

async function previewDocumentVersion(contentHash) {
  const result = await api(
    `/api/admin/documents/${encodeURIComponent(state.activeDocId)}/versions/${encodeURIComponent(contentHash)}`,
  );
  state.previewVersion = result.content_hash;
  byId("document-content").textContent = result.content;
  byId("content-note").textContent = `历史版本 · ${formatDate(result.fetched_at)}`;
  const action = byId("document-action");
  action.dataset.action = "rollback";
  action.textContent = "回退到正在查看的版本";
  action.classList.add("is-restore");
  byId("governance-note").textContent = "回退会追加一个新版本，不删除当前版；之后需重新体检并发布。";
  byId("action-reason").value = "";
}

function closeDrawer() {
  byId("drawer-backdrop").hidden = true;
  byId("document-drawer").hidden = true;
  document.body.style.overflow = "";
  if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
}

async function runDocumentAction() {
  const action = byId("document-action").dataset.action;
  const reason = byId("action-reason").value.trim();
  if (reason.length < 2) {
    byId("action-reason").focus();
    toast("请填写至少 2 个字的操作说明", true);
    return;
  }
  const verb = action === "restore" ? "恢复" : "隔离";
  const actionVerb = action === "rollback" ? "回退" : verb;
  if (!window.confirm(`确认${actionVerb}这份文档？操作会写入版本记录。`)) return;
  const button = byId("document-action");
  button.disabled = true;
  try {
    await api(`/api/admin/documents/${encodeURIComponent(state.activeDocId)}/action`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action, reason, version_hash: state.previewVersion}),
    });
    toast(`已${actionVerb}；请重新体检后再发布。`);
    await Promise.all([loadOverview(), loadDocuments()]);
    await openDocument(state.activeDocId);
  } finally {
    button.disabled = false;
  }
}

/* ---------- 体检 / 发布 ---------- */

async function runAudit() {
  const button = byId("audit-button");
  button.disabled = true;
  button.textContent = "体检中…";
  try {
    const result = await api("/api/admin/audit", {method: "POST"});
    const blockers = qualityBlockers(result.quality);
    toast(blockers ? `体检完成：仍有 ${blockers} 个阻断项` : "体检通过，可以发布", Boolean(blockers));
    await loadOverview();
  } finally {
    button.disabled = false;
    button.textContent = "重新体检";
  }
}

async function pollJob() {
  window.clearTimeout(state.pollTimer);
  try {
    const job = await api("/api/admin/job");
    if (job.status === "running") {
      byId("publish-button").disabled = true;
      byId("publish-button").textContent = "发布中…";
      state.pollTimer = window.setTimeout(pollJob, 1200);
    } else {
      byId("publish-button").textContent = "发布到问答库";
      if (job.status === "completed") toast("知识库已发布到学生问答端");
      if (job.status === "failed") toast(`发布失败：${job.error || "请检查服务日志"}`, true);
      await loadOverview();
    }
  } catch (error) {
    handleError(error);
  }
}

async function runPublish() {
  if (!window.confirm("确认用当前馆藏更新学生问答库？发布期间问答会短暂暂停。")) return;
  try {
    await api("/api/admin/publish", {method: "POST"});
    toast("发布任务已开始");
    pollJob();
  } catch (error) {
    handleError(error);
  }
}

/* ---------- 导入 ---------- */

async function runImport(event) {
  event.preventDefault();
  const file = byId("import-file").files[0];
  if (!file) return;
  if (file.size > 25_000_000) {
    toast("文件超过 25 MB，请压缩或拆分后再导入", true);
    return;
  }
  const params = new URLSearchParams({
    filename: file.name,
    category: byId("import-category").value,
    publisher: byId("import-publisher").value.trim(),
    source_url: byId("import-source-url").value.trim(),
  });
  const button = byId("import-button");
  button.disabled = true;
  button.textContent = "解析检查中…";
  try {
    const result = await api(`/api/admin/import?${params}`, {
      method: "POST",
      headers: {"Content-Type": "application/octet-stream"},
      body: file,
    });
    byId("import-form").reset();
    byId("import-note").textContent = `已导入《${result.document.title}》。下一步：体检并发布；发布后可作为标准答复依据。`;
    toast("资料已进入待发布馆藏");
    state.offset = 0;
    await Promise.all([loadOverview(), loadDocuments()]);
  } finally {
    button.disabled = false;
    button.textContent = "检查并导入";
  }
}

async function runWechatImport(event) {
  event.preventDefault();
  const button = byId("wechat-import-button");
  button.disabled = true;
  button.textContent = "抓取检查中…";
  try {
    const result = await api("/api/admin/wechat/import", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: byId("wechat-url").value.trim()}),
    });
    const titles = result.documents.map((documentItem) => `《${documentItem.title}》`).join("、");
    byId("wechat-import-form").reset();
    byId("wechat-import-note").textContent = `已入库 ${titles}。下一步：体检并发布。`;
    toast("公众号文章已通过白名单与质量门");
    state.offset = 0;
    await Promise.all([loadOverview(), loadDocuments()]);
  } finally {
    button.disabled = false;
    button.textContent = "抓取并入库";
  }
}

/* ---------- 登录 / 登出 ---------- */

function logout() {
  window.clearTimeout(state.pollTimer);
  state.token = "";
  sessionStorage.removeItem("sufe-admin-token");
  byId("admin-shell").hidden = true;
  byId("login-shell").hidden = false;
  byId("admin-token").value = "";
  closeDrawer();
}

async function enterAdmin() {
  await api("/api/admin/session");
  sessionStorage.setItem("sufe-admin-token", state.token);
  byId("login-message").textContent = "";
  byId("login-shell").hidden = true;
  byId("admin-shell").hidden = false;
  showView(currentRoute(), {updateHash: false});
  await Promise.all([loadOverview(), loadDocuments()]);
  const job = await api("/api/admin/job");
  if (job.status === "running") pollJob();
}

/* ---------- 事件绑定 ---------- */

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = byId("admin-token").value.trim();
  byId("login-message").textContent = "正在验证…";
  try {
    await enterAdmin();
  } catch (error) {
    sessionStorage.removeItem("sufe-admin-token");
    byId("login-message").textContent = error.message;
  }
});

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    showView(item.dataset.view);
  });
});
document.querySelectorAll("[data-goto]").forEach((card) => {
  card.addEventListener("click", () => {
    if (card.dataset.goto === "documents-attention") {
      byId("quality-filter").value = "quarantined";
      state.offset = 0;
      loadDocuments().catch(handleError);
    }
    showView("documents");
  });
});
window.addEventListener("hashchange", () => {
  if (!byId("admin-shell").hidden) showView(currentRoute(), {updateHash: false});
});

let searchTimer;
byId("search-filter").addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    state.offset = 0;
    loadDocuments().catch(handleError);
  }, 250);
});
["category-filter", "quality-filter", "source-filter"].forEach((id) => {
  byId(id).addEventListener("change", () => {
    state.offset = 0;
    if (id === "category-filter" && state.overview) renderCategories(state.overview.categories);
    loadDocuments().catch(handleError);
  });
});
byId("filter-form").addEventListener("submit", (event) => event.preventDefault());
byId("filter-form").addEventListener("reset", () => window.setTimeout(() => {
  state.offset = 0;
  state.fetchedDay = "";
  byId("clear-day-filter").hidden = true;
  if (state.overview) {
    renderTimeline(state.overview.timeline);
    renderCategories(state.overview.categories);
  }
  loadDocuments().catch(handleError);
}));
byId("clear-day-filter").addEventListener("click", () => {
  state.fetchedDay = "";
  state.offset = 0;
  byId("clear-day-filter").hidden = true;
  if (state.overview) renderTimeline(state.overview.timeline);
  loadDocuments().catch(handleError);
});
byId("previous-page").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  loadDocuments().catch(handleError);
});
byId("next-page").addEventListener("click", () => {
  state.offset += state.limit;
  loadDocuments().catch(handleError);
});
byId("drawer-close").addEventListener("click", closeDrawer);
byId("drawer-backdrop").addEventListener("click", closeDrawer);
byId("document-action").addEventListener("click", () => runDocumentAction().catch(handleError));
byId("debug-form").addEventListener("submit", (event) => runDebug(event).catch(handleError));
byId("answer-form").addEventListener("submit", (event) => saveCuratedAnswer(event).catch(handleError));
byId("audit-button").addEventListener("click", () => runAudit().catch(handleError));
byId("publish-button").addEventListener("click", runPublish);
byId("import-form").addEventListener("submit", (event) => runImport(event).catch(handleError));
byId("wechat-import-form").addEventListener("submit", (event) => runWechatImport(event).catch(handleError));
byId("logout-button").addEventListener("click", logout);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !byId("document-drawer").hidden) closeDrawer();
});

if (state.token) {
  enterAdmin().catch((error) => {
    logout();
    byId("login-message").textContent = error.status === 503
      ? "服务端尚未配置管理员令牌。"
      : "上次管理会话已失效，请重新输入。";
  });
}
