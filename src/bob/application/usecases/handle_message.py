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
from typing import TYPE_CHECKING, Protocol

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.capabilities.tool_loop import ToolLoop
from bob.application.router.llm_router import LLMRequest, TaskType
from bob.application.router.reply_tier_selector import select_reply_tier
from bob.application.usecases.update_mood_from_text import TextSignals
from bob.domain.memory.entities import EpisodicEvent
from bob.domain.personality.addressivity import (
    AddressivityThresholds,
    ResponseOutcome,
    classify_addressivity,
    decide_response,
    others_present,
)
from bob.domain.personality.conversation import is_user_repeat
from bob.domain.personality.engagement import (
    ConversationalFatigue,
    EngagementLevel,
    EngagementThresholds,
    FatigueRates,
    decide_engagement,
    engagement_mood_lift,
    topic_interest,
)
from bob.domain.personality.expression import (
    ExpressionFreqs,
    ExpressionMode,
    ExpressionPlan,
    ExpressionSignals,
    FormHint,
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
from bob.domain.personality.taste import Verdict
from bob.domain.personality.voice import (
    OffDayThresholds,
    RelationshipToneThresholds,
    anti_bait_directive,
    engagement_directive,
    guppi_canon,
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
    from bob.domain.personality.soul import SOUL
    from bob.domain.personality.sulk import SulkState
    from bob.domain.ports import (
        Clock,
        LLMMessage,
        MemoryRecall,
        MessageReactor,
        Recalled,
        ReflectionReader,
        ToolCallingProvider,
        ZoneClassifier,
    )

logger = logging.getLogger(__name__)

# How many memories to recall when assembling the reply context.
_RECALL_K = 5

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

# Form-hint → soft compose directive (BOB-018). The ExpressionPlan's form_hint is
# a state-driven length cue that AUGMENTS the variable-form voice (and anti-bait):
# it nudges this turn shorter or longer without ever licensing the closing-bait
# tic. NORMAL carries no directive — the variable-form voice already covers the
# default — so a neutral turn's prompt is unchanged but for that one voice line.
# Russian persona directives (project language); Cyrillic look-alikes intentional.
_FORM_HINT_DIRECTIVE: dict[FormHint, str] = {
    FormHint.TERSE: (
        "Сейчас тянет ответить коротко — реплика в одну-две строки, "
        "без развёртывания."
    ),
    FormHint.EXPANSIVE: (
        "Сейчас есть что сказать — можешь развёрнуто, на несколько абзацев."
    ),
}

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


class HandleMessage:
    """Run one full Telegram turn: perceive mood, decide a reply, act, persist."""

    def __init__(
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
        # REACT reuses the BOB-018 react-only path. In a 1:1 owner thread the outcome is
        # always ENGAGE, so the turn behaves exactly as before.
        outcome = await self._decide_addressivity(event, interest)
        if outcome is ResponseOutcome.SILENT:
            return
        if outcome is ResponseOutcome.REACT and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            return
        # React-only (BOB-018): when a reactor is wired and the plan picks
        # REACT_ONLY, Bob acknowledges with a native mood emoji INSTEAD of composing
        # a reply — no LLM call, no rich final, no episode (there is no reply text).
        # It is still real engagement, so the owner-activity marker fires. Unwired,
        # the plan falls back to a full reply below (backward-compatible).
        if plan.mode is ExpressionMode.REACT_ONLY and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            return
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
        recalled: Sequence[Recalled] = (
            [] if is_guest else await self._recall.recall(event.text, k=_RECALL_K)
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
            )
        await self._gateway.reply(chat_id=event.chat_id, markdown=reply)
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
        """Update mood from the message text and store the new soul snapshot."""
        signals = TextSignals(text=event.text, message_count=_SINGLE_MESSAGE, present=True)
        new_mood = await self._update_mood.run(self._state.soul.mood, signals)
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

    async def _decide_addressivity(
        self, event: MessageReceived, interest: float
    ) -> ResponseOutcome:
        """Decide whether/how Bob takes THIS turn by addressivity (BOB-023).

        Classifies who the message is for from the gateway's signals (``mentions_bob``,
        ``reply_to_sender_id`` against Bob's own resolved id, an "Боб, …" name-address
        in the text), reads whether the recent thread has other participants, then maps
        that to an outcome (ENGAGE / REACT / SILENT) via the pure
        :func:`~bob.domain.personality.addressivity.decide_response`. One seeded RNG draw
        (the same injected RNG, so the turn stays reproducible) resolves the rare
        barge-in / like-react branches. Pure-ish: only reads recent history + the id seam.
        """
        present = await self._others_present(event)
        addressivity = classify_addressivity(
            text=event.text,
            mentions_bob=event.mentions_bob,
            reply_to_sender_id=event.reply_to_sender_id,
            bob_user_id=self._bob_user_id(),
            others_present=present,
        )
        roll = self._rng.random()
        return decide_response(
            addressivity,
            interest=interest,
            others_present=present,
            roll=roll,
            thresholds=self._addressivity_thresholds,
        )

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
    ) -> str:
        """Compose a full reply, folding the plan's form hint into the prompt.

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
            plan,
            user_repeated=user_repeated,
            interlocutor=interlocutor,
            is_guest=is_guest,
            prior_impression=prior_impression,
            relationship=relationship,
            engagement=engagement,
            sulk=sulk,
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
    ) -> str:
        """Recompose once if ``reply`` byte-repeats Bob's last reply (BOB-022).

        The verbatim-repeat bug was greedy decoding: an identical prompt returned
        byte-identical text. Sampling temperature (the primary fix) makes that
        stochastic; this is defense in depth. Only an EXACT duplicate (after strip)
        of Bob's most-recent prior reply on record triggers a single regeneration —
        the retry, drawn stochastically, almost always differs. If it is still
        identical it is kept, so there is never more than one extra generation.
        """
        previous = _last_bob_reply(history)
        if not previous or reply.strip() != previous.strip():
            return reply
        return await self._compose_reply(
            text,
            soul,
            recalled,
            history,
            plan,
            user_repeated=user_repeated,
            interlocutor=interlocutor,
            is_guest=is_guest,
            prior_impression=prior_impression,
            relationship=relationship,
            engagement=engagement,
            sulk=sulk,
        )

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
        plan: ExpressionPlan,
        *,
        user_repeated: bool = False,
        interlocutor: Interlocutor | None = None,
        is_guest: bool = False,
        prior_impression: str | None = None,
        relationship: Relationship | None = None,
        engagement: EngagementLevel = EngagementLevel.FULL,
        sulk: SulkState | None = None,
    ) -> str:
        """Augment the base prompt with the mood tone, stance, and form-hint directives.

        The mood-conditioned tone directive (BOB-020) leads: a normal/good mood keeps
        Bob's warm, concise tone, a flat low mood swaps it for the quieter, honest
        off-day band ("не знаю" over confabulation) — replacing the old unconditional
        warm line. The taste verdict + conviction on ``text`` then pick the zone and
        stance (BOB-013), and the plan's ``form_hint`` appends a soft length cue
        (BOB-018). When ``user_repeated`` (BOB-022 — the owner sent a near-verbatim
        repeat) the user-repeat directive is appended so Bob notices it in voice. When
        an ``interlocutor`` is perceived (BOB-019) the who-is-writing line is appended
        so Bob answers as someone who knows WHO is on the other side (the owner
        recognised AS owner) — additive, never changing which pipeline runs. With a
        normal mood, no target opinion, no user-domain signal, a NORMAL form hint, no
        repeat, and no perceived interlocutor, only the warm tone line augments the
        base voice.
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
            _FORM_HINT_DIRECTIVE.get(plan.form_hint, ""),
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


def _last_bob_reply(history: Sequence[Mapping[str, object]]) -> str:
    """Return Bob's most-recent reply text from the replayed history, or ``""``.

    Episodes are stored as ``"<sender>: <text>\\nbob: <reply>"`` (see
    :meth:`HandleMessage._persist`); this scans the most-recent episodes back to
    front and recovers the ``bob:`` half so the anti-repeat guard can compare the
    fresh reply against it (BOB-022). No Bob turn on record yields ``""``.
    """
    for item in reversed(list(history)):
        content = item.get("content")
        if not isinstance(content, str):
            continue
        marker = content.rfind(_BOB_TURN_MARKER)
        if marker != -1:
            return content[marker + len(_BOB_TURN_MARKER) :]
    return ""


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
