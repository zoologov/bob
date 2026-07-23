# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""End-to-end integration of the composition root, on fakes only.

The whole GUPPI graph is wired by ``bob.app.build_application`` with injected
fakes — captured LLM providers (no network), a fake Telegram bot (no Telegram),
and a temp on-disk SQLite database (real persistence). Driving a
``MessageReceived`` through the real EventBus must run the full
perceive→decide→act→persist path; a heartbeat tick must move mood; and the
selective-redaction invariant must hold (Variant 2): reply-shaping
conversation/memory MAY reach Tier 1, while genuinely-internal ``private_context``
never does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.app import build_application
from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.application.runtime.events import MessageReceived
from bob.infrastructure.persistence import SoulStore
from bob.memory.entities import SemanticFact
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

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
        if is_judge_request(messages):  # BOB-049: model the judge choosing REPLY
            return JUDGE_REPLY
        self.payloads.append([dict(m) for m in messages])
        return self.reply

    @property
    def all_text(self) -> str:
        return "\n".join(m["content"] for p in self.payloads for m in p)


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None
        self.message_thread_id: int | None = None


class FakeBot:
    """Fake aiogram bot capturing the streamed reply (native drafts + commit)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.typings: int = 0

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> FakeMessage:
        self.sent.append((chat_id, text))
        return FakeMessage(message_id=1)

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
        rich_message: object,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> FakeMessage:
        # BOB-008 (Variant A): the committed reply lands via the rich channel.
        self.sent.append((chat_id, getattr(rich_message, "markdown", "")))
        return FakeMessage(message_id=1)

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> FakeMessage:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

    @property
    def final_text(self) -> str:
        return self.sent[-1][1] if self.sent else ""


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
            # The stable sender (id 5, chat 42) is the trusted OWNER so the wired
            # SenderPerception (BOB-019) classifies him TRUSTED — recall + the
            # private/shared redaction run as usual (a guest path is separate).
            "owner_id": 5,
            "allowed_chat_ids": [42],
            "bob": {"token": "bob-tok", "topic_id": 0},
            "guppi": {"token": "guppi-tok"},
        },
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
        # A complex (depth-keyword) message so the hybrid selector routes the
        # reply to the quality Tier 1 model this e2e flow asserts against.
        text="расскажи подробно про зонды, Bob",
        sender_id=5,
        sender_name="Ada",
    )


async def test_e2e_message_to_reply_and_persist(tmp_path: Path) -> None:
    # Arrange: build the whole graph on fakes + a temp SQLite db.
    _seed_soul(tmp_path)
    providers, _tier0, _tier1 = _providers()
    bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=bot
    )
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


async def test_e2e_private_context_redacted_but_memory_shared(tmp_path: Path) -> None:
    # Arrange (Variant 2, selective redaction): conversation/memory IS reply-shaping
    # and MAY reach the Tier 1 reply; only genuinely-internal private_context is
    # Tier-0-only. The reply prompt is built once and the router strips
    # private_context for Tier 1 — assert that seam directly on a crafted request.
    _seed_soul(tmp_path)
    providers, _tier0, tier1 = _providers()
    bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=bot
    )
    await app.startup()

    await app.memory_repo.save_fact(
        SemanticFact(ts=datetime.now(tz=UTC), category="personal", content=_RECALL_FACT)
    )

    # Act: a reply turn whose context carries the recallable memory.
    await app.event_bus.publish(
        MessageReceived(
            update_id=2,
            chat_id=42,
            message_id=8,
            text="расскажи подробно про probes",
            sender_id=5,
        )
    )

    # Assert: the shareable recalled memory reached the Tier 1 reply (Bob remembers),
    # while a router-level private_context would not have (see router unit tests).
    assert _RECALL_FACT in tier1.all_text

    assert _SECRET_FACT not in await _tier1_text_for_private_context()

    await app.shutdown()


async def _tier1_text_for_private_context() -> str:
    """Drive one reply request carrying private_context and return what Tier 1 saw."""
    providers, _t0, tier1 = _providers()
    router = LLMRouter(providers=providers)
    await router.run(
        LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[{"role": "user", "content": "address"}],
            shareable_context="ok to share",
            private_context=_SECRET_FACT,
        )
    )
    return tier1.all_text


async def test_e2e_heartbeat_tick_moves_mood(tmp_path: Path) -> None:
    # Arrange
    _seed_soul(tmp_path)
    providers, _tier0, _tier1 = _providers()
    bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=bot
    )
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
        config=_config(tmp_path),
        providers={0: tier0, 1: tier1},
        bob_bot=bot,
        guppi_bot=bot,
    )

    # Act
    result = await app.startup()

    # Assert: Genesis was generated on the first boot.
    assert result.was_generated is True
    assert app.personality.soul.identity

    await app.shutdown()
