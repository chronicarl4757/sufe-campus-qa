# 进度日志

## 2026-08-01

- 读取用户要求、仓库现有设计/计划、seeds、manifest、corpus、evalset 和 crawl reports。
- 验证当前公开站点可访问，记录 JWC/XSC/GS 的真实导航、分页和附件结构。
- 创建隔离 worktree 和分支 `feat/question-driven-crawl`。
- 基线测试完成：235 passed。
- 设计已按用户 14 项修订写入并提交：`05f709d docs: define question-driven SUFE crawl architecture`。
- 详细实施计划已写入 `docs/superpowers/plans/2026-08-01-sufe-question-driven-crawl.md`。
- 固定题库已完成：150 条、11 个场景配额，commit `c1b9ba7`。
- before 覆盖审计已完成：commit `aa6e59f`；当前场景语料 63 篇，问题状态 0/37/113（answerable/partial/not）。
- 全套回归测试已验证：240 passed，1 个既有依赖警告。
- 文档类型/来源/版本证据/关系模型已完成，commit 待随 collection 阶段一并记录；新增流水线元数据测试通过。
- 当前完整测试：245 passed，1 个既有依赖警告。
- 下一步：实现主问答/公示双 collection、原子 full rebuild 和按 collection 隔离的 BM25。

## 2026-08-07（benchmark 固化链收尾）

- 审查 codex 分支并修复四类回归；全部 329 测试通过，ruff 全绿。
- 转写用户 345 题真实场景 benchmark → `data/eval/sufe_benchmark_v2.jsonl`。
- 修复附件发现三类误判；八源全量抓取 + hq/nic 重抓；jwc 学生类/管理类制度、xsc 资助（+176）、保卫处（+16）入库 → 993 accepted docs（main 5262 / public 1372 / historical 1326 chunks）。
- 正式 eval 门禁 993 篇下 3×100%（vector_min_similarity=0.50 未动，evalset.v1 未动）。
- 探针：573 篇 29.4% → 767 篇 38.1% → 993 篇 47.2%；域名复核自动扩写 61 条（全部官方 .sufe.edu.cn，0 人工复核）→ 重跑 223/323 可答（69.0%）、97 部分、2 不可答。
- 固化 `ground-benchmark`：231 grounded（209 文档支撑题全部绑定真实 expected_doc_ids + 12 拒答 + 10 追问）；114 needs_docs（含 missing_reason + suggested_departments），最大缺口=教务处选课通知、career 就业手续、nic 统一认证/校园卡服务页。
- 30 题生成级抽查（真实 DeepSeek）：30 作答、29 引用校验通过、0 拒答；缺文档题目（统一认证密码）正确降级为“资料未提及+给出 NIC 联系方式”。
- coverage-audit after（150 题库）：86/150 可答（57%）、64 部分、0 不可答（before 为 0/37/113 @63 篇）。
- 分批提交：data(corpus) `82b40f2`、data(index) `63a9e8e`、data(reports) `88d08eb`、test(eval) `1383af4`。
