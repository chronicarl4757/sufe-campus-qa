# 上财问题覆盖驱动采集系统设计规格

日期：2026-08-01
状态：已确认；首个交付为教务处、学生处、研究生院端到端垂直切片

## 1. 目标与阶段边界

把采集系统从“抓到页面”改造成“学生问题 → 正确职能部门 → 当前有效资料/附件 → 可追溯答案”。本轮先完成一个可独立验收的垂直切片，包含：

- 教务处：办事流程、规章制度、学生类制度、常用下载、真实栏目分页；
- 学生工作处：行政规章、部门制度、学生资助及全部分页；
- 研究生院：招生、培养、学位、学籍、国际交流、综合服务及附件集合页；
- 至少 30 条固定覆盖问题、父子/多父附件关系、版本状态、双 collection、before/after 报告；
- 每阶段数据质量门，不以抓取页数作为完成标准。

就业、网络、图书馆、后勤/信息公开、医疗、财务、国际交流、保卫处和学院实施细则在垂直切片通过后接入，沿用同一数据契约。

当前基线：`manifest.jsonl` 有 617 条历史记录但同一 `doc_id` 多次追加；有效内容集中于研究生院和学院，教务、资助、信息化、就业、住宿等高频场景不足。教务处 `5124` 已验证为直接挂载选课、重修、学分认定、休复学、缓考、转专业、学生证补发等 PDF/DOC/XLS 的入口；学生处 `5437` 有两页；研究生院主页导航公开了完整业务板块。当前入口无需登录；若后续遇到 SSO/403/内网限制，只记录为 `blocked_source` 并报告具体 URL。

## 2. 总体数据流

```text
权威来源清单 + seeds.yaml
  -> SiteAdapter（栏目/分页/页面语义）
  -> PageSpec -> SafeFetcher -> PageContent
  -> ArticleSpec
  -> 通用附件下载、魔数识别、格式解析、质量门
  -> DocumentCandidate
  -> corpus + manifest + relations + version graph
  -> main_qa / public_list collection
  -> 固定题库覆盖探针与证据报告
```

SafeFetcher、robots、限速、重定向、缓存、重试、附件下载和状态报告只在通用引擎；Adapter 不写 corpus、下载附件、修改 manifest 或更新索引。

## 3. Adapter 契约与对象边界

### 3.1 固定协议

```python
class SiteAdapter(Protocol):
    def discover_sections(self, homepage: PageContent) -> list[SectionSpec]: ...
    def iter_list_pages(self, section: SectionSpec) -> Iterator[PageSpec]: ...
    def parse_listing(self, page: PageContent, section: SectionSpec) -> ListingResult: ...
    def parse_article(self, page: PageContent, spec: PageSpec) -> ArticleSpec: ...
```

对象职责固定为：

- `SectionSpec`：栏目 ID、名称、父栏目、业务场景、来源类型、发布单位、入口 URL、时间策略、公示标记和 adapter 配置；
- `PageSpec`：待抓任务（URL、`homepage/list/article/attachment_index` 类型、栏目、页码、父页、标题提示、优先级）；
- `PageContent`：HTTP 结果（请求/最终 URL、状态码、响应头、原始 bytes、MIME、ETag、抓取时间、错误）；
- `ListingResult`：文章 PageSpec、下一页/尾页、总页数、总记录数、页面 hash、停止建议；
- `ArticleSpec`：标题、发布日期、正文、栏目路径、发布单位、附件候选、服务项、分类提示和解析证据；
- `DocumentCandidate`：正文与附件完成解析后的待入库文档、hash、关系、类型、来源、版本字段和证据；
- `DocMeta`：最终 manifest 元数据，不保存原始 HTTP bytes。

### 3.2 继承/组合关系

