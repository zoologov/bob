# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for OllamaReranker against an in-process aiohttp server (no network).

The reranker is an ADDITIVE quality boost on top of hybrid recall: it re-scores
top-K candidates with a local Ollama model (Ollama-as-scorer — there is no native
rerank endpoint, Q1) and returns the best top-N. It must NEVER crash recall: a
disabled reranker, an unavailable endpoint, or a malformed score all degrade to
returning the input candidates unchanged (the hybrid order).

The test server binds to loopback and emulates the local Ollama chat-completions
API, returning a per-candidate relevance score; no real Ollama is contacted, so
CI needs neither network nor a model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aiohttp import web

from bob.domain.ports import Reranker
from bob.memory.adapters.ollama_reranker import OllamaReranker

_CHAT_PATH = "/v1/chat/completions"

type _Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


async def _start_server(routes: dict[str, _Handler]) -> tuple[str, web.AppRunner]:
    """Start a loopback aiohttp server for ``routes`` and return (base_url, runner)."""
    app = web.Application()
    for path, handler in routes.items():
        app.router.add_post(path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][0], runner.addresses[0][1]
    return f"http://{host}:{port}", runner


def _candidate(content: str) -> dict[str, object]:
    return {"content": content, "source": "semantic"}


def _score_response(score: str) -> web.Response:
    """An OpenAI chat-completions body whose message content is ``score``."""
    return web.json_response(
        {"choices": [{"message": {"role": "assistant", "content": score}}]}
    )


async def test_is_reranker_port() -> None:
    reranker = OllamaReranker(base_url="http://localhost:11434", model="bge-reranker", top_n=3)
    assert isinstance(reranker, Reranker)


async def test_reorders_candidates_by_model_score() -> None:
    # Arrange: a server that scores each candidate by a number embedded in its
    # content (so the expected order is deterministic and reproducible).
    async def chat(request: web.Request) -> web.Response:
        payload = await request.json()
        prompt = str(payload["messages"][-1]["content"])
        # The candidate text carries its own score, e.g. "doc score=0.9".
        score = prompt.rsplit("score=", 1)[1].strip()
        return _score_response(score)

    base_url, runner = await _start_server({_CHAT_PATH: chat})
    try:
        reranker = OllamaReranker(base_url=base_url, model="bge-reranker", top_n=3)
        candidates = [
            _candidate("low score=0.1"),
            _candidate("high score=0.9"),
            _candidate("mid score=0.5"),
        ]

        ranked = await reranker.rerank("q", candidates)

        contents = [str(c["content"]) for c in ranked]
        assert contents == ["high score=0.9", "mid score=0.5", "low score=0.1"]
    finally:
        await runner.cleanup()


async def test_trims_to_top_n() -> None:
    async def chat(request: web.Request) -> web.Response:
        payload = await request.json()
        prompt = str(payload["messages"][-1]["content"])
        score = prompt.rsplit("score=", 1)[1].strip()
        return _score_response(score)

    base_url, runner = await _start_server({_CHAT_PATH: chat})
    try:
        reranker = OllamaReranker(base_url=base_url, model="bge-reranker", top_n=2)
        candidates = [
            _candidate("a score=0.1"),
            _candidate("b score=0.9"),
            _candidate("c score=0.5"),
            _candidate("d score=0.7"),
        ]

        ranked = await reranker.rerank("q", candidates)

        assert [str(c["content"]) for c in ranked] == ["b score=0.9", "d score=0.7"]
    finally:
        await runner.cleanup()


async def test_endpoint_unavailable_returns_input_unchanged() -> None:
    # A bad base_url (nothing listening) must NOT crash recall: the reranker
    # degrades to the input order. This is the core "additive, no regression" rule.
    reranker = OllamaReranker(
        base_url="http://127.0.0.1:1",  # nothing listening on this port
        model="bge-reranker",
        top_n=3,
        timeout_seconds=0.2,
    )
    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]

    ranked = await reranker.rerank("q", candidates)

    assert list(ranked) == candidates  # unchanged hybrid order, no exception


async def test_malformed_score_falls_back_to_input_order() -> None:
    # The model returns non-numeric garbage for every candidate: the reranker
    # cannot trust the scores, so it returns the input candidates unchanged.
    async def chat(request: web.Request) -> web.Response:
        return _score_response("not-a-number")

    base_url, runner = await _start_server({_CHAT_PATH: chat})
    try:
        reranker = OllamaReranker(base_url=base_url, model="bge-reranker", top_n=3)
        candidates = [_candidate("a"), _candidate("b"), _candidate("c")]

        ranked = await reranker.rerank("q", candidates)

        assert list(ranked) == candidates
    finally:
        await runner.cleanup()


async def test_empty_candidates_makes_no_request() -> None:
    async def chat(request: web.Request) -> web.Response:  # pragma: no cover - must not run
        raise AssertionError("rerank([]) must not hit the network")

    base_url, runner = await _start_server({_CHAT_PATH: chat})
    try:
        reranker = OllamaReranker(base_url=base_url, model="bge-reranker", top_n=3)
        assert await reranker.rerank("q", []) == []
    finally:
        await runner.cleanup()


async def test_partial_failure_keeps_input_order() -> None:
    # If scoring ONE candidate raises mid-batch, the whole rerank degrades to the
    # input order rather than returning a partial/misleading ranking.
    state: dict[str, int] = {"calls": 0}

    async def chat(request: web.Request) -> web.Response:
        state["calls"] += 1
        if state["calls"] == 2:
            raise web.HTTPInternalServerError
        return _score_response("0.5")

    base_url, runner = await _start_server({_CHAT_PATH: chat})
    try:
        reranker = OllamaReranker(
            base_url=base_url,
            model="bge-reranker",
            top_n=3,
            max_attempts=1,
        )
        candidates = [_candidate("a"), _candidate("b"), _candidate("c")]

        ranked = await reranker.rerank("q", candidates)

        assert list(ranked) == candidates
    finally:
        await runner.cleanup()


async def test_score_clamped_and_parsed_from_prose() -> None:
    # A chatty model wraps the score in prose ("Relevance: 0.83 because..."): the
    # first number is parsed out so the candidate is still scored.
    contents: Sequence[str] = ("Relevance: 0.83 — strongly on-topic", "0.10")

    async def chat(request: web.Request) -> web.Response:
        payload = await request.json()
        prompt = str(payload["messages"][-1]["content"])
        reply = contents[0] if "first" in prompt else contents[1]
        return _score_response(reply)

    base_url, runner = await _start_server({_CHAT_PATH: chat})
    try:
        reranker = OllamaReranker(base_url=base_url, model="bge-reranker", top_n=2)
        candidates = [_candidate("first"), _candidate("second")]

        ranked = await reranker.rerank("q", candidates)

        assert [str(c["content"]) for c in ranked] == ["first", "second"]
    finally:
        await runner.cleanup()
