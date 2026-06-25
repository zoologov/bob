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

import asyncio
import logging
import os
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from bob.application.authz import Authorizer, SenderPerception
from bob.application.capabilities import (
    CapabilityRegistry,
    SafeCapabilityDispatcher,
    make_inspect_architecture_capability,
    make_list_work_capability,
    make_read_code_capability,
    make_recall_memory_capability,
    make_search_memory_capability,
)
from bob.application.proactivity import (
    ProactiveTick,
    ProactivityEngine,
    RecordOwnerActivity,
)
from bob.application.router import LLMRouter
from bob.application.runtime import (
    MESSAGE_RECEIVED,
    AgentRuntime,
    AsyncEventBus,
    MessageReceived,
    RetryPolicy,
    periodic,
)
from bob.application.usecases.announce_rules import AnnounceProposedRules
from bob.application.usecases.apply_reflection import ApplyReflection
from bob.application.usecases.consolidate_memory import ConsolidateMemory
from bob.application.usecases.dedup_facts import DedupFacts
from bob.application.usecases.detect_patterns import DetectPatterns, LlmPatternDetector
from bob.application.usecases.evolve_fascination import EvolveFascination
from bob.application.usecases.evolve_phantoms import EvolvePhantoms
from bob.application.usecases.extract_facts import ExtractFacts
from bob.application.usecases.fascination_sources import (
    RepoFascinationGrounding,
    StoreFascinationReader,
)
from bob.application.usecases.first_impression_sources import FirstImpressionTracker
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
from bob.application.usecases.plan_goal import LlmPlanner, PlanGoal
from bob.application.usecases.pursue_goals import PursueGoalsTick
from bob.application.usecases.reappraise_reflection import ReappraiseReflection
from bob.application.usecases.reflection_parser import HeuristicReflectionParser
from bob.application.usecases.relationship_sources import RelationshipTracker
from bob.application.usecases.run_genesis import RunGenesis
from bob.application.usecases.self_improvement_sources import ActiveRulesReader
from bob.application.usecases.sulk_sources import SulkRecoveryStep, SulkTracker
from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
from bob.domain.introspection.privacy_guard import PrivacyGuard
from bob.domain.personality.addressivity import AddressivityThresholds
from bob.domain.personality.brevity import BrevityThresholds
from bob.domain.personality.conversation import RepeatThresholds
from bob.domain.personality.conversation_floor import FloorConfig
from bob.domain.personality.disposition import DEFAULT_DISPOSITION, Disposition
from bob.domain.personality.engagement import EngagementThresholds, FatigueRates
from bob.domain.personality.expression import ExpressionFreqs
from bob.domain.personality.language import DEFAULT_LANGUAGE
from bob.domain.personality.mood import Mood
from bob.domain.personality.negotiation import Negotiation
from bob.domain.personality.phantom_evolution import CHANGE_RATE as _PHANTOM_RATE
from bob.domain.personality.phantom_evolution import MAX_PHANTOMS as _PHANTOM_MAX
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine
from bob.domain.personality.taste_evolution import ALPHA as _EVOLUTION_ALPHA
from bob.domain.personality.taste_evolution import BETA as _EVOLUTION_BETA
from bob.domain.personality.voice import OffDayThresholds
from bob.domain.personality.zone_classifier import TasteZoneClassifier
from bob.domain.proactivity.decision import ProactiveDecider
from bob.domain.proactivity.governance import Governance
from bob.infrastructure.config import ConfigLoader
from bob.infrastructure.introspection.subprocess_introspector import (
    SubprocessRepoIntrospector,
)
from bob.infrastructure.llm import build_embedder, build_reranker, build_tier_providers
from bob.infrastructure.persistence import (
    HybridMemoryRecall,
    KvAllowlistStore,
    RepoProactivitySources,
    SoulStore,
    SqliteConversationFloorStore,
    SqliteFascinationStore,
    SqliteFirstImpressionStore,
    SqliteGoalStore,
    SqliteMemoryRepo,
    SqliteProactivityStore,
    SqliteRelationshipStore,
    SqliteSelfImprovementStore,
    SqliteSulkStore,
)
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)

if TYPE_CHECKING:
    from aiogram.types import InputRichMessage, ReactionTypeEmoji

    from bob.application.runtime.agent import BackgroundTask
    from bob.application.usecases.handle_message import ReplyGateway
    from bob.application.usecases.run_genesis import GenesisResult
    from bob.domain.ports import (
        Clock,
        DomainEvent,
        Embedder,
        EventHandler,
        LLMProvider,
        MemoryRecall,
        Reranker,
        ToolCallingProvider,
    )
    from bob.infrastructure.telegram.gateway import (
        BotLike,
        BotUserLike,
        MessageLike,
        UpdateLike,
    )

logger = logging.getLogger(__name__)

# Default heartbeat cadence and gateway streaming knobs.
_DEFAULT_HEARTBEAT_SECONDS = 30
_DEFAULT_POLL_TIMEOUT = 10
_BATCH_TOKENS = 4
_THROTTLE_INTERVAL = 0.5
_MOOD_DRIFT_SECONDS = 60.0

# Production tick resilience: retry a tick's *transient* LLM/network blips with
# bounded exponential backoff (BEAD-04) before isolating whatever it ultimately
# raises, so a momentary hiccup never silently skips an idle tick.
_TICK_RETRY_POLICY = RetryPolicy()

# The reply tier (Tier 1) is the one whose provider drives the capability tool-loop.
_REPLY_TIER = 1

# Per-persona id for Bob's proactivity state (Bobiverse replicas each get their own).
_BOB_PERSONA = "bob"

# Self-improvement defaults (BOB-028 .3): the soft-tilt ceiling each APPROVED rule's
# magnitude is clamped to, and the cap on how many LIVE rules may accrue. Mirror the
# ``self_improvement.*`` config defaults; only matter when the master switch is on.
_DEFAULT_SI_MAX_MAGNITUDE = 0.3
_DEFAULT_SI_MAX_ACTIVE_RULES = 5

# Default vividness of a freshly-grounded fascination (BOB-020); it then decays with
# age. Overridable via ``emotion.fascination.initial_intensity``.
_DEFAULT_FASCINATION_INTENSITY = 0.85

# Default phantom-evolution bound + cadence (BOB-020 wave 3); overridable via
# ``emotion.phantom.{max_count,change_rate}``. Sourced from the pure kernel's constants
# so the domain and composition agree on the conservative defaults.
_PHANTOM_MAX_COUNT = _PHANTOM_MAX
_PHANTOM_CHANGE_RATE = _PHANTOM_RATE

# Default memory-consolidation guardrails (BOB-021); overridable via
# ``memory.consolidation.{max_age_days,batch_size}``. Conservative: only fold
# episodes at least two weeks old, a modest batch per rare reflect tick.
_CONSOLIDATION_MAX_AGE_DAYS = 14.0
_CONSOLIDATION_BATCH_SIZE = 50

# Default fact-dedup guardrails (BOB-021); overridable via
# ``memory.dedup.{threshold,batch_size}``. Conservative: a high cosine threshold so
# only true near-duplicates merge, a bounded batch per rare reflect tick.
_DEDUP_THRESHOLD = 0.92
_DEDUP_BATCH_SIZE = 200

# Default surface-old frequency (BOB-021 mechanism 1); overridable via
# ``memory.surface_old.freq``. Small (anti-tic): a callback turn only occasionally
# reaches for an OLD-but-relevant deep cut; the default recall stays unchanged.
_SURFACE_OLD_FREQ = 0.15

# Default good-exchange mood lift (BOB-014 .2a); overridable via ``engagement.mood_lift``.
# Small: a genuinely interesting, well-engaged exchange brightens Bob a touch — it
# accrues over a real exchange rather than jolting his mood.
_DEFAULT_ENGAGEMENT_MOOD_LIFT = 0.1

