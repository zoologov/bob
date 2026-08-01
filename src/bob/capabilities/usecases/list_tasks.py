# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``list_tasks`` — the dev-introspection capability over the tracker by status (BOB-081).

The thin skill that lets Bob list his OWN tracker tasks FILTERED BY STATUS: it
forwards the OPTIONAL ``status`` to :meth:`RepoIntrospector.tasks_by_status`
(``bd list [--status <enum>]``, normalised + sanitised behind the .1 port — an
unknown/absent status yields the unfiltered list, never a guessed filter) and gives
an honest message on empty output.

This is the by-status view; it is DISTINCT from ``list_work`` (a free-text query /
ready queue), so both coexist without conflict. It is ``permission="safe"`` and
conversation-only, registered behind the ``introspection.dev_tools`` sub-flag.
Construct it with :func:`make_list_tasks_capability`, passing the introspector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model: a single OPTIONAL ``status`` from the enum.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["open", "in_progress", "blocked", "deferred", "closed"],
        }
    },
}

_DESCRIPTION = (
    "Верни РЕАЛЬНЫЕ задачи из трекера (beads) по статусу "
    "(открытые/в работе/закрытые). НЕ выдумывай."  # noqa: RUF001
)

# Honest empty-result message (INV-5): Bob never invents a task that is not there.
_NOT_FOUND = "Ничего не нашёл в трекере по этому статусу."


class _ListTasksCapability:
    """Capability listing tracker tasks by status via the port (read-only ``bd list``)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "list_tasks"

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
        """List tasks for ``args['status']`` (unfiltered if absent; honest if empty)."""
        raw = args.get("status")
        status = raw if isinstance(raw, str) else None
        tasks = await self._introspector.tasks_by_status(status)
        return {"tasks": tasks if tasks.strip() else _NOT_FOUND}


def make_list_tasks_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``list_tasks`` capability over the given repo-introspector port."""
    return _ListTasksCapability(introspector)
