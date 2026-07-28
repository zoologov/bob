# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=application

"""RecordOwnerActivity — fold an incoming owner message into proactivity state.

The reactive chat path (:class:`~bob.application.usecases.handle_message.HandleMessage`)
calls this after each owner message so the proactivity drive-model reflects real
interaction: it stamps ``last_user_msg_at`` to the injected ``now`` — which arms
the engine's owner-cooldown veto so Bob never talks over the person — and
partially restores the :class:`~bob.proactivity.social_energy.SocialEnergy`
reservoir (the "you came back" bump), yielding a natural cooldown after a reply.

The rest of the per-persona state is preserved verbatim: the owner's ``/quiet``
mute (``proactivity_enabled``) survives an incoming message, and ``last_spoke_at``
is untouched. Time is injected via :class:`~bob.kernel.ports.Clock`; the use-case
holds no globals and is deterministic in tests.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.kernel.ports import Clock
    from bob.proactivity.ports import ProactivityStore


class RecordOwnerActivity:
    """Stamp the owner-message marker and restore some social energy, per persona."""

    def __init__(
        self, *, store: ProactivityStore, clock: Clock, persona_id: str = "bob"
    ) -> None:
        self._store = store
        self._clock = clock
        self._persona_id = persona_id

    async def run(self) -> None:
        """Record that the owner just wrote: stamp the marker, restore energy."""
        state = await self._store.load(self._persona_id)
        updated = replace(
            state,
            social_energy=state.social_energy.replenish_from_reply(),
            last_user_msg_at=self._clock.now(),
        )
        await self._store.save(self._persona_id, updated)
