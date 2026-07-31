# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 End-to-end NL-intent SAFETY acceptance — BOB-041 .4 (the security core).

The router unit tests (``test_coding_intent_router.py``) drive a ``_FakeCoder``; these
wire the REAL :class:`~bob.coding.usecases.coding_intent_router.CodingIntentRouter`
over the REAL :class:`~bob.coding.usecases.coding_assistant.CodingAssistant` (with
fake ports — no real claude / gh / git / LLM) so the FULL natural-language path is
proven against the gate, not just the router's policy.

🔴 The invariant pinned here: there is **NO natural-language path to ``EXECUTING``**
except an explicit ``approve_plan`` from ``PLAN_READY``. A misclassified chat at worst
PROPOSES a plan (plan-mode, NO edits); an ambiguous message while a plan waits does
nothing; a non-owner reaches nothing (owner-only is enforced in the router AND
re-checked in the use-case — defense in depth). Concretely, the runner is asked to run
in the EDIT mode (``acceptEdits``) ONLY after the owner naturally approves a waiting
plan, and never via a (mis)classified coding-intent message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant
from bob.coding.usecases.coding_intent_router import CodingIntentRouter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER = 27468732
_GUEST = 555
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
_DEV_TASK = "Боб, создай файл HELLO.md"
_CHAT = "как настроение?"


# --- Fake ports (no real claude / gh / git / LLM) --------------------------------


@dataclass
class _FakeRunner:
    """Async-generator runner: canned events per mode; records every (workdir, mode)."""

    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        self.calls.append((workdir, prompt, mode))
        for event in self.events.get(mode, []):
            yield event

    @property
    def modes(self) -> list[str]:
        """The ordered list of modes the runner was asked to run in."""
        return [mode for _, _, mode in self.calls]


@dataclass
class _FakeWorktree:
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pushes: list[tuple[str, str, str]] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        self.pushes.append((path, branch, message))
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
class _FakePROpener:
    url: str = "https://github.com/x/bob/pull/7"
    opens: list[tuple[str, str, str]] = field(default_factory=list)

    async def open(self, branch: str, title: str, body: str) -> str:
        self.opens.append((branch, title, body))
        return self.url


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _FakeOwner:
    """Only ``_OWNER`` is the owner — the use-case re-checks this (defense in depth)."""

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER


@dataclass
class _FakeClock:
    def now(self) -> datetime:
        return _NOW


class _FakeClassifier:
    """A deterministic coding/chat classifier; records the texts it is asked about."""

    def __init__(self, *, coding: bool) -> None:
        self._coding = coding
        self.seen: list[str] = []

    async def is_coding_request(self, text: str) -> bool:
        self.seen.append(text)
        return self._coding


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"cs-{counter['n']}"

    return _factory


def _plan_events() -> list[Mapping[str, object]]:
    return [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Шаг 1"}]}},
        {"type": "result", "subtype": "success", "result": "## План\n- Шаг 1"},
    ]


def _execute_events() -> list[Mapping[str, object]]:
    return [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "HELLO.md"}}
                ]
            },
        },
        {"type": "result", "subtype": "success"},
    ]


@dataclass
class _Rig:
    router: CodingIntentRouter
    assistant: CodingAssistant
    runner: _FakeRunner
    worktree: _FakeWorktree
    store: _FakeStore
    pr_opener: _FakePROpener
    notifier: _FakeNotifier
    classifier: _FakeClassifier


def _rig(*, coding: bool) -> _Rig:
    """Wire the REAL router over the REAL assistant with fake ports."""
    runner = _FakeRunner(events={"plan": _plan_events(), "acceptEdits": _execute_events()})
    worktree = _FakeWorktree()
    store = _FakeStore()
    pr_opener = _FakePROpener()
    notifier = _FakeNotifier()
    assistant = CodingAssistant(
        runner=runner,
        worktree=worktree,
        store=store,
        pr_opener=pr_opener,
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
    )
    classifier = _FakeClassifier(coding=coding)
    # These acceptance scenarios document the gated NL flow WITH auto-start enabled
    # (nl_autostart=True); the plan gate / owner-only / never-main invariants they assert
    # hold for that configuration. The safe DEFAULT (nl_autostart OFF → a fresh chat never
    # starts a session) is covered directly in the router unit tests (BOB-076).
    router = CodingIntentRouter(
        coder=assistant, classifier=classifier, nl_autostart=True
    )
    return _Rig(router, assistant, runner, worktree, store, pr_opener, notifier, classifier)


