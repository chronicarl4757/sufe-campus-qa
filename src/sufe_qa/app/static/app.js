/* 上财校务问答 前端逻辑：SSE 流式渲染答复函，引文联动档案卡，完成后盖印。 */
"use strict";

const thread = document.getElementById("thread");
const emptyState = document.getElementById("empty");
const dock = document.getElementById("dock");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");

const OFFICE_LINKS = [
  ["教务处", "https://jwc.sufe.edu.cn/"],
  ["研究生院", "https://gs.sufe.edu.cn/"],
  ["就业指导中心", "https://career.sufe.edu.cn/"],
];

/* ---------- 档案信息 ---------- */
async function loadMeta() {
  try {
    const r = await fetch("/api/meta");
    const m = await r.json();
    document.getElementById("doc-count").textContent = m.doc_count;
    document.getElementById("updated-at").textContent = m.updated_at
      ? m.updated_at.slice(0, 10)
      : "—";
    const cats = document.getElementById("categories");
    cats.innerHTML = m.categories.length
      ? m.categories.map((c) => `<li>${escapeHtml(c)}</li>`).join("")
      : '<li class="rail-loading">尚无在库档案</li>';
    const box = document.getElementById("examples");
    box.innerHTML = "";
    for (const q of m.examples) {
      const b = document.createElement("button");
      b.className = "example-q";
      b.type = "button";
      b.textContent = q;
      b.addEventListener("click", () => {
        input.value = q;
        dock.requestSubmit();
      });
      box.appendChild(b);
    }
  } catch {
    document.getElementById("updated-at").textContent = "档案信息读取失败";
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/* ---------- SSE：POST 流读取 ---------- */
async function* sseEvents(resp) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let event = "message", data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (data) {
        try { yield { event, data: JSON.parse(data) }; } catch { /* 跳过坏帧 */ }
      }
    }
  }
}

/* ---------- 答复函 DOM ---------- */
function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function addQuery(question) {
  thread.appendChild(
    el(`<div class="query"><span class="query-tag">问</span><p>${escapeHtml(question)}</p></div>`)
  );
}

function addReplyShell() {
  const card = el(`
    <article class="reply">
      <header class="reply-head">
        <div class="reply-title">上财校务问答 · 智能答复</div>
        <div class="reply-rules"><span class="rule-thick"></span><span class="rule-thin"></span></div>
        <div class="reply-no"></div>
      </header>
      <div class="reply-body"><span class="stream"></span><span class="caret"></span></div>
    </article>`);
  thread.appendChild(card);
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  return card;
}

const SEAL_SVG = `
  <svg viewBox="0 0 100 100" aria-hidden="true">
    <circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" stroke-width="3"/>
    <path id="sealArc" d="M 50,50 m -33,0 a 33,33 0 1,1 66,0 a 33,33 0 1,1 -66,0" fill="none"/>
    <text font-size="13" letter-spacing="3" fill="currentColor" font-family="serif">
      <textPath href="#sealArc" startOffset="6%">上财校务问答核讫</textPath>
    </text>
    <path fill="currentColor" d="M50 33l4.6 10.8 11.6.6-9.1 7.3 3.1 11.4L50 56.6l-10.2 6.5 3.1-11.4-9.1-7.3 11.6-.6z"/>
  </svg>`;

/* 正文后处理：转义 → **粗体** → [n] 引文按 cite_map 重编号为卡片序号并可点 */
function renderAnswerText(bodyEl, citeMap) {
  let html = escapeHtml(bodyEl.textContent);
  html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\[(\d{1,2})\]/g, (m, n) => {
    const cardIdx = citeMap[n];
    if (!cardIdx) return m; // 模型写出越界编号，原样保留
    return `<sup class="cite" data-src="${cardIdx}">[${cardIdx}]</sup>`;
  });
  bodyEl.innerHTML = html;
}

function renderSources(card, cards) {
  if (!cards.length) return;
  const box = el(`<section class="attachments"><p class="attachments-title">附件 · 依据档案</p></section>`);
  for (const c of cards) {
    const date = c.publish_date && c.publish_date !== "unknown" ? ` · ${c.publish_date}` : "";
    const a = el(`
      <a class="file-card" id="src-${c.index}" href="${escapeHtml(c.source_url)}"
         target="_blank" rel="noopener">
        <span class="file-no">〔${c.index}〕</span>
        <div><h4>${escapeHtml(c.title)}</h4><p>${escapeHtml(c.publisher)}${escapeHtml(date)}</p></div>
        <span class="file-arrow">→</span>
      </a>`);
    box.appendChild(a);
  }
  card.appendChild(box);
  card.querySelectorAll(".cite").forEach((s) => {
    s.addEventListener("click", () => {
      const target = card.querySelector(`#src-${s.dataset.src}`);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.remove("flash");
      void target.offsetWidth; // 重触发动画
      target.classList.add("flash");
    });
  });
}

