# 上财校园问答智能体（sufe-campus-qa）

面向上海财经大学学生的校内知识问答智能体：定向爬取学校公开官网资料，混合检索后由
DeepSeek 生成**带 [n] 来源引用**的回答；检索不到可靠来源时直接拒答，不走 LLM。

知识范围：评奖评优 / 奖助学金 / 推免升学 / 实习就业 / 学工事务 / 校园生活 / 其他。

## 架构

```
离线索引：
  crawler/(seeds.yaml 种子站 | discover-site 学院主页勘探→crawl-site)
  + data/inbox/(手动投放) + data/curated/(人工精编指南, front matter 元数据)
  → SafeFetcher(安全抓取: 协议/私网含DNS解析/robots逐跳重检/限速/大小上限)
  → 栏目分页(listN.htm/下一页/?page=N) → 文章元数据解析(标题回退链/日期规范化)
  → 附件发现(a/iframe/embed/object 打分) → 下载(pdf.js 查看器解析) 
  → 解析(trafilatura/pymupdf/python-docx/openpyxl/LibreOffice适配)
  → 质量门(附件依赖页/无效标题/导航污染/正文过短 → 九类文档分型)
  → 父子文档(附件带父级上下文, 多父关系 relations.jsonl)
  → data/corpus/<category>/*.md + manifest.jsonl (三级 hash 增量去重)
  → 结构感知切分(第X条/一、) → BGE-M3 → Chroma(持久化)

在线问答：
  问题 → 向量 top-20 + BM25(jieba) top-20 → RRF 融合
  → 时效重排(年更政策新版优先) × 类型权重(policy 1.1 / news 0.85)
  → 多样性截留(单文档≤3 chunk, 防长 PDF/同模板兄弟文档霸屏) → top-8
  → 向量最高相似度 < 门控阈值 → 拒答模板(不走 LLM)
  → DeepSeek(流式, 严格引用 prompt) → 句子级引用门禁(越界编号整答撤回) → 回答 + [n]引用 → 来源卡片

Web 界面（FastAPI + SSE，app/）：
  红头档案设计语言——每次回答渲染为带文号/文武线/仿宋正文的"答复函"，
  流式输出完成后盖朱砂印章；来源为可点档案卡；👍👎 批注落 feedback.jsonl
```

工程要点：robots 合规爬虫（RFC 9309 语义/Crawl-delay/逐跳重定向检查）；抓取状态
`data/crawl_state/<host>.json`（ETag/Last-Modified 条件请求、本轮未出现标 not_seen
不删除）；原始文件缓存 `data/raw/<host>/`；站点级抓取报告 `data/crawl_reports/`；
content_hash 增量索引（幂等，重复运行 no-op）；quality_status≠accepted 只入 manifest
审计不进索引；旧有效文档本轮被拒（附件失败/质量门回归）保留旧版本不删除；
指针型公示页（具体标题+明确日期）豁免正文过短判定；标题链识别栏目名冒充的 h1
（命中 <title> 面包屑非首段即跳过）；chunk 嵌入带标题前缀（contextual header，
区分各学院同名模板文件，库存文档保持原文）；入库前身份证/手机号敏感信息隔离；
评测门禁（命中率/拒答率不达标退出码 1，改动检索或 prompt 前必跑）。

## 快速开始

```bash
uv sync
cp .env.example .env   # 填入 DEEPSEEK_API_KEY

sufe-qa crawl                    # 按 seeds.yaml 抓种子站（分页+附件+质量门）入库
sufe-qa discover-site https://scai.sufe.edu.cn/   # 勘探学院主页 → 生成 site profile
sufe-qa crawl-site scai.sufe.edu.cn               # 按确定性 profile 整站抓取
sufe-qa crawl-report gs.sufe.edu.cn               # 查看站点抓取报告
sufe-qa ingest --category 学工事务  # 可选：data/inbox/ 手动文件入库
sufe-qa ingest-curated           # 可选：data/curated/ 人工精编指南入库（解析 front matter）
sufe-qa index                    # 建索引（首次自动下载 BGE-M3，约 2GB）
sufe-qa ask "推免申请条件是什么？"  # CLI 问答
sufe-qa serve                    # Web 界面：http://127.0.0.1:7860
```

crawl/crawl-site 通用参数：`--max-list-pages` `--max-articles` `--max-attachment-bytes`
`--since YYYY-MM-DD`（跳过早于该日期的文章）`--dry-run`（只评估不写库）
`--no-attachments` `--report-json`（输出机器可读站点报告）。

## 微信公众号数据接入

公众号文章是官网之外的补充官方数据源，**定位为学院级、年度性招生/推免/选拔信息**
（推免/预推免/夏令营/复试/调剂/硕博招生/实验班/转专业/项目报名），不追求校园
生活服务覆盖。文章**发现**与**解析**彻底解耦：

