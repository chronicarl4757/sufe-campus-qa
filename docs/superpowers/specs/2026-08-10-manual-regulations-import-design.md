# 上财人工规章制度安全导入设计

日期：2026-08-10

## 目标

把 `data/raw/规章制度` 中用户提供的本地文件作为可审计的人工来源导入现有语料生命周期，随后使用真实 BGE-M3 增量更新索引。导入不改变公开网站的权威等级，不把“能解析”视为“可进入主问答”，也不依据文件名年份自动宣布制度当前有效。

## 准入边界

采用精确文件 allowlist。配置中未列出的文件一律只进入导入报告，不写 corpus、manifest 或索引。以下材料即使被误列入 allowlist 也由安全门强制排除：

- 文件名含“征求意见稿”；
- 解析失败、扫描件无正文或正文过短；
- 命中身份证号、手机号等敏感信息；
- 党务经费、教师管理、内部绩效、科研保密、期刊目录和普通财务报销等非学生校务问答材料。

正式且面向学生的学校制度、学院实施细则、办事指南、表格和操作手册可进入语料。旧制度仅在配置明确标记时进入 historical collection；草稿、无正文和非学生材料不进入任何检索 collection。

## 数据模型与来源

每个准入文件具有稳定来源标识：

```text
manual://sufe-regulations/<percent-encoded-relative-path>
```

它用于生成稳定 `doc_id`，避免同名文件冲突。元数据规则如下：

- `source_type=manual_upload`，不冒充 `official_department`；
- `document_type=attachment`，保留文件名、MIME、binary hash 和 text hash；
- `publisher`、`scope_unit`、`category`、`source_section`、`document_kind`、`retention_status` 均由精确 allowlist 提供；
- `validity_status` 默认 `unknown_validity`；只有正文出现明确施行、修订或废止证据时，现有版本协调器才能提升置信度；
- 文件名前缀 `YYYYMMDD` 可作为发布日期证据，括号中的“某年某月修订”只记录修订年份，不冒充发布日期；
- 内容 hash 重复时复用已有文档，不生成第二份正文。

## 组件边界

新增 `manual_authority.py`，负责读取 allowlist、递归盘点来源目录、调用现有附件解析器、产生导入候选和审计报告。它不实现 PDF/DOCX/XLSX 解析；格式识别、LibreOffice DOC 转换和表格抽取继续复用 `attachment_parsers.py`。

CLI 新增 `ingest-authority-files`：默认 dry-run，只有 `--apply` 才写 corpus/manifest。所有文件先完成解析与准入检查，随后统一持久化，报告记录 imported、duplicate、excluded、incomplete、quarantined 及逐文件理由。

Indexer 不增加特殊分支。导入文档仍由显式 `document_kind + retention_status` 规则路由到 main/public/historical；隔离文档不进入 Chroma 或 BM25。

## 导入后的采集

导入、版本协调和真实 BGE-M3 增量索引完成后，使用固定 benchmark 的 `needs_docs` 作为下一轮抓取队列。优先顺序为：

1. 教务处选课、退课、重修和办事流程；
2. 就业平台三方、网签、档案和去向登记；
3. 网络信息中心统一认证、校园卡、无线网和 VPN；
4. 其余仍缺权威正文的问题。

抓取仍使用通用 SafeFetcher 和站点 adapter；招聘岗位、新闻、公示名单和标题页不因本轮导入而放宽准入门。

## 验证

- dry-run 与 apply 的逐文件决策一致；
- 未列入 allowlist 的文件写入数为 0；
- 草稿、敏感、空正文和非学生材料进入隔离报告；
- corpus 文件 hash、manifest 和索引指纹一致；
- main/public/historical collection 无类型污染；
- BGE 元数据必须为 `BAAI/bge-m3`、`test_only=false`；
- 固定题库阈值、问题文本和 expected doc 不被导入程序修改。
