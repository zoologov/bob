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
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from bob.application.reliability import call_with_retry
from bob.application.router.llm_router import LLMRequest, TaskType
from bob.application.router.reply_tier_selector import select_reply_tier
from bob.application.usecases.update_mood_from_text import TextSignals
from bob.capabilities.diagrams import (
    extract_mermaid_blocks,
    normalize_mermaid,
    strip_mermaid_blocks,
)
from bob.capabilities.usecases.progress_announcer import GatewayProgressAnnouncer
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.domain.personality.absence import absence_hint
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
    closer_text,
    is_bob_repeat,
    is_phrase_tic,
    is_recurring_closer_tic,
    is_user_repeat,
    recalled_bob_replies,
    recalled_bob_reply,
    recalled_excluding_reflections,
    recalled_without_copied_exemplars,
    recurring_closer,
    strip_recurring_closer,
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
from bob.domain.personality.reaction_aloud import acknowledgment_hint
from bob.domain.personality.relationship import compromise_bias
from bob.domain.personality.response_choice import ResponseIntent
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
    sulk_directive,
    tone_directive,
    user_repeat_directive,
    variable_form_directive,
    who_is_writing_directive,
)
from bob.domain.personality.volatility_judgment import VolatilityContext
from bob.domain.personality.zone_classifier import TasteZoneClassifier
from bob.domain.ports import DiagramRenderError, DiagramResult
from bob.memory.entities import EpisodicEvent
from bob.proactivity.self_improvement import RuleModulators, build_modulators

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from random import Random

    from bob.application.reliability import Sleep
    from bob.application.router.llm_router import LLMRouter
    from bob.application.runtime.events import MessageReceived
    from bob.application.usecases.decide_response import DecideResponse
    from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
    from bob.capabilities.usecases.progress_announcer import InterimLineGenerator
    from bob.domain.personality.fascination import Fascination
    from bob.domain.personality.interlocutor import Interlocutor
    from bob.domain.personality.mood import Mood
    from bob.domain.personality.relationship import Relationship
    from bob.domain.personality.response_choice import ResponseChoice
    from bob.domain.personality.soul import SOUL
    from bob.domain.personality.sulk import SulkState
    from bob.domain.personality.volatility_judgment import (
        VolatilityJudge,
        VolatilityVerdict,
    )
    from bob.domain.ports import (
        Clock,
        CloserLog,
        ConversationFloorStore,
        DiagramRenderer,
        DiagramSink,
        LLMMessage,
        MemoryRecall,
        MessageReactor,
        NotableReactionStore,
        Recalled,
        ReflectionReader,
        ToolCallingProvider,
        WebSearchProvider,
        ZoneClassifier,
    )
    from bob.memory.usecases.extract_facts import ExtractFacts
    from bob.proactivity.self_improvement import ImprovementRule

logger = logging.getLogger(__name__)

# Reliability defaults (BOB-049 .3 — «полный Боб или честный GUPPI-нотис»). An ESSENTIAL
# LLM step (the semantic judgment, the reply generation) is retried a bounded number of
# times before Bob falls back to the honest outage notice — never a degraded half-answer.
# ``_DEFAULT_ESSENTIAL_ATTEMPTS`` is the TOTAL number of tries (one initial call + two
# retries); the short backoff is awaited through an injected sleep seam (deterministic in
# tests). Both tunable per persona via ``reliability.*``.
_DEFAULT_ESSENTIAL_ATTEMPTS = 3
_DEFAULT_ESSENTIAL_BACKOFF_SECONDS = 0.5

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

# The SOFT anti-tic nudge (BOB-061 .2 — the «провязка»). When Bob's recent closers
# (the cross-session persist ring UNION the live session window) cluster into ONE
# recurring motif — a genuine closer-tic caught by
# :func:`~bob.domain.personality.conversation.is_recurring_closer_tic` at the CONSERVATIVE
# ``motif_similarity_threshold`` — this ONE line folds into the generation context. 🔴 It
# is a NUDGE toward variety, never a ban / forbidden-phrase list / topic restriction: Bob
# is asked to END DIFFERENTLY, in his own words, WITHOUT changing the meaning — so liveness
# (US-4) is intact and no legitimate meaning-level repetition is hollowed out. It fires
# ONLY on a genuinely detected tic; on no tic the reply context is byte-for-byte unchanged.
_CLOSER_TIC_NUDGE = (
    "Эту концовку/оборот ты в последнее время повторяешь часто — заверши ПО-ДРУГОМУ, "
    "своими словами (не меняя смысла)."
)

# Pre-answer epistemic verify (BOB-057 .2). BEFORE generation a conservative Tier-0
# ``VolatilityJudge`` decides whether the answer hinges on a FRESH volatile fact; on
# ``needs_check`` Bob makes ONE DIRECT ``WebSearchProvider.search`` (NOT via the
# capability registry / tool-loop → not the BOB-052 per-sender gate — an internal
# public-verify that exposes only public web info) and folds the finding into the
# reply-generation context. Everything is decorative: a judge failure degrades to
# «no check» (normal answer), a search failure/timeout/empty to an honest hedge —
# the turn is never blocked or broken.
_DEFAULT_VERIFY_TIMEOUT_SECONDS = 75.0

# The web finding is trimmed before it enters the generation context (it only needs to
# ground the answer, not dump the whole search payload into the prompt).
_VERIFY_ANSWER_MAX_CHARS = 800

# The GROUNDED note (US-1/US-4 + BOB-060 .2 register-nudge): the fresh finding + an
# explicit steer to present it IN BOB'S OWN VOICE, reacting to it — NOT as a generic
# agent report («выполнен поиск, найдено N…»). The tone adapts through generation,
# unprogrammed; the note only nudges the register, never the search mechanism.
_VERIFY_GROUNDED_NOTE = (
    "СВЕЖАЯ ПРОВЕРКА (веб): {answer}. Ты сходил и глянул это в сети — отреагируй "
    "по-своему, как БОБ, со своим отношением и тоном, если картина изменилась; "  # noqa: RUF001
    "НЕ отчётом («выполнен поиск, найдено…»), не сухой сводкой."  # noqa: RUF001
)

# The HEDGE note (US-6 + BOB-060 .2): on a failed/timed-out/empty verify Bob makes an
# HONEST epistemic caveat — 🔴 never a confident STALE number dressed as fact, never a
# fabrication (BOB-053 invariant). The register-nudge steers a LIVE, in-voice caveat
# (not a robotic «поиск не удался»), without weakening the anti-confabulation intent.
_VERIFY_HEDGE_NOTE = (
    "Свериться со свежими данными по {topic} не вышло — скажи это честно и живо, "  # noqa: RUF001
    "своими словами (не сухим «поиск не удался»); не выдавай устаревшие цифры за "
    "точные и ничего не выдумывай."
)

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


class NaturalCodingRouter(Protocol):
    """The natural-language coding-intent seam HandleMessage delegates to (BOB-041 .2).

    Realised by
    :class:`~bob.coding.usecases.coding_intent_router.CodingIntentRouter`: given an
    owner message in Bob's topic it decides WHEN to drive the gated coding session
    (plan / approve / stop) and returns whether it CONSUMED the turn (so HandleMessage
    short-circuits the normal compose). Owner-only and gate-bound live in the router +
    the use-case + the domain machine, never here. Unwired (the default) OR ``coder.enabled``
    false → no router is injected, so the natural-language path is inert and every
    message takes the normal chat flow exactly as before.
    """

    async def route(self, *, text: str, sender: int | None, is_owner: bool) -> bool: ...


