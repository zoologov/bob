# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""Focus predicate (BOB-066 Срез 2.1) — is an inbound message a direct focus signal?

The intake debounce must never hold back a message that directly addresses Bob (INV-1/10),
so :class:`~bob.application.runtime.intake.inbox.ChatInbox` needs a cheap, synchronous
"is this focused?" check. It reuses the SAME pure detector the addressivity gate reads
(:func:`~bob.conversation.addressivity.classify_addressivity`) so "focus" here means exactly
``DIRECTED_TO_BOB`` — a @mention of Bob, a reply to one of Bob's messages, or a «Боб, …»
name-address. ``others_present`` is irrelevant to that classification (the detector ignores
it), so the check stays context-free and instant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.conversation.addressivity import Addressivity, classify_addressivity

if TYPE_CHECKING:
    from collections.abc import Callable

    from bob.application.runtime.events import MessageReceived
    from bob.application.usecases.handle_message import BobUserIdSource


def message_is_focused(message: MessageReceived, *, bob_user_id: int | None) -> bool:
    """Whether ``message`` directly addresses Bob (mention / reply-to-Bob / «Боб, …»)."""
    return (
        classify_addressivity(
            text=message.text,
            mentions_bob=message.mentions_bob,
            reply_to_sender_id=message.reply_to_sender_id,
            bob_user_id=bob_user_id,
            others_present=False,
        )
        is Addressivity.DIRECTED_TO_BOB
    )


def make_focus_predicate(
    bob_user_id_source: BobUserIdSource | None,
) -> Callable[[MessageReceived], bool]:
    """Bind a message→focus predicate over the late-resolved Bob ``user_id`` source.

    Bob's numeric id is resolved asynchronously at startup (long after wiring), so the id
    is read lazily per message through ``bob_user_id_source`` (``None`` until resolved —
    reply-to-Bob simply cannot fire yet, while @mention / name-address still do).
    """

    def is_focused(message: MessageReceived) -> bool:
        bob_user_id = bob_user_id_source() if bob_user_id_source is not None else None
        return message_is_focused(message, bob_user_id=bob_user_id)

    return is_focused
