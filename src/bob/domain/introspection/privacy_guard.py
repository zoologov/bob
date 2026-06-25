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

* **ALLOW ONLY** paths under the read-only roots ``src/``, ``tests/``, ``docs/``
  of the repo (and those roots themselves).
* **DENY** everything else, in particular the personal-data roots — ``data/soul/**``
  (SOUL.md + profiles), ``data/bob.db*`` (the memory DB + its WAL/SHM siblings),
  ``.env*`` (secrets), and ``config/**`` — plus any path that escapes the repo via
  ``..`` traversal or an absolute path outside the repo root.

Paths are resolved (``..`` collapsed) against the repo root and tested for
containment in an allowed root, so a path that climbs out of an allowed root into
a denied one is denied by construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The ONLY roots Bob may read from — repo-relative, read-only source/docs trees.
# Exposed (also under the private alias for in-module use) as the single source of
# truth so the infra adapter's symlink-containment re-check shares the same roots.
ALLOWED_ROOTS: tuple[str, ...] = ("src", "tests", "docs")
_ALLOWED_ROOTS: tuple[str, ...] = ALLOWED_ROOTS

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
        disk access) and accepted ONLY when it lands inside one of the allowed
        roots (``src``/``tests``/``docs``) or is one of those roots itself.
        Everything else — denied personal-data roots, repo-root files, traversal
        that escapes an allowed root, absolute paths outside the repo — is denied.
        """
        root = self._resolve(self.repo_root)
        target = self._resolve(path if path.is_absolute() else self.repo_root / path)

        try:
            rel = target.relative_to(root)
        except ValueError:
            # Escapes the repo entirely (e.g. ``../../etc/passwd`` or /etc/passwd).
            return False

        head = rel.parts[0] if rel.parts else ""
        return head in _ALLOWED_ROOTS

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
