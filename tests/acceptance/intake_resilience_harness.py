# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Intake-resilience acceptance harness (BOB-078 D).

Witnesses, through REAL production code, that a BROKEN coding session never deafens Bob.
The live incident: the coding-intent router is consulted on EVERY inbound owner message;
one unparseable ``coding_session`` row (e.g. an out-of-enum ``state``) made ``active()``
raise ``ValueError`` on every message → the whole intake worker fell over → Bob went silent
on his owner. The fix has two real loci, both driven here:

* :class:`~bob.coding.adapters.session_store.SqliteCodingSessionStore.active` SKIPS an
  unparseable row (logs + drops it) and still returns the valid in-flight session; and
* :class:`~bob.application.usecases.precompose_gate.PreComposeGate.maybe_route_coding`
  wraps the router call in try/except, so ANY router failure is swallowed and the turn
  FALLS THROUGH to the normal chat path (not consumed) instead of crashing reception.

Both are exercised over real objects; the boundary observed is the resilience contract —
the lookup does not throw and the turn is not lost — which is exactly what keeps Bob
answering.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.usecases.precompose_gate import PreComposeGate
from bob.coding.adapters.session_store import SqliteCodingSessionStore
from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState
from bob.kernel.events import MessageReceived
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust

if TYPE_CHECKING:
    from pathlib import Path

_T0 = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
_OWNER = Interlocutor(
    sender_id=5,
    display_name="Vladimir",
    kind=InterlocutorKind.OWNER,
    trust=Trust.TRUSTED,
)


def _owner_message() -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=42,
        message_id=1,
        text="Боб, поправь баг в Z",
        sender_id=5,
        sender_name="Vladimir",
    )


async def _seed_broken_and_valid_session(repo: SqliteMemoryRepo) -> None:
    """Persist ONE valid in-flight session and INSERT a broken row beside it.

    The broken row carries ``state='CANCELLED'`` (upper-case — not a valid enum; the enum
    value is the lower-case ``'cancelled'``), the exact shape of the live corrupt row.
    """
    store = SqliteCodingSessionStore(repo)
    await store.save(
        CodingSession(
            id="live",
            task="починить парсер",
            state=CodingSessionState.EXECUTING,
            branch="bob/fix-parser",
            created_at=_T0,
            updated_at=_T0,
        )
    )
    await repo.connection.execute(
        "INSERT INTO coding_session (id, task, state, branch, created_at, updated_at, "
        "worktree_path, plan, pr_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("broken", "t", "CANCELLED", "b", _T0.isoformat(), _T0.isoformat(), None, None, None),
    )
    await repo.connection.commit()


async def broken_session_lookup(tmp_path: Path) -> tuple[str, ...]:
    """Return the ids the REAL ``active()`` yields over a broken+valid session mix.

    A raise here is what deafened Bob live; the resilient store must return the valid
    in-flight session and swallow the broken row.
    """
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        await _seed_broken_and_valid_session(repo)
        active = await SqliteCodingSessionStore(repo).active()
    finally:
        await repo.close()
    return tuple(session.id for session in active)


class _RaisingCodingRouter:
    """A router that raises as the corrupt session did (``'CANCELLED'`` → ValueError)."""

    async def route(self, *, text: str, sender: int | None, is_owner: bool) -> bool:
        raise ValueError("'CANCELLED' is not a valid CodingSessionState")


async def coding_gate_consumed_the_turn() -> bool:
    """Drive the REAL pre-compose gate with a raising router; return whether it CONSUMED.

    The gate must swallow the failure and return False (turn NOT consumed) so reception
    falls through to the normal chat path — Bob still answers.
    """
    gate = PreComposeGate(coding_router=_RaisingCodingRouter(), permission_flow=None)
    return await gate.maybe_route_coding(_owner_message(), _OWNER)
