# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Negotiation — how firmly Bob holds a position, by zone and conviction.

Three zones partition who owns the matter at hand: ``BOB_PERSONAL`` (Bob's own
domain), ``SHARED`` (jointly owned), and ``USER_DOMAIN`` (the user's own
business). Conviction (a ``[0, 1]`` strength) then decides how firmly Bob holds:
he concedes outright in the user's domain, but in his own or shared space a
firmly held view escalates from agreeing to proposing an alternative. In P0 this
acts only on **text/conversation** — there is no visual surface (rooms/clothes
return with the look in P1). The decision is pure and deterministic.
"""

from __future__ import annotations

from enum import Enum

from bob.personality.taste import Verdict

# Conviction is a [0, 1] strength of how firmly Bob holds a position.
_MIN_CONVICTION = 0.0
_MAX_CONVICTION = 1.0

# Per-zone conviction needed before Bob pushes back instead of agreeing. He
# defends his own domain more readily (lower bar) than shared space.
_BOB_PERSONAL_THRESHOLD = 0.5
_SHARED_THRESHOLD = 0.7


class NegotiationZone(Enum):
    """Who owns the matter under negotiation — sets how much Bob will hold."""

    BOB_PERSONAL = "bob_personal"
    SHARED = "shared"
    USER_DOMAIN = "user_domain"


class Stance(Enum):
    """Bob's conversational stance, from yielding to holding ground."""

    AGREE = "agree"
    PROPOSE_ALTERNATIVE = "propose_alternative"
    CONCEDE = "concede"


# Conviction threshold above which Bob proposes an alternative in a held zone.
# The user's own domain is absent: there Bob always concedes.
_PUSHBACK_THRESHOLD: dict[NegotiationZone, float] = {
    NegotiationZone.BOB_PERSONAL: _BOB_PERSONAL_THRESHOLD,
    NegotiationZone.SHARED: _SHARED_THRESHOLD,
}


class Negotiation:
    """Decide Bob's text-zone stance from the zone and his conviction."""

    def decide(self, zone: NegotiationZone, *, conviction: float) -> Stance:
        """Return Bob's deterministic stance for ``zone`` at ``conviction``.

        In the user's domain Bob always concedes. In his own or shared space he
        agrees below the zone's conviction threshold and proposes an alternative
        at or above it.
        """
        if not _MIN_CONVICTION <= conviction <= _MAX_CONVICTION:
            raise ValueError(
                f"conviction must be within "
                f"[{_MIN_CONVICTION}, {_MAX_CONVICTION}], got {conviction}"
            )
        if zone is NegotiationZone.USER_DOMAIN:
            return Stance.CONCEDE
        threshold = _PUSHBACK_THRESHOLD[zone]
        return Stance.PROPOSE_ALTERNATIVE if conviction >= threshold else Stance.AGREE


def _clamp_conviction(value: float) -> float:
    """Saturate ``value`` into the conviction bounds Negotiation requires."""
    return max(_MIN_CONVICTION, min(_MAX_CONVICTION, value))


# Stance→prompt directive (BOB-013 Phase 1): the negotiation stance augments —
# never replaces — the warm base tone, so Bob stays warm without being a yes-man.
# These are a pure mapping; no extra LLM call. A stance with no directive (none
# below) leaves the prompt exactly as it was before BOB-013.
_STANCE_DIRECTIVE: dict[Stance, str] = {
    # Russian persona directives (project language); Cyrillic look-alikes are
    # intentional, so the ambiguous-character lint is silenced for these literals.
    Stance.CONCEDE: "Стойка: это территория пользователя — спокойно прими его выбор.",  # noqa: RUF001
    Stance.AGREE: "Стойка: у тебя нет сильной позиции — поддержи, без навязывания.",  # noqa: RUF001
    Stance.PROPOSE_ALTERNATIVE: (
        "Стойка: у тебя есть своё мнение и убеждённость — аргументируй и предложи "  # noqa: RUF001
        "своё, уважительно, без агрессии и без капитуляции."
    ),
}


def _stance_directive(
    stance: Stance, *, verdict: Verdict, zone: NegotiationZone
) -> str:
    """Map a stance to its prompt directive, gated to a real negotiation signal.

    The directive is emitted only when there is something to negotiate: Bob holds
    an opinion on the topic (a non-NEUTRAL verdict) or the matter is explicitly
    the user's domain (a logistics signal). A neutral, jointly-owned topic carries
    no directive, so that path behaves exactly as it did before BOB-013.
    """
    has_signal = verdict is not Verdict.NEUTRAL or zone is NegotiationZone.USER_DOMAIN
    if not has_signal:
        return ""
    return _STANCE_DIRECTIVE.get(stance, "")
