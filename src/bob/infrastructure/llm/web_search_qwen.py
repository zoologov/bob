# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""QwenWebSearchProvider — web search over the Qwen MaaS **Responses API**.

Realises :class:`bob.domain.ports.WebSearchProvider` against the Qwen MaaS
``/responses`` endpoint — NOT ``/chat/completions``. Verify .1 (BOB-053) proved
this is the only path that returns clickable sources on the workspace ``sk`` key:
chat/completions and legacy-native text-generation return a grounded answer but no
``search_info``. The same workspace host + key as the Tier-1 provider is reused
(no separate / global DashScope key needed); the factory injects both from config.

Request: ``POST {base}/responses`` with ``{model, input: <query>, tools:[{type:
web_search}]}``. Response: a top-level ``output`` LIST of items —

* ``type == "web_search_call"`` -> ``action.sources[*]`` (``{type:"url", url, title?}``)
  -> :class:`WebSource` (sources are collected across ALL search-call items, deduped
  by url, order preserved);
* ``type == "message"`` -> ``content[*]`` output_text pieces joined into the answer.

Other item types (``reasoning`` …) are ignored. Any failure — a network error, a
non-200, or a malformed/absent expected field — RAISES (the caller owns
fault-tolerance; Bob never confabulates). An empty sources list is allowed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import aiohttp

from bob.domain.ports import WebSearchResult, WebSource

_RESPONSES_PATH = "responses"
_WEB_SEARCH_CALL = "web_search_call"
_MESSAGE = "message"
_OUTPUT_TEXT = "output_text"

# Generous default — a Responses-API web search is slow (several seconds), mirroring
# the Tier-1 reasoning-model timeout so a slow search does not spuriously time out.
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
        """Search the web for ``query`` over the Responses API (raises on failure)."""
        payload: dict[str, object] = {
            "model": self._model,
            "input": query,
            "tools": [{"type": "web_search"}],
        }
        body = await self._post_json(payload)
        return _parse_responses_body(body)

    async def _post_json(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.post(
                self._endpoint(), json=payload, headers=self._headers()
            ) as response,
        ):
            response.raise_for_status()
            body = await response.json()
        if not isinstance(body, Mapping):
            raise ValueError("web search response is not a JSON object")
        return body

    def _endpoint(self) -> str:
        return f"{self._base_url}/{_RESPONSES_PATH}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


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
