# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The relationship VALUE's invariant (BOB-113, bob-etb.8): each axis in ``[-1, 1]``, inclusive.

The behaviour that accrues a relationship is tested in
``tests/domain/personality/test_relationship.py``; this file pins the kernel value's own
rule — both edges of the closed interval accepted, the nearest value past either edge
rejected, on EVERY one of the four axes (so dropping an axis or turning ``<=`` into ``<``
cannot pass), with the offending axis named in the error.
"""

from __future__ import annotations

import pytest

from bob.kernel.relationship import MAX_AXIS, MIN_AXIS, Relationship

_AXES = ("trust", "respect", "warmth", "compatibility")
_JUST_PAST = 1e-9


def test_the_bounds_are_the_closed_unit_interval() -> None:
    assert (MIN_AXIS, MAX_AXIS) == (-1.0, 1.0)


@pytest.mark.parametrize("axis", _AXES)
@pytest.mark.parametrize("value", [MIN_AXIS, MAX_AXIS, 0.0])
def test_every_axis_accepts_both_edges_of_the_interval(axis: str, value: float) -> None:
    relationship = Relationship(sender_id=1, **{axis: value})

    assert getattr(relationship, axis) == value


@pytest.mark.parametrize("axis", _AXES)
@pytest.mark.parametrize("value", [MIN_AXIS - _JUST_PAST, MAX_AXIS + _JUST_PAST])
def test_every_axis_rejects_the_nearest_value_past_either_edge(axis: str, value: float) -> None:
    with pytest.raises(ValueError, match=rf"relationship axis '{axis}' must be within"):
        Relationship(sender_id=1, **{axis: value})
