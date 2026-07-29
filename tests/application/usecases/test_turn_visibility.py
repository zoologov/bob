# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Gap-fill: the write-side scope-provenance classifier of такт разглашения (BOB-066 2.6).

:func:`~bob.application.usecases.handle_message._turn_is_shared_scope` is the pure
application-layer decision that decides, per turn, whether the memory Bob writes is a
SHARED (public) surface or the owner's PRIVATE world — it feeds
:func:`~bob.social.disclosure.visibility_for_scope` to stamp every new episode/fact.
It is load-bearing for INV-7 (an owner-DM turn must be tagged ``owner_private`` so it
never later surfaces to a guest) and INV-8 (an UNIDENTIFIED turn is conservatively
withheld). These behaviour tests pin the full classification the recall filter later
relies on; they are pure (no store, no LLM).
"""

from __future__ import annotations

import pytest

from bob.application.usecases.handle_message import _turn_is_shared_scope
from bob.social.disclosure import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    visibility_for_scope,
)
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust


def _interlocutor(kind: InterlocutorKind, trust: Trust) -> Interlocutor:
    return Interlocutor(sender_id=1, display_name="X", kind=kind, trust=trust)


def test_owner_turn_is_not_a_shared_scope() -> None:
    # An owner-DM turn is his private world (False → owner_private downstream).
    owner = _interlocutor(InterlocutorKind.OWNER, Trust.TRUSTED)

    assert _turn_is_shared_scope(owner) is False


@pytest.mark.parametrize(
    ("kind", "trust"),
    [
        (InterlocutorKind.GUEST, Trust.GUEST),
        (InterlocutorKind.KNOWN, Trust.TRUSTED),
        (InterlocutorKind.BOT, Trust.GUEST),
    ],
)
def test_non_owner_turn_is_a_shared_scope(
    kind: InterlocutorKind, trust: Trust
) -> None:
    # Any non-owner author's turn is that person's OWN shared contribution (True →
    # public) — never the owner's private data, so BOB-051 unified memory stays intact.
    assert _turn_is_shared_scope(_interlocutor(kind, trust)) is True


def test_unidentified_turn_is_uncertain_scope() -> None:
    # No perception seam → UNCERTAIN (None), which visibility_for_scope treats as the
    # conservative owner_private fail-safe (INV-8: doubt withholds, never leaks).
    assert _turn_is_shared_scope(None) is None


# --- End-to-end write-side provenance (classifier → visibility tag) ----------------
# The pair that stamps every new row: _turn_is_shared_scope feeds visibility_for_scope.


def test_owner_turn_is_stamped_owner_private() -> None:
    owner = _interlocutor(InterlocutorKind.OWNER, Trust.TRUSTED)

    visibility = visibility_for_scope(is_group=_turn_is_shared_scope(owner))

    assert visibility == VISIBILITY_OWNER_PRIVATE


def test_guest_turn_is_stamped_public() -> None:
    guest = _interlocutor(InterlocutorKind.GUEST, Trust.GUEST)

    visibility = visibility_for_scope(is_group=_turn_is_shared_scope(guest))

    # A guest's OWN turn is public shared memory (BOB-051) — the guest-facing withholding
    # is only ever about the OWNER's private data, never a guest's own contribution.
    assert visibility == VISIBILITY_PUBLIC


def test_unidentified_turn_is_stamped_owner_private_by_the_fail_safe() -> None:
    # INV-8: an uncertain scope is written owner_private, never public by accident.
    visibility = visibility_for_scope(is_group=_turn_is_shared_scope(None))

    assert visibility == VISIBILITY_OWNER_PRIVATE
