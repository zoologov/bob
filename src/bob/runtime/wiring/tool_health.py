# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Startup check: which capabilities are mute because their binary is absent here.

Issues #62 / BOB-111. Several of Bob's capabilities are only as alive as a binary on
the host, and until now nothing noticed when one went missing — so he discovered he was
mute at the moment he was ASKED. Moving to the VPS silenced introspection (no
``beadloom``) and the renderer (``mmdc_bin`` still pointing at the owner's MacBook) at
once, and both stayed silent for a day until the owner asked for a diagram in the group.

The verdict logic is the pure core in :mod:`bob.capabilities.tool_availability`; the
filesystem contact is :func:`bob.capabilities.adapters.tool_resolver.resolve_tool`.
This module only collects the requirements from the SAME config the wiring reads, so
the check and the real call can never disagree about which binary is meant.

🔴 Deliberately reports, never refuses. A missing ``mmdc`` must not stop Bob from
living — he simply cannot draw. Refusing to start would be worse than the illness it
guards against.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.capabilities.adapters.tool_resolver import resolve_tool
from bob.capabilities.tool_availability import (
    ToolRequirement,
    assess_tools,
    describe_unavailable,
)
from bob.runtime.config import _flag, _section, _str

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.capabilities.tool_availability import ToolVerdict

logger = logging.getLogger(__name__)


def collect_requirements(config: Mapping[str, object]) -> tuple[ToolRequirement, ...]:
    """The external binaries this configuration actually depends on.

    🔴 Only ENABLED capabilities are listed. Reporting a missing ``claude`` while the
    coder is switched off would be noise — and a report people learn to ignore is
    worth less than no report at all.
    """
    introspection = _section(config, "introspection")
    capabilities = _section(config, "capabilities")
    intro_flags = _section(capabilities, "introspection")
    coder = _section(config, "coder")

    requirements: list[ToolRequirement] = []

    if _flag(intro_flags, "architecture_tools"):
        requirements.append(
            ToolRequirement(
                capability="схема архитектуры и состояние проекта",
                tool="beadloom",
                configured=_str(introspection, "beadloom_bin", "beadloom"),
            )
        )
    if _flag(intro_flags, "dev_tools"):
        requirements.append(
            ToolRequirement(
                capability="разговор про задачи трекера",
                tool="bd",
                configured=_str(introspection, "bd_bin", "bd"),
            )
        )
        requirements.append(
            ToolRequirement(
                capability="история репозитория в разговоре",
                tool="git",
                configured=_str(introspection, "git_bin", "git"),
            )
        )
    requirements.append(
        ToolRequirement(
            capability="картинка из mermaid",
            tool="mmdc",
            configured=_str(_section(config, "diagrams"), "mmdc_bin", "mmdc"),
        )
    )
    if _flag(coder, "enabled"):
        requirements.append(
            ToolRequirement(
                capability="Боб-кодер",
                tool="claude",
                configured=_str(coder, "claude_bin", "claude"),
            )
        )
    return tuple(requirements)


def report_tool_health(config: Mapping[str, object]) -> Sequence[ToolVerdict]:
    """Assess the configured tools and make any muteness VISIBLE in the log.

    Returns the verdicts so a caller can do more with them; the logging here is the
    point, though. The wording is chosen so the line cannot be skim-read as "fine":
    a WARNING that names the capability, the tool and the reason, versus the previous
    behaviour — total silence until a human asked.
    """
    try:
        requirements = collect_requirements(config)
        verdicts = assess_tools(requirements, resolve=resolve_tool)
    except Exception:
        # 🔴 The contract above says «reports, never refuses» — so it must hold even
        # when THIS check is what breaks. A probe that can kill the boot is a worse
        # failure than the muteness it was written to reveal, and it would be the
        # cruellest possible version of it: Bob dead because we tried to ask whether
        # he could draw. Found by reviewing this bead against its own promise.
        logger.exception("проверка внешних инструментов сорвалась — старт продолжаю")
        return ()
    description = describe_unavailable(verdicts)
    if description:
        logger.warning(
            "НЕДОСТУПНЫ способности (нет внешнего инструмента):\n%s", description
        )
    else:
        logger.info(
            "внешние инструменты на месте: проверено %d", len(requirements)
        )
    return verdicts
