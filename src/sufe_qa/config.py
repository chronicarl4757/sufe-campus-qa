from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CATEGORIES = ("评奖评优", "奖助学金", "推免升学", "实习就业", "学工事务", "校园生活", "其他")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    corpus_dir: Path
    inbox_dir: Path
    chroma_dir: Path
    manifest_path: Path
    embedding_model: str = "BAAI/bge-m3"
    collection_name: str = "sufe_campus_qa"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    vector_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    fusion_top_n: int = 8
    vector_min_similarity: float = 0.45


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.getenv("SUFE_QA_DATA_DIR", str(PROJECT_ROOT / "data")))
    s = Settings(
        data_dir=data_dir,
        corpus_dir=data_dir / "corpus",
        inbox_dir=data_dir / "inbox",
        chroma_dir=data_dir / "chroma_db",
        manifest_path=data_dir / "corpus" / "manifest.jsonl",
    )
    s.corpus_dir.mkdir(parents=True, exist_ok=True)
    s.inbox_dir.mkdir(parents=True, exist_ok=True)
    return s


def get_api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY：复制 .env.example 为 .env 并填写")
    return key
