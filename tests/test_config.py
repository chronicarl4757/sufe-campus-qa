from sufe_qa.config import CATEGORIES, load_settings


def test_categories_cover_competition_scope():
    assert CATEGORIES == (
        "评奖评优",
        "奖助学金",
        "推免升学",
        "实习就业",
        "学工事务",
        "校园生活",
        "其他",
    )


def test_load_settings_creates_data_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path / "data"))
    s = load_settings()
    assert s.corpus_dir.exists()
    assert s.inbox_dir.exists()
    assert s.vector_top_k == 20 and s.fusion_top_n == 8


def test_get_api_key_returns_env_value(monkeypatch):
    from sufe_qa.config import get_api_key

    # 屏蔽真实 .env 文件对测试的污染
    monkeypatch.setattr("sufe_qa.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    assert get_api_key() == "sk-test-123"


def test_get_api_key_missing_raises(monkeypatch):
    import pytest

    from sufe_qa.config import get_api_key

    # 屏蔽真实 .env 文件对测试的污染
    monkeypatch.setattr("sufe_qa.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        get_api_key()
