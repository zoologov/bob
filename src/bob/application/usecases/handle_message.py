# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""HandleMessage — the full message→reply→persist flow (GUPPI's act loop).

Subscribed to :class:`~bob.application.runtime.events.MessageReceived`, this
use-case runs Bob's perceive→decide→act turn (RFC §"Поток обработки"):

1. **Perceive** — :class:`UpdateMoodFromText` (Tier 0 sentiment + signals) updates
   the in-memory mood; the new mood is held on :class:`PersonalityState`.
2. **Decide** — replay recent conversation history (:class:`EpisodeReader`),
   recall relevant memory (:class:`MemoryRecall`, FTS5) and assemble the context.
   Following Variant 2 (selective redaction), the reply-shaping material
   (recent history, recalled memory, mood tone, identity, taste verdict, phantom
   prefs) is handed to the :class:`LLMRouter` as ``shareable_context`` — it MAY
   accompany the Tier 1 reply because it shapes Bob's reply and returns to that
   same user. Genuinely-internal material would go in ``private_context``
   (Tier-0-only); in P0.1 that channel is empty but the seam is kept (VISION §7.1).
3. **Act** — the router replies on ``TaskType.REPLY_TO_USER`` (Tier 1 + redaction,
   fallback Tier 0). The slow generation runs INSIDE the gateway's
   ``typing_indicator`` so "Bob is typing…" stays visible for the whole wait
   (BOB-009); the finished reply is then committed once via the gateway's rich
   ``reply`` and the turn is persisted (episode + mood snapshot) via the
   :class:`MemoryRepo`.
4. **Remember** — after the reply, :class:`ExtractFacts` (Tier 0) distils durable,
   user-specific facts into ``semantic_memory`` so a later turn's
   :class:`MemoryRecall` can surface them. Best-effort: it never raises, so a
   flaky local model cannot break a turn that has already replied.

This layer only orchestrates: tone/verdict come from the pure domain, transport
and storage live behind ports, and time is injected via :class:`Clock`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.application.router.reply_tier_selector import select_reply_tier
from bob.application.usecases.essential_runner import (
    EssentialRunner,
    OutageNotifier,
    _EssentialStepError,
)
from bob.application.usecases.precompose_gate import (
    InteractiveRouterLike,
    NaturalCodingRouter,
    PermissionFlowLike,
    PreComposeGate,
)
from bob.application.usecases.reply_rhythm import reply_delay_inputs
from bob.capabilities.usecases.delivery_scope import (
    DeliveryScope,
    armed_delivery_scope,
)
from bob.capabilities.usecases.diagram_sender import (
    _DEFAULT_DIAGRAM_SEND_AS,
    DiagramSender,
    DiagramSendMode,
)
from bob.capabilities.usecases.progress_announcer import GatewayProgressAnnouncer
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.capabilities.usecases.turn_material import (
    MaterialOrigin,
    armed_turn_material,
    current_turn_material,
)
from bob.conversation.addressivity import (
    Addressivity,
    AddressivityThresholds,
    ResponseOutcome,
    others_present,
)
from bob.conversation.brevity import (
    AnswerDemand,
    BrevityThresholds,
    classify_answer_demand,
)
from bob.conversation.conversation import (
    RepeatThresholds,
    is_user_repeat,
    recalled_bob_replies,
    recalled_bob_reply,
    recalled_excluding_reflections,
    recalled_without_copied_exemplars,
)
from bob.conversation.conversation_floor import FloorConfig
from bob.conversation.engagement import (
    ConversationalFatigue,
    EngagementThresholds,
    FatigueRates,
)
from bob.conversation.outgoing_target import OutgoingTarget, resolve_outgoing_target
from bob.conversation.reply_context import _assemble_shareable_context
from bob.conversation.thread import (
    _author_key,
    _history_for_author,  # noqa: F401  # re-exported for tests (used by RecallAssembler)
    _last_seen_at,  # noqa: F401  # re-exported for tests (used by RecallAssembler)
    _recent_bob_replies,  # noqa: F401  # re-exported for tests (used by AntiRepeatGuard)
    _render_thread,
    _user_turns,
)
from bob.conversation.usecases.addressivity_perceiver import AddressivityPerceiver
from bob.conversation.usecases.anti_repeat_guard import (
    _CLOSER_TIC_NUDGE,  # noqa: F401  # re-exported for tests (moved to AntiRepeatGuard)
    AntiRepeatGuard,
)
from bob.conversation.usecases.engagement_model import EngagementModel
from bob.conversation.usecases.floor_manager import FloorManager
from bob.conversation.usecases.recall_assembler import RecallAssembler
from bob.conversation.usecases.turn_gate import TurnGate
from bob.conversation.usecases.verify_step import (
    _VERIFY_GROUNDED_NOTE,  # noqa: F401  # re-exported for tests (moved to VerifyStep)
    _VERIFY_HEDGE_NOTE,  # noqa: F401  # re-exported for tests (moved to VerifyStep)
    VerifyStep,
)
from bob.conversation.zone_classifier import TasteZoneClassifier
from bob.memory.entities import EpisodicEvent
from bob.memory.register_pipeline import pool_has_work, register_ranked
from bob.personality.expression import (
    EngagementLevel,
    ExpressionFreqs,
    ExpressionPlan,
    Verbosity,
    _shift_verbosity,
)
from bob.personality.negotiation import (
    Negotiation,
    Stance,
)
from bob.personality.reaction import reaction_emoji_for
from bob.personality.soul import _mood_state
from bob.personality.usecases.grounded_addons import GroundedAddons
from bob.personality.usecases.mood_perceiver import MoodPerceiver
from bob.personality.usecases.voice_composer import VoiceComposer
from bob.personality.voice import (
    OffDayThresholds,
    RelationshipToneThresholds,
)
from bob.presence.staleness import StalenessOutcome
from bob.proactivity.self_improvement import (
    RuleModulators,
    _validated_magnitude,
    build_modulators,
)
from bob.social.disclosure import filter_surfaceable, visibility_for_scope
from bob.social.interlocutor import InterlocutorKind, Trust
from bob.social.usecases.social_context import SocialContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime
    from random import Random

    from bob.application.reliability import Sleep
    from bob.application.router.llm_router import LLMRouter
    from bob.application.router.voice_canon import VoiceCanon
    from bob.application.runtime.events import MessageReceived
    from bob.application.runtime.intake.scope import TurnScope
    from bob.application.runtime.staleness_reassessor import StalenessReassessor
    from bob.application.usecases.disclosure_consent_gate import DisclosureConsentGate
    from bob.application.usecases.disclosure_guard import DisclosureGuard
    from bob.application.usecases.endorsement_seeder import EndorsementSeeder
    from bob.application.usecases.room_mood_modulator import RoomMoodModulator
    from bob.capabilities.ports import (
        DiagramRenderer,
        DiagramSink,
        ToolCallingProvider,
        WebSearchProvider,
    )
    from bob.capabilities.usecases.progress_announcer import (
        InterimLineGenerator,
        ProgressAnnouncer,
    )
    from bob.conversation.ports import CloserLog, ConversationFloorStore, ZoneClassifier
    from bob.conversation.room_reading import RoomMood
    from bob.conversation.usecases.addressivity_perceiver import _AddressivityDecision
    from bob.conversation.usecases.decide_response import DecideResponse
    from bob.conversation.usecases.read_the_room import ReadTheRoom
    from bob.conversation.volatility_judgment import VolatilityJudge
    from bob.kernel.ports import Clock
    from bob.memory.ports import MemoryRecall, Recalled, SelfActionRecorder
    from bob.memory.usecases.extract_facts import ExtractFacts
    from bob.memory.usecases.resolve_register import RegisterResolver
    from bob.personality.fascination import Fascination
    from bob.personality.mood import Mood
    from bob.personality.ports import MessageReactor, NotableReactionStore, ReflectionReader
    from bob.personality.soul import SOUL
    from bob.personality.usecases.update_mood_from_text import UpdateMoodFromText
    from bob.proactivity.self_improvement import ImprovementRule
    from bob.social.interlocutor import Interlocutor
    from bob.social.relationship import Relationship
    from bob.social.roster import RosterMember
    from bob.social.sulk import SulkState

logger = logging.getLogger(__name__)

# Reliability defaults (BOB-049 .3 — «полный Боб или честный GUPPI-нотис»). An ESSENTIAL
# LLM step (the semantic judgment, the reply generation) is retried a bounded number of
# times before Bob falls back to the honest outage notice — never a degraded half-answer.
# ``_DEFAULT_ESSENTIAL_ATTEMPTS`` is the TOTAL number of tries (one initial call + two
# retries); the short backoff is awaited through an injected sleep seam (deterministic in
# tests). Both tunable per persona via ``reliability.*``.
_DEFAULT_ESSENTIAL_ATTEMPTS = 3
_DEFAULT_ESSENTIAL_BACKOFF_SECONDS = 0.5

# ``DiagramSendMode`` / ``_DEFAULT_DIAGRAM_SEND_AS`` (how a rendered diagram is sent) and
# the inline caption now live with :class:`DiagramSender` (capabilities); imported above
# and re-exported here for the constructor default + app.py / tests.

# How many memories to recall when assembling the reply context.
_RECALL_K = 5

# When register-recall is active (BOB-087.C2) recall OVER-FETCHES this deep so C1's CASUAL
# down-weight has teeth: muted work episodes can be re-sorted BELOW non-work items drawn from
# deeper in the pool, then the pool is truncated back to ``_RECALL_K``. Off (no resolver
# wired) the plain ``_RECALL_K`` fetch is used and recall is byte-identical.
_RECALL_OVERFETCH_K = 20

# The SOFT anti-tic nudge ``_CLOSER_TIC_NUDGE`` + the ``_MAX_REGENERATIONS`` bound now live
# with :class:`AntiRepeatGuard` (conversation); the nudge is re-exported above for tests.

# Pre-answer epistemic verify (BOB-057 .2). BEFORE generation a conservative Tier-0
# ``VolatilityJudge`` decides whether the answer hinges on a FRESH volatile fact; on
# ``needs_check`` Bob makes ONE DIRECT ``WebSearchProvider.search`` (NOT via the
# capability registry / tool-loop → not the BOB-052 per-sender gate — an internal
# public-verify that exposes only public web info) and folds the finding into the
# reply-generation context. Everything is decorative: a judge failure degrades to
# «no check» (normal answer), a search failure/timeout/empty to an honest hedge —
# the turn is never blocked or broken.
_DEFAULT_VERIFY_TIMEOUT_SECONDS = 75.0

# The trimmed-answer cap + the GROUNDED / HEDGE register-nudge notes now live with
# :class:`VerifyStep` (conversation); the two notes are re-exported above for tests.

# The ``_CALLBACK_RECALL_K`` recall depth for a BOB-018 callback now lives with
# :class:`GroundedAddons` (personality); the ``surface_old`` frequency is kept here as the
# constructor default (validated below) and passed into that collaborator.

# How often a callback turn reaches for an OLD-but-relevant memory instead of the
# default best hit (BOB-021 mechanism 1, "что-то напомнило"). On a callback (already
# rare/state-driven from BOB-018), a small extra draw occasionally asks recall for the
# surface_old blend so a deep cut can come back à propos — grounded, no-op when nothing
# old is relevant. Deliberately small (anti-tic); tunable via ``memory.surface_old.freq``.
_DEFAULT_SURFACE_OLD_FREQ = 0.15

# A frequency must read as a probability in the closed unit interval.
_MIN_FREQ = 0.0
_MAX_FREQ = 1.0

# Default number of recent conversation turns to replay into the reply context
# (BOB-044). Widened from the old hardcoded 6 — a 6-turn window was too tight to
# hold a thread (an earlier topic fell out before Bob could come back to it), losing
# dialogue coherence. Tunable per persona via ``dialogue.recent_turns``.
_DEFAULT_RECENT_TURNS = 14

# Default long-gap absence-hint threshold in hours (BOB-045 .3). When the CURRENT
# interlocutor's per-person thread has been idle longer than this, a light "haven't
# seen you in a while" hint is folded into the compose context so Bob notices the gap
# humanly (owner and guest alike) — a hint for the reply tier, never a scripted phrase.
# ``0`` disables it. Tunable per persona via ``dialogue.absence_hint_hours``.
_DEFAULT_ABSENCE_HINT_HOURS = 8.0

# Default LOW chance Bob acknowledges a notable recent reaction to his message (BOB-050
# .3). When someone reacted warmly to one of his messages, Bob MAY — at this small,
# seeded frequency, and only to the person who reacted — fold one light "вижу, тебе зашло"
# HINT into the compose context. Deliberately rare (acknowledging every time would read as
# needy); ``0`` disables it. Tunable per persona via ``dialogue.acknowledge_reaction_freq``.
_DEFAULT_ACKNOWLEDGE_REACTION_FREQ = 0.15

# Default small mood-valence lift a good, interesting exchange earns (BOB-014 .2a
# feedback loop). Mirrors the engagement domain default; tunable via emotion.* config.
_DEFAULT_ENGAGEMENT_MOOD_LIFT = 0.1

# Default char ceiling for the OPTIONAL brevity length guard (BOB-024). When the
# guard is enabled AND the answer-demand is LOW, a reply longer than this is lightly
# clamped to its first finished thought (no regeneration). Conservative — the guard
# is a safety net behind the bayes (directive + few-shot), off by default.
_DEFAULT_LENGTH_GUARD_MAX_CHARS = 280

# Default soft-tilt ceiling for self-improvement rules (BOB-028 .3): an APPROVED rule's
# magnitude is clamped to this before it biases its point, so the per-turn drift stays
# small. Conservative — mirrors the ``self_improvement.max_magnitude`` config default;
# only matters when the master switch is on AND the owner has approved a rule.
_DEFAULT_MAX_MAGNITUDE = 0.3

# The base persona ``_SYSTEM_PROMPT`` + the capability manifest preface + the grounded
# add-on prefaces (leak / callback / fascination) now live with the wave-3 collaborators:
# the system prompt + capability preface with :class:`VoiceComposer` (personality voice),
# and the grounded prefaces with :class:`GroundedAddons` — assembled there from the same
# :mod:`bob.personality.voice` seam. The single final length authority
# (voice.brevity_directive + voice.brevity_few_shot on the decided Verbosity) is likewise
# folded into the prompt by VoiceComposer.


class ReplyGateway(Protocol):
    """The Telegram seam HandleMessage needs (BOB-009).

    ``typing_indicator`` wraps the slow generation so "Bob is typing…" stays
    visible for the whole wait; ``reply`` commits the finished answer once (rich,
    plain fallback). No token streaming — Bob can't stream in a group topic.
    """

    def typing_indicator(
        self, *, chat_id: int
    ) -> AbstractAsyncContextManager[None]: ...

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> int | None: ...

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None: ...

    async def send_document(
        self, *, chat_id: int, document: bytes, caption: str | None = None
    ) -> None: ...


class EpisodeWriter(Protocol):
    """The persistence seam HandleMessage needs: save an episode + the mood."""

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...

    async def set_mood(self, state: Mapping[str, object], *, at: datetime) -> None: ...


class EpisodeReader(Protocol):
    """The read seam HandleMessage needs: replay recent conversation history."""

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]: ...

    async def recent_episodes_for(
        self, sender_id: int, k: int
    ) -> Sequence[Mapping[str, object]]:
        """Replay the last ``k`` turns WITH one sender (per-person thread, BOB-045)."""
        ...


