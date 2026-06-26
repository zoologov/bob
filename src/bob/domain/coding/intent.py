# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Чистые предикаты естественного апрува/стопа coding-сессии (BOB-041 .2).

В топике Боба owner управляет идущей гейтед-сессией обычными словами: «давай / го /
поехали» одобряет план, «стоп / отмена / останови» гасит сессию. Эти предикаты —
чистая, детерминированная, КОНСЕРВАТИВНАЯ классификация одной строки: совпадает
только короткая фраза-команда целиком (после нормализации), а вопрос или обычная
реплика, где слово-команда лишь упомянуто («а давай попозже…», «а что если
остановить…»), НЕ совпадает. Консервативность — часть безопасности: ложный апрув
мог бы запустить исполнение, поэтому при любой неоднозначности предикат отдаёт
``False`` (трактуется как болтовня, а не как команда).
"""

from __future__ import annotations

__all__ = ["is_approval", "is_stop"]

# Exact, normalised approval phrases (the WHOLE message must be one of these). Kept a
# curated short set so an approval word merely MENTIONED inside a longer sentence never
# counts — the message has to BE the command, not contain it.
_APPROVE_PHRASES: frozenset[str] = frozenset(
    {
        "давай",
        "давай го",
        "го",
        "го делай",
        "апрув",
        "approve",
        "поехали",
        "погнали",
        "вперёд",
        "вперед",
        "делай",
        "ок делай",
        "окей делай",
        "да делай",
        "да давай",
        "одобряю",
    }
)

# Exact, normalised stop phrases (the WHOLE message must be one of these).
_STOP_PHRASES: frozenset[str] = frozenset(
    {
        "стоп",
        "stop",
        "отмена",
        "отмени",
        "останови",
        "останови это",
        "прекрати",
        "хватит",
        "отбой",
    }
)

# Punctuation flattened to spaces before matching, so «Давай!» / «Окей, делай» / «Стоп.»
# all normalise to their bare command phrase.
_PUNCT_CHARS = ".!?,…;:\"'()-—"
_PUNCT_TO_SPACE = str.maketrans(dict.fromkeys(_PUNCT_CHARS, " "))


def _normalize(text: str) -> str:
    """Lowercase, flatten punctuation to spaces and collapse whitespace for matching."""
    flattened = text.translate(_PUNCT_TO_SPACE)
    return " ".join(flattened.split()).casefold()


def is_approval(text: str) -> bool:
    """Whether ``text`` is a clear, whole-message approval of the pending plan.

    Conservative: matches only when the normalised message IS one of the curated
    approval phrases. A question or a longer sentence that merely contains an
    approval-ish word does not match (default to chat on doubt — never an accidental
    approve).
    """
    return _normalize(text) in _APPROVE_PHRASES


def is_stop(text: str) -> bool:
    """Whether ``text`` is a clear, whole-message request to stop the session.

    Conservative in the same way as :func:`is_approval`: only an exact normalised
    stop phrase matches, never a sentence that merely mentions stopping.
    """
    return _normalize(text) in _STOP_PHRASES
