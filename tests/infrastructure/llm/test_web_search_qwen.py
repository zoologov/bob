# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for QwenWebSearchProvider against an in-process aiohttp server (BOB-053 .1).

No real network: the test server binds to loopback and emulates the Qwen MaaS
**Responses API** (``/responses``) — the path verify .1 proved returns clickable
sources on the workspace key. This exercises the real aiohttp request/response
path and the ``output[]`` parser (web_search_call sources + message output_text).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import aiohttp
import pytest
from aiohttp import web

from bob.domain.ports import WebSearchProvider, WebSource
from bob.infrastructure.llm.web_search_qwen import QwenWebSearchProvider

_RESPONSES_PATH = "/v1/responses"

# An aiohttp request handler returning a buffered JSON response.
type _Handler = Callable[[web.Request], Awaitable[web.Response]]


async def _start_server(handler: _Handler) -> tuple[str, web.AppRunner]:
    """Start a loopback aiohttp server for ``handler`` and return (base_url, runner)."""
    app = web.Application()
    app.router.add_post(_RESPONSES_PATH, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][0], runner.addresses[0][1]
    return f"http://{host}:{port}/v1", runner


@pytest.fixture
def captured() -> dict[str, object]:
    return {}


def _realistic_body() -> dict[str, object]:
    """A realistic multi-item Responses-API body: reasoning + two search calls + message."""
    return {
        "output": [
            {"type": "reasoning", "content": "thinking about the query"},
            {
                "type": "web_search_call",
                "action": {
                    "sources": [
                        {"type": "url", "url": "https://a.example/news", "title": "A News"},
                        {"type": "url", "url": "https://b.example/post"},
                    ]
                },
            },
            {
                "type": "web_search_call",
                "action": {
                    "sources": [
                        # Duplicate of the first call's url — must be deduped.
                        {"type": "url", "url": "https://a.example/news", "title": "A News"},
                        {"type": "url", "url": "https://c.example/page", "title": "C Page"},
                    ]
                },
            },
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Свежий обоснованный ответ."}
                ],
            },
        ]
    }


async def test_search_parses_payload_collects_and_dedups_sources(
    captured: dict[str, object],
) -> None:
    # Arrange: a server returning a realistic Responses-API body.
    async def handler(request: web.Request) -> web.Response:
        captured["payload"] = await request.json()
        captured["auth"] = request.headers.get("Authorization")
        return web.json_response(_realistic_body())

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(
            base_url=base_url, model="qwen3.7-plus", api_key="sk-secret"
        )

        # Act
        result = await provider.search("что нового")

        # Assert: answer extracted, sources collected from all calls, deduped, ordered.
        assert result.answer == "Свежий обоснованный ответ."
        assert result.sources == (
            WebSource(title="A News", url="https://a.example/news"),
            WebSource(title="", url="https://b.example/post"),
            WebSource(title="C Page", url="https://c.example/page"),
        )
        # Request shape: Responses API body + bearer auth + /responses endpoint.
        assert captured["payload"] == {
            "model": "qwen3.7-plus",
            "input": "что нового",
            "tools": [{"type": "web_search"}],
        }
        assert captured["auth"] == "Bearer sk-secret"
    finally:
        await runner.cleanup()


async def test_search_allows_empty_sources(captured: dict[str, object]) -> None:
    # Arrange: a grounded answer with NO sources is valid (not an error).
    async def handler(request: web.Request) -> web.Response:
        body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Ничего не нашёл."}],
                }
            ]
        }
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert
        assert result.answer == "Ничего не нашёл."
        assert result.sources == ()
    finally:
        await runner.cleanup()


async def test_search_joins_multiple_output_text_pieces() -> None:
    # Arrange: a message split into several output_text pieces.
    async def handler(request: web.Request) -> web.Response:
        body = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Часть один. "},
                        {"type": "refusal", "text": "ignore me"},
                        {"type": "output_text", "text": "Часть два."},
                    ],
                }
            ]
        }
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert: only output_text pieces are joined.
        assert result.answer == "Часть один. Часть два."
    finally:
        await runner.cleanup()


