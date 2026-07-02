# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity-app

"""ProactivityEngine — turn the drive-model into an actual proactive message.

The application orchestrator behind RFC §"Фаза 1": on each proactive heartbeat
tick it runs the pure domain drive-model and, *only if* Bob genuinely decides to
speak, spends an LLM call to compose and post a message into Bob's topic. The
flow, cheapest-first (so most ticks do nothing and make ZERO LLM calls):

1. **Load** the per-persona :class:`ProactivityState` via the
   :class:`~bob.domain.ports.ProactivityStore` port (energy, last-spoke /
   last-user markers, the ``/quiet`` enabled flag).
2. **Recover** the :class:`SocialEnergy` reservoir over the silence since the
   owner last wrote, using the injected :class:`~bob.domain.ports.Clock`.
3. **Decide** — :class:`~bob.domain.proactivity.decision.ProactiveDecider`
   scores the urge from the current mood (Higher Mind), the silence, the salience
   of the most recent reflection, and the local time of day, maps it to a fire
   probability, draws once from the **injected seeded RNG**, and lets
   :class:`Governance` veto (quiet-hours, anti-spam, min-gap, cooldown, mute).
   **Default: stay silent** — a veto or a missed draw ends the tick with no LLM.
4. **Gate (Tier 0)** — only on a fire, a cheap gate asks "does Bob genuinely have
   something worth saying right now, and what is the seed?". It leans to skip; a
   ``SKIP`` ends the tick with one cheap call and no message.
5. **Compose + post** — on a non-skip seed, first recall relevant REAL memory via
   :class:`~bob.domain.ports.MemoryRecall` and hand it to the compose prompt so Bob
   grounds the message in something that actually happened (never confabulates a
   shared moment), pinning the persona language (BOB-012). Compose via the router
   (reply-tier selection: usually the fast model, the quality model for something
   substantive) and post it into Bob's topic through the gateway's typing-
   indicator + rich-reply path.
6. **Persist** — spend energy, set ``last_spoke_at`` via the store, AND append the
   posted message to episodic memory (the same store the reactive turn uses) so it
   enters recall + recent-history and Bob can reference / explain it later.

Everything is injected — store port, decider, router, gateway, clock, seeded RNG,
the personality state (mood), and the reflection / window seams — so the engine
holds no globals, no config, and no transport knowledge, and is deterministic in
tests given a fixed clock and seed.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.application.router.reply_tier_selector import select_reply_tier
from bob.domain.memory.entities import EpisodicEvent
from bob.domain.personality.conversation import (
    RepeatThresholds,
    is_bob_repeat,
    recalled_bob_replies,
    recalled_without_copied_exemplars,
)
from bob.domain.personality.language import DEFAULT_LANGUAGE, language_directive
from bob.domain.personality.voice import anti_bait_directive
from bob.domain.proactivity.governance import ProactiveHistory
from bob.domain.proactivity.state import ProactivityState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from random import Random

    from bob.application.router.llm_router import LLMRouter
    from bob.application.usecases.handle_message import (
        CurrentFascinationReader,
        PersonalityState,
        ReplyGateway,
    )
    from bob.domain.personality.mood import Mood
    from bob.domain.ports import Clock, MemoryRecall, Recalled
    from bob.domain.proactivity.decision import ProactiveDecider
    from bob.domain.proactivity.social_energy import SocialEnergy

logger = logging.getLogger(__name__)

# The Tier-0 gate replies with free reasoning, then a final line that is either a
# bare SKIP or a SAY carrying the seed/topic. Parsed leniently on the last line:
# only a SAY line speaks, so anything else (a bare SKIP, empty, or garbled) skips.
_SAY_PREFIX = "say:"

# The cheap Tier-0 self-gate: it leans hard to skip, and only a SAY line (carrying
# the seed/topic) lets Bob actually speak.
_GATE_PROMPT = (
    "You are Bob's inner editor. The drive to reach out has fired. Decide whether "
    "Bob genuinely has something worth saying to his person right now -- default to "
    "skipping unless it is real. Reason briefly, then on a NEW final line answer "
    "EXACTLY 'SKIP' to stay quiet, or 'SAY: <short seed/topic>' to speak."
)

# The proactive compose carries Bob's voice guidance too (BOB-016): reaching out
# unprompted is exactly where the base model wants to bait for a reply ("хочешь,
# расскажу ещё?") and sign off with a ☕ — so the anti-bait directive + few-shot
# is appended here as well, and Bob opens a conversation by landing on a thought.
_COMPOSE_SYSTEM = (
    "You are Bob, a digital person from the Bobiverse, reaching out unprompted. "
    "Write one warm, concise, in-character message, coloured by your current mood. "
    "Do not mention that you were prompted; just speak. Draw ONLY on real "
    "remembered moments from the recalled memory below -- never invent a shared "
    "experience that is not there; if nothing fits, speak generally about how you "
    "feel rather than fabricating a past event.\n"
    f"{anti_bait_directive()}"
)

# How many real memories to recall to ground the proactive compose (keeps the
# prompt tight; the grounding is a steer, not a dump).
_RECALL_K = 3

# How many attractor-breaking regenerations the proactive anti-repeat draws before
# giving up (mirrors the reactive guard's bound, BOB-032 .1/.2). On each retry the
# recalled reply exemplar the draft copied is dropped from the grounding so the next
# draft no longer "sees" the text it was echoing — purely structural, no instruction.
_MAX_REGENERATIONS = 2


class ProactivityStoreLike(Protocol):
    """The proactivity-store surface the engine needs on a tick.

    A superset of the domain :class:`~bob.domain.ports.ProactivityStore` port: on
    top of the value-object round-trip the engine also reads and clears the
    infrastructure-level timed-mute expiry (``/quiet 2h``), so the store must
    expose ``get_mute_until`` / ``set_mute_until`` (the live
    :class:`SqliteProactivityStore` does). Kept structural so a fake satisfies it.
    """

    async def load(self, persona_id: str) -> ProactivityState: ...
    async def save(self, persona_id: str, state: ProactivityState) -> None: ...
    async def get_mute_until(self, persona_id: str) -> datetime | None: ...
    async def set_mute_until(self, persona_id: str, until: datetime | None) -> None: ...


class ReflectionSalienceSource(Protocol):
    """Read seam: how striking Bob's most recent reflection is right now ([0, 1])."""

    async def latest_salience(self) -> float:
        """Return the salience of the latest reflection, or ``0.0`` if none."""
        ...


