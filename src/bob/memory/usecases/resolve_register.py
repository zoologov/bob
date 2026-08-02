# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=application

"""RegisterResolver — per-turn DEV/CASUAL register resolution (BOB-087.C2).

The memory-side mirror of ``HandleMessage._surface_audience``: given a turn it decides the
conversational :class:`~bob.memory.register.Register` that colours recall. A turn is DEV if
EITHER a deterministic signal fires (it is in the dev-DM chat — ``coder.dev_dm_chat_id``, a
1:1 operator channel) OR the cheap Tier-0 :class:`~bob.memory.usecases.classify_work_talk.
ClassifyWorkTalk` judges the message to be about dev work (the owner's «direct question
surfaces work» mechanism, alive in ANY chat); otherwise CASUAL.

🔴 Tier-0 economy: the classifier is consulted ONLY when the recall pool actually holds work
episodes (``pool_has_work``). With nothing to mute, muting is a no-op, so there is no reason
to burn a local call — the register is CASUAL (or DEV by the deterministic signal) and the
register filter passes through. Resilience lives in the classifier (a fault → chat), so a
model hiccup never crashes recall.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.memory.register import Register

if TYPE_CHECKING:
    from bob.application.runtime.events import MessageReceived

__all__ = ["RegisterResolver", "WorkTalkClassifier"]


class WorkTalkClassifier(Protocol):
    """The Tier-0 «is this turn about dev work?» seam the resolver consults."""

    async def is_work_talk(self, text: str) -> bool: ...


class RegisterResolver:
    """Resolve a turn's DEV/CASUAL register from a deterministic signal + Tier-0 judge."""

    def __init__(
        self,
        *,
        classify_work_talk: WorkTalkClassifier,
        dev_dm_chat_id: int | None = None,
    ) -> None:
        self._classify = classify_work_talk
        self._dev_dm_chat_id = dev_dm_chat_id

    async def resolve(
        self, event: MessageReceived, *, pool_has_work: bool
    ) -> Register:
        """Resolve the register for ``event`` (DEV/CASUAL).

        DEV when the deterministic dev-context signal fires; else — only if the pool has
        work to mute — DEV when the Tier-0 classifier judges the message about dev work.
        CASUAL otherwise. The ``pool_has_work`` short-circuit keeps a work-free turn off
        the local model (and the register filter a no-op).
        """
        if self._is_dev_context(event):
            return Register.DEV
        if not pool_has_work:
            return Register.CASUAL
        if await self._classify.is_work_talk(event.text):
            return Register.DEV
        return Register.CASUAL

    def _is_dev_context(self, event: MessageReceived) -> bool:
        """The deterministic DEV signal: the turn is in the dev-DM operator channel."""
        return (
            self._dev_dm_chat_id is not None
            and event.chat_id == self._dev_dm_chat_id
        )
