# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Gender — the interlocutor's grammatical gender by SELF-identification (BOB-078 A).

A live bug: Bob addressed a woman in the masculine («он») even though her own speech
was feminine («Пошл**а** учить Python», «Пролистал**а** чат»). 🔴 The owner's principle:
never guess gender from a NAME (unreliable — «Саша»/«Женя»), but from **self-
presentation** — how a person grammatically marks themselves in their own words.

This is the pure, I/O-free core of that read:

* :func:`detect_self_gender` — a single message →
  :class:`~bob.kernel.interlocutor.Gender` (FEM / MASC / UNKNOWN; the Enum lives in
  the shared kernel, BOB-113 — the inference stays here). The ONLY signal is
  1st-person self-presentation: a gendered past-tense verb the speaker uses about
  themselves («пошла»/«сделал»), or an explicit «я сама»/«я сам» marker. A gendered
  verb that belongs to a THIRD person («пошёл **он**») or a contradictory pair in one
  message decides nothing (UNKNOWN).
* :class:`GenderRead` — a frozen confidence axis (a signed ``lean`` in ``[-1, 1]``,
  ``> 0`` feminine, ``< 0`` masculine) that ACCUMULATES over turns the way a
  relationship axis does: each observation nudges the lean, contradictory signals net
  out, and :meth:`resolve` only commits to a gender once the lean clears a threshold —
  so a weak or conflicted read stays UNKNOWN (Bob forces nothing).

Deterministic and rule-based (no LLM): Russian past-tense gender is carried by the
verb ending, which parses by rule. No name, no transport, no clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bob.kernel.interlocutor import Gender

__all__ = ["GenderRead", "detect_self_gender"]


# Word tokens Bob reads from a message — Cyrillic (and Latin, harmlessly) runs only,
# lower-cased. Cyrillic look-alikes in these literals are intentional (Russian).
_WORD = re.compile(r"[а-яёa-z]+")

# The 1st-person subject: a gendered verb "belongs" to the speaker when it opens the
# message (dropped «я», e.g. «Пошла учить…») or directly follows «я».
_FIRST_PERSON = "я"

# 2nd/3rd-person subject pronouns: a gendered verb sitting right before one of these
# is THEIR verb, not the speaker's («пошёл он», «сделала она») — so it is NOT a
# self-presentation signal and must not decide gender.
_OTHER_SUBJECTS = frozenset({"он", "она", "оно", "они", "ты", "вы"})

# Explicit self-markers: «я сам» / «я сама» state the speaker's gender outright.
_SELF_MARKER_FEM = "сама"
_SELF_MARKER_MASC = "сам"

# Feminine past tense ends in «-ла» / reflexive «-лась» («пошла», «разобралась»).
# A minimum length keeps very short, noisy «-ла» tokens from posing as verbs.
_FEM_SUFFIXES = ("лась", "ла")
_MIN_FEM_VERB_LEN = 4

# Masculine past tense ends in «-л» (reflexive «-лся»), preceded by a vowel
# («сделал», «пошёл», «устал») — the vowel-before-«л» test is what tells a past-tense
# verb from a noun ending merely in «-л».
_MASC_REFLEXIVE_SUFFIX = "лся"
_MASC_SUFFIX = "л"
_MIN_MASC_VERB_LEN = 4
_VOWELS = frozenset("аеёиоуыэюя")

# Accumulation (mirrors a relationship axis): each committed self-signal nudges the
# lean by one STEP; a lean at or beyond ±THRESHOLD commits to a gender. THRESHOLD is TWO
# steps, so a gender commits only after ≥2 CONSISTENT self-signals (BOB-078.8): ONE
# leading gendered verb — «Была ошибка в коде», «Сделана миграция», where the subject is
# a noun, not the speaker — merely leans and reads UNKNOWN, never a false FEM/MASC in one
# turn. A contradicting later signal nets the lean back below threshold → UNKNOWN again.
_LEAN_STEP = 0.3
_LEAN_THRESHOLD = 0.6
_LEAN_MIN = -1.0
_LEAN_MAX = 1.0


def detect_self_gender(text: str) -> Gender:
    """Read the speaker's gender from ONE message's self-presentation — pure (BOB-078 A).

    Returns :attr:`Gender.FEM` / :attr:`Gender.MASC` only when the message carries an
    unambiguous 1st-person self-signal — an explicit «я сама»/«я сам», or a gendered
    past-tense verb the speaker uses about themselves (the verb opens the message or
    follows «я», and is not immediately handed to a 2nd/3rd-person subject like «он»).
    A verb about a third person, no gendered verb at all, or contradictory feminine +
    masculine self-verbs in one message all read :attr:`Gender.UNKNOWN`. 🔴 A name is
    never a signal. Deterministic: same text → same gender.
    """
    tokens = _WORD.findall(text.casefold())
    fem = False
    masc = False
    for i, token in enumerate(tokens):
        if not _is_self_position(tokens, i):
            continue
        signal = _self_signal(tokens, i, token)
        if signal is Gender.FEM:
            fem = True
        elif signal is Gender.MASC:
            masc = True
    if fem and not masc:
        return Gender.FEM
    if masc and not fem:
        return Gender.MASC
    return Gender.UNKNOWN


