# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``find_file`` — the repo-navigation capability that finds files (BOB-067).

The thin skill that lets Bob LOCATE a file in his own repo by name or glob. A single
``pattern`` argument (e.g. ``*.py`` or ``nodes.yml``) is routed to
:meth:`RepoIntrospector.find_file`, which walks the repo tree and returns the real
repo-relative paths that match (``.git/`` and outward symlinks skipped, capped with
an honest truncation note). It is read-only; the privacy invariant (full-repo
containment) is enforced INSIDE the .1 port, so this application policy only
validates input, delegates, and gives an honest "not found" on empty output. It is
``permission="safe"`` and conversation-only (never on the autonomous allowlist).

The imperative description is deliberate: Bob must CALL the tool and report the REAL
matches (INV-N1), not narrate an intention. Construct it with
:func:`make_find_file_capability`, passing the introspector port.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model so it knows the single ``pattern`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"pattern": {"type": "string"}},
    "required": ["pattern"],
}

_DESCRIPTION = (
    "Find files in Bob's repo by name or glob pattern and return their REAL "
    "repo-relative paths. Pass a filename or glob (e.g. 'nodes.yml', '*.py', "
    "'privacy_guard.py'). Use this whenever asked to find or locate a file — call it "
    "and report the actual matching paths, never guess where a file lives. Read-only; "
    "searches the whole tree (excluding .git), results are capped."
)

# Honest empty-result message: Bob never confabulates a non-existent path.
_NOT_FOUND = "Не нашёл файлов по этому шаблону в репозитории."


class _FindFileCapability:
    """Capability finding repo files by glob via the port (read-only, whole-tree)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "find_file"

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
        """Find files matching ``args['pattern']`` (honest not-found on empty)."""
        pattern = args.get("pattern")
        if not isinstance(pattern, str):
            raise ValueError("find_file requires a string 'pattern' argument")
        matches = await self._introspector.find_file(pattern.strip())
        return {"matches": matches if matches.strip() else _NOT_FOUND}


def make_find_file_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``find_file`` capability over the given repo-introspector port."""
    return _FindFileCapability(introspector)
