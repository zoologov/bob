# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Profanity perception — directed hostility vs casual мат (BOB-014 .2b).

Bob is a grown-up about language: casual/emphatic мат "with him" ("блин, охренеть
как круто") is part of how people talk and он спокоен к нему — he may even quip back
in his dry style (see :func:`~bob.domain.personality.voice.profanity_stance`), and it
must NEVER crater the relationship or trigger обида. What he DOES register is hostility
aimed AT him — directed insults / "at him" profanity.

:func:`is_directed_hostility` is the light, pure heuristic that feeds the obida signal:
it fires only when the text reads as DIRECTED at the second person (an insult word, or
profanity together with a "ты"/"иди …" address), so the relationship-damage / sulk
signal reacts to directed hostility, not to vocabulary. Deliberately conservative —
casual мат is left calm — and deterministic: same text → same verdict. No I/O.
"""

from __future__ import annotations

__all__ = ["is_directed_hostility"]

# Second-person address markers — the "at YOU" half of "directed". A bare profanity
# with no addressing reads as casual emphasis; paired with one of these it reads as
# aimed at Bob. Russian (project language); Cyrillic look-alikes are intentional.
_ADDRESS_MARKERS = (
    "ты ",
    "тебе",
    "тебя",
    "иди ",
    "пошёл ты",
    "пошел ты",
    "заткнись",
)

# Insult lexicon — words that are an attack by themselves (no addressing needed). Kept
# small and conservative on purpose: this is a SIGNAL, not a censor. Russian.
_INSULT_WORDS = (
    "идиот",
    "тупой",
    "дебил",
    "придурок",
    "кретин",
    "урод",
    "мудак",
)

# Profanity stems that read as hostile ONLY when DIRECTED (paired with an address
# marker). On their own ("охренеть", "да хрен") they are casual emphasis "with him"
# and stay calm. Russian; Cyrillic look-alikes intentional.
_PROFANITY_STEMS = (
    "хрен",
    "хер",
    "блят",
    "сука",
    "нах",
)


def is_directed_hostility(text: str) -> bool:
    """Whether ``text`` reads as hostility DIRECTED at Bob (BOB-014 .2b) — pure.

    Fires when the text contains an insult word (an attack on its own), OR profanity
    together with a second-person address ("ты"/"иди …"/"заткнись") — the "at him"
    pattern. Casual/emphatic мат with no addressing ("блин, охренеть") returns
    ``False`` — Bob stays calm about it, so it never craters the relationship or
    triggers обида. Case-insensitive and conservative; an empty/blank text is never
    hostile. Deterministic: same text → same verdict.
    """
    lowered = text.casefold()
    if not lowered.strip():
        return False
    if any(word in lowered for word in _INSULT_WORDS):
        return True
    has_address = any(marker in lowered for marker in _ADDRESS_MARKERS)
    has_profanity = any(stem in lowered for stem in _PROFANITY_STEMS)
    return has_address and has_profanity
