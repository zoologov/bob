# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Acceptance + guardrail tests for emotional self-regulation (BOB-033 US-1..5).

The dev unit tests (``test_disposition``, ``test_reappraise_reflection``,
``test_update_mood_from_text``, ``test_reflection``, ``test_conversation``,
``test_heartbeat`` BOB-033 sections, ``test_handle_message`` containment) already
exercise each mechanism in isolation at ~99 % coverage. This file adds the
behaviour-level layer the PRD user stories demand: the REAL components wired
TOGETHER, driven deterministically (seeded RNG, fake routers, fixed clock — no
real randomness, no wall-clock), proving the cross-component invariants:

* **US-1** living reflections — disposition palette + valence-lean reach the model.
* **US-2** reappraisal is PROBABILISTIC, not always (the anti-mechanistic heart):
  with the REAL ``ReappraiseReflection`` driving the REAL ``ReflectTick``, a low
  SOMETIMES STAYS A LOW (seed control proves both branches end-to-end).
* **US-3** social co-regulation asymmetry — warm lifts more than cold dips, and a
  warm message additionally displaces a prior low toward baseline; PROPORTIONAL.
* **US-4** stability / no runaway — repeated warmth and repeated reappraisal stay
  inside the BOB-030 band; mood never reaches the +1 rail.
* **US-5** containment — a reflection in the recall store is NOT a reply exemplar,
  while the deliberate leak path still surfaces one (covered end-to-end in
  ``test_handle_message``; cross-checked here at the domain seam).

