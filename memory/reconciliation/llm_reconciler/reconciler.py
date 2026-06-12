"""LLM-main memory reconciler orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from llm.interfaces import ChatClient

from ..deterministic import LegacyDeterministicMemoryReconciler
from ..models import MemoryReconciliationRequest, MemoryWritePlan
from .client import LLMReconciliationClient
from .compiler import MemoryWritePlanCompiler
from .models import LLMReconciliationCallResult
from .parser import LLMReconciliationParser
from .prompt import LLMReconciliationPromptBuilder
from .validator import ReconciliationDecisionValidator


class LLMMemoryReconciler:
    """LLM-main reconciler with validation, repair, and deterministic fallback."""

    def __init__(
        self,
        chat_client: ChatClient,
        model: str | None = None,
        temperature: float = 0.0,
        fallback: LegacyDeterministicMemoryReconciler | None = None,
        max_repair_attempts: int = 1,
        prompt_builder: LLMReconciliationPromptBuilder | None = None,
        parser: LLMReconciliationParser | None = None,
        validator: ReconciliationDecisionValidator | None = None,
        compiler: MemoryWritePlanCompiler | None = None,
    ) -> None:
        self.prompt_builder = prompt_builder or LLMReconciliationPromptBuilder()
        self.client = LLMReconciliationClient(
            chat_client=chat_client,
            model=model,
            temperature=temperature,
            prompt_builder=self.prompt_builder,
        )
        self.fallback = fallback or LegacyDeterministicMemoryReconciler()
        self.max_repair_attempts = max(0, max_repair_attempts)
        self.parser = parser or LLMReconciliationParser()
        self.validator = validator or ReconciliationDecisionValidator()
        self.compiler = compiler or MemoryWritePlanCompiler()

    def reconcile(self, request: MemoryReconciliationRequest) -> MemoryWritePlan:
        calls: list[LLMReconciliationCallResult] = []
        try:
            call = self.client.reconcile(request)
            calls.append(call)
            response = self.parser.parse(call.raw_output)
            validation = self.validator.validate(response, request)
            attempts = 0
            while not validation.ok and attempts < self.max_repair_attempts:
                attempts += 1
                call = self.client.repair(request, call.raw_output, validation.errors)
                calls.append(call)
                response = self.parser.parse(call.raw_output)
                validation = self.validator.validate(response, request)
            if validation.ok:
                return self.compiler.compile(
                    response,
                    request,
                    metadata={
                        "model": calls[-1].model,
                        "usage": calls[-1].usage,
                        "provider_message_id": calls[-1].provider_message_id,
                        "raw_output": calls[-1].raw_output,
                        "prompt_messages": calls[-1].prompt_messages,
                        "repair_attempts": len(calls) - 1,
                        "warnings": validation.warnings,
                    },
                )
            return self._fallback(request, calls, validation.errors)
        except Exception as error:
            return self._fallback(request, calls, [str(error)])

    def _fallback(
        self,
        request: MemoryReconciliationRequest,
        calls: Sequence[LLMReconciliationCallResult],
        errors: Sequence[str],
    ) -> MemoryWritePlan:
        plan = self.fallback.reconcile(request)
        return MemoryWritePlan(
            operations=list(plan.operations),
            metadata={
                **dict(plan.metadata),
                "reconciler": "llm_fallback",
                "llm_errors": list(errors),
                "llm_call_count": len(calls),
                "llm_raw_outputs": [call.raw_output for call in calls],
            },
        )
