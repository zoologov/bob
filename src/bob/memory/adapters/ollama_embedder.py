# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

"""OllamaEmbedder — local dense embeddings over a LOCAL Ollama server.

Realises :class:`bob.domain.ports.Embedder` against Ollama's embeddings API,
default model ``bge-m3`` (dense, 1024-dim, multilingual/Russian). Embeddings stay
on the machine — memory content never leaves it (privacy, see BOB-011 CONTEXT).

Two request shapes, tried in order:

* **batch** — ``POST {base_url}/api/embed`` with ``{"model", "input": [...]}``,
  returning ``{"embeddings": [[...], ...]}`` (one vector per input, one round-trip);
* **legacy per-text fallback** — ``POST {base_url}/api/embeddings`` with
  ``{"model", "prompt": "..."}`` returning ``{"embedding": [...]}``, used when an
  older Ollama lacks the batch endpoint (it 404s).

Transient faults (connection drops, timeouts, 5xx) are retried with bounded
exponential backoff (reusing :func:`bob.application.runtime.retry.retry_with_backoff`
from BOB-002); permanent errors (4xx, malformed body, dimension mismatch) surface
at once. The adapter is provider-agnostic in spirit: swap ``model``/``dim`` via
config to point at a different local model without touching consumers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import aiohttp

from bob.application.runtime.retry import retry_with_backoff

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.runtime.retry import Sleep

_BATCH_PATH = "api/embed"
_LEGACY_PATH = "api/embeddings"
_HTTP_NOT_FOUND = 404

# Generous default: a cold local model load (first embed after a pull) can be slow.
_DEFAULT_TIMEOUT_SECONDS = 120.0


class OllamaEmbedder:
    """Local Ollama-backed :class:`bob.domain.ports.Embedder` (BGE-M3, 1024-dim).

    One instance targets one ``base_url`` + ``model`` + ``dim``; build it from the
    ``embeddings`` config section via :func:`build_embedder`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dim: int,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        sleep: Sleep | None = None,
    ) -> None:
        if dim <= 0:
            msg = "embeddings.dim must be a positive integer"
            raise ValueError(msg)
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dim = dim
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._sleep = sleep

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` into one ``dim``-length vector each (order-preserving)."""
        items = list(texts)
        if not items:
            return []
        vectors = await retry_with_backoff(lambda: self._embed_once(items), sleep=self._sleep)
        return [self._validated(vector) for vector in vectors]

    async def _embed_once(self, texts: list[str]) -> list[list[float]]:
        """One embedding round-trip: batch endpoint, falling back to per-text legacy."""
        try:
            return await self._embed_batch(texts)
        except aiohttp.ClientResponseError as error:
            if error.status != _HTTP_NOT_FOUND:
                raise
        # Older Ollama without /api/embed: embed each text via the legacy endpoint.
        return [await self._embed_legacy(text) for text in texts]

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self._model, "input": texts}
        body = await self._post_json(_BATCH_PATH, payload)
        raw = body.get("embeddings")
        if not isinstance(raw, list) or len(raw) != len(texts):
            msg = "Ollama batch embed returned a malformed 'embeddings' array"
            raise ValueError(msg)
        return [_as_floats(vector) for vector in raw]

    async def _embed_legacy(self, text: str) -> list[float]:
        payload = {"model": self._model, "prompt": text}
        body = await self._post_json(_LEGACY_PATH, payload)
        raw = body.get("embedding")
        if not isinstance(raw, list):
            msg = "Ollama legacy embed returned a malformed 'embedding' array"
            raise ValueError(msg)
        return _as_floats(raw)

    async def _post_json(
        self,
        path: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.post(f"{self._base_url}/{path}", json=payload) as response,
        ):
            response.raise_for_status()
            body = await response.json()
        if not isinstance(body, Mapping):
            msg = "Ollama embed response is not a JSON object"
            raise ValueError(msg)
        return body

    def _validated(self, vector: list[float]) -> list[float]:
        if len(vector) != self._dim:
            msg = f"embedding dimension {len(vector)} != configured {self._dim}"
            raise ValueError(msg)
        return vector


def _as_floats(raw: object) -> list[float]:
    """Coerce a JSON number array into a list of floats (raises on non-numbers)."""
    if not isinstance(raw, list):
        msg = "embedding vector is not an array"
        raise ValueError(msg)
    result: list[float] = []
    for component in raw:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            msg = "embedding vector contains a non-numeric component"
            raise ValueError(msg)
        result.append(float(component))
    return result
