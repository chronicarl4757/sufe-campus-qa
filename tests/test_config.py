from sufe_qa.config import CATEGORIES, load_settings


def test_categories_cover_competition_scope():
    assert CATEGORIES == ("评奖评优", "奖助学金", "推免升学", "实习就业", "学工事务", "校园生活", "其他")


def test_load_settings_creates_data_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path / "data"))
    s = load_settings()
    assert s.corpus_dir.exists()
    assert s.inbox_dir.exists()
    assert s.vector_top_k == 20 and s.fusion_top_n == 8
