# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""VoiceComposer — compose Bob's reply text for one turn (BOB-013/018/024/049/057).

The turn's «shape Bob's voice and generate his reply» concern in one cohesive collaborator
(extracted from ``HandleMessage`` in BOB-062.6b, wave 3, behavior-preserving). It:

* assembles the reply-shaping context (via an injected context assembler + the light
  absence / being-received add-ons), folds the grounded owner inner-life add-ons
  (:class:`GroundedAddons`) on a non-guest turn, and the once-per-turn epistemic-verify
  note (:meth:`compose` threads it in as a turn-LOCAL, never recomputes it);
* augments the base persona with the mood tone, relationship-tone, sulk, negotiation
  stance, engagement, brevity and self-improvement directives (:meth:`_system_prompt_for`,
  all :mod:`bob.personality.voice`); and
* generates the reply — either driving the capability tool-loop
  (:meth:`_reply_with_tools`, non-guest + wired) or the plain reply tier.

🔴 This vertical («who Bob is» — his voice) reaches EVERY OTHER bounded context through
INJECTED ports/values only: the conversation context assembler + recall/verify ports, the
social stance port, the application reply generators (plain-reply + essential-runner) and
the capabilities tool-loop / announcer factories are all passed in — VoiceComposer imports
none of them, so ``personality`` never depends on conversation / social / capabilities /
application-core internals (the bounded-context boundaries stay clean).

