# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Fake-gateway harness for the BDD acceptance layer (BOB-066 Срез 0).

The acceptance scenarios pin Bob's OBSERVABLE behaviour — a reply, a reaction,
silence, or an honest outage notice — *through the outgoing boundary*, never his
private state. This module is that boundary: a fake aiogram bot (:class:`FakeGateway`)
that records everything Bob emits, plus a small driver (:func:`run_turn`) that boots
the whole GUPPI graph on fakes (captured LLM providers, no network, a temp SQLite db)
and drives one inbound message end-to-end.

Why its own module: the Given/When/Then step definitions read as behaviour, and the
"how" (wiring the graph, capturing sends) lives here as one cohesive harness reused by
every ``.feature``. It mirrors the seams the live e2e tests already use, so acceptance
scenarios and unit e2e exercise the same real path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.app import build_application
from bob.application.runtime.events import MessageReceived
from bob.social.adapters.soul_store import SoulStore
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import UpdateLike
    from bob.kernel.ports import LLMProvider

# The trusted OWNER identity the wired SenderPerception (BOB-019) classifies TRUSTED,
# so a direct turn runs the normal reply path (recall + redaction) rather than a guest
# path. Chat 42 is the single allowed chat.
OWNER_ID = 5
CHAT_ID = 42


class _FakeMessage:
    """Minimal aiogram ``Message`` stand-in returned by the fake send calls."""

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None
        self.message_thread_id: int | None = None


@dataclass(slots=True)
class FakeGateway:
    """A fake aiogram bot that records everything Bob emits (the outgoing boundary).

    Acceptance steps assert against these observations only — ``sent`` replies,
    ``reactions``, and ``typings`` — so behaviour is pinned as a user would witness it,
    never via Bob's internals.
    """

    sent: list[tuple[int, str]] = field(default_factory=list)
    reactions: list[tuple[int, int]] = field(default_factory=list)
    typings: int = 0
    # BOB-066 Срез 1.1: the message_id each reply QUOTED (a Telegram reply-to), or
    # ``None`` for an un-quoted topic-only send — one entry per ``sent`` reply, so a
    # scenario can witness "Bob quoted the addressed message" through the boundary.
    reply_targets: list[int | None] = field(default_factory=list)

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,
    ) -> _FakeMessage:
        self.sent.append((chat_id, text))
        self.reply_targets.append(_reply_to_id(reply_parameters))
        return _FakeMessage(message_id=1)

    async def send_rich_message(
        self, *, chat_id: int, rich_message: object, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,
    ) -> _FakeMessage:
        # BOB-008: the committed reply lands via the rich channel.
        self.sent.append((chat_id, getattr(rich_message, "markdown", "")))
        self.reply_targets.append(_reply_to_id(reply_parameters))
        return _FakeMessage(message_id=1)

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # BOB-018: react-only seam — record that Bob reacted rather than replied.
        self.reactions.append((chat_id, message_id))
        return True

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> bool:
        self.typings += 1
        return True

    async def send_photo(
        self, *, chat_id: int, photo: object, caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        raise NotImplementedError  # pragma: no cover — acceptance turns never post media

    async def send_document(
        self, *, chat_id: int, document: object, caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        raise NotImplementedError  # pragma: no cover — acceptance turns never post media

    @property
    def replied(self) -> bool:
        """Whether Bob sent any reply text through the boundary."""
        return bool(self.sent)

    @property
    def last_reply(self) -> str:
        """The text of Bob's most recent reply (empty when he stayed silent)."""
        return self.sent[-1][1] if self.sent else ""

    @property
    def last_reply_quoted(self) -> int | None:
        """The message_id Bob's most recent reply QUOTED, or ``None`` if un-quoted (BOB-066 .1)."""
        return self.reply_targets[-1] if self.reply_targets else None


def _reply_to_id(reply_parameters: object) -> int | None:
    """The quoted message_id carried by an aiogram ``ReplyParameters`` (or ``None``)."""
    message_id = getattr(reply_parameters, "message_id", None)
    return message_id if isinstance(message_id, int) else None


class _ScriptedProvider:
    """Fake ``LLMProvider`` returning a fixed reply (and a scripted judge verdict)."""

    def __init__(self, *, reply: str) -> None:
        self.reply = reply

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):  # BOB-049: model the judge choosing REPLY
            return JUDGE_REPLY
        return self.reply


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
            "owner_id": OWNER_ID,
            "allowed_chat_ids": [CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": 0},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _seed_soul(tmp_path: Path) -> None:
    """Pre-write a SOUL so Genesis is a no-op for the acceptance turns."""
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    zero = {"valence": 0.0, "arousal": 0.0, "openness": 0.0, "social": 0.0, "stability": 0.0}
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


async def run_turn(tmp_path: Path, *, text: str, reply: str) -> FakeGateway:
    """Boot the full graph on fakes and drive one direct-address turn end-to-end.

    Returns the :class:`FakeGateway` so a scenario can assert on the observable
    outcome. ``reply`` is the scripted Tier-1 answer Bob composes when he chooses to
    reply; the fake providers never touch the network.
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    providers: dict[int, LLMProvider] = {
        0: _ScriptedProvider(reply="positive"),
        1: _ScriptedProvider(reply=reply),
    }
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=gateway, guppi_bot=gateway
    )
    await app.startup()
    try:
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=CHAT_ID,
                message_id=7,
                text=text,
                sender_id=OWNER_ID,
                sender_name="Vladimir",
            )
        )
    finally:
        await app.shutdown()
    return gateway


# A second participant in Bob's topic (BOB-066 Срез 1.1): a distinct sender whose
# earlier turn puts a THIRD voice in the thread, so the next turn reads as multi-party.
NORMAN_ID = 6
_OWNER_MESSAGE_ID = 7


async def run_group_turn(tmp_path: Path, *, text: str, reply: str) -> FakeGateway:
    """Boot the full graph and drive a MULTI-PARTY turn end-to-end (BOB-066 Срез 1.1).

    A prior direct turn from another participant (Norman) lands first — so when the
    owner then addresses Bob, the recent thread already carries a third voice and the
    turn reads as multi-party (``others_present``). Returns the :class:`FakeGateway`
    so a scenario can witness that Bob's reply QUOTES the owner's message
    (``reply_targets``), the observable multi-party behaviour. The owner message keeps
    the same id (:data:`_OWNER_MESSAGE_ID`) the 1:1 driver uses, so the two scenarios
    differ ONLY in whether a third participant is present.
    """
    _seed_soul(tmp_path)
    gateway = FakeGateway()
    providers: dict[int, LLMProvider] = {
        0: _ScriptedProvider(reply="positive"),
        1: _ScriptedProvider(reply=reply),
    }
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=gateway, guppi_bot=gateway
    )
    await app.startup()
    try:
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=CHAT_ID,
                message_id=3,
                text="Bob, привет от Нормана",
                sender_id=NORMAN_ID,
                sender_name="Norman",
            )
        )
        await app.event_bus.publish(
            MessageReceived(
                update_id=2,
                chat_id=CHAT_ID,
                message_id=_OWNER_MESSAGE_ID,
                text=text,
                sender_id=OWNER_ID,
                sender_name="Vladimir",
            )
        )
    finally:
        await app.shutdown()
    return gateway


def now() -> datetime:
    """A timezone-aware stamp for scenarios that need a clock value."""
    return datetime.now(tz=UTC)
