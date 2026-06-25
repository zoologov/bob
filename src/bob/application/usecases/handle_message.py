# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

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

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.capabilities.tool_loop import ToolLoop
from bob.application.router.llm_router import LLMRequest, TaskType
from bob.application.router.reply_tier_selector import select_reply_tier
from bob.application.usecases.update_mood_from_text import TextSignals
from bob.domain.diagrams import (
    extract_mermaid_blocks,
    normalize_mermaid,
    strip_mermaid_blocks,
)
from bob.domain.memory.entities import EpisodicEvent
from bob.domain.personality.addressivity import (
    Addressivity,
    AddressivityThresholds,
    ResponseOutcome,
    classify_addressivity,
    decide_response,
    others_present,
)
from bob.domain.personality.brevity import (
    AnswerDemand,
    BrevityThresholds,
    Verbosity,
    clamp_reply,
    classify_answer_demand,
    decide_verbosity,
)
from bob.domain.personality.conversation import (
    RepeatThresholds,
    is_bob_repeat,
    is_phrase_tic,
    is_user_repeat,
    recalled_bob_replies,
    recalled_bob_reply,
    recalled_excluding_reflections,
    recalled_without_copied_exemplars,
)
from bob.domain.personality.conversation_floor import (
    FloorConfig,
    advance_floor,
    resolve_addressivity,
)
from bob.domain.personality.engagement import (
    ConversationalFatigue,
    EngagementLevel,
    EngagementThresholds,
    FatigueRates,
    appetite_of,
    decide_engagement,
    engagement_mood_lift,
    topic_interest,
)
from bob.domain.personality.expression import (
    ExpressionFreqs,
    ExpressionMode,
    ExpressionPlan,
    ExpressionSignals,
    decide_expression,
)
from bob.domain.personality.interlocutor import InterlocutorKind, Trust
from bob.domain.personality.mood import MoodDelta
from bob.domain.personality.mood_taste import experiment_bias, modulate
from bob.domain.personality.negotiation import (
    Negotiation,
    NegotiationZone,
    Stance,
)
from bob.domain.personality.profanity import is_directed_hostility
from bob.domain.personality.reaction import reaction_emoji_for
from bob.domain.personality.relationship import compromise_bias
from bob.domain.personality.self_improvement import RuleModulators, build_modulators
from bob.domain.personality.taste import Verdict
from bob.domain.personality.voice import (
    OffDayThresholds,
    RelationshipToneThresholds,
    anti_bait_directive,
    brevity_directive,
    brevity_few_shot,
    engagement_directive,
    guppi_canon,
    improvement_directive,
    profanity_stance,
    recalled_impression_directive,
    relationship_tone_directive,
    stranger_directive,
    sulk_directive,
    tone_directive,
    user_repeat_directive,
    variable_form_directive,
    who_is_writing_directive,
)
from bob.domain.personality.zone_classifier import TasteZoneClassifier
from bob.domain.ports import DiagramRenderError, DiagramResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime
    from random import Random

    from bob.application.router.llm_router import LLMRouter
    from bob.application.runtime.events import MessageReceived
    from bob.application.usecases.extract_facts import ExtractFacts
    from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
    from bob.domain.personality.fascination import Fascination
    from bob.domain.personality.interlocutor import Interlocutor
    from bob.domain.personality.mood import Mood
    from bob.domain.personality.relationship import Relationship
    from bob.domain.personality.self_improvement import ImprovementRule
    from bob.domain.personality.soul import SOUL
    from bob.domain.personality.sulk import SulkState
    from bob.domain.ports import (
        Clock,
        ConversationFloorStore,
        DiagramRenderer,
        DiagramSink,
        LLMMessage,
        MemoryRecall,
        MessageReactor,
        Recalled,
        ReflectionReader,
        ToolCallingProvider,
        ZoneClassifier,
    )

logger = logging.getLogger(__name__)

# How a rendered diagram is sent (BOB-037 C). ``document`` posts the PNG as an
# UNCOMPRESSED file (full resolution, tap → real pixels) — the product default, since
# Telegram ``send_photo`` recompresses to JPEG and caps the long side (~1280px), which
# makes a dense diagram unreadable. ``photo`` keeps the inline-preview photo.
type DiagramSendMode = Literal["document", "photo"]
_DEFAULT_DIAGRAM_SEND_AS: DiagramSendMode = "document"

# The short caption sent alongside an auto-rendered inline diagram (BOB-037 A): Bob's
# in-character Russian line, mirroring the render_diagram tool's caption.
_INLINE_DIAGRAM_CAPTION = "Вот диаграмма."

# How many memories to recall when assembling the reply context.
_RECALL_K = 5

# Max attractor-breaking regenerations the anti-repeat guard may draw before keeping the
# last draft (BOB-032 .1, R2). Each retry strips the recalled exemplar(s) the candidate
# copied; bounded so a stubborn repeat can never spin an infinite loop.
_MAX_REGENERATIONS = 2

# How many memories to recall for a BOB-018 callback: just the single strongest real
# past moment on the topic (a tight, grounded steer — never a memory dump).
_CALLBACK_RECALL_K = 1

# How often a callback turn reaches for an OLD-but-relevant memory instead of the
# default best hit (BOB-021 mechanism 1, "что-то напомнило"). On a callback (already
# rare/state-driven from BOB-018), a small extra draw occasionally asks recall for the
# surface_old blend so a deep cut can come back à propos — grounded, no-op when nothing
# old is relevant. Deliberately small (anti-tic); tunable via ``memory.surface_old.freq``.
_DEFAULT_SURFACE_OLD_FREQ = 0.15

# A frequency must read as a probability in the closed unit interval.
_MIN_FREQ = 0.0
_MAX_FREQ = 1.0

# Conviction is a [0, 1] strength; the relationship compromise-bias nudge must keep
# the effective conviction it feeds Negotiation inside those bounds.
_MIN_CONVICTION = 0.0
_MAX_CONVICTION = 1.0

# How many recent conversation turns to replay into the reply context.
_HISTORY_K = 6

# Default small mood-valence lift a good, interesting exchange earns (BOB-014 .2a
# feedback loop). Mirrors the engagement domain default; tunable via emotion.* config.
_DEFAULT_ENGAGEMENT_MOOD_LIFT = 0.1

# Each turn perceives one message; a present sender is engaged.
_SINGLE_MESSAGE = 1

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

# The base persona, then two voice concerns Bob's persona leans on (BOB-016): the
# anti-bait directive + few-shot (so he lands like a person, not an assistant
# fishing for the next reply with a ☕ signature), and the GUPPI canon (so whenever
# GUPPI comes up — tools wired or not — Bob speaks of him as "он", his non-sentient
# executor, with the wry running relationship). Both live in the domain (persona
# voice) and are assembled here. The TONE itself is no longer baked in as an
# unconditional "warmly and concisely" line: it is now mood-conditioned per turn via
# voice.tone_directive (BOB-020), appended in _system_prompt_for, so Bob can have an
# off-day instead of forcing warmth.
_SYSTEM_PROMPT = (
    "You are Bob, a digital person from the Bobiverse. Reply in character.\n"
    f"{guppi_canon()}\n"
    f"{anti_bait_directive()}\n"
    f"{variable_form_directive()}\n"
    # BOB-014 .2b: Bob's persona stance on profanity — calm about casual emphatic мат
    # (may quip back), registers hostility aimed AT him. Lives in the base persona so
    # the calm-about-profanity character is always present, not a per-turn filter.
    f"{profanity_stance()}"
)

# Final length authority (BOB-024). The old soft form_hint → length directive path
# (BOB-018) is GONE: it competed with this bead's decided Verbosity (two length
# signals). ``form_hint`` is now an INPUT to decide_verbosity (a mood-driven length
# lean), and the single final directive is voice.brevity_directive(verbosity) +
# voice.brevity_few_shot(verbosity) — a strong instruction plus, on a TERSE turn,
# the short-answer few-shot that actually beats Qwen's verbosity prior.

# Grounded add-on prefaces (BOB-018 wave 3). Both fold a REAL, persisted piece of
# Bob's inner life into the compose context behind the same grounding seam BOB-012
# uses — and are strictly anti-confabulation: with no real material they no-op, so
# Bob never invents a thought he didn't have or a moment that didn't happen. The
# prefaces are Russian persona voice (project language); Cyrillic look-alikes
# intentional, so the ambiguous-character lint is silenced for these literals.
_LEAK_PREFACE = (
    "То, о чём ты ловил себя на мысли, пока его не было (можешь обронить это "  # noqa: RUF001
    "к слову, естественно — не пересказывай дословно):"
)
_CALLBACK_PREFACE = (
    "Можешь к месту вспомнить это — реальный момент из вашего прошлого, "
    "не выдумывай деталей сверх него:"
)

# Fascination preface (BOB-020 wave 2). When the plan sets ``mention_fascination``
# AND Bob has a real, current passion (a persisted Fascination that has not faded),
# its topic is folded into the compose context so Bob can drop it à propos — it is
# his REAL state, never a fabricated interest. No current fascination → no line (a
# clean no-op). Russian persona voice; Cyrillic look-alikes intentional.
_FASCINATION_PREFACE = (
    "Можешь к месту обронить, чем сейчас увлечён — это твоё реальное состояние, "
    "не пересказывай как факт, просто упомяни живо, если в тему:"
)

# Preface for the capability manifest in Bob's prompt: GUPPI is Bob's executor
# subsystem (canon already in the base persona above), so this just frames the
# manifest as the skills GUPPI runs for Bob.
_CAPABILITY_PREFACE = (
    "Эти возможности GUPPI исполняет для тебя; вызови одну, когда она помогает "
    "ответить:"
)

