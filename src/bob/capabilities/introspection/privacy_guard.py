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
* **DENY** an ESCAPE past the repo boundary: a path that climbs out via ``..``
  traversal or an absolute path pointing outside the repo root. The repo subtree is
  the containment boundary, not the whole filesystem.
* **DENY** *private-key / credential-store SHAPES* wherever they sit in that subtree
  (bob-zmp) — see :func:`_is_secret_shaped`. This is the one HOLE the full-repo
  allowance had: a GitHub-App key living in ``.secrets/*.pem`` was returned verbatim
  and would have shipped to the external LLM. Key material is not "code Bob may read":
  there is no engineering question a private key answers.

Full-repo *read* access is not full *leak*: :meth:`sanitize` remains the
defence-in-depth backstop that redacts secret-shaped values (PEM private-key blocks,
GitHub tokens, JWTs, ``sk-`` tokens, ``KEY=value`` env assignments, api-key literals)
from any returned text, so a literal secret string never leaves the machine (INV-N4).
Paths are resolved (``..`` collapsed, no disk access) against the repo root before
both checks, so neither an escaping nor a laundered path slips through.

The two layers are deliberately INDEPENDENT: the path rule cannot see a key pasted
into ``notes.md``, and the text rule cannot stop a key from being *opened*. Either one
alone would have leaked the reproduced key, so both must hold.
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

# --- private-key / credential-store path shapes (bob-zmp) ---------------------
# Names that ARE a secret store, matched EXACTLY (case-insensitively) against any segment
# of the repo-relative path — so both the store itself (``list_dir('.secrets')``) and
# everything under it (whatever the suffix: a ``.txt`` note next to a key is still key
# inventory) are refused. Exact match keeps the denial pointed: ``.secretsfoo/`` or a
# module named ``secrets.py`` stays readable (BOB-067 must survive this fix).
_SECRET_STORE_NAMES: frozenset[str] = frozenset(
    {
        ".secrets",  # where this repo's GitHub-App keys were reproduced
        ".ssh",  # an ssh key dir planted in a tree (e.g. a spawn's isolated home)
        ".gnupg",
        ".netrc",  # plaintext machine/login/password
        ".git-credentials",  # git's plaintext credential store
    }
)

# Suffixes that carry key material by convention (PEM keys, PKCS#12 bundles). A suffix is
# enough on its own: there is no in-repo engineering reason to read a ``.pem``/``.key``.
_SECRET_FILE_SUFFIXES: tuple[str, ...] = (".pem", ".key", ".p12", ".pfx")

# Name PREFIXES of ssh keys, which carry NO suffix at all (``id_rsa``, ``id_ed25519``).
# The prefix also catches ``id_rsa.pub``: a public half is harmless, but denying it costs
# nothing and keeps the rule one phrase long.
_SECRET_NAME_PREFIXES: tuple[str, ...] = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")

# --- secret-shaped TEXT that must never leave the machine ---------------------
# A PEM PRIVATE-KEY block — marker AND body. 🔴 The closing ``-----END-----`` marker is
# OPTIONAL (``|\Z``) because the reproduced leak was a ``max_lines=5`` read: the block was
# cut mid-body, so a pattern requiring the terminator would have matched nothing and the
# key would still have travelled. Non-greedy, so two keys in one dump stay two matches.
# Only PRIVATE KEY blocks are collapsed; a ``CERTIFICATE`` block is public material.
_PEM_PRIVATE_KEY = re.compile(
    r"(?s)-----BEGIN[A-Z ]*PRIVATE KEY-----.*?(?:-----END[A-Z ]*PRIVATE KEY-----|\Z)"
)

# GitHub credentials BY SUBSTANCE (not by an accidental neighbouring word): the prefix is
# GitHub's own token scheme — ``ghs_`` installation, ``ghp_`` classic PAT, ``gho_``/``ghu_``
# /``ghr_`` oauth-family, ``github_pat_`` fine-grained. Real tokens are ~36+ chars; the
# ``{16,}`` floor keeps identifiers like ``ghost_writer`` / ``github_pattern`` untouched.
_GITHUB_TOKEN = re.compile(r"\b(?:gh[psuor]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})")

# A three-segment JWT (the App-JWT Bob signs to mint installation tokens). Anchored on
# ``eyJ`` — the base64url of ``{"``, so EVERY JWT header starts with it — because a bare
# ``a.b.c`` shape would swallow dotted module paths and version strings.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")

# Secret-shaped substitutions scrubbed from any tool output before it can be returned.
# Each entry is ``(pattern, replacement)``: patterns with a capture group keep the KEY
# readable (``FOO_TOKEN=[REDACTED]``) and redact only the value; value-shape patterns
# replace the whole match. BOB-067.6 hotfix — the previous patterns MISSED the real
# ``.env`` format the live smoke leaked (INV-N4 hole):
#
# 1. **Sensitive-key assignment.** A key whose name CONTAINS (case-insensitively, with
#    NO word boundary so ``__TOKEN`` / ``_API_KEY`` match) any of
#    token|key|secret|password|api|credential|auth, followed by ``:``/``=`` and an inline
#    value, has that value redacted — regardless of leading indentation (the old ``^``
#    anchor broke on indented ``read_file`` output). The value is required to be a
#    non-space token on the SAME line (``[ \t]*`` not ``\s*``) so ``for key in d:`` and
#    ``if token in seen_tokens:\n …`` are NOT touched.
# 2. **Generic uppercase env assignment** (prior behaviour, anchor loosened to tolerate
#    indentation) — an ``ALL_CAPS = value`` line has its value redacted.
# 3. **``sk-`` value shape WITH dots/underscores** — the Qwen-key format
#    ``sk-xx.yyyy.zzzz`` (the old ``[A-Za-z0-9_-]`` class stopped at the first ``.``).
# 4. **Telegram bot-token value shape** ``<digits>:<long-base64>`` — redacted by shape
#    even when it appears without a key label.
#
# Over-redaction is deliberately bounded to secret-NAMED assignments + secret value
# shapes; ordinary code that merely mentions key/token/secret is left untouched. A
# sensitive-named key that IS assigned an inline value is redacted even if the value
# looks ordinary — a SECURITY-FIRST tradeoff (under-redaction leaks a live credential
# to the external LLM; over-redacting a rare code line is cosmetic).
#
# bob-zmp prepends the KEY-MATERIAL rules and they run FIRST, deliberately: a whole PEM
# block collapses into ONE marker before the line-oriented rules can shred its body into
# a dozen half-redacted base64 lines.
_SECRET_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_PEM_PRIVATE_KEY, _REDACTION),
    (_GITHUB_TOKEN, _REDACTION),
    (_JWT, _REDACTION),
    (
        re.compile(
            r"(\S*(?i:token|key|secret|password|api|credential|auth)\S*"
            r"[ \t]*[:=][ \t]*)\S+"
        ),
        r"\1" + _REDACTION,
    ),
    (
        re.compile(r"(?m)^([ \t]*[A-Z][A-Z0-9_]*[ \t]*=[ \t]*)\S+"),
        r"\1" + _REDACTION,
    ),
    (re.compile(r"sk-[A-Za-z0-9_.-]{8,}"), _REDACTION),
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), _REDACTION),
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


def _is_secret_shaped(relative: Path) -> bool:
    """Whether ``relative`` names private-key / credential-store material (bob-zmp).

    Judged on the path RELATIVE to the repo root, segment by segment, so the verdict is
    about what Bob is reaching for and never about where the checkout happens to live (a
    repo cloned under ``~/.secrets/`` must not deny its own whole tree). A segment that IS
    a secret store (:data:`_SECRET_STORE_NAMES`) denies the store and everything beneath
    it; a key SUFFIX (:data:`_SECRET_FILE_SUFFIXES`) or an ssh-key NAME PREFIX
    (:data:`_SECRET_NAME_PREFIXES`) denies that file wherever in the tree it sits.

    Matching is case-insensitive (``server.KEY`` is the same file to the filesystem Bob
    reads on) and, for the store names, EXACT — the denial is a pointed hole in the
    full-repo allowance, not a retreat from BOB-067.
    """
    for part in relative.parts:
        name = part.lower()
        if name in _SECRET_STORE_NAMES:
            return True
        if name.endswith(_SECRET_FILE_SUFFIXES):
            return True
        if name.startswith(_SECRET_NAME_PREFIXES):
            return True
    return False


def _allows_path(repo_root: Path, path: Path) -> bool:
    """Whether ``path`` may be read under the full-repo containment invariant.

    ``path`` is resolved against ``repo_root`` (``..`` segments collapsed, no disk
    access) and accepted whenever it resolves UNDER (or equal to) the repo root —
    the whole working tree is readable (BOB-067) — UNLESS it names private-key or
    credential-store material (:func:`_is_secret_shaped`), which is refused wherever
    it sits in the tree. Two denials, then:

    * an escape past the repo boundary — a ``..`` traversal that climbs out, or an
      absolute path outside the repo, for which ``relative_to`` raises;
    * key material inside the repo — checked on the RESOLVED path, so a detour through
      ``src/../.secrets/…`` cannot launder it.
    """
    root = _resolve(repo_root)
    target = _resolve(path if path.is_absolute() else repo_root / path)

    try:
        relative = target.relative_to(root)
    except ValueError:
        # Escapes the repo entirely (e.g. ``../../etc/passwd`` or /etc/passwd).
        return False
    return not _is_secret_shaped(relative)


def _sanitize(text: str) -> str:
    """Redact anything secret-shaped from tool ``text`` before it is returned.

    A defence-in-depth backstop on top of :func:`_allows_path`: even output from an
    allowed path (or a CLI) is scrubbed of env assignments and api-key-like tokens so
    a stray secret can never leave the machine. Ordinary code/text is returned
    unchanged.
    """
    out = text
    for pattern, replacement in _SECRET_SUBSTITUTIONS:
        out = pattern.sub(replacement, out)
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