```text
SiteAdapter
  -> BaseAdapter（URL、栏目、文本辅助，不做网络请求）
  -> Wp3Adapter（_wp3 导航、listN.htm、文章、附件候选）
       -> JwcAdapter（教务特殊栏目/接口探测/办事流程附件）
       -> NicServiceAdapter（服务卡片/标签页/FAQ/下载）
标准学院和普通职能部门直接配置 Wp3Adapter

GraduateSchoolAdapter：自建 /Home/List 与 /Home/Detail
BusinessSchoolAdapter：自建商学院结构
CareerAdapter：就业平台公开手续页及接口
```

子类只覆盖页面发现和解析策略，不复制 SafeFetcher 或附件下载逻辑。

## 4. 来源、文档类型与 collection

`source_type` 表达来源权威性/来源形态：

```text
official_department | official_college | information_disclosure
service_platform | attachment | manual_upload
```

`document_kind` 表达内容用途：

```text
policy | procedure | faq | annual_notice | form | manual | service_guide
public_list | news | event | promotion | incomplete
```

代码使用显式 allowlist，不能用“前七类/前八类”：

```python
MAIN_QA_KINDS = frozenset({
    "policy", "procedure", "faq", "annual_notice",
    "form", "manual", "service_guide",
})
PUBLIC_LIST_KINDS = frozenset({"public_list"})
ARCHIVED_KINDS = frozenset({"news", "event", "promotion", "incomplete"})
```

主问答 collection 只接收 `MAIN_QA_KINDS`；公示 collection 只接收 `PUBLIC_LIST_KINDS`；归档/隔离类型不进入正常索引。质量拒绝文档可以保留审计行，但 `index_collection=none`。

当前 `sufe_campus_qa` 迁移为：

```text
sufe_qa_main_v2
sufe_qa_public_list_v2
```

indexer 按 `index_collection` 实际写入两个 collection。retriever 默认只查 `main_qa`，CLI/API 支持显式 `collection=public_list`；名单/公示路由不依赖相似度偶然混入。BM25 也按 collection 独立建立。`--full` 在临时 Chroma 目录构建并写入 schema/fingerprint 后原子 rename，失败保留旧目录；旧 collection 只读保留作迁移输入和回滚来源。`data/chroma_db/index_metadata.json` 记录 schema、collection、embedding、splitter、manifest fingerprint、时间和计数。

## 5. 元数据、主题和关系

### 5.1 `DocMeta` 兼容扩展

新增字段：

```text
document_kind, policy_name, document_number, effective_date, valid_until,
revision_year, supersedes, superseded_by, applicable_student_type,
applicable_school_year, source_type, source_section, scope_unit, topic_key,
validity_status, validity_confidence, validity_evidence,
relation_confidence, relation_evidence, index_collection
```

`validity_status` 只取 `current`、`historical`、`superseded`、`unknown_validity`。只有正文/标题/附件明确出现“自某日起施行”“同时废止”“以本办法为准”“修订/废止/替代”等证据，才能自动标记 current/superseded/supersedes；仅凭年份新旧不能判废，不能确认则 `unknown_validity` 并进入冲突报告。`validity_confidence`、`relation_confidence` 为 0–1，`*_evidence` 保存原文证据与 doc/chunk/页码。

### 5.2 标准主题

`policy_name` 是去掉“关于印发/关于修订/通知”等包装后的正式制度名称；`topic_key` 是稳定主题，如 `undergraduate.scholarship.merit`。长期 policy、年度 annual_notice、学院实施细则通过 topic_key 关联；学院文档另记 `scope_unit`，不能替代学校制度的 publisher/source_type。

### 5.3 多父附件关系

`DocMeta.parent_doc_id` 只用于简单展示；`relations.jsonl` 是真实关系来源，支持：

```text
article -> attachment
policy -> annual_notice
policy -> implementation_rule
document -> supersedes
document -> references
attachment -> referenced_by
```

附件可按 `binary_hash/text_hash` 复用正文，但不同父页面的关系必须全部保留。关系行带 evidence、confidence、created_at，只去重完全相同的边。

## 6. 分页和附件规则

Adapter 必须读取当前页、总页数、总记录数、下一页、尾页、分页 URL 模式和 page hash；到达末页、时间边界、连续两页无新 URL 或重复 hash 才结束。长期制度/指南/培养方案抓全部历史，年度通知抓最近 5 学年，公示抓最近 2 学年并降权，新闻默认排除。

