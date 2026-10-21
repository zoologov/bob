# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Interlocutor — WHO is writing, as social identity (BOB-019): the shared VALUES.

* :class:`Interlocutor` — a frozen value object: the sender's identity (id +
  display name) plus a :class:`InterlocutorKind` (OWNER / KNOWN / GUEST / BOT)
  and a :class:`Trust` level (TRUSTED / GUEST).
* :class:`Gender` — the interlocutor's grammatical gender as read from THEIR own
  self-presentation (BOB-078 A); the field type of ``Interlocutor.gender``.

Why the shared kernel (BOB-113, RFC D): «who is talking to Bob» is the vocabulary of
the whole of Bob, not of ``social`` alone — ``conversation`` (room reading, voice
inputs), ``personality`` (reaction meaning, voice), ``memory`` (register) and the
runtime wiring read these values, and they sit BELOW ``social`` in the runtime order.
Declared in ``social``, the values dragged their signatures into an upward edge. The
BEHAVIOUR stays in ``social``: :func:`~bob.social.interlocutor.classify` derives an
interlocutor from the turn's authz facts, and
:func:`~bob.social.gender.detect_self_gender` / :class:`~bob.social.gender.GenderRead`
read gender from self-presentation. Values only here; no logic, no first-party import.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["Gender", "Interlocutor", "InterlocutorKind", "Trust"]


class Gender(Enum):
    """The interlocutor's grammatical gender, as read from THEIR self-presentation.

    FEM / MASC are committed reads; UNKNOWN is the safe default — Bob addresses an
    UNKNOWN interlocutor neutrally, forcing no grammatical gender.
    """

    FEM = "fem"
    MASC = "masc"
    UNKNOWN = "unknown"


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
    """The perceived social identity of the sender of one turn (immutable).

    ``gender`` is the interlocutor's grammatical gender as read from THEIR own
    self-presentation (BOB-078 A) — never from their name. It defaults to
    :attr:`Gender.UNKNOWN` (neutral: Bob forces no grammatical gender) so an
    unperceived or newly-met sender is unchanged.

    ``username`` is their Telegram ``@ник`` without the «собака» (BOB-090.B3) — how they
    can be ADDRESSED in a room, as opposed to ``display_name``, which is how they are
    CALLED. ``None`` (the default) means «ника нет / не знаю», a normal state in Telegram;
    it must lead to addressing them by name, never to a tag composed out of one.
    """

    sender_id: int | None
    display_name: str
    kind: InterlocutorKind
    trust: Trust
    gender: Gender = Gender.UNKNOWN
    username: str | None = None
