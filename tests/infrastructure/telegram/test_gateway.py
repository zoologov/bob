# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Telegram gateway (transport-only: intake, dedup, typing+rich reply).

No real Telegram network: a hand-rolled fake aiogram-style bot records calls. A
monotonic fake clock makes the "Bob is typing…" cadence deterministic.

BOB-009 (typing keepalive): the slow generation runs INSIDE
``typing_indicator(chat_id)`` — an async context manager that fires
``sendChatAction("typing")`` immediately, then re-sends it every ``typing_interval``
seconds from a background task (driven by the injected ``sleep``), and cancels that
task on exit (no leak). The finished reply is committed once via :meth:`reply`
(rich ``send_rich_message``, degrading to a plain ``send_message`` on a rich error).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import (
    PLAIN_TEXT_LIMIT,
    BotIdentitySignals,
    TelegramGateway,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from aiogram.types import InputRichMessage

    from bob.domain import ports

# --- Test doubles -------------------------------------------------------------


@dataclass
class _FakeEntity:
    type: str
    offset: int
    length: int
    user: _FakeUser | None = None


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None
    from_user: _FakeUser | None = None
    reply_to_message: _FakeMessage | None = None
    entities: list[_FakeEntity] | None = None


@dataclass
class _FakeUser:
    id: int
    full_name: str = ""
    username: str | None = None


@dataclass
class _FakeChat:
    id: int


@dataclass
class _FakeUpdate:
    update_id: int
    message: _FakeMessage | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None


def _update(
    update_id: int,
    *,
    chat_id: int = 100,
    text: str | None = "hello",
    message_id: int = 1,
    user: _FakeUser | None = None,
    reply_to_message: _FakeMessage | None = None,
    entities: list[_FakeEntity] | None = None,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(
            message_id=message_id,
            text=text,
            from_user=user,
            reply_to_message=reply_to_message,
            entities=entities,
        ),
        effective_chat=_FakeChat(id=chat_id),
        effective_user=user,
    )


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _TypingCall:
    chat_id: int
    action: str
    message_thread_id: int | None


@dataclass
class _RichCall:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _PhotoCall:
    chat_id: int
    data: bytes
    caption: str | None
    message_thread_id: int | None


@dataclass
class _DocumentCall:
    chat_id: int
    data: bytes
    filename: str
    caption: str | None
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Records send/typing/rich calls; can be scripted to fail the rich final."""

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    get_updates_calls: list[tuple[int, int]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    typings: list[_TypingCall] = field(default_factory=list)
    rich_sends: list[_RichCall] = field(default_factory=list)
    photo_sends: list[_PhotoCall] = field(default_factory=list)
    document_sends: list[_DocumentCall] = field(default_factory=list)
    next_message_id: int = 500
    rich_send_raises: bool = False
    photo_send_raises: bool = False
    document_send_raises: bool = False
    typing_raises: bool = False

    async def get_me(self) -> _FakeUser:
        return _FakeUser(id=4242, username="bob_companion_bot")

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[_FakeUpdate]:
        self.get_updates_calls.append((offset, timeout))
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
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        if self.typing_raises:
            raise ValueError("typing boom")
        self.typings.append(
            _TypingCall(
                chat_id=chat_id, action=action, message_thread_id=message_thread_id
            )
        )
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        if self.rich_send_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="rich rejected",
            )
        self.rich_sends.append(
            _RichCall(
                chat_id=chat_id,
                markdown=rich_message.markdown,
                message_thread_id=message_thread_id,
            )
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=rich_message.markdown)
        self.next_message_id += 1
        return msg

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        if self.photo_send_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="photo rejected",
            )
        self.photo_sends.append(
            _PhotoCall(
                chat_id=chat_id,
                data=getattr(photo, "data", b""),
                caption=caption,
                message_thread_id=message_thread_id,
            )
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=caption)
        self.next_message_id += 1
        return msg

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        if self.document_send_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="document rejected",
            )
        self.document_sends.append(
            _DocumentCall(
                chat_id=chat_id,
                data=getattr(document, "data", b""),
                filename=getattr(document, "filename", ""),
                caption=caption,
                message_thread_id=message_thread_id,
            )
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=caption)
        self.next_message_id += 1
        return msg


class _FakeClock:
    """Monotonic seconds source advanced explicitly (drives the typing cadence)."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _RecordingSleep:
    """Async sleep that records durations and advances the bound clock."""

    def __init__(self, clock: _FakeClock) -> None:
        self.clock = clock
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        self.clock.value += seconds


async def _tokens(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


def _make_gateway(bot: _FakeBot, **kwargs: Any) -> TelegramGateway:
    clock = kwargs.pop("clock", _FakeClock())
    sleep = kwargs.pop("sleep", _RecordingSleep(clock))
    bus = kwargs.pop("bus", AsyncEventBus())
    return TelegramGateway(
        bot=bot,
        bus=bus,
        poll_timeout=kwargs.pop("poll_timeout", 10),
        typing_interval=kwargs.pop("typing_interval", 4.0),
        clock=clock,
        sleep=sleep,
        reply_thread_id=kwargs.pop("reply_thread_id", None),
        bob_identity=kwargs.pop("bob_identity", None),
    )


# --- Intake / dedup -----------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_publishes_message_received() -> None:
    bus = AsyncEventBus()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(_FakeBot(), bus=bus)

    published = await gateway.intake(
        _update(10, chat_id=42, text="hi bob", message_id=7)
    )

    assert published is True
    assert len(received) == 1
    assert received[0].chat_id == 42
    assert received[0].text == "hi bob"
    assert received[0].update_id == 10


@pytest.mark.asyncio
async def test_intake_deduplicates_by_update_id() -> None:
    bus = AsyncEventBus()
    count = 0

    async def handler(event: ports.DomainEvent) -> None:
        nonlocal count
        count += 1

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(_FakeBot(), bus=bus)

    first = await gateway.intake(_update(10))
    second = await gateway.intake(_update(10))

    assert first is True
    assert second is False
    assert count == 1


@pytest.mark.asyncio
async def test_intake_ignores_update_without_text() -> None:
    gateway = _make_gateway(_FakeBot())
    published = await gateway.intake(_update(10, text=None))
    assert published is False


@pytest.mark.asyncio
async def test_intake_carries_sender_metadata() -> None:
    bus = AsyncEventBus()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(_FakeBot(), bus=bus)

    await gateway.intake(_update(10, user=_FakeUser(id=99, full_name="Alice")))

    assert received[0].sender_id == 99
    assert received[0].sender_name == "Alice"


# --- Addressivity signals (BOB-023) -------------------------------------------

_BOB_ID = 4242
_BOB_USERNAME = "bob_companion_bot"


def _bob_identity() -> BotIdentitySignals:
    return BotIdentitySignals(user_id=_BOB_ID, username=_BOB_USERNAME)


async def _capture(gateway: TelegramGateway, update: _FakeUpdate) -> MessageReceived:
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    gateway._bus.subscribe(MESSAGE_RECEIVED, handler)
    await gateway.intake(update)
    assert len(received) == 1
    return received[0]


@pytest.mark.asyncio
async def test_addressivity_defaults_when_no_reply_or_entities() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())

    event = await _capture(gateway, _update(10, text="just talking"))

    assert event.reply_to_sender_id is None
    assert event.mentions_bob is False


@pytest.mark.asyncio
async def test_reply_to_carries_replied_sender_id() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    replied = _FakeMessage(
        message_id=1, text="earlier", from_user=_FakeUser(id=_BOB_ID)
    )

    event = await _capture(
        gateway, _update(10, text="re", reply_to_message=replied)
    )

    assert event.reply_to_sender_id == _BOB_ID


@pytest.mark.asyncio
async def test_reply_to_another_user_carries_that_users_id() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    replied = _FakeMessage(message_id=1, text="earlier", from_user=_FakeUser(id=777))

    event = await _capture(
        gateway, _update(10, text="re", reply_to_message=replied)
    )

    assert event.reply_to_sender_id == 777
    assert event.mentions_bob is False


@pytest.mark.asyncio
async def test_reply_to_topic_root_is_not_a_real_reply() -> None:
    # BOB-027: in a forum topic every message implicitly "replies" to the topic root
    # (reply_to_message.message_id == message_thread_id), created by the owner. That is
    # NOT a real reply, else addressivity reads the whole topic as directed-to-other.
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    topic_root = _FakeMessage(
        message_id=555, text="topic", from_user=_FakeUser(id=27468732)
    )
    update = _FakeUpdate(
        update_id=10,
        message=_FakeMessage(
            message_id=999,
            text="как настроение?",
            message_thread_id=555,
            from_user=_FakeUser(id=27468732),
            reply_to_message=topic_root,
        ),
        effective_chat=_FakeChat(id=100),
        effective_user=_FakeUser(id=27468732),
    )

    event = await _capture(gateway, update)

    assert event.reply_to_sender_id is None


@pytest.mark.asyncio
async def test_real_reply_in_a_topic_still_carries_sender() -> None:
    # A real reply to a DIFFERENT message in the topic (message_id != thread_id) is
    # genuine: its sender_id is preserved (the forum guard only drops the root).
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    replied = _FakeMessage(message_id=777, text="earlier", from_user=_FakeUser(id=42))
    update = _FakeUpdate(
        update_id=11,
        message=_FakeMessage(
            message_id=1000,
            text="re",
            message_thread_id=555,
            from_user=_FakeUser(id=27468732),
            reply_to_message=replied,
        ),
        effective_chat=_FakeChat(id=100),
        effective_user=_FakeUser(id=27468732),
    )

    event = await _capture(gateway, update)

    assert event.reply_to_sender_id == 42


@pytest.mark.asyncio
async def test_reply_to_without_from_user_yields_none() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    replied = _FakeMessage(message_id=1, text="anon", from_user=None)

    event = await _capture(
        gateway, _update(10, text="re", reply_to_message=replied)
    )

    assert event.reply_to_sender_id is None


@pytest.mark.asyncio
async def test_username_mention_of_bob_sets_mentions_bob() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    text = f"hey @{_BOB_USERNAME} look"
    entity = _FakeEntity(type="mention", offset=4, length=len(_BOB_USERNAME) + 1)

    event = await _capture(
        gateway, _update(10, text=text, entities=[entity])
    )

    assert event.mentions_bob is True


@pytest.mark.asyncio
async def test_username_mention_of_other_does_not_set_mentions_bob() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    text = "hey @someone_else look"
    entity = _FakeEntity(type="mention", offset=4, length=len("@someone_else"))

    event = await _capture(
        gateway, _update(10, text=text, entities=[entity])
    )

    assert event.mentions_bob is False


@pytest.mark.asyncio
async def test_text_mention_of_bob_sets_mentions_bob() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    entity = _FakeEntity(
        type="text_mention", offset=0, length=3, user=_FakeUser(id=_BOB_ID)
    )

    event = await _capture(gateway, _update(10, text="Bob hi", entities=[entity]))

    assert event.mentions_bob is True


@pytest.mark.asyncio
async def test_text_mention_of_other_does_not_set_mentions_bob() -> None:
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus, bob_identity=_bob_identity())
    entity = _FakeEntity(
        type="text_mention", offset=0, length=3, user=_FakeUser(id=999)
    )

    event = await _capture(gateway, _update(10, text="Ann hi", entities=[entity]))

    assert event.mentions_bob is False


