# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""Backlog catch-up — rank an away-period backlog and pick ONE pass worth of it (BOB-066 3.2).

When Bob comes back to a chat that filled up while he was busy, a real participant does
not machine-gun a reply at every message he missed. He glances over the pile ONCE, and
answers the handful that actually want him — under a budget — while the ambient chatter he
merely skims stays skimmed. This module holds the two pure decisions behind that «catch
up like a person» behaviour:

* :func:`score` — the priority of one backlogged message, as a single number. The order is
  **banded and load-bearing**: a message that addressed Bob *directly* always outranks a
  reply within *his thread*, which always outranks *ambient* chatter — no matter how fresh
  or salient the ambient is (the band gap exceeds the in-band range by construction).
  Within a band, a fresher message beats a merely more-salient one (freshness > salience).
* :func:`select_catchup` — one reflective pass over the whole backlog: rank it, then keep
  the top of it under an action ``budget``. 🔴 **Backpressure with priority:** a focal
  (direct-address) message is NEVER dropped or collapsed — only *peripheral ambient* beyond
  the budget collapses (INV-1/INV-10). The budget caps how many *ambient* asides Bob picks
  up on re-entry, never how many people he answers.

Pure and deterministic by construction (``now`` is injected, no I/O, no rng): the verdict
is pinned by unit tests and hardened by mutation — the ``LLM verbalises → pure core
decides`` principle, exactly like :func:`~bob.presence.staleness.decide_staleness`. The
semantic inputs a message carries (``salience``, the addressivity flags) are VERBALISED
upstream; this core only weighs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

__all__ = [
    "BacklogMessage",
    "BacklogScorer",
    "CatchUpPlan",
    "is_reentry",
    "rank",
    "score",
    "select_catchup",
]

# ── Banded priority weights ──────────────────────────────────────────────────────
# Each band is a whole-number floor; the in-band contribution (freshness + salience)
# can never reach a full band, so the order direct > reply-thread > ambient is ABSOLUTE
# regardless of freshness/salience. This is the focal guarantee at the score level.
_BAND_DIRECT = 2.0  # addressed to Bob directly (mention / reply-to-Bob / «Боб,»)
_BAND_REPLY_THREAD = 1.0  # a reply continuing a thread Bob is part of
_BAND_AMBIENT = 0.0  # everything else — passing chatter

# In-band contribution: freshness outweighs salience (a fresh message wants Bob's
# attention more than a stale-but-interesting one), and the two together stay below the
# 1.0 band gap so a band is never crossed. 0.6 + 0.3 = 0.9 < 1.0.
_FRESHNESS_WEIGHT = 0.6
_SALIENCE_WEIGHT = 0.3

_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, slots=True)
class BacklogMessage:
    """One backlogged message as value primitives — no transport/application types.

    Carried BY VALUE (not the runtime ``MessageReceived``) so the presence domain stays
    free of application imports, mirroring
    :class:`~bob.presence.staleness.ArrivedMessage`. ``addressed_to_bob`` marks a raw
    direct address (mention / reply-to-Bob / name) — the focal band that is never dropped;
    ``reply_to_bob_thread`` marks a message continuing a thread Bob is in without a raw
    direct address; ``salience`` is the ambient «worth chiming in» read in ``[0, 1]``;
    ``at`` is the message's arrival time (weighed against ``now`` for freshness).
    """

    sender_id: int | None
    text: str
    addressed_to_bob: bool
    reply_to_bob_thread: bool
    salience: float
    at: datetime


@dataclass(frozen=True, slots=True)
class CatchUpPlan:
    """The outcome of one catch-up pass: what Bob acts on now vs what he lets pass.

    ``to_answer`` is the ranked, focal-first slice Bob picks up on re-entry (every focal
    message plus ambient up to the budget); ``collapsed`` is the peripheral ambient that
    exceeded the budget — skimmed, not individually replied to. A focal message is never
    in ``collapsed``.
    """

    to_answer: tuple[BacklogMessage, ...]
    collapsed: tuple[BacklogMessage, ...]


