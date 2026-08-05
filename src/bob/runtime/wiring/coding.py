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
from bob.interactive.adapters.runner import InteractiveClaudeRunner
from bob.interactive.usecases.intake import InteractiveIntakeRouter
from bob.interactive.usecases.recover_sessions import RecoverInteractiveSessions
from bob.interactive.usecases.session import InteractiveSessionManager
from bob.runtime.config import (
    _CODING_TYPING_INTERVAL,
    _REPO_ROOT,
    _flag,
    _int,
    _section,
    _str,
    _str_list,
)
from bob.runtime.wiring.capabilities import _build_introspector

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router import LLMRouter
    from bob.coding.adapters.indicator import EditableStatusBot, TypingActionBot
    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
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
    stream_bot: BotLike,
    chat_id: int,
    topic_id: int | None,
    owner_id: int,
    clock: Clock,
    recorder: SelfActionRecorder,
    work_journal: WorkJournalRecorder,
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

    🔴 Firehose channel (BOB-087.A1): the mechanical per-event narration + the DM
    live-stream are GUPPI's work (the dry executor), so under ``coder.stream_via_guppi``
    (default OFF) they are routed AS GUPPI — the ``stream_notifier`` + the live-streamer are
    built over ``stream_bot`` (GUPPI's bot). Bob's OWN voice (the ``session_voice`` gate
    lines, the "продолжаю" cap notice, the typing/status indicators) stays on ``notifier_bot``
    (Bob's bot). OFF → the firehose falls back to Bob's bot exactly as before (byte-identical:
    ``stream_notifier`` is ``None`` and the live-streamer targets ``notifier_bot``).

    🔴 WHO says WHAT is not decided here (BOB-090.D). The wiring only answers «does GUPPI
    have a channel of his own this boot» (the flag); the canon line — mechanics is GUPPI's
    voice, everything live and addressed to people is Bob's, and a permission request is
    Bob's too — lives in the pure :mod:`bob.coding.speaker`, and the use-case routes every
    single message through it. Change the canon there, never at a send site or here.

    🔴 Owner-only sandbox relaxations (BOB-087.D2): ``coder.allow_bypass`` (default OFF)
    admits ``bypassPermissions`` into the runner's ``--permission-mode`` allowlist, and
    ``coder.extra_dirs`` (default empty) passes ``--add-dir`` paths OUTSIDE the worktree.
    Both are threaded into the runner here and are inert by default. 🔴 Said honestly
    (BOB-087.D5b): Bob's OWN code still has no push/merge path, but ``bypassPermissions``
    hands claude an unsupervised shell in a worktree that SHARES the main repo's ``.git``
    (refs, remotes, credentials), so with that flag on «main is reached only through a PR»
    rests on the owner's judgement rather than on structure. OFF (the default) keeps the
    per-action gate that actually makes it structural.

    🔴 Push guard (BOB-087.E, bob-5ao): under ``allow_bypass`` the runner's spawn carries a
    git config (``url.<stub>.pushInsteadOf``) that makes a network push from the worktree
    die on a non-existent remote helper — see :mod:`bob.coding.push_guard`, including the
    honest limits (it is an ACCIDENT guard, not a boundary: the process owns its own
    environment, and a local ``update-ref`` on the shared ``.git`` bypasses push entirely).
    Bob's own integration path is untouched — :class:`GitWorktree` / :class:`GhPullRequestOpener`
    run in BOB's process, not in the guarded spawn.
    """
    coder = _section(config, "coder")
    if not _flag(coder, "enabled"):
        return None
    timeout = float(_int(coder, "timeout", 600))
    # Firehose bot selection (BOB-087.A1): GUPPI's bot when the flag is ON, else Bob's bot
    # (so the OFF path is byte-identical — the same single channel as today).
    stream_via_guppi = _flag(coder, "stream_via_guppi")
    firehose_bot = stream_bot if stream_via_guppi else notifier_bot
    return CodingAssistant(
        recorder=recorder,
        # Distilled work memory (BOB-087.B1): flag-gated (``memory.work_journal``, OFF → NoOp)
        # recorder that distills the run's key facts into first-person operator episodes at
        # session end. Threaded from the composition root, like ``recorder``.
        work_journal=work_journal,
        context=make_coding_context(
            _build_introspector(config), PrivacyGuard(repo_root=_REPO_ROOT)
        ),
        runner=SubprocessClaudeRunner(
            claude_bin=_str(coder, "claude_bin", "claude"),
            timeout=timeout,
            # 🔴 Owner-only sandbox relaxations (BOB-087.D2), both inert by default:
            # ``allow_bypass`` OFF keeps the allowlist at {plan, acceptEdits} and an empty
            # ``extra_dirs`` appends no ``--add-dir`` — the argv stays byte-identical.
            allow_bypass=_flag(coder, "allow_bypass"),
            extra_dirs=_str_list(coder, "extra_dirs"),
        ),
        worktree=GitWorktree(_str(coder, "worktree_root", ".worktrees")),
        store=SqliteCodingSessionStore(repo),
        pr_opener=GhPullRequestOpener(gh_bin=_str(coder, "gh_bin", "gh")),
        notifier=_CodingOwnerNotifier(
            bot=notifier_bot, chat_id=chat_id, topic_id=topic_id
        ),
        # The mechanical per-event narration firehose → GUPPI's bot when the flag is ON; OFF
        # → ``None`` so the use-case falls back to the Bob ``notifier`` (byte-identical).
        stream_notifier=(
            _CodingOwnerNotifier(bot=firehose_bot, chat_id=chat_id, topic_id=topic_id)
            if stream_via_guppi
            else None
        ),
        owner=authorizer,
        clock=clock,
        execute_mode=_str(coder, "permission_mode", "acceptEdits"),
        # Work indicator (BOB-046 .2): "Bob is typing…" through the silent claude waits
        # + one editable status panel, both into Bob's topic via Bob's bot. Both degrade
        # to a no-op if the bot cannot send the action / edit the message. These are Bob's
        # own presence markers → they stay on Bob's bot regardless of the firehose flag.
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
        # to the group capped exactly as before (zero behaviour change). The raw stream is
        # firehose → it follows ``firehose_bot`` (GUPPI when ``stream_via_guppi`` is ON).
        live_streamer=_build_dm_live_streamer(
            coder, bot=firehose_bot, owner_id=owner_id
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


def _build_interactive_session(
    config: Mapping[str, object],
    *,
    repo: SqliteConnection,
    authorizer: Authorizer,
    bot: BotLike,
    stream_bot: BotLike,
    owner_id: int,
    clock: Clock,
) -> InteractiveSessionManager | None:
    """Assemble the interactive-session manager, or ``None`` when off (BOB-083 .3).

    Built ONLY when ``coder.interactive`` is on (conservative default off): a live,
    bidirectional ``claude`` terminal in the owner's DM is the most powerful capability
    of the coding seam, so it stays unwired unless the owner switches it on (off → the
    manager is not built and the ``.4`` intake mode is inert). It injects a FRESH
    :class:`InteractiveClaudeRunner` per session (a factory), the SAME isolated
    :class:`GitWorktree` (edits go to a ``bob/<slug>`` branch — NEVER main, INV-2) and
    durable :class:`SqliteCodingSessionStore` the gated coder uses, the shared
    :class:`Authorizer` as the owner gate, and a per-session :class:`_DmLiveStreamer`
    (reuse of BOB-082) targeting the owner's private DM for the live output. 🔴 There is
    DELIBERATELY no PR-opener here — the manager physically cannot merge/push; the owner
    reviews the worktree branch and lands it through the existing BOB-039 gate.

    🔴 Firehose channel (BOB-087.A1): the interactive DM live-stream IS the mechanical
    firehose, so under ``coder.stream_via_guppi`` (default OFF) it is rendered AS GUPPI —
    the per-session streamer is built over ``stream_bot`` (GUPPI's bot). OFF → ``bot`` (Bob's
    bot) exactly as before (byte-identical). The short Bob mode lines (open/stop) live in the
    intake router (`_build_interactive_intake`) and stay on Bob's bot regardless. In the
    canon vocabulary (:mod:`bob.coding.speaker`, BOB-090.D) the split here is structural, so
    it needs no per-message verdict: the raw stream is ``TOOL_OUTPUT`` (GUPPI's), while every
    line the manager and the router speak is a ``MODE_NOTICE`` — Bob talking to a person.

    🔴 Owner-only sandbox relaxations (BOB-087.D2): ``coder.allow_bypass`` (default OFF)
    and ``coder.extra_dirs`` (default empty) are read once and baked into every
    per-session runner, so the owner can trade sandbox strictness for speed INSIDE the
    worktree. Inert by default → the spawn argv is byte-identical to BOB-083. 🔴 Honestly
    (BOB-087.D5b): the manager itself still has no PR-opener and cannot merge / push, and
    that part IS structural. But a worktree is a LINKED checkout sharing the main repo's
    ``.git`` — refs, remotes, credentials — so once ``allow_bypass`` gives claude an
    unsupervised shell in it, the trunk is protected by the owner's judgement about what
    he lets claude do, not by the absence of a code path in Bob. 🔴 BOB-087.E (bob-5ao)
    lowers that risk WITHOUT pretending to close it: every per-session runner built here
    inherits the same ``allow_bypass``, so its spawn carries the push guard
    (:mod:`bob.coding.push_guard`) — a network push from the live terminal dies on a
    non-existent remote helper. It is an accident guard, not a boundary (the process owns
    its environment; a local ``update-ref`` on the shared ``.git`` never touches push).

    🔴 Реплика о конце сеанса (bob-kv4): менеджер получает СВОЙ owner-нотификатор в личку
    (бот Боба) — единственный канал для того, что он говорит по собственной инициативе,
    когда ``claude`` кончился САМ. Все прочие реплики возвращаются ходу, который их
    попросил; у смерти процесса такого хода нет, и без этого сейма Боб просто немел.

    🔴 Долгоживущее рабочее место + resume (BOB-087.D3, D5b): под флагом ``coder.resume``
    (default OFF) в менеджер инъектируются два узких порта: ``lookup`` (поиск сессий по
    ветке, структурно тот же :class:`SqliteCodingSessionStore`) и ``workspace``
    (персистентный worktree, структурно тот же :class:`GitWorktree`). Они обслуживают ОБА
    конца цикла: ``open_workspace`` (завести накапливающее дерево) и ``resume`` (поднять в
    нём прошлую сессию). OFF → порты ``None``, путь не собран: ни ``/workspace``, ни
    ``/resume`` не распознаются интейком, персистентное дерево не создаётся, поведение
    байт-в-байт как в BOB-083.
    """
    coder = _section(config, "coder")
    if not _flag(coder, "interactive"):
        return None
    dm_chat_id = _int(coder, "dev_dm_chat_id", owner_id)
    claude_bin = _str(coder, "claude_bin", "claude")
    # 🔴 Owner-only sandbox relaxations (BOB-087.D2) — read ONCE here and baked into every
    # per-session runner. Both inert by default (allowlist {plan, acceptEdits}, no
    # ``--add-dir``), so an unconfigured interactive spawn is byte-identical to BOB-083.
    allow_bypass = _flag(coder, "allow_bypass")
    extra_dirs = _str_list(coder, "extra_dirs")
    firehose_bot = stream_bot if _flag(coder, "stream_via_guppi") else bot
    worktree = GitWorktree(_str(coder, "worktree_root", ".worktrees"))
    store = SqliteCodingSessionStore(repo)
    # 🔴 Resume seams (BOB-087.D3) — wired ONLY under ``coder.resume``. The same two
    # adapters, seen through their narrow read/ensure ports; OFF → ``None`` → the whole
    # resume path is structurally unavailable.
    resume_on = _flag(coder, "resume")
    return InteractiveSessionManager(
        runner_factory=lambda: InteractiveClaudeRunner(
            claude_bin=claude_bin,
            allow_bypass=allow_bypass,
            extra_dirs=extra_dirs,
        ),
        worktree=worktree,
        store=store,
        lookup=store if resume_on else None,
        workspace=worktree if resume_on else None,
        # verbose=True (BOB-085.2): the INTERACTIVE DM output renders the FULL curated rich
        # event (assistant text in full + markdown passthrough) and chunks an over-limit
        # piece into ≤ Telegram-limit messages, so claude's answer arrives whole + formatted.
        # The group one-way dev-channel path (`_build_dm_live_streamer`) stays concise.
        streamer_factory=lambda: _DmLiveStreamer(
            notifier=_CodingOwnerNotifier(
                bot=firehose_bot, chat_id=dm_chat_id, topic_id=None
            ),
            panel=StatusPanel(
                bot=cast("EditableStatusBot", firehose_bot),
                chat_id=dm_chat_id,
                thread_id=None,
            ),
            verbose=True,
        ),
        owner=authorizer,
        clock=clock,
        permission_mode=_str(coder, "permission_mode", "acceptEdits"),
        # 🔴 Реплика «сеанс кончился сам» (bob-kv4) — единственная, которую менеджер шлёт
        # по СОБСТВЕННОЙ инициативе: у смерти процесса нет хода-адресата, а раньше она не
        # доходила вообще (сеанс оставался «живым», Боб в личке нем до «стоп»). Это голос
        # САМОГО Боба, поэтому она идёт на ботe Боба в его личку — как короткие строки
        # режима интейка, а не за GUPPI (тот везёт только механический firehose).
        notifier=_CodingOwnerNotifier(bot=bot, chat_id=dm_chat_id, topic_id=None),
    )


def _build_interactive_recovery(
    *, repo: SqliteConnection, clock: Clock
) -> RecoverInteractiveSessions:
    """Assemble the boot-time sweep of orphaned live sessions (BOB-087.D5b).

    Built UNCONDITIONALLY — and that is deliberate, not an oversight of the flag rule. An
    ``INTERACTIVE`` row can only exist because a live terminal once ran, and the process
    that could have closed it is gone by the time this runs; leaving it non-terminal
    blocks the GATED coder («я уже в работе») even after the owner switches
    ``coder.interactive`` back off. With no such row the sweep writes nothing at all, so
    the flags-off path stays behaviourally identical.
    """
    return RecoverInteractiveSessions(store=SqliteCodingSessionStore(repo), clock=clock)


def _build_interactive_intake(
    config: Mapping[str, object],
    *,
    manager: InteractiveSessionManager | None,
    bot: BotLike,
    owner_id: int,
) -> InteractiveIntakeRouter | None:
    """Assemble the interactive-terminal intake router, or ``None`` when off (BOB-083 .4).

    Built ONLY when the interactive-session ``manager`` is wired (``coder.interactive``
    on); off → ``None`` and HandleMessage's interactive intake gate stays inert (the mode
    is entirely unavailable — no entry, the consume-gate never fires). It pairs the live
    :class:`InteractiveSessionManager` with a DM-targeted :class:`_CodingOwnerNotifier`
    (the owner's private 1:1 chat, ``message_thread_id`` ``None``) that carries the short
    explicit mode lines Bob sends on open/stop (INV-5). 🔴 owner-only + DM-only live inside
    the router (defense-in-depth over the manager's own owner gate); HandleMessage threads
    the perceived owner verdict + the channel signal in.

    🔴 Persistent workspace + resume (BOB-087.D3, D5b): the manager doubles as the router's
    ``resume`` seam ONLY under ``coder.resume`` (default OFF). OFF → the router holds no
    reference to it at all, so neither ``/workspace …`` nor ``/resume …`` is a command and
    the pending-answer path cannot fire — the turn goes down the ordinary chat path exactly
    as in BOB-083.
    """
    if manager is None:
        return None
    coder = _section(config, "coder")
    dm_chat_id = _int(coder, "dev_dm_chat_id", owner_id)
    return InteractiveIntakeRouter(
        manager=manager,
        notifier=_CodingOwnerNotifier(bot=bot, chat_id=dm_chat_id, topic_id=None),
        resume=manager if _flag(coder, "resume") else None,
    )
