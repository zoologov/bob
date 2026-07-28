# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Long-gap absence texture — "haven't seen you in a while" (BOB-045 .3).

One pure, deterministic helper, :func:`absence_hint`. When Bob resumes a
conversation with a person after a long pause (a night, a day), he should notice
it HUMANLY — not with a scripted phrase, but with a light contextual hint the reply
tier can fold in naturally. Given the timestamp of that person's LAST prior turn and
``now`` (plus a threshold), this returns a SHORT neutral note bucketing the gap the
way a person would feel it — hours, "вчера", or "несколько дней" — rather than a raw
delta. It is a HINT for the compose prompt, never a directive Bob must utter.

Pure and deterministic by construction: it takes ``now`` (from the injected
:class:`~bob.domain.ports.Clock`) and the last-seen timestamp, does no I/O, and is
safe under clock skew (a non-positive gap never hints).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_SECONDS_PER_HOUR = 3600.0
_HOURS_PER_DAY = 24
_HOURS_PER_TWO_DAYS = 48

# Russian numeral-agreement boundaries for the "час" plural (see :func:`_plural_hours`).
_TEENS_START = 11  # 11-14 always take the "часов" form, regardless of the last digit
_TEENS_END = 14
_FEW_START = 2  # a last digit of 2-4 takes "часа"
_FEW_END = 4


def absence_hint(
    last_seen: datetime, now: datetime, *, threshold_hours: float
) -> str | None:
    """Return a light absence note for the gap since ``last_seen``, or ``None``.

    The gap between ``last_seen`` (the person's last prior turn) and ``now`` is
    bucketed humanly. ``None`` — meaning "add no line, behave as before" — is returned
    when the hint is disabled (``threshold_hours <= 0``), when the gap does not EXCEED
    ``threshold_hours``, or when the gap is non-positive (clock skew / first contact
    fed a future or equal timestamp). Otherwise a short neutral Russian note describes
    the gap as a person would feel it: a count of hours within a day, "вчера" up to two
    days, or "несколько дней" beyond — a context HINT for the reply tier, never a
    scripted phrase Bob must say. Pure and deterministic; no I/O.
    """
    if threshold_hours <= 0:
        return None
    gap_hours = (now - last_seen).total_seconds() / _SECONDS_PER_HOUR
    if gap_hours <= threshold_hours:
        return None
    if gap_hours < _HOURS_PER_DAY:
        hours = round(gap_hours)
        return f"последний разговор был около {hours} {_plural_hours(hours)} назад"
    if gap_hours < _HOURS_PER_TWO_DAYS:
        return "последний разговор был вчера"
    return "последний разговор был несколько дней назад"


def _plural_hours(count: int) -> str:
    """Return the Russian plural of "час" agreeing with ``count``.

    Standard Russian numeral agreement: "час" for a count ending in 1 (but not 11),
    "часа" for 2-4 (but not 12-14), "часов" otherwise — so the hint reads naturally
    ("21 час", "22 часа", "11 часов").
    """
    tens = count % 100
    if _TEENS_START <= tens <= _TEENS_END:
        return "часов"
    ones = count % 10
    if ones == 1:
        return "час"
    if _FEW_START <= ones <= _FEW_END:
        return "часа"
    return "часов"
