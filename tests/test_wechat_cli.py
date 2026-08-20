"""crawl-wechat CLI 接线测试（离线）。"""

from __future__ import annotations

import json

import httpx
import yaml

from sufe_qa import cli
from sufe_qa.schema import load_manifest
from sufe_qa.wechat.article import WechatArticleFetcher

from test_wechat_pipeline import _handler, NORMAL_URL


def _setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(data_dir))
    whitelist = tmp_path / "wechat.yaml"
    whitelist.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "sufe_jwc",
                        "account_name": "上海财经大学教务处",
                        "publisher": "上海财经大学教务处",
                        "scope_unit": "本科生",
                        "category": "学工事务",
                        "enabled": True,
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    seed = tmp_path / "seeds.jsonl"
    seed.write_text(
        json.dumps({"account": "上海财经大学教务处", "url": NORMAL_URL}) + "\n",
        encoding="utf-8",
    )
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    from sufe_qa.crawler.fetcher import SafeFetcher

    real_fetcher = WechatArticleFetcher(
        SafeFetcher(
            client=client, delay=0, allowed_hosts={"mp.weixin.qq.com"}, respect_robots=False
        )
    )
    monkeypatch.setattr(cli.WechatArticleFetcher, "create", staticmethod(lambda **kw: real_fetcher))
    return whitelist, seed


def test_crawl_wechat_seed_mode(tmp_path, monkeypatch, capsys):
    whitelist, seed = _setup(tmp_path, monkeypatch)
    rc = cli.main(
        ["crawl-wechat", "--mode", "seed", "--sources", str(whitelist), "--seed-file", str(seed)]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "发现文章: 1" in out
    assert "最终入库候选: 1" in out
    manifest = load_manifest(tmp_path / "data" / "corpus" / "manifest.jsonl")
    assert len(manifest) == 1


def test_crawl_wechat_werss_unconfigured_skips(tmp_path, monkeypatch, capsys):
    whitelist, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("WERSS_BASE_URL", raising=False)
    rc = cli.main(["crawl-wechat", "--mode", "werss", "--sources", str(whitelist)])
    assert rc == 0  # skip 不是失败（规格 §二十三）
    assert "跳过" in capsys.readouterr().err


def test_crawl_wechat_dry_run(tmp_path, monkeypatch):
    whitelist, seed = _setup(tmp_path, monkeypatch)
    rc = cli.main(
        [
            "crawl-wechat",
            "--mode",
            "seed",
            "--sources",
            str(whitelist),
            "--seed-file",
            str(seed),
            "--dry-run",
        ]
    )
    assert rc == 0
    assert not (tmp_path / "data" / "corpus" / "manifest.jsonl").exists()
