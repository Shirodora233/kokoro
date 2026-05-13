"""Recording helpers for real LLM integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm.interfaces import ChatClient, ChatCompletionResult, ChatMessageParam


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    raw_usage: dict[str, Any] = field(default_factory=dict)


class RecordingChatClient:
    """Capture the latest chat request, response, and usage."""

    def __init__(self, inner: ChatClient) -> None:
        self.inner = inner
        self.last_usage: TokenUsage | None = None
        self.last_input: list[dict[str, str]] = []
        self.last_output: str | None = None

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        self.last_input = [dict(message) for message in messages]
        self.last_output = None
        completion = self.inner.complete(
            messages=messages,
            model=model,
            temperature=temperature,
        )
        self.last_usage = _token_usage_from_raw(completion.usage)
        self.last_output = completion.content
        return completion

    def clear(self) -> None:
        self.last_usage = None
        self.last_input = []
        self.last_output = None


def _token_usage_from_raw(raw_usage: dict[str, object]) -> TokenUsage:
    input_tokens = _first_int_field(raw_usage, ("prompt_tokens", "input_tokens"))
    output_tokens = _first_int_field(raw_usage, ("completion_tokens", "output_tokens"))
    total_tokens = _first_int_field(raw_usage, ("total_tokens",))
    cached_tokens = _cached_tokens(raw_usage)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
        raw_usage=dict(raw_usage),
    )


def _int_field(raw_usage: dict[str, object], key: str) -> int | None:
    value = raw_usage.get(key)
    return value if isinstance(value, int) else None


def _first_int_field(
    raw_usage: dict[str, object],
    keys: tuple[str, ...],
) -> int | None:
    for key in keys:
        value = _int_field(raw_usage, key)
        if value is not None:
            return value
    return None


def _cached_tokens(raw_usage: dict[str, object]) -> int | None:
    for key in ("prompt_tokens_details", "input_tokens_details"):
        details = raw_usage.get(key)
        if isinstance(details, dict):
            value = details.get("cached_tokens")
            if isinstance(value, int):
                return value
    return None
