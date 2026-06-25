# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""``read_code`` — the self-introspection capability over Bob's own source.

The thin skill that lets Bob look at his OWN code. A single ``query`` argument is
routed by shape: a repo-relative source PATH (e.g. ``src/bob/app.py``) is read via
:meth:`RepoIntrospector.read_file`; anything else is a FTS query delegated to
:meth:`RepoIntrospector.search_code`. Both seams are read-only and the privacy
invariant (DENY ``data/soul`` / ``bob.db`` / ``.env`` / ``config``) is enforced
INSIDE the .1 port — this application policy only validates input, routes,
delegates, and gives an honest "ничего не нашёл" (US-5) on empty output. It is
``permission="safe"`` and conversation-only (never on the autonomous allowlist).

Construct it with :func:`make_read_code_capability`, passing the introspector
port (modelled on :mod:`bob.application.capabilities.recall_memory`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model so it knows the single ``query`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

_DESCRIPTION = (
    "Read Bob's own source code and project plans: pass a repo-relative file path "
    "(e.g. 'src/bob/app.py', '.claude/dev-docs/ROADMAP.md', or "
    "'.claude/development/docs/features/<KEY>/PRD.md') to read that file, or a "
    "symbol/text query to search the repo. Read-only and privacy-guarded: Bob's "
    "source/tests/docs plus the roadmap, vision and feature specs are visible, but "
    "personal data and secrets (memory DB, soul, .env, config, settings) are not."
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
