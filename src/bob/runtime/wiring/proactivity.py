# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root proactivity wiring — the proactivity engine + background-task schedule.

Assembles the per-persona :class:`ProactivityEngine` (pure drive-model + governance over a
seeded RNG, wired to the store / router / Bob's gateway / the read-seams) and the supervised
background tasks (one poll drives both bots; the heartbeat ticks + the optional pursuit tick,
each wrapped in the shared retry policy). Part of the ``bob.runtime`` composition root
(BOB-062.7a).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from bob.application.runtime import periodic
from bob.application.runtime.heartbeat import health_gated
from bob.infrastructure.telegram.restart_notifier import _RestartNotifier
from bob.kernel.provider_health import TIER0_EFFECTIVE, TIER0_PRIMARY
from bob.personality.language import DEFAULT_LANGUAGE
from bob.proactivity.adapters import KvRestartMarkerStore, RepoProactivitySources
from bob.proactivity.decision import ProactiveDecider
from bob.proactivity.governance import Governance
from bob.proactivity.usecases import ProactivityEngine
from bob.proactivity.usecases.announce_restart import AnnounceRestart
from bob.runtime.config import (
    _BOB_PERSONA,
    _DEFAULT_HEARTBEAT_SECONDS,
    _MOOD_DRIFT_SECONDS,
    _PROACTIVE_TICK_MULTIPLIER,
    _TICK_RETRY_POLICY,
    _flag,
    _int,
    _section,
)
from bob.runtime.wiring.parameters import _build_pursuit_tick_seconds, _resolve_seed

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router import LLMRouter
    from bob.application.runtime.agent import BackgroundTask
    from bob.application.runtime.heartbeat import Tick
    from bob.application.usecases.heartbeat import (
        InnerMonologueTick,
        MoodDriftTick,
        ReflectTick,
    )
    from bob.conversation.conversation import RepeatThresholds
    from bob.infrastructure.telegram.multibot import MultiBotGateway
    from bob.infrastructure.telegram.restart_notifier import _PlainNotifyBot
    from bob.kernel.ports import Clock, HealthReader, MemoryRecall, ReplyGateway
    from bob.memory.adapters import SqliteMemoryRepo
    from bob.personality.state import PersonalityState
    from bob.personality.usecases.fascination_sources import StoreFascinationReader
    from bob.proactivity.adapters import SqliteProactivityStore
    from bob.proactivity.adapters.restart_marker_store import _KvStore
    from bob.proactivity.usecases import ProactiveTick
    from bob.proactivity.usecases.engine import ShareCeiling
    from bob.proactivity.usecases.pursue_goals import PursueGoalsTick
    from bob.social.usecases.sulk_sources import SulkTracker


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
    share_ceiling: ShareCeiling | None = None,
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
        # Share-of-voice throttle (BOB-066 Срез W): the proactive tick defers when Bob has just
        # hogged the room. None (``presence.rhythm`` off) → no throttle, byte-identical.
        share_ceiling=share_ceiling,
    )


def _build_restart_announcer(
    config: Mapping[str, object],
    *,
    bot: _PlainNotifyBot,
    kv: _KvStore,
) -> AnnounceRestart | None:
    """Собрать объявление рестарта — голос Боба «ухожу обновиться» / «вернулся» (BOB-094).

    За флагом ``runtime.restart_notice`` (default OFF → ``None`` → shutdown/startup-хуки
    не вызывают ничего → поведение lifecycle байт-в-байт прежнее). ON → notifier над
    ботом Боба (личка owner'а + топик Боба в группе) поверх маркера апдейт-остановки в
    ``kv``. Реплику подбирает чистое ядро :mod:`bob.proactivity.restart_voice`; таймаут и
    best-effort (чтобы shutdown не подвис) живут в use-case.
    """
    if not _flag(_section(config, "runtime"), "restart_notice"):
        return None
    telegram = _section(config, "telegram")
    notifier = _RestartNotifier(
        bot=bot,
        owner_id=_int(telegram, "owner_id", 0),
        chat_id=_int(telegram, "chat_id", 0),
        topic_id=_int(_section(telegram, "bob"), "topic_id", 0),
    )
    return AnnounceRestart(notifier=notifier, marker_store=KvRestartMarkerStore(kv))