class PermissionFlowLike(Protocol):
    """The permission-flow seam HandleMessage delegates privilege gating to (BOB-052 .2).

    Realised by :class:`~bob.application.usecases.permission_flow.PermissionFlow`. On a
    turn it owns two decisions, each returning whether it CONSUMED the turn (so
    HandleMessage short-circuits the normal compose): ``maybe_decide`` records the
    OWNER's verdict on an active pending request (grant / deny / authorize), and
    ``maybe_request`` opens a pending request + asks the owner when a NON-authorized
    member asks for something privileged. 🔴 Owner-only decision and the
    non-authorized-only request gate live INSIDE the flow; HandleMessage only passes the
    perceived authz facts. Unwired (the default) the seam is inert and every message
    takes the normal chat flow exactly as before.
    """

    async def maybe_decide(self, *, text: str, is_owner: bool) -> bool: ...

    async def maybe_request(
        self,
        *,
        text: str,
        requester_id: int,
        requester_name: str,
        is_owner: bool,
        is_authorized: bool,
        recent_thread: str = "",
    ) -> bool: ...


class OutageNotifier(Protocol):
    """GUPPI's honest-outage seam (BOB-049 .3 — «полный Боб или GUPPI-нотис»).

    When an ESSENTIAL turn step (the semantic judgment or the reply generation) keeps
    failing after the bounded retries, Bob — the mind — is unavailable. Rather than ship a
    degraded half-answer («уверенный бред», the antipattern), GUPPI (the infrastructure
    subsystem) honestly reports the outage into Bob's topic via this seam. Optional: with
    no notifier wired the turn still ends cleanly — the user's turn is persisted and NO
    degraded reply is produced — just without a visible notice. The concrete adapter sends
    a fixed system line through Bob's bot into his topic; the third-person text reads as
    GUPPI reporting, not Bob being rude.
    """

    async def notify_outage(self) -> None:
        """Post GUPPI's honest "Bob temporarily unavailable" connectivity notice."""
        ...


class _EssentialStepError(Exception):
    """An ESSENTIAL turn step failed after the bounded retries (BOB-049 .3).

    Raised by the retry-wrapped essential calls (the semantic judgment, the reply
    generation) so the turn falls back to the honest GUPPI outage notice instead of a
    degraded reply. Carries the step label for the log only — never shown to the user.
    """

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


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


@dataclass(frozen=True, slots=True)
class _AddressivitySignals:
    """This turn's structural addressivity signals (perception, BOB-023/025/049).

    The raw, grounded read of WHO the message is for: ``per_message`` is the
    per-message classification; ``effective`` is it raised by the conversation floor
    (continuity); ``others_present`` whether the thread has a third participant;
    ``floor_engaged`` whether the floor actually raised an ambient message to Bob;
    ``reply_to_bob`` whether the inbound replies to Bob's own message; and
    ``directed_to_id`` the person a ``DIRECTED_TO_OTHER`` turn turned to (for the
    floor pass), else ``None``. These are INPUTS — the legacy policy decides the
    outcome on ``effective`` (BOB-023/025), the BOB-049 judge weighs them by meaning.
    """

    per_message: Addressivity
    effective: Addressivity
    others_present: bool
    floor_engaged: bool
    reply_to_bob: bool
    directed_to_id: int | None


