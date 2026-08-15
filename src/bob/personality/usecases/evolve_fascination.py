# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""EvolveFascination — the rare, grounded fascination-evolution step (BOB-020).

Hooked onto the heartbeat reflect tick (a slow cadence), this lets Bob's current
fascination *evolve over time* — never randomly. Each run:

1. **Load + age.** Read the persisted :class:`Fascination` and decay it against the
   injected :class:`~bob.kernel.ports.Clock` (intensity wanes with age).
2. **Decide a shift.** A shift happens only when there is no current fascination,
   or the current one has decayed past its floor (:meth:`Fascination.has_faded`).
   A still-alive passion is left untouched — so the step is naturally **idempotent**
   within a period: a freshly-picked fascination has age ≈ 0, so a second tick in
   the same period does not shift again (no processed-marker bookkeeping needed).
3. **Ground the pick.** On a shift, a cheap Tier-0 call picks the new topic from
   Bob's REAL inner life — his most recent reflection and his strongest taste
   topics — so the passion is grounded, not invented. If Tier 0 yields nothing
   usable — no answer, or no model willing to answer for Bob at all (see
   :meth:`EvolveFascination._tier0_pick`) — a deterministic **heuristic fallback**
   derives the topic straight from the same grounding material. With NO grounding
   material at all, the step is a clean no-op (Bob simply has no fascination yet).
4. **Persist** the fresh fascination (full initial intensity, ``created_at`` = now)
   via the :class:`~bob.personality.ports.FascinationStore`.

Everything is injected — store, router, the grounding seam, clock, and the initial
intensity — so the step holds no globals and is deterministic in tests on fakes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.personality.fascination import MAX_INTENSITY, MIN_INTENSITY, Fascination
from bob.personality.language import DEFAULT_LANGUAGE, language_directive

if TYPE_CHECKING:
    from datetime import datetime

    from bob.kernel.ports import Clock
    from bob.personality.ports import FascinationStore

logger = logging.getLogger(__name__)

# A fresh pick starts vivid; it then decays with age (Fascination.aged). Tunable
# per persona via config (``emotion.fascination.initial_intensity``).
_DEFAULT_INITIAL_INTENSITY = 0.85

# How many strong taste topics to offer the Tier-0 pick as grounding (a tight
# steer, not a dump).
_MAX_TASTE_TOPICS = 4

# The cheap Tier-0 pick: choose, from Bob's REAL recent inner life, the one topic he
# is most into right now. It must answer with ONLY the topic (a short noun phrase),
# grounded in the material — never an invented interest.
_PICK_PROMPT = (
    "You are Bob's inner voice. From the real material below — a recent private "
    "reflection and the topics you care most about — name in a short noun phrase the "
    "ONE thing you are most absorbed by right now. Answer with ONLY that topic, no "
    "preamble, no quotes. It MUST come from the material; do not invent a new interest."
)


class _Router(Protocol):
    """The narrow router seam the pick needs: run one LLM request, get text back.

    Structurally satisfied by :class:`~bob.application.router.LLMRouter` (which app.py
    injects); depending on the contract rather than the concrete router keeps the step
    testable on a cheap fake.
    """

    async def run(self, request: LLMRequest) -> str: ...


class FascinationGrounding(Protocol):
    """The grounding seam: Bob's real inner-life sources for a fascination pick.

    Two REAL, persisted sources (never random): his most recent reflection text
    (the same :class:`~bob.personality.ports.ReflectionReader` seam the leak path uses,
    ``None`` when there is none) and his strongest taste topics (the names of the
    axes he holds with real conviction). A fascination is derived from these, so it
    is always rooted in something Bob actually thinks or cares about.
    """

    async def latest_reflection_text(self) -> str | None:
        """Return Bob's most recent real reflection text, or ``None`` if there is none."""
        ...

    def strong_taste_topics(self) -> tuple[str, ...]:
        """Return the topics Bob holds strongest opinions on (strongest first)."""
        ...


