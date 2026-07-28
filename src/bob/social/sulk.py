# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Sulk — Bob's обида/охлаждение state, the bottom of the engagement axis (BOB-014 .2b).

Bob can get genuinely hurt — but as a CHARACTER, never as a book-Exodus hard reset.
This is a pure affect state with stakes, modelled with the same guardrails as the
rest of his personality (a threshold + sustaining, bounded dynamics, a GUARANTEED
exit). Crucially, обида touches NO memory and NO soul — Bob "отходит", he never
"уходит":

* **Entry needs a threshold AND sustaining.** A single bad message — or casual мат —
  never enters обида. Only when the OWNER relationship sits critically low (cold
  warmth at-or-below ``critical_warmth``, OR a turn carrying DIRECTED hostility) for
  a SUSTAINED run of ``sustain_count`` observations does Bob enter — the obida reacts
  to sustained directed hostility, not to one number or to vocabulary. A healthy turn
  in between resets the streak, so intermittent dips never accrete into обида.
* **Cold-but-still-Bob while sulking.** The state carries an ``intensity`` (0..1) that
  the voice/governance read; the tone goes quieter and curt (see
  :func:`~bob.personality.voice.sulk_directive`), never a personality reset.
* **A GUARANTEED exit.** :func:`recover` decays ``intensity`` purely by elapsed time
  (so Bob always отходит even with zero warmth — no permanent lock-out), and тёплые
  сообщения (a positive ``warmth_delta``) accelerate the decay. Below ``exit_intensity``
  обида ends and the one-shot ``announced`` flag is cleared so a future entry announces
  afresh.

No I/O, no clock — elapsed time and signals are passed in (the clock lives in the
application layer), so every transition is deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "SulkConfig",
    "SulkState",
    "observe_relationship",
    "recover",
]

# Intensity is a bounded scalar in the closed unit interval [0, 1].
_MIN_INTENSITY = 0.0
_MAX_INTENSITY = 1.0

# Default critical warmth: the OWNER relationship warmth at/below which a turn counts
# as a "low" observation toward обида. Negative, so only a genuinely cold relationship
# (not a neutral one) can build a streak.
_DEFAULT_CRITICAL_WARMTH = -0.4

# Default sustaining: how many consecutive low/hostile observations are needed before
# Bob enters обида. Greater than one, so a single bad message never trips it.
_DEFAULT_SUSTAIN_COUNT = 3

# Intensity обида starts at on entry — full, then it decays.
_DEFAULT_ENTER_INTENSITY = 1.0

# Below this intensity обида ends (Bob has отошёл). Small and positive so a tiny
# residue still counts as recovered.
_DEFAULT_EXIT_INTENSITY = 0.05

# How fast intensity decays per second of elapsed time — the GUARANTEE of exit (by
# time alone, with no warmth at all). Tuned so обида measured in hours, not forever.
_DEFAULT_DECAY_PER_SECOND = 1.0 / 7200.0

# Extra decay (added to the per-second decay) per unit of POSITIVE warmth_delta on a
# recovery step — тёплые сообщения accelerate отход. Only positive warmth helps.
_DEFAULT_WARMTH_DECAY_BONUS = 0.3


def _clamp_intensity(value: float) -> float:
    """Saturate ``value`` into the [0, 1] intensity bounds rather than overflowing."""
    return max(_MIN_INTENSITY, min(_MAX_INTENSITY, value))


@dataclass(frozen=True, slots=True)
class SulkConfig:
    """Tunable обида thresholds + dynamics (injected from ``sulk.*`` config).

    ``critical_warmth`` — owner warmth at/below which a turn is a "low" observation;
    ``sustain_count`` — consecutive low/hostile observations needed to enter (> 1, so
    one bad message never trips it); ``enter_intensity`` — the intensity on entry;
    ``exit_intensity`` — the intensity below which обида ends; ``decay_per_second`` —
    the time-only decay that GUARANTEES exit; ``warmth_decay_bonus`` — extra decay per
    unit of positive warmth, so тёплые сообщения accelerate отход. The defaults make a
    single dip / casual мат harmless and a sustained cold/hostile run enter обида,
    while time alone always brings Bob back.
    """

    critical_warmth: float = _DEFAULT_CRITICAL_WARMTH
    sustain_count: int = _DEFAULT_SUSTAIN_COUNT
    enter_intensity: float = _DEFAULT_ENTER_INTENSITY
    exit_intensity: float = _DEFAULT_EXIT_INTENSITY
    decay_per_second: float = _DEFAULT_DECAY_PER_SECOND
    warmth_decay_bonus: float = _DEFAULT_WARMTH_DECAY_BONUS


