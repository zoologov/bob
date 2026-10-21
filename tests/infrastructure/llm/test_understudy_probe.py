# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Проверка дублёра при старте: включён ли, есть ли модель, отвечает ли (BOB-116 D3).

Факт для сигнала «дублёр включён, но модели нет» (сам сигнал шлёт сборка, D10). Эндпоинт —
НАСТОЯЩИЙ loopback-сервер в форме Ollama ``/v1/models``: проверка про транспорт, и фейк
доказал бы только контракт фейка (П.0.3 п.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from aiohttp import web

from bob.infrastructure.llm.factory import UnderstudyEndpoint, understudy_endpoint
from bob.infrastructure.llm.understudy_probe import probe_understudy

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

type _Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _config(**llm: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tier0_base_url": "http://cloud/v1",
        "tier0_model": "cloud",
        "tier1_base_url": "http://tier1/v1",
        "tier1_model": "tier1",
    }
    return {"llm": {**base, **llm}}


@pytest.fixture
async def serve() -> AsyncIterator[Callable[[_Handler], Awaitable[str]]]:
    runners: list[web.AppRunner] = []

    async def _start(handler: _Handler) -> str:
        app = web.Application()
        app.router.add_get("/v1/models", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        host, port = runner.addresses[0][0], runner.addresses[0][1]
        return f"http://{host}:{port}/v1"

    yield _start
    for runner in runners:
        await runner.cleanup()


def _models(*ids: str) -> _Handler:
    async def _handler(_request: web.Request) -> web.StreamResponse:
        return web.json_response({"object": "list", "data": [{"id": i} for i in ids]})

    return _handler


# --- что говорит конфигурация -------------------------------------------------------


def test_endpoint_is_absent_when_the_understudy_is_off() -> None:
    assert understudy_endpoint(_config()) is None
    assert understudy_endpoint(_config(tier0_fallback="")) is None


def test_endpoint_names_the_configured_understudy() -> None:
    config = _config(
        tier0_fallback="Ollama",
        tier0_fallback_base_url="http://127.0.0.1:11434/v1",
        tier0_fallback_model="qwen3:8b",
    )
    assert understudy_endpoint(config) == UnderstudyEndpoint(
        base_url="http://127.0.0.1:11434/v1", model="qwen3:8b"
    )


def test_unknown_backend_is_a_loud_config_error() -> None:
    with pytest.raises(KeyError, match="tier0_fallback"):
        understudy_endpoint(_config(tier0_fallback="llamafile"))


# --- проверка на живом эндпоинте ----------------------------------------------------


async def test_off_understudy_is_reported_as_off() -> None:
    check = await probe_understudy(None)
    assert not check.configured
    assert not check.ready
    assert check.reason is None
    assert check.summary == "tier0 understudy: off"


async def test_model_present_is_ready(serve: Callable[[_Handler], Awaitable[str]]) -> None:
    url = await serve(_models("bge-m3:latest", "qwen3:8b"))
    check = await probe_understudy(UnderstudyEndpoint(base_url=url, model="qwen3:8b"))
    assert check.configured
    assert check.ready
    assert check.reason is None
    assert check.summary == "tier0 understudy: on, model qwen3:8b ready"


async def test_untagged_model_matches_the_latest_tag(
    serve: Callable[[_Handler], Awaitable[str]],
) -> None:
    url = await serve(_models("qwen3:latest"))
    check = await probe_understudy(UnderstudyEndpoint(base_url=url, model="qwen3"))
    assert check.ready


async def test_missing_model_gives_a_human_reason(
    serve: Callable[[_Handler], Awaitable[str]],
) -> None:
    url = await serve(_models("bge-m3:latest"))
    check = await probe_understudy(UnderstudyEndpoint(base_url=url, model="qwen3:8b"))
    assert check.configured
    assert not check.ready
    assert check.reason == f"модели qwen3:8b нет на {url} (нужен ollama pull qwen3:8b)"
    assert check.summary == f"tier0 understudy: on, NOT ready — {check.reason}"


async def test_http_error_gives_a_human_reason(
    serve: Callable[[_Handler], Awaitable[str]],
) -> None:
    async def _broken(_request: web.Request) -> web.StreamResponse:
        return web.json_response({"error": "boom"}, status=500)

    url = await serve(_broken)
    check = await probe_understudy(UnderstudyEndpoint(base_url=url, model="qwen3:8b"))
    assert not check.ready
    assert check.reason == f"{url} ответил 500"


async def test_refused_connection_gives_a_human_reason() -> None:
    runner = web.AppRunner(web.Application())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][0], runner.addresses[0][1]
    await runner.cleanup()  # порт свободен — соединение будет отвергнуто
    url = f"http://{host}:{port}/v1"
    check = await probe_understudy(UnderstudyEndpoint(base_url=url, model="qwen3:8b"))
    assert not check.ready
    assert check.reason is not None
    assert check.reason.startswith(f"{url} не отвечает (")


async def test_broken_body_gives_a_human_reason(
    serve: Callable[[_Handler], Awaitable[str]],
) -> None:
    async def _garbage(_request: web.Request) -> web.StreamResponse:
        return web.Response(text="not json", content_type="text/plain")

    url = await serve(_garbage)
    check = await probe_understudy(UnderstudyEndpoint(base_url=url, model="qwen3:8b"))
    assert not check.ready
    assert check.reason == f"{url} ответил непонятно — это точно Ollama?"