class EvolveFascination:
    """Rarely refresh Bob's current fascination — grounded, idempotent, bounded."""

    def __init__(
        self,
        *,
        persona_id: str,
        store: FascinationStore,
        router: _Router,
        grounding: FascinationGrounding,
        clock: Clock,
        initial_intensity: float = _DEFAULT_INITIAL_INTENSITY,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._persona_id = persona_id
        self._store = store
        self._router = router
        self._grounding = grounding
        self._clock = clock
        self._initial_intensity = _bounded(initial_intensity)
        self._language = language

    async def run(self) -> None:
        """Run one evolution step: shift the fascination only when it has spent itself."""
        now = self._clock.now()
        if not await self._should_shift(now):
            return
        material = await self._collect_grounding()
        if not material:
            logger.debug("no grounding material for fascination; staying empty")
            return
        topic = await self._pick_topic(material)
        if not topic:
            return
        fresh = Fascination(topic=topic, intensity=self._initial_intensity, created_at=now)
        await self._store.save(self._persona_id, fresh)
        logger.debug("fascination shifted to %r for persona %s", topic, self._persona_id)

    async def _should_shift(self, now: datetime) -> bool:
        """A shift is due only with no current fascination or a faded one (idempotent)."""
        current = await self._store.load(self._persona_id)
        if current is None:
            return True
        return current.aged(now=now).has_faded()

    async def _collect_grounding(self) -> list[str]:
        """Gather Bob's real grounding material (recent reflection + strong tastes)."""
        material: list[str] = []
        reflection = await self._grounding.latest_reflection_text()
        if reflection and reflection.strip():
            material.append(reflection.strip())
        material.extend(self._grounding.strong_taste_topics()[:_MAX_TASTE_TOPICS])
        return material

    async def _pick_topic(self, material: list[str]) -> str:
        """Pick the new topic: a Tier-0 grounded choice, heuristic fallback otherwise."""
        chosen = await self._tier0_pick(material)
        if chosen:
            return chosen
        return self._heuristic_pick(material)

    async def _tier0_pick(self, material: list[str]) -> str:
        """Ask Tier 0 for the one topic Bob is most into, grounded in ``material``.

        🔴 The pick goes through its OWN door (BOB-096.8). It used to travel as an
        ``INNER_MONOLOGUE`` — a door the registry called служебной, «nowhere published,
        nowhere saved» — while this very method persists the model's answer: it becomes
        :class:`~bob.personality.fascination.Fascination.topic` in SQLite and is woven into
        Bob's replies for weeks («меня сейчас занимает…»). So the work is its own door,
        ``FASCINATION_PICK``, and it is «the voice that stays»: the ban on role-playing
        GUPPI reaches it, and a local stand-in never chooses what Bob is into.

        An outage therefore yields NOTHING here rather than a 0.5b answer — and the step
        does not lose its tick over it: the caller falls to the deterministic heuristic
        pick, grounded in the very same real material, which invents nothing.
        """
        try:
            verdict = await self._router.run(
                LLMRequest(
                    task_type=TaskType.FASCINATION_PICK,
                    messages=[{"role": "system", "content": self._localised(_PICK_PROMPT)}],
                    shareable_context="Real material:\n- " + "\n- ".join(material),
                )
            )
        except Exception:
            logger.warning(
                "fascination pick got no model answer; grounding it heuristically instead"
            )
            return ""
        return _first_line(verdict)

    @staticmethod
    def _heuristic_pick(material: list[str]) -> str:
        """Deterministic, still-grounded fallback: the first real grounding item."""
        return material[0]

    def _localised(self, prompt: str) -> str:
        """Prepend the persona language directive to a self-generated prompt (BOB-012)."""
        return f"{language_directive(self._language)}\n{prompt}"


def _first_line(text: str) -> str:
    """Take the first non-empty line of a Tier-0 reply as the topic (``""`` if blank)."""
    for line in text.splitlines():
        stripped = line.strip().strip('"').strip("«»").strip()
        if stripped:
            return stripped
    return ""


def _bounded(intensity: float) -> float:
    """Clamp a configured initial intensity into the valid ``[0, 1]`` range."""
    return max(MIN_INTENSITY, min(MAX_INTENSITY, intensity))
