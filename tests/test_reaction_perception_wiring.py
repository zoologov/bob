# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""End-to-end wiring of reaction perception through the composition root (BOB-050 .7).

The unit tests (``test_perceive_reaction.py`` / the acceptance guardrails) pin the
PIECES; this proves the WIRING the review flagged as missing. The whole graph is
assembled by ``bob.app.build_application`` on fakes only (captured Tier-0/Tier-1
providers — no network, fake Telegram bots, a temp on-disk SQLite db), then a
:class:`BobMessageReaction` is published on the REAL EventBus. It must reach the
real ``PerceiveReaction`` subscribed to ``BOB_MESSAGE_REACTION`` and apply its
effects:

* mood lifts (the warm meaning, BOB-033 band),
* a per-person ``reaction_received`` episode is written (BOB-045),
* the SHARED being-received note is recorded — and is visible to the SAME store the
  acknowledgment hint (.3) in HandleMessage reads (the shared-store linkage).

A scripted fake judge (the Tier-0 provider answers the reaction-judgment prompt with
a fixed warm reading) keeps it deterministic. A garbage Tier-0 reply proves the path
is DECORATIVE: the judge parse-error is caught and dropped, so a published reaction
never crashes the bus or moves Bob.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from bob.app import Application, build_application
from bob.kernel.events import BobMessageReaction
from bob.personality.adapters.notable_reaction_store import KvNotableReactionStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import BotLike, UpdateLike
    from bob.kernel.ports import LLMProvider

# A stable fragment of REACTION_JUDGE_SYSTEM_PROMPT — present only on the reaction
# judgment call, so the fake provider can tell it from any other tier-0 request.
_REACTION_MARKER = "reaction on one of YOUR OWN messages"

# A warm, high-intensity reading the fake judge returns for the reaction call: a
# positive sentiment lifts mood + warms the reactor, and "acknowledge: yes" records a
# being-received note (the labelled format REACTION_JUDGE_SYSTEM_PROMPT asks for).
_WARM_JUDGMENT = (
    "interpretation: его это по-настоящему тронуло\n"
    "sentiment: warm\n"
    "intensity: high\n"
    "acknowledge: yes"
)

_OWNER_ID = 5
_CHAT_ID = 42
_BOB_MESSAGE_ID = 7777


class _ScriptedProvider:
    """Fake LLMProvider: a fixed warm reading for the reaction call, else a default."""

    def __init__(self, *, reaction_reply: str, default: str = "neutral") -> None:
        self._reaction_reply = reaction_reply
        self._default = default

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        if any(_REACTION_MARKER in str(m.get("content", "")) for m in messages):
            return self._reaction_reply
        return self._default


