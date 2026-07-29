# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BEAD-07 integration + e2e over the composition root, on fakes only.

The deferred BOB-002 pieces are wired in ``bob.app.build_application``: a populated
:class:`CapabilityRegistry` (carrying the live ``recall_memory`` capability) drives
the production tool-loop, the heartbeat ticks run under a retry policy, and the
rich gateway + authz gate are composed coherently. These tests prove that wiring
end to end with fakes at the external edges only — a fake aiogram bot (no
Telegram), fake LLM providers shaped like real reasoning models (no network), and
a real temp SQLite database (real persistence):

* an unauthorized user/chat is dropped at the single gate;
* an authorized message yields a streamed reply;
* the tool-loop calls ``recall_memory`` end to end and the reply uses the result;
* ``RichBlockThinking`` renders when a ``thinking`` block is present;
* a heartbeat tick survives a transient error (retry policy + isolation).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiohttp

from bob.app import build_application
from bob.application.runtime.events import MessageReceived
from bob.capabilities.ports import ToolCall, ToolCallResult
from bob.infrastructure.telegram.guppi import GUPPI_REJECT_TEXT
from bob.infrastructure.telegram.multibot import BotIdentity
from bob.memory.entities import SemanticFact
from bob.social.adapters.soul_store import SoulStore
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence
    from pathlib import Path

    from bob.capabilities.ports import ToolDefinition
    from bob.infrastructure.telegram.gateway import UpdateLike
    from bob.kernel.ports import LLMProvider

_OWNER = 1
_CHAT = 100
_TOPIC = 32
_RECALL_FACT = "user adores deep-space probes"
_PLAIN_REPLY = "Hey, good to hear from you!"


# --- Fakes at the external edges (no network, no Telegram) --------------------


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


class ToolCallingTier1:
    """Fake tier-1 provider shaped like a reasoning model that calls a tool.

    Realises BOTH :class:`LLMProvider` (the plain reply path) AND
    :class:`ToolCallingProvider` (the tool-loop path). On the first
    ``complete_with_tools`` turn it requests ``recall_memory``; on the next turn,
    having seen the tool result, it returns a final answer that quotes it — so the
    e2e asserts the loop fed the capability result back into the reply.
    """

    def __init__(self, *, plain_reply: str) -> None:
        self.plain_reply = plain_reply
        self.tool_calls_seen = 0
        self.last_tool_result = ""
        self.plain_payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        self.plain_payloads.append([dict(m) for m in messages])
        return self.plain_reply

    async def complete_with_tools(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        if self.tool_calls_seen == 0:
            assert any(
                _tool_name(t) == "recall_memory" for t in tools
            ), "recall_memory must be advertised in the manifest"
            self.tool_calls_seen += 1
            return ToolCallResult(
                text="",
                tool_calls=(
                    ToolCall(id="c1", name="recall_memory", arguments={"query": "probes"}),
                ),
            )
        # Second turn: the tool result is now the last message; quote it back.
        self.last_tool_result = str(messages[-1].get("content", ""))
        return ToolCallResult(
            text=f"From memory: {self.last_tool_result}", tool_calls=()
        )


def _tool_name(tool: ToolDefinition) -> str:
    function = tool.get("function")
    if isinstance(function, Mapping):
        name = function.get("name")
        if isinstance(name, str):
            return name
    return ""


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None
        self.message_thread_id: int | None = None


class FakeBot:
    """Fake aiogram bot capturing drafts, plain sends, and rich sends."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.sent_threads: list[int | None] = []
        self.typings: int = 0
        self.rich_sent: list[tuple[int, str]] = []
        self.rich_threads: list[int | None] = []
        self._next_id = 1

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> FakeMessage:
        self.sent.append((chat_id, text))
        self.sent_threads.append(message_thread_id)
        message_id = self._next_id
        self._next_id += 1
        return FakeMessage(message_id=message_id)

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
        message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> FakeMessage:
        self.rich_sent.append((chat_id, _rich_markdown(rich_message)))
        self.rich_threads.append(message_thread_id)
        return FakeMessage(message_id=999)

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
        """Bob's committed reply: the rich final in a topic, else the last plain."""
        if self.rich_sent:
            return self.rich_sent[-1][1]
        return self.sent[-1][1] if self.sent else ""


def _rich_markdown(rich_message: object) -> str:
    markdown = getattr(rich_message, "markdown", "")
    return markdown if isinstance(markdown, str) else ""


class _Chat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class _User:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.full_name = "U"


class _Update:
    def __init__(
        self,
        update_id: int,
        *,
        chat_id: int,
        user_id: int,
        text: str,
        thread_id: int | None = _TOPIC,
    ) -> None:
        self.update_id = update_id
        self.message = FakeMessage(message_id=update_id)
        self.message.text = text
        self.message.message_thread_id = thread_id
        self.effective_chat = _Chat(chat_id)
        self.effective_user = _User(user_id)


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
            "chat_id": _CHAT,
            "owner_id": _OWNER,
            "allowed_chat_ids": [_CHAT],
            "bob": {"token": "bob-tok", "topic_id": _TOPIC},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _seed_soul(tmp_path: Path) -> None:
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    zero = {"valence": 0.0, "arousal": 0.0, "openness": 0.0, "social": 0.0, "stability": 0.0}
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


def _message(*, chat_id: int = _CHAT, user_id: int = _OWNER) -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=chat_id,
        message_id=7,
        # A complex (depth-keyword) message so the hybrid reply selector escalates
        # the plain-reply path to the quality Tier 1 model this e2e asserts against.
        text="расскажи подробно про зонды, Bob",
        sender_id=user_id,
        sender_name="Ada",
    )