@dataclass(frozen=True, slots=True)
class SulkState:
    """Bob's обида state — active flag, bounded intensity, entry stamp, and flags.

    ``active`` — whether Bob is обижен right now; ``intensity`` — how hurt (0..1),
    decaying toward exit; ``low_streak`` — the running count of consecutive low/hostile
    observations (resets on a healthy turn), the "sustaining" half of the entry
    threshold; ``since`` — when this обида was entered (``None`` when not sulking);
    ``announced`` — the one-shot flag so GUPPI announces обида exactly once per entry.
    This carries NO memory and NO soul — an обида never touches Bob's identity (anti-
    Exodus).
    """

    active: bool = False
    intensity: float = _MIN_INTENSITY
    low_streak: int = 0
    since: datetime | None = None
    announced: bool = False


def observe_relationship(
    state: SulkState,
    *,
    owner_warmth: float,
    hostile: bool,
    now: datetime,
    config: SulkConfig | None = None,
) -> SulkState:
    """Fold one OWNER turn into обида state — pure threshold + sustaining (BOB-014 .2b).

    A turn is a "low" observation when the owner warmth is at/below ``critical_warmth``
    OR the turn carried DIRECTED ``hostile`` ity (so обида reacts to sustained directed
    hostility, not to a low number alone, and never to casual мат — that is not flagged
    hostile by the perception layer). A low observation extends ``low_streak``; a
    healthy turn RESETS it (intermittent dips never accrete). Once the streak reaches
    ``sustain_count`` Bob ENTERS обида at ``enter_intensity`` and stamps ``since``.

    Idempotent once sulking: a further low observation does not re-stamp the entry nor
    inflate intensity past the cap (recovery, not observation, lowers intensity). Pure
    and deterministic: same inputs → same state.
    """
    cfg = config if config is not None else SulkConfig()
    is_low = owner_warmth <= cfg.critical_warmth or hostile
    if not is_low:
        # A healthy turn breaks the run — обида never builds from intermittent dips.
        # An ACTIVE обида is left to the recovery path; only the streak is reset.
        return replace(state, low_streak=0)

    streak = state.low_streak + 1
    if state.active:
        # Already обижен: keep the (capped) intensity + entry stamp stable; just track
        # the streak. Recovery — not observation — is what lowers intensity.
        return replace(state, low_streak=streak)
    if streak >= cfg.sustain_count:
        # Sustained critical drop → enter обида.
        return SulkState(
            active=True,
            intensity=_clamp_intensity(cfg.enter_intensity),
            low_streak=streak,
            since=now,
            announced=False,
        )
    return replace(state, low_streak=streak)


def recover(
    state: SulkState,
    *,
    elapsed_seconds: float,
    warmth_delta: float = 0.0,
    config: SulkConfig | None = None,
) -> SulkState:
    """Decay обида over elapsed time (+ warmth), exiting below the floor (BOB-014 .2b).

    Intensity falls by ``decay_per_second`` * ``elapsed_seconds`` — the GUARANTEE of
    exit, since time alone (with zero warmth) always brings it down — plus an extra
    ``warmth_decay_bonus`` * positive ``warmth_delta`` so тёплые сообщения accelerate
    отход (negative warmth never deepens обида here; that is the observation path's
    job). Below ``exit_intensity`` обида ENDS: ``active`` clears, intensity floors to
    zero, ``since`` is dropped, and the one-shot ``announced`` flag is reset so the
    NEXT entry announces afresh.

    A no-op when Bob is not обижен (recovery never reactivates обида or "sticks").
    Pure: elapsed time is passed in, so it is deterministic and unit-testable.
    """
    if elapsed_seconds < 0.0:
        raise ValueError(f"elapsed seconds must be non-negative, got {elapsed_seconds}")
    if not state.active:
        return state
    cfg = config if config is not None else SulkConfig()
    warmth_help = max(0.0, warmth_delta) * cfg.warmth_decay_bonus
    decayed = _clamp_intensity(
        state.intensity - elapsed_seconds * cfg.decay_per_second - warmth_help
    )
    if decayed <= cfg.exit_intensity:
        return SulkState(low_streak=0)
    return replace(state, intensity=decayed)
