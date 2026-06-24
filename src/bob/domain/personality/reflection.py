# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Grounded reflection prompt — make Bob's inner monologue about NOW (BOB-026 .2).

Pure, no-LLM prompt assembly. The reflect tick used a single STATIC template
("write one short reflective sentence about how things have been going lately")
and a low Tier-0 temperature, so it returned the same thought every ~5 min — 740
reflections, only 565 unique, plus mass near-duplicates (a stuck record).

:func:`build_reflection_prompt` weaves a little FRESH context — a few of Bob's
most-recent episodes and his current mood tone — into the prompt so the reflection
is grounded in what is actually happening now rather than a fixed template. It
still asks for exactly ONE short introspective sentence. With NO fresh context
(no episodes, no tone) it returns the generic prompt verbatim, so an unwired tick
behaves exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# The legacy static template (kept as the no-context fallback so an unwired tick is
# byte-for-byte unchanged).
GENERIC_REFLECT_PROMPT = (
    "As Bob, write one short, reflective sentence about how things have been "
    "going lately. Keep it private and introspective."
)

_GROUNDED_HEADER = (
    "As Bob, reflect privately on how things are going RIGHT NOW. Recent moments "
    "from your day:"
)
_GROUNDED_FOOTER = (
    "Write one short, introspective sentence about this present moment — not a "
    "generic musing. Keep it private; do not repeat a thought you have already had."
)
_MOOD_LINE_PREFIX = "Your current mood feels:"


def build_reflection_prompt(
    recent_contents: Iterable[str],
    *,
    mood_tone: str,
) -> str:
    """Weave fresh context into a grounded reflection prompt (BOB-026 .2).

    ``recent_contents`` are the textual contents of Bob's most-recent episodes,
    oldest-first; blank entries are skipped. ``mood_tone`` is the current mood's
    deterministic tone word (empty to omit). With neither — no usable episode and
    no tone — the generic template is returned verbatim (legacy behaviour).

    The grounded prompt lists the recent moments and the mood, then asks for ONE
    short introspective sentence about the present moment, so the reflection is
    about NOW instead of a fixed template that produces the same line every tick.
    """
    moments = [content.strip() for content in recent_contents if content.strip()]
    tone = mood_tone.strip()
    if not moments and not tone:
        return GENERIC_REFLECT_PROMPT
    lines = [_GROUNDED_HEADER]
    lines.extend(f"- {moment}" for moment in moments)
    if tone:
        lines.append(f"{_MOOD_LINE_PREFIX} {tone}.")
    lines.append(_GROUNDED_FOOTER)
    return "\n".join(lines)
