# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Coding ports — the «Bob runs Claude Code» session seam (BOB-039/040).

The headless ``claude`` runner (:class:`ClaudeCodeRunner`), the isolated worktree
(:class:`Worktree`), the durable session store (:class:`CodingSessionStore`), and
the PR opener (:class:`PullRequestOpener`), plus the two NARROW resume seams
(:class:`ResumableSessionLookup`, :class:`PersistentWorkspace`, BOB-087.D3). These are
*interfaces only*: structural
:class:`typing.Protocol` definitions with no implementations; the shell-free
subprocess / SQLite adapters live in ``bob.infrastructure``. There is DELIBERATELY
no merge seam — Bob opens a PR and stops; the owner merges.

🔴 BOB-087.E (bob-6u2): three of these ports — :class:`OwnerNotifier`,
:class:`OwnerCheck` and :class:`LiveRunStreamer` — used to live inside the gated
use-case :mod:`bob.coding.usecases.coding_assistant`. They are the seams BOTH bounded
contexts rest on (the gated coder AND the live terminal :mod:`bob.interactive`, split
out into its own node), so their home is the shared port module, not one context's
orchestrator: a module may depend on another module's PORTS, never on its use-cases.
The gated-coder-only seams (typing indicator / status panel / prompt context / work
journal) deliberately stayed with the use-case that alone knows them. The old import
paths keep working — ``coding_assistant`` re-exports all three.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession


@runtime_checkable
class ClaudeCodeRunner(Protocol):
    """Run the local ``claude`` CLI headless and stream its events (BOB-039 .2).

    The seam the gated coding session delegates execution to: given a ``workdir``
    (the isolated git worktree), a ``prompt`` (the task), and a ``mode`` (``"plan"``
    for plan-mode — a plan with NO edits, the plan gate — or an execute mode such as
    ``"acceptEdits"`` that applies changes inside the worktree), it yields the
    ``--output-format stream-json`` events one by one (each a decoded NDJSON object).
    The contract is deliberately abstract: the live realisation
    (``SubprocessClaudeRunner``) runs ``create_subprocess_exec`` WITHOUT a shell and
    parses NDJSON line-by-line; a deterministic fake yields canned events in tests
    with no subprocess. Events are mapped to narrative lines by the pure
    :func:`bob.coding.narrate.narrate`.
    """

    def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        """Run ``claude`` in ``workdir`` under ``mode``; yield stream-json events."""
        ...


@runtime_checkable
class InteractiveRunner(Protocol):
    """Drive a PERSISTENT bidirectional ``claude`` session (BOB-083 .2).

    Distinct from the one-shot :class:`ClaudeCodeRunner`: instead of a single
    ``claude -p <prompt>`` run that ends at EOF, this seam holds a long-lived
    ``claude -p --input-format stream-json`` process with an OPEN stdin, so the
    owner can steer it in real time. :meth:`open` spawns the process (validated
    ``mode``; optional ``resume_session_id`` / ``continue_session`` resume a prior
    session — both default OFF, BOB-087.D1); :meth:`feed` writes one owner text turn
    as a stream-json ``user`` frame to stdin; :meth:`events` async-iterates the live
    stdout NDJSON; and :meth:`close` terminates (then kills after a grace) + reaps —
    idempotent and best-effort. The live realisation (``InteractiveClaudeRunner``) runs
    ``create_subprocess_exec`` WITHOUT a shell; a fake bidirectional process
    substitutes in tests. This is a pure transport adapter — no session / worktree
    / state logic (that is the interactive-session manager, BOB-083 .3).
    """

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
    ) -> None:
        """Spawn the persistent ``claude`` process in ``workdir`` under ``mode``.

        ``resume_session_id`` / ``continue_session`` (BOB-087.D1) opt into RESUMING a
        prior session instead of starting a fresh one; both default OFF, so an unchanged
        call site spawns exactly the BOB-083 fresh session. They live on the port (not
        only on the adapter) since BOB-087.D3, because the interactive-session manager —
        an application use-case that only ever sees this port — is what resumes a
        long-lived workspace by the persisted claude session id.
        """
        ...

    async def feed(self, text: str) -> None:
        """Send ``text`` to the live process as one stream-json ``user`` frame."""
        ...

    def events(self) -> AsyncIterator[Mapping[str, object]]:
        """Async-iterate the process's stdout stream-json events until it exits."""
        ...

    async def close(self) -> None:
        """Terminate (then kill after a grace) + reap the process (idempotent)."""
        ...

    @property
    def session_id(self) -> str | None:
        """The claude session id from the init event, or ``None`` if not yet seen.

        Captured off the stream so the manager can persist it for a later ``--resume``
        (BOB-087.D1); the transport itself owns no session state.
        """
        ...