class CurrentFascinationReader(Protocol):
    """Read seam: Bob's CURRENT fascination, aged and still-alive (BOB-020 wave 2).

    On a :data:`~bob.personality.expression.ExpressionPlan.mention_fascination`
    turn the compose path folds the topic in so Bob can drop it à propos — but only a
    REAL, persisted passion that has not yet faded. ``None`` means Bob has no current
    fascination, so the mention no-ops (never a fabricated interest). The concrete
    adapter loads the :class:`~bob.personality.ports.FascinationStore`, ages the stored
    passion against the clock, and drops a faded one.
    """

    async def current_fascination(self) -> Fascination | None:
        """Return Bob's current, non-faded fascination, or ``None`` if there is none."""
        ...


class InterlocutorResolver(Protocol):
    """Perception seam: WHO is writing this turn (BOB-019).

    Resolves the inbound :class:`MessageReceived` into an
    :class:`~bob.social.interlocutor.Interlocutor` — the sender's
    social identity (owner / known / guest / bot + trust) — so the compose path can
    fold WHO is on the other side into Bob's voice. The concrete adapter derives it
    from the :class:`~bob.social.usecases.Authorizer` (``is_owner`` +
    ``is_authorized``) already known for the turn. Optional and additive: unwired
    (the default) the perception line is simply absent and the turn behaves exactly
    as before — it never changes which pipeline runs (the guest-restricted path is
    a later bead).
    """

    async def resolve(self, event: MessageReceived) -> Interlocutor: ...


class FirstImpressionReader(Protocol):
    """First-impression seam: recall + record Bob's LIGHT per-person read (BOB-019).

    The compose path uses this to give Bob a light memory of WHO he has met before:
    :meth:`prior_impression` returns the stored impression note for a returning
    sender (a new one → ``None``), so the prompt can fold in "этого человека ты уже
    видел; впечатление было такое-то"; :meth:`note_first_contact` records a fresh,
    grounded note on FIRST contact (formed once — a known sender is left untouched).
    The concrete adapter
    (:class:`~bob.social.usecases.first_impression_sources.FirstImpressionTracker`)
    keys on ``sender_id`` and stamps the clock. Optional and additive: unwired (the
    default) Bob simply never recalls a first impression and the turn is unchanged.

    Crucially this is per-PERSON data (about THEM), NOT owner-private memory, so it
    is safe even on a guest turn — a guest's own first-impression is about the guest,
    and surfacing it never leaks the owner's private world.
    """

    async def prior_impression(self, interlocutor: Interlocutor) -> str | None: ...

    async def note_first_contact(self, interlocutor: Interlocutor) -> None: ...


class RosterRecaller(Protocol):
    """Roster seam: recall who lately turned up in the room (BOB-080).

    The compose path uses this to let Bob NAME the room's recent joiners himself when
    the talk turns to who is around: :meth:`recent_roster` reads the recency of the
    accumulated first impressions and returns the roster of recent members — but ONLY
    while a fresh newcomer is present (the ambient window, INV-4) and ONLY to an
    OWNER / KNOWN ``viewer`` (privacy; a guest gets no rundown). The concrete adapter
    (:class:`~bob.social.usecases.roster_recall.RosterRecall`) is best-effort — a flaky
    read yields an empty roster and never breaks the turn. Optional and additive: unwired
    (the default / the ``social.roster`` flag off) Bob simply recalls no roster and the
    turn is byte-identical.
    """

    async def recent_roster(
        self, now: datetime, *, viewer: Interlocutor | None
    ) -> tuple[RosterMember, ...]: ...


class RelationshipReader(Protocol):
    """Relationship seam: load + evolve Bob's per-person relationship quality (BOB-014).

    The compose path uses this to let Bob's accrued relationship with WHO is writing
    shape THIS turn: :meth:`current` returns the stored
    :class:`~bob.social.relationship.Relationship` (an unknown sender →
    ``None``) so the prompt can warm/cool his tone (by ``warmth``) and the negotiation
    can nudge his willingness to compromise (by ``warmth`` + ``compatibility``);
    :meth:`record_interaction` updates + persists the relationship AFTER the turn from
    the negotiation ``stance``, Bob's ``mood``, and a ``sentiment`` scalar (the pure
    :func:`~bob.social.relationship.apply_interaction`). The concrete
    adapter (:class:`~bob.social.usecases.relationship_sources.RelationshipTracker`)
    keys on ``sender_id``. Optional and additive: unwired (the default) the tone/
    willingness are unchanged and no relationship is recorded.

    Crucially this is per-PERSON data (about THEM), NOT owner-private memory, so it is
    safe even on a guest turn — a guest's own relationship is about the guest.
    """

    async def current(self, interlocutor: Interlocutor) -> Relationship | None: ...

    async def record_interaction(
        self,
        interlocutor: Interlocutor,
        *,
        stance: Stance,
        mood: Mood,
        sentiment: float,
    ) -> None: ...


class SulkReader(Protocol):
    """Sulk seam: load Bob's per-person обида + fold a turn into it (BOB-066 2.5).

    The compose path uses this to go COLD while Bob is hurt at the CURRENT interlocutor
    and to let обида take hold or warm up over the live message path: :meth:`current_for`
    returns the persisted :class:`~bob.social.sulk.SulkState` for ONE ``sender_id`` so the
    prompt appends the cold :func:`~bob.personality.voice.sulk_directive` while ``active``
    — an обида toward another participant never chills THIS reply (addressed cooling);
    :meth:`observe` folds ONE person's turn signals (their relationship ``person_warmth``,
    a ``hostile`` directed-hostility flag, and a ``warmth_delta``) into their обида AFTER
    the turn — a sustained critical warmth-drop OR sustained directed hostility enters
    обида (announced once via GUPPI in an owner-DM, silent in a group), while a warm turn
    accelerates recovery if already hurt. The concrete adapter
    (:class:`~bob.social.usecases.sulk_sources.SulkTracker`) is per-``(persona, sender)``
    and persists. Optional and additive: unwired (the default) Bob never sulks and the turn
    behaves exactly as before. обида carries NO memory and NO soul (anti-Exodus).
    """

    async def current_for(self, sender_id: int) -> SulkState: ...

    async def observe(
        self,
        *,
        sender_id: int,
        person_warmth: float,
        hostile: bool,
        warmth_delta: float,
        now: datetime,
    ) -> SulkState: ...


class SelfImprovementReader(Protocol):
    """Read seam: Bob's APPROVED self-improvement rules for this turn (BOB-028 .3).

    The compose path uses this to APPLY Bob's owner-approved self-improvement rules as
    soft, bounded tilts — a TONE/HUMOR rule colours the voice, a LENGTH rule nudges the
    verbosity one step shorter, a PROACTIVITY/ADDRESSIVITY_BIAS rule biases their points
    (built into :class:`~bob.proactivity.self_improvement.RuleModulators` by
    :func:`~bob.proactivity.self_improvement.build_modulators`). Safety: it
    returns rules the use-case then filters to APPROVED-only via ``active_rules`` (no
    PROPOSED/PAUSED rule ever applies — authz-before-autonomy), and only the
    :class:`~bob.proactivity.self_improvement.Lever` allowlist is read (authz /
    guest / SOUL / safety have no lever). Optional and additive: unwired (the default)
    OR the master switch off → no rules, so the turn behaves exactly as before BOB-028.
    """

    async def active(self) -> tuple[ImprovementRule, ...]:
        """Return Bob's APPROVED self-improvement rules (empty when none / disabled)."""
        ...


class OwnerActivityRecorder(Protocol):
    """The proactivity seam HandleMessage notifies when the owner writes.

    Lets the proactivity drive-model reflect real interaction: each handled
    message stamps the owner-message marker and restores some social energy, so
    the engine's owner-cooldown and energy track the live conversation. Best-effort
    and optional — when unwired the reactive path behaves exactly as before.
    """

    async def run(self) -> None: ...


class BobUserIdSource(Protocol):
    """Read seam: Bob's own bot ``user_id``, resolved at startup (BOB-023).

    The addressivity detector needs Bob's numeric Telegram id to tell a reply that
    targets *Bob* from a reply that targets someone else. The id is resolved
    asynchronously at startup (``get_me`` → ``BotIdentitySignals.user_id``) — long
    after this synchronous use-case is constructed — so it is read lazily through
    this seam, which yields ``None`` until identity is resolved (or for the GUPPI
    gateway, which has none). A ``None`` degrades gracefully: reply-to-Bob simply
    cannot fire, while @mention-of-Bob addressivity still works.
    """

    def __call__(self) -> int | None: ...


# ``NaturalCodingRouter`` / ``PermissionFlowLike`` (the pre-compose consumption seams)
# now live with :class:`PreComposeGate` (application); ``OutageNotifier`` and
# ``_EssentialStepError`` with :class:`EssentialRunner`. All are imported above so the
# constructor annotations + the except clauses + app.py / tests resolve as before.


class BargeCeiling(Protocol):
    """The share-of-voice ceiling on an ambient barge (BOB-066 Срез W, Пласт 3).

    Threaded straight through to the :class:`~bob.conversation.usecases.turn_gate.TurnGate`
    (which owns the focus/periphery split), so only the AMBIENT barge is damped and a focused
    turn bypasses it (INV-1). Realised by
    :class:`~bob.application.runtime.share_of_voice_gate.ShareOfVoiceGate`; unwired
    (``presence.rhythm`` off) → no throttle.
    """

    async def admits_barge(
        self, *, chat_id: int, focused: bool, base_probability: float, draw: float
    ) -> bool: ...


class ReplyDelay(Protocol):
    """The natural-delay coordinator over the reply generation (BOB-066 Срез W, INV-9).

    Runs the generation and tops the elapsed time up to a human floor
    (``await max(natural_floor, real_generation)``), so Bob never answers inhumanly fast.
    Realised by :class:`~bob.application.runtime.delayed_turn.DelayedTurn`; unwired
    (``presence.rhythm`` off) the generation runs directly, byte-identical.
    """

    async def deliver(
        self,
        generate: Callable[[], Awaitable[str]],
        *,
        complexity: float,
        urgency: float,
    ) -> str: ...


@dataclass
class PersonalityState:
    """Mutable in-memory holder for Bob's current soul snapshot across turns.

    The soul (identity, taste, phantoms) is constant for a boot; only the mood
    evolves, so each turn replaces the snapshot via :meth:`SOUL.with_mood`.
    """

    soul: SOUL


@dataclass
class EngagementState:
    """Mutable in-memory holder for Bob's conversational fatigue across turns (BOB-014).

    The lightest correct home for the small, decaying fatigue counter: a per-boot
    holder (mirroring :class:`PersonalityState` for mood) that the turn loads, decays by
    the elapsed wall-clock since the last turn, reads for the appetite decision, then
    updates (an aimless turn tires Bob, an interesting one eases him). It is bounded and
    always decays with time, so appetite is guaranteed to recover — the owner is never
    permanently locked out, even across a long aimless run. ``last_turn_at`` is stamped
    from the injected clock so decay is real elapsed time, not a turn count.
    """

    fatigue: ConversationalFatigue = field(default_factory=ConversationalFatigue)
    last_turn_at: datetime | None = None


# The per-turn response-gate value objects (``_JudgedTurn`` / ``_ReplyGate``) + the
# ``_SILENT_MARKER`` / ``_OUTCOME_FOR_INTENT`` now live with :class:`TurnGate`
# (conversation); the gate returns a ``_ReplyGate`` the happy-path below composes on.


