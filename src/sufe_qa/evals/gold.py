"""gold.v1 人工金标评测集：校验器 + 标注候选推荐。

与 150 题覆盖探针（sufe_question_bank）、冻结措辞集（holdout.v1）分工：
gold 由人工精标 expected_doc_ids / required_answer_points / evidence / gold_answer，
evidence_text 必须与原文逐字吻合（校验器强制），用于判断"检索对没对、答案对没对、
引用支不支撑"。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sufe_qa.indexing.collections import collection_for_kind
from sufe_qa.schema import load_manifest

SCENES = {
    "本科教务",
    "奖助学金",
    "研究生培养与学位",
    "就业手续",
    "宿舍后勤",
    "信息化与校园卡",
    "图书馆",
    "医疗医保",
    "国际交流",
    "新生与安全",
    "推免与招生",
}
INTENTS = {"条件", "材料", "流程", "时间", "地点", "金额", "资格"}
VALIDITY = {"current", "historical", "superseded", "unknown_validity"}
# 泛词不算要点：要点必须是可检查的事实
# 泛词不算要点：整句仅由泛词组成（如"申请""申请流程"）即拒绝
GENERIC_POINT = re.compile(
    r"^(申请|流程|办理|部门|材料|条件|时间|地点|联系方式|注意事项|规定|办法)+$"
)


@dataclass
class GoldIssue:
    id: str
    level: str  # error | warn
    message: str


@dataclass
class GoldReport:
    total: int
    issues: list[GoldIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[GoldIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[GoldIssue]:
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def validate_gold(path: Path, manifest_path: Path, corpus_dir: Path | None = None) -> GoldReport:
    """逐条校验 gold 集：schema、词表、来源文档现行性、evidence 逐字存在。"""
    corpus_dir = corpus_dir or manifest_path.parent
    manifest = load_manifest(manifest_path)
    issues: list[GoldIssue] = []
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            issues.append(GoldIssue(f"第{lineno}行", "error", f"不是合法 JSON: {exc}"))
    report = GoldReport(total=len(rows), issues=issues)
    seen_ids: set[str] = set()

    for row in rows:
        rid = str(row.get("id", "?"))

        def err(msg: str) -> None:
            issues.append(GoldIssue(rid, "error", msg))

        def warn(msg: str) -> None:
            issues.append(GoldIssue(rid, "warn", msg))

        if rid in seen_ids:
            err(f"重复 id: {rid}")
        seen_ids.add(rid)

        # ---- 1. 基本属性与词表 ----
        for f in ("question", "scene", "topic_key", "question_intent", "student_type"):
            if not row.get(f):
                err(f"缺字段: {f}")
        if row.get("scene") and row["scene"] not in SCENES:
            err(f"scene 不在词表: {row['scene']}")
        if row.get("question_intent") and row["question_intent"] not in INTENTS:
            warn(f"question_intent 建议用词表 {sorted(INTENTS)}: {row['question_intent']}")
        for f in ("should_answer", "should_refuse", "needs_clarification", "needs_current_version"):
            if not isinstance(row.get(f), bool):
                err(f"{f} 必须是 true/false")
        if row.get("should_answer") and row.get("should_refuse"):
            err("should_answer 与 should_refuse 不能同时 true")

        # ---- 2. 权威来源 ----
        doc_ids = [str(x) for x in row.get("expected_doc_ids") or []]
        if row.get("should_answer") and not doc_ids:
            err("应答题必须有 expected_doc_ids（至少一份人工确认的正确原文）")
        if row.get("should_refuse") and doc_ids:
            warn("拒答题一般不留 expected_doc_ids")
        for doc_id in doc_ids:
            meta = manifest.get(doc_id)
            if meta is None:
                err(f"expected_doc_id 不存在于 manifest: {doc_id}")
                continue
            if meta.quality_status != "accepted" or meta.retention_status != "active":
                err(
                    f"gold 来源不是现行文档: {doc_id}（{meta.quality_status}/{meta.retention_status}）"
                )
            # 以 kind+retention 实时判定是否入索引（manifest 的 index_collection 字段可能过期）
            if collection_for_kind(meta.document_kind, meta.retention_status) is None:
                err(f"gold 来源按其类型不会进入检索索引: {doc_id}")
            if meta.validity_status in {"superseded", "historical"}:
                warn(f"gold 来源已是旧版（{meta.validity_status}），确认是否应换现行版: {doc_id}")
        publishers = {manifest[d].publisher for d in doc_ids if d in manifest}
        for pub in row.get("expected_publishers") or []:
            if publishers and pub not in publishers:
                warn(f"expected_publisher 与来源文档发布单位不符: {pub}")

        # ---- 3. 要点必须是可以检查的事实 ----
        points = [str(p) for p in row.get("required_answer_points") or []]
        if row.get("should_answer") and not points:
            err("应答题必须有 required_answer_points")
        for p in points:
            if GENERIC_POINT.match(_squash(p)):
                err(f"要点太泛，需写成可检查的事实句: {p}")
            elif len(_squash(p)) < 6:
                warn(f"要点偏短，可能难以区分对错: {p}")

        # ---- 4. evidence 逐字核对（防标注者脑补）----
        for ev in row.get("evidence") or []:
            ev_doc = str(ev.get("doc_id", ""))
            ev_text = str(ev.get("evidence_text", ""))
            meta = manifest.get(ev_doc)
            if meta is None or not meta.file_path:
                err(f"evidence 文档不存在或无正文: {ev_doc}")
                continue
            body_path = corpus_dir / meta.file_path
            if not body_path.is_file():
                err(f"evidence 正文文件缺失: {meta.file_path}")
                continue
            body = body_path.read_text(encoding="utf-8", errors="replace")
            if _squash(ev_text) not in _squash(body):
                err(f"evidence_text 在原文中逐字找不到（{ev_doc}）: {ev_text[:40]}…")

        # ---- 5. gold_answer 长度 ----
        gold_answer = str(row.get("gold_answer") or "")
        if row.get("should_answer"):
            n = len(gold_answer)
            if not (30 <= n <= 300):
                warn(f"gold_answer 建议 50~150 字（当前 {n} 字）")

        # ---- 5.5 机器起草必须有人工复核署名 ----
        if "ai-draft" in str(row.get("reviewer", "")):
            warn("机器起草待人工复核：复核通过后把 reviewer 改为复核人署名")

        # ---- 6. 版本有效性人工确认 ----
        vs = str(row.get("validity_status") or "")
        if vs and vs not in VALIDITY:
            err(f"validity_status 词表外: {vs}")
        if row.get("needs_current_version") and vs == "unknown_validity":
            warn("needs_current_version=true 但版本有效性标了 unknown，请尽量确认")

    return report


def suggest_candidates(question: str, retriever, n: int = 8) -> list[dict]:
    """对给定问题跑真实检索，返回候选官方文档供人工勾选 gold 来源。"""
    out = []
    for hit in retriever.search_routed(question)[:n]:
        out.append(
            {
                "doc_id": hit.doc_id,
                "title": hit.title,
                "publisher": hit.publisher,
                "publish_date": hit.publish_date,
                "validity_status": hit.validity_status,
                "similarity": round(hit.vector_similarity or 0.0, 3),
                "snippet": hit.text[:160].replace("\n", " "),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 机器起草：人只做复核确认，不手写 JSON
# ---------------------------------------------------------------------------

DRAFT_SYSTEM = """你是校务问答评测集的标注助手。根据给定的官方资料为问题起草 gold 标注。
硬性要求：
1. 只输出一个 JSON 对象，不要输出任何其他文字；
2. evidence_text 必须逐字复制资料原文（连续片段，可跨标点），禁止改写；
3. required_answer_points 必须是资料直接支撑的具体事实句（含主语和关键值），禁止"申请/流程"式泛词；
4. gold_answer 50~150 字，只写资料支持的内容；
5. question_intent 只能从 条件/材料/流程/时间/地点/金额/资格 中选一个；
6. scene 只能从给定场景词表中选一个；
7. 资料不足以完整回答时，insufficient=true，其余字段尽量给出。"""


def _draft_prompt(question: str, docs: list[dict], scenes: list[str]) -> str:
    blocks = "\n\n".join(
        f"资料 {d['doc_id']}《{d['title']}》（{d['publisher']}，{d['publish_date']}，{d['validity_status']}）\n{d['body'][:3000]}"
        for d in docs
    )
    return f"""问题：{question}

