# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding-domain

"""Чистые предикаты естественного апрува/стопа coding-сессии (BOB-041 .2, BOB-042 .4).

В топике Боба owner управляет идущей гейтед-сессией обычными словами. BOB-042 .4
расширил классификацию с «сообщение ЦЕЛИКОМ есть команда» до «короткая реплика
СОДЕРЖИТ команду по смыслу», потому что в живом прогоне естественный апрув «План, ок,
давай» не распознавался и сессия не запускалась.

Правила (детерминированно, без LLM и I/O):

* :func:`is_stop` — True, если нормализованная реплика содержит стоп/отрицание-токен
  («стоп», «отмена», «останови», «не надо», «cancel»…). Стоп — это аварийный
  выключатель, поэтому проверяется ПЕРВЫМ и не ограничен длиной.
* :func:`is_approval` — True, ТОЛЬКО если это не стоп, в реплике нет отрицания
  («не» / «нет») и она содержит аффирматив-токен («ок», «да», «давай», «поехали»…),
  И реплика короткая (ответ, а не абзац-новая-задача).

Консервативность — часть безопасности: совпадение токенов проверяется по границам слов
(после нормализации), поэтому «да» внутри «создай» не срабатывает; длинное off-topic
сообщение, лишь упоминающее «ок», не апрувит; при любой неоднозначности предикат отдаёт
``False`` (трактуется как болтовня → обычный чат, а не команда).
"""

from __future__ import annotations

__all__ = ["is_approval", "is_stop"]

# Stop / negation tokens (word-boundary matched after normalisation). A multi-word entry
# («не надо») matches only as a consecutive whole-word run. Stop is the kill-switch, so it
# is intentionally NOT length-bounded — any live reply carrying one of these stops.
_STOP_TOKENS: frozenset[str] = frozenset(
    {
        "стоп",
        "отмена",
        "отмени",
        "останови",
        "не надо",
        "погоди",
        "подожди",
        "хватит",
        "прекрати",
        "отбой",
        "cancel",
        "abort",
        "stop",
    }
)

# Affirmative tokens — a SHORT reply containing one (and no negation, and not a stop) is an
# approval of the waiting plan.
_AFFIRM_TOKENS: frozenset[str] = frozenset(
    {
        "давай",
        "го",
        "погнали",
        "поехали",
        "вперёд",
        "вперед",
        "ок",
        "окей",
        "да",
        "ага",
        "апрув",
        "утверждаю",
        "одобряю",
        "делай",
        "начинай",
        "approve",
        "yes",
        "go",
        "ok",
    }
)

# Standalone negation tokens — their presence vetoes an approval (e.g. «не сейчас»,
# «да, но нет»). A negated stop phrase («не надо») is handled by stop-first ordering.
_NEGATION_TOKENS: frozenset[str] = frozenset({"не", "нет"})

# An approval must be a REPLY, not a paragraph: a longer message that merely contains an
# affirmative word (a deferral «а давай попозже…», or a new task «ок, а можешь ещё…») is
# left to chat rather than auto-approved. Bounds the false-approve surface conservatively.
_MAX_REPLY_WORDS = 6

# Punctuation flattened to spaces before matching, so «Давай!» / «План, ок, давай» / «Стоп.»
# all normalise to space-separated bare tokens.
_PUNCT_CHARS = ".!?,…;:\"'()-—"
_PUNCT_TO_SPACE = str.maketrans(dict.fromkeys(_PUNCT_CHARS, " "))


def _normalize(text: str) -> str:
    """Lowercase, flatten punctuation to spaces and collapse whitespace for matching."""
    flattened = text.translate(_PUNCT_TO_SPACE)
    return " ".join(flattened.split()).casefold()


def _contains_token(normalized: str, tokens: frozenset[str]) -> bool:
    """Whether ``normalized`` contains any token as a whole-word run (boundary-aware)."""
    padded = f" {normalized} "
    return any(f" {token} " in padded for token in tokens)


def is_stop(text: str) -> bool:
    """Whether ``text`` is a request to stop the live session (the kill-switch).

    True when the normalised reply contains any stop/negation token as a whole word.
    Checked FIRST by callers, so a message carrying both a stop and an affirmative is a
    stop. Word-boundary matched, so «остановку поездов» / «останавливайся» do not bite.
    """
    return _contains_token(_normalize(text), _STOP_TOKENS)


def is_approval(text: str) -> bool:
    """Whether ``text`` is a natural approval of the pending plan.

    Conservative by construction: returns ``False`` when the reply is a stop (stop-first),
    contains a standalone negation, or is longer than a short reply — so a deferral, a new
    task, or a long off-topic message that merely mentions «ок» never auto-approves. Only a
    short, non-negated reply containing an affirmative token (word-boundary matched) approves.
    """
    if is_stop(text):
        return False
    normalized = _normalize(text)
    if _contains_token(normalized, _NEGATION_TOKENS):
        return False
    if len(normalized.split()) > _MAX_REPLY_WORDS:
        return False
    return _contains_token(normalized, _AFFIRM_TOKENS)