function renderFoot(card, question, meta, done) {
  const foot = el(`
    <div class="reply-foot">
      <span>检索 ${meta.retrieval_ms} ms · 全程 ${done.total_ms} ms</span>
      <button class="fb-btn" data-r="up" type="button">此复有据</button>
      <button class="fb-btn" data-r="down" type="button">此复存疑</button>
    </div>`);
  card.appendChild(foot);
  foot.querySelectorAll(".fb-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      const answer = card.querySelector(".reply-body").textContent;
      try {
        await fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, answer, rating: b.dataset.r }),
        });
        foot.innerHTML = `<span class="fb-done">批注已记录在案，谢过。</span>`;
      } catch {
        foot.innerHTML = `<span class="fb-done">批注未能送达，请稍后再试。</span>`;
      }
    });
  });
}

/* ---------- 主流程 ---------- */
async function ask(question) {
  if (emptyState) emptyState.remove();
  addQuery(question);
  const card = addReplyShell();
  const bodyEl = card.querySelector(".reply-body");
  const streamEl = card.querySelector(".stream");
  let meta = { retrieval_ms: 0, doc_no: "" };
  let doneData = null;
  let refused = false;

  try {
    const resp = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    for await (const { event, data } of sseEvents(resp)) {
      if (event === "meta") {
        meta = data;
        refused = data.refused;
        card.querySelector(".reply-no").textContent = data.doc_no;
        if (refused) {
          card.classList.add("refused");
          card.querySelector(".reply-title").textContent = "查无在库可靠依据 · 退文说明";
        }
      } else if (event === "token") {
        streamEl.appendChild(document.createTextNode(data.text));
      } else if (event === "sources") {
        card.dataset.cards = JSON.stringify(data.cards);
        card.dataset.citeMap = JSON.stringify(data.cite_map || {});
        card.dataset.citeCheck = JSON.stringify(data.citation_check || null);
      } else if (event === "done") {
        doneData = data;
      } else if (event === "error") {
        const err = new Error(data.message);
        err.kind = data.kind || "";
        throw err;
      }
    }
  } catch (e) {
    card.remove();
    // 引用门禁撤回：服务端已拦截越界引用，提示与传输故障区分
    const notice = e.kind === "citation_gate"
      ? `${escapeHtml(e.message)}`
      : `答复未能送达：${escapeHtml(e.message)}。请检查服务与网络后重试。`;
    thread.appendChild(el(`<div class="err">${notice}</div>`));
    return;
  }

  card.querySelector(".caret")?.remove();

  if (refused) {
    const links = el(`<div class="office-links"></div>`);
    for (const [name, url] of OFFICE_LINKS) {
      links.appendChild(el(`<a href="${url}" target="_blank" rel="noopener">${name}官网 →</a>`));
    }
    bodyEl.appendChild(links);
    renderFoot(card, question, meta, doneData || { total_ms: 0 });
    return; // 退文不盖印
  }

  const cards = JSON.parse(card.dataset.cards || "[]");
  const citeMap = JSON.parse(card.dataset.citeMap || "{}");
  renderAnswerText(bodyEl, citeMap);
  renderSources(card, cards);
  // 后端引文核验未通过（编号越界或无引用）时降级提示，以来源卡片为准
  const citeCheck = JSON.parse(card.dataset.citeCheck || "null");
  if (citeCheck && !citeCheck.ok) {
    bodyEl.appendChild(
      el(`<div class="cite-warn">引文核验未通过：回答中出现无法对应的来源编号，请以来源卡片与原文为准。</div>`)
    );
  }
  renderFoot(card, question, meta, doneData || { total_ms: 0 });

  // 盖印：答复完成的签名时刻
  const seal = el(`<div class="seal">${SEAL_SVG}</div>`);
  card.appendChild(seal);
  requestAnimationFrame(() => seal.classList.add("stamped"));
}

dock.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  sendBtn.disabled = true;
  ask(q).finally(() => {
    sendBtn.disabled = false;
    input.focus();
  });
});

loadMeta();