# Stance→prompt directive (BOB-013 Phase 1): the negotiation stance augments —
# never replaces — the warm base tone, so Bob stays warm without being a yes-man.
# These are a pure mapping; no extra LLM call. A stance with no directive (none
# below) leaves the prompt exactly as it was before BOB-013.
_STANCE_DIRECTIVE: dict[Stance, str] = {
    # Russian persona directives (project language); Cyrillic look-alikes are
    # intentional, so the ambiguous-character lint is silenced for these literals.
    Stance.CONCEDE: "Стойка: это территория пользователя — спокойно прими его выбор.",  # noqa: RUF001
    Stance.AGREE: "Стойка: у тебя нет сильной позиции — поддержи, без навязывания.",  # noqa: RUF001
    Stance.PROPOSE_ALTERNATIVE: (
        "Стойка: у тебя есть своё мнение и убеждённость — аргументируй и предложи "  # noqa: RUF001
        "своё, уважительно, без агрессии и без капитуляции."
    ),
}


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
        self, *, chat_id: int, markdown: str, thinking: str | None = None
    ) -> None: ...

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


class CurrentFascinationReader(Protocol):
    """Read seam: Bob's CURRENT fascination, aged and still-alive (BOB-020 wave 2).

    On a :data:`~bob.domain.personality.expression.ExpressionPlan.mention_fascination`
    turn the compose path folds the topic in so Bob can drop it à propos — but only a
    REAL, persisted passion that has not yet faded. ``None`` means Bob has no current
    fascination, so the mention no-ops (never a fabricated interest). The concrete
    adapter loads the :class:`~bob.domain.ports.FascinationStore`, ages the stored
    passion against the clock, and drops a faded one.
    """

    async def current_fascination(self) -> Fascination | None:
        """Return Bob's current, non-faded fascination, or ``None`` if there is none."""
        ...


class InterlocutorResolver(Protocol):
    """Perception seam: WHO is writing this turn (BOB-019).

    Resolves the inbound :class:`MessageReceived` into an
    :class:`~bob.domain.personality.interlocutor.Interlocutor` — the sender's
    social identity (owner / known / guest / bot + trust) — so the compose path can
    fold WHO is on the other side into Bob's voice. The concrete adapter derives it
    from the :class:`~bob.application.authz.Authorizer` (``is_owner`` +
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
    (:class:`~bob.application.usecases.first_impression_sources.FirstImpressionTracker`)
    keys on ``sender_id`` and stamps the clock. Optional and additive: unwired (the
    default) Bob simply never recalls a first impression and the turn is unchanged.

    Crucially this is per-PERSON data (about THEM), NOT owner-private memory, so it
    is safe even on a guest turn — a guest's own first-impression is about the guest,
    and surfacing it never leaks the owner's private world.
    """

    async def prior_impression(self, interlocutor: Interlocutor) -> str | None: ...

    async def note_first_contact(self, interlocutor: Interlocutor) -> None: ...


