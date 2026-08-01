# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary harness for the BOB-082 dev-channel + cross-channel-memory scenarios.

The ``.feature`` for BOB-082 asserts OBSERVABLE behaviour through real seams — never
private state:

* :class:`RecordingNotifier` / :class:`RecordingPanel` are the transport boundary the
  live streamer writes to (they realise the :class:`~bob.coding.usecases.coding_assistant`
  ``OwnerNotifier`` / ``StatusPanel`` ports). A scenario drives
  :class:`~bob.coding.adapters.live_stream._DmLiveStreamer` over a scripted event stream
  and asserts what actually reached the DM chat — the raw, uncapped firehose (S1) — and
  that the GROUP got only the one-line pointer (S2).
* :func:`build_memory` stands up a real-but-disposable SQLite archive with the live FTS5
  index and the real :class:`~bob.memory.adapters.Fts5MemoryRecall`, so the seamless
  cross-channel recall (S3, the anti-amnesia invariant INV-1) is proven end-to-end.
* :class:`ScriptedConsentJudge` is the injectable Tier-0 double the
  :class:`~bob.application.usecases.disclosure_consent_gate.DisclosureConsentGate` weighs
  (S5 yes / S6 never-fires-for-non-owner).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.memory.adapters import Fts5MemoryRecall
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.social.disclosure_consent import DisclosureConsentContext


class RecordingNotifier:
    """An ``OwnerNotifier`` double recording every line sent to its (DM / group) chat."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


class RecordingPanel:
    """A ``StatusPanel`` double recording the rolling terminal panel's edits."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.updates: list[str] = []

    async def open(self, text: str) -> None:
        self.opened.append(text)

    async def update(self, text: str) -> None:
        self.updates.append(text)


class ScriptedConsentJudge:
    """A Tier-0 consent-judge double: a scripted verdict + a record of every call.

    Lets a scenario prove not only the verdict but that a non-owner turn is NEVER
    judged (S6 — the detector must not even fire for a guest).
    """

    def __init__(self, verdict: bool) -> None:
        self._verdict = verdict
        self.calls: list[DisclosureConsentContext] = []

    async def assess(self, ctx: DisclosureConsentContext) -> bool:
        self.calls.append(ctx)
        return self._verdict


async def drain(events: Sequence[Mapping[str, object]]) -> AsyncIterator[Mapping[str, object]]:
    """Yield a scripted event list as the async stream the live streamer consumes."""
    for event in events:
        yield event


async def build_memory(tmp_path: Path) -> tuple[SqliteMemoryRepo, Fts5MemoryRecall]:
    """Stand up a real disposable archive + the real FTS5 recall (no chat_id filter)."""
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    return repo, Fts5MemoryRecall(repo)


async def save_turn(
    repo: SqliteMemoryRepo, *, content: str, visibility: str, sender_id: int
) -> None:
    """Persist one episodic turn with its scope provenance (visibility) — no channel tag."""
    await repo.save_episode(
        {
            "ts": datetime.now(UTC).isoformat(),
            "event_type": "user_message",
            "content": content,
            "sender_id": sender_id,
            "visibility": visibility,
        }
    )
