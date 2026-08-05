# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure request core for the read-only project-health reads (BOB-091.2).

ONE responsibility: shape a read-only beadloom HEALTH request — decide which fixed
invocation form answers the report that was asked for, and validate the single dynamic
slot (a git ref) that will reach argv.

Six reports, and they are deliberately a CLOSED list rather than a subcommand the model
picks: ``status`` (index statistics), ``prime`` (the compact project context),
``doctor`` (graph-integrity checks), ``sync-check`` (doc↔code freshness), ``lint``
(architecture boundaries) and ``diff`` (graph changes since a git ref). The same CLI
also has WRITE subcommands — ``reindex``, ``docs generate``, ``snapshot save``,
``link``, ``init``, ``install-hooks``, ``setup-*``, ``active-sync``, ``sync-update``,
``ci`` — so "let the model name the subcommand" would BE the write vector. Here an
unrecognised value raises instead of being forwarded, and the adapter re-checks the
resulting form before exec.

🔴 Two live facts of the real CLI are baked into the forms, not guessed:

* ``lint`` is planned as ``lint --no-reindex --strict``. A PLAIN ``beadloom lint``
  reindexes first — i.e. it WRITES the index (measured on this repo: the db file's
  content hash changes) — so ``--no-reindex`` is what keeps the read read-only, and
  ``--strict`` is what makes the exit code mean "error-level violations" (plain ``lint``
  exits 0 even when an error-level rule is broken). The price is honest and named in the
  digest: the verdict is read off the STORED index, which may lag the working tree.
* ``prime`` has an ``--update`` flag that REWRITES ``AGENTS.md``. Since the form is a
  fixed empty tuple, that flag is structurally inexpressible — the reason these are
  forms and not flag passthrough.

Pure functions: no subprocess, no disk, no LLM. This is a mutation-tested core; the
subprocess reads live behind the :class:`~bob.capabilities.ports.RepoIntrospector` port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The canonical checks, in the order the tool advertises them: cheapest/most general
# first. This tuple IS the closed enum the model chooses from.
HEALTH_CHECKS: tuple[str, ...] = (
    "status",
    "prime",
    "doctor",
    "sync-check",
    "lint",
    "diff",
)

# The exact argv tail of each check (after the subcommand). Empty for the reports that
# take no argument — which is precisely what makes ``--json`` / ``--project <other repo>``
# / ``prime --update`` inexpressible. ``diff`` is absent: its form carries a slot and is
# built by :func:`_diff_form`.
_FIXED_FORMS: dict[str, tuple[str, ...]] = {
    "status": (),
    "prime": (),
    "doctor": (),
    "sync-check": (),
    # 🔴 --no-reindex: a plain ``lint`` WRITES the index. --strict: otherwise rc=0 even
    # on an error-level violation.
    "lint": ("--no-reindex", "--strict"),
}

# The literal flag of the ``diff`` form (its value is a validated git ref).
_SINCE_FLAG = "--since"

# What ``diff`` compares against when the owner named no ref — the CLI's own default,
# stated explicitly so the planned form has exactly ONE shape to check.
DEFAULT_DIFF_REF = "HEAD"

# Paraphrases a model actually sends instead of the canonical enum value. Answering a
# paraphrase is not a widening of the surface: every value here maps onto one of
# :data:`HEALTH_CHECKS`, so nothing new becomes expressible — an unknown value still
# raises.
#
# 🔴 Deliberately ABSENT: ``docs`` and ``sync`` (for ``sync-check``). Both are the names
# of WRITE commands of the same CLI (``docs generate`` / ``sync-update``), and an alias
# that reads like a write command is a trap for the next reader even though it could only
# ever resolve to the read. They are refused instead — the ambiguity is not worth it.
_ALIASES: dict[str, str] = {
    "статус": "status",
    "состояние": "status",
    "stats": "status",
    "context": "prime",
    "контекст": "prime",
    "health": "doctor",
    "здоровье": "doctor",
    "доктор": "doctor",
    "sync_check": "sync-check",
    "synccheck": "sync-check",
    "доки": "sync-check",
    "линт": "lint",
    "boundaries": "lint",
    "границы": "lint",
    "дифф": "diff",
    "changes": "diff",
    "изменения": "diff",
}

