# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""OpenAICompatProvider — OpenAI-compatible chat completions over aiohttp.

Implements :class:`bob.kernel.ports.LLMProvider` against any endpoint that
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

from bob.capabilities.ports import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from bob.capabilities.ports import ToolDefinition
    from bob.kernel.ports import LLMMessage

logger = logging.getLogger(__name__)

_CHAT_COMPLETIONS_PATH = "chat/completions"
_SSE_DATA_PREFIX = "data:"
_SSE_DONE_SENTINEL = "[DONE]"

# Prompt-protocol fallback: when an endpoint does not support native OpenAI
# tools, we instruct the model to emit a tool-call as a JSON object of this shape
# and parse it tolerantly from the reply text (reasoning-model wrapping tolerated).
_FALLBACK_TOOL_KEY = "tool_call"

# qwen3 "no thinking" directive for OpenAI-compatible endpoints. Both keys are
# sent so the call works whether the upstream reads it from ``extra_body`` (the
# OpenAI-SDK passthrough) or ``chat_template_kwargs`` (the vLLM/dashscope shape).
_NO_THINKING_DIRECTIVE: dict[str, object] = {
    "extra_body": {"enable_thinking": False},
    "chat_template_kwargs": {"enable_thinking": False},
}


class OpenAICompatProvider:
    """OpenAI-compatible completion provider (Tier 0 local / Tier 1 API).

    Realises :class:`bob.kernel.ports.LLMProvider`. One instance targets one
    ``base_url`` + ``model``; build via :func:`bob.infrastructure.llm.factory`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float = 180.0,
        disable_thinking: bool = False,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._disable_thinking = disable_thinking
        # Sampling controls (BOB-022): without an explicit ``temperature`` Qwen MaaS
        # decodes greedily, so an identical prompt yields byte-identical output (the
        # verbatim-repeat bug). A set temperature makes decoding stochastic; ``top_p``
        # is an optional nucleus-sampling companion. Either is sent ONLY when set, so
        # an unconfigured provider keeps the endpoint's own defaults.
        self._temperature = temperature
        self._top_p = top_p

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat turn; yield delta tokens when ``stream`` is true."""
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "stream": stream,
        }
        if self._disable_thinking:
            payload.update(_NO_THINKING_DIRECTIVE)
        self._apply_sampling(payload)
        if stream:
            return self._stream_tokens(payload)
        return await self._complete_once(payload)

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        """Complete a turn that may request tool calls (realises ToolCallingProvider).

        Sends the manifest as native OpenAI ``tools`` and parses the response: a
        native ``tool_calls`` array when the endpoint supports tools, else a
        prompt-protocol JSON tool-call recovered tolerantly from the reply text
        (the fallback for an endpoint without native tool support). When neither
        is present the turn is final and the text is the answer.
        """
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "stream": False,
            "tools": list(tools),
        }
        if self._disable_thinking:
            payload.update(_NO_THINKING_DIRECTIVE)
        self._apply_sampling(payload)
        body = await self._post_json(payload)
        return _extract_tool_call_result(body)

    def _apply_sampling(self, payload: dict[str, object]) -> None:
        """Fold the configured sampling controls into ``payload`` (only when set).

        Adds ``temperature`` / ``top_p`` to the request body only when configured,
        so an unconfigured provider sends neither and the endpoint keeps its own
        defaults (BOB-022 — a set temperature stops greedy verbatim-repeat decoding).
        """
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        if self._top_p is not None:
            payload["top_p"] = self._top_p

    async def _complete_once(self, payload: Mapping[str, object]) -> str:
        body = await self._post_json(payload)
        return _extract_message_content(body)

    async def _post_json(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.post(self._endpoint(), json=payload, headers=self._headers()) as response,
        ):
            response.raise_for_status()
            body = await response.json()
        if not isinstance(body, Mapping):
            raise ValueError("completion response is not a JSON object")
        return body

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
    """Pull the assistant message content from a non-stream completion body.

    Structural errors (no choices / no message) still raise — they mean the
    upstream is broken. A missing/null/non-string ``content`` does NOT: a
    reasoning model can return a successful response having spent its budget on
    ``reasoning_content``, leaving ``content`` empty. Degrade to ``""`` so the
    turn proceeds gracefully instead of erroring the caller into a fallback.
    """
    content = _message_object(body).get("content")
    return content if isinstance(content, str) else ""


def _extract_tool_call_result(body: Mapping[str, object]) -> ToolCallResult:
    """Pull a tool-aware result from a completion body.

    Prefers a native OpenAI ``tool_calls`` array (the endpoint-supports-tools
    path); if absent, falls back to recovering a prompt-protocol JSON tool-call
    from the reply text (reasoning-model wrapping — code fences, prose preamble —
    tolerated). With neither, the turn is final and ``text`` is the answer.
    """
    message = _message_object(body)
    native = _native_tool_calls(message)
    if native:
        return ToolCallResult(text="", tool_calls=native)
    text = message.get("content")
    text = text if isinstance(text, str) else ""
    fallback = _fallback_tool_call(text)
    if fallback is not None:
        return ToolCallResult(text="", tool_calls=(fallback,))
    return ToolCallResult(text=text, tool_calls=())


def _message_object(body: Mapping[str, object]) -> Mapping[str, object]:
    """Return the assistant message object from a completion body (raises if absent)."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("completion response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("completion choice is not an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("completion choice has no message")
    return message


def _native_tool_calls(message: Mapping[str, object]) -> tuple[ToolCall, ...]:
    """Decode an OpenAI-native ``tool_calls`` array into ToolCall value objects."""
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return ()
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        if not isinstance(raw, Mapping):
            continue
        function = raw.get("function")
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        call_id = raw.get("id")
        calls.append(
            ToolCall(
                id=call_id if isinstance(call_id, str) and call_id else f"call_{index}",
                name=name,
                arguments=_decode_arguments(function.get("arguments")),
            )
        )
    return tuple(calls)


def _decode_arguments(raw: object) -> dict[str, object]:
    """Decode an OpenAI tool-call ``arguments`` field (a JSON string) into a dict.

    Malformed or non-object arguments degrade to ``{}`` rather than erroring, so a
    flaky model cannot crash the dispatch.
    """
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str):
        return {}
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _fallback_tool_call(text: str) -> ToolCall | None:
    """Recover a prompt-protocol JSON tool-call from reply text, or ``None``.

    The fallback contract is a JSON object ``{"tool_call": {"name": ...,
    "arguments": {...}}}`` which a model may wrap in reasoning prose or a markdown
    code fence; the first balanced JSON object is scanned out and inspected.
    """
    obj = _first_json_object(text)
    if obj is None:
        return None
    try:
        decoded = json.loads(obj)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    spec = decoded.get(_FALLBACK_TOOL_KEY)
    if not isinstance(spec, dict):
        return None
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        return None
    arguments = spec.get("arguments")
    return ToolCall(
        id="fallback_0",
        name=name,
        arguments=dict(arguments) if isinstance(arguments, dict) else {},
    )


def _first_json_object(text: str) -> str | None:
    """Extract the first balanced ``{...}`` substring of ``text``, or ``None``.

    Scans from the first ``{`` to its matching ``}``, respecting nesting and
    skipping braces inside JSON string literals (with escapes). Tolerates a
    prose/reasoning preamble before, and trailing text after, the object.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


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
