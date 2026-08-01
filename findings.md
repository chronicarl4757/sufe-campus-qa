# 现状与研究发现

## 仓库基线

- 当前分支由 `m1-core` 创建为 `feat/question-driven-crawl`，worktree 位于 `/home/chronicarl/.config/superpowers/worktrees/sufe-campus-qa/feat/question-driven-crawl`。
- 原 checkout 的 `data/chroma_db/chroma.sqlite3` 有用户未提交修改；隔离 worktree 未触碰该修改。
- 基线 `uv run pytest -q`：235 passed，4 个既有依赖警告。
- `data/corpus/manifest.jsonl` 共有 617 行历史记录，`data/corpus/` 有 275 个 corpus 文件，现有评测集只有 22 行。

## 当前采集缺口

- `seeds.yaml` 仍以教务处首页静态链接、学生处两栏第一页和 `_wp3` 宽选择器为主。
- 现有抓取报告只覆盖 `gs.sufe.edu.cn`。
- 现有 manifest 元数据主要有 `document_type/quality_status` 等附件字段，尚无完整的主题、版本证据、来源类型和 collection 字段。

## 公开站点形态

- `https://jwc.sufe.edu.cn/5124/list.htm` 是 `_wp3` 页面，正文直接挂载选课、重修、双专业、校外学习学分认定、休学复学、退学、缓考、转专业和学生证补发的 PDF/DOC/XLS。
- `https://jwc.sufe.edu.cn/5127/list.htm` 暴露总记录数 61、总页数 5、`list2.htm` 到 `list5.htm`。
- `https://xsc.sufe.edu.cn/5437/list.htm` 暴露总记录数 21、总页数 2，下一页为 `/5437/list2.htm`。
- `https://gs.sufe.edu.cn/` 的导航包含招生、培养、学位、学籍、国际交流、综合服务等多个 `/Home/List/<id>` 栏目。
- career、NIC、图书馆、后勤、信息公开、医疗、财务、国际交流、保卫处主页均可从当前网络访问；尚未进行写入抓取。

## 已遇到的错误

| 错误 | 尝试次数 | 解决方案 |
|---|---:|---|
| zsh 变量 `path` 覆盖 `PATH`，导致 `mkdir/git` 未找到 | 1 | 使用 `worktree_target` 显式变量和绝对路径重试；未产生仓库变更 |
| 设计文档补丁缺少行首 `+` | 2 | 拆分补丁并用 `git diff --check` 验证；设计文档已成功提交 |
