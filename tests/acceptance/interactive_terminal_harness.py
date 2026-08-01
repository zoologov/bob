# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Harness for the interactive-terminal acceptance scenarios (BOB-083 S0–S5).

Wires the REAL interactive stack — :class:`InteractiveClaudeRunner` (over a fake
bidirectional process, never the real ``claude``) → :class:`InteractiveSessionManager`
(real worktree/streamer boundaries faked) → :class:`InteractiveIntakeRouter` (the real
owner-DM entry/steer/exit gate) — and drives owner-DM turns through the router the way
HandleMessage does. Every assertion is on OBSERVABLE behaviour through a boundary:

* what the router CONSUMED (interactive turn) vs left for the normal Bob path;
* what text reached the fake process's STDIN (steer → ``claude``), decoded from the
  stream-json frame the runner actually wrote — so :func:`encode_user_message` is
  exercised end-to-end, not stubbed;
* whether the process was TERMINATED (kill-switch) and the worktree torn down;
* the rendered output lines that reached the owner's DM (live stream);
* 🔴 that the manager NEVER commits/pushes/opens a PR (``pushes`` stays empty — INV-2).

The foundation route (S0) is asserted through the REAL :class:`MultiBotGateway`: an owner
DM reaches Bob's pipeline and his reply targets the DM, while a stranger DM is dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.coding.adapters.interactive_runner import InteractiveClaudeRunner
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.coding_assistant import CodingOutcome
from bob.coding.usecases.interactive_intake import InteractiveIntakeRouter
from bob.coding.usecases.interactive_session import InteractiveSessionManager
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)
from bob.runtime.wiring.coding import _build_interactive_intake

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from aiogram.types import InputRichMessage

    from bob.coding.entities import CodingSession
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel import ports

_OWNER_ID = 27468732
_GUEST_ID = 555
_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

# A tiny canned claude output: one assistant line + a success result. Rendered by the
# reused BOB-082 stream renderer into DM lines, so "output streams to the DM" is observable.
_CANNED_OUTPUT: tuple[Mapping[str, object], ...] = (
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "смотрю код"}]}},
    {"type": "result", "subtype": "success", "result": "готово"},
)


# --------------------------------------------------------------------------- #
# Fake bidirectional process + spawner (the subprocess boundary)
# --------------------------------------------------------------------------- #


class _FakeProcess:
    """A scripted bidirectional process: records fed bytes, terminate, kill.

    ``read_lines`` yields the canned NDJSON lines then stays open (like a real long-lived
    ``claude``) until ``terminate``/``kill`` — so the manager's background output pump is
    live between steer replies and only ends when the kill-switch fires.
    """

    def __init__(self, lines: Sequence[str]) -> None:
        self.fed: list[bytes] = []
        self.terminated = 0
        self.killed = 0
        self._lines = list(lines)
        self._alive = True
        self._closed = asyncio.Event()
        self.drained = asyncio.Event()

    async def feed(self, data: bytes) -> None:
        self.fed.append(data)

    async def read_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line
        self.drained.set()
        await self._closed.wait()  # a real process keeps stdout open until it dies

    def terminate(self) -> None:
        self.terminated += 1
        self._alive = False
        self._closed.set()

    def kill(self) -> None:
        self.killed += 1
        self._alive = False
        self._closed.set()

    async def wait(self, *, timeout: float | None = None) -> bool:
        return not self._alive

    @property
    def alive(self) -> bool:
        return self._alive


class _FakeSpawner:
    """Spawns a fresh fake process per ``open`` (records argv / cwd)."""

    def __init__(self, lines: Sequence[Mapping[str, object]]) -> None:
        self._lines = [json.dumps(event, ensure_ascii=False) + "\n" for event in lines]
        self.processes: list[_FakeProcess] = []
        self.argvs: list[list[str]] = []

    async def __call__(self, argv: list[str], *, cwd: str) -> _FakeProcess:
        self.argvs.append(list(argv))
        proc = _FakeProcess(self._lines)
        self.processes.append(proc)
        return proc


