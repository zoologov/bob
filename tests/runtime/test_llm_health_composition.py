# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Здоровье LLM собрано в живое приложение (BOB-116 D10).

🔴 Отгрузка ≠ активация (П.0.3 п.10): монитор, сигнал владельцу, гейт дорожек, эпизод «я
молчал» и проверка дублёра при старте написаны в W1/W2 — здесь проверяется, что
``build_application`` их ДЕЙСТВИТЕЛЬНО соединил. Всё наблюдается через границу: что ушло
боту Боба в личку владельца, сколько раз позвали провайдера, что легло в эпизодическую
память, что сказал лог, — а не какой объект где лежит.

Отказ провайдера — фейк в сборке (сеть тут ни при чём: роутер докладывает исход вызова), а
вот дублёр при старте проверяется НАСТОЯЩИМ HTTP — мёртвым портом и живым loopback-сервером
(П.0.3 п.4: тест на фейке доказывает контракт фейка).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import aiohttp
from aiohttp import web

from bob.infrastructure.telegram.multibot import BotIdentity
from bob.runtime.composition import build_application
from bob.runtime.wiring.tool_health import report_understudy
from bob.social.adapters.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    import pytest

    from bob.infrastructure.telegram.gateway import BotLike, UpdateLike
    from bob.kernel.ports import LLMProvider
    from bob.runtime.composition import Application

_OWNER_ID = 111
_CHAT_ID = 222
_TOPIC_ID = 5
_THRESHOLD = 5  # дефолт llm.health.failures_threshold
_UNDERSTUDY_MODEL = "qwen3:8b"