@dataclass(frozen=True, slots=True)
class _JudgedTurn:
    """The semantic judge's outcome for one turn + the pieces the flow reuses (BOB-049).

    ``choice`` is the judge's :class:`ResponseChoice` (REPLY / REACT / IGNORE +
    emoji); ``floor`` carries the RAW per-message addressivity the conversation floor
    advances on after the turn; ``history`` is the CURRENT person's per-person thread
    already replayed for the judgment, threaded into the REPLY compose path so it is
    not re-read.
    """

    choice: ResponseChoice
    floor: _AddressivityDecision
    history: Sequence[Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class _ReplyGate:
    """A turn that PASSED the response gate as a REPLY (BOB-049): compose+send next.

    ``decision`` is the floor signal the turn advances on after Bob replies;
    ``history`` is the CURRENT person's per-person thread already replayed for the
    judgment (the judge REPLY path), threaded into compose so it is not re-read —
    ``None`` on the legacy path, where compose replays it itself.
    """

    decision: _AddressivityDecision
    history: Sequence[Mapping[str, object]] | None


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
        # member's turn a privileged request opens a pending + asks the owner («Вова, <кто>
        # просит <что> — разрешить?») and the member is told «спрошу Вову». 🔴 Owner-only
        # decision + the non-authorized-only request gate live inside the flow; an
        # AUTHORIZED member never enters it. Either consumes the turn (the normal compose
        # is skipped). Unwired (the default) the seam is inert and the turn is unchanged.
        self._permission_flow = permission_flow
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

    async def _run_essential[T](
        self, operation: Callable[[], Awaitable[T]], *, step: str
    ) -> T:
        """Run an ESSENTIAL LLM step with bounded retry (BOB-049 .3).

        The semantic judgment and the reply generation are the steps whose persistent
        failure must NOT yield a degraded reply. Each is retried up to
        ``essential_attempts`` times with the injected backoff sleep; if every attempt
        raises, the last error is wrapped in :class:`_EssentialStepError` so the turn
        falls back to the honest GUPPI outage notice. OPTIONAL add-ons are never routed
        through here — they drop silently at their own call sites.
        """
        try:
            return await call_with_retry(
                operation,
                attempts=self._essential_attempts,
                backoff_seconds=self._essential_backoff_seconds,
                sleep=self._retry_sleep,
            )
        except Exception as exc:
            raise _EssentialStepError(step) from exc

    async def _notify_outage(self) -> None:
        """Emit GUPPI's honest outage notice into Bob's topic, best-effort (BOB-049 .3).

        Unwired notifier → a clean no-op (the turn already ended with no degraded reply).
        A flaky send is logged and swallowed so the failure handling itself can never
        raise on top of the original essential failure.
        """
        if self._outage_notifier is None:
            return
        try:
            await self._outage_notifier.notify_outage()
        except Exception:
            logger.exception("sending the GUPPI outage notice failed (ignored)")

    async def _handle_essential_failure(
        self, event: MessageReceived, soul: SOUL, exc: _EssentialStepError
    ) -> None:
        """End a turn whose ESSENTIAL step failed: persist + GUPPI notice (BOB-049 .3).

        🔴 «Полный Боб или честный GUPPI-нотис»: NO degraded reply is produced. The user's
        turn is persisted (so the message is not lost — consistent with .2) and GUPPI
        honestly reports the outage into Bob's topic. The same path runs for a guest turn
        (only the episodic record is written — no owner facts, no reply — so nothing leaks).
        """
        logger.warning(
            "essential turn step (%s) failed after %d attempts; "
            "emitting GUPPI outage notice (no degraded reply)",
            exc.step,
            self._essential_attempts,
        )
        await self._persist(event, _OUTAGE_MARKER, soul)
        await self._notify_outage()

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
        # Natural-language coding intent (BOB-041 .2): for an OWNER message in Bob's
        # topic (and only when the coder is wired/enabled), route a dev-work request
        # — or a natural approve/stop of a live session — into the gated CodingAssistant
        # BEFORE composing a normal reply. When it consumes the turn the message was a
        # coding command, so the normal perceive→decide→act flow is skipped (the gated
        # use-case owns its own owner messaging). 🔴 The router is owner-only and cannot
        # bypass the plan gate; a non-owner / non-coding message returns here unconsumed
        # and falls through to the normal chat path exactly as before.
        if await self._maybe_route_coding(event, interlocutor):
            return
        # Privilege gating (BOB-052 .2): BEFORE composing a normal reply, route the turn
        # through the permission flow. On the OWNER's turn it records a decision on an
        # active pending request (grant / deny / authorize); on a NON-authorized member's
        # turn a privileged request opens a pending + asks the owner. 🔴 Owner-only
        # decision + the non-authorized-only request gate live inside the flow (an
        # AUTHORIZED member is never gated). When it consumes the turn the message was a
        # privilege decision/request, so the normal perceive→decide→act flow is skipped.
        # Unwired (the default) this is inert and the turn falls through exactly as before.
        if await self._maybe_permission(event, interlocutor):
            return
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
            gate = await self._gate_turn(
                event, soul, interlocutor, plan, interest, modulators
            )
        except _EssentialStepError as exc:
            await self._handle_essential_failure(event, soul, exc)
            return
        if gate is None:
            return
        decision = gate.decision
        prefetched_history = gate.history
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
        # extraction (every member's turn feeds the shared/public group memory).
        is_guest = interlocutor is not None and interlocutor.trust is Trust.GUEST
        # Reflection containment (BOB-033 .3): the reply-recall pool excludes private
        # reflection episodes so Bob's inner monologue never becomes a copyable exemplar
        # in a user-facing reply — the inner life colours tone via MOOD, not by parroting
        # reflection TEXT. Facts + past message turns still ground the reply, and the
        # deliberate ``leak_inner_life`` path (below, via self._reflection) is untouched.
        # Recall is UNIFIED (BOB-051): Bob's full knowledge surfaces for owner and member
        # alike — no per-person scoping. Continuity (WHO Bob talked to) lives in the
        # per-person history thread (below), not in a knowledge restriction.
        recalled: Sequence[Recalled] = recalled_excluding_reflections(
            await self._recall.recall(event.text, k=_RECALL_K)
        )
        # On the judge REPLY path the shared recent thread was already replayed for the
        # judgment (BOB-049); reuse it so it is not read twice. Otherwise (legacy path)
        # replay it now — the SHARED group thread (BOB-058 .1), all participants labeled.
        history: Sequence[Mapping[str, object]] = (
            prefetched_history
            if prefetched_history is not None
            else await self._replay_recent_thread(interlocutor)
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
        try:
            async with self._gateway.typing_indicator(chat_id=event.chat_id):
                # 🔴 BOB-057 .5 (US-3 «один поиск, не петля»): compute the epistemic-verify
                # step (judge → interim → search → grounded/hedge note) EXACTLY ONCE per turn
                # as a PER-TURN LOCAL, then thread the SAME note into the first composition
                # AND every anti-repeat regeneration. This makes «один поиск» a consequence of
                # real structure — judge.assess / provider.search / the interim line each fire
                # at most once, even on a turn that is both volatile AND trips the tic. It is a
                # local (never a HandleMessage attribute) because the use case is a shared
                # singleton — an instance flag would leak the note / «already searched» state
                # across turns and concurrent users. ``""`` when the judge says «no check».
                verify_note = await self._verify_note(
                    event.text,
                    history,
                    interlocutor=interlocutor,
                    chat_id=event.chat_id,
                )
                # Anti-tic «провязка» (BOB-061 .2): BEFORE generation, detect whether Bob's
                # recent closers (persist ring + live window) cluster into ONE recurring
                # motif. When they do, (a) STRIP that motif off the recalled Bob-reply
                # exemplars so the tic is not fed back as few-shot, and (b) fold a SOFT
                # nudge («заверши по-другому») into the generation context — carried through
                # the first composition AND every anti-repeat regeneration this turn. 🔴
                # Fully decorative: on no tic (or an unwired/failing log) ``recalled`` is
                # unchanged and the nudge is "" — zero change to the reply (US-4 liveness).
                recalled, closer_nudge = await self._closer_anti_tic(recalled, history)
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
                    chat_id=event.chat_id,
                    verify_note=verify_note,
                    closer_nudge=closer_nudge,
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
                    verify_note=verify_note,
                    closer_nudge=closer_nudge,
                )
        except _EssentialStepError as exc:
            await self._handle_essential_failure(event, soul, exc)
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
        reply = await self._autorender_inline_mermaid(reply)
        # Send any diagrams the render_diagram capability queued this turn (BOB-035):
        # the tool-loop (inside _compose_reply) pushed each rendered PNG into the
        # per-turn sink; here — where the chat_id and the gateway live — they are
        # drained and posted as Telegram photos BEFORE the text confirmation, so the
        # image leads. Best-effort and gated on a wired sink (no diagram skill → no-op).
        await self._send_pending_diagrams(event.chat_id)
        # Capture the Telegram message_id of Bob's outgoing reply (BOB-050) so the
        # episode records which message was Bob's — a later reaction on it can then be
        # linked back to what Bob said. ``None`` if nothing was sent (degraded path).
        bob_message_id = await self._gateway.reply(
            chat_id=event.chat_id, markdown=reply
        )
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
        await self._persist(event, reply, soul, bob_message_id=bob_message_id)
        # Log Bob's closer to the cross-session ring (BOB-061 .2): only a GENUINE reply
        # feeds the anti-tic memory (the silent/react/outage markers persist through their
        # own paths and are never logged). 🔴 Decorative — a failed append is swallowed so
        # this local memory can never break a turn that already replied; an empty closer is
        # skipped.
        await self._log_closer(reply)
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

    async def _maybe_route_coding(
        self, event: MessageReceived, interlocutor: Interlocutor | None
    ) -> bool:
        """Route an owner coding-intent message into the gated session (BOB-041 .2).

        Returns whether the natural-language coding path CONSUMED the turn (so the
        caller short-circuits the normal compose). Inert when no router is wired (the
        default / ``coder.enabled`` false). Owner is derived from the perceived
        interlocutor — only an :class:`~bob.domain.personality.interlocutor.InterlocutorKind.OWNER`
        sender is ever owner here, so with no perception seam (or a guest/known sender)
        the message is never routed (``is_owner`` false) and the router itself re-checks;
        the gated use-case re-checks the owner again (defense-in-depth).
        """
        if self._coding_router is None:
            return False
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        return await self._coding_router.route(
            text=event.text, sender=event.sender_id, is_owner=is_owner
        )

    async def _maybe_permission(
        self, event: MessageReceived, interlocutor: Interlocutor | None
    ) -> bool:
        """Route the turn through the permission flow; return whether it consumed it.

        Inert when no flow is wired (the default). The authz facts are derived from the
        perceived interlocutor: OWNER → owner; a TRUSTED non-owner (KNOWN) → authorized;
        a GUEST → non-authorized. 🔴 On the OWNER's turn the flow may record a decision
        on an active pending; on a NON-authorized member's turn it may open a privileged
        request and ask the owner. The flow itself enforces owner-only decision and the
        non-authorized-only request gate — an AUTHORIZED member is never gated. With no
        perceived interlocutor (no perception seam) the message is treated as
        non-owner/non-authorized only for the request path, and the owner-decision path
        cannot fire — so an unidentified turn is never auto-approved.
        """
        if self._permission_flow is None:
            return False
        is_owner = (
            interlocutor is not None and interlocutor.kind is InterlocutorKind.OWNER
        )
        is_authorized = interlocutor is not None and interlocutor.trust is Trust.TRUSTED
        if is_owner and await self._permission_flow.maybe_decide(
            text=event.text, is_owner=True
        ):
            return True
        if event.sender_id is None:
            return False
        return await self._permission_flow.maybe_request(
            text=event.text,
            requester_id=event.sender_id,
            requester_name=event.sender_name or "",
            is_owner=is_owner,
            is_authorized=is_authorized,
        )

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
        signals = await self._addressivity_signals(event)
        roll = self._rng.random()
        outcome = decide_response(
            signals.effective,
            interest=interest,
            others_present=signals.others_present,
            roll=roll,
            thresholds=self._addressivity_thresholds,
        )
        return _AddressivityDecision(
            outcome=outcome,
            per_message=signals.per_message,
            directed_to_id=signals.directed_to_id,
        )

    async def _addressivity_signals(
        self, event: MessageReceived
    ) -> _AddressivitySignals:
        """Compute this turn's structural addressivity signals (BOB-023/025/049).

        The shared perception both the legacy policy and the BOB-049 judge read:
        classify who the message is for from the gateway's signals (``mentions_bob``,
        ``reply_to_sender_id`` against Bob's own resolved id, an "Боб, …" name-address),
        read whether the recent thread has other participants, then raise the per-message
        classification to the EFFECTIVE addressivity by the conversation floor (BOB-025 —
        an ambient message in a thread where Bob holds a live floor reads as continuity).
        ``floor_engaged`` records when that raise actually fired (Bob holds the floor);
        ``reply_to_bob`` whether the inbound replies to Bob; ``directed_to_id`` the person
        a ``DIRECTED_TO_OTHER`` turn turned to. These are INPUTS only — the policy decides
        on ``effective``, the judge weighs them by meaning; neither overrides the other.
        """
        present = await self._others_present(event)
        bob_id = self._bob_user_id()
        per_message = classify_addressivity(
            text=event.text,
            mentions_bob=event.mentions_bob,
            reply_to_sender_id=event.reply_to_sender_id,
            bob_user_id=bob_id,
            others_present=present,
        )
        effective = await self._resolve_effective_addressivity(event, per_message)
        floor_engaged = (
            effective is Addressivity.DIRECTED_TO_BOB
            and per_message is not Addressivity.DIRECTED_TO_BOB
        )
        reply_to_bob = bob_id is not None and event.reply_to_sender_id == bob_id
        directed_to_id = (
            event.reply_to_sender_id
            if per_message is Addressivity.DIRECTED_TO_OTHER
            else None
        )
        return _AddressivitySignals(
            per_message=per_message,
            effective=effective,
            others_present=present,
            floor_engaged=floor_engaged,
            reply_to_bob=reply_to_bob,
            directed_to_id=directed_to_id,
        )

    async def _gate_turn(
        self,
        event: MessageReceived,
        soul: SOUL,
        interlocutor: Interlocutor | None,
        plan: ExpressionPlan,
        interest: float,
        modulators: RuleModulators,
    ) -> _ReplyGate | None:
        """Decide whether/how Bob takes this turn (BOB-049 judge, or legacy fallback).

        With the semantic judge wired (the LIVE path) Bob UNDERSTANDS the message and
        chooses REPLY / REACT / IGNORE — the structural signals are INPUTS he weighs, not
        deciders, and the decision holds for ANY interlocutor (authz orthogonal). A
        non-REPLY (REACT / IGNORE) is fully handled here — it persists the user's turn (so
        a follow-up keeps the per-person thread, BOB-045) and advances the floor — and
        returns ``None`` so the caller stops. A REPLY returns a :class:`_ReplyGate` so the
        caller composes+sends (guest restrictions intact). Unwired (the default) OR no
        sender perceived → the legacy addressivity ladder (BOB-023/025) + the BOB-018
        REACT_ONLY form gate run exactly as before (their silent/react early-outs return
        ``None`` WITHOUT persisting, as today).
        """
        if self._decide_response is not None and interlocutor is not None:
            judged = await self._judge_turn(event, soul, interlocutor)
            if judged.choice.intent is not ResponseIntent.REPLY:
                await self._act_non_reply(event, soul, judged.choice, judged.floor)
                return None
            return _ReplyGate(decision=judged.floor, history=judged.history)
        # Legacy addressivity path (BOB-023/025). ADDRESSIVITY self-improvement tilt
        # (BOB-028 .3): an APPROVED ADDRESSIVITY_BIAS rule softly RAISES the effective
        # interest the policy reads — a bounded nudge (clamped to [0, 1]) on TOP of the
        # decision, never a base override and never able to silence Bob. No rule → unchanged.
        addressivity_interest = _clamp_unit(interest + modulators.addressivity_bias)
        decision = await self._decide_addressivity(event, addressivity_interest)
        if decision.outcome is ResponseOutcome.SILENT:
            await self._advance_floor_after_turn(event, decision, bob_replied=False)
            return None
        if decision.outcome is ResponseOutcome.REACT and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            await self._advance_floor_after_turn(event, decision, bob_replied=False)
            return None
        # React-only (BOB-018): when a reactor is wired and the plan picks REACT_ONLY, Bob
        # acknowledges with a native mood emoji INSTEAD of composing a reply — no LLM call,
        # no rich final, no episode (there is no reply text). It is still real engagement,
        # so the owner-activity marker fires. Unwired, the plan falls back to a full reply.
        if plan.mode is ExpressionMode.REACT_ONLY and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            await self._advance_floor_after_turn(event, decision, bob_replied=False)
            return None
        return _ReplyGate(decision=decision, history=None)

    async def _judge_turn(
        self, event: MessageReceived, soul: SOUL, interlocutor: Interlocutor
    ) -> _JudgedTurn:
        """Ask the semantic judge how Bob takes this turn (BOB-049, the LIVE path).

        Assembles the turn's context — the message, the sender as social context, the
        SHARED recent thread of the whole topic (BOB-058 .1: all participants, author-
        labeled, so Bob holds the multi-party thread), the structural HINTS and the mood
        tone — and delegates
        the single semantic decision to the injected :class:`DecideResponse`. The judge
        raises on failure (the fault-tolerant path is BOB-049 .3); here we assume success.
        Returns the choice plus the floor signal (RAW per-message addressivity) and the
        already-replayed history so a REPLY does not re-read it.
        """
        assert self._decide_response is not None  # guarded by the caller
        decide_response = self._decide_response
        signals = await self._addressivity_signals(event)
        history = await self._replay_recent_thread(interlocutor)
        # ESSENTIAL step (BOB-049 .3): the semantic judgment is retry-wrapped — a flaky
        # judge call retries with backoff, then (if still failing) raises
        # _EssentialStepError so the turn falls back to the honest GUPPI outage notice
        # rather than a guessed default. A SUCCESSFUL REACT/IGNORE is a genuine choice,
        # not a failure (no retry, no notice).
        choice = await self._run_essential(
            lambda: decide_response.decide(
                text=event.text,
                interlocutor=interlocutor,
                recent_thread=_render_thread(history),
                mentions_bob=event.mentions_bob,
                reply_to_bob=signals.reply_to_bob,
                addressivity=signals.per_message,
                others_present=signals.others_present,
                floor_engaged=signals.floor_engaged,
                mood_tone=soul.mood.tone(),
            ),
            step="response judgment",
        )
        floor = _AddressivityDecision(
            outcome=_OUTCOME_FOR_INTENT[choice.intent],
            per_message=signals.per_message,
            directed_to_id=signals.directed_to_id,
        )
        return _JudgedTurn(choice=choice, floor=floor, history=history)

    async def _act_non_reply(
        self,
        event: MessageReceived,
        soul: SOUL,
        choice: ResponseChoice,
        decision: _AddressivityDecision,
    ) -> None:
        """Carry out a REACT or IGNORE turn: persist the user's turn + advance (BOB-049).

        🔴 The user's turn is persisted in BOTH branches so a follow-up always has the
        prior turn in the per-person thread (BOB-045): REACT records ``bob: (реакция:
        <emoji>)`` and sets the meaning-chosen emoji on the inbound, IGNORE records
        ``bob: (промолчал)``. Only the episodic conversation record is written — never an
        owner FACT (no fact extraction here), so a guest turn never enters owner memory
        (BOB-019). The floor advances with ``bob_replied=False`` and the owner-activity
        marker fires (the owner did interact this turn). No reply text → no typing
        indicator / router call.
        """
        if choice.intent is ResponseIntent.REACT:
            emoji = choice.emoji or reaction_emoji_for(soul.mood)
            await self._react_with_emoji(event, emoji)
            await self._persist(event, _reaction_marker(emoji), soul)
        else:
            await self._persist(event, _SILENT_MARKER, soul)
        await self._advance_floor_after_turn(event, decision, bob_replied=False)
        await self._record_owner_activity()

    async def _react_with_emoji(self, event: MessageReceived, emoji: str) -> None:
        """Set the meaning-chosen emoji reaction on the inbound, best-effort (BOB-049).

        The judge picked the emoji BY MEANING (replacing the BOB-018 mood→emoji table as
        the source). When a reactor is wired it is set on the user's message; unwired the
        decision still stands (the turn persists as a reaction) but no native reaction is
        sent — a clean no-op, so the path stays backward-compatible.
        """
        if self._reactor is None:
            return
        await self._reactor.react(
            chat_id=event.chat_id, message_id=event.message_id, emoji=emoji
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

    async def _replay_recent_thread(
        self, interlocutor: Interlocutor | None
    ) -> Sequence[Mapping[str, object]]:
        """Replay the SHARED recent thread of the whole topic (BOB-058 .1).

        The conversation context for judgment + reply is the group's recent thread —
        the last ``recent_turns`` episodes across ALL participants (``recent_episodes``),
        already author-labeled ``"<name>: …\\nbob: …"``. So Bob hears the whole room and
        holds the multi-party thread: when Vladimir asks Bob to answer Lyosha, Alexey's
        film message is right there in the context (US-1/2/3) instead of hidden behind a
        per-person replay. Memory is unified for the closed group (BOB-051), so the shared
        read is safe — it is ordinary topic traffic, not owner-private material.

        Scope hook (BOB-058 .1): a PUBLIC group reads the shared thread. A future
        PRIVATE/DM scope would read the CURRENT interlocutor's per-person slice
        (``recent_episodes_for(interlocutor.sender_id, …)``) instead — only the public
        group exists today, so the per-person branch is intentionally NOT wired here. The
        ``interlocutor`` argument is retained as the seam that a private scope would key on.
        """
        del interlocutor  # public group → shared thread (see the scope hook above)
        return await self._episodes.recent_episodes(self._recent_turns)

    def _absence_for(
        self,
        history: Sequence[Mapping[str, object]],
        interlocutor: Interlocutor | None,
    ) -> str | None:
        """A light long-gap absence hint for the CURRENT person, or ``None`` (BOB-045 .3).

        🔴 Per-person over the SHARED thread (BOB-058 .3): ``history`` is now the whole
        group's recent thread, so the last-seen must be filtered to the CURRENT author's
        own turns (by ``sender_id``, robust to homonyms / renames — the ``"<name>:"`` label
        stays only for rendering) before reading the freshest timestamp — a DIFFERENT member
        speaking recently must never reset THIS person's gap. Via the pure :func:`absence_hint`
        domain helper the
        gap to ``self._clock.now()`` becomes a SHORT neutral note Bob can fold in to notice
        the pause humanly. Returns ``None`` — add no line, unchanged behaviour — when the
        current author has no turn in the shared window (graceful, exactly like an empty
        history today), on an unparseable timestamp, a gap under the configured threshold,
        or the hint disabled (``absence_hint_hours == 0``). Deterministic given the clock.
        """
        mine = _history_for_author(history, _author_key(interlocutor))
        last_seen = _last_seen_at(mine)
        if last_seen is None:
            return None
        return absence_hint(
            last_seen, self._clock.now(), threshold_hours=self._absence_hint_hours
        )

    async def _acknowledgment_for(self, interlocutor: Interlocutor | None) -> str:
        """A RARE being-received acknowledgment hint for THIS person, or "" (BOB-050 .3).

        When someone reacted warmly to one of Bob's recent messages, Bob may — at the
        small seeded ``acknowledge_reaction_freq`` — fold ONE light HINT into the compose
        context so he can naturally mention being received (he weaves it himself; never a
        scripted phrase). Returns ``""`` — add no line, behave as before — unless ALL hold:
        a store is wired, a notable reaction is on record, its reactor is THIS interlocutor
        (per-person / BOB-019 authz: a guest's reaction never surfaces to the owner and
        vice-versa; an anonymous reaction has no person to acknowledge), and the seeded roll
        lands inside the low frequency. The marker is read BEFORE the roll, so an unlucky
        turn spends no draw and LEAVES the marker for a later turn; on a lucky turn it is
        CLEARED (consumed) so Bob acknowledges the moment at most once — never needy. The
        whole call is wrapped by :meth:`_safe_addon` at the call site, so a store failure is
        dropped silently (decorative, never an outage notice).
        """
        if self._notable_reaction is None or interlocutor is None:
            return ""
        note = await self._notable_reaction.latest()
        if note is None or note.sender_id is None:
            return ""
        if note.sender_id != interlocutor.sender_id:
            return ""
        if self._rng.random() >= self._acknowledge_reaction_freq:
            return ""
        await self._notable_reaction.clear()
        return acknowledgment_hint(note)

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
            history = await self._episodes.recent_episodes(self._recent_turns)
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
        chat_id: int | None = None,
        verify_note: str | None = None,
        closer_nudge: str = "",
    ) -> str:
        """Compose a full reply, folding the decided verbosity into the prompt.

        On a guest turn (``is_guest``) the PRIVILEGE restriction applies (BOB-051 keeps
        the authz gate while memory/voice are unified): the grounded owner inner-life
        add-ons (leak / callback / fascination) are skipped (they surface Bob's private
        inner world) and the tool-loop is NEVER used (a guest can trigger no capability)
        — the application half of the security invariant. Recall, history and voice are
        unified for the closed group and no longer branch on guest status.
        """
        context = _assemble_shareable_context(
            soul, text, recalled, history, absence=self._absence_for(history, interlocutor)
        )
        # Being-received acknowledgment (BOB-050 .3): a RARE, per-person hint that someone
        # warmly reacted to one of Bob's messages — applies to ANY interlocutor (owner and
        # guest alike, since it is about Bob's OWN message, not owner-private material) and
        # is wrapped so a store failure drops silently (decorative, never the outage notice).
        acknowledgment = await self._safe_addon(
            self._acknowledgment_for(interlocutor), name="reaction acknowledgment"
        )
        if acknowledgment:
            context = f"{context}\n{acknowledgment}"
        if not is_guest:
            # Grounded add-ons surface Bob's PRIVATE inner life / shared past —
            # withheld from a stranger (audience redaction).
            context = await self._with_grounded_addons(context, text, plan)
        # Pre-answer epistemic verify (BOB-057 .2): a conservative Tier-0 judge decides if
        # the answer hinges on a FRESH volatile fact; if so Bob does ONE DIRECT web_search
        # (ungated internal public-verify — see _verify_note) and this grounded/hedge note
        # folds into the SAME generation context as the other add-ons. Applies to owner and
        # guest alike (public web info, no owner/private leak). Wrapped so ANY failure drops
        # to «no note» — never blocks or breaks the turn (zero added latency when inert).
        #
        # 🔴 BOB-057 .5 (US-3 «один поиск, не петля»): the verify step is computed EXACTLY
        # ONCE per turn and THREADED IN via ``verify_note`` so the anti-repeat regeneration
        # loop (``_guard_against_verbatim_repeat``) REUSES it instead of re-judging /
        # re-searching / re-announcing on every retry. ``None`` = «not yet computed» (the
        # first composition falls through and computes it); any string (INCLUDING ``""`` =
        # «judged, no note») means «already computed this turn» → reuse verbatim. The cache
        # is this PER-TURN LOCAL parameter, NOT an instance attribute — ``HandleMessage`` is
        # a shared singleton, so an instance flag would leak the note (and the «already
        # searched» state) across turns/users.
        if verify_note is None:
            verify_note = await self._verify_note(
                text, history, interlocutor=interlocutor, chat_id=chat_id
            )
        if verify_note:
            context = f"{context}\n{verify_note}"
        # Anti-tic soft nudge (BOB-061 .2): when a recurring closer-tic was detected for
        # this turn (persist + window), the single nudge line steers Bob to END DIFFERENTLY
        # — a push toward variety, never a ban. Empty on no tic (US-4 liveness: the context
        # is then byte-for-byte the pre-BOB-061 context).
        if closer_nudge:
            context = f"{context}\n{closer_nudge}"
        system_prompt = self._system_prompt_for(
            soul,
            text,
            user_repeated=user_repeated,
            interlocutor=interlocutor,
            prior_impression=prior_impression,
            relationship=relationship,
            engagement=engagement,
            sulk=sulk,
            verbosity=verbosity,
            modulators=modulators,
        )
        provider = self._tool_provider
        # ESSENTIAL step (BOB-049 .3): the reply generation is retry-wrapped — a flaky
        # router/tool-loop call retries with backoff, then (if still failing) raises
        # _EssentialStepError so the turn ends in the honest GUPPI outage notice rather
        # than a degraded half-answer. The OPTIONAL grounded add-ons folded above already
        # dropped silently on their own (a flaky add-on never reaches here / never trips
        # the notice).
        if not is_guest and provider is not None and not self._registry.is_empty:
            tool_sender_name = (
                interlocutor.display_name if interlocutor is not None else ""
            )
            return await self._run_essential(
                lambda: self._reply_with_tools(
                    provider,
                    system_prompt,
                    text,
                    context,
                    chat_id=chat_id,
                    sender_name=tool_sender_name,
                ),
                step="reply generation",
            )
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
        return await self._run_essential(
            lambda: self._router.run(request), step="reply generation"
        )

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
        verify_note: str | None = None,
        closer_nudge: str = "",
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
        # BOB-043: a WIDE window of Bob's recent closers. The signature tic is SCATTERED
        # (~21% prevalence), so the narrow per-turn view (recent history + query-recall)
        # sees it 0-1 times -- below the occurrence bar -- and BOB-036 misses it live.
        # Over the last ``tic_lookback`` (~20) replies it recurs ~4 times -> reliably >=2
        # -> caught. The only new I/O: one extra recent_episodes read (BOB-051: runs for
        # every member — it scans Bob's OWN closers, not owner-private material).
        wide_replies = await self._recent_bob_closers()
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
            # BOB-043: ADD the wide-lookback check — a tic too scattered for the narrow
            # union still recurs across Bob's last ~tic_lookback closers.
            wide_tic = is_phrase_tic(
                current,
                wide_replies,
                min_words=tic_min_words,
                min_occurrences=tic_min_occurrences,
            )
            if not (full_repeat or phrase_tic or wide_tic):
                return current
            # Break the attractor: strip the recalled reply exemplar(s) the candidate
            # copied so the next draft no longer sees the text it was echoing.
            current_recalled = recalled_without_copied_exemplars(
                current, current_recalled, threshold=threshold
            )
            # 🔴 BOB-057 .5 (US-3 «один поиск, не петля»): REUSE the verify note computed
            # once for this turn instead of recomputing it on every regeneration. Threading
            # the same ``verify_note`` here means judge.assess / provider.search / the live
            # interim line each fire AT MOST ONCE per turn, even across the attractor-breaking
            # retries. ``chat_id`` is intentionally omitted on regeneration (as before) — the
            # interim already spoke on the first pass and rides the same once-per-turn compute.
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
                verify_note=verify_note,
                closer_nudge=closer_nudge,
            )
        # BOB-043: regeneration could not shake the tic (it keeps re-copying the closer
        # from recalled exemplars — a self-reinforcing loop). If the final draft STILL
        # ends with a closer that RECURS across the wide window, deterministically STRIP
        # that trailing sentence so the tic NEVER ships. Only a genuinely recurring closer
        # is removed (``recurring_closer`` returns None for a one-off ending) — no false
        # positive, and the substantive reply survives. The WIDE window is the
        # authoritative recurrence signal (and a superset of ``recent``), so a one-off
        # full-repeat — which recurs only once there — is never stripped.
        closer = recurring_closer(
            current,
            wide_replies,
            min_words=tic_min_words,
            min_occurrences=tic_min_occurrences,
        )
        if closer is not None:
            # Guard the edge case where the ENTIRE reply is the recurring closer (a bare
            # "Мне так спокойнее."): stripping would leave an empty string, so keep the
            # last draft rather than ship nothing (BOB-043 review).
            stripped = strip_recurring_closer(current, closer)
            return stripped if stripped.strip() else current
        return current

    async def _recent_bob_closers(self) -> tuple[str, ...]:
        """Bob's last ``tic_lookback`` reply texts for the wide tic check (BOB-043).

        The single new read behind the anti-repeat guard: a WIDE window of Bob's recent
        replies (whose closers the phrase-tic detector scans) via the existing
        ``recent_episodes`` seam. It scans Bob's OWN closers (not owner-private material),
        so BOB-051 runs it for every member alike — the anti-tic quality is unified.
        """
        lookback = self._repeat_thresholds.tic_lookback
        wide_history = await self._episodes.recent_episodes(lookback)
        return _recent_bob_replies(wide_history, limit=lookback)

    async def _log_closer(self, reply: str) -> None:
        """Append Bob's reply CLOSER to the cross-session ring (BOB-061 .2 wiring).

        The persist half of the «провязка»: the reply's final notable closer (normalised,
        via :func:`closer_text`) is logged so a signature ending recurring ONCE PER SESSION
        over days accumulates in the ring and the tic detector can finally see it. An empty
        closer (a short/blank ending, or an unwired log) is skipped. 🔴 Decorative: a store
        failure is swallowed — this local memory NEVER breaks a turn that already replied.
        """
        if self._closer_log is None:
            return
        closer = closer_text(reply, min_words=self._repeat_thresholds.tic_min_words)
        if not closer:
            return
        try:
            await self._closer_log.append(closer)
        except Exception:
            # Decorative persist: log + drop, never break a turn that already replied.
            logger.warning("appending Bob's closer to the ring failed (ignored)")

    async def _closer_anti_tic(
        self, recalled: Sequence[Recalled], history: Sequence[Mapping[str, object]]
    ) -> tuple[Sequence[Recalled], str]:
        """Detect a cross-session closer-tic and return (recalled, soft-nudge) (BOB-061 .2).

        The detect half of the «провязка», computed ONCE per turn BEFORE generation. Reads
        Bob's persisted closers (the ring) UNION the live-window closers and asks
        :func:`is_recurring_closer_tic` — at the CONSERVATIVE ``motif_similarity_threshold``
        — whether his freshest ending clusters into a recurring motif. When it fires:

        * (a) the motif closer is STRIPPED off the recalled Bob-reply exemplars so the tic is
          not fed back as few-shot (strengthening the existing anti-mimicry, now informed by
          the persisted motif), and
        * (b) the soft :data:`_CLOSER_TIC_NUDGE` line is returned to fold into the context.

        🔴 Decorative + conservative (US-4 liveness): an unwired log, a read failure, or NO
        tic all return ``(recalled, "")`` UNCHANGED — zero effect on the reply. The nudge is
        a push toward variety, never a ban.
        """
        if self._closer_log is None:
            return recalled, ""
        try:
            motif = await self._detect_closer_tic(history)
        except Exception:
            # Decorative detect: on any failure, no nudge and a normal reply (never break).
            logger.warning("closer-tic detection failed (ignored) — no nudge")
            return recalled, ""
        if motif is None:
            return recalled, ""
        stripped = tuple(_strip_recalled_closer(item, motif) for item in recalled)
        return stripped, _CLOSER_TIC_NUDGE

    async def _detect_closer_tic(
        self, history: Sequence[Mapping[str, object]]
    ) -> str | None:
        """Return the recurring closer MOTIF for this turn, or ``None`` (BOB-061 .2).

        Assembles Bob's recent closers — the persist ring (``recent(tic_lookback)``) UNION
        the live-window closers extracted from ``history`` — and probes the FRESHEST closer
        against the rest via :func:`is_recurring_closer_tic`. Fires only when that ending
        near-verbatim RECURS at least ``tic_min_occurrences`` times at the conservative
        ``motif_similarity_threshold`` (so a genuinely distinct ending never trips it). The
        matched closer is returned so the caller can strip it off the recalled exemplars.
        """
        assert self._closer_log is not None  # guarded by the caller
        persisted = await self._closer_log.recent(self._repeat_thresholds.tic_lookback)
        min_words = self._repeat_thresholds.tic_min_words
        window_replies = _recent_bob_replies(
            history, limit=self._repeat_thresholds.window
        )
        window_closers = tuple(
            c for r in window_replies if (c := closer_text(r, min_words=min_words))
        )
        closers = (*persisted, *window_closers)
        if not closers:
            return None
        current, prior = closers[0], closers[1:]
        if is_recurring_closer_tic(
            current,
            prior,
            similarity_threshold=self._repeat_thresholds.motif_similarity_threshold,
            min_occurrences=self._repeat_thresholds.tic_min_occurrences,
        ):
            return current
        return None

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
        # 🔴 Each add-on is OPTIONAL flavour (BOB-049 .3): wrapped so a flaky reflection /
        # recall / fascination read DROPS the add-on (logged, returns "") and the core full
        # Bob reply still ships. A failing add-on must NEVER trip the GUPPI outage notice —
        # it is not an essential step.
        additions = [
            await self._safe_addon(self._leak_inner_life(plan), name="inner-life leak"),
            await self._safe_addon(self._callback(plan, text), name="memory callback"),
            await self._safe_addon(
                self._mention_fascination(plan), name="fascination mention"
            ),
        ]
        suffix = "".join(f"\n{line}" for line in additions if line)
        return f"{context}{suffix}" if suffix else context

    async def _safe_addon(self, addon: Awaitable[str], *, name: str) -> str:
        """Run one OPTIONAL grounded add-on, dropping it silently on failure (BOB-049 .3).

        An add-on is FLAVOUR, never the core reply: if it raises (a flaky reflection /
        recall / fascination read), the error is logged and the add-on dropped so the full
        Bob reply still ships. Returns the add-on's line, or ``""`` when it had nothing OR
        failed — so a failing optional add-on can never trigger the honest outage notice.
        """
        try:
            return await addon
        except Exception:
            logger.exception("optional grounded add-on %r failed (dropped)", name)
            return ""

    async def _verify_note(
        self,
        text: str,
        history: Sequence[Mapping[str, object]],
        *,
        interlocutor: Interlocutor | None = None,
        chat_id: int | None = None,
    ) -> str:
        """The pre-answer epistemic-verify note for this turn, or ``""`` (BOB-057 .2).

        The whole step is DECORATIVE and DIRECT:

        * Unwired (no judge OR no provider — ``verify.enabled`` off) → ``""`` immediately,
          zero judge/search calls, zero added latency (US-2 «не зануда» by default).
        * A CONSERVATIVE Tier-0 :class:`VolatilityJudge` decides whether the answer hinges
          on a FRESH volatile fact. A judge failure is caught and treated as «no check»
          (``""``) — the turn is never blocked by a flaky judge.
        * On ``needs_check`` Bob runs ONE search via :meth:`_verify_search_note`.

        🔴 The search is DIRECT (``provider.search``), NOT ``registry.dispatch`` /
        the tool-loop — so it is NOT the BOB-052 per-sender privilege gate. This is an
        internal public-verify (nobody asked for a tool; only PUBLIC web info is exposed,
        never owner/private data), so it works for owner and guest alike without weakening
        BOB-051/052 on user-facing tool requests.
        """
        judge = self._verify_judge
        provider = self._verify_provider
        if judge is None or provider is None:
            return ""
        try:
            verdict = await judge.assess(
                VolatilityContext(text=text, recent_thread=_render_thread(history))
            )
        except Exception:
            # Decorative: a judge failure degrades to «no check» (normal answer), never
            # blocks or breaks the turn.
            logger.exception("volatility judge failed (verify skipped)")
            return ""
        if not verdict.needs_check:
            return ""
        # BOB-057 .3 (US-3b): before the search, Bob sends a LIVE, ADDRESSED interim line
        # naming WHAT he checks and WHO he's talking to («Леш, гляну свежие ставки,
        # секунду 🙂»). Decorative (live gen → silence) and does
        # NOT block the search below.
        await self._send_verify_interim(verdict, interlocutor, chat_id)
        return await self._verify_search_note(provider, verdict)

    async def _send_verify_interim(
        self,
        verdict: VolatilityVerdict,
        interlocutor: Interlocutor | None,
        chat_id: int | None,
    ) -> None:
        """Send the live addressed interim line for the verify search (BOB-057 US-3b).

        Reuses the :class:`GatewayProgressAnnouncer` in its BOB-060 live-only mode so
        the decorative chain (live Tier-0 gen → silence) lives
        in one place. No ``chat_id`` (an unaddressed path) → no interim. The sender's
        perceived ``display_name`` addresses the line; an unknown sender → topic-only.
        """
        if chat_id is None:
            return
        sender_name = interlocutor.display_name if interlocutor is not None else ""
        announcer = GatewayProgressAnnouncer(
            chat_id=chat_id,
            gateway=self._gateway,
            line_generator=self._interim_line_generator,
            sender_name=sender_name,
        )
        await announcer.announce_verify(topic=verdict.topic)

    async def _verify_search_note(
        self, provider: WebSearchProvider, verdict: VolatilityVerdict
    ) -> str:
        """Run ONE direct, short-timeout web_search and return the grounded/hedge note.

        On success with a non-empty answer → a GROUNDED note (the trimmed finding + a nudge
        to react in Bob's own voice/tone). On failure / timeout / empty → an HONEST hedge
        note (US-6: never a confident stale number as fact, never a fabrication). The
        provider call is bounded by ``verify.timeout_seconds`` so a slow search cannot
        stall the turn (US-3 «не 5 минут»).
        """
        try:
            # ``asyncio.wait_for`` raises ``TimeoutError`` past the deadline; a slow/failing
            # provider raises its own error — both are caught below as one honest hedge.
            result = await asyncio.wait_for(
                provider.search(verdict.query), timeout=self._verify_timeout_seconds
            )
        except Exception:
            logger.exception("verify web_search failed (hedge)")
            return _VERIFY_HEDGE_NOTE.format(topic=verdict.topic)
        answer = result.answer.strip()[:_VERIFY_ANSWER_MAX_CHARS]
        if not answer:
            return _VERIFY_HEDGE_NOTE.format(topic=verdict.topic)
        return _VERIFY_GROUNDED_NOTE.format(answer=answer)

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
        self,
        provider: ToolCallingProvider,
        system_prompt: str,
        text: str,
        context: str,
        *,
        chat_id: int | None = None,
        sender_name: str = "",
    ) -> str:
        """Drive the capability tool-loop, advertising the manifest in the prompt.

        ``chat_id`` (the turn's chat) wires the per-turn progress announcer (BOB-060):
        before a SLOW ``web_search`` runs, Bob sends a LIVE "searching…" line in his own
        voice (generated from the query as the topic, addressing ``sender_name``) so the
        owner is not left in silence. Unset ``chat_id`` → no announcer. The announce is
        decorative and live-only — a gen/send failure stays silent, never breaks the reply.
        """
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
        announcer = (
            GatewayProgressAnnouncer(
                chat_id=chat_id,
                gateway=self._gateway,
                line_generator=self._interim_line_generator,
                sender_name=sender_name,
            )
            if chat_id is not None
            else None
        )
        loop = ToolLoop(provider=provider, registry=self._registry, announcer=announcer)
        return await loop.run(messages)

    async def _persist(
        self,
        event: MessageReceived,
        reply: str,
        soul: SOUL,
        *,
        bob_message_id: int | None = None,
    ) -> None:
        """Save the turn as an episode and snapshot the updated mood.

        ``bob_message_id`` is the Telegram message_id of Bob's outgoing reply this
        turn (BOB-050), recorded on the episode so a later reaction on that message
        can be linked back to what Bob said. ``None`` for a turn where Bob sent no
        message (a silent/degraded turn).
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
            }
        )
        await self._repo.set_mood(_mood_state(soul), at=now)


# Bob's persisted half of a non-reply turn (BOB-049), so a follow-up keeps the
# per-person thread (BOB-045): IGNORE writes "(промолчал)", REACT "(реакция: <emoji>)".
# Russian persona voice (project language); Cyrillic look-alikes are intentional.
_SILENT_MARKER = "(промолчал)"

# Bob's persisted half when an ESSENTIAL step failed after retries (BOB-049 .3): the
# user's turn is saved (so the message is not lost) with this marker — no degraded reply
# was produced; GUPPI reported the outage separately. Russian persona voice.
_OUTAGE_MARKER = "(нет ответа: проблемы со связью)"  # noqa: RUF001


def _reaction_marker(emoji: str) -> str:
    """Bob's persisted half for a REACT turn: the meaning-chosen emoji (BOB-049)."""
    return f"(реакция: {emoji})"


