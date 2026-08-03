# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root register-recall wiring — behind ``memory.register_recall``.

The single place the bare ``memory.register_recall`` flag is read (mirroring
``memory.work_journal``). OFF (the default) → ``None``: :class:`HandleMessage` keeps the
byte-identical recall — over-fetch off, no register filter (INV-5). ON → a real
:class:`~bob.memory.usecases.resolve_register.RegisterResolver` over the cheap Tier-0
:class:`~bob.memory.usecases.classify_work_talk.ClassifyWorkTalk` judge plus the
deterministic dev-DM signal, so a CASUAL turn mutes distilled ``work`` recollections while a
DEV turn (in the operator DM, or judged about dev work) surfaces them at full weight.

🔴 Dev signal honesty: the deterministic ``dev_dm_chat_id`` is threaded ONLY when a dev-DM
channel is genuinely active (``coder.dev_dm`` OR ``coder.interactive`` — both target the
owner's 1:1 DM). With neither on there is no clean transport signal, so the resolver leans on
the Tier-0 classifier alone (``dev_dm_chat_id=None``) rather than inventing a new field.

🔴 Flag stays OFF until the owner activates read+write together (with ``memory.work_journal``);
there is no "writing-but-not-filtering" window that would leak work episodes into casual.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.memory.usecases.classify_work_talk import ClassifyWorkTalk
from bob.memory.usecases.resolve_register import RegisterResolver
from bob.runtime.config import _flag, _int, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router.llm_router import LLMRouter

__all__ = ["build_register_resolver"]


def build_register_resolver(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    owner_id: int,
) -> RegisterResolver | None:
    """Build the per-turn register resolver, or ``None`` when register-recall is off.

    OFF (default) → ``None`` → :class:`HandleMessage` keeps byte-identical recall (INV-5).
    ON → a :class:`RegisterResolver` over the Tier-0 :class:`ClassifyWorkTalk` classifier
    and the deterministic dev-DM signal (present only when a dev-DM channel is active).
    """
    if not _flag(_section(config, "memory"), "register_recall"):
        return None
    return RegisterResolver(
        classify_work_talk=ClassifyWorkTalk(router=router),
        dev_dm_chat_id=_resolve_dev_dm_chat_id(config, owner_id=owner_id),
    )


def _resolve_dev_dm_chat_id(
    config: Mapping[str, object], *, owner_id: int
) -> int | None:
    """The deterministic dev-DM chat id, or ``None`` when no dev-DM channel is active.

    A dev-DM channel exists only when ``coder.dev_dm`` or ``coder.interactive`` is on (both
    target the owner's 1:1 DM at ``coder.dev_dm_chat_id``, default = ``owner_id``). With
    neither on the signal is absent and the resolver relies on the Tier-0 classifier alone.
    """
    coder = _section(config, "coder")
    if not (_flag(coder, "dev_dm") or _flag(coder, "interactive")):
        return None
    return _int(coder, "dev_dm_chat_id", owner_id)
