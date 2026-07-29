# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""Series-salience plan — the batch top-k action budget (BOB-066 Срез W.2, Пласт 3).

When several inbound messages settle in one intake window, a living participant does NOT
fire N replies — he answers the one addressed to him (or the most salient ambient line)
ONCE and, at most, drops a like on another. This pure core decides that, deterministically,
from the cheap per-message FOCUS signal the intake worker already has (a direct address vs
ambient chatter):

* 🔴 **INV-1** — every FOCUSED message (direct address to Bob) is a :data:`SeriesAction.REPLY`,
  NEVER dropped or downgraded by the budget, however many arrive at once.
* **One addressed reply** — with NO focus in the burst, only the FIRST ambient message earns a
  reply (the series' one barge-in); a focused burst spends its replies on the focus messages and
  the ambient ones around them collapse to a like/silence (Bob already engaged the addresser).
* **Reaction budget** — the remaining messages earn at most ``max_reactions`` likes
  (:data:`SeriesAction.REACT`), then :data:`SeriesAction.SILENT` — one gentle like per series,
  never a burst of them.

Module-level + deterministic (no I/O, no clock, no rng), so the collapse is exhaustively
truth-tabled and mutation-tested; the async intake worker stays a thin shell over it.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["SeriesAction", "plan_series_actions"]


class SeriesAction(Enum):
    """What Bob does about one message in a settled burst (the batch top-k verdict).

    * :data:`REPLY` — compose + send a reply (a focus message, or the series' one ambient barge).
    * :data:`REACT` — spend a like from the series' reaction budget (a notable-but-not-addressed
      message), never a full reply.
    * :data:`SILENT` — read it, add nothing (the burst already spent its reply + like budget).
    """

    REPLY = "reply"
    REACT = "react"
    SILENT = "silent"


def plan_series_actions(
    focused: Sequence[bool], *, max_reactions: int
) -> tuple[SeriesAction, ...]:
    """Assign each message in a settled burst its action, collapsing N inbound to one reply.

    ``focused[i]`` is whether message ``i`` directly addresses Bob (the cheap intake signal).
    🔴 Every focused message is a :data:`SeriesAction.REPLY` (INV-1 — never dropped). With NO
    focus in the burst the FIRST ambient message also replies (the one addressed reply for the
    series); the remaining messages earn up to ``max_reactions`` likes and then fall silent.
    Deterministic: same inputs → same plan.
    """
    has_focus = any(focused)
    ambient_reply_spent = False
    reactions_spent = 0
    plan: list[SeriesAction] = []
    for is_focused in focused:
        if is_focused:
            plan.append(SeriesAction.REPLY)
        elif not has_focus and not ambient_reply_spent:
            plan.append(SeriesAction.REPLY)
            ambient_reply_spent = True
        elif reactions_spent < max_reactions:
            plan.append(SeriesAction.REACT)
            reactions_spent += 1
        else:
            plan.append(SeriesAction.SILENT)
    return tuple(plan)