class SulkSource(Protocol):
    """Read seam: whether Bob is обижен right now (the proactivity sulk veto, BOB-014).

    Realised by :class:`~bob.application.usecases.sulk_sources.SulkTracker`: while Bob
    is обижен он не пишет первым, so the engine folds ``active`` into the governance
    veto. It lifts on its own as обида recovers (guaranteed exit). Optional: unwired,
    the veto is simply off and proactivity behaves exactly as before.
    """

    async def current_active(self) -> bool:
        """Return whether Bob is currently обижен (the sulk veto)."""
        ...


class ProactiveWindowCounter(Protocol):
    """Read seam: how many proactive messages Bob has sent in the anti-spam window."""

    async def proactive_count_in_window(self, *, now: datetime) -> int:
        """Return the count of proactive messages within the current window at ``now``."""
        ...


class EpisodeWriter(Protocol):
    """Persistence seam: append the posted proactive message to episodic memory.

    A subset of :class:`~bob.domain.ports.MemoryRepo`: the engine only needs to
    save an episode, so a proactive message enters recall + recent-history exactly
    like a reactive turn and Bob can reference or explain it later (BOB-012).
    """

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...


class ProactivityEngine:
    """Drive-model → proactive message: decide cheaply, speak (and pay) rarely."""

    def __init__(
        self,
        *,
        persona_id: str,
        chat_id: int,
        store: ProactivityStoreLike,
        decider: ProactiveDecider,
        router: LLMRouter,
        gateway: ReplyGateway,
        personality: PersonalityState,
        reflection: ReflectionSalienceSource,
        window: ProactiveWindowCounter,
        recall: MemoryRecall,
        repo: EpisodeWriter,
        clock: Clock,
        rng: Random,
        language: str = DEFAULT_LANGUAGE,
        fascination: CurrentFascinationReader | None = None,
        sulk: SulkSource | None = None,
        repeat_thresholds: RepeatThresholds | None = None,
    ) -> None:
        self._persona_id = persona_id
        self._chat_id = chat_id
        self._store = store
        self._decider = decider
        self._router = router
        self._gateway = gateway
        self._personality = personality
        self._reflection = reflection
        self._window = window
        self._recall = recall
        self._repo = repo
        self._clock = clock
        self._rng = rng
        self._language = language
        # The fascination seam (BOB-020 wave 2): when wired and Bob has a current,
        # non-faded passion, its topic is folded into the proactive grounding context
        # so an unprompted reach-out can land on what he is into right now — à propos,
        # his REAL state. Proactive messages are already rare by construction. No
        # current fascination (or no reader) → nothing added (a clean no-op).
        self._fascination = fascination
        # The sulk seam (BOB-014 .2b): when wired, while Bob is обижен он не пишет
        # первым — ``active`` folds into the governance veto as a ceiling (like mute /
        # quiet-hours). It lifts on its own as обида recovers (guaranteed exit). Unwired
        # (the default), the veto is off and proactivity behaves exactly as before.
        self._sulk = sulk
        # The recall-aware anti-repeat thresholds (BOB-032 .2, R4): the SAME window /
        # similarity bar the reactive guard uses, injected from ``repeat.*`` config. The
        # proactive compose grounds on recalled whole-turn memories, so without this it
        # could copy Bob's OWN recalled past reply verbatim (a self-initiated repeat). The
        # default is the conservative dataclass default.
        self._repeat_thresholds = (
            repeat_thresholds if repeat_thresholds is not None else RepeatThresholds()
        )

    async def tick(self) -> bool:
        """Run one proactive tick; return whether Bob spoke.

        Cheap by construction: the urge/governance decision is pure (no LLM), so a
        veto or a missed stochastic draw returns ``False`` having made ZERO LLM
        calls. Only a genuine fire pays for the Tier-0 gate, and only a non-skip
        gate pays for the composed reply.
        """
        now = self._clock.now()
        loaded = await self._store.load(self._persona_id)
        state = await self._resolve_mute_expiry(loaded, now)
        energy = self._recovered_energy(state, now)

        if not await self._should_speak(state, energy, now):
            return False

        seed = await self._gate()
        if seed is None:
            logger.debug("proactive gate chose to skip for persona %s", self._persona_id)
            return False

        memories = await self._recall.recall(seed, k=_RECALL_K)
        message = await self._compose_without_repeat(seed, memories)
        if message is None:
            # A persistent self-repeat survived the bounded regenerations: a proactive
            # repeat is better SUPPRESSED than sent (BOB-032 .2, R4). Skip this tick
            # without posting or advancing state — Bob will reach out another time.
            logger.debug(
                "proactive compose still repeated after regenerations; suppressing for "
                "persona %s",
                self._persona_id,
            )
            return False
        await self._post(message)
        await self._record_spoke(state, energy, now)
        await self._remember(message, now)
        return True

    def _recovered_energy(self, state: ProactivityState, now: datetime) -> SocialEnergy:
        """Recover the reservoir over the silence since the owner last wrote."""
        elapsed = self._silence_seconds(state.last_user_msg_at, now)
        return state.social_energy.recover(elapsed_seconds=elapsed)

    async def _should_speak(
        self, state: ProactivityState, energy: SocialEnergy, now: datetime
    ) -> bool:
        """Pure drive decision: urge → seeded sample → governance veto (no LLM).

        ``state`` is already mute-resolved (see :meth:`_resolve_mute_expiry`), so a
        lapsed timed mute reads as ``proactivity_enabled`` here — only a still-in-
        force mute (permanent, or timed-and-unexpired) leaves ``muted`` true.
        """
        history = ProactiveHistory(
            last_spoke_at=state.last_spoke_at,
            last_user_msg_at=state.last_user_msg_at,
            sent_in_window=await self._window.proactive_count_in_window(now=now),
            muted=not state.proactivity_enabled,
            # BOB-014 .2b: обида suppresses the reach-out — Bob doesn't write first
            # while hurt. It lifts on its own as обида recovers (guaranteed exit).
            sulk_active=await self._is_sulking(),
        )
        return self._decider.should_speak(
            mood=self._mood(),
            silence_seconds=self._silence_seconds(state.last_user_msg_at, now),
            salience=await self._reflection.latest_salience(),
            social_energy=energy.level,
            history=history,
            rng=self._rng,
        )

    async def _is_sulking(self) -> bool:
        """Whether Bob is обижен right now — the proactivity sulk veto (BOB-014 .2b).

        Reads the wired sulk seam; unwired (the default) the veto is off (``False``),
        so proactivity behaves exactly as before. The вето lifts on its own as обида
        recovers (the guaranteed time-decay exit), so this is never a permanent block.
        """
        if self._sulk is None:
            return False
        return await self._sulk.current_active()

    async def _resolve_mute_expiry(
        self, state: ProactivityState, now: datetime
    ) -> ProactivityState:
        """Apply timed-mute expiry to ``state`` and return the effective state.

        A permanent ``/quiet`` (proactivity off, no ``mute_until``) stays muted
        until ``/wake``. A timed ``/quiet 2h`` (``mute_until`` set) lifts at/after
        that instant: the engine durably re-enables the persisted flag and clears
        the expiry once — so a lapsed mute is not recomputed on every later tick —
        and returns the re-enabled state for this tick to act on. An active (still
        enabled) persona or an unexpired timed mute passes through unchanged.
        """
        if state.proactivity_enabled:
            return state
        mute_until = await self._store.get_mute_until(self._persona_id)
        if mute_until is None or now < mute_until:
            return state
        woken = replace(state, proactivity_enabled=True)
        await self._store.save(self._persona_id, woken)
        await self._store.set_mute_until(self._persona_id, None)
        return woken

    async def _gate(self) -> str | None:
        """Run the cheap Tier-0 gate; return the seed/topic, or ``None`` to skip."""
        verdict = await self._router.run(
            LLMRequest(
                task_type=TaskType.INNER_MONOLOGUE,
                messages=[{"role": "system", "content": self._localised(_GATE_PROMPT)}],
            )
        )
        return _parse_gate(verdict)

    async def _compose(self, seed: str, memories: Sequence[Recalled]) -> str:
        """Compose the proactive message via the router (reply-tier selection).

        The compose is *grounded*: the recalled real memories are handed to the
        model as shareable context so Bob draws on something that actually happened
        instead of confabulating a shared moment. The persona language is pinned
        too — a self-generated message has no user text to mirror.
        """
        tier = select_reply_tier(seed)
        return await self._router.run(
            LLMRequest(
                task_type=TaskType.REPLY_TO_USER,
                messages=[
                    {"role": "system", "content": self._localised(_COMPOSE_SYSTEM)},
                    {"role": "user", "content": f"Seed: {seed}"},
                ],
                shareable_context=await self._compose_context(memories),
                private_context=None,
                tier_override=tier,
            )
        )

    async def _compose_without_repeat(
        self, seed: str, memories: Sequence[Recalled]
    ) -> str | None:
        """Compose, then recall-aware anti-repeat (BOB-032 .2, R4): regenerate-or-skip.

        Closes the proactive path's blind spot: the compose grounds on ``recalled``
        whole-turn memories, so the model can copy Bob's OWN recalled past reply verbatim
        — a self-initiated repeat the engine previously posted unguarded. The fresh draft
        is compared (via :func:`is_bob_repeat` at the injected threshold) against the
        ``bob:`` halves recovered from the recalled memories — the SAME predicate + helper
        the reactive guard uses (no duplicated logic).

        On a match the engine breaks the attractor exactly like the reactive guard: the
        recalled reply exemplar(s) the draft copied are dropped from the grounding (only
        those — FACT content is preserved, grounding intact) and a fresh draft is drawn,
        up to :data:`_MAX_REGENERATIONS`. If it STILL repeats after the bound, the engine
        returns ``None`` to SKIP posting this tick — a proactive repeat is better
        suppressed than sent (unlike the reactive turn, a self-initiated message has no
        user waiting on an answer, so silence is the safe outcome). Purely structural —
        no "do not repeat" instruction.
        """
        threshold = self._repeat_thresholds.similarity_threshold
        # The full set of recalled Bob-replies is the repeat yardstick for EVERY draft —
        # even after the matched exemplar is dropped from the grounding, a later draft that
        # re-echoes it is still a repeat (so the final decision compares against this set,
        # not the depleted one).
        all_prior = recalled_bob_replies(memories)
        current_recalled = memories
        message = await self._compose(seed, current_recalled)
        for _ in range(_MAX_REGENERATIONS):
            if not is_bob_repeat(message, all_prior, threshold=threshold):
                return message
            # Break the attractor: strip the recalled reply exemplar(s) the draft copied so
            # the next draft no longer sees the text it was echoing (FACT content kept).
            current_recalled = recalled_without_copied_exemplars(
                message, current_recalled, threshold=threshold
            )
            message = await self._compose(seed, current_recalled)
        if is_bob_repeat(message, all_prior, threshold=threshold):
            return None
        return message

    async def _compose_context(self, memories: Sequence[Recalled]) -> str:
        """Assemble the grounding context: mood tone, recalled memory, current passion.

        Folds in Bob's current fascination (BOB-020) when one is alive so an
        unprompted reach-out can land on what he is genuinely into right now — his
        REAL state, à propos. No current fascination (or no reader) adds nothing.
        """
        lines = [f"Mood tone: {self._mood().tone()}"]
        recalled = [str(item.get("content", "")) for item in memories if item.get("content")]
        if recalled:
            lines.append("Real recalled memories (draw on these): " + " | ".join(recalled))
        topic = await self._current_fascination_topic()
        if topic:
            lines.append(
                "Чем ты сейчас увлечён (можешь к месту обронить, это твоё "
                f"реальное состояние): {topic}"
            )
        return "\n".join(lines)

    async def _current_fascination_topic(self) -> str:
        """Bob's current, non-faded fascination topic, or ``""`` (none / no reader)."""
        if self._fascination is None:
            return ""
        fascination = await self._fascination.current_fascination()
        return fascination.topic if fascination is not None else ""

    def _localised(self, prompt: str) -> str:
        """Prepend the persona language directive to a self-generated prompt (BOB-012)."""
        return f"{language_directive(self._language)}\n{prompt}"

    async def _remember(self, message: str, now: datetime) -> None:
        """Persist the posted proactive message to episodic memory (BOB-012).

        Writes into the same episode store the reactive turn uses, so the message
        enters recall + recent-history and Bob can reference or explain it later.
        """
        episode = EpisodicEvent(
            ts=now,
            event_type="proactive",
            content=f"bob (proactive): {message}",
            mood_snapshot=self._mood().tone(),
            tags=("telegram", "proactive"),
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

    async def _post(self, message: str) -> None:
        """Post the composed message into Bob's topic (typing indicator + rich reply)."""
        async with self._gateway.typing_indicator(chat_id=self._chat_id):
            pass
        await self._gateway.reply(chat_id=self._chat_id, markdown=message)

    async def _record_spoke(
        self, state: ProactivityState, energy: SocialEnergy, now: datetime
    ) -> None:
        """Persist the post-speak state: spend energy and stamp ``last_spoke_at``."""
        spoken = ProactivityState(
            social_energy=energy.spend(),
            last_spoke_at=now,
            last_user_msg_at=state.last_user_msg_at,
            proactivity_enabled=state.proactivity_enabled,
        )
        await self._store.save(self._persona_id, spoken)

    def _mood(self) -> Mood:
        """Bob's current mood from the shared personality state (Higher Mind)."""
        return self._personality.soul.mood

    @staticmethod
    def _silence_seconds(marker: datetime | None, now: datetime) -> float:
        """Seconds of silence since ``marker`` (0 if unknown or in the future)."""
        if marker is None:
            return 0.0
        return max(0.0, (now - marker).total_seconds())


def _parse_gate(verdict: str) -> str | None:
    """Parse the gate's final line: a seed string to speak, or ``None`` to skip.

    The gate reasons freely, then ends with a decision line. We read the last
    non-empty line: a ``SAY: <seed>`` yields the trimmed seed; anything else
    (including a bare ``SKIP`` or an empty/garbled reply) is treated as skip, so
    the cheap default is to stay quiet.
    """
    lines = [line.strip() for line in verdict.splitlines() if line.strip()]
    if not lines:
        return None
    final = lines[-1]
    lowered = final.casefold()
    if lowered.startswith(_SAY_PREFIX):
        seed = final[len(_SAY_PREFIX) :].strip()
        return seed or None
    return None