# Map the judge's intent to the legacy outcome the conversation floor advances on
# (BOB-049): the floor reads per_message + bob_replied, so this is the cosmetic
# outcome label only — REPLY engages, REACT like-reacts, IGNORE stays silent.
_OUTCOME_FOR_INTENT: dict[ResponseIntent, ResponseOutcome] = {
    ResponseIntent.REPLY: ResponseOutcome.ENGAGE,
    ResponseIntent.REACT: ResponseOutcome.REACT,
    ResponseIntent.IGNORE: ResponseOutcome.SILENT,
}


def _render_thread(history: Sequence[Mapping[str, object]]) -> str:
    """Render the shared recent thread into the judge's recent-thread snippet (BOB-049).

    Joins each replayed episode's ``content`` (stored as ``"<name>: <text>\\nbob:
    <reply>"``) oldest-first; an empty history yields ``""`` (the judge reads it as a
    fresh thread). No I/O — a pure projection of the already-replayed history (BOB-058 .1:
    the shared group thread, author-labeled).
    """
    return "\n".join(
        str(item.get("content", "")) for item in history if item.get("content")
    )


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
    *,
    absence: str | None = None,
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

    When ``absence`` is given (BOB-045 .3) — the person's per-person thread has been
    idle past the configured threshold — ONE light ``Absence:`` line is appended so the
    reply tier can acknowledge the pause naturally. It is a hint, not a directive; with
    no/short gap (or the hint disabled) ``absence`` is ``None`` and no line is added.
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
    if absence:
        lines.append(f"Absence: {absence}")
    memories = [str(item.get("content", "")) for item in recalled]
    if memories:
        lines.append("Recalled memories: " + " | ".join(memories))
    return "\n".join(lines)


