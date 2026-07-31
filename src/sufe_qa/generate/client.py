"""LLM 客户端：DeepSeek（OpenAI 兼容协议），流式输出；测试用 FakeLLM 离线替代。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from sufe_qa.config import Settings, get_api_key


class LLMClient(Protocol):
    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]: ...


class DeepSeekClient:
    def __init__(self, settings: Settings):
        from openai import OpenAI  # 仅此处置允许 import

        self._client = OpenAI(api_key=get_api_key(), base_url=settings.llm_base_url)
        self._model = settings.llm_model

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            stream=True,
            temperature=0.1,  # 事实型问答压低温，减编造
            extra_body={
                "thinking": {
                    "type": "disabled",
                },
            },
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class FakeLLM:
    """离线替身：按资料编号拼接确定性回答，仅用于测试/离线演示。"""

    def __init__(self, n_sources: int = 1):
        self._n = n_sources

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        refs = "".join(f"[{i}]" for i in range(1, self._n + 1))
        yield f"（离线演示回答）依据已收录资料{refs}：请接入 DEEPSEEK_API_KEY 获取真实回答。"
