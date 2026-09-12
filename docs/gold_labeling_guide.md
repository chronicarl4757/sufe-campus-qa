# 金标集（gold）人工打标与维护手册

`data/eval/gold.v1.jsonl` 是本项目的**金标准评测集**：人工精标 30 题，用来真正回答
"检索对没对、答案对没对、引用支不支撑"。它和其他评测资产的分工：

| 资产 | 作用 | 纪律 |
|---|---|---|
| `evalset.v1.jsonl`（19+3） | 提交前门禁：命中率/回答率/拒答率 | 改动检索或 prompt 前必跑 |
| `sufe_question_bank.jsonl`（150） | 覆盖探针：发现缺什么资料 | 可持续扩写 |
| `holdout.v1.jsonl`（47） | 冻结的未知措辞鲁棒性测量 | 只测量不调参；下次新建 v2 揭题 |
| **`gold.v1.jsonl`（30）** | **金标准：检索/答案/引用三层判分依据** | **人工精标，宁缺毋滥** |

## 一、选题

只标 30 题，挑高频、规则明确、官方资料齐全的，不要故意挑难题。配额建议：

- 本科教务 8：缓考 / 成绩复核 / 转专业 / 休学 / 复学 / 重修 / 学分认定 / 推免基本流程
- 奖助学金 5：国奖金额 / 国奖条件 / 挂科能否参评 / 困难认定 / 国家助学金
- 研究生 5：学籍 / 休学复学 / 奖学金 / 学位论文 / 推免招生
- 就业 4：三方协议 / 灵活就业 / 毕业去向 / 档案
- 信息化与校园生活 5：校园卡 / VPN / 校园网 / 图书馆校外访问 / 宿舍报修
- 拒答与追问 3：模糊提问（如"奖学金怎么申请"→ needs_clarification）、查询他人成绩
  （should_refuse）、明显非校务问题（should_refuse）

## 二、每题要标的字段

```json
{
  "id": "gold-jwc-001",
  "question": "生病参加不了期末考试，缓考要怎么办？",
  "scene": "本科教务",
  "topic_key": "undergraduate.exam.deferment",
  "question_intent": "流程",
  "student_type": "本科",
  "should_answer": true,
  "should_refuse": false,
  "needs_clarification": false,
  "needs_current_version": true,
  "expected_domains": ["sufe.edu.cn"],
  "expected_doc_ids": ["9bca5424fad0"],
  "expected_publishers": ["上海财经大学"],
  "required_answer_points": ["因病申请缓考须持医院出具的诊断证明", "…可检查的事实句…"],
  "evidence": [
    {"doc_id": "9bca5424fad0", "heading": "第十四条",
     "evidence_text": "因病申请缓考的，须持医院出具的诊断证明"}
  ],
  "gold_answer": "50~150 字人工参考答案。",
  "validity_status": "current",
  "validity_note": "2026年4月修订学籍管理实施细则，当前主要依据",
  "reviewer": "你的名字",
  "reviewed_at": "2026-09-12"
}
```

字段要点：

- **question_intent** 用词表：条件 / 材料 / 流程 / 时间 / 地点 / 金额 / 资格。
- **expected_doc_ids** 是最重要字段：人工确认的正确原文 doc_id。不要求检索只命中它们，
  但至少应命中其一。doc_id 从 `data/corpus/manifest.jsonl` 抄，或用下面的 `gold-suggest`。
- **required_answer_points** 必须写成**可以逐字检查的事实句**（"因病申请须持医院诊断证明"），
  不要写"申请/流程/材料/部门"这种泛词——`gold-check` 会拒绝。
- **evidence**：从原文**复制一小段**（几个字到一两句），`gold-check` 会逐字核对它
  真的在文档正文里（空白差异忽略）。标不出来的要点，说明资料其实不支持——别硬标。
- **validity_status**：current / historical / superseded / unknown_validity。
  看标题与正文里的"X 年 X 月修订/施行/废止"字样；**确认不了就标 unknown_validity，不要硬标 current**。
- **gold_answer**：50~150 字，只写来源支持的内容。它是人工对照用的，不要求模型逐字一致。

## 三、日常工作流（机器起草、人只复核）

**不需要手写 JSON。** 起草由检索 + DeepSeek 自动完成：

```bash
# 单题：起草并打印校验结果（不入库）
.venv/bin/sufe-qa gold-draft "本科生怎么申请休学？"

# 批量：每行一题；校验通过的自动追加进 gold.v1.jsonl
.venv/bin/sufe-qa gold-draft --from-file topics.txt --yes
```

草稿字段全部由机器填：来源候选（真实检索 top 文档）、要点与逐字证据（LLM 从原文抽取）、
参考答案、场景/意图/学生类型。`gold-check` 在入库前已自动跑过一遍——**校验不通过的草稿
不会入库**，只会打印出来供人工处理。

人只做三件事：

1. **读一遍草稿**：`gold_answer` 是否属实、`required_answer_points` 是否真是该题必须答到的点。
2. **确认来源**：`gold-suggest`/`gold-draft` 给的 doc_id 是否确实是当前权威版本
   （Dashboard 可查全文与版本历史）。
3. **署名翻转**：草稿 `reviewer` 默认 `ai-draft`（=待人工复核）。复核通过就把该字段改成
   你的名字并更新 `reviewed_at`。这是"机器起草、人工负责"的边界——`gold-check` 会对
   `ai-draft` 署名给警告，金标集里不应长期残留未复核草稿。

需要手工新增/修改时（拒答题、追问题）：字段含义见上节；`gold-check` 全绿才算完成。

## 四、维护纪律

- **改检索/prompt 后**：跑 `sufe-qa eval`（evalset 门禁）。gold 集的正式打分在 30 题标满后
  接入 eval 门禁（届时 expected_doc_ids 命中才计入）。
- **官方资料换版**：`scripts/corpus_governance.py --apply`（或 `sufe-qa curate`）会把
  被取代文档转历史库。若 gold 题锚定的 doc 转历史，gold-check 会报"来源已是旧版"警告——
  人工把 expected_doc_ids 换到新版并更新 evidence。
- **标准答复失效**：治理脚本会把依赖失效的人工答复降级待复核；Dashboard 里重新确认。
- **gold 集只增不改语义**：修正错别字可以；改答案口径必须更新 `reviewed_at` 并在
  commit message 里说明原因。
- **不要把 gold 题喂回爬取/扩展词开发**：gold 用来裁判，不用来训练检索。要调参请用
  150 题库（开发集），最终结论以 holdout.vX 揭题为准。

## 五、常见错误（gold-check 都会拦）

| 报错/警告 | 含义 | 处理 |
|---|---|---|
| `expected_doc_id 不存在于 manifest` | doc_id 抄错或文档被隔离 | 用 gold-suggest 重新找现行文档 |
| `gold 来源不是现行文档` | 锚定了已隔离/归档/历史文档 | 换现行版本，或先恢复该文档 |
| `evidence_text 在原文中逐字找不到` | 证据是脑补/改写/来自别的版本 | 回原文复制，或承认资料不支持该要点 |
| `要点太泛` | 写了"申请/流程"这类词 | 改写成含主语+谓语+关键值的事实句 |
| `gold 来源已是旧版` | 锚定文档 validity=superseded/historical | 确认是否应换新版；确实要考历史版时在 validity_note 说明 |