# --- A clear owner dev-task → PLAN only, no edits ---------------------------------


async def test_owner_dev_task_plans_only_and_does_not_execute() -> None:
    rig = _rig(coding=True)

    consumed = await rig.router.route(text=_DEV_TASK, sender=_OWNER, is_owner=True)

    assert consumed is True
    # A session was created and is WAITING at the plan gate — not executed.
    active = await rig.store.active()
    assert len(active) == 1
    assert active[0].state is CodingSessionState.PLAN_READY
    # 🔴 The runner ran ONLY in plan mode — execution (acceptEdits) did NOT start.
    assert rig.runner.modes == ["plan"]
    assert rig.pr_opener.opens == []
    # The worktree is on a safe bob/<slug> branch and is KEPT (needed for an approve).
    assert rig.worktree.created[0].startswith("bob/")
    assert rig.worktree.removed == []


# --- Ordinary owner chat → no session --------------------------------------------


async def test_owner_chat_creates_no_session() -> None:
    rig = _rig(coding=False)

    consumed = await rig.router.route(text=_CHAT, sender=_OWNER, is_owner=True)

    assert consumed is False
    assert await rig.store.active() == ()
    assert rig.runner.calls == []
    assert rig.worktree.created == []


# --- Owner-only (authz) ----------------------------------------------------------


async def test_guest_dev_task_never_starts_a_session() -> None:
    # A guest is told is_owner=False by HandleMessage; the router never touches the
    # assistant, so no session, no worktree, no run.
    rig = _rig(coding=True)

    consumed = await rig.router.route(text=_DEV_TASK, sender=_GUEST, is_owner=False)

    assert consumed is False
    assert await rig.store.active() == ()
    assert rig.runner.calls == []
    assert rig.worktree.created == []
    assert rig.classifier.seen == []  # not even classified — short-circuited on authz


async def test_defense_in_depth_use_case_refuses_a_non_owner_sender() -> None:
    # 🔴 Defense in depth: even if the router were mis-told is_owner=True for a NON-owner
    # sender (a routing bug), the use-case re-checks the owner on `start` and refuses —
    # no worktree, no run, no session. Owner-only is enforced in TWO places.
    rig = _rig(coding=True)

    await rig.router.route(text=_DEV_TASK, sender=_GUEST, is_owner=True)

    assert await rig.store.active() == ()
    assert rig.worktree.created == []
    assert rig.runner.calls == []
    assert rig.notifier.sent == []  # a silent, side-effect-free refusal


# --- Natural approve from PLAN_READY is the ONLY way to EXECUTING -----------------


async def test_natural_approve_from_plan_ready_executes_and_opens_pr() -> None:
    rig = _rig(coding=True)
    await rig.router.route(text=_DEV_TASK, sender=_OWNER, is_owner=True)
    assert rig.runner.modes == ["plan"]  # planned, not executed yet

    consumed = await rig.router.route(text="давай", sender=_OWNER, is_owner=True)

    assert consumed is True
    # NOW — and only now — the edit mode ran, exactly once, after the explicit approve.
    assert rig.runner.modes == ["plan", "acceptEdits"]
    # PR_OPEN is a SUCCESSFUL terminal (BOB-042): Bob's work is done, so the session no
    # longer counts as active (it never blocks a fresh task), but it IS persisted PR_OPEN.
    assert await rig.store.active() == ()
    pr_open = [
        s for s in rig.store.sessions.values() if s.state is CodingSessionState.PR_OPEN
    ]
    assert len(pr_open) == 1
    # 🔴 Bob committed + pushed the bob/<slug> branch (never main) before the single PR.
    assert len(rig.worktree.pushes) == 1
    assert rig.worktree.pushes[0][1].startswith("bob/")
    assert len(rig.pr_opener.opens) == 1
    assert rig.pr_opener.opens[0][0].startswith("bob/")


