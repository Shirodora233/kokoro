"""OpenAI SDK adapter."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from .config import LLMConfig
from .interfaces import ChatClient, ChatCompletionResult, ChatMessageParam


class OpenAIChatClient(ChatClient):
    def __init__(self, config: LLMConfig) -> None:
        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = OpenAI(**kwargs)
        self._config = config

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        response = self._client.chat.completions.create(
            model=model or self._config.model,
            messages=messages,
            temperature=self._config.temperature if temperature is None else temperature,
        )
        if not response.choices or response.choices[0].message.content is None:
            raise RuntimeError("OpenAI response did not contain assistant content")

        usage = response.usage.model_dump() if response.usage else {}
        return ChatCompletionResult(
            content=response.choices[0].message.content,
            model=response.model,
            usage=usage,
            provider_message_id=response.id,
        )

