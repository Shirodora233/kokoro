"""Run real-LLM integration tests for the in-memory memory system."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from llm.config import LLMConfig
from llm.openai_client import OpenAIChatClient
from memory.config import MemoryRuntimeConfig
from memory.extraction import LLMMemoryExtractor, MemoryExtractionPromptBuilder
from memory.system import InMemoryMemorySystem

from .cases import MemorySystemTestScenario, build_scenarios
from .checks import ScenarioResult, TurnRun, evaluate_scenario
from .recording import RecordingChatClient
from .report import write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real memory system tests")
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
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only the selected scenario id. Can be repeated.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_file = Path(args.env_file)
    llm_config = LLMConfig.from_env(env_file)
    memory_config = MemoryRuntimeConfig.from_env(env_file)
    chat_client = RecordingChatClient(OpenAIChatClient(llm_config))
    scenarios = _selected_scenarios(build_scenarios(), args.case_ids)

    results = [
        _run_scenario(
            scenario=scenario,
            chat_client=chat_client,
            llm_config=llm_config,
            memory_config=memory_config,
        )
        for scenario in scenarios
    ]

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


def _run_scenario(
    scenario: MemorySystemTestScenario,
    chat_client: RecordingChatClient,
    llm_config: LLMConfig,
    memory_config: MemoryRuntimeConfig,
) -> ScenarioResult:
    system = InMemoryMemorySystem(
        extractor=LLMMemoryExtractor(
            chat_client=chat_client,
            model=memory_config.extraction_model or llm_config.model,
            temperature=memory_config.extraction_temperature,
            prompt_builder=MemoryExtractionPromptBuilder(
                max_context_messages=memory_config.extraction_max_context_messages,
            ),
        )
    )
    if scenario.seed_records:
        system.seed_records(scenario.seed_records)

    turns: list[TurnRun] = []
    for index, turn in enumerate(scenario.turns, start=1):
        chat_client.clear()
        start = time.perf_counter()
        try:
            result = system.process_turn(turn)
            duration = time.perf_counter() - start
            turns.append(
                TurnRun(
                    turn_index=index,
                    result=result,
                    duration_seconds=duration,
                    token_usage=chat_client.last_usage,
                    llm_input=chat_client.last_input,
                    llm_output=chat_client.last_output,
                )
            )
        except Exception as error:
            duration = time.perf_counter() - start
            turns.append(
                TurnRun(
                    turn_index=index,
                    error=f"{type(error).__name__}: {error}",
                    duration_seconds=duration,
                    token_usage=chat_client.last_usage,
                    llm_input=chat_client.last_input,
                    llm_output=chat_client.last_output,
                )
            )
            break

    last_turn = scenario.turns[min(len(turns), len(scenario.turns)) - 1]
    final_records = system.store.list_records(
        user_id=last_turn.user_id,
        session_id=last_turn.session_id,
    )
    active_context = system.get_active_context(
        user_id=last_turn.user_id,
        session_id=last_turn.session_id,
    )
    return evaluate_scenario(
        scenario=scenario,
        turns=turns,
        final_records=final_records,
        active_context=active_context.to_record(),
    )


def _selected_scenarios(
    scenarios: list[MemorySystemTestScenario],
    case_ids: list[str] | None,
) -> list[MemorySystemTestScenario]:
    if not case_ids:
        return scenarios
    selected = [scenario for scenario in scenarios if scenario.scenario_id in case_ids]
    missing = sorted(set(case_ids) - {scenario.scenario_id for scenario in selected})
    if missing:
        raise SystemExit(f"Unknown scenario ids: {', '.join(missing)}")
    return selected


def _default_report_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("tests") / "memory" / "system_real" / "reports" / f"{timestamp}.md"


if __name__ == "__main__":
    sys.exit(main())