def _background_tasks(
    config: Mapping[str, object],
    *,
    multibot: MultiBotGateway,
    inner_monologue_tick: InnerMonologueTick,
    mood_drift_tick: MoodDriftTick,
    reflect_tick: ReflectTick,
    proactive_tick: ProactiveTick,
    pursue_goals_tick: PursueGoalsTick | None = None,
    health: HealthReader | None = None,
) -> list[BackgroundTask]:
    """Build the supervised background tasks: polling + the heartbeat ticks.

    One poll task drives BOTH bots (Bob + GUPPI) through the multi-bot gateway. The
    proactivity tick runs on the heartbeat cadence like its siblings and is wrapped
    in the same :data:`_TICK_RETRY_POLICY` so a transient LLM/network blip on a
    firing tick is retried before isolation — it is cheap by construction (most
    ticks make ZERO LLM calls). The self-directed goal-pursuit tick (BOB-015 .3) is
    scheduled ONLY when wired (``goals.pursuit_enabled``), on its own (rare) cadence
    ``goals.tick_seconds``; unwired (the default) the schedule is exactly as before.

    LLM-health gate (BOB-116, RFC «Гейт дорожек»): with ``health`` wired, the lanes that
    think with Tier 0 stop calling a provider the monitor has declared degraded.
    ``inner_monologue`` (Tier 0, the shortest cadence) is the PROBE — it runs only when a
    probe is due and its success lifts the degradation through the router's ordinary
    report; ``reflect``, ``proactive`` and ``pursue_goals`` wait silently until it does.
    ``poll`` and ``mood_drift`` make no LLM call and are not gated. A lane closes only when
    Tier 0 as a whole cannot think (BOB-116 F2, review M2): the cloud is down AND the
    understudy is absent, stood down at startup or down too — the monitor's answer for
    ``TIER0_EFFECTIVE``, the same rule that tells the owner «не могу думать». While the
    understudy holds a dead cloud every lane keeps its rhythm (PRD US-2). The probe, its
    schedule and its log line stay ``tier0-primary``'s — the id under which both the router
    and the understudy wrapper report the cloud's call; the wrapper calls the dead cloud only
    when its probe is due and answers on the understudy in between (review R2 N1), so a
    cloud that came back is seen by the first call after its next due probe. ``None`` → the
    schedule is exactly as before BOB-116.
    """
    runtime = _section(config, "runtime")
    heartbeat = float(_int(runtime, "heartbeat_seconds", _DEFAULT_HEARTBEAT_SECONDS))

    async def poll() -> None:
        await multibot.poll_once()

    def gated(tick: Tick, *, probe: bool = False) -> Tick:
        if health is None:
            return tick
        return health_gated(
            tick, reader=health, provider_id=TIER0_PRIMARY, probe=probe, gate_id=TIER0_EFFECTIVE
        )

    tasks: list[BackgroundTask] = [
        periodic(poll, interval_seconds=0.0),
        periodic(
            gated(inner_monologue_tick.run, probe=True),
            interval_seconds=heartbeat,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            mood_drift_tick.run,
            interval_seconds=_MOOD_DRIFT_SECONDS,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            gated(reflect_tick.run),
            interval_seconds=heartbeat * 10,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            gated(proactive_tick.run),
            interval_seconds=heartbeat * _PROACTIVE_TICK_MULTIPLIER,
            retry=_TICK_RETRY_POLICY,
        ),
    ]
    if pursue_goals_tick is not None:
        tasks.append(
            periodic(
                gated(pursue_goals_tick.run),
                interval_seconds=_build_pursuit_tick_seconds(config),
                retry=_TICK_RETRY_POLICY,
            )
        )
    return tasks