```
ArticleDiscovery（SeedURLDiscovery | WeRSSDiscovery）→ 文章 URL (+WeRSS 已存正文)
  → 统一 normalize（页面/WeRSS content_html 同一套清洗）
  → 白名单/时间窗/相关性门（招生选拔口径 + meaningful-facts 启发）
  → 现有质量门 + 生命周期 + manifest（source_type=official_wechat）
```

- **只接收公开的 `mp.weixin.qq.com` 文章 URL**。不逆向微信历史消息接口，不用
  Cookie 池/代理池/验证码与风控绕过；命中风控验证页只记 `verify_required` 跳过。
- **Seed URL 模式可完全独立工作**：`data/sources/wechat_seed_urls.jsonl` 每行
  `{"account": "...", "url": "https://mp.weixin.qq.com/s/...", "title": "", "publish_date": ""}`，
  title/date 可空，由 fetcher 补齐；`force_include: true` 可豁免 2024-01-01 时间窗。
- **We-MP-RSS 是可选的 discovery service + 正文缓存**：配置 `WERSS_BASE_URL` /
  `WERSS_ACCESS_KEY` / `WERSS_SECRET_KEY`（见 `.env.example`）后
  `--mode werss` 从其公开 API 发现文章——`/mps` 查订阅、`/articles` 列元数据、
  `/articles/{id}` 取已存正文（`content_html` 优先、`content` 兜底）；有正文直接
  normalize，**不回源微信**；无正文才 fallback `WechatArticleFetcher`。
  未配置或服务不可用时跳过并告警，不影响其他 crawler。
- 公众号文章须经**官方账号白名单**（`data/sources/sufe_wechat.yaml`，页面内
  account_name 精确匹配；每账号记录 focus 主题与 official_evidence_url）
  + 2024-01-01 时间窗 + deterministic 相关性过滤（招生/推免/选拔正向词，
  喜报/风采/讲座回顾/党建/研讨会/成果新闻强排除；无事实元素的宣传拒绝为 no_facts）。
- **质量判断不看图片**（公众号含海报/二维码/头图是常态），只看可提取正文中
  是否有可引用事实（日期/数字/联系方式/报名-条件-材料类关键词）。
- **正文图片可选 OCR**：`crawl-wechat --ocr` 或管理端单篇导入时，正文内容图
  （表格/名单/流程图）经 RapidOCR 识别后以 `[图片识别]` 块按原位置回填正文；
  图标/二维码等小图自动跳过，引擎未安装时安静降级为丢弃图片的旧行为。
  引擎为可选依赖：`uv pip install '.[ocr]'`（rapidocr-onnxruntime + opencv + pillow）。
- **官方公开联系方式不算敏感信息**：官方来源正文中带公开语境（咨询电话/招生办公室/
  联系老师/“电 话：”等排版变体）的电话号码按 official_public_contact 放行；
  私人手机号、无上下文手机号、身份证号继续隔离。
- 权威等级：官网正式政策 > 官网办事指南 > 公众号办事解读 > 公众号新闻；
  公众号解读与官网正式政策共存，种子可用 `related_official_url` 建立
  `explains` 关系（官网为 canonical），同 topic_key 唯一匹配时自动建立。
- 只按 exact text_hash 去重（不做语义去重）；doc_id 锚定 biz+mid+idx（JS 变量优先，
  长链 URL query 兜底），退化为规范化 URL。
- robots 说明：mp.weixin.qq.com 的 robots.txt 为 UA=* 全站 Disallow。本功能只抓
  白名单收敛、显式给定的单篇文章 URL（默认 2 秒限速），不做站内发现式爬取；
  `SafeFetcher(respect_robots=False)` 仅限该用途，其余安全检查不变。

```bash
sufe-qa crawl-wechat --mode seed --dry-run    # 预览：各门计数 + 话题分布 + 拒绝分布
sufe-qa crawl-wechat --mode seed --report-json
sufe-qa crawl-wechat --mode werss --limit 20  # 需先配置 WERSS_*
```

抓取只写 corpus/manifest；索引仍由 `sufe-qa index` 显式执行。

## 管理员 Dashboard（知识库治理）

`sufe-qa serve` 后访问 `http://127.0.0.1:7860/admin`（与学生问答端同进程、不同入口）。
管理 API 使用独立 Bearer 令牌：**未配置 `SUFE_QA_ADMIN_TOKEN` 时管理接口全部拒绝**；
令牌用密码管理器生成的长随机串（见 `.env.example`）。

Dashboard 是“馆藏账本”而非统计图，覆盖非专业维护者的日常闭环：

- **概览与发布状态**：当前唯一文档/可检索/已隔离三口径，manifest 与索引指纹是否一致、
  质量报告是否过期（陈旧即显目标红）；入库时间脉冲带可按日反查当天新增/更新文档。
- **文档治理**：列表/搜索/筛选、正文与版本历史查看；治理动作只有**可逆的隔离/恢复**
  （追加 manifest 记录回退），不做不可逆删除。
- **问答诊室**：输入学生问题实时复现真实链路（检索证据、拒答原因、引用校验），
  用于判断“答得差”是缺资料还是检索问题。
