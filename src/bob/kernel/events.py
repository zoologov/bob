# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Intake events carried on the EventBus.

These are plain, frozen value objects the runtime and use-cases exchange. The
Telegram gateway (infrastructure) translates an inbound update into a
:class:`MessageReceived` and publishes it; a use-case (application) consumes it.
The event is transport-agnostic data a use-case needs to react — not an
infrastructure detail. It lives in the shared kernel (BOB-113) because modules
BELOW the runtime that owns the bus (``conversation``, ``personality``) read it
too; parked in ``application/runtime`` it forced their signatures into an upward
edge. :class:`MessageReceived` exposes a stable ``name`` so it satisfies the
:class:`bob.kernel.ports.DomainEvent` contract for bus routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "BOB_MESSAGE_REACTION",
    "MESSAGE_RECEIVED",
    "BobMessageReaction",
    "MessageReceived",
]

# Stable event-type name used for EventBus subscription routing.
MESSAGE_RECEIVED: Final = "telegram.message_received"

# Stable event-type name for a reaction on one of Bob's own messages (BOB-050).
BOB_MESSAGE_REACTION: Final = "telegram.bob_message_reaction"


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

    ``is_group`` is the **channel signal** (BOB-082 .1): whether this message
    arrived in a shared group/supergroup (``True``) as opposed to the owner's 1:1
    DM (``False``). The Telegram gateway derives it from ``chat.type``; downstream
    it decides a turn's scope-provenance BY WHERE it was said (a group turn is
    shared/``public``; a DM turn is the owner's ``owner_private`` world) rather than
    by who spoke. It defaults to ``True`` because every existing (non-DM) construction
    is the shared companion group — the DM path sets it to ``False`` explicitly — and
    because in production the gateway always sets it from the real ``chat.type``, so
    the default only ever affects synthetic (group) events, never a live turn.

    ``topic_id`` is the **exact-address signal** (BOB-090.C2): the forum topic
    (Telegram's ``message_thread_id``) this message was said in, next to ``chat_id``.
    ``is_group`` alone answers only "DM or a room"; to later write back into the place
    something was actually discussed — the right chat AND the right topic — the precise
    address has to reach the application, and the gateway has known it all along (it
    already pins Bob's own replies to a thread). ``None`` means the message has NO
    topic: a 1:1 DM (private chats have no forum topics) or a group without them. It is
    NOT a guess and never a substitute for an unknown chat.

    ``sender_username`` is the sender's Telegram ``@ник`` WITHOUT the «собака»
    (BOB-090.B3), next to their human ``sender_name``. The two are different things and
    only the handle can address a person in a room; it was carried by every update and
    dropped at this boundary, which is why it existed NOWHERE and Bob wrote «@Норман»
    instead of ``@NormanGri`` (эпизод 3088). ``None`` means the person has no handle —
    a perfectly normal state in Telegram, and one that must lead to addressing them BY
    NAME rather than to a composed tag.
    """

    update_id: int
    chat_id: int
    message_id: int
    text: str
    sender_id: int | None = None
    sender_name: str | None = None
    reply_to_sender_id: int | None = None
    mentions_bob: bool = False
    is_group: bool = True
    topic_id: int | None = None
    sender_username: str | None = None

    @property
    def name(self) -> str:
        """Stable event type name (satisfies the ``DomainEvent`` port)."""
        return MESSAGE_RECEIVED


@dataclass(frozen=True, slots=True)
class BobMessageReaction:
    """A reaction added to / removed from one of **Bob's own** messages (BOB-050).

    The Telegram gateway translates a ``message_reaction`` update into this event
    after confirming the reacted-to ``message_id`` is one of Bob's recorded
    outgoing messages, and publishes it on the :class:`EventBus`; a use-case (the
    BOB-050 .2 ``PerceiveReaction``) consumes it to read what Bob said and judge
    what the reaction means.

    ``emoji_added`` / ``emoji_removed`` are derived from the
    ``MessageReactionUpdated`` ``old_reaction → new_reaction`` diff: which standard
    emoji this reactor newly placed, and which they took away. ``reactor_sender_id``
    / ``reactor_name`` attribute the reaction to who (BOB-019 social identity).

    **Defensive anonymous case:** a private group may deliver only an aggregate
    ``message_reaction_count`` update with no user — then ``reactor_sender_id`` and
    ``reactor_name`` are ``None`` (a "someone reacted" signal without who), and the
    emoji currently on the message arrive as ``emoji_added`` (no diff is available).
    """

    chat_id: int
    message_id: int
    emoji_added: tuple[str, ...] = ()
    emoji_removed: tuple[str, ...] = ()
    reactor_sender_id: int | None = None
    reactor_name: str | None = None

    @property
    def name(self) -> str:
        """Stable event type name (satisfies the ``DomainEvent`` port)."""
        return BOB_MESSAGE_REACTION
