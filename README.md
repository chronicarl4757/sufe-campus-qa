# 上财校园问答智能体（sufe-campus-qa）

面向上海财经大学学生的校内知识问答智能体：定向爬取学校公开官网资料，混合检索后由
DeepSeek 生成**带 [n] 来源引用**的回答；检索不到可靠来源时直接拒答，不走 LLM。

知识范围：评奖评优 / 奖助学金 / 推免升学 / 实习就业 / 学工事务 / 校园生活 / 其他。

## 架构

```
离线索引：
  crawler/(种子站) + data/inbox/(手动投放)
  → 解析(trafilatura/pymupdf/python-docx) → data/corpus/<category>/*.md + manifest.jsonl
  → 结构感知切分(第X条/一、) → BGE-M3 → Chroma(持久化)

在线问答：
  问题 → 向量 top-20 + BM25(jieba) top-20 → RRF 融合 top-8
  → 向量最高相似度 < 0.45 → 拒答模板(不走 LLM)
  → DeepSeek(流式, 严格引用 prompt) → 回答 + [n]引用 → 来源卡片

Web 界面（FastAPI + SSE，app/）：
  红头档案设计语言——每次回答渲染为带文号/文武线/仿宋正文的"答复函"，
  流式输出完成后盖朱砂印章；来源为可点档案卡；👍👎 批注落 feedback.jsonl
```

工程要点：robots 合规爬虫（RFC 9309 语义/Crawl-delay/出站防护）；content_hash 增量
索引（幂等，重复运行 no-op）；入库前身份证/手机号敏感信息隔离；评测门禁（命中率/
拒答率不达标退出码 1，改动检索或 prompt 前必跑）。

## 快速开始

```bash
uv sync
cp .env.example .env   # 填入 DEEPSEEK_API_KEY

sufe-qa crawl                    # 按 seeds.yaml 抓种子站入库
sufe-qa ingest --category 学工事务  # 可选：data/inbox/ 手动文件入库
sufe-qa index                    # 建索引（首次自动下载 BGE-M3，约 2GB）
sufe-qa ask "推免申请条件是什么？"  # CLI 问答
sufe-qa serve                    # Web 界面：http://127.0.0.1:7860
```

回答末尾输出来源卡片（标题/发布单位/原文链接）。

## 评测

```bash
cp data/eval/evalset.example.jsonl data/eval/evalset.v1.jsonl
# 按 manifest.jsonl 里的 doc_id 填写题目后：
sufe-qa eval                     # 检索命中率 + 拒答正确率，不达标退出码 1
```

达标线（M2）：检索命中率 ≥ 90%，拒答正确率 = 100%。引用正确率需 LLM 判分，由
answer_points 字段人工复核。

## 目录

```
src/sufe_qa/
  crawler/    种子站抓取（robots 合规、限速、出站防护）
  ingest/     解析 / 结构感知切分 / inbox 收集（去重+敏感隔离）
  indexing/   content_hash 增量索引（Chroma）
  retrieve/   向量 + BM25 + RRF 融合，置信门控
  generate/   DeepSeek 流式客户端、严格引用 prompt、来源卡片
  evals/      评测集加载、打分、门禁
  app/        FastAPI + SSE 服务、静态前端（红头档案界面）
  cli.py      crawl / ingest / index / ask / eval / serve
data/
  inbox/      手动投放入口    corpus/  标准语料（提交材料）
  chroma_db/  索引产物        eval/    评测集
```

## 开发

- `uv run pytest`：63 项测试，全程 FakeEmbedder/FakeLLM 离线可跑
- `uv run ruff check && uv run ruff format`
- CLI 的 `--fake-embed` 为离线开发开关（确定性假向量，索引与问答需同用）
- 种子站 24 个（`seeds.yaml`）：研究生院/商学院为自建站，各学院 _wp3 站走
  静态列表链接（部分模板 href 用单引号，BeautifulSoup 选择器天然兼容）；
  教务处列表页为 generalQuery 接口 JS 渲染（未逆向），以首页为种子；
  career 就业网为招聘系统不抓——相关政策可投 `data/inbox/`
- 换 embedding 模型：改 `config.py` 的 `embedding_model` + `index --full` 重建


## 部署（HF Spaces）

Docker SDK（根目录 `Dockerfile` 已备好）：`DEEPSEEK_API_KEY` 存 Spaces Secrets；
`data/corpus` 与 `data/chroma_db` 随 git 提交，启动只读加载；BGE-M3 首次启动下载
（约 2GB），开 Spaces 持久存储挂 `/data` 复用缓存。本地/自有服务器：
`docker build -t sufe-qa . && docker run -p 7860:7860 sufe-qa`。

> 设计规格原定为 Gradio 界面；为达到定制视觉与交互（红头档案设计语言、盖章动效、
> 引文联动），实现改为 FastAPI + 手写静态前端，能力覆盖规格 4.4 全部要求
> （流式/来源卡片/示例问题/反馈/页头更新时间/页脚免责）。

