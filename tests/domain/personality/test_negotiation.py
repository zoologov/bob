# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Negotiation — deterministic text-zone stance (no I/O, no visuals)."""

from __future__ import annotations

import pytest

from bob.domain.personality.negotiation import (
    Negotiation,
    NegotiationZone,
    Stance,
)


def test_user_domain_always_concedes_regardless_of_conviction() -> None:
    # Arrange: the user's own domain — Bob defers even when he cares.
    negotiation = Negotiation()

    # Act
    stance = negotiation.decide(NegotiationZone.USER_DOMAIN, conviction=0.95)

    # Assert
    assert stance is Stance.CONCEDE


def test_bob_personal_high_conviction_proposes_alternative() -> None:
    # Arrange: Bob's own domain + a firmly held view → he pushes back.
    negotiation = Negotiation()

    # Act
    stance = negotiation.decide(NegotiationZone.BOB_PERSONAL, conviction=0.9)

    # Assert
    assert stance is Stance.PROPOSE_ALTERNATIVE


def test_bob_personal_low_conviction_agrees() -> None:
    # Arrange: Bob's domain but he barely cares → he goes along.
    negotiation = Negotiation()

    # Act
    stance = negotiation.decide(NegotiationZone.BOB_PERSONAL, conviction=0.1)

    # Assert
    assert stance is Stance.AGREE


def test_shared_zone_high_conviction_proposes_alternative() -> None:
    # Arrange / Act
    stance = Negotiation().decide(NegotiationZone.SHARED, conviction=0.85)

    # Assert: in shared space a strong view earns a counter-proposal.
    assert stance is Stance.PROPOSE_ALTERNATIVE


def test_shared_zone_low_conviction_agrees() -> None:
    # Arrange / Act
    stance = Negotiation().decide(NegotiationZone.SHARED, conviction=0.2)

    # Assert
    assert stance is Stance.AGREE


def test_decide_rejects_out_of_range_conviction() -> None:
    # Arrange / Act / Assert: conviction is a [0, 1] strength.
    with pytest.raises(ValueError, match="conviction"):
        Negotiation().decide(NegotiationZone.SHARED, conviction=1.5)


def test_decide_is_deterministic() -> None:
    # Arrange
    negotiation = Negotiation()

    # Act / Assert: same zone + conviction → same stance, no randomness.
    first = negotiation.decide(NegotiationZone.SHARED, conviction=0.85)
    second = negotiation.decide(NegotiationZone.SHARED, conviction=0.85)
    assert first is second


def test_shared_zone_needs_more_conviction_than_bob_personal() -> None:
    # Arrange: a conviction between the two thresholds.
    negotiation = Negotiation()
    mid_conviction = 0.6

    # Act
    personal = negotiation.decide(NegotiationZone.BOB_PERSONAL, conviction=mid_conviction)
    shared = negotiation.decide(NegotiationZone.SHARED, conviction=mid_conviction)

    # Assert: Bob holds his own domain more firmly than shared space.
    assert personal is Stance.PROPOSE_ALTERNATIVE
    assert shared is Stance.AGREE
