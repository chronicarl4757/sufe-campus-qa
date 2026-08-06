# 上财校务知识库干净数据管道设计

## 目标

采集系统应保留可追溯的原始资料，同时让默认校务问答只看到当前有效、可回答、来源权威的文档。标题带年份本身不是低质量；问题在于同一年度系列的历年通知、公示、活动和错误日期未经生命周期治理便进入 corpus 和默认索引。

## 现状证据

以 `feat/question-driven-crawl` 工作树的 last-wins manifest 为准：

- 1293 个当前文档，1132 个 accepted；955 个标题含年份。
- 显式主问答类型 528 个，其中 460 个标题含年份，210 个发布于 2021 年前。
- 主问答候选中 393 个来自研究生院“招生通知”，占 74%。
- 315 个 `public_list` 已可分流，但 230 个 `annual_notice` 和 208 个带年份的 `policy` 仍会进入主问答。
- 483/528 个主问答候选为 `unknown_validity`。
- `SectionSpec.time_policy` 已被 YAML 解析，但抓取/入库没有消费它；所有权威栏目实际按 `all` 处理。
- 研究生院详情页的通用 `.info` 日期选择器会先命中侧栏。样本页面原文为 `发布时间：2017-05-09`，manifest 却记录 `2015-06-20`。
- 旧 manifest 没有 `document_kind` 时，indexer 会把无法分类的 accepted 文档兜底为 `manual`，存在污染风险。

## 原则

1. 不按“标题含年份”直接删除。长期制度、修订版本和年度办理通知的生命周期不同。
2. `validity_status` 只表达制度效力，不承担保留策略或检索可见性。
3. 原始 HTML、附件二进制和关系永久保留；默认 corpus/index 可以只保留干净视图。
4. 年份较新只能决定年度通知的展示优先级，不能自动证明长期制度已废止。
5. 迁移先生成审计报告，应用阶段使用 staging + 原子切换并保留备份。

## 数据模型

`DocMeta` 新增以下互不混淆的字段：

```text
publish_date_evidence   原页面中支持发布日期的短证据
publish_date_confidence 0..1
date_conflict           页面标签日期、结构化日期冲突时为 true
temporal_class          enduring | annual | recurring_public | ephemeral | undated
series_key              年度系列稳定键，不等同于粗粒度 topic_key
retention_status        active | historical | archived
retention_reason        确定性保留判定理由
canonical_doc_id        年度系列默认展示文档；非系列为空
```

`topic_key` 继续表示业务主题，例如 `graduate.admission.retest`；`series_key` 区分同一业务下的不同系列，例如“硕士初试成绩复核公告”和“硕士复试录取办法”。

## 日期解析

日期解析顺序固定为：

1. 文章正文附近的带标签日期，例如“发布时间/发布日期”；
2. Adapter 的站点专用精确选择器；
3. JSON-LD、OpenGraph 或 trafilatura 元数据；
4. 无标签全文日期仅作为低置信候选，不得覆盖前三项。

研究生院 Adapter 删除 `.info`、`.time` 这类全局选择器，使用详情页 `.key-feature` 内的“发布时间”节点。若两个高置信来源冲突，保留页面标签日期并设置 `date_conflict=true`，进入质量报告。

## 文档分类与年度系列

分类以标题和栏目语义为主，正文只提供结构证据：

1. 名单、公示、拟录取、抽检结果优先判为 `public_list`。
2. 新闻、活动回顾、宣讲会、分享团、访问交流优先判为 `news/event/promotion`。
3. 标题含年份/学年且含报名、评选、复试、调剂、招生、申请、安排、通知、公告等年度业务词时，判为 `annual_notice`，即使正文引用“办法/规定”。
4. `policy` 必须由正式标题或文号支持；不能仅因正文出现“管理办法”而提升。
5. 表格、操作手册、FAQ、服务指南和办事流程按各自显式信号分类。

`series_key` 由标准化标题、业务主题、发布部门和适用单位生成。标准化只删除年份、学年、批次、周次和“关于/通知”等包装词，不删除学院、学生类型、项目名称等区分信息。

## 生命周期与时间策略

栏目配置使用显式策略：

| 策略 | 适用内容 | corpus 保留 | 默认 collection |
|---|---|---|---|
| `all_history` | 制度、办事指南、FAQ、表格、手册 | 全部合法版本 | active 进 main；明确 superseded 进 historical |
| `recent_5_school_years` | 年度通知、招生办理通知 | 最近 5 学年 | 每个 series 最新一份进 main，其余进 historical |
| `recent_2_school_years` | 名单、公示、结果 | 最近 2 学年 | public_list |
| `current_school_year` | 调停课、答辩日程等高频运营公示 | 当前学年 | public_list |
| `archive_only` | 新闻、活动、宣传、无法确认的旧运营页 | raw/audit | 不索引 |

超出时间边界的年度材料标记 `archived`，不生成默认 corpus Markdown，但 raw 和关系保留。年度系列中“最新”只决定检索展示，不修改 `validity_status`。

## Collection 与检索

使用三个内容 collection：

```text
main_qa     active policy/procedure/faq/annual_notice/form/manual/service_guide
public_list active public_list
historical historical policy/procedure/annual_notice/form/manual/service_guide
```

`news/event/promotion/incomplete/archived` 没有默认 collection。默认检索只查 `main_qa`；用户明确询问某年政策时路由到 `historical`；查询名单时显式路由 `public_list`。BM25 与 Chroma 使用相同边界。

旧 manifest 缺少类型时必须重新分类；仍无法确定则隔离，不允许兜底成 `manual`。

## 现有数据迁移

迁移分两步：

1. `quality-audit` 只读 last-wins manifest、corpus 和 raw，输出逐文档日期修正、类型、series、retention、canonical 和理由，不写数据。
2. `rebuild-clean-corpus --apply` 在 staging 目录重建干净 corpus/manifest/relations；校验通过后原子切换，旧 corpus 保留为带时间戳备份。

迁移不得修改问题库、降低检索阈值，也不得删除 raw。附件按原关系继承父文档的系列和生命周期，但同一附件被 active 父文档引用时至少保留为 historical/active，不能因另一个旧父页面被归档而丢失。

## 数据质量门

完成条件：

- 日期标签样本解析正确，`date_conflict` 全部有证据和报告。
- 主问答中同一 `annual` series 最多 1 个 active 文档。
- 主问答中超出最近 5 学年的 annual notice 为 0。
- public_list 中超出最近 2 学年的普通公示为 0；运营公示只保留当前学年。
- 主问答中的 public_list/news/event/promotion/incomplete/archived 为 0。
- 旧 schema 无法分类文档进入隔离，不再变成 manual。
- raw、附件多父关系和历史查询能力不丢失。
- 固定问题库前后使用相同 hash、检索配置和阈值；清理后核心问题可回答率不得下降。

