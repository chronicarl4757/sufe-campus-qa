"""问答编排：检索 → 置信门控（拒答不走 LLM）→ 流式生成（句子级引用门禁）→ 来源卡片。"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from sufe_qa.config import Settings
from sufe_qa.generate.client import DeepSeekClient, LLMClient
from sufe_qa.generate.prompt import build_messages
from sufe_qa.retrieve.retriever import Hit, HybridRetriever, is_confident

REFUSAL_TEMPLATE = (
    "未在已收录的学校官方资料中找到可靠依据，为避免误导不作回答。\n"
    "建议直接查询相关职能部门官网（教务处/研究生院/学生工作部）或到行政楼现场咨询。"
)

_CITE_RE = re.compile(r"\[\s*(\d+)\s*\]")  # 任意位数编号都进入统一范围校验（[0]/[99]/[100]…）
# 句子边界：引用标注附在句末，按句缓冲即可在发出前完成校验
_SENTENCE_END_RE = re.compile(r"[。！？!?；;\n]")


class CitationGateError(Exception):
    """引用门禁拦截：回答含越界引用编号，未发出的句子一律不下发。"""

    def __init__(self, invalid_refs: list[int]):
        self.invalid_refs = invalid_refs
        super().__init__(f"非法引用编号: {invalid_refs}")


def _raise_on_invalid_refs(segment: str, n_refs: int) -> None:
    invalid = sorted(
        {int(m.group(1)) for m in _CITE_RE.finditer(segment) if not 1 <= int(m.group(1)) <= n_refs}
    )
    if invalid:
        raise CitationGateError(invalid)


def gated_citation_stream(stream: Iterator[str], n_refs: int) -> Iterator[str]:
    """句子级引用门禁：每句发出前校验 [n] 编号落在 1..n_refs，越界即抛错撤回。

    引用编号内不含句末符，按句切分不会拆断 [n] 标记；无引用句正常放行，
    保留流式体验。"全文无引用"不在此拦截，由 sources 事件的 citation_check
    降级提示处理。
    """
    buf = ""
    end = 0
    for token in stream:
        buf += token
        for m in _SENTENCE_END_RE.finditer(buf, end):
            segment = buf[end : m.end()]
            _raise_on_invalid_refs(segment, n_refs)
            yield segment
            end = m.end()
    if end < len(buf):
        segment = buf[end:]
        _raise_on_invalid_refs(segment, n_refs)
        yield segment


@dataclass(frozen=True)
class CitationCheck:
    """回答文本的引用校验结果；ok = 有引用且所有编号都在资料范围内。"""

    ok: bool
    has_citation: bool
    invalid_refs: list[int]


def validate_citations(text: str, n_refs: int) -> CitationCheck:
    """后端强制校验 [n] 引用：编号必须落在 1..n_refs（prompt 资料编号范围）。

    越界编号（如 [99]）在流式路径由 gated_citation_stream 按句拦截并整答撤回，
    不会进入本校验；"全文无引用"判不通过，由服务端记录并随 sources 事件告知
    前端降级提示。论断是否真被资料支撑需 LLM 判分，属评测层职责，不在此校验。
    """
    refs = [int(m.group(1)) for m in _CITE_RE.finditer(text)]
    invalid = sorted({r for r in refs if r < 1 or r > n_refs})
    return CitationCheck(
        ok=bool(refs) and not invalid, has_citation=bool(refs), invalid_refs=invalid
    )


@dataclass(frozen=True)
class SourceCard:
    """回答末尾展示的来源卡片；index 为展示序号（1 起连续）。"""

    index: int
    title: str
    publisher: str
    source_url: str
    publish_date: str = "unknown"


@dataclass
class Answer:
    question: str
    refused: bool
    hits: list[Hit]
    stream: Iterator[str]  # LLM token 流；拒答时为单段模板

    def sources_and_map(self) -> tuple[list[SourceCard], dict[int, int]]:
        """按 doc_id 去重出卡片；返回 (卡片, {prompt 引文编号(命中位次) -> 卡片序号})。

        LLM 按命中位次引用 [n]，同文档多 chunk 合并后卡片序号不连续；
        前端据映射表把 [n] 重编号并锚到正确卡片。
        附件命中展示父级标题，避免「硕士生招生.pdf」这类无上下文文件名误导用户。
        """
        cards: list[SourceCard] = []
        doc_to_card: dict[str, int] = {}
        mapping: dict[int, int] = {}
        for pos, h in enumerate(self.hits, start=1):
            if h.doc_id not in doc_to_card:
                title = f"{h.parent_title}（附件：{h.title}）" if h.parent_title else h.title
                doc_to_card[h.doc_id] = len(cards) + 1
                cards.append(
                    SourceCard(
                        index=doc_to_card[h.doc_id],
                        title=title,
                        publisher=h.publisher,
                        source_url=h.source_url,
                        publish_date=h.publish_date,
                    )
                )
            mapping[pos] = doc_to_card[h.doc_id]
        return cards, mapping

    def sources(self) -> list[SourceCard]:
        return self.sources_and_map()[0]


def answer_question(
    question: str,
    settings: Settings,
    retriever: HybridRetriever,
    llm: LLMClient | None = None,
) -> Answer:
    """低置信直接拒答（不走 LLM）；llm 缺省才构造 DeepSeekClient，便于测试注入。"""
    hits = retriever.search_routed(question)
    if not hits or not is_confident(hits, settings.vector_min_similarity):
        return Answer(question=question, refused=True, hits=[], stream=iter([REFUSAL_TEMPLATE]))
    llm = llm or DeepSeekClient(settings)
    return Answer(
        question=question,
        refused=False,
        hits=hits,
        stream=llm.stream_chat(build_messages(question, hits)),
    )
