# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""DecideResponse — assemble the context and ask the judge, by meaning (BOB-049).

The thin application use-case over the response-judgment seam: it gathers the
turn's pieces (the message, the sender as social context, the recent per-person
thread, the structural HINTS and the mood tone) into a
:class:`~bob.domain.personality.response_choice.ResponseContext` and delegates the
single semantic decision to the injected
:class:`~bob.domain.personality.response_choice.ResponseJudge`. It holds no policy
of its own — the structural signals are passed through as inputs, never as rules —
so the meaning-judgment lives entirely behind the (deterministic-in-tests) seam.

``handle_message`` wires this in BOB-049 .2; here it is the use-case plus its
context assembly only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.personality.addressivity import Addressivity
    from bob.domain.personality.response_choice import (
        ResponseChoice,
        ResponseJudge,
    )
    from bob.social.interlocutor import Interlocutor

from bob.domain.personality.response_choice import ResponseContext

__all__ = ["DecideResponse"]


class DecideResponse:
    """Assemble a :class:`ResponseContext` and decide via the injected judge."""

    def __init__(self, *, judge: ResponseJudge) -> None:
        self._judge = judge

    async def decide(
        self,
        *,
        text: str,
        interlocutor: Interlocutor,
        recent_thread: str,
        mentions_bob: bool,
        reply_to_bob: bool,
        addressivity: Addressivity,
        others_present: bool,
        floor_engaged: bool,
        mood_tone: str,
    ) -> ResponseChoice:
        """Assemble the turn's context and return the judge's :class:`ResponseChoice`.

        The structural arguments (``mentions_bob`` / ``reply_to_bob`` /
        ``addressivity`` / ``others_present`` / ``floor_engaged``) and the mood
        tone are carried into the context as HINTS the judge weighs by meaning —
        none forces the outcome.
        """
        ctx = ResponseContext(
            text=text,
            interlocutor=interlocutor,
            recent_thread=recent_thread,
            mentions_bob=mentions_bob,
            reply_to_bob=reply_to_bob,
            addressivity=addressivity,
            others_present=others_present,
            floor_engaged=floor_engaged,
            mood_tone=mood_tone,
        )
        return await self._judge.decide(ctx)
