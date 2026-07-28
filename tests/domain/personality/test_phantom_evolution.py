# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for phantom_evolution.evolve_phantoms — the pure phantom-membership kernel.

Bob's phantom preferences come alive: a grounded fresh symphony can emerge from a
real strong taste/reflection, an old one fades, the set stays bounded, and the
step is slow, seeded-deterministic and idempotent (no churn without material).
"""

from __future__ import annotations

from random import Random

from bob.personality.phantom_evolution import (
    PhantomSignals,
    evolve_phantoms,
)


def _always_fires() -> Random:
    """An RNG whose first ``random()`` draw is below any sane change-rate gate."""

    class _Stub(Random):
        def random(self) -> float:
            return 0.0

    return _Stub()


def _never_fires() -> Random:
    """An RNG whose first ``random()`` draw is above any sane change-rate gate."""

    class _Stub(Random):
        def random(self) -> float:
            return 0.999999

    return _Stub()


def test_emergence_adds_a_grounded_candidate() -> None:
    # Arrange: a real strong taste surfaces as a candidate phantom.
    phantoms = ("кофе", "дождь")
    signals = PhantomSignals(candidate="ночные поезда", max_count=5)

    # Act: with the change gate open, the grounded candidate emerges.
    evolved = evolve_phantoms(phantoms, signals, rng=_always_fires())

    # Assert: the new phantom joins the set; nothing fabricated beyond the candidate.
    assert "ночные поезда" in evolved
    assert set(evolved) - set(phantoms) == {"ночные поезда"}


def test_no_fabrication_without_material_is_a_noop() -> None:
    # Arrange: no candidate, set within bounds — there is nothing to ground a change.
    phantoms = ("кофе", "дождь", "книги")
    signals = PhantomSignals(candidate=None, max_count=5)

    # Act: even with the gate wide open, no material means no invented phantom.
    evolved = evolve_phantoms(phantoms, signals, rng=_always_fires())

    # Assert: identical membership — Bob never invents a preference.
    assert evolved == phantoms


def test_blank_candidate_is_treated_as_no_material() -> None:
    # Arrange
    phantoms = ("кофе",)
    signals = PhantomSignals(candidate="   ", max_count=5)

    # Act
    evolved = evolve_phantoms(phantoms, signals, rng=_always_fires())

    # Assert: whitespace is not grounding.
    assert evolved == phantoms


def test_emergence_over_bound_fades_the_oldest() -> None:
    # Arrange: already at the max; a fresh grounded candidate wants in.
    phantoms = ("кофе", "дождь", "книги")
    signals = PhantomSignals(candidate="ночные поезда", max_count=3)

    # Act
    evolved = evolve_phantoms(phantoms, signals, rng=_always_fires())

    # Assert: bounded — the newest joins, the oldest ("кофе", at the front) fades out.
    assert len(evolved) == 3
    assert "ночные поезда" in evolved
    assert "кофе" not in evolved
    assert "дождь" in evolved
    assert "книги" in evolved


def test_membership_changes_by_at_most_one_per_step() -> None:
    # Arrange: a grounded candidate, room to grow (slow membership change).
    phantoms = ("кофе", "дождь")
    signals = PhantomSignals(candidate="ночные поезда", max_count=5)

    # Act
    evolved = evolve_phantoms(phantoms, signals, rng=_always_fires())

    # Assert: exactly one phantom added, none dropped — a single small step.
    added = set(evolved) - set(phantoms)
    dropped = set(phantoms) - set(evolved)
    assert len(added) == 1
    assert len(dropped) == 0


def test_change_is_gated_slow_when_rng_does_not_fire() -> None:
    # Arrange: a grounded candidate but the slowness gate stays shut this step.
    phantoms = ("кофе", "дождь")
    signals = PhantomSignals(candidate="ночные поезда", max_count=5)

    # Act
    evolved = evolve_phantoms(phantoms, signals, rng=_never_fires())

    # Assert: slow — most steps leave the set untouched.
    assert evolved == phantoms


def test_idempotent_when_candidate_already_present() -> None:
    # Arrange: the candidate is already a phantom — re-grounding must not churn.
    phantoms = ("кофе", "ночные поезда")
    signals = PhantomSignals(candidate="ночные поезда", max_count=5)

    # Act: a double run with the gate open.
    once = evolve_phantoms(phantoms, signals, rng=_always_fires())
    twice = evolve_phantoms(once, signals, rng=_always_fires())

    # Assert: no churn — an already-present candidate is a no-op both times.
    assert once == phantoms
    assert twice == phantoms


def test_double_run_settles_after_one_effect() -> None:
    # Arrange: emergence happens once, then the candidate is present → idempotent.
    phantoms = ("кофе", "дождь")
    signals = PhantomSignals(candidate="ночные поезда", max_count=5)

    # Act
    once = evolve_phantoms(phantoms, signals, rng=_always_fires())
    twice = evolve_phantoms(once, signals, rng=_always_fires())

    # Assert: the second identical run adds nothing further.
    assert "ночные поезда" in once
    assert twice == once


def test_deterministic_under_seed() -> None:
    # Arrange: the same seed must reproduce the same membership outcome.
    phantoms = ("кофе", "дождь")
    signals = PhantomSignals(candidate="ночные поезда", max_count=5)

    # Act
    a = evolve_phantoms(phantoms, signals, rng=Random(7))
    b = evolve_phantoms(phantoms, signals, rng=Random(7))

    # Assert: seeded RNG → reproducible evolution.
    assert a == b


def test_existing_phantoms_preserved_on_emergence() -> None:
    # Arrange
    phantoms = ("кофе", "дождь")
    signals = PhantomSignals(candidate="ночные поезда", max_count=5)

    # Act
    evolved = evolve_phantoms(phantoms, signals, rng=_always_fires())

    # Assert: relative order of the survivors is preserved (newest appended last).
    assert evolved[: len(phantoms)] == phantoms
    assert evolved[-1] == "ночные поезда"
