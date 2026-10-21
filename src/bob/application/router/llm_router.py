# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=router

"""LLMRouter — task classification, privacy redaction, and tier fallback.

GUPPI's policy layer over the provider-agnostic :class:`LLMProvider` ports
(Tier 0 local / Tier 1 API). For each request it:

1. **Classifies** the task type to a preferred tier — replying to the user
   defaults to **Tier 1** (Qwen) for quality (CONTEXT Q2); cheap or sensitive
   work (sentiment, inner monologue) stays on **Tier 0** locally.
2. **Selectively redacts** before any Tier 1 call (Variant 2, VISION §7.1).
   Each request splits its context in two: ``shareable_context``
   (conversation/memory/mood/identity/taste — material that shapes Bob's reply
   and returns to that same user) MAY accompany a Tier 1 call, while
   ``private_context`` (genuinely-internal scratch) is Tier-0-only and is
   stripped before any Tier 1 call. Redaction is a property of the *request*,
   applied whenever the destination is Tier 1, including on a Tier 1 -> Tier 0
   fallback (the redacted payload is what was built, so the fallback sees it too).
3. **Falls back** Tier 1 -> Tier 0 when the cloud tier is UNREACHABLE, so a flaky Qwen
   API never blocks a reply — but only then. Which failures count is not decided here:
   it is the same pure :func:`~bob.application.router.fallback_policy.should_fall_back` core the
   Tier-0 understudy obeys (bob-41o), so a 4xx or a broken response shape from Tier 1
   surfaces instead of being answered — and hidden — by the weaker tier.
4. **Protects Bob's voice** when Tier 0 is understudy-backed (BOB-087.E-M1). Tier 0 may be
   composed with a local emergency stand-in (``llm.tier0_fallback``), which is right for a
   служебный ход and wrong for a turn published AS BOB — the composite is invisible to its
   caller, so a 0.5b answer would ship in his voice and settle into memory. Only the router
   knows the task type, so the direction of the fallback is decided HERE, by the pure
   :mod:`bob.application.router.voice_integrity` core: a turn that is «the voice that
   STAYS» (BOB-096.4 — the door both speaks AS BOB and is kept) keeps the stand-in out and
   escalates **UP** to Tier 1 (one hop, same redaction), or fails honestly.
5. **Reports every provider outcome to the health monitor** (BOB-116). Each attempt on a
   tier is reported to the injected :class:`~bob.kernel.ports.HealthObserver` — as ``tier1``
   or ``tier0-primary`` — ONLY when the provider actually called does not report itself.
   Two kinds do: the understudy wrapper
   (:class:`~bob.kernel.ports.UnderstudyBackedProvider`) reports its primary and its
   stand-in, and a :class:`~bob.kernel.ports.SelfReportingProvider` reports its own calls —
   the factory wraps Tier 1 so, because the tool loop calls Tier 1 past this router (F1). One
   HTTP call is one record, never two. Bob's own voice on Tier 0 goes to the BARE primary
   (``without_understudy``), past the understudy wrapper — that call the router reports.
   🔴 A failure is recorded BEFORE it propagates: the heartbeat lane gate reads the snapshot
   right after the tick (BOB-116 D5).
6. **Carries the VOICE canon to every door** (BOB-096.3). The ban on role-playing GUPPI
   stood on ONE door out of sixteen — the conversational turn — while the reflection,
   its reappraisal, the consolidation digest, the proactive line, the work journal and
   ``extract_facts`` all walked past it and wrote canon-breaking few-shot INTO memory,
   which recall then feeds back into Bob's behaviour (BOB-074). The router is the place
   EVERY ordinary door passes through, so the seam lives here: what a door's output IS
   comes from :mod:`bob.application.router.generation_door`, the folding from
   :mod:`bob.application.router.voice_canon`, and the text itself is injected from the
   persona (the router imports no domain vertical). 🔴 It is not the ONLY point a payload
   leaves for a provider, and BOB-096.3 read as if it were: the tool-driven turn goes out
   through :class:`~bob.capabilities.usecases.tool_loop.ToolLoop`, which the privileged
   fulfilment drove with the router nowhere in sight — so it carried no canon at all until
   BOB-096.8 put the SAME seam at that second door too.
7. **Lets a turn survive a side step the provider could not serve** (BOB-116 D13).
   :meth:`LLMRouter.run_optional` is for a step its CALLER declares optional — the mood read
   off the inbound, the staleness re-read before sending. When the provider could not or
   would not serve it (the same verdict that decides a fallback: 401/403, 429, 5xx, timeout,
   a dropped channel) the step yields ``None`` and the turn goes on to the voice door, which
   already ends in Bob's reply or the honest GUPPI notice. Until D13 a 403 on the mood
   classifier killed the whole turn before that door, so with no understudy the room got
   silence instead of the notice. A ``contract`` failure and anything that is not a provider
   failure at all still propagate: the seam skips an outage, it does not hide a defect.

This module is pure application policy: it holds no transport/HTTP knowledge —
that lives behind the injected :class:`LLMProvider` adapters.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.application.router.fallback_policy import classify_failure, should_fall_back
from bob.application.router.generation_door import TaskType, door_for
from bob.application.router.health_monitor import TIER0_PRIMARY, TIER1, NoopHealthObserver
from bob.application.router.voice_canon import fold_voice_canon
from bob.application.router.voice_integrity import OutageVoice, who_may_answer_for_bob
from bob.kernel.ports import HealthReader, SelfReportingProvider, UnderstudyBackedProvider

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.application.router.voice_canon import VoiceCanon
    from bob.kernel.ports import HealthObserver, LLMMessage, LLMProvider

logger = logging.getLogger(__name__)

_TIER_LOCAL = 0
_TIER_API = 1


# 🔴 ``TaskType`` now lives in :mod:`bob.application.router.generation_door`, next to the
# answer to «what IS this door's output» (BOB-096.3): the kind of work and the nature of
# its output are one concept, and splitting them across modules is how a door ends up
# known by its TIER alone — the shape the canon leak grew in. The name is re-exported
# here, so every existing ``from …llm_router import TaskType`` keeps working.
__all__ = ["LLMRequest", "LLMRouter", "TaskType"]

# Task -> preferred tier. Quality-critical, user-facing work goes to Tier 1
# (with redaction); cheap or privacy-sensitive work stays local on Tier 0.
_PREFERRED_TIER: dict[TaskType, int] = {
    TaskType.REPLY_TO_USER: _TIER_API,
    TaskType.GENESIS: _TIER_API,
    TaskType.SENTIMENT: _TIER_LOCAL,
    TaskType.INNER_MONOLOGUE: _TIER_LOCAL,
    # Fascination pick (BOB-020, split off INNER_MONOLOGUE in BOB-096.8): a cheap
    # noun-phrase choice grounded in Bob's own reflection + tastes — Tier 0, exactly where
    # it ran before the split, so the routing is byte-identical.
    TaskType.FASCINATION_PICK: _TIER_LOCAL,
    TaskType.REFLECT: _TIER_LOCAL,
    TaskType.EXTRACT_FACTS: _TIER_LOCAL,
    # Goal decomposition (BOB-015) is reasoning-heavy: Tier 1 by default for a
    # sensible plan (the config can pin the tier per persona via tier_override).
    TaskType.PLAN_GOAL: _TIER_API,
    # Pattern detection (BOB-028) is reasoning over self-signals: Tier 1 by default
    # for a human-readable rule (config can pin the tier via detector_tier override).
    TaskType.DETECT_PATTERNS: _TIER_API,
    # Coding-intent classification (BOB-041 .2) is a cheap one-word coding/chat call
    # that also keeps dev-intent local (privacy) — Tier 0.
    TaskType.CODING_INTENT: _TIER_LOCAL,
    # Response judgment (BOB-049) is a cheap per-inbound reply/react/ignore decision
    # run on every message — Tier 0 for cost, like the other classifiers.
    TaskType.RESPONSE_JUDGE: _TIER_LOCAL,
    # Reaction judgment (BOB-050) reads what a reaction on Bob's OWN message means —
    # a cheap, privacy-adjacent local read, like the other personality classifiers.
    TaskType.REACTION_JUDGE: _TIER_LOCAL,
    # Privilege judgment (BOB-052) decides whether a not-yet-authorised person's
    # request needs owner permission — a cheap, privacy-sensitive local read, like
    # the other classifiers.
    TaskType.PRIVILEGE_JUDGE: _TIER_LOCAL,
    # Volatility judgment (BOB-057) decides, before Bob answers, whether the answer
    # hinges on a fresh volatile fact — a cheap per-inbound classifier, Tier 0.
    TaskType.VOLATILITY_JUDGE: _TIER_LOCAL,
    # Interim line (BOB-057 .3) is a cheap one-liner in Bob's voice before the verify
    # search — a fast, latency-tolerant local gen (the search wait dwarfs it), Tier 0.
    TaskType.INTERIM_LINE: _TIER_LOCAL,
    # Reflective «read the room» (BOB-066 Срез 2.2) is the rich semantic pass on a
    # PERIPHERY turn — situation / room-mood / intent / salience / wants_web. It is the
    # heart of Bob's living group presence, so it runs on Tier 1 for real understanding
    # («не жалеть LLM», PRINCIPLE-1 liveness > economy) — unlike the cheap Tier-0 judge.
    TaskType.ROOM_READ: _TIER_API,
    # Staleness judgment (BOB-066 Срез W.3) reads how the room shifted under a drafted reply
    # while Bob was composing — a cheap per-turn classifier over a short burst, Tier 0.
    TaskType.STALENESS_JUDGE: _TIER_LOCAL,
    # Disclosure-consent judgment (BOB-082 .4) reads whether the OWNER authorised voicing
    # previously-private content into the group — privacy-sensitive, so it stays local (Tier 0).
    TaskType.DISCLOSURE_CONSENT: _TIER_LOCAL,
    # Work-journal distillation (BOB-087.B1) sweeps a coding session's key facts into a few
    # first-person operator episodes — privacy-sensitive (owner's repo work) + a background
    # side-channel, so it stays local (Tier 0), like the other cheap classifiers.
    TaskType.WORK_JOURNAL: _TIER_LOCAL,
    # Work-talk classification (BOB-087.C2) is a cheap one-word work/chat call deciding
    # whether a turn is ABOUT Bob's dev work (so his work memories lift to full recall) —
    # privacy-sensitive (dev context) + per-inbound, so it stays local (Tier 0).
    TaskType.WORK_TALK: _TIER_LOCAL,
}


@dataclass(frozen=True)
class LLMRequest:
    """A unit of LLM work: the prompt plus its two-tier context split.

    Context is split by destination policy (Variant 2, selective redaction):

    - ``shareable_context`` — conversation/memory/mood/identity/taste material
      that shapes Bob's reply and returns to that same user. It MAY accompany a
      Tier 1 (remote API) call.
    - ``private_context`` — genuinely-internal material that is Tier-0-only and
      MUST be redacted before any Tier 1 call. May be empty in P0.1, but the seam
      is kept so internal-only context never silently leaks.

    ``tier_override`` lets a caller pick the destination tier for *this* request,
    overriding the task's default (BOB-006 hybrid reply tiering: a casual reply
    runs on the fast Tier 0 model, a complex one on the quality Tier 1 model).
    Redaction is unaffected — it follows the *task* policy, not the chosen tier,
    so a reply overridden down to Tier 0 still never bundles ``private_context``.
    """

    task_type: TaskType
    messages: Sequence[LLMMessage]
    shareable_context: str | None = None
    private_context: str | None = None
    stream: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
    tier_override: int | None = None


class LLMRouter:
    """Route a task to a tier, redacting private context before Tier 1, with fallback."""

    def __init__(
        self,
        *,
        providers: Mapping[int, LLMProvider],
        tier1_max_concurrency: int | None = None,
        voice_canon: VoiceCanon | None = None,
        health: HealthObserver | None = None,
    ) -> None:
        if _TIER_LOCAL not in providers:
            raise ValueError("LLMRouter requires a Tier 0 (local) provider")
        self._providers = dict(providers)
        # 🔴 The VOICE canon that reaches every door (BOB-096.3). The TEXT belongs to the
        # persona and arrives INJECTED — ``personality`` already depends on the router, so
        # the reverse import would close a node cycle. The composition root supplies the
        # implementation (an architectural test guards that line); an unwired seam leaves
        # the payload byte-for-byte, which is what every hand-built test router gets.
        self._voice_canon = voice_canon
        # 🔴 Tier-1 rate-cap (BOB-072): a ceiling on CONCURRENT Tier-1 (Qwen API) completions —
        # invisible insurance against 429/degradation when bursts across chats (incl. batch
        # ROOM_READ) hit Tier 1 at once. It only SERIALIZES calls; it never touches the routing
        # decision or the payload. ``None``/``<= 0`` (the default) → no gate → byte-identical.
        self._tier1_gate = (
            asyncio.Semaphore(tier1_max_concurrency)
            if tier1_max_concurrency is not None and tier1_max_concurrency > 0
            else None
        )
        # 🔴 Is Tier 0 composed with a local emergency stand-in (``llm.tier0_fallback``,
        # BOB-087.E1)? This — not a config read — is how the router learns the flag: the
        # voice policy exists PRECISELY because a stand-in could answer in Bob's place, so
        # with a plain Tier-0 provider (the default) every branch below is unreachable and
        # the routing is byte-identical to the pre-flag one.
        self._tier0_has_understudy = isinstance(
            self._providers[_TIER_LOCAL], UnderstudyBackedProvider
        )
        # Provider health (BOB-116): every attempt's outcome goes here. ``None`` → a no-op,
        # so a hand-built router and every existing test are byte-identical. When the same
        # object can also READ health (the monitor does), a Tier-0 failure during an outage
        # the monitor already declared is logged as one line instead of a fresh stack.
        self._health: HealthObserver = health if health is not None else NoopHealthObserver()
        self._health_reader = health if isinstance(health, HealthReader) else None

    def stand_down_tier0_understudy(self) -> None:
        """Take the Tier-0 stand-in out for the rest of the process (BOB-116 D11).

        The composition root calls this at startup when the understudy is enabled in the
        config but not ready (no Ollama, no model): Tier 0 then goes on as the bare primary,
        exactly as if the understudy had never been composed — its calls are reported here
        under ``tier0-primary`` and the voice policy no longer counts on a stand-in. There is
        no way back short of a restart: a model pulled later is not picked up. A plain Tier-0
        provider is left untouched.
        """
        provider = self._providers[_TIER_LOCAL]
        if isinstance(provider, UnderstudyBackedProvider):
            self._providers[_TIER_LOCAL] = provider.without_understudy()
        self._tier0_has_understudy = False

    async def run(self, request: LLMRequest) -> str:
        """Complete ``request`` on its preferred tier, with ONE rescue attempt on failure.

        The payload is built once: a Tier 1-bound request carries only its
        ``shareable_context`` (private context is stripped); a local-only Tier 0
        request carries both. That same built payload is what a Tier 1 -> Tier 0
        fallback sends — the private-context redaction is preserved end to end.

        A Tier-1 attempt is throttled by the optional concurrency gate (BOB-072); the
        Tier-0 fallback runs OUTSIDE the gate so a failing Tier-1 call never holds a
        Tier-1 slot while its local fallback completes.

        🔴 **Who falls where** — the full matrix, after bob-41o closed the last hole in it:

        ========================  =====================  ==============================
        preferred tier            failure                what happens
        ========================  =====================  ==============================
        Tier 1                    transport / outage     ONE hop DOWN to Tier 0 (same
                                  (5xx, 408, 429,        redacted payload; a turn in
                                  timeout, disconnect,   Bob's voice gets Tier 0 without
                                  refused, truncated)    its stand-in, see
                                                         :meth:`_provider_for`)
        Tier 1                    contract (4xx, broken  NOTHING answers — the error
                                  shape, InvalidURL,     surfaces (bob-41o)
                                  our own bug)
        Tier 0, служебный ход     any                    no rescue here: the stand-in
                                                         under Tier 0 already applied the
                                                         SAME policy one floor below
        Tier 0, Bob's own voice   any                    ONE hop UP to Tier 1 (E-M1)
        Tier 0, voice, nothing    any                    NOBODY answers — the error
        to escalate to                                   surfaces
        ========================  =====================  ==============================

        🔴 Why DOWN is conservative and UP is not (the deliberate asymmetry). Falling DOWN
        is a *degradation*: a weaker model answers and the operator sees only a plausible
        reply, so a stale Tier-1 key or an unknown model name would live on for weeks
        behind it — exactly the masking Срез E refused one floor below, and the reason both
        floors now share :func:`~bob.application.router.fallback_policy.should_fall_back`.
        Escalating UP is not a degradation at all: it is the ordinary call to the QUALITY
        tier, so a Tier-0 contract defect must not cost the interlocutor a real answer —
        and it stays visible anyway, because every служебный Tier-0 turn surfaces it.

        🔴 No merry-go-round. There is exactly ONE rescue attempt and it is made OUTSIDE the
        ``try``, so a Tier 1 -> Tier 0 fallback can never bounce back up (nor a Tier 0 -> Tier 1
        escalation back down): its own failure propagates. When nobody answers for Bob the
        turn ends in the honest GUPPI outage notice (``EssentialRunner`` ->
        :data:`~bob.infrastructure.telegram.guppi.GUPPI_OUTAGE_TEXT`, the third-person
        "connection trouble, Bob is temporarily unavailable" system line) — the interlocutor
        gets a live line, never a borrowed voice, a bare traceback or silence.
        """
        return await self._run(request, optional=False)

    async def run_optional(self, request: LLMRequest) -> str | None:
        """Complete a step the caller declares OPTIONAL; ``None`` when no provider could serve it.

        For a side step of a turn — the mood read off the inbound, the staleness re-read
        before sending — whose absence the turn survives (BOB-116 D13). The routing, the
        rescue matrix and the health reporting are exactly those of :meth:`run`; only the end
        differs. When the last attempt failed because the endpoint could not or would not
        serve us — the SAME verdict that decides a fallback
        (:func:`~bob.application.router.fallback_policy.should_fall_back`: auth, rate, server,
        timeout, connection, shape) — the step is skipped: one WARNING line without a stack,
        and ``None``. The monitor has already recorded that failure, so nothing more is
        reported, and the caller leaves its state as it was.

        🔴 Not a catch-all. A ``contract`` failure (a 400, a broken body, our own bug) is a
        defect the fallback policy refuses to hide, and this method refuses to hide it too;
        an error that is not a provider failure at all (a database error, a ``TypeError``)
        classifies as ``contract`` and propagates as well. Cancellation is not an
        ``Exception`` and is never caught.
        """
        try:
            return await self._run(request, optional=True)
        except Exception as error:
            if not should_fall_back(error):
                raise
            logger.warning(
                "optional step %s skipped: the provider could not serve it (%s: %s: %s)",
                request.task_type.value,
                classify_failure(error),
                type(error).__name__,
                error,
            )
            return None

    async def _run(self, request: LLMRequest, *, optional: bool) -> str:
        """The one routing path behind :meth:`run` and :meth:`run_optional`."""
        preferred = self._destination_tier(request)
        messages = self._build_messages(request)
        voice = self._who_may_answer(request)
        try:
            return await self._complete_gated(preferred, messages, voice)
        except Exception as error:
            rescue = self._rescue_tier(
                request, preferred=preferred, voice=voice, error=error, optional=optional
            )
            if rescue is None:
                raise
        return await self._complete_gated(rescue, messages, voice)

    def _rescue_tier(
        self,
        request: LLMRequest,
        *,
        preferred: int,
        voice: OutageVoice,
        error: Exception,
        optional: bool,
    ) -> int | None:
        """Which tier — if any — may try this turn once more; ``None`` = the failure stands.

        The single place the fallback matrix in :meth:`run` is decided, so the direction of
        a rescue and the right to have one at all are read in one screen instead of being
        spread over the ``except`` arms. Announcing the switch is part of it: a degradation
        the owner cannot see in the log is exactly the silent one Срез E ruled out.
        ``optional`` (from :meth:`run_optional`) changes only what a Tier-0 outage that
        nobody rescues writes to the log here: nothing, because the skip writes its own line.
        """
        if preferred != _TIER_LOCAL:
            if not should_fall_back(error):
                logger.error(
                    "Tier 1 failed on %s with a CONTRACT failure (%s: %s); surfacing it "
                    "instead of hiding a broken Tier-1 configuration behind Tier 0",
                    request.task_type.value,
                    type(error).__name__,
                    error,
                )
                return None
            logger.warning(
                "Tier 1 completion failed for %s; falling back to Tier 0",
                request.task_type.value,
            )
            return _TIER_LOCAL
        if voice is OutageVoice.CLOUD_TIER1:
            logger.warning(
                "Tier 0 outage on %s; escalating UP to Tier 1 — Bob's own voice is "
                "never handed to the local understudy",
                request.task_type.value,
            )
            return _TIER_API
        if optional and should_fall_back(error):
            # The skip in run_optional is the one line about this outage: logging it here
            # too would report one failure twice, once with a stack. A contract failure is
            # not skipped, so it keeps the stack below.
            return None
        if self._health_reader is not None and self._health_reader.is_degraded(TIER0_PRIMARY):
            # The outage is already declared — the monitor logged the transition once and
            # told the owner; a stack per failed turn would only bury that line.
            logger.warning(
                "Tier 0 completion failed with no fallback on %s while %s is degraded (%s: %s)",
                request.task_type.value,
                TIER0_PRIMARY,
                type(error).__name__,
                error,
            )
            return None
        logger.exception("Tier 0 completion failed with no fallback")
        return None

    def _who_may_answer(self, request: LLMRequest) -> OutageVoice:
        """Ask the pure voice-integrity core who may answer if this turn's tier goes down.

        Translates the router's knowledge into the core's plain facts: whether the task
        ships AS BOB, whether a stand-in and a cloud tier are wired at all, and whether this
        payload already went through the Tier-1 redaction (the same predicate
        :meth:`_build_messages` redacts by — one source of truth, so an escalation can never
        carry context the normal Tier-1 call would have stripped).

        🔴 What counts as Bob's voice is read from the DOOR, not from the task's name
        (BOB-096.4). Until this slice the question was asked as ``task_type is
        REPLY_TO_USER``, which put the protection on three doors out of nineteen: on the
        night of 2026-08-06 Tier 1 dropped, the understudy composed a rule proposal
        through ``DETECT_PATTERNS`` and it shipped to the owner, while the reflections of
        those hours went into ``episodic_log`` in a borrowed voice and came back as
        few-shot. The concept that replaces it is «the voice that STAYS» —
        :attr:`~bob.application.router.generation_door.GenerationDoor.speaks_as_bob` AND
        :attr:`~bob.application.router.generation_door.GenerationDoor.output_is_kept`:
        the turn is published/written AS BOB *and* it survives the turn. Both halves are
        load-bearing. ``INTERIM_LINE`` speaks as Bob but is never persisted and drops
        silently on failure, so the owner's decision (BOB-087.E-M1) that the stand-in may
        voice it survives with no special case in the code; ``EXTRACT_FACTS`` is kept but
        is machine-format material, not his voice, so an outage does not cost Bob his
        facts. An unclassified door is fail-closed (a voice that stays) one module over.
        """
        door = door_for(request.task_type)
        return who_may_answer_for_bob(
            speaks_in_bobs_voice=door.speaks_as_bob and door.output_is_kept,
            understudy_wired=self._tier0_has_understudy,
            cloud_tier_wired=_TIER_API in self._providers,
            payload_redacted_for_cloud=self._redacts_private_context(request),
        )

    async def _complete_gated(
        self, tier: int, messages: Sequence[LLMMessage], voice: OutageVoice
    ) -> str:
        """Complete on ``tier``, holding the Tier-1 concurrency gate when it applies.

        Only a Tier-1 attempt with a configured gate is throttled; every other call (Tier 0,
        or Tier 1 with no cap) runs ungated — byte-identical to the pre-cap path.
        """
        if tier != _TIER_API or self._tier1_gate is None:
            return await self._complete(tier, messages, voice)
        async with self._tier1_gate:
            return await self._complete(tier, messages, voice)

    def _destination_tier(self, request: LLMRequest) -> int:
        """The tier to attempt first: the caller's override if wired, else the task default.

        An override naming an unknown tier is ignored (falls through to the task
        default) so a mis-set override can never route to a missing provider.
        """
        override = request.tier_override
        if override is not None and override in self._providers:
            return override
        return _PREFERRED_TIER[request.task_type]

    @staticmethod
    def _redacts_private_context(request: LLMRequest) -> bool:
        """Does this task's policy STRIP ``private_context`` from the built payload?

        The redaction predicate itself (Variant 2): true for every task whose policy is
        Tier 1, false for a local-only task, which keeps its private context. Named so both
        readers of the fact — :meth:`_build_messages`, which performs the redaction, and
        :meth:`_who_may_answer`, which may only escalate an already-redacted payload — rest
        on ONE definition instead of two that could drift apart.
        """
        return _PREFERRED_TIER[request.task_type] != _TIER_LOCAL

    def _build_messages(self, request: LLMRequest) -> list[LLMMessage]:
        """Build the payload with selective redaction by destination tier.

        A local-only (Tier 0) request gets BOTH ``shareable_context`` and
        ``private_context``; a Tier 1-bound request gets ONLY
        ``shareable_context`` — ``private_context`` is never attached, so
        genuinely-internal material cannot reach Tier 1 (nor a Tier 1 -> Tier 0
        fallback, nor a Tier 0 -> Tier 1 escalation, since the payload is built once).

        🔴 And this is exactly where the VOICE canon reaches the door (BOB-096.3): the
        payload is built ONCE per request, so the ban rides the rescue attempt too, while
        a служебный door gets not one extra byte. WHICH door needs it, and in which shape,
        is decided by :func:`~bob.application.router.voice_canon.fold_voice_canon` from the
        door's properties; the text itself is injected from the persona.
        """
        parts = [request.shareable_context]
        if not self._redacts_private_context(request):
            parts.append(request.private_context)
        context = "\n".join(part for part in parts if part)
        messages: list[LLMMessage] = list(request.messages)
        if context:
            context_message: LLMMessage = {"role": "system", "content": context}
            messages = [context_message, *messages]
        return fold_voice_canon(
            messages, door=door_for(request.task_type), canon=self._voice_canon
        )

    def _provider_for(self, tier: int, voice: OutageVoice) -> LLMProvider:
        """The provider to call — with the local stand-in taken OUT for Bob's own voice.

        For a служебный ход (:attr:`OutageVoice.LOCAL_UNDERSTUDY`) the composite is used as
        composed, so Срез E's insurance is untouched. For a turn published AS BOB the bare
        primary is used instead: the stand-in must not answer through EITHER door — neither
        the direct Tier-0 attempt nor the Tier 1 -> Tier 0 fallback — so what reaches the
        user is Bob's own model or an honest outage. A provider with no stand-in (the flag
        off, and every Tier-1 provider) is returned untouched.
        """
        provider = self._providers[tier]
        if voice is OutageVoice.LOCAL_UNDERSTUDY:
            return provider
        if isinstance(provider, UnderstudyBackedProvider):
            return provider.without_understudy()
        return provider

    async def _complete(
        self, tier: int, messages: Sequence[LLMMessage], voice: OutageVoice
    ) -> str:
        provider = self._provider_for(tier, voice)
        provider_id = self._reported_id(tier, provider)
        try:
            result = await provider.complete(messages, stream=False)
        except Exception as error:
            if provider_id is not None:
                # Awaited BEFORE the error propagates: the lane gate compares snapshots
                # around the tick and must already see this failure (BOB-116 D5).
                await self._health.record_failure(provider_id, classify_failure(error))
            raise
        if provider_id is not None:
            await self._health.record_success(provider_id)
        if not isinstance(result, str):
            raise TypeError("non-stream completion must return str")
        return result

    @staticmethod
    def _reported_id(tier: int, provider: LLMProvider) -> str | None:
        """Under which id the router reports a call to ``provider`` — ``None``: not its to report.

        The understudy wrapper reports ``tier0-primary`` and ``tier0-understudy`` itself, and
        a self-reporting provider (Tier 1 from the factory, BOB-116 F1) reports its own calls,
        so a call that goes THROUGH either is left to it; reporting it here as well would
        count one HTTP call twice. The decision is made on the provider actually called, so
        the bare primary behind Bob's own voice (``without_understudy``) is reported here.
        """
        if isinstance(provider, (UnderstudyBackedProvider, SelfReportingProvider)):
            return None
        return TIER0_PRIMARY if tier == _TIER_LOCAL else TIER1
