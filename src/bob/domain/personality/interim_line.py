# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Interim-line seam — pure prompt + cleaner for the live verify reply (BOB-057 .3).

US-3b: when the pre-answer verify (.2) decides to check, Bob does NOT go silent or
emit a scripted "ищу…". He sends a LIVE, ADDRESSED one-liner in his own voice that
names WHAT he's about to check and WHO he's talking to — «Леш, надо кое-что
проверить, погоди маленько…». This module holds the model-facing (pure) half:

* :data:`INTERIM_LINE_SYSTEM_PROMPT` — the persona contract: ONE short living line
  in Bob's voice, addressed by name, no preamble / quotes / multi-line ramble.
* :func:`build_interim_line_user_prompt` — folds the ``topic`` (human subject) and
  the ``sender_name`` into the Tier-0 user prompt (empty name → topic-only).
* :func:`clean_interim_line` — keeps the reply a single tidy line: first non-empty
  line, unquoted, bounded — so a chatty model still yields a one-liner.

DECORATIVE by design: the caller (the announcer) stays silent when this yields
nothing, so an empty clean is a legitimate "no live line".
"""

from __future__ import annotations

__all__ = [
    "INTERIM_LINE_SYSTEM_PROMPT",
    "build_interim_line_user_prompt",
    "clean_interim_line",
]

# One live line cannot be a paragraph — a runaway reply is trimmed to this bound so
# the interim stays a glance, never an essay (US-3b «живая реплика, не простыня»).
_MAX_INTERIM_CHARS = 160

# The minimum length for a line to POSSIBLY be a quoted pair (an opener + a closer).
_MIN_QUOTED_LEN = 2

# Wrapping quotes a model likes to add around a "quote me" line — stripped as a pair.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("'", "'"),
    ("«", "»"),
    ("“", "”"),
)

INTERIM_LINE_SYSTEM_PROMPT = (
    "Ты — Боб. Прямо сейчас ты собираешься быстро глянуть кое-что в сети — свериться "
    "с фактом или поискать по запросу, чтобы ответить точно. Напиши ЖИВУЮ реплику "
    "собеседнику — как в чате, своими словами, по-русски: обратись к человеку по имени, "
    "назови, ЧТО именно идёшь глянуть, и попроси секунду подождать. Тепло, "
    "по-человечески, можно лёгкий смайлик.\n"
    "Строго: ОДНА короткая строка, без кавычек, без вступлений и пояснений — только "
    "сама реплика. Не выдумывай сам факт (ты его ещё не знаешь) — только скажи, что "
    "идёшь проверить.\n"
    "Пример стиля: «Леш, гляну свежие ставки, секунду 🙂»."
)


def build_interim_line_user_prompt(*, topic: str, sender_name: str) -> str:
    """Fold ``topic`` + ``sender_name`` into the Tier-0 interim-line user prompt (pure).

    An empty ``sender_name`` (an unknown sender) drops the name line, leaving a
    usable topic-only prompt — Bob still names what he's checking, just unaddressed.
    """
    lines = [f"Что проверяешь: {topic}"]
    if sender_name.strip():
        lines.append(f"Имя собеседника: {sender_name.strip()}")
    lines.append("Твоя одна живая реплика:")
    return "\n".join(lines)


def clean_interim_line(raw: str) -> str:
    """Reduce a model reply to a single tidy interim line (pure).

    Keeps the FIRST non-empty line (a chatty model may add extra lines), strips a
    pair of wrapping quotes, and bounds the length so the interim stays a one-liner.
    An all-blank reply yields ``""`` — a legitimate "no live line" for the caller's
    silence.
    """
    line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    if not line:
        return ""
    line = _strip_wrapping_quotes(line)
    if len(line) > _MAX_INTERIM_CHARS:
        line = line[:_MAX_INTERIM_CHARS].rstrip()
    return line


def _strip_wrapping_quotes(line: str) -> str:
    """Strip ONE pair of matching wrapping quotes from ``line`` (else return as-is)."""
    for opening, closing in _QUOTE_PAIRS:
        if (
            len(line) >= _MIN_QUOTED_LEN
            and line.startswith(opening)
            and line.endswith(closing)
        ):
            return line[1:-1].strip()
    return line
