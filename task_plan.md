# 上财问题覆盖驱动采集任务计划

## 目标

在隔离分支 `feat/question-driven-crawl` 中，先完成教务处、学生处、研究生院的端到端垂直切片，再扩展其余权威来源；用固定问题分母验证可回答性、附件完整性、版本证据和 collection 隔离。

## 阶段

- [completed] 1. 固定题库、现状覆盖审计与 before 报告
- [completed] 2. 文档类型、来源、版本证据和多父关系模型
- [in_progress] 3. 主问答/公示双 collection、迁移和独立 BM25
- [pending] 4. Adapter 契约、Wp3、JWC、XSC、研究生院
- [pending] 5. 通用 orchestrator、垂直切片抓取与 after 报告
- [pending] 6. 定向补抓、P0/P1 扩展和学院细则
- [pending] 7. 全量 150 探针、质量门和最终交付报告

## 约束

- 先生成 `data/coverage/sufe_coverage_before.json/.md`，再执行任何新站点写入抓取。
- 主问答显式 allowlist 为 `policy/procedure/faq/annual_notice/form/manual/service_guide`；`public_list` 单独 collection；news/event/promotion/incomplete 不进正常检索。
- Adapter 不请求、不写 corpus/manifest、不更新 index；网络行为只在通用引擎。
- 150 条 `sufe_question_bank` 是覆盖探针；`evalset.v2` 只有人工确认条目才是正式门禁。
- 不降低相似度阈值，不用新闻、公示或标题页冒充答案，不以网页数量作为完成标准。

## 当前状态

设计文档已提交，实施计划已写入 `docs/superpowers/plans/2026-08-01-sufe-question-driven-crawl.md`。分支基线测试 235 passed；还未修改生产代码或抓取新站点。
