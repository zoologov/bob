# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Endorsement perception — кредит доверия по рекомендации owner (BOB-066 2.6, Пласт 4).

When the owner introduces or vouches for a newcomer ("это мой друг Норман, ему можно
доверять"), Bob should meet that person with a warm start rather than as a blank
stranger — a credit of trust the owner extends on their behalf (a drift-to-neutral
relationship will dissolve it if the person's own behaviour doesn't confirm it, so it is
a *seed*, never a permanent grant).

* :func:`detected_endorsement` — the light, pure heuristic (в духе
  :func:`~bob.personality.profanity.is_directed_hostility`): fires when the text reads as
  the owner VOUCHING for a person — an introduction ("познакомься", "это мой друг") or a
  trust vouch ("ему можно доверять", "я за него ручаюсь", "он свой"). Deliberately
  conservative: a neutral mention of someone is not an endorsement.
* :func:`owner_endorsed_sender` — narrows the signal to ONE person: an endorsement among
  the owner's recent turns that NAMES this sender. So a warm word about Лёша never
  warm-starts Норман.

Pure and deterministic (no I/O), so the warm-start decision stays testable without an LLM.
The credit is applied elsewhere (:func:`~bob.social.relationship.endorsed_seed`) and only
on a first contact — this module only PERCEIVES the endorsement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["detected_endorsement", "owner_endorsed_sender"]

# Vouch markers — the "I stand behind this person" half of an endorsement. Any one is
# enough on its own (a trust vouch is an endorsement even without an introduction).
# Russian (project language); Cyrillic look-alikes are intentional.
_VOUCH_MARKERS = (
    "можно доверять",
    "ему можно",
    "ей можно",
    "ручаюсь",
    "поручаюсь",
    "он свой",
    "она своя",
    "хороший человек",
    "хороший парень",
    "хорошая девушка",
    "доверяю ему",
    "доверяю ей",
    "с ним можно",
    "с ней можно",
)

# Introduction markers — presenting a person. On their own these read as an endorsement
# only when paired with a "friend/ours" possessive that carries a warm standing, so a
# bare "познакомься" is handled together with :data:`_FRIEND_MARKERS` below.
_INTRO_MARKERS = (
    "познакомься",
    "знакомься",
    "это мой друг",
    "это моя подруга",
    "мой друг",
    "моя подруга",
    "мой хороший знакомый",
)


def detected_endorsement(owner_text: str) -> bool:
    """Whether ``owner_text`` reads as the owner VOUCHING for a person — pure (BOB-066 2.6).

    Fires on a trust vouch ("ему можно доверять", "я за него ручаюсь", "он свой",
    "хороший человек") OR an introduction that carries warm standing ("познакомься, это
    мой друг"). Deliberately conservative in the spirit of
    :func:`~bob.personality.profanity.is_directed_hostility`: a neutral mention of
    someone ("Лёша опять опоздал") is NOT an endorsement, and blank text never is.
    Case-insensitive and deterministic: same text → same verdict.
    """
    lowered = owner_text.casefold()
    if not lowered.strip():
        return False
    if any(marker in lowered for marker in _VOUCH_MARKERS):
        return True
    return any(marker in lowered for marker in _INTRO_MARKERS)


def owner_endorsed_sender(owner_texts: Sequence[str], *, sender_name: str) -> bool:
    """Whether the owner endorsed THIS sender by name among ``owner_texts`` — pure.

    The narrowing half of the credit: an endorsement warm-starts a person only when it
    NAMES them, so a warm word about one member never warm-starts another. Requires a
    single owner turn that BOTH :func:`detected_endorsement` and mentions ``sender_name``
    (its first name is enough, case-insensitive). A blank name has nothing to attribute
    the credit to and yields ``False`` (conservative). Deterministic.
    """
    first_name = sender_name.strip().casefold().split(" ", 1)[0]
    if not first_name:
        return False
    return any(
        detected_endorsement(text) and first_name in text.casefold()
        for text in owner_texts
    )
