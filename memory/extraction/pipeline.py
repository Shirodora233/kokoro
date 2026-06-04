"""Memory extraction pipeline orchestration."""

from __future__ import annotations

import logging
from typing import Sequence

from llm.interfaces import ChatClient

from ..debug import MemoryDebugRecorder, trace_id_from_metadata
from ..models import MemoryRecord, MemoryTurnInput
from .coalescer import MemoryCandidateCoalescer
from .llm import LLMMemoryExtractionCallResult, LLMMemoryExtractionClient
from .normalizer import MemoryCandidateNormalizer
from .parser import MemoryExtractionParseError, parse_extraction_response
from .prompt import MemoryExtractionPromptBuilder
from .validation import MemoryCandidateValidator

LOGGER = logging.getLogger(__name__)


class LLMMemoryExtractor:
    """Extract candidate memory records through a small LLM pipeline."""

    def __init__(
        self,
        chat_client: ChatClient | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        prompt_builder: MemoryExtractionPromptBuilder | None = None,
        llm_client: LLMMemoryExtractionClient | None = None,
        coalescer: MemoryCandidateCoalescer | None = None,
        normalizer: MemoryCandidateNormalizer | None = None,
        validator: MemoryCandidateValidator | None = None,
        debug_recorder: MemoryDebugRecorder | None = None,
    ) -> None:
        if llm_client is None and chat_client is None:
            raise ValueError("chat_client or llm_client is required")
        self.llm_client = llm_client or LLMMemoryExtractionClient(
            chat_client=chat_client,
            model=model,
            temperature=temperature,
            prompt_builder=prompt_builder,
        )
        self.coalescer = coalescer or MemoryCandidateCoalescer()
        self.normalizer = normalizer or MemoryCandidateNormalizer()
        self.validator = validator or MemoryCandidateValidator()
        self.debug_recorder = debug_recorder

    def extract(self, turn: MemoryTurnInput) -> Sequence[MemoryRecord]:
        trace_id = trace_id_from_metadata(turn.metadata)
        call_result = self._extract_call(turn)
        response_text = call_result.raw_output
        try:
            candidates = parse_extraction_response(response_text)
        except MemoryExtractionParseError as error:
            LOGGER.warning("Failed to parse memory extraction response: %s", error)
            self._record_debug(
                trace_id=trace_id,
                turn=turn,
                call_result=call_result,
                parse_status="error",
                parse_error=str(error),
            )
            return []
        coalesced_candidates = self.coalescer.coalesce(candidates)
        validation_result = self.validator.validate(coalesced_candidates)
        for error in validation_result.errors:
            LOGGER.info("Dropped invalid memory candidate: %s", error)
        records = self.normalizer.normalize(validation_result.batch, turn)
        self._record_debug(
            trace_id=trace_id,
            turn=turn,
            call_result=call_result,
            parse_status="ok",
            parsed_batch=candidates,
            validated_batch=validation_result.batch,
            validation_errors=validation_result.errors,
            normalized_records=records,
        )
        return records

    def _extract_call(self, turn: MemoryTurnInput) -> LLMMemoryExtractionCallResult:
        if hasattr(self.llm_client, "extract"):
            return self.llm_client.extract(turn)
        response_text = self.llm_client.extract_text(turn)
        return LLMMemoryExtractionCallResult(
            prompt_messages=[],
            raw_output=response_text,
        )

    def _record_debug(
        self,
        trace_id: str | None,
        turn: MemoryTurnInput,
        call_result: LLMMemoryExtractionCallResult,
        parse_status: str,
        parse_error: str | None = None,
        parsed_batch=None,
        validated_batch=None,
        validation_errors: Sequence[str] = (),
        normalized_records: Sequence[MemoryRecord] = (),
    ) -> None:
        if self.debug_recorder is None:
            return
        self.debug_recorder.record_extraction(
            trace_id,
            turn=turn,
            prompt_messages=call_result.prompt_messages,
            raw_output=call_result.raw_output,
            parse_status=parse_status,
            parse_error=parse_error,
            parsed_batch=parsed_batch,
            validated_batch=validated_batch,
            validation_errors=validation_errors,
            normalized_records=normalized_records,
            metadata={
                "llm_model": call_result.model,
                "provider_message_id": call_result.provider_message_id,
                "usage": call_result.usage,
            },
        )
