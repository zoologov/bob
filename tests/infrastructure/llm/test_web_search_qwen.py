# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for QwenWebSearchProvider against an in-process aiohttp server (BOB-055 .1).

No real network: the test server binds to loopback and emulates the Qwen MaaS
**Responses API** (``/responses``) in **streaming** mode — it writes a sequence of
Server-Sent-Events (``data: <json>`` lines) ending in a terminal
``response.completed`` event that carries the full final ``response`` object. This
exercises the real aiohttp streamed request/response path (which survives the ~30s
idle gateway cutoff, unlike a single buffered POST) and the ``output[]`` parser
(web_search_call sources + message output_text), reused unchanged from the
non-streaming implementation.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping

import aiohttp
import pytest
from aiohttp import web

from bob.capabilities.adapters.web_search_qwen import QwenWebSearchProvider
from bob.domain.ports import WebSearchProvider, WebSource

_RESPONSES_PATH = "/v1/responses"

# An aiohttp request handler returning a (streamed) response.
type _Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


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


def _sse(event: object) -> bytes:
    """Encode one object as an SSE ``data:`` line (blank line terminated)."""
    return f"data: {json.dumps(event)}\n\n".encode()


def _completed(body: Mapping[str, object]) -> dict[str, object]:
    """Wrap a final response object into a terminal ``response.completed`` event."""
    return {"type": "response.completed", "response": body}


def _sse_handler(
    chunks: list[bytes], *, captured: dict[str, object] | None = None
) -> _Handler:
    """Build a handler that streams ``chunks`` as ``text/event-stream`` (200 OK)."""

    async def handler(request: web.Request) -> web.StreamResponse:
        if captured is not None:
            captured["payload"] = await request.json()
            captured["auth"] = request.headers.get("Authorization")
            captured["accept"] = request.headers.get("Accept")
        resp = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await resp.prepare(request)
        for chunk in chunks:
            await resp.write(chunk)
        await resp.write_eof()
        return resp

    return handler


@pytest.fixture
def captured() -> dict[str, object]:
    return {}


def _realistic_output() -> list[dict[str, object]]:
    """A realistic multi-item output: two search calls (with a dup) + a message."""
    return [
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
            "content": [{"type": "output_text", "text": "Свежий обоснованный ответ."}],
        },
    ]


async def test_search_streams_parses_and_dedups_sources(
    captured: dict[str, object],
) -> None:
    # Arrange: a realistic stream — delta/unknown events first, then the terminal
    # response.completed carrying the full final response object.
    chunks = [
        _sse({"type": "response.created", "response": {"id": "resp_1"}}),
        _sse({"type": "response.web_search_call.in_progress"}),
        _sse({"type": "response.output_text.delta", "delta": "Све"}),
        _sse(_completed({"output": _realistic_output()})),
    ]
    handler = _sse_handler(chunks, captured=captured)

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
        # Request shape: streaming body + event-stream Accept + bearer auth.
        assert captured["payload"] == {
            "model": "qwen3.7-plus",
            "input": "что нового",
            "tools": [{"type": "web_search"}],
            "stream": True,
        }
        assert captured["accept"] == "text/event-stream"
        assert captured["auth"] == "Bearer sk-secret"
    finally:
        await runner.cleanup()


async def test_search_allows_empty_sources() -> None:
    # Arrange: a grounded answer with NO sources is valid (not an error).
    body = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Ничего не нашёл."}]}
        ]
    }
    handler = _sse_handler([_sse(_completed(body))])

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
    # Arrange: a message split into several output_text pieces in the final event.
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
    handler = _sse_handler([_sse(_completed(body))])

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert: only output_text pieces are joined.
        assert result.answer == "Часть один. Часть два."
    finally:
        await runner.cleanup()


async def test_search_ignores_delta_and_unknown_events() -> None:
    # Arrange: many intermediate deltas / unknown types precede the terminal event
    # and must all be ignored — only response.completed's output is parsed.
    chunks = [
        _sse({"type": "response.created"}),
        _sse({"type": "response.in_progress"}),
        _sse({"type": "response.output_item.added", "item": {"type": "reasoning"}}),
        _sse({"type": "response.output_text.delta", "delta": "иг"}),
        _sse({"type": "some.future.unknown.event", "payload": 123}),
        _sse(
            _completed(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Готово."}],
                        }
                    ]
                }
            )
        ),
    ]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert
        assert result.answer == "Готово."
    finally:
        await runner.cleanup()