def _last_seen_at(history: Sequence[Mapping[str, object]]) -> datetime | None:
    """Return the timestamp of the person's MOST RECENT prior turn, or ``None`` (BOB-045 .3).

    The replayed per-person ``history`` is oldest-first, so the freshest prior turn is
    the last one carrying a parseable ``ts`` (the ISO-8601 string the episode store
    persists, or a ``datetime`` if already typed). Scans back to front and returns the
    first such timestamp; an empty history (first contact) or rows with no/garbled ``ts``
    yield ``None``, so the absence hint simply does not fire — never a crash. No I/O.
    """
    for item in reversed(list(history)):
        ts = item.get("ts")
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                continue
    return None


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


def _strip_recalled_closer(item: Recalled, closer: str) -> Recalled:
    """Return ``item`` with the recurring ``closer`` stripped off its content (BOB-061 .2).

    On a detected closer-tic, the recalled exemplar's whole-turn content (
    ``"<sender>: <text>\\nbob: <reply>"``) may END with the tic motif — feeding it back as
    few-shot would reinforce the very ending the nudge is trying to break. This excises the
    trailing motif sentence via :func:`strip_recurring_closer` (the SAME deterministic strip
    the anti-repeat guard uses) and returns a shallow copy carrying the tidied content. When
    the content does not end with the motif (nothing to strip) or is not a string, the
    original ``item`` is returned untouched — the fact body is always preserved.
    """
    content = item.get("content")
    if not isinstance(content, str):
        return item
    stripped = strip_recurring_closer(content, closer)
    if stripped == content:
        return item
    updated = dict(item)
    updated["content"] = stripped
    return updated


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


