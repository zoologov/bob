# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""HandleMessage — the full message→reply→persist flow (GUPPI's act loop).

Subscribed to :class:`~bob.application.runtime.events.MessageReceived`, this
use-case runs Bob's perceive→decide→act turn (RFC §"Поток обработки"):

1. **Perceive** — :class:`UpdateMoodFromText` (Tier 0 sentiment + signals) updates
   the in-memory mood; the new mood is held on :class:`PersonalityState`.
2. **Decide** — replay recent conversation history (:class:`EpisodeReader`),
   recall relevant memory (:class:`MemoryRecall`, FTS5) and assemble the context.
   Following Variant 2 (selective redaction), the reply-shaping material
   (recent history, recalled memory, mood tone, identity, taste verdict, phantom
   prefs) is handed to the :class:`LLMRouter` as ``shareable_context`` — it MAY
   accompany the Tier 1 reply because it shapes Bob's reply and returns to that
   same user. Genuinely-internal material would go in ``private_context``
   (Tier-0-only); in P0.1 that channel is empty but the seam is kept (VISION §7.1).
3. **Act** — the router replies on ``TaskType.REPLY_TO_USER`` (Tier 1 + redaction,
   fallback Tier 0); the reply is streamed back through the Telegram gateway and
   the turn is persisted (episode + mood snapshot) via the :class:`MemoryRepo`.
4. **Remember** — after the reply, :class:`ExtractFacts` (Tier 0) distils durable,
   user-specific facts into ``semantic_memory`` so a later turn's
   :class:`MemoryRecall` can surface them. Best-effort: it never raises, so a
   flaky local model cannot break a turn that has already replied.

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
    from bob.application.usecases.extract_facts import ExtractFacts
    from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
    from bob.domain.personality.soul import SOUL
    from bob.domain.ports import Clock, MemoryRecall, Recalled

logger = logging.getLogger(__name__)

# How many memories to recall when assembling the reply context.
_RECALL_K = 5

# How many recent conversation turns to replay into the reply context.
_HISTORY_K = 6

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


class EpisodeReader(Protocol):
    """The read seam HandleMessage needs: replay recent conversation history."""

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]: ...


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
        episodes: EpisodeReader,
        update_mood: UpdateMoodFromText,
        extract_facts: ExtractFacts,
        clock: Clock,
        state: PersonalityState,
    ) -> None:
        self._router = router
        self._gateway = gateway
        self._recall = recall
        self._repo = repo
        self._episodes = episodes
        self._update_mood = update_mood
        self._extract_facts = extract_facts
        self._clock = clock
        self._state = state

    async def handle(self, event: MessageReceived) -> None:
        """Process one received message end to end (the EventBus subscriber)."""
        soul = await self._perceive(event)
        recalled = await self._recall.recall(event.text, k=_RECALL_K)
        history = await self._episodes.recent_episodes(_HISTORY_K)
        reply = await self._decide(event.text, soul, recalled, history)
        await self._gateway.stream_reply(chat_id=event.chat_id, tokens=_iter_tokens(reply))
        await self._persist(event, reply, soul)
        # Tier 0 "remember" step: distil durable facts into semantic memory so a
        # later turn's recall can surface them. Best-effort — run() never raises,
        # so a flaky local model can never break a turn that already replied.
        await self._extract_facts.run(user_message=event.text, reply=reply)

    async def _perceive(self, event: MessageReceived) -> SOUL:
        """Update mood from the message text and store the new soul snapshot."""
        signals = TextSignals(text=event.text, message_count=_SINGLE_MESSAGE, present=True)
        new_mood = await self._update_mood.run(self._state.soul.mood, signals)
        soul = self._state.soul.with_mood(new_mood)
        self._state.soul = soul
        return soul

    async def _decide(
        self,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
    ) -> str:
        """Build the request (selective redaction) and get the reply.

        Reply-shaping context (history + memory + mood/identity/taste) goes in
        ``shareable_context`` so it reaches the Tier 1 reply; the
        ``private_context`` channel is kept for Tier-0-only material (empty here).
        """
        request = LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            shareable_context=_assemble_shareable_context(soul, text, recalled, history),
            private_context=None,
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


def _assemble_shareable_context(
    soul: SOUL,
    topic: str,
    recalled: Sequence[Recalled],
    history: Sequence[Mapping[str, object]],
) -> str:
    """Compose Bob's reply-shaping context (Variant 2: MAY reach Tier 1).

    Carries recent conversation history, identity, mood tone, the taste verdict
    on the topic, phantom preferences, and recalled memories — all material that
    shapes Bob's reply and returns to the same user, so the reply tier sees it
    (this is what lets Bob remember a name said one message ago). Genuinely
    internal material is NOT assembled here; it belongs in ``private_context``.
    """
    verdict = soul.taste.score(topic).value
    lines = [
        f"Identity: {soul.identity}",
        f"Mood tone: {soul.mood.tone()}",
        f"Taste verdict on '{topic}': {verdict}",
    ]
    if soul.phantom_prefs:
        lines.append("Phantom preferences: " + ", ".join(soul.phantom_prefs))
    turns = [str(item.get("content", "")) for item in history if item.get("content")]
    if turns:
        lines.append("Recent conversation:\n" + "\n".join(turns))
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