class _Clock:
    """Часы, которые двигает тест: зонд не наступает сам по себе."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)

    def now(self) -> datetime:
        return self.moment


class _Tier0:
    """Tier-0, который тест включает и выключает; считает вызовы."""

    def __init__(self) -> None:
        self.alive = False
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        if not self.alive:
            raise aiohttp.ClientConnectionError("tier0 refused")
        return "мысль"


class _Tier1:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        return "ok"


class _Msg:
    message_id = 1


class _Bot:
    def __init__(self) -> None:
        self.sends: list[tuple[int, str, int | None]] = []

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _Msg:
        self.sends.append((chat_id, text, message_thread_id))
        return _Msg()

    async def set_message_reaction(self, **_: object) -> bool:
        return True

    async def send_chat_action(self, **_: object) -> bool:
        return True

    def owner_dms(self) -> list[str]:
        """Тексты, ушедшие в личку владельца (chat_id == owner_id, без топика)."""
        return [text for chat, text, thread in self.sends if chat == _OWNER_ID and thread is None]


def _config(
    tmp_path: Path,
    *,
    llm: Mapping[str, object] | None = None,
    autobiography: bool = False,
) -> dict[str, object]:
    config: dict[str, object] = {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 1},
        "telegram": {
            "poll_timeout": 1,
            "owner_id": _OWNER_ID,
            "chat_id": _CHAT_ID,
            "owner_name": "Вова",
            "bob": {"token": "bob-tok", "topic_id": _TOPIC_ID},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
        "memory": {"autobiography": autobiography},
    }
    if llm is not None:
        config["llm"] = dict(llm)
    return config


def _build(
    tmp_path: Path,
    *,
    tier0: _Tier0,
    bob_bot: _Bot,
    clock: _Clock,
    llm: Mapping[str, object] | None = None,
    autobiography: bool = False,
) -> Application:
    # SOUL заранее — иначе Genesis на старте позвал бы фейк и не разобрал бы ответ.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    providers: dict[int, LLMProvider] = {0: tier0, 1: _Tier1()}
    return build_application(
        config=_config(tmp_path, llm=llm, autobiography=autobiography),
        providers=providers,
        bob_bot=cast("BotLike", bob_bot),
        guppi_bot=cast("BotLike", _Bot()),
        clock=clock,
    )




@contextlib.asynccontextmanager
async def _running(app: Application) -> AsyncIterator[Application]:
    """Старт и гарантированный shutdown: незакрытая БД держит процесс pytest после прогона."""
    await app.startup()
    try:
        yield app
    finally:
        await app.shutdown()


async def _think(app: Application, times: int) -> None:
    """Прогнать тик внутреннего монолога ``times`` раз; его отказ здесь не предмет теста."""
    for _ in range(times):
        with contextlib.suppress(Exception):
            await app.inner_monologue_tick.run()


async def _run_heartbeat_briefly(app: Application) -> None:
    """Дать каждой фоновой задаче собранного рантайма сделать круг и остановить его."""
    await app.runtime.start()
    try:
        for _ in range(20):
            await asyncio.sleep(0)
    finally:
        await app.runtime.stop()


# --- сигнал владельцу -------------------------------------------------------------


async def test_default_config_tells_the_owner_in_bobs_dm_when_tier0_dies(
    tmp_path: Path,
) -> None:
    """Дефолтный конфиг: порог отказов Tier-0 → одно сообщение ботом Боба в личку владельца."""
    bob_bot, tier0, clock = _Bot(), _Tier0(), _Clock()
    async with _running(_build(tmp_path, tier0=tier0, bob_bot=bob_bot, clock=clock)) as app:
        bob_bot.sends.clear()

        await _think(app, _THRESHOLD - 1)
        assert bob_bot.owner_dms() == []  # до порога владельца не будят

        await _think(app, 1)

    dms = bob_bot.owner_dms()
    assert len(dms) == 1
    assert "Вова" in dms[0]


async def test_owner_alert_off_keeps_the_owner_dm_silent(tmp_path: Path) -> None:
    """``llm.health.owner_alert: false`` — приложение собирается, отказ есть, сообщения нет."""
    bob_bot, tier0, clock = _Bot(), _Tier0(), _Clock()
    app = _build(
        tmp_path,
        tier0=tier0,
        bob_bot=bob_bot,
        clock=clock,
        llm={"health": {"owner_alert": False}},
    )
    async with _running(app):
        bob_bot.sends.clear()
        await _think(app, _THRESHOLD + 2)

    assert tier0.calls >= _THRESHOLD  # отказы были, порог пройден
    assert bob_bot.owner_dms() == []


async def test_thresholds_come_from_the_health_block(tmp_path: Path) -> None:
    """Порог из ``llm.health.failures_threshold`` — тот, на котором приходит сигнал."""
    bob_bot, tier0, clock = _Bot(), _Tier0(), _Clock()
    app = _build(
        tmp_path,
        tier0=tier0,
        bob_bot=bob_bot,
        clock=clock,
        llm={"health": {"failures_threshold": 2}},
    )
    async with _running(app):
        bob_bot.sends.clear()
        await _think(app, 2)

    assert len(bob_bot.owner_dms()) == 1


# --- GUPPI /status ------------------------------------------------------------------


@dataclass
class _Message:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _User:
    id: int
    full_name: str = "Owner"
    username: str | None = None


@dataclass
class _Chat:
    id: int
    type: str = "supergroup"


@dataclass
class _Update:
    update_id: int
    message: _Message | None = None
    effective_chat: _Chat | None = None
    effective_user: _User | None = None


async def test_guppi_status_shows_the_monitors_snapshot(tmp_path: Path) -> None:
    """``/status`` владельца в General показывает здоровье того же монитора, что ведёт роутер."""
    bob_bot, guppi_bot, tier0, clock = _Bot(), _Bot(), _Tier0(), _Clock()
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    app = build_application(
        config=_config(tmp_path),
        providers={0: tier0, 1: _Tier1()},
        bob_bot=cast("BotLike", bob_bot),
        guppi_bot=cast("BotLike", guppi_bot),
        clock=clock,
    )
    async with _running(app):
        await _think(app, _THRESHOLD)
        status = _Update(
            update_id=1,
            message=_Message(message_id=7, text="/status"),
            effective_chat=_Chat(id=_CHAT_ID),
            effective_user=_User(id=_OWNER_ID),
        )
        await app.multibot.route(cast("UpdateLike", status), BotIdentity.GUPPI)

    answers = [text for _chat, text, _thread in guppi_bot.sends]
    assert len(answers) == 1
    assert "LLM:" in answers[0]
    assert "tier0 облако — деградирован" in answers[0]


# --- гейт дорожек в собранном рантайме ---------------------------------------------


async def test_composed_heartbeat_stops_calling_a_degraded_tier0(tmp_path: Path) -> None:
    """После деградации дорожки собранного рантайма к Tier-0 не ходят, пока зонд не наступил."""
    bob_bot, tier0, clock = _Bot(), _Tier0(), _Clock()
    async with _running(_build(tmp_path, tier0=tier0, bob_bot=bob_bot, clock=clock)) as app:
        await _think(app, _THRESHOLD)
        calls_at_degradation = tier0.calls

        await _run_heartbeat_briefly(app)

    assert tier0.calls == calls_at_degradation


async def test_composed_heartbeat_probes_once_the_probe_is_due(tmp_path: Path) -> None:
    """Зонд наступил — дорожка монолога идёт к Tier-0, и его ответ снимает деградацию."""
    bob_bot, tier0, clock = _Bot(), _Tier0(), _Clock()
    async with _running(_build(tmp_path, tier0=tier0, bob_bot=bob_bot, clock=clock)) as app:
        await _think(app, _THRESHOLD)
        calls_at_degradation = tier0.calls
        bob_bot.sends.clear()

        tier0.alive = True
        clock.moment += timedelta(seconds=61)  # первый интервал зонда — 60 с
        await _run_heartbeat_briefly(app)

    assert tier0.calls > calls_at_degradation
    assert any("вернулся" in text for text in bob_bot.owner_dms())


# --- эпизод «я молчал» -------------------------------------------------------------


async def _outage_episodes(app: Application) -> list[Mapping[str, object]]:
    episodes = await app.memory_repo.recent_episodes(50)
    return [
        row
        for row in episodes
        if row["event_type"] == "self_action" and "outage" in str(row["tags"])
    ]


async def test_recovery_after_silence_is_written_to_the_autobiography(tmp_path: Path) -> None:
    """Боб молчал (Tier-0 лёг, дублёра нет) и вернулся.

    Эпизод от первого лица, только владельцу, без отправителя.
    """
    bob_bot, tier0, clock = _Bot(), _Tier0(), _Clock()
    app = _build(tmp_path, tier0=tier0, bob_bot=bob_bot, clock=clock, autobiography=True)
    async with _running(app):
        await _think(app, _THRESHOLD)
        clock.moment += timedelta(hours=3)
        tier0.alive = True
        await _think(app, 1)

        episodes = await _outage_episodes(app)

    assert len(episodes) == 1
    assert episodes[0]["visibility"] == "owner_private"
    assert episodes[0]["sender_id"] is None
    assert "молчал" in str(episodes[0]["content"])


async def test_no_outage_episode_without_autobiography(tmp_path: Path) -> None:
    """``memory.autobiography`` выключена — восстановление проходит, эпизода нет."""
    bob_bot, tier0, clock = _Bot(), _Tier0(), _Clock()
    async with _running(_build(tmp_path, tier0=tier0, bob_bot=bob_bot, clock=clock)) as app:
        await _think(app, _THRESHOLD)
        tier0.alive = True
        await _think(app, 1)

        episodes = await _outage_episodes(app)

    assert episodes == []
    assert any("вернулся" in text for text in bob_bot.owner_dms())


# --- дублёр при старте --------------------------------------------------------------


def _dead_port() -> int:
    """Порт, на котором точно никто не слушает: заняли у ОС и сразу отпустили."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _understudy_llm(base_url: str, **extra: object) -> dict[str, object]:
    return {
        "tier0_fallback": "ollama",
        "tier0_fallback_base_url": base_url,
        "tier0_fallback_model": _UNDERSTUDY_MODEL,
        **extra,
    }


