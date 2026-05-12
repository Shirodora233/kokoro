"""Context maintenance policy placeholders."""

from __future__ import annotations

from typing import Sequence

from ..models import ContextAction, MemoryTurnInput


class NoopContextPolicy:
    """Return no context actions until compression policies are implemented."""

    def plan_actions(self, turn: MemoryTurnInput) -> Sequence[ContextAction]:
        return []
