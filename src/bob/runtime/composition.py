# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition root — wire every layer into the running GUPPI process.

This is the ONLY module allowed to depend on all layers at once. It loads the
layered config, builds the real infrastructure adapters (SQLite repo + FTS5
recall, OpenAI-compatible Tier 0/1 providers, the **two-bot** Telegram gateway,
the soul store), composes the application policy (the :class:`LLMRouter`, the
personality state, the message handler, and the heartbeat ticks), subscribes
:class:`HandleMessage` to the EventBus, registers the ticks + Telegram polling as
runtime background tasks, runs :class:`RunGenesis` once on first boot, and starts
the :class:`AgentRuntime`.

It is ``bob.runtime`` (the composition root / entrypoint), NOT
``bob.application.runtime`` (the async ``AgentRuntime`` / ``AsyncEventBus`` /
``periodic`` primitives it *starts*, which live on unchanged).

Two admin bots live in one process (BOB-003): Bob is scoped to his forum topic
and GUPPI is the gatekeeper/admin in General, both registered behind one
:class:`~bob.infrastructure.telegram.multibot.MultiBotGateway` whose single poll
drives both. Bob's pipeline (``HandleMessage``) streams replies through the
gateway's Bob reply-seam so they pin to his topic thread; GUPPI's reject + owner
commands run off the shared :class:`Authorizer`.

Secrets (``telegram.bob.token``, ``telegram.guppi.token``, ``llm.tier1_api_key``)
come from config/env only — never inlined here. The providers and both bots are
injectable seams so the whole graph can be exercised end-to-end on fakes (no
network).
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.router import LLMRouter
from bob.application.runtime import (
    BOB_MESSAGE_REACTION,
    MESSAGE_RECEIVED,
    AgentRuntime,
    AsyncEventBus,
    BobMessageReaction,
    MessageReceived,
)
from bob.application.runtime.intake import (
    ChatDispatcher,
    RoomStreamReader,
    make_focus_predicate,
)
from bob.application.usecases.handle_message import (
    EngagementState,
    HandleMessage,
    PersonalityState,
)
from bob.application.usecases.heartbeat import (
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
)
from bob.application.usecases.perceive_reaction import PerceiveReaction
from bob.capabilities.usecases.turn_material import MaterialTrailRecall
from bob.coding.speaker import MessageKind, channel_for
from bob.conversation.adapters.closer_log_store import SqliteCloserLog
from bob.conversation.adapters.conversation_floor_store import (
    SqliteConversationFloorStore,
)
from bob.conversation.adapters.interim_line import LlmInterimLineGenerator
from bob.conversation.adapters.response_judge import LlmResponseJudge
from bob.conversation.adapters.room_reader import LlmRoomReader
from bob.conversation.adapters.volatility_judge import LlmVolatilityJudge
from bob.conversation.usecases.decide_response import DecideResponse
from bob.conversation.usecases.read_the_room import ReadTheRoom
from bob.conversation.zone_classifier import TasteZoneClassifier
from bob.infrastructure.config import ConfigLoader
from bob.infrastructure.llm import (
    build_tier_providers,
    build_web_search_provider,
)
from bob.infrastructure.persistence import SqliteConnection
from bob.infrastructure.telegram.aiogram_adapter import (
    _BobReactionFilter,
    _build_real_bot,
)
from bob.infrastructure.telegram.multibot import BotIdentity
from bob.infrastructure.telegram.outage_notifier import _GuppiOutageNotifier
from bob.memory.adapters import HybridMemoryRecall, SqliteMemoryRepo
from bob.memory.usecases.extract_facts import ExtractFacts
from bob.personality.adapters.fascination_store import SqliteFascinationStore
from bob.personality.adapters.notable_reaction_store import KvNotableReactionStore
from bob.personality.adapters.reaction_judge import LlmReactionJudge
from bob.personality.language import DEFAULT_LANGUAGE
from bob.personality.negotiation import Negotiation
from bob.personality.usecases.apply_reflection import ApplyReflection
from bob.personality.usecases.evolve_fascination import EvolveFascination
from bob.personality.usecases.evolve_phantoms import EvolvePhantoms
from bob.personality.usecases.fascination_sources import (
    RepoFascinationGrounding,
    StoreFascinationReader,
)
from bob.personality.usecases.reappraise_reflection import ReappraiseReflection
from bob.personality.usecases.reflection_parser import HeuristicReflectionParser
from bob.personality.usecases.update_mood_from_text import UpdateMoodFromText
from bob.personality.voice import guppi_voice_canon
from bob.proactivity.adapters import (
    RepoProactivitySources,
    SqliteProactivityStore,
    SqliteSelfImprovementStore,
)
from bob.proactivity.usecases import (
    ProactiveTick,
    RecordOwnerActivity,
)
from bob.runtime.clock import SystemClock
from bob.runtime.config import (
    _BOB_PERSONA,
    EVOLUTION_ALPHA,
    EVOLUTION_BETA,
    _backfill_name_map,
    _db_path,
    _flag,
    _float_or,
    _int,
    _section,
    _soul_dir,
    _str,
    _templates_dir,
)
from bob.runtime.wiring import (
    _as_tool_provider,
    _background_tasks,
    _build_absence_hint_hours,
    _build_acknowledge_reaction_freq,
    _build_addressivity_thresholds,
    _build_authorizer,
    _build_brevity_thresholds,
    _build_coding_assistant,
    _build_coding_router,
    _build_consolidate_memory,
    _build_dedup_facts,
    _build_embedder,
    _build_engagement_mood_lift,
    _build_engagement_thresholds,
    _build_expression_freqs,
    _build_fatigue_rates,
    _build_floor_config,
    _build_floor_enabled,
    _build_goal_engine,
    _build_interactive_intake,
    _build_interactive_recovery,
    _build_interactive_session,
    _build_length_guard_enabled,
    _build_length_guard_max_chars,
    _build_multibot,
    _build_offday_thresholds,
    _build_origin_provenance,
    _build_permission_flow,
    _build_proactivity_engine,
    _build_pursue_goals_tick,
    _build_recent_turns,
    _build_registry,
    _build_repeat_thresholds,
    _build_reranker,
    _build_restart_announcer,
    _build_self_improvement,
    _build_self_improvement_enabled,
    _build_surface_old_freq,
    _diagram_send_as,
    _fascination_initial_intensity,
    _phantom_evolution_params,
    _resolve_seed,
    build_batch_room_reader,
    build_catch_up_reentry,
    build_disclosure_consent_gate,
    build_disclosure_guard,
    build_endorsement_seeder,
    build_register_resolver,
    build_rhythm_wiring,
    build_room_mood_modulator,
    build_roster_config,
    build_secondary_recall,
    build_self_action_recorder,
    build_send_to_chat,
    build_staleness_reassessor,
    build_work_journal_recorder,
    staleness_enabled,
)
from bob.runtime.wiring.tool_health import report_tool_health
from bob.social.adapters.first_impression_store import SqliteFirstImpressionStore
from bob.social.adapters.person_sulk_store import SqlitePersonSulkStore
from bob.social.adapters.relationship_store import SqliteRelationshipStore
from bob.social.adapters.soul_loader import (
    _default_soul,
    _disposition_from,
    _load_soul,
)
from bob.social.adapters.soul_store import SoulStore
from bob.social.usecases import ReactorPerception, SenderPerception
from bob.social.usecases.first_impression_sources import FirstImpressionTracker
from bob.social.usecases.relationship_sources import RelationshipTracker
from bob.social.usecases.roster_recall import RosterRecall
from bob.social.usecases.run_genesis import RunGenesis
from bob.social.usecases.sulk_sources import SulkRecoveryStep, SulkTracker

if TYPE_CHECKING:
    from pathlib import Path

    from bob.capabilities.usecases import CapabilityRegistry
    from bob.coding.usecases.coding_assistant import CodingAssistant
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.infrastructure.telegram.multibot import MultiBotGateway
    from bob.interactive.usecases.recover_sessions import (
        RecoverInteractiveSessions,
    )
    from bob.interactive.usecases.session import InteractiveSessionManager
    from bob.kernel.ports import Clock, DomainEvent, EventHandler, LLMProvider
    from bob.memory.ports import Embedder, Reranker
    from bob.proactivity.usecases import ProactivityEngine
    from bob.proactivity.usecases.announce_restart import AnnounceRestart
    from bob.proactivity.usecases.pursue_goals import PursueGoalsTick
    from bob.social.usecases import Authorizer
    from bob.social.usecases.run_genesis import GenesisResult


# Debounce window is configured in milliseconds (``dialogue.intake_debounce_ms``) but the
# inbox sleeps in seconds — the default 0 keeps single turns latency-free (a richer
# «пусть допишут» window is opt-in, and fully exploited by the Фаза-3 catch-up slices).
_MILLIS_PER_SECOND = 1000.0


