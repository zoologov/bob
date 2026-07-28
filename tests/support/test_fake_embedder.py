# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the deterministic FakeEmbedder test double."""

from __future__ import annotations

import math

import pytest

from bob.memory.ports import Embedder
from tests.support.fake_embedder import FakeEmbedder


def test_fake_embedder_satisfies_embedder_port() -> None:
    assert isinstance(FakeEmbedder(dim=8), Embedder)


async def test_embed_returns_one_vector_per_text_of_fixed_dim() -> None:
    # Arrange
    embedder = FakeEmbedder(dim=16)

    # Act
    vectors = await embedder.embed(["alpha", "beta", "gamma"])

    # Assert: aligned, fixed-dimension output.
    assert len(vectors) == 3
    assert all(len(vector) == 16 for vector in vectors)


async def test_embed_is_deterministic_for_same_text() -> None:
    # Arrange
    embedder = FakeEmbedder(dim=16)

    # Act
    first = await embedder.embed(["repeatable"])
    second = await embedder.embed(["repeatable"])

    # Assert: same text -> identical vector (reproducible tests).
    assert first == second


async def test_embed_differs_for_distinct_texts() -> None:
    # Arrange
    embedder = FakeEmbedder(dim=16)

    # Act
    vectors = await embedder.embed(["one", "two"])

    # Assert: distinct inputs map to distinct vectors.
    assert vectors[0] != vectors[1]


async def test_embed_empty_input_yields_empty_list() -> None:
    embedder = FakeEmbedder(dim=16)
    assert await embedder.embed([]) == []


async def test_vectors_are_l2_normalised() -> None:
    # Arrange
    embedder = FakeEmbedder(dim=32)

    # Act
    (vector,) = await embedder.embed(["normalise me"])

    # Assert: unit length (within float tolerance).
    norm = math.sqrt(sum(component * component for component in vector))
    assert norm == pytest.approx(1.0)


def test_default_dim_matches_bge_m3() -> None:
    assert FakeEmbedder().dim == 1024


def test_non_positive_dim_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        FakeEmbedder(dim=0)
