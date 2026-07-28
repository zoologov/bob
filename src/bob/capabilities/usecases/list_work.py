# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``list_work`` — the self-introspection capability over Bob's tracker.

The thin skill that lets Bob look at his OWN backlog: it delegates a ``query`` to
:meth:`RepoIntrospector.list_tasks` (``bd show <id>`` for a specific task, else
``bd ready`` for the ready queue, behind the .1 port) and renders it compactly. It
is read-only (``permission="safe"``) and conversation-only — never on the
autonomous safe-allowlist. This application policy only validates input,
delegates, and gives an honest "ничего не нашёл" (US-5) on empty output.

Construct it with :func:`make_list_work_capability`, passing the introspector port
(modelled on :mod:`bob.capabilities.usecases.recall_memory`).
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
    "List Bob's own work from his tracker: pass a task id to show that task, or an "
    "empty query for the ready queue. Use this to answer what Bob is working on or "
    "what is up next."
)

# Honest empty-result message (US-5): Bob never invents a task that is not there.
_NOT_FOUND = "Ничего не нашёл в трекере по этому запросу."


class _ListWorkCapability:
    """Capability delegating a tracker query to the RepoIntrospector port (read-only)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "list_work"

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
        """Return tracker state for ``args['query']`` (honest not-found if empty)."""
        query = args.get("query")
        if not isinstance(query, str):
            raise ValueError("list_work requires a string 'query' argument")
        tasks = await self._introspector.list_tasks(query)
        return {"tasks": tasks if tasks.strip() else _NOT_FOUND}


def make_list_work_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``list_work`` capability over the given port."""
    return _ListWorkCapability(introspector)
