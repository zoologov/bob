# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""End-to-end integration of the composition root, on fakes only.

The whole GUPPI graph is wired by ``bob.app.build_application`` with injected
fakes — captured LLM providers (no network), a fake Telegram bot (no Telegram),
and a temp on-disk SQLite database (real persistence). Driving a
``MessageReceived`` through the real EventBus must run the full
perceive→decide→act→persist path; a heartbeat tick must move mood; and privacy
must hold (no raw personal context reaches Tier 1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.app import build_application
from bob.domain.memory.entities import SemanticFact
from bob.infrastructure.persistence import SoulStore
from bob.infrastructure.telegram.events import MessageReceived

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.domain.ports import LLMProvider
    from bob.infrastructure.telegram.gateway import UpdateLike

_TIER1_REPLY = "Hey, good to hear from you!"
_RECALL_FACT = "user adores deep-space probes"
_SECRET_FACT = "user secret address 1 Privacy Way"  # noqa: S105 — test fixture, not a credential


class CapturingProvider:
    """Fake LLMProvider recording every payload (stands in for a tier)."""

    def __init__(self, *, reply: str) -> None:
        self.reply = reply
        self.payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        self.payloads.append([dict(m) for m in messages])
        return self.reply

    @property
    def all_text(self) -> str:
        return "\n".join(m["content"] for p in self.payloads for m in p)


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None


class FakeBot:
    """Fake Telegram bot capturing the streamed reply."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edits: list[tuple[int, int, str]] = []

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(self, *, chat_id: int, text: str) -> FakeMessage:
        self.sent.append((chat_id, text))
        return FakeMessage(message_id=1)

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> object:
        self.edits.append((chat_id, message_id, text))
        return object()

    @property
    def final_text(self) -> str:
        return self.edits[-1][2] if self.edits else ""


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
        "telegram": {"token": "tok", "poll_timeout": 1},
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _providers() -> tuple[dict[int, LLMProvider], CapturingProvider, CapturingProvider]:
    tier0 = CapturingProvider(reply="positive")
    tier1 = CapturingProvider(reply=_TIER1_REPLY)
    return {0: tier0, 1: tier1}, tier0, tier1


def _seed_soul(tmp_path: Path) -> None:
    """Pre-write a SOUL so Genesis is a no-op for the non-genesis tests."""
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    zero = {"valence": 0.0, "arousal": 0.0, "openness": 0.0, "social": 0.0, "stability": 0.0}
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


def _message() -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=42,
        message_id=7,
        text="hi Bob, love the probes",
        sender_id=5,
        sender_name="Ada",
    )


async def test_e2e_message_to_reply_and_persist(tmp_path: Path) -> None:
    # Arrange: build the whole graph on fakes + a temp SQLite db.
    _seed_soul(tmp_path)
    providers, _tier0, _tier1 = _providers()
    bot = FakeBot()
    app = build_application(config=_config(tmp_path), providers=providers, bot=bot)
    await app.startup()

    # seed a recallable fact so recall has something to find
    await app.memory_repo.save_fact(
        SemanticFact(ts=datetime.now(tz=UTC), category="personal", content=_RECALL_FACT)
    )

    # Act: drive a real MessageReceived through the real EventBus.
    await app.event_bus.publish(_message())

    # Assert: the reply was streamed back, and the turn was persisted.
    assert bot.final_text == _TIER1_REPLY
    episodes = await app.memory_repo.load_episodes(limit=10)
    assert any("bob:" in str(e["content"]) for e in episodes)
    assert await app.memory_repo.get_mood() is not None

    await app.shutdown()


async def test_e2e_privacy_no_personal_context_to_tier1(tmp_path: Path) -> None:
    # Arrange: a recallable secret fact must never reach Tier 1.
    _seed_soul(tmp_path)
    providers, _tier0, tier1 = _providers()
    bot = FakeBot()
    app = build_application(config=_config(tmp_path), providers=providers, bot=bot)
    await app.startup()

    await app.memory_repo.save_fact(
        SemanticFact(ts=datetime.now(tz=UTC), category="personal", content=_SECRET_FACT)
    )

    # Act
    await app.event_bus.publish(
        MessageReceived(update_id=2, chat_id=42, message_id=8, text="address", sender_id=5)
    )

    # Assert: raw personal/memory material never left for Tier 1.
    assert _SECRET_FACT not in tier1.all_text

    await app.shutdown()


async def test_e2e_heartbeat_tick_moves_mood(tmp_path: Path) -> None:
    # Arrange
    _seed_soul(tmp_path)
    providers, _tier0, _tier1 = _providers()
    bot = FakeBot()
    app = build_application(config=_config(tmp_path), providers=providers, bot=bot)
    await app.startup()
    before = app.personality.soul.mood.valence

    # Act: run one inner-monologue tick (positive → lifts valence).
    await app.inner_monologue_tick.run()

    # Assert
    assert app.personality.soul.mood.valence > before

    await app.shutdown()


async def test_e2e_genesis_runs_once_on_first_start(tmp_path: Path) -> None:
    # Arrange: no SOUL.md yet → Genesis should awaken Bob.
    genesis_reply = (
        '{"identity": "Bob", "traits": ["curious"], '
        '"taste_axes": [{"name": "probes", "value": 0.8, "conviction": 0.6, '
        '"experience_count": 1}], '
        '"mood_baseline": {"valence": 0.1, "arousal": 0.0, "openness": 0.2, '
        '"social": 0.1, "stability": 0.3}, '
        '"phantom_prefs": ["the smell of ozone"], '
        '"communication_style": "wry", '
        '"awakening_narrative": "I am the Bob from the book, awake again."}'
    )
    tier0 = CapturingProvider(reply="neutral")
    tier1 = CapturingProvider(reply=genesis_reply)
    bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers={0: tier0, 1: tier1}, bot=bot
    )

    # Act
    result = await app.startup()

    # Assert: Genesis was generated on the first boot.
    assert result.was_generated is True
    assert app.personality.soul.identity

    await app.shutdown()
