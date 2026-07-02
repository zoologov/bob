# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=introspection-domain

"""Pure parsers linking code history to its decision record (BOB-038 .1).

The deterministic, I/O-free domain predicates the ``code_rationale`` skill (.2)
uses to turn raw ``git log`` text into the "why" trail:

* :func:`parse_bead_refs` lifts the ``[BOB-XXX]`` bead keys out of commit-message
  lines (de-duplicated, first-seen order preserved) — the decisions a piece of
  code traces back to.
* :func:`commits_mentioning` filters that same ``git log`` text down to the lines
  that bracket ONE such key — the concrete commit trail behind that decision.
* :func:`feature_doc_dir` maps one such bead key to its feature-doc directory
  (``.claude/development/docs/features/{KEY}``) so the skill can read the PRD/RFC
  that explains the decision.

Both are pure functions: no subprocess, no disk — the git read itself lives behind
the :class:`~bob.domain.ports.RepoIntrospector` port in infrastructure.
"""

from __future__ import annotations

import re

# A bracketed decision key as it appears in a commit subject, e.g. ``[BOB-037]``.
# Case-insensitive on input; the captured number identifies the bead/epic.
_BEAD_REF_RE = re.compile(r"\[BOB-(\d+)\]", re.IGNORECASE)

# A standalone feature/epic bead key (``BOB-038``) — the only shape that maps to a
# feature-doc directory. The node-id shape (``bob-4be.1``) is deliberately excluded.
_FEATURE_KEY_RE = re.compile(r"^BOB-\d+$", re.IGNORECASE)

# Where a feature's decision docs (PRD/RFC/CONTEXT/PLAN) live, keyed by bead key.
_FEATURE_DOCS_BASE = ".claude/development/docs/features"


def parse_bead_refs(git_log_text: str) -> list[str]:
    """Return the ``[BOB-XXX]`` bead keys mentioned in ``git_log_text``.

    Scans commit-message text for bracketed decision keys, normalises each to the
    canonical upper-case ``BOB-<n>`` form, and returns them de-duplicated with the
    first-seen order preserved. Only bracketed keys count (a bare ``BOB-999`` or a
    ``[#42]`` PR ref is not a decision key); no match yields an empty list.
    """
    seen: dict[str, None] = {}
    for match in _BEAD_REF_RE.finditer(git_log_text):
        key = f"BOB-{match.group(1)}"
        seen.setdefault(key, None)
    return list(seen)


def commits_mentioning(bead_key: str, git_log_text: str) -> list[str]:
    """Return the ``git_log_text`` lines whose subject brackets ``bead_key``.

    Filters the raw history to the commit lines carrying the ``[BOB-<n>]`` decision
    key (matched case-insensitively, exactly — ``BOB-3`` never matches ``BOB-37``),
    in first-seen order, each stripped of surrounding whitespace. A key that is not a
    strict feature bead key (a node-id like ``bob-4be.1``, or empty) yields an empty
    list, as does a history with no such line — the caller then renders nothing for
    that key rather than guessing. Pure: no subprocess, no disk.
    """
    token = bead_key.strip()
    if not _FEATURE_KEY_RE.match(token):
        return []
    number = token.upper().removeprefix("BOB-")
    pattern = re.compile(rf"\[BOB-{number}\]", re.IGNORECASE)
    return [
        line.strip()
        for line in git_log_text.splitlines()
        if pattern.search(line)
    ]


def feature_doc_dir(bead_key: str) -> str:
    """Return the feature-doc directory for ``bead_key`` (e.g. ``BOB-025``).

    The key is trimmed and case-normalised to ``BOB-<n>`` and joined onto the
    feature-docs base, yielding ``.claude/development/docs/features/BOB-<n>``. A
    value that is not a strict feature bead key (empty, a node-id like ``bob-4be.1``,
    or arbitrary text) raises :class:`ValueError` — the mapping is never guessed.
    """
    token = bead_key.strip()
    if not _FEATURE_KEY_RE.match(token):
        raise ValueError(f"not a feature bead key: {bead_key!r}")
    normalised = token.upper()
    return f"{_FEATURE_DOCS_BASE}/{normalised}"
