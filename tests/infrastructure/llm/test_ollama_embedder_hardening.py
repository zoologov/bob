# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening edge cases for OllamaEmbedder (BOB-011 BEAD-07 coverage).

Privacy/locality + resilience contract: the embedder coerces the local model's
JSON into typed float vectors and rejects anything that is not a clean numeric
array (a misconfiguration must surface, not slip a junk vector into the store).
These tests drive the per-vector coercion error branch and the positive-dimension
constructor guard. No network: an in-process loopback aiohttp server stands in for
the local Ollama embeddings API.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from aiohttp import web

from bob.infrastructure.llm.ollama_embedder import OllamaEmbedder

_BATCH_PATH = "/api/embed"

type _Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


async def _start_server(handler: _Handler) -> tuple[str, web.AppRunner]:
    app = web.Application()
    app.router.add_post(_BATCH_PATH, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][0], runner.addresses[0][1]
    return f"http://{host}:{port}", runner


async def test_batch_element_that_is_not_an_array_is_rejected() -> None:
    # Arrange: the batch endpoint returns the right OUTER shape (a list of the right
    # length) but one INNER vector is not an array — a malformed component.
    async def embed(request: web.Request) -> web.Response:
        return web.json_response({"embeddings": ["not-a-vector"]})

    base_url, runner = await _start_server(embed)
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=3)

        # Act / Assert: coercion refuses a non-array vector rather than storing junk.
        with pytest.raises(ValueError, match=r"vector is not an array"):
            await embedder.embed(["hello"])
    finally:
        await runner.cleanup()


async def test_batch_vector_with_non_numeric_component_is_rejected() -> None:
    # Arrange: a well-shaped array whose components include a non-number.
    async def embed(request: web.Request) -> web.Response:
        return web.json_response({"embeddings": [[0.1, "oops", 0.3]]})

    base_url, runner = await _start_server(embed)
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=3)

        # Act / Assert
        with pytest.raises(ValueError, match=r"non-numeric component"):
            await embedder.embed(["hello"])
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("bad_dim", [0, -1, -1024])
def test_non_positive_dim_is_rejected(bad_dim: int) -> None:
    # Arrange / Act / Assert: a non-positive dimension can never match the schema's
    # float[N] width, so it is a config error rejected at construction.
    with pytest.raises(ValueError, match=r"dim must be a positive integer"):
        OllamaEmbedder(base_url="http://localhost:11434", model="bge-m3", dim=bad_dim)


async def test_empty_input_makes_no_request() -> None:
    # Arrange: a server that must never be hit for an empty batch.
    async def embed(request: web.Request) -> web.Response:
        raise AssertionError("embed([]) must not hit the network")

    base_url, runner = await _start_server(embed)
    try:
        embedder = OllamaEmbedder(base_url=base_url, model="bge-m3", dim=3)

        # Act / Assert: an empty input short-circuits to an empty result, no I/O.
        assert await embedder.embed([]) == []
    finally:
        await runner.cleanup()
