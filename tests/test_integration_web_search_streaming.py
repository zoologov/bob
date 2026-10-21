# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Cross-layer integration for BOB-055 (.1 streaming provider + .2 announcer).

These tests wire the REAL pieces together — no mocks of the unit under test:

* the REAL streamed :class:`QwenWebSearchProvider` against a loopback aiohttp server
  (no live network) driven through the REAL ``web_search`` capability, to prove the
  🔴 BOB-053 invariant survives the .1 streaming rewrite: a genuine transport failure
  (a non-200, or a stream that never completes) NEVER confabulates — it surfaces the
  honest "couldn't search" notice with anti-confabulation guidance; and
* the REAL :class:`GatewayProgressAnnouncer` wired into the REAL :class:`ToolLoop`, to
  prove the interim "searching…" line is spoken to the chat BEFORE the slow web_search
  dispatch runs (BOB-055 US-4), using only a recording fake gateway at the boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from aiohttp import web

from bob.capabilities.adapters.web_search_qwen import QwenWebSearchProvider
from bob.capabilities.ports import WebSearchResult, WebSource
from bob.capabilities.usecases.progress_announcer import GatewayProgressAnnouncer
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.capabilities.usecases.web_search import make_web_search_capability
from bob.kernel.ports import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from bob.kernel.ports import ToolDefinition, ToolLoopMessage

_RESPONSES_PATH = "/v1/responses"

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


def _stream_handler(chunks: list[bytes]) -> _Handler:
    """Build a 200 handler that streams ``chunks`` as ``text/event-stream``."""

    async def handler(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await resp.prepare(request)
        for chunk in chunks:
            await resp.write(chunk)
        await resp.write_eof()
        return resp

    return handler


async def test_streaming_provider_500_surfaces_honest_notice_through_capability() -> None:
    # Arrange: the REAL streamed provider hits a 500 from the loopback endpoint,
    # wired through the REAL web_search capability with no retry budget. 🔴 BOB-053:
    # a real transport failure must become the honest "couldn't search" notice —
    # never a fabricated answer — even after the .1 streaming rewrite.
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.json_response({"error": "boom"}, status=500)

    base_url, runner = await _start_server(handler)
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")
        cap = make_web_search_capability(provider, attempts=1)

        # Act
        result = await cap.execute({"query": "свежие новости"})

        # Assert: honest notice — no sources, explicit anti-confabulation guidance.
        assert isinstance(result, Mapping)
        assert result["sources"] == []
        assert "guidance" in result
        assert str(result["guidance"]).strip()
        answer = str(result["answer"]).lower()
        assert "не смог" in answer or "не удалось" in answer
    finally:
        await runner.cleanup()


async def test_streaming_provider_broken_stream_surfaces_honest_notice() -> None:
    # Arrange: the stream stays alive (200) but never emits a terminal
    # ``response.completed`` — the streaming-specific failure the .1 rewrite must
    # still treat as a real failure. 🔴 BOB-053: honest notice, not confabulation.
    chunks = [
        f"data: {json.dumps({'type': 'response.created'})}\n\n".encode(),
        f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': 'x'})}\n\n".encode(),
    ]
    base_url, runner = await _start_server(_stream_handler(chunks))
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")
        cap = make_web_search_capability(provider, attempts=1)

        # Act
        result = await cap.execute({"query": "что нового"})

        # Assert
        assert isinstance(result, Mapping)
        assert result["sources"] == []
        assert "guidance" in result
    finally:
        await runner.cleanup()


async def test_streaming_provider_success_projects_answer_through_capability() -> None:
    # Arrange: the happy path end-to-end — a real streamed completed event carrying a
    # message + a source, projected by the REAL capability into the compact tool-loop
    # shape. Proves the .1 provider and the BOB-053 capability compose unchanged.
    body = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"sources": [{"type": "url", "url": "https://x.example", "title": "X"}]},
            },
            {"type": "message", "content": [{"type": "output_text", "text": "Свежий ответ."}]},
        ]
    }
    completed = {"type": "response.completed", "response": body}
    chunks = [f"data: {json.dumps(completed)}\n\n".encode()]
    base_url, runner = await _start_server(_stream_handler(chunks))
    try:
        provider = QwenWebSearchProvider(base_url=base_url, model="m", api_key="k")
        cap = make_web_search_capability(provider, attempts=1)

        # Act
        result = await cap.execute({"query": "новости"})

        # Assert: grounded answer + source projected; no failure guidance on success.
        assert isinstance(result, Mapping)
        assert result["answer"] == "Свежий ответ."
        assert result["sources"] == [{"title": "X", "url": "https://x.example"}]
        assert "guidance" not in result
    finally:
        await runner.cleanup()


class _RecordingGateway:
    """A reply gateway that logs ordering into a shared list (boundary fake)."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.calls: list[Mapping[str, object]] = []

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,  # noqa: ARG002
        reply_to_message_id: int | None = None,  # noqa: ARG002
    ) -> int | None:
        self._order.append("announce")
        self.calls.append({"chat_id": chat_id, "markdown": markdown})
        return 1


class _OrderingWebSearchProvider:
    """A fake WebSearchProvider that logs when its search runs (ordering probe)."""

    def __init__(self, order: list[str]) -> None:
        self._order = order

    async def search(self, query: str) -> WebSearchResult:  # noqa: ARG002
        self._order.append("dispatch")
        return WebSearchResult(
            answer="ответ", sources=(WebSource(title="S", url="https://s.example"),)
        )


class _ScriptedToolProvider:
    """Returns a scripted ToolCallResult per turn (the model side of the loop)."""

    def __init__(self, results: Sequence[ToolCallResult]) -> None:
        self._results = list(results)
        self._call = 0

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],  # noqa: ARG002
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        index = min(self._call, len(self._results) - 1)
        self._call += 1
        return self._results[index]


class _LiveInterimGenerator:
    """A live interim-line generator (BOB-060): echoes the topic into a Bob-voice line."""

    async def generate(self, *, topic: str, sender_name: str) -> str:  # noqa: ARG002
        return f"секунду, гляну «{topic}» 🙂"


async def test_real_announcer_speaks_before_web_search_dispatch_through_tool_loop() -> None:
    # Arrange: the REAL GatewayProgressAnnouncer + REAL ToolLoop + REAL web_search
    # capability. When the model asks for web_search, the LIVE interim line (generated
    # from the query as topic) must be sent to the turn's chat BEFORE the (slow) provider
    # search runs — the whole BOB-060 wiring, end-to-end, recording gateway at the boundary.
    order: list[str] = []
    gateway = _RecordingGateway(order)
    provider = _OrderingWebSearchProvider(order)
    registry = CapabilityRegistry()
    registry.register(make_web_search_capability(provider, attempts=1))
    announcer = GatewayProgressAnnouncer(
        chat_id=777,
        gateway=gateway,
        line_generator=_LiveInterimGenerator(),
        sender_name="Лёша",
    )
    call = ToolCall(id="c1", name="web_search", arguments={"query": "что нового"})
    model = _ScriptedToolProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="Вот что нашёл.", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=model, registry=registry, announcer=announcer)

    # Act
    answer = await loop.run([{"role": "user", "content": "что нового?"}])

    # Assert: exactly one LIVE interim line, to the right chat, strictly before dispatch.
    assert order == ["announce", "dispatch"]
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["chat_id"] == 777
    assert gateway.calls[0]["markdown"] == "секунду, гляну «что нового» 🙂"
    assert answer == "Вот что нашёл."
