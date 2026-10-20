# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root Telegram wiring — assemble the two-bot MultiBot gateway.

Registers Bob (his topic) + GUPPI (General) behind one
:class:`~bob.infrastructure.telegram.multibot.MultiBotGateway` whose single poll drives
both; each bot is injected (a fake in tests) or built from its env token. Part of the
``bob.runtime`` composition root (BOB-062.7a).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.infrastructure.telegram.aiogram_adapter import _build_real_bot
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)
from bob.runtime.config import (
    _DEFAULT_OUTAGE_THRESHOLD,
    _DEFAULT_POLL_TIMEOUT,
    _int,
    _section,
)
from bob.runtime.wiring.self_improvement import _self_improvement_max_magnitude

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.runtime import AsyncEventBus
    from bob.coding.usecases.coding_assistant import CodingAssistant
    from bob.infrastructure.telegram.gateway import BobMessageFilter, BotLike
    from bob.kernel.ports import Clock
    from bob.proactivity.adapters import (
        SqliteGoalStore,
        SqliteProactivityStore,
        SqliteSelfImprovementStore,
    )
    from bob.proactivity.usecases.plan_goal import PlanGoal
    from bob.social.usecases import Authorizer


def _build_multibot(
    config: Mapping[str, object],
    *,
    bus: AsyncEventBus,
    bob_bot: BotLike | None,
    guppi_bot: BotLike | None,
    authorizer: Authorizer,
    proactivity_store: SqliteProactivityStore,
    proactivity_clock: Clock,
    goal_store: SqliteGoalStore | None = None,
    plan_goal: PlanGoal | None = None,
    pursuit_store: SqliteProactivityStore | None = None,
    rule_store: SqliteSelfImprovementStore | None = None,
    coding_assistant: CodingAssistant | None = None,
    bob_reaction_filter: BobMessageFilter | None = None,
) -> MultiBotGateway:
    """Build the two-bot gateway: Bob (his topic) + GUPPI (General), one poller.

    Each bot is injected (a fake in tests) or built from its env token
    (``telegram.bob.token`` / ``telegram.guppi.token``). Bob is scoped to the
    group's Bob topic so his replies pin to that thread; GUPPI owns the General /
    un-threaded scope. The shared :class:`Authorizer` drives GUPPI's reject + the
    owner commands — no duplicated authz.
    """
    telegram = _section(config, "telegram")
    chat_id = _int(telegram, "chat_id", 0)
    owner_id = _int(telegram, "owner_id", 0)
    # The owner's 1:1 DM chat id (BOB-083.1). Defaults to ``owner_id`` (a 1:1 chat's
    # id equals the user's id), matching the Authorizer's owner-DM authz (BOB-082).
    # ``... or None`` disables DM routing when neither is configured (owner_id == 0),
    # so behaviour is unchanged until an owner is set — group path untouched.
    owner_dm_chat_id = _int(telegram, "owner_dm_chat_id", owner_id) or None
    bob_section = _section(telegram, "bob")
    registry = BotRegistry()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bob_bot if bob_bot is not None else _build_real_bot(bob_section, "bob"),
        scope=BotScope(chat_id=chat_id, topic_id=_int(bob_section, "topic_id", 0)),
    )
    registry.register(
        identity=BotIdentity.GUPPI,
        bot=(
            guppi_bot
            if guppi_bot is not None
            else _build_real_bot(_section(telegram, "guppi"), "guppi")
        ),
        scope=BotScope(chat_id=chat_id, topic_id=None),
    )
    return MultiBotGateway(
        registry=registry,
        bus=bus,
        poll_timeout=_int(telegram, "poll_timeout", _DEFAULT_POLL_TIMEOUT),
        # BOB-094: how many CONSECUTIVE poll failures we diagnose as «оглох» (a
        # WARNING in the log / a ./bob-status signal, NOT a Telegram alert). > 1 by
        # design so a routine long-poll blip never raises the alarm.
        outage_threshold=_int(
            telegram, "outage_threshold", _DEFAULT_OUTAGE_THRESHOLD
        ),
        authorizer=authorizer,
        owner_dm_chat_id=owner_dm_chat_id,
        proactivity_store=proactivity_store,
        proactivity_clock=proactivity_clock,
        goal_store=goal_store,
        plan_goal=plan_goal,
        pursuit_store=pursuit_store,
        rule_store=rule_store,
        # Тот же потолок величины, по которому Боб решает, о каком предложении говорить
        # (BOB-096): список ``/rules`` объясняет владельцу его молчание, поэтому судить
        # они обязаны по ОДНОМУ числу — иначе список и поведение расходятся.
        rule_max_magnitude=_self_improvement_max_magnitude(config),
        coding_assistant=coding_assistant,
        bob_reaction_filter=bob_reaction_filter,
    )
