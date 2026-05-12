"""Run real-LLM integration tests for LLMMemoryExtractor."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from llm.config import LLMConfig
from llm.openai_client import OpenAIChatClient
from memory.config import MemoryRuntimeConfig
from memory.extraction import LLMMemoryExtractor, MemoryExtractionPromptBuilder

from .cases import build_cases
from .checks import CaseResult, evaluate_case, failed_case
from .report import write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run memory extractor tests")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument(
        "--report-path",
        default="memory_extractor_tests/reports/latest.md",
        help="Markdown report path",
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
    chat_client = OpenAIChatClient(llm_config)
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
        start = time.perf_counter()
        try:
            records = list(extractor.extract(case.turn))
            duration = time.perf_counter() - start
            results.append(evaluate_case(case, records, duration))
        except Exception as error:
            duration = time.perf_counter() - start
            results.append(failed_case(case, error, duration))

    report_path = Path(args.report_path)
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


if __name__ == "__main__":
    sys.exit(main())
