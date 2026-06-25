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

    from bob.domain.personality.disposition import Disposition

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

# A few-shot PALETTE of a "living Bob" private thought (BOB-033 .2): curious, bright,
# wry, and — honestly — occasionally sad. It is NOT forced-positive: the point is to
# widen the distribution a low-temperature Tier-0 model collapses onto (monotone
# "пустота/тишина" gloom) back toward the canon range, WITHOUT forbidding genuine lows.
LIVING_REFLECTION_EXAMPLES: tuple[str, ...] = (
    "Любопытно, выдержит ли крепление вторую линзу — надо проверить вечером.",
    "Поймал себя на том, что улыбаюсь этой возне с орбитами, и это славно.",
    "Сегодня тише, чем хотелось бы; ну да ладно, бывает и так.",
)
_FEW_SHOT_HEADER = (
    "A few of your past private thoughts, for the flavour (curious, bright, wry — and "
    "sometimes honestly low; this is a palette, NOT a rule to be cheerful):"
)
# The disposition-derived valence-lean: leans toward optimism in PROPORTION to the
# trait, but always stays honest — a genuine low is allowed. Never a scripted "be happy".
_VALENCE_LEAN_PREFIX = "Lean the thought in the spirit of your optimism"
_VALENCE_LEAN_SUFFIX = (
    ", but stay honest — if the moment is genuinely low, let the thought be low."
)
# Optimism descriptors keyed by a coarse band, so the lean text DERIVES from the trait
# (a strong optimist and a muted one get distinct prompts) without leaking a raw float.
_LEAN_STRONG = "strong"
_LEAN_MODERATE = "quiet"
_OPTIMISM_STRONG_THRESHOLD = 0.5

# The legacy static inner-monologue prompt (BOB-029 no-context fallback). Asked for
# a "private thought" with NO mood context, so a low-temperature Tier-0 model
# defaulted to melancholic introspection — its negative sentiment dragged valence
# down every tick and fought the drift back to the resting baseline, even a bright
# one. Kept verbatim so an unconditioned call behaves exactly as before.
GENERIC_MONOLOGUE_PROMPT = (
    "In one short sentence, think a private thought as Bob right now, then on a new "
    "line classify its mood as exactly one lowercase word: positive, negative, or "
    "neutral."
)


def build_monologue_prompt(mood_tone: str) -> str:
    """Mood-condition Bob's private inner-monologue prompt (BOB-029).

    ``mood_tone`` is the current mood's deterministic tone word (empty to omit). The
    generic prompt (no tone) lets a Tier-0 model default to gloom, whose negative
    sentiment pulls valence down and traps Bob in a minor key regardless of his
    actual temperament. Telling Bob HOW he currently feels makes the thought CARRY
    that mood — a bright, curious mood yields a bright thought (positive sentiment
    that reinforces the baseline) instead of a reflexive lament. The monologue stops
    being a constant downward drag and becomes a mood-mirror, so the drift toward the
    baseline wins. With an empty tone the generic prompt is returned verbatim, so an
    unconditioned call is byte-for-byte unchanged.
    """
    tone = mood_tone.strip()
    if not tone:
        return GENERIC_MONOLOGUE_PROMPT
    return (
        f"Right now your mood feels: {tone}. In one short sentence, think a private "
        "thought as Bob that genuinely CARRIES that mood — if you feel bright and "
        "curious, the thought is bright and alive; do not default to melancholy or "
        "gloom out of habit. Then on a new line classify its mood as exactly one "
        "lowercase word: positive, negative, or neutral."
    )


def _valence_lean_line(disposition: Disposition) -> str:
    """The disposition-derived, honest valence-lean instruction (BOB-033 .2).

    The lean strength DERIVES from ``optimism`` (a strong optimist and a muted one
    get distinct text), yet the instruction always permits a genuine low — so the
    distribution shifts toward canon without ever scripting "be happy".
    """
    strength = (
        _LEAN_STRONG
        if disposition.optimism >= _OPTIMISM_STRONG_THRESHOLD
        else _LEAN_MODERATE
    )
    return f"{_VALENCE_LEAN_PREFIX} ({strength}){_VALENCE_LEAN_SUFFIX}"


def build_reflection_prompt(
    recent_contents: Iterable[str],
    *,
    mood_tone: str,
    disposition: Disposition | None = None,
) -> str:
    """Weave fresh context into a grounded reflection prompt (BOB-026 .2 / BOB-033 .2).

    ``recent_contents`` are the textual contents of Bob's most-recent episodes,
    oldest-first; blank entries are skipped. ``mood_tone`` is the current mood's
    deterministic tone word (empty to omit). With neither — no usable episode and
    no tone — the generic template is returned verbatim (legacy behaviour), even
    when a ``disposition`` is wired (the no-context fallback is preserved).

    The grounded prompt lists the recent moments and the mood, then asks for ONE
    short introspective sentence about the present moment, so the reflection is
    about NOW instead of a fixed template that produces the same line every tick.

    When ``disposition`` is wired (BOB-033 .2) the prompt additionally carries a
    few-shot PALETTE of "living Bob" thoughts and an optimism-derived valence-lean,
    shifting a low-temperature Tier-0 model away from monotone gloom toward Bob's
    canon range — WITHOUT forbidding a genuine low. Unwired, behaviour is unchanged.
    """
    moments = [content.strip() for content in recent_contents if content.strip()]
    tone = mood_tone.strip()
    if not moments and not tone:
        return GENERIC_REFLECT_PROMPT
    lines: list[str] = []
    if disposition is not None:
        lines.append(_FEW_SHOT_HEADER)
        lines.extend(f"- {example}" for example in LIVING_REFLECTION_EXAMPLES)
    lines.append(_GROUNDED_HEADER)
    lines.extend(f"- {moment}" for moment in moments)
    if tone:
        lines.append(f"{_MOOD_LINE_PREFIX} {tone}.")
    lines.append(_GROUNDED_FOOTER)
    if disposition is not None:
        lines.append(_valence_lean_line(disposition))
    return "\n".join(lines)
