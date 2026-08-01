# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Consent-раскрытия seam — value-тип, порт, чистый промпт + парсер (BOB-082 .4).

Приватность по умолчанию — не тюрьма: если OWNER в группе САМ разрешает Бобу вынести
ранее-приватное в комнату, это нормально (раскрытие по согласию owner'а, INV-2). Этот
модуль задаёт форму того семантического (Tier-0, НЕ по ключевым словам — north star)
решения и шов, через который оно делается, плюс его модель-обращённую (чистую) половину:

* :class:`DisclosureConsentContext` — immutable ВХОД: текст owner-хода + лёгкий
  контекст (recent thread, может быть пустым).
* :class:`DisclosureConsentJudge` — инжектируемый порт: ``assess(ctx) -> bool``. Tier-0
  LLM-реализация живёт в infrastructure; тесты инжектят фейк.
* :func:`build_disclosure_consent_user_prompt` — чисто сворачивает контекст в Tier-0
  user-prompt; :data:`DISCLOSURE_CONSENT_SYSTEM_PROMPT` задаёт вопрос и размеченный
  выходной контракт (``consent: <yes|no>``).
* :func:`parse_disclosure_consent` — чисто мапит ответ модели в ``bool``.

🔴 КОНСЕРВАТИВНО, смещение к NO: раскрытие приватного — необратимая утечка, поэтому
только явное ``consent: yes`` = согласие; ``no``, неоднозначный или непарсибельный ответ
= NO (без raise — безопасный дефолт «не раскрывать», а не тихая утечка). Ложно пропущенное
согласие безопасно (owner повторит просьбу); ложное раскрытие — недопустимо.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "DISCLOSURE_CONSENT_SYSTEM_PROMPT",
    "DisclosureConsentContext",
    "DisclosureConsentJudge",
    "build_disclosure_consent_user_prompt",
    "parse_disclosure_consent",
]

# The single labelled line the parser reads (case-insensitive, whitespace-tolerant).
_CONSENT_LABEL = re.compile(r"^\s*consent\s*:\s*(.+)$", re.IGNORECASE)

# Affirmative / negative tokens for the boolean ``consent`` field. Anything OUTSIDE these
# sets (an ambiguous «maybe», garbage, silence) resolves to NO — the conservative default.
_YES_TOKENS: frozenset[str] = frozenset({"yes", "true", "y", "да"})
_NO_TOKENS: frozenset[str] = frozenset({"no", "false", "n", "нет"})

# Punctuation trimmed off a scanned token before matching.
_WORD_TRIM = " \t\n.!?,:;'\"*-"

DISCLOSURE_CONSENT_SYSTEM_PROMPT = (
    "You are Bob deciding ONE thing about the OWNER's latest message in a GROUP chat: is "
    "the owner, in THIS message, explicitly AUTHORISING you to share something previously "
    "PRIVATE (things said just between you two) with the other people in this group?\n"
    "Say yes ONLY for a clear authorisation to disclose private matter to the group "
    "(«расскажи ребятам, что мы обсуждали», «да, можешь рассказать им про X», «поделись "
    "с группой тем, что мы решили»).\n"
    "Say no for ANYTHING else: an ordinary question, a request about a public/neutral "
    "topic («расскажи про погоду»), or anything not clearly about disclosing private "
    "matter. Be CONSERVATIVE — if in any doubt, say no.\n"
    "Reply in exactly this labelled format, nothing else:\n"
    "consent: <yes|no>"
)


@dataclass(frozen=True, slots=True)
class DisclosureConsentContext:
    """The immutable input to a disclosure-consent judgment (owner's turn + light context).

    ``request_text`` is the owner's latest message (judged for a disclosure authorisation).
    ``recent_thread`` is a light per-turn snippet for context (e.g. what Bob just asked);
    it may be empty.
    """

    request_text: str
    recent_thread: str = ""


@runtime_checkable
class DisclosureConsentJudge(Protocol):
    """The seam: decide, by meaning, whether the owner consents to disclose this turn.

    Injectable so the decision is deterministic in tests (a fake returns a scripted bool)
    and swappable in tier without touching any consumer.
    """

    async def assess(self, ctx: DisclosureConsentContext) -> bool:
        """Weigh ``ctx`` and return whether the owner consents to disclosure this turn."""
        ...


def build_disclosure_consent_user_prompt(ctx: DisclosureConsentContext) -> str:
    """Fold ``ctx`` into the Tier-0 user prompt (pure).

    Includes the owner's message and the recent thread for light context (``(none)`` when
    absent), so the judge weighs the ask in situ.
    """
    lines = [
        "Recent thread:",
        ctx.recent_thread or "  (none)",
        "",
        "Owner's latest message:",
        ctx.request_text,
    ]
    return "\n".join(lines)


def parse_disclosure_consent(raw: str) -> bool:
    """Parse the model's reply into a consent bool — conservative, biased to NO (pure).

    Reads the labelled ``consent: <yes|no>`` line: a clear yes token → ``True``. ANY other
    outcome — a ``no``, an ambiguous value, a missing label, or garbage — is ``False``
    (never raises: the safe default for a disclosure decision is «не раскрывать»).
    """
    value = _scan_consent_label(raw)
    if value is None:
        return False
    return _parse_yes(value)


def _scan_consent_label(raw: str) -> str | None:
    """Extract the ``consent:`` label value from ``raw`` (or ``None`` when absent)."""
    for line in raw.splitlines():
        if match := _CONSENT_LABEL.match(line):
            return match.group(1)
    return None


def _parse_yes(text: str) -> bool:
    """Whether ``text`` carries a clear yes token — a no / unknown token yields ``False``."""
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        if word in _YES_TOKENS:
            return True
        if word in _NO_TOKENS:
            return False
    return False