# --- Tests --------------------------------------------------------------------


async def test_e2e_guest_in_topic_routed_but_foreign_chat_dropped(
    tmp_path: Path,
) -> None:
    # BOB-019 bob-apv.2: the single authz gate is wired from config. A stranger IN
    # the allowed chat + Bob's topic is a GUEST (Bob's pipeline runs, restricted
    # downstream); a stranger OUTSIDE the allowed chat is still dropped (chat-scope
    # intact). The owner is the trusted path. No GUPPI hard-reject for the guest.
    _seed_soul(tmp_path)
    providers: dict[int, LLMProvider] = {
        0: CapturingProvider(reply="positive"),
        1: CapturingProvider(reply=_PLAIN_REPLY),
    }
    bot = FakeBot()
    guppi_bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=guppi_bot
    )
    await app.startup()

    try:
        guest = await app.multibot.route(
            _Update(1, chat_id=_CHAT, user_id=555, text="hi"), BotIdentity.BOB
        )
        foreign = await app.multibot.route(
            _Update(2, chat_id=_CHAT + 1, user_id=555, text="hi", thread_id=None),
            BotIdentity.BOB,
        )
        owner = await app.multibot.route(
            _Update(3, chat_id=_CHAT, user_id=_OWNER, text="hi"), BotIdentity.BOB
        )
    finally:
        await app.shutdown()

    assert guest is True  # guest in Bob's topic reaches the pipeline
    assert foreign is False  # outside the allowed chat → dropped
    assert owner is True
    # No GUPPI hard-reject for the guest (the visible reject path is gone).
    assert GUPPI_REJECT_TEXT not in [text for _, text in guppi_bot.sent]


async def test_e2e_authorized_message_yields_reply(tmp_path: Path) -> None:
    # Arrange: no capabilities registry override → plain reply path through tier 1.
    _seed_soul(tmp_path)
    tier1 = CapturingProvider(reply=_PLAIN_REPLY)
    providers: dict[int, LLMProvider] = {0: CapturingProvider(reply="positive"), 1: tier1}
    bot = FakeBot()
    guppi_bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=guppi_bot
    )
    await app.startup()

    # Act (intake-развязка BOB-066 2.1: publish enqueues → await the worker).
    await app.event_bus.publish(_message())
    await app.intake_dispatcher.wait_for_idle()

    # Assert: the reply reached the user (plain commit) and the turn persisted.
    assert bot.final_text == _PLAIN_REPLY
    episodes = await app.memory_repo.load_episodes(limit=10)
    assert any("bob:" in str(e["content"]) for e in episodes)

    await app.shutdown()


async def test_e2e_tool_loop_calls_recall_memory(tmp_path: Path) -> None:
    # Arrange: the production registry (recall_memory) + a tool-calling tier 1.
    _seed_soul(tmp_path)
    tier1 = ToolCallingTier1(plain_reply=_PLAIN_REPLY)
    providers: dict[int, LLMProvider] = {0: CapturingProvider(reply="positive"), 1: tier1}
    bot = FakeBot()
    guppi_bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=guppi_bot
    )
    await app.startup()

    # A recallable fact the capability will surface.
    await app.memory_repo.save_fact(
        SemanticFact(ts=datetime.now(tz=UTC), category="personal", content=_RECALL_FACT)
    )

    # Act: drive a real turn; the model asks for recall_memory, GUPPI executes it.
    await app.event_bus.publish(_message())
    await app.intake_dispatcher.wait_for_idle()

    # Assert: the tool-loop ran, the capability result fed back, and the reply
    # quotes the recalled fact.
    assert tier1.tool_calls_seen == 1
    assert _RECALL_FACT in tier1.last_tool_result
    assert _RECALL_FACT in bot.final_text

    await app.shutdown()