# --------------------------------------------------------------------------- #
# Fake session boundaries (worktree / store / notifiers / owner / clock)
# --------------------------------------------------------------------------- #


@dataclass
class _FakeWorktree:
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pushes: list[tuple[str, str, str]] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        slug = branch.split("/", 1)[1]
        return f"/wt/{slug}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        self.pushes.append((path, branch, message))  # 🔴 must NEVER be called (INV-2)
        return True

    async def remove(self, path: str) -> None:
        self.removed.append(path)


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))


@dataclass
class _RecordingNotifier:
    """Records the lines sent to the owner's DM (live output OR mode lines)."""

    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


@dataclass
class _FakeClock:
    moment: datetime = _NOW

    def now(self) -> datetime:
        return self.moment


def _ids() -> object:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"is-{counter['n']}"

    return _factory


# --------------------------------------------------------------------------- #
# Observations + the interactive-stack rig
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class InteractiveObservations:
    """What the interactive stack did, seen only through its boundaries."""

    consumed: list[bool] = field(default_factory=list)
    fed_texts: list[str] = field(default_factory=list)
    terminated: int = 0
    killed: int = 0
    worktree_created: list[str] = field(default_factory=list)
    worktree_removed: list[str] = field(default_factory=list)
    dm_output_lines: list[str] = field(default_factory=list)
    mode_lines: list[str] = field(default_factory=list)
    pushes: list[tuple[str, str, str]] = field(default_factory=list)
    spawned: int = 0
    active_after: bool = False


def _decode_stdin_frame(raw: bytes) -> str:
    """Decode ``text`` back out of the stream-json ``user`` frame written to stdin."""
    frame = json.loads(raw.decode("utf-8").rstrip("\n"))
    content = frame["message"]["content"]
    text = content[0]["text"]
    assert isinstance(text, str)
    return text


@dataclass
class _Rig:
    router: InteractiveIntakeRouter
    manager: InteractiveSessionManager
    spawner: _FakeSpawner
    worktree: _FakeWorktree
    store: _FakeStore
    stream_notifier: _RecordingNotifier
    mode_notifier: _RecordingNotifier


def _build_rig(*, canned: Sequence[Mapping[str, object]] = _CANNED_OUTPUT) -> _Rig:
    spawner = _FakeSpawner(canned)
    worktree = _FakeWorktree()
    store = _FakeStore()
    stream_notifier = _RecordingNotifier()
    mode_notifier = _RecordingNotifier()
    manager = InteractiveSessionManager(
        runner_factory=lambda: InteractiveClaudeRunner(spawner=spawner),
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=stream_notifier),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),  # type: ignore[arg-type]
        permission_mode="acceptEdits",
    )
    router = InteractiveIntakeRouter(manager=manager, notifier=mode_notifier)
    return _Rig(
        router, manager, spawner, worktree, store, stream_notifier, mode_notifier
    )


@dataclass(slots=True)
class Turn:
    """One owner/guest DM turn fed to the interactive intake router."""

    text: str
    is_owner: bool = True
    is_group: bool = False
    sender: int | None = _OWNER_ID


async def _await_first_drain(rig: _Rig) -> None:
    """Let the background output pump consume the canned events before we assert."""
    if rig.spawner.processes:
        # Defensive timeout; the canned output is finite so this always drains promptly.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(rig.spawner.processes[0].drained.wait(), timeout=1.0)