class RelationshipReader(Protocol):
    """Relationship seam: load + evolve Bob's per-person relationship quality (BOB-014).

    The compose path uses this to let Bob's accrued relationship with WHO is writing
    shape THIS turn: :meth:`current` returns the stored
    :class:`~bob.domain.personality.relationship.Relationship` (an unknown sender →
    ``None``) so the prompt can warm/cool his tone (by ``warmth``) and the negotiation
    can nudge his willingness to compromise (by ``warmth`` + ``compatibility``);
    :meth:`record_interaction` updates + persists the relationship AFTER the turn from
    the negotiation ``stance``, Bob's ``mood``, and a ``sentiment`` scalar (the pure
    :func:`~bob.domain.personality.relationship.apply_interaction`). The concrete
    adapter (:class:`~bob.application.usecases.relationship_sources.RelationshipTracker`)
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
    """Sulk seam: load Bob's обида state + fold an owner turn into it (BOB-014 .2b).

    The compose path uses this to go COLD while Bob is hurt and to let обида take hold
    or warm up over the live message path: :meth:`current` returns the persisted
    :class:`~bob.domain.personality.sulk.SulkState` so the prompt appends the cold
    :func:`~bob.domain.personality.voice.sulk_directive` while ``active``;
    :meth:`observe` folds ONE owner turn's signals (the relationship ``owner_warmth``,
    a ``hostile`` directed-hostility flag, and a ``warmth_delta``) into обида AFTER the
    turn — a sustained critical owner-drop OR sustained directed hostility enters обида
    (announced once via GUPPI), while a warm turn accelerates recovery if already hurt.
    The concrete adapter
    (:class:`~bob.application.usecases.sulk_sources.SulkTracker`) is per-PERSONA and
    persists. Optional and additive: unwired (the default) Bob never sulks and the turn
    behaves exactly as before. обида carries NO memory and NO soul (anti-Exodus).
    """

    async def current(self) -> SulkState: ...

    async def observe(
        self,
        *,
        owner_warmth: float,
        hostile: bool,
        warmth_delta: float,
        now: datetime,
    ) -> SulkState: ...


class SelfImprovementReader(Protocol):
    """Read seam: Bob's APPROVED self-improvement rules for this turn (BOB-028 .3).

    The compose path uses this to APPLY Bob's owner-approved self-improvement rules as
    soft, bounded tilts — a TONE/HUMOR rule colours the voice, a LENGTH rule nudges the
    verbosity one step shorter, a PROACTIVITY/ADDRESSIVITY_BIAS rule biases their points
    (built into :class:`~bob.domain.personality.self_improvement.RuleModulators` by
    :func:`~bob.domain.personality.self_improvement.build_modulators`). Safety: it
    returns rules the use-case then filters to APPROVED-only via ``active_rules`` (no
    PROPOSED/PAUSED rule ever applies — authz-before-autonomy), and only the
    :class:`~bob.domain.personality.self_improvement.Lever` allowlist is read (authz /
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


@dataclass(frozen=True, slots=True)
class _AddressivityDecision:
    """The addressivity gate's result for one turn (BOB-023 + BOB-025 floor).

    ``outcome`` is the policy decision (ENGAGE / REACT / SILENT) taken on the
    EFFECTIVE addressivity (per-message raised by the conversation floor when Bob
    holds a live floor). ``per_message`` is the RAW per-message classification — it
    is what ``advance_floor`` reads after the turn (the floor reflects the real
    signals; whether Bob actually replied is tracked separately). ``directed_to_id``
    is the person the turn turned to on a ``DIRECTED_TO_OTHER`` per-message (so the
    floor can pass to them), else ``None``.
    """

    outcome: ResponseOutcome
    per_message: Addressivity
    directed_to_id: int | None


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
        repeat_thresholds: RepeatThresholds | None = None,
        floor_store: ConversationFloorStore | None = None,
        floor_config: FloorConfig | None = None,
        floor_enabled: bool = True,
        self_improvement: SelfImprovementReader | None = None,
        self_improvement_max_magnitude: float = _DEFAULT_MAX_MAGNITUDE,
        diagram_sink: DiagramSink | None = None,
        diagram_renderer: DiagramRenderer | None = None,
        diagram_send_as: DiagramSendMode = _DEFAULT_DIAGRAM_SEND_AS,
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
        # Anti-repeat window (BOB-026 .1): the fresh reply is checked against a WINDOW
        # of Bob's recent replies (not just the last), verbatim OR near-verbatim, so a
        # repeat "через ход" no longer slips through. Conservative defaults; tunable
        # via repeat.*.
        self._repeat_thresholds = (
            repeat_thresholds if repeat_thresholds is not None else RepeatThresholds()
        )
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
        # pushes each rendered :class:`~bob.domain.ports.DiagramResult` (PNG + caption)
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

    async def handle(self, event: MessageReceived) -> None:
        """Process one received message end to end (the EventBus subscriber)."""
        soul = await self._perceive(event)
        # Perceive WHO is writing (BOB-019): owner / known / guest / bot. Resolved
        # once per turn so the same identity threads through every (re)compose; None
        # when no perception seam is wired (additive, behaviour as before).
        interlocutor = await self._perceive_interlocutor(event)
        # Recall Bob's LIGHT prior first impression of this sender (BOB-019 bob-apv.3):
        # a returning person → his stored note, so the compose prompt can recall him
        # ("кажется, мы уже сталкивались"); a new person → None. It is per-PERSON data
        # (about THEM), so it is recalled even on a guest turn (a guest's own first
        # impression is about the guest, never an owner-memory leak).
        prior_impression = await self._recall_prior_impression(interlocutor)
        # Load Bob's accrued relationship with this sender (BOB-014): a known person →
        # his stored relationship, so his tone (warmth) and willingness to compromise
        # (warmth + compatibility) are coloured for THEM this turn; a new person →
        # None (a neutral turn). Per-PERSON data, so it is loaded even on a guest turn.
        relationship = await self._load_relationship(interlocutor)
        # Load Bob's обида state (BOB-014 .2b): while active, the reactive tone goes
        # COLD (a quieter, curt sulk_directive) — composed over mood/relationship tone.
        # None when no seam is wired / not hurt, so the turn behaves exactly as before.
        sulk = await self._load_sulk()
        # Build this turn's self-improvement modulators (BOB-028 .3): the soft, bounded
        # tilts Bob's OWNER-APPROVED rules apply — voice (tone/humor), length, proactivity
        # and addressivity biases — each into ITS OWN point below. Unwired / disabled → a
        # neutral RuleModulators (no tilt), so the turn behaves exactly as before BOB-028.
        modulators = await self._load_modulators()
        # Plan how Bob expresses this turn (BOB-018): pure, deterministic by seed.
        # Computed up front so the mode steers the reply path and the form hint
        # shapes the prompt; the rare flags ride along for later beads.
        plan = self._plan_expression(event, soul)
        # Decide Bob's APPETITE to converse this turn (BOB-014 .2a): a LEVEL from mood x
        # topic interest x conversational fatigue x relationship. Computed up front so the
        # level appends a voice directive to the prompt and the topic interest feeds the
        # after-turn feedback (mood lift + fatigue update). The fatigue is decayed by the
        # real elapsed time since the last turn first, so appetite always recovers.
        interest = await self._topic_interest(soul, event.text)
        level = self._decide_engagement(soul, interest, relationship)
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
        # ADDRESSIVITY self-improvement tilt (BOB-028 .3): an APPROVED ADDRESSIVITY_BIAS
        # rule softly RAISES the effective interest the addressivity policy reads — Bob is
        # a touch more willing to engage an ambient/borderline turn. It is a bounded nudge
        # (clamped to [0, 1]) on TOP of the BOB-023/025 decision, never a base override and
        # never able to silence Bob (the bias is non-negative). No rule → interest unchanged.
        addressivity_interest = _clamp_unit(interest + modulators.addressivity_bias)
        decision = await self._decide_addressivity(event, addressivity_interest)
        if decision.outcome is ResponseOutcome.SILENT:
            await self._advance_floor_after_turn(event, decision, bob_replied=False)
            return
        if decision.outcome is ResponseOutcome.REACT and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            await self._advance_floor_after_turn(event, decision, bob_replied=False)
            return
        # React-only (BOB-018): when a reactor is wired and the plan picks
        # REACT_ONLY, Bob acknowledges with a native mood emoji INSTEAD of composing
        # a reply — no LLM call, no rich final, no episode (there is no reply text).
        # It is still real engagement, so the owner-activity marker fires. Unwired,
        # the plan falls back to a full reply below (backward-compatible).
        if plan.mode is ExpressionMode.REACT_ONLY and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            await self._advance_floor_after_turn(event, decision, bob_replied=False)
            return
        # Decide how SHORT Bob answers this ENGAGE turn (BOB-024): answer-demand of the
        # message x interest x mood/appetite x the BOB-018 form_hint → a Verbosity, the
        # single final length directive + (on a terse turn) the short-answer few-shot.
        # Computed only after the addressivity gate commits to engaging — a SILENT/REACT
        # turn never needs it and never spends the seeded brevity roll, so addressivity's
        # own roll stays unperturbed. The LOW answer-demand is reused by the optional
        # length guard after generation.
        demand = classify_answer_demand(text=event.text)
        verbosity = self._decide_verbosity(soul, demand, interest, level, plan, interlocutor)
        # LENGTH self-improvement tilt (BOB-028 .3): an APPROVED LENGTH rule nudges the
        # decided verbosity ONE step shorter (clipped at TERSE) — a soft bias on TOP of
        # the BOB-024 decision, never a base override (наклон, не перехват). No such rule
        # (the default) → length_step 0 → verbosity unchanged.
        verbosity = _shift_verbosity(verbosity, modulators.length_step)
        # Guest (restricted social) mode (BOB-019 bob-apv.2 — the security core).
        # An unauthorized GUEST reached Bob's social path (routed in by multibot),
        # so Bob may talk to them like a person, but NEVER as a trusted peer:
        #   * NO owner-private memory — recall is skipped (empty), so no stored
        #     owner fact can enter a stranger's prompt (audience redaction);
        #   * NO owner conversation history — the replayed recent episodes (the
        #     owner's earlier turns in Bob's topic) are withheld too, so a stranger
        #     who joins the group never sees the owner's prior conversation;
        #   * NO tool-loop / capabilities — composition stays on the plain router
        #     (a guest can trigger no capability), enforced in _compose_reply;
        #   * NO grounded owner inner-life add-ons (leak/callback/fascination) —
        #     they surface Bob's private world, withheld from a stranger;
        #   * NO fact extraction — a guest turn is never written into the owner's
        #     semantic memory.
        # The stranger voice directive is appended so the wariness reads as
        # character. Default to MORE restriction when unsure.
        is_guest = interlocutor is not None and interlocutor.trust is Trust.GUEST
        # Reflection containment (BOB-033 .3): the reply-recall pool excludes private
        # reflection episodes so Bob's inner monologue never becomes a copyable exemplar
        # in a user-facing reply — the inner life colours tone via MOOD, not by parroting
        # reflection TEXT. Facts + past message turns still ground the reply, and the
        # deliberate ``leak_inner_life`` path (below, via self._reflection) is untouched.
        recalled: Sequence[Recalled] = (
            []
            if is_guest
            else recalled_excluding_reflections(
                await self._recall.recall(event.text, k=_RECALL_K)
            )
        )
        history: Sequence[Mapping[str, object]] = (
            [] if is_guest else await self._episodes.recent_episodes(_HISTORY_K)
        )
        # User-repeat detection (BOB-022): does the OWNER repeat (near-)verbatim what
        # he already said in the recent window? Pure, no-LLM, conservative (exact after
        # normalise). When True the compose prompt carries the user-repeat directive so
        # Bob NOTICES it in voice instead of silently re-answering. This is the opposite
        # side of the own-reply guard below (which catches BOB repeating himself).
        user_repeated = is_user_repeat(event.text, _user_turns(history))
        # Run the slow generation inside the typing keepalive so "Bob is typing…"
        # stays visible for the whole real wait (BOB-009); then commit one rich final.
        async with self._gateway.typing_indicator(chat_id=event.chat_id):
            reply = await self._compose_reply(
                event.text,
                soul,
                recalled,
                history,
                plan,
                user_repeated=user_repeated,
                interlocutor=interlocutor,
                is_guest=is_guest,
                prior_impression=prior_impression,
                relationship=relationship,
                engagement=level,
                sulk=sulk,
                verbosity=verbosity,
                modulators=modulators,
            )
            # Anti-repeat guard (BOB-022, defense in depth): if the fresh reply is
            # byte-identical (after strip) to Bob's most-recent prior reply, regenerate
            # ONCE — with sampling now stochastic the retry differs. At most one extra
            # generation, only on an exact duplicate; if the retry is still identical it
            # is kept (no infinite loop).
            reply = await self._guard_against_verbatim_repeat(
                reply,
                event.text,
                soul,
                recalled,
                history,
                plan,
                user_repeated,
                interlocutor,
                is_guest=is_guest,
                prior_impression=prior_impression,
                relationship=relationship,
                engagement=level,
                sulk=sulk,
                verbosity=verbosity,
                modulators=modulators,
            )
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
        reply = await self._autorender_inline_mermaid(reply)
        # Send any diagrams the render_diagram capability queued this turn (BOB-035):
        # the tool-loop (inside _compose_reply) pushed each rendered PNG into the
        # per-turn sink; here — where the chat_id and the gateway live — they are
        # drained and posted as Telegram photos BEFORE the text confirmation, so the
        # image leads. Best-effort and gated on a wired sink (no diagram skill → no-op).
        await self._send_pending_diagrams(event.chat_id)
        await self._gateway.reply(chat_id=event.chat_id, markdown=reply)
        # Advance the conversation floor AFTER Bob actually replied (BOB-025): an ENGAGE
        # turn that reached the reply sticks the floor to Bob (``bob_replied=True``), so
        # the next ambient message in the thread is read as continuity. Pass the RAW
        # per-message addressivity — the floor reflects the real signal, while
        # ``bob_replied`` separately records that Bob held the turn.
        await self._advance_floor_after_turn(event, decision, bob_replied=True)
        # Run the engagement feedback loops (BOB-014 .2a) BEFORE persisting the mood,
        # so the mood snapshot reflects this turn: an interesting, well-engaged exchange
        # lifts Bob's mood a touch; an aimless turn tires him. The fatigue holder's
        # elapsed-time decay was already applied in _decide_engagement; here it is
        # updated with the turn outcome. (The fascination-grounding nudge toward a
        # well-going topic is left to the reflect-tick evolution path it already owns.)
        soul = self._apply_engagement_feedback(soul, level, interest)
        await self._persist(event, reply, soul)
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
        if is_guest:
            # SECURITY: a guest turn is never distilled into the owner's semantic
            # memory — no stranger input becomes a stored owner fact.
            return
        # Tier 0 "remember" step: distil durable facts into semantic memory so a
        # later turn's recall can surface them. Best-effort — run() never raises,
        # so a flaky local model can never break a turn that already replied.
        await self._extract_facts.run(user_message=event.text, reply=reply)

    async def _react_only(self, event: MessageReceived, soul: SOUL) -> None:
        """Set a native mood emoji reaction on the inbound (BOB-018 react-only).

        Picks a standard-reaction emoji from Bob's current mood and asks the wired
        reactor to set it on the user's message. The reaction is best-effort (the
        adapter degrades to a brief ack and never raises), so this never breaks the
        turn. Called only when a reactor is wired and the plan picked REACT_ONLY.
        """
        assert self._reactor is not None  # guarded by the caller
        emoji = reaction_emoji_for(soul.mood)
        await self._reactor.react(
            chat_id=event.chat_id, message_id=event.message_id, emoji=emoji
        )

    async def _autorender_inline_mermaid(self, reply: str) -> str:
        """Render fenced ```mermaid blocks in ``reply`` and strip them (BOB-037 A).

        The reliability fix: the model usually writes the mermaid as a fenced block in
        its TEXT reply instead of calling the render_diagram tool. Each fenced block is
        rendered via the wired renderer and queued to the same per-turn sink, and the
        fence is stripped from the visible reply (the image replaces it). A block whose
        source the render_diagram tool ALREADY rendered this turn is skipped (dedup by
        normalised source) so the same diagram is never sent twice. A
        :class:`DiagramRenderError` leaves that block AS text (graceful — no crash);
        unwired renderer / no sink / no fenced block → the reply is returned unchanged.
        """
        if self._diagram_renderer is None or self._diagram_sink is None:
            return reply
        blocks = extract_mermaid_blocks(reply)
        if not blocks:
            return reply
        # Sources the render_diagram TOOL already queued this turn — dedup keys so the
        # same diagram is never rendered/sent twice. They count as "handled" (stripped).
        handled = {
            normalize_mermaid(result.source)
            for result in self._diagram_sink.pending()
        }
        for source in blocks:
            key = normalize_mermaid(source)
            if key in handled:
                continue  # the tool already queued it; just strip the echoed fence
            if await self._render_inline_block(source):
                handled.add(key)
        # Strip ONLY the blocks that were rendered or deduped; a block whose render
        # failed stays as text so Bob still answers (graceful).
        return strip_mermaid_blocks(reply, only=handled)

    async def _render_inline_block(self, source: str) -> bool:
        """Render one inline mermaid ``source`` and queue it; ``False`` on failure (BOB-037).

        Renders via the wired renderer and pushes a :class:`DiagramResult` (carrying the
        source for dedup) onto the per-turn sink. A :class:`DiagramRenderError` (mmdc
        missing / malformed) is logged and swallowed and returns ``False`` so the caller
        leaves the fence as text.
        """
        assert self._diagram_renderer is not None  # guarded by the caller
        assert self._diagram_sink is not None  # guarded by the caller
        try:
            png = await self._diagram_renderer.render(source)
        except DiagramRenderError as exc:
            logger.info("inline mermaid render failed (graceful): %s", exc)
            return False
        self._diagram_sink.push(
            DiagramResult(png=png, caption=_INLINE_DIAGRAM_CAPTION, source=source)
        )
        return True

    async def _send_pending_diagrams(self, chat_id: int) -> None:
        """Post the diagrams queued this turn (BOB-035 + BOB-037 C).

        Drains the per-turn :class:`~bob.domain.ports.DiagramSink` (cleared so the
        next turn starts empty) and sends each rendered PNG into ``chat_id`` via the
        gateway — keeping the chat_id strictly per-turn and the send a transport
        concern. The send MODE is config-driven (BOB-037 C): ``document`` posts the PNG
        UNCOMPRESSED (full resolution, the readable default), ``photo`` the inline-
        preview photo. No sink wired (the default) or an empty sink → a clean no-op.
        Best-effort: a flaky send is logged and swallowed so it can never break a turn
        whose text reply still lands.
        """
        if self._diagram_sink is None:
            return
        for diagram in self._diagram_sink.drain():
            try:
                await self._send_one_diagram(chat_id, diagram)
            except Exception:
                logger.exception("sending a diagram failed (ignored)")

    async def _send_one_diagram(self, chat_id: int, diagram: DiagramResult) -> None:
        """Send one drained diagram via the configured mode (document / photo)."""
        if self._diagram_send_as == "photo":
            await self._gateway.send_photo(
                chat_id=chat_id, photo=diagram.png, caption=diagram.caption
            )
            return
        await self._gateway.send_document(
            chat_id=chat_id, document=diagram.png, caption=diagram.caption
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
        """Update mood from the message text and store the new soul snapshot.

        Passes the soul's mood baseline as the social co-regulation ``target``
        (BOB-033 .3): a warm incoming message tugs mood a proportional fraction back
        toward this baseline, so connection genuinely displaces accumulated low.
        """
        signals = TextSignals(text=event.text, message_count=_SINGLE_MESSAGE, present=True)
        new_mood = await self._update_mood.run(
            self._state.soul.mood, signals, target=self._state.soul.mood_baseline
        )
        soul = self._state.soul.with_mood(new_mood)
        self._state.soul = soul
        return soul

    async def _perceive_interlocutor(
        self, event: MessageReceived
    ) -> Interlocutor | None:
        """Perceive WHO is writing this turn, or ``None`` (no seam wired) (BOB-019).

        Asks the wired perception seam to resolve the inbound into an
        :class:`~bob.domain.personality.interlocutor.Interlocutor` (owner / known /
        guest / bot). Unwired (the default) returns ``None`` so the compose path
        adds no who-is-writing line and the turn behaves exactly as before.
        """
        if self._perceive_sender is None:
            return None
        return await self._perceive_sender.resolve(event)

    async def _recall_prior_impression(
        self, interlocutor: Interlocutor | None
    ) -> str | None:
        """Recall Bob's LIGHT prior first-impression note for this sender (BOB-019).

        Asks the wired first-impression seam for the stored note of a returning
        sender; a new sender (or no seam / no perceived interlocutor) yields ``None``
        so the compose path adds no recall line. Per-PERSON data, so it is recalled
        even on a guest turn (a guest's own impression is about the guest).
        """
        if self._first_impression is None or interlocutor is None:
            return None
        return await self._first_impression.prior_impression(interlocutor)

    async def _record_first_impression(
        self, interlocutor: Interlocutor | None
    ) -> None:
        """Record Bob's LIGHT first impression of this sender on first contact (BOB-019).

        Best-effort and optional: with no seam wired (or no perceived interlocutor)
        this is a no-op. The grounded note is formed once (the store records once), so
        a returning sender is never overwritten. A flaky store can never break a turn
        that has already replied.
        """
        if self._first_impression is None or interlocutor is None:
            return
        try:
            await self._first_impression.note_first_contact(interlocutor)
        except Exception:
            logger.exception("recording first impression failed (ignored)")

    async def _load_relationship(
        self, interlocutor: Interlocutor | None
    ) -> Relationship | None:
        """Load Bob's accrued relationship with this sender, or ``None`` (BOB-014).

        Asks the wired relationship seam for the stored relationship of a known
        sender; a new sender (or no seam / no perceived interlocutor) yields ``None``
        so the turn behaves as a neutral one (no tone/willingness colour). Per-PERSON
        data, so it is loaded even on a guest turn (about the guest).
        """
        if self._relationship is None or interlocutor is None:
            return None
        return await self._relationship.current(interlocutor)

    async def _record_relationship(
        self,
        interlocutor: Interlocutor | None,
        soul: SOUL,
        text: str,
        relationship: Relationship | None,
    ) -> None:
        """Evolve + persist Bob's relationship with this sender after the turn (BOB-014).

        Best-effort and optional: with no seam wired (or no perceived interlocutor)
        this is a no-op. The negotiation stance Bob took THIS turn (decided over the
        same relationship-nudged conviction the prompt used), his current mood, and the
        turn's sentiment (read off the mood valence — the mood already reflects the
        perceived sentiment of the message) evolve the relationship via the pure
        :func:`~bob.domain.personality.relationship.apply_interaction`. A flaky store
        can never break a turn that has already replied.
        """
        if self._relationship is None or interlocutor is None:
            return
        # Sentiment of the turn: the mood valence already folds in the message's
        # perceived sentiment (UpdateMoodFromText nudges valence by it), so it is the
        # grounded affective signal here — no second classification round-trip.
        sentiment = soul.mood.valence
        stance, _verdict, _zone = self._decide_stance(soul, text, relationship)
        try:
            await self._relationship.record_interaction(
                interlocutor, stance=stance, mood=soul.mood, sentiment=sentiment
            )
        except Exception:
            logger.exception("recording relationship failed (ignored)")

    async def _load_sulk(self) -> SulkState | None:
        """Load Bob's обида state for this turn, or ``None`` (BOB-014 .2b).

        With no sulk seam wired returns ``None`` so the compose path adds no cold-tone
        line and the turn behaves exactly as before. Otherwise returns the persisted
        :class:`~bob.domain.personality.sulk.SulkState` so the prompt can go cold while
        Bob is hurt. обида carries NO memory and NO soul — only the affect state.
        """
        if self._sulk is None:
            return None
        return await self._sulk.current()

    async def _observe_sulk(
        self, interlocutor: Interlocutor | None, soul: SOUL, text: str
    ) -> None:
        """Fold this OWNER turn into Bob's обида state after the turn (BOB-014 .2b).

        Owner-only (обида v1 is tied to the OWNER relationship that leads proactivity).
        The "low" signal is BOTH the owner relationship warmth (a critically cold
        relationship) AND a DIRECTED hostility flag from
        :func:`~bob.domain.personality.profanity.is_directed_hostility` — so it reacts to
        sustained directed hostility, NOT to casual мат (which is never flagged hostile).
        A warm turn (positive ``warmth_delta``, read off the turn's mood valence)
        accelerates recovery if already hurt. Best-effort: a flaky store can never break
        a turn that already replied.
        """
        if self._sulk is None or interlocutor is None:
            return
        if interlocutor.kind is not InterlocutorKind.OWNER:
            return
        # The owner relationship warmth this turn (the relationship was just re-recorded
        # for the owner); a not-yet-formed relationship reads as neutral 0.
        owner_warmth = await self._owner_warmth(interlocutor)
        hostile = is_directed_hostility(text)
        # A warm message has positive sentiment; the mood valence folds in the perceived
        # sentiment of the turn (UpdateMoodFromText nudged it), so it is the grounded
        # "how warm was this turn" signal that accelerates отход while sulking.
        warmth_delta = soul.mood.valence
        try:
            await self._sulk.observe(
                owner_warmth=owner_warmth,
                hostile=hostile,
                warmth_delta=warmth_delta,
                now=self._clock.now(),
            )
        except Exception:
            logger.exception("observing sulk failed (ignored)")

    async def _owner_warmth(self, interlocutor: Interlocutor) -> float:
        """The owner relationship warmth for the обида signal, or neutral 0 (BOB-014).

        Reads the freshly-updated relationship for the owner (re-recorded earlier this
        turn) off the relationship seam; a not-yet-formed relationship (or no seam)
        reads as neutral ``0.0`` so a fresh Bob never sulks from a blank read.
        """
        if self._relationship is None:
            return 0.0
        rel = await self._relationship.current(interlocutor)
        return rel.warmth if rel is not None else 0.0

    def _decide_stance(
        self, soul: SOUL, text: str, relationship: Relationship | None
    ) -> tuple[Stance, Verdict, NegotiationZone]:
        """Decide Bob's negotiation stance for the turn (BOB-013 + BOB-014).

        Classifies the zone owning ``text`` from the taste verdict + conviction, then
        maps zone + an EFFECTIVE conviction to a :class:`Stance`. The effective
        conviction is the raw conviction lowered by the relationship's
        :func:`~bob.domain.personality.relationship.compromise_bias` — a close person
        (high warmth + compatibility) tips a borderline stance from holding ground
        toward agreeing (more willing to compromise), clamped to ``[0, 1]``. Returns
        the stance plus the verdict + zone so the prompt's stance-directive gate can
        reuse them. Pure-ish: no I/O, deterministic for a given soul/text/relationship.
        """
        verdict = soul.taste.score(text)
        conviction = soul.taste.conviction_for(text)
        zone = self._zone_classifier.classify(
            text, taste_verdict=verdict, conviction=conviction
        )
        effective = _clamp_conviction(conviction - compromise_bias(relationship))
        stance = self._negotiation.decide(zone, conviction=effective)
        return stance, verdict, zone

    def _relationship_tone(self, relationship: Relationship | None) -> str:
        """The relationship-warmth tone line for this turn, or ``""`` (BOB-014).

        No relationship on record (a new person) or a neutral warmth → no line, so the
        turn keeps the base mood tone. A close relationship reads warmer, a distant one
        more reserved (never rude — relational hostility is the sulk, .2). The warm/
        cool bands are config-tunable via ``relationship_tone_thresholds``.
        """
        if relationship is None:
            return ""
        return relationship_tone_directive(
            relationship.warmth, thresholds=self._relationship_tone_thresholds
        )

    async def _topic_interest(self, soul: SOUL, text: str) -> float:
        """Return how INTERESTING the inbound topic is to Bob, a [0, 1] scalar (BOB-014).

        Derived from his deterministic taste verdict + conviction on ``text`` (a strong
        love/hate is engaging, a NEUTRAL/unknown topic is "какие-попало" — low) and
        lifted when the topic MATCHES his current, non-faded fascination (the strongest
        pull — it clears the bar even on a bad day). The fascination match reuses the
        wired :class:`CurrentFascinationReader`; with no reader / no current passion the
        match is simply ``False``, so the interest is taste-only (behaviour as before).
        """
        verdict = soul.taste.score(text)
        conviction = soul.taste.conviction_for(text)
        match = await self._fascination_matches(text)
        return topic_interest(verdict, conviction, fascination_match=match)

    async def _fascination_matches(self, text: str) -> bool:
        """Whether the inbound topic is the thing Bob is currently fascinated by (BOB-014).

        Loads Bob's current, non-faded passion off the wired reader and checks whether
        its topic is mentioned in ``text`` (a light, case-insensitive substring match).
        No reader / no current fascination → ``False`` (a clean no-op). Best-effort —
        the appetite decision must never break on a flaky read, so a failure reads as no
        match rather than raising.
        """
        if self._fascination is None:
            return False
        try:
            fascination = await self._fascination.current_fascination()
        except Exception:
            logger.exception("reading current fascination for engagement failed (ignored)")
            return False
        if fascination is None:
            return False
        return fascination.topic.strip().casefold() in text.casefold()

    def _decide_engagement(
        self, soul: SOUL, interest: float, relationship: Relationship | None
    ) -> EngagementLevel:
        """Decide Bob's appetite LEVEL for this turn, decaying fatigue first (BOB-014 .2a).

        Decays the per-boot fatigue holder by the REAL elapsed time since the last turn
        (so appetite recovers between turns — the recovery guarantee), stores the decayed
        value back, then maps mood x ``interest`` x fatigue x ``relationship`` to an
        :class:`~bob.domain.personality.engagement.EngagementLevel` via the pure
        :func:`~bob.domain.personality.engagement.decide_engagement` (seeded by the same
        injected RNG, so the whole turn stays reproducible).
        """
        now = self._clock.now()
        state = self._engagement_state
        if state.last_turn_at is not None:
            elapsed = max(0.0, (now - state.last_turn_at).total_seconds())
            state.fatigue = state.fatigue.decayed(
                elapsed_seconds=elapsed, rates=self._fatigue_rates
            )
        return decide_engagement(
            mood=soul.mood,
            topic_interest=interest,
            fatigue=state.fatigue,
            relationship=relationship,
            rng=self._rng,
            thresholds=self._engagement_thresholds,
        )

    def _apply_engagement_feedback(
        self, soul: SOUL, level: EngagementLevel, interest: float
    ) -> SOUL:
        """Run the after-turn engagement feedback loops (BOB-014 .2a) and stamp the clock.

        Two loops close the appetite model: (1) an interesting, well-engaged exchange
        (FULL/PLAYFUL on an interesting topic) lifts Bob's mood valence a touch — a small
        bounded :class:`~bob.domain.personality.mood.MoodDelta` returned on a fresh soul
        snapshot, stored on :class:`PersonalityState`; (2) the fatigue holder is updated
        with the turn outcome — an aimless turn tires Bob, an interesting one eases him —
        and ``last_turn_at`` is stamped so the next turn decays the elapsed gap. Returns
        the (possibly mood-lifted) soul so the caller persists the post-feedback mood.
        (Fascination grounding toward a well-going topic stays with the reflect-tick
        evolution path that already owns it — this loop only lifts mood + eases fatigue.)
        """
        interesting = interest >= self._engagement_thresholds.interesting
        lift = engagement_mood_lift(
            level, interesting=interesting, lift=self._engagement_mood_lift
        )
        if lift > 0.0:
            soul = soul.with_mood(soul.mood.update(MoodDelta(valence=lift)))
            self._state.soul = soul
        self._engagement_state.fatigue = self._engagement_state.fatigue.after_turn(
            interesting=interesting, rates=self._fatigue_rates
        )
        self._engagement_state.last_turn_at = self._clock.now()
        return soul

    def _decide_verbosity(
        self,
        soul: SOUL,
        demand: AnswerDemand,
        interest: float,
        engagement: EngagementLevel,
        plan: ExpressionPlan,
        interlocutor: Interlocutor | None,
    ) -> Verbosity:
        """Decide how SHORT Bob answers this turn — pure, deterministic by seed (BOB-024).

        Folds the already-computed turn signals into the pure
        :func:`~bob.domain.personality.brevity.decide_verbosity`: the message's
        answer-``demand`` is the base; topic ``interest`` can rarely upgrade it (seeded);
        a low ``mood_valence`` / thin appetite (the :class:`EngagementLevel` mapped to a
        [0, 1] appetite via :func:`~bob.domain.personality.engagement.appetite_of`) pull
        it down; the BOB-018 ``form_hint`` is a mood length lean (now an INPUT, not a
        rival directive); and a HIGH-demand owner is never clipped below NORMAL. The
        seeded ``roll`` is one draw off the same injected RNG, so the whole turn stays
        reproducible. ``is_owner`` keys off the perceived interlocutor (BOB-019).
        """
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        roll = self._rng.random()
        return decide_verbosity(
            demand=demand,
            interest=interest,
            mood_valence=soul.mood.valence,
            engagement=appetite_of(engagement),
            form_hint=plan.form_hint,
            roll=roll,
            is_owner=is_owner,
            thresholds=self._brevity_thresholds,
        )

    def _guard_reply_length(self, reply: str, demand: AnswerDemand) -> str:
        """Lightly clamp an over-long reply to a simple question (BOB-024 length guard).

        The OPTIONAL safety net behind the brevity bayes: only when the guard is enabled
        AND the message wanted a short answer (``demand`` LOW) does an over-long reply get
        trimmed to its first finished thought via
        :func:`~bob.domain.personality.brevity.clamp_reply` (no regeneration, never a
        mid-word cut). Disabled (the default) or a non-LOW demand leaves the reply exactly
        as composed — the bayes is the mechanism, this is only a backstop.
        """
        if not self._length_guard_enabled or demand is not AnswerDemand.LOW:
            return reply
        return clamp_reply(reply, max_chars=self._length_guard_max_chars)

    async def _decide_addressivity(
        self, event: MessageReceived, interest: float
    ) -> _AddressivityDecision:
        """Decide whether/how Bob takes THIS turn by addressivity (BOB-023 + BOB-025).

        Classifies who the message is for from the gateway's signals (``mentions_bob``,
        ``reply_to_sender_id`` against Bob's own resolved id, an "Боб, …" name-address
        in the text), reads whether the recent thread has other participants, then —
        when the conversation floor is wired AND enabled — RAISES that per-message
        classification to the EFFECTIVE addressivity: an ``AMBIENT`` message in a thread
        where Bob holds a live floor reads as ``DIRECTED_TO_BOB`` (continuity, BOB-025).
        The policy (:func:`~bob.domain.personality.addressivity.decide_response`) runs on
        the EFFECTIVE addressivity, so a barge/react/silent decision honours continuity.
        One seeded RNG draw (the same injected RNG, so the turn stays reproducible)
        resolves the rare barge-in / like-react branches. The RAW per-message
        classification is returned alongside the outcome so the floor can advance on the
        real signal after the turn. Floor unwired / disabled → effective == per-message,
        so behaviour is exactly BOB-023.
        """
        present = await self._others_present(event)
        per_message = classify_addressivity(
            text=event.text,
            mentions_bob=event.mentions_bob,
            reply_to_sender_id=event.reply_to_sender_id,
            bob_user_id=self._bob_user_id(),
            others_present=present,
        )
        effective = await self._resolve_effective_addressivity(event, per_message)
        roll = self._rng.random()
        outcome = decide_response(
            effective,
            interest=interest,
            others_present=present,
            roll=roll,
            thresholds=self._addressivity_thresholds,
        )
        directed_to_id = (
            event.reply_to_sender_id
            if per_message is Addressivity.DIRECTED_TO_OTHER
            else None
        )
        return _AddressivityDecision(
            outcome=outcome,
            per_message=per_message,
            directed_to_id=directed_to_id,
        )

    async def _resolve_effective_addressivity(
        self, event: MessageReceived, per_message: Addressivity
    ) -> Addressivity:
        """Raise per-message addressivity by the conversation floor (BOB-025).

        With the floor wired AND enabled, an ``AMBIENT`` message in a thread where Bob
        holds a live floor is raised to ``DIRECTED_TO_BOB`` (continuity); the floor is
        loaded for ``(chat_id, thread_id)``. Floor unwired or disabled → the per-message
        classification is returned unchanged (BOB-023 behaviour). Best-effort: a flaky
        floor store can never break a turn — on a load/resolve failure Bob falls back to
        the per-message BOB-023 classification (a hiccup must never mute him), mirroring
        the advance side.
        """
        if self._floor_store is None or not self._floor_enabled:
            return per_message
        try:
            floor = await self._floor_store.load(
                event.chat_id, self._floor_thread_id(event)
            )
            return resolve_addressivity(
                per_message, floor, now=self._clock.now(), config=self._floor_config
            )
        except Exception:
            logger.exception(
                "resolving the conversation floor failed; using per-message addressivity"
            )
            return per_message

    async def _advance_floor_after_turn(
        self,
        event: MessageReceived,
        decision: _AddressivityDecision,
        *,
        bob_replied: bool,
    ) -> None:
        """Advance + persist the conversation floor after a turn (BOB-025).

        Reloads the floor for the thread, advances it on the RAW per-message addressivity
        (the floor reflects the real signal) plus whether Bob actually replied
        (``bob_replied`` sticks the floor to him on an ENGAGE turn; a SILENT/REACT turn
        passes ``False`` so idle_streak / decay are counted), then UPSERTs it. No-op when
        the floor is unwired or disabled (BOB-023 behaviour). Best-effort: a flaky floor
        store can never break a turn that has already acted.
        """
        if self._floor_store is None or not self._floor_enabled:
            return
        thread_id = self._floor_thread_id(event)
        try:
            floor = await self._floor_store.load(event.chat_id, thread_id)
            new_floor = advance_floor(
                floor,
                addressivity=decision.per_message,
                sender_id=event.sender_id,
                directed_to_id=decision.directed_to_id,
                bob_replied=bob_replied,
                now=self._clock.now(),
                config=self._floor_config,
            )
            await self._floor_store.save(event.chat_id, thread_id, new_floor)
        except Exception:
            logger.exception("advancing the conversation floor failed (ignored)")

    @staticmethod
    def _floor_thread_id(event: MessageReceived) -> int | None:
        """The thread key for the conversation floor (BOB-025).

        The floor is a property of one running exchange (Bob's forum topic). The
        application event does not yet carry a forum ``thread_id``, so the floor is
        keyed by ``chat_id`` alone for now (``None`` = main chat / no topic — the store's
        sentinel). Kept as a seam so a real per-topic key threads through later.
        """
        del event  # no forum thread id on the event yet; keyed by chat for now
        return None

    def _bob_user_id(self) -> int | None:
        """Bob's own bot ``user_id`` (resolved at startup), or ``None`` (BOB-023).

        Read lazily through the injected seam so the synchronous use-case need not
        know Bob's id at construction; ``None`` (unwired / not yet resolved / the GUPPI
        gateway) degrades gracefully — reply-to-Bob cannot fire, @mention still does.
        """
        if self._bob_user_id_source is None:
            return None
        return self._bob_user_id_source()

    async def _others_present(self, event: MessageReceived) -> bool:
        """Whether the recent thread has senders OTHER than the current one (BOB-023).

        A light, grounded heuristic over the replayed recent episodes (stored as
        ``"<sender>: <text>\\nbob: <reply>"``): in a 1:1 owner↔Bob thread every label
        matches the current sender → ``False`` (Bob's space, he engages on ambient); a
        third participant appears → ``True`` (mostly stay quiet / like-react on ambient).
        Best-effort: a flaky history read degrades to ``False`` (treat as 1:1 — never
        wrongly silences Bob in his own space).
        """
        try:
            history = await self._episodes.recent_episodes(_HISTORY_K)
        except Exception:
            logger.exception("reading history for addressivity failed (ignored)")
            return False
        lines = [
            str(item.get("content", "")) for item in history if item.get("content")
        ]
        return others_present(lines, current_sender_name=event.sender_name)

    def _plan_expression(self, event: MessageReceived, soul: SOUL) -> ExpressionPlan:
        """Decide this turn's expression plan — pure, deterministic by seed (BOB-018).

        Reads the freshly-updated mood + the inbound's shape, draws from the
        injected seeded RNG, and returns the plan: mode, the rare add-on flags
        (carried for later beads), and the soft form hint applied to the prompt.
        """
        signals = ExpressionSignals(inbound_text=event.text)
        return decide_expression(
            soul.mood, signals, rng=self._rng, freqs=self._expression_freqs
        )

    async def _compose_reply(
        self,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        plan: ExpressionPlan,
        *,
        user_repeated: bool = False,
        interlocutor: Interlocutor | None = None,
        is_guest: bool = False,
        prior_impression: str | None = None,
        relationship: Relationship | None = None,
        engagement: EngagementLevel = EngagementLevel.FULL,
        sulk: SulkState | None = None,
        verbosity: Verbosity = Verbosity.NORMAL,
        modulators: RuleModulators | None = None,
    ) -> str:
        """Compose a full reply, folding the decided verbosity into the prompt.

        On a guest turn (``is_guest``) the restricted social mode applies: the
        grounded owner inner-life add-ons (leak / callback / fascination) are
        skipped (they surface Bob's private world), the tool-loop is NEVER used (a
        guest can trigger no capability), and the stranger voice directive is
        appended — the application half of the security invariant.
        """
        context = _assemble_shareable_context(soul, text, recalled, history)
        if not is_guest:
            # Grounded add-ons surface Bob's PRIVATE inner life / shared past —
            # withheld from a stranger (audience redaction).
            context = await self._with_grounded_addons(context, text, plan)
        system_prompt = self._system_prompt_for(
            soul,
            text,
            user_repeated=user_repeated,
            interlocutor=interlocutor,
            is_guest=is_guest,
            prior_impression=prior_impression,
            relationship=relationship,
            engagement=engagement,
            sulk=sulk,
            verbosity=verbosity,
            modulators=modulators,
        )
        provider = self._tool_provider
        if not is_guest and provider is not None and not self._registry.is_empty:
            return await self._reply_with_tools(provider, system_prompt, text, context)
        # Hybrid reply tiering (BOB-006): a casual/short message answers on the
        # fast Tier 0 (flash) model for responsiveness; a complex/long message
        # escalates to the quality Tier 1 (plus) model — picked by a pure
        # heuristic on the user's message, no extra LLM round-trip.
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

    async def _guard_against_verbatim_repeat(
        self,
        reply: str,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        plan: ExpressionPlan,
        user_repeated: bool = False,
        interlocutor: Interlocutor | None = None,
        *,
        is_guest: bool = False,
        prior_impression: str | None = None,
        relationship: Relationship | None = None,
        engagement: EngagementLevel = EngagementLevel.FULL,
        sulk: SulkState | None = None,
        verbosity: Verbosity = Verbosity.NORMAL,
        modulators: RuleModulators | None = None,
    ) -> str:
        """Recompose if ``reply`` (near-)repeats a recent OR recalled Bob reply (BOB-032 .1).

        The verbatim-repeat bug was greedy decoding: an identical prompt returned
        byte-identical text. Sampling temperature (the primary fix) makes that
        stochastic; this is defense in depth. BOB-026 .1 widened it from Bob's single
        most-recent reply to a WINDOW of his last N replies and from exact-only to
        verbatim-OR-near-verbatim.

        BOB-032 .1 closes the deeper hole:

        * **R1 (recall-aware).** The compose context folds in ``recalled`` semantic
          memories as whole turns, so the model can copy Bob's OWN recalled past reply
          verbatim — a far-back repeat the history-only window never saw. The candidate
          is now compared against the UNION of recent-history replies AND the ``bob:``
          halves recovered from ``recalled``.
        * **R2 (attractor-breaking).** A plain re-roll re-uses the SAME recalled exemplar
          and falls back into the same attractor. So on each retry the recalled
          episode(s) the candidate copied are DROPPED from the context (only those — the
          fact content is preserved), and up to ``_MAX_REGENERATIONS`` retries are drawn,
          re-checking after each. If it is still a repeat after the bound the last draft
          is kept (no infinite loop), purely structural — no "do not repeat" instruction.

        BOB-036 .1 also guards the PHRASE level: a signature CLOSER ("Мне так спокойнее.")
        recurring across the recent window is invisible to the full-reply bar (two
        substantively different replies can share the same tail). When
        :func:`is_phrase_tic` fires on the same recall-aware union, the SAME regeneration
        path runs — a structural detector, never a scripted "do not say X".
        """
        threshold = self._repeat_thresholds.similarity_threshold
        tic_min_words = self._repeat_thresholds.tic_min_words
        tic_min_occurrences = self._repeat_thresholds.tic_min_occurrences
        recent = _recent_bob_replies(history, limit=self._repeat_thresholds.window)
        current = reply
        current_recalled = recalled
        for _ in range(_MAX_REGENERATIONS):
            prior_replies = (*recent, *recalled_bob_replies(current_recalled))
            full_repeat = is_bob_repeat(current, prior_replies, threshold=threshold)
            # BOB-036 .1: a phrase-tic (a signature CLOSER recurring across the recent
            # window) is invisible to the full-reply bar above — two DIFFERENT replies
            # can share the same tail. Break it via the SAME regeneration path.
            phrase_tic = is_phrase_tic(
                current,
                prior_replies,
                min_words=tic_min_words,
                min_occurrences=tic_min_occurrences,
            )
            if not (full_repeat or phrase_tic):
                return current
            # Break the attractor: strip the recalled reply exemplar(s) the candidate
            # copied so the next draft no longer sees the text it was echoing.
            current_recalled = recalled_without_copied_exemplars(
                current, current_recalled, threshold=threshold
            )
            current = await self._compose_reply(
                text,
                soul,
                current_recalled,
                history,
                plan,
                user_repeated=user_repeated,
                interlocutor=interlocutor,
                is_guest=is_guest,
                prior_impression=prior_impression,
                relationship=relationship,
                engagement=engagement,
                sulk=sulk,
                verbosity=verbosity,
                modulators=modulators,
            )
        return current

    async def _with_grounded_addons(
        self, context: str, text: str, plan: ExpressionPlan
    ) -> str:
        """Fold the plan's grounded add-ons into the compose context (BOB-018 w3).

        Behind the existing grounding seam, when the plan sets ``leak_inner_life``
        and a real reflection exists, Bob's latest reflection is appended as a
        leaking-inner-life line; when it sets ``callback`` and a STRONG real past
        moment is recalled on the topic, that moment is appended as a callback.
        Both are strictly anti-confabulation: no real material → no line added (a
        clean no-op), so Bob never invents a thought or a shared past that is not
        there. Composes additively with the existing context (voice/language/
        negotiation/form-hint all live elsewhere and are untouched).
        """
        additions = [
            await self._leak_inner_life(plan),
            await self._callback(plan, text),
            await self._mention_fascination(plan),
        ]
        suffix = "".join(f"\n{line}" for line in additions if line)
        return f"{context}{suffix}" if suffix else context

    async def _leak_inner_life(self, plan: ExpressionPlan) -> str:
        """The leak line for this turn, or ``""`` (no flag / no reader / no reflection)."""
        if not plan.leak_inner_life or self._reflection is None:
            return ""
        reflection = await self._reflection.latest_reflection_text()
        if not reflection:
            return ""
        return f"{_LEAK_PREFACE} {reflection}"

    async def _callback(self, plan: ExpressionPlan, text: str) -> str:
        """The callback line for this turn, or ``""`` (no flag / weak-or-empty recall).

        Reuses the hybrid recall (BOB-011) on the current topic; a real past moment
        comes back → it is offered as a callback. Mirrors BOB-012 grounding: an
        empty recall yields nothing, so Bob never confabulates a shared moment.

        Occasionally (a small seeded draw, BOB-021 mechanism 1) the recall is asked
        with ``surface_old`` so the callback can reach an OLD-but-relevant deep cut
        ("что-то напомнило") instead of only the freshest hit — still grounded (a real
        recall hit) and a no-op when nothing relevant comes back. The draw rides ONLY
        the callback path and fires on a fraction of callbacks, never every turn.
        """
        if not plan.callback:
            return ""
        surface_old = self._draw_surface_old()
        recalled = await self._recall.recall(
            text, k=_CALLBACK_RECALL_K, surface_old=surface_old
        )
        moment = next(
            (str(item.get("content", "")) for item in recalled if item.get("content")),
            "",
        )
        if not moment:
            return ""
        return f"{_CALLBACK_PREFACE} {moment}"

    def _draw_surface_old(self) -> bool:
        """Fire the rare surface_old draw for this callback (BOB-021, seeded RNG).

        A hard off at frequency ``0`` (the default path never asks for the old blend);
        otherwise an occasional ``True`` so a callback reaches an old-but-relevant deep
        cut on a small fraction of callbacks. Uses the same injected seeded RNG as the
        expression plan, so the whole turn stays reproducible under a fixed seed.
        """
        if self._surface_old_freq <= _MIN_FREQ:
            return False
        return self._rng.random() < self._surface_old_freq

    async def _mention_fascination(self, plan: ExpressionPlan) -> str:
        """The fascination line for this turn, or ``""`` (no flag / no reader / none).

        On a ``mention_fascination`` turn, asks the wired reader for Bob's current,
        non-faded passion; a real one is offered as something he can drop à propos.
        Strictly anti-confabulation: ``None`` (no reader, or no current fascination)
        yields nothing, so Bob never invents an interest he does not have.
        """
        if not plan.mention_fascination or self._fascination is None:
            return ""
        fascination = await self._fascination.current_fascination()
        if fascination is None:
            return ""
        return f"{_FASCINATION_PREFACE} {fascination.topic}"

    def _system_prompt_for(
        self,
        soul: SOUL,
        text: str,
        *,
        user_repeated: bool = False,
        interlocutor: Interlocutor | None = None,
        is_guest: bool = False,
        prior_impression: str | None = None,
        relationship: Relationship | None = None,
        engagement: EngagementLevel = EngagementLevel.FULL,
        sulk: SulkState | None = None,
        verbosity: Verbosity = Verbosity.NORMAL,
        modulators: RuleModulators | None = None,
    ) -> str:
        """Augment the base prompt with the mood tone, stance, and brevity directives.

        The mood-conditioned tone directive (BOB-020) leads: a normal/good mood keeps
        Bob's warm, concise tone, a flat low mood swaps it for the quieter, honest
        off-day band ("не знаю" over confabulation) — replacing the old unconditional
        warm line. The taste verdict + conviction on ``text`` then pick the zone and
        stance (BOB-013), and the decided ``verbosity`` (BOB-024) appends the SINGLE
        final length directive + (on a terse turn) the short-answer few-shot — replacing
        the old soft form_hint length cue (form_hint is now an INPUT to the verbosity
        decision, so there are no competing length signals). When ``user_repeated``
        (BOB-022 — the owner sent a near-verbatim repeat) the user-repeat directive is
        appended so Bob notices it in voice. When an ``interlocutor`` is perceived
        (BOB-019) the who-is-writing line is appended so Bob answers as someone who knows
        WHO is on the other side (the owner recognised AS owner) — additive, never
        changing which pipeline runs. With a normal mood, no target opinion, no
        user-domain signal, a NORMAL verbosity, no repeat, and no perceived interlocutor,
        only the warm tone line augments the base voice.
        """
        stance, verdict, zone = self._decide_stance(soul, text, relationship)
        directives = [
            tone_directive(soul.mood, thresholds=self._offday_thresholds),
            # BOB-014: Bob's accrued WARMTH toward this specific person colours his
            # voice on TOP of the mood tone — warmer for a close relationship, more
            # reserved (never rude) for a distant one. No relationship / neutral
            # warmth → no line (a new person is met at the base tone).
            self._relationship_tone(relationship),
            # BOB-014 .2b: while Bob is обижен his reactive tone goes COLD — quieter,
            # curt, minimal (sulk_directive) — composed on TOP of the mood/relationship
            # tone. It is cold-but-still-Bob, never rude, never a reset. No sulk / not
            # active → no line (a not-hurt Bob keeps his normal tone).
            sulk_directive(intensity=sulk.intensity)
            if sulk is not None and sulk.active
            else "",
            _stance_directive(stance, verdict=verdict, zone=zone),
            # BOB-014 .2a: Bob's APPETITE to converse this turn colours HOW he engages
            # on TOP of mood/relationship tone — PLAYFUL invites banter, TERSE keeps it
            # short as interest thins, DECLINE softly winds the chatter down (never rude;
            # relational hostility is the sulk, .2b). FULL adds no line (default voice).
            engagement_directive(engagement),
            # BOB-024: the SINGLE final length authority — a strong directive for the
            # decided Verbosity plus, on a TERSE turn, the short-answer few-shot that
            # beats Qwen's verbosity prior (replacing the old soft form_hint length cue,
            # which is now an INPUT to decide_verbosity — no competing length signals).
            # NORMAL adds nothing; the few-shot is empty off a TERSE turn.
            brevity_directive(verbosity),
            brevity_few_shot(verbosity),
            user_repeat_directive() if user_repeated else "",
            # BOB-019: fold WHO is writing (owner / known / guest / bot) into the
            # voice as character — additive, no-op when no interlocutor perceived.
            who_is_writing_directive(interlocutor) if interlocutor is not None else "",
            # BOB-019 bob-apv.2: on a guest turn, the stranger voice — Bob meets a
            # stranger warily-but-human and never reveals the owner's private info
            # (the voice half of the restricted-mode security invariant).
            stranger_directive() if is_guest else "",
            # BOB-019 bob-apv.3: a returning sender Bob has met before — recall his
            # LIGHT prior first impression ("кажется, мы уже сталкивались"), grounded
            # in the real stored note. Per-PERSON data (about THEM), so it is folded
            # in even on a guest turn — never an owner-memory leak. No prior note → no
            # line (a new person is met fresh).
            recalled_impression_directive(prior_impression)
            if prior_impression
            else "",
            # BOB-028 .3: Bob's OWNER-APPROVED TONE/HUMOR self-improvement rules fold
            # into ONE soft voice tilt on TOP of mood/relationship tone — a reminder he
            # gives himself, never a command or a reset (наклон, не перехват). No such
            # rule (the default / disabled) → no line. Only the Lever allowlist is ever
            # read (authz/guest/SOUL/safety have no lever).
            improvement_directive(
                modulators.voice_adjustments if modulators is not None else ()
            ),
        ]
        suffix = "".join(f"\n{d}" for d in directives if d)
        return f"{_SYSTEM_PROMPT}{suffix}"

    async def _reply_with_tools(
        self, provider: ToolCallingProvider, system_prompt: str, text: str, context: str
    ) -> str:
        """Drive the capability tool-loop, advertising the manifest in the prompt."""
        manifest = "\n".join([_CAPABILITY_PREFACE, self._registry.describe()])
        parts = (
            [system_prompt, manifest, context]
            if context
            else [system_prompt, manifest]
        )
        messages: list[LLMMessage] = [
            {"role": "system", "content": "\n".join(parts)},
            {"role": "user", "content": text},
        ]
        loop = ToolLoop(provider=provider, registry=self._registry)
        return await loop.run(messages)

    async def _persist(self, event: MessageReceived, reply: str, soul: SOUL) -> None:
        """Save the turn as an episode and snapshot the updated mood."""
        now = self._clock.now()
        episode = EpisodicEvent(
            ts=now,
            event_type="message",
            content=f"{event.sender_name or 'user'}: {event.text}\nbob: {reply}",
            mood_snapshot=soul.mood.tone(),
            tags=("telegram",),
        )
        await self._repo.save_episode(
            {
                "ts": episode.ts.isoformat(),
                "event_type": episode.event_type,
                "content": episode.content,
                "mood_snapshot": episode.mood_snapshot,
                "tags": ",".join(episode.tags),
            }
        )
        await self._repo.set_mood(_mood_state(soul), at=now)


# The verbosity ladder, low → high, for the self-improvement LENGTH tilt (BOB-028 .3).
# A LENGTH rule shifts the BOB-024 verbosity by ``step`` (only ever -1 → shorter),
# clipped at the ends — a soft bias on TOP of the decision, never a base override.
_VERBOSITY_LADDER: tuple[Verbosity, ...] = (
    Verbosity.TERSE,
    Verbosity.NORMAL,
    Verbosity.EXPANSIVE,
)


def _shift_verbosity(verbosity: Verbosity, step: int) -> Verbosity:
    """Shift ``verbosity`` by ``step`` steps on the ladder, clipped at the ends (BOB-028).

    The LENGTH self-improvement tilt: ``step`` is the modulator's ``length_step`` (0 →
    unchanged, -1 → one step shorter). A no-op for ``step == 0`` (the default / disabled
    path), and clipped at TERSE/EXPANSIVE so a tilt never wraps the ladder — наклон, не
    перехват.
    """
    if step == 0:
        return verbosity
    index = _VERBOSITY_LADDER.index(verbosity)
    clamped = max(0, min(len(_VERBOSITY_LADDER) - 1, index + step))
    return _VERBOSITY_LADDER[clamped]


def _validated_magnitude(value: float) -> float:
    """Validate the self-improvement soft-tilt ceiling lies in [0, 1] (BOB-028 .3)."""
    if not _MIN_FREQ <= value <= _MAX_FREQ:
        msg = (
            f"self_improvement_max_magnitude must be within "
            f"[{_MIN_FREQ}, {_MAX_FREQ}], got {value}"
        )
        raise ValueError(msg)
    return value


def _clamp_unit(value: float) -> float:
    """Saturate ``value`` into the closed unit interval (a bounded interest/bias)."""
    return max(_MIN_FREQ, min(_MAX_FREQ, value))


def _clamp_conviction(value: float) -> float:
    """Saturate ``value`` into the conviction bounds Negotiation requires."""
    return max(_MIN_CONVICTION, min(_MAX_CONVICTION, value))


def _stance_directive(
    stance: Stance, *, verdict: Verdict, zone: NegotiationZone
) -> str:
    """Map a stance to its prompt directive, gated to a real negotiation signal.

    The directive is emitted only when there is something to negotiate: Bob holds
    an opinion on the topic (a non-NEUTRAL verdict) or the matter is explicitly
    the user's domain (a logistics signal). A neutral, jointly-owned topic carries
    no directive, so that path behaves exactly as it did before BOB-013.
    """
    has_signal = verdict is not Verdict.NEUTRAL or zone is NegotiationZone.USER_DOMAIN
    if not has_signal:
        return ""
    return _STANCE_DIRECTIVE.get(stance, "")


# Effective-verdict modulation (BOB-020) needs the sign of Bob's liking to lean a
# NEUTRAL verdict the right way; the stored axis value is private to TasteEngine, so
# we read the sign off the verdict itself (positive verdicts → +1, negative → -1,
# NEUTRAL → 0 so an unknown topic stays a clean identity under any mood).
_POSITIVE_VERDICTS = frozenset({Verdict.LOVE, Verdict.LIKE})
_NEGATIVE_VERDICTS = frozenset({Verdict.DISLIKE, Verdict.HATE})


def _verdict_sign(verdict: Verdict) -> float:
    """+1.0 for a positive verdict, -1.0 for a negative one, 0.0 for NEUTRAL."""
    if verdict in _POSITIVE_VERDICTS:
        return 1.0
    if verdict in _NEGATIVE_VERDICTS:
        return -1.0
    return 0.0


def _assemble_shareable_context(
    soul: SOUL,
    topic: str,
    recalled: Sequence[Recalled],
    history: Sequence[Mapping[str, object]],
) -> str:
    """Compose Bob's reply-shaping context (Variant 2: MAY reach Tier 1).

    Carries recent conversation history, identity, mood tone, the taste verdict
    on the topic, phantom preferences, and recalled memories — all material that
    shapes Bob's reply and returns to the same user, so the reply tier sees it
    (this is what lets Bob remember a name said one message ago). Genuinely
    internal material is NOT assembled here; it belongs in ``private_context``.

    The taste verdict injected is the EFFECTIVE one (BOB-020): Bob's current mood
    temporarily colours it via :func:`modulate` — a flat day reads it stricter, a
    bright day softer — and an experiment-readiness hint from the same mood rides
    along. This is temporary modulation only; the stored taste axes are untouched.
    """
    stored = soul.taste.score(topic)
    effective = modulate(stored, _verdict_sign(stored), soul.mood)
    lines = [
        f"Identity: {soul.identity}",
        f"Mood tone: {soul.mood.tone()}",
        f"Taste verdict on '{topic}': {effective.value}",
        f"Experiment readiness: {experiment_bias(soul.mood):.2f}",
    ]
    if soul.phantom_prefs:
        lines.append("Phantom preferences: " + ", ".join(soul.phantom_prefs))
    turns = [str(item.get("content", "")) for item in history if item.get("content")]
    if turns:
        lines.append("Recent conversation:\n" + "\n".join(turns))
    memories = [str(item.get("content", "")) for item in recalled]
    if memories:
        lines.append("Recalled memories: " + " | ".join(memories))
    return "\n".join(lines)


# Marker prefixing Bob's turn inside a persisted episode's ``content`` (see
# :meth:`HandleMessage._persist`, which writes "<sender>: <text>\nbob: <reply>").
_BOB_TURN_MARKER = "\nbob: "


def _recent_bob_replies(
    history: Sequence[Mapping[str, object]], *, limit: int
) -> tuple[str, ...]:
    """Return Bob's last ``limit`` reply texts (freshest first) from history (BOB-026 .1).

    Episodes are stored as ``"<sender>: <text>\\nbob: <reply>"`` (see
    :meth:`HandleMessage._persist`); this scans the most-recent episodes back to
    front and recovers the ``bob:`` half of each so the anti-repeat guard can compare
    the fresh reply against a WINDOW of Bob's own recent replies — not just the last —
    catching a repeat "через ход". No Bob turn on record yields an empty tuple.
    """
    replies: list[str] = []
    for item in reversed(list(history)):
        if len(replies) >= limit:
            break
        content = item.get("content")
        if not isinstance(content, str):
            continue
        marker = content.rfind(_BOB_TURN_MARKER)
        if marker != -1:
            replies.append(content[marker + len(_BOB_TURN_MARKER) :])
    return tuple(replies)


# BOB-032 .2: the recall-aware anti-repeat helpers were lifted to the domain
# (``conversation.py``) so the reactive turn AND the proactive engine share ONE
# implementation instead of duplicating the predicate. These module-level aliases
# preserve the original import paths used within this module (and its tests).
_recalled_bob_reply = recalled_bob_reply
_recalled_bob_replies = recalled_bob_replies
_recalled_without_copied_exemplars = recalled_without_copied_exemplars


# Separator between a turn's sender label and the user's message text inside a
# persisted episode's ``content`` ("<sender>: <text>\nbob: <reply>"); the user half
# is what sits between this and ``_BOB_TURN_MARKER`` (see :meth:`HandleMessage._persist`).
_SENDER_TEXT_SEPARATOR = ": "


def _user_turns(history: Sequence[Mapping[str, object]]) -> list[str]:
    """Recover the USER half of each replayed episode (BOB-022 repeat detection).

    Episodes are stored as ``"<sender>: <text>\\nbob: <reply>"`` (see
    :meth:`HandleMessage._persist`); this extracts the ``<text>`` between the first
    ``"<sender>: "`` and the ``"\\nbob: "`` marker for each episode so the user-repeat
    predicate compares the current message ONLY against prior USER turns — never
    against Bob's own replies. Episodes without the expected shape are skipped.
    """
    turns: list[str] = []
    for item in history:
        content = item.get("content")
        if not isinstance(content, str):
            continue
        marker = content.find(_BOB_TURN_MARKER)
        head = content[:marker] if marker != -1 else content
        sep = head.find(_SENDER_TEXT_SEPARATOR)
        if sep == -1:
            continue
        user_text = head[sep + len(_SENDER_TEXT_SEPARATOR) :]
        if user_text:
            turns.append(user_text)
    return turns


def _mood_state(soul: SOUL) -> dict[str, object]:
    """Serialise the soul's mood vector into a persistable state blob."""
    mood = soul.mood
    return {
        "valence": mood.valence,
        "arousal": mood.arousal,
        "openness": mood.openness,
        "social": mood.social,
        "stability": mood.stability,
    }