def _clamp_unit(value: float) -> float:
    """Clamp ``value`` into ``[0.0, 1.0]`` so an out-of-range salience never crosses a band."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _band(msg: BacklogMessage) -> float:
    """Return the priority-band floor for ``msg`` (direct > reply-thread > ambient)."""
    if msg.addressed_to_bob:
        return _BAND_DIRECT
    if msg.reply_to_bob_thread:
        return _BAND_REPLY_THREAD
    return _BAND_AMBIENT


def _recency(at: datetime, now: datetime) -> float:
    """Return a freshness factor in ``(0, 1]`` — 1.0 at ``now``, decaying with age.

    Uses ``1 / (1 + age_hours)`` so freshness falls off smoothly and monotonically.
    A non-positive age (a message timestamped at or after ``now`` — clock skew) clamps to
    the maximum 1.0, so skew never yields a negative or runaway score.
    """
    age_hours = (now - at).total_seconds() / _SECONDS_PER_HOUR
    if age_hours <= 0.0:
        return 1.0
    return 1.0 / (1.0 + age_hours)


def is_reentry(
    last_seen: datetime | None, now: datetime, *, threshold_hours: float
) -> bool:
    """Return whether Bob is RE-ENTERING this chat after an away period — pure, deterministic.

    A re-entry is what turns «reply to each backlogged message» into «one catch-up pass»: it is
    ``True`` only when Bob has a prior activity mark (``last_seen``) AND the gap to ``now`` is at
    or beyond ``threshold_hours`` (the boundary is inclusive). A missing ``last_seen`` (the
    first-ever batch — nothing to catch up on) and a non-positive gap (clock skew — ``last_seen``
    at/after ``now``) both read as «not a re-entry», so catch-up never fires on normal
    back-and-forth or a skewed clock. No I/O — pinned by unit tests and mutation.
    """
    if last_seen is None:
        return False
    gap_hours = (now - last_seen).total_seconds() / _SECONDS_PER_HOUR
    return gap_hours >= threshold_hours


def score(msg: BacklogMessage, *, now: datetime) -> float:
    """Return the catch-up priority of ``msg`` at ``now`` — pure, banded, deterministic.

    The result is ``band + freshness·w_f + salience·w_s``: the band
    (direct/reply-thread/ambient) sets the whole-number floor and dominates absolutely,
    while freshness (weighted above salience) breaks ties within a band. Higher means
    «answer this sooner». No I/O, no rng — pinned by unit tests and mutation.
    """
    return (
        _band(msg)
        + _FRESHNESS_WEIGHT * _recency(msg.at, now)
        + _SALIENCE_WEIGHT * _clamp_unit(msg.salience)
    )


def rank(
    messages: Iterable[BacklogMessage], *, now: datetime
) -> tuple[BacklogMessage, ...]:
    """Return ``messages`` ordered by :func:`score` descending (stable for ties).

    A stable sort means messages of equal score keep their arrival order, so a tie is
    resolved the way a person reads a backlog — oldest-first among equals.
    """
    return tuple(sorted(messages, key=lambda m: score(m, now=now), reverse=True))


def select_catchup(
    messages: Iterable[BacklogMessage], *, now: datetime, budget: int
) -> CatchUpPlan:
    """Pick ONE catch-up pass over ``messages`` under an ambient action ``budget``.

    Ranks the whole backlog, then keeps every focal (direct-address) message plus ambient
    up to ``budget`` peripheral slots. 🔴 Focal messages are NEVER collapsed — the budget
    only limits how many *ambient* asides ride along on re-entry (INV-1/INV-10); a
    non-positive budget still answers all focal and drops all ambient. The kept slice
    stays in ranked order.
    """
    ranked = rank(messages, now=now)
    focal_count = sum(1 for msg in ranked if msg.addressed_to_bob)
    ambient_slots = max(0, budget - focal_count)
    to_answer: list[BacklogMessage] = []
    collapsed: list[BacklogMessage] = []
    ambient_used = 0
    for msg in ranked:
        if msg.addressed_to_bob:
            to_answer.append(msg)
        elif ambient_used < ambient_slots:
            to_answer.append(msg)
            ambient_used += 1
        else:
            collapsed.append(msg)
    return CatchUpPlan(to_answer=tuple(to_answer), collapsed=tuple(collapsed))


@dataclass(frozen=True, slots=True)
class BacklogScorer:
    """Pure facade over the catch-up core — scores and selects a backlog.

    Wraps the module-level :func:`score` and :func:`select_catchup` so a collaborator can
    hold one injectable object; carries no state, so the pure functions stay the mutation
    surface.
    """

    def score(self, msg: BacklogMessage, *, now: datetime) -> float:
        """Return the catch-up priority of ``msg`` at ``now`` (delegates to :func:`score`)."""
        return score(msg, now=now)

    def select(
        self, messages: Iterable[BacklogMessage], *, now: datetime, budget: int
    ) -> CatchUpPlan:
        """Return the catch-up plan for ``messages`` (delegates to :func:`select_catchup`)."""
        return select_catchup(messages, now=now, budget=budget)
