# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""ShareOfVoiceGate (BOB-066 Срез 2.3) — the ambient-barge ceiling as one decision.

The application collaborator that applies Bob's soft share-of-voice ceiling to the
probability of barging into an ambient (un-addressed) message. It joins the durable
:class:`~bob.presence.ports.OutgoingActivityStore` (how much airtime Bob has taken in
this chat) with the pure
:class:`~bob.presence.share_of_voice.ShareOfVoicePolicy` (the damping curve), then
scales a caller-supplied base probability by the damping and compares it to a
caller-supplied random draw. Two invariants ride through by construction:

* **INV-1 (focus bypass):** ``focused=True`` makes the policy return a ``1.0``
  multiplier, so a direct address is never throttled by the ceiling.
* **INV-3 (anti-script):** the multiplier is a soft scaler ``> 0`` and the decision
  is a probabilistic draw, never a hard per-turn counter.
* **INV-4 (turn-local rng):** the random ``draw`` is passed IN (from the turn's
  :class:`~bob.application.runtime.intake.scope.TurnScope` rng), so concurrent chats
  never share a draw stream — the gate itself holds no rng.

The proactive tick can reuse the same gate (same per-chat window) so a proactive
barge sees a reply Bob just sent and damps itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.presence.ports import OutgoingActivityStore
    from bob.presence.share_of_voice import ShareOfVoicePolicy


class ShareOfVoiceGate:
    """Scales an ambient-barge probability by Bob's per-chat share-of-voice ceiling."""

    def __init__(
        self, store: OutgoingActivityStore, policy: ShareOfVoicePolicy
    ) -> None:
        self._store = store
        self._policy = policy

    async def admits_barge(
        self,
        *,
        chat_id: int,
        focused: bool,
        base_probability: float,
        draw: float,
    ) -> bool:
        """Return whether Bob may barge into this ambient turn under the ceiling.

        ``base_probability`` is the caller's un-ceiled p(barge); ``draw`` is a
        pre-sampled ``[0, 1)`` value from the turn-local rng. The effective
        probability is ``base_probability * damping``; the barge is admitted when
        ``draw`` falls under it. A focused message bypasses the ceiling (INV-1).
        """
        activity = await self._store.load(chat_id)
        multiplier = self._policy.damping(activity, focused=focused)
        return draw < base_probability * multiplier
