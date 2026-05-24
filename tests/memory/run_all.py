"""Run memory test suites from one stable entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys

FAST_SUITES = [
    "tests.memory.retrieval.runner",
    "tests.memory.reconciliation.runner",
    "tests.memory.writing.runner",
    "tests.memory.system.runner",
]

POSTGRES_SUITES = [
    "tests.memory.persistence.runner",
]

REAL_LLM_SUITES = [
    "tests.memory.extractor_real.runner",
    "tests.memory.system_real.runner",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run memory test suites")
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Include PostgreSQL persistence tests.",
    )
    parser.add_argument(
        "--real-llm",
        action="store_true",
        help="Include real LLM integration tests.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env for real LLM tests.",
    )
    parser.add_argument(
        "--strict-real",
        action="store_true",
        help="Pass --strict to real LLM suites.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    suites = [*FAST_SUITES]
    if args.postgres:
        suites.extend(POSTGRES_SUITES)
    if args.real_llm:
        suites.extend(REAL_LLM_SUITES)

    failures: list[str] = []
    for suite in suites:
        command = [sys.executable, "-m", suite]
        if suite in REAL_LLM_SUITES:
            command.extend(["--env-file", args.env_file])
            if args.strict_real:
                command.append("--strict")
        print(f"RUN {suite}", flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            failures.append(suite)

    if failures:
        print("FAILED " + ", ".join(failures), flush=True)
        return 1
    print(f"passed_suites={len(suites)}/{len(suites)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
