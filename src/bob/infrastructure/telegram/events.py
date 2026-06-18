# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Transport-level events the Telegram gateway publishes onto the EventBus.

These are plain, frozen value objects: the gateway translates an inbound
Telegram update into a :class:`MessageReceived` and publishes it. They carry no
Higher-Mind / LLM / memory logic — only the data a use-case needs to react.
:class:`MessageReceived` exposes a stable ``name`` so it satisfies the
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
    """

    update_id: int
    chat_id: int
    message_id: int
    text: str
    sender_id: int | None = None
    sender_name: str | None = None

    @property
    def name(self) -> str:
        """Stable event type name (satisfies the ``DomainEvent`` port)."""
        return MESSAGE_RECEIVED
