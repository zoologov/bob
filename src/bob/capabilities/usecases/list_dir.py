# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``list_dir`` — the repo-navigation capability that lists a directory (BOB-067).

The thin skill that lets Bob SEE what is really in a folder of his own repo. A
single ``path`` argument (repo-relative, e.g. ``.beadloom`` or ``src/bob``) is
routed to :meth:`RepoIntrospector.list_dir`, which returns the real, sorted entries
(name + kind + size) — never recursive. It is read-only; the privacy invariant
(full-repo containment: any in-repo path allowed, an escape past the repo refused)
is enforced INSIDE the .1 port, so this application policy only validates input,
delegates, and gives an honest empty/not-found message. It is ``permission="safe"``
and conversation-only (never on the autonomous allowlist).

The imperative description is deliberate: Bob must CALL the tool and report the REAL
listing (INV-N1), not narrate that "GUPPI went to look". Construct it with
:func:`make_list_dir_capability`, passing the introspector port.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model so it knows the single ``path`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
}

_DESCRIPTION = (
    "Return the REAL list of files and sub-folders in a directory of Bob's repo. "
    "Pass a repo-relative directory path (e.g. '.beadloom', 'src/bob', or '.' for "
    "the repo root). Use this whenever asked to show, list or look inside a folder — "
    "call it and report the actual entries, never guess or invent them. Read-only and "
    "non-recursive; each entry is shown as name, kind (file/dir) and size."
)

# Honest empty-result message: Bob never confabulates a non-existent listing.
_NOT_FOUND = "Не удалось перечислить эту директорию."


class _ListDirCapability:
    """Capability listing one repo directory via the port (read-only, non-recursive)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "list_dir"

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
        """List ``args['path']`` on the port (honest message on empty output)."""
        path = args.get("path")
        if not isinstance(path, str):
            raise ValueError("list_dir requires a string 'path' argument")
        listing = await self._introspector.list_dir(path.strip())
        return {"entries": listing if listing.strip() else _NOT_FOUND}


def make_list_dir_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``list_dir`` capability over the given repo-introspector port."""
    return _ListDirCapability(introspector)
