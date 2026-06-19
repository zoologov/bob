# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition root — wire every layer into the running GUPPI process.

This is the ONLY module allowed to depend on all layers at once. It loads the
layered config, builds the real infrastructure adapters (SQLite repo + FTS5
recall, OpenAI-compatible Tier 0/1 providers, the Telegram gateway, the soul
store), composes the application policy (the :class:`LLMRouter`, the personality
state, the message handler, and the heartbeat ticks), subscribes
:class:`HandleMessage` to the EventBus, registers the ticks + Telegram polling as
runtime background tasks, runs :class:`RunGenesis` once on first boot, and starts
the :class:`AgentRuntime`.

Secrets (``telegram.token``, ``llm.tier1_api_key``) come from config/env only —
never inlined here. The providers and the Telegram bot are injectable seams so
the whole graph can be exercised end-to-end on fakes (no network).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bob.application.router import LLMRouter
from bob.application.runtime import (
    MESSAGE_RECEIVED,
    AgentRuntime,
    AsyncEventBus,
    MessageReceived,
    periodic,
)
from bob.application.usecases.extract_facts import ExtractFacts
from bob.application.usecases.handle_message import HandleMessage, PersonalityState
from bob.application.usecases.heartbeat import (
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
)
from bob.application.usecases.run_genesis import RunGenesis
from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
from bob.domain.personality.mood import Mood
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine
from bob.infrastructure.config import ConfigLoader
from bob.infrastructure.llm import build_tier_providers
from bob.infrastructure.persistence import Fts5MemoryRecall, SoulStore, SqliteMemoryRepo
from bob.infrastructure.telegram.gateway import (
    BotLike,
    MessageLike,
    TelegramGateway,
    UpdateLike,
)

if TYPE_CHECKING:
    from bob.application.runtime.agent import BackgroundTask
    from bob.application.usecases.run_genesis import GenesisResult
    from bob.domain.ports import DomainEvent, EventHandler, LLMProvider

logger = logging.getLogger(__name__)

# Default heartbeat cadence and gateway streaming knobs.
_DEFAULT_HEARTBEAT_SECONDS = 30
_DEFAULT_POLL_TIMEOUT = 10
_BATCH_TOKENS = 4
_THROTTLE_INTERVAL = 0.5
_MOOD_DRIFT_SECONDS = 60.0

# Where the bob-soul personality templates live (repo root / bob-soul).
_DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "bob-soul"


