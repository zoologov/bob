# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Volatility-judgment seam — value types, port, pure prompt + parser (BOB-057 .1).

BEFORE Bob answers, a cheap Tier-0 judge (in the spirit of ``ResponseJudge``
BOB-049 / ``PrivilegeJudge`` BOB-052) decides whether a good answer HINGES on a
FRESH, fast-decaying fact his training might have stale. This module defines the
shape of that one decision and the seam through which it is made, plus its
model-facing (pure) half:

* :class:`VolatilityVerdict` — the immutable outcome: ``needs_check`` (the gate),
  a ``query`` (a good web-search query) and a ``topic`` (a short human-readable
  subject for the live interim line, wired in .2/.3).
* :class:`VolatilityContext` — the immutable INPUT: the user's ``text`` plus a
  light ``recent_thread`` snippet for context — only what the prompt needs.
* :class:`VolatilityJudge` — the injectable port: ``assess(ctx) -> VolatilityVerdict``.
  A Tier-0 LLM realisation lives in infrastructure; tests inject a fake.
* :func:`build_volatility_user_prompt` — folds ``VolatilityContext`` into the
  Tier-0 user prompt; :data:`VOLATILITY_JUDGE_SYSTEM_PROMPT` states the CONSERVATIVE
  task and the labelled output contract.
* :func:`parse_volatility_verdict` — maps the reply to a :class:`VolatilityVerdict`,
  TOLERANT of format. 🔴 US-2 «не зануда»: an ambiguous / negative / garbled reply
  DEFAULTS to ``needs_check=False`` (don't check when unsure); only an affirmative
  verdict with no actionable query raises :class:`VolatilityJudgeParseError` (an
  unusable "check" — the infra propagates it so the caller safe-defaults).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "VOLATILITY_JUDGE_SYSTEM_PROMPT",
    "VolatilityContext",
    "VolatilityJudge",
    "VolatilityJudgeParseError",
    "VolatilityVerdict",
    "build_volatility_user_prompt",
    "parse_volatility_verdict",
]

# Labelled-line prefixes the parser recognises (case-insensitive, whitespace-tolerant).
_NEEDS_LABEL = re.compile(r"^\s*needs_check\s*:\s*(.+)$", re.IGNORECASE)
_QUERY_LABEL = re.compile(r"^\s*query\s*:\s*(.+)$", re.IGNORECASE)
_TOPIC_LABEL = re.compile(r"^\s*topic\s*:\s*(.+)$", re.IGNORECASE)

# Affirmative / negative tokens for the boolean ``needs_check`` field.
_YES_TOKENS: frozenset[str] = frozenset({"yes", "true", "y", "да"})
_NO_TOKENS: frozenset[str] = frozenset({"no", "false", "n", "нет"})

# Punctuation trimmed off a scanned token before matching.
_WORD_TRIM = " \t\n.!?,:;'\"*-"

VOLATILITY_JUDGE_SYSTEM_PROMPT = (
    "Ты — Боб. ДО того как ответить, реши: зависит ли хороший ответ на это "
    "сообщение от СВЕЖЕГО, быстро протухающего факта, который твоя память могла "
    "запомнить устаревшим. Отвечай КОНСЕРВАТИВНО.\n"
    "needs_check = yes ТОЛЬКО если верны ОБА условия:\n"
    "(a) ответу нужен реально ВОЛАТИЛЬНЫЙ факт — процентные ставки, цены, курсы "
    "валют/крипты, «сейчас/сегодня/актуальный/последний», рейтинги/турнирная "
    "таблица, версии ПО, кто сейчас занимает пост, погода, идущие прямо сейчас "
    "события; И\n"
    "(b) этот факт МАТЕРИАЛЬНО меняет ответ.\n"
    "Во всех остальных случаях needs_check = no: мнения, шутки, болтовня, "
    "стабильные факты (история, математика, определения, география), твоя "
    "собственная память и чувства, гипотетические вопросы. Сомневаешься — no.\n"
    "Примеры YES: «какая сейчас ставка ЦБ?», «сколько стоит биткоин сегодня?», "
    "«кто сейчас чемпион мира по шахматам?», «какая последняя версия Python?».\n"
    "Примеры NO: «расскажи анекдот», «как дела?», «что думаешь про осень?», "
    "«столица Франции?», «сколько будет 2+2?», «помнишь, о чём мы вчера "
    "говорили?».\n"
    "Ответь СТРОГО в этом размеченном формате, без лишнего:\n"
    "needs_check: <yes|no>\n"
    "query: <хороший поисковый запрос, только когда yes>\n"
    "topic: <короткий человекочитаемый предмет для живой реплики, только когда yes>"
)


