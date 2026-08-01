"""CLI 离线端到端：ingest → index → ask → eval → crawl 胶水，全程 FakeEmbedder/FakeLLM。"""

from __future__ import annotations

import pytest

from sufe_qa import cli
from sufe_qa.config import load_settings
from sufe_qa.generate.client import FakeLLM
from sufe_qa.schema import doc_id_from, load_manifest

DOC_TEXT = (
    "推免工作实施办法 第一条 申请推免的学生应为纳入国家普通本科招生计划录取的应届毕业生，"
    "拥护中国共产党的领导，品德良好，遵纪守法，身心健康，诚实守信，学风端正。"
    "第二条 申请学生应勤奋学习，刻苦钻研，成绩优秀，学术研究兴趣浓厚。"
) * 2
QUESTION = DOC_TEXT[10:110]  # 用正文子串提问：FakeEmbedder 下保证高相似度过门控


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_make_llm", lambda s: FakeLLM(1))
    s = load_settings()
    (s.inbox_dir / "tuimian.md").write_text("# 推免工作实施办法\n\n" + DOC_TEXT, encoding="utf-8")
    return s


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0


def test_offline_end_to_end(settings, capsys):
    assert cli.main(["ingest", "--category", "学工事务", "--publisher", "研究生院"]) == 0
    assert cli.main(["index", "--fake-embed"]) == 0

    assert cli.main(["ask", QUESTION, "--fake-embed"]) == 0
    out = capsys.readouterr().out
    assert "来源：" in out
    assert "推免工作实施办法" in out

    # 无稽问题：相似度过不了门控 → 拒答模板，无来源卡片
    assert cli.main(["ask", "qwerty asdfg zxcvb", "--fake-embed"]) == 0
    out = capsys.readouterr().out
    assert "未在已收录的学校官方资料中找到可靠依据" in out
    assert "来源：" not in out


def test_eval_command_gate(settings, tmp_path, capsys):
    cli.main(["ingest", "--category", "学工事务"])
    cli.main(["index", "--fake-embed"])
    evalset = tmp_path / "evalset.jsonl"
    evalset.write_text(
        '{"id": "q1", "question": "%s", "expected_doc_ids": ["%s"]}\n'
        '{"id": "q2", "question": "qwerty asdfg", "should_refuse": true}\n'
        % (QUESTION.replace('"', "'"), doc_id_from("inbox/tuimian.md")),
        encoding="utf-8",
    )
    assert cli.main(["eval", "--evalset", str(evalset), "--fake-embed"]) == 0
    out = capsys.readouterr().out
    assert "检索命中率: 100.0%" in out
    assert "拒答正确率: 100.0%" in out
    # 达标线拉满到不可能的水平 → 门禁失败，退出码 1
    capsys.readouterr()
    assert (
        cli.main(["eval", "--evalset", str(evalset), "--fake-embed", "--min-refusal", "1.1"]) == 1
    )


def test_crawl_glues_pages_into_corpus(settings, tmp_path, monkeypatch):
    """crawl 走新引擎：stub SafeFetcher 返回列表页+文章页，验证入库与 doc_id 锚定。"""
    from sufe_qa.crawler.fetcher import FetchResult

    article_url = "https://gs.sufe.edu.cn/Home/Detail/8001"
    list_url = "https://gs.sufe.edu.cn/Home/List/31"
    routes = {
        list_url: FetchResult(
            requested_url=list_url,
            final_url=list_url,
            status_code=200,
            content=f'<html><body><div class="blog-content"><a href="{article_url}">推免通知</a></div></body></html>'.encode(),
        ),
        article_url: FetchResult(
            requested_url=article_url,
            final_url=article_url,
            status_code=200,
            content=f"<html><body><article><h1>推免通知</h1><p>{DOC_TEXT}</p></article></body></html>".encode(),
        ),
    }

    class StubFetcher:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def fetch(self, url, kind="html", headers=None):
            return routes.get(url) or FetchResult(
                requested_url=url, final_url=url, status="http_error", status_code=404, error="404"
            )

    monkeypatch.setattr(cli, "SafeFetcher", StubFetcher)
    seeds = tmp_path / "seeds.yaml"
    seeds.write_text(
        "seeds:\n"
        "  - name: 测试种子\n"
        f"    list_url: {list_url}\n"
        '    link_selector: ".blog-content a"\n'
        "    url_prefix: https://gs.sufe.edu.cn/Home/Detail/\n"
        "    category: 推免升学\n"
        "    publisher: 研究生院\n",
        encoding="utf-8",
    )
    assert cli.main(["crawl", "--seeds", str(seeds)]) == 0
    manifest = load_manifest(settings.manifest_path)
    assert len(manifest) == 1
    meta = next(iter(manifest.values()))
    assert meta.source_url == article_url
    assert meta.doc_id == doc_id_from(article_url)
    assert meta.category == "推免升学"
    assert meta.quality_status == "accepted"
    assert meta.document_type == "article"
    # 抓取状态已持久化，raw 缓存已落地
    assert (settings.data_dir / "crawl_state" / "gs.sufe.edu.cn.json").is_file()
    assert (
        settings.data_dir / "raw" / "gs.sufe.edu.cn" / "articles" / f"{meta.doc_id}.html"
    ).is_file()
