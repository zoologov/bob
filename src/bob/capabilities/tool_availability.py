# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Which of Bob's capabilities are mute because their external tool is absent.

Several capabilities are only as alive as a binary on the host: introspection shells
``beadloom``/``bd``/``git``, the diagram renderer shells ``mmdc``, the coder shells
``claude``. Nothing used to notice when one of them went missing, so Bob discovered he
was mute at the moment he was asked — which is exactly how it happened (Issues #62):
moving to the VPS silenced introspection AND the renderer at once, and both stayed
silent until the owner asked for an architecture diagram in the group.

🔴 The verdict is about REACHABILITY, never about the shape of the configured string.
The setting that broke us read ``/Users/<owner>/.nvm/versions/node/v18.20.8/bin/mmdc``
— a valid absolute path, set deliberately, with a comment beside it explaining why.
Any check judging the FORM of that value would have passed it. Only "does this actually
run on THIS machine?" catches it, so resolution is injected and every verdict comes
from an attempt to resolve, not from parsing (CLAUDE.md §0.3 п.12).

Pure and deterministic on purpose: the filesystem contact lives in the resolver the
caller passes in, which keeps this a mutation-testable core (§0.2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: Resolves a configured tool value to a usable path, or ``None`` when it is not
#: reachable here. A bare name is looked up on ``PATH``; a path is checked for
#: existence AND executability. Injected, so this module stays pure — and so the
#: verdict can never be derived from the STRING instead of the host.
type ToolResolver = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    """One capability's dependency on an external binary.

    ``capability`` is named in Bob's terms («схема архитектуры»), not in code terms:
    the point of the report is that a human reads what STOPPED WORKING, not which
    class failed to import.
    """

    capability: str
    tool: str
    configured: str


@dataclass(frozen=True, slots=True)
class ToolVerdict:
    """Whether one requirement is satisfied here — and, when not, why."""

    requirement: ToolRequirement
    available: bool
    reason: str


def assess_tools(
    requirements: Iterable[ToolRequirement],
    *,
    resolve: ToolResolver,
) -> tuple[ToolVerdict, ...]:
    """Judge every requirement by trying to RESOLVE it, never by reading it.

    Returns one verdict per requirement, in the order given. An empty input yields an
    empty result rather than a cheerful "all good": «ничего не проверено» and «ничего
    не сломано» must stay distinguishable, or the check reports success for work it
    never did (§0.3 п.6).
    """
    verdicts: list[ToolVerdict] = []
    for requirement in requirements:
        resolved = resolve(requirement.configured)
        if resolved is None:
            verdicts.append(
                ToolVerdict(
                    requirement=requirement,
                    available=False,
                    reason=_reason(requirement),
                )
            )
        else:
            verdicts.append(
                ToolVerdict(requirement=requirement, available=True, reason="")
            )
    return tuple(verdicts)


def unavailable(verdicts: Sequence[ToolVerdict]) -> tuple[ToolVerdict, ...]:
    """Only the broken ones — what an operator (or Bob) actually needs to act on."""
    return tuple(verdict for verdict in verdicts if not verdict.available)


def describe_unavailable(verdicts: Sequence[ToolVerdict]) -> str:
    """One human line per mute capability; empty string when nothing is mute.

    Empty means «проверено, всё на месте» — which is only honest because
    :func:`assess_tools` refuses to invent verdicts it did not make.
    """
    broken = unavailable(verdicts)
    if not broken:
        return ""
    lines = [
        f"— {verdict.requirement.capability}: {verdict.reason}" for verdict in broken
    ]
    return "\n".join(lines)


def _reason(requirement: ToolRequirement) -> str:
    """Why this tool could not be reached, in words an operator can act on.

    Names BOTH the tool and the configured value: told only «mmdc missing», an operator
    checks ``PATH``, finds nothing wrong there, and concludes the report is noise — the
    configured value is the thing that was actually wrong (Issues #62).
    """
    if requirement.configured == requirement.tool:
        return f"нет инструмента {requirement.tool!r} (не найден в PATH)"
    return (
        f"нет инструмента {requirement.tool!r} по заданному пути "
        f"{requirement.configured!r} (не существует или не исполняем)"
    )
