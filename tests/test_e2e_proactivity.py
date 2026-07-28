# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-010 Ф1 BEAD-04 — proactivity integration e2e over the composition root.

``build_application`` now wires the drive-engine end to end: the per-persona
:class:`SqliteProactivityStore`, the :class:`ProactivityEngine` (urge → seeded
sample → governance veto → Tier-0 gate → composed reply → post into Bob's topic),
the :class:`ProactiveTick` on the heartbeat, GUPPI's ``/quiet`` / ``/wake`` over
the live store, and the owner-activity recorder on the reactive path. These tests
prove that wiring on fakes only — two fake aiogram bots (no Telegram), fake LLM
providers (no network), a real temp SQLite database, and an **injected fixed clock
+ seed** so the stochastic draw and circadian/governance decision are deterministic:

* (a) high urge + permissive governance → the tick fires, the Tier-0 gate says
  SAY, and the composed message is posted into Bob's topic thread;
* (b) ``/quiet`` (owner-mute) → the tick is vetoed: silent, and ZERO LLM calls;
* (c) an owner message updates ``last_user_msg_at`` and restores social energy;
* (d) ``/wake`` re-enables proactivity (the flag flips back on, timed mute cleared).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.app import Application, build_application
from bob.personality.mood import Mood
from bob.proactivity.adapters import SqliteProactivityStore
from bob.proactivity.decision import ProactiveDecider
from bob.proactivity.governance import Governance, ProactiveHistory
from bob.proactivity.social_energy import SocialEnergy
from bob.proactivity.state import ProactivityState
from bob.social.adapters.soul_store import SoulStore
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from aiogram.types import InputRichMessage

    from bob.kernel.ports import LLMProvider

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_ID = 27468732
_PERSONA = "bob"

# An evening hour, well outside quiet-hours (23:00 to 09:00), so governance permits.
_NOW = datetime(2026, 6, 20, 20, 0, tzinfo=UTC)

_GATE_SAY = "Mulling it over...\nSAY: ask how the day went"
_COMPOSE = "Hey — how did your day go?"


# --- Fakes at the external edges ----------------------------------------------


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _ScriptedProvider:
    """Fake LLMProvider returning scripted replies in order, counting calls."""

    def __init__(self, *, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):  # BOB-049: model the judge choosing REPLY
            return JUDGE_REPLY
        index = min(self.calls, len(self._replies) - 1)
        self.calls += 1
        return self._replies[index]


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _FakeUser:
    id: int
    full_name: str = "Ada"


@dataclass
class _FakeChat:
    id: int


@dataclass
class _FakeUpdate:
    update_id: int
    message: _FakeMessage | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    rich_sends: list[_SendCall] = field(default_factory=list)
    typings: int = 0
    next_message_id: int = 900

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[_FakeUpdate]:
        if not self.updates_batches:
            return []
        return self.updates_batches.pop(0)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=text)
        self.next_message_id += 1
        return msg

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # BOB-018: react-only seam; fakes accept the BotLike reaction call.
        return True

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> bool:
        self.typings += 1
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        self.rich_sends.append(
            _SendCall(
                chat_id=chat_id,
                text=rich_message.markdown or "",
                message_thread_id=message_thread_id,
            )
        )
        return _FakeMessage(message_id=0, text=rich_message.markdown)

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

# --- Config + builders --------------------------------------------------------


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
            "chat_id": _CHAT_ID,
            "owner_id": _OWNER_ID,
            "allowed_chat_ids": [_CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": _BOB_TOPIC_ID},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _seed_soul(tmp_path: Path, *, mood: Mood) -> None:
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    high = {
        "valence": mood.valence,
        "arousal": mood.arousal,
        "openness": mood.openness,
        "social": mood.social,
        "stability": mood.stability,
    }
    store.write_json("mood", {"baseline": high, "current": high})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


def _providers(*, tier0: _ScriptedProvider, tier1: _ScriptedProvider) -> dict[int, LLMProvider]:
    return {0: tier0, 1: tier1}


def _firing_seed(mood: Mood) -> int:
    """Find a seed whose first draw fires the high urge (keeps the test honest)."""
    decider = ProactiveDecider(clock=_FixedClock(_NOW), governance=Governance())
    for seed in range(2000):
        if decider.should_speak(
            mood=mood,
            silence_seconds=12.0 * 3600.0,
            salience=1.0,
            social_energy=1.0,
            history=ProactiveHistory(
                last_spoke_at=None, last_user_msg_at=None, sent_in_window=0, muted=False
            ),
            rng=random.Random(seed),
        ):
            return seed
    raise AssertionError("no firing seed found")


_HIGH_MOOD = Mood(valence=0.9, arousal=0.9, openness=0.9, social=0.9)


async def _seed_proactivity_state(
    app: Application, state: ProactivityState
) -> None:
    store = SqliteProactivityStore(app.memory_repo)
    await store.save(_PERSONA, state)


async def _add_recent_reflection(app: Application) -> None:
    await app.memory_repo.save_episode(
        {
            "ts": _NOW.isoformat(),
            "event_type": "reflection",
            "content": "I've been wondering how the day treated them.",
            "mood_snapshot": None,
            "tags": "heartbeat",
        }
    )


def _build(tmp_path: Path, *, bob_bot: _FakeBot, guppi_bot: _FakeBot, seed: int) -> Application:
    tier0 = _ScriptedProvider(replies=[_GATE_SAY, _COMPOSE])
    tier1 = _ScriptedProvider(replies=[_COMPOSE])
    return build_application(
        config=_config(tmp_path),
        providers=_providers(tier0=tier0, tier1=tier1),
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        clock=_FixedClock(_NOW),
        proactivity_seed=seed,
    )


def _command(text: str) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=1,
        message=_FakeMessage(message_id=1, text=text, message_thread_id=None),
        effective_chat=_FakeChat(id=_CHAT_ID),
        effective_user=_FakeUser(id=_OWNER_ID),
    )