# A git ref: a branch / tag / sha / ``HEAD``-relative expression. Anchored and
# separator-strict — this regex IS the injection guard for the ref slot, since the value
# reaches a git-shaped argument. Allowed: letters, digits, ``_``, ``-``, ``.``, ``/``
# (branch paths) and the ``~`` / ``^`` navigation suffixes. A leading ``-`` (a flag), a
# leading ``/`` or ``.``, whitespace, a shell metacharacter, a quote, ``@{`` (reflog) or
# a glob character therefore cannot match.
_GIT_REF_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./~^-]*$")

# Ref shapes that MATCH the character class above but are still refused, mirroring git's
# own refname rules: a range (``a..b``) is two refs, a trailing ``/`` or ``.`` is
# malformed, and ``.lock`` is reserved.
_REF_FORBIDDEN_SUBSTRINGS = ("..",)
_REF_FORBIDDEN_SUFFIXES = ("/", ".", ".lock")

# Upper bound on a ref's length: a 40-char sha is the longest real value by far.
_MAX_REF_CHARS = 64


@dataclass(frozen=True)
class HealthForm:
    """One allowed read-only beadloom health invocation.

    ``check`` is the canonical report name (what the answer is LABELLED by, so Bob can
    say which command he actually ran), ``subcommand`` + ``args`` are the fully-resolved
    invocation the adapter membership-checks and runs.
    """

    check: str
    subcommand: str
    args: tuple[str, ...]


def is_git_ref(raw: str) -> bool:
    """Whether ``raw`` (trimmed) is a strict, safe git ref for the ``diff`` slot.

    The non-raising twin of :func:`validate_git_ref`, exposed so the adapter can
    re-assert the slot of an already-built form without an exception.
    """
    token = raw.strip()
    if not token or len(token) > _MAX_REF_CHARS:
        return False
    if not _GIT_REF_RE.match(token):
        return False
    if any(bad in token for bad in _REF_FORBIDDEN_SUBSTRINGS):
        return False
    return not token.endswith(_REF_FORBIDDEN_SUFFIXES)


def validate_git_ref(raw: str) -> str:
    """Return ``raw`` trimmed as a git ref, or raise :class:`ValueError`.

    Case is preserved: git refs are case-SENSITIVE, so folding it would answer about a
    different branch. A flag, a path, a range, a shell metacharacter, embedded
    whitespace, reflog syntax, an over-long or empty value raises — this is the guard for
    the only model-chosen value that reaches argv on this path.
    """
    token = raw.strip()
    if not is_git_ref(token):
        raise ValueError(f"not a valid git ref: {raw!r}")
    return token


def normalize_check(raw: str) -> str:
    """Return the canonical check name for ``raw``, or raise :class:`ValueError`.

    Trims, case-folds and resolves a paraphrase. 🔴 An unrecognised value RAISES: the
    write subcommands of this CLI (``reindex`` / ``docs`` / ``link`` / ``setup-*``) are
    exactly the strings that would arrive here, and forwarding one would be the write
    vector this planner exists to close.
    """
    token = raw.strip().lower()
    canonical = _ALIASES.get(token, token)
    if canonical not in HEALTH_CHECKS:
        raise ValueError(f"{raw!r} is not a read-only project-health check")
    return canonical


def _diff_form(since: str | None) -> HealthForm:
    """The graph-diff form: ``diff --since <ref>`` with a validated ref slot."""
    asked = since.strip() if since is not None else ""
    ref = validate_git_ref(asked) if asked else DEFAULT_DIFF_REF
    return HealthForm(check="diff", subcommand="diff", args=(_SINCE_FLAG, ref))


def plan_health_form(check: str, *, since: str | None = None) -> HealthForm:
    """Plan the allowed read-only beadloom form that produces the asked-for report.

    ``check`` is resolved against the closed list (:func:`normalize_check`); ``since``
    applies to ``diff`` alone and is IGNORED elsewhere, so it cannot widen another
    check's fixed form. A blank ``since`` means "not asked" and yields the CLI's own
    default ref; a non-blank value that is not a git ref raises :class:`ValueError`
    before any form exists.
    """
    canonical = normalize_check(check)
    if canonical == "diff":
        return _diff_form(since)
    return HealthForm(
        check=canonical, subcommand=canonical, args=_FIXED_FORMS[canonical]
    )
