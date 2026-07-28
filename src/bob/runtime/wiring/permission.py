# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root permission wiring — the privilege-gating flow + its execution (BOB-052).

Assembles the :class:`PermissionFlow`: the safe-default-guarded Tier-0 judge, the durable
request store, the two-channel notifier, and the :class:`PermissionExecutor` over the
:class:`PrivilegedRequestFulfiller`. Part of the ``bob.runtime`` composition root
(BOB-062.7a).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.usecases.privileged_fulfiller import PrivilegedRequestFulfiller
from bob.social.adapters.permission_channels import (
    _PermissionNotifier,
    _PermissionRequesterChannel,
    _SafeDefaultPrivilegeJudge,
)
from bob.social.adapters.permission_request_store import SqlitePermissionRequestStore
from bob.social.adapters.privilege_judge import LlmPrivilegeJudge
from bob.social.usecases.permission_execution import PermissionExecutor
from bob.social.usecases.permission_flow import PermissionFlow

if TYPE_CHECKING:
    from bob.application.router import LLMRouter
    from bob.capabilities.ports import ToolCallingProvider
    from bob.capabilities.usecases import CapabilityRegistry
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.social.usecases import Authorizer


def _build_permission_flow(
    *,
    router: LLMRouter,
    repo: SqliteConnection,
    bot: BotLike,
    chat_id: int,
    topic_id: int | None,
    owner_id: int,
    clock: Clock,
    authorizer: Authorizer,
    registry: CapabilityRegistry,
    tool_provider: ToolCallingProvider | None,
) -> PermissionFlow:
    """Assemble the privilege-gating flow + its execution (BOB-052 .2/.3).

    Pairs the Tier-0 :class:`LlmPrivilegeJudge` (wrapped in a safe-default guard so a
    flaky judgment never breaks a live turn — it refuses, i.e. falls through to a normal
    reply) with the durable :class:`SqlitePermissionRequestStore` and the two-channel
    :class:`_PermissionNotifier` (owner notice into Bob's topic, requester ack into the
    chat).

    The EXECUTION (.3) is wired here: a :class:`PermissionExecutor` over the
    :class:`PrivilegedRequestFulfiller` (a one-shot elevated tool-loop / router run of the
    stored ``request_text``), the requester-channel (Bob's reply into the group chat) and
    the real :class:`Authorizer` (the durable grant on AUTHORIZE). 🔴 The elevation is
    per-request (the fulfiller is invoked once per approved request and holds no durable
    state); the durable grant happens ONLY on an explicit authorize; and the whole
    execution is decorative (safe-default refuse inside the executor). The flow itself
    enforces owner-only decision + the non-authorized-only request gate; HandleMessage
    only passes the perceived authz facts. ``owner_id`` is unused (the owner is decided by
    HandleMessage's perceived interlocutor) but kept for symmetry with the other builders.
    """
    del owner_id  # the owner is decided by HandleMessage's perceived interlocutor
    return PermissionFlow(
        judge=_SafeDefaultPrivilegeJudge(LlmPrivilegeJudge(router=router)),
        store=SqlitePermissionRequestStore(repo),
        notifier=_PermissionNotifier(bot=bot, chat_id=chat_id, topic_id=topic_id),
        clock=clock,
        executor=PermissionExecutor(
            fulfiller=PrivilegedRequestFulfiller(
                router=router, registry=registry, tool_provider=tool_provider
            ),
            channel=_PermissionRequesterChannel(bot=bot, chat_id=chat_id),
            authorizer=authorizer,
        ),
    )
