# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary harness for the GUPPI-channel scenarios (BOB-087 Срез A).

Drives a REAL :class:`~bob.coding.usecases.coding_assistant.CodingAssistant` over the REAL
:class:`~bob.coding.adapters.owner_notifier._CodingOwnerNotifier` transport adapter, but with
TWO fake bots — one for Bob, one for GUPPI — recording exactly which bot carried which line.
Everything else (runner / worktree / store / PR-opener / owner / clock) is a deterministic
in-memory fake, so a whole plan→approve→PR session runs without a subprocess.

The single knob a scenario flips is the firehose routing, mirroring the composition root
(:func:`~bob.runtime.wiring.coding._build_coding_assistant`): when the ``stream_via_guppi``
flag is ON the firehose ``stream_notifier`` is a DISTINCT notifier over GUPPI's bot; OFF (the
default) it is ``None`` so the use-case falls back to Bob's notifier — byte-identical to today.
Assertions read only the two bots' recorded sends (a real transport boundary), never private
use-case state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.coding.state import is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from aiogram.types import InputRichMessage

    from bob.coding.entities import CodingSession
    from bob.infrastructure.telegram.gateway import MessageLike

OWNER_ID = 27468732
CHAT_ID = -1004372947307
BOB_TOPIC_ID = 77
PR_URL = "https://github.com/x/bob/pull/7"

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


@dataclass
class RecordingBot:
    """A fake bot recording every line it was asked to send (its bot identity's channel).

    Implements the narrow ``MarkdownSendBot`` surface the coding owner-notifier drives; the
    rich path always succeeds here, so ``sent`` captures the messages this identity carried.
    """

    sent: list[str] = field(default_factory=list)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike:  # pragma: no cover - plain fallback not exercised (rich succeeds)
        self.sent.append(text)
        return _FakeMessage(text=text)

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        markdown = rich_message.markdown or ""
        self.sent.append(markdown)
        return _FakeMessage(text=markdown)

    def carried(self, needle: str) -> bool:
        """Whether any recorded line on this bot's channel contains ``needle``."""
        return any(needle in line for line in self.sent)


@dataclass
class _FakeMessage:
    text: str | None = None
    message_id: int = 0
    message_thread_id: int | None = None


@dataclass
class _FakeRunner:
    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        for event in self.events.get(mode, []):
            yield event


@dataclass
class _FakeWorktree:
    committed: bool = True

    async def create(self, branch: str) -> str:
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        return self.committed

    async def remove(self, path: str) -> None:
        return None


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
class _FakePROpener:
    url: str = PR_URL

    async def open(self, branch: str, title: str, body: str) -> str:
        return self.url


@dataclass
class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == OWNER_ID


@dataclass
class _FakeClock:
    def now(self) -> datetime:
        return _NOW


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"cs-{counter['n']}"

    return _factory


def _edit(path: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}]
        },
    }


def execute_events(n_edits: int = 2) -> list[Mapping[str, object]]:
    """A scripted execute run: ``n_edits`` file edits + the final success result."""
    events: list[Mapping[str, object]] = [_edit(f"f{i}.py") for i in range(n_edits)]
    events.append({"type": "result", "subtype": "success"})
    return events


def _notifier(bot: RecordingBot) -> _CodingOwnerNotifier:
    return _CodingOwnerNotifier(bot=bot, chat_id=CHAT_ID, topic_id=BOB_TOPIC_ID)


def build_assistant(
    *,
    bob_bot: RecordingBot,
    guppi_bot: RecordingBot,
    stream_via_guppi: bool,
    execute: list[Mapping[str, object]] | None = None,
) -> CodingAssistant:
    """Assemble the assistant over the two-bot boundary, mirroring the composition root.

    ``stream_via_guppi`` ON → a DISTINCT firehose notifier over GUPPI's bot; OFF → ``None``
    so the firehose falls back to Bob's notifier (byte-identical). Bob's own voice always
    goes through the Bob notifier regardless.
    """
    runner = _FakeRunner(
        events={
            "plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}],
            "acceptEdits": execute if execute is not None else execute_events(),
        }
    )
    return CodingAssistant(
        runner=runner,
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=_notifier(bob_bot),
        stream_notifier=_notifier(guppi_bot) if stream_via_guppi else None,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
    )
