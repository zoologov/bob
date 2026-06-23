# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Interlocutor — WHO is writing, as social identity (BOB-019).

Bob is a person, not a gate: he should *perceive* who is on the other side of a
turn — the owner he knows, a known (allowlisted) friend, a stranger, or another
bot — and let that colour how he answers. This module is the pure foundation of
that social layer, sitting *above* the unchanged access policy (``Authorizer``):

* :class:`Interlocutor` — a frozen value object: the sender's identity (id +
  display name) plus a :class:`InterlocutorKind` (OWNER / KNOWN / GUEST / BOT)
  and a :class:`Trust` level (TRUSTED / GUEST).
* :func:`classify` — a pure function that derives that identity from the authz
  facts already known for the turn (``is_owner`` / ``is_authorized``) and the
  Telegram ``is_bot`` flag.

It is deliberately transport-free and covers humans AND bots, so it is ready for
a future BobNet bot-to-bot exchange without pulling any real bot transport into
the domain. It changes NO behaviour or security on its own: classification is
perception, not a decision — the guest-restricted pipeline is a later bead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["Interlocutor", "InterlocutorKind", "Trust", "classify"]

# Stable label used when the transport hands us no display name, so a perceived
# interlocutor always has a non-empty, human-readable name to fold into voice.
_UNKNOWN_NAME = "незнакомец"


class InterlocutorKind(Enum):
    """Who, socially, is writing this turn.

    OWNER — Bob's person; KNOWN — an allowlisted (authorized) human friend;
    GUEST — an unauthorized human (a stranger Bob can still meet socially); BOT —
    another bot (a distinct kind, the foundation for a future BobNet peer).
    """

    OWNER = "owner"
    KNOWN = "known"
    GUEST = "guest"
    BOT = "bot"


class Trust(Enum):
    """How much Bob trusts this interlocutor — orthogonal to the kind.

    TRUSTED — owner or an authorized peer (full social standing); GUEST — not
    authorized (a stranger; in a later bead this gates the restricted pipeline).
    A bot's trust still follows authorization, so an allowlisted peer bot is
    TRUSTED while a random bot is GUEST.
    """

    TRUSTED = "trusted"
    GUEST = "guest"


@dataclass(frozen=True, slots=True)
class Interlocutor:
    """The perceived social identity of the sender of one turn (immutable)."""

    sender_id: int | None
    display_name: str
    kind: InterlocutorKind
    trust: Trust


def classify(
    *,
    sender_id: int | None,
    sender_name: str | None,
    is_owner: bool,
    is_authorized: bool,
    is_bot: bool = False,
) -> Interlocutor:
    """Derive the :class:`Interlocutor` from the turn's authz facts (pure).

    Mapping (deterministic, no side effects): the owner is OWNER/TRUSTED; an
    authorized non-owner human is KNOWN/TRUSTED; an unauthorized human is
    GUEST/GUEST. A bot is its own KIND (BOT) regardless of authorization, while
    its TRUST still follows authorization (an allowlisted peer bot is TRUSTED, a
    random bot is GUEST) — ready for a future BobNet peer with no transport here.
    """
    trust = Trust.TRUSTED if (is_owner or is_authorized) else Trust.GUEST
    if is_bot:
        kind = InterlocutorKind.BOT
    elif is_owner:
        kind = InterlocutorKind.OWNER
    elif is_authorized:
        kind = InterlocutorKind.KNOWN
    else:
        kind = InterlocutorKind.GUEST
    return Interlocutor(
        sender_id=sender_id,
        display_name=sender_name or _UNKNOWN_NAME,
        kind=kind,
        trust=trust,
    )
