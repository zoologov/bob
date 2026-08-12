# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``read_code`` — the self-introspection capability over Bob's own source.

The thin skill that lets Bob look at his OWN code. A single ``query`` argument is
routed by shape: a repo-relative source PATH (e.g. ``src/bob/app.py``) is read via
:meth:`RepoIntrospector.read_file`; anything else is a FTS query delegated to
:meth:`RepoIntrospector.search_code`. Both seams are read-only and the privacy
invariant is enforced INSIDE the .1 port — this application policy only validates
input, routes, delegates, and gives an honest "ничего не нашёл" (US-5) on empty
output. It is ``permission="safe"`` and conversation-only (never on the autonomous
allowlist).

🔴 CORRECTED TO FACT (bob-a6b.17; the error is left VISIBLE rather than rewritten
after the fact — Issues #49). This docstring AND :data:`_DESCRIPTION` described the
invariant as "DENY ``data/soul`` / ``bob.db`` / ``.env`` / ``config``", i.e. the world
BEFORE BOB-067. That is worse than an ordinary stale docstring: ``_DESCRIPTION`` is
read by the MODEL, so Bob promised the owner a privacy the schema does not hold — and
could refuse to open a file that is in fact open to him. What the guard really decides
(:mod:`bob.capabilities.introspection.privacy_guard`, BOB-067 + bob-zmp + bob-a6b.13):

* ALLOW the WHOLE working tree, ``config/`` and ``data/`` included — Bob reads his repo
  like any engineer; only an ESCAPE past the repo root is refused;
* DENY key material wherever it sits — ``.secrets/`` (and the other credential stores),
  any ``*.pem`` / ``*.key`` / ``*.p12`` / ``*.pfx``, any ``id_rsa`` / ``id_ed25519``;
* DENY git's own bookkeeping — the ``.git`` subtree and any ``gitconfig``, because a
  https remote URL is exactly where a token lands;
* SANITISE everything that IS returned: a PEM private-key block (including one cut off
  by ``max_lines``), ``ghs_`` / ``ghp_`` / ``github_pat_`` tokens, a three-segment JWT,
  the password in any URL's userinfo, ``KEY=value`` assignments.

So ``.env`` now READS — its secrets just do not travel. The two rules are independent
layers, and neither is this module's to enforce.

Construct it with :func:`make_read_code_capability`, passing the introspector
port (modelled on :mod:`bob.capabilities.usecases.recall_memory`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model so it knows the single ``query`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

# 🔴 The text the MODEL reads — so it must state the invariant that HOLDS, not the one
# that used to (bob-a6b.17; see the module docstring for what it said and why it was
# worse than a stale comment). Wrong here, and Bob refuses a file that is open to him
# or assures the owner of a privacy he does not have.
_DESCRIPTION = (
    "Read Bob's own source code and project plans: pass a repo-relative file path "
    "(e.g. 'src/bob/app.py', '.claude/dev-docs/ROADMAP.md', or "
    "'.claude/development/docs/features/<KEY>/PRD.md') to read that file, or a "
    "symbol/text query to search the repo. Read-only. Since BOB-067 the WHOLE repo "
    "is readable — source, tests, docs, config/ and data/ alike — so do not tell the "
    "owner a file is hidden from you without trying it. Refused outright: key "
    "material wherever it sits (.secrets/, *.pem, *.key, *.p12, *.pfx, id_rsa, "
    "id_ed25519) and git's own .git/ bookkeeping. Everything else comes back with "
    "secret-shaped VALUES replaced by [REDACTED] (private keys, GitHub tokens, JWTs, "
    "a password inside a URL, KEY=value assignments) — so a .env or a config file "
    "reads fine, but its secrets never travel."
)

# Default line cap for a file read — enough to ground an answer without flooding
# the model; the port also bounds and sanitises the returned text.
_DEFAULT_READ_MAX_LINES = 200

# Honest empty-result message (US-5): Bob never confabulates a non-existent symbol.
_NOT_FOUND = "Ничего не нашёл по этому запросу в коде."

# A query is treated as a file path when it carries a path separator AND a file
# extension (e.g. ``src/bob/app.py``); a bare word/symbol is a search query.
_PATH_SEPARATOR = "/"
_EXTENSION_DOT = "."


def _looks_like_path(query: str) -> bool:
    """Whether ``query`` is a repo-relative file path rather than a search term."""
    if _PATH_SEPARATOR not in query:
        return False
    last_segment = query.rsplit(_PATH_SEPARATOR, 1)[-1]
    return _EXTENSION_DOT in last_segment


class _ReadCodeCapability:
    """Capability routing a query to file-read or search on the port (read-only)."""

    def __init__(
        self, introspector: RepoIntrospector, *, read_max_lines: int = _DEFAULT_READ_MAX_LINES
    ) -> None:
        self._introspector = introspector
        self._read_max_lines = read_max_lines

    @property
    def name(self) -> str:
        return "read_code"

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _INPUT_SCHEMA

    @property
    def permission(self) -> Permission:
        return "safe"

    async def execute(self, args: Mapping[str, object]) -> object:
        """Read a file or search the repo for ``args['query']`` (honest not-found)."""
        query = args.get("query")
        if not isinstance(query, str):
            raise ValueError("read_code requires a string 'query' argument")
        if _looks_like_path(query.strip()):
            text = await self._introspector.read_file(
                query.strip(), max_lines=self._read_max_lines
            )
        else:
            text = await self._introspector.search_code(query)
        return {"matches": text if text.strip() else _NOT_FOUND}


def make_read_code_capability(
    introspector: RepoIntrospector, *, read_max_lines: int = _DEFAULT_READ_MAX_LINES
) -> Capability:
    """Build the ``read_code`` capability over the given port (line-cap configurable)."""
    return _ReadCodeCapability(introspector, read_max_lines=read_max_lines)