@pytest.mark.asyncio
async def test_addressivity_signals_absent_without_bob_identity() -> None:
    # No bob_identity wired (e.g. the GUPPI inner gateway): mentions cannot be
    # resolved, so mentions_bob stays False, but reply-to is still carried.
    bus = AsyncEventBus()
    gateway = _make_gateway(_FakeBot(), bus=bus)
    text = f"hey @{_BOB_USERNAME}"
    entity = _FakeEntity(type="mention", offset=4, length=len(_BOB_USERNAME) + 1)
    replied = _FakeMessage(message_id=1, text="x", from_user=_FakeUser(id=5))

    event = await _capture(
        gateway,
        _update(10, text=text, entities=[entity], reply_to_message=replied),
    )

    assert event.mentions_bob is False
    assert event.reply_to_sender_id == 5


@pytest.mark.asyncio
async def test_poll_once_consumes_batch_and_advances_offset() -> None:
    bot = _FakeBot(updates_batches=[[_update(10), _update(11)]])
    bus = AsyncEventBus()
    seen: list[int] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        seen.append(event.update_id)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(bot, bus=bus)

    published = await gateway.poll_once()

    assert published == 2
    assert seen == [10, 11]
    # Next poll uses offset = last_update_id + 1; an empty batch is a no-op.
    assert await gateway.poll_once() == 0


