# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root access wiring — the Authorizer + the tool-calling provider seam.

Builds the access-policy :class:`Authorizer` over the persisted allowlist and picks the
reply-tier provider as the tool-calling provider when it supports the loop. Part of the
``bob.runtime`` composition root (BOB-062.7a).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.runtime.config import _REPLY_TIER, _int, _int_list, _section
from bob.social.adapters.allowlist_store import KvAllowlistStore
from bob.social.usecases import Authorizer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import ToolCallingProvider
    from bob.infrastructure.persistence import SqliteConnection
    from bob.kernel.ports import LLMProvider


def _build_authorizer(
    config: Mapping[str, object], *, repo: SqliteConnection
) -> Authorizer:
    """Build the access-policy Authorizer from config over the SQLite allowlist.

    ``owner_id`` and ``allowed_chat_ids`` come from the ``telegram`` config; the
    dynamic allowlist is persisted in the kv store so ``/authorize`` survives a
    restart. ``owner_dm_chat_id`` authorizes the owner's own private DM and
    defaults to ``owner_id`` (a 1:1 chat's id equals the user's id), so no config
    change is needed.
    """
    telegram = _section(config, "telegram")
    owner_id = _int(telegram, "owner_id", 0)
    return Authorizer(
        owner_id=owner_id,
        allowed_chat_ids=_int_list(telegram, "allowed_chat_ids"),
        store=KvAllowlistStore(repo),
        owner_dm_chat_id=_int(telegram, "owner_dm_chat_id", owner_id),
    )


def _as_tool_provider(
    providers: Mapping[int, LLMProvider],
) -> ToolCallingProvider | None:
    """Pick the reply-tier provider as the tool-calling provider, if it supports it.

    The Tier 1 reply provider (:class:`OpenAICompatProvider`) realises
    :class:`ToolCallingProvider`; a fake or a tool-less endpoint may not, in which
    case the tool-loop stays dormant and HandleMessage keeps the plain path.
    """
    provider = providers.get(_REPLY_TIER)
    if provider is not None and hasattr(provider, "complete_with_tools"):
        # The reply tier advertises complete_with_tools → it can drive the loop.
        return cast("ToolCallingProvider", provider)
    return None