def _author_key(interlocutor: Interlocutor | None) -> int | None:
    """The CURRENT author's ``sender_id`` signal key, or ``None`` when unresolved (BOB-058 .3).

    Per-person signals (absence, anti-repeat) over the SHARED thread key on the ROBUST
    ``sender_id`` — the same identity the per-person stores (relationship BOB-014,
    first-impression BOB-019) already use — NOT the parsed ``"<name>:"`` label. The label
    is brittle as a signal key: homonymous members cross-attribute, a display name with a
    ``": "`` or a rename between turns silently drops the signal. ``None`` — no perception
    seam, no interlocutor, or an unresolved ``sender_id`` — means "do not filter": the
    signal falls back to the whole window, exactly as before perception was wired.
    """
    return interlocutor.sender_id if interlocutor is not None else None


def _history_for_author(
    history: Sequence[Mapping[str, object]], sender_id: int | None
) -> list[Mapping[str, object]]:
    """Filter the shared thread to the episodes authored by ``sender_id`` (BOB-058 .3).

    Keeps ordering (oldest-first) so the per-person signals — absence last-seen,
    anti-repeat turns — see only the CURRENT author's own turns even though ``history``
    now interleaves the whole group. Episodes are attributed by their persisted
    ``sender_id`` (robust to homonyms / renames / a ``": "`` in the display name — the
    human-readable ``"<name>:"`` label is only for rendering the thread, never the signal
    key). ``sender_id is None`` (unresolved identity) means "do not filter" → the full
    window is returned (the pre-BOB-058 degraded behaviour).
    """
    if sender_id is None:
        return list(history)
    return [item for item in history if item.get("sender_id") == sender_id]


def _user_turns(
    history: Sequence[Mapping[str, object]], sender_id: int | None = None
) -> list[str]:
    """Recover the USER half of each replayed episode (BOB-022 repeat detection).

    Episodes are stored as ``"<name>: <text>\\nbob: <reply>"`` (see
    :meth:`HandleMessage._persist`); this extracts the ``<text>`` between the first
    ``"<name>: "`` and the ``"\\nbob: "`` marker for each episode so the user-repeat
    predicate compares the current message ONLY against prior USER turns — never against
    Bob's own replies. 🔴 BOB-058 .3: over the now-SHARED thread, ``sender_id`` (when given)
    restricts the turns to the CURRENT author's episodes BY ID, so a DIFFERENT member's
    similar line is not mistaken for this person repeating themselves. Episodes without
    the expected shape are skipped.
    """
    turns: list[str] = []
    for item in _history_for_author(history, sender_id):
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
