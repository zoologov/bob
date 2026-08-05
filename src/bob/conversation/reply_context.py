# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Shareable reply context — compose Bob's reply-shaping context (Variant 2).

The material that shapes Bob's reply AND returns to the same user (recent history,
identity, mood tone, the EFFECTIVE taste verdict, phantom preferences, recalled
memories) is assembled here into the ``shareable_context`` the reply tier MAY see
(VISION §7.1) — as opposed to genuinely-internal material, which belongs in
``private_context``.

Lives in the conversation domain (BOB-062.6b Wave 0): assembling the turn's reply
context is a conversation concern that legitimately reaches into ``personality`` for
the soul's mood-modulated taste (:func:`~bob.personality.mood_taste.modulate`,
:func:`~bob.personality.mood_taste.experiment_bias`) — the one-directional
conversation→personality edge (BOB-062.6a).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.conversation.thread_places import thread_block
from bob.personality.mood_taste import experiment_bias, modulate
from bob.personality.taste import Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.memory.ports import Recalled
    from bob.personality.soul import SOUL

# Effective-verdict modulation (BOB-020) needs the sign of Bob's liking to lean a
# NEUTRAL verdict the right way; the stored axis value is private to TasteEngine, so
# we read the sign off the verdict itself (positive verdicts → +1, negative → -1,
# NEUTRAL → 0 so an unknown topic stays a clean identity under any mood).
_POSITIVE_VERDICTS = frozenset({Verdict.LOVE, Verdict.LIKE})
_NEGATIVE_VERDICTS = frozenset({Verdict.DISLIKE, Verdict.HATE})


def _verdict_sign(verdict: Verdict) -> float:
    """+1.0 for a positive verdict, -1.0 for a negative one, 0.0 for NEUTRAL."""
    if verdict in _POSITIVE_VERDICTS:
        return 1.0
    if verdict in _NEGATIVE_VERDICTS:
        return -1.0
    return 0.0


def _assemble_shareable_context(
    soul: SOUL,
    topic: str,
    recalled: Sequence[Recalled],
    history: Sequence[Mapping[str, object]],
    *,
    absence: str | None = None,
    mark_places: bool = False,
) -> str:
    """Compose Bob's reply-shaping context (Variant 2: MAY reach Tier 1).

    Carries recent conversation history, identity, mood tone, the taste verdict
    on the topic, phantom preferences, and recalled memories — all material that
    shapes Bob's reply and returns to the same user, so the reply tier sees it
    (this is what lets Bob remember a name said one message ago). Genuinely
    internal material is NOT assembled here; it belongs in ``private_context``.

    The taste verdict injected is the EFFECTIVE one (BOB-020): Bob's current mood
    temporarily colours it via :func:`modulate` — a flat day reads it stricter, a
    bright day softer — and an experiment-readiness hint from the same mood rides
    along. This is temporary modulation only; the stored taste axes are untouched.

    When ``absence`` is given (BOB-045 .3) — the person's per-person thread has been
    idle past the configured threshold — ONE light ``Absence:`` line is appended so the
    reply tier can acknowledge the pause naturally. It is a hint, not a directive; with
    no/short gap (or the hint disabled) ``absence`` is ``None`` and no line is added.

    🔴 ``mark_places`` (BOB-090.C3, behind ``memory.origin_provenance``): the replayed
    thread carries WHERE each turn was said (:func:`~bob.conversation.thread_places.
    thread_block`). The DM appeared in BOB-082 and its turns share this thread with the
    room's, so without the place Bob read сказанное наедине as сказанное при всех and
    announced «я же только что рассказал ГРУППЕ» about a joke he had made in the DM.
    OFF (default) → the block is byte-identical to the pre-C3 one.
    """
    stored = soul.taste.score(topic)
    effective = modulate(stored, _verdict_sign(stored), soul.mood)
    lines = [
        f"Identity: {soul.identity}",
        f"Mood tone: {soul.mood.tone()}",
        f"Taste verdict on '{topic}': {effective.value}",
        f"Experiment readiness: {experiment_bias(soul.mood):.2f}",
    ]
    if soul.phantom_prefs:
        lines.append("Phantom preferences: " + ", ".join(soul.phantom_prefs))
    thread = thread_block(history, mark_places=mark_places)
    if thread:
        lines.append(thread)
    if absence:
        lines.append(f"Absence: {absence}")
    memories = [str(item.get("content", "")) for item in recalled]
    if memories:
        lines.append("Recalled memories: " + " | ".join(memories))
    return "\n".join(lines)