🔴 ``verify_note`` and ``closer_nudge`` are TURN-LOCAL arguments, NEVER instance attributes:
``HandleMessage`` is a shared singleton, so an instance flag would leak one turn's note /
nudge across turns and concurrent users. ``verify_note`` is ``None`` = «not yet computed»
(the first composition computes it), any string (INCLUDING ``""`` = «judged, no note») =
«already computed this turn» → reuse verbatim, so :class:`AntiRepeatGuard`'s regeneration
reuses it instead of re-judging / re-searching. 🔴 ``is_guest`` is a per-turn argument that
gates the tool-loop + the grounded inner-life add-ons ONLY (recall/history/voice are unified
for the closed group, BOB-051).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.personality.expression import EngagementLevel, Verbosity
from bob.personality.negotiation import _stance_directive
from bob.personality.voice import (
    anti_bait_directive,
    brevity_directive,
    brevity_few_shot,
    engagement_directive,
    guppi_canon,
    improvement_directive,
    profanity_stance,
    recalled_impression_directive,
    sulk_directive,
    tone_directive,
    user_repeat_directive,
    variable_form_directive,
    who_is_writing_directive,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from bob.domain.ports import LLMMessage, Recalled, ToolCallingProvider
    from bob.personality.expression import ExpressionPlan
    from bob.personality.negotiation import NegotiationZone, Stance
    from bob.personality.soul import SOUL
    from bob.personality.taste import Verdict
    from bob.personality.usecases.grounded_addons import GroundedAddons
    from bob.personality.voice import OffDayThresholds
    from bob.proactivity.self_improvement import RuleModulators
    from bob.social.interlocutor import Interlocutor
    from bob.social.relationship import Relationship
    from bob.social.sulk import SulkState

# The base persona (assembled once at import), then the voice concerns Bob's persona leans on
# (BOB-016): the anti-bait directive + few-shot (so he lands like a person, not an assistant
# fishing for the next reply), the variable-form directive, and the calm-about-profanity
# stance. The TONE itself is mood-conditioned per turn via voice.tone_directive (BOB-020),
# appended in :meth:`_system_prompt_for`, so Bob can have an off-day instead of forcing warmth.
_SYSTEM_PROMPT = (
    "You are Bob, a digital person from the Bobiverse. Reply in character.\n"
    f"{guppi_canon()}\n"
    f"{anti_bait_directive()}\n"
    f"{variable_form_directive()}\n"
    f"{profanity_stance()}"
)

# Preface for the capability manifest in Bob's prompt: GUPPI is Bob's executor subsystem
# (canon already in the base persona above), so this just frames the manifest as the skills
# GUPPI runs for Bob.
_CAPABILITY_PREFACE = (
    "Эти возможности GUPPI исполняет для тебя; вызови одну, когда она помогает "
    "ответить:"
)


class _ToolRegistry(Protocol):
    """The capability-registry seam VoiceComposer reads (structural — no import)."""

    @property
    def is_empty(self) -> bool: ...

    def describe(self) -> str: ...


class _EssentialRunner(Protocol):
    """The reliability seam: run an ESSENTIAL LLM step with bounded retry (BOB-049 .3)."""

    async def run(
        self, operation: Callable[[], Awaitable[str]], *, step: str
    ) -> str: ...


class _ContextAssembler(Protocol):
    """The conversation context assembler (injected — personality never imports it)."""

    def __call__(
        self,
        soul: SOUL,
        topic: str,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        *,
        absence: str | None = None,
    ) -> str: ...


class _RecallPorts(Protocol):
    """The recall-assembler seam: the light absence / acknowledgment add-ons."""

    def absence_for(
        self,
        history: Sequence[Mapping[str, object]],
        interlocutor: Interlocutor | None,
    ) -> str | None: ...

    async def acknowledgment_for(self, interlocutor: Interlocutor | None) -> str: ...


class _VerifyPort(Protocol):
    """The epistemic-verify seam: the once-per-turn grounded/hedge note (BOB-057)."""

    async def note(
        self,
        text: str,
        history: Sequence[Mapping[str, object]],
        *,
        interlocutor: Interlocutor | None = None,
        chat_id: int | None = None,
    ) -> str: ...


class _StancePorts(Protocol):
    """The social-context seam: the negotiation stance + relationship-tone line."""

    def decide_stance(
        self, soul: SOUL, text: str, relationship: Relationship | None
    ) -> tuple[Stance, Verdict, NegotiationZone]: ...

    def relationship_tone(self, relationship: Relationship | None) -> str: ...


class _PlainReply(Protocol):
    """The plain reply-tier generator (injected — personality never imports the router)."""

    async def __call__(self, system_prompt: str, text: str, context: str) -> str: ...


class _ProgressAnnouncer(Protocol):
    """The per-turn progress announcer (structural — matches capabilities' announcer)."""

    async def announce(
        self, capability_name: str, arguments: Mapping[str, object]
    ) -> None: ...


class _AnnouncerFactory(Protocol):
    """Build the per-turn, chat-bound progress announcer from the turn's chat_id."""

    def __call__(
        self, *, chat_id: int, sender_name: str
    ) -> _ProgressAnnouncer: ...


class _ToolLoop(Protocol):
    """The capability tool-loop (structural — VoiceComposer runs it via a factory)."""

    async def run(self, messages: Sequence[LLMMessage]) -> str: ...


class _ToolLoopFactory(Protocol):
    """Build the capability tool-loop for a provider + optional announcer."""

    def __call__(
        self,
        provider: ToolCallingProvider,
        announcer: _ProgressAnnouncer | None,
    ) -> _ToolLoop: ...


class VoiceComposer:
    """Compose Bob's reply text for one turn — voice, context, and generation."""

    def __init__(
        self,
        *,
        registry: _ToolRegistry,
        tool_provider: ToolCallingProvider | None,
        offday_thresholds: OffDayThresholds,
        addons: GroundedAddons,
        essential: _EssentialRunner,
        assemble_context: _ContextAssembler,
        assembler: _RecallPorts,
        verify: _VerifyPort,
        social: _StancePorts,
        plain_reply: _PlainReply,
        announcer_factory: _AnnouncerFactory,
        tool_loop_factory: _ToolLoopFactory,
    ) -> None:
        self._registry = registry
        self._tool_provider = tool_provider
        self._offday_thresholds = offday_thresholds
        self._addons = addons
        self._essential = essential
        self._assemble_context = assemble_context
        self._assembler = assembler
        self._verify = verify
        self._social = social
        self._plain_reply = plain_reply
        self._announcer_factory = announcer_factory
        self._tool_loop_factory = tool_loop_factory

    async def compose(
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
        context = self._assemble_context(
            soul,
            text,
            recalled,
            history,
            absence=self._assembler.absence_for(history, interlocutor),
        )
        # Being-received acknowledgment (BOB-050 .3): a RARE, per-person hint that someone
        # warmly reacted to one of Bob's messages — applies to ANY interlocutor (owner and
        # guest alike, since it is about Bob's OWN message, not owner-private material) and
        # is wrapped so a store failure drops silently (decorative, never the outage notice).
        acknowledgment = await self._addons.safe(
            self._assembler.acknowledgment_for(interlocutor), name="reaction acknowledgment"
        )
        if acknowledgment:
            context = f"{context}\n{acknowledgment}"
        if not is_guest:
            # Grounded add-ons surface Bob's PRIVATE inner life / shared past —
            # withheld from a stranger (audience redaction).
            context = await self._addons.with_grounded_addons(context, text, plan)
        # Pre-answer epistemic verify (BOB-057 .2): a conservative Tier-0 judge decides if
        # the answer hinges on a FRESH volatile fact; if so Bob does ONE DIRECT web_search
        # (ungated internal public-verify) and this grounded/hedge note folds into the SAME
        # generation context as the other add-ons. Applies to owner and guest alike (public
        # web info, no owner/private leak). Wrapped so ANY failure drops to «no note».
        #
        # 🔴 BOB-057 .5 (US-3 «один поиск, не петля»): the verify step is computed EXACTLY
        # ONCE per turn and THREADED IN via ``verify_note`` so the anti-repeat regeneration
        # loop REUSES it instead of re-judging / re-searching / re-announcing on every retry.
        # ``None`` = «not yet computed» (the first composition falls through and computes it);
        # any string (INCLUDING ``""`` = «judged, no note») means «already computed this turn»
        # → reuse verbatim. The cache is this PER-TURN LOCAL parameter, NOT an instance
        # attribute — VoiceComposer is a shared singleton, so an instance flag would leak the
        # note (and the «already searched» state) across turns/users.
        if verify_note is None:
            verify_note = await self._verify.note(
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
            return await self._essential.run(
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
        # Hybrid reply tiering (BOB-006): a casual/short message answers on the fast Tier 0
        # (flash) model for responsiveness; a complex/long message escalates to the quality
        # Tier 1 (plus) model — picked by a pure heuristic on the user's message inside the
        # injected plain-reply generator, no extra LLM round-trip.
        return await self._essential.run(
            lambda: self._plain_reply(system_prompt, text, context),
            step="reply generation",
        )

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
        off-day band ("не знаю" over confabulation). The taste verdict + conviction on
        ``text`` then pick the zone and stance (BOB-013), and the decided ``verbosity``
        (BOB-024) appends the SINGLE final length directive + (on a terse turn) the
        short-answer few-shot. When ``user_repeated`` (BOB-022) the user-repeat directive
        is appended; when an ``interlocutor`` is perceived (BOB-019) the who-is-writing
        line is appended. With a normal mood, no target opinion, no user-domain signal, a
        NORMAL verbosity, no repeat, and no perceived interlocutor, only the warm tone line
        augments the base voice.
        """
        stance, verdict, zone = self._social.decide_stance(soul, text, relationship)
        directives = [
            tone_directive(soul.mood, thresholds=self._offday_thresholds),
            # BOB-014: Bob's accrued WARMTH toward this specific person colours his
            # voice on TOP of the mood tone — warmer for a close relationship, more
            # reserved (never rude) for a distant one. No relationship / neutral
            # warmth → no line (a new person is met at the base tone).
            self._social.relationship_tone(relationship),
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
        The announcer + tool-loop are built through INJECTED factories, so this personality
        vertical never imports the capabilities use-cases.
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
            self._announcer_factory(chat_id=chat_id, sender_name=sender_name)
            if chat_id is not None
            else None
        )
        loop = self._tool_loop_factory(provider, announcer)
        return await loop.run(messages)
