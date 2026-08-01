# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for RosterRecall — the ambient «состав комнаты» recall use-case (BOB-080).

RosterRecall reads the recency of accumulated first impressions and hands the compose
path a roster of who lately turned up — but only WHEN and TO WHOM it is appropriate:

* AMBIENT WINDOW (INV-4): a roster surfaces ONLY if it carries a fresh newcomer; with
  no recent joiners it stays empty (no line → no flood).
* PRIVACY: only an OWNER / KNOWN viewer gets the room's rundown; a GUEST gets nothing.
* BEST-EFFORT: a flaky store never breaks the turn — a raising read yields an empty roster.
* FLAG: with the roster disabled the use-case is inert (empty).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.social.first_impression import FirstImpression
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.social.usecases.roster_recall import RosterRecall

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
_OWNER_ID = 1
_BOB_ID = 2

_OWNER = Interlocutor(
    sender_id=_OWNER_ID,
    display_name="Влад",
    kind=InterlocutorKind.OWNER,
    trust=Trust.TRUSTED,
)
_KNOWN = Interlocutor(
    sender_id=50,
    display_name="Паша",
    kind=InterlocutorKind.KNOWN,
    trust=Trust.TRUSTED,
)
_GUEST = Interlocutor(
    sender_id=999,
    display_name="Незнакомец",
    kind=InterlocutorKind.GUEST,
    trust=Trust.GUEST,
)
_BOT = Interlocutor(
    sender_id=777,
    display_name="ботяра",
    kind=InterlocutorKind.BOT,
    trust=Trust.GUEST,
)


def _impression(sender_id: int, name: str, *, days_ago: float) -> FirstImpression:
    return FirstImpression(
        sender_id=sender_id,
        first_seen_at=_NOW - timedelta(days=days_ago),
        note=f"{name} — кто-то из знакомых, уже виделись.",
        display_name=name,
    )


class _FakeRecencyStore:
    """In-memory recency reader: returns the seeded impressions newest-first."""

    def __init__(self, impressions: list[FirstImpression]) -> None:
        self._impressions = sorted(
            impressions, key=lambda i: i.first_seen_at, reverse=True
        )
        self.calls: list[int] = []

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        self.calls.append(limit)
        return self._impressions[:limit]


class _RaisingStore:
    async def recent(self, *, limit: int) -> list[FirstImpression]:  # noqa: ARG002
        raise RuntimeError("first-impression store unavailable")


def _recall(
    store: object, *, newcomer_days: float = 7.0, limit: int = 6
) -> RosterRecall:
    return RosterRecall(
        store=store,  # type: ignore[arg-type]
        newcomer_days=newcomer_days,
        limit=limit,
        owner_id=_OWNER_ID,
        bob_id_source=lambda: _BOB_ID,
    )


async def test_recent_newcomer_surfaces_the_roster() -> None:
    # AMBIENT WINDOW: a fresh joiner is present → the roster is handed back, named.
    store = _FakeRecencyStore(
        [_impression(50, "Паша", days_ago=1.0), _impression(60, "Лиля", days_ago=2.0)]
    )
    roster = await _recall(store).recent_roster(_NOW, viewer=_OWNER)

    assert {m.name for m in roster} == {"Паша", "Лиля"}
    assert any(m.is_newcomer for m in roster)


async def test_no_recent_newcomer_returns_empty() -> None:
    # AMBIENT WINDOW (INV-4): only old-timers on record → no roster line (no flood).
    store = _FakeRecencyStore(
        [_impression(50, "Паша", days_ago=40.0), _impression(60, "Лиля", days_ago=90.0)]
    )
    roster = await _recall(store).recent_roster(_NOW, viewer=_OWNER)

    assert roster == ()


async def test_known_viewer_gets_the_roster() -> None:
    store = _FakeRecencyStore([_impression(50, "Паша", days_ago=1.0)])
    roster = await _recall(store).recent_roster(_NOW, viewer=_KNOWN)

    assert roster != ()


