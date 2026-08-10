# 150 问真实回答评测设计

## 修复目标

当前 `/coverage` 展示的是 `audit_manifest` 的规则探针，不包含生成答案，并把宽泛关键词命中误称为“完整可回答”。本修复新增一次可复现、可续跑的真实问答评测：固定 150 问逐题经过当前 BGE-M3/Chroma/BM25 检索、置信门控和 DeepSeek 生成，答案、提示词顺序对应的命中 chunks、引用校验、模型与索引版本一起持久化。

规则探针继续用于发现语料候选，但页面必须明确标记为“规则探针”，不得代替真实答案状态。

## 数据分层

- `data/coverage/sufe_coverage_after.json`：保留现有规则探针结果，不写入模型答案。
- `data/coverage/sufe_real_answers.json`：新增真实生成快照，schema version 为 `1`。
- `/api/coverage`：按问题 ID 将两个文件只读合并；缺少答案快照时仍可打开页面，但显示“尚未运行真实问答”。

真实答案报告顶层记录：

- `schema_version`
- `run_id`
- `question_bank_version` / `question_bank_hash`
- `index_fingerprint` / `embedding_model`
- `llm_model` / `prompt_hash`
- `started_at` / `completed_at`
- `total` 与各状态数量
- `results`

每题记录：

- `id` / `question` / `scene`
- `status`: `answered`、`answered_with_citation_issue`、`refused`、`error`
- `answer_text`
- `refused`
- `citation_check`
- `expected_domains` / `required_answer_points`
- `matched_domains` / `domain_match`
- `generated_at` / `latency_ms` / `error`
- `hits`: 提示词编号、doc_id、chunk_id、标题、部门、URL、日期、文档类型、版本状态、相似度、RRF 分数和实际 chunk 正文

`answered` 只表示真实模型已生成且引用编号格式通过，不自动宣称答案经过人工事实审核。题库仍为 `unverified` 时，页面显示“待人工复核”。

## 批处理命令

新增：

```text
sufe-qa answer-benchmark
  --bank data/eval/sufe_question_bank.jsonl
  --output-json data/coverage/sufe_real_answers.json
  --workers 4
  --resume
```

执行逻辑：

1. 加载固定题库并校验 150 问哈希；
2. 加载 BGE-M3 一次，按原题顺序串行检索，避免 GPU 模型并发；
3. 未过置信门的题保存真实拒答模板；
4. 已过门题最多使用 4 个工作线程调用 DeepSeek；每个答案沿用线上 `SYSTEM_PROMPT`；
5. 校验 `[n]` 引用是否存在且位于提示词 chunk 范围；
6. 每完成一题原子写入快照，进程中断后可 `--resume`；
7. `--resume` 仅复用题库哈希、索引指纹、模型和 prompt hash 全部一致的结果，否则拒绝混写；
8. `error` 默认在续跑时重试，已完成结果不重复计费。

## 页面修复

- 总览优先显示真实生成数量、拒答、错误和引用异常；“85 完整”改为“规则探针完整 85”。
- 场景条与 150 格矩阵默认编码真实回答状态。
- 筛选器拆分为“真实回答状态”和“规则探针状态”。
- 逐题抽屉首先展示真实 `answer_text`；引用 `[n]` 可定位到本次生成实际使用的第 n 个 chunk。
- 命中文档表改用真实生成 hits，并显示 prompt 编号、chunk_id、相似度和版本状态。
- 原来的 `point_evidence` 标题改为“规则探针证据（非人工判分）”。
- 快照缺失或单题错误时显示明确原因，不回退成伪答案。

## 安全与质量边界

- 不把 `FakeLLM` 输出写入正式答案文件；报告记录 embedding backend/test_only，正式命令发现 test-only embedding 时拒绝，除非测试显式注入。
- 不记录 API key、Authorization 或请求头。
- 答案只引用已进入 prompt 的 chunks；引用越界或全文无引用单独标记。
- 旧制度不会仅因年份较早自动判失效；每个 hit 原样展示 `validity_status`。
- 页面不把 `answered` 改写为 `verified`。

## 验收

- 150 条结果均有 `answer_text`、拒答或明确错误；不得静默缺项。
- 每条非拒答答案保存实际 hits 与 citation check。
- 页面可逐题看到真实答案，并能从引用定位对应 chunk。
- 页面明确区分真实生成状态与规则探针状态。
- 题库哈希、索引指纹、模型和 prompt hash 可追溯。
- 单元测试覆盖生成、拒答、引用异常、错误、续跑兼容检查、API 合并和前端渲染。
