# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Чистые NL-предикаты owner-решения по permission-request (BOB-052 .1).

Owner отвечает на «Норман просит *X* — разрешить?» обычными словами. Эти предикаты
(детерминированно, без LLM и I/O, в духе BOB-042 ``is_approval``/``is_stop``)
классифицируют короткую реплику owner'а:

* :func:`is_deny` — True, если реплика содержит отказ-токен («нет», «откажи», «не
  надо», «нельзя»). Отказ — безопасный дефолт, поэтому проверяется ПЕРВЫМ.
* :func:`is_grant` — True, ТОЛЬКО если это не отказ, нет отрицания и реплика короткая
  и содержит grant-токен («да», «разреши», «покажи», «ок»). Разовый approve.
* :func:`is_authorize` — True, если реплика содержит durable-токен («авторизуй»,
  «дай доступ», «добавь в список»). Долгосрочная авторизация (→ ``Authorizer``).

🔴 Консервативность — часть безопасности: совпадение по границам слов (после
нормализации), поэтому «да» внутри «создай» не срабатывает; длинный абзац не апрувит;
отрицание ветирует grant; при любой неоднозначности → ``False``. Эти предикаты
вычисляются ТОЛЬКО для owner (в .2).
"""

from __future__ import annotations

__all__ = ["is_authorize", "is_deny", "is_grant"]

# Deny / refusal tokens (word-boundary matched). A multi-word entry («не надо») matches
# only as a consecutive whole-word run. Deny is the safe default, so it is checked first
# and is NOT length-bounded.
_DENY_TOKENS: frozenset[str] = frozenset(
    {
        "нет",
        "откажи",
        "отказать",
        "отказываю",
        "не надо",
        "нельзя",
        "запрети",
        "deny",
        "no",
    }
)

# Grant tokens — a SHORT reply containing one (and no negation, and not a deny) is a
# one-off approval of the pending request.
_GRANT_TOKENS: frozenset[str] = frozenset(
    {
        "да",
        "ага",
        "ок",
        "окей",
        "разреши",
        "разрешаю",
        "покажи",
        "можно",
        "конечно",
        "давай",
        "approve",
        "allow",
        "yes",
        "ok",
    }
)

# Durable-authorisation tokens — promote the requester to the allowlist (BOB-019),
# not a one-off grant. Multi-word entries match as a consecutive whole-word run.
_AUTHORIZE_TOKENS: frozenset[str] = frozenset(
    {
        "авторизуй",
        "авторизую",
        "дай доступ",
        "добавь в список",
        "добавь в белый список",
        "authorize",
    }
)

# Standalone negation tokens — their presence vetoes a grant («не сейчас», «не
# показывай»). A negated deny phrase («не надо») is handled by deny-first ordering.
_NEGATION_TOKENS: frozenset[str] = frozenset({"не", "нет"})

# A grant must be a REPLY, not a paragraph: a longer message that merely contains a
# grant word is left to chat rather than auto-approved. Bounds the false-grant surface.
_MAX_REPLY_WORDS = 6

# Punctuation flattened to spaces before matching, so «Да!» / «Покажи, ок» / «Нет.»
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


def is_deny(text: str) -> bool:
    """Whether ``text`` is the owner refusing the pending request (the safe default).

    True when the normalised reply contains any deny token («откажи», «нельзя») OR a
    standalone negation («не» / «нет») as a whole word — so «не показывай» / «не надо»
    are refusals too. Checked FIRST, so a reply carrying both a deny and a grant word
    is a deny. Word-boundary matched, so a deny token inside a longer word does not
    bite.
    """
    normalized = _normalize(text)
    return _contains_token(normalized, _DENY_TOKENS) or _contains_token(
        normalized, _NEGATION_TOKENS
    )


def is_grant(text: str) -> bool:
    """Whether ``text`` is the owner granting the pending request (a one-off approve).

    Conservative by construction: returns ``False`` when the reply is a deny
    (deny-first — which also covers a standalone negation «не»/«нет») or is longer
    than a short reply — so a refusal, a negated phrase, or a long off-topic message
    that merely mentions «ок» never auto-grants. Only a short, non-negated reply
    containing a grant token (word-boundary matched) grants.
    """
    if is_deny(text):
        return False
    normalized = _normalize(text)
    if len(normalized.split()) > _MAX_REPLY_WORDS:
        return False
    return _contains_token(normalized, _GRANT_TOKENS)


def is_authorize(text: str) -> bool:
    """Whether ``text`` is the owner durably authorising the requester (BOB-019).

    True when the normalised reply contains a durable-authorisation token
    («авторизуй», «дай доступ», «добавь в список»). A plain one-off grant/deny is NOT
    a durable authorise. Word-boundary matched.
    """
    return _contains_token(_normalize(text), _AUTHORIZE_TOKENS)