场景词表：{"、".join(scenes)}

{blocks}

请输出 JSON，字段：
{{"question_intent":"流程","scene":"本科教务","student_type":"本科",
 "insufficient":false,
 "required_answer_points":["…"],"evidence":[{{"doc_id":"…","heading":"第X条或空","evidence_text":"…"}}],
 "gold_answer":"…","validity_note":"一句话版本依据说明"}}
student_type 只能从 本科/硕士/博士/全体 中选。evidence 的 doc_id 必须来自上面资料的编号。"""


def _parse_draft_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型未返回 JSON")
    return json.loads(m.group(0))


def draft_gold_entry(
    question: str,
    settings,
    retriever,
    llm,
    *,
    manifest_path: Path,
    corpus_dir: Path,
    reviewer: str = "ai-draft",
    today: str,
    next_seq: int = 1,
) -> tuple[dict, GoldReport]:
    """检索 + LLM 起草 gold 记录；返回 (entry, 校验报告)。人只需复核确认。"""
    from sufe_qa.retrieve.retriever import is_confident

    hits = retriever.search_routed(question)
    confident = bool(hits) and is_confident(hits, settings.vector_min_similarity)
    manifest = load_manifest(manifest_path)

    if not confident:
        entry = {
            "id": f"gold-auto-{next_seq:03d}",
            "question": question,
            "scene": "本科教务",
            "topic_key": "auto.unverified.topic",
            "question_intent": "流程",
            "student_type": "全体",
            "should_answer": False,
            "should_refuse": True,
            "needs_clarification": False,
            "needs_current_version": False,
            "expected_domains": [],
            "expected_doc_ids": [],
            "expected_publishers": [],
            "required_answer_points": [],
            "evidence": [],
            "gold_answer": "",
            "validity_status": "unknown_validity",
            "validity_note": "检索无可靠来源，起草为拒答样例，待人工确认",
            "reviewer": reviewer,
            "reviewed_at": today,
        }
        # 场景/意图留给人工复核修改；先过基本校验
        tmp = corpus_dir / f".gold_draft_{next_seq}.jsonl"
        tmp.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
        report = validate_gold(tmp, manifest_path, corpus_dir)
        tmp.unlink(missing_ok=True)
        return entry, report

    # 选候选文档：现行优先，按命中序去重，最多 3 份
    seen: set[str] = set()
    docs: list[dict] = []
    for h in hits:
        if h.doc_id in seen:
            continue
        meta = manifest.get(h.doc_id)
        if meta is None or not meta.file_path:
            continue
        body_path = corpus_dir / meta.file_path
        if not body_path.is_file():
            continue
        seen.add(h.doc_id)
        docs.append(
            {
                "doc_id": h.doc_id,
                "title": h.title,
                "publisher": h.publisher,
                "publish_date": h.publish_date,
                "validity_status": h.validity_status,
                "body": body_path.read_text(encoding="utf-8", errors="replace"),
            }
        )
        if len(docs) >= 3:
            break

    last_error = ""
    for _attempt in range(2):  # 证据逐字校验失败时带错误信息重试一次
        prompt = _draft_prompt(question, docs, sorted(SCENES))
        if last_error:
            prompt += f"\n\n上一次起草未通过校验：{last_error}。请修正（evidence_text 必须逐字复制原文）。"
        raw = "".join(llm.stream_chat([
            {"role": "system", "content": DRAFT_SYSTEM},
            {"role": "user", "content": prompt},
        ]))
        try:
            draft = _parse_draft_json(raw)
        except ValueError as e:
            last_error = str(e)
            continue
        primary = docs[0]
        entry = {
            "id": f"gold-auto-{next_seq:03d}",
            "question": question,
            "scene": str(draft.get("scene") or "本科教务"),
            "topic_key": f"auto.{primary['doc_id'][:8]}",
            "question_intent": str(draft.get("question_intent") or "流程"),
            "student_type": str(draft.get("student_type") or "全体"),
            "should_answer": not bool(draft.get("insufficient")),
            "should_refuse": bool(draft.get("insufficient")),
            "needs_clarification": False,
            "needs_current_version": True,
            "expected_domains": [],
            "expected_doc_ids": [
                str(d["doc_id"]) for d in docs if d["doc_id"] in {str(e.get("doc_id")) for e in draft.get("evidence") or []}
            ] or [primary["doc_id"]],
            "expected_publishers": sorted(
                {d["publisher"] for d in docs if d["doc_id"] in {str(e.get("doc_id")) for e in draft.get("evidence") or []}}
                or {docs[0]["publisher"]}
            ),
            "required_answer_points": [str(p) for p in draft.get("required_answer_points") or []],
            "evidence": [
                {
                    "doc_id": str(e.get("doc_id", "")),
                    "heading": str(e.get("heading", "")),
                    "evidence_text": str(e.get("evidence_text", "")),
                }
                for e in draft.get("evidence") or []
                if str(e.get("doc_id")) in {d["doc_id"] for d in docs}
            ],
            "gold_answer": str(draft.get("gold_answer") or ""),
            "validity_status": "current",
            "validity_note": str(draft.get("validity_note") or ""),
            "reviewer": reviewer,
            "reviewed_at": today,
        }
        tmp = corpus_dir / f".gold_draft_{next_seq}.jsonl"
        tmp.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
        report = validate_gold(tmp, manifest_path, corpus_dir)
        tmp.unlink(missing_ok=True)
        if report.ok:
            return entry, report
        last_error = "；".join(i.message for i in report.errors[:3])
    return entry, report  # 返回最后草稿与未过校验的报告，由人工定夺