@pytest.mark.asyncio
async def test_poll_once_dedup_persists_across_polls() -> None:
    bot = _FakeBot(updates_batches=[[_update(10)], [_update(10)]])
    gateway = _make_gateway(bot)

    first = await gateway.poll_once()
    second = await gateway.poll_once()

    assert first == 1
    assert second == 0


# --- Typing keepalive: indicator concurrent with the (slow) generation --------


class _GatedSleep:
    """Async sleep whose every call blocks until the test releases one tick.

    Lets a test step the keepalive loop deterministically: each ``sleep(interval)``
    parks on an event the test fires with :meth:`tick`, modelling the passage of one
    ``typing_interval`` of real generation time without any wall-clock wait.
    """

    def __init__(self) -> None:
        self.durations: list[float] = []
        self._gate = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        self._gate.clear()
        await self._gate.wait()

    def tick(self) -> None:
        self._gate.set()


@pytest.mark.asyncio
async def test_typing_indicator_fires_immediately_on_enter() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, reply_thread_id=37, sleep=_GatedSleep())

    async with gateway.typing_indicator(chat_id=42):
        # The up-front "Bob is typing…" must appear at once, before any wait.
        await asyncio.sleep(0)
        assert bot.typings, "typing did not fire immediately on enter"

    assert all(t.action == "typing" for t in bot.typings)
    assert all(t.message_thread_id == 37 for t in bot.typings)