附件发现覆盖 `href/src`、链接文字、Content-Type、Content-Disposition、文件魔数、最终重定向地址、`iframe/embed/object`，以及 PDF/DOC/DOCX/XLS/XLSX/PPT/PPTX、`download.jsp`、`Service/UeditorDownload`、`/_upload/article/files/`、`/yanyan/ueditor/` 和无后缀接口。正文有“详见附件”等指针但附件失败时，父页标为 `incomplete`，不得进入主问答 collection。
## 7. 覆盖探针与正式评测

`data/eval/sufe_question_bank.jsonl` 是覆盖探针，至少 150 条，按指定场景配额生成，初始 `status=unverified`；它用于发现缺口，不直接作为 CI 硬门禁。

`data/eval/evalset.v2.jsonl` 是正式评测候选/门禁集。只有人工确认“问题有官方答案、expected_doc_ids 正确、要点来自原文、有效期和适用对象明确”后，条目才能标为 `verified` 并进入硬门禁；程序不得修改问题、期望文档或要点。垂直切片先准备至少 30 条固定探针和 v2 候选，未人工确认者不报告为正式 CI 通过。

回答性检查分两层：

1. 确定性检查域名、source_type、document_kind、index_collection、expected doc_id/附件关系、validity_status、适用对象和附件完整性；
2. 证据化语义检查逐个 required_answer_point 输出 `supported/unsupported/uncertain`、证据 chunk/doc_id、摘要、理由和置信度。可用模型辅助，但必须保存证据；无模型时使用可复现的术语规则并标记 `checker=deterministic`。

最终状态只有 `answerable`、`partially_answerable`、`not_answerable`。before/after 使用相同题库文件，并保存：

```text
question_bank_version, question_bank_hash, retriever_config,
embedding_model, similarity_threshold, index_fingerprint, evaluated_at
```

分母固定为该版本题库对应场景的题数；`sufe_full_report.json` 保存 150 条逐题结果，`sufe_missing_sources.json` 保存缺口和理由。

## 8. 权威来源与种子

新增机器可读权威来源清单，记录优先级、域名、发布单位、场景、允许文档类型、时间策略和主问答资格。P0 包含教务处、学生处、研究生院、就业服务平台、网络信息中心、图书馆、宿舍/后勤/信息公开；P1 包含医疗、财务、国际交流、保卫处。

`seeds.yaml` 改为使用 `adapter`、`homepage_url`、`section_ids`、`source_type`、`time_policy` 和场景配置。删除“马克思主义学院—校友动态”；不再把 `a[href$="page.htm"]` 作为通用主采集逻辑。学院只补培养、制度、办事、奖助、推免、毕业、就业、国际交流、下载等差异化细则。

## 9. 阶段质量门

每个阶段输出并检查：有效正文比例、附件发现/下载/解析成功率、incomplete 比例、news/event/promotion 污染率、重复文档率、unknown_validity 比例、固定问题可回答率、错误部门命中率、双 collection 交叉污染率。先跑单元测试和 dry-run，再写入公开站点结果；403、SSO、超时或格式限制必须保留失败对象、重试次数和可替代来源，不能降低相似度阈值或放宽质量门。

## 10. 实施顺序与首个里程碑

1. 生成固定题库和当前覆盖审计；
2. 完成 DocMeta、关系、版本证据、显式 collection 和索引迁移；
3. 完成 BaseAdapter、Wp3Adapter、通用 orchestrator；
4. 完成 JwcAdapter、学生处分页、GraduateSchoolAdapter 全导航与附件集合；
5. 写入首个垂直切片 corpus/manifest/relations，构建双 collection；
6. 用至少 30 条固定问题生成 before/after、逐题证据和质量门；
7. 按缺失问题定向补抓；
8. 扩展其余职能部门和学院细则，最后形成全量 150 条探针及待人工确认的 evalset.v2。

任何阶段都不以新增网页数量单独作为完成依据。
