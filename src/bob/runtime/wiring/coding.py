# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root coding wiring — the gated «Bob runs Claude Code» assistant + NL router.

Assembles the gated :class:`CodingAssistant` (only when ``coder.enabled``: shell-free infra
adapters over the durable session store, the owner gate + a BOB-bot owner-notifier, the
UNBYPASSABLE plan gate) and the natural-language :class:`CodingIntentRouter`. Off → both
``None`` (inert). Part of the ``bob.runtime`` composition root (BOB-062.7a).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.coding.adapters import (
    GhPullRequestOpener,
    GitWorktree,
    SubprocessClaudeRunner,
)
from bob.coding.adapters.indicator import StatusPanel, TypingKeepalive
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.coding.adapters.session_store import SqliteCodingSessionStore
from bob.coding.usecases.classify_coding_intent import ClassifyCodingIntent
from bob.coding.usecases.coding_assistant import CodingAssistant, LiveRunStreamer
from bob.coding.usecases.coding_context import make_coding_context
from bob.coding.usecases.coding_intent_router import CodingIntentRouter
from bob.runtime.config import (
    _CODING_TYPING_INTERVAL,
    _REPO_ROOT,
    _flag,
    _int,
    _section,
    _str,
)
from bob.runtime.wiring.capabilities import _build_introspector

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router import LLMRouter
    from bob.coding.adapters.indicator import EditableStatusBot, TypingActionBot
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.social.usecases import Authorizer


def _build_coding_router(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    coder: CodingAssistant | None,
) -> CodingIntentRouter | None:
    """Assemble the natural-language coding-intent router, or ``None`` when off (BOB-041 .2).

    Built ONLY when the gated coding assistant is wired (``coder.enabled``). It pairs the
    cheap Tier-0 :class:`ClassifyCodingIntent` (coding vs chat) with the same gated
    :class:`CodingAssistant` the ``/code`` command drives, so an owner message in Bob's
    topic can plan / approve / stop a session naturally. Off (coder disabled → ``coder``
    is ``None``) → ``None``, and HandleMessage's natural-language path stays inert.

    🔴 SAFETY (BOB-076): auto-starting a FRESH session from natural chat is gated behind
    ``coder.nl_autostart`` (default OFF). A cheap Tier-0 misclassification of a casual
    owner reply once launched a runaway coder from ordinary chat, so by default the
    router only drives approve/stop of an ALREADY-live session and a fresh session starts
    ONLY via an explicit ``/code`` command. Flip the flag on to opt back into NL start.
    """
    if coder is None:
        return None
    return CodingIntentRouter(
        coder=coder,
        classifier=ClassifyCodingIntent(router=router),
        nl_autostart=_flag(_section(config, "coder"), "nl_autostart"),
    )


def _build_coding_assistant(
    config: Mapping[str, object],
    *,
    repo: SqliteConnection,
    authorizer: Authorizer,
    notifier_bot: BotLike,
    chat_id: int,
    topic_id: int | None,
    owner_id: int,
    clock: Clock,
    recorder: SelfActionRecorder,
) -> CodingAssistant | None:
    """Assemble the gated coding assistant, or ``None`` when off (BOB-039 .3).

    Built ONLY when ``coder.enabled`` is on (conservative default off): «Bob runs Claude
    Code» is the most powerful capability, so it stays unwired unless the owner switches
    it on (unwired → ``/code`` answers "disabled"). It composes the shell-free infra
    adapters — :class:`SubprocessClaudeRunner` (a fixed ``--permission-mode`` allowlist),
    :class:`GitWorktree` (an isolated worktree of TRACKED files only — Bob's private data
    never reaches Claude Code) and :class:`GhPullRequestOpener` (``gh pr create`` only,
    NO merge / push-main) — over the durable :class:`SqliteCodingSessionStore`, with the
    shared :class:`Authorizer` as the owner gate and a BOB-bot owner-notifier (BOB-046 .1:
    Bob speaks, GUPPI executes). The UNBYPASSABLE plan gate lives in the use-case + domain
    machine; this only wires it. The assistant is deliberately NOT added to
    ``goals.safe_capabilities`` (never autonomous).

    The flag-gated ``recorder`` (BOB-079) is threaded in from the composition root so each
    lifecycle transition records a first-person ``self_action`` episode; when
    ``memory.autobiography`` is OFF it is the NoOp (zero writes, unchanged behaviour).
    """
    coder = _section(config, "coder")
    if not _flag(coder, "enabled"):
        return None
    timeout = float(_int(coder, "timeout", 600))
    return CodingAssistant(
        recorder=recorder,
        context=make_coding_context(
            _build_introspector(config), PrivacyGuard(repo_root=_REPO_ROOT)
        ),
        runner=SubprocessClaudeRunner(
            claude_bin=_str(coder, "claude_bin", "claude"), timeout=timeout
        ),
        worktree=GitWorktree(_str(coder, "worktree_root", ".worktrees")),
        store=SqliteCodingSessionStore(repo),
        pr_opener=GhPullRequestOpener(gh_bin=_str(coder, "gh_bin", "gh")),
        notifier=_CodingOwnerNotifier(
            bot=notifier_bot, chat_id=chat_id, topic_id=topic_id
        ),
        owner=authorizer,
        clock=clock,
        execute_mode=_str(coder, "permission_mode", "acceptEdits"),
        # Work indicator (BOB-046 .2): "Bob is typing…" through the silent claude waits
        # + one editable status panel, both into Bob's topic via Bob's bot. Both degrade
        # to a no-op if the bot cannot send the action / edit the message.
        typing_keepalive=TypingKeepalive(
            bot=cast("TypingActionBot", notifier_bot),
            chat_id=chat_id,
            thread_id=topic_id,
            interval=_CODING_TYPING_INTERVAL,
            sleep=asyncio.sleep,
        ),
        status_panel=StatusPanel(
            bot=cast("EditableStatusBot", notifier_bot),
            chat_id=chat_id,
            thread_id=topic_id,
        ),
        # Dev-channel live-stream (BOB-082.3): when ``coder.dev_dm`` is ON, the raw,
        # UNCAPPED execute stream renders into the owner's private DM (the group topic gets
        # only a one-line pointer, INV-5). OFF (default) → ``None`` and the run is narrated
        # to the group capped exactly as before (zero behaviour change).
        live_streamer=_build_dm_live_streamer(
            coder, bot=notifier_bot, owner_id=owner_id
        ),
    )


def _build_dm_live_streamer(
    coder: Mapping[str, object],
    *,
    bot: BotLike,
    owner_id: int,
) -> LiveRunStreamer | None:
    """Assemble the DM live-stream renderer, or ``None`` when the dev-channel is off (BOB-082.3).

    Built ONLY when ``coder.dev_dm`` is on (conservative default off). It targets the
    owner's private DM (``coder.dev_dm_chat_id``, default = ``owner_id``; a 1:1 chat, so
    ``message_thread_id`` is ``None``) through the same BOB-bot :class:`_CodingOwnerNotifier`
    used for the group — only the chat/thread differ — plus a rolling editable
    :class:`StatusPanel` for the live "terminal" feel. Off (the default) → ``None`` and the
    use-case narrates the run to the group capped, exactly as before.
    """
    if not _flag(coder, "dev_dm"):
        return None
    dm_chat_id = _int(coder, "dev_dm_chat_id", owner_id)
    return _DmLiveStreamer(
        notifier=_CodingOwnerNotifier(bot=bot, chat_id=dm_chat_id, topic_id=None),
        panel=StatusPanel(
            bot=cast("EditableStatusBot", bot), chat_id=dm_chat_id, thread_id=None
        ),
    )
