# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=infrastructure

"""QwenWebSearchProvider — web search over the Qwen MaaS **Responses API** (streamed).

Realises :class:`bob.domain.ports.WebSearchProvider` against the Qwen MaaS
``/responses`` endpoint — NOT ``/chat/completions``. Verify .1 (BOB-053) proved
this is the only path that returns clickable sources on the workspace ``sk`` key:
chat/completions and legacy-native text-generation return a grounded answer but no
``search_info``. The same workspace host + key as the Tier-1 provider is reused
(no separate / global DashScope key needed); the factory injects both from config.

The call is **streamed** (``stream: true``): a single buffered POST is dropped by the
gateway after ~30s of idle, but a live web search takes 1-2 min. Streaming keeps the
connection alive with a continuous flow of SSE events and survives 90-120s (BOB-055
diagnosis). We read the Server-Sent-Events line by line and accumulate until the
terminal ``response.completed`` event, whose ``response`` object carries the SAME
final ``output`` list a non-streamed body would — then reuse the ``output[]`` parser.

Request: ``POST {base}/responses`` with ``{model, input: <query>, tools:[{type:
web_search}], stream: true}`` and ``Accept: text/event-stream``. The terminal
``response.completed`` event's ``response.output`` is a LIST of items —

* ``type == "web_search_call"`` -> ``action.sources[*]`` (``{type:"url", url, title?}``)
  -> :class:`WebSource` (sources are collected across ALL search-call items, deduped
  by url, order preserved);
* ``type == "message"`` -> ``content[*]`` output_text pieces joined into the answer.

Intermediate events (deltas, reasoning, ``web_search_call`` progress, unknown types)
are ignored. Any failure — a network error, a non-200, a stream that ends WITHOUT a
``response.completed``, a malformed/undecodable event, an explicit ``response.failed``,
or a malformed/absent expected field — RAISES (the caller owns fault-tolerance; Bob
never confabulates). An empty sources list is allowed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import aiohttp

from bob.domain.ports import WebSearchResult, WebSource

_RESPONSES_PATH = "responses"
_WEB_SEARCH_CALL = "web_search_call"
_MESSAGE = "message"
_OUTPUT_TEXT = "output_text"

# SSE framing + Responses-API stream event vocabulary.
_SSE_DATA_PREFIX = "data:"
_SSE_DONE_SENTINEL = "[DONE]"
_COMPLETED_EVENT = "response.completed"
_FAILURE_EVENTS = frozenset({"response.failed", "response.error", "error"})

# Generous total timeout — a streamed web search runs 1-2 min. A *total* budget (not a
# per-read one) must not kill a slow-but-alive stream; streaming is what dodges the
# ~30s idle gateway cutoff, this ceiling only bounds a genuinely stuck call.
_DEFAULT_TIMEOUT_SECONDS = 180.0


class QwenWebSearchProvider:
    """Qwen-native web search over the MaaS Responses API (realises WebSearchProvider).

    One instance targets one ``base_url`` (the ``/compatible-mode/v1`` workspace base)
    + ``model``; build via :func:`bob.infrastructure.llm.factory.build_web_search_provider`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def search(self, query: str) -> WebSearchResult:
        """Search the web for ``query`` over the streamed Responses API (raises on failure)."""
        payload: dict[str, object] = {
            "model": self._model,
            "input": query,
            "tools": [{"type": "web_search"}],
            "stream": True,
        }
        final_response = await self._stream_final_response(payload)
        return _parse_responses_body(final_response)

    async def _stream_final_response(
        self, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Read the SSE stream and return the ``response.completed`` response object.

        Raises when the stream ends without a terminal event, an event is malformed,
        or the server reports an explicit failure.
        """
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.post(
                self._endpoint(), json=payload, headers=self._headers()
            ) as response,
        ):
            response.raise_for_status()
            async for raw_line in response.content:
                event = _decode_sse_line(raw_line)
                if event is None:
                    continue
                final = _terminal_response(event)
                if final is not None:
                    return final
        raise ValueError("web search stream ended without a 'response.completed' event")

    def _endpoint(self) -> str:
        return f"{self._base_url}/{_RESPONSES_PATH}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


def _decode_sse_line(raw_line: bytes) -> Mapping[str, object] | None:
    """Decode one SSE line into an event mapping, or None for a non-data / blank line.

    Raises when a ``data:`` payload is present but not a decodable JSON object.
    """
    line = raw_line.decode("utf-8", "replace").strip()
    if not line.startswith(_SSE_DATA_PREFIX):
        return None
    data = line[len(_SSE_DATA_PREFIX) :].strip()
    if not data or data == _SSE_DONE_SENTINEL:
        return None
    try:
        event = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed SSE event in web search stream") from exc
    if not isinstance(event, Mapping):
        raise ValueError("SSE event is not a JSON object")
    return event


def _terminal_response(event: Mapping[str, object]) -> Mapping[str, object] | None:
    """Return the final ``response`` object for a completed event, else None.

    Raises on an explicit failure event or a completed event without a response object.
    """
    event_type = event.get("type")
    if event_type in _FAILURE_EVENTS:
        raise ValueError(f"web search stream reported failure: {event_type!r}")
    if event_type != _COMPLETED_EVENT:
        return None
    response_obj = event.get("response")
    if not isinstance(response_obj, Mapping):
        raise ValueError("'response.completed' event has no 'response' object")
    return response_obj


def _parse_responses_body(body: Mapping[str, object]) -> WebSearchResult:
    """Parse a Responses-API body into a :class:`WebSearchResult` (raises if malformed)."""
    output = body.get("output")
    if not isinstance(output, list):
        raise ValueError("web search response has no 'output' list")
    sources = _collect_sources(output)
    answer = _collect_answer(output)
    return WebSearchResult(answer=answer, sources=sources)


def _collect_sources(output: Sequence[object]) -> tuple[WebSource, ...]:
    """Collect WebSources across all web_search_call items, deduped by url, order kept."""
    seen: set[str] = set()
    sources: list[WebSource] = []
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != _WEB_SEARCH_CALL:
            continue
        action = item.get("action")
        if not isinstance(action, Mapping):
            continue
        raw_sources = action.get("sources")
        if not isinstance(raw_sources, list):
            continue
        for raw in raw_sources:
            if not isinstance(raw, Mapping):
                continue
            url = raw.get("url")
            if not isinstance(url, str) or not url or url in seen:
                continue
            seen.add(url)
            title = raw.get("title")
            sources.append(WebSource(title=title if isinstance(title, str) else "", url=url))
    return tuple(sources)


def _collect_answer(output: Sequence[object]) -> str:
    """Join the output_text pieces of the message item(s) (raises when none present)."""
    parts: list[str] = []
    found_message = False
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != _MESSAGE:
            continue
        found_message = True
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for piece in content:
            if not isinstance(piece, Mapping) or piece.get("type") != _OUTPUT_TEXT:
                continue
            text = piece.get("text")
            if isinstance(text, str):
                parts.append(text)
    if not found_message:
        raise ValueError("web search response has no 'message' item")
    return "".join(parts)