async def test_e2e_registry_is_populated_with_recall_memory(tmp_path: Path) -> None:
    # Arrange/Act
    _seed_soul(tmp_path)
    providers: dict[int, LLMProvider] = {
        0: CapturingProvider(reply="positive"),
        1: ToolCallingTier1(plain_reply=_PLAIN_REPLY),
    }
    app = build_application(
        config=_config(tmp_path),
        providers=providers,
        bob_bot=FakeBot(),
        guppi_bot=FakeBot(),
    )

    # Assert: the composition root registered recall_memory in the manifest.
    names = [_tool_name(t) for t in app.registry.manifest()]
    assert "recall_memory" in names
    assert not app.registry.is_empty


async def test_e2e_bob_reply_is_pinned_to_his_topic_thread(tmp_path: Path) -> None:
    # Arrange: an authorized owner message routed into Bob's topic. The reply
    # streams through the multi-bot gateway's Bob seam, which pins his topic.
    _seed_soul(tmp_path)
    providers: dict[int, LLMProvider] = {
        0: CapturingProvider(reply="positive"),
        1: CapturingProvider(reply=_PLAIN_REPLY),
    }
    bot = FakeBot()
    guppi_bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=guppi_bot
    )
    await app.startup()

    # Act: route the owner's message in Bob's topic through the central router.
    try:
        published = await app.multibot.route(
            _Update(7, chat_id=_CHAT, user_id=_OWNER, text="расскажи подробно, Bob"),
            BotIdentity.BOB,
        )
    finally:
        await app.shutdown()

    # Assert: Bob replied, pinned to his topic thread; GUPPI stayed silent.
    # BOB-007: the topic streams via native drafts and commits the rich final, so the
    # thread pin is asserted on the rich final (rich_threads), not a plain send.
    assert published is True
    assert bot.final_text == _PLAIN_REPLY
    assert bot.rich_threads[-1] == _TOPIC
    assert guppi_bot.sent == []
    assert guppi_bot.rich_sent == []


async def test_e2e_tick_survives_transient_error(tmp_path: Path) -> None:
    # Arrange: a tier-0 provider that blips transiently on its first call, then
    # recovers — the inner-monologue tick runs under the production retry policy.
    _seed_soul(tmp_path)
    tier0 = _FlakyTier0(reply="positive")
    providers: dict[int, LLMProvider] = {0: tier0, 1: CapturingProvider(reply=_PLAIN_REPLY)}
    bot = FakeBot()
    guppi_bot = FakeBot()
    app = build_application(
        config=_config(tmp_path), providers=providers, bob_bot=bot, guppi_bot=guppi_bot
    )
    await app.startup()
    before = app.personality.soul.mood.valence

    # Act: run the runtime so the supervised periodic tick fires under retry. The
    # first attempt blips transiently; the retry recovers and the tick lifts mood.
    await app.runtime.start()
    try:
        await _wait_until(
            lambda: app.personality.soul.mood.valence > before, timeout=5.0
        )
    finally:
        await app.shutdown()

    # Assert: the transient error did not kill the tick; the retry recovered and
    # mood moved (≥2 attempts means the blip was retried, not surfaced).
    assert tier0.calls >= 2
    assert app.personality.soul.mood.valence > before


async def _wait_until(
    predicate: Callable[[], bool], *, timeout: float, interval: float = 0.01
) -> None:
    """Poll ``predicate`` until true or ``timeout`` elapses (deterministic edge)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() >= deadline:
            raise AssertionError("condition not met before timeout")
        await asyncio.sleep(interval)


class _FlakyTier0:
    """Tier-0 fake that raises a transient connection error on its first call."""

    def __init__(self, *, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):  # BOB-049: model the judge choosing REPLY
            return JUDGE_REPLY
        self.calls += 1
        if self.calls == 1:
            raise aiohttp.ServerDisconnectedError("transient blip")
        return self.reply
