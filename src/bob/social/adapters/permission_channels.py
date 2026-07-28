# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""Permission-flow channel adapters — the transport edges of the privilege gate (BOB-052).

Realise the permission flow's outward seams over BOB'S bot: the two-channel
:class:`_PermissionNotifier` (owner «разрешить?» into Bob's topic, requester ack into the
chat), the :class:`_PermissionRequesterChannel` (Bob's fulfilment / decline into the
group chat), and the :class:`_SafeDefaultPrivilegeJudge` guard that swallows a flaky Tier-0
judgment into the safe non-privileged default so a live turn never breaks. Extracted
verbatim from the composition root (BOB-062.7a).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from bob.infrastructure.telegram.gateway import RichMarkdownSender
from bob.social.permission.privilege import PrivilegeNeed

if TYPE_CHECKING:
    from bob.infrastructure.telegram.gateway import BotLike, MarkdownSendBot
    from bob.social.adapters.privilege_judge import LlmPrivilegeJudge
    from bob.social.permission.privilege import PrivilegeContext

logger = logging.getLogger(__name__)


class _PermissionRequesterChannel:
    """Send Bob's fulfilment / decline to the requester through BOB'S bot (BOB-052 .3).

    Realises the executor's ``RequesterChannel`` (structurally). The approved fulfilment
    result — or the gentle decline on a denial — is sent into the GROUP CHAT (no topic
    thread, where the requester wrote) through the shared :class:`RichMarkdownSender`
    (rich, plain fallback). Transport only — the executor owns the wording.
    """

    def __init__(self, *, bot: BotLike, chat_id: int) -> None:
        self._sender = RichMarkdownSender(cast("MarkdownSendBot", bot))
        self._chat_id = chat_id

    async def send(self, text: str) -> None:
        """Post Bob's line to the requester in the group chat (rich markdown)."""
        await self._sender.send(chat_id=self._chat_id, markdown=text)


class _SafeDefaultPrivilegeJudge:
    """Guard the Tier-0 privilege judge so a flaky judgment never breaks a turn (BOB-052 .2).

    The raw :class:`LlmPrivilegeJudge` raises on a model/parse failure (by design, for .3's
    decorative fault-tolerance). Wiring it into the LIVE turn, this guard swallows that into
    the SAFE default — ``needs_permission=False`` — so the message simply falls through to a
    normal reply instead of breaking the turn. 🔴 The safe default is REFUSE-to-gate (no
    privileged action is ever taken from a failed judgment); .3 refines the decorative
    handling around execution.
    """

    def __init__(self, inner: LlmPrivilegeJudge) -> None:
        self._inner = inner

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:
        """Assess ``ctx``; on any judge/parse failure return the safe non-privileged default."""
        try:
            return await self._inner.assess(ctx)
        except Exception:
            logger.exception("privilege judgment failed (treated as non-privileged)")
            return PrivilegeNeed(needs_permission=False, kind="", what="")


class _PermissionNotifier:
    """Two-channel notice adapter for the permission flow through BOB'S bot (BOB-052 .2).

    Realises the flow's ``PermissionNotifier`` (structurally). ``notify_owner`` posts Bob's
    «Вова, <кто> просит <что> — разрешить?» into Bob's TOPIC (``message_thread_id ==
    telegram.bob.topic_id``) — where the owner converses with Bob and decides — through the
    shared :class:`RichMarkdownSender` (rich, plain fallback). ``tell_requester`` sends the
    light «спрошу Вову» acknowledgement into the same group chat (no topic thread) so the
    requester sees Bob took the ask to the owner. Transport only — the flow owns the wording.
    """

    def __init__(
        self, *, bot: BotLike, chat_id: int, topic_id: int | None
    ) -> None:
        self._sender = RichMarkdownSender(cast("MarkdownSendBot", bot))
        self._chat_id = chat_id
        self._topic_id = topic_id

    async def notify_owner(self, text: str) -> None:
        """Post the owner's «разрешить?» notice into Bob's topic (rich markdown, threaded)."""
        await self._sender.send(
            chat_id=self._chat_id, markdown=text, message_thread_id=self._topic_id
        )

    async def tell_requester(self, text: str) -> None:
        """Post the requester's light «спрошу Вову» ack into the group chat."""
        await self._sender.send(chat_id=self._chat_id, markdown=text)