def _is_self_position(tokens: list[str], i: int) -> bool:
    """True when token ``i`` is a candidate the SPEAKER says of themselves.

    That is: it opens the message (a dropped «я» self-report) or directly follows «я».
    """
    return i == 0 or tokens[i - 1] == _FIRST_PERSON


def _self_signal(tokens: list[str], i: int, token: str) -> Gender:
    """The gender a self-positioned ``token`` carries, or UNKNOWN if it carries none."""
    if _handed_to_other_subject(tokens, i):
        return Gender.UNKNOWN
    if token == _SELF_MARKER_FEM:
        return Gender.FEM
    if token == _SELF_MARKER_MASC:
        return Gender.MASC
    if _is_fem_past(token):
        return Gender.FEM
    if _is_masc_past(token):
        return Gender.MASC
    return Gender.UNKNOWN


def _handed_to_other_subject(tokens: list[str], i: int) -> bool:
    """True when the token right after ``i`` is a 2nd/3rd-person subject («пошёл он»).

    Then the gendered verb is THAT subject's, not the speaker's, so it is no self-signal.
    """
    return i + 1 < len(tokens) and tokens[i + 1] in _OTHER_SUBJECTS


def _is_fem_past(token: str) -> bool:
    """True for a feminine past-tense verb ending («пошла», «разобралась»)."""
    return len(token) >= _MIN_FEM_VERB_LEN and token.endswith(_FEM_SUFFIXES)


def _is_masc_past(token: str) -> bool:
    """True for a masculine past-tense verb ending («сделал», «пошёл», «оделся»).

    A reflexive «-лся» always qualifies; a bare «-л» qualifies only when a vowel
    precedes it, which distinguishes a past-tense verb from a noun ending in «-л»
    («стол» has a vowel too, but such nouns are filtered by the 1st-person framing).
    """
    if token.endswith(_MASC_REFLEXIVE_SUFFIX):
        return True
    if len(token) < _MIN_MASC_VERB_LEN or not token.endswith(_MASC_SUFFIX):
        return False
    return token[-2] in _VOWELS


@dataclass(frozen=True, slots=True)
class GenderRead:
    """Accumulated confidence in the interlocutor's gender — a signed axis (BOB-078 A).

    ``lean`` is a running confidence in ``[-1, 1]``: positive leans feminine, negative
    masculine, ``0`` is a blank read. It accrues over turns like a relationship axis —
    :meth:`observe` nudges it by each message's committed self-signal, contradictory
    signals net out, and :meth:`resolve` commits to a gender only once ``|lean|`` clears
    the threshold. The threshold is TWO steps (BOB-078.8), so a gender commits only after
    ≥2 CONSISTENT self-signals: a single lone self-signal — including a leading gendered
    verb whose real subject is a noun («Была ошибка в коде») — only leans and still reads
    UNKNOWN, so one turn never flips the gender falsely. A quoted/3rd-person verb (no
    signal) never moves it, and a weak or conflicted history stays UNKNOWN (Bob forces no
    gender).
    """

    lean: float = 0.0

    def observe(self, text: str) -> GenderRead:
        """Return a new read with ``text``'s self-signal folded in (pure).

        A feminine self-signal nudges the lean up one step, a masculine one down; an
        UNKNOWN message leaves the lean unchanged. One step alone stays below the
        two-step threshold, so a single self-signal only leans (BOB-078.8). The lean is
        clamped to ``[-1, 1]`` so repeated evidence saturates rather than running away.
        """
        signal = detect_self_gender(text)
        if signal is Gender.FEM:
            return GenderRead(_clamp_lean(self.lean + _LEAN_STEP))
        if signal is Gender.MASC:
            return GenderRead(_clamp_lean(self.lean - _LEAN_STEP))
        return self

    def resolve(self) -> Gender:
        """Commit to a :class:`Gender` once the lean clears the threshold, else UNKNOWN."""
        if self.lean >= _LEAN_THRESHOLD:
            return Gender.FEM
        if self.lean <= -_LEAN_THRESHOLD:
            return Gender.MASC
        return Gender.UNKNOWN


def _clamp_lean(value: float) -> float:
    """Saturate ``value`` into the confidence bounds ``[-1, 1]``."""
    return max(_LEAN_MIN, min(_LEAN_MAX, value))
