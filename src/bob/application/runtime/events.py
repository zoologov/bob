# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Application-level events carried on the EventBus.

These are plain, frozen value objects the runtime and use-cases exchange. The
Telegram gateway (infrastructure) translates an inbound update into a
:class:`MessageReceived` and publishes it; a use-case (application) consumes it.
The event is an application concern — transport-agnostic data a use-case needs
to react — not an infrastructure detail, so it lives with the runtime that owns
the bus. :class:`MessageReceived` exposes a stable ``name`` so it satisfies the
:class:`bob.domain.ports.DomainEvent` contract for bus routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["MESSAGE_RECEIVED", "MessageReceived"]

# Stable event-type name used for EventBus subscription routing.
MESSAGE_RECEIVED: Final = "telegram.message_received"


@dataclass(frozen=True, slots=True)
class MessageReceived:
    """A user message received from Telegram, normalised for the application.

    Attributes mirror just enough of a Telegram message for a use-case to reply
    in the right place and attribute the text to a sender.

    ``reply_to_sender_id`` and ``mentions_bob`` are the **addressivity signals**
    (BOB-023): who, if anyone, this message is for. ``reply_to_sender_id`` is the
    from-user id of the message this one replies to (``None`` when it is not a
    reply); ``mentions_bob`` is whether the text @mentions Bob's bot (by username
    or a ``text_mention`` to his user id). Both are populated by the Telegram
    gateway from the inbound update and default to absence (``None`` / ``False``)
    so the event stays backward-compatible — a later use-case (the addressivity
    detector + policy) decides what to do with them.
    """

    update_id: int
    chat_id: int
    message_id: int
    text: str
    sender_id: int | None = None
    sender_name: str | None = None
    reply_to_sender_id: int | None = None
    mentions_bob: bool = False

    @property
    def name(self) -> str:
        """Stable event type name (satisfies the ``DomainEvent`` port)."""
        return MESSAGE_RECEIVED