async def test_search_raises_on_non_200() -> None:
    # Arrange: the endpoint errors — must NOT be swallowed (caller handles faults).
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "boom"}, status=500)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(aiohttp.ClientResponseError):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_when_output_missing() -> None:
    # Arrange: a malformed body with no ``output`` list — raise, never confabulate.
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"id": "resp_1"})

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="output"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_when_no_message_item() -> None:
    # Arrange: a body with only a search call and no message — no answer is malformed.
    async def handler(request: web.Request) -> web.Response:
        body = {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {"sources": [{"type": "url", "url": "https://a.example"}]},
                }
            ]
        }
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="message"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_when_body_is_not_json_object() -> None:
    # Arrange: a 200 whose JSON top level is a LIST, not an object — malformed,
    # must raise (the parser commits to a JSON object), never silently degrade.
    async def handler(request: web.Request) -> web.Response:
        return web.json_response([{"type": "message"}])

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="JSON object"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_ignores_malformed_search_call_items() -> None:
    # Arrange: web_search_call items with a non-Mapping action, a non-list
    # ``sources``, and a non-Mapping raw source are all skipped gracefully — the
    # grounded answer is still returned (sources just come out empty), never a raise.
    async def handler(request: web.Request) -> web.Response:
        body = {
            "output": [
                {"type": "web_search_call", "action": "not-a-mapping"},
                {"type": "web_search_call", "action": {"sources": "not-a-list"}},
                {"type": "web_search_call", "action": {"sources": ["not-a-mapping"]}},
                {"type": "web_search_call"},  # no action key at all
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Ответ есть."}],
                },
            ]
        }
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert: malformed search calls ignored, answer survives, sources empty.
        assert result.answer == "Ответ есть."
        assert result.sources == ()
    finally:
        await runner.cleanup()


async def test_search_skips_sources_with_missing_or_blank_url() -> None:
    # Arrange: only sources with a non-empty string url survive; a missing/blank/
    # non-string url is dropped, and a non-string title degrades to "".
    async def handler(request: web.Request) -> web.Response:
        body = {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {"type": "url"},  # no url -> dropped
                            {"type": "url", "url": ""},  # blank url -> dropped
                            {"type": "url", "url": 42},  # non-string url -> dropped
                            {"type": "url", "url": "https://ok.example", "title": 7},
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                },
            ]
        }
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert: one valid source kept; non-string title coerced to "".
        assert result.sources == (WebSource(title="", url="https://ok.example"),)
    finally:
        await runner.cleanup()


async def test_search_message_with_non_list_content_yields_empty_answer() -> None:
    # Arrange: a message item whose ``content`` is not a list — the message exists
    # (so it is NOT the missing-message error) but contributes no text: answer "".
    async def handler(request: web.Request) -> web.Response:
        body = {"output": [{"type": "message", "content": "oops-not-a-list"}]}
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert: no raise (a message item was present), empty answer + sources.
        assert result.answer == ""
        assert result.sources == ()
    finally:
        await runner.cleanup()


async def test_search_joins_text_across_multiple_message_items() -> None:
    # Arrange: the answer text may be split across SEVERAL message items, not one.
    async def handler(request: web.Request) -> web.Response:
        body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Первый. "}],
                },
                {"type": "foo", "content": [{"type": "output_text", "text": "ignored"}]},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Второй."}],
                },
            ]
        }
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert: both message items joined; the unknown ``foo`` item is ignored.
        assert result.answer == "Первый. Второй."
    finally:
        await runner.cleanup()


async def test_provider_satisfies_web_search_provider_protocol() -> None:
    provider = QwenWebSearchProvider(base_url="http://x/v1", model="m", api_key="k")
    assert isinstance(provider, WebSearchProvider)


async def test_timeout_is_configurable() -> None:
    provider = QwenWebSearchProvider(
        base_url="http://x/v1", model="m", api_key="k", timeout_seconds=180.0
    )
    assert provider._timeout.total == 180.0


async def test_no_api_key_omits_authorization_header(captured: dict[str, object]) -> None:
    # Arrange: with no key, no Authorization header is sent (mirrors openai_compat).
    async def handler(request: web.Request) -> web.Response:
        captured["auth"] = request.headers.get("Authorization")
        body = {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}
            ]
        }
        return web.json_response(body)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key=None)

        # Act
        await provider.search("q")

        # Assert
        assert captured["auth"] is None
    finally:
        await runner.cleanup()
