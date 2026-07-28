# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the BOB-062.6b wave-1 leaf collaborators.

These pin the two SUBTLE 🔴 invariants at the collaborator level (the full handle()
suite covers behaviour end to end): the diagram sink is the SAME injected instance
(push and drain act on one object), and the verify note is a PER-TURN LOCAL never
cached on the collaborator (a shared singleton must not leak it across turns/users).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.application.usecases.essential_runner import (
    EssentialRunner,
    _EssentialStepError,
)
from bob.capabilities.ports import DiagramResult, WebSearchResult
from bob.capabilities.usecases.diagram_sender import DiagramSender
from bob.conversation.addressivity import Addressivity
from bob.conversation.conversation_floor import FloorConfig
from bob.conversation.usecases.floor_manager import FloorManager
from bob.conversation.usecases.verify_step import (
    _VERIFY_GROUNDED_NOTE,
    VerifyInterimAnnouncer,
    VerifyStep,
)
from bob.conversation.volatility_judgment import VolatilityContext, VolatilityVerdict


class _RecordingSink:
    """A minimal DiagramSink recording push/drain against ONE instance."""

    def __init__(self) -> None:
        self._items: list[DiagramResult] = []
        self.drained = 0

    def push(self, result: DiagramResult) -> None:
        self._items.append(result)

    def pending(self) -> tuple[DiagramResult, ...]:
        return tuple(self._items)

    def drain(self) -> tuple[DiagramResult, ...]:
        self.drained += 1
        out = tuple(self._items)
        self._items = []
        return out


class _CapturingGateway:
    def __init__(self) -> None:
        self.photos: list[tuple[int, bytes, str | None]] = []
        self.documents: list[tuple[int, bytes, str | None]] = []

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None:
        self.photos.append((chat_id, photo, caption))

    async def send_document(
        self, *, chat_id: int, document: bytes, caption: str | None = None
    ) -> None:
        self.documents.append((chat_id, document, caption))


async def test_diagram_sender_drains_the_same_injected_sink_instance() -> None:
    # 🔴 shared-instance diagram_sink: the sender drains the VERY sink it was given (the
    # same object the render_diagram capability pushes into) — never a fresh one.
    sink = _RecordingSink()
    sink.push(DiagramResult(png=b"PNG", caption="c", source="graph TD; A-->B"))
    gateway = _CapturingGateway()
    sender = DiagramSender(
        gateway=gateway, diagram_sink=sink, diagram_renderer=None
    )

    await sender.send_pending(chat_id=7)

    assert sink.drained == 1  # drained THIS instance
    assert gateway.documents == [(7, b"PNG", "c")]  # default send mode = document
    assert gateway.photos == []


class _FlakyOp:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        raise RuntimeError("boom")


async def test_essential_runner_wraps_persistent_failure() -> None:
    # A step that keeps failing after the bounded retries surfaces as _EssentialStepError
    # (carrying the step label) so the turn can fall back to the honest GUPPI notice.
    async def _no_sleep(_seconds: float) -> None:
        return None

    op = _FlakyOp()
    runner = EssentialRunner(
        attempts=3,
        backoff_seconds=0.0,
        retry_sleep=_no_sleep,
        outage_notifier=None,
        persist=_unused_persist,
    )

    with pytest.raises(_EssentialStepError) as excinfo:
        await runner.run(op, step="reply generation")

    assert excinfo.value.step == "reply generation"
    assert op.calls == 3  # one initial + two retries


async def _unused_persist(event: object, marker: str, soul: object) -> None:
    raise AssertionError("persist not expected in this test")


class _FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 28, tzinfo=UTC)


async def test_floor_manager_is_inert_when_disabled() -> None:
    # Floor unwired/disabled → resolve_effective returns the per-message class unchanged
    # and advance is a clean no-op (BOB-023 behaviour), so a store is never touched.
    manager = FloorManager(
        floor_store=None,
        floor_config=FloorConfig(),
        floor_enabled=False,
        clock=_FrozenClock(),
    )

    effective = await manager.resolve_effective(
        chat_id=1, per_message=Addressivity.AMBIENT
    )

    assert effective is Addressivity.AMBIENT
    # No store wired → advance simply returns without raising.
    await manager.advance_after_turn(
        chat_id=1,
        sender_id=2,
        per_message=Addressivity.AMBIENT,
        directed_to_id=None,
        bob_replied=True,
    )


class _FakeJudge:
    def __init__(self, verdict: VolatilityVerdict) -> None:
        self._verdict = verdict
        self.calls = 0
        self.contexts: list[VolatilityContext] = []

    async def assess(self, ctx: VolatilityContext) -> VolatilityVerdict:
        self.contexts.append(ctx)
        self.calls += 1
        return self._verdict


class _FakeProvider:
    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.queries: list[str] = []

    async def search(self, query: str) -> WebSearchResult:
        self.queries.append(query)
        return WebSearchResult(answer=self._answer)


def _null_announcer_factory(
    *, chat_id: int, sender_name: str
) -> VerifyInterimAnnouncer:
    raise AssertionError("no interim expected without chat_id")


async def test_verify_note_is_turn_local_not_cached_on_collaborator() -> None:
    # 🔴 verify-once-per-turn: note() RETURNS the note (a per-turn local); it is never an
    # attribute of VerifyStep. Two calls each judge + search afresh — no cross-turn cache.
    judge = _FakeJudge(
        VolatilityVerdict(needs_check=True, query="q", topic="rate")
    )
    provider = _FakeProvider(answer="16%")
    step = VerifyStep(
        verify_judge=judge,
        verify_provider=provider,
        verify_timeout_seconds=1.0,
        announcer_factory=_null_announcer_factory,
    )

    note_a = await step.note("what is the rate?", [])
    note_b = await step.note("and now?", [])

    assert note_a == _VERIFY_GROUNDED_NOTE.format(answer="16%")
    assert note_a == note_b  # same shape, but recomputed — not a stored attribute
    assert judge.calls == 2, "each turn judges afresh (no cross-turn cache)"
    assert provider.queries == ["q", "q"], "one search per turn"
    assert not hasattr(step, "_note"), "the note is a turn-local, never an attribute"
