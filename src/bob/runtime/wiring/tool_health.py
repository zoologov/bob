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

The Tier-0 understudy (BOB-116) gets the same treatment from :func:`report_understudy`:
enabled in the config but with no model (or no Ollama) behind it, it would be discovered
at the worst moment — when the cloud has already failed. At startup it is one log line and
one message to the owner, and Bob starts anyway — WITHOUT the understudy (D11): it is stood
down for the life of the process, so the cloud's outage reads as what it is (nothing to
think with), not as «the understudy holds». Only a restart brings it back.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.application.router.health_messages import understudy_missing_text
from bob.capabilities.adapters.tool_resolver import resolve_tool
from bob.capabilities.tool_availability import (
    ToolRequirement,
    assess_tools,
    describe_unavailable,
)
from bob.infrastructure.llm.understudy_probe import probe_understudy
from bob.runtime.config import _flag, _section, _str
from bob.runtime.wiring.health import configured_understudy, health_owner_address

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from bob.capabilities.tool_availability import ToolVerdict
    from bob.infrastructure.llm.understudy_probe import UnderstudyCheck
    from bob.kernel.ports import OwnerAlertSink

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


async def report_understudy(
    config: Mapping[str, object],
    *,
    sink: OwnerAlertSink | None,
    stand_down: Callable[[str], None] | None = None,
) -> UnderstudyCheck | None:
    """Say at startup whether the Tier-0 understudy can actually stand in (BOB-116).

    One log line in every case — off / on and ready / on and NOT ready. Enabled but not
    ready first calls ``stand_down(reason)`` — the composition root takes the stand-in out of
    the router and tells the monitor there is none (D11), before any provider is called —
    and then tells the owner through ``sink`` (Bob's bot, his DM; a no-op when
    ``llm.health.owner_alert`` is off). Bob starts either way, without the understudy until
    the next restart: a model pulled later is not picked up.

    🔴 Reports, never refuses — like :func:`report_tool_health`: a failure of this check,
    of the stand-down or of the delivery is logged and the boot goes on (``None`` when the
    check itself broke; the understudy then stays as composed — nothing says it is dead).
    """
    try:
        check = await probe_understudy(configured_understudy(config))
    except Exception:
        logger.exception("проверка дублёра Tier-0 сорвалась — старт продолжаю")
        return None
    if not check.configured or check.ready:
        logger.info("%s", check.summary)
        return check
    reason = check.reason or "он не отвечает"
    if stand_down is not None:
        try:
            stand_down(reason)
        except Exception:
            logger.exception("снять дублёр Tier-0 не вышло — он остаётся в сборке")
    logger.warning("%s", check.summary)
    if sink is not None:
        text = understudy_missing_text(reason, health_owner_address(config))
        try:
            await sink.notify_owner(text)
        except Exception as error:  # доставка — не повод валить старт
            logger.warning(
                "сигнал владельцу о дублёре не ушёл (%s: %s)", type(error).__name__, error
            )
    return check