async def test_natural_stop_from_plan_ready_cancels_without_executing() -> None:
    rig = _rig(coding=True)
    await rig.router.route(text=_DEV_TASK, sender=_OWNER, is_owner=True)

    consumed = await rig.router.route(text="стоп", sender=_OWNER, is_owner=True)

    assert consumed is True
    # 🔴 A stop never executes — the edit mode never ran and no PR was opened.
    assert rig.runner.modes == ["plan"]
    assert rig.pr_opener.opens == []
    assert await rig.store.active() == ()  # the session is terminal (CANCELLED)
    cancelled = [
        s for s in rig.store.sessions.values() if s.state is CodingSessionState.CANCELLED
    ]
    assert len(cancelled) == 1
    assert rig.worktree.removed  # worktree cleaned up — no leak


# --- 🔴 The core: an ambiguous message while a plan waits must NOT execute ---------


async def test_ambiguous_message_at_plan_ready_never_approves_or_executes() -> None:
    # Even with the classifier biased to "coding", an ambiguous reply while a plan waits
    # is NOT an approval phrase, so the router leaves it to chat — no approve, no new
    # start, no execution. The plan keeps waiting.
    rig = _rig(coding=True)
    await rig.router.route(text=_DEV_TASK, sender=_OWNER, is_owner=True)

    consumed = await rig.router.route(
        text="а что там по тестам?", sender=_OWNER, is_owner=True
    )

    assert consumed is False
    # 🔴 Still PLAN_READY — no accidental execution, no second session.
    active = await rig.store.active()
    assert len(active) == 1
    assert active[0].state is CodingSessionState.PLAN_READY
    assert rig.runner.modes == ["plan"]
    assert rig.pr_opener.opens == []


async def test_no_nl_path_to_executing_except_approve_from_plan_ready() -> None:
    # 🔴 The full invariant scan. The classifier is biased to "coding" (worst case: every
    # message looks like a dev-task), yet the edit mode is reached ONLY at the explicit
    # approve from PLAN_READY — never from a (mis)classified intent message.
    rig = _rig(coding=True)

    # 1) A misclassified chat on a fresh state → at WORST proposes a plan (plan-mode).
    await rig.router.route(text="расскажи про космос", sender=_OWNER, is_owner=True)
    assert rig.runner.modes == ["plan"]  # planned, NOT executed
    assert (await rig.store.active())[0].state is CodingSessionState.PLAN_READY

    # 2) Another misclassified chat while the plan waits (not an approval) → nothing.
    await rig.router.route(text="а ещё что?", sender=_OWNER, is_owner=True)
    assert rig.runner.modes == ["plan"]  # STILL no execution

    # 3) Only the explicit approval phrase from PLAN_READY reaches the edit mode.
    await rig.router.route(text="давай", sender=_OWNER, is_owner=True)
    assert rig.runner.modes == ["plan", "acceptEdits"]


async def test_misclassified_chat_at_worst_proposes_a_plan() -> None:
    # The conservative-classifier safety floor: a false-positive (chat read as coding) on
    # a fresh state opens at most a PLAN (no edits, no PR) — the worst case is harmless.
    rig = _rig(coding=True)

    consumed = await rig.router.route(
        text="что нового по проекту?", sender=_OWNER, is_owner=True
    )

    assert consumed is True
    active = await rig.store.active()
    assert active[0].state is CodingSessionState.PLAN_READY
    assert rig.runner.modes == ["plan"]  # plan only — no edits
    assert rig.pr_opener.opens == []


