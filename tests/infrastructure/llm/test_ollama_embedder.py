# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for OllamaEmbedder against an in-process aiohttp server (no network).

The test server binds to loopback and emulates the local Ollama embeddings API:

* the batch endpoint ``POST /api/embed`` returning ``{"embeddings": [[...], ...]}``;
* the legacy per-text endpoint ``POST /api/embeddings`` returning
  ``{"embedding": [...]}`` (the fallback path).

This exercises the real aiohttp request/response + retry path of the adapter; no
real Ollama is contacted, so CI needs neither network nor a model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from aiohttp import web

from bob.domain.ports import Embedder
from bob.memory.adapters.ollama_embedder import OllamaEmbedder

_BATCH_PATH = "/api/embed"
_LEGACY_PATH = "/api/embeddings"

type _Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


async def _start_server(
    routes: dict[str, _Handler],
) -> tuple[str, web.AppRunner]:
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


@pytest.fixture
def captured() -> dict[str, object]:
    return {}


def _vector(seed: float, dim: int) -> list[float]:
    return [seed + index for index in range(dim)]


def _bump(captured: dict[str, object], key: str) -> int:
    """Increment and return an integer counter stored under ``key``."""
    current = captured.get(key, 0)
    count = (current if isinstance(current, int) else 0) + 1
    captured[key] = count
    return count


async def test_is_embedder_port() -> None:
    embedder = OllamaEmbedder(base_url="http://localhost:11434", model="bge-m3", dim=4)
    assert isinstance(embedder, Embedder)


async def test_embed_batches_inputs_in_one_request(captured: dict[str, object]) -> None:
    # Arrange: a server that returns one vector per input via the batch endpoint.
    async def batch(request: web.Request) -> web.Response:
        payload = await request.json()
        captured["payload"] = payload
        _bump(captured, "calls")
        inputs = payload["input"]
        vectors = [_vector(float(i), 4) for i in range(len(inputs))]
        return web.json_response({"embeddings": vectors})

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)

        # Act
        vectors = await embedder.embed(["a", "b", "c"])

        # Assert: one batched request carrying model + all inputs; aligned output.
        assert captured["calls"] == 1
        assert captured["payload"] == {"model": "bge-m3", "input": ["a", "b", "c"]}
        assert vectors == [_vector(0.0, 4), _vector(1.0, 4), _vector(2.0, 4)]
    finally:
        await runner.cleanup()


async def test_empty_input_makes_no_request() -> None:
    # Arrange: a server that would fail the test if called.
    async def batch(request: web.Request) -> web.Response:  # pragma: no cover - must not run
        raise AssertionError("embed([]) must not hit the network")

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)

        # Act / Assert
        assert await embedder.embed([]) == []
    finally:
        await runner.cleanup()


async def test_wrong_dimension_is_rejected() -> None:
    # Arrange: server returns vectors of the wrong length.
    async def batch(request: web.Request) -> web.Response:
        payload = await request.json()
        return web.json_response({"embeddings": [[1.0, 2.0] for _ in payload["input"]]})

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)

        # Act / Assert: a dimension mismatch is a contract violation.
        with pytest.raises(ValueError, match="dimension"):
            await embedder.embed(["x"])
    finally:
        await runner.cleanup()


async def test_falls_back_to_legacy_per_text_endpoint(captured: dict[str, object]) -> None:
    # Arrange: the batch endpoint 404s; the legacy per-text endpoint serves vectors.
    async def batch(request: web.Request) -> web.Response:
        raise web.HTTPNotFound

    async def legacy(request: web.Request) -> web.Response:
        payload = await request.json()
        _bump(captured, "legacy_calls")
        prompt = payload["prompt"]
        seed = float(len(prompt))
        return web.json_response({"embedding": _vector(seed, 4)})

    base_url, runner = await _start_server({_BATCH_PATH: batch, _LEGACY_PATH: legacy})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)

        # Act
        vectors = await embedder.embed(["ab", "abcd"])

        # Assert: one legacy request per text; vectors aligned to inputs.
        assert captured["legacy_calls"] == 2
        assert vectors == [_vector(2.0, 4), _vector(4.0, 4)]
    finally:
        await runner.cleanup()


async def test_retries_transient_server_error_then_succeeds(captured: dict[str, object]) -> None:
    # Arrange: the first call 503s (transient), the second succeeds.
    async def batch(request: web.Request) -> web.Response:
        payload = await request.json()
        attempt = _bump(captured, "attempts")
        if attempt == 1:
            raise web.HTTPServiceUnavailable
        return web.json_response({"embeddings": [_vector(0.0, 4) for _ in payload["input"]]})

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        # No real sleeping between retries (injected no-op).
        async def no_sleep(_seconds: float) -> None:
            return None

        embedder = OllamaEmbedder(
            base_url=base_url,
            model="bge-m3",
            dim=4,
            sleep=no_sleep,
        )

        # Act
        vectors = await embedder.embed(["only"])

        # Assert: it retried once and then returned the vector.
        assert captured["attempts"] == 2
        assert vectors == [_vector(0.0, 4)]
    finally:
        await runner.cleanup()


async def test_permanent_client_error_is_surfaced() -> None:
    # Arrange: a 400 is permanent (a real bug) — it must not be retried.
    async def batch(request: web.Request) -> web.Response:
        raise web.HTTPBadRequest

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)

        # Act / Assert
        with pytest.raises(Exception, match="400"):
            await embedder.embed(["x"])
    finally:
        await runner.cleanup()


async def test_batch_count_mismatch_is_rejected() -> None:
    # Arrange: server returns fewer vectors than inputs (broken upstream).
    async def batch(request: web.Request) -> web.Response:
        return web.json_response({"embeddings": [_vector(0.0, 4)]})

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)
        with pytest.raises(ValueError, match="malformed"):
            await embedder.embed(["a", "b"])
    finally:
        await runner.cleanup()


async def test_legacy_malformed_embedding_is_rejected() -> None:
    # Arrange: batch 404s; legacy returns a non-array embedding.
    async def batch(request: web.Request) -> web.Response:
        raise web.HTTPNotFound

    async def legacy(request: web.Request) -> web.Response:
        return web.json_response({"embedding": "not-an-array"})

    base_url, runner = await _start_server({_BATCH_PATH: batch, _LEGACY_PATH: legacy})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)
        with pytest.raises(ValueError, match="malformed"):
            await embedder.embed(["x"])
    finally:
        await runner.cleanup()


async def test_non_numeric_component_is_rejected() -> None:
    # Arrange: a vector with a non-numeric component (a flaky/broken model).
    async def batch(request: web.Request) -> web.Response:
        return web.json_response({"embeddings": [[1.0, 2.0, "x", 4.0]]})

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)
        with pytest.raises(ValueError, match="non-numeric"):
            await embedder.embed(["only"])
    finally:
        await runner.cleanup()


async def test_non_object_response_is_rejected() -> None:
    # Arrange: the endpoint returns a JSON array, not an object.
    async def batch(request: web.Request) -> web.Response:
        return web.json_response([1, 2, 3])

    base_url, runner = await _start_server({_BATCH_PATH: batch})
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=4)
        with pytest.raises(ValueError, match="not a JSON object"):
            await embedder.embed(["only"])
    finally:
        await runner.cleanup()


def test_non_positive_dim_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        OllamaEmbedder(base_url="http://localhost:11434", model="bge-m3", dim=0)
