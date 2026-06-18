# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""HandleMessage — the full message→reply→persist flow (GUPPI's act loop).

Subscribed to :class:`~bob.application.runtime.events.MessageReceived`, this
use-case runs Bob's perceive→decide→act turn (RFC §"Поток обработки"):

1. **Perceive** — :class:`UpdateMoodFromText` (Tier 0 sentiment + signals) updates
   the in-memory mood; the new mood is held on :class:`PersonalityState`.
2. **Decide** — recall relevant memory (:class:`MemoryRecall`, FTS5) and assemble
   the personality context (identity, mood tone, taste verdict, phantom prefs).
   That context is private: it is handed to the :class:`LLMRouter` as
   ``personal_context``, which the router strips before any Tier 1 call so raw
   personal/memory material never leaves the machine (VISION §7.1).
3. **Act** — the router replies on ``TaskType.REPLY_TO_USER`` (Tier 1 + redaction,
   fallback Tier 0); the reply is streamed back through the Telegram gateway and
   the turn is persisted (episode + mood snapshot) via the :class:`MemoryRepo`.

This layer only orchestrates: tone/verdict come from the pure domain, transport
and storage live behind ports, and time is injected via :class:`Clock`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.application.usecases.update_mood_from_text import TextSignals
from bob.domain.memory.entities import EpisodicEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from datetime import datetime

    from bob.application.router.llm_router import LLMRouter
    from bob.application.runtime.events import MessageReceived
    from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
    from bob.domain.personality.soul import SOUL
    from bob.domain.ports import Clock, MemoryRecall, Recalled

logger = logging.getLogger(__name__)

# How many memories to recall when assembling the reply context.
_RECALL_K = 5

# Each streamed reply is a single message; a present sender is engaged.
_SINGLE_MESSAGE = 1

_SYSTEM_PROMPT = (
    "You are Bob, a digital person from the Bobiverse. Reply in character, "
    "warmly and concisely, coloured by your current mood."
)


class ReplyStreamer(Protocol):
    """The Telegram seam HandleMessage needs: stream a reply into a chat."""

    async def stream_reply(self, *, chat_id: int, tokens: AsyncIterator[str]) -> int: ...


class EpisodeWriter(Protocol):
    """The persistence seam HandleMessage needs: save an episode + the mood."""

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...

    async def set_mood(self, state: Mapping[str, object], *, at: datetime) -> None: ...


@dataclass
class PersonalityState:
    """Mutable in-memory holder for Bob's current soul snapshot across turns.

    The soul (identity, taste, phantoms) is constant for a boot; only the mood
    evolves, so each turn replaces the snapshot via :meth:`SOUL.with_mood`.
    """

    soul: SOUL


class HandleMessage:
    """Run one full Telegram turn: perceive mood, decide a reply, act, persist."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        gateway: ReplyStreamer,
        recall: MemoryRecall,
        repo: EpisodeWriter,
        update_mood: UpdateMoodFromText,
        clock: Clock,
        state: PersonalityState,
    ) -> None:
        self._router = router
        self._gateway = gateway
        self._recall = recall
        self._repo = repo
        self._update_mood = update_mood
        self._clock = clock
        self._state = state

    async def handle(self, event: MessageReceived) -> None:
        """Process one received message end to end (the EventBus subscriber)."""
        soul = await self._perceive(event)
        recalled = await self._recall.recall(event.text, k=_RECALL_K)
        reply = await self._decide(event.text, soul, recalled)
        await self._gateway.stream_reply(chat_id=event.chat_id, tokens=_iter_tokens(reply))
        await self._persist(event, reply, soul)

    async def _perceive(self, event: MessageReceived) -> SOUL:
        """Update mood from the message text and store the new soul snapshot."""
        signals = TextSignals(text=event.text, message_count=_SINGLE_MESSAGE, present=True)
        new_mood = await self._update_mood.run(self._state.soul.mood, signals)
        soul = self._state.soul.with_mood(new_mood)
        self._state.soul = soul
        return soul

    async def _decide(
        self, text: str, soul: SOUL, recalled: Sequence[Recalled]
    ) -> str:
        """Build the request (private context redacted for Tier 1) and get the reply."""
        request = LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            personal_context=_assemble_context(soul, text, recalled),
        )
        return await self._router.run(request)

    async def _persist(self, event: MessageReceived, reply: str, soul: SOUL) -> None:
        """Save the turn as an episode and snapshot the updated mood."""
        now = self._clock.now()
        episode = EpisodicEvent(
            ts=now,
            event_type="message",
            content=f"{event.sender_name or 'user'}: {event.text}\nbob: {reply}",
            mood_snapshot=soul.mood.tone(),
            tags=("telegram",),
        )
        await self._repo.save_episode(
            {
                "ts": episode.ts.isoformat(),
                "event_type": episode.event_type,
                "content": episode.content,
                "mood_snapshot": episode.mood_snapshot,
                "tags": ",".join(episode.tags),
            }
        )
        await self._repo.set_mood(_mood_state(soul), at=now)


def _assemble_context(soul: SOUL, topic: str, recalled: Sequence[Recalled]) -> str:
    """Compose Bob's private personality + memory context (Tier-0-only).

    This string is deliberately NEVER sent to Tier 1: the router redacts it for
    remote calls. It carries identity, mood tone, the taste verdict on the topic,
    phantom preferences, and recalled memories.
    """
    verdict = soul.taste.score(topic).value
    lines = [
        f"Identity: {soul.identity}",
        f"Mood tone: {soul.mood.tone()}",
        f"Taste verdict on '{topic}': {verdict}",
    ]
    if soul.phantom_prefs:
        lines.append("Phantom preferences: " + ", ".join(soul.phantom_prefs))
    memories = [str(item.get("content", "")) for item in recalled]
    if memories:
        lines.append("Recalled memories: " + " | ".join(memories))
    return "\n".join(lines)


def _mood_state(soul: SOUL) -> dict[str, object]:
    """Serialise the soul's mood vector into a persistable state blob."""
    mood = soul.mood
    return {
        "valence": mood.valence,
        "arousal": mood.arousal,
        "openness": mood.openness,
        "social": mood.social,
        "stability": mood.stability,
    }


async def _iter_tokens(text: str) -> AsyncIterator[str]:
    """Yield ``text`` word by word so the gateway streams it as a reply."""
    words = text.split(" ")
    for index, word in enumerate(words):
        yield word if index == 0 else f" {word}"
