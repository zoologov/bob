# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""TasteZoneClassifier — deterministic negotiation-zone heuristic (no LLM, no I/O).

The default realisation of the :class:`~bob.domain.ports.ZoneClassifier` port.
A topic Bob holds a strong taste on (an extreme verdict backed by conviction)
maps to ``BOB_PERSONAL`` — his territory of opinions, where he may push back.
Explicit user-logistics markers (schedule/time/volume — "когда", "во сколько",
"громче") map to ``USER_DOMAIN``, where Bob always concedes. Everything else
stays ``SHARED``. Logistics wins over taste: a "when" is the user's call even on
a topic Bob loves. Keywords and the conviction threshold live here, not in the
domain core — the port stays abstract so a Tier-0 LLM classifier swaps in later.
"""

from __future__ import annotations

from bob.personality.negotiation import NegotiationZone
from bob.personality.taste import Verdict

# A topic is Bob's own territory only when his opinion is firm: a strong
# (love/hate) verdict AND conviction at or above this bar.
_BOB_PERSONAL_CONVICTION_THRESHOLD = 0.5

# Verdicts that count as a strong, held opinion (vs a mild like/dislike/neutral).
_STRONG_VERDICTS = frozenset({Verdict.LOVE, Verdict.HATE})

# Explicit user-logistics markers: scheduling, timing, and volume — the user's
# own business, so Bob concedes. Matched case-insensitively as substrings.
_USER_DOMAIN_MARKERS: tuple[str, ...] = (
    "когда",
    "во сколько",
    "сколько времени",
    "расписан",
    "график",
    "громче",
    "тише",
    "громкость",
    "schedule",
    "volume",
    "louder",
)


class TasteZoneClassifier:
    """Deterministic taste/keyword classifier for negotiation zones."""

    def classify(
        self,
        topic: str,
        *,
        taste_verdict: Verdict,
        conviction: float,
    ) -> NegotiationZone:
        """Return the zone owning ``topic`` (logistics > strong taste > shared).

        Logistics markers take precedence: a scheduling/volume "when" is the
        user's call regardless of how strongly Bob feels about the subject.
        """
        if self._has_logistics_marker(topic):
            return NegotiationZone.USER_DOMAIN
        if self._is_strongly_held(taste_verdict, conviction):
            return NegotiationZone.BOB_PERSONAL
        return NegotiationZone.SHARED

    @staticmethod
    def _has_logistics_marker(topic: str) -> bool:
        text = topic.casefold()
        return any(marker in text for marker in _USER_DOMAIN_MARKERS)

    @staticmethod
    def _is_strongly_held(taste_verdict: Verdict, conviction: float) -> bool:
        return (
            taste_verdict in _STRONG_VERDICTS
            and conviction >= _BOB_PERSONAL_CONVICTION_THRESHOLD
        )
