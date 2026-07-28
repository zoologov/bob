# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Outgoing-target policy — WHERE Bob's reply lands this turn (BOB-066 Срез 1.1).

A pure, deterministic conversation-domain core (no LLM, no transport): given this
turn's structural signals it decides whether Bob's reply should QUOTE the message it
answers (a Telegram reply-to) and WHOM it addresses. The rule for this first slice:

* **3+ participants** (``others_present``) and NOT a locked focal 1:1 → quote the
  addressed message, so in a busy thread it is unambiguous which message Bob answers.
* **a focal 1:1** (``focal_1to1``) — or simply a thread with no third participant →
  no quote: the reply goes to the topic as it does today (additive, zero regression).

The verdict is a small frozen :class:`OutgoingTarget` value object the application
threads to the gateway; generation (the voice composer) never sees it — quoting is a
transport-shaped output concern the use-case owns, kept out of the domain of *what*
Bob says. This mirrors the epic principle "LLM verbalises → pure core decides the
verdict → application orchestrates → infrastructure realises the port": the reply-to
decision is code, not a model whim, so it is exhaustively unit- and mutation-tested.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutgoingTarget:
    """Where one turn's reply lands: an optional quoted message + the addressee.

    ``reply_to_message_id`` is the message Bob's reply QUOTES (a Telegram reply-to),
    or ``None`` for the un-quoted, topic-only send that is today's whole behaviour.
    ``addressee_id`` is the ``sender_id`` of the person Bob is answering (carried for
    later floor/addressing use), or ``None`` when the sender is unresolved. The bare
    default is the legacy send — no quote, no addressee — so an unset target never
    changes behaviour.
    """

    reply_to_message_id: int | None = None
    addressee_id: int | None = None


def resolve_outgoing_target(
    *,
    message_id: int,
    addressee_id: int | None,
    others_present: bool,
    focal_1to1: bool,
) -> OutgoingTarget:
    """Decide this turn's :class:`OutgoingTarget` from its structural signals.

    Bob's reply quotes the addressed ``message_id`` exactly when a third participant
    is around (``others_present``) AND the turn is not a locked focal 1:1
    (``focal_1to1``); otherwise it lands un-quoted (``None``). ``addressee_id`` is
    carried through unchanged — it names WHOM Bob answers independently of whether the
    reply visibly quotes them. Pure and total: same inputs, same target, always.
    """
    reply_to = message_id if others_present and not focal_1to1 else None
    return OutgoingTarget(reply_to_message_id=reply_to, addressee_id=addressee_id)
