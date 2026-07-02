# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Coding ports — the gated «Bob runs Claude Code» session seam (BOB-039/040).

The headless ``claude`` runner (:class:`ClaudeCodeRunner`), the isolated worktree
(:class:`Worktree`), the durable session store (:class:`CodingSessionStore`), and
the PR opener (:class:`PullRequestOpener`). These are *interfaces only*: structural
:class:`typing.Protocol` definitions with no implementations; the shell-free
subprocess / SQLite adapters live in ``bob.infrastructure``. There is DELIBERATELY
no merge seam — Bob opens a PR and stops; the owner merges.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from bob.domain.coding.entities import CodingSession


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
    :func:`bob.domain.coding.narrate.narrate`.
    """

    def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        """Run ``claude`` in ``workdir`` under ``mode``; yield stream-json events."""
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

    Round-trips the :class:`bob.domain.coding.entities.CodingSession` — its task,
    :class:`~bob.domain.coding.state.CodingSessionState`, branch, worktree path, plan
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
