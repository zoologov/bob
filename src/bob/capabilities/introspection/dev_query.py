# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure validation core for Bob's read-only dev-introspection (BOB-081.1).

The deterministic, I/O-free predicates that shape EVERY dynamic value before it
reaches a subprocess in the introspection adapter — the form guard that keeps the
read-only invariant (INV-1) impossible to talk around:

* :func:`clamp_commit_count` bounds a requested ``git log`` size into ``[1, 50]``
  (``None`` → a sensible default) so history is never unbounded.
* :func:`validate_bead_id` accepts ONLY a bead-key shape (``BOB-<n>`` / ``bob-<id>``
  with an optional ``.<n>`` node suffix) and raises on anything else — a flag, a
  shell metacharacter, a path segment, whitespace, empty — so an id forwarded to
  ``bd``/``git`` can never smuggle an argument.
* :func:`normalize_status` maps a free-text status (English enum or a Russian
  synonym) to the tracker allowlist, returning ``None`` for anything unknown
  (meaning "no status filter") — a status outside the enum never reaches the CLI.

Pure functions: no subprocess, no disk, no LLM — so they cannot be bypassed by
anything the model says. This is the mutation-tested core; the subprocess reads
live behind the :class:`~bob.capabilities.ports.RepoIntrospector` port.
"""

from __future__ import annotations

import re

# A strict bead key: an epic key ``BOB-076`` or a graph node-id ``bob-0gj``, with an
# optional ``.<n>`` sub-task/node suffix (``bob-0gj.1``). Case-insensitive. This is
# the ONLY shape allowed for an id forwarded to ``bd``/``git`` — a flag, a shell
# metacharacter, a path segment, or whitespace never matches, so the regex is the
# injection guard.
_BEAD_ID_RE = re.compile(r"^(?:BOB-\d+|bob-[a-z0-9]+)(?:\.\d+)?$", re.IGNORECASE)

# The tracker's stored-status enum — the only values ``bd list --status`` accepts.
_TRACKER_STATUSES: frozenset[str] = frozenset(
    {"open", "in_progress", "blocked", "deferred", "closed"}
)

# Free-text synonyms (RU) mapping to the tracker enum. Keys are compared lower-cased
# and trimmed; anything not here (and not already an enum value) → ``None``.
_STATUS_SYNONYMS: dict[str, str] = {
    "в работе": "in_progress",
    "закрытые": "closed",
    "закрыто": "closed",
    "открытые": "open",
}

# History-size bounds for ``git log -n <N>``.
_MIN_COMMITS = 1
_MAX_COMMITS = 50
_DEFAULT_COMMITS = 10


def clamp_commit_count(n: int | None) -> int:
    """Return a bounded ``git log`` commit count in ``[1, 50]``.

    ``None`` yields the default (10). A value below the minimum clamps up to 1, a
    value above the maximum clamps down to 50 — so history is always bounded and a
    caller can never request an unbounded (or non-positive) log.
    """
    if n is None:
        return _DEFAULT_COMMITS
    return max(_MIN_COMMITS, min(n, _MAX_COMMITS))


def validate_bead_id(raw: str) -> str:
    """Return the trimmed ``raw`` iff it is a strict bead-key, else raise.

    Accepts only ``BOB-<n>`` / ``bob-<id>`` with an optional ``.<n>`` suffix
    (case-insensitive). A flag (``-x`` / ``--x``), a shell metacharacter (``;``), a
    path char (``..`` / ``/``), embedded whitespace, or an empty value raises
    :class:`ValueError` — this is the injection guard for ids passed to a subprocess.
    """
    token = raw.strip()
    if not _BEAD_ID_RE.match(token):
        raise ValueError(f"not a valid bead id: {raw!r}")
    return token


def normalize_status(raw: str | None) -> str | None:
    """Map ``raw`` to a tracker-status enum value, or ``None`` (no status filter).

    An exact enum value passes through; a known Russian synonym (``в работе`` →
    ``in_progress``, ``закрытые``/``закрыто`` → ``closed``, ``открытые`` → ``open``)
    maps to its enum; ``None``, empty, or an unrecognised value yields ``None`` —
    meaning "list without a status filter" (never a guessed status).
    """
    if raw is None:
        return None
    token = raw.strip().lower()
    if token in _TRACKER_STATUSES:
        return token
    return _STATUS_SYNONYMS.get(token)
