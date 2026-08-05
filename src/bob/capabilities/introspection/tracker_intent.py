# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure tracker-intent planner — what is this question asking the tracker for?

ONE responsibility: turn a free-text tracker question into a :class:`TrackerPlan` —
the ready queue, a listing (optionally filtered by status), one task by id, or a
SEARCH by epic key / word. Deterministic and I/O-free; the adapter merely executes
the plan against the read-only ``bd`` allowlist, so this module decides WHAT is read
and never HOW.

Why it exists (BOB-090.A, the live symptom): «какие открыты?» produced «Пусто»
because the keyword map had закрыт/в работе/все but no *открыт*, so an obvious
listing question fell through to a doomed ``bd show`` on prose; and «расскажи про
BOB-087» could not work at all, because in ``bd`` the identifier is ``bob-abk`` while
the key ``BOB-087`` lives only in the TITLE — a question about an epic is a SEARCH,
and the key has to be cut out of the sentence (``bd`` matches a title substring, so
the whole phrase matches nothing).

🔴 Every search term leaves here through :func:`sanitize_search_term`, so a
flag-shaped fragment of a question can never become a flag in argv (BOB-087.D2).
Policy words live INSIDE the functions (not in module constants) so the mutation gate
on them is real — see ``.claude/dev-docs/MUTATION.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from bob.capabilities.introspection.dev_query import is_bead_id, sanitize_search_term

# A bead/epic key MENTIONED inside a sentence: an epic key (``BOB-087``) or a node id
# (``bob-alr.1``). The boundaries keep it from matching inside a longer word
# (``abob-1``) while allowing the punctuation a human writes around it
# (``[BOB-090].A``, ``про BOB-087.``). Case-insensitive — ``bd`` matches titles
# case-insensitively too.
_BEAD_KEY_IN_TEXT_RE = re.compile(
    r"(?<![\w-])(?:BOB-\d+|bob-[a-z0-9]+)(?:\.\d+)?(?!\w)", re.IGNORECASE
)

# Word boundaries for keyword matching: anything that is not a word char or a hyphen
# separates words, so "in-progress" stays ONE token while "какие открыты?" splits.
_WORD_SPLIT_RE = re.compile(r"[^\w-]+")

TrackerPlanKind = Literal["ready", "list", "show", "search"]


@dataclass(frozen=True)
class TrackerPlan:
    """A read-only tracker read to perform: ``kind`` plus its single argument.

    ``ready`` — the ready queue (no argument); ``list`` — a listing, ``argument``
    being a status enum or ``None`` for unfiltered; ``show`` — one task, ``argument``
    being its id; ``search`` — a title search, ``argument`` being the sanitised term.
    """

    kind: TrackerPlanKind
    argument: str | None = None


def find_bead_key(text: str) -> str | None:
    """Return the first bead/epic key mentioned in ``text``, or ``None``.

    ``"расскажи про нашу задачу BOB-087"`` → ``"BOB-087"``. This is what makes a
    question about an epic answerable: the key lives in tracker TITLES, and ``bd``
    matches a title substring, so the sentence around the key must be dropped.
    """
    match = _BEAD_KEY_IN_TEXT_RE.search(text)
    if match is None:
        return None
    return match.group(0)


def _mentions(low: str, words: tuple[str, ...]) -> bool:
    """Whether the lower-cased ``low`` mentions any of ``words``.

    A single-word keyword matches a WORD PREFIX, not a bare substring: Russian
    inflection means "закрыт" must catch "закрытые", but a blind substring test also
    catches "все" inside "совсем" and turns an ordinary sentence into a listing
    request. A multi-word keyword ("в работе") is matched as a substring, since it
    already carries its own boundaries.
    """
    tokens = _WORD_SPLIT_RE.split(low)
    return any(
        word in low
        if " " in word
        else any(token.startswith(word) for token in tokens)
        for word in words
    )


def _wants_ready(low: str) -> bool:
    """Whether the question asks for the ready queue (what can be started now)."""
    return _mentions(low, ("ready", "готов"))


def _plan_listing(low: str) -> TrackerPlan | None:
    """Return the listing plan the question asks for, or ``None`` if it asks none.

    The status vocabulary is checked in a FIXED precedence — closed, in-progress,
    open, then an unfiltered "all" — so a question naming two of them resolves
    deterministically. The words live here, in the body, so that dropping one is a
    mutant the tests must kill (MUTATION.md: policy values belong inside functions).
    """
    closed_words = ("закрыт", "недавн", "истори", "recent", "closed", "history")
    # "занят" — a question about what Bob is BUSY with is a question about the
    # in-progress list (the phrasing that used to fall through to a plain list).
    in_progress_words = ("в работе", "in progress", "in-progress", "занят")
    open_words = ("открыт", "open", "актуальн")
    all_words = ("все", "весь", "all", "list", "список")
    if _mentions(low, closed_words):
        return TrackerPlan(kind="list", argument="closed")
    if _mentions(low, in_progress_words):
        return TrackerPlan(kind="list", argument="in_progress")
    if _mentions(low, open_words):
        return TrackerPlan(kind="list", argument="open")
    if _mentions(low, all_words):
        return TrackerPlan(kind="list", argument=None)
    return None


def _plan_for_key(token: str) -> TrackerPlan | None:
    """Return the plan for a question that NAMES a task, or ``None`` if it names none.

    A bare id is that one task; a key mentioned inside a sentence is a search for that
    key (a question about one epic is never a request to list everything).
    """
    if is_bead_id(token):
        return TrackerPlan(kind="show", argument=token)
    key = find_bead_key(token)
    if key is None:
        return None
    return TrackerPlan(kind="search", argument=key)


def plan_tracker_query(query: str) -> TrackerPlan:
    """Plan the read-only tracker read that answers ``query``.

    Precedence, most specific first: an empty question or a "ready" question → the
    ready queue; a bare id → that one task; a key MENTIONED in a sentence → a search
    for that key (a question about one epic is never a request to list everything);
    a status/listing question → the matching listing; anything else → a search on the
    sanitised text, degrading to the plain listing when nothing safe survives
    sanitising.
    """
    token = query.strip()
    if not token:
        return TrackerPlan(kind="ready")
    low = token.lower()
    if _wants_ready(low):
        return TrackerPlan(kind="ready")
    named = _plan_for_key(token)
    if named is not None:
        return named
    listing = _plan_listing(low)
    if listing is not None:
        return listing
    term = sanitize_search_term(token)
    if term is None:
        return TrackerPlan(kind="list")
    return TrackerPlan(kind="search", argument=term)