class _FakeBot:
    """Fake aiogram bot satisfying BotLike; this test never polls or sends.

    Only :meth:`get_updates` is reachable (and returns nothing): the test publishes a
    reaction directly on the EventBus and never starts the runtime, so the send seams
    are unused parity stubs cast to :class:`BotLike` at the build site.
    """

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]:
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object:
        raise NotImplementedError  # pragma: no cover

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        return True  # pragma: no cover

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,
    ) -> object:
        raise NotImplementedError  # pragma: no cover

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> object:
        raise NotImplementedError  # pragma: no cover

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> object:
        raise NotImplementedError  # pragma: no cover

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: object,
        message_thread_id: int | None = None,
    ) -> bool:
        return True  # pragma: no cover


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 0},
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "tier0",
            "tier1_base_url": "https://api.example/v1",
            "tier1_model": "tier1",
            "tier1_api_key": "sk-test",
        },
        "telegram": {
            "poll_timeout": 1,
            "owner_id": _OWNER_ID,
            "allowed_chat_ids": [_CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": 0},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _providers(reaction_reply: str) -> dict[int, LLMProvider]:
    tier0 = _ScriptedProvider(reaction_reply=reaction_reply)
    tier1 = _ScriptedProvider(reaction_reply=reaction_reply, default="reply")
    return {0: tier0, 1: tier1}


def _build(tmp_path: Path, *, reaction_reply: str) -> Application:
    bot = cast("BotLike", _FakeBot())
    return build_application(
        config=_config(tmp_path),
        providers=_providers(reaction_reply),
        bob_bot=bot,
        guppi_bot=bot,
    )


async def _seed_bobs_message(app: Application) -> None:
    """Record an episode whose outgoing Bob message is the one the reaction lands on."""
    await app.memory_repo.save_episode(
        {
            "ts": "2026-06-30T12:00:00+00:00",
            "event_type": "owner_message",
            "content": "Хозяин: как ты\nbob: рад, что ты написал — правда",
            "mood_snapshot": "ok",
            "tags": "",
            "sender_id": _OWNER_ID,
            "bob_message_id": _BOB_MESSAGE_ID,
        }
    )


def _reaction() -> BobMessageReaction:
    return BobMessageReaction(
        chat_id=_CHAT_ID,
        message_id=_BOB_MESSAGE_ID,
        emoji_added=("❤",),
        emoji_removed=(),
        reactor_sender_id=_OWNER_ID,
        reactor_name="Хозяин",
    )


# --- off the poll path (BOB-126 review M1) ---------------------------------------------
#
# The reaction judge is a Tier-0 call. With the understudy on and the cloud down it goes to
# a slow local model (up to timeout_seconds = 180 s): perceived INSIDE the poll loop, one
# reaction stalled get_updates for both bots. Here the whole graph runs on the REAL
# MultiBotGateway poll loop; the judge blocks on an event the test controls.

_POLL_WAIT_S = 5.0  # generous: a poll that is not blocked returns in milliseconds


@dataclass
class _Emoji:
    emoji: str


@dataclass
class _Chat:
    id: int
    type: str = "supergroup"


@dataclass
class _User:
    id: int
    full_name: str = "Хозяин"
    username: str | None = None


@dataclass
class _MessageReaction:
    chat: _Chat
    message_id: int
    old_reaction: list[_Emoji]
    new_reaction: list[_Emoji]
    user: _User | None = None


@dataclass
class _ReactionUpdate:
    update_id: int
    message: object | None = None
    effective_chat: _Chat | None = None
    effective_user: _User | None = None
    message_reaction: _MessageReaction | None = None
    message_reaction_count: object | None = None


@dataclass
class _PollingBot(_FakeBot):
    """A fake bot that hands out update batches and counts every ``get_updates``."""

    batches: list[list[_ReactionUpdate]] = field(default_factory=list)
    polls: int = 0

    async def get_updates(  # type: ignore[override]  # batches of the reaction-shaped fake
        self, *, offset: int, timeout: int
    ) -> Sequence[_ReactionUpdate]:
        self.polls += 1
        return self.batches.pop(0) if self.batches else []


class _BlockingJudgeProvider:
    """Tier-0 whose reaction judgment waits until the test releases it."""

    def __init__(self) -> None:
        self.judging = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        if any(_REACTION_MARKER in str(m.get("content", "")) for m in messages):
            self.judging.set()
            await self.release.wait()
            return _WARM_JUDGMENT
        return "neutral"


def _reaction_update_on_bobs_message() -> _ReactionUpdate:
    return _ReactionUpdate(
        update_id=900,
        message_reaction=_MessageReaction(
            chat=_Chat(id=_CHAT_ID),
            message_id=_BOB_MESSAGE_ID,
            old_reaction=[],
            new_reaction=[_Emoji("❤")],
            user=_User(id=_OWNER_ID),
        ),
    )


async def test_a_slow_reaction_judge_does_not_hold_the_next_poll(tmp_path: Path) -> None:
    tier0 = _BlockingJudgeProvider()
    bob_bot = _PollingBot(batches=[[_reaction_update_on_bobs_message()]])
    app = build_application(
        config=_config(tmp_path),
        providers={0: tier0, 1: _ScriptedProvider(reaction_reply="", default="reply")},
        bob_bot=cast("BotLike", bob_bot),
        guppi_bot=cast("BotLike", _PollingBot()),
    )
    await app.memory_repo.initialize()
    try:
        await _seed_bobs_message(app)

        # The poll that carries the reaction returns while the judge is still thinking ...
        await asyncio.wait_for(app.multibot.poll_once(), _POLL_WAIT_S)
        await asyncio.wait_for(tier0.judging.wait(), _POLL_WAIT_S)
        # ... and the NEXT get_updates goes out with the judge still blocked.
        await asyncio.wait_for(app.multibot.poll_once(), _POLL_WAIT_S)
        assert bob_bot.polls == 2
        assert not tier0.release.is_set()

        # Released, the reaction is still felt: it was deferred, not dropped.
        tier0.release.set()
        await asyncio.wait_for(app.reaction_queue.wait_for_idle(), _POLL_WAIT_S)
        episodes = await app.memory_repo.load_episodes(limit=10)
        assert any(e["event_type"] == "reaction_received" for e in episodes)
    finally:
        # A failed assertion must not leave the db thread alive: pytest would hang on exit.
        tier0.release.set()
        await app.reaction_queue.aclose()
        await app.memory_repo.close()


async def test_published_reaction_reaches_perception_and_writes_shared_note(
    tmp_path: Path,
) -> None:
    # Arrange: the whole graph on fakes; the Tier-0 provider scripts a warm reading.
    app = _build(tmp_path, reaction_reply=_WARM_JUDGMENT)
    await app.memory_repo.initialize()
    await _seed_bobs_message(app)
    before = app.personality.soul.mood.valence

    # Act: publish a reaction on Bob's message through the REAL EventBus; perception runs
    # on the reaction queue, off the publisher's path (BOB-126), so wait for it.
    await app.event_bus.publish(_reaction())
    await app.reaction_queue.wait_for_idle()

    # Assert: PerceiveReaction ran end-to-end — mood lifted (BOB-033 band) ...
    assert app.personality.soul.mood.valence > before
    # ... a per-person reaction memory was written (BOB-045) ...
    episodes = await app.memory_repo.load_episodes(limit=10)
    assert any(e["event_type"] == "reaction_received" for e in episodes)
    # ... and the SHARED being-received note is visible to the SAME store the .3
    # acknowledgment hint reads (a second instance over the same repo = the read path).
    hint_view = KvNotableReactionStore(app.memory_repo)
    note = await hint_view.latest()
    assert note is not None
    assert note.sender_id == _OWNER_ID
    assert "тронуло" in note.interpretation

    await app.memory_repo.close()


async def test_reaction_perception_is_decorative_and_never_crashes_the_bus(
    tmp_path: Path,
) -> None:
    # A garbage Tier-0 reply makes the judge raise; the decorative path must catch it.
    app = _build(tmp_path, reaction_reply="???")
    await app.memory_repo.initialize()
    await _seed_bobs_message(app)
    before = app.personality.soul.mood.valence

    # Act: publishing must NOT raise even though the judge fails.
    await app.event_bus.publish(_reaction())
    await app.reaction_queue.wait_for_idle()

    # Assert: Bob is untouched and nothing notable was recorded (failure was dropped).
    assert app.personality.soul.mood.valence == before
    note = await KvNotableReactionStore(app.memory_repo).latest()
    assert note is None

    await app.memory_repo.close()
