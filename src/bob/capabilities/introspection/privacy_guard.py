# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""PrivacyGuard — the deterministic privacy invariant for self-introspection.

The single source of truth for "may Bob read this path / return this text" in
Phase A (BOB-017), widened to FULL-REPO access in BOB-067. It is a PURE domain
object: no I/O, no LLM, no prompt — so it **cannot be bypassed by anything the
model says**. The infrastructure adapter
(:class:`~bob.capabilities.adapters.introspection.subprocess_introspector.SubprocessRepoIntrospector`)
consults :meth:`PrivacyGuard.allows_path` BEFORE opening any file and runs every
tool's text output through :meth:`PrivacyGuard.sanitize`.

The invariant (BOB-067 — the owner's deliberate choice: Bob is an equal engineer
who works across the WHOLE repo, not a narrow whitelist):

* **ALLOW** any path that resolves UNDER the repo root — the full working tree,
  including ``.beadloom/``, ``config/``, ``data/``, the repo root itself, and
  every source/test/doc file. Bob navigates and reads his own repo like any
  developer would.
* **DENY** only an ESCAPE past the repo boundary: a path that climbs out via ``..``
  traversal or an absolute path pointing outside the repo root. The repo subtree is
  the containment boundary, not the whole filesystem.

Full-repo *read* access is not full *leak*: :meth:`sanitize` remains the
defence-in-depth backstop that redacts secret-shaped values (``sk-`` tokens,
``KEY=value`` env assignments, api-key literals) from any returned text, so a
literal secret string never leaves the machine (INV-N4). Paths are resolved
(``..`` collapsed, no disk access) against the repo root before the containment
check, so an escaping path is denied by construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The anchor root(s) the infra adapter re-checks symlink containment against. Under
# the BOB-067 full-repo invariant the single boundary is the repo root itself
# (``"."`` = repo root), so a symlink is allowed iff its REAL path still resolves
# under the repo — the filesystem-level twin of :meth:`PrivacyGuard.allows_path`.
# Exposed as the single source of truth so the adapter shares this boundary.
ALLOWED_ROOTS: tuple[str, ...] = (".",)

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


# --- pure module-level core ---------------------------------------------------
# The security-critical logic lives in module-level functions (not dataclass
# methods) SO IT IS MUTATION-TESTABLE: mutmut 3.x mutates module-level functions
# but not methods of a slots/frozen dataclass, so keeping the verdict here lets the
# mutation gate actually bite on the containment + redaction invariants (the same
# reason ``social.sulk`` exposes module-level policy functions). :class:`PrivacyGuard`
# delegates to these, so its public API is unchanged and behaviour is byte-identical.


def _resolve(path: Path) -> Path:
    """Collapse ``..`` segments purely (no disk / symlink resolution).

    ``.`` (current-dir) segments never reach here — ``Path`` normalises them away at
    construction, so ``path.parts`` only ever carries real names and ``..``. Only the
    upward-climb (``..``) needs collapsing, which pathlib does NOT do (it must not,
    across symlinks) — so this pops it purely, without touching disk.
    """
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
        parts.append(part)
    return Path(anchor).joinpath(*parts)


def _allows_path(repo_root: Path, path: Path) -> bool:
    """Whether ``path`` may be read under the full-repo containment invariant.

    ``path`` is resolved against ``repo_root`` (``..`` segments collapsed, no disk
    access) and accepted whenever it resolves UNDER (or equal to) the repo root —
    the whole working tree is readable (BOB-067). The ONLY denial is an escape past
    the repo boundary: a ``..`` traversal that climbs out, or an absolute path
    outside the repo, for which ``relative_to`` raises and the read is refused by
    construction.
    """
    root = _resolve(repo_root)
    target = _resolve(path if path.is_absolute() else repo_root / path)

    try:
        target.relative_to(root)
    except ValueError:
        # Escapes the repo entirely (e.g. ``../../etc/passwd`` or /etc/passwd).
        return False
    return True


def _sanitize(text: str) -> str:
    """Redact anything secret-shaped from tool ``text`` before it is returned.

    A defence-in-depth backstop on top of :func:`_allows_path`: even output from an
    allowed path (or a CLI) is scrubbed of env assignments and api-key-like tokens so
    a stray secret can never leave the machine. Ordinary code/text is returned
    unchanged.
    """
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(_REDACTION, out)
    return out


@dataclass(frozen=True, slots=True)
class PrivacyGuard:
    """Pure, frozen policy deciding readable paths and redacting secret output.

    Construct with the absolute ``repo_root``; both predicates are deterministic and
    side-effect free. The methods DELEGATE to the module-level :func:`_allows_path` /
    :func:`_sanitize` so the security core stays mutation-testable while the public
    ``PrivacyGuard`` API is unchanged.
    """

    repo_root: Path

    def allows_path(self, path: Path) -> bool:
        """Whether ``path`` may be read (delegates to :func:`_allows_path`)."""
        return _allows_path(self.repo_root, path)

    def sanitize(self, text: str) -> str:
        """Redact secret-shaped values from ``text`` (delegates to :func:`_sanitize`)."""
        return _sanitize(text)
