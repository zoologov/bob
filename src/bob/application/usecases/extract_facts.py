# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ExtractFacts — distil durable, user-specific facts into semantic memory.

Tier 0 of the turn (GUPPI's "remember" step). After a reply is sent and the
episode persisted, this use-case asks the cheap, local **Tier 0** provider (via
the :class:`LLMRouter`, ``TaskType.EXTRACT_FACTS``) to read the latest exchange
and return durable facts about the user — a name, a preference, a person, a
decision — as structured JSON items ``{"category": ..., "content": ...}``.

Each item becomes a :class:`~bob.domain.memory.entities.SemanticFact` and is
written through the :class:`FactWriter` seam (the SQLite repo, whose FTS5 trigger
indexes the content) so a later turn's :class:`~bob.domain.ports.MemoryRecall`
can surface it back into the reply context. Obvious repeats are de-duplicated.

It is **best-effort**: episodic conversation already carries the turn, so a model
that returns prose instead of JSON, or a provider that errors, must never break
the turn — the caller invokes :meth:`run` after the reply and swallows nothing of
value if it yields no facts. This layer only orchestrates; parsing is local and
the durable-fact rules live in the pure domain entity.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.memory.entities import SemanticFact

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.domain.ports import Clock

logger = logging.getLogger(__name__)

# Confidence assigned to an extracted fact — distilled, but model-derived.
_EXTRACTED_CONFIDENCE = 0.7

_SYSTEM_PROMPT = (
    "Extract durable, user-specific facts from the conversation: the user's "
    "name, stable preferences, important people, and decisions. Ignore small "
    "talk and anything transient. Reply with ONLY a JSON array of objects, each "
    '{"category": "<user|preference|person|decision>", "content": "<short fact>"}. '
    "If there are no durable facts, reply with []."
)


class FactWriter(Protocol):
    """The persistence seam ExtractFacts needs: store one durable fact."""

    async def save_fact(self, fact: SemanticFact) -> None: ...


class ExtractFacts:
    """Extract durable facts from a turn (Tier 0) and persist them, best-effort."""

    def __init__(self, *, router: LLMRouter, repo: FactWriter, clock: Clock) -> None:
        self._router = router
        self._repo = repo
        self._clock = clock

    async def run(self, *, user_message: str, reply: str | None = None) -> None:
        """Extract and persist durable facts from the latest exchange.

        Never raises: extraction is an enrichment on top of the already-persisted
        episode, so a provider error or malformed output is logged and dropped.
        """
        try:
            raw = await self._extract(user_message, reply)
        except Exception:
            logger.exception("Tier 0 fact extraction failed; skipping (best-effort)")
            return
        await self._persist(_parse_facts(raw))

    async def _extract(self, user_message: str, reply: str | None) -> str:
        """Ask the Tier 0 provider for the structured fact payload."""
        request = LLMRequest(
            task_type=TaskType.EXTRACT_FACTS,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _exchange(user_message, reply)},
            ],
        )
        return await self._router.run(request)

    async def _persist(self, items: list[tuple[str, str]]) -> None:
        """Persist each de-duplicated fact as a SemanticFact."""
        seen: set[str] = set()
        now = self._clock.now()
        for category, content in items:
            key = content.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            await self._repo.save_fact(
                SemanticFact(
                    ts=now,
                    category=category,
                    content=content.strip(),
                    confidence=_EXTRACTED_CONFIDENCE,
                )
            )


def _exchange(user_message: str, reply: str | None) -> str:
    """Render the latest exchange the extractor should read."""
    if reply:
        return f"User: {user_message}\nBob: {reply}"
    return f"User: {user_message}"


def _parse_facts(raw: str) -> list[tuple[str, str]]:
    """Parse the model's JSON array into ``(category, content)`` pairs.

    Tolerant by design (best-effort): non-JSON, a non-array, non-object entries,
    or missing/blank ``content`` yield no item rather than an error.
    """
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.debug("Fact extraction returned non-JSON output; ignoring")
        return []
    if not isinstance(decoded, list):
        return []
    facts: list[tuple[str, str]] = []
    for entry in decoded:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        category = entry.get("category")
        facts.append((category if isinstance(category, str) and category else "user", content))
    return facts