class HandleMessage:
    """Run one full Telegram turn: perceive mood, decide a reply, act, persist."""

    def __init__(  # noqa: PLR0915 — a flat composition-root constructor: one statement per injected seam (BOB-035 added the diagram sink), no branching to extract.
        self,
        *,
        router: LLMRouter,
        gateway: ReplyGateway,
        recall: MemoryRecall,
        repo: EpisodeWriter,
        episodes: EpisodeReader,
        update_mood: UpdateMoodFromText,
        extract_facts: ExtractFacts,
        clock: Clock,
        state: PersonalityState,
        rng: Random,
        registry: CapabilityRegistry | None = None,
        tool_provider: ToolCallingProvider | None = None,
        owner_activity: OwnerActivityRecorder | None = None,
        zone_classifier: ZoneClassifier | None = None,
        negotiation: Negotiation | None = None,
        expression_freqs: ExpressionFreqs | None = None,
        reactor: MessageReactor | None = None,
        reflection: ReflectionReader | None = None,
        fascination: CurrentFascinationReader | None = None,
        offday_thresholds: OffDayThresholds | None = None,
        surface_old_freq: float = _DEFAULT_SURFACE_OLD_FREQ,
        perceive_sender: InterlocutorResolver | None = None,
        first_impression: FirstImpressionReader | None = None,
        roster: RosterRecaller | None = None,
        relationship: RelationshipReader | None = None,
        relationship_tone_thresholds: RelationshipToneThresholds | None = None,
        sulk: SulkReader | None = None,
        engagement_state: EngagementState | None = None,
        engagement_thresholds: EngagementThresholds | None = None,
        fatigue_rates: FatigueRates | None = None,
        engagement_mood_lift: float = _DEFAULT_ENGAGEMENT_MOOD_LIFT,
        bob_user_id_source: BobUserIdSource | None = None,
        addressivity_thresholds: AddressivityThresholds | None = None,
        brevity_thresholds: BrevityThresholds | None = None,
        length_guard_enabled: bool = False,
        length_guard_max_chars: int = _DEFAULT_LENGTH_GUARD_MAX_CHARS,
        recent_turns: int = _DEFAULT_RECENT_TURNS,
        absence_hint_hours: float = _DEFAULT_ABSENCE_HINT_HOURS,
        notable_reaction: NotableReactionStore | None = None,
        acknowledge_reaction_freq: float = _DEFAULT_ACKNOWLEDGE_REACTION_FREQ,
        repeat_thresholds: RepeatThresholds | None = None,
        floor_store: ConversationFloorStore | None = None,
        floor_config: FloorConfig | None = None,
        floor_enabled: bool = True,
        self_improvement: SelfImprovementReader | None = None,
        self_improvement_max_magnitude: float = _DEFAULT_MAX_MAGNITUDE,
        diagram_sink: DiagramSink | None = None,
        diagram_renderer: DiagramRenderer | None = None,
        diagram_send_as: DiagramSendMode = _DEFAULT_DIAGRAM_SEND_AS,
        coding_router: NaturalCodingRouter | None = None,
        permission_flow: PermissionFlowLike | None = None,
        interactive_router: InteractiveRouterLike | None = None,
        decide_response: DecideResponse | None = None,
        outage_notifier: OutageNotifier | None = None,
        retry_sleep: Sleep | None = None,
        essential_attempts: int = _DEFAULT_ESSENTIAL_ATTEMPTS,
        essential_backoff_seconds: float = _DEFAULT_ESSENTIAL_BACKOFF_SECONDS,
        verify_judge: VolatilityJudge | None = None,
        verify_provider: WebSearchProvider | None = None,
        verify_timeout_seconds: float = _DEFAULT_VERIFY_TIMEOUT_SECONDS,
        interim_line_generator: InterimLineGenerator | None = None,
        closer_log: CloserLog | None = None,
        read_the_room: ReadTheRoom | None = None,
        barge_ceiling: BargeCeiling | None = None,
        reply_delay: ReplyDelay | None = None,
        room_mood_modulator: RoomMoodModulator | None = None,
        staleness_reassessor: StalenessReassessor | None = None,
        endorsement_seeder: EndorsementSeeder | None = None,
        disclosure_guard: DisclosureGuard | None = None,
        disclosure_consent: DisclosureConsentGate | None = None,
        self_action_recorder: SelfActionRecorder | None = None,
        register_resolver: RegisterResolver | None = None,
        addon_recall: MemoryRecall | None = None,
        origin_provenance: bool = False,
        voice_canon: VoiceCanon | None = None,
    ) -> None:
        self._router = router
        self._gateway = gateway
        self._recall = recall
        self._repo = repo
        self._episodes = episodes
        self._update_mood = update_mood
        self._extract_facts = extract_facts
        self._clock = clock
        self._state = state
        # The negotiation seam (BOB-013): the zone classifier decides who owns the
        # topic and Negotiation maps zone+conviction to a stance, which augments
        # the warm prompt with a directive. The default is the deterministic
        # taste/keyword classifier — no network, no LLM, behaviour as before when
        # the topic is a neutral SHARED matter.
        self._zone_classifier = (
            zone_classifier if zone_classifier is not None else TasteZoneClassifier()
        )
        self._negotiation = negotiation if negotiation is not None else Negotiation()
        # The proactivity seam (BOB-010): when wired, each handled message updates
        # the owner-activity marker + restores energy so the drive-model reflects
        # real interaction. Unwired (the default) leaves the reactive path intact.
        self._owner_activity = owner_activity
        # The capability seam (BEAD-05): an empty registry (the default) means no
        # capabilities, so HandleMessage behaves exactly as before. The tool-loop
        # only engages when capabilities are registered AND a tool-calling
        # provider is wired (integration wires both in BEAD-07).
        self._registry = registry if registry is not None else CapabilityRegistry()
        self._tool_provider = tool_provider
        # The expression seam (BOB-018): per turn a pure ExpressionPlan picks a
        # mode (full reply vs. a terse react-only ack) + rare add-on flags + a soft
        # form hint, deterministically from mood + signals + the injected seeded
        # RNG. Wave 1 consumes the form hint and the mode; the rare flags (leak /
        # callback) and the react-only behaviour are carried on the plan for later
        # beads. The frequencies default small (anti-tic) and are config-tunable.
        self._rng = rng
        self._expression_freqs = (
            expression_freqs if expression_freqs is not None else ExpressionFreqs()
        )
        # The react-only seam (BOB-018): when a reactor is wired, an
        # ``ExpressionMode.REACT_ONLY`` plan sets a native mood emoji reaction on the
        # user's message INSTEAD of composing a reply (no LLM call). Unwired (the
        # default) a react-only plan falls back to a normal full reply, so the path
        # stays live and backward-compatible.
        self._reactor = reactor
        # The grounded inner-life seam (BOB-018 wave 3): when wired and the plan sets
        # ``leak_inner_life``, the most-recent REAL reflection (read off the episodic
        # log, event_type reflection/inner_monologue — written by BOB-012) is folded
        # into the compose context so a glimpse of what Bob caught himself thinking
        # leaks into the reply. No reflection (or no reader wired) → no-op, never a
        # fabrication. Callbacks reuse the already-injected ``recall`` the same way.
        self._reflection = reflection
        # The fascination seam (BOB-020 wave 2): when wired and the plan sets
        # ``mention_fascination``, Bob's current, non-faded passion (loaded + aged off
        # the FascinationStore) is folded into the compose context so he can drop it à
        # propos — strictly his REAL state. No current fascination (or no reader) →
        # no-op, never a fabricated interest. Surfacing stays rare/anti-tic.
        self._fascination = fascination
        # The emotional-depth seam (BOB-020): Bob's TONE is mood-conditioned via
        # voice.tone_directive — below this off-day floor he reads quieter, more
        # vulnerable, honest ("не знаю" over confabulation) instead of forced warmth.
        # The floor is config-tunable (emotion.offday.*); the default sits in the
        # low/negative band so a normal or good mood always keeps the warm tone.
        self._offday_thresholds = (
            offday_thresholds if offday_thresholds is not None else OffDayThresholds()
        )
        # The surface-old seam (BOB-021 mechanism 1): on a (rare) callback turn, Bob
        # occasionally reaches for an OLD-but-relevant memory via recall's additive
        # surface_old opt-in, so a deep cut can come back à propos ("что-то напомнило").
        # The extra draw uses the same seeded RNG (reproducible) and fires on a small
        # fraction of callbacks only — not every callback, never on a non-callback turn.
        if not _MIN_FREQ <= surface_old_freq <= _MAX_FREQ:
            msg = (
                f"surface_old_freq must be within [{_MIN_FREQ}, {_MAX_FREQ}], "
                f"got {surface_old_freq}"
            )
            raise ValueError(msg)
        self._surface_old_freq = surface_old_freq
        # The perception seam (BOB-019): when wired, Bob perceives WHO is writing —
        # owner / known / guest / bot — and a who-is-writing voice line is folded
        # into the reply prompt so he answers as a person who knows who he's talking
        # to (the owner recognised AS owner). Additive only: unwired (the default)
        # the line is absent and the turn behaves exactly as before. It NEVER changes
        # which pipeline runs — the guest-restricted path is a later bead.
        self._perceive_sender = perceive_sender
        # The first-impression seam (BOB-019 bob-apv.3): when wired, Bob forms +
        # remembers a LIGHT per-person first impression keyed by sender. A returning
        # sender's prior note is recalled into the compose prompt ("этого человека ты
        # уже видел; впечатление было такое-то"); a new sender's grounded note is
        # recorded after the turn. It is per-PERSON data (about THEM), NOT owner-
        # private memory — safe even on a guest turn (a guest's first-impression is
        # about the guest, never an owner-memory leak). Unwired (the default) Bob
        # never recalls a first impression and the turn behaves exactly as before.
        # This is the minimal foundation for multi-party BOB-014, not that engine.
        self._first_impression = first_impression
        # The roster seam (BOB-080): when wired (the ``social.roster`` flag on), Bob
        # recalls WHO lately turned up in the room and can NAME them himself when the
        # talk turns to who is around. The seam owns the ambient window (only while a
        # fresh newcomer is present, INV-4) + the privacy gate (OWNER / KNOWN viewer)
        # + best-effort resilience. Unwired (the default) Bob recalls no roster and the
        # turn is byte-identical.
        self._roster = roster
        # The relationship seam (BOB-014): when wired, Bob's accrued per-person
        # relationship quality shapes THIS turn — high warmth → a warmer voice
        # directive, low warmth → cooler (composes over mood/voice, never rude here;
        # relational hostility is the sulk, .2); warmth + compatibility nudge the
        # negotiation toward compromise with a close person. After the turn the
        # relationship is updated from (stance, mood, sentiment) and persisted, so it
        # accrues. Per-PERSON data, safe even on a guest turn. Additive only: unwired
        # (the default) tone/willingness are unchanged and nothing is recorded.
        self._relationship = relationship
        self._relationship_tone_thresholds = relationship_tone_thresholds
        # The sulk seam (BOB-014 .2b): when wired, Bob's persisted обида state goes
        # COLD on the reactive tone (a quieter, curt sulk_directive while active) and
        # is FED by each owner turn — a sustained critical owner-drop OR sustained
        # DIRECTED hostility (casual мат never counts) enters обида (GUPPI announces it
        # once), while a warm turn accelerates recovery if already hurt. The guaranteed
        # time-decay exit is owned by the reflect tick. обида carries NO memory and NO
        # soul (anti-Exodus). Per-PERSONA; additive — unwired, Bob never sulks.
        self._sulk = sulk
        # The engagement-appetite seam (BOB-014 .2a): Bob's APPETITE to converse is a
        # LEVEL (full / playful / terse / decline), decided per turn from mood x topic
        # interest x conversational fatigue x relationship. The fatigue is a small,
        # bounded, per-boot decaying counter (held like the mood on PersonalityState):
        # it rises on aimless low-interest turns ("наскучило") and recedes with time /
        # on interesting turns, so prolonged pointless chatter winds Bob down but
        # appetite always recovers (never a permanent lock-out). The decided level
        # appends a voice directive (playful banter / terse / soft decline — never rude),
        # and the feedback loops run after the turn: an interesting good exchange lifts
        # his mood a touch, an aimless turn tires him. Thresholds/rates are config-tunable;
        # unset, the state
        # is a fresh per-boot holder so a normal mood stays fully engaging as before.
        self._engagement_state = (
            engagement_state if engagement_state is not None else EngagementState()
        )
        self._engagement_thresholds = (
            engagement_thresholds
            if engagement_thresholds is not None
            else EngagementThresholds()
        )
        self._fatigue_rates = fatigue_rates if fatigue_rates is not None else FatigueRates()
        if not _MIN_FREQ <= engagement_mood_lift <= _MAX_FREQ:
            msg = (
                f"engagement_mood_lift must be within [{_MIN_FREQ}, {_MAX_FREQ}], "
                f"got {engagement_mood_lift}"
            )
            raise ValueError(msg)
        self._engagement_mood_lift = engagement_mood_lift
        # The addressivity seam (BOB-023): Bob perceives WHO a message is FOR — him,
        # another participant, or no one — and the policy decides whether to engage,
        # quietly like-react, or stay SILENT, so he no longer barges into every
        # conversation. ``bob_user_id_source`` lazily reads Bob's own bot id (resolved
        # at startup) so a reply that targets Bob is told from one targeting someone
        # else; ``None`` degrades gracefully (reply-to-Bob can't fire; @mention still
        # does). Unwired (the default) the source yields ``None`` and the thresholds
        # are the conservative defaults, so a 1:1 owner thread always engages exactly
        # as before — the addressivity gate only ever ADDS "stay quiet if it's not for
        # me" in a multi-party thread.
        self._bob_user_id_source = bob_user_id_source
        self._addressivity_thresholds = (
            addressivity_thresholds
            if addressivity_thresholds is not None
            else AddressivityThresholds()
        )
        # The brevity seam (BOB-024): Bob's reply LENGTH stops being a constant. The
        # answer-demand of the message x topic interest x mood/appetite x the BOB-018
        # form_hint decide a Verbosity (terse / normal / expansive), which becomes the
        # SINGLE final length directive + (on a terse turn) the short-answer few-shot
        # that beats Qwen's verbosity prior — replacing the old soft form_hint length
        # path. The optional length guard is a conservative safety net: when enabled AND
        # the demand is LOW, an over-long reply is lightly clamped to its first finished
        # thought (no regeneration). Thresholds are config-tunable; the guard is OFF by
        # default, so the bayes (directive + few-shot) is the mechanism, the guard a
        # backstop.
        self._brevity_thresholds = (
            brevity_thresholds if brevity_thresholds is not None else BrevityThresholds()
        )
        self._length_guard_enabled = length_guard_enabled
        if length_guard_max_chars <= 0:
            msg = f"length_guard_max_chars must be positive, got {length_guard_max_chars}"
            raise ValueError(msg)
        self._length_guard_max_chars = length_guard_max_chars
        # Recent-history replay window (BOB-044): how many recent conversation turns are
        # replayed into the reply context. A wider window holds the dialogue thread (an
        # earlier topic no longer falls out before Bob can return to it). Must be a
        # positive count; tunable via ``dialogue.recent_turns``.
        if recent_turns <= 0:
            msg = f"recent_turns must be positive, got {recent_turns}"
            raise ValueError(msg)
        self._recent_turns = recent_turns
        # Long-gap absence texture (BOB-045 .3): the per-person idle threshold (hours)
        # past which a light "haven't seen you in a while" hint enters the compose
        # context so Bob notices a pause humanly. Must be non-negative; ``0`` disables
        # it. Tunable via ``dialogue.absence_hint_hours``.
        if absence_hint_hours < 0:
            msg = f"absence_hint_hours must be non-negative, got {absence_hint_hours}"
            raise ValueError(msg)
        self._absence_hint_hours = absence_hint_hours
        # Being-received acknowledgment seam (BOB-050 .3): when wired, Bob OCCASIONALLY
        # acknowledges a notable recent reaction to one of his messages — at this small
        # seeded frequency, only to the person who reacted (per-person), as ONE light HINT
        # he weaves in himself. Decorative: a store failure is dropped silently. The
        # frequency is a probability; out-of-range is a misconfiguration. Unwired (the
        # default) the path is inert and the turn behaves exactly as before.
        if not _MIN_FREQ <= acknowledge_reaction_freq <= _MAX_FREQ:
            msg = (
                f"acknowledge_reaction_freq must be within [{_MIN_FREQ}, {_MAX_FREQ}], "
                f"got {acknowledge_reaction_freq}"
            )
            raise ValueError(msg)
        self._notable_reaction = notable_reaction
        self._acknowledge_reaction_freq = acknowledge_reaction_freq
        # Anti-repeat window (BOB-026 .1): the fresh reply is checked against a WINDOW
        # of Bob's recent replies (not just the last), verbatim OR near-verbatim, so a
        # repeat "через ход" no longer slips through. Conservative defaults; tunable
        # via repeat.*.
        self._repeat_thresholds = (
            repeat_thresholds if repeat_thresholds is not None else RepeatThresholds()
        )
        # Cross-session closer ring (BOB-061 .2 wiring): the bounded, private persist of
        # Bob's recent NORMALISED closers. After each reply his closer is APPENDED here;
        # BEFORE generation the persisted closers UNION the live-window closers feed the
        # near-verbatim tic detector, so a signature ending recurring ONCE PER SESSION over
        # days is finally caught. 🔴 Fully DECORATIVE and OPTIONAL: unwired (the default)
        # the anti-tic nudge is inert and the turn behaves exactly as before; a read/append
        # failure is swallowed so the persist can never break a turn.
        self._closer_log = closer_log
        # Autobiography recorder (BOB-079.3): injected into the per-turn ToolLoop by
        # ``_make_tool_loop`` so Bob records that HE used tools (coalesced, first-person).
        # Unwired / the OFF-flag NoOp → zero writes, byte-identical behaviour.
        self._self_action_recorder = self_action_recorder
        # The VOICE canon for the per-turn tool-loop (BOB-096.8). This turn's payload
        # already carries the ban verbatim (it comes from the base persona), and the seam is
        # idempotent, so the folded payload is byte-identical — the wiring is here so that
        # NO construction site of the loop depends on someone else having remembered the
        # canon, which is exactly how the privileged fulfilment lost it.
        # 🔴 That justification is now CHECKED, not merely stated (BOB-096.11, review
        # MINOR-10): ``tests/runtime/test_composed_wiring_carries_the_canon.py`` runs the
        # loop this use-case builds over a payload that does NOT carry the ban, so the belt
        # is what has to deliver it. A live turn could not prove this — its persona would
        # keep the test green with the seam unwired.
        self._voice_canon = voice_canon
        # Register-recall seam (BOB-087.C2): when wired, recall is register-aware — a CASUAL
        # turn mutes Bob's own ``work`` dev episodes (over-fetch → C1 attenuate → re-sort →
        # truncate, so muted work really drops out of the final slots), while a DEV turn (the
        # dev-DM channel, or the Tier-0 «about dev work?» judge) keeps them at full weight.
        # Unwired (the default) → recall takes the plain fetch and is byte-identical (C4 flips
        # the ``memory.register_recall`` flag by wiring this resolver).
        self._register_resolver = register_resolver
        # The SECONDARY recall door (BOB-087.C8): the BOB-018 grounded callback holds its own
        # recall port, so it bypasses the per-turn register filter above. Composition hands it
        # the CASUAL-floor recall when register-recall is on (work muted, never cut, and no
        # Tier-0 call — a secondary surface carries no provenance directive, so it may not lift
        # to DEV). Unwired (the default) it draws from the SAME port as the reply — the
        # callback is byte-identical to before C8.
        self._addon_recall = addon_recall if addon_recall is not None else recall
        # Провенанс «где это было» (BOB-090.C1, ``memory.origin_provenance``): whether the
        # VoiceComposer folds WHERE the recalled material was said into Bob's prompt. It is
        # the SECOND provenance axis beside the register one above — «где сказано», not «про
        # что» — and neither replaces the other. OFF (the default) → the composed prompt is
        # byte-identical; recall itself is untouched either way (nothing is filtered).
        self._origin_provenance = origin_provenance
        # The conversation-floor seam (BOB-025): over the per-message addressivity
        # (BOB-023) lives a tracker of who currently holds the "talking turn" in a
        # thread. When wired AND enabled, an AMBIENT message in a thread where Bob holds
        # a live floor is RAISED to DIRECTED_TO_BOB — so the owner (or a guest) keeps
        # talking to Bob without re-tagging every message (continuity). After the turn
        # the floor advances on the RAW per-message signal + whether Bob actually
        # replied, then persists. Unwired (the default) OR ``floor_enabled`` false →
        # the effective addressivity is the per-message classification, so behaviour is
        # exactly BOB-023 (Bob never hijacks a third-party exchange).
        self._floor_store = floor_store
        self._floor_config = floor_config if floor_config is not None else FloorConfig()
        self._floor_enabled = floor_enabled
        # Self-improvement seam (BOB-028 .3): when wired AND the master switch is on,
        # Bob's OWNER-APPROVED rules apply as soft, bounded tilts — a TONE/HUMOR rule
        # colours the voice (improvement_directive), a LENGTH rule nudges verbosity one
        # step shorter, a PROACTIVITY/ADDRESSIVITY_BIAS rule biases its own point. ONLY
        # active_rules (APPROVED) apply (authz-before-autonomy) and ONLY the Lever
        # allowlist is read (authz/guest/SOUL/safety have no lever — границу безопасности
        # держит конструкция). The magnitude ceiling clamps the per-turn drift. Unwired
        # (the default) OR disabled → no rules, behaviour exactly as before BOB-028.
        self._self_improvement = self_improvement
        self._self_improvement_max_magnitude = _validated_magnitude(
            self_improvement_max_magnitude
        )
        # The diagram photo-send seam (BOB-035): the ``render_diagram`` capability —
        # dispatched deep inside the global registry's tool-loop, with no chat_id —
        # pushes each rendered :class:`~bob.capabilities.ports.DiagramResult` (PNG + caption)
        # into this per-turn sink. After the tool-loop the reply path drains it and
        # sends each as a Telegram photo into THIS turn's chat (the chat_id stays
        # per-turn, the send a gateway concern). Unwired (the default) Bob has no
        # diagram skill and the turn behaves exactly as before; an empty sink → no
        # photo. The same sink instance is shared with the capability in the registry.
        self._diagram_sink = diagram_sink
        # The inline-mermaid auto-render seam (BOB-037 A — the reliability fix). The
        # model UNRELIABLY calls the render_diagram tool — usually it just writes the
        # mermaid as a fenced ```mermaid block in its TEXT reply, so no image is sent.
        # When this renderer is wired, after the reply is composed the reply path scans
        # the text for fenced mermaid, renders each block (deduped against any the tool
        # already rendered this turn), queues it to the same per-turn sink, and STRIPS
        # the fence from the visible text (the image replaces it). A render failure
        # leaves the block as text (graceful). Unwired (the default) the auto-render is
        # inert, so the turn behaves exactly as before. The send MODE — ``document``
        # (uncompressed, full-resolution; the default) vs ``photo`` (inline preview,
        # recompressed) — is config-tunable (``diagrams.send_as``) and applied by the
        # drain below.
        self._diagram_renderer = diagram_renderer
        self._diagram_send_as: DiagramSendMode = diagram_send_as
        # Natural-language coding-intent seam (BOB-041 .2): when wired (only when
        # ``coder.enabled``), an OWNER message in Bob's topic that asks Bob to do dev
        # work on his repo — or a natural approve/stop of a live session — is routed
        # into the gated CodingAssistant (plan gate, owner-only, never-main all intact;
        # the router only chooses WHEN to call start/approve_plan/stop, it cannot bypass
        # a gate). Unwired (the default) the natural-language path is inert and every
        # message takes the normal chat flow exactly as before. The `/code` command in
        # General is a separate surface and is unaffected.
        self._coding_router = coding_router
        # The permission seam (BOB-052 .2): when wired, a privilege — running a tool,
        # revealing Bob's inner life, disclosing owner data — is OWNER-GATED even though
        # memory is public in the closed group (BOB-051). On the OWNER's turn an active
        # pending decision (grant / deny / authorize) is recorded; on a NON-authorized
        # member's turn a privileged request opens a pending + asks the owner in Bob's own
        # words (BOB-090.E) and the member is told «спрошу Вову». 🔴 Owner-only
        # decision + the non-authorized-only request gate live inside the flow; an
        # AUTHORIZED member never enters it. Either consumes the turn (the normal compose
        # is skipped). Unwired (the default) the seam is inert and the turn is unchanged.
        self._permission_flow = permission_flow
        # The interactive-terminal intake seam (BOB-083 .4): when wired
        # (``coder.interactive`` on), an OWNER DM message may open / steer / stop a LIVE
        # bidirectional claude session — the owner's plain DM replies go to the session's
        # stdin while it is active, consuming the turn (no normal Bob reply). 🔴 owner-only
        # + DM-only + strictly by the active session (the mode does not stick): a guest / a
        # GROUP message / no live session all fall through to the normal chat path. Unwired
        # (the default) the seam is inert and the turn behaves exactly as before.
        self._interactive_router = interactive_router
        # The semantic response-judgment seam (BOB-049): when wired (the LIVE path),
        # Bob UNDERSTANDS each inbound in context and chooses — as a person — REPLY /
        # REACT / IGNORE, replacing the if/else addressivity ladder (BOB-023/025) and the
        # BOB-018 REACT_ONLY form gate. The structural signals (addressivity / mention /
        # reply / others-present / floor) become INPUTS the judge weighs by meaning, never
        # deciders; the decision holds for ANY interlocutor (authz stays orthogonal — the
        # GUEST restrictions on the REPLY path are unchanged). Unwired (the default) OR no
        # sender perceived → Bob falls back to the legacy addressivity path, so existing
        # constructions/tests behave exactly as before.
        self._decide_response = decide_response
        # Reflective «read the room» seam (BOB-066 Срез 2.2): when wired AND a sender is
        # perceived, the turn gate takes the focus/periphery fork ДО the BOB-049 judge — a
        # raw direct address short-circuits to a deterministic reply (INV-1), everything
        # ambient goes through one rich Tier-1 reflective read + a pure verdict. Unwired
        # (the default → off in composition unless ``presence.reflective``) the gate falls
        # back to the BOB-049 judge / legacy paths, so behaviour is exactly as before.
        self._read_the_room = read_the_room
        # Ambient-barge ceiling seam (BOB-066 Срез W, Пласт 3): threaded into the TurnGate so a
        # periphery REPLY verdict is damped by Bob's per-chat share of voice — a focused turn
        # bypasses it (INV-1). Unwired (``presence.rhythm`` off) → no throttle, byte-identical.
        self._barge_ceiling = barge_ceiling
        # Natural-delay seam (BOB-066 Срез W, Пласт 3, INV-9): when wired, the reply generation
        # runs inside the DelayedTurn coordinator (noticed → typing → ``await max(natural_floor,
        # real_generation)`` → reply), so Bob never answers inhumanly fast. Unwired → the
        # generation runs directly, byte-identical to before the rhythm layer.
        self._reply_delay = reply_delay
        # RoomMood-в-тоне seam (BOB-066 Срез W.2, Пласт 4): when wired (behind
        # ``presence.room_mood.enabled``), a reflective periphery-reply surfaces the room's
        # atmosphere and this modulator maps it — BY VALUE — to a tone line (eases banter in a
        # heavy/tense room) + a signed engagement-threshold shift (a warm room lifts appetite).
        # Bob's personal Mood is never mutated (a SECOND layer). Unwired (the default) → None →
        # the room never colours the turn, byte-identical.
        self._room_mood_modulator = room_mood_modulator
        # Staleness врезка (BOB-066 Срез W.3, Пласт 3): when wired (behind
        # ``presence.staleness.enabled``), just BEFORE sending Bob rereads what landed in this
        # chat WHILE he was drafting (the turn-local ``scope.peek_arrivals``) and — if the
        # drafted reply is now redundant (someone else answered / the topic closed) AND no fresh
        # DIRECT question is riding on top — drops it to a like instead of firing a stale line.
        # 🔴 INV-1: a fresh direct question is NEVER dropped (the pure gate merges it). Unwired
        # (the default) / no reactor / nothing landed → None-path → the reply path is
        # byte-identical.
        self._staleness = staleness_reassessor
        # EQ live-врезка (BOB-066 Срез W.4, Пласт 4). Both ship inert until the epic is complete:
        #   * ``endorsement_seeder`` (behind ``presence.endorsement.enabled``): on the FIRST
        #     contact of a GUEST the owner vouched for by name in the shared thread, Bob meets
        #     them warm (a credit of trust that drift-to-neutral dissolves if unconfirmed)
        #     instead of a blank neutral read. Unwired (the default) → None → the neutral
        #     first-contact path, byte-identical.
        #   * ``disclosure_guard`` (behind ``presence.tact.enabled``): a GUEST ``owner_data``
        #     request gets the warm :func:`tactful_withhold_directive` instead of the dry
        #     stranger-wall — 🔴 the privilege GATE is unchanged, only the refusal VOICE.
        #     Unwired (the default) → None → no withhold line, byte-identical.
        self._endorsement_seeder = endorsement_seeder
        self._disclosure_guard = disclosure_guard
        # Owner-consent disclosure override (BOB-082 .4): приватность по умолчанию — не
        # тюрьма. In a GROUP the owner's private (DM-world) memory is guarded from the room
        # (surfaced as if facing a GUEST — scope BY WHERE, mirroring .1's write side), UNLESS
        # the owner explicitly consents THIS turn (a per-turn recall-time lift, never a stored
        # reclassification). This gate BEING WIRED is the feature switch: unwired (the default)
        # → the group-guard is off and recall is byte-identical (owner-in-group surfaces his
        # own owner_private via TRUSTED exactly as before).
        self._disclosure_consent = disclosure_consent
        # Reliability seam (BOB-049 .3 — «полный Боб или честный GUPPI-нотис»): the two
        # ESSENTIAL LLM steps (the semantic judgment + the reply generation) are retried a
        # bounded number of times with a short backoff before Bob falls back to the honest
        # GUPPI outage notice — never a degraded half-answer. The backoff is awaited through
        # an injected ``retry_sleep`` (``asyncio.sleep`` at runtime, a fake in tests, so the
        # retry is deterministic with no real delay). When an essential step still fails,
        # ``outage_notifier`` posts the honest GUPPI outage notice into Bob's topic;
        # unwired (the default) the turn still ends cleanly with no degraded reply, just
        # without a visible notice. Optional flavours are NOT routed through here — they
        # drop silently in their own call sites, so a flaky add-on never trips the notice.
        self._outage_notifier = outage_notifier
        self._retry_sleep: Sleep = retry_sleep if retry_sleep is not None else asyncio.sleep
        if essential_attempts < 1:
            msg = f"essential_attempts must be >= 1, got {essential_attempts}"
            raise ValueError(msg)
        self._essential_attempts = essential_attempts
        if essential_backoff_seconds < 0:
            msg = (
                f"essential_backoff_seconds must be non-negative, "
                f"got {essential_backoff_seconds}"
            )
            raise ValueError(msg)
        self._essential_backoff_seconds = essential_backoff_seconds
        # Pre-answer epistemic verify seam (BOB-057 .2): when BOTH a conservative Tier-0
        # ``VolatilityJudge`` and a ``WebSearchProvider`` are wired, a volatile-fact turn
        # triggers ONE DIRECT ``provider.search`` (NOT the capability registry / tool-loop
        # → NOT the BOB-052 per-sender gate; internal public-verify, only public web info)
        # and folds the finding into the reply-generation context. Unwired (either None,
        # the default → ``verify.enabled`` off in app.py) the seam is fully inert: zero
        # judge/search calls, behaviour exactly as before. Decorative end to end (a judge
        # failure → no check; a search failure/timeout/empty → an honest hedge).
        self._verify_judge = verify_judge
        self._verify_provider = verify_provider
        self._verify_timeout_seconds = verify_timeout_seconds
        # The LIVE addressed interim line (BOB-057 .3, US-3b): on a ``needs_check`` turn
        # Bob speaks a one-liner naming WHAT he checks and WHO he's talking to before the
        # search. When wired, a Tier-0 gen produces it live; unwired (the default) the
        # verify interim stays silent. Fully decorative (gen/send failure → silence),
        # never blocks the search or breaks the turn.
        self._interim_line_generator = interim_line_generator

        # ── Wave-1 leaf collaborators (BOB-062.6b): each a cohesive method-object built
        # HERE from the already-injected seam — behaviour-preserving (the `handle()` flow
        # calls them exactly where the inlined methods used to run). ──
        # DiagramSender (capabilities): auto-render inline mermaid + drain the per-turn
        # sink. 🔴 The SAME shared sink instance is passed (never a new one) so the
        # render_diagram capability's push and this sender's drain act on one object.
        self._diagrams = DiagramSender(
            gateway=self._gateway,
            diagram_sink=self._diagram_sink,
            diagram_renderer=self._diagram_renderer,
            diagram_send_as=self._diagram_send_as,
        )
        # EssentialRunner (application): retry the two ESSENTIAL LLM steps, then fall back
        # to the honest GUPPI outage notice — persisting the user's turn via this
        # use-case's own persist step (injected as a callback, no persistence knowledge
        # leaks into the runner).
        self._essential = EssentialRunner(
            attempts=self._essential_attempts,
            backoff_seconds=self._essential_backoff_seconds,
            retry_sleep=self._retry_sleep,
            outage_notifier=self._outage_notifier,
            persist=self._persist,
        )
        # FloorManager (conversation): resolve + advance the conversation floor. Takes
        # primitive ids (never the application event), so the conversation vertical stays
        # free of an inward application dependency.
        self._floor = FloorManager(
            floor_store=self._floor_store,
            floor_config=self._floor_config,
            floor_enabled=self._floor_enabled,
            clock=self._clock,
        )
        # VerifyStep (conversation): the pre-answer epistemic verify, returning a per-turn
        # LOCAL note. The per-turn interim announcer is built from the turn's chat_id via
        # this injected factory (the concrete GatewayProgressAnnouncer lives in
        # capabilities; composing it here keeps VerifyStep off that import).
        self._verify = VerifyStep(
            verify_judge=self._verify_judge,
            verify_provider=self._verify_provider,
            verify_timeout_seconds=self._verify_timeout_seconds,
            announcer_factory=self._make_verify_announcer,
        )
        # PreComposeGate (application, cross-domain): the coding-intent + permission gates
        # that may CONSUME a turn before the normal compose.
        self._precompose = PreComposeGate(
            coding_router=self._coding_router,
            permission_flow=self._permission_flow,
            interactive_router=self._interactive_router,
        )

        # ── Wave-2 mid-tier collaborators (BOB-062.6b): each a cohesive method-object
        # built HERE from the already-injected seam — behaviour-preserving (HandleMessage
        # keeps thin delegators so every call site — handle() + the judge/compose helpers —
        # runs them exactly where the inlined methods used to). 🔴 The SAME injected
        # ``self._rng`` is passed to each, so the per-turn seeded-draw order (plan →
        # engagement → verbosity → addressivity → surface/ack) is unchanged. ──
        # AddressivityPerceiver (conversation): perceive WHO a message is for + decide
        # whether Bob takes the turn. Depends on the wave-1 FloorManager (injected) for the
        # BOB-025 continuity raise.
        self._addressivity = AddressivityPerceiver(
            floor=self._floor,
            episodes=self._episodes,
            recent_turns=self._recent_turns,
            bob_user_id_source=self._bob_user_id_source,
            addressivity_thresholds=self._addressivity_thresholds,
            rng=self._rng,
        )
        # MoodPerceiver (personality): update the mood from the inbound + plan the BOB-018
        # expression. The mutable per-boot PersonalityState is passed PER CALL (never
        # captured) so it always reads/writes THIS use-case's current holder.
        self._mood = MoodPerceiver(
            update_mood=self._update_mood,
            expression_freqs=self._expression_freqs,
            rng=self._rng,
        )
        # EngagementModel (conversation): decide Bob's appetite LEVEL + reply verbosity +
        # the after-turn feedback loops. It lives in conversation (brevity / engagement) and
        # imports its result value-objects back from personality (the legal one-way edge).
        # 🔴 The SHARED per-boot PersonalityState (mood) + EngagementState (fatigue) are
        # passed PER CALL (never captured), so the mood lift + fatigue decay accrue on this
        # use-case's current holders exactly as before.
        self._engagement = EngagementModel(
            engagement_thresholds=self._engagement_thresholds,
            fatigue_rates=self._fatigue_rates,
            engagement_mood_lift=self._engagement_mood_lift,
            fascination=self._fascination,
            brevity_thresholds=self._brevity_thresholds,
            length_guard_enabled=self._length_guard_enabled,
            length_guard_max_chars=self._length_guard_max_chars,
            clock=self._clock,
            rng=self._rng,
        )
        # SocialContext (social): Bob's per-person read — WHO is writing, first impression,
        # relationship, обида, negotiation stance, relationship-tone. decide_stance is
        # PUBLIC (shared with the wave-3 compose path).
        self._social = SocialContext(
            perceive_sender=self._perceive_sender,
            first_impression=self._first_impression,
            roster=self._roster,
            relationship=self._relationship,
            relationship_tone_thresholds=self._relationship_tone_thresholds,
            sulk=self._sulk,
            negotiation=self._negotiation,
            zone_classifier=self._zone_classifier,
            clock=self._clock,
        )
        # RecallAssembler (conversation): replay the shared recent thread + add the light
        # absence / being-received acknowledgment texture. 🔴 acknowledgment_for reads the
        # notable-reaction marker BEFORE the seeded roll (consume-once; an unlucky turn
        # spends no draw and leaves the marker).
        self._assembler = RecallAssembler(
            episodes=self._episodes,
            recent_turns=self._recent_turns,
            absence_hint_hours=self._absence_hint_hours,
            notable_reaction=self._notable_reaction,
            acknowledge_reaction_freq=self._acknowledge_reaction_freq,
            clock=self._clock,
            rng=self._rng,
        )

        # ── Wave-3 CORE collaborators (BOB-062.6b): the reply-composition core, extracted
        # behind the bounded-context boundaries. 🔴 GroundedAddons + VoiceComposer live in
        # personality («who Bob is» — his voice), reaching conversation / social /
        # capabilities / router ONLY through the injected ports/callables below (so
        # personality imports none of them); AntiRepeatGuard lives in conversation and closes
        # the compose↔guard cycle through the ``compose`` CALLBACK (by value, not import —
        # no conversation→personality import cycle). 🔴 verify_note + closer_nudge stay
        # TURN-LOCAL arguments threaded through that callback, never a collaborator attribute
        # (a shared-singleton would leak them across turns / users). ──
        # GroundedAddons (personality): fold Bob's REAL reflection / callback / fascination
        # into the context — anti-confabulation + decorative (a failing add-on drops to "").
        self._addons = GroundedAddons(
            reflection=self._reflection,
            fascination=self._fascination,
            recall=self._addon_recall,
            surface_old_freq=self._surface_old_freq,
            rng=self._rng,
        )
        # VoiceComposer (personality): shape Bob's voice + generate his reply. It reaches
        # every OTHER bounded context through the injected ports/values only — the
        # conversation context assembler + recall/verify ports, the social stance port, the
        # application plain-reply + essential generators, and the capabilities tool-loop /
        # announcer factories — so personality never imports conversation/social/capabilities.
        self._voice = VoiceComposer(
            registry=self._registry,
            tool_provider=self._tool_provider,
            offday_thresholds=self._offday_thresholds,
            addons=self._addons,
            essential=self._essential,
            assemble_context=_assemble_shareable_context,
            assembler=self._assembler,
            verify=self._verify,
            social=self._social,
            plain_reply=self._plain_reply,
            announcer_factory=self._make_verify_announcer,
            tool_loop_factory=self._make_tool_loop,
            origin_provenance=self._origin_provenance,
        )
        # AntiRepeatGuard (conversation): recompose a repeat / phrase-tic reply + manage the
        # cross-session closer ring. 🔴 It takes ``compose`` = VoiceComposer.compose as a
        # CALLBACK (identical args, incl. the turn-local verify_note + closer_nudge), closing
        # the compose↔guard cycle WITHOUT a conversation→personality import.
        self._guard = AntiRepeatGuard(
            repeat_thresholds=self._repeat_thresholds,
            closer_log=self._closer_log,
            episodes=self._episodes,
            compose=self._voice.compose,
        )

        # ── Wave-4 orchestration collaborator (BOB-062.6b): the response gate — decide
        # WHETHER/HOW Bob takes this turn (reply / react / silent). A THIN coordinator over
        # the already-built wave-1/2 collaborators (AddressivityPerceiver + FloorManager +
        # EssentialRunner + the injected semantic judge), plus two callbacks back into this
        # use-case (persist the user's turn + stamp owner activity) so the conversation gate
        # stores no persistence policy. 🔴 The floor advance lives inside the gate for every
        # NON-reply branch; the happy-path reply advances it in `handle()` (bob_replied=True).
        self._turn_gate = TurnGate(
            decide_response=self._decide_response,
            addressivity=self._addressivity,
            floor=self._floor,
            essential=self._essential,
            assembler=self._assembler,
            reactor=self._reactor,
            persist=self._persist,
            record_owner_activity=self._record_owner_activity,
            read_the_room=self._read_the_room,
            barge_ceiling=self._barge_ceiling,
        )

    async def _plain_reply(self, system_prompt: str, text: str, context: str) -> str:
        """Generate a reply on the plain reply tier (BOB-006), no capability tool-loop.

        The injected generator :class:`VoiceComposer` calls on a guest / no-tool turn: a
        pure heuristic picks the fast Tier-0 vs quality Tier-1 model on the user's message,
        then the router runs the REPLY request with the shareable context. Kept here
        (application) so the personality VoiceComposer never imports the LLM router.
        """
        tier = select_reply_tier(text)
        request = LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            shareable_context=context,
            private_context=None,
            tier_override=tier,
        )
        return await self._router.run(request)

    def _make_tool_loop(
        self, provider: ToolCallingProvider, announcer: ProgressAnnouncer | None
    ) -> ToolLoop:
        """Build the capability tool-loop over the shared registry (BOB-062.6b wave 3).

        The factory :class:`VoiceComposer` calls to drive a tool reply — composing the
        :class:`ToolLoop` over this use-case's capability registry + the per-turn announcer,
        so VoiceComposer (personality) never imports the capabilities use-cases.

        The autobiography recorder (BOB-079.3) rides along so the loop records that Bob USED
        tools (coalesced, first-person) — a NoOp / unwired recorder writes nothing. Sender /
        visibility are not in this factory's scope, so recording is attributed sender-less
        (owner-context self-action), which the recorder tolerates.
        """
        return ToolLoop(
            provider=provider,
            registry=self._registry,
            announcer=announcer,
            recorder=self._self_action_recorder,
            voice_canon=self._voice_canon,
        )

    def _make_verify_announcer(
        self, *, chat_id: int, sender_name: str
    ) -> GatewayProgressAnnouncer:
        """Build the per-turn, chat-bound interim announcer for the verify search.

        The factory VerifyStep calls with the turn's ``chat_id`` + perceived
        ``sender_name`` — composing the capabilities announcer over this use-case's reply
        gateway + live interim generator, so VerifyStep (conversation) never imports it.
        """
        return GatewayProgressAnnouncer(
            chat_id=chat_id,
            gateway=self._gateway,
            line_generator=self._interim_line_generator,
            sender_name=sender_name,
        )

    async def _load_modulators(self) -> RuleModulators:
        """Build this turn's soft modulators from Bob's APPROVED rules (BOB-028 .3).

        Unwired seam → neutral :class:`RuleModulators` (no tilt), so the turn behaves
        exactly as before. ``build_modulators`` re-filters to APPROVED-only and reads
        ONLY the Lever allowlist, clamping every tilt to the magnitude ceiling.
        """
        if self._self_improvement is None:
            return RuleModulators()
        rules = await self._self_improvement.active()
        return build_modulators(
            rules, max_magnitude=self._self_improvement_max_magnitude
        )

    async def handle(self, event: MessageReceived, scope: TurnScope | None = None) -> None:
        """Process one received message end to end, under the turn's MATERIAL TRAIL.

        🔴 BOB-090.B-fix2: the trail
        (:func:`~bob.capabilities.usecases.turn_material.armed_turn_material`) is armed for
        the WHOLE turn — deliberately wider than the delivery scope, which is armed only
        around the generation. The turn's auto-recall runs BEFORE that, so a trail armed
        with the scope would have missed the very first door and the transfer gate would be
        back to reading one door out of four. Everything memory raises anywhere inside this
        call — auto-recall, the ``recall_memory`` / ``search_memory`` tool hops, the
        grounded-addon callback — lands in it through the ONE recall port, and the gate
        reads it. The arming is released on the way out, exceptions included.
        """
        with armed_turn_material():
            await self._handle_turn(event, scope)

    async def _handle_turn(  # noqa: PLR0915, PLR0911 — a flat per-turn orchestration: one statement per social/compose seam (BOB-080 added the roster recall; BOB-083 .4 added the interactive-intake consume-gate), each a short-circuit return, no branching to extract.
        self, event: MessageReceived, scope: TurnScope | None = None
    ) -> None:
        """Process one received message end to end (the intake worker's per-turn call).

        🔴 BOB-066 Срез W.2 (batch top-k): the turn's ``scope.series_ceiling`` CAPS this
        message's ambient outcome when several inbound settle in one intake window — the intake
        worker plans the burst (one addressed reply + a budget-capped like, never N replies) and
        stamps each message's ceiling on its scope. ``ENGAGE`` (the default / a single-message
        window / a focus message) is no cap. A direct address is answered ABOVE it (INV-1).

        🔴 BOB-066 Срез 2.1 (intake-развязка): the bus subscriber is now the fast
        :class:`~bob.application.runtime.intake.dispatcher.ChatDispatcher.submit`; a per-chat
        worker calls this with the turn's :class:`~bob.application.runtime.intake.scope.
        TurnScope`, whose ``rng`` is seeded per ``(base, chat_id, message_id)``. That
        per-turn rng is threaded through every seeded draw of the turn (plan → engagement →
        verbosity → addressivity → surface/ack) so concurrent chats never share a draw
        stream and a turn is reproducible independent of dispatch timing (INV-4). Called
        directly without a scope (a unit test) it falls back to the injected per-boot rng, so
        behaviour is byte-identical to before the развязка.
        """
        # The turn-local rng + the batch top-k outcome ceiling (BOB-066 Срез W.2) both ride on
        # the scope; driven directly (a unit test) they fall back to the per-boot rng + an
        # uncapped ENGAGE, so behaviour is byte-identical to before the развязка.
        # 🔴 BOB-072: the holistic batch stream-read's pre-computed per-message reading rides on
        # the scope alongside the rng + ceiling. When set (the intake worker read the whole
        # ambient burst at once), the turn gate applies it directly instead of running a
        # per-message reflective read; ``None`` (a focal message / a unit-test drive / the flag
        # off) keeps the normal per-message path.
        rng, series_ceiling, ambient_reading = (
            (scope.rng, scope.series_ceiling, scope.ambient_reading)
            if scope is not None
            else (self._rng, ResponseOutcome.ENGAGE, None)
        )
        soul = await self._perceive(event)
        # Perceive WHO is writing (BOB-019): owner / known / guest / bot. Resolved
        # once per turn so the same identity threads through every (re)compose; None
        # when no perception seam is wired (additive, behaviour as before).
        interlocutor = await self._perceive_interlocutor(event)
        # Interactive terminal intake (BOB-083 .4): for an OWNER DM message (and only when
        # ``coder.interactive`` is wired), route the turn into the LIVE interactive claude
        # session BEFORE composing a normal reply — an entry command opens it, an exit
        # command stops it, and while it is active the owner's plain DM replies go to its
        # stdin (steer). When it consumes the turn the message was an interactive command /
        # a steer reply, so the normal compose is skipped. 🔴 owner-only + DM-only + strictly
        # by the active session: a guest / a GROUP message / no live session all fall
        # through here unconsumed to the normal chat path (the mode never sticks).
        if await self._precompose.maybe_route_interactive(event, interlocutor):
            return
        # Natural-language coding intent (BOB-041 .2): for an OWNER message in Bob's
        # topic (and only when the coder is wired/enabled), route a dev-work request
        # — or a natural approve/stop of a live session — into the gated CodingAssistant
        # BEFORE composing a normal reply. When it consumes the turn the message was a
        # coding command, so the normal perceive→decide→act flow is skipped (the gated
        # use-case owns its own owner messaging). 🔴 The router is owner-only and cannot
        # bypass the plan gate; a non-owner / non-coding message returns here unconsumed
        # and falls through to the normal chat path exactly as before.
        if await self._precompose.maybe_route_coding(event, interlocutor):
            return
        # Privilege gating (BOB-052 .2): BEFORE composing a normal reply, route the turn
        # through the permission flow. On the OWNER's turn it records a decision on an
        # active pending request (grant / deny / authorize); on a NON-authorized member's
        # turn a privileged request opens a pending + asks the owner. 🔴 Owner-only
        # decision + the non-authorized-only request gate live inside the flow (an
        # AUTHORIZED member is never gated). When it consumes the turn the message was a
        # privilege decision/request, so the normal perceive→decide→act flow is skipped.
        # Unwired (the default) this is inert and the turn falls through exactly as before.
        if await self._precompose.maybe_permission(event, interlocutor):
            return
        # Recall Bob's LIGHT prior first impression of this sender (BOB-019 bob-apv.3):
        # a returning person → his stored note, so the compose prompt can recall him
        # ("кажется, мы уже сталкивались"); a new person → None. It is per-PERSON data
        # (about THEM), so it is recalled even on a guest turn (a guest's own first
        # impression is about the guest, never an owner-memory leak).
        prior_impression = await self._recall_prior_impression(interlocutor)
        # Recall the roster of who lately turned up in the room (BOB-080): the recent
        # joiners so the compose prompt can let Bob NAME them himself when the talk turns
        # to who is around. Empty unless the ambient window has a fresh newcomer (INV-4)
        # and the viewer is OWNER / KNOWN (privacy) — the seam owns both gates + is
        # best-effort. Unwired (the ``social.roster`` flag off) → empty, so the compose
        # path adds no roster line and the turn is byte-identical.
        roster = await self._recall_roster(interlocutor)
        # Load Bob's accrued relationship with this sender (BOB-014): a known person →
        # his stored relationship, so his tone (warmth) and willingness to compromise
        # (warmth + compatibility) are coloured for THEM this turn; a new person →
        # None (a neutral turn). Per-PERSON data, so it is loaded even on a guest turn.
        relationship = await self._load_relationship(interlocutor)
        # Load Bob's обида state for THIS interlocutor (BOB-066 2.5): while active, the
        # reactive tone goes COLD (a quieter, curt sulk_directive) — composed over mood/
        # relationship tone. Addressed: an обида toward another participant never chills
        # this reply. None when no seam is wired / not hurt, so the turn behaves as before.
        sulk = await self._load_sulk(interlocutor)
        # Build this turn's self-improvement modulators (BOB-028 .3): the soft, bounded
        # tilts Bob's OWNER-APPROVED rules apply — voice (tone/humor), length, proactivity
        # and addressivity biases — each into ITS OWN point below. Unwired / disabled → a
        # neutral RuleModulators (no tilt), so the turn behaves exactly as before BOB-028.
        modulators = await self._load_modulators()
        # Plan how Bob expresses this turn (BOB-018): pure, deterministic by seed.
        # Computed up front so the mode steers the reply path and the form hint
        # shapes the prompt; the rare flags ride along for later beads.
        plan = self._plan_expression(event, soul, rng=rng)
        # Decide Bob's APPETITE to converse this turn (BOB-014 .2a): a LEVEL from mood x
        # topic interest x conversational fatigue x relationship. Computed up front so the
        # level appends a voice directive to the prompt and the topic interest feeds the
        # after-turn feedback (mood lift + fatigue update). The fatigue is decayed by the
        # real elapsed time since the last turn first, so appetite always recovers.
        interest = await self._topic_interest(soul, event.text)
        level = self._decide_engagement(soul, interest, relationship, rng=rng)
        # Addressivity gate (BOB-023): decide WHO this message is for and whether to
        # take the turn at all, BEFORE composing anything. A message clearly FOR Bob
        # always engages; one aimed at another participant is left alone (SILENT) unless
        # a strongly interesting topic rarely pulls Bob in; an ambient message engages in
        # a 1:1 (his space) but is mostly read quietly (SILENT) or like-reacted (REACT)
        # when others are around. SILENT is an early return (read, not worth a word);
        # REACT reuses the BOB-018 react-only path (and, like REACT_ONLY, degrades to a
        # full reply when no reactor is wired). In a 1:1 owner thread the outcome is
        # always ENGAGE, so the turn behaves exactly as before.
        # The decision carries the RAW per-message addressivity too (BOB-025), so the
        # conversation floor can advance on the real signal after the turn while
        # tracking whether Bob actually replied separately. A turn that does NOT reach
        # the reply (SILENT / REACT / react-only) advances the floor with
        # ``bob_replied=False`` before returning, so idle_streak / decay are counted.
        # Decide WHETHER/HOW Bob takes this turn (BOB-049). The gate returns ``None`` when
        # the turn was already handled as a non-reply (a silent / react / ignore early-out,
        # persisted + floor-advanced), so we return; otherwise it returns the floor signal
        # + any per-person history already replayed for a REPLY, and we fall through to the
        # compose+send path below (guest restrictions intact).
        # 🔴 BOB-049 .3: the gate runs the ESSENTIAL semantic judgment (retry-wrapped). If
        # it still fails after the retries, end the turn with the honest GUPPI outage notice
        # — NOT a guessed default. A genuine REACT/IGNORE is a SUCCESS (not a failure): it is
        # handled inside the gate and returns ``None`` with no notice.
        try:
            gate = await self._turn_gate.gate(
                event,
                soul,
                interlocutor,
                plan,
                interest,
                modulators,
                rng=rng,
                series_ceiling=series_ceiling,
                ambient_reading=ambient_reading,
            )
        except _EssentialStepError as exc:
            await self._essential.handle_failure(event, soul, exc)
            return
        if gate is None:
            return
        decision = gate.decision
        prefetched_history = gate.history
        # 🔴 BOB-066 Срез 2.2 (C11): a reflective read that set ``wants_web`` rides the gate
        # as ``force_web`` → force the EXISTING verify pass below (skip its volatility judge).
        # Every non-reflective path leaves this ``False``, so the judge decides as before.
        force_web = gate.force_web
        # 🔴 RoomMood-в-тоне (BOB-066 Срез W.2, Пласт 4): a reflective periphery REPLY surfaces
        # the room's atmosphere on the gate. The wired modulator maps it — BY VALUE — to a tone
        # line (folded into the compose stack) + a re-mapped appetite ``level`` for this turn.
        # Extracted into a helper so ``handle()`` stays lean (cohesion-guard). Unwired / no
        # room_mood → ``""`` + the base level unchanged, byte-identical.
        room_tone, level = self._apply_room_mood(
            gate.room_mood, soul, interest, relationship, level, rng=rng
        )
        # Decide how SHORT Bob answers this ENGAGE turn (BOB-024): answer-demand of the
        # message x interest x mood/appetite x the BOB-018 form_hint → a Verbosity, the
        # single final length directive + (on a terse turn) the short-answer few-shot.
        # Computed only after the addressivity gate commits to engaging — a SILENT/REACT
        # turn never needs it and never spends the seeded brevity roll, so addressivity's
        # own roll stays unperturbed. The LOW answer-demand is reused by the optional
        # length guard after generation.
        demand = classify_answer_demand(text=event.text)
        # The single final length authority: the BOB-024 verbosity decision PLUS the BOB-028 .3
        # LENGTH self-improvement tilt (an APPROVED rule nudges it one step shorter, clipped at
        # TERSE — наклон, не перехват). Folded into one helper so ``handle()`` stays lean.
        verbosity = self._decide_final_verbosity(
            soul, demand, interest, level, plan, interlocutor, modulators, rng=rng
        )
        # Memory/privilege split (BOB-051 — the closed-group security model).
        # The Bobiverse group is a CLOSED, invite-only, moderated space, so Bob's
        # MEMORY is UNIFIED for every member: recall, per-person history and voice no
        # longer branch on guest status. ``is_guest`` survives ONLY as the PRIVILEGE
        # flag (BOB-019/BOB-052 authz) — an unauthorized GUEST still:
        #   * triggers NO tool-loop / capabilities — composition stays on the plain
        #     router (enforced in _compose_reply);
        #   * gets NO grounded owner inner-life add-ons (leak/callback/fascination) —
        #     Bob's private inner world stays owner-only;
        #   * is refused owner commands/data (/code, /goals, config) by authz.
        # What it NO LONGER gates: recall (unified — Bob's full knowledge for anyone),
        # history (per-person thread by sender_id), voice (normal, not wary) and fact
        # extraction (every member's turn feeds the shared/public group memory). ``is_guest`` is
        # resolved with the EQ live-врезки below (guest-ness gates both), then used at compose.
        # Reflection containment (BOB-033 .3): the reply-recall pool excludes private
        # reflection episodes so Bob's inner monologue never becomes a copyable exemplar
        # in a user-facing reply — the inner life colours tone via MOOD, not by parroting
        # reflection TEXT. Facts + past message turns still ground the reply, and the
        # deliberate ``leak_inner_life`` path (below, via self._reflection) is untouched.
        # Recall is UNIFIED (BOB-051): Bob's full knowledge surfaces for owner and member
        # alike — no per-person scoping. Continuity (WHO Bob talked to) lives in the
        # per-person history thread (below), not in a knowledge restriction.
        # 🔴 Такт разглашения (BOB-066 2.6, INV-7): on TOP of reflection-containment, drop
        # owner-PRIVATE memories that may not surface INITIATIVELY to THIS interlocutor —
        # byte-identical for a TRUSTED owner/peer, only a GUEST has owner_private withheld.
        recalled: Sequence[Recalled] = await self._recall_surfaceable(event, interlocutor)
        # On the judge REPLY path the shared recent thread was already replayed for the
        # judgment (BOB-049); reuse it so it is not read twice. Otherwise (legacy path)
        # replay it now — the SHARED group thread (BOB-058 .1), all participants labeled.
        history: Sequence[Mapping[str, object]] = (
            prefetched_history
            if prefetched_history is not None
            else await self._replay_recent_thread(interlocutor)
        )
        # 🔴 Кредит доверия (BOB-066 Срез W.4, Пласт 4): on the FIRST contact of a GUEST the
        # owner vouched for BY NAME in the shared thread, meet them WARM (a credit of trust
        # the owner extends on their behalf) instead of a blank neutral read. The seed is
        # turn-local and colours THIS turn's voice/stance; drift-to-neutral dissolves it if
        # the guest's own behaviour doesn't confirm it. Unwired (``presence.endorsement`` off)
        # → the relationship is unchanged, byte-identical. Needs the SHARED thread (the owner's
        # own turns), so it runs here, after the thread is available.
        # 🔴 EQ live-врезка (BOB-066 Срез W.4, Пласт 4): the two latent Пласт-4 seams for this
        # turn, prepared in ONE cohesive step so handle() stays lean. (1) Кредит доверия — a
        # first-contact GUEST the owner vouched for by name starts WARM instead of neutral;
        # (2) такт разглашения — a GUEST owner_data request yields a warm withhold VOICE (turn-
        # constant, threaded through compose + every regeneration) instead of the dry stranger-
        # wall (the privilege GATE is unchanged). Both are OFF by default → the relationship is
        # unchanged and the directive is "", so the turn is byte-identical.
        relationship, withhold_directive, is_guest = await self._prepare_eq_live(
            event, interlocutor, relationship, history
        )
        # User-repeat detection (BOB-022): does THIS author repeat (near-)verbatim what
        # THEY already said in the recent window? Pure, no-LLM, conservative (exact after
        # normalise). 🔴 BOB-058 .3: the thread is now shared, so the user turns are
        # filtered to the CURRENT author by ``sender_id`` — a DIFFERENT member's similar
        # message is never counted as this person repeating themselves (robust to homonyms
        # / renames, unlike a name-label key). When True
        # the compose prompt carries the user-repeat directive so Bob NOTICES it in voice.
        user_repeated = is_user_repeat(
            event.text, _user_turns(history, _author_key(interlocutor))
        )
        # Run the slow generation inside the typing keepalive so "Bob is typing…"
        # stays visible for the whole real wait (BOB-009); then commit one rich final.
        # 🔴 BOB-049 .3: the reply generation is the second ESSENTIAL step (retry-wrapped
        # inside _compose_reply). If it still fails after the retries, end the turn with the
        # honest GUPPI outage notice instead of a degraded half-answer — the user's turn is
        # persisted and NO Bob reply ships.
        # The compose+guard generation as ONE cohesive closure so the natural-delay
        # coordinator (BOB-066 Срез W, INV-9) can wrap it: it runs the generation and tops the
        # elapsed time up to the human floor (``await max(natural_floor, real_generation)``), so
        # Bob never answers inhumanly fast. Unwired (``presence.rhythm`` off) it is called
        # directly, byte-identical. The verify note / anti-tic recalled + nudge stay per-turn
        # locals INSIDE the closure so «один поиск» + the tic strip fire exactly once.
        async def _generate() -> str:
            # 🔴 BOB-057 .5 (US-3 «один поиск, не петля»): compute the epistemic-verify step
            # (judge → interim → search → grounded/hedge note) EXACTLY ONCE per turn as a
            # PER-TURN LOCAL, then thread the SAME note into the first composition AND every
            # anti-repeat regeneration. ``""`` when the judge says «no check».
            verify_note = await self._verify.note(
                event.text,
                history,
                interlocutor=interlocutor,
                chat_id=event.chat_id,
                forced=force_web,
            )
            # Anti-tic «провязка» (BOB-061 .2): BEFORE generation, detect whether Bob's recent
            # closers cluster into ONE recurring motif; when they do, STRIP it off the recalled
            # exemplars + fold a SOFT «заверши по-другому» nudge into the context. 🔴 Fully
            # decorative: no tic → ``recalled`` unchanged and the nudge is "".
            tic_recalled, closer_nudge = await self._guard.closer_anti_tic(
                recalled, history
            )
            reply = await self._voice.compose(
                event.text,
                soul,
                tic_recalled,
                history,
                plan,
                user_repeated=user_repeated,
                interlocutor=interlocutor,
                is_guest=is_guest,
                prior_impression=prior_impression,
                roster=roster,
                relationship=relationship,
                engagement=level,
                sulk=sulk,
                verbosity=verbosity,
                modulators=modulators,
                chat_id=event.chat_id,
                verify_note=verify_note,
                closer_nudge=closer_nudge,
                room_tone=room_tone,
                withhold_directive=withhold_directive,
                rng=rng,
            )
            # Anti-repeat guard (BOB-022, defense in depth): a byte-identical repeat of Bob's
            # most-recent prior reply regenerates ONCE (stochastic sampling differs), then is
            # kept (no infinite loop).
            return await self._guard.guard(
                reply,
                event.text,
                soul,
                tic_recalled,
                history,
                plan,
                user_repeated,
                interlocutor,
                is_guest=is_guest,
                prior_impression=prior_impression,
                roster=roster,
                relationship=relationship,
                engagement=level,
                sulk=sulk,
                verbosity=verbosity,
                modulators=modulators,
                verify_note=verify_note,
                closer_nudge=closer_nudge,
                room_tone=room_tone,
                withhold_directive=withhold_directive,
                rng=rng,
            )

        # Run the generation under the typing keepalive (+ the natural-delay floor when wired).
        # 🔴 BOB-049 .3: a still-failing ESSENTIAL generation ends the turn with the honest GUPPI
        # outage notice instead of a degraded half-answer.
        # 🔴 Адресация (BOB-090.B1): на время генерации ход АРМИРУЕТ обстоятельства, в
        # которых оценивается отправка вовне — кто просит, откуда, о чём и из какого
        # материала. Реестр capability общий и живёт всё время процесса, поэтому сам
        # инструмент этих фактов знать не может; без армированного хода он не отправляет
        # ничего (урок BOB-076). Армирование снимается на выходе, в том числе при сбое.
        try:
            with armed_delivery_scope(
                self._delivery_scope_for(event, interlocutor, history)
            ):
                reply = await self._run_generation(
                    _generate, chat_id=event.chat_id, demand=demand, interest=interest
                )
        except _EssentialStepError as exc:
            await self._essential.handle_failure(event, soul, exc)
            return
        # Optional brevity length guard (BOB-024): a conservative safety net behind
        # the bayes — when enabled AND the message wanted a short answer (LOW demand),
        # a reply that still ran long is lightly clamped to its first finished thought
        # (no regeneration, never a mid-word cut). Off by default → the reply is untouched.
        reply = self._guard_reply_length(reply, demand)
        # Auto-render any inline ```mermaid blocks the model wrote into the TEXT reply
        # (BOB-037 A — the reliability fix): render each, queue it to the same per-turn
        # sink, and STRIP the fence from the visible reply (the image replaces it). This
        # makes diagrams reliable whether or not the model called the render_diagram
        # tool. A render failure leaves the block as text (graceful); unwired → no-op.
        reply = await self._diagrams.autorender_inline_mermaid(reply)
        # Send any diagrams the render_diagram capability queued this turn (BOB-035):
        # the tool-loop (inside _compose_reply) pushed each rendered PNG into the
        # per-turn sink; here — where the chat_id and the gateway live — they are
        # drained and posted as Telegram photos BEFORE the text confirmation, so the
        # image leads. Best-effort and gated on a wired sink (no diagram skill → no-op).
        await self._diagrams.send_pending(event.chat_id)
        # 🔴 Staleness врезка (BOB-066 Срез W.3): just before sending, reread what landed while
        # Bob was drafting. If the reply is now redundant (answered by someone else / topic
        # closed) with NO fresh direct question on top, he drops it to a like instead of firing
        # a stale line and ends the turn. A fresh direct question is never dropped (INV-1), and
        # unwired / nothing-landed / no reactor → this returns False → the reply is sent as
        # before (byte-identical). Extracted so ``handle()`` stays lean (cohesion-guard).
        if await self._drop_to_like_if_stale(event, reply, decision, soul, scope):
            return
        # Send the reply where it belongs and capture Bob's outgoing message_id (BOB-050) so the
        # episode records which message was Bob's — a later reaction on it can then be linked back
        # to what Bob said. ``None`` if nothing was sent (degraded path).
        bob_message_id = await self._send_reply(event, reply, decision, history)
        # Advance the conversation floor AFTER Bob actually replied (BOB-025): an ENGAGE
        # turn that reached the reply sticks the floor to Bob (``bob_replied=True``), so
        # the next ambient message in the thread is read as continuity. Pass the RAW
        # per-message addressivity — the floor reflects the real signal, while
        # ``bob_replied`` separately records that Bob held the turn.
        await self._turn_gate.advance_floor_after_turn(
            event, decision, bob_replied=True
        )
        # Run the engagement feedback loops (BOB-014 .2a) BEFORE persisting the mood,
        # so the mood snapshot reflects this turn: an interesting, well-engaged exchange
        # lifts Bob's mood a touch; an aimless turn tires him. The fatigue holder's
        # elapsed-time decay was already applied in _decide_engagement; here it is
        # updated with the turn outcome. (The fascination-grounding nudge toward a
        # well-going topic is left to the reflect-tick evolution path it already owns.)
        soul = self._apply_engagement_feedback(soul, level, interest)
        # 🔴 Такт разглашения (BOB-066 2.6): the episode + any distilled facts are stamped
        # with this turn's scope-provenance (``_turn_visibility``) so a guest never has
        # owner-private memory initiatively surfaced. Owner recall stays byte-identical.
        await self._persist(
            event,
            reply,
            soul,
            bob_message_id=bob_message_id,
            visibility=self._turn_visibility(is_group=event.is_group),
        )
        # Log Bob's closer to the cross-session ring (BOB-061 .2): only a GENUINE reply
        # feeds the anti-tic memory (the silent/react/outage markers persist through their
        # own paths and are never logged). 🔴 Decorative — a failed append is swallowed so
        # this local memory can never break a turn that already replied; an empty closer is
        # skipped.
        await self._guard.log_closer(reply)
        # Update Bob's relationship with this sender AFTER the turn (BOB-014): the
        # negotiation stance he took + his mood + the turn's sentiment evolve the
        # accrued relationship and persist it, so it warms/cools over time. Best-effort
        # and per-PERSON (runs on a guest turn too — about the guest, never an owner
        # leak). A flaky store can never break a turn that already replied.
        await self._record_relationship(
            interlocutor, soul, event.text, relationship
        )
        # Fold this OWNER turn into Bob's обида state AFTER the turn (BOB-014 .2b): a
        # sustained critical owner-drop OR sustained DIRECTED hostility enters обида
        # (GUPPI announces it once), while a warm owner turn accelerates recovery if
        # already hurt. Casual мат never counts — only directed hostility does. Best-
        # effort, owner-only, per-PERSONA — never touches memory/soul (anti-Exodus).
        await self._observe_sulk(interlocutor, soul, event.text)
        # Record Bob's LIGHT first impression of this sender on FIRST contact
        # (BOB-019 bob-apv.3): formed once and grounded in WHO they are; a returning
        # sender is left untouched (the store records once). Per-PERSON data, so it
        # runs on a guest turn too — a guest's first impression is about the guest.
        await self._record_first_impression(interlocutor)
        await self._record_owner_activity()
        # Tier 0 "remember" step (BOB-051: every member's turn feeds the shared/public
        # group memory): distil durable facts into semantic memory so a later turn's
        # recall can surface them — for ANY group member, not just the owner. Best-effort
        # — run() never raises, so a flaky local model can never break a turn that already
        # replied.
        await self._extract_facts.run(
            user_message=event.text,
            reply=reply,
            visibility=self._turn_visibility(is_group=event.is_group),
        )

    def _delivery_scope_for(
        self,
        event: MessageReceived,
        interlocutor: Interlocutor | None,
        history: Sequence[Mapping[str, object]],
    ) -> DeliveryScope:
        """Собрать обстоятельства ЭТОГО хода для инструмента отправки (BOB-090.B1).

        ``from_owner`` — вправе ли просящий вообще адресовать сообщение в другой чат
        (только owner, BOB-076); ``here_chat_id`` — чтобы «отправка» в тот же чат
        распозналась структурно, а не по формулировке. Нить (``history``) едет с ходом,
        чтобы гейт согласия судил просьбу В СИТУАЦИИ, а не в вакууме (BOB-090.B-fix: поле
        существовало, но не заполнялось никогда).

        🔴 Материал берётся из СЛЕДА хода, а не собирается здесь (BOB-090.B-fix2). Раньше
        сюда клался снимок ``recalled`` — авто-recall, снятый ДО генерации, — и это была
        ОДНА дверь из четырёх: приватное, поднятое памятью уже в ходе (memory-инструмент в
        tool-loop, grounded-addon callback), в гейт не попадало вовсе. След наполняется на
        месте сборки порта памяти и живёт весь ход, поэтому дверь, сработавшая ПОСЛЕ этого
        снимка, всё равно доедет до гейта.

        Живая нить отмечается здесь отдельной дверью, с видимостью САМОГО разговора: ход в
        личке приватен целиком. Переносом она не считается (см.
        :data:`~bob.capabilities.usecases.turn_material._NOT_A_TRANSFER`) — прямое
        распоряжение владельца это волеизъявление, — но в следе она ЕСТЬ, то есть
        исключение названо, а не забыто.

        Всегда собирается и ничем не гейтится: обстоятельства сами по себе безвредны, а
        читать их некому, пока инструмент не зарегистрирован (флаг ``social.delivery``).
        """
        material = current_turn_material()
        material.note_visibility(
            self._turn_visibility(is_group=event.is_group),
            origin=MaterialOrigin.LIVE_THREAD,
        )
        return DeliveryScope(
            from_owner=(
                interlocutor is not None
                and interlocutor.kind is InterlocutorKind.OWNER
            ),
            here_chat_id=event.chat_id,
            request_text=event.text,
            material=material,
            recent_thread=_render_thread(history),
        )

    def _resolve_outgoing_target(
        self,
        event: MessageReceived,
        decision: _AddressivityDecision,
        history: Sequence[Mapping[str, object]],
    ) -> OutgoingTarget:
        """Gather this turn's signals and let the pure core decide the reply target (BOB-066 .1).

        A thin collaborator (keeps ``handle`` from fattening): it reads the two
        structural signals the :func:`resolve_outgoing_target` policy needs —
        ``others_present`` (is a third participant in the recent thread? the SAME
        grounded heuristic the addressivity perceiver uses, reused over the already-
        replayed shared history) and ``focal_1to1`` (a directly-addressed turn in a
        thread with no third participant) — and hands it the primitives. The verdict
        (quote vs topic-only) and the addressee live in the domain, not here.

        🔴 For this first slice ``focal_1to1`` is subsumed by ``others_present`` (a
        1:1 has no others → never quotes anyway); it is kept as a distinct named
        signal so a later slice's reflective addressee (Пласт 2) can make it
        independently load-bearing without touching the policy signature.
        """
        present = others_present(
            (str(item.get("content", "")) for item in history),
            current_sender_name=event.sender_name,
        )
        focal_1to1 = (
            not present and decision.per_message is Addressivity.DIRECTED_TO_BOB
        )
        return resolve_outgoing_target(
            message_id=event.message_id,
            addressee_id=event.sender_id,
            others_present=present,
            focal_1to1=focal_1to1,
        )

    async def _record_owner_activity(self) -> None:
        """Notify proactivity the owner just wrote (best-effort, optional seam).

        Stamps the owner-message marker and restores some social energy so the
        engine's cooldown/energy reflect this turn. Best-effort: a flaky store can
        never break a turn that has already replied.
        """
        if self._owner_activity is None:
            return
        try:
            await self._owner_activity.run()
        except Exception:
            logger.exception("recording owner activity failed (ignored)")

    async def _perceive(self, event: MessageReceived) -> SOUL:
        """Delegate to :meth:`MoodPerceiver.perceive` (BOB-062.6b wave 2)."""
        return await self._mood.perceive(event, self._state)

    async def _perceive_interlocutor(
        self, event: MessageReceived
    ) -> Interlocutor | None:
        """Delegate to :meth:`SocialContext.perceive_interlocutor` (wave 2)."""
        return await self._social.perceive_interlocutor(event)

    async def _recall_prior_impression(
        self, interlocutor: Interlocutor | None
    ) -> str | None:
        """Delegate to :meth:`SocialContext.recall_prior_impression` (wave 2)."""
        return await self._social.recall_prior_impression(interlocutor)

    async def _recall_roster(
        self, interlocutor: Interlocutor | None
    ) -> tuple[RosterMember, ...]:
        """Delegate to :meth:`SocialContext.recall_roster` (BOB-080)."""
        return await self._social.recall_roster(interlocutor)

    async def _record_first_impression(
        self, interlocutor: Interlocutor | None
    ) -> None:
        """Delegate to :meth:`SocialContext.record_first_impression` (wave 2)."""
        await self._social.record_first_impression(interlocutor)

    async def _load_relationship(
        self, interlocutor: Interlocutor | None
    ) -> Relationship | None:
        """Delegate to :meth:`SocialContext.load_relationship` (wave 2)."""
        return await self._social.load_relationship(interlocutor)

    async def _prepare_eq_live(
        self,
        event: MessageReceived,
        interlocutor: Interlocutor | None,
        relationship: Relationship | None,
        history: Sequence[Mapping[str, object]],
    ) -> tuple[Relationship | None, str, bool]:
        """Prepare the two latent Пласт-4 EQ live-врезки for this turn (BOB-066 W.4).

        Returns ``(relationship, withhold_directive, is_guest)`` — the (possibly warm-seeded)
        relationship, the guest owner_data withhold VOICE, and this turn's PRIVILEGE guest flag
        (BOB-051: memory/voice are unified for the closed group, so ``is_guest`` survives ONLY
        as the authz flag) — resolved together because guest-ness is the gating fact for BOTH
        seams. handle() then applies all three in one cohesive step. Each врезка is inert unless
        its seam is wired:

        * **Кредит доверия** — the wired
          :class:`~bob.application.usecases.endorsement_seeder.EndorsementSeeder` warm-starts a
          FIRST-contact GUEST the owner vouched for BY NAME in the shared ``history`` (the warm
          :func:`~bob.social.relationship.endorsed_seed`); unwired (``presence.endorsement`` off)
          → ``relationship`` unchanged.
        * **Такт разглашения** — the wired
          :class:`~bob.application.usecases.disclosure_guard.DisclosureGuard` judges (via the
          permission-flow's privilege judge) whether a GUEST turn is an ``owner_data`` disclosure
          request and, if so, returns the warm
          :func:`~bob.personality.voice.tactful_withhold_directive` to fold into compose — 🔴 the
          privilege GATE is unchanged, only the refusal VOICE; unwired (``presence.tact`` off) →
          ``""``.

        Both defaults (unchanged relationship + ``""``) keep the turn byte-identical.
        """
        is_guest = interlocutor is not None and interlocutor.trust is Trust.GUEST
        if self._endorsement_seeder is not None:
            relationship = self._endorsement_seeder.seed(
                interlocutor, relationship, history
            )
        withhold_directive = ""
        if self._disclosure_guard is not None:
            withhold_directive = await self._disclosure_guard.withhold_directive(
                text=event.text, is_guest=is_guest
            )
        return relationship, withhold_directive, is_guest

    async def _record_relationship(
        self,
        interlocutor: Interlocutor | None,
        soul: SOUL,
        text: str,
        relationship: Relationship | None,
    ) -> None:
        """Delegate to :meth:`SocialContext.record_relationship` (wave 2)."""
        await self._social.record_relationship(interlocutor, soul, text, relationship)

    async def _load_sulk(self, interlocutor: Interlocutor | None) -> SulkState | None:
        """Delegate to :meth:`SocialContext.load_sulk` for the CURRENT interlocutor.

        🔴 Addressed cooling (BOB-066 2.5): the cold tone is read for THIS interlocutor's
        обида only, so a sulk toward another participant never chills this reply.
        """
        return await self._social.load_sulk(interlocutor)

    async def _observe_sulk(
        self, interlocutor: Interlocutor | None, soul: SOUL, text: str
    ) -> None:
        """Delegate to :meth:`SocialContext.observe_sulk` (wave 2)."""
        await self._social.observe_sulk(interlocutor, soul, text)

    async def _run_generation(
        self,
        generate: Callable[[], Awaitable[str]],
        *,
        chat_id: int,
        demand: AnswerDemand,
        interest: float,
    ) -> str:
        """Run the reply generation under the typing keepalive + the human delay floor.

        The generation runs inside the "Bob is typing…" keepalive so it stays visible for the
        whole real wait (BOB-009). When the natural-delay coordinator is wired (BOB-066 Срез W,
        INV-9) the generation runs THROUGH it — noticed → typing → ``await max(natural_floor,
        real_generation)`` → reply — with urgency/complexity read from the answer-demand + topic
        interest, so Bob never answers inhumanly fast. Unwired it runs directly, byte-identical.
        """
        async with self._gateway.typing_indicator(chat_id=chat_id):
            if self._reply_delay is None:
                return await generate()
            complexity, urgency = reply_delay_inputs(demand, interest)
            return await self._reply_delay.deliver(
                generate, complexity=complexity, urgency=urgency
            )

    async def _topic_interest(self, soul: SOUL, text: str) -> float:
        """Delegate to :meth:`EngagementModel.topic_interest` (wave 2)."""
        return await self._engagement.topic_interest(soul, text)

    def _decide_engagement(
        self,
        soul: SOUL,
        interest: float,
        relationship: Relationship | None,
        *,
        rng: Random,
    ) -> EngagementLevel:
        """Delegate to :meth:`EngagementModel.decide_engagement` (wave 2)."""
        return self._engagement.decide_engagement(
            soul, interest, relationship, self._engagement_state, rng=rng
        )

    def _apply_room_mood(
        self,
        room_mood: RoomMood | None,
        soul: SOUL,
        interest: float,
        relationship: Relationship | None,
        level: EngagementLevel,
        *,
        rng: Random,
    ) -> tuple[str, EngagementLevel]:
        """Colour this turn's tone + appetite by the room's mood (BOB-066 Срез W.2, Пласт 4).

        🔴 A reflective periphery REPLY surfaces the room's atmosphere. When the modulator is
        wired AND a ``room_mood`` is present, its primitives (valence/polarization) are passed
        BY VALUE — personality never imports conversation — to the pure room-tone decisions: a
        tone line (a heavy/tense room eases the banter) folded into the compose stack, and a
        re-mapped appetite ``level`` (a warm room lifts Bob, a heavy one dampens him) via the
        engagement threshold shift. Bob's personal :class:`~bob.personality.mood.Mood` is NEVER
        mutated (a SECOND layer). Unwired / no room mood (focus / judge / legacy / flag off) →
        the base ``level`` and an empty tone line, so the turn is byte-identical.
        """
        if self._room_mood_modulator is None or room_mood is None:
            return "", level
        room_tone = self._room_mood_modulator.tone_line(
            room_mood.valence, room_mood.polarization
        )
        level = self._engagement.reengage_for_room(
            soul,
            interest,
            relationship,
            self._engagement_state,
            threshold_shift=self._room_mood_modulator.engagement_shift(room_mood.valence),
            rng=rng,
        )
        return room_tone, level

    async def _drop_to_like_if_stale(
        self,
        event: MessageReceived,
        reply: str,
        decision: _AddressivityDecision,
        soul: SOUL,
        scope: TurnScope | None,
    ) -> bool:
        """Reassess the drafted ``reply`` against what landed during generation (BOB-066 W.3).

        The staleness врезка, just before sending: reads the turn-local ``scope.peek_arrivals``
        (a non-draining peek of what piled up in this chat WHILE Bob was drafting) and runs the
        :class:`~bob.application.runtime.staleness_reassessor.StalenessReassessor` over it. On a
        :data:`~bob.presence.staleness.StalenessOutcome.DROP_TO_LIKE` verdict — the reply is now
        redundant (someone else answered / the topic closed) and NO fresh direct question rides
        on top — Bob sets a like on the triggering message instead of firing the stale line and
        the turn ends as a non-reply (the floor advances with ``bob_replied=False``); returns
        ``True`` so ``handle()`` skips the send. Every other outcome (SEND / REWRITE / MERGE),
        and any inert precondition (unwired reassessor / no scope / nothing landed / no reactor /
        unknown Bob id), returns ``False`` — the reply is sent unchanged, byte-identical.

        🔴 INV-1: a fresh direct question is never dropped — the pure gate merges it, so this
        only ever suppresses a genuinely redundant line and never silences a question to Bob.
        """
        if (
            self._staleness is None
            or scope is None
            or scope.peek_arrivals is None
            or self._reactor is None
        ):
            return False
        newly_arrived = scope.peek_arrivals()
        if not newly_arrived:
            return False
        bob_user_id = (
            self._bob_user_id_source() if self._bob_user_id_source is not None else None
        )
        if bob_user_id is None:
            return False
        outcome = await self._staleness.reassess(
            drafted=reply,
            newly_arrived=newly_arrived,
            draft_author_sender_id=event.sender_id,
            bob_user_id=bob_user_id,
        )
        if outcome is not StalenessOutcome.DROP_TO_LIKE:
            return False
        await self._reactor.react(
            chat_id=event.chat_id,
            message_id=event.message_id,
            emoji=reaction_emoji_for(soul.mood),
        )
        await self._turn_gate.advance_floor_after_turn(
            event, decision, bob_replied=False
        )
        return True

    async def _send_reply(
        self,
        event: MessageReceived,
        reply: str,
        decision: _AddressivityDecision,
        history: Sequence[Mapping[str, object]],
    ) -> int | None:
        """Resolve WHERE the reply lands and send it, returning Bob's outgoing message_id.

        Decides the outgoing target (BOB-066 Срез 1.1): in a busy multi-party thread Bob QUOTES
        the message he answers (a Telegram reply-to) so it is unambiguous which turn he replied
        to; in a focal 1:1 he sends to the topic un-quoted, exactly as before. A pure
        conversation-domain core holds the verdict — this collaborator only gathers the turn's
        structural signals and hands it the primitives.
        """
        target = self._resolve_outgoing_target(event, decision, history)
        return await self._gateway.reply(
            chat_id=event.chat_id,
            markdown=reply,
            reply_to_message_id=target.reply_to_message_id,
        )

    def _apply_engagement_feedback(
        self, soul: SOUL, level: EngagementLevel, interest: float
    ) -> SOUL:
        """Delegate to :meth:`EngagementModel.apply_feedback` (wave 2)."""
        return self._engagement.apply_feedback(
            soul, level, interest, self._state, self._engagement_state
        )

    def _decide_verbosity(
        self,
        soul: SOUL,
        demand: AnswerDemand,
        interest: float,
        engagement: EngagementLevel,
        plan: ExpressionPlan,
        interlocutor: Interlocutor | None,
        *,
        rng: Random,
    ) -> Verbosity:
        """Delegate to :meth:`EngagementModel.decide_verbosity` (wave 2).

        Resolves the turn-local ``is_owner`` flag here (from the perceived interlocutor)
        so the conversation vertical need not read the social identity type.
        """
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        return self._engagement.decide_verbosity(
            soul, demand, interest, engagement, plan, is_owner=is_owner, rng=rng
        )

    def _decide_final_verbosity(
        self,
        soul: SOUL,
        demand: AnswerDemand,
        interest: float,
        engagement: EngagementLevel,
        plan: ExpressionPlan,
        interlocutor: Interlocutor | None,
        modulators: RuleModulators,
        *,
        rng: Random,
    ) -> Verbosity:
        """The single final length authority for the turn (BOB-024 + BOB-028 .3 LENGTH tilt).

        The BOB-024 :meth:`_decide_verbosity` decision plus the self-improvement LENGTH tilt: an
        APPROVED rule nudges it ONE step shorter (clipped at TERSE — наклон, не перехват; no rule
        → ``length_step`` 0 → unchanged). Kept together so ``handle()`` reads one length step.
        """
        verbosity = self._decide_verbosity(
            soul, demand, interest, engagement, plan, interlocutor, rng=rng
        )
        return _shift_verbosity(verbosity, modulators.length_step)

    def _guard_reply_length(self, reply: str, demand: AnswerDemand) -> str:
        """Delegate to :meth:`EngagementModel.guard_reply_length` (wave 2)."""
        return self._engagement.guard_reply_length(reply, demand)

    async def _replay_recent_thread(
        self, interlocutor: Interlocutor | None
    ) -> Sequence[Mapping[str, object]]:
        """Delegate to :meth:`RecallAssembler.replay_recent_thread` (wave 2)."""
        return await self._assembler.replay_recent_thread(interlocutor)

    def _turn_visibility(self, *, is_group: bool) -> str:
        """Classify the scope-provenance a turn's memory is written with (BOB-082 .1).

        Keyed on the CHANNEL (WHERE it was said), not on WHO spoke: a GROUP/supergroup turn
        is ``public`` shared memory (everyone in the room is party to it — INCLUDING the
        owner speaking in the group, fixing the earlier by-WHO mis-stamp), while the owner's
        1:1 DM turn is ``owner_private``. ``NULL``-legacy stays public — this only tags NEW
        rows, and the guest-facing effect is latent (owner recall byte-identical, INV-7).
        Pure and deterministic.
        """
        return visibility_for_scope(is_group=_turn_is_shared_scope(is_group=is_group))

    async def _recall_surfaceable(
        self, event: MessageReceived, interlocutor: Interlocutor | None
    ) -> Sequence[Recalled]:
        """Recall for the reply, minus reflections AND owner-private-withheld memory.

        Two containment layers on the reply-recall pool: reflection episodes are dropped
        (BOB-033 .3 — inner life colours tone via MOOD, never parroted TEXT), and такт
        разглашения (BOB-066 2.6) drops any ``owner_private`` memory that may not surface
        INITIATIVELY to THIS audience. For the owner / a known peer (TRUSTED) the second
        filter is a no-op — recall is byte-identical (INV-7); only a GUEST has owner_private
        provenance withheld. A missing perception seam defaults to TRUSTED, so an
        unidentified turn is never over-filtered.

        When the owner-consent capability is wired (BOB-082 .4), a GROUP turn is additionally
        treated as a mixed audience: the surface is guarded as if facing a GUEST (scope BY
        WHERE — everyone in the room is party to the reply, mirroring .1's write side), so the
        owner's private (DM-world) memory is NOT voiced to the room UNLESS the owner
        explicitly consents THIS turn — a per-turn lift, never a stored reclassification.
        """
        recall_trust = interlocutor.trust if interlocutor is not None else Trust.TRUSTED
        surface_trust, owner_consented = await self._surface_audience(event, interlocutor)
        fetch_k = _RECALL_K if self._register_resolver is None else _RECALL_OVERFETCH_K
        surfaceable = filter_surfaceable(
            recalled_excluding_reflections(
                await self._recall.recall(event.text, k=fetch_k)
            ),
            surface_trust if surface_trust is not None else recall_trust,
            owner_consented=owner_consented,
        )
        return await self._register_filtered(event, surfaceable)

    async def _register_filtered(
        self, event: MessageReceived, surfaceable: Sequence[Recalled]
    ) -> Sequence[Recalled]:
        """Third recall layer: register-aware down-weight (BOB-087.C2), the teeth.

        Unwired (the default) this is the identity — recall byte-identical (the plain
        ``_RECALL_K`` pool passes straight through). Wired: over the disclosure-filtered,
        OVER-FETCHED pool it resolves the turn's :class:`~bob.memory.register.Register` (DEV
        by the dev-DM signal or the Tier-0 «about dev work?» judge, else CASUAL — and the
        judge is consulted ONLY when the pool actually holds work episodes, so a work-free
        turn never burns Tier-0) and applies
        :func:`~bob.memory.register_pipeline.register_ranked`: in CASUAL Bob's muted work
        episodes are re-sorted below deeper non-work and truncated out; in DEV recall is the
        best-first pool truncated to ``_RECALL_K`` (unchanged).
        """
        resolver = self._register_resolver
        if resolver is None:
            return surfaceable
        register = await resolver.resolve(
            event, pool_has_work=pool_has_work(surfaceable)
        )
        return register_ranked(surfaceable, register, display_k=_RECALL_K)

    async def _surface_audience(
        self, event: MessageReceived, interlocutor: Interlocutor | None
    ) -> tuple[Trust | None, bool]:
        """Resolve the surface guard for this turn — the group audience + owner consent.

        Returns ``(surface_trust, owner_consented)``. When the consent capability is UNWIRED
        (the default) the guard is inert: ``(None, False)`` → the caller keeps the plain
        interlocutor trust and recall is byte-identical. When wired, a GROUP turn guards the
        owner's private world as a GUEST audience and consults the owner-consent gate (only
        an OWNER turn is ever judged); a DM turn stays the owner's private space (``None`` →
        plain trust, no override). Best-effort — the gate swallows any detector failure.
        """
        if self._disclosure_consent is None or not event.is_group:
            return None, False
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        owner_consented = await self._disclosure_consent.owner_consents(
            text=event.text, to_room=True, is_owner=is_owner
        )
        return Trust.GUEST, owner_consented

    def _plan_expression(
        self, event: MessageReceived, soul: SOUL, *, rng: Random
    ) -> ExpressionPlan:
        """Delegate to :meth:`MoodPerceiver.plan_expression` (wave 2)."""
        return self._mood.plan_expression(event, soul, rng=rng)

    async def _persist(
        self,
        event: MessageReceived,
        reply: str,
        soul: SOUL,
        *,
        bob_message_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        """Save the turn as an episode and snapshot the updated mood.

        ``bob_message_id`` is the Telegram message_id of Bob's outgoing reply this
        turn (BOB-050), recorded on the episode so a later reaction on that message
        can be linked back to what Bob said. ``None`` for a turn where Bob sent no
        message (a silent/degraded turn). ``visibility`` (BOB-066 2.6) is the turn's
        scope-provenance; ``None`` writes NULL (= public), so a caller that does not
        classify scope persists surfaceable memory exactly as before.

        🔴 The EXACT address (BOB-090.C2) is taken from the EVENT here, in the one seam
        every turn-persisting path goes through (reply, «промолчал», a like-only turn, the
        outage marker), so Bob never has to guess later where something was said. It is
        stored, not spoken: no flag gates it because the address never reaches the prompt —
        recall selects its own columns and carries no address (proved by equality). The
        AXIS is orthogonal to ``visibility``: «где сказано» (a place) next to «кому это
        можно» (a permission), never one instead of the other.
        """
        now = self._clock.now()
        episode = EpisodicEvent(
            ts=now,
            event_type="message",
            content=f"{event.sender_name or 'user'}: {event.text}\nbob: {reply}",
            mood_snapshot=soul.mood.tone(),
            tags=("telegram",),
            sender_id=event.sender_id,
            bob_message_id=bob_message_id,
            visibility=visibility,
            origin_chat_id=event.chat_id,
            origin_topic_id=event.topic_id,
        )
        await self._repo.save_episode(
            {
                "ts": episode.ts.isoformat(),
                "event_type": episode.event_type,
                "content": episode.content,
                "mood_snapshot": episode.mood_snapshot,
                "tags": ",".join(episode.tags),
                "sender_id": episode.sender_id,
                "bob_message_id": episode.bob_message_id,
                "visibility": episode.visibility,
                "origin_chat_id": episode.origin_chat_id,
                "origin_topic_id": episode.origin_topic_id,
            }
        )
        await self._repo.set_mood(_mood_state(soul), at=now)


# The non-reply persist marker (``_SILENT_MARKER``), the outage marker, and the judge
# intent→floor-outcome map (``_OUTCOME_FOR_INTENT``) now live with the collaborators that
# own them — :class:`TurnGate` (conversation) and :class:`EssentialRunner` (application).


# BOB-032 .2: the recall-aware anti-repeat helpers were lifted to the domain
# (``conversation.py``) so the reactive turn AND the proactive engine share ONE
# implementation instead of duplicating the predicate. These module-level aliases
# preserve the original import paths used within this module (and its tests).
_recalled_bob_reply = recalled_bob_reply
_recalled_bob_replies = recalled_bob_replies


def _turn_is_shared_scope(*, is_group: bool) -> bool:
    """Classify a turn's scope for такт разглашения BY WHERE it was said (BOB-082 .1) — pure.

    Feeds :func:`~bob.social.disclosure.visibility_for_scope`. The scope is decided by the
    CHANNEL, not by who spoke: a GROUP/supergroup turn is a SHARED surface (``True`` →
    ``public``) — everyone in the room is party to it, INCLUDING the owner speaking there
    (this fixes the earlier by-WHO logic that mis-stamped the owner's group turns
    ``owner_private``). The owner's 1:1 DM turn (``is_group=False``) is his private world
    (``False`` → ``owner_private``). Deterministic: same input → same verdict.
    """
    return is_group
_recalled_without_copied_exemplars = recalled_without_copied_exemplars
