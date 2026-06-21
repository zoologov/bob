# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""HeuristicReflectionParser — deterministic reflection -> signal (no LLM, no I/O).

The default realisation of the :class:`~bob.application.usecases.apply_reflection.ReflectionParser`
port. A conservative keyword heuristic: it fires only when a reflection mentions
a topic Bob actually has a taste for AND carries a clear sentiment polarity
(positive/negative markers, ru + en since Bob's persona language is Russian).
Anything vague returns ``None`` so the relevance gate keeps the soul still.

The port stays abstract on purpose — a Tier-0 LLM parser swaps in later without
any consumer change (see RFC Q1). Keywords live here, not in the domain core.
"""

from __future__ import annotations

import re

from bob.application.usecases.apply_reflection import ReflectionSignal

# Sentiment polarity is a bounded, fixed-magnitude nudge — evolution stays slow.
_NUDGE_MAGNITUDE = 1.0

# Lowercased sentiment markers; bilingual because Bob reflects in Russian (BOB-012).
_POSITIVE_MARKERS = frozenset(
    {
        "love",
        "like",
        "enjoy",
        "adore",
        "lifts",
        "люблю",
        "нравится",
        "обожаю",
        "радует",
    }
)
_NEGATIVE_MARKERS = frozenset(
    {
        "hate",
        "dislike",
        "loathe",
        "tired",
        "annoy",
        "ненавижу",
        "раздражает",
        "надоело",
        "устал",
    }
)


class HeuristicReflectionParser:
    """Deterministic keyword parser mapping a reflection to a taste signal."""

    def parse(
        self,
        reflection: str,
        *,
        topics: tuple[str, ...],
    ) -> ReflectionSignal | None:
        """Return the signal in ``reflection`` over Bob's ``topics``, or ``None``.

        Fires only on a topic match AND a clear sentiment polarity; mixed or
        absent sentiment, or an unknown topic, yields ``None`` (relevance gate).
        """
        text = reflection.casefold()
        topic = _first_mentioned(text, topics)
        if topic is None:
            return None
        nudge = _polarity(text)
        if nudge == 0.0:
            return None
        return ReflectionSignal(topic=topic, nudge=nudge)


def _first_mentioned(text: str, topics: tuple[str, ...]) -> str | None:
    """Return the first ``topics`` entry that appears in ``text`` (case-folded)."""
    for topic in topics:
        if topic.casefold() in text:
            return topic
    return None


def _polarity(text: str) -> float:
    """Return a signed nudge from sentiment markers, or 0.0 if mixed/absent.

    Markers match on word boundaries so "dislike" never trips the "like" marker.
    """
    words = set(re.findall(r"\w+", text, flags=re.UNICODE))
    has_positive = bool(words & _POSITIVE_MARKERS)
    has_negative = bool(words & _NEGATIVE_MARKERS)
    if has_positive == has_negative:  # both or neither -> ambiguous, no signal.
        return 0.0
    return _NUDGE_MAGNITUDE if has_positive else -_NUDGE_MAGNITUDE
