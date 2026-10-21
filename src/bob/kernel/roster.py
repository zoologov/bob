# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Roster member — one person on the «состав комнаты» Bob recalls (BOB-080): the VALUE.

* :class:`RosterMember` — one named person on the roster: who (``sender_id``), their
  ``name``, WHEN Bob first met them, and whether they are a ``is_newcomer`` (fresh).

Why the shared kernel (BOB-113, RFC D): the roster is rendered into a directive by
``conversation`` (room reading / voice inputs), which sits BELOW ``social`` in the
runtime order — declared in ``social``, the member type pulled that signature into an
upward edge. The BEHAVIOUR that builds a roster stays in ``social``:
:func:`~bob.social.roster.build_roster`, :func:`~bob.social.roster.is_newcomer` and
:func:`~bob.social.roster.member_name`. Value only here; no first-party import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["RosterMember"]


@dataclass(frozen=True, slots=True)
class RosterMember:
    """One named person Bob recalls on the roster: who, name, when-met, newcomer?"""

    sender_id: int
    name: str
    first_seen_at: datetime
    is_newcomer: bool
