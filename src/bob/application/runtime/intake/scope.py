# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""TurnScope (BOB-066 Срез 2.1) — the isolated per-turn context threaded through a turn.

Under the intake-развязка different chats run on different worker tasks concurrently, so a
single shared per-boot rng would interleave draws non-deterministically. :class:`TurnScope`
carries a per-turn :class:`~random.Random` seeded from the turn's ``(base_seed, chat_id,
message_id)`` coordinates, so every seeded draw of a turn (plan → engagement → verbosity →
addressivity → surface/ack) is reproducible independent of dispatch timing and never leaks
into another message/turn (INV-4). ``chat_id`` / ``message_id`` ride along so a later step
(staleness / catch-up) can identify the turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from bob.application.runtime.intake.decisions import derive_turn_seed
from bob.conversation.addressivity import ResponseOutcome


@dataclass(frozen=True, slots=True)
class TurnScope:
    """The isolated per-turn context: the turn's coordinates + its own seeded rng.

    ``series_ceiling`` (BOB-066 Срез W.2) CAPS this message's ambient outcome when several
    inbound settle in one intake window — the intake worker plans the burst (one addressed
    reply + a budget-capped like) and stamps each message's ceiling here. ``ENGAGE`` (the
    default / a single-message window / a focus message) is no cap; a direct address is
    answered ABOVE it (INV-1). Threaded on the scope (not the handler signature) so every
    existing handler seam is untouched.
    """

    chat_id: int
    message_id: int
    rng: Random
    series_ceiling: ResponseOutcome = ResponseOutcome.ENGAGE


def new_turn_scope(
    *,
    base_seed: int,
    chat_id: int,
    message_id: int,
    series_ceiling: ResponseOutcome = ResponseOutcome.ENGAGE,
) -> TurnScope:
    """Build the :class:`TurnScope` for one message, seeding its rng deterministically.

    The rng is seeded via :func:`~bob.application.runtime.intake.decisions.derive_turn_seed`
    so two messages of the same chat draw independently and the same turn always reproduces.
    ``series_ceiling`` (default ``ENGAGE`` — uncapped) rides along for the batch top-k budget.
    """
    seed = derive_turn_seed(base_seed=base_seed, chat_id=chat_id, message_id=message_id)
    return TurnScope(
        chat_id=chat_id,
        message_id=message_id,
        rng=Random(seed),  # noqa: S311
        series_ceiling=series_ceiling,
    )