class VolatilityJudgeParseError(ValueError):
    """Raised when an affirmative reply carries no actionable search ``query``.

    A real failure signal (not a silent default): the infrastructure judge lets it
    propagate so the caller in .2 safe-defaults to «не проверять» — Bob never runs
    a verify pass from an unusable "check" verdict. An ambiguous / negative /
    garbled reply is NOT an error — :func:`parse_volatility_verdict` conservatively
    returns ``needs_check=False`` for it.
    """


@dataclass(frozen=True, slots=True)
class VolatilityVerdict:
    """The immutable outcome of one volatility judgment.

    ``needs_check`` is the gate: when ``False`` (the conservative default) Bob
    answers normally with zero delay. When ``True``, ``query`` is a good web-search
    query («текущие ставки ОФЗ РФ 2026») and ``topic`` is a short human-readable
    subject («свежие ставки») for the live interim line (wired in .2/.3).
    """

    needs_check: bool
    query: str
    topic: str


@dataclass(frozen=True, slots=True)
class VolatilityContext:
    """The immutable input to a volatility judgment (only what the prompt needs).

    ``text`` is the user's incoming message. ``recent_thread`` is a light per-person
    snippet for light context (it may be empty). Kept minimal on purpose — the judge
    weighs meaning, not the full conversation state.
    """

    text: str
    recent_thread: str


@runtime_checkable
class VolatilityJudge(Protocol):
    """The seam: decide, by meaning, whether the answer hinges on a fresh volatile fact.

    Injectable so the decision is deterministic in tests (a fake returns a scripted
    :class:`VolatilityVerdict`) and swappable in tier without touching any consumer.
    """

    async def assess(self, ctx: VolatilityContext) -> VolatilityVerdict:
        """Weigh ``ctx`` and return the :class:`VolatilityVerdict`."""
        ...


def build_volatility_user_prompt(ctx: VolatilityContext) -> str:
    """Fold ``ctx`` into the Tier-0 user prompt (pure).

    Includes the light recent-thread snippet (context only) and the incoming
    message the judge weighs by meaning.
    """
    lines = [
        "Recent thread with this person:",
        ctx.recent_thread or "  (none)",
        "",
        "Incoming message:",
        ctx.text,
    ]
    return "\n".join(lines)


def parse_volatility_verdict(raw: str) -> VolatilityVerdict:
    """Parse the model's reply into a :class:`VolatilityVerdict` (conservative).

    Reads the labelled format (``needs_check:`` / ``query:`` / ``topic:``).
    🔴 US-2: an ambiguous, negative or garbled ``needs_check`` (no clear ``yes``)
    DEFAULTS to a non-checking verdict — don't check when unsure. Only an
    affirmative (``yes``) verdict with an empty ``query`` raises
    :class:`VolatilityJudgeParseError` (an unusable "check").
    """
    needs_text, query_text, topic_text = _scan_labels(raw)
    if not _is_affirmative(needs_text):
        return VolatilityVerdict(needs_check=False, query="", topic="")
    query = (query_text or "").strip()
    if not query:
        raise VolatilityJudgeParseError(f"affirmative verdict with no query in: {raw!r}")
    return VolatilityVerdict(
        needs_check=True, query=query, topic=(topic_text or "").strip()
    )


def _scan_labels(raw: str) -> tuple[str | None, str | None, str | None]:
    """Extract the needs_check / query / topic label values from ``raw`` (any may be None)."""
    needs_text: str | None = None
    query_text: str | None = None
    topic_text: str | None = None
    for line in raw.splitlines():
        if needs_text is None and (m := _NEEDS_LABEL.match(line)):
            needs_text = m.group(1)
        elif query_text is None and (m := _QUERY_LABEL.match(line)):
            query_text = m.group(1)
        elif topic_text is None and (m := _TOPIC_LABEL.match(line)):
            topic_text = m.group(1)
    return needs_text, query_text, topic_text


def _is_affirmative(text: str | None) -> bool:
    """Return ``True`` only for a clear affirmative ``needs_check`` value.

    Conservative by construction: a missing value, an explicit negative, or any
    unrecognisable token all yield ``False`` (don't check when unsure).
    """
    if text is None:
        return False
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        if word in _YES_TOKENS:
            return True
        if word in _NO_TOKENS:
            return False
    return False