# --- Tests --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_high_urge_fires_gate_says_and_posts_into_bob_thread(
    tmp_path: Path,
) -> None:
    # Arrange: high mood + a recent reflection + full energy + a firing seed; the
    # gate replies SAY so Bob composes and posts.
    _seed_soul(tmp_path, mood=_HIGH_MOOD)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot, seed=_firing_seed(_HIGH_MOOD))
    await app.startup()
    await _add_recent_reflection(app)
    await _seed_proactivity_state(
        app,
        ProactivityState(
            social_energy=SocialEnergy(1.0),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=True,
        ),
    )

    # Act: run one proactive tick through the wired engine.
    try:
        spoke = await app.proactivity_engine.tick()
    finally:
        await app.shutdown()

    # Assert: Bob spoke — the composed message landed in his topic thread.
    assert spoke is True
    assert bob_bot.rich_sends, "Bob should have posted a proactive message"
    final = bob_bot.rich_sends[-1]
    assert final.text == _COMPOSE
    assert final.message_thread_id == _BOB_TOPIC_ID


@pytest.mark.asyncio
async def test_quiet_mute_vetoes_the_tick_silently_with_zero_llm(
    tmp_path: Path,
) -> None:
    # Arrange: same firing conditions, but the owner has /quiet-ed Bob first.
    _seed_soul(tmp_path, mood=_HIGH_MOOD)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    seed = _firing_seed(_HIGH_MOOD)
    tier0 = _ScriptedProvider(replies=[_GATE_SAY, _COMPOSE])
    tier1 = _ScriptedProvider(replies=[_COMPOSE])
    app = build_application(
        config=_config(tmp_path),
        providers=_providers(tier0=tier0, tier1=tier1),
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        clock=_FixedClock(_NOW),
        proactivity_seed=seed,
    )
    await app.startup()
    await _add_recent_reflection(app)
    await _seed_proactivity_state(
        app,
        ProactivityState(
            social_energy=SocialEnergy(1.0),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=True,
        ),
    )

    # The owner mutes Bob via GUPPI's /quiet in General (toggles the live flag).
    guppi_bot.updates_batches = [[_command("/quiet")]]
    await app.multibot.poll_once()

    # Act: the proactive tick now runs against a muted persona.
    try:
        spoke = await app.proactivity_engine.tick()
    finally:
        await app.shutdown()

    # Assert: governance vetoed — silent, no proactive post, and ZERO LLM calls.
    assert spoke is False
    assert bob_bot.rich_sends == []
    assert tier0.calls == 0
    assert tier1.calls == 0


@pytest.mark.asyncio
async def test_owner_message_records_activity_and_restores_energy(
    tmp_path: Path,
) -> None:
    # Arrange: a depleted reservoir and no prior owner marker.
    _seed_soul(tmp_path, mood=_HIGH_MOOD)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot, seed=0)
    await app.startup()
    await _seed_proactivity_state(
        app,
        ProactivityState(
            social_energy=SocialEnergy(0.1),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=True,
        ),
    )

    # Act: the owner writes in Bob's topic — the reactive path records activity.
    bob_bot.updates_batches = [
        [
            _FakeUpdate(
                update_id=5,
                message=_FakeMessage(
                    message_id=5, text="hey Bob", message_thread_id=_BOB_TOPIC_ID
                ),
                effective_chat=_FakeChat(id=_CHAT_ID),
                effective_user=_FakeUser(id=_OWNER_ID),
            )
        ]
    ]
    try:
        published = await app.multibot.poll_once()
        state = await app.proactivity_store.load(_PERSONA)
    finally:
        await app.shutdown()

    # Assert: the turn published, the owner marker is stamped to now, and energy
    # was partially restored (the "you came back" bump).
    assert published == 1
    assert state.last_user_msg_at == _NOW
    assert state.social_energy.level > 0.1


@pytest.mark.asyncio
async def test_wake_reenables_proactivity(tmp_path: Path) -> None:
    # Arrange: Bob is muted (proactivity off, with a timed mute).
    _seed_soul(tmp_path, mood=_HIGH_MOOD)
    bob_bot, guppi_bot = _FakeBot(), _FakeBot()
    app = _build(tmp_path, bob_bot=bob_bot, guppi_bot=guppi_bot, seed=0)
    await app.startup()
    await _seed_proactivity_state(
        app,
        ProactivityState(
            social_energy=SocialEnergy(0.5),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=False,
        ),
    )
    await app.proactivity_store.set_mute_until(_PERSONA, _NOW + timedelta(hours=2))

    # Act: the owner sends /wake.
    guppi_bot.updates_batches = [[_command("/wake")]]
    try:
        await app.multibot.poll_once()
        state = await app.proactivity_store.load(_PERSONA)
        mute_until = await app.proactivity_store.get_mute_until(_PERSONA)
    finally:
        await app.shutdown()

    # Assert: proactivity is back on and the timed mute is cleared.
    assert state.proactivity_enabled is True
    assert mute_until is None
