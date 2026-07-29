# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""Staleness-judge prompt + parser — the model-facing half of the seam (BOB-066 Срез W.3).

The pure verdict lives in :mod:`bob.presence.staleness` (``decide_staleness``); the
SEMANTIC read that feeds it — «did the room shift under this draft?» — is verbalised by a
cheap judge through the :class:`~bob.presence.ports.StalenessJudge` port. This module is that
judge's pure half, mirroring :mod:`bob.conversation.volatility_judgment`:

* :data:`STALENESS_JUDGE_SYSTEM_PROMPT` — states the task and the labelled output contract.
  🔴🔴 It instructs the model that ``answered``/``closed`` are MUTUALLY EXCLUSIVE with
  ``new_question``: a message carrying a fresh DIRECT question to Bob is NEVER «redundant», so
  the focal signal can never be read into a drop (INV-1, belt-and-braces with the pure core,
  which also merges a fresh question ahead of any drop).
* :func:`build_staleness_user_prompt` — folds the drafted reply + what landed during
  generation into the user prompt.
* :func:`parse_staleness_reading` — maps the reply to a
  :class:`~bob.presence.staleness.StalenessReading`, TOLERANT of format. An unreadable field
  DEFAULTS to ``False`` (the fail-safe = «ничего не сместилось» → the gate SENDs), so a garbled
  read never silently drops Bob's reply.
"""

from __future__ import annotations

import re

from bob.presence.staleness import StalenessContext, StalenessReading

__all__ = [
    "STALENESS_JUDGE_SYSTEM_PROMPT",
    "build_staleness_user_prompt",
    "parse_staleness_reading",
]

# Labelled-line prefixes the parser recognises (case-insensitive, whitespace-tolerant).
_ANSWERED_LABEL = re.compile(r"^\s*answered\s*:\s*(.+)$", re.IGNORECASE)
_CLOSED_LABEL = re.compile(r"^\s*closed\s*:\s*(.+)$", re.IGNORECASE)
_CLARIFIED_LABEL = re.compile(r"^\s*clarified\s*:\s*(.+)$", re.IGNORECASE)
_NEW_QUESTION_LABEL = re.compile(r"^\s*new_question\s*:\s*(.+)$", re.IGNORECASE)

# Affirmative / negative tokens for the boolean fields.
_YES_TOKENS: frozenset[str] = frozenset({"yes", "true", "y", "да"})
_NO_TOKENS: frozenset[str] = frozenset({"no", "false", "n", "нет"})

# Punctuation trimmed off a scanned token before matching.
_WORD_TRIM = " \t\n.!?,:;'\"*-"

STALENESS_JUDGE_SYSTEM_PROMPT = (
    "Ты — Боб. Ты уже написал ЧЕРНОВИК ответа, но пока писал, в чат прилетели новые "
    "сообщения. Реши, как сместился контекст под твоим черновиком. Отвечай КОНСЕРВАТИВНО: "
    "если не уверен — считай, что ничего не сместилось.\n"
    "Оцени ЧЕТЫРЕ признака:\n"
    "answered = yes, если на тот же вопрос УЖЕ ответил кто-то другой за это время "
    "(твой черновик стал дублем).\n"
    "closed = yes, если тема закрылась / вопрос сняли и ответ больше не нужен.\n"
    "clarified = yes, если ТОТ ЖЕ автор уточнил/поправил свой вопрос.\n"
    "new_question = yes, если прилетел СВЕЖИЙ ПРЯМОЙ вопрос к тебе (обращение к Бобу).\n"
    "🔴 ВАЖНО: answered и closed ВЗАИМОИСКЛЮЧАЮТ new_question. Сообщение со свежим "
    "прямым вопросом к тебе НИКОГДА не «избыточно» — если есть new_question=yes, ставь "
    "answered=no и closed=no.\n"
    "Ответь СТРОГО в этом размеченном формате, без лишнего:\n"
    "answered: <yes|no>\n"
    "closed: <yes|no>\n"
    "clarified: <yes|no>\n"
    "new_question: <yes|no>"
)


def build_staleness_user_prompt(ctx: StalenessContext) -> str:
    """Fold ``ctx`` into the Tier-0 user prompt (pure).

    Shows the draft Bob composed this turn and, in arrival order, what landed while he composed
    it — each arrival marked when it @mentions Bob / replies to him / comes from the same author
    he is answering, so the judge can read a fresh direct question or a same-author clarification.
    """
    lines = ["Твой черновик ответа:", ctx.drafted, "", "Прилетело, пока ты писал:"]
    if not ctx.newly_arrived:
        lines.append("  (ничего)")
    for arrival in ctx.newly_arrived:
        marks = []
        if arrival.from_draft_author:
            marks.append("тот же автор")
        if arrival.reply_to_bob:
            marks.append("ответ тебе")
        if arrival.mentions_bob:
            marks.append("упоминает тебя")
        suffix = f" [{', '.join(marks)}]" if marks else ""
        lines.append(f"- {arrival.text}{suffix}")
    return "\n".join(lines)


def parse_staleness_reading(raw: str) -> StalenessReading:
    """Parse the model's reply into a :class:`StalenessReading` (fail-safe by construction).

    Reads the labelled format; each unreadable / negative / missing field DEFAULTS to ``False``
    (= «этот сигнал не сместился»). So a garbled reply reads as «ничего не сместилось» and the
    pure gate SENDs the draft — Bob never silently drops a reply on an unreadable judge read.
    """
    answered, closed, clarified, new_question = _scan_labels(raw)
    return StalenessReading(
        answered_by_other=_is_affirmative(answered),
        topic_closed=_is_affirmative(closed),
        same_author_clarified=_is_affirmative(clarified),
        new_direct_question=_is_affirmative(new_question),
        reason=raw.strip(),
    )


def _scan_labels(
    raw: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract the answered / closed / clarified / new_question label values (any may be None)."""
    answered: str | None = None
    closed: str | None = None
    clarified: str | None = None
    new_question: str | None = None
    for line in raw.splitlines():
        if answered is None and (m := _ANSWERED_LABEL.match(line)):
            answered = m.group(1)
        elif closed is None and (m := _CLOSED_LABEL.match(line)):
            closed = m.group(1)
        elif clarified is None and (m := _CLARIFIED_LABEL.match(line)):
            clarified = m.group(1)
        elif new_question is None and (m := _NEW_QUESTION_LABEL.match(line)):
            new_question = m.group(1)
    return answered, closed, clarified, new_question


def _is_affirmative(text: str | None) -> bool:
    """Return ``True`` only for a clear affirmative value (a missing/negative/garbled → False)."""
    if text is None:
        return False
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        if word in _YES_TOKENS:
            return True
        if word in _NO_TOKENS:
            return False
    return False
