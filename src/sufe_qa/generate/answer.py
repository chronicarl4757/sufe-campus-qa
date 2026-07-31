"""问答编排：检索 → 置信门控（拒答不走 LLM）→ 流式生成 → 来源卡片。"""

from __future__ import annotations

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


@dataclass(frozen=True)
class SourceCard:
    """回答末尾展示的来源卡片；index 为展示序号（1 起连续）。"""

    index: int
    title: str
    publisher: str
    source_url: str


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
        """
        cards: list[SourceCard] = []
        doc_to_card: dict[str, int] = {}
        mapping: dict[int, int] = {}
        for pos, h in enumerate(self.hits, start=1):
            if h.doc_id not in doc_to_card:
                doc_to_card[h.doc_id] = len(cards) + 1
                cards.append(
                    SourceCard(
                        index=doc_to_card[h.doc_id],
                        title=h.title,
                        publisher=h.publisher,
                        source_url=h.source_url,
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
    hits = retriever.search(question)
    if not hits or not is_confident(hits, settings.vector_min_similarity):
        return Answer(question=question, refused=True, hits=[], stream=iter([REFUSAL_TEMPLATE]))
    llm = llm or DeepSeekClient(settings)
    return Answer(
        question=question,
        refused=False,
        hits=hits,
        stream=llm.stream_chat(build_messages(question, hits)),
    )
