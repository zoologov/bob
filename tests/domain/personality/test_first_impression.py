# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for FirstImpression — the light per-person first-impression note (BOB-019).

A pure, immutable value object (sender_id + first_seen_at + a short impression note)
plus :func:`impression_note_for`, the cheap heuristic that derives a light, grounded
one-liner from the perceived interlocutor's kind — never a fabricated fact about the
person, just how Bob clocked them on first contact.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.domain.personality.first_impression import (
    FirstImpression,
    impression_note_for,
)
from bob.domain.personality.interlocutor import Interlocutor, InterlocutorKind, Trust

_SEEN = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


_TRUSTED_KINDS = {InterlocutorKind.OWNER, InterlocutorKind.KNOWN}


def _interlocutor(kind: InterlocutorKind, *, name: str = "Алиса") -> Interlocutor:
    trust = Trust.TRUSTED if kind in _TRUSTED_KINDS else Trust.GUEST
    return Interlocutor(sender_id=7, display_name=name, kind=kind, trust=trust)


def test_is_immutable() -> None:
    impression = FirstImpression(sender_id=7, first_seen_at=_SEEN, note="хмм")

    with pytest.raises(AttributeError):
        impression.note = "иначе"  # type: ignore[misc]


def test_rejects_blank_note() -> None:
    with pytest.raises(ValueError, match="note"):
        FirstImpression(sender_id=7, first_seen_at=_SEEN, note="   ")


def test_note_is_a_short_grounded_line_per_kind() -> None:
    for kind in InterlocutorKind:
        note = impression_note_for(_interlocutor(kind))
        assert note.strip(), f"note for {kind} should be non-empty"
        # Light, not a dossier: a single short line.
        assert "\n" not in note


def test_note_mentions_the_display_name() -> None:
    note = impression_note_for(_interlocutor(InterlocutorKind.GUEST, name="Боря"))

    assert "Боря" in note


def test_guest_and_owner_notes_differ() -> None:
    guest = impression_note_for(_interlocutor(InterlocutorKind.GUEST))
    owner = impression_note_for(_interlocutor(InterlocutorKind.OWNER))

    assert guest != owner