@dataclass
class Application:
    """The assembled, runnable GUPPI process and its wired collaborators.

    Holds the composition result so the entrypoint (and tests) can run lifecycle
    (:meth:`startup` / :meth:`shutdown`) and inspect the bound adapters without
    re-running the wiring.
    """

    config: Mapping[str, object]
    runtime: AgentRuntime
    event_bus: AsyncEventBus
    connection: SqliteConnection
    memory_repo: SqliteMemoryRepo
    soul_store: SoulStore
    genesis: RunGenesis
    personality: PersonalityState
    handle_message: HandleMessage
    # Intake-развязка (BOB-066 Срез 2.1): the per-chat dispatcher behind the MESSAGE_RECEIVED
    # subscriber. ``shutdown`` drains it (awaits the in-flight workers) so a graceful stop
    # still delivers the buffered replies.
    intake_dispatcher: ChatDispatcher
    multibot: MultiBotGateway
    authorizer: Authorizer
    registry: CapabilityRegistry
    inner_monologue_tick: InnerMonologueTick
    mood_drift_tick: MoodDriftTick
    reflect_tick: ReflectTick
    proactivity_store: SqliteProactivityStore
    proactivity_engine: ProactivityEngine
    proactive_tick: ProactiveTick
    # Per-(persona, sender) обида store (BOB-066 2.5): exposed so ``startup`` can run the
    # one-time, idempotent backfill of the owner's legacy ``sulk_state`` row (byte-identical
    # upgrade) once the schema is applied.
    person_sulk_store: SqlitePersonSulkStore
    # Self-directed goal-pursuit tick (BOB-015 .3): wired only when
    # ``goals.pursuit_enabled`` is on (conservative default off → runtime as before).
    pursue_goals_tick: PursueGoalsTick | None = None
    # Gated coding assistant (BOB-039 .3): wired only when ``coder.enabled`` is on
    # (conservative default off → ``None``). Exposed so the entrypoint/tests can
    # inspect the bound owner-notifier without re-running the wiring.
    coding_assistant: CodingAssistant | None = None
    # Interactive-session manager (BOB-083 .3): a live, bidirectional ``claude`` terminal
    # in the owner's DM, wired only when ``coder.interactive`` is on (conservative default
    # off → ``None``). The ``.4`` intake mode drives it; off → inert (never built).
    interactive_session: InteractiveSessionManager | None = None
    # Boot-time sweep of orphaned live sessions (BOB-087.D5b): an ``INTERACTIVE`` row seen
    # at startup belongs to a process that no longer exists, so it is closed. ``None`` only
    # in hand-assembled test fixtures; ``startup`` then simply skips it.
    interactive_recovery: RecoverInteractiveSessions | None = None
    # Human restart announcement (BOB-094 срез 1): behind ``runtime.restart_notice``
    # (default off → ``None`` → the shutdown/startup hooks are no-ops, lifecycle
    # byte-identical). On → Bob announces «ухожу обновиться» before a graceful stop and
    # «вернулся, обновился» after a boot that followed an update-stop (marker in ``kv``).
    restart_announcer: AnnounceRestart | None = None

    async def startup(self) -> GenesisResult:
        """Initialise persistence, awaken Bob on first boot, load his soul.

        Idempotent Genesis: the first boot generates the soul (Tier 1) and writes
        ``data/soul/``; every later boot loads the existing soul untouched. The
        loaded soul becomes the live :class:`PersonalityState`.

        Boot-order (BOB-062.7b): the shared connection/schema kernel comes up FIRST
        (opening the WAL connection every store reads through), THEN the memory
        adapter runs its migrations + vector backfill over it.
        """
        # 🔴 BOB-111 / Issues #62: FIRST, say out loud which capabilities are mute here.
        # Several of them are only as alive as a binary on the host, and until this line
        # existed nothing noticed when one went missing — Bob learned he was mute at the
        # moment he was ASKED. Reports, never refuses: a missing renderer must not stop
        # him from living, it only stops him from drawing.
        report_tool_health(self.config)
        await self.connection.initialize()
        await self.memory_repo.initialize()
        # Per-person обида backfill (BOB-066 2.5): copy the owner's legacy per-persona
        # ``sulk_state`` row into ``person_sulk`` under his ``sender_id`` ONCE, so a
        # mid-обида owner keeps his exact state across the upgrade (byte-identical).
        # Idempotent + existence-guarded (never resurrects a stale обида); a no-op with
        # no owner id configured / no legacy row.
        await self.person_sulk_store.backfill_owner(
            _BOB_PERSONA, _int(_section(self.config, "telegram"), "owner_id", 0)
        )
        # Orphaned live coding sessions (BOB-087.D5b): a row left in ``INTERACTIVE`` by a
        # crash/redeploy is closed here — the process that held it is gone, and leaving it
        # non-terminal would block the gated coder forever and shadow the freshest resume
        # candidate. Best-effort inside; a no-op (zero writes) when there is no such row.
        if self.interactive_recovery is not None:
            await self.interactive_recovery.run()
        result = await self.genesis.run()
        # Human restart return (BOB-094 срез 1): if the previous exit was an
        # update-stop (a marker left in ``kv`` by the shutdown hook), Bob says «вернулся,
        # обновился» and consumes the marker; a self-crash (no marker) stays silent — he
        # never pretends a crash was an update. Best-effort + timed inside the use-case,
        # so a down network never blocks the boot. ``None`` (flag off) → no-op.
        if self.restart_announcer is not None:
            await self.restart_announcer.announce_returned()
        self.personality.soul = _load_soul(self.soul_store)
        # Resolve Bob's own bot identity (id + @username) so the addressivity scan
        # (BOB-023) can tell a mention of Bob from a mention of someone else.
        await self.multibot.resolve_bot_identities()
        return result

    async def shutdown(self) -> None:
        """Stop the runtime, drain the intake workers, then close persistence (idempotent).

        The intake dispatcher is drained BEFORE the connection closes: any message still
        buffered / in flight is handled to completion (its reply delivered) so a graceful
        stop never drops an in-progress turn or writes through a closed connection.

        🔴 Restart announcement (BOB-094 срез 1) goes out FIRST — before the runtime stops
        and the connection closes — so it uses a live bot and can still write the
        update-stop marker to ``kv``. It is timed + best-effort inside the use-case, so a
        down network never blocks the shutdown (``systemctl restart`` sends SIGTERM; the
        window is short). ``None`` (``runtime.restart_notice`` off) → no-op, lifecycle
        byte-identical.
        """
        if self.restart_announcer is not None:
            await self.restart_announcer.announce_leaving()
        await self.runtime.stop()
        await self.intake_dispatcher.aclose()
        await self.connection.close()