async def run_interactive(turns: Sequence[Turn]) -> InteractiveObservations:
    """Drive ``turns`` through the real interactive stack; return the observations."""
    rig = _build_rig()
    obs = InteractiveObservations()
    for turn in turns:
        consumed = await rig.router.route(
            text=turn.text,
            sender=turn.sender,
            is_owner=turn.is_owner,
            is_group=turn.is_group,
        )
        obs.consumed.append(consumed)
        await _await_first_drain(rig)

    # Ensure no live session leaks past the scenario (kill-switch backstop for teardown).
    if rig.manager.active():
        await rig.manager.stop(_OWNER_ID)

    obs.active_after = rig.manager.active()
    obs.spawned = len(rig.spawner.processes)
    if rig.spawner.processes:
        proc = rig.spawner.processes[0]
        obs.fed_texts = [_decode_stdin_frame(raw) for raw in proc.fed]
        obs.terminated = proc.terminated
        obs.killed = proc.killed
    obs.worktree_created = list(rig.worktree.created)
    obs.worktree_removed = list(rig.worktree.removed)
    obs.pushes = list(rig.worktree.pushes)
    obs.dm_output_lines = list(rig.stream_notifier.sent)
    obs.mode_lines = list(rig.mode_notifier.sent)
    return obs


# --- scenario builders (mirror the .feature Given phrasing) ------------------


def owner_opens_interactive() -> list[Turn]:
    return [Turn(text="/code -i fix the bug")]


def owner_opens_then_steers() -> list[Turn]:
    return [Turn(text="/code -i fix the bug"), Turn(text="теперь добавь тест")]


def owner_opens_then_stops_then_talks() -> list[Turn]:
    return [
        Turn(text="/code -i fix the bug"),
        Turn(text="stop"),
        Turn(text="привет, как дела"),  # after stop → normal Bob path (mode doesn't stick)
    ]


def guest_tries_to_open() -> list[Turn]:
    return [Turn(text="/code -i почини баг", is_owner=False, sender=_GUEST_ID)]


def owner_tries_to_open_in_group() -> list[Turn]:
    return [Turn(text="/code -i почини баг", is_group=True)]


def owner_opens_feeds_stops() -> list[Turn]:
    return [
        Turn(text="/code -i fix the bug"),
        Turn(text="правь дальше"),
        Turn(text="stop"),
    ]


# --------------------------------------------------------------------------- #
# S0 — foundation: owner DM reaches Bob, reply targets DM, stranger dropped
# --------------------------------------------------------------------------- #

_GROUP_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_DM_CHAT_ID = _OWNER_ID  # a 1:1 DM chat.id equals the user's id


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _FakeUser:
    id: int
    full_name: str = "Owner"


@dataclass
class _FakeChat:
    id: int
    type: str = "supergroup"


@dataclass
class _FakeUpdate:
    update_id: int
    message: _FakeMessage | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str | None
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Minimal BotLike: records sends, no network."""

    sends: list[_SendCall] = field(default_factory=list)
    next_message_id: int = 900

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[_FakeUpdate]:  # pragma: no cover - poll loop not driven here
        return []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=text)
        self.next_message_id += 1
        return msg

    async def send_chat_action(
        self,
        *,
        chat_id: int,
        action: str,
        message_thread_id: int | None = None,
    ) -> bool:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=None, message_thread_id=message_thread_id)
        )
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(
                chat_id=chat_id,
                text=rich_message.markdown,
                message_thread_id=message_thread_id,
            )
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=rich_message.markdown)
        self.next_message_id += 1
        return msg

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: object,
        message_thread_id: int | None = None,
    ) -> bool:  # pragma: no cover - not exercised here
        return True

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - not exercised here
        raise NotImplementedError


@dataclass
class _DmAuthorizer:
    """Owner is authorized in his own DM (and Bob's group); strangers are not."""

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(self, *, user_id: int | None, chat_id: int) -> bool:
        if user_id == _OWNER_ID and chat_id == _OWNER_DM_CHAT_ID:
            return True
        return user_id == _OWNER_ID and chat_id == _GROUP_CHAT_ID

    async def authorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError


def _build_multibot() -> tuple[MultiBotGateway, AsyncEventBus, _FakeBot, _FakeBot]:
    bus = AsyncEventBus()
    registry = BotRegistry()
    bob, guppi = _FakeBot(), _FakeBot()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bob,
        scope=BotScope(chat_id=_GROUP_CHAT_ID, topic_id=_BOB_TOPIC_ID),
    )
    registry.register(
        identity=BotIdentity.GUPPI,
        bot=guppi,
        scope=BotScope(chat_id=_GROUP_CHAT_ID, topic_id=None),
    )
    gateway = MultiBotGateway(
        registry=registry,
        bus=bus,
        poll_timeout=10,
        authorizer=_DmAuthorizer(),
        owner_dm_chat_id=_OWNER_DM_CHAT_ID,
    )
    return gateway, bus, bob, guppi


