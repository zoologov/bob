# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for HandleMessage — the full message→reply→persist flow on fakes.

Everything external is faked: a captured LLM provider (no network), a fake
Telegram bot (no Telegram), and an in-memory SQLite repo/recall (temp DB). The
test asserts the whole perceive→decide→act path: mood update → recall + context
→ Tier 1 reply (with redaction) → streamed reply out → episode + mood persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.application.runtime.events import MessageReceived
from bob.application.usecases.handle_message import HandleMessage, PersonalityState
from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
from bob.domain.personality.mood import Mood
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.domain.ports import Recalled
    from bob.infrastructure.telegram.gateway import UpdateLike

_SECRET_PHANTOM = "phantom-secret-coffee"  # noqa: S105 — test fixture, not a credential
_RECALL_SECRET = "user lives at 42 Privacy Lane"  # noqa: S105 — test fixture


class FixedClock:
    """Clock returning a fixed timezone-aware instant (deterministic tests)."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class CapturingProvider:
    """Fake LLMProvider that records every payload it is asked to complete."""

    def __init__(self, *, reply: str) -> None:
        self.reply = reply
        self.payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol
    ) -> str | AsyncIterator[str]:
        self.payloads.append([dict(m) for m in messages])
        return self.reply

    @property
    def all_text(self) -> str:
        """Concatenated content of every message ever sent to this provider."""
        return "\n".join(m["content"] for payload in self.payloads for m in payload)


class FakeMessage:
    """A minimal Telegram message with a stable id (for the placeholder)."""

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None


class FakeBot:
    """Fake Telegram bot capturing the streamed reply (no network)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edits: list[tuple[int, int, str]] = []

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(self, *, chat_id: int, text: str) -> FakeMessage:
        self.sent.append((chat_id, text))
        return FakeMessage(message_id=777)

    async def edit_message_text(self, *, chat_id: int, message_id: int, text: str) -> object:
        self.edits.append((chat_id, message_id, text))
        return object()

    @property
    def final_text(self) -> str:
        """The last text the reply message was edited to (the full reply)."""
        return self.edits[-1][2] if self.edits else ""


class FakeRepo:
    """In-memory MemoryRepo capturing episodes, facts, and the persisted mood."""

    def __init__(self) -> None:
        self.episodes: list[Mapping[str, object]] = []
        self.facts: list[object] = []
        self.mood: Mapping[str, object] | None = None

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.episodes.append(episode)

    async def save_fact(self, fact: object) -> None:
        self.facts.append(fact)

    async def set_mood(self, state: Mapping[str, object], *, at: datetime) -> None:  # noqa: ARG002
        self.mood = state


class FakeRecall:
    """Recall returning a canned secret memory (to test redaction)."""

    async def recall(self, query: str, *, k: int) -> Sequence[Recalled]:  # noqa: ARG002
        return [{"content": _RECALL_SECRET, "category": "personal"}]


def _moment() -> datetime:
    return datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)


def _soul() -> SOUL:
    baseline = Mood(valence=0.1, social=0.2)
    taste = TasteEngine(axes=(TasteAxis(name="coffee", value=0.9, conviction=0.8),))
    return SOUL(
        identity="I am the Bob from the book.",
        mood=baseline,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=(_SECRET_PHANTOM,),
    )


def _build(*, reply: str) -> tuple[HandleMessage, FakeBot, FakeRepo, CapturingProvider]:
    tier0 = CapturingProvider(reply="positive")
    tier1 = CapturingProvider(reply=reply)
    router = LLMRouter(providers={0: tier0, 1: tier1})
    clock = FixedClock(_moment())
    bot = FakeBot()
    repo = FakeRepo()
    gateway = TelegramGateway(
        bot=bot,
        bus=_NullBus(),
        poll_timeout=1,
        batch_tokens=1,
        throttle_interval=0.0,
        clock=lambda: 0.0,
        sleep=_no_sleep,
    )
    handler = HandleMessage(
        router=router,
        gateway=gateway,
        recall=FakeRecall(),
        repo=repo,
        update_mood=UpdateMoodFromText(router=router, clock=clock),
        clock=clock,
        state=PersonalityState(soul=_soul()),
    )
    return handler, bot, repo, tier1


async def _no_sleep(_seconds: float) -> None:
    return None


class _NullBus:
    async def publish(self, event: object) -> None:  # noqa: ARG002
        return None

    def subscribe(self, event_name: str, handler: object) -> None:  # noqa: ARG002
        return None


def _message(text: str = "tell me about coffee") -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=555,
        message_id=10,
        text=text,
        sender_id=99,
        sender_name="Ada",
    )


async def test_handle_streams_reply_back_to_telegram() -> None:
    # Arrange
    handler, bot, _repo, _tier1 = _build(reply="Coffee is the best.")

    # Act
    await handler.handle(_message())

    # Assert: the reply was streamed out (placeholder + final edit).
    assert bot.sent
    assert bot.sent[0][0] == 555
    assert bot.final_text == "Coffee is the best."


async def test_handle_persists_episode_and_mood() -> None:
    # Arrange
    handler, _bot, repo, _tier1 = _build(reply="ok")

    # Act
    await handler.handle(_message())

    # Assert: an episode and the new mood were persisted.
    assert len(repo.episodes) == 1
    assert repo.episodes[0]["content"]
    assert repo.mood is not None


async def test_reply_uses_tier1_provider() -> None:
    # Arrange
    handler, _bot, _repo, tier1 = _build(reply="hi")

    # Act
    await handler.handle(_message())

    # Assert: the user-facing reply went to the Tier 1 (API) provider.
    assert len(tier1.payloads) == 1


async def test_personal_context_never_reaches_tier1() -> None:
    # Arrange: recall carries a secret; SOUL carries a phantom secret.
    handler, _bot, _repo, tier1 = _build(reply="hi")

    # Act
    await handler.handle(_message())

    # Assert: privacy — no raw personal/memory material leaked to Tier 1.
    assert _RECALL_SECRET not in tier1.all_text
    assert _SECRET_PHANTOM not in tier1.all_text


async def test_mood_updates_from_message() -> None:
    # Arrange: a positive Tier 0 sentiment should lift valence.
    handler, _bot, repo, _tier1 = _build(reply="hi")

    # Act
    await handler.handle(_message("I love this, thank you!"))

    # Assert: persisted mood reflects an update (valence rose from baseline 0.1).
    assert repo.mood is not None
    valence = repo.mood["valence"]
    assert isinstance(valence, float)
    assert valence > 0.1
