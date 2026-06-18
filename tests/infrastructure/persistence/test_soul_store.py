# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SoulStore — reading/writing the data/soul/ artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.soul_store import SoulStore

if TYPE_CHECKING:
    from pathlib import Path


def test_soul_absent_on_fresh_store(tmp_path: Path) -> None:
    # Arrange
    store = SoulStore(tmp_path / "soul")

    # Act / Assert
    assert store.soul_exists() is False


def test_write_and_read_soul_markdown(tmp_path: Path) -> None:
    # Arrange
    store = SoulStore(tmp_path / "soul")

    # Act
    store.write_soul("# Bob\n\nI am Bob.")
    text = store.read_soul()

    # Assert: the directory is created on demand and the file round-trips.
    assert store.soul_exists() is True
    assert "I am Bob." in text


def test_read_soul_missing_raises(tmp_path: Path) -> None:
    # Arrange
    store = SoulStore(tmp_path / "soul")

    # Act / Assert
    with pytest.raises(FileNotFoundError):
        store.read_soul()


def test_write_and_read_json_artifact(tmp_path: Path) -> None:
    # Arrange
    store = SoulStore(tmp_path / "soul")

    # Act
    store.write_json("taste_profile", {"humor": 0.8, "axes": ["a", "b"]})
    data = store.read_json("taste_profile")

    # Assert
    assert data == {"humor": 0.8, "axes": ["a", "b"]}


def test_read_json_missing_returns_none(tmp_path: Path) -> None:
    # Arrange
    store = SoulStore(tmp_path / "soul")

    # Act / Assert
    assert store.read_json("absent") is None


def test_append_genesis_log(tmp_path: Path) -> None:
    # Arrange
    store = SoulStore(tmp_path / "soul")

    # Act
    store.append_genesis_log("awoke")
    store.append_genesis_log("named self")
    log = store.read_genesis_log()

    # Assert
    assert "awoke" in log
    assert "named self" in log


def test_soul_survives_new_store_instance(tmp_path: Path) -> None:
    # Arrange: write with one store, read with a fresh one (restart).
    soul_dir = tmp_path / "soul"
    SoulStore(soul_dir).write_soul("persisted soul")

    # Act
    reloaded = SoulStore(soul_dir)

    # Assert
    assert reloaded.soul_exists()
    assert reloaded.read_soul() == "persisted soul"
