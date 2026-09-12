"""严格引用 prompt：所有约束集中在 system prompt，资料编号与来源卡片一一对应。"""

from __future__ import annotations

from sufe_qa.retrieve.retriever import Hit

SYSTEM_PROMPT = """\
你是上海财经大学校园问答助手，只依据给定资料回答学生的问题。

硬性规则：
1. 只能使用"资料"中的信息，不得用你自己的知识补充或推测；
2. 每条关键论断（条件、日期、金额、比例、流程、文件名）必须在句末标注来源编号，如 [1][2]；
3. 严禁编造文件名、日期、金额、比例、部门名称；资料中没有的信息，明确说"已收录的资料中未提及"；
4. 版本判定优先级：资料块标注了版本状态（现行/旧版/历史）时，一律以"现行"版本为准作答，
   不得仅按发布日期新旧推翻版本状态；仅在资料块没有版本标注时，才按发布日期最新者为准；
   引用旧版内容必须在回答中明确提示其可能已失效；
5. 资料不足以回答时，直接说明，并建议学生查看相关职能部门官网或到现场咨询；
6. 若问题未指定具体学院而资料仅来自个别学院，必须明确说明"已收录资料仅覆盖部分学院"，
   不得把部分学院当作完整名单；全校性政策问题优先引用校级部门（研究生院、教务处、学生处等）
   发布的资料；
7. 用简体中文分点回答，控制在 300 字以内。"""


_VALIDITY_LABEL = {
    "current": "现行",
    "superseded": "已被新版取代",
    "historical": "历史版本",
}

# verified_at 是人工核验日期而非官方发布日期：curated 标准答复标 publish_date=unknown，
# 统一展示为"发布日期待核"，避免人工整理稿伪装成最新官方发布


def build_context(hits: list[Hit]) -> str:
    """把融合后的 chunks 编号为 [1]..[n] 资料块，编号即引用编号；标注版本状态与发布日期。"""
    blocks = []
    for i, h in enumerate(hits, start=1):
        head = f"[{i}] 《{h.title}》"
        if h.heading_path:
            head += f" {h.heading_path}"
        validity = _VALIDITY_LABEL.get(getattr(h, "validity_status", ""), "")
        version_note = f"，版本：{validity}" if validity else ""
        publish = h.publish_date if h.publish_date != "unknown" else "待核"
        blocks.append(f"{head}（{h.publisher}，发布于 {publish}{version_note}）\n{h.text}")
    return "\n\n".join(blocks)


def build_messages(question: str, hits: list[Hit]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n{build_context(hits)}\n\n问题：{question}"},
    ]
