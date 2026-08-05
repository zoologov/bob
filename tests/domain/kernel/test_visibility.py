# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the shared PRIVACY-axis vocabulary + inheritance rule — bob-g7t.

``strictest_visibility`` is the pure rule a DERIVED memory record (today: the
consolidation digest) uses to decide which privacy label it carries: the strictest
label present among its sources. The rule lives in the kernel because it is a shared
*term* — ``memory`` mints derived records, ``social`` decides tact on them — and a
peer ``memory → social`` import closes a node cycle (proved by ``beadloom lint``).

Covered here: one private source outweighs any number of public ones (strictest, not
majority and not last); an all-public / all-legacy-NULL set stays public; an
unrecognised tag reads as public exactly as :func:`bob.social.disclosure.may_surface`
reads it; an EMPTY source set is private (fail-safe — public is a claim that needs a
source to back it); and the kernel words do not drift from the social ones.
"""

from __future__ import annotations

from bob.kernel.visibility import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    is_owner_private,
    strictest_visibility,
)
from bob.social import disclosure


def test_one_private_source_makes_the_derived_record_private() -> None:
    """A single owner-private source outweighs the public majority — strictest wins."""
    labels = [VISIBILITY_PUBLIC, VISIBILITY_PUBLIC, VISIBILITY_OWNER_PRIVATE]

    assert strictest_visibility(labels) == VISIBILITY_OWNER_PRIVATE


def test_a_private_source_is_not_outvoted_by_position() -> None:
    """The rule is not «the last source wins»: a private FIRST source still decides."""
    assert (
        strictest_visibility([VISIBILITY_OWNER_PRIVATE, VISIBILITY_PUBLIC])
        == VISIBILITY_OWNER_PRIVATE
    )


def test_all_public_sources_stay_public() -> None:
    """Nothing private went in, so nothing private comes out — no over-labelling."""
    assert (
        strictest_visibility([VISIBILITY_PUBLIC, VISIBILITY_PUBLIC]) == VISIBILITY_PUBLIC
    )


def test_legacy_unlabelled_sources_read_as_public() -> None:
    """``NULL`` = public (the deliberate fail-open of a PERMISSION label, BOB-066 2.6)."""
    assert strictest_visibility([None, None, VISIBILITY_PUBLIC]) == VISIBILITY_PUBLIC


def test_an_unrecognised_tag_reads_as_public() -> None:
    """An unknown word is never allowed to silently hide public memory (as may_surface)."""
    assert strictest_visibility(["weird-future-tag"]) == VISIBILITY_PUBLIC


def test_the_private_tag_is_matched_case_insensitively() -> None:
    """A differently-cased tag is the SAME permission — casing must not launder it."""
    assert strictest_visibility(["  Owner_Private "]) == VISIBILITY_OWNER_PRIVATE


def test_no_sources_at_all_is_private() -> None:
    """Fail-safe: «публично» is a claim, and with zero sources there is nothing to back it."""
    assert strictest_visibility([]) == VISIBILITY_OWNER_PRIVATE


def test_is_owner_private_is_the_single_privacy_predicate() -> None:
    """The one definition of «приватное» on this axis — used by the rule above."""
    assert is_owner_private(VISIBILITY_OWNER_PRIVATE)
    assert is_owner_private("OWNER_PRIVATE")
    assert not is_owner_private(VISIBILITY_PUBLIC)
    assert not is_owner_private(None)
    assert not is_owner_private("")


def test_the_kernel_words_do_not_drift_from_the_social_ones() -> None:
    """🔴 Drift guard: ``social.disclosure`` still declares its own copies of these two
    PERSISTED literals (pointing it at the kernel was out of scope — ``social/**`` was a
    parallel agent's live zone in this wave). Until it imports them, this assert is what
    makes a divergence impossible to land silently.
    """
    assert disclosure.VISIBILITY_PUBLIC == VISIBILITY_PUBLIC
    assert disclosure.VISIBILITY_OWNER_PRIVATE == VISIBILITY_OWNER_PRIVATE
