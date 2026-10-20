# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Sulk state — Bob's обида/охлаждение (BOB-014 .2b): the shared VALUE.

:class:`SulkState` carries the active flag, a bounded ``intensity`` in
``[MIN_INTENSITY, MAX_INTENSITY]`` (the closed unit interval), the sustaining
``low_streak``, the entry stamp and the one-shot ``announced`` flag. It carries NO
memory and NO soul — an обида never touches Bob's identity (anti-Exodus).

Why the shared kernel (BOB-113, RFC D): the state is read below ``social`` in the
runtime order — ``personality`` (``voice.sulk_directive``) and ``conversation`` take it
in their signatures — so declared in ``social`` it pulled them into an upward edge. The
BEHAVIOUR stays in ``social``: :class:`~bob.social.sulk.SulkConfig`,
:func:`~bob.social.sulk.observe_relationship` (threshold + sustaining) and
:func:`~bob.social.sulk.recover` (the guaranteed exit). Value only here; no
first-party import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["MAX_INTENSITY", "MIN_INTENSITY", "SulkState"]

# Intensity is a bounded scalar in the closed unit interval [0, 1].
MIN_INTENSITY = 0.0
MAX_INTENSITY = 1.0


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
    intensity: float = MIN_INTENSITY
    low_streak: int = 0
    since: datetime | None = None
    announced: bool = False
