# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""OpenAICompatProvider — OpenAI-compatible chat completions over aiohttp.

Implements :class:`bob.domain.ports.LLMProvider` against any endpoint that
speaks the OpenAI ``/chat/completions`` shape — used for both Tier 0 (a local
mlx-lm server, no auth) and Tier 1 (the Qwen API, bearer-token auth). The same
adapter serves both tiers; flipping local <-> API is a config change, not a
rewrite (see RFC "Ключевые порты").

Two modes:

* non-stream — POST with ``stream=False`` and return the single message content;
* stream — POST with ``stream=True`` and yield delta tokens from the SSE body.

The API key is never inlined: it is supplied by the factory from config/env and,
when absent (Tier 0 local), no ``Authorization`` header is sent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from bob.domain.ports import LLMMessage

logger = logging.getLogger(__name__)

_CHAT_COMPLETIONS_PATH = "chat/completions"
_SSE_DATA_PREFIX = "data:"
_SSE_DONE_SENTINEL = "[DONE]"


class OpenAICompatProvider:
    """OpenAI-compatible completion provider (Tier 0 local / Tier 1 API).

    Realises :class:`bob.domain.ports.LLMProvider`. One instance targets one
    ``base_url`` + ``model``; build via :func:`bob.infrastructure.llm.factory`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat turn; yield delta tokens when ``stream`` is true."""
        payload = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "stream": stream,
        }
        if stream:
            return self._stream_tokens(payload)
        return await self._complete_once(payload)

    async def _complete_once(self, payload: Mapping[str, object]) -> str:
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.post(self._endpoint(), json=payload, headers=self._headers()) as response,
        ):
            response.raise_for_status()
            body = await response.json()
        return _extract_message_content(body)

    async def _stream_tokens(self, payload: Mapping[str, object]) -> AsyncIterator[str]:
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.post(self._endpoint(), json=payload, headers=self._headers()) as response,
        ):
            response.raise_for_status()
            async for raw_line in response.content:
                token = _parse_sse_token(raw_line)
                if token is not None:
                    yield token

    def _endpoint(self) -> str:
        return f"{self._base_url}/{_CHAT_COMPLETIONS_PATH}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


def _extract_message_content(body: Mapping[str, object]) -> str:
    """Pull the assistant message content from a non-stream completion body."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("completion response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("completion choice is not an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("completion choice has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("completion message content is not a string")
    return content


def _parse_sse_token(raw_line: bytes) -> str | None:
    """Extract a delta token from one SSE line, or ``None`` if not a token line."""
    line = raw_line.decode("utf-8").strip()
    if not line or not line.startswith(_SSE_DATA_PREFIX):
        return None
    data = line[len(_SSE_DATA_PREFIX) :].strip()
    if data == _SSE_DONE_SENTINEL:
        return None
    chunk = json.loads(data)
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    delta = choices[0].get("delta")
    if not isinstance(delta, Mapping):
        return None
    content = delta.get("content")
    return content if isinstance(content, str) else None
