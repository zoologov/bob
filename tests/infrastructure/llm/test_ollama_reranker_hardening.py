# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening edge cases for OllamaReranker (BOB-011 BEAD-07 coverage).

The reranker is an ADDITIVE boost that must NEVER regress recall: every malformed
response shape from the local model degrades to the input (hybrid) order rather
than crashing the recall pipeline. These tests drive the response-parsing error
branches and the constructor guard against an unusable ``top_n``. No network: an
in-process loopback aiohttp server emulates the local Ollama chat-completions API.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from aiohttp import web

from bob.infrastructure.llm.ollama_reranker import OllamaReranker

_CHAT_PATH = "/v1/chat/completions"

type _Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


async def _start_server(handler: _Handler) -> tuple[str, web.AppRunner]:
    """Start a loopback aiohttp server serving ``handler`` on the chat path."""
    app = web.Application()
    app.router.add_post(_CHAT_PATH, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][0], runner.addresses[0][1]
    return f"http://{host}:{port}", runner


def _candidate(content: str) -> dict[str, object]:
    return {"content": content, "source": "semantic"}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(["not", "an", "object"], id="body-is-a-json-array"),
        pytest.param({"choices": []}, id="choices-empty"),
        pytest.param({"choices": ["not-an-object"]}, id="choice-not-an-object"),
        pytest.param({"choices": [{"role": "assistant"}]}, id="choice-has-no-message"),
        pytest.param(
            {"choices": [{"message": "not-an-object"}]}, id="message-not-an-object"
        ),
        pytest.param(
            {"choices": [{"message": {"role": "assistant", "content": 42}}]},
            id="content-not-a-string",
        ),
        pytest.param(
            {"choices": [{"message": {"role": "assistant"}}]}, id="message-has-no-content"
        ),
    ],
)
async def test_malformed_response_shape_falls_back_to_input_order(
    body: object,
) -> None:
    # Arrange: the server returns a structurally-broken chat-completions body for
    # every candidate, so no score can be parsed.
    async def chat(request: web.Request) -> web.Response:
        return web.json_response(body)

    base_url, runner = await _start_server(chat)
    try:
        reranker = OllamaReranker(
            base_url=base_url, model="bge-reranker", top_n=3, max_attempts=1
        )
        candidates = [_candidate("a"), _candidate("b"), _candidate("c")]

        # Act
        ranked = await reranker.rerank("q", candidates)

        # Assert: the hybrid order is returned unchanged (no crash, no regression).
        assert list(ranked) == candidates
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("bad_top_n", [0, -1, -50])
def test_non_positive_top_n_is_rejected(bad_top_n: int) -> None:
    # Arrange / Act / Assert: a top_n that could never yield results is a config
    # error and must be rejected at construction, not silently produce an empty pool.
    with pytest.raises(ValueError, match=r"top_n must be a positive integer"):
        OllamaReranker(base_url="http://localhost:11434", model="m", top_n=bad_top_n)