@contextlib.asynccontextmanager
async def _models_server(ids: Sequence[str]) -> AsyncIterator[str]:
    """Настоящий loopback-эндпоинт формы Ollama ``GET /v1/models``."""

    async def models(_request: web.Request) -> web.StreamResponse:
        return web.json_response({"object": "list", "data": [{"id": i} for i in ids]})

    server = web.Application()
    server.router.add_get("/v1/models", models)
    runner = web.AppRunner(server)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0][0], runner.addresses[0][1]
        yield f"http://{host}:{port}/v1"
    finally:
        await runner.cleanup()


def _logged(caplog: pytest.LogCaptureFixture, fragment: str) -> bool:
    return any(fragment in record.getMessage() for record in caplog.records)


async def test_dead_understudy_at_startup_tells_the_owner_once_and_boots(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Дублёр включён, эндпоинт мёртв: старт проходит.

    Владельцу одно сообщение, в логе одна строка «NOT ready».
    """
    bob_bot = _Bot()
    app = _build(
        tmp_path,
        tier0=_Tier0(),
        bob_bot=bob_bot,
        clock=_Clock(),
        llm=_understudy_llm(f"http://127.0.0.1:{_dead_port()}/v1"),
    )

    with caplog.at_level(logging.INFO):
        async with _running(app):
            pass

    dms = bob_bot.owner_dms()
    assert len(dms) == 1
    assert "без дублёра" in dms[0]
    assert _logged(caplog, "understudy: on, NOT ready")


async def test_ready_understudy_at_startup_stays_quiet(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Дублёр включён и модель на месте — владельцу ничего, в логе «ready»."""
    bob_bot = _Bot()
    async with _models_server([_UNDERSTUDY_MODEL]) as base_url:
        app = _build(
            tmp_path,
            tier0=_Tier0(),
            bob_bot=bob_bot,
            clock=_Clock(),
            llm=_understudy_llm(base_url),
        )
        with caplog.at_level(logging.INFO):
            async with _running(app):
                pass

    assert bob_bot.owner_dms() == []
    assert _logged(caplog, f"model {_UNDERSTUDY_MODEL} ready")


async def test_dead_understudy_with_owner_alert_off_only_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """``owner_alert: false`` гасит и сигнал при старте; строка лога остаётся."""
    bob_bot = _Bot()
    app = _build(
        tmp_path,
        tier0=_Tier0(),
        bob_bot=bob_bot,
        clock=_Clock(),
        llm=_understudy_llm(
            f"http://127.0.0.1:{_dead_port()}/v1", health={"owner_alert": False}
        ),
    )

    with caplog.at_level(logging.INFO):
        async with _running(app):
            pass

    assert bob_bot.owner_dms() == []
    assert _logged(caplog, "understudy: on, NOT ready")


async def test_understudy_off_is_reported_off_without_a_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Дублёр выключен — строка «off» в логе, никаких сообщений и никакой сети."""
    bob_bot = _Bot()
    app = _build(tmp_path, tier0=_Tier0(), bob_bot=bob_bot, clock=_Clock())

    with caplog.at_level(logging.INFO):
        async with _running(app):
            pass

    assert bob_bot.owner_dms() == []
    assert _logged(caplog, "tier0 understudy: off")


# --- настоящие провайдеры: облако 403, дублёр держит -------------------------------


@contextlib.asynccontextmanager
async def _llm_stack() -> AsyncIterator[str]:
    """Loopback-стек: облако Tier-0 отвечает 403, дублёр и Tier-1 отвечают, модель на месте."""

    def completion(text: str) -> web.StreamResponse:
        message = {"role": "assistant", "content": text}
        return web.json_response({"choices": [{"message": message}]})

    async def cloud_refuses(_request: web.Request) -> web.StreamResponse:
        return web.json_response({"error": "forbidden"}, status=403)

    async def understudy_answers(_request: web.Request) -> web.StreamResponse:
        return completion("мысль дублёра")

    async def tier1_answers(_request: web.Request) -> web.StreamResponse:
        return completion("ok")

    async def models(_request: web.Request) -> web.StreamResponse:
        return web.json_response({"object": "list", "data": [{"id": _UNDERSTUDY_MODEL}]})

    server = web.Application()
    server.router.add_post("/cloud/v1/chat/completions", cloud_refuses)
    server.router.add_post("/local/v1/chat/completions", understudy_answers)
    server.router.add_get("/local/v1/models", models)
    server.router.add_post("/tier1/v1/chat/completions", tier1_answers)
    runner = web.AppRunner(server)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0][0], runner.addresses[0][1]
        yield f"http://{host}:{port}"
    finally:
        await runner.cleanup()


async def test_real_wrapper_reports_a_dead_cloud_while_the_understudy_holds(
    tmp_path: Path,
) -> None:
    """Сборка из конфигурации: облако 403, дублёр отвечает — владелец всё равно узнаёт.

    Исход облака докладывает дублёр-обёртка (роутер вызов через неё не считает), так что
    сигнал доходит, только если монитор отдан в ``build_tier_providers``.
    """
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    bob_bot = _Bot()
    async with _llm_stack() as base:
        llm: dict[str, object] = {
            "tier0_base_url": f"{base}/cloud/v1",
            "tier0_model": "qwen-cloud",
            "tier1_base_url": f"{base}/tier1/v1",
            "tier1_model": "qwen-max",
            "timeout_seconds": 5,
            **_understudy_llm(f"{base}/local/v1"),
        }
        app = build_application(
            config=_config(tmp_path, llm=llm),
            bob_bot=cast("BotLike", bob_bot),
            guppi_bot=cast("BotLike", _Bot()),
            clock=_Clock(),
        )
        async with _running(app):
            bob_bot.sends.clear()
            await _think(app, _THRESHOLD)

    dms = bob_bot.owner_dms()
    assert len(dms) == 1
    assert "дублёр" in dms[0]


# --- дублёр не готов при старте: Боб стартует БЕЗ него (BOB-116 D11, bob-i83.15) ------
# Дублёр включён в конфигурации, Ollama отвечает, но модели нет. До D11 сборка лишь
# предупреждала владельца, а обёртка оставалась: простой облака монитор читал как «держусь на
# дублёре», хотя думать было нечем. Теперь проверка при старте снимает дублёр до перезапуска:
# Tier-0 — одно облако, монитор знает, что дублёра нет, /status называет причину.


@dataclass
class _StackCalls:
    cloud: int = 0
    understudy_chat: int = 0


@contextlib.asynccontextmanager
async def _stack_without_the_model() -> AsyncIterator[tuple[str, _StackCalls]]:
    """Облако 403; Ollama дублёра жив и отвечает на чат, но модели в списке нет."""
    calls = _StackCalls()

    def completion(text: str) -> web.StreamResponse:
        message = {"role": "assistant", "content": text}
        return web.json_response({"choices": [{"message": message}]})

    async def cloud_refuses(_request: web.Request) -> web.StreamResponse:
        calls.cloud += 1
        return web.json_response({"error": "forbidden"}, status=403)

    async def understudy_answers(_request: web.Request) -> web.StreamResponse:
        calls.understudy_chat += 1
        return completion("мысль дублёра")

    async def models_without_ours(_request: web.Request) -> web.StreamResponse:
        return web.json_response({"object": "list", "data": [{"id": "llama3:8b"}]})

    async def tier1_answers(_request: web.Request) -> web.StreamResponse:
        return completion("ok")

    server = web.Application()
    server.router.add_post("/cloud/v1/chat/completions", cloud_refuses)
    server.router.add_post("/local/v1/chat/completions", understudy_answers)
    server.router.add_get("/local/v1/models", models_without_ours)
    server.router.add_post("/tier1/v1/chat/completions", tier1_answers)
    runner = web.AppRunner(server)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0][0], runner.addresses[0][1]
        yield f"http://{host}:{port}", calls
    finally:
        await runner.cleanup()


async def _guppi_status(app: Application, guppi_bot: _Bot) -> str:
    status = _Update(
        update_id=1,
        message=_Message(message_id=7, text="/status"),
        effective_chat=_Chat(id=_CHAT_ID),
        effective_user=_User(id=_OWNER_ID),
    )
    await app.multibot.route(cast("UpdateLike", status), BotIdentity.GUPPI)
    return guppi_bot.sends[-1][1]


async def test_understudy_without_its_model_is_stood_down_at_startup(tmp_path: Path) -> None:
    """Модели дублёра нет → старт без дублёра: облако одно, «думать нечем», /status с причиной."""
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    bob_bot, guppi_bot = _Bot(), _Bot()
    async with _stack_without_the_model() as (base, calls):
        llm: dict[str, object] = {
            "tier0_base_url": f"{base}/cloud/v1",
            "tier0_model": "qwen-cloud",
            "tier1_base_url": f"{base}/tier1/v1",
            "tier1_model": "qwen-max",
            "timeout_seconds": 5,
            **_understudy_llm(f"{base}/local/v1"),
        }
        app = build_application(
            config=_config(tmp_path, llm=llm),
            bob_bot=cast("BotLike", bob_bot),
            guppi_bot=cast("BotLike", guppi_bot),
            clock=_Clock(),
        )
        async with _running(app):
            startup_dms = list(bob_bot.owner_dms())
            bob_bot.sends.clear()
            await _think(app, _THRESHOLD)
            status = await _guppi_status(app, guppi_bot)

    # Старт: ровно одно сообщение владельцу — без дублёра и до перезапуска.
    assert len(startup_dms) == 1
    assert "стартовал без дублёра" in startup_dms[0]
    assert f"модели {_UNDERSTUDY_MODEL} нет" in startup_dms[0]
    assert "до перезапуска" in startup_dms[0]
    # Дублёр не собран: к его чату никто не ходит, облако зовут напрямую.
    assert calls.understudy_chat == 0
    assert calls.cloud >= _THRESHOLD
    # Монитор знает, что дублёра нет: облако легло — думать нечем, а не «держусь на дублёре».
    dms = bob_bot.owner_dms()
    assert len(dms) == 1
    assert "не могу думать" in dms[0]
    assert "Дублёра на этой машине нет" in dms[0]
    assert "держусь на дублёре" not in dms[0]
    # /status называет причину и границу «до перезапуска».
    assert (
        f"дублёр — выключен при старте: модели {_UNDERSTUDY_MODEL} нет на "
        f"{base}/local/v1 (нужен ollama pull {_UNDERSTUDY_MODEL}) (до перезапуска)"
    ) in status


async def test_dead_understudy_at_startup_shows_in_status_with_the_reason(
    tmp_path: Path,
) -> None:
    """Мёртвый эндпоинт дублёра: /status говорит «выключен при старте», а не «нет»."""
    bob_bot, guppi_bot = _Bot(), _Bot()
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")
    url = f"http://127.0.0.1:{_dead_port()}/v1"
    app = build_application(
        config=_config(tmp_path, llm=_understudy_llm(url)),
        providers={0: _Tier0(), 1: _Tier1()},
        bob_bot=cast("BotLike", bob_bot),
        guppi_bot=cast("BotLike", guppi_bot),
        clock=_Clock(),
    )
    async with _running(app):
        status = await _guppi_status(app, guppi_bot)

    assert f"дублёр — выключен при старте: {url} не отвечает" in status
    assert status.rstrip().endswith("tier1 — ок")


# --- report_understudy и снятие дублёра: кто и когда зовёт stand_down ----------------


class _OwnerSink:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def notify_owner(self, text: str) -> None:
        self.texts.append(text)


async def test_not_ready_understudy_is_stood_down_once_with_the_reason() -> None:
    url = f"http://127.0.0.1:{_dead_port()}/v1"
    reasons: list[str] = []
    sink = _OwnerSink()

    await report_understudy(
        {"llm": _understudy_llm(url)}, sink=sink, stand_down=reasons.append
    )

    assert len(reasons) == 1
    assert reasons[0].startswith(f"{url} не отвечает")
    assert len(sink.texts) == 1
    assert reasons[0] in sink.texts[0]


async def test_ready_or_absent_understudy_is_not_stood_down() -> None:
    reasons: list[str] = []
    async with _models_server([_UNDERSTUDY_MODEL]) as base_url:
        await report_understudy(
            {"llm": _understudy_llm(base_url)}, sink=_OwnerSink(), stand_down=reasons.append
        )
    await report_understudy({"llm": {}}, sink=_OwnerSink(), stand_down=reasons.append)

    assert reasons == []


async def test_a_failing_stand_down_does_not_stop_the_boot_or_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(_reason: str) -> None:
        raise RuntimeError("boom")

    sink = _OwnerSink()
    url = f"http://127.0.0.1:{_dead_port()}/v1"
    with caplog.at_level(logging.INFO):
        check = await report_understudy(
            {"llm": _understudy_llm(url)}, sink=sink, stand_down=broken
        )

    assert check is not None
    assert not check.ready
    assert len(sink.texts) == 1
    assert _logged(caplog, "снять дублёр Tier-0 не вышло")
