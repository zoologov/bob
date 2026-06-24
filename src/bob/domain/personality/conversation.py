# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Repeat detection — owner repeats himself (BOB-022) + Bob repeats himself (BOB-026).

Pure, no-LLM predicates.

* :func:`is_user_repeat` (BOB-022) — when the owner sends (near-)the-same message
  he already sent in the recent window, Bob should NOTICE it (and react in his own
  wry voice via :func:`~bob.domain.personality.voice.user_repeat_directive`) rather
  than silently re-answer. Deliberately CONSERVATIVE: an EXACT match after
  normalisation (strip / casefold / collapse internal whitespace), never fuzzy —
  so Bob never accuses the owner of repeating himself when he did not.

* :func:`is_bob_repeat` (BOB-026 .1) — the own-reply twin: does Bob's fresh
  candidate reply echo one of his OWN recent replies (verbatim OR near-verbatim) so
  the anti-repeat guard regenerates? Checks the whole recent window — not just the
  last reply — so a repeat "через ход" no longer slips through.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Дефолтный порог сходства для near-repeat ответа Боба (BOB-026 .1). Консервативно
# высокий: ловит дословные и near-дословные повторы (мелкие правки одной фразы), но
# НЕ срабатывает на просто похожие по теме, но разные по сути ответы. Перекрывается
# из конфига (``repeat.similarity_threshold``) через app-композицию.
_DEFAULT_BOB_REPEAT_THRESHOLD = 0.9

# Дефолтный размер окна последних ответов Боба, с которыми сравнивается кандидат
# (BOB-026 .1). Достаточно широкое, чтобы поймать повтор «через ход», но не больше
# обычной истории. Перекрывается из конфига (``repeat.window``).
_DEFAULT_BOB_REPEAT_WINDOW = 5

_MIN_REPEAT_WINDOW = 1
_MIN_REPEAT_THRESHOLD = 0.0
_MAX_REPEAT_THRESHOLD = 1.0


@dataclass(frozen=True, slots=True)
class RepeatThresholds:
    """Пороги анти-повтора ответа Боба (инъекция из ``repeat.*`` конфига, BOB-026 .1).

    * ``window`` — сколько последних ответов Боба сравнивать с кандидатом (окно, не
      только последний ответ): ловит повтор «через ход».
    * ``similarity_threshold`` — порог сходства ``[0, 1]`` для near-verbatim
      детекции; консервативно высокий, чтобы не было ложных регенераций на просто
      похожих по теме, но разных по сути ответах.

    Дефолты консервативны.
    """

    window: int = _DEFAULT_BOB_REPEAT_WINDOW
    similarity_threshold: float = _DEFAULT_BOB_REPEAT_THRESHOLD

    def __post_init__(self) -> None:
        if self.window < _MIN_REPEAT_WINDOW:
            raise ValueError(
                f"repeat threshold 'window' must be >= {_MIN_REPEAT_WINDOW}, "
                f"got {self.window}"
            )
        if not _MIN_REPEAT_THRESHOLD <= self.similarity_threshold <= _MAX_REPEAT_THRESHOLD:
            raise ValueError(
                f"repeat threshold 'similarity_threshold' must be within "
                f"[{_MIN_REPEAT_THRESHOLD}, {_MAX_REPEAT_THRESHOLD}], "
                f"got {self.similarity_threshold}"
            )


def _normalise(text: str) -> str:
    """Strip, casefold, and collapse internal whitespace for an exact compare.

    Two messages that differ only in case or whitespace are the same message for
    repeat-detection purposes; everything else is left intact so the match stays
    exact (never fuzzy).
    """
    return " ".join(text.split()).casefold()


def is_user_repeat(current: str, prior_user_texts: Iterable[str]) -> bool:
    """Return ``True`` iff ``current`` exactly repeats a recent prior user turn.

    Both sides are normalised (strip / casefold / collapse whitespace) and matched
    exactly — conservative by design so it never false-fires. An empty/blank
    ``current`` is never a repeat (nothing meaningful to repeat).
    """
    normalised_current = _normalise(current)
    if not normalised_current:
        return False
    return any(normalised_current == _normalise(prior) for prior in prior_user_texts)


def is_bob_repeat(
    candidate: str,
    recent_bob_replies: Iterable[str],
    *,
    threshold: float = _DEFAULT_BOB_REPEAT_THRESHOLD,
) -> bool:
    """Return ``True`` iff ``candidate`` (near-)repeats ANY recent Bob reply (BOB-026 .1).

    The own-reply twin of :func:`is_user_repeat`: does Bob's fresh candidate reply
    echo one of his OWN recent replies — verbatim (after the same strip / casefold /
    whitespace normalisation) OR near-verbatim (a similarity ratio at or above
    ``threshold``)? Unlike the previous guard, which only looked at Bob's most-recent
    reply, this checks the whole window, so a repeat "через ход" — отказ → another
    turn → the SAME отказ — no longer slips through.

    Near-verbatim uses :class:`difflib.SequenceMatcher` (stdlib, no new deps) on the
    normalised texts. ``threshold`` is deliberately conservative (high) so a merely
    topically-similar but substantively different reply never false-fires a needless
    regeneration. An empty/blank ``candidate`` is never a repeat; blank recent replies
    are skipped.
    """
    normalised_candidate = _normalise(candidate)
    if not normalised_candidate:
        return False
    for prior in recent_bob_replies:
        normalised_prior = _normalise(prior)
        if not normalised_prior:
            continue
        if normalised_candidate == normalised_prior:
            return True
        ratio = SequenceMatcher(None, normalised_candidate, normalised_prior).ratio()
        if ratio >= threshold:
            return True
    return False
