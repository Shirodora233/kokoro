"""DTOs for LLM-backed memory reconciliation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from llm.interfaces import ChatMessageParam

from ..models import ReconciliationConfidence, WriteAction


@dataclass(frozen=True)
class LLMReconciliationInput:
    """Prompt-ready reconciliation case file for the LLM."""

    candidates: list[dict[str, Any]]
    candidate_graph: dict[str, Any]
    retrieval_groups: list[dict[str, Any]]
    active_memory_context: dict[str, Any] | None
    scope: dict[str, Any]
    write_policy: dict[str, Any]
    output_contract: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LLMReconciliationDecision:
    """One LLM decision for an extracted candidate."""

    candidate_id: str
    action: WriteAction
    existing_record_id: str | None = None
    target_record_id: str | None = None
    target_candidate_id: str | None = None
    relation_type: str | None = None
    replacement_text: str | None = None
    replacement_metadata: dict[str, Any] = field(default_factory=dict)
    merge_source_record_ids: list[str] = field(default_factory=list)
    invalidated_record_ids: list[str] = field(default_factory=list)
    confidence: ReconciliationConfidence = "medium"
    reason: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LLMReconciliationResponse:
    """Parsed LLM reconciliation response."""

    decisions: list[LLMReconciliationDecision]
    summary: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LLMReconciliationCallResult:
    """Raw LLM call result used for debug metadata."""

    prompt_messages: list[ChatMessageParam]
    raw_output: str
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider_message_id: str | None = None


@dataclass(frozen=True)
class LLMReconciliationValidationResult:
    """Validation result for LLM decisions."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
