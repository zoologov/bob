# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure digest of a tracker SEARCH listing — the epic, what is alive, how many closed.

ONE responsibility: condense a long ``bd search`` listing into something a person can
read in a chat. A search by epic key legitimately matches dozens of tasks (``BOB-087``
matches 39 on the live tracker); pasting 39 lines back is exactly the wall of text
BOB-086 was fought over. So a listing LONGER than :data:`MAX_DIGEST_ITEMS` collapses
to three things — a status summary, the epic/feature nodes plus whatever is still not
closed, and an honest "not shown" tail — while a SHORT listing is returned untouched
(it is already readable, and re-rendering it would only lose information).

Nothing is ever invented and nothing is silently dropped: the counts are computed from
the real lines, and the tail states how many were left out. Deterministic, I/O-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# One ``bd search`` result line: ``<id> [P<n>] [<kind>] <status> [@assignee] - <title>``.
# Anything that does not match (the English "Found N issues" header, a blank line, a
# truncation marker) is not an entry and is simply not counted.
_ENTRY_RE = re.compile(
    r"^(?P<id>[A-Za-z][\w.-]*)\s+\[P\d+\]\s+\[(?P<kind>[a-z]+)\]\s+(?P<status>[a-z_]+)(?:\s|$)"
)

# How many result lines may survive into the digest. Chosen for a chat message: a
# dozen lines still reads as an answer, forty reads as a dump.
MAX_DIGEST_ITEMS = 10


@dataclass(frozen=True)
class _Entry:
    """One parsed search-result line: its raw text plus the two fields we sort by."""

    line: str
    kind: str
    status: str


def _parse_entry(line: str) -> _Entry | None:
    """Parse one listing line into an :class:`_Entry`, or ``None`` if it is not one."""
    match = _ENTRY_RE.match(line)
    if match is None:
        return None
    return _Entry(line=line, kind=match.group("kind"), status=match.group("status"))


def _summary(entries: list[_Entry]) -> str:
    """Render the status summary line (``Найдено: 39 — закрытых 39.``).

    Buckets are named here, in the body, so that losing one is a mutant the tests must
    kill (MUTATION.md). Statuses outside the three interesting ones (blocked/deferred)
    are counted honestly as "прочих" rather than vanishing from the total.
    """
    buckets = (("open", "открытых"), ("in_progress", "в работе"), ("closed", "закрытых"))
    parts = []
    named = 0
    for status, label in buckets:
        count = sum(1 for entry in entries if entry.status == status)
        named += count
        if count:
            parts.append(f"{label} {count}")
    other = len(entries) - named
    if other:
        parts.append(f"прочих {other}")
    return f"Найдено: {len(entries)} — {', '.join(parts)}."


def _highlights(entries: list[_Entry], max_items: int) -> list[_Entry]:
    """Pick the lines worth showing: the epic/feature nodes, then what is not closed.

    An epic answers "what was this about", the not-closed tasks answer "what is left"
    — together they are the question a person actually asked. The closed bulk is left
    to the counts, and the whole selection is capped.
    """
    container_kinds = ("epic", "feature")
    closed = "closed"
    containers = [entry for entry in entries if entry.kind in container_kinds]
    alive = [
        entry
        for entry in entries
        if entry.kind not in container_kinds and entry.status != closed
    ]
    return [*containers, *alive][:max_items]


def digest_search_results(raw: str, *, max_items: int = MAX_DIGEST_ITEMS) -> str:
    """Condense a long ``bd search`` listing; return a short one unchanged.

    ``raw`` is the CLI output. When it holds no more than ``max_items`` result lines
    it is returned verbatim. Otherwise the digest is: the status summary, the
    epic/feature and not-closed lines (capped at ``max_items``), and an honest tail
    naming how many lines were hidden.
    """
    parsed = (_parse_entry(line) for line in raw.splitlines())
    entries = [entry for entry in parsed if entry is not None]
    if len(entries) <= max_items:
        return raw
    shown = _highlights(entries, max_items)
    hidden = len(entries) - len(shown)
    tail = f"Скрыто: {hidden} — спроси про конкретную задачу."
    return "\n".join([_summary(entries), *(entry.line for entry in shown), tail])