# Default char ceiling for the BOB-024 brevity length guard (mirrors HandleMessage's
# default). The guard is off by default; when on, an over-long reply to a LOW-demand
# message is lightly clamped to its first finished thought at this ceiling.
_DEFAULT_LENGTH_GUARD_MAX_CHARS = 280

# The proactivity engine ticks on the heartbeat cadence: cheap by construction
# (the urge/governance decision is pure, defaulting to silence), so most ticks
# make ZERO LLM calls.
_PROACTIVE_TICK_MULTIPLIER = 1

# Default cadence of the self-directed goal-pursuit tick (BOB-015 .3) when wired:
# rare (≈15 min) and under the governance ceiling; overridable via goals.tick_seconds.
_DEFAULT_PURSUIT_TICK_SECONDS = 900

# Default self-evolution learning rates (BOB-013 Фаза 2); overridable via
# personality.evolution.{alpha,beta}. Sourced from the pure kernel's constants.
EVOLUTION_ALPHA = _EVOLUTION_ALPHA
EVOLUTION_BETA = _EVOLUTION_BETA

# The repo root (``.../src/bob/app.py`` -> two parents up): the read-only tree Bob's
# self-introspection (BOB-017 Phase A) is rooted at, so the PrivacyGuard resolves
# ``src``/``tests``/``docs`` against it and DENIES everything else.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Where the bob-soul personality templates live (repo root / bob-soul).
_DEFAULT_TEMPLATES_DIR = _REPO_ROOT / "bob-soul"

# Default self-introspection resource bounds (BOB-017 Phase A); mirror the
# ``introspection.*`` config defaults. Only consulted when introspection is enabled.
_DEFAULT_INTROSPECTION_MAX_OUTPUT_CHARS = 20_000
_DEFAULT_INTROSPECTION_READ_MAX_LINES = 200


