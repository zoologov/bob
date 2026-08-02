# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Gap-fill for the channel split: Bob's gate voice never leaks to the firehose (BOB-087.A2).

A1 proved the happy path (firehose → the ``stream_notifier``, the accepted/PR gate lines →
the ``notifier``). These fill the edges A1 left open — the routing guarantee must hold on the
DM-pointer, stop, failure and no-changes paths too:

* the DM group pointer is Bob's OWN voice → it stays on ``notifier`` even when a DISTINCT
  ``stream_notifier`` (GUPPI's channel) is wired for the live stream;
* the kill-switch, the honest failure and the no-changes gate lines are Bob's voice → they
  land on ``notifier`` and NEVER on the firehose ``stream_notifier`` — while a no-changes run's
  mechanical result narration still goes to the firehose channel (the split holds both ways).

Uses two recording notifiers (Bob vs GUPPI) as the observed boundary — never private state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding import session_voice
from bob.coding.state import is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_PR_URL = "https://github.com/x/bob/pull/7"


@dataclass
class _FakeRunner:
    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)
    raise_on: str | None = None

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        if self.raise_on == mode:
            raise RuntimeError("runner boom")
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
    url: str = _PR_URL

    async def open(self, branch: str, title: str, body: str) -> str:
        return self.url


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _FakeLiveStreamer:
    """Records the events it was handed — stands in for the wired DM live-streamer."""

    seen: list[Mapping[str, object]] = field(default_factory=list)

    async def stream(
        self,
        events: AsyncIterator[Mapping[str, object]],
        *,
        is_cancelled: Callable[[], bool],
    ) -> None:
        async for event in events:
            self.seen.append(event)


@dataclass
class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


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


def _plan_events() -> dict[str, list[Mapping[str, object]]]:
    return {"plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}]}


def _edit(path: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}]
        },
    }


def _execute_events(n: int = 2) -> list[Mapping[str, object]]:
    edits: list[Mapping[str, object]] = [_edit(f"f{i}.py") for i in range(n)]
    edits.append({"type": "result", "subtype": "success"})
    return edits


def _build(
    *,
    bob: _FakeNotifier,
    guppi: _FakeNotifier,
    execute: list[Mapping[str, object]] | None = None,
    committed: bool = True,
    raise_on: str | None = None,
    live_streamer: _FakeLiveStreamer | None = None,
) -> CodingAssistant:
    acceptedits = execute if execute is not None else _execute_events()
    runner = _FakeRunner(
        events={**_plan_events(), "acceptEdits": acceptedits},
        raise_on=raise_on,
    )
    return CodingAssistant(
        runner=runner,
        worktree=_FakeWorktree(committed=committed),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=bob,
        stream_notifier=guppi,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        live_streamer=live_streamer,
    )


@pytest.mark.asyncio
async def test_dm_group_pointer_is_bob_voice_not_the_firehose_channel() -> None:
    # dev_dm wired: the raw stream is handed to the live-streamer (GUPPI's channel in wiring),
    # but the group pointer is Bob's OWN voice → it stays on Bob's notifier, not GUPPI's.
    bob, guppi = _FakeNotifier(), _FakeNotifier()
    streamer = _FakeLiveStreamer()
    assistant = _build(bob=bob, guppi=guppi, live_streamer=streamer)

    await assistant.start("Починить парсер", _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    assert session_voice.dev_pointer() in bob.sent
    assert session_voice.dev_pointer() not in guppi.sent
    # The raw firehose was delegated to the live-streamer, NOT narrated onto Bob's channel.
    assert streamer.seen  # the streamer received the run's events
    assert not any("GUPPI: правлю" in t for t in bob.sent)


@pytest.mark.asyncio
async def test_stop_kill_switch_voice_stays_on_bob_channel() -> None:
    # The stop gate line is Bob's voice → Bob's notifier; the firehose channel stays silent.
    bob, guppi = _FakeNotifier(), _FakeNotifier()
    assistant = _build(bob=bob, guppi=guppi)

    await assistant.start("Починить парсер", _OWNER_ID)
    outcome = await assistant.stop(_OWNER_ID)

    assert outcome.ok is True
    assert session_voice.stopped() in bob.sent
    assert guppi.sent == []  # no run happened → the firehose channel carried nothing


@pytest.mark.asyncio
async def test_failure_gate_line_never_leaks_to_the_firehose_channel() -> None:
    # A runner fault is an honest FAILED in Bob's voice → Bob's notifier, never GUPPI's.
    bob, guppi = _FakeNotifier(), _FakeNotifier()
    assistant = _build(bob=bob, guppi=guppi, raise_on="acceptEdits")

    await assistant.start("Починить парсер", _OWNER_ID)
    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is False
    assert session_voice.failed("runner boom") in bob.sent
    assert session_voice.failed("runner boom") not in guppi.sent


@pytest.mark.asyncio
async def test_no_changes_voice_is_bob_but_firehose_still_goes_to_guppi() -> None:
    # No edits committed: the honest "no changes" line is Bob's voice (Bob's notifier), while
    # the mechanical result narration still went to the firehose channel — the split holds.
    bob, guppi = _FakeNotifier(), _FakeNotifier()
    assistant = _build(bob=bob, guppi=guppi, committed=False)

    await assistant.start("Починить парсер", _OWNER_ID)
    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is False
    assert session_voice.no_changes() in bob.sent
    assert session_voice.no_changes() not in guppi.sent
    # The per-event firehose (incl. the result narration) still landed on GUPPI's channel.
    assert any("GUPPI" in t for t in guppi.sent)
    assert not any("GUPPI: правлю" in t for t in bob.sent)


@pytest.mark.asyncio
async def test_stream_notifier_defaults_to_main_notifier_when_omitted() -> None:
    # OFF-path contract: omit the stream_notifier → the firehose falls back to the SAME
    # notifier, so a single-channel session carries both the firehose and Bob's voice.
    bob = _FakeNotifier()
    assistant = CodingAssistant(
        runner=_FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events()}),
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=bob,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
    )  # stream_notifier omitted

    await assistant.start("Починить парсер", _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    assert any("GUPPI: правлю" in t for t in bob.sent)  # firehose on the sole channel
    assert session_voice.accepted() in bob.sent  # Bob's voice on the same channel
    assert session_voice.pr(_PR_URL) in bob.sent