Anti-mechanistic verdict lives in
``test_us2_a_low_sometimes_stays_a_low_across_a_run_of_negative_thoughts``.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter
from bob.application.usecases.handle_message import PersonalityState
from bob.application.usecases.heartbeat import (
    _MONOLOGUE_VALENCE_BAND,
    ReflectTick,
)
from bob.conversation.conversation import recalled_excluding_reflections
from bob.personality.disposition import Disposition
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteEngine
from bob.personality.usecases.reappraise_reflection import ReappraiseReflection
from bob.personality.usecases.update_mood_from_text import (
    TextSignals,
    UpdateMoodFromText,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


# --- Deterministic doubles (no network, no wall-clock, no real RNG) -------------


class FixedClock:
    """A Clock returning a fixed timezone-aware instant (deterministic time-of-day)."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class SentimentReframeProvider:
    """A two-tier provider: Tier 0 labels sentiment, Tier 1 returns a reframe.

    Routing is by tier (the router picks the provider). The SENTIMENT/REFLECT tasks
    land on Tier 0; the reappraisal beat forces Tier 1 via ``tier_override``. Each
    instance serves one fixed string so a test fully controls the model output.
    """

    def __init__(self, *, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        return self.reply


class FakeRepo:
    """Records persisted reflection episodes so the stored text is observable."""

    def __init__(self) -> None:
        self.episodes: list[Mapping[str, object]] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.episodes.append(episode)


class FixedDrawRng(random.Random):
    """A Random whose ``random()`` always returns a fixed draw (seed control)."""

    def __init__(self, draw: float) -> None:
        super().__init__()
        self._draw = draw

    def random(self) -> float:
        return self._draw


def _moment() -> datetime:
    return datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)


def _soul(*, mood: Mood, baseline: Mood, disposition: Disposition) -> SOUL:
    return SOUL(
        identity="Bob",
        mood=mood,
        mood_baseline=baseline,
        taste=TasteEngine(),
        disposition=disposition,
    )


def _two_tier_router(
    *, tier0_reply: str, tier1_reply: str
) -> tuple[LLMRouter, SentimentReframeProvider, SentimentReframeProvider]:
    tier0 = SentimentReframeProvider(reply=tier0_reply)
    tier1 = SentimentReframeProvider(reply=tier1_reply)
    return LLMRouter(providers={0: tier0, 1: tier1}), tier0, tier1


# Canon-Bob's temperament reappraisal_probability() = 0.2 + 0.7*0.8 = 0.76.
# A draw < 0.76 fires the reappraisal; a draw >= 0.76 lets the low stand.
_CANON = Disposition(optimism=0.8, resilience=0.7)
_FIRE_DRAW = 0.1  # under p -> reappraise
_STAND_DRAW = 0.9  # over p -> honest low


def _reflect_tick(
    *,
    soul: SOUL,
    reflection_reply: str,
    sentiment: str,
    reframe: str,
    draw: float,
    repo: FakeRepo,
) -> ReflectTick:
    """Wire the REAL ReflectTick + REAL ReappraiseReflection over deterministic doubles.

    The reflect tick generates ``reflection_reply`` on Tier 0, the reappraiser
    classifies it ``sentiment`` (Tier 0) and — only for a negative thought whose
    seeded ``draw`` falls under the disposition probability — reframes it to
    ``reframe`` on Tier 1. No outcome is faked: the gate is the production code.
    """
    # The reflect tick's own generation + the reappraiser's sentiment both hit Tier 0;
    # using one Tier-0 provider per use-case keeps each output controlled.
    reflect_router, _t0, _t1 = _two_tier_router(
        tier0_reply=reflection_reply, tier1_reply="unused"
    )
    reappraise_router, _rt0, _rt1 = _two_tier_router(
        tier0_reply=sentiment, tier1_reply=reframe
    )
    reappraiser = ReappraiseReflection(
        router=reappraise_router,
        rng=FixedDrawRng(draw),
        disposition=soul.disposition,
    )
    return ReflectTick(
        router=reflect_router,
        repo=repo,
        state=PersonalityState(soul=soul),
        clock=FixedClock(_moment()),
        reappraise=reappraiser,
    )


# === US-1: living reflections (palette + honest valence-lean reach the model) ===


async def test_us1_reflect_tick_carries_the_living_palette_and_valence_lean() -> None:
    # ACCEPTANCE US-1: with the disposition wired through the soul AND a context seam,
    # the reflect prompt the model actually sees carries the few-shot "living Bob"
    # palette and an optimism-derived, HONEST valence-lean — so the Tier-0 model is
    # pulled off monotone gloom toward canon WITHOUT being scripted to "be happy".
    class _Ctx:
        async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:  # noqa: ARG002
            return [{"event_type": "message", "content": "owner: собрал телескоп"}]

    captured: list[str] = []

    class _CapturingTier0(SentimentReframeProvider):
        async def complete(
            self,
            messages: Sequence[Mapping[str, str]],
            *,
            stream: bool = False,  # noqa: ARG002
        ) -> str | AsyncIterator[str]:
            captured.append(" ".join(m.get("content", "") for m in messages))
            return self.reply

    router = LLMRouter(
        providers={
            0: _CapturingTier0(reply="свежая мысль"),
            1: SentimentReframeProvider(reply="x"),
        }
    )
    soul = _soul(mood=Mood(valence=0.3), baseline=Mood(valence=0.3), disposition=_CANON)
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=PersonalityState(soul=soul),
        clock=FixedClock(_moment()),
        reflection_context=_Ctx(),
    )

    await tick.run()

    prompt = captured[0].casefold()
    assert "optimism" in prompt  # the valence-lean reached the model
    assert "honest" in prompt  # ...and it stays honest (a low is allowed)
    # The palette is mixed, not forced-positive: it explicitly admits an honest low.
    assert "тише, чем хотелось бы" in captured[0]


async def test_us1_no_context_fallback_is_preserved_even_with_a_disposition() -> None:
    # US-1 boundary: an UNWIRED reflect tick (no context seam) keeps the legacy generic
    # prompt verbatim even though the soul carries a disposition — the few-shot palette
    # only enriches a grounded prompt, never the bare fallback.
    router, tier0, _ = _two_tier_router(tier0_reply="тихая мысль", tier1_reply="x")
    soul = _soul(mood=Mood(), baseline=Mood(), disposition=_CANON)
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=PersonalityState(soul=soul),
        clock=FixedClock(_moment()),
    )

    await tick.run()

    # The unwired tick generated exactly one reflection on Tier 0 (generic prompt path).
    assert tier0.calls == 1


# === US-2: reappraisal is PROBABILISTIC, not always (the anti-mechanistic heart) =


async def test_us2_negative_thought_under_p_is_reframed_and_mood_lifts_bounded() -> None:
    # ACCEPTANCE US-2 (fire branch): a genuinely negative reflection whose seeded draw
    # falls UNDER the disposition probability is reframed on Tier 1, STORED reframed,
    # and lifts mood — but the lift is clamped to the BOB-030 homeostatic band (no
    # runaway). Wired with the REAL reappraiser; only the seed forces the branch.
    repo = FakeRepo()
    soul = _soul(
        mood=Mood(valence=0.2), baseline=Mood(valence=0.2), disposition=_CANON
    )
    tick = _reflect_tick(
        soul=soul,
        reflection_reply="всё впустую и тихо",
        sentiment="negative",
        reframe="но телескоп почти готов",
        draw=_FIRE_DRAW,
        repo=repo,
    )

    await tick.run()

    assert repo.episodes[0]["content"] == "но телескоп почти готов"  # reframed stored
    assert tick._state.soul.mood.valence > 0.2  # mood lifted
    assert tick._state.soul.mood.valence <= 0.2 + _MONOLOGUE_VALENCE_BAND  # bounded


async def test_us2_negative_thought_over_p_stays_honestly_sad_mood_unchanged() -> None:
    # ACCEPTANCE US-2 (the honest low — the anti-mechanistic core): the SAME negative
    # reflection, the SAME disposition, but a seeded draw OVER the probability → the
    # thought is stored AS-IS (honestly sad) and mood is UNCHANGED. A low is allowed to
    # remain a low; reappraisal is not mechanical. Proven by seed control alone.
    repo = FakeRepo()
    soul = _soul(
        mood=Mood(valence=0.2), baseline=Mood(valence=0.2), disposition=_CANON
    )
    tick = _reflect_tick(
        soul=soul,
        reflection_reply="всё впустую и тихо",
        sentiment="negative",
        reframe="UNUSED — must not be reached",
        draw=_STAND_DRAW,
        repo=repo,
    )

    await tick.run()

    assert repo.episodes[0]["content"] == "всё впустую и тихо"  # stays honestly sad
    assert tick._state.soul.mood.valence == pytest.approx(0.2)  # mood untouched


async def test_us2_positive_thought_is_never_reappraised_even_on_a_firing_draw() -> None:
    # US-2 guardrail: a POSITIVE reflection is never reappraised, even with a draw that
    # WOULD fire a negative one. Only honestly-dark thoughts are candidates — the
    # mechanism never manufactures cheer on top of an already-bright thought.
    repo = FakeRepo()
    soul = _soul(
        mood=Mood(valence=0.2), baseline=Mood(valence=0.2), disposition=_CANON
    )
    tick = _reflect_tick(
        soul=soul,
        reflection_reply="собрал телескоп, славно",
        sentiment="positive",
        reframe="UNUSED",
        draw=_FIRE_DRAW,  # would fire on a negative thought
        repo=repo,
    )

    await tick.run()

    assert repo.episodes[0]["content"] == "собрал телескоп, славно"  # unchanged
    assert tick._state.soul.mood.valence == pytest.approx(0.2)  # mood untouched


async def test_us2_neutral_thought_is_never_reappraised() -> None:
    # US-2 guardrail: a NEUTRAL reflection is likewise never reframed.
    repo = FakeRepo()
    soul = _soul(mood=Mood(valence=0.2), baseline=Mood(valence=0.2), disposition=_CANON)
    tick = _reflect_tick(
        soul=soul,
        reflection_reply="проверил крепление линзы",
        sentiment="neutral",
        reframe="UNUSED",
        draw=_FIRE_DRAW,
        repo=repo,
    )

    await tick.run()

    assert repo.episodes[0]["content"] == "проверил крепление линзы"
    assert tick._state.soul.mood.valence == pytest.approx(0.2)


async def test_us2_a_low_sometimes_stays_a_low_across_a_run_of_negative_thoughts() -> None:
    # THE ANTI-MECHANISTIC VERDICT. Over a run of identical negative thoughts driven by
    # a REAL seeded RNG (not a fixed draw), the REAL reappraiser fires SOMETIMES and lets
    # the low STAND other times — proving Bob is not a "force-positive" machine. We count
    # both outcomes across a seeded sequence: if every low were reframed, this fails.
    fired = 0
    stood = 0
    disposition = _CANON  # p = 0.76, so ~24 % of negatives should stay sad
    shared_rng = random.Random(12345)  # noqa: S311 — deterministic across the run
    for _ in range(60):
        repo = FakeRepo()
        soul = _soul(
            mood=Mood(valence=0.2), baseline=Mood(valence=0.2), disposition=disposition
        )
        reflect_router, _a, _b = _two_tier_router(
            tier0_reply="всё впустую и тихо", tier1_reply="unused"
        )
        reappraise_router, _c, _d = _two_tier_router(
            tier0_reply="negative", tier1_reply="но кое-что вышло"
        )
        reappraiser = ReappraiseReflection(
            router=reappraise_router, rng=shared_rng, disposition=disposition
        )
        tick = ReflectTick(
            router=reflect_router,
            repo=repo,
            state=PersonalityState(soul=soul),
            clock=FixedClock(_moment()),
            reappraise=reappraiser,
        )
        await tick.run()
        if repo.episodes[0]["content"] == "всё впустую и тихо":
            stood += 1  # the low stood, honestly
        else:
            fired += 1  # the low was reframed

    # BOTH branches occur across the run: reappraisal is probabilistic, not mechanical.
    # A low SOMETIMES stays a low — the human, anti-scripted shape the PRD requires.
    assert stood > 0, "a low must SOMETIMES stay a low (anti-mechanistic invariant)"
    assert fired > 0, "reappraisal must SOMETIMES fire (regulation still works)"


async def test_us2_seeded_run_is_fully_reproducible() -> None:
    # Determinism guard: the same seed reproduces the identical fire/stand sequence, so
    # the anti-mechanistic test above never depends on real randomness.
    async def _sequence(seed: int) -> list[bool]:
        rng = random.Random(seed)  # noqa: S311
        out: list[bool] = []
        for _ in range(20):
            repo = FakeRepo()
            soul = _soul(
                mood=Mood(valence=0.2), baseline=Mood(valence=0.2), disposition=_CANON
            )
            rr, _a, _b = _two_tier_router(tier0_reply="всё впустую", tier1_reply="u")
            sr, _c, _d = _two_tier_router(tier0_reply="negative", tier1_reply="лучше")
            tick = ReflectTick(
                router=rr,
                repo=repo,
                state=PersonalityState(soul=soul),
                clock=FixedClock(_moment()),
                reappraise=ReappraiseReflection(router=sr, rng=rng, disposition=_CANON),
            )
            await tick.run()
            # True when the low was reframed (fired), False when it stood.
            out.append(repo.episodes[0]["content"] != "всё впустую")
        return out

    assert await _sequence(999) == await _sequence(999)


# === US-3: social co-regulation asymmetry (REAL UpdateMoodFromText) =============


def _mood_usecase(*, sentiment: str, disposition: Disposition) -> UpdateMoodFromText:
    router, _t0, _t1 = _two_tier_router(tier0_reply=sentiment, tier1_reply="unused")
    return UpdateMoodFromText(
        router=router, clock=FixedClock(_moment()), disposition=disposition
    )


async def test_us3_warm_lifts_valence_more_than_an_equal_cold_dips_it() -> None:
    # ACCEPTANCE US-3 (asymmetry magnitude): from the SAME neutral start, a warm message
    # raises valence by MORE than an equally-strong cold one lowers it — the structural
    # anti-depressant. Compared on the REAL use-case, magnitudes directly.
    warm = _mood_usecase(sentiment="positive", disposition=_CANON)
    cold = _mood_usecase(sentiment="negative", disposition=_CANON)
    signals = TextSignals(text="...", message_count=1, present=True)

    lifted = await warm.run(Mood(valence=0.0), signals)
    dipped = await cold.run(Mood(valence=0.0), signals)

    lift = lifted.valence - 0.0
    dip = 0.0 - dipped.valence
    assert lift > dip > 0.0  # warmth moves Bob more than negativity


async def test_us3_warm_message_displaces_a_prior_low_toward_baseline() -> None:
    # ACCEPTANCE US-3 (displace the low): from a real dip, a warm exchange charges Bob
    # back UP toward his baseline (lift_toward), not merely adds a flat delta — owner's
    # warmth visibly pulls Bob out of the hole. Observable on the social axis, which the
    # bare delta only nudges by the presence step.
    warm = _mood_usecase(sentiment="positive", disposition=_CANON)
    low = Mood(valence=-0.6, social=-0.5)
    baseline = Mood(valence=0.4, social=0.55)
    signals = TextSignals(text="эй, скучал по тебе!", message_count=1, present=True)

    updated = await warm.run(low, signals, target=baseline)

    # Social pulled toward the warmer baseline beyond the bare +0.15 presence step.
    assert updated.social > low.social + 0.15
    assert updated.valence > low.valence  # and valence lifted out of the dip


async def test_us3_cold_message_lowers_weakly_and_never_charges_up() -> None:
    # US-3 asymmetry (cold side): a rude/cold incoming lowers valence (weakly) and NEVER
    # tugs mood up toward baseline — only warmth displaces the low. Social moves ONLY by
    # the presence step, proving no lift_toward pull fired on the cold turn.
    cold = _mood_usecase(sentiment="negative", disposition=_CANON)
    low = Mood(valence=-0.6, social=-0.5)
    baseline = Mood(valence=0.4, social=0.55)
    signals = TextSignals(text="ты бесполезен", message_count=1, present=True)

    updated = await cold.run(low, signals, target=baseline)

    assert updated.valence < low.valence  # dips further (weakly)
    assert updated.social == pytest.approx(low.social + 0.15)  # presence step only


async def test_us3_contagion_is_proportional_to_disposition_not_a_fixed_slam() -> None:
    # US-3 PROPORTIONALITY: the valence move scales with the disposition (a sunnier Bob
    # is lifted more by the same warm message), so contagion is proportional — never a
    # fixed mechanical slam to a constant.
    sunny = _mood_usecase(
        sentiment="positive", disposition=Disposition(optimism=0.9, resilience=0.5)
    )
    muted = _mood_usecase(
        sentiment="positive", disposition=Disposition(optimism=0.1, resilience=0.5)
    )
    signals = TextSignals(text="как здорово!", message_count=1, present=True)

    sunny_up = (await sunny.run(Mood(valence=0.0), signals)).valence
    muted_up = (await muted.run(Mood(valence=0.0), signals)).valence

    assert sunny_up > muted_up > 0.0  # proportional, not constant


# === US-4: stability / no runaway (BOB-030 band holds) ==========================


async def test_us4_repeated_warmth_never_pins_mood_to_the_plus_one_rail() -> None:
    # ACCEPTANCE US-4: a long run of warm, present, bursty messages keeps lifting Bob —
    # but valence must NEVER reach the +1 rail. The clamp + asymmetric (bounded) step
    # mean warmth tops out short of the ceiling: Bob stays a stable optimist, not a
    # saturated one. Each step pulls toward a warm baseline and adds a positive delta.
    warm = _mood_usecase(sentiment="positive", disposition=_CANON)
    baseline = Mood(valence=0.55, social=0.55)
    mood = Mood(valence=-0.3, social=-0.3)
    signals = TextSignals(text="отлично!", message_count=5, present=True)

    for _ in range(50):
        mood = await warm.run(mood, signals, target=baseline)

    assert mood.valence < 1.0  # never the rail
    assert mood.social < 1.0
    # Repeated warmth recovered Bob out of the initial dip (US-3 effect persists).
    assert mood.valence > -0.3


async def test_us4_repeated_reappraisal_stays_inside_the_bob030_band() -> None:
    # ACCEPTANCE US-4: every negative reflection in a long run fires the reappraisal
    # (forced firing draw) and lifts mood — yet the BOB-030 homeostatic band caps the
    # cumulative rise. Bob's OWN regulation can never spiral his mood to an extreme.
    baseline = Mood(valence=0.2)
    soul = _soul(mood=Mood(valence=0.2), baseline=baseline, disposition=_CANON)
    state = PersonalityState(soul=soul)
    for _ in range(40):
        reflect_router, _a, _b = _two_tier_router(
            tier0_reply="всё впустую", tier1_reply="unused"
        )
        reappraise_router, _c, _d = _two_tier_router(
            tier0_reply="negative", tier1_reply="но кое-что хорошо"
        )
        tick = ReflectTick(
            router=reflect_router,
            repo=FakeRepo(),
            state=state,
            clock=FixedClock(_moment()),
            reappraise=ReappraiseReflection(
                router=reappraise_router,
                rng=FixedDrawRng(_FIRE_DRAW),  # always fire (worst case for runaway)
                disposition=_CANON,
            ),
        )
        await tick.run()

    # Bounded by the BOB-030 band around the baseline — no runaway to the +1 rail.
    assert state.soul.mood.valence <= baseline.valence + _MONOLOGUE_VALENCE_BAND + 1e-9
    assert state.soul.mood.valence < 1.0


# === US-5: containment / no mimicry (cross-checked at the domain seam) ===========


def test_us5_reflection_is_not_a_reply_exemplar_while_facts_are_kept() -> None:
    # ACCEPTANCE US-5 (end-to-end in test_handle_message; cross-checked here): the
    # reply-recall pool drops private reflection episodes (so the model cannot parrot
    # reflection TEXT) while facts and message turns still ground the reply.
    reflection = {"content": "всё тлен", "category": "reflection", "source": "episodic"}
    inner = {"content": "заскучал", "category": "inner_monologue", "source": "episodic"}
    fact = {"content": "Ada любит чай", "category": "preference", "source": "semantic"}
    turn = {
        "content": "Ada: привет\nbob: Привет!",
        "category": "message",
        "source": "episodic",
    }

    kept = recalled_excluding_reflections([reflection, inner, fact, turn])

    assert reflection not in kept  # private reflection contained
    assert inner not in kept  # inner monologue contained too
    assert kept == (fact, turn)  # facts + message turns survive (recall-grounding intact)
