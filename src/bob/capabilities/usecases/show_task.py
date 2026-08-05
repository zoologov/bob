# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``show_task`` — the dev-introspection capability for one task's details (BOB-081).

The thin skill that lets Bob look at the details of ONE of his OWN tracker tasks: it
delegates the required ``id`` to :meth:`RepoIntrospector.show_task` (``bd show
<id>``, the id validated to a strict bead-key + sanitised behind the .1 port,
retried as a title search when the key is an epic key that ``bd`` does not know as an
identifier — BOB-090.A) and gives an honest message on empty output. An id-shape
:class:`ValueError` from the
port (a flag / injection-shaped value the validator refuses) is turned into a short
honest message rather than crashing the turn — the model simply learns the id was
invalid.

It is ``permission="safe"`` and conversation-only, registered behind the
``introspection.dev_tools`` sub-flag. Construct it with
:func:`make_show_task_capability`, passing the introspector.
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
    "Верни РЕАЛЬНЫЕ детали одной задачи из трекера (beads) по её id "
    "(например, BOB-076 или bob-0gj). Ключ эпика (BOB-087) тоже подойдёт: если такого "
    "id нет, задача найдётся по заголовку, включая закрытые. НЕ выдумывай."  # noqa: RUF001
)

# Honest empty-result message (INV-5): Bob never invents a task that is not there.
_NOT_FOUND = "Не нашёл такой задачи в трекере."  # noqa: RUF001
# Honest message when the id was refused by the port's validator (INV-1 guard).
_BAD_ID = "Неверный id задачи."


class _ShowTaskCapability:
    """Capability showing one tracker task via the port (read-only ``bd show``)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "show_task"

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
        """Return the details of ``args['id']`` (honest message on bad id / empty)."""
        raw = args.get("id")
        if not isinstance(raw, str):
            raise ValueError("show_task requires a string 'id' argument")
        try:
            detail = await self._introspector.show_task(raw.strip())
        except ValueError:
            return {"task": _BAD_ID}
        return {"task": detail if detail.strip() else _NOT_FOUND}


def make_show_task_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``show_task`` capability over the given repo-introspector port."""
    return _ShowTaskCapability(introspector)