@pytest.mark.asyncio
async def test_typing_indicator_repeats_on_interval_during_slow_generation() -> None:
    bot = _FakeBot()
    sleep = _GatedSleep()
    gateway = _make_gateway(bot, sleep=sleep, typing_interval=4.0)

    async with gateway.typing_indicator(chat_id=7):
        await asyncio.sleep(0)  # let the up-front action + first sleep happen
        before = len(bot.typings)
        sleep.tick()  # one interval of generation elapses
        await asyncio.sleep(0)
        sleep.tick()  # a second interval
        await asyncio.sleep(0)

    # Re-sent on each elapsed interval, always on the keepalive's interval cadence.
    assert len(bot.typings) > before
    assert sleep.durations
    assert all(d == 4.0 for d in sleep.durations)


@pytest.mark.asyncio
async def test_typing_indicator_cancels_keepalive_on_exit() -> None:
    bot = _FakeBot()
    sleep = _GatedSleep()
    gateway = _make_gateway(bot, sleep=sleep)

    async with gateway.typing_indicator(chat_id=7):
        await asyncio.sleep(0)
    sent_at_exit = len(bot.typings)

    # No leaked task and no further typing after the context closed.
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert pending == [], "the keepalive task leaked past the context"
    sleep.tick()  # would re-type if the loop were still alive
    await asyncio.sleep(0)
    assert len(bot.typings) == sent_at_exit


@pytest.mark.asyncio
async def test_typing_indicator_failure_does_not_break_the_turn() -> None:
    # A failing sendChatAction is swallowed: entering/exiting the context must not
    # raise, so the surrounding generation + reply still go through.
    bot = _FakeBot(typing_raises=True)
    gateway = _make_gateway(bot, sleep=_GatedSleep())

    async with gateway.typing_indicator(chat_id=7):
        await asyncio.sleep(0)
    await gateway.reply(chat_id=7, markdown="still here")

    assert len(bot.rich_sends) == 1
    assert bot.rich_sends[0].markdown == "still here"


# --- Rich reply: send_rich_message + thinking + plain fallback ----------------


@pytest.mark.asyncio
async def test_reply_rich_sends_rich_message() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    await gateway.reply(chat_id=7, markdown="a **bold** word")

    assert len(bot.rich_sends) == 1
    assert bot.rich_sends[0].chat_id == 7
    assert bot.rich_sends[0].markdown == "a **bold** word"
    assert bot.sends == []


@pytest.mark.asyncio
async def test_reply_rich_renders_thinking_block() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    await gateway.reply(chat_id=7, markdown="the answer", thinking="be brief")

    assert len(bot.rich_sends) == 1
    sent = bot.rich_sends[0].markdown
    assert sent is not None
    assert "be brief" in sent
    assert sent.strip().endswith("the answer")


