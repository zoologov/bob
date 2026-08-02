# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=domain

"""Register-aware recall — the pure down-weight core of Bob's dev/casual memory (BOB-087.C1).

Register is the conversational MODE of a turn — is Bob operating as a developer (``DEV``)
or just chatting (``CASUAL``) — and it colours which of his own memories should press into
a reply. This is a distinct concern from такт разглашения
(:mod:`~bob.social.disclosure`): disclosure keys on WHO is listening (the social
:class:`~bob.social.interlocutor.Trust`); register keys on WHAT mode the conversation is
in. It lives in the memory domain because it works purely on recalled memory items, keyed
on the ``work`` provenance minted by :mod:`~bob.memory.work_journal`.

* :class:`Register` — ``DEV`` / ``CASUAL`` (the memory-side analogue of ``Trust``).
* :func:`may_recall_in_register` — the pure weight: a ``work`` dev episode gets a small
  :data:`CASUAL_WORK_WEIGHT` in CASUAL (muted) but :data:`RECALL_WEIGHT_FULL` in DEV; any
  non-work memory always keeps full weight.
* :func:`filter_by_register` — the recall-pipeline filter (mirrors
  :func:`~bob.social.disclosure.filter_surfaceable`): in CASUAL it ATTENUATES each work
  episode's relevance ``score`` by that weight so it rarely wins a slot, yet is NEVER cut
  (сквозной Боб — a strong match can still surface one); in DEV it returns the input
  byte-identical (the identity path, like a TRUSTED interlocutor in disclosure).

Pure and deterministic (no I/O, same inputs → same verdict), so the recall filter stays
testable without a store or an LLM. Attenuation is multiplicative on a relevance score
where HIGHER means a stronger claim to a slot; a work item with no score is baselined to
:data:`RECALL_WEIGHT_FULL` first, so it too becomes rankable and muted rather than silently
un-weighted.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from bob.memory.work_journal import _WORK_TAGS as _WORK_TAG_SOURCE
from bob.memory.work_journal import WORK_EVENT_TYPE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "CASUAL_WORK_WEIGHT",
    "RECALL_WEIGHT_FULL",
    "Register",
    "filter_by_register",
    "may_recall_in_register",
]

# The identity multiplier: recall untouched (full standing).
RECALL_WEIGHT_FULL = 1.0

# The slot-claim a work episode retains in CASUAL — small but > 0, so a dev memory is
# muted yet can still surface on a strong match (сквозной Боб, not a silo).
CASUAL_WORK_WEIGHT = 0.15

# Recall-side recognition of the work provenance minted by ``work_journal`` (BOB-087.B1):
# the ``work`` event_type OR any of its domain/provenance tags. A memory carrying any of
# these is one of Bob's operator dev recollections. Sourced from ``work_journal`` (the same
# memory domain) so the write-side and read-side share ONE provenance definition — no drift.
_WORK_TAGS = frozenset(_WORK_TAG_SOURCE)


class Register(Enum):
    """The conversational MODE of a turn — orthogonal to who is listening.

    DEV — Bob is operating as a developer (his work memories carry full weight); CASUAL —
    ordinary chat (his ``work`` dev episodes are muted so they rarely crowd a casual reply,
    though a strong match can still surface one).
    """

    DEV = "dev"
    CASUAL = "casual"


def may_recall_in_register(
    *,
    category: str | None,
    tags: Iterable[str] | None,
    register: Register,
) -> float:
    """The weight a memory of this provenance keeps in ``register`` — pure.

    In a DEV register every memory keeps :data:`RECALL_WEIGHT_FULL` (recall unchanged). In
    CASUAL a ``work`` dev episode — matched by ``category`` (case-insensitive) OR any work
    provenance tag — is muted to :data:`CASUAL_WORK_WEIGHT`, while any non-work memory
    keeps full weight. Deterministic: same inputs → same weight.
    """
    if register is Register.DEV:
        return RECALL_WEIGHT_FULL
    if _is_work_memory(category, tags):
        return CASUAL_WORK_WEIGHT
    return RECALL_WEIGHT_FULL


def filter_by_register(
    recalled: Sequence[Mapping[str, object]],
    register: Register,
) -> tuple[Mapping[str, object], ...]:
    """Attenuate work episodes' relevance for ``register`` — pure and order-preserving.

    The recall-pipeline filter (mirrors
    :func:`~bob.social.disclosure.filter_surfaceable`): in a DEV register every item passes
    through byte-identical (INV — dev recall unchanged); in CASUAL each ``work`` dev
    episode's ``score`` is multiplied by :data:`CASUAL_WORK_WEIGHT` so it rarely wins a
    slot, yet stays in the result (сквозной Боб — never cut). Non-work items are untouched.
    Nothing is added or removed; order is preserved.
    """
    if register is Register.DEV:
        return tuple(recalled)
    return tuple(_attenuated(item, register) for item in recalled)


def _attenuated(
    item: Mapping[str, object], register: Register
) -> Mapping[str, object]:
    """Return ``item`` with its ``score`` scaled by its register weight (untouched if full)."""
    weight = may_recall_in_register(
        category=_category_of(item), tags=_tags_of(item), register=register
    )
    if weight >= RECALL_WEIGHT_FULL:
        return item
    return {**item, "score": _score_of(item) * weight}


def _is_work_memory(category: str | None, tags: Iterable[str] | None) -> bool:
    """True when the memory is one of Bob's ``work`` dev episodes (category OR tag)."""
    if isinstance(category, str) and category.casefold() == WORK_EVENT_TYPE:
        return True
    if tags is None:
        return False
    return any(
        isinstance(tag, str) and tag.casefold() in _WORK_TAGS for tag in tags
    )


def _category_of(item: Mapping[str, object]) -> str | None:
    """Read a recalled memory's ``category`` (its episodic ``event_type``) as a string."""
    value = item.get("category")
    return value if isinstance(value, str) else None


def _tags_of(item: Mapping[str, object]) -> tuple[str, ...] | None:
    """Read a recalled memory's ``tags`` as a tuple of strings, or ``None`` if absent."""
    value = item.get("tags")
    if isinstance(value, (list, tuple)):
        return tuple(tag for tag in value if isinstance(tag, str))
    return None


def _score_of(item: Mapping[str, object]) -> float:
    """Read a recalled memory's relevance ``score``; baseline to full weight when absent.

    A score-less work item is baselined to :data:`RECALL_WEIGHT_FULL` so multiplying by its
    register weight still yields a concrete, muted score rather than leaving it un-weighted.
    """
    value = item.get("score")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return RECALL_WEIGHT_FULL