class SystemClock:
    """Real time source (UTC). Injected so the domain avoids ``datetime.now()``."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


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
    memory_repo: SqliteMemoryRepo
    soul_store: SoulStore
    genesis: RunGenesis
    personality: PersonalityState
    handle_message: HandleMessage
    multibot: MultiBotGateway
    authorizer: Authorizer
    registry: CapabilityRegistry
    inner_monologue_tick: InnerMonologueTick
    mood_drift_tick: MoodDriftTick
    reflect_tick: ReflectTick
    proactivity_store: SqliteProactivityStore
    proactivity_engine: ProactivityEngine
    proactive_tick: ProactiveTick
    # Self-directed goal-pursuit tick (BOB-015 .3): wired only when
    # ``goals.pursuit_enabled`` is on (conservative default off → runtime as before).
    pursue_goals_tick: PursueGoalsTick | None = None

    async def startup(self) -> GenesisResult:
        """Initialise persistence, awaken Bob on first boot, load his soul.

        Idempotent Genesis: the first boot generates the soul (Tier 1) and writes
        ``data/soul/``; every later boot loads the existing soul untouched. The
        loaded soul becomes the live :class:`PersonalityState`.
        """
        await self.memory_repo.initialize()
        result = await self.genesis.run()
        self.personality.soul = _load_soul(self.soul_store)
        # Resolve Bob's own bot identity (id + @username) so the addressivity scan
        # (BOB-023) can tell a mention of Bob from a mention of someone else.
        await self.multibot.resolve_bot_identities()
        return result

    async def shutdown(self) -> None:
        """Stop the runtime and close persistence (idempotent)."""
        await self.runtime.stop()
        await self.memory_repo.close()


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

    **Hybrid memory (BOB-011):** a local :class:`~bob.domain.ports.Embedder`
    (BGE-M3/Ollama) and an optional :class:`~bob.domain.ports.Reranker` are built
    from config (``embeddings.*`` / ``reranker.*``). The live recall is the
    :class:`~bob.infrastructure.persistence.HybridMemoryRecall` (FTS5 + sqlite-vec
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
    router = LLMRouter(providers=tier_providers)

    # Hybrid memory (BOB-011): the embedder + optional reranker are injectable
    # seams; when omitted they are built from config. Building them never touches
    # the network (only `embed()`/`rerank()` calls do), so the app starts even with
    # Ollama down — the embedder is then `None` (keyword-only) and the hybrid recall
    # degrades gracefully at call time.
    resolved_embedder = embedder if embedder is not None else _build_embedder(merged)
    resolved_reranker = reranker if reranker is not None else _build_reranker(merged)

    # The embedder is wired into the repo so the sqlite-vec table is backfilled with
    # existing memory on startup (initialize) and new facts/episodes are embedded on
    # write — a no-op when there is no embedder (keyword-only).
    memory_repo = SqliteMemoryRepo(_db_path(merged), embedder=resolved_embedder)
    recall = HybridMemoryRecall(memory_repo, resolved_embedder, reranker=resolved_reranker)
    soul_store = SoulStore(_soul_dir(merged))

    # Capability seam (BEAD-05/06): advertise recall_memory + the agentic
    # search_memory to the model so the production tool-loop is active — the model
    # may call either, GUPPI executes it, the result loops back into the reply. The
    # tier-1 reply provider is the tool-calling provider; when it cannot do tools the
    # loop stays dormant and HandleMessage keeps the plain reply path.
    registry = _build_registry(merged, recall=recall)
    tool_provider = _as_tool_provider(tier_providers)

    genesis = RunGenesis(
        templates_dir=_templates_dir(merged),
        router=router,
        soul_store=soul_store,
        clock=resolved_clock,
    )

    personality = PersonalityState(soul=_default_soul())
    update_mood = UpdateMoodFromText(router=router, clock=resolved_clock)
    extract_facts = ExtractFacts(router=router, repo=memory_repo, clock=resolved_clock)
    authorizer = _build_authorizer(merged, repo=memory_repo)

    # Proactivity (BOB-010 Ф1): the per-persona store backs both the engine and
    # GUPPI's /quiet,/wake; RecordOwnerActivity folds each owner message into the
    # drive-state. The store/clock are handed to GUPPI through the gateway.
    proactivity_store = SqliteProactivityStore(memory_repo)
    record_owner_activity = RecordOwnerActivity(
        store=proactivity_store, clock=resolved_clock, persona_id=_BOB_PERSONA
    )

    # Fascination (BOB-020 wave 2): the per-persona store backs both the evolution
    # step (on the reflect tick) and the compose-surfacing reader. The reader loads
    # + ages the stored passion and drops a faded one, so a spent fascination never
    # surfaces and the reply/proactive compose no-ops until evolution grounds a fresh one.
    fascination_store = SqliteFascinationStore(memory_repo)
    fascination_reader = StoreFascinationReader(
        persona_id=_BOB_PERSONA, store=fascination_store, clock=resolved_clock
    )

    # First impression (BOB-019 bob-apv.3): a LIGHT per-sender store backs the tracker
    # that recalls a returning person's prior impression into the compose prompt and
    # records a fresh, grounded note on first contact. Keyed by sender_id (owner /
    # known / guest / bot alike); per-PERSON data (about them), not owner memory, so it
    # is safe even on a guest turn. The minimal foundation for multi-party BOB-014.
    first_impression_store = SqliteFirstImpressionStore(memory_repo)
    first_impression_tracker = FirstImpressionTracker(
        store=first_impression_store, clock=resolved_clock
    )
    # Relationship-врезка (BOB-014): per-sender relationship quality (trust / respect
    # / warmth / compatibility) accrued over turns — it warms/cools Bob's tone and
    # nudges his willingness to compromise with a close person, then is updated after
    # each turn. Keyed by sender_id; per-PERSON data (about them), not owner memory.
    relationship_store = SqliteRelationshipStore(memory_repo)
    relationship_tracker = RelationshipTracker(store=relationship_store)
    # Conversation-floor store (BOB-025): the per-thread "talking turn" — who currently
    # holds the floor in Bob's topic — so an ambient message in a thread where Bob holds
    # a live floor reads as DIRECTED_TO_BOB (continuity). Wired into HandleMessage only
    # when addressivity.floor.enabled is true; disabled → exactly BOB-023.
    floor_enabled = _build_floor_enabled(merged)
    floor_store = SqliteConversationFloorStore(memory_repo) if floor_enabled else None
    # Sulk/обида store (BOB-014 .2b): the per-persona affect state — entered on a
    # SUSTAINED critical owner-drop / directed hostility, decaying to a GUARANTEED exit.
    # Carries NO memory and NO soul (anti-Exodus). The tracker is built AFTER multibot
    # so GUPPI can be its one-shot announcer.
    sulk_store = SqliteSulkStore(memory_repo)

    # Goal Engine (BOB-015): the per-persona goal store backs the Planner-driven
    # plan_goal use-case (double approval) and GUPPI's owner goal-commands. The
    # kill-switch (`/goals stop`) persists on the proactivity store, which the
    # self-directed tick (.3) will read. No tick is wired here — that is .3's job.
    goal_store, plan_goal = _build_goal_engine(merged, router=router, repo=memory_repo)

    # Self-improvement (BOB-028): the master switch (``self_improvement.enabled``, OFF by
    # default) gates the WHOLE feature. Off → ``rule_store`` is None, so GUPPI has no /rules
    # command and (below) HandleMessage applies no rule and the reflect tick runs no
    # detector/announcer — the runtime behaves EXACTLY as before BOB-028. The store is built
    # here (before multibot) because GUPPI needs it; the apply reader + reflect-tick seams,
    # which need Bob's gateway, are assembled just after multibot.
    si_enabled = _build_self_improvement_enabled(merged)
    rule_store = SqliteSelfImprovementStore(memory_repo) if si_enabled else None

    multibot = _build_multibot(
        merged,
        bus=event_bus,
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        authorizer=authorizer,
        proactivity_store=proactivity_store,
        proactivity_clock=resolved_clock,
        goal_store=goal_store,
        plan_goal=plan_goal,
        rule_store=rule_store,
        pursuit_store=proactivity_store,
    )
    # обида seam (BOB-014 .2b): GUPPI announces a fresh sulk entry once ("Боб обижен …")
    # — the внеличностный systemic voice. The tracker loads/evolves/recovers обида and
    # is read by HandleMessage (cold tone + owner-turn observation), the reflect tick
    # (guaranteed time-decay recovery), and the proactivity engine (the sulk veto).
    sulk_tracker = SulkTracker(
        store=sulk_store,
        persona_id=_BOB_PERSONA,
        announcer=multibot.guppi,
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
        perceive_sender=SenderPerception(authorizer=authorizer),
        # First-impression seam (BOB-019 bob-apv.3): Bob forms + remembers a LIGHT
        # per-person first impression keyed by sender — a returning person's prior
        # note is recalled into the prompt ("кажется, мы уже сталкивались"), a new
        # person's grounded note is recorded after the turn. Per-PERSON data, safe even
        # for a guest (about the guest, never an owner-memory leak). Additive only.
        first_impression=first_impression_tracker,
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
    )
    event_bus.subscribe(MESSAGE_RECEIVED, _as_handler(handle_message))

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
        recall=recall,
        clock=resolved_clock,
        seed=proactivity_seed,
        language=language,
        fascination=fascination_reader,
        sulk=sulk_tracker,
        # The SAME recall-aware anti-repeat thresholds the reactive turn uses (BOB-032 .2):
        # the proactive compose grounds on recalled whole-turn memories, so it gets the
        # same window / similarity bar to keep Bob from copying his OWN recalled past reply.
        repeat_thresholds=_build_repeat_thresholds(merged),
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

    return Application(
        config=merged,
        runtime=runtime,
        event_bus=event_bus,
        memory_repo=memory_repo,
        soul_store=soul_store,
        genesis=genesis,
        personality=personality,
        handle_message=handle_message,
        multibot=multibot,
        authorizer=authorizer,
        registry=registry,
        inner_monologue_tick=inner_monologue_tick,
        mood_drift_tick=mood_drift_tick,
        reflect_tick=reflect_tick,
        proactivity_store=proactivity_store,
        proactivity_engine=proactivity_engine,
        proactive_tick=proactive_tick,
        pursue_goals_tick=pursue_goals_tick,
    )


# --- Wiring helpers -----------------------------------------------------------


def _as_handler(handle_message: HandleMessage) -> EventHandler:
    """Adapt :meth:`HandleMessage.handle` to the EventBus handler signature."""

    async def handler(event: DomainEvent) -> None:
        if isinstance(event, MessageReceived):
            await handle_message.handle(event)

    return handler


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
        authorizer=authorizer,
        proactivity_store=proactivity_store,
        proactivity_clock=proactivity_clock,
        goal_store=goal_store,
        plan_goal=plan_goal,
        pursuit_store=pursuit_store,
        rule_store=rule_store,
    )


def _build_goal_engine(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    repo: SqliteMemoryRepo,
) -> tuple[SqliteGoalStore, PlanGoal]:
    """Assemble the Goal Engine store + plan use-case (BOB-015 .2).

    The per-persona :class:`SqliteGoalStore` round-trips Bob's goals; the
    :class:`LlmPlanner` decomposes an APPROVED goal via the Tier-1 router (strict
    JSON, ``needs_external_agency`` classification); :class:`PlanGoal` saves the tasks
    and shows the owner the plan, holding the goal at APPROVED until the plan is also
    approved (``goals.require_plan_approval``, default true — the double gate). No
    self-directed tick is wired here — that is .3's job.
    """
    store = SqliteGoalStore(repo)
    plan_goal = PlanGoal(
        planner=LlmPlanner(router=router),
        store=store,
        persona_id=_BOB_PERSONA,
        require_plan_approval=_build_require_plan_approval(config),
    )
    return store, plan_goal


@dataclass(frozen=True)
class _SelfImprovement:
    """The wired self-improvement pieces (BOB-028 .3), all None when the switch is off.

    ``reader`` is the apply-side seam HandleMessage reads (APPROVED-only soft tilts);
    ``detect_patterns`` + ``announce_rules`` are the reflect-tick seams; ``max_magnitude``
    is the soft-tilt ceiling. Off → ``reader`` / ``detect_patterns`` / ``announce_rules``
    are None and the magnitude is the default, so every consumer is a no-op.
    """

    reader: ActiveRulesReader | None
    detect_patterns: DetectPatterns | None
    announce_rules: AnnounceProposedRules | None
    max_magnitude: float


def _build_self_improvement_enabled(config: Mapping[str, object]) -> bool:
    """Whether self-improvement is wired (``self_improvement.enabled``, OFF default).

    The master switch: OFF (the conservative start of metacognition) → the whole feature
    is unwired, so behaviour is exactly as before BOB-028. Tolerates an env-string bool.
    """
    return _flag(_section(config, "self_improvement"), "enabled")


def _build_self_improvement(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    rule_store: SqliteSelfImprovementStore | None,
    gateway: ReplyGateway,
    chat_id: int,
    clock: Clock,
) -> _SelfImprovement:
    """Assemble the self-improvement apply + reflect-tick pieces, or no-ops (BOB-028 .3).

    Built ONLY when the master switch is on AND the rule store is wired: the
    :class:`ActiveRulesReader` (APPROVED-only soft tilts into HandleMessage), the
    :class:`DetectPatterns` reflect-tick seam (Tier-``detector_tier`` LLM detector →
    candidate PROPOSED rules, capped by ``max_active_rules``; it runs on empty signals
    for now — a signal-collection adapter is a later step), and the
    :class:`AnnounceProposedRules` reflect-tick seam (Bob tactfully voices ONE fresh
    proposal into his topic). Off / no store → every piece is None and the magnitude is
    the config ceiling, so the runtime behaves exactly as before BOB-028.
    """
    section = _section(config, "self_improvement")
    max_magnitude = _float_or(section, "max_magnitude", _DEFAULT_SI_MAX_MAGNITUDE)
    if rule_store is None:
        return _SelfImprovement(
            reader=None,
            detect_patterns=None,
            announce_rules=None,
            max_magnitude=max_magnitude,
        )
    detector = LlmPatternDetector(router=router, clock=clock)
    detect_patterns = DetectPatterns(
        detector=detector,
        store=rule_store,
        persona_id=_BOB_PERSONA,
        max_active_rules=_int(section, "max_active_rules", _DEFAULT_SI_MAX_ACTIVE_RULES),
    )
    announce_rules = AnnounceProposedRules(
        store=rule_store,
        gateway=gateway,
        chat_id=chat_id,
        persona_id=_BOB_PERSONA,
    )
    reader = ActiveRulesReader(store=rule_store, persona_id=_BOB_PERSONA)
    return _SelfImprovement(
        reader=reader,
        detect_patterns=detect_patterns,
        announce_rules=announce_rules,
        max_magnitude=max_magnitude,
    )


def _build_proactivity_engine(
    config: Mapping[str, object],
    *,
    store: SqliteProactivityStore,
    router: LLMRouter,
    gateway: ReplyGateway,
    personality: PersonalityState,
    repo: SqliteMemoryRepo,
    recall: MemoryRecall,
    clock: Clock,
    seed: int | None,
    language: str = DEFAULT_LANGUAGE,
    fascination: StoreFascinationReader | None = None,
    sulk: SulkTracker | None = None,
    repeat_thresholds: RepeatThresholds | None = None,
) -> ProactivityEngine:
    """Assemble the per-persona proactivity engine (drive-model → message).

    Wires the pure :class:`ProactiveDecider` (urge model + :class:`Governance`
    ceilings over the injected clock and a **seeded** RNG) to the live store, the
    LLM router (Tier-0 gate + composed reply), Bob's reply gateway (posts into his
    topic), and the live reflection-salience / proactive-window read-seams over the
    episodic log. The seed is injectable/deterministic: an explicit ``seed`` wins,
    else config (``runtime.proactivity_seed``) or the ``BOB_PROACTIVITY_SEED`` env,
    else a fresh per-process seed — so tests pin the stochastic draw exactly.
    """
    telegram = _section(config, "telegram")
    sources = RepoProactivitySources(repo, clock=clock)
    decider = ProactiveDecider(clock=clock, governance=Governance())
    return ProactivityEngine(
        persona_id=_BOB_PERSONA,
        chat_id=_int(telegram, "chat_id", 0),
        store=store,
        decider=decider,
        router=router,
        gateway=gateway,
        personality=personality,
        reflection=sources,
        window=sources,
        recall=recall,
        repo=repo,
        clock=clock,
        # The drive-model's stochastic draw is deterministic-by-seed, NOT
        # cryptographic: a seeded PRNG is exactly what makes the proactive decision
        # reproducible in tests.
        rng=random.Random(_resolve_seed(config, seed)),  # noqa: S311
        language=language,
        fascination=fascination,
        # The sulk veto (BOB-014 .2b): while обижен Bob does not write first.
        sulk=sulk,
        # Recall-aware anti-repeat on the proactive path (BOB-032 .2, R4).
        repeat_thresholds=repeat_thresholds,
    )


def _build_pursue_goals_tick(
    config: Mapping[str, object],
    *,
    goal_store: SqliteGoalStore,
    pursuit_store: SqliteProactivityStore,
    history: SqliteProactivityStore,
    registry: CapabilityRegistry,
    gateway: ReplyGateway,
    personality: PersonalityState,
    repo: SqliteMemoryRepo,
    clock: Clock,
    seed: int | None,
) -> PursueGoalsTick | None:
    """Assemble the self-directed goal-pursuit tick, or ``None`` when off (BOB-015 .3).

    Built ONLY when ``goals.pursuit_enabled`` is on (conservative default off): the
    self-directed tick is the most safety-critical path, so it stays unwired unless
    the owner deliberately enables it (unwired → the runtime behaves exactly as
    before). It reuses the SAME :class:`Governance` ceilings and the kill-switch the
    proactive chat uses (one config governs both reach-out paths), the Goal Engine
    store (only an APPROVED/ACTIVE goal is ever advanced), and a
    :class:`SafeCapabilityDispatcher` over the registry restricted to
    ``goals.safe_capabilities`` — the hard boundary that keeps an external-agency or
    arbitrary capability unreachable on the autonomous path. The window-count seam
    (over ``goal_progress`` episodes) enforces ``goals.max_tasks_per_window`` on top
    of governance. The seed is shared so the autonomous choice is reproducible.
    """
    if not _build_pursuit_enabled(config):
        return None
    telegram = _section(config, "telegram")
    sources = RepoProactivitySources(repo, clock=clock)
    dispatcher = SafeCapabilityDispatcher(
        registry, allowlist=_build_safe_capabilities(config)
    )
    return PursueGoalsTick(
        persona_id=_BOB_PERSONA,
        chat_id=_int(telegram, "chat_id", 0),
        goal_store=goal_store,
        pursuit_store=pursuit_store,
        governance=Governance(),
        history=history,
        window=sources,
        dispatcher=dispatcher,
        episodes=repo,
        gateway=gateway,
        personality=personality,
        clock=clock,
        # Deterministic-by-seed, NOT cryptographic: the same seed knob that pins the
        # proactive draw also pins which safe capability the tick picks.
        rng=random.Random(_resolve_seed(config, seed)),  # noqa: S311
        safe_capabilities=_build_safe_capabilities(config),
        max_tasks_per_window=_build_max_tasks_per_window(config),
    )


def _build_pursuit_enabled(config: Mapping[str, object]) -> bool:
    """Whether the self-directed goal-pursuit tick is wired (``goals.pursuit_enabled``).

    Off by default — the conservative start of autonomy-execution: the tick is the
    most safety-critical path, so it is scheduled ONLY when the owner explicitly
    switches it on. Tolerates an env-string boolean.
    """
    return _flag(_section(config, "goals"), "pursuit_enabled")


def _build_safe_capabilities(config: Mapping[str, object]) -> tuple[str, ...]:
    """The autonomous safe-allowlist (``goals.safe_capabilities``) as capability names.

    Only these capability names are runnable on the self-directed path; anything
    else (external-agency / arbitrary) is unreachable. An absent or empty list means
    the tick runs no capability at all (the conservative default).
    """
    section = _section(config, "goals")
    raw = section.get("safe_capabilities", [])
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(name) for name in raw if isinstance(name, str) and name)


def _build_max_tasks_per_window(config: Mapping[str, object]) -> int:
    """The per-window autonomous-advance ceiling (``goals.max_tasks_per_window``).

    A rate-limit ON TOP of the governance per-window ceiling — at most this many
    goal advances per window. Falls back to a conservative ``1`` when unset.
    """
    return _int(_section(config, "goals"), "max_tasks_per_window", 1)


def _fascination_initial_intensity(config: Mapping[str, object]) -> float:
    """Read the BOB-020 fresh-fascination intensity from ``emotion.fascination.*``.

    How vivid a freshly-grounded fascination starts (it then decays with age). Falls
    back to the :class:`EvolveFascination` default when absent; out-of-range values
    are clamped to ``[0, 1]`` by the use-case itself.
    """
    fascination = _section(_section(config, "emotion"), "fascination")
    return _float_or(fascination, "initial_intensity", _DEFAULT_FASCINATION_INTENSITY)


def _phantom_evolution_params(config: Mapping[str, object]) -> tuple[int, float]:
    """Read the BOB-020 phantom-evolution bound + cadence from ``emotion.phantom.*``.

    ``max_count`` caps how many phantom preferences Bob carries at once; ``change_rate``
    is the small per-step probability a grounded candidate actually emerges (keeping the
    drift slow). Both fall back to the kernel's conservative defaults when absent; an
    out-of-range ``change_rate`` is clamped to ``[0, 1]`` and a non-positive ``max_count``
    to at least 1, so misconfiguration cannot break the bound.
    """
    phantom = _section(_section(config, "emotion"), "phantom")
    max_count = max(1, _int(phantom, "max_count", _PHANTOM_MAX_COUNT))
    change_rate = min(1.0, max(0.0, _float_or(phantom, "change_rate", _PHANTOM_CHANGE_RATE)))
    return max_count, change_rate


def _build_consolidate_memory(
    config: Mapping[str, object],
    *,
    store: SqliteMemoryRepo,
    router: LLMRouter,
    clock: Clock,
    language: str,
) -> ConsolidateMemory | None:
    """Build the optional BOB-021 :class:`ConsolidateMemory`, or ``None`` when off.

    Reads ``memory.consolidation.*``: ``enabled`` (off by default — the step stays
    inert until deliberately switched on), ``max_age_days`` and ``batch_size`` (the
    conservative age/batch guardrails). When disabled, the reflect tick gets no
    consolidator and behaves exactly as before. ``SqliteMemoryRepo`` structurally
    satisfies the use-case's ``ConsolidationStore`` seam.
    """
    section = _section(_section(config, "memory"), "consolidation")
    if not _flag(section, "enabled"):
        return None
    return ConsolidateMemory(
        store=store,
        router=router,
        clock=clock,
        max_age_days=_float_or(section, "max_age_days", _CONSOLIDATION_MAX_AGE_DAYS),
        batch_size=_int(section, "batch_size", _CONSOLIDATION_BATCH_SIZE),
        language=language,
    )


def _build_dedup_facts(
    config: Mapping[str, object],
    *,
    store: SqliteMemoryRepo,
    embedder: Embedder | None,
    clock: Clock,
) -> DedupFacts | None:
    """Build the optional BOB-021 :class:`DedupFacts`, or ``None`` when off.

    Reads ``memory.dedup.*``: ``enabled`` (off by default — the step stays inert until
    deliberately switched on), ``threshold`` (the conservative cosine bar) and
    ``batch_size``. Returns ``None`` when disabled OR when there is no embedder
    (keyword-only memory cannot compute cosine), so the reflect tick gets no deduper and
    behaves exactly as before. ``SqliteMemoryRepo`` structurally satisfies the
    use-case's ``DedupStore`` seam.
    """
    section = _section(_section(config, "memory"), "dedup")
    if not _flag(section, "enabled") or embedder is None:
        return None
    return DedupFacts(
        store=store,
        embedder=embedder,
        clock=clock,
        threshold=_float_or(section, "threshold", _DEDUP_THRESHOLD),
        batch_size=_int(section, "batch_size", _DEDUP_BATCH_SIZE),
    )


def _flag(section: Mapping[str, object], key: str) -> bool:
    """Read a boolean config flag, tolerating env-string ``"true"``/``"false"``."""
    value = section.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _build_offday_thresholds(config: Mapping[str, object]) -> OffDayThresholds:
    """Build the BOB-020 off-day tone thresholds from config (low/negative defaults).

    Reads ``emotion.offday.{valence,arousal}`` — the mood floor below which Bob's
    tone shifts to the quieter, vulnerable, honest off-day band instead of forced
    warmth. Falls back to the dataclass defaults (which sit in the low/negative band,
    so a normal or good mood always keeps the warm tone) when a value is absent.
    """
    offday = _section(_section(config, "emotion"), "offday")
    defaults = OffDayThresholds()
    return OffDayThresholds(
        valence=_float_or(offday, "valence", defaults.valence),
        arousal=_float_or(offday, "arousal", defaults.arousal),
    )


def _build_expression_freqs(config: Mapping[str, object]) -> ExpressionFreqs:
    """Build the BOB-018 expression add-on frequencies from config (small defaults).

    Reads ``expression.freqs.{leak_inner_life,callback}`` — the small fractions of
    turns the rare add-on flags fire on (anti-tic). Falls back to the dataclass
    defaults when a value is absent. Out-of-range values are rejected by
    :class:`ExpressionFreqs` itself ([0, 1] probabilities).
    """
    freqs = _section(_section(config, "expression"), "freqs")
    defaults = ExpressionFreqs()
    # The fascination-surfacing frequency (BOB-020) can be set under either
    # ``expression.freqs.mention_fascination`` (alongside the other add-ons) or the
    # emotion-scoped ``emotion.fascination.mention_freq`` knob; the emotion knob wins
    # when present so all fascination tuning lives in one place.
    fascination = _section(_section(config, "emotion"), "fascination")
    mention = _float_or(
        freqs,
        "mention_fascination",
        _float_or(fascination, "mention_freq", defaults.mention_fascination),
    )
    return ExpressionFreqs(
        leak_inner_life=_float_or(freqs, "leak_inner_life", defaults.leak_inner_life),
        callback=_float_or(freqs, "callback", defaults.callback),
        mention_fascination=mention,
    )


def _build_engagement_thresholds(config: Mapping[str, object]) -> EngagementThresholds:
    """Build the BOB-014 .2a appetite thresholds from ``engagement.thresholds.*``.

    Tunes the appetite boundaries: ``interesting`` (the interest bar a topic clears even
    on a low mood), ``high_fatigue`` (the "наскучило" point), ``low_mood`` / ``bright_mood``
    (the mood bands raising the bar / unlocking banter), and ``playful_chance`` (how
    often a bright-mood engaged turn tips into playful banter). Each falls back to the
    dataclass default — which keeps a normal mood fully engaging on any non-trivial topic.
    """
    section = _section(_section(config, "engagement"), "thresholds")
    defaults = EngagementThresholds()
    return EngagementThresholds(
        interesting=_float_or(section, "interesting", defaults.interesting),
        high_fatigue=_float_or(section, "high_fatigue", defaults.high_fatigue),
        low_mood=_float_or(section, "low_mood", defaults.low_mood),
        bright_mood=_float_or(section, "bright_mood", defaults.bright_mood),
        playful_chance=_float_or(section, "playful_chance", defaults.playful_chance),
    )


def _build_addressivity_thresholds(
    config: Mapping[str, object],
) -> AddressivityThresholds:
    """Build the BOB-023 addressivity policy thresholds from ``addressivity.*``.

    Tunes how readily Bob takes a turn by who it is for: ``barge_in_interest`` (the
    HIGH interest bar to rarely cut into someone ELSE's exchange) and ``barge_in_freq``
    (the small seeded frequency of doing so); ``ambient_interest`` (the lower bar to
    join a general ambient turn when others are around) and ``ambient_barge_in_freq``
    (its — easier — frequency); ``react_chance`` (how often an ambient-with-others turn
    becomes a quiet like-reaction instead of full silence). Each falls back to the
    conservative dataclass default — so Bob almost never intrudes into a private 1:1.
    """
    section = _section(config, "addressivity")
    defaults = AddressivityThresholds()
    return AddressivityThresholds(
        barge_in_interest=_float_or(
            section, "barge_in_interest", defaults.barge_in_interest
        ),
        ambient_interest=_float_or(
            section, "ambient_interest", defaults.ambient_interest
        ),
        barge_in_freq=_float_or(section, "barge_in_freq", defaults.barge_in_freq),
        ambient_barge_in_freq=_float_or(
            section, "ambient_barge_in_freq", defaults.ambient_barge_in_freq
        ),
        react_chance=_float_or(section, "react_chance", defaults.react_chance),
    )


def _build_brevity_thresholds(config: Mapping[str, object]) -> BrevityThresholds:
    """Build the BOB-024 brevity verbosity thresholds from ``brevity.thresholds.*``.

    Tunes the verbosity decision: ``interest_upgrade`` (the high interest bar that can
    rarely upgrade a turn's length) at ``upgrade_freq`` (the small seeded chance);
    ``bad_mood`` / ``low_engagement`` (the mood/appetite points that pull length a step
    down); ``tilt_mood`` (the soft-mood point where a terse form_hint adds a downshift).
    Each falls back to the conservative dataclass default — so Bob rarely unfurls "from
    interest" and trims only on a clearly bad mood / thin appetite.
    """
    section = _section(_section(config, "brevity"), "thresholds")
    defaults = BrevityThresholds()
    return BrevityThresholds(
        interest_upgrade=_float_or(
            section, "interest_upgrade", defaults.interest_upgrade
        ),
        upgrade_freq=_float_or(section, "upgrade_freq", defaults.upgrade_freq),
        bad_mood=_float_or(section, "bad_mood", defaults.bad_mood),
        low_engagement=_float_or(section, "low_engagement", defaults.low_engagement),
        tilt_mood=_float_or(section, "tilt_mood", defaults.tilt_mood),
    )


def _build_repeat_thresholds(config: Mapping[str, object]) -> RepeatThresholds:
    """Build the BOB-026 .1 anti-repeat window thresholds from ``repeat.*``.

    Tunes the own-reply guard: ``window`` (how many of Bob's recent replies the fresh
    reply is compared against — not just the last, so a repeat "через ход" is caught)
    and ``similarity_threshold`` (the conservative near-verbatim bar, so a merely
    topically-similar but substantively different reply never false-fires a needless
    regeneration). Each falls back to the conservative dataclass default.
    """
    section = _section(config, "repeat")
    defaults = RepeatThresholds()
    return RepeatThresholds(
        window=_int(section, "window", defaults.window),
        similarity_threshold=_float_or(
            section, "similarity_threshold", defaults.similarity_threshold
        ),
    )


def _build_floor_enabled(config: Mapping[str, object]) -> bool:
    """Whether the BOB-025 conversation floor is on (``addressivity.floor.enabled``).

    On by default (the floor is the BOB-025 mechanism); when off, no floor store is
    wired and the effective addressivity is the per-message classification, so
    behaviour is exactly BOB-023. Tolerates an env-string ``"true"``/``"false"``.
    """
    section = _section(_section(config, "addressivity"), "floor")
    value = section.get("enabled", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _build_floor_config(config: Mapping[str, object]) -> FloorConfig:
    """Build the BOB-025 conversation-floor config from ``addressivity.floor.*``.

    Tunes the floor's life and decay: ``timeout_seconds`` (how long Bob's floor lives
    without re-confirmation — ~5 min) and ``reset_after_silent`` (how many silent
    ambient turns collapse Bob's floor to idle). Each falls back to the conservative
    dataclass default; the domain validates both are positive.
    """
    section = _section(_section(config, "addressivity"), "floor")
    defaults = FloorConfig()
    return FloorConfig(
        timeout_seconds=_int(section, "timeout_seconds", defaults.timeout_seconds),
        reset_after_silent=_int(
            section, "reset_after_silent", defaults.reset_after_silent
        ),
    )


def _build_require_plan_approval(config: Mapping[str, object]) -> bool:
    """Whether the Goal Engine DOUBLE gate is on (``goals.require_plan_approval``).

    Default ``True`` (conservative at the start of autonomy): after the owner
    approves a goal, the decomposed plan must ALSO be approved before the goal goes
    ACTIVE. Only an explicit falsy value (``false``/``0``/``no``/``off``) drops to
    the single-gate flow. Tolerates an env-string boolean.
    """
    section = _section(config, "goals")
    value = section.get("require_plan_approval", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _build_length_guard_enabled(config: Mapping[str, object]) -> bool:
    """Whether the BOB-024 brevity length guard is on (``brevity.length_guard.enabled``).

    Off by default (the bayes — directive + few-shot — is the mechanism); when on, an
    over-long reply to a LOW-demand message is lightly clamped to its first finished
    thought (no regeneration). Tolerates an env-string ``"true"``/``"false"``.
    """
    section = _section(_section(config, "brevity"), "length_guard")
    return _flag(section, "enabled")


def _build_length_guard_max_chars(config: Mapping[str, object]) -> int:
    """The BOB-024 length-guard char ceiling (``brevity.length_guard.max_chars``).

    The threshold above which a LOW-demand reply is clamped to its first finished
    thought when the guard is enabled. Falls back to the conservative default;
    HandleMessage validates it is positive.
    """
    section = _section(_section(config, "brevity"), "length_guard")
    return _int(section, "max_chars", _DEFAULT_LENGTH_GUARD_MAX_CHARS)


def _build_fatigue_rates(config: Mapping[str, object]) -> FatigueRates:
    """Build the BOB-014 .2a conversational-fatigue dynamics from ``engagement.fatigue.*``.

    Tunes the bounded reservoir: ``decay_per_second`` (the recovery guarantee — fatigue
    always unwinds with time, so the owner is never permanently locked out),
    ``aimless_rise`` (how much one aimless turn tires Bob) and ``interest_ease`` (how much
    an interesting turn restores). Each falls back to the dataclass default.
    """
    section = _section(_section(config, "engagement"), "fatigue")
    defaults = FatigueRates()
    return FatigueRates(
        decay_per_second=_float_or(section, "decay_per_second", defaults.decay_per_second),
        aimless_rise=_float_or(section, "aimless_rise", defaults.aimless_rise),
        interest_ease=_float_or(section, "interest_ease", defaults.interest_ease),
    )


def _build_engagement_mood_lift(config: Mapping[str, object]) -> float:
    """Resolve the BOB-014 .2a good-exchange mood lift from ``engagement.mood_lift``.

    The small mood-valence bump a good, interesting exchange earns (scenario 4's
    feedback). Falls back to the small default; HandleMessage validates it is a [0, 1]
    amount.
    """
    section = _section(config, "engagement")
    return _float_or(section, "mood_lift", _DEFAULT_ENGAGEMENT_MOOD_LIFT)


def _build_surface_old_freq(config: Mapping[str, object]) -> float:
    """Resolve the BOB-021 surface-old frequency from config (small default).

    Reads ``memory.surface_old.freq`` — how often a (rare) callback turn reaches for
    an OLD-but-relevant memory via recall's additive opt-in ("что-то напомнило").
    Falls back to the small anti-tic default when absent; the default recall path is
    unchanged regardless (surface_old only ever rides the callback). HandleMessage
    validates the value is a [0, 1] probability.
    """
    section = _section(_section(config, "memory"), "surface_old")
    return _float_or(section, "freq", _SURFACE_OLD_FREQ)


def _resolve_seed(config: Mapping[str, object], seed: int | None) -> int:
    """Resolve the proactivity RNG seed: arg → config → env → fresh per-process."""
    if seed is not None:
        return seed
    configured = _int(_section(config, "runtime"), "proactivity_seed", -1)
    if configured >= 0:
        return configured
    env = os.environ.get("BOB_PROACTIVITY_SEED")
    if env is not None and env.isdigit():
        return int(env)
    return random.SystemRandom().randrange(2**32)


def _build_authorizer(
    config: Mapping[str, object], *, repo: SqliteMemoryRepo
) -> Authorizer:
    """Build the access-policy Authorizer from config over the SQLite allowlist.

    ``owner_id`` and ``allowed_chat_ids`` come from the ``telegram`` config; the
    dynamic allowlist is persisted in the kv store so ``/authorize`` survives a
    restart.
    """
    telegram = _section(config, "telegram")
    return Authorizer(
        owner_id=_int(telegram, "owner_id", 0),
        allowed_chat_ids=_int_list(telegram, "allowed_chat_ids"),
        store=KvAllowlistStore(repo),
    )


def _build_registry(
    config: Mapping[str, object], *, recall: HybridMemoryRecall
) -> CapabilityRegistry:
    """Build the capability registry GUPPI advertises and dispatches.

    Always registers the two memory capabilities over the live hybrid
    :class:`~bob.domain.ports.MemoryRecall`: ``recall_memory`` (the thin auto-recall
    wrapper) and ``search_memory`` (BOB-011 — the agentic skill Bob chooses to
    invoke through the tool-loop). When ``introspection.enabled`` (BOB-017 Phase A,
    default on) the three read-only self-introspection skills
    (``inspect_architecture`` / ``read_code`` / ``list_work``) are ALSO registered,
    over a :class:`SubprocessRepoIntrospector` guarded by the pure
    :class:`PrivacyGuard` — so Bob can answer about his own world. They are
    conversation-only (NOT added to ``goals.safe_capabilities``). Disabled → the
    registry holds exactly the memory capabilities, behaviour as before. New skills
    register here without touching consumers.
    """
    registry = CapabilityRegistry()
    registry.register(make_recall_memory_capability(recall))
    registry.register(make_search_memory_capability(recall))
    if _build_introspection_enabled(config):
        introspector = _build_introspector(config)
        read_max_lines = _int(
            _section(config, "introspection"),
            "read_max_lines",
            _DEFAULT_INTROSPECTION_READ_MAX_LINES,
        )
        registry.register(make_inspect_architecture_capability(introspector))
        registry.register(make_read_code_capability(introspector, read_max_lines=read_max_lines))
        registry.register(make_list_work_capability(introspector))
    return registry


def _build_introspection_enabled(config: Mapping[str, object]) -> bool:
    """Whether read-only self-introspection is wired (``introspection.enabled``).

    Default ON (BOB-017 Phase A — read-only, owner-only chat): on → the three
    self-introspection skills are advertised; off → the registry holds only the
    memory capabilities, exactly as before. Tolerates an env-string boolean.
    """
    return _flag(_section(config, "introspection"), "enabled")


def _build_introspector(config: Mapping[str, object]) -> SubprocessRepoIntrospector:
    """Construct the read-only :class:`SubprocessRepoIntrospector` for BOB-017.

    The pure :class:`PrivacyGuard` (rooted at the repo) enforces the DENY-invariant
    BEFORE any file read; the subprocess adapter runs ``beadloom`` / ``bd`` against a
    FIXED read-only allowlist (never a shell). Output bounds + the CLI binaries are
    config-tunable via ``introspection.*``.
    """
    section = _section(config, "introspection")
    return SubprocessRepoIntrospector(
        PrivacyGuard(repo_root=_REPO_ROOT),
        max_output_chars=_int(
            section, "max_output_chars", _DEFAULT_INTROSPECTION_MAX_OUTPUT_CHARS
        ),
        beadloom_bin=_str(section, "beadloom_bin", "beadloom"),
        bd_bin=_str(section, "bd_bin", "bd"),
    )


def _build_embedder(config: Mapping[str, object]) -> Embedder | None:
    """Build the local :class:`Embedder` from ``embeddings.*``, or ``None``.

    Graceful degradation: a missing/invalid ``embeddings`` section is logged and
    yields ``None`` (keyword-only recall) rather than failing the whole boot —
    building the embedder never touches the network, so this only guards config
    shape. An embedder that later fails at runtime (Ollama down) is handled inside
    the hybrid recall, not here.
    """
    try:
        return build_embedder(config)
    except (KeyError, ValueError) as error:
        logger.warning(
            "embeddings not configured (%s); memory recall degrades to keyword-only",
            error,
        )
        return None


def _build_reranker(config: Mapping[str, object]) -> Reranker | None:
    """Build the optional :class:`Reranker` from ``reranker.*``, or ``None``.

    The reranker is an ADDITIVE boost: it is off by default (``reranker.enabled``
    false) and a missing/invalid section degrades to ``None`` (the hybrid order
    ships unchanged) rather than failing the boot.
    """
    try:
        return build_reranker(config)
    except (KeyError, ValueError) as error:
        logger.warning("reranker not configured (%s); using hybrid order", error)
        return None


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


def _build_real_bot(bot_section: Mapping[str, object], identity: str) -> BotLike:
    """Construct a real aiogram ``Bot`` from a bot's configured (env) token.

    ``identity`` (``"bob"`` / ``"guppi"``) only names the missing token in the
    error — the token itself comes from env (``BOB_TELEGRAM__TOKEN`` /
    ``GUPPI_TELEGRAM__TOKEN``), never inlined.
    """
    from aiogram import Bot  # noqa: PLC0415 — lazy: only the real-bot path needs aiogram

    token = bot_section.get("token")
    if not isinstance(token, str) or not token:
        raise KeyError(
            f"telegram.{identity}.token is required to build the real {identity} bot"
        )
    return _AiogramBotAdapter(Bot(token=token))


def _background_tasks(
    config: Mapping[str, object],
    *,
    multibot: MultiBotGateway,
    inner_monologue_tick: InnerMonologueTick,
    mood_drift_tick: MoodDriftTick,
    reflect_tick: ReflectTick,
    proactive_tick: ProactiveTick,
    pursue_goals_tick: PursueGoalsTick | None = None,
) -> list[BackgroundTask]:
    """Build the supervised background tasks: polling + the heartbeat ticks.

    One poll task drives BOTH bots (Bob + GUPPI) through the multi-bot gateway. The
    proactivity tick runs on the heartbeat cadence like its siblings and is wrapped
    in the same :data:`_TICK_RETRY_POLICY` so a transient LLM/network blip on a
    firing tick is retried before isolation — it is cheap by construction (most
    ticks make ZERO LLM calls). The self-directed goal-pursuit tick (BOB-015 .3) is
    scheduled ONLY when wired (``goals.pursuit_enabled``), on its own (rare) cadence
    ``goals.tick_seconds``; unwired (the default) the schedule is exactly as before.
    """
    runtime = _section(config, "runtime")
    heartbeat = float(_int(runtime, "heartbeat_seconds", _DEFAULT_HEARTBEAT_SECONDS))

    async def poll() -> None:
        await multibot.poll_once()

    tasks: list[BackgroundTask] = [
        periodic(poll, interval_seconds=0.0),
        periodic(
            inner_monologue_tick.run,
            interval_seconds=heartbeat,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            mood_drift_tick.run,
            interval_seconds=_MOOD_DRIFT_SECONDS,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            reflect_tick.run,
            interval_seconds=heartbeat * 10,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            proactive_tick.run,
            interval_seconds=heartbeat * _PROACTIVE_TICK_MULTIPLIER,
            retry=_TICK_RETRY_POLICY,
        ),
    ]
    if pursue_goals_tick is not None:
        tasks.append(
            periodic(
                pursue_goals_tick.run,
                interval_seconds=_build_pursuit_tick_seconds(config),
                retry=_TICK_RETRY_POLICY,
            )
        )
    return tasks


def _build_pursuit_tick_seconds(config: Mapping[str, object]) -> float:
    """The self-directed pursuit cadence (``goals.tick_seconds``), in seconds.

    A rare cadence (the default is 900s ≈ 15 min) under the governance ceiling.
    Falls back to that conservative default when unset.
    """
    return float(_int(_section(config, "goals"), "tick_seconds", _DEFAULT_PURSUIT_TICK_SECONDS))


def _monotonic() -> float:
    return asyncio.get_event_loop().time()


# --- Soul loading -------------------------------------------------------------


def _load_soul(soul_store: SoulStore) -> SOUL:
    """Build the in-memory :class:`SOUL` from the persisted soul artifacts.

    Falls back to a neutral default if the JSON profiles are absent (a fresh
    install before Genesis has fully written them).
    """
    if not soul_store.soul_exists():
        return _default_soul()
    identity = soul_store.read_soul()
    mood_doc = soul_store.read_json("mood")
    baseline = _mood_from(mood_doc, "baseline")
    current = _mood_from(mood_doc, "current")
    taste = _taste_from(soul_store.read_json("taste_profile"))
    phantoms = _phantoms_from(soul_store.read_json("phantom_prefs"))
    disposition = _disposition_from(soul_store.read_json("disposition"))
    return SOUL(
        identity=identity,
        mood=current,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=phantoms,
        disposition=disposition,
    )


def _default_soul() -> SOUL:
    """A neutral starting soul used before Genesis has run."""
    neutral = Mood()
    return SOUL(
        identity="I am Bob, awaiting Genesis.",
        mood=neutral,
        mood_baseline=neutral,
        taste=TasteEngine(),
    )


def _mood_from(doc: object, key: str) -> Mood:
    if not isinstance(doc, Mapping):
        return Mood()
    section = doc.get(key)
    if not isinstance(section, Mapping):
        return Mood()
    return Mood(
        valence=_float(section, "valence"),
        arousal=_float(section, "arousal"),
        openness=_float(section, "openness"),
        social=_float(section, "social"),
        stability=_float(section, "stability"),
    )


def _taste_from(doc: object) -> TasteEngine:
    if not isinstance(doc, Mapping):
        return TasteEngine()
    axes_doc = doc.get("axes")
    if not isinstance(axes_doc, list):
        return TasteEngine()
    axes: list[TasteAxis] = []
    for raw in axes_doc:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        if not isinstance(name, str):
            continue
        axes.append(
            TasteAxis(
                name=name,
                value=_float(raw, "value"),
                conviction=_float(raw, "conviction"),
                experience_count=_int(raw, "experience_count", 0),
            )
        )
    return TasteEngine(axes=tuple(axes))


def _phantoms_from(doc: object) -> tuple[str, ...]:
    if not isinstance(doc, Mapping):
        return ()
    prefs = doc.get("preferences")
    if not isinstance(prefs, list):
        return ()
    return tuple(str(p) for p in prefs)


def _disposition_from(doc: object) -> Disposition:
    """Build Bob's :class:`Disposition`, falling back to canon per missing field.

    An absent or malformed ``disposition.json`` (an existing install predating
    BOB-033) yields the canon-optimist default, so every install Just Works.
    """
    if not isinstance(doc, Mapping):
        return DEFAULT_DISPOSITION
    return Disposition(
        optimism=_float_or(doc, "optimism", DEFAULT_DISPOSITION.optimism),
        resilience=_float_or(doc, "resilience", DEFAULT_DISPOSITION.resilience),
    )


# --- Config readers -----------------------------------------------------------


def _db_path(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "db_path", "data/bob.db"))


def _soul_dir(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "soul_dir", "data/soul"))


def _templates_dir(config: Mapping[str, object]) -> Path:
    genesis = _section(config, "genesis")
    configured = genesis.get("templates_dir")
    if isinstance(configured, str) and configured:
        return Path(configured)
    return _DEFAULT_TEMPLATES_DIR


def _section(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _str(section: Mapping[str, object], key: str, default: str) -> str:
    value = section.get(key)
    return value if isinstance(value, str) and value else default


def _int(section: Mapping[str, object], key: str, default: int) -> int:
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _int_list(section: Mapping[str, object], key: str) -> tuple[int, ...]:
    """Read a list of ints from config (YAML list or a CSV env string)."""
    value = section.get(key)
    if isinstance(value, str):
        return tuple(int(part) for part in value.split(",") if part.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(int(item) for item in value if isinstance(item, int))
    return ()


def _float(section: Mapping[str, object], key: str) -> float:
    value = section.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _float_or(section: Mapping[str, object], key: str, default: float) -> float:
    """Read a float from config, falling back to ``default`` when absent/invalid."""
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


# --- aiogram bot adapter ------------------------------------------------------


@dataclass(frozen=True)
class _ChatView:
    """An :class:`UpdateLike` chat view over an aiogram ``Update``."""

    id: int


@dataclass(frozen=True)
class _UserView:
    """An :class:`UpdateLike` user view over an aiogram ``Update``."""

    id: int
    full_name: str


@dataclass(frozen=True)
class _UpdateView:
    """Adapt an aiogram ``Update`` to the gateway's :class:`UpdateLike`.

    aiogram nests chat/sender under ``message``; the gateway reads them as the
    flat ``effective_chat`` / ``effective_user`` accessors, so this view lifts them
    up while leaving the underlying aiogram message as the message.
    """

    update_id: int
    message: MessageLike | None
    effective_chat: _ChatView | None
    effective_user: _UserView | None


class _AiogramBotAdapter:
    """Adapt aiogram's async ``Bot`` to the gateway's :class:`BotLike`.

    Intake calls ``get_updates`` and normalises each aiogram ``Update`` into an
    :class:`UpdateLike`; the reply path (BOB-008, Variant A) shows a "typing…"
    indicator via ``send_chat_action`` while it assembles the reply, then commits
    the finished reply with ``send_rich_message`` (degrading to ``send_message`` on
    a rich error).
    """

    def __init__(self, bot: object) -> None:
        self._bot = bot

    async def get_me(self) -> BotUserLike:
        # Bob's own bot identity (id + @username), resolved once at startup so the
        # addressivity scan (BOB-023) can tell a mention of Bob from one of others.
        return await self._bot.get_me()  # type: ignore[attr-defined,no-any-return]

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]:
        updates = await self._bot.get_updates(offset=offset, timeout=timeout)  # type: ignore[attr-defined]
        return [_to_update_view(update) for update in updates]

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike:
        return await self._bot.send_message(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, text=text, message_thread_id=message_thread_id
        )

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        return await self._bot.send_chat_action(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, action=action, message_thread_id=message_thread_id
        )

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        return await self._bot.send_rich_message(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id,
            rich_message=rich_message,
            message_thread_id=message_thread_id,
        )

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: Sequence[ReactionTypeEmoji],
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # Telegram's ``setMessageReaction`` targets the message directly (no thread
        # arg); ``message_thread_id`` is accepted for BotLike parity and dropped.
        return await self._bot.set_message_reaction(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, message_id=message_id, reaction=list(reaction)
        )


def _to_update_view(update: object) -> _UpdateView:
    """Lift an aiogram ``Update``'s nested chat/sender into an :class:`UpdateLike`."""
    message: MessageLike | None = getattr(update, "message", None)
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    return _UpdateView(
        update_id=update.update_id,  # type: ignore[attr-defined]
        message=message,
        effective_chat=_ChatView(id=chat.id) if chat is not None else None,
        effective_user=(
            _UserView(id=user.id, full_name=user.full_name) if user is not None else None
        ),
    )


# --- Entrypoint ---------------------------------------------------------------


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(app: Application) -> None:
    await app.startup()
    await app.runtime.start()
    try:
        await app.runtime.run_until_stopped()
    finally:
        await app.shutdown()


def main(*, config_path: Path | None = None) -> None:
    """Process entrypoint: build the application and run until stopped."""
    app = build_application(config_path=config_path)
    runtime_cfg = _section(app.config, "runtime")
    _configure_logging(_str(runtime_cfg, "log_level", "INFO"))
    logger.info("Bob GUPPI starting")
    asyncio.run(_run(app))


if __name__ == "__main__":
    main()