async def test_guest_viewer_gets_no_roster() -> None:
    # PRIVACY: a guest is not handed a rundown of everyone in the room.
    store = _FakeRecencyStore([_impression(50, "Паша", days_ago=1.0)])
    roster = await _recall(store).recent_roster(_NOW, viewer=_GUEST)

    assert roster == ()
    assert store.calls == []  # the store is never even read for a guest


async def test_owner_and_bob_are_excluded_from_the_roster() -> None:
    # The owner + Bob himself are known, not «newcomers» — excluded from the roster.
    store = _FakeRecencyStore(
        [
            _impression(_OWNER_ID, "Влад", days_ago=1.0),
            _impression(_BOB_ID, "Боб", days_ago=1.0),
            _impression(50, "Паша", days_ago=1.0),
        ]
    )
    roster = await _recall(store).recent_roster(_NOW, viewer=_OWNER)

    assert {m.sender_id for m in roster} == {50}


async def test_store_failure_yields_empty_roster() -> None:
    # BEST-EFFORT: a raising store never propagates — the turn continues roster-less.
    roster = await _recall(_RaisingStore()).recent_roster(_NOW, viewer=_OWNER)

    assert roster == ()


async def test_no_viewer_returns_empty() -> None:
    # No perceived viewer (None) → no roster (privacy cannot be established).
    store = _FakeRecencyStore([_impression(50, "Паша", days_ago=1.0)])
    roster = await _recall(store).recent_roster(_NOW, viewer=None)

    assert roster == ()


async def test_bot_viewer_gets_no_roster() -> None:
    # PRIVACY: a bot is not one of {OWNER, KNOWN} → no rundown, store never read.
    store = _FakeRecencyStore([_impression(50, "Паша", days_ago=1.0)])
    roster = await _recall(store).recent_roster(_NOW, viewer=_BOT)

    assert roster == ()
    assert store.calls == []


async def test_bob_id_source_omitted_excludes_only_the_owner() -> None:
    # With no bob_id_source wired, only the owner is kept off the roster (no id for Bob).
    store = _FakeRecencyStore(
        [
            _impression(_OWNER_ID, "Влад", days_ago=1.0),
            _impression(_BOB_ID, "Боб", days_ago=1.0),
            _impression(50, "Паша", days_ago=1.0),
        ]
    )
    recall = RosterRecall(
        store=store,  # type: ignore[arg-type]
        newcomer_days=7.0,
        limit=6,
        owner_id=_OWNER_ID,
        bob_id_source=None,
    )

    roster = await recall.recent_roster(_NOW, viewer=_OWNER)

    # Owner excluded; Bob's own id is present (no source to resolve+exclude it).
    assert {m.sender_id for m in roster} == {_BOB_ID, 50}


async def test_bob_id_source_returning_none_excludes_only_the_owner() -> None:
    # A source that yields None (Bob's id not resolved yet) excludes only the owner.
    store = _FakeRecencyStore(
        [_impression(_BOB_ID, "Боб", days_ago=1.0), _impression(50, "Паша", days_ago=1.0)]
    )
    recall = RosterRecall(
        store=store,  # type: ignore[arg-type]
        newcomer_days=7.0,
        limit=6,
        owner_id=_OWNER_ID,
        bob_id_source=lambda: None,
    )

    roster = await recall.recent_roster(_NOW, viewer=_OWNER)

    assert {m.sender_id for m in roster} == {_BOB_ID, 50}


async def test_limit_is_passed_through_to_the_store_read() -> None:
    # The configured cap flows into the recency read (the store is asked for `limit`).
    store = _FakeRecencyStore([_impression(50, "Паша", days_ago=1.0)])

    await _recall(store, limit=3).recent_roster(_NOW, viewer=_OWNER)

    assert store.calls == [3]