- **标准答复热修**：确认问题后可撰写人工答案，必须绑定现行可追溯资料；正文以
  不可变版本文件保存，随后只做**单条增量索引**并自动复测该问题。
- **资料补充**：上传单个文件或粘贴一篇公众号文章 URL（复用白名单/质量门，
  不绕过爬虫管道）。
- **体检与发布**：一键运行质量审计；“发布”仅在体检新鲜且阻断项为 0 时可用，
  发布即增量索引，完成后页面显示新的索引指纹。

典型日常维护顺序：补充资料（上传/公众号链接/爬虫）→ 体检 → 问答诊室抽查 → 发布。
任何一步报错都先停下来看报告，不要重复点发布。

回答末尾输出来源卡片（标题/发布单位/原文链接）。

## 评测

正式评测集 `data/eval/evalset.v1.jsonl`（9 应答题 + 3 拒答题，doc_id 锚定 manifest）随仓库提供：

```bash
sufe-qa eval   # 检索命中率 / 应答题回答率 / 拒答正确率，任一不达标退出码 1
```

达标线（M2）：检索命中率 ≥ 90%，应答题回答率 = 100%，拒答正确率 = 100%；空评测集
或缺少应答/拒答样本直接判失败，应答题被门控拦下视同作答失败。拒答题语义为"知识库
无此领域内容"；语义贴库的不当请求（如代写）由生成层拒答，不在离线集内。自定义评测集
可复制 `evalset.example.jsonl`（支持 `#` 注释行），引用正确率需 LLM 判分，由
answer_points 字段人工复核。

## 目录

```
src/sufe_qa/
  crawler/    fetcher(安全抓取) pagination(栏目分页) article(文章解析+附件发现)
              engine(抓取编排) state(抓取状态) discover(站点勘探) profile(站点画像)
  ingest/     解析(parsers/attachment_parsers) 质量门(quality) 切分(splitter)
              inbox 收集  pipeline(父子文档入库/去重增量)
  indexing/   content_hash 增量索引（Chroma，只收 quality_status=accepted）
  retrieve/   向量 + BM25 + RRF 融合，置信门控，时效×类型重排
  generate/   DeepSeek 流式客户端、严格引用 prompt + 引用编号校验/门禁、来源卡片
  evals/      评测集加载、打分、门禁
  app/        FastAPI + SSE 服务、静态前端（红头档案界面）
  cli.py      crawl / discover-site / crawl-site / crawl-report / ingest / index / ask / eval / serve
data/
  inbox/          手动投放入口       corpus/     标准语料 + manifest + relations
  chroma_db/      索引产物           eval/       评测集
  raw/<host>/     原始 HTML/附件缓存  crawl_state/ 抓取状态（增量/not_seen）
  crawl_reports/  站点抓取报告       site_profiles/ discover-site 生成的站点画像
```

## 开发

- `uv run pytest`：233 项测试，全程 FakeEmbedder/FakeLLM/MockTransport 离线可跑
- `uv run ruff check && uv run ruff format`
- CLI 的 `--fake-embed` 为离线开发开关（确定性假向量，索引与问答需同用）
- 种子站 24 个（`seeds.yaml`）：研究生院/商学院为自建站，各学院 _wp3 站走
  静态列表链接；gs 站正文经 ssd.sufe.edu.cn 的 pdf.js 查看器嵌入，抓取侧已做
  查看器解析（`_fileurl` → getStream 真实文件）；教务处列表页为 generalQuery
  接口 JS 渲染（未逆向），以首页为种子；career 就业网为招聘系统不抓——相关
  政策可投 `data/inbox/`
- 附件链路：文章页 a/iframe/embed/object 打分发现 → 下载（魔数识别）→ PDF/DOCX/
  XLSX 解析（扫描 PDF 与旧 DOC 标状态保留原件）→ 附件文档带父级上下文入库，
  同 binary 多父只嵌一份正文、relations.jsonl 记全部引用
- 换 embedding 模型：改 `config.py` 的 `embedding_model` + `index --full` 重建


## 部署（HF Spaces）

Docker SDK（根目录 `Dockerfile` 已备好）：依赖按 `uv.lock` 锁定安装，容器以非 root
用户运行，`.dockerignore` 排除 `.env`/`.venv`/缓存与 `data/inbox` 等本地投放态文件
（语料与索引随 git 提交、正常入镜像）。`DEEPSEEK_API_KEY` 存 Spaces Secrets；
`data/corpus` 与 `data/chroma_db` 随 git 提交，启动只读加载；BGE-M3 首次启动下载
（约 2GB），开 Spaces 持久存储挂 `/data` 复用缓存。本地/自有服务器：
`docker build -t sufe-qa . && docker run -p 7860:7860 sufe-qa`。

> 设计规格原定为 Gradio 界面；为达到定制视觉与交互（红头档案设计语言、盖章动效、
> 引文联动），实现改为 FastAPI + 手写静态前端，能力覆盖规格 4.4 全部要求
> （流式/来源卡片/示例问题/反馈/页头更新时间/页脚免责）。

