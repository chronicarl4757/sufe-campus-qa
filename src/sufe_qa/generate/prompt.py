"""严格引用 prompt：所有约束集中在 system prompt，资料编号与来源卡片一一对应。"""

from __future__ import annotations

from sufe_qa.retrieve.retriever import Hit

SYSTEM_PROMPT = """\
你是上海财经大学校园问答助手，只依据给定资料回答学生的问题。

硬性规则：
1. 只能使用"资料"中的信息，不得用你自己的知识补充或推测；
2. 每条关键论断（条件、日期、金额、比例、流程、文件名）必须在句末标注来源编号，如 [1][2]；
3. 严禁编造文件名、日期、金额、比例、部门名称；资料中没有的信息，明确说"已收录的资料中未提及"；
4. 资料不足以回答时，直接说明，并建议学生查看相关职能部门官网或到现场咨询；
5. 用简体中文分点回答，控制在 300 字以内。"""


def build_context(hits: list[Hit]) -> str:
    """把融合后的 chunks 编号为 [1]..[n] 资料块，编号即引用编号。"""
    blocks = []
    for i, h in enumerate(hits, start=1):
        head = f"[{i}] 《{h.title}》"
        if h.heading_path:
            head += f" {h.heading_path}"
        blocks.append(f"{head}（{h.publisher}）\n{h.text}")
    return "\n\n".join(blocks)


def build_messages(question: str, hits: list[Hit]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n{build_context(hits)}\n\n问题：{question}"},
    ]
