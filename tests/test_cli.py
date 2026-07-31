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
    pages = [
        (
            "https://gs.sufe.edu.cn/Home/Detail/8001",
            "<html><body><article><h1>推免通知</h1><p>" + DOC_TEXT + "</p></article></body></html>",
        )
    ]
    monkeypatch.setattr(cli, "crawl_seed", lambda seed, delay: pages)
    seeds = tmp_path / "seeds.yaml"
    seeds.write_text(
        "seeds:\n"
        "  - name: 测试种子\n"
        "    list_url: https://gs.sufe.edu.cn/Home/List/31\n"
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
    assert meta.source_url == "https://gs.sufe.edu.cn/Home/Detail/8001"
    assert meta.doc_id == doc_id_from("https://gs.sufe.edu.cn/Home/Detail/8001")
    assert meta.category == "推免升学"
    # 暂存目录已清理
    assert not (settings.data_dir / "crawl_staging").exists()
