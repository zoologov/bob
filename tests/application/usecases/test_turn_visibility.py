# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Write-side scope-provenance classifier — scope BY WHERE it was said (BOB-082 .1).

:func:`~bob.application.usecases.handle_message._turn_is_shared_scope` is the pure
application-layer decision that names, per turn, whether the memory Bob writes is a
SHARED (public) surface or the owner's PRIVATE world. Since BOB-082 .1 it keys on the
CHANNEL signal (``is_group``) — WHERE the turn was said — not on WHO spoke: a group turn
is shared/``public`` (including the owner speaking there, which the earlier by-WHO logic
wrongly stamped ``owner_private``); the owner's 1:1 DM is ``owner_private``. It feeds
:func:`~bob.social.disclosure.visibility_for_scope` to stamp every new episode/fact.
These behaviour tests pin the full classification the recall filter later relies on;
they are pure (no store, no LLM).
"""

from __future__ import annotations

from bob.application.usecases.handle_message import _turn_is_shared_scope
from bob.kernel.interlocutor import Trust
from bob.social.disclosure import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    filter_surfaceable,
    visibility_for_scope,
)

# --- The channel → shared-scope classifier ------------------------------------------


def test_group_turn_is_a_shared_scope() -> None:
    # A group/supergroup channel is a SHARED surface (True → public downstream).
    assert _turn_is_shared_scope(is_group=True) is True


def test_dm_turn_is_not_a_shared_scope() -> None:
    # The owner's 1:1 DM is his private world (False → owner_private downstream).
    assert _turn_is_shared_scope(is_group=False) is False


# --- End-to-end write-side provenance (classifier → visibility tag) -----------------
# The pair that stamps every new row: _turn_is_shared_scope feeds visibility_for_scope.


def test_group_turn_is_stamped_public() -> None:
    visibility = visibility_for_scope(is_group=_turn_is_shared_scope(is_group=True))

    assert visibility == VISIBILITY_PUBLIC


def test_dm_turn_is_stamped_owner_private() -> None:
    visibility = visibility_for_scope(is_group=_turn_is_shared_scope(is_group=False))

    assert visibility == VISIBILITY_OWNER_PRIVATE


def test_owner_in_group_is_stamped_public_the_fix() -> None:
    # 🔴 BOB-082 .1 correctness fix: the owner speaking in the GROUP is a shared turn
    # (public), NOT owner_private. Scope is decided BY WHERE (the group channel), so the
    # owner's identity no longer forces owner_private for a turn he says in the room.
    visibility = visibility_for_scope(is_group=_turn_is_shared_scope(is_group=True))

    assert visibility == VISIBILITY_PUBLIC


def test_guest_in_group_is_stamped_public_as_before() -> None:
    # A guest/known peer in the group stays public shared memory (BOB-051) — unchanged.
    visibility = visibility_for_scope(is_group=_turn_is_shared_scope(is_group=True))

    assert visibility == VISIBILITY_PUBLIC


# --- Regression: the recall FILTER is unchanged (owner surface intact, INV-7) --------
# This bead only changes how a turn's OWN visibility is STAMPED (write side), never the
# read-side filter. The owner is TRUSTED, so owner_private memory still surfaces to him.


def test_owner_still_surfaces_owner_private_memory_to_themselves() -> None:
    private_item = {"content": "адрес владельца", "visibility": VISIBILITY_OWNER_PRIVATE}

    kept = filter_surfaceable([private_item], Trust.TRUSTED)

    # INV-7: the filter is untouched — a TRUSTED interlocutor (the owner) sees everything,
    # so his own owner_private memory is never withheld from him.
    assert kept == (private_item,)