@pytest.mark.asyncio
async def test_reply_falls_back_to_plain_on_rich_error() -> None:
    bot = _FakeBot(rich_send_raises=True)
    gateway = _make_gateway(bot)

    await gateway.reply(chat_id=7, markdown="hello **world**")

    assert bot.rich_sends == []
    assert len(bot.sends) == 1
    assert bot.sends[0].chat_id == 7
    assert bot.sends[0].text == "hello **world**"


@pytest.mark.asyncio
async def test_reply_plain_fallback_splits_on_length_limit() -> None:
    bot = _FakeBot(rich_send_raises=True)
    gateway = _make_gateway(bot)
    long_text = "x" * (PLAIN_TEXT_LIMIT + 50)

    await gateway.reply(chat_id=7, markdown=long_text)

    assert len(bot.sends) == 2
    assert all(len(s.text) <= PLAIN_TEXT_LIMIT for s in bot.sends)
    assert "".join(s.text for s in bot.sends) == long_text


@pytest.mark.asyncio
async def test_reply_empty_markdown_without_thinking_sends_nothing() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    result = await gateway.reply(chat_id=7, markdown="   ")

    assert bot.rich_sends == []
    assert bot.sends == []
    assert result is None


@pytest.mark.asyncio
async def test_reply_returns_sent_rich_message_id() -> None:
    # BOB-050: reply returns the Telegram message_id of Bob's outgoing message so
    # the caller can record which message was Bob's reply.
    bot = _FakeBot(next_message_id=900)
    gateway = _make_gateway(bot)

    message_id = await gateway.reply(chat_id=7, markdown="hi")

    assert message_id == 900


@pytest.mark.asyncio
async def test_reply_returns_first_chunk_id_on_plain_fallback() -> None:
    bot = _FakeBot(next_message_id=900, rich_send_raises=True)
    gateway = _make_gateway(bot)
    long_text = "x" * (PLAIN_TEXT_LIMIT + 50)

    message_id = await gateway.reply(chat_id=7, markdown=long_text)

    # The first plain chunk's id (the message a reaction would land on).
    assert message_id == 900


# --- BOB-035: send_photo (render_diagram PNG into the chat) --------------------


@pytest.mark.asyncio
async def test_send_photo_posts_the_png_pinned_to_the_thread() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, reply_thread_id=37)

    await gateway.send_photo(chat_id=9, photo=b"PNGBYTES", caption="вот")

    assert len(bot.photo_sends) == 1
    call = bot.photo_sends[0]
    assert call.chat_id == 9
    assert call.data == b"PNGBYTES"
    assert call.caption == "вот"
    assert call.message_thread_id == 37


@pytest.mark.asyncio
async def test_send_photo_swallows_a_transport_error() -> None:
    # A failed photo send is logged and swallowed — it never raises into the turn.
    bot = _FakeBot(photo_send_raises=True)
    gateway = _make_gateway(bot)

    await gateway.send_photo(chat_id=9, photo=b"PNGBYTES", caption="вот")

    assert bot.photo_sends == []


# --- BOB-037: send_document (uncompressed diagram, full resolution) ------------


@pytest.mark.asyncio
async def test_send_document_posts_the_png_uncompressed_pinned_to_the_thread() -> None:
    # BOB-037 C: send the PNG as an uncompressed FILE so Telegram does not recompress
    # it — full resolution, tap → real pixels.
    bot = _FakeBot()
    gateway = _make_gateway(bot, reply_thread_id=37)

    await gateway.send_document(chat_id=9, document=b"PNGBYTES", caption="вот")

    assert len(bot.document_sends) == 1
    call = bot.document_sends[0]
    assert call.chat_id == 9
    assert call.data == b"PNGBYTES"
    assert call.caption == "вот"
    assert call.message_thread_id == 37
    assert call.filename.endswith(".png")


@pytest.mark.asyncio
async def test_send_document_swallows_a_transport_error() -> None:
    # A failed document send is logged and swallowed — it never raises into the turn.
    bot = _FakeBot(document_send_raises=True)
    gateway = _make_gateway(bot)

    await gateway.send_document(chat_id=9, document=b"PNGBYTES", caption="вот")

    assert bot.document_sends == []
