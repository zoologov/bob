# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the work-journal exclusion from the replayed thread (BOB-087.C8).

The recent thread Bob replays into every compose prompt is CONVERSATION — what was
actually said in the room. A distilled ``work`` episode is not a turn anybody spoke: it is
the operator journal Bob writes to himself at the end of a coding session, and it lands in
the same episodic log. Replayed verbatim it would reach EVERY chat's prompt with no
relevance gate, no register and no provenance directive at all — a wider hole than any
recall door. It is dropped here; his work comes back through RECALL, where the register
decides and the provenance directive rides along.

Purely additive today: with ``memory.work_journal`` off no ``work`` row exists, so the
projection is the identity — the thread is byte-identical.
"""

from __future__ import annotations

from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

from bob.conversation.thread import _thread_without_work_journal
from bob.conversation.usecases.recall_assembler import RecallAssembler
from bob.memory.work_journal import WORK_EVENT_TYPE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _turn(content: str) -> Mapping[str, object]:
    return {"content": content, "event_type": "message"}


def _journal(content: str) -> Mapping[str, object]:
    return {"content": content, "event_type": WORK_EVENT_TYPE}


def test_work_journal_entries_are_not_replayed_as_conversation() -> None:
    history = [
        _turn("Вова: как дела?\nbob: нормально"),
        _journal("я попросил GUPPI поднять лимит буфера, тесты позеленели"),
        _turn("Лиля: всем привет\nbob: привет!"),
    ]

    kept = _thread_without_work_journal(history)

    assert [item["content"] for item in kept] == [
        "Вова: как дела?\nbob: нормально",
        "Лиля: всем привет\nbob: привет!",
    ]


def test_a_thread_without_work_is_the_identity() -> None:
    # INV: nothing else is touched — same items, same objects, same order (today's
    # behaviour byte-for-byte while the work journal is off).
    history = [_turn("Вова: привет\nbob: здравствуй"), _turn("Вова: ну как?\nbob: живу")]

    kept = _thread_without_work_journal(history)

    assert list(kept) == history
    assert kept[0] is history[0]


def test_other_episode_kinds_are_kept() -> None:
    # Defensive default: only the KNOWN work marker is dropped — a digest / self_action /
    # unlabeled row still replays exactly as before.
    history = [
        {"content": "дайджест недели", "event_type": "digest"},
        {"content": "я собрал схему", "event_type": "self_action"},
        {"content": "без типа"},
    ]

    assert list(_thread_without_work_journal(history)) == history


def test_work_marker_is_matched_case_insensitively() -> None:
    history = [_journal("я чинил раннер"), {"content": "и ещё", "event_type": "WORK"}]

    assert _thread_without_work_journal(history) == ()


def test_an_empty_thread_stays_empty() -> None:
    assert _thread_without_work_journal([]) == ()


# --- The replay seam: the assembler is where the projection actually bites --------------


class _StubEpisodes:
    """An episode reader returning a canned recent thread (the store boundary)."""

    def __init__(self, history: list[Mapping[str, object]]) -> None:
        self._history = history

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        del k
        return self._history

    async def recent_episodes_for(
        self, sender_id: int, k: int
    ) -> Sequence[Mapping[str, object]]:  # pragma: no cover - the shared thread is read
        del sender_id, k
        return []


def _assembler(history: list[Mapping[str, object]]) -> RecallAssembler:
    return RecallAssembler(
        episodes=_StubEpisodes(history),
        recent_turns=14,
        absence_hint_hours=8.0,
        notable_reaction=None,
        acknowledge_reaction_freq=0.0,
        clock=_FixedClock(),
        rng=Random(0),  # noqa: S311 — a test stub, not cryptography
    )


async def test_replayed_thread_leaves_the_work_journal_behind() -> None:
    history = [
        _turn("Вова: как дела?\nbob: нормально"),
        _journal("я попросил GUPPI поднять лимит буфера, тесты позеленели"),
    ]

    replayed = await _assembler(history).replay_recent_thread(None)

    assert [item["content"] for item in replayed] == ["Вова: как дела?\nbob: нормально"]


async def test_replayed_thread_without_work_is_unchanged() -> None:
    history = [_turn("Вова: привет\nbob: здравствуй")]

    replayed = await _assembler(history).replay_recent_thread(None)

    assert list(replayed) == history
