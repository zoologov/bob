# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=domain

"""Register-recall RANK pipeline — the teeth of the down-weight (BOB-087.C2).

C1 (:mod:`bob.memory.register`) gives the pure, ORDER-PRESERVING attenuation of a work
episode's relevance in CASUAL. On its own that cannot EVICT a work episode: attenuating a
pool that is already the display-k top-k just re-weights the same k items — there is nothing
below them to promote. The teeth are here.

:func:`register_ranked` runs the full recall-side policy on an OVER-FETCHED pool (best-first):

* it stamps a higher-is-better POSITIONAL relevance onto each item, derived from recall's own
  ranking (so the attenuation is sign-independent of the underlying BM25 score and C1's
  «higher = stronger claim» contract holds by construction);
* it lets C1's :func:`~bob.memory.register.filter_by_register` MUTE the work episodes;
* it RE-SORTS by that relevance (descending) and truncates to display-k.

So in CASUAL a work episode genuinely drops out of the final slots while a non-work item
rises from deeper in the over-fetched pool — yet сквозной Боб holds: when there is not enough
non-work to fill the slots, the strongest work episode still surfaces (muted, never cut). In
DEV the pipeline is the identity truncation — recall unchanged, the original item objects
preserved (no re-scoring).

:func:`pool_has_work` is the Tier-0 economy gate: whether the pool holds any work episode at
all, so the resolver can skip the classifier when there is nothing to mute. Both are pure and
deterministic (no I/O), the mutation-bearing core of the register-recall teeth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.memory.register import (
    RECALL_WEIGHT_FULL,
    Register,
    filter_by_register,
    may_recall_in_register,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.memory.ports import Recalled

__all__ = ["pool_has_work", "register_ranked"]


def register_ranked(
    pool: Sequence[Recalled],
    register: Register,
    *,
    display_k: int,
) -> tuple[Recalled, ...]:
    """Apply ``register`` to an over-fetched ``pool`` and return the top ``display_k``.

    In DEV this is the identity truncation: the best-first ``pool`` truncated to
    ``display_k`` with its item objects untouched. In CASUAL each item is stamped with a
    higher-is-better positional relevance (from its recall rank), C1 mutes the work
    episodes, and the pool is re-sorted by that relevance (descending) before truncation —
    so muted work drops out of the final slots while deeper non-work rises. Pure.
    """
    if register is Register.DEV:
        return tuple(pool[:display_k])
    ranked = _with_positional_relevance(pool)
    attenuated = filter_by_register(ranked, register)
    ordered = sorted(attenuated, key=_relevance_of, reverse=True)
    return tuple(ordered[:display_k])


def pool_has_work(pool: Sequence[Recalled]) -> bool:
    """Whether ``pool`` holds any of Bob's ``work`` dev episodes — pure.

    Reuses C1's public weight: an item is a work episode iff it would be muted in CASUAL
    (``may_recall_in_register < RECALL_WEIGHT_FULL``). The Tier-0 economy gate — no work to
    mute means the register classifier can be skipped entirely.
    """
    return any(_is_work(item) for item in pool)


def _is_work(item: Recalled) -> bool:
    """True when ``item`` is a work episode (muted in CASUAL by C1's public weight)."""
    weight = may_recall_in_register(
        category=_category_of(item),
        tags=_tags_of(item),
        register=Register.CASUAL,
    )
    return weight < RECALL_WEIGHT_FULL


def _with_positional_relevance(pool: Sequence[Recalled]) -> tuple[Recalled, ...]:
    """Stamp each item with a higher-is-better ``score`` from its recall rank.

    Recall returns best-first; the top item gets ``len(pool)`` and each subsequent item one
    less, so the relevance is monotonic with recall order and strictly positive. This is the
    score C1 attenuates, making the down-weight bite regardless of the underlying (BM25)
    score's sign or magnitude.
    """
    n = len(pool)
    return tuple({**item, "score": float(n - index)} for index, item in enumerate(pool))


def _relevance_of(item: Recalled) -> float:
    """Read an item's (possibly attenuated) positional relevance for the re-sort."""
    value = item.get("score")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _category_of(item: Recalled) -> str | None:
    """Read a recalled memory's ``category`` (its episodic ``event_type``) as a string."""
    value = item.get("category")
    return value if isinstance(value, str) else None


def _tags_of(item: Recalled) -> tuple[str, ...] | None:
    """Read a recalled memory's ``tags`` as a tuple of strings, or ``None`` if absent."""
    value = item.get("tags")
    if isinstance(value, (list, tuple)):
        return tuple(tag for tag in value if isinstance(tag, str))
    return None
