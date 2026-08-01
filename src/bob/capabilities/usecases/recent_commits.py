# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``recent_commits`` — the dev-introspection capability over git history (BOB-081).

The thin skill that lets Bob look at his OWN recent commits: it resolves the
OPTIONAL ``count`` to a bounded integer with the pure
:func:`~bob.capabilities.introspection.dev_query.clamp_commit_count` (so history is
never unbounded and a missing count falls back to the domain default), delegates to
:meth:`RepoIntrospector.recent_commits` (the read-only ``git log --oneline -n N``
form, sanitised behind the .1 port), and gives an honest message on empty output.

The imperative description is deliberate: Bob must CALL the tool and report the REAL
commits (INV-5), never confabulate history. It is ``permission="safe"`` and
conversation-only, registered behind the ``introspection.dev_tools`` sub-flag.
Construct it with :func:`make_recent_commits_capability`, passing the introspector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.introspection.dev_query import clamp_commit_count

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model: a single OPTIONAL integer ``count``.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"count": {"type": "integer"}},
}

_DESCRIPTION = (
    "Верни РЕАЛЬНЫЕ последние N коммитов из git-истории репозитория Боба — что и "
    "когда менялось. НЕ выдумывай коммиты; если пусто — так и скажи."  # noqa: RUF001
)

# Honest empty-result message: Bob never confabulates a non-existent history.
_NOT_FOUND = "Не нашёл коммитов в истории."  # noqa: RUF001


class _RecentCommitsCapability:
    """Capability listing the last N repo commits via the port (read-only git log)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "recent_commits"

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
        """Return the last ``args['count']`` commits (bounded; honest if empty)."""
        raw = args.get("count")
        count = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        commits = await self._introspector.recent_commits(clamp_commit_count(count))
        return {"commits": commits if commits.strip() else _NOT_FOUND}


def make_recent_commits_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``recent_commits`` capability over the given repo-introspector port."""
    return _RecentCommitsCapability(introspector)
