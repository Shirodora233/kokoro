"""Memory extraction pipeline orchestration."""

from __future__ import annotations

import logging
from typing import Sequence

from llm.interfaces import ChatClient

from ..models import MemoryRecord, MemoryTurnInput
from .llm import LLMMemoryExtractionClient
from .normalizer import MemoryCandidateNormalizer
from .parser import MemoryExtractionParseError, parse_extraction_response
from .prompt import MemoryExtractionPromptBuilder

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
        normalizer: MemoryCandidateNormalizer | None = None,
    ) -> None:
        if llm_client is None and chat_client is None:
            raise ValueError("chat_client or llm_client is required")
        self.llm_client = llm_client or LLMMemoryExtractionClient(
            chat_client=chat_client,
            model=model,
            temperature=temperature,
            prompt_builder=prompt_builder,
        )
        self.normalizer = normalizer or MemoryCandidateNormalizer()

    def extract(self, turn: MemoryTurnInput) -> Sequence[MemoryRecord]:
        response_text = self.llm_client.extract_text(turn)
        try:
            candidates = parse_extraction_response(response_text)
        except MemoryExtractionParseError as error:
            LOGGER.warning("Failed to parse memory extraction response: %s", error)
            return []
        return self.normalizer.normalize(candidates, turn)
