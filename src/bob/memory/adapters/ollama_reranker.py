# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

"""OllamaReranker — a LOCAL relevance reranker realised as an Ollama-as-scorer.

Realises :class:`bob.domain.ports.Reranker`: an ADDITIVE quality boost that
re-orders the hybrid recall's wide top-``K`` pool by a sharper relevance
judgement and trims it to a tight top-``N``. Like embeddings, it runs locally —
memory content never leaves the machine (privacy, see BOB-011 CONTEXT).

Ollama exposes no native rerank endpoint (the open Q1), so this adapter scores
each ``(query, candidate)`` pair by prompting a local model (a reranker GGUF such
as ``bge-reranker-v2-m3`` / Qwen3-Reranker, or any instruct model) for a single
relevance number in ``[0, 1]`` over the OpenAI-compatible ``/v1/chat/completions``
shape, then sorts candidates by that score (descending) and keeps the top ``N``.
The score is parsed tolerantly: the first number in the reply wins (a chatty
model may wrap it in prose), clamped to ``[0, 1]``.

**Never crashes recall (the additive contract).** The reranker is a boost, not a
dependency: if the endpoint is unavailable, a transient fault persists past the
retries, or *any* candidate's score cannot be parsed, the adapter returns the
input ``candidates`` unchanged (the hybrid order) and logs a one-liner — Bob's
retrieval never regresses because reranking was unavailable. Transient faults are
retried with bounded exponential backoff (reusing
:func:`bob.application.runtime.retry.retry_with_backoff` from BOB-002).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import aiohttp

from bob.application.runtime.retry import retry_with_backoff

if TYPE_CHECKING:
    from bob.application.runtime.retry import Sleep
    from bob.memory.ports import Recalled

logger = logging.getLogger(__name__)

_CHAT_COMPLETIONS_PATH = "v1/chat/completions"

# A cold local model load (first score after a pull) can be slow; the per-call
# budget is modest because reranking runs over ~20-50 short candidates.
_DEFAULT_TIMEOUT_SECONDS = 30.0

# A few quick attempts then give up (and degrade to the input order) — reranking
# must stay snappy; it is a boost, not a blocking dependency.
_DEFAULT_MAX_ATTEMPTS = 2

# Relevance is reported in [0, 1]; out-of-range model output is clamped to it.
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0

# Matches the first (optionally signed/decimal) number in the model's reply.
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")

_SYSTEM_PROMPT = (
    "You are a relevance scorer. Given a user query and one candidate memory, "
    "reply with ONLY a single number between 0 and 1 — how relevant the candidate "
    "is to the query (1 = perfectly relevant, 0 = irrelevant). No other text."
)


class OllamaReranker:
    """Local Ollama-as-scorer :class:`bob.domain.ports.Reranker` (top-K -> top-N).

    One instance targets one ``base_url`` + ``model`` and trims to ``top_n``; build
    it from the ``reranker`` config section via
    :func:`bob.memory.adapters.reranker_factory.build_reranker`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        top_n: int,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        sleep: Sleep | None = None,
    ) -> None:
        if top_n <= 0:
            msg = "reranker.top_n must be a positive integer"
            raise ValueError(msg)
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._top_n = top_n
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._max_attempts = max_attempts
        self._sleep = sleep

    async def rerank(
        self,
        query: str,
        candidates: Sequence[Recalled],
    ) -> list[Recalled]:
        """Re-order ``candidates`` by model-scored relevance; trim to ``top_n``.

        On any unavailability or scoring failure the input ``candidates`` are
        returned unchanged (the hybrid order) — reranking never regresses recall.
        """
        items = list(candidates)
        if not items:
            return []
        try:
            scored = await self._score_all(query, items)
        except Exception:
            logger.warning(
                "reranker unavailable; keeping hybrid order (no rerank)", exc_info=True
            )
            return items
        ranked = sorted(
            range(len(items)),
            key=lambda index: (-scored[index], index),
        )
        return [items[index] for index in ranked[: self._top_n]]

    async def _score_all(self, query: str, candidates: list[Recalled]) -> list[float]:
        """Score every candidate (raises on the first unscorable one, by design).

        A single unparseable score means the ranking would be untrustworthy, so we
        let it propagate and have :meth:`rerank` fall back to the input order — a
        partial/misleading reorder is worse than no reorder.
        """
        return [await self._score_one(query, candidate) for candidate in candidates]

    async def _score_one(self, query: str, candidate: Recalled) -> float:
        content = str(candidate.get("content", ""))
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(query, content)},
        ]
        reply = await retry_with_backoff(
            lambda: self._complete(messages),
            max_attempts=self._max_attempts,
            sleep=self._sleep,
        )
        return _parse_score(reply)

    async def _complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        payload = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "stream": False,
        }
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.post(
                f"{self._base_url}/{_CHAT_COMPLETIONS_PATH}", json=payload
            ) as response,
        ):
            response.raise_for_status()
            body = await response.json()
        if not isinstance(body, Mapping):
            msg = "reranker response is not a JSON object"
            raise ValueError(msg)
        return _message_content(body)


def _user_prompt(query: str, content: str) -> str:
    return f"Query: {query}\nCandidate: {content}\nRelevance score:"


def _message_content(body: Mapping[str, object]) -> str:
    """Pull the assistant message content from a chat-completions body (raises if absent)."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        msg = "reranker response has no choices"
        raise ValueError(msg)
    first = choices[0]
    if not isinstance(first, Mapping):
        msg = "reranker choice is not an object"
        raise ValueError(msg)
    message = first.get("message")
    if not isinstance(message, Mapping):
        msg = "reranker choice has no message"
        raise ValueError(msg)
    content = message.get("content")
    if not isinstance(content, str):
        msg = "reranker message has no string content"
        raise ValueError(msg)
    return content


def _parse_score(reply: str) -> float:
    """Parse the first number from ``reply`` into a relevance score in [0, 1].

    A chatty model may wrap the number in prose ("Relevance: 0.83 because ..."),
    so the first number wins; the result is clamped to ``[0, 1]``. A reply with no
    number is a contract violation and raises (so rerank degrades to input order).
    """
    match = _NUMBER_RE.search(reply)
    if match is None:
        msg = f"reranker reply has no numeric score: {reply!r}"
        raise ValueError(msg)
    score = float(match.group())
    return max(_SCORE_MIN, min(_SCORE_MAX, score))
