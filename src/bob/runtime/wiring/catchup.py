# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root catch-up wiring — «догоняющий» behind ``presence.catchup``.

The catch-up re-entry seam (BOB-066 Срез W.3): this is the ONE place the ``presence.catchup``
flag is read and the
:class:`~bob.application.runtime.catch_up_reentry.CatchUpReentry` collaborator is assembled over
Bob's clock + late-resolved user-id source. Off (the default — the whole «человеческое групповое
присутствие» epic ships as one piece) it is ``None`` so the intake worker replays every drained
batch exactly as before and Bob is byte-identical.

The flag follows the nested ``<section>.enabled`` convention; the away threshold + ambient
budget live under ``presence.catchup.{absence_hours,budget}``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.runtime.catch_up_reentry import CatchUpReentry
from bob.runtime.config import _flag, _float_or, _int, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.usecases.handle_message import BobUserIdSource
    from bob.kernel.ports import Clock

# The gap (hours) beyond which a drained batch reads as a re-entry (Bob was away), and the
# default total action budget for one catch-up pass (every focal message plus ambient up to it).
_DEFAULT_ABSENCE_HOURS = 4.0
_DEFAULT_CATCHUP_BUDGET = 3


def build_catch_up_reentry(
    config: Mapping[str, object],
    *,
    clock: Clock,
    bob_user_id_source: BobUserIdSource,
) -> CatchUpReentry | None:
    """Assemble the catch-up re-entry collaborator, or ``None`` when ``presence.catchup`` is off.

    Off (the default) → ``None`` so the intake worker replays every batch as before
    (byte-identical). On → the collaborator over Bob's ``clock`` + user-id source, with the away
    threshold + ambient budget from ``presence.catchup.{absence_hours,budget}``.
    """
    catchup = _section(_section(config, "presence"), "catchup")
    if not _flag(catchup, "enabled"):
        return None
    return CatchUpReentry(
        clock=clock,
        bob_user_id_source=bob_user_id_source,
        absence_threshold_hours=_float_or(catchup, "absence_hours", _DEFAULT_ABSENCE_HOURS),
        budget=_int(catchup, "budget", _DEFAULT_CATCHUP_BUDGET),
        enabled=True,
    )
