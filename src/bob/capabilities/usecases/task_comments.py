# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``task_comments`` — the dev-introspection capability over a task's history (BOB-081).

The thin skill that lets Bob read the comments/checkpoints on ONE of his OWN tracker
tasks: it delegates the required ``id`` to :meth:`RepoIntrospector.task_comments`
(``bd comments <id>``, the id validated to a strict bead-key + sanitised behind the
.1 port) and gives an honest message on empty output. An id-shape :class:`ValueError`
from the port (a flag / injection-shaped value the validator refuses) is turned into
a short honest message rather than crashing the turn.

It is ``permission="safe"`` and conversation-only, registered behind the
``introspection.dev_tools`` sub-flag. Construct it with
:func:`make_task_comments_capability`, passing the introspector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model: a single required ``id`` (a bead key).
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"id": {"type": "string"}},
    "required": ["id"],
}

_DESCRIPTION = (
    "Верни РЕАЛЬНЫЕ комментарии и чекпоинты одной задачи из трекера (beads) по её id "
    "(например, BOB-076 или bob-0gj). НЕ выдумывай."  # noqa: RUF001
)

# Honest empty-result message (INV-5): Bob never invents comments that are not there.
_NOT_FOUND = "Не нашёл комментариев к этой задаче."  # noqa: RUF001
# Honest message when the id was refused by the port's validator (INV-1 guard).
_BAD_ID = "Неверный id задачи."


class _TaskCommentsCapability:
    """Capability reading one task's comments via the port (read-only ``bd comments``)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "task_comments"

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
        """Return the comments on ``args['id']`` (honest message on bad id / empty)."""
        raw = args.get("id")
        if not isinstance(raw, str):
            raise ValueError("task_comments requires a string 'id' argument")
        try:
            comments = await self._introspector.task_comments(raw.strip())
        except ValueError:
            return {"comments": _BAD_ID}
        return {"comments": comments if comments.strip() else _NOT_FOUND}


def make_task_comments_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``task_comments`` capability over the given repo-introspector port."""
    return _TaskCommentsCapability(introspector)
