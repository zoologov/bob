# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""PrivacyGuard — the deterministic privacy invariant for self-introspection.

The single source of truth for "may Bob read this path / return this text" in
Phase A (BOB-017). It is a PURE domain object: no I/O, no LLM, no prompt — so it
**cannot be bypassed by anything the model says**. The infrastructure adapter
(:class:`~bob.infrastructure.introspection.subprocess_introspector.SubprocessRepoIntrospector`)
consults :meth:`PrivacyGuard.allows_path` BEFORE opening any file and runs every
tool's text output through :meth:`PrivacyGuard.sanitize`.

The invariant (PRD-mandated, not an option):

* **ALLOW ONLY** paths under the read-only roots — the source/test/doc trees
  ``src/``, ``tests/``, ``docs/`` plus the curation-vision doc subtrees
  ``.claude/dev-docs/`` (ROADMAP / VISION / audits) and
  ``.claude/development/docs/`` (feature PRD/RFC/CONTEXT/PLAN/BRIEF) — and those
  roots themselves.
* **DENY** everything else, in particular the personal-data roots — ``data/soul/**``
  (SOUL.md + profiles), ``data/bob.db*`` (the memory DB + its WAL/SHM siblings),
  ``.env*`` (secrets), and ``config/**`` — plus the rest of ``.claude/`` (its
  ``settings*.json``, ``agents/``, ``commands/``, top-level ``CLAUDE.md``) and any
  path that escapes the repo via ``..`` traversal or an absolute path outside the
  repo root.

An allowed root may be MULTI-SEGMENT (``.claude/dev-docs``): containment is matched
by FULL path-prefix — every segment of a root must be a prefix of the target's
segments — so adding ``.claude/dev-docs`` opens ONLY that subtree, never the rest
of ``.claude/``. Paths are resolved (``..`` collapsed) against the repo root before
matching, so a path that climbs out of an allowed root into a denied one is denied
by construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The ONLY roots Bob may read from — repo-relative, read-only source/docs trees.
# Each entry is a repo-relative root spec, written with ``/`` and possibly
# MULTI-SEGMENT (``.claude/dev-docs``); a root is split into its path segments and
# matched by full path-prefix (see :meth:`PrivacyGuard.allows_path`) so a
# multi-segment root opens ONLY that subtree and never its siblings (the rest of
# ``.claude/`` — settings, agents, commands, CLAUDE.md — stays denied). Exposed
# (and aliased privately for in-module use) as the single source of truth so the
# infra adapter's symlink-containment re-check shares the same roots.
ALLOWED_ROOTS: tuple[str, ...] = (
    "src",
    "tests",
    "docs",
    ".claude/dev-docs",
    ".claude/development/docs",
)
_ALLOWED_ROOTS: tuple[str, ...] = ALLOWED_ROOTS

# Each allowed root pre-split into its path segments, so matching is a pure
# segment-prefix comparison (no string-prefix ambiguity: ``srcfoo`` is not ``src``).
_ALLOWED_ROOT_SEGMENTS: tuple[tuple[str, ...], ...] = tuple(
    tuple(root.split("/")) for root in _ALLOWED_ROOTS
)

# What the redaction marker leaves behind in sanitized output.
_REDACTION = "[REDACTED]"

# Secret-shaped patterns scrubbed from any tool output before it can be returned:
# - KEY=value env assignments (uppercase env-style key with a non-trivial value),
# - api-key-ish tokens (``sk-``-prefixed or long opaque secret values).
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^[A-Z][A-Z0-9_]*\s*=\s*\S+\s*$"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*\S+"),
)


@dataclass(frozen=True, slots=True)
class PrivacyGuard:
    """Pure, frozen policy deciding readable paths and redacting secret output.

    Construct with the absolute ``repo_root``; both predicates are deterministic
    and side-effect free.
    """

    repo_root: Path

    def allows_path(self, path: Path) -> bool:
        """Whether ``path`` may be read under the DENY-invariant.

        ``path`` is resolved against the repo root (``..`` segments collapsed, no
        disk access) and accepted ONLY when its segments are prefixed by one of the
        allowed roots (``src``/``tests``/``docs``, or the multi-segment
        ``.claude/dev-docs`` / ``.claude/development/docs``) or exactly equal a root.
        Matching is by full path-prefix on segments, so a multi-segment root opens
        only its own subtree (the rest of ``.claude/`` stays denied) and a lookalike
        sibling (``srcfoo``) is never mistaken for an allowed root. Everything else —
        denied personal-data roots, repo-root files, traversal that escapes an
        allowed root, absolute paths outside the repo — is denied.
        """
        root = self._resolve(self.repo_root)
        target = self._resolve(path if path.is_absolute() else self.repo_root / path)

        try:
            rel = target.relative_to(root)
        except ValueError:
            # Escapes the repo entirely (e.g. ``../../etc/passwd`` or /etc/passwd).
            return False

        return any(
            self._has_segment_prefix(rel.parts, allowed)
            for allowed in _ALLOWED_ROOT_SEGMENTS
        )

    @staticmethod
    def _has_segment_prefix(
        parts: tuple[str, ...], prefix: tuple[str, ...]
    ) -> bool:
        """Whether ``prefix`` is a full leading run of path segments of ``parts``.

        A pure segment comparison (never a string-prefix one): every segment of
        ``prefix`` must equal the corresponding segment of ``parts``, so ``parts``
        either equals the root or sits strictly under it. ``("src",)`` matches
        ``src`` and ``src/x``; ``(".claude", "dev-docs")`` matches that subtree but
        not ``.claude`` alone, ``.claude/agents``, or ``.claude/dev-docs-extra``.
        """
        if len(parts) < len(prefix):
            return False
        return parts[: len(prefix)] == prefix

    def sanitize(self, text: str) -> str:
        """Redact anything secret-shaped from tool ``text`` before it is returned.

        A defence-in-depth backstop on top of :meth:`allows_path`: even output from
        an allowed path (or a CLI) is scrubbed of env assignments and api-key-like
        tokens so a stray secret can never leave the machine. Ordinary code/text is
        returned unchanged.
        """
        out = text
        for pattern in _SECRET_PATTERNS:
            out = pattern.sub(_REDACTION, out)
        return out

    @staticmethod
    def _resolve(path: Path) -> Path:
        """Collapse ``..``/``.`` segments purely (no disk / symlink resolution)."""
        # ``os.path``-free, no I/O: rebuild the path from its parts.
        anchor = path.anchor
        parts: list[str] = []
        for part in path.parts:
            if part == anchor:
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            if part == ".":
                continue
            parts.append(part)
        return Path(anchor).joinpath(*parts)
