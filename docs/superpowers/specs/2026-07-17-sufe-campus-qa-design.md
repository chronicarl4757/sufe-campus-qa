# 上财校园问答智能体 — 设计规格

日期：2026-07-17 ｜ 状态：已批准（用户口头授权自主推进）

## 1. 背景与目标

上海财经大学计算机与人工智能学院"校园问答智能体开发大赛"参赛作品（[大赛公告](https://mp.weixin.qq.com/s/1eRCtViXfitcuZsolPKiZQ)，截止 2026 年 9 月中旬）。

目标：搭建一款理解学生问题、检索校园官方资料并生成**有来源依据**的回答的智能体。知识范围对齐公告：评奖评优 / 奖助学金 / 推免升学 / 实习就业 / 学工事务 / 校园生活 / 其他。

评审维度决定设计优先级：**回答准确性 > 来源可追溯 > 知识库质量 > 校园实用性 > 交互体验 > 创新性**。成本约束：报销上限 100 元/队，设计目标全程 < 20 元。

## 2. 关键决策（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 技术路线 | 自建 RAG，独立仓库 `~/Github/sufe-campus-qa`，复用 obsidian-rag-agent 的思路但不耦合 |
| Embedding | BGE-M3 本地运行（免费、可复现、中文强） |
| LLM | DeepSeek API（主）/ 智谱 GLM（备），OpenAI 兼容协议 |
| 部署 | HuggingFace Spaces 免费 CPU 档，Gradio SDK，公开 https 链接 |
| 数据来源 | 定向爬虫抓公开官网 + `data/inbox/` 手动投放双入口 |
| 混合检索 | **必须**：向量 + BM25，RRF 融合 |
| 增量索引 | **必须**：content_hash 判重，只处理新增/变更/删除 |

## 3. 总体架构

```
离线索引（本地）：
  crawler/ + data/inbox/ → 解析(trafilatura/pymupdf/python-docx)
  → data/corpus/<category>/*.md + manifest.jsonl
  → 结构感知切分 → BGE-M3 → Chroma(持久化, 随 git 提交)

在线问答（HF Spaces, CPU, 只读加载索引）：
  问题 → 向量 top-20 + BM25 top-20 → RRF 融合 top-8
  → DeepSeek(流式, 严格引用 prompt) → 回答 + [n]引用 → 来源卡片
  低置信 → 拒答模板(不走 LLM)
```

## 4. 分层设计

### 4.1 采集层与语料规范

- `crawler/`：种子站（启动时验证 URL/栏目）：上财官网通知公告、学生工作部/学生处、教务处、研究生院、就业指导中心、计算机与人工智能学院官网。只抓公开页，遵守 robots，限速
- `data/inbox/`：手动投放 PDF/docx/html（群文件、公众号另存）
- 解析：trafilatura(html) / pymupdf(pdf) / python-docx(docx)
- 产出：`data/corpus/<category>/<slug>.md` + `manifest.jsonl`，字段：
  `doc_id, title, source_url, publisher, publish_date, category, fetched_at, content_hash`
- 分类法：评奖评优 / 奖助学金 / 推免升学 / 实习就业 / 学工事务 / 校园生活 / 其他
- 合规红线：不收录含个人隐私/账号密码的材料；inbox 入库前过敏感信息扫描
- `manifest.jsonl` 直接导出为提交材料 #6（知识库来源清单）

### 4.2 索引层（增量）

- 结构感知切分：政策文按"第 X 条/一、二、三/小标题"，普通文按 400–500 字递归切 + 50 字重叠
- chunk 元数据：`doc_id, title, category, source_url, heading_path`
- 增量逻辑：按 `content_hash` diff manifest ↔ Chroma，仅 embed 新增/变更 chunk；删除文档级联删 chunk；`--full` 保留全量重建选项

### 4.3 检索与回答层

- 向量路：BGE-M3，Chroma top-20
- 词面路：BM25（jieba 分词，rank_bm25）top-20
- 融合：RRF top-8；`bge-reranker` 精排为配置开关，默认关（CPU 延迟），评测证明需要再开
- 生成：DeepSeek 流式；system prompt 硬约束——只依据给定资料；每条关键论断带 `[n]` 引用；资料不足明说并指路官方渠道；严禁编造文件名/日期/金额/比例
- 拒答：融合分低于阈值直接返回"未找到可靠来源"模板 + 部门官网指引，不走 LLM；阈值用评测集标定
- query rewrite：v1 不做；评测暴露口语/术语失配后再加开关

### 4.4 交互层（Gradio）

- 流式聊天；回答下来源卡片（标题/发布单位/日期/可点链接）
- 6–8 个示例问题按钮
- 👍👎 反馈写 `feedback.jsonl`（→ 提交材料 #9）。注意 Spaces 重启清盘：反馈日志每周由团队手动从 Space 文件页导出归档，丢失容忍；不为此引入付费持久存储
- 页头：作品名 + 简介 + 知识库更新时间；页脚免责声明
- 视觉从简干净，不堆功能

### 4.5 评测

- 50 题评测集：出自已收录文档，每题带答案要点 + 应引用 doc_id
- 三项指标：检索命中率 / 引用正确率 / 拒答正确率
- M2 达标线（评测集 v1）：检索命中率 ≥ 90%，引用正确率 ≥ 85%，应拒答题拒答正确率 = 100%
- 门禁：改动检索或提示词后评测集分数不降才允许合并

## 5. 工程结构

```
sufe-campus-qa/
├── pyproject.toml          # uv 管理
├── src/sufe_qa/
│   ├── config.py           # 路径/阈值/模型配置, .env 加载
│   ├── crawler/            # 种子站抓取
│   ├── ingest/             # 解析、切分、增量索引
│   ├── retrieve/           # 向量+BM25+RRF
│   ├── generate/           # LLM 客户端、prompt、引用组装
│   ├── app/                # Gradio 界面
│   └── eval/               # 评测集与打分脚本
├── data/
│   ├── inbox/              # 手动投放（gitignore 大文件）
│   ├── corpus/             # 标准语料 + manifest.jsonl（提交）
│   └── chroma_db/          # 索引产物（提交, Spaces 只读）
├── tests/                  # pytest
├── docs/submission/        # 9 项提交材料草稿
└── README.md               # 使用说明（→ 提交材料 #7）
```

约定：uv + pytest + ruff；`.env` 存 API key（不进 git）；中文文档，代码注释从简。

## 6. 部署方案

- Space：Gradio SDK，免费 CPU；`DEEPSEEK_API_KEY` 存 Spaces Secrets
- Chroma 索引与语料随 git 提交；启动只读加载
- BGE-M3 首次启动下载（约 2GB），走 Spaces 持久缓存
- Space README = 作品使用说明

## 7. 提交材料映射（docs/submission/）

1. 团队信息（用户自填）2. 作品简介 3. 体验入口（Space 链接）4. 开发平台说明 5. 费用说明（目标 <20 元，留支付凭证）6. 知识库来源清单（manifest 导出）7. 使用说明（README）8. 演示材料（M4 录制）9. 学生反馈（feedback.jsonl + 试用整理）

## 8. 里程碑

- M1（7 月底）：采集 + 解析 + 增量索引 + CLI 问答闭环
- M2（8 月上旬）：Gradio UI + 来源卡片 + 拒答 + 评测集 v1 达标
- M3（8 月中旬）：HF Spaces 上线 + 10+ 同学试用收反馈
- M4（8 月底–9 月初）：迭代、演示视频、材料定稿

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 官网结构各异，爬虫覆盖不全 | 种子站逐个适配 + inbox 兜底；先量后精 |
| 政策更新过期 | 增量重爬流程 + 页头显示知识库更新时间 |
| Spaces 免费档慢（BGE-M3 冷启动） | 首启预载提示；检索保持 top-k 小；reranker 默认关 |
| 模型编造 | 严格 prompt + 拒答阈值 + 评测集门禁 |
