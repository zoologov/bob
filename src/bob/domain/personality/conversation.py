# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""User-repeat detection — does the owner repeat what he just said? (BOB-022).

A pure, no-LLM predicate. When the owner sends (near-)the-same message he already
sent in the recent window, Bob should NOTICE it (and react in his own wry voice
via :func:`~bob.domain.personality.voice.user_repeat_directive`) rather than
silently re-answer. The detection is the upstream side of that reaction; the voice
directive is the downstream side.

Deliberately CONSERVATIVE: a repeat is an EXACT match after normalisation
(strip / casefold / collapse internal whitespace), never fuzzy. Exact-after-
normalise can never false-fire on a merely-similar turn, so Bob never accuses the
owner of repeating himself when he did not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def _normalise(text: str) -> str:
    """Strip, casefold, and collapse internal whitespace for an exact compare.

    Two messages that differ only in case or whitespace are the same message for
    repeat-detection purposes; everything else is left intact so the match stays
    exact (never fuzzy).
    """
    return " ".join(text.split()).casefold()


def is_user_repeat(current: str, prior_user_texts: Iterable[str]) -> bool:
    """Return ``True`` iff ``current`` exactly repeats a recent prior user turn.

    Both sides are normalised (strip / casefold / collapse whitespace) and matched
    exactly — conservative by design so it never false-fires. An empty/blank
    ``current`` is never a repeat (nothing meaningful to repeat).
    """
    normalised_current = _normalise(current)
    if not normalised_current:
        return False
    return any(normalised_current == _normalise(prior) for prior in prior_user_texts)