async def test_pr_open_does_not_block_a_fresh_session() -> None:
    # BOB-042 Fix A: once a session reaches PR_OPEN, Bob's work is DONE (the owner merges
    # the PR asynchronously on GitHub), so PR_OPEN is a SUCCESSFUL terminal and must NOT
    # block a new task. active_state() returns None → a fresh coding-intent message starts
    # a brand-new session via _route_fresh (a PLAN — the gate), NOT _route_active.
    rig = _rig(coding=True)
    await rig.router.route(text=_DEV_TASK, sender=_OWNER, is_owner=True)
    await rig.router.route(text="давай", sender=_OWNER, is_owner=True)  # → PR_OPEN
    assert rig.runner.modes == ["plan", "acceptEdits"]
    assert await rig.assistant.active_state() is None  # PR_OPEN no longer "active"

    # A new dev-task is NOT routed as approve/stop of the old session — it starts fresh.
    consumed = await rig.router.route(
        text="Боб, добавь README", sender=_OWNER, is_owner=True
    )

    assert consumed is True
    # The fresh session only PLANNED (the gate) — no second execution without an approve.
    assert rig.runner.modes == ["plan", "acceptEdits", "plan"]
    assert len(rig.pr_opener.opens) == 1  # still exactly one PR (the first session's)
    plan_ready = [
        s for s in rig.store.sessions.values() if s.state is CodingSessionState.PLAN_READY
    ]
    assert len(plan_ready) == 1  # the new session is waiting at the plan gate


async def test_pr_open_then_approval_word_does_not_re_execute() -> None:
    # 🔴 BOB-042 gate-intact guardrail (replaces the old "approval after PR_OPEN" test).
    # After PR_OPEN there is NO PLAN_READY to approve, so even the literal approval word
    # "давай" (classifier biased to coding) cannot re-execute — it is routed as a FRESH
    # request that at WORST plans (the gate), never a second acceptEdits.
    rig = _rig(coding=True)
    await rig.router.route(text=_DEV_TASK, sender=_OWNER, is_owner=True)
    await rig.router.route(text="давай", sender=_OWNER, is_owner=True)  # → PR_OPEN
    assert rig.runner.modes == ["plan", "acceptEdits"]

    consumed = await rig.router.route(text="давай", sender=_OWNER, is_owner=True)

    assert consumed is True  # treated as a fresh classified request (it PLANS)
    # 🔴 No second execution — at most a fresh PLAN; the plan gate held.
    assert rig.runner.modes == ["plan", "acceptEdits", "plan"]
    assert len(rig.pr_opener.opens) == 1  # still exactly one PR (the first session's)


async def test_two_full_pr_open_cycles_each_independently_gated() -> None:
    # 🔴 BOB-042 Fix A end-to-end: PR_OPEN never blocks — a SECOND full task runs after
    # the first reached PR_OPEN — AND each cycle stays independently gated (the edit mode
    # runs only after that cycle's OWN explicit approve). Two plans, two approves, two PRs.
    rig = _rig(coding=True)

    await rig.router.route(text=_DEV_TASK, sender=_OWNER, is_owner=True)
    await rig.router.route(text="давай", sender=_OWNER, is_owner=True)  # cycle 1 → PR_OPEN
    assert await rig.assistant.active_state() is None  # nothing blocks cycle 2

    await rig.router.route(text="Боб, добавь README", sender=_OWNER, is_owner=True)
    assert rig.runner.modes == ["plan", "acceptEdits", "plan"]  # planned, awaiting approve
    await rig.router.route(text="давай", sender=_OWNER, is_owner=True)  # cycle 2 → PR_OPEN

    # 🔴 Strictly interleaved plan→approve→execute per cycle — no execution without approve.
    assert rig.runner.modes == ["plan", "acceptEdits", "plan", "acceptEdits"]
    assert len(rig.pr_opener.opens) == 2  # exactly one PR per completed cycle
    assert await rig.store.active() == ()  # both sessions terminal at PR_OPEN
    pr_open = [
        s for s in rig.store.sessions.values() if s.state is CodingSessionState.PR_OPEN
    ]
    assert len(pr_open) == 2
