"""Run real-LLM integration tests for LLMMemoryExtractor."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from llm.config import LLMConfig
from llm.interfaces import ChatClient, ChatCompletionResult, ChatMessageParam
from llm.openai_client import OpenAIChatClient
from memory.config import MemoryRuntimeConfig
from memory.extraction import LLMMemoryExtractor, MemoryExtractionPromptBuilder

from .cases import build_cases
from .checks import CaseResult, TokenUsage, evaluate_case, failed_case
from .report import write_report


class RecordingChatClient:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run memory extractor tests")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument(
        "--report-path",
        default=None,
        help="Markdown report path. Defaults to a timestamped report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when any expectation fails",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_file = Path(args.env_file)
    llm_config = LLMConfig.from_env(env_file)
    memory_config = MemoryRuntimeConfig.from_env(env_file)
    chat_client = RecordingChatClient(OpenAIChatClient(llm_config))
    extractor = LLMMemoryExtractor(
        chat_client=chat_client,
        model=memory_config.extraction_model or llm_config.model,
        temperature=memory_config.extraction_temperature,
        prompt_builder=MemoryExtractionPromptBuilder(
            max_context_messages=memory_config.extraction_max_context_messages,
        ),
    )

    results: list[CaseResult] = []
    for case in build_cases():
        chat_client.last_usage = None
        chat_client.last_input = []
        chat_client.last_output = None
        start = time.perf_counter()
        try:
            records = list(extractor.extract(case.turn))
            duration = time.perf_counter() - start
            results.append(
                evaluate_case(
                    case,
                    records,
                    duration,
                    token_usage=chat_client.last_usage,
                    llm_input=chat_client.last_input,
                    llm_output=chat_client.last_output,
                )
            )
        except Exception as error:
            duration = time.perf_counter() - start
            results.append(
                failed_case(
                    case,
                    error,
                    duration,
                    token_usage=chat_client.last_usage,
                    llm_input=chat_client.last_input,
                    llm_output=chat_client.last_output,
                )
            )

    report_path = Path(args.report_path) if args.report_path else _default_report_path()
    write_report(
        report_path,
        results=results,
        model=llm_config.model,
        extraction_model=memory_config.extraction_model,
        base_url_configured=bool(llm_config.base_url),
    )
    passed_count = sum(1 for result in results if result.passed)
    print(f"report={report_path}")
    print(f"passed={passed_count}/{len(results)}")
    if args.strict and passed_count != len(results):
        return 1
    return 0


def _default_report_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("tests") / "memory" / "extractor_real" / "reports" / f"{timestamp}.md"


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


if __name__ == "__main__":
    sys.exit(main())