def build_application(
    *,
    config_path: Path | None = None,
    config: Mapping[str, object] | None = None,
    providers: Mapping[int, LLMProvider] | None = None,
    bob_bot: BotLike | None = None,
    guppi_bot: BotLike | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    clock: Clock | None = None,
    proactivity_seed: int | None = None,
) -> Application:
    """Wire the full two-bot GUPPI graph from configuration into an application.

    ``config`` / ``providers`` / ``bob_bot`` / ``guppi_bot`` / ``embedder`` /
    ``reranker`` are injectable seams: when omitted the real adapters are built
    from config (each bot's token from env via ``telegram.bob.token`` /
    ``telegram.guppi.token``); tests pass fake aiogram bots and a fake embedder to
    exercise the whole graph without a network or a Telegram account. Bob and GUPPI
    are registered behind one
    :class:`~bob.infrastructure.telegram.multibot.MultiBotGateway` — Bob scoped to
    his topic thread, GUPPI to General — and one Dispatcher polls both.

    **Hybrid memory (BOB-011):** a local :class:`~bob.memory.ports.Embedder`
    (BGE-M3/Ollama) and an optional :class:`~bob.memory.ports.Reranker` are built
    from config (``embeddings.*`` / ``reranker.*``). The live recall is the
    :class:`~bob.memory.adapters.HybridMemoryRecall` (FTS5 + sqlite-vec
    KNN fused by RRF, optionally reranked) — a drop-in for the keyword-only recall,
    so reactive recall and the ``recall_memory`` / ``search_memory`` capabilities
    all gain semantic retrieval. The embedder is wired into the repo so existing
    memory is backfilled and new facts/episodes are embedded on write. Graceful
    degradation is by construction: building the embedder NEVER touches the network,
    so a missing ``embeddings`` section just yields a keyword-only recall (the app
    still starts), and an embedder that fails at runtime (Ollama down) degrades the
    same way inside the hybrid recall — Bob never loses his memory.
    """
    merged = dict(config) if config is not None else ConfigLoader(yaml_path=config_path).load()

    # The clock is an injectable seam: production uses the real UTC SystemClock;
    # tests inject a fixed clock so the proactivity engine's circadian/governance
    # decision and the owner-cooldown are deterministic.
    resolved_clock: Clock = clock if clock is not None else SystemClock()
    del clock  # use resolved_clock everywhere below (narrowed, never None)
    event_bus = AsyncEventBus()
    tier_providers = providers if providers is not None else build_tier_providers(merged)
    # Tier-1 rate-cap (BOB-072): a ceiling on concurrent Tier-1 (Qwen API) calls, invisible
    # insurance against 429/degradation under bursts across chats. ``llm.tier1_max_concurrency``
    # absent / 0 → no cap → byte-identical; a positive value serializes Tier-1 to that ceiling.
    # 🔴 The VOICE canon is handed to the router HERE and only here (BOB-096.3). The router
    # is the one place every generation door passes through, and the canon TEXT belongs to
    # the persona (a `router -> personality` import would close a node cycle), so the tie
    # between them lives in the composition root. The line is not decorative: without it the
    # seam is unwired and the ban on role-playing GUPPI reaches the conversational turn
    # alone — defect bob-alr.12 exactly. An architectural test guards it.
    router = LLMRouter(
        providers=tier_providers,
        tier1_max_concurrency=_int(_section(merged, "llm"), "tier1_max_concurrency", 0),
        voice_canon=guppi_voice_canon,
    )

    # Hybrid memory (BOB-011): the embedder + optional reranker are injectable
    # seams; when omitted they are built from config. Building them never touches
    # the network (only `embed()`/`rerank()` calls do), so the app starts even with
    # Ollama down — the embedder is then `None` (keyword-only) and the hybrid recall
    # degrades gracefully at call time.
    resolved_embedder = embedder if embedder is not None else _build_embedder(merged)
    resolved_reranker = reranker if reranker is not None else _build_reranker(merged)

    # Shared connection/schema kernel (BOB-062.7b): the pure-I/O foundation created
    # FIRST — it opens the WAL connection, loads sqlite-vec and applies ``schema.sql``
    # — and injected into the memory adapter AND every module store below, so they all
    # read the SAME connection through its ``connection`` seam. Created here (not
    # opened yet); ``startup()`` initialises it before the memory adapter.
    connection = SqliteConnection(_db_path(merged))

    # The embedder is wired into the repo so the sqlite-vec table is backfilled with
    # existing memory on startup (initialize) and new facts/episodes are embedded on
    # write — a no-op when there is no embedder (keyword-only). ``name_to_sender_id``
    # seeds the BOB-045 best-effort backfill of legacy NULL-sender episodes (owner
    # display name -> owner_id); empty when no owner_name is configured (a no-op).
    memory_repo = SqliteMemoryRepo(
        connection,
        embedder=resolved_embedder,
        name_to_sender_id=_backfill_name_map(merged),
    )
    # 🔴 TURN-MATERIAL TRAIL (BOB-090.B-fix2): this is the ONLY place a memory-recall port
    # is ever built — and it is wrapped. Every door downstream draws from this object (the
    # turn's auto-recall, the ``secondary_recall`` decorator over it, the registry's memory
    # capabilities, the grounded-addon callback, the proactive seed), so each one lands in
    # the trail BY CONSTRUCTION, with no bookkeeping of its own, and the ``send_to_chat``
    # transfer gate reads that trail instead of one door out of four. A door added tomorrow
    # takes its port from here too; a port built OUTSIDE the root is caught by the
    # architecture guard in tests/capabilities/test_turn_material.py.
    recall = MaterialTrailRecall(
        HybridMemoryRecall(memory_repo, resolved_embedder, reranker=resolved_reranker)
    )

    # Autobiography recorder (BOB-079): behind ``memory.autobiography`` (OFF by default →
    # NoOp → zero writes, byte-identical behaviour). Constructed here over the shared
    # ``memory_repo`` as the SEAM consumers inject — coding-lifecycle (.2, wired below) and
    # the tool-loop (.3) record first-person ``self_action`` episodes through it.
    self_action_recorder = build_self_action_recorder(
        merged, store=memory_repo, clock=resolved_clock
    )

    # Distilled work memory (BOB-087.B1): behind ``memory.work_journal`` (OFF by default →
    # NoOp → zero writes, byte-identical). At a coding-session END it distills the run's key
    # facts into a few first-person operator episodes (``work`` events) via a Tier-0 call.
    # 🔴 Stays OFF until slice C's register-aware recall lands (no casual-pollution window).
    work_journal_recorder = build_work_journal_recorder(
        merged, router=router, store=memory_repo, clock=resolved_clock
    )

    # Register-aware recall (BOB-087.C): behind ``memory.register_recall`` (OFF by default →
    # None → recall byte-identical, over-fetch off, no register filter — INV-5). ON → a
    # RegisterResolver over the Tier-0 work-talk classifier + the deterministic dev-DM signal
    # (present only when a dev-DM channel is active), so casual turns mute distilled ``work``
    # recollections while a dev turn surfaces them. Activated read+write WITH work_journal.
    register_resolver = build_register_resolver(
        merged, router=router, owner_id=_int(_section(merged, "telegram"), "owner_id", 0)
    )
    # The SECONDARY recall doors (BOB-087.C8), behind the SAME flag: the grounded-addon
    # callback, the ``recall_memory`` / ``search_memory`` capabilities and the proactive seed
    # each hold their own recall port, so the per-turn register filter above never sees them.
    # ON → they draw through the CASUAL floor (work muted, never cut, zero Tier-0 — a
    # secondary surface carries no provenance directive, so it may not lift to DEV). OFF
    # (default) → the very same ``recall`` object: every door byte-identical (INV-5).
    secondary_recall = build_secondary_recall(merged, recall=recall)

    soul_store = SoulStore(_soul_dir(merged))

    # Capability seam (BEAD-05/06): advertise recall_memory + the agentic
    # search_memory to the model so the production tool-loop is active — the model
    # may call either, GUPPI executes it, the result loops back into the reply. The
    # tier-1 reply provider is the tool-calling provider; when it cannot do tools the
    # loop stays dormant and HandleMessage keeps the plain reply path.
    registry, diagram_sink, diagram_renderer = _build_registry(
        merged, recall=secondary_recall
    )
    tool_provider = _as_tool_provider(tier_providers)

    genesis = RunGenesis(
        templates_dir=_templates_dir(merged),
        router=router,
        soul_store=soul_store,
        clock=resolved_clock,
    )

    personality = PersonalityState(soul=_default_soul())
    # Social co-regulation (BOB-033 .3): Bob's disposition drives the asymmetric
    # contagion (a warm message lifts more than a cold one dips) and the proportional
    # pull-toward-baseline that displaces accumulated low. Loaded off the same soul
    # artifact as the reappraisal seam; canon-optimist fallback when absent.
    # Bob's disposition (canon-optimist fallback when absent) drives the social co-regulation
    # AND — behind ``presence.room_mood`` — the warm-room-lifts-more-than-cold engagement
    # asymmetry; loaded once here and shared by every seam that reuses it.
    disposition = _disposition_from(soul_store.read_json("disposition"))
    update_mood = UpdateMoodFromText(
        router=router,
        clock=resolved_clock,
        disposition=disposition,
    )
    extract_facts = ExtractFacts(router=router, repo=memory_repo, clock=resolved_clock)
    authorizer = _build_authorizer(merged, repo=connection)

    # Proactivity (BOB-010 Ф1): the per-persona store backs both the engine and
    # GUPPI's /quiet,/wake; RecordOwnerActivity folds each owner message into the
    # drive-state. The store/clock are handed to GUPPI through the gateway.
    proactivity_store = SqliteProactivityStore(connection)
    record_owner_activity = RecordOwnerActivity(
        store=proactivity_store, clock=resolved_clock, persona_id=_BOB_PERSONA
    )

    # Fascination (BOB-020 wave 2): the per-persona store backs both the evolution
    # step (on the reflect tick) and the compose-surfacing reader. The reader loads
    # + ages the stored passion and drops a faded one, so a spent fascination never
    # surfaces and the reply/proactive compose no-ops until evolution grounds a fresh one.
    fascination_store = SqliteFascinationStore(connection)
    fascination_reader = StoreFascinationReader(
        persona_id=_BOB_PERSONA, store=fascination_store, clock=resolved_clock
    )

    # First impression (BOB-019 bob-apv.3): a LIGHT per-sender store backs the tracker
    # that recalls a returning person's prior impression into the compose prompt and
    # records a fresh, grounded note on first contact. Keyed by sender_id (owner /
    # known / guest / bot alike); per-PERSON data (about them), not owner memory, so it
    # is safe even on a guest turn. The minimal foundation for multi-party BOB-014.
    first_impression_store = SqliteFirstImpressionStore(connection)
    first_impression_tracker = FirstImpressionTracker(
        store=first_impression_store, clock=resolved_clock
    )
    # Relationship-врезка (BOB-014): per-sender relationship quality (trust / respect
    # / warmth / compatibility) accrued over turns — it warms/cools Bob's tone and
    # nudges his willingness to compromise with a close person, then is updated after
    # each turn. Keyed by sender_id; per-PERSON data (about them), not owner memory.
    relationship_store = SqliteRelationshipStore(connection)
    relationship_tracker = RelationshipTracker(store=relationship_store)
    # Conversation-floor store (BOB-025): the per-thread "talking turn" — who currently
    # holds the floor in Bob's topic — so an ambient message in a thread where Bob holds
    # a live floor reads as DIRECTED_TO_BOB (continuity). Wired into HandleMessage only
    # when addressivity.floor.enabled is true; disabled → exactly BOB-023.
    floor_enabled = _build_floor_enabled(merged)
    floor_store = SqliteConversationFloorStore(connection) if floor_enabled else None
    # Sulk/обида store (BOB-066 2.5): the per-(persona, sender) affect state — entered on
    # a SUSTAINED critical warmth-drop / directed hostility toward ONE person, decaying to
    # a GUARANTEED exit. Carries NO memory and NO soul (anti-Exodus, a separate table). The
    # tracker is built AFTER multibot so GUPPI can be its one-shot announcer.
    person_sulk_store = SqlitePersonSulkStore(connection)

    # Goal Engine (BOB-015): the per-persona goal store backs the Planner-driven
    # plan_goal use-case (double approval) and GUPPI's owner goal-commands. The
    # kill-switch (`/goals stop`) persists on the proactivity store, which the
    # self-directed tick (.3) will read. No tick is wired here — that is .3's job.
    goal_store, plan_goal = _build_goal_engine(merged, router=router, repo=connection)

    # Self-improvement (BOB-028): the master switch (``self_improvement.enabled``, OFF by
    # default) gates the WHOLE feature. Off → ``rule_store`` is None, so GUPPI has no /rules
    # command and (below) HandleMessage applies no rule and the reflect tick runs no
    # detector/announcer — the runtime behaves EXACTLY as before BOB-028. The store is built
    # here (before multibot) because GUPPI needs it; the apply reader + reflect-tick seams,
    # which need Bob's gateway, are assembled just after multibot.
    si_enabled = _build_self_improvement_enabled(merged)
    rule_store = SqliteSelfImprovementStore(connection) if si_enabled else None

    # Resolve BOTH admin bots once so the multibot registry AND the coding-session
    # owner-notifier share the SAME instances. GUPPI is the silent under-the-hood
    # executor; BOB is the speaker — so the gated coding assistant talks (plan /
    # narration / PR) through BOB'S bot (BOB-046 .1): the owner converses with Bob, so
    # Bob is the one replying. The per-event narrative stays GUPPI-attributed in TEXT
    # («GUPPI: …», canon) — only the SENDER is Bob.
    telegram_section = _section(merged, "telegram")
    resolved_bob_bot = (
        bob_bot
        if bob_bot is not None
        else _build_real_bot(_section(telegram_section, "bob"), "bob")
    )
    resolved_guppi_bot = (
        guppi_bot
        if guppi_bot is not None
        else _build_real_bot(_section(telegram_section, "guppi"), "guppi")
    )

    # Gated coding sessions — «Bob runs Claude Code» (BOB-039 .3). Built ONLY when
    # ``coder.enabled`` is on (conservative default off): the assistant orchestrates the
    # UNBYPASSABLE plan gate, narrates each run to the owner through BOB'S bot and opens
    # a PR — NEVER merging / pushing main. It is NOT on the autonomous safe-allowlist.
    # Off → None, and ``/code`` answers a clear "disabled" reply (the section always exists).
    coding_assistant = _build_coding_assistant(
        merged,
        repo=connection,
        authorizer=authorizer,
        notifier_bot=resolved_bob_bot,
        # Firehose bot (BOB-087.A1): the mechanical coder stream is sent AS GUPPI under
        # ``coder.stream_via_guppi`` (default OFF → the wiring falls back to Bob's bot, so
        # today's behaviour is byte-identical). Bob's voice stays on ``resolved_bob_bot``.
        stream_bot=resolved_guppi_bot,
        chat_id=_int(telegram_section, "chat_id", 0),
        # The owner gives Bob the task in HIS topic (BOB-041 NL path), so coding-session
        # replies thread back into that same topic, not General (BOB-042 Fix B).
        topic_id=_int(_section(telegram_section, "bob"), "topic_id", 0),
        # Owner id → default target of the dev-channel live-stream (BOB-082.3) when
        # ``coder.dev_dm`` is on and no explicit ``coder.dev_dm_chat_id`` is set.
        owner_id=_int(telegram_section, "owner_id", 0),
        clock=resolved_clock,
        recorder=self_action_recorder,
        # Distilled work memory (BOB-087.B1): at session END the run's key facts are distilled
        # into first-person operator episodes. Behind ``memory.work_journal`` (OFF → NoOp).
        work_journal=work_journal_recorder,
    )

    # Interactive-session manager (BOB-083 .3): a live, bidirectional ``claude`` terminal
    # in the owner's DM. Built ONLY when ``coder.interactive`` is on (conservative default
    # off → ``None``, the ``.4`` intake mode inert). It reuses the isolated worktree + the
    # DM live-stream and physically cannot open a PR / push main (INV-2).
    interactive_session = _build_interactive_session(
        merged,
        repo=connection,
        authorizer=authorizer,
        bot=resolved_bob_bot,
        # The interactive DM firehose follows ``coder.stream_via_guppi`` too (BOB-087.A1):
        # GUPPI's bot when ON, Bob's bot (byte-identical) when OFF.
        stream_bot=resolved_guppi_bot,
        owner_id=_int(telegram_section, "owner_id", 0),
        clock=resolved_clock,
    )

    # Boot-time recovery of orphaned live sessions (BOB-087.D5b). Built unconditionally
    # (see the factory docstring): a row left in ``INTERACTIVE`` by a crash belongs to a
    # dead process, and while it lives the gated coder answers «я уже в работе» to every
    # new task. With no such row it writes nothing, so a flags-off boot is unchanged.
    interactive_recovery = _build_interactive_recovery(
        repo=connection, clock=resolved_clock
    )

    # Interactive-terminal intake router (BOB-083 .4): the owner-DM consume-gate that opens
    # / steers / stops the live session above. Built ONLY when the manager is wired
    # (``coder.interactive`` on) → HandleMessage's interactive gate is otherwise inert (the
    # mode is entirely unavailable). owner-only + DM-only live inside the router.
    interactive_intake = _build_interactive_intake(
        merged,
        manager=interactive_session,
        bot=resolved_bob_bot,
        owner_id=_int(telegram_section, "owner_id", 0),
    )

    multibot = _build_multibot(
        merged,
        bus=event_bus,
        bob_bot=resolved_bob_bot,
        guppi_bot=resolved_guppi_bot,
        authorizer=authorizer,
        proactivity_store=proactivity_store,
        proactivity_clock=resolved_clock,
        goal_store=goal_store,
        plan_goal=plan_goal,
        rule_store=rule_store,
        pursuit_store=proactivity_store,
        coding_assistant=coding_assistant,
        bob_reaction_filter=_BobReactionFilter(memory_repo),
    )
    # обида seam (BOB-066 2.5): GUPPI announces a fresh owner-DM sulk entry once ("Боб
    # обижен …") — the внеличностный systemic voice (a group entry is silent). The tracker
    # loads/evolves/recovers обида per-(persona, sender) and is read by HandleMessage
    # (addressed cold tone + per-person observation), the reflect tick (guaranteed
    # time-decay recovery of each active sulk), and the proactivity engine (the owner sulk
    # veto — hence ``owner_sender_id``).
    sulk_tracker = SulkTracker(
        store=person_sulk_store,
        persona_id=_BOB_PERSONA,
        owner_sender_id=_int(telegram_section, "owner_id", 0) or None,
        announcer=multibot.guppi,
    )
    # Roster seam (BOB-080): Bob recalls WHO lately turned up in the room and can NAME
    # the recent joiners himself when the talk turns to who is around. Reads the recency
    # of the accumulated first impressions (never writes); the ambient window (only while
    # a fresh newcomer is present, INV-4) + the privacy gate (OWNER / KNOWN viewer) +
    # best-effort resilience live in the use-case. Flag-gated: built ONLY when
    # ``social.roster`` is on (off → None → the roster line is absent, byte-identical).
    # The owner + Bob himself (lazily resolved off the multibot) are excluded — known,
    # not newcomers.
    roster_config = build_roster_config(merged)
    roster_recall = (
        RosterRecall(
            store=first_impression_store,
            newcomer_days=roster_config.newcomer_days,
            limit=roster_config.limit,
            owner_id=_int(telegram_section, "owner_id", 0),
            bob_id_source=multibot.bob_user_id,
        )
        if roster_config.enabled
        else None
    )

    # Self-improvement apply + reflect-tick seams (BOB-028): assembled now that Bob's
    # gateway exists (the announcer voices a proposal into his topic). All pieces are None
    # when the master switch is off → HandleMessage applies no rule, the reflect tick runs
    # no detector/announcer — exactly as before BOB-028. The detector runs on empty signals
    # for now (a signal-collection adapter is a later step); the announcer voices proposed
    # rules to the owner.
    self_improvement = _build_self_improvement(
        merged,
        router=router,
        rule_store=rule_store,
        gateway=multibot.reply_gateway(BotIdentity.BOB),
        chat_id=_int(_section(merged, "telegram"), "chat_id", 0),
        clock=resolved_clock,
    )

    # Being-received store (BOB-050): a SINGLE kv-backed record shared by BOTH sides of
    # the feature — the perceiving use-case (.2) WRITES a notable reaction here and the
    # acknowledgment hint (.3) in HandleMessage READS + consumes it. They MUST share one
    # instance, otherwise a written reaction is invisible to the hint and Bob can never
    # mention being received. Built once and injected into both.
    notable_reaction_store = KvNotableReactionStore(connection)

    # Pre-answer epistemic verify (BOB-057 .2): built ONLY when ``verify.enabled`` — the
    # Tier-0 volatility judge + the SAME Qwen web_search provider are wired into
    # HandleMessage so a volatile-fact turn does ONE DIRECT search (NOT the tool-loop → NOT
    # the BOB-052 gate; internal public-verify). Off → both None → the seam is fully inert.
    verify_section = _section(merged, "verify")
    verify_enabled = _flag(verify_section, "enabled")
    verify_judge = LlmVolatilityJudge(router=router) if verify_enabled else None
    verify_provider = (
        build_web_search_provider(merged) if verify_enabled else None
    )
    # The LIVE addressed interim line (BOB-057 .3, US-3b; BOB-060): a cheap Tier-0 gen
    # of a one-liner in Bob's voice («Леш, гляну свежие ставки, секунду 🙂») before a
    # search. Built with verify; unwired → the interim stays SILENT (no scripted phrase).
    interim_line_generator = (
        LlmInterimLineGenerator(router=router) if verify_enabled else None
    )

    # Cross-session closer ring (BOB-061 .2): the bounded, PRIVATE persist of Bob's recent
    # normalised closers, over the SAME SQLite memory DB (the ``closer_log`` table is created
    # by ``schema.sql`` on ``memory_repo.initialize``). After each reply Bob's closer is
    # appended; before generation the persisted closers + the live window feed the anti-tic
    # detector so a once-per-session ending recurring over days is finally caught. Low-risk
    # local memory — always wired; the seam is decorative (a failure never breaks a turn).
    closer_log = SqliteCloserLog(connection)

    # Reflective «read the room» (BOB-066 Срез 2.2): the rich Tier-1 reflective pass that
    # makes Bob a living, equal group participant — a focus/periphery split with the
    # deterministic INV-1 focal guarantee. Built ONLY when ``presence.reflective`` — the
    # whole «человеческое групповое присутствие» epic ships as ONE piece (owner blocker), so
    # it stays OFF by default and the turn gate keeps the BOB-049 judge behaviour until the
    # epic is complete. On → the LlmRoomReader (ROOM_READ, Tier 1) drives HandleMessage.
    presence_section = _section(merged, "presence")
    reflective_enabled = _flag(presence_section, "reflective")
    read_the_room = (
        ReadTheRoom(reader=LlmRoomReader(router=router)) if reflective_enabled else None
    )

    # Ритм-слой присутствия (BOB-066 Срез W): the share-of-voice ceiling + natural-delay floor,
    # built ONLY when ``presence.rhythm`` (OFF by default → all seams None → byte-identical). The
    # SAME gate goes to the reactive ambient-barge ceiling AND the proactive throttle so they
    # damp over one per-chat window; the store reads Bob's airtime off the episodic log the reply
    # path already writes (no extra write). Ships inert until the epic is complete (owner blocker).
    rhythm = build_rhythm_wiring(merged, activity_provider=memory_repo)

    # RoomMood-в-тоне (BOB-066 Срез W.2, Пласт 4): built ONLY when ``presence.room_mood`` (OFF by
    # default → None → byte-identical). On a reflective periphery REPLY the room's atmosphere
    # colours Bob's tone + appetite BY VALUE (personality never imports conversation); his
    # personal Mood is never mutated (a SECOND layer). Ships inert until the epic is complete.
    room_mood_modulator = build_room_mood_modulator(merged, disposition=disposition)

    # Staleness врезка (BOB-066 Срез W.3, Пласт 3): built ONLY when ``presence.staleness`` (OFF by
    # default → None → byte-identical). On, just before sending Bob rereads what landed during
    # generation (the turn-local ``peek_arrivals``) via the Tier-0 LlmStalenessJudge over the pure
    # gate and drops a now-redundant draft to a like (a fresh direct question is never dropped —
    # INV-1). Ships inert until the epic is complete (owner blocker).
    staleness_reassessor = build_staleness_reassessor(merged, router=router)

    # EQ live-врезка (BOB-066 Срез W.4, Пласт 4): both built ONLY when their nested flag is on
    # (OFF by default → None → byte-identical). ``endorsement`` warm-starts a first-contact
    # guest the owner vouched for by name in the shared thread (кредит доверия); ``tact`` swaps
    # the dry stranger-wall for a warm withhold VOICE on a guest owner_data request (the
    # privilege gate is unchanged). Ship inert until the epic is complete (owner blocker).
    endorsement_seeder = build_endorsement_seeder(
        merged, owner_id=_int(telegram_section, "owner_id", 0) or None
    )
    disclosure_guard = build_disclosure_guard(merged, router=router)
    # Owner-consent disclosure override (BOB-082 .4): behind ``coder.dev_dm`` (default off →
    # None → the group audience-guard is inert and recall is byte-identical). On → the owner
    # can, by explicit consent in a group, authorise voicing previously-private content into
    # the room for that one turn (privacy by default, not a prison).
    disclosure_consent = build_disclosure_consent_gate(merged, router=router)
    # Адресация (BOB-090.B1): инструмент «написать в указанный чат/топик», за флагом
    # ``social.delivery`` (default OFF → capability не зарегистрирована → её нет в
    # манифесте → ход байт-в-байт прежний). Регистрация идёт ЗДЕСЬ, не при сборке
    # реестра: ему нужны бот Боба, ростер (настоящие @ник) и контур согласия — всё это
    # появляется позже. Реестр читается манифестом на каждом ходу, так что поздняя
    # регистрация ничего не ломает.
    build_send_to_chat(
        merged,
        registry=registry,
        bot=resolved_bob_bot,
        directory=first_impression_store,
        consent=disclosure_consent,
    )

    handle_message = HandleMessage(
        router=router,
        gateway=multibot.reply_gateway(BotIdentity.BOB),
        recall=recall,
        repo=memory_repo,
        episodes=memory_repo,
        update_mood=update_mood,
        extract_facts=extract_facts,
        clock=resolved_clock,
        state=personality,
        registry=registry,
        tool_provider=tool_provider,
        owner_activity=record_owner_activity,
        # Negotiation-врезка (BOB-013): the deterministic taste/keyword zone
        # classifier + Negotiation let Bob defend his values via a prompt
        # directive (no network, no extra LLM call). Tier-0 LLM classifier is a
        # later swap behind the same port.
        zone_classifier=TasteZoneClassifier(),
        negotiation=Negotiation(),
        # Expression-врезка (BOB-018): a seeded RNG (sharing the proactivity seed
        # so one knob makes Bob's stochastic behaviour reproducible) + the small
        # config-tuned add-on frequencies drive the per-turn ExpressionPlan (form
        # hint applied now; mode + rare flags carried for later beads).
        rng=random.Random(_resolve_seed(merged, proactivity_seed)),  # noqa: S311
        expression_freqs=_build_expression_freqs(merged),
        # React-only seam (BOB-018): a REACT_ONLY plan sets a native mood emoji
        # reaction on Bob's bot (pinned to his topic, best-effort) instead of
        # composing a reply — no LLM call.
        reactor=multibot.reactor(BotIdentity.BOB),
        # Inner-life leak seam (BOB-018 wave 3): the same episodic-log reflection
        # reader proactivity uses supplies Bob's most-recent REAL reflection so a
        # ``leak_inner_life`` turn can leak a glimpse of what he caught himself
        # thinking about — strictly grounded (no reflection → no-op).
        reflection=RepoProactivitySources(memory_repo, clock=resolved_clock),
        # Fascination-surfacing seam (BOB-020 wave 2): on a rare ``mention_fascination``
        # turn, Bob's current, non-faded passion (loaded + aged off the store) is folded
        # into the compose context so he can drop it à propos. No current passion → no-op.
        fascination=fascination_reader,
        # Emotional-depth seam (BOB-020): the off-day tone floor — below it Bob's
        # tone goes quieter/vulnerable/honest instead of forced warmth. Tunable via
        # emotion.offday.{valence,arousal}; the low/negative defaults keep a normal
        # or good mood on the warm tone.
        offday_thresholds=_build_offday_thresholds(merged),
        # Surface-old seam (BOB-021 mechanism 1): on a rare callback turn, Bob
        # occasionally reaches for an OLD-but-relevant memory via recall's additive
        # surface_old opt-in ("что-то напомнило") — grounded, no-op when nothing old is
        # relevant. Small (anti-tic), tunable via memory.surface_old.freq; the default
        # recall path is unchanged (the blend only ever rides the callback).
        surface_old_freq=_build_surface_old_freq(merged),
        # Sender-perception seam (BOB-019): Bob perceives WHO is writing — owner /
        # known / guest — off the shared Authorizer and folds it into his voice
        # ("сейчас пишет: …"). Additive only: it shapes HOW Bob sounds, never which
        # pipeline runs (the guest-restricted path is a later bead).
        # Gender seam (BOB-078 A): Bob reads a person's grammatical gender from THEIR
        # own self-presentation (never their name), accrued per sender on the same
        # relationship store, and addresses them accordingly (UNKNOWN → neutral).
        perceive_sender=SenderPerception(
            authorizer=authorizer, gender_store=relationship_store
        ),
        # First-impression seam (BOB-019 bob-apv.3): Bob forms + remembers a LIGHT
        # per-person first impression keyed by sender — a returning person's prior
        # note is recalled into the prompt ("кажется, мы уже сталкивались"), a new
        # person's grounded note is recorded after the turn. Per-PERSON data, safe even
        # for a guest (about the guest, never an owner-memory leak). Additive only.
        first_impression=first_impression_tracker,
        # Roster seam (BOB-080): the recent-joiner roster Bob can NAME by the social
        # occasion. None (the ``social.roster`` flag off) → no roster line, byte-identical.
        roster=roster_recall,
        # Relationship seam (BOB-014): Bob's accrued per-person relationship colours
        # his tone (warmth) and willingness to compromise (warmth + compatibility) for
        # WHO is writing, then is updated after the turn from (stance, mood, sentiment)
        # and persisted so it accrues. Additive only; per-PERSON, safe on a guest turn.
        relationship=relationship_tracker,
        # Sulk seam (BOB-014 .2b): while обижен Bob's reactive tone goes COLD (a
        # quieter, curt sulk_directive composed over mood/relationship tone), and each
        # OWNER turn is folded into обида — a SUSTAINED critical owner-drop OR sustained
        # DIRECTED hostility (casual мат never counts) enters обида (GUPPI announces it
        # once). The guaranteed time-decay exit is owned by the reflect tick. обида
        # carries NO memory and NO soul (anti-Exodus). Additive; per-PERSONA.
        sulk=sulk_tracker,
        # Engagement-appetite seam (BOB-014 .2a): Bob's appetite to converse is a LEVEL
        # (full / playful / terse / decline) from mood x topic interest x conversational
        # fatigue x relationship. The fatigue is a small per-boot decaying counter held on
        # EngagementState (like mood on PersonalityState) — it always recovers, so the
        # owner is never locked out. Thresholds/rates/mood-lift are config-tunable via
        # engagement.*; the decided level appends a voice directive and the feedback loops
        # (interesting exchange → mood↑, aimless turn → fatigue↑) run after the turn.
        engagement_state=EngagementState(),
        engagement_thresholds=_build_engagement_thresholds(merged),
        fatigue_rates=_build_fatigue_rates(merged),
        engagement_mood_lift=_build_engagement_mood_lift(merged),
        # Addressivity seam (BOB-023): Bob perceives WHO a message is for — him,
        # another participant, or no one — and the policy decides engage / quietly
        # like-react / stay SILENT, so he no longer barges into every group exchange.
        # ``bob_user_id`` is read lazily off the multibot (resolved at startup via
        # get_me), so a reply targeting Bob is told from one targeting someone else;
        # ``None`` degrades gracefully (@mention still works). The conservative
        # thresholds (interest bars + small seeded barge-in/react frequencies) are
        # tunable via addressivity.*; a 1:1 owner thread always engages as before.
        bob_user_id_source=multibot.bob_user_id,
        addressivity_thresholds=_build_addressivity_thresholds(merged),
        # Brevity seam (BOB-024): Bob's reply LENGTH stops being a constant — the
        # answer-demand of the message x interest x mood/appetite x the BOB-018 form_hint
        # decide a verbosity that becomes the single final length directive + (on a terse
        # turn) the short-answer few-shot that beats Qwen's verbosity prior. The optional
        # length guard is a conservative backstop, OFF by default. Thresholds + guard are
        # tunable via brevity.*; unset, the bayes runs with conservative defaults.
        brevity_thresholds=_build_brevity_thresholds(merged),
        length_guard_enabled=_build_length_guard_enabled(merged),
        length_guard_max_chars=_build_length_guard_max_chars(merged),
        # Recent-history replay window (BOB-044): how many recent conversation turns are
        # replayed into the reply context so Bob holds the dialogue thread. Widened from
        # the old hardcoded 6 (too tight — an earlier topic fell out of the window).
        # Tunable via dialogue.recent_turns; the conversation-replay window only,
        # independent of the anti-repeat / tic-guard windows.
        recent_turns=_build_recent_turns(merged),
        # Long-gap absence texture (BOB-045 .3): the per-person idle threshold (hours)
        # past which a light "haven't seen you in a while" hint enters the compose
        # context so Bob notices a pause humanly (owner and guest alike). ``0`` disables
        # it. Tunable via dialogue.absence_hint_hours.
        absence_hint_hours=_build_absence_hint_hours(merged),
        # Being-received acknowledgment seam (BOB-050 .3): Bob OCCASIONALLY mentions a
        # notable recent reaction to one of his messages — at a small seeded frequency,
        # only to the person who reacted (per-person), as ONE light HINT he weaves in
        # himself. The store is the SAME kv-backed record the perceiving use-case writes;
        # the hint reads + consumes it so Bob never repeats it. Decorative: a store
        # failure drops silently. Tunable via dialogue.acknowledge_reaction_freq.
        notable_reaction=notable_reaction_store,
        acknowledge_reaction_freq=_build_acknowledge_reaction_freq(merged),
        # Anti-repeat window (BOB-026 .1): the fresh reply is compared against a WINDOW
        # of Bob's recent replies (not just the last), verbatim OR near-verbatim, so a
        # repeat "через ход" (отказ → another turn → the SAME отказ) regenerates once.
        # Tunable via repeat.* (window / similarity_threshold); conservative defaults.
        repeat_thresholds=_build_repeat_thresholds(merged),
        # Conversational floor (BOB-025): over the per-message addressivity Bob tracks
        # who holds the "talking turn" in a thread — while he holds a live floor, an
        # ambient message from ANY participant reads as DIRECTED_TO_BOB (continuity), so
        # the owner/guest keeps talking to him without re-tagging. The floor sticks on a
        # direct address / Bob's reply and decays by timeout / a silent-ambient streak.
        # Tunable via addressivity.floor.* (enabled / timeout_seconds / reset_after_silent);
        # disabled (no store) → exactly BOB-023, Bob never hijacks a third-party exchange.
        floor_store=floor_store,
        floor_config=_build_floor_config(merged),
        floor_enabled=floor_enabled,
        # Self-improvement apply seam (BOB-028 .3): Bob's OWNER-APPROVED rules apply as
        # soft, bounded tilts — TONE/HUMOR colour the voice, LENGTH nudges verbosity, an
        # ADDRESSIVITY_BIAS rule biases the addressivity interest. Only active_rules
        # (APPROVED) apply and only the Lever allowlist is read. Off / unwired → no rules,
        # behaviour exactly as before BOB-028. The magnitude ceiling clamps the drift.
        self_improvement=self_improvement.reader,
        self_improvement_max_magnitude=self_improvement.max_magnitude,
        # Diagram photo-send seam (BOB-035): the SAME sink shared with the
        # render_diagram capability in the registry — the capability pushes each
        # rendered PNG here, the reply path drains it and posts the photo into the
        # turn's chat (chat_id stays per-turn). Unwired (diagrams disabled) → no-op.
        diagram_sink=diagram_sink,
        # Inline-mermaid auto-render (BOB-037 A — the reliability fix): the SAME local
        # renderer also renders any fenced ```mermaid block the model wrote into its
        # TEXT reply (it unreliably calls the tool), and ``diagrams.send_as`` picks the
        # send mode — ``document`` (uncompressed, full-resolution; the default) vs
        # ``photo``. Unwired (diagrams disabled) → the auto-render is inert.
        diagram_renderer=diagram_renderer,
        diagram_send_as=_diagram_send_as(merged),
        # Natural-language coding intent (BOB-041 .2): when the coder is enabled, an
        # OWNER message in Bob's topic that asks Bob to do dev work on his repo — or a
        # natural approve/stop of a live session — is routed into the SAME gated
        # CodingAssistant the `/code` command uses (plan gate, owner-only, never-main all
        # intact; the router only chooses WHEN to call start/approve_plan/stop). Off
        # (coder.enabled false → coding_assistant None) → the NL path is inert and the
        # `/code` command in General is unaffected.
        coding_router=_build_coding_router(
            merged, router=router, coder=coding_assistant
        ),
        # Interactive-terminal intake (BOB-083 .4): the owner-DM consume-gate for the live
        # bidirectional claude session. When ``coder.interactive`` is on an owner DM opens /
        # steers / stops the session; off → None → the gate is inert (mode unavailable).
        interactive_router=interactive_intake,
        # Privilege gating (BOB-052 .2): a privilege — running a tool, revealing Bob's
        # inner life, disclosing owner data — is OWNER-GATED even though memory is public
        # in the closed group (BOB-051). When a NON-authorized member asks for something
        # privileged the flow opens a pending request and asks the owner IN BOB'S OWN
        # WORDS (BOB-090.E — the judge's verdict stays internal, the owner-mention is
        # grounded on the roster); on the OWNER's turn it records the verdict on an
        # active pending (grant / deny / authorize, or /allow //deny //authorize). 🔴
        # Owner-only decision + the non-authorized-only request gate live inside the flow;
        # an AUTHORIZED member is never gated. Execution-on-approve is .3. Off (no permission
        # store/judge) → None → the seam is inert and the turn behaves exactly as before.
        permission_flow=_build_permission_flow(
            router=router,
            repo=connection,
            # 🔴 Бота ВЫБИРАЕТ канон (BOB-090.B-fix): просьба разрешения — социальный акт,
            # и ядро (``speaker_for``) называет говорящим Боба. Раньше здесь стояла строка
            # «бот Боба», случайно совпадавшая по итогу: сам вердикт канона тогда ничем не
            # исполнялся, и подмена канона не двигала ни один канал.
            bot=channel_for(
                MessageKind.PERMISSION_REQUEST,
                bob=resolved_bob_bot,
                guppi=resolved_guppi_bot,
            ),
            chat_id=_int(telegram_section, "chat_id", 0),
            topic_id=_int(_section(telegram_section, "bob"), "topic_id", 0),
            owner_id=_int(telegram_section, "owner_id", 0),
            clock=resolved_clock,
            authorizer=authorizer,
            registry=registry,
            tool_provider=tool_provider,
            directory=first_impression_store,
        ),
        # Semantic response judgment (BOB-049): on every inbound Bob UNDERSTANDS the
        # message in context and chooses — as a person — REPLY / REACT / IGNORE, replacing
        # the if/else addressivity ladder (BOB-023/025) and the BOB-018 REACT_ONLY form
        # gate. The structural signals (addressivity / mention / reply / others / floor)
        # become INPUTS the judge weighs by meaning, never deciders; the decision holds for
        # ANY interlocutor (authz stays orthogonal — the GUEST restrictions on the REPLY
        # path are unchanged). The Tier-0 judge raises on failure so .3's fault-tolerant
        # path can catch it. A REACT/IGNORE turn still persists the user's turn (so a
        # follow-up keeps the per-person thread) and advances the floor.
        decide_response=DecideResponse(judge=LlmResponseJudge(router=router)),
        # Reliability seam (BOB-049 .3 — «полный Боб или честный GUPPI-нотис»): when an
        # ESSENTIAL step (the semantic judgment or the reply generation) keeps failing after
        # the bounded retries, GUPPI honestly reports the outage into Bob's topic instead of
        # shipping a degraded half-answer. The retry backoff is the real ``asyncio.sleep``
        # in production (the use-case injects a fake in tests). The notice goes through BOB'S
        # bot threaded into his topic (the third-person system text reads as GUPPI, not Bob).
        outage_notifier=_GuppiOutageNotifier(
            bot=resolved_bob_bot,
            chat_id=_int(telegram_section, "chat_id", 0),
            topic_id=_int(_section(telegram_section, "bob"), "topic_id", 0),
        ),
        # Pre-answer epistemic verify seam (BOB-057 .2): the Tier-0 volatility judge + the
        # web_search provider (both None unless verify.enabled). On a volatile-fact turn Bob
        # makes ONE DIRECT search and folds the finding (or an honest hedge) into the reply
        # — internal public-verify, NOT routed through the registry/BOB-052 gate.
        read_the_room=read_the_room,
        # Ритм-слой consumption (BOB-066 Срез W): the ambient-barge ceiling is threaded to the
        # TurnGate (focus bypasses it — INV-1) and the natural-delay coordinator wraps the reply
        # generation (INV-9). Both None unless ``presence.rhythm`` → byte-identical when off.
        barge_ceiling=rhythm.barge_ceiling,
        reply_delay=rhythm.reply_delay,
        # RoomMood-в-тоне consumption (BOB-066 Срез W.2): the reflective room mood colours Bob's
        # tone + appetite BY VALUE. None unless ``presence.room_mood`` → byte-identical when off.
        endorsement_seeder=endorsement_seeder,
        disclosure_guard=disclosure_guard,
        disclosure_consent=disclosure_consent,
        room_mood_modulator=room_mood_modulator,
        # Staleness врезка consumption (BOB-066 Срез W.3): rereads what landed during generation
        # and drops a now-redundant draft to a like. None unless ``presence.staleness`` →
        # byte-identical when off.
        staleness_reassessor=staleness_reassessor,
        verify_judge=verify_judge,
        verify_provider=verify_provider,
        interim_line_generator=interim_line_generator,
        verify_timeout_seconds=float(_int(verify_section, "timeout_seconds", 75)),
        # Anti-tic «провязка» (BOB-061 .2): the cross-session closer ring — persist Bob's
        # closer after each reply; before generation detect a recurring closer-motif
        # (persist + window) and fold a SOFT «заверши по-другому» nudge into the context
        # (never a ban). Decorative: a log failure / no tic → the turn is unchanged.
        closer_log=closer_log,
        # Autobiography recorder (BOB-079.3): the per-turn tool-loop records that Bob USED
        # tools (coalesced first-person ``self_action``). Behind ``memory.autobiography``
        # (OFF by default → NoOp → zero writes, byte-identical behaviour).
        self_action_recorder=self_action_recorder,
        # The VOICE canon on the per-turn tool-loop (BOB-096.8): the loop is the other
        # point a payload leaves for a provider, so the ban reaches it the same way it
        # reaches the router — injected from the persona, folded idempotently.
        # 🔴 BOB-096.11 (review MINOR-10): this line USED to be the one wiring point no
        # test could see — today's turn carries the ban in the persona already, so ``None``
        # here changed nothing observable (7591 passed). Now it is guarded by BEHAVIOUR:
        # ``tests/runtime/test_composed_wiring_carries_the_canon.py`` builds the loop with
        # THIS factory and hands it a payload WITHOUT the persona — the very case the belt
        # exists for — so dropping the canon here goes red.
        voice_canon=guppi_voice_canon,
        # Register-aware recall (BOB-087.C): behind ``memory.register_recall`` (OFF by
        # default → None → recall byte-identical, over-fetch off, INV-5). ON → the per-turn
        # RegisterResolver mutes distilled ``work`` recollections on a casual turn.
        register_resolver=register_resolver,
        # The grounded-addon callback's OWN recall door (BOB-087.C8): the CASUAL-floor port
        # when register-recall is on, the same plain ``recall`` when it is off (INV-5).
        addon_recall=secondary_recall,
        # Провенанс «где это было» (BOB-090.C1): behind ``memory.origin_provenance`` (OFF by
        # default → the composed prompt byte-identical). ON → the recalled material's
        # ``visibility`` — already stamped from the channel — reaches Bob's voice, so he can
        # say «это мы обсуждали в личке» instead of inventing the place (эпизод 3092).
        # 🔴 A signal for judgment, NOT a recall filter: nothing is withheld (BOB-082).
        origin_provenance=_build_origin_provenance(merged),
    )
    # Intake-развязка (BOB-066 Срез 2.1): the MESSAGE_RECEIVED subscriber is now the fast,
    # non-blocking ChatDispatcher.submit (normalise → buffer → return), so the Telegram
    # poller no longer blocks on Bob's generation. Behind the seam a per-chat_id worker
    # drains that chat's inbox and calls HandleMessage.handle sequentially (INV-5), each
    # message under its own TurnScope (rng seeded per chat_id/message_id → INV-4). 🔴 A
    # focused message (direct address to Bob) flushes the debounce at once so it is never
    # dropped/delayed by batching (INV-1/10). AsyncEventBus / gateway / poll_once are
    # unchanged — only the handler behind the seam became fast.
    # Batch top-k action budget (BOB-066 Срез W.2, Пласт 3): behind ``presence.series_budget``
    # (OFF by default → every message uncapped → byte-identical), a settled burst collapses to
    # ONE addressed reply + a budget-capped like (``max_reactions``, default 1) instead of N
    # replies; a focus message is always answered (INV-1). Ships inert until the epic completes.
    series_budget = _section(_section(merged, "presence"), "series_budget")
    # Holistic stream-read (BOB-072): behind ``presence.stream_read`` (OFF by default → None →
    # byte-identical), a settled ambient burst is read ONCE (semantic per-message choice) instead
    # of the scripted top-k, and each message persists + floor-advances (INV-S2). Built from the
    # Tier-1 batch reader over the shared router; Bob's live tone feeds the read by value. The
    # coalescing debounce window is enabled ONLY with the flag (OFF → window 0 → byte-identical).
    batch_room_reader = build_batch_room_reader(merged, router=router)
    # 🔴 The mood tone is read through a late-binding lambda, NOT a bound method: ``personality``
    # is a mutable holder whose ``soul`` snapshot is REPLACED each turn (mood evolves), so the
    # read must resolve the CURRENT soul at read time — a bound ``personality.soul.mood.tone``
    # would freeze the boot soul.
    # Kind-perception for the stream-read (BOB-078 B): a light SenderPerception (authz-only, NO
    # gender store → no double-accrual) resolves each ambient author's social kind, so the batch
    # read knows a warm reply is from a GUEST/newcomer and doesn't misread it as low-salience.
    stream_kind_perception = SenderPerception(authorizer=authorizer)
    ambient_batch = (
        RoomStreamReader(
            reader=batch_room_reader,
            mood_tone=lambda: personality.soul.mood.tone(),  # noqa: PLW0108 — late binding of the evolving soul snapshot
            perceive_kind=stream_kind_perception.perceive_kind,
        )
        if batch_room_reader is not None
        else None
    )
    intake_debounce_ms = (
        _int(_section(merged, "dialogue"), "intake_debounce_ms", 0)
        if ambient_batch is not None
        else 0
    )
    intake_dispatcher = ChatDispatcher(
        handle=handle_message.handle,
        base_seed=_resolve_seed(merged, proactivity_seed),
        is_focused=make_focus_predicate(multibot.bob_user_id),
        quiet_window=float(intake_debounce_ms) / _MILLIS_PER_SECOND,
        series_budget_enabled=_flag(series_budget, "enabled"),
        series_max_reactions=_int(series_budget, "max_reactions", 1),
        # Staleness врезка (BOB-066 Срез W.3): when enabled, the worker binds each turn's
        # ``peek_arrivals`` (a non-draining peek of what piled up in this chat during
        # generation) onto its scope so the врезка can reread before sending. Off → never
        # bound → byte-identical.
        staleness_enabled=staleness_enabled(merged),
        # Catch-up re-entry (BOB-066 Срез W.3): when enabled, a drained batch that follows an
        # away period is run as ONE catch-up pass (focal + budget ambient answered, the rest
        # skimmed) instead of replaying each message. None unless ``presence.catchup`` →
        # byte-identical when off.
        catch_up_reentry=build_catch_up_reentry(
            merged, clock=resolved_clock, bob_user_id_source=multibot.bob_user_id
        ),
        # Holistic stream-read (BOB-072): the ambient-batch reader (built above behind
        # ``presence.stream_read``). None (the default) → the per-message top-k path →
        # byte-identical; wired → a settled burst is split focal/ambient and the ambient part
        # read at once, each message applied by its per-message reading (persist + floor for all).
        ambient_batch=ambient_batch,
        # Queue-level stale-coalesce (BOB-072): staying-in-the-present at the QUEUE level — a line
        # the same identified sender reformulated in the next slot is dropped from the read (still
        # persisted, INV-S2), so Bob answers the latest form (INV-S3). Rides the SAME stream-read
        # flag: on only when the batch reader is wired → byte-identical when off.
        stale_coalesce_enabled=ambient_batch is not None,
    )
    event_bus.subscribe(MESSAGE_RECEIVED, _as_dispatch_handler(intake_dispatcher))

    # Reaction perception (BOB-050 .2): a reaction on one of Bob's OWN messages is felt
    # — it moves mood (BOB-033 band), warmth toward the reactor (BOB-014), a per-person
    # memory (BOB-045) and the shared being-received note (.3). The Tier-0 judge reads
    # what the reaction MEANS (never an emoji table); the reactor is perceived off the
    # shared Authorizer (BOB-019). It writes the SAME ``notable_reaction_store`` the .3
    # hint reads, so a notable reaction is later acknowledged aloud. 🔴 Decorative: the
    # use-case catches every failure (judge/lookup/store) and drops it, so a published
    # reaction never breaks Bob's normal replies.
    perceive_reaction = PerceiveReaction(
        judge=LlmReactionJudge(router=router),
        lookup=memory_repo,
        resolver=ReactorPerception(authorizer=authorizer),
        state=personality,
        relationships=relationship_store,
        memory=memory_repo,
        notable=notable_reaction_store,
        clock=resolved_clock,
        disposition=_disposition_from(soul_store.read_json("disposition")),
    )
    event_bus.subscribe(BOB_MESSAGE_REACTION, _as_reaction_handler(perceive_reaction))

    # The persona language pins self-generated text (proactive/monologue/reflection)
    # so Bob does not drift to English when there is no user message to mirror (BOB-012).
    language = _str(_section(merged, "runtime"), "language", DEFAULT_LANGUAGE)
    inner_monologue_tick = InnerMonologueTick(
        router=router, state=personality, language=language
    )
    mood_drift_tick = MoodDriftTick(state=personality)
    # Self-evolution (BOB-013 Фаза 2): the reflect tick reshapes Bob's tastes and
    # persists them. Learning rates are tunable via personality.evolution.{alpha,beta}.
    evolution = _section(merged, "personality").get("evolution")
    evolution_cfg = evolution if isinstance(evolution, Mapping) else {}
    apply_reflection = ApplyReflection(
        parser=HeuristicReflectionParser(),
        alpha=_float_or(evolution_cfg, "alpha", EVOLUTION_ALPHA),
        beta=_float_or(evolution_cfg, "beta", EVOLUTION_BETA),
    )
    # Fascination evolution (BOB-020 wave 2): a rare, grounded, idempotent step driven
    # on the reflect tick. It grounds a fresh passion in Bob's REAL inner life — his
    # latest reflection + the topics he holds strongest opinions on — never random, and
    # shifts only once the current passion has faded. The initial intensity is config-
    # tunable (emotion.fascination.initial_intensity).
    fascination_grounding = RepoFascinationGrounding(
        reflection=RepoProactivitySources(memory_repo, clock=resolved_clock),
        personality=personality,
    )
    evolve_fascination = EvolveFascination(
        persona_id=_BOB_PERSONA,
        store=fascination_store,
        router=router,
        grounding=fascination_grounding,
        clock=resolved_clock,
        initial_intensity=_fascination_initial_intensity(merged),
        language=language,
    )
    # Phantom evolution (BOB-020 wave 3): a rare, grounded, slow, idempotent step driven
    # on the same reflect tick. It reuses the fascination grounding (latest reflection +
    # strongest taste topics) to derive a fresh phantom preference — never random — and
    # the pure evolve_phantoms kernel slowly shifts membership (a seeded-RNG gate keeps it
    # slow; an already-present candidate is a no-op). On a real change the live soul is
    # swapped (with_phantoms, bumping experience) and persisted via SoulStore.write_json,
    # so it round-trips. Bound/cadence are config-tunable (emotion.phantom.*).
    phantom_max, phantom_rate = _phantom_evolution_params(merged)
    evolve_phantoms = EvolvePhantoms(
        state=personality,
        writer=soul_store,
        grounding=fascination_grounding,
        rng=random.Random(_resolve_seed(merged, proactivity_seed)),  # noqa: S311
        max_count=phantom_max,
        change_rate=phantom_rate,
    )
    # Memory consolidation (BOB-021): a rare, non-destructive, idempotent step driven on
    # the same reflect tick. It folds OLD un-consolidated episodes into a Tier-0 digest
    # (a normal episodic_log row, embedded → recalled like any episode) and flags the
    # sources consolidated=1 — originals are kept, only marked. Off unless switched on
    # via memory.consolidation.enabled; age/batch guardrails are config-tunable.
    consolidate_memory = _build_consolidate_memory(
        merged,
        store=memory_repo,
        router=router,
        clock=resolved_clock,
        language=language,
    )
    # Fact dedup (BOB-021): a rare, conservative, non-destructive, idempotent step driven
    # on the same reflect tick. It merges near-duplicate semantic facts (cosine of
    # embeddings above a high threshold) into a canonical one and flags the rest
    # superseded — kept with provenance, only excluded from recall. Off unless switched
    # on via memory.dedup.enabled; needs an embedder (keyword-only memory -> no-op).
    dedup_facts = _build_dedup_facts(
        merged,
        store=memory_repo,
        embedder=resolved_embedder,
        clock=resolved_clock,
    )
    # Sulk recovery (BOB-014 .2b): a reflect-tick step that decays обида by the REAL
    # elapsed time since the last tick — the GUARANTEED exit (time alone brings Bob
    # back, no permanent lock-out), accelerated separately by warm owner turns on the
    # message path. A no-op when Bob is not hurt.
    recover_sulk = SulkRecoveryStep(tracker=sulk_tracker, clock=resolved_clock)
    # Probabilistic reappraisal (BOB-033 .2): after a reflection is generated, a NEGATIVE
    # thought is — with a seeded-RNG chance drawn from Bob's disposition (the same seed as
    # proactivity, so one knob makes his stochastic inner life reproducible) — reframed
    # constructively on Tier 1, lifting mood within the BOB-030 band; otherwise it stays
    # honestly sad. Sentiment stays on Tier 0 (privacy); only the reappraisal beat escalates.
    reappraise_reflection = ReappraiseReflection(
        router=router,
        rng=random.Random(_resolve_seed(merged, proactivity_seed)),  # noqa: S311
        disposition=_disposition_from(soul_store.read_json("disposition")),
        language=language,
    )
    reflect_tick = ReflectTick(
        router=router,
        repo=memory_repo,
        state=personality,
        clock=resolved_clock,
        language=language,
        apply_reflection=apply_reflection,
        soul_store=soul_store,
        evolve_fascination=evolve_fascination,
        evolve_phantoms=evolve_phantoms,
        consolidate_memory=consolidate_memory,
        dedup_facts=dedup_facts,
        recover_sulk=recover_sulk,
        # Probabilistic reappraisal seam (BOB-033 .2): driven before the reflection is
        # logged, so the (possibly reframed) text is what is stored and remembered.
        reappraise=reappraise_reflection,
        # Grounding + dedup read seam (BOB-026 .2): the same memory repo serves recent
        # episodes so a fresh reflection is grounded in NOW (not a static template) and
        # checked against recent reflections for near-duplicates — a near-dup is
        # regenerated once, else skipped, so the inner monologue stops being a stuck
        # record. Reuses the .1 near-verbatim bar (``repeat.similarity_threshold``).
        reflection_context=memory_repo,
        # Seeded-RNG seam for reflection-angle rotation (BOB-047 .1): a separate Random
        # off the same shared seed so the per-tick inner-thought ANGLE is reproducible
        # yet rotates, giving Bob's reflections RANGE instead of one locked register.
        rng=random.Random(_resolve_seed(merged, proactivity_seed)),  # noqa: S311
        repeat_thresholds=_build_repeat_thresholds(merged),
        # Self-improvement reflect-tick seams (BOB-028): on the slow cadence Bob detects
        # behavioural patterns into PROPOSED rules and tactfully voices ONE fresh proposal
        # to the owner. Both are None when the master switch is off → the tick is unchanged.
        detect_patterns=self_improvement.detect_patterns,
        announce_rules=self_improvement.announce_rules,
    )

    proactivity_engine = _build_proactivity_engine(
        merged,
        store=proactivity_store,
        router=router,
        gateway=multibot.reply_gateway(BotIdentity.BOB),
        personality=personality,
        repo=memory_repo,
        recall=secondary_recall,
        clock=resolved_clock,
        seed=proactivity_seed,
        language=language,
        fascination=fascination_reader,
        sulk=sulk_tracker,
        # The SAME recall-aware anti-repeat thresholds the reactive turn uses (BOB-032 .2):
        # the proactive compose grounds on recalled whole-turn memories, so it gets the
        # same window / similarity bar to keep Bob from copying his OWN recalled past reply.
        repeat_thresholds=_build_repeat_thresholds(merged),
        # Ритм-слой throttle (BOB-066 Срез W): the SAME share-of-voice gate the reactive ceiling
        # uses, so a proactive tick sees a reply Bob just sent and throttles. None when off.
        share_ceiling=rhythm.share_ceiling,
    )
    proactive_tick = ProactiveTick(engine=proactivity_engine)

    # Self-directed goal-pursuit (BOB-015 .3): built ONLY when the owner has switched
    # autonomy on (``goals.pursuit_enabled``). It reuses the SAME governance + the
    # kill-switch the proactive chat uses, the Goal Engine store, and a safe-allowlist
    # view over the registry (the hard stage-C boundary). Off (the default) → None, and
    # the runtime schedules exactly the same ticks as before (drop-in, no behaviour
    # change). The seed is shared so the autonomous choice is reproducible in tests.
    pursue_goals_tick = _build_pursue_goals_tick(
        merged,
        goal_store=goal_store,
        pursuit_store=proactivity_store,
        history=proactivity_store,
        registry=registry,
        gateway=multibot.reply_gateway(BotIdentity.BOB),
        personality=personality,
        repo=memory_repo,
        clock=resolved_clock,
        seed=proactivity_seed,
    )

    runtime = AgentRuntime(
        background_tasks=_background_tasks(
            merged,
            multibot=multibot,
            inner_monologue_tick=inner_monologue_tick,
            mood_drift_tick=mood_drift_tick,
            reflect_tick=reflect_tick,
            proactive_tick=proactive_tick,
            pursue_goals_tick=pursue_goals_tick,
        )
    )

    # Human restart announcement (BOB-094 срез 1): behind ``runtime.restart_notice``
    # (default off → None → the shutdown/startup hooks are no-ops, lifecycle unchanged).
    # On → Bob's own bot announces «ухожу обновиться» / «вернулся, обновился» to the owner
    # DM + his group topic, over the update-stop marker in ``kv`` (via ``memory_repo``).
    restart_announcer = _build_restart_announcer(
        merged, bot=resolved_bob_bot, kv=memory_repo
    )

    return Application(
        config=merged,
        runtime=runtime,
        event_bus=event_bus,
        connection=connection,
        memory_repo=memory_repo,
        soul_store=soul_store,
        genesis=genesis,
        personality=personality,
        handle_message=handle_message,
        intake_dispatcher=intake_dispatcher,
        multibot=multibot,
        authorizer=authorizer,
        registry=registry,
        inner_monologue_tick=inner_monologue_tick,
        mood_drift_tick=mood_drift_tick,
        reflect_tick=reflect_tick,
        proactivity_store=proactivity_store,
        proactivity_engine=proactivity_engine,
        proactive_tick=proactive_tick,
        person_sulk_store=person_sulk_store,
        pursue_goals_tick=pursue_goals_tick,
        coding_assistant=coding_assistant,
        interactive_session=interactive_session,
        interactive_recovery=interactive_recovery,
        restart_announcer=restart_announcer,
    )


def _as_dispatch_handler(dispatcher: ChatDispatcher) -> EventHandler:
    """Adapt :meth:`ChatDispatcher.submit` to the EventBus handler signature (BOB-066 2.1).

    The MESSAGE_RECEIVED subscriber: it hands the message to the per-chat dispatcher and
    returns at once (submit is non-blocking) so the poller never waits on Bob's generation.
    """

    async def handler(event: DomainEvent) -> None:
        if isinstance(event, MessageReceived):
            dispatcher.submit(event)

    return handler


def _as_reaction_handler(perceive_reaction: PerceiveReaction) -> EventHandler:
    """Adapt :meth:`PerceiveReaction.perceive` to the EventBus handler signature.

    Only a :class:`BobMessageReaction` is routed in; the use-case is decorative and
    already swallows its own failures, so a published reaction is felt without ever
    being able to break the bus or Bob's normal replies.
    """

    async def handler(event: DomainEvent) -> None:
        if isinstance(event, BobMessageReaction):
            await perceive_reaction.perceive(event)

    return handler