def _owner_dm_update(
    update_id: int,
    *,
    text: str = "привет, Боб",
    chat_id: int = _OWNER_DM_CHAT_ID,
    user_id: int = _OWNER_ID,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(message_id=80, text=text, message_thread_id=None),
        effective_chat=_FakeChat(id=chat_id, type="private"),
        effective_user=_FakeUser(id=user_id),
    )


@dataclass(slots=True)
class DmRouteObservations:
    """What the multibot router did with a DM, seen through the boundary."""

    published: bool = False
    received_texts: list[str] = field(default_factory=list)
    received_is_group: list[bool] = field(default_factory=list)
    reply_chat_ids: list[int] = field(default_factory=list)
    reply_threads: list[int | None] = field(default_factory=list)


async def run_owner_dm() -> DmRouteObservations:
    """Route an owner DM through the real gateway and send a reply; observe both."""
    gateway, bus, bob, _guppi = _build_multibot()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)

    published = await gateway.route(_owner_dm_update(100), BotIdentity.BOB)

    reply_gateway = gateway.reply_gateway(BotIdentity.BOB)
    await reply_gateway.reply(chat_id=_OWNER_DM_CHAT_ID, markdown="готово")

    return DmRouteObservations(
        published=published,
        received_texts=[event.text for event in received],
        received_is_group=[event.is_group for event in received],
        reply_chat_ids=[call.chat_id for call in bob.sends],
        reply_threads=[call.message_thread_id for call in bob.sends],
    )


async def run_stranger_dm() -> DmRouteObservations:
    """A stranger's DM (foreign chat, non-owner) must be dropped (never published)."""
    gateway, bus, bob, _guppi = _build_multibot()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:  # pragma: no cover - never fires
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)

    published = await gateway.route(
        _owner_dm_update(101, chat_id=_GUEST_ID, user_id=_GUEST_ID),
        BotIdentity.BOB,
    )

    return DmRouteObservations(
        published=published,
        received_texts=[event.text for event in received],
        reply_chat_ids=[call.chat_id for call in bob.sends],
    )


# --------------------------------------------------------------------------- #
# S5 — flag OFF: the interactive mode is entirely unavailable (wiring boundary)
# --------------------------------------------------------------------------- #


def interactive_router_when_flag_off() -> object | None:
    """The intake router the wiring assembles when ``coder.interactive`` is off.

    Off → the session manager is not built → the intake router is ``None`` → the mode is
    entirely unavailable (no entry, the consume-gate never fires). Observed through the
    real wiring boundary rather than any private flag.
    """
    # manager=None short-circuits before ``bot`` is touched; a cast placeholder keeps the
    # types honest without wiring a real bot for the flag-off path.
    return _build_interactive_intake(
        {"coder": {"interactive": False}},
        manager=None,
        bot=cast("BotLike", None),
        owner_id=_OWNER_ID,
    )


# Re-export the outcome type so steps can reference it if needed.
__all__ = [
    "CodingOutcome",
    "CodingSessionState",
    "DmRouteObservations",
    "InteractiveObservations",
    "Turn",
    "guest_tries_to_open",
    "interactive_router_when_flag_off",
    "owner_opens_feeds_stops",
    "owner_opens_interactive",
    "owner_opens_then_steers",
    "owner_opens_then_stops_then_talks",
    "owner_tries_to_open_in_group",
    "run_interactive",
    "run_owner_dm",
    "run_stranger_dm",
]
