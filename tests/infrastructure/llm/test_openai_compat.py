# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for OpenAICompatProvider against an in-process aiohttp server.

No real network: the test server binds to loopback and emulates the OpenAI
``/v1/chat/completions`` endpoint in both non-stream (JSON) and stream (SSE)
modes. This exercises the real aiohttp request/response path of the provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable

import aiohttp
import pytest
from aiohttp import web

from bob.domain.ports import LLMProvider
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider

_CHAT_PATH = "/v1/chat/completions"

# An aiohttp request handler returning either a buffered or a streaming response.
type _Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


async def _start_server(handler: _Handler) -> tuple[str, web.AppRunner]:
    """Start a loopback aiohttp server for ``handler`` and return (base_url, runner)."""
    app = web.Application()
    app.router.add_post(_CHAT_PATH, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = runner.addresses
    host, port = sockets[0][0], sockets[0][1]
    return f"http://{host}:{port}/v1", runner


@pytest.fixture
def captured() -> dict[str, object]:
    return {}


async def test_complete_non_stream_returns_full_text(captured: dict[str, object]) -> None:
    # Arrange: a server that echoes a single non-stream completion.
    async def handler(request: web.Request) -> web.Response:
        captured["payload"] = await request.json()
        captured["auth"] = request.headers.get("Authorization")
        body = {"choices": [{"message": {"content": "hello there"}}]}
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = OpenAICompatProvider(base_url=base_url, model="m", api_key="sk-secret")

        # Act
        result = await provider.complete([{"role": "user", "content": "hi"}], stream=False)

        # Assert
        assert result == "hello there"
        assert captured["payload"] == {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        }
        assert captured["auth"] == "Bearer sk-secret"
    finally:
        await runner.cleanup()


async def test_complete_stream_yields_tokens(captured: dict[str, object]) -> None:
    # Arrange: a server that streams SSE chunks then [DONE].
    async def handler(request: web.Request) -> web.StreamResponse:
        captured["payload"] = await request.json()
        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        await response.prepare(request)
        for token in ("Hel", "lo", "!"):
            chunk = {"choices": [{"delta": {"content": token}}]}
            await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    base_url, runner = await _start_server(handler)
    try:
        provider = OpenAICompatProvider(base_url=base_url, model="m", api_key="sk")

        # Act
        result = await provider.complete([{"role": "user", "content": "hi"}], stream=True)
        assert isinstance(result, AsyncIterator)
        tokens = [tok async for tok in result]

        # Assert
        assert tokens == ["Hel", "lo", "!"]
        assert captured["payload"] == {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }
    finally:
        await runner.cleanup()


async def test_provider_satisfies_llm_provider_protocol() -> None:
    provider = OpenAICompatProvider(base_url="http://x/v1", model="m", api_key="k")
    assert isinstance(provider, LLMProvider)


async def test_no_api_key_omits_authorization_header(captured: dict[str, object]) -> None:
    # Arrange: Tier 0 local server needs no auth.
    async def handler(request: web.Request) -> web.Response:
        captured["auth"] = request.headers.get("Authorization")
        return web.json_response({"choices": [{"message": {"content": "ok"}}]})

    base_url, runner = await _start_server(handler)
    try:
        provider = OpenAICompatProvider(base_url=base_url, model="m", api_key=None)

        # Act
        await provider.complete([{"role": "user", "content": "hi"}], stream=False)

        # Assert
        assert captured["auth"] is None
    finally:
        await runner.cleanup()


async def test_http_error_raises() -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "boom"}, status=500)

    base_url, runner = await _start_server(handler)
    try:
        provider = OpenAICompatProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert: aiohttp raises ClientResponseError on raise_for_status().
        with pytest.raises(aiohttp.ClientResponseError):
            await provider.complete([{"role": "user", "content": "hi"}], stream=False)
    finally:
        await runner.cleanup()
