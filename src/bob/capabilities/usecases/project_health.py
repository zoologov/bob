# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``project_health`` — «как дела у проекта» (BOB-091.2).

The skill that answers a question about the STATE of Bob's own repository: index
statistics (``status``), the compact project context (``prime``), graph integrity
(``doctor``), doc↔code freshness (``sync-check``), architecture boundaries (``lint``) and
graph changes since a git ref (``diff``). It delegates one report to the read-only
:meth:`~bob.capabilities.ports.RepoIntrospector.project_health` and returns the
already-condensed answer.

**Why ONE tool with a closed enum and not six tools.** The manifest advertised to the
model is already large; six siblings differing by a single word would make the model's
choice WORSE, not better, and would spend six description slots on one idea. The
argument is therefore a value from a closed list — which is also the security shape: the
model never names a beadloom subcommand, so the write commands of the same CLI
(``reindex`` / ``docs generate`` / ``link`` / ``setup-*``) are not expressible even as a
typo. A value outside the list comes back as an error that NAMES the legal reports, so
the model can retry instead of guessing again.

Read-only (``permission="safe"``) and conversation-only — never on the autonomous
safe-allowlist. Registered behind the ``introspection.architecture_tools`` sub-flag,
together with the slice-1 architecture reads: one shippable piece, one gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.introspection.health_form import (
    HEALTH_CHECKS,
    InvalidGitRefError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model: the report is required and comes from the CLOSED
# list; ``since`` is the optional git ref of the ``diff`` report.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "check": {"type": "string", "enum": list(HEALTH_CHECKS)},
        "since": {"type": "string"},
    },
    "required": ["check"],
}

_DESCRIPTION = (
    "Look at the STATE of Bob's own project (read-only). Pass 'check' — one of: "
    "'status' (index numbers: nodes, edges, docs, coverage), 'prime' (compact project "
    "context: layers, domains, health), 'doctor' (architecture-graph integrity checks), "
    "'sync-check' (are the docs still in sync with the code?), 'lint' (are the "
    "architecture boundaries clean?), 'diff' (what changed in the graph since a git ref "
    "— pass that ref as 'since'). Use it for questions like «как дела у проекта?», «доки "
    "не отстали?», «границы не поехали?». A non-zero exit code of these commands is a "
    "RESULT, not a failure: report the verdict as it is."
)

# Fed back when the report came out empty: the command ran and said nothing, which is a
# tooling fact, not a fact about the project — Bob must not fill the gap himself.
_EMPTY = "Команда ничего не ответила — я не смог посмотреть, так и скажи."

# Fed back when the ``check`` slot was refused before any read. It NAMES the legal values,
# because a refusal that does not teach makes the model retry the same wrong word.
_BAD_CHECK = (
    "Так нельзя: 'check' — это один из отчётов " + ", ".join(HEALTH_CHECKS) + ". "
    "Ничего другого я запускать не умею (я только читаю). Спроси заново."
)

# Fed back when the ``diff`` ref was refused: a branch/tag/sha only.
_BAD_REF = (
    "Так нельзя: 'since' — это git-ref (ветка, тег или хеш коммита, например 'main' или "
    "'HEAD~1'), а не флаг, путь или диапазон. Спроси заново с настоящим ref."
)


def _as_ref(raw: object) -> str | None:
    """Read the ``since`` slot: a non-blank string, or ``None`` when it was not asked."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw


class _ProjectHealthCapability:
    """Capability delegating one health report to the RepoIntrospector port."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "project_health"

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
        """Return the condensed report for ``args['check']``, or an honest refusal."""
        check = args.get("check")
        if not isinstance(check, str) or not check.strip():
            return {"error": _BAD_CHECK}
        since = args.get("since")
        if since is not None and not isinstance(since, str):
            return {"error": _BAD_REF}
        try:
            health = await self._introspector.project_health(
                check, since=_as_ref(since)
            )
        except InvalidGitRefError:
            return {"error": _BAD_REF}
        except ValueError:
            # Everything else the planner refuses is a check it does not know — including
            # a write subcommand of the same CLI, which is the whole point of the closed
            # list. 🔴 Chosen BY TYPE: this branch used to sniff the exception's English
            # prose ('git ref' in str(exc)), so rewording a message would have shown the
            # model the wrong lesson (BOB-091.4, review Minor-7).
            return {"error": _BAD_CHECK}
        if not health.report.strip():
            return {"error": _EMPTY}
        return {"check": health.check, "report": health.report}


def make_project_health_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``project_health`` capability over the read-only introspector."""
    return _ProjectHealthCapability(introspector)