@runtime_checkable
class Worktree(Protocol):
    """Create / remove an isolated git worktree for a coding session (BOB-039 .2).

    The isolation seam: :meth:`create` adds a fresh ``git worktree`` on a new branch
    and returns its path; only TRACKED files are present, so Bob's private data
    (``data/soul/``, ``bob.db*``, ``.env*``, ``config/*`` — all gitignored) is absent
    from the worktree and never reaches Claude Code. :meth:`remove` tears the worktree
    down (the use-case calls it in a ``finally``, so an aborted session cleans up).
    The live realisation (``GitWorktree``) runs git as fixed-form, shell-free
    invocations; a fake substitutes in tests.
    """

    async def create(self, branch: str) -> str:
        """Add an isolated worktree on ``branch`` and return its filesystem path."""
        ...

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        """Stage, commit and push the worktree's changes to the ``bob/<slug>`` branch.

        Bob's DETERMINISTIC integration step (BOB-040): after ``claude`` applies the
        approved plan it does NOT commit (``acceptEdits`` auto-accepts file edits only,
        never git), so the use-case commits + pushes the feature branch before a PR is
        opened. Returns ``True`` when a real commit was pushed, ``False`` when there was
        NOTHING to commit (claude made no change — the use-case then FAILS honestly and
        opens no PR). 🔴 ``branch`` MUST be the validated ``bob/<slug>`` feature branch;
        any other (e.g. ``main``) is refused before git runs — there is no path that can
        push the trunk.
        """
        ...

    async def remove(self, path: str) -> None:
        """Remove the worktree at ``path`` (idempotent cleanup)."""
        ...


@runtime_checkable
class CodingSessionStore(Protocol):
    """Durable store for Bob's gated coding sessions (BOB-039 .1).

    Round-trips the :class:`bob.coding.entities.CodingSession` — its task,
    :class:`~bob.coding.state.CodingSessionState`, branch, worktree path, plan
    text and PR url — so a gated session (and its stage) survives a restart, keeping
    the double gate honest across process boundaries. :meth:`save` UPSERTs on the
    session ``id`` (a session advances, so each step re-saves the newer state);
    :meth:`get` returns ``None`` for an unknown id; :meth:`active` lists the
    non-terminal sessions (so the use-case can find the in-flight one for
    ``/code approve`` / ``/code stop``). The concrete SQLite-backed adapter
    (``SqliteCodingSessionStore``) lives in ``bob.infrastructure.persistence``.
    """

    async def save(self, session: CodingSession) -> None:
        """Persist ``session`` (UPSERT on its ``id`` — an advancing session is updated)."""
        ...

    async def get(self, session_id: str) -> CodingSession | None:
        """Return the session with ``session_id``, or ``None`` if there is none."""
        ...

    async def active(self) -> tuple[CodingSession, ...]:
        """Return the non-terminal sessions (oldest first; empty when none in flight)."""
        ...


@runtime_checkable
class ResumableSessionLookup(Protocol):
    """Look up the sessions recorded on ONE branch (BOB-087.D3).

    A deliberately NARROW read seam next to :class:`CodingSessionStore` (not folded into
    it: the store's contract is the gated lifecycle, and every one of its fakes would
    otherwise have to grow a method it never uses). It answers exactly one question — «что
    вообще писалось по этой ветке» — and returns EVERY state, terminal included: WHICH of
    them may be resumed is the pure domain policy's call
    (:func:`bob.interactive.resume_policy.select_resumable`), so the storage layer can never
    drift from the «no live-attach» rule. Realised by ``SqliteCodingSessionStore``.
    """

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        """Return every recorded session on ``branch`` (empty when there is none)."""
        ...


