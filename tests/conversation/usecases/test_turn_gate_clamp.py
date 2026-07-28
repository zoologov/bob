# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit test for the turn-gate unit-interval clamp (BOB-062.7a).

``_clamp_unit`` is the generic ``[0, 1]`` saturation the legacy addressivity path
applies to the self-improvement ADDRESSIVITY_BIAS tilt (a bounded nudge on top of the
policy interest — never a base override, never able to silence Bob). It lives beside
its only consumer in ``turn_gate`` (relocated out of ``proactivity.self_improvement``
in BOB-062.7a to break a conversation↔proactivity import cycle). These pin the
saturation contract at the boundary values.
"""

from __future__ import annotations

from bob.conversation.usecases.turn_gate import _clamp_unit


def test_clamp_unit_keeps_value_inside_the_unit_interval() -> None:
    assert _clamp_unit(0.5) == 0.5


def test_clamp_unit_floors_negative_to_zero() -> None:
    assert _clamp_unit(-0.3) == 0.0


def test_clamp_unit_caps_above_one_to_one() -> None:
    assert _clamp_unit(1.4) == 1.0