class SystemClock:
    """Real time source (UTC). Injected so the domain avoids ``datetime.now()``."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclass
class Application:
    """The assembled, runnable GUPPI process and its wired collaborators.

    Holds the composition result so the entrypoint (and tests) can run lifecycle
    (:meth:`startup` / :meth:`shutdown`) and inspect the bound adapters without
    re-running the wiring.
    """

    config: Mapping[str, object]
    runtime: AgentRuntime
    event_bus: AsyncEventBus
    memory_repo: SqliteMemoryRepo
    soul_store: SoulStore
    genesis: RunGenesis
    personality: PersonalityState
    handle_message: HandleMessage
    inner_monologue_tick: InnerMonologueTick
    mood_drift_tick: MoodDriftTick
    reflect_tick: ReflectTick

    async def startup(self) -> GenesisResult:
        """Initialise persistence, awaken Bob on first boot, load his soul.

        Idempotent Genesis: the first boot generates the soul (Tier 1) and writes
        ``data/soul/``; every later boot loads the existing soul untouched. The
        loaded soul becomes the live :class:`PersonalityState`.
        """
        await self.memory_repo.initialize()
        result = await self.genesis.run()
        self.personality.soul = _load_soul(self.soul_store)
        return result

    async def shutdown(self) -> None:
        """Stop the runtime and close persistence (idempotent)."""
        await self.runtime.stop()
        await self.memory_repo.close()


def build_application(
    *,
    config_path: Path | None = None,
    config: Mapping[str, object] | None = None,
    providers: Mapping[int, LLMProvider] | None = None,
    bot: BotLike | None = None,
) -> Application:
    """Wire the full GUPPI graph from configuration into a runnable application.

    ``config`` / ``providers`` / ``bot`` are injectable seams: when omitted the
    real adapters are built from config; tests pass fakes to exercise the whole
    graph without a network or a Telegram account.
    """
    merged = dict(config) if config is not None else ConfigLoader(yaml_path=config_path).load()

    clock = SystemClock()
    event_bus = AsyncEventBus()
    tier_providers = providers if providers is not None else build_tier_providers(merged)
    router = LLMRouter(providers=tier_providers)

    memory_repo = SqliteMemoryRepo(_db_path(merged))
    recall = Fts5MemoryRecall(memory_repo)
    soul_store = SoulStore(_soul_dir(merged))

    genesis = RunGenesis(
        templates_dir=_templates_dir(merged),
        router=router,
        soul_store=soul_store,
        clock=clock,
    )

    personality = PersonalityState(soul=_default_soul())
    update_mood = UpdateMoodFromText(router=router, clock=clock)
    extract_facts = ExtractFacts(router=router, repo=memory_repo, clock=clock)
    gateway = _build_gateway(merged, bus=event_bus, bot=bot)

    handle_message = HandleMessage(
        router=router,
        gateway=gateway,
        recall=recall,
        repo=memory_repo,
        episodes=memory_repo,
        update_mood=update_mood,
        extract_facts=extract_facts,
        clock=clock,
        state=personality,
    )
    event_bus.subscribe(MESSAGE_RECEIVED, _as_handler(handle_message))

    inner_monologue_tick = InnerMonologueTick(router=router, state=personality)
    mood_drift_tick = MoodDriftTick(state=personality)
    reflect_tick = ReflectTick(
        router=router, repo=memory_repo, state=personality, clock=clock
    )

    runtime = AgentRuntime(
        background_tasks=_background_tasks(
            merged,
            gateway=gateway,
            inner_monologue_tick=inner_monologue_tick,
            mood_drift_tick=mood_drift_tick,
            reflect_tick=reflect_tick,
        )
    )

    return Application(
        config=merged,
        runtime=runtime,
        event_bus=event_bus,
        memory_repo=memory_repo,
        soul_store=soul_store,
        genesis=genesis,
        personality=personality,
        handle_message=handle_message,
        inner_monologue_tick=inner_monologue_tick,
        mood_drift_tick=mood_drift_tick,
        reflect_tick=reflect_tick,
    )


# --- Wiring helpers -----------------------------------------------------------


def _as_handler(handle_message: HandleMessage) -> EventHandler:
    """Adapt :meth:`HandleMessage.handle` to the EventBus handler signature."""

    async def handler(event: DomainEvent) -> None:
        if isinstance(event, MessageReceived):
            await handle_message.handle(event)

    return handler


def _build_gateway(
    config: Mapping[str, object], *, bus: AsyncEventBus, bot: BotLike | None
) -> TelegramGateway:
    """Build the Telegram gateway; the bot is injected (real PTB or a fake)."""
    telegram = _section(config, "telegram")
    return TelegramGateway(
        bot=bot if bot is not None else _build_real_bot(telegram),
        bus=bus,
        poll_timeout=_int(telegram, "poll_timeout", _DEFAULT_POLL_TIMEOUT),
        batch_tokens=_BATCH_TOKENS,
        throttle_interval=_THROTTLE_INTERVAL,
        clock=_monotonic,
        sleep=_async_sleep,
    )


def _build_real_bot(telegram: Mapping[str, object]) -> BotLike:
    """Construct the real python-telegram-bot ``Bot`` from the configured token."""
    from telegram import Bot  # noqa: PLC0415 — lazy: only the real-bot path needs PTB

    token = telegram.get("token")
    if not isinstance(token, str) or not token:
        raise KeyError("telegram.token is required to build the real bot")
    return _PtbBotAdapter(Bot(token=token))


def _background_tasks(
    config: Mapping[str, object],
    *,
    gateway: TelegramGateway,
    inner_monologue_tick: InnerMonologueTick,
    mood_drift_tick: MoodDriftTick,
    reflect_tick: ReflectTick,
) -> list[BackgroundTask]:
    """Build the supervised background tasks: polling + the three heartbeat ticks."""
    runtime = _section(config, "runtime")
    heartbeat = float(_int(runtime, "heartbeat_seconds", _DEFAULT_HEARTBEAT_SECONDS))

    async def poll() -> None:
        await gateway.poll_once()

    return [
        periodic(poll, interval_seconds=0.0),
        periodic(inner_monologue_tick.run, interval_seconds=heartbeat),
        periodic(mood_drift_tick.run, interval_seconds=_MOOD_DRIFT_SECONDS),
        periodic(reflect_tick.run, interval_seconds=heartbeat * 10),
    ]


def _monotonic() -> float:
    return asyncio.get_event_loop().time()


# --- Soul loading -------------------------------------------------------------


def _load_soul(soul_store: SoulStore) -> SOUL:
    """Build the in-memory :class:`SOUL` from the persisted soul artifacts.

    Falls back to a neutral default if the JSON profiles are absent (a fresh
    install before Genesis has fully written them).
    """
    if not soul_store.soul_exists():
        return _default_soul()
    identity = soul_store.read_soul()
    mood_doc = soul_store.read_json("mood")
    baseline = _mood_from(mood_doc, "baseline")
    current = _mood_from(mood_doc, "current")
    taste = _taste_from(soul_store.read_json("taste_profile"))
    phantoms = _phantoms_from(soul_store.read_json("phantom_prefs"))
    return SOUL(
        identity=identity,
        mood=current,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=phantoms,
    )


def _default_soul() -> SOUL:
    """A neutral starting soul used before Genesis has run."""
    neutral = Mood()
    return SOUL(
        identity="I am Bob, awaiting Genesis.",
        mood=neutral,
        mood_baseline=neutral,
        taste=TasteEngine(),
    )


def _mood_from(doc: object, key: str) -> Mood:
    if not isinstance(doc, Mapping):
        return Mood()
    section = doc.get(key)
    if not isinstance(section, Mapping):
        return Mood()
    return Mood(
        valence=_float(section, "valence"),
        arousal=_float(section, "arousal"),
        openness=_float(section, "openness"),
        social=_float(section, "social"),
        stability=_float(section, "stability"),
    )


def _taste_from(doc: object) -> TasteEngine:
    if not isinstance(doc, Mapping):
        return TasteEngine()
    axes_doc = doc.get("axes")
    if not isinstance(axes_doc, list):
        return TasteEngine()
    axes: list[TasteAxis] = []
    for raw in axes_doc:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        if not isinstance(name, str):
            continue
        axes.append(
            TasteAxis(
                name=name,
                value=_float(raw, "value"),
                conviction=_float(raw, "conviction"),
                experience_count=_int(raw, "experience_count", 0),
            )
        )
    return TasteEngine(axes=tuple(axes))


def _phantoms_from(doc: object) -> tuple[str, ...]:
    if not isinstance(doc, Mapping):
        return ()
    prefs = doc.get("preferences")
    if not isinstance(prefs, list):
        return ()
    return tuple(str(p) for p in prefs)


# --- Config readers -----------------------------------------------------------


def _db_path(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "db_path", "data/bob.db"))


def _soul_dir(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "soul_dir", "data/soul"))


def _templates_dir(config: Mapping[str, object]) -> Path:
    genesis = _section(config, "genesis")
    configured = genesis.get("templates_dir")
    if isinstance(configured, str) and configured:
        return Path(configured)
    return _DEFAULT_TEMPLATES_DIR


def _section(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _str(section: Mapping[str, object], key: str, default: str) -> str:
    value = section.get(key)
    return value if isinstance(value, str) and value else default


def _int(section: Mapping[str, object], key: str, default: int) -> int:
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _float(section: Mapping[str, object], key: str) -> float:
    value = section.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


# --- PTB bot adapter ----------------------------------------------------------


class _PtbBotAdapter:
    """Adapt python-telegram-bot's async ``Bot`` to the gateway's :class:`BotLike`."""

    def __init__(self, bot: object) -> None:
        self._bot = bot

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]:
        return await self._bot.get_updates(offset=offset, timeout=timeout)  # type: ignore[attr-defined,no-any-return]

    async def send_message(self, *, chat_id: int, text: str) -> MessageLike:
        return await self._bot.send_message(chat_id=chat_id, text=text)  # type: ignore[attr-defined,no-any-return]

    async def edit_message_text(self, *, chat_id: int, message_id: int, text: str) -> object:
        return await self._bot.edit_message_text(  # type: ignore[attr-defined]
            chat_id=chat_id, message_id=message_id, text=text
        )


# --- Entrypoint ---------------------------------------------------------------


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(app: Application) -> None:
    await app.startup()
    await app.runtime.start()
    try:
        await app.runtime.run_until_stopped()
    finally:
        await app.shutdown()


def main(*, config_path: Path | None = None) -> None:
    """Process entrypoint: build the application and run until stopped."""
    app = build_application(config_path=config_path)
    runtime_cfg = _section(app.config, "runtime")
    _configure_logging(_str(runtime_cfg, "log_level", "INFO"))
    logger.info("Bob GUPPI starting")
    asyncio.run(_run(app))


if __name__ == "__main__":
    main()
