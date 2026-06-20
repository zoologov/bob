# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""FakeEmbedder — a deterministic in-memory :class:`bob.domain.ports.Embedder`.

No network, no Ollama: maps each text to a stable pseudo-vector of the configured
dimension by seeding ``random.Random`` with a hash of the text. The same text
always yields the same vector (so similarity tests are reproducible) and CI never
touches a real embedding server. Vectors are L2-normalised so cosine-similarity
comparisons in higher beads behave sensibly.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_DEFAULT_DIM = 1024


class FakeEmbedder:
    """Deterministic embedder for tests: text -> stable normalised vector.

    Realises :class:`bob.domain.ports.Embedder`. ``dim`` defaults to 1024 (BGE-M3)
    so fakes match the production dimension; pass a smaller ``dim`` for fast unit
    tests where the exact size doesn't matter.
    """

    def __init__(self, *, dim: int = _DEFAULT_DIM) -> None:
        if dim <= 0:
            msg = "embedding dimension must be positive"
            raise ValueError(msg)
        self._dim = dim

    @property
    def dim(self) -> int:
        """The fixed dimension of every vector this embedder produces."""
        return self._dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one stable, L2-normalised pseudo-vector per input text."""
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        raw = [rng.uniform(-1.0, 1.0) for _ in range(self._dim)]
        norm = math.sqrt(sum(component * component for component in raw))
        if norm == 0.0:
            return raw
        return [component / norm for component in raw]
