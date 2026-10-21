# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root roster config — the ``social.roster.*`` reader behind its flag (BOB-080).

The roster («состав комнаты» Bob recalls by social occasion) ships inert behind the bare
``social.roster`` flag (mirroring ``presence.stream_read`` — a bare boolean, not the nested
``<section>.enabled`` convention). This is the ONE place that flag + its thresholds are read
into a :class:`RosterConfig`: ``roster_newcomer_days`` (the time-window that makes someone a
newcomer) and ``roster_limit`` (the cap on named members). Off (the default) → ``enabled``
is ``False`` so bead .2's usecase builds no roster (zero behaviour change).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.runtime.config import _flag, _float_or, _int, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["RosterConfig", "build_roster_config"]

# Conservative roster defaults: someone counts as a newcomer for a week, and Bob names
# at most a handful so a recall stays compact (INV-4, anti-flood).
_DEFAULT_NEWCOMER_DAYS = 7.0
_DEFAULT_LIMIT = 6


@dataclass(frozen=True, slots=True)
class RosterConfig:
    """The resolved ``social.roster.*`` settings the roster usecase (bead .2) consumes."""

    enabled: bool
    newcomer_days: float
    limit: int


def build_roster_config(config: Mapping[str, object]) -> RosterConfig:
    """Read the ``social.roster`` flag + thresholds into a :class:`RosterConfig`.

    Off by default (the whole roster epic ships as one piece behind the flag). The
    ``roster_newcomer_days`` / ``roster_limit`` knobs fall back to conservative defaults
    when absent or malformed. This accessor never builds the usecase — bead .2 does.
    """
    section = _section(config, "social")
    return RosterConfig(
        enabled=_flag(section, "roster"),
        newcomer_days=_float_or(section, "roster_newcomer_days", _DEFAULT_NEWCOMER_DAYS),
        limit=_int(section, "roster_limit", _DEFAULT_LIMIT),
    )
