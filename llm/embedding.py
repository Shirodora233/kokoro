"""Embedding provider abstraction and OpenAI implementation."""

from __future__ import annotations

from openai import OpenAI

from .config import LLMConfig
from .interfaces import EmbeddingClient


class OpenAIEmbeddingClient:
    """Generate embeddings via the OpenAI embeddings API."""

    def __init__(self, config: LLMConfig) -> None:
        kwargs: dict[str, object] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = OpenAI(**kwargs)
        self._config = config

    def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        response = self._client.embeddings.create(
            input=texts,
            model=model or "text-embedding-3-small",
        )
        return [item.embedding for item in response.data]
