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
    # collection_name 保留为主问答 collection 的兼容字段；旧名称只用于迁移输入。
    collection_name: str = "sufe_qa_main_v2"
    public_list_collection_name: str = "sufe_qa_public_list_v2"
    legacy_collection_name: str = "sufe_campus_qa"
    collection_schema_version: str = "2"
    llm_model: str = "deepseek-v4-flash"
    llm_base_url: str = "https://api.deepseek.com"
    vector_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    fusion_top_n: int = 8
    # 最终 top-N 中同一文档的 chunk 数上限：防止单文档/同模板兄弟文档霸占全部
    # 生成上下文槽位（长 PDF FAQ、各学院同名"复试办法"的真实故障形态）
    max_chunks_per_doc: int = 3
    vector_min_similarity: float = (
        0.5  # 以 data/eval/evalset.v1.jsonl 标定：应答题最低 0.55，垃圾问题最高 0.47
    )
    llm_timeout: float = 60.0  # DeepSeek 请求超时（秒），防止流式连接悬挂
    max_question_chars: int = 500  # 问题长度上限，超出直接拒绝
    rate_limit_per_minute: int = 12  # 单 IP 每分钟问答/反馈请求上限
    max_concurrent_llm: int = 8  # 全局 LLM 并发闸，保护配额与成本


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except ValueError:
        return default


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.getenv("SUFE_QA_DATA_DIR", str(PROJECT_ROOT / "data")))
    s = Settings(
        data_dir=data_dir,
        corpus_dir=data_dir / "corpus",
        inbox_dir=data_dir / "inbox",
        chroma_dir=data_dir / "chroma_db",
        manifest_path=data_dir / "corpus" / "manifest.jsonl",
        llm_timeout=_env_float("SUFE_QA_LLM_TIMEOUT", 60.0),
        max_question_chars=_env_int("SUFE_QA_MAX_QUESTION_CHARS", 500),
        rate_limit_per_minute=_env_int("SUFE_QA_RATE_LIMIT_PER_MINUTE", 12),
        max_concurrent_llm=_env_int("SUFE_QA_MAX_CONCURRENT_LLM", 8),
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