async def test_search_raises_on_non_200() -> None:
    # Arrange: the endpoint errors — must NOT be swallowed (caller handles faults).
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.json_response({"error": "boom"}, status=500)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(aiohttp.ClientResponseError):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_when_stream_has_no_completed_event() -> None:
    # Arrange: a stream of only delta events, never a response.completed — the
    # connection stayed alive but produced no final aggregate: raise, never confabulate.
    chunks = [
        _sse({"type": "response.created"}),
        _sse({"type": "response.output_text.delta", "delta": "x"}),
        _sse({"type": "response.output_text.delta", "delta": "y"}),
    ]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match=r"response\.completed"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_on_malformed_terminal_event() -> None:
    # Arrange: the terminal data line is not decodable JSON — a corrupt stream must
    # raise (honest-notice contract), never silently degrade.
    chunks = [
        _sse({"type": "response.created"}),
        b"data: {this is not valid json\n\n",
    ]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="malformed"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_on_explicit_failure_event() -> None:
    # Arrange: the server streams an explicit response.failed event — raise.
    chunks = [
        _sse({"type": "response.created"}),
        _sse({"type": "response.failed", "response": {"error": {"message": "quota"}}}),
    ]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="fail"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_when_completed_response_not_object() -> None:
    # Arrange: response.completed whose ``response`` is not a JSON object — malformed.
    chunks = [_sse({"type": "response.completed", "response": ["not", "an", "object"]})]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="response"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_when_output_missing() -> None:
    # Arrange: a terminal event whose response has no ``output`` list — raise.
    chunks = [_sse(_completed({"id": "resp_1"}))]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="output"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_raises_when_no_message_item() -> None:
    # Arrange: only a search call and no message — no answer is malformed.
    body = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"sources": [{"type": "url", "url": "https://a.example"}]},
            }
        ]
    }
    handler = _sse_handler([_sse(_completed(body))])

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="message"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_ignores_malformed_search_call_items() -> None:
    # Arrange: web_search_call items with a non-Mapping action, a non-list
    # ``sources``, and a non-Mapping raw source are all skipped gracefully — the
    # grounded answer is still returned (sources just come out empty), never a raise.
    body = {
        "output": [
            {"type": "web_search_call", "action": "not-a-mapping"},
            {"type": "web_search_call", "action": {"sources": "not-a-list"}},
            {"type": "web_search_call", "action": {"sources": ["not-a-mapping"]}},
            {"type": "web_search_call"},  # no action key at all
            {"type": "message", "content": [{"type": "output_text", "text": "Ответ есть."}]},
        ]
    }
    handler = _sse_handler([_sse(_completed(body))])

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
            {"type": "message", "content": [{"type": "output_text", "text": "ok"}]},
        ]
    }
    handler = _sse_handler([_sse(_completed(body))])

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
    body = {"output": [{"type": "message", "content": "oops-not-a-list"}]}
    handler = _sse_handler([_sse(_completed(body))])

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
    body = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Первый. "}]},
            {"type": "foo", "content": [{"type": "output_text", "text": "ignored"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "Второй."}]},
        ]
    }
    handler = _sse_handler([_sse(_completed(body))])

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert: both message items joined; the unknown ``foo`` item is ignored.
        assert result.answer == "Первый. Второй."
    finally:
        await runner.cleanup()


async def test_search_parses_data_line_without_space_after_colon() -> None:
    # Arrange: SSE spec allows ``data:<payload>`` with NO space after the colon.
    # The decoder strips the value, so a space-less terminal must still parse (BOB-055
    # framing robustness — real gateways vary the framing).
    body = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Готово."}]}]
    }
    raw = f"data:{json.dumps(_completed(body))}\n\n".encode()  # no space after colon
    handler = _sse_handler([raw])

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert
        assert result.answer == "Готово."
    finally:
        await runner.cleanup()


async def test_search_ignores_comment_blank_empty_and_done_lines_before_terminal() -> None:
    # Arrange: a realistic keep-alive-laden stream — SSE comment lines (``:``), bare
    # blank lines, an empty ``data:`` line and a ``[DONE]`` sentinel must ALL be
    # skipped without derailing the parse; the terminal ``response.completed`` that
    # follows is still read (framing quirks are non-fatal, only the aggregate matters).
    body = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Финал."}]}]
    }
    chunks = [
        b": keep-alive\n\n",  # SSE comment line -> ignored
        b"\n",  # bare blank separator -> ignored
        b"data:\n\n",  # empty data payload -> ignored
        b"data: [DONE]\n\n",  # sentinel -> ignored, NOT treated as terminal
        _sse({"type": "response.output_text.delta", "delta": "Фи"}),
        _sse(_completed(body)),
    ]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act
        result = await provider.search("q")

        # Assert
        assert result.answer == "Финал."
    finally:
        await runner.cleanup()


async def test_search_raises_when_terminal_data_is_valid_json_but_not_object() -> None:
    # Arrange: a ``data:`` line that decodes to valid JSON which is NOT an object
    # (a bare array) — decodable but structurally wrong, so it must raise (not be
    # mistaken for an event), distinct from the undecodable-JSON path.
    handler = _sse_handler([b"data: [1, 2, 3]\n\n"])

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="JSON object"):
            await provider.search("q")
    finally:
        await runner.cleanup()


async def test_search_reasoning_only_completed_raises_no_message() -> None:
    # Arrange: a terminal ``response.completed`` whose output carries ONLY reasoning
    # (no message, no search call). Lock the current parser contract: no message item
    # -> raise (honest notice upstream), NEVER an empty answer passed off as found.
    body = {"output": [{"type": "reasoning", "content": "just thinking, no answer"}]}
    handler = _sse_handler([_sse(_completed(body))])

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="message"):
            await provider.search("q")
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("failure_type", ["response.error", "error"])
async def test_search_raises_on_failure_event_variants(failure_type: str) -> None:
    # Arrange: besides ``response.failed`` (tested above), the terminal failure
    # vocabulary also covers ``response.error`` and a bare ``error`` event — each is
    # an explicit server-side failure that must raise, never silently degrade.
    chunks = [
        _sse({"type": "response.created"}),
        _sse({"type": failure_type, "response": {"error": {"message": "boom"}}}),
    ]
    handler = _sse_handler(chunks)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")

        # Act / Assert
        with pytest.raises(ValueError, match="failure"):
            await provider.search("q")
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
    body = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}
    handler = _sse_handler([_sse(_completed(body))], captured=captured)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key=None)

        # Act
        await provider.search("q")

        # Assert
        assert captured["auth"] is None
    finally:
        await runner.cleanup()
