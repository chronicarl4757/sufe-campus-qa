# 上财校园问答智能体（sufe-campus-qa）

面向上海财经大学学生的校内知识问答智能体：定向爬取学校公开官网资料，混合检索后由
DeepSeek 生成**带 [n] 来源引用**的回答；检索不到可靠来源时直接拒答，不走 LLM。

知识范围：评奖评优 / 奖助学金 / 推免升学 / 实习就业 / 学工事务 / 校园生活 / 其他。

## 架构

```
离线索引：
  crawler/(seeds.yaml 种子站 | discover-site 学院主页勘探→crawl-site)
  + data/inbox/(手动投放) + data/curated/(人工精编指南, front matter 元数据)
  → SafeFetcher(安全抓取: 协议/私网/robots逐跳重检/限速/大小上限)
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
  → DeepSeek(流式, 严格引用 prompt + 后端引用编号校验) → 回答 + [n]引用 → 来源卡片

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
  generate/   DeepSeek 流式客户端、严格引用 prompt + 引用编号校验、来源卡片
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

