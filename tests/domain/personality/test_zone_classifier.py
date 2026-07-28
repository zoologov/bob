# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for TasteZoneClassifier — deterministic zone heuristic (no LLM, no I/O).

A topic Bob holds a strong taste on maps to BOB_PERSONAL (his territory of
opinions); explicit user-logistics markers (schedule/time/volume) map to
USER_DOMAIN; everything else stays SHARED. Keywords and thresholds live in the
implementation; the port stays abstract (swappable for a Tier-0 LLM later).
"""

from __future__ import annotations

from bob.conversation.zone_classifier import TasteZoneClassifier
from bob.personality.negotiation import NegotiationZone
from bob.personality.taste import Verdict


def test_strong_taste_topic_is_bob_personal() -> None:
    # Arrange / Act: Bob holds a firm opinion (high conviction, strong verdict).
    zone = TasteZoneClassifier().classify(
        "jazz", taste_verdict=Verdict.LOVE, conviction=0.9
    )

    # Assert: it is his territory of opinions.
    assert zone is NegotiationZone.BOB_PERSONAL


def test_strong_negative_taste_topic_is_bob_personal() -> None:
    # Arrange / Act: a strong dislike is just as much Bob's territory.
    zone = TasteZoneClassifier().classify(
        "rain", taste_verdict=Verdict.HATE, conviction=0.9
    )

    # Assert
    assert zone is NegotiationZone.BOB_PERSONAL


def test_user_logistics_marker_is_user_domain() -> None:
    # Arrange / Act: an explicit schedule/time marker — the user's own business.
    zone = TasteZoneClassifier().classify(
        "во сколько встречаемся завтра", taste_verdict=Verdict.NEUTRAL, conviction=0.0
    )

    # Assert
    assert zone is NegotiationZone.USER_DOMAIN


def test_volume_marker_is_user_domain() -> None:
    # Arrange / Act: a "громче" (volume) logistics marker.
    zone = TasteZoneClassifier().classify(
        "сделай громче", taste_verdict=Verdict.NEUTRAL, conviction=0.0
    )

    # Assert
    assert zone is NegotiationZone.USER_DOMAIN


def test_neutral_topic_is_shared() -> None:
    # Arrange / Act: no strong taste, no logistics marker → jointly owned.
    zone = TasteZoneClassifier().classify(
        "что думаешь о погоде", taste_verdict=Verdict.NEUTRAL, conviction=0.0  # noqa: RUF001
    )

    # Assert
    assert zone is NegotiationZone.SHARED


def test_weak_taste_without_conviction_is_shared_not_bob_personal() -> None:
    # Arrange / Act: a mild like with low conviction is not yet Bob's hill.
    zone = TasteZoneClassifier().classify(
        "tea", taste_verdict=Verdict.LIKE, conviction=0.1
    )

    # Assert
    assert zone is NegotiationZone.SHARED


def test_logistics_marker_wins_even_over_a_taste_verdict() -> None:
    # Arrange / Act: logistics is the user's call regardless of Bob's opinion.
    zone = TasteZoneClassifier().classify(
        "когда включить джаз", taste_verdict=Verdict.LOVE, conviction=0.9
    )

    # Assert: the user owns the "when".
    assert zone is NegotiationZone.USER_DOMAIN