@runtime_checkable
class PersistentWorkspace(Protocol):
    """Ensure a LONG-LIVED named worktree exists and return its path (BOB-087.D3).

    The durable counterpart of :class:`Worktree`'s ephemeral ``create`` / ``remove``: a
    ``bob/epic-<slug>`` workspace (:func:`bob.coding.naming.workspace_branch`) whose work
    ACCUMULATES across sessions, so a resumed session lands back in the same tree. Kept as
    its OWN one-method port (rather than a fourth method on :class:`Worktree`) so every
    existing worktree fake stays valid and so a use-case that only needs to «ensure»
    cannot even express a removal. :meth:`ensure` is idempotent — an already-registered
    worktree is REUSED, never re-created and never removed. Realised by ``GitWorktree``.

    🔴 Isolation is unchanged: a persistent worktree is still a worktree, never the main
    tree — integration still goes through a PR.
    """

    async def ensure(self, branch: str) -> str:
        """Return the path of the persistent worktree on ``branch``, creating it once."""
        ...


@runtime_checkable
class PullRequestOpener(Protocol):
    """Open a pull request for a coding session's branch (BOB-039 .2).

    The PR seam: given the session ``branch``, a ``title`` and a ``body``, it opens a
    PR (the live realisation shells ``gh pr create --base main --head <branch>``,
    shell-free) and returns the PR url. There is DELIBERATELY NO ``merge`` method —
    Bob NEVER merges and never pushes to ``main``: he opens the PR and stops, and the
    owner merges by hand. The absence of a merge path here is part of the safety
    invariant (the use-case physically cannot merge), not an oversight.
    """

    async def open(self, branch: str, title: str, body: str) -> str:
        """Open a PR for ``branch`` and return its url (NEVER merges — owner does)."""
        ...


class OwnerNotifier(Protocol):
    """Узкий порт уведомления owner: послать одну строку в его чат (GUPPI-бот).

    Реализуется в композиции адаптером над GUPPI-ботом (шлёт в General). Use-case
    шлёт сюда план, нарратив-строки прогона, URL PR и короткие подтверждения —
    единственный канал общения с owner, чтобы use-case не знал про chat_id/транспорт.
    """

    async def send(self, text: str) -> None:
        """Послать ``text`` owner (best-effort, транспорт за адаптером)."""
        ...


class OwnerCheck(Protocol):
    """Узкий порт authz: только owner управляет coding-сессией (defense-in-depth).

    Реализуется :class:`~bob.social.usecases.Authorizer` (его ``is_owner``). Гейт
    дублируется на уровне GUPPI (команда от не-owner туда не доходит), но use-case
    проверяет owner на КАЖДОМ методе сам — никакой сессии/исполнения для чужого.
    """

    def is_owner(self, user_id: int | None) -> bool:
        """Является ли ``user_id`` owner'ом (единственный, кто вправе командовать)."""
        ...


class LiveRunStreamer(Protocol):
    """Сейм ЛАЙВ-стрима сырых событий прогона в dev-канал owner'а (BOB-082.3).

    Когда завязан (флаг ``coder.dev_dm`` ON), use-case делегирует сюда ВЕСЬ поток
    execute-событий: адаптер (:class:`~bob.coding.adapters.live_stream._DmLiveStreamer`)
    рендерит каждое сырое событие через :func:`~bob.coding.stream_render.render_stream_event`
    (не lossy ``narrate``) и льёт БЕЗ капа в ЛИЧКУ owner'а — прогрессивная «терминальная»
    панель + отдельные сообщения. Групповой топик при этом получает только короткий
    указатель (INV-5: firehose не флудит группу). Незавязан (``None``) → use-case идёт
    прежним путём: капнутый групповой нарратив ``narrate`` (поведение без флага не меняется).
    Живой интерактивный сеанс (:mod:`bob.interactive`) льёт через ЭТОТ ЖЕ порт — потому
    он и общий.

    Порт transport-free: use-case не знает про DM chat_id / edit_message_text — только
    вызывает :meth:`stream`; выбор цели/рендера делает композиция (wiring).
    """

    async def stream(
        self,
        events: AsyncIterator[Mapping[str, object]],
        *,
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Пролить сырые события прогона в dev-канал (пока ``is_cancelled()`` ложно)."""
        ...
