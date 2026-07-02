# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

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
import re
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


# Markdown code fence, optionally tagged (``` or ```json), capturing its body.
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _strip_code_fence(raw: str) -> str:
    """Return the body of the first markdown code fence, or ``raw`` unchanged.

    Reasoning models often wrap their answer in a fenced block (``` or ```json);
    parsing the body is more reliable than parsing the fenced wrapper.
    """
    match = _FENCE_RE.search(raw)
    return match.group(1) if match else raw


def _first_json_array(text: str) -> str | None:
    """Extract the first balanced ``[...]`` substring, or ``None``.

    Scans from the first ``[`` to its matching ``]``, respecting nesting and
    skipping brackets inside JSON string literals (with escapes). Tolerates a
    prose/reasoning preamble before, and any trailing text after, the array.
    """
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _decode_array(raw: str) -> list[object] | None:
    """Decode ``raw`` into a JSON list, recovering from reasoning-model wrapping.

    Tries, in order: the raw text, its code-fence body, then the first balanced
    JSON array substring (tolerating a prose preamble or trailing text). Returns
    ``None`` if no JSON array can be recovered.
    """
    candidates = [raw, _strip_code_fence(raw)]
    array = _first_json_array(raw)
    if array is not None:
        candidates.append(array)
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(decoded, list):
            return decoded
    return None


def _parse_facts(raw: str) -> list[tuple[str, str]]:
    """Parse the model's JSON array into ``(category, content)`` pairs.

    Tolerant by design (best-effort): reasoning-model wrapping (markdown code
    fences, a prose/reasoning preamble, or trailing text) is stripped before
    parsing; genuine non-JSON, a non-array, non-object entries, or missing/blank
    ``content`` yield no item rather than an error.
    """
    decoded = _decode_array(raw)
    if decoded is None:
        logger.debug("Fact extraction returned no parseable JSON array; ignoring")
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
