# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for disclosure tact — the initiative-surfacing filter (BOB-066 2.6, Пласт 4).

Такт разглашения is ORTHOGONAL to the privilege gate: it filters what Bob *initiatively
surfaces* from memory, not what a person *asks* for. :func:`may_surface` is the pure
predicate — an ``owner_private`` memory never surfaces initiatively to a GUEST, while a
``public`` (or legacy ``NULL``) one always does; a TRUSTED interlocutor (owner / known)
sees everything (INV-7: owner recall stays byte-identical). :func:`visibility_for_scope`
is the conservative write-side classifier — a group turn is ``public`` shared memory, an
owner-DM or an uncertain scope is ``owner_private`` (fail-safe, INV-8).
"""

from __future__ import annotations

from bob.social.disclosure import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    filter_surfaceable,
    may_surface,
    visibility_for_scope,
)
from bob.social.interlocutor import Trust


def test_public_surfaces_to_a_guest() -> None:
    assert may_surface(VISIBILITY_PUBLIC, Trust.GUEST) is True


def test_owner_private_does_not_surface_to_a_guest() -> None:
    assert may_surface(VISIBILITY_OWNER_PRIVATE, Trust.GUEST) is False


def test_owner_private_surfaces_to_a_trusted_interlocutor() -> None:
    # INV-7: for owner / known (TRUSTED) recall is byte-identical — everything surfaces.
    assert may_surface(VISIBILITY_OWNER_PRIVATE, Trust.TRUSTED) is True


def test_public_surfaces_to_a_trusted_interlocutor() -> None:
    assert may_surface(VISIBILITY_PUBLIC, Trust.TRUSTED) is True


def test_legacy_null_visibility_is_treated_as_public_for_a_guest() -> None:
    # NULL = public (BOB-051 unified memory + legacy rows stay intact).
    assert may_surface(None, Trust.GUEST) is True


def test_unknown_visibility_is_treated_as_public_for_a_guest() -> None:
    # Defensive default: only a KNOWN owner_private tag withholds — anything else
    # (a stray/unrecognised value) surfaces, never silently hiding public memory.
    assert may_surface("weird-value", Trust.GUEST) is True


def test_owner_private_case_insensitive_for_a_guest() -> None:
    assert may_surface("OWNER_PRIVATE", Trust.GUEST) is False


def test_scope_group_turn_is_public() -> None:
    assert visibility_for_scope(is_group=True) == VISIBILITY_PUBLIC


def test_scope_owner_dm_turn_is_owner_private() -> None:
    assert visibility_for_scope(is_group=False) == VISIBILITY_OWNER_PRIVATE


def test_scope_uncertain_defaults_to_owner_private() -> None:
    # Conservative (INV-8): an uncertain scope is withheld, never public by accident.
    assert visibility_for_scope(is_group=None) == VISIBILITY_OWNER_PRIVATE


def test_visibility_constants_are_the_expected_literals() -> None:
    assert VISIBILITY_PUBLIC == "public"
    assert VISIBILITY_OWNER_PRIVATE == "owner_private"


# --- filter_surfaceable — the recall-pipeline filter --------------------------------

_PUBLIC_ITEM = {"content": "любит кофе", "visibility": VISIBILITY_PUBLIC}
_PRIVATE_ITEM = {"content": "адрес владельца", "visibility": VISIBILITY_OWNER_PRIVATE}
_LEGACY_ITEM = {"content": "старый факт"}  # no visibility key → NULL = public


def test_filter_surfaceable_is_byte_identical_for_a_trusted_interlocutor() -> None:
    # INV-7: owner/known recall is unchanged — every item passes, order preserved.
    items = [_PRIVATE_ITEM, _PUBLIC_ITEM, _LEGACY_ITEM]

    assert filter_surfaceable(items, Trust.TRUSTED) == tuple(items)


def test_filter_surfaceable_withholds_owner_private_from_a_guest() -> None:
    items = [_PRIVATE_ITEM, _PUBLIC_ITEM, _LEGACY_ITEM]

    kept = filter_surfaceable(items, Trust.GUEST)

    assert kept == (_PUBLIC_ITEM, _LEGACY_ITEM)


def test_filter_surfaceable_keeps_legacy_and_public_for_a_guest() -> None:
    # NULL (no key) and public both surface — BOB-051 memory stays intact for a guest.
    assert filter_surfaceable([_LEGACY_ITEM], Trust.GUEST) == (_LEGACY_ITEM,)


def test_filter_surfaceable_on_empty_is_empty() -> None:
    assert filter_surfaceable([], Trust.GUEST) == ()
