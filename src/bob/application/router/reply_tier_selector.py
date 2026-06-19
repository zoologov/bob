# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Hybrid reply-tier selector — pick a fast or a quality model per user message.

GUPPI's responsiveness policy for user replies (BOB-006). A live reply on the
Tier 1 reasoning model (``qwen3.7-plus``) can take minutes — too slow for chat —
so casual/short turns should answer on the fast Tier 0 model (``qwen3.6-flash``)
and only complex/long/tool-needing turns should pay for the quality model.

The choice is a **pure, deterministic heuristic on the incoming user message**
(no extra LLM round-trip): escalate to the quality tier when the message is long,
asks several questions, carries code, or contains a depth/complexity keyword
(``объясни`` / ``проанализируй`` / ``напиши код`` …); otherwise stay on flash. A
turn that needs tools always prefers the quality model, which tool-calls more
reliably.

This is pure application policy — it returns a tier index for the
:class:`~bob.application.router.llm_router.LLMRouter`; it holds no model names or
transport knowledge (those live in the per-tier provider built by the factory).
"""

from __future__ import annotations

import re

_TIER_LOCAL = 0  # the fast model (qwen3.6-flash) — responsive default for chat.
_TIER_API = 1  # the quality model (qwen3.7-plus) — depth for complex turns.

# A message longer than this many characters is treated as "long" and escalated
# to the quality model. Tuned for chat: a casual turn is well under this.
_LONG_MESSAGE_CHARS = 240

# More than this many question marks signals a multi-question turn wanting depth.
_MAX_CASUAL_QUESTIONS = 1

# Depth/complexity cues: a turn asking Bob to explain, analyse, compare, or write
# code wants the quality model. Matched whole-word and case-insensitively below.
# Tunable: extend this set as new complexity cues surface in real conversations.
_DEPTH_KEYWORDS = frozenset(
    {
        "объясни",
        "расскажи",
        "подробно",
        "проанализируй",
        "сравни",
        "напиши",
        "разбери",
        "почему",
        "устроен",
        "устроена",
    }
)

# Whole-word matcher over the lowercased message (Unicode word boundaries), so a
# keyword embedded in a larger word (e.g. "сравни" inside "сравнительно") does
# not spuriously escalate.
_WORD_RE = re.compile(r"\w+", re.UNICODE)

# A fenced code block is a strong signal of a coding turn.
_CODE_FENCE = "```"


def select_reply_tier(message: str, *, needs_tools: bool = False) -> int:
    """Pick the reply tier for ``message`` — fast Tier 0 unless it looks complex.

    Returns ``_TIER_API`` (quality model) when the turn needs tools or the
    message looks complex (long, multi-question, code, or a depth keyword);
    otherwise ``_TIER_LOCAL`` (fast model). Deterministic: equal inputs always
    yield the same tier.
    """
    if needs_tools or _looks_complex(message):
        return _TIER_API
    return _TIER_LOCAL


def _looks_complex(message: str) -> bool:
    """True when the message carries any escalation signal (length/questions/code/keyword)."""
    if len(message) > _LONG_MESSAGE_CHARS:
        return True
    if message.count("?") > _MAX_CASUAL_QUESTIONS:
        return True
    if _CODE_FENCE in message:
        return True
    return _has_depth_keyword(message)


def _has_depth_keyword(message: str) -> bool:
    """True when any whole word in ``message`` is a depth/complexity keyword."""
    words = _WORD_RE.findall(message.lower())
    return any(word in _DEPTH_KEYWORDS for word in words)
