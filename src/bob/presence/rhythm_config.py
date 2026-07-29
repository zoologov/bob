# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""RhythmConfig — the tunable knobs of Bob's presence rhythm layer (pure config).

One frozen value object gathers every threshold the three rhythm policies read —
share-of-voice damping, natural-delay flooring, and reaction budgeting — so the
composition root can build them from ``presence.rhythm.*`` config in one place and
the domain stays free of literals. All defaults keep the layer gentle: a soft
ceiling that never fully silences Bob (INV-3 anti-script), a human but short delay
floor, and a like budget that admits at most one reaction per short series.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RhythmConfig:
    """Tunables for the presence rhythm policies (share / delay / reactions)."""

    # ── Share of voice (ambient ceiling) ─────────────────────────────────────
    # The floor a damping multiplier never drops below: even when Bob dominates,
    # p(barge) is only *scaled down*, never zeroed — the ceiling is a soft nudge,
    # not a hard mute (INV-3). > 0 keeps Bob a probabilistic, not scripted, speaker.
    share_min_multiplier: float = 0.05
    # How sharply damping bites as Bob's share runs past his fair target share.
    share_steepness: float = 2.0

    # ── Natural delay (human floor) ──────────────────────────────────────────
    # A short "he noticed and is reacting" base, before any reading/typing time.
    delay_base_seconds: float = 1.5
    # Seconds of "reading + typing" per character of the drafted reply.
    delay_seconds_per_char: float = 0.03
    # How much a long/complex reply stretches the floor (multiplies complexity).
    delay_complexity_seconds: float = 4.0
    # The hard cap so a huge draft never floors an absurd wait.
    delay_max_seconds: float = 12.0
    # How much urgency (a demanded, time-critical answer) shortens the floor,
    # as a fraction: urgency=1.0 removes this share of the computed floor.
    delay_urgency_relief: float = 0.8

    # ── Reaction budget (separate like limits) ───────────────────────────────
    # The shortest gap (seconds) between two of Bob's likes — one per series.
    reaction_min_gap_seconds: float = 90.0
    # A like is only worth spending on a genuinely notable message.
    reaction_quality_threshold: float = 0.6
