# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Gap-fill: the VECTOR (semantic) recall seam must also carry visibility (BOB-066 2.6).

The keyword (FTS5) recall seam already carries the ``visibility`` provenance
(``test_fts_recall``), but такт разглашения only holds if the *other* recall source —
:meth:`~bob.memory.adapters.vector_store.MemoryVectorStore.knn`, fused into hybrid
recall — carries it too; otherwise an ``owner_private`` memory could reach a guest via
the vector path while :func:`~bob.social.disclosure.filter_surfaceable` reads a missing
tag as public. These tests exercise ``knn`` over a real sqlite-vec store (the changed
``t.visibility`` SELECT column) and assert INV-7 end-to-end through the vector path:
owner_private is withheld from a GUEST, everything surfaces to a TRUSTED interlocutor,
and a legacy (NULL) row stays public.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.entities import SemanticFact
from bob.social.disclosure import filter_surfaceable, may_surface
from bob.social.interlocutor import Trust
from tests.support.fake_embedder import FakeEmbedder

if TYPE_CHECKING:
    from pathlib import Path

_DIM = 1024  # must match the schema's float[1024] (BGE-M3) or on-write embeds are dropped


def _ts() -> datetime:
    return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


async def _query_vector(text: str) -> list[float]:
    """A deterministic query vector for ``text`` (matches the on-write embedder)."""
    (vector,) = await FakeEmbedder(dim=_DIM).embed([text])
    return vector


async def test_vector_recall_hit_carries_semantic_visibility(tmp_path: Path) -> None:
    # Arrange: an owner_private fact embedded on write via the (deterministic) embedder.
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=FakeEmbedder(dim=_DIM))
    await repo.initialize()
    await repo.save_fact(
        SemanticFact(
            ts=_ts(), category="pref", content="адрес владельца", visibility="owner_private"
        )
    )

    # Act: a KNN query returns the nearest memory (its own vector is the nearest).
    hits = await repo.vector_knn(await _query_vector("адрес владельца"), k=5)

    # Assert: the vector-recall hit carries the scope-provenance the filter reads.
    await repo.close()
    assert hits, "expected at least one KNN neighbour"
    assert any(hit.get("visibility") == "owner_private" for hit in hits)


async def test_vector_recall_legacy_row_visibility_is_none_public(tmp_path: Path) -> None:
    # A fact saved WITHOUT visibility (NULL) surfaces from the vector path as None (=public).
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=FakeEmbedder(dim=_DIM))
    await repo.initialize()
    await repo.save_fact(SemanticFact(ts=_ts(), category="pref", content="любит джаз"))

    hits = await repo.vector_knn(await _query_vector("любит джаз"), k=5)

    await repo.close()
    assert hits
    assert all(hit.get("visibility") is None for hit in hits)


async def test_vector_recall_withholds_owner_private_from_a_guest(tmp_path: Path) -> None:
    # INV-7 end-to-end through the VECTOR path: an owner_private memory recalled by KNN
    # is dropped by filter_surfaceable for a GUEST, while the public one survives.
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=FakeEmbedder(dim=_DIM))
    await repo.initialize()
    await repo.save_fact(
        SemanticFact(
            ts=_ts(), category="pref", content="адрес владельца", visibility="owner_private"
        )
    )
    await repo.save_fact(
        SemanticFact(ts=_ts(), category="pref", content="любит джаз", visibility="public")
    )

    hits = await repo.vector_knn(await _query_vector("адрес владельца"), k=5)
    surfaced = filter_surfaceable(hits, Trust.GUEST)

    await repo.close()
    contents = {str(item["content"]) for item in surfaced}
    assert "адрес владельца" not in contents  # owner_private withheld from the guest
    assert any(
        may_surface(str(hit.get("visibility")) if hit.get("visibility") else None, Trust.GUEST)
        for hit in hits
    )


async def test_vector_recall_is_byte_identical_for_a_trusted_interlocutor(
    tmp_path: Path,
) -> None:
    # INV-7: for the owner / a known peer (TRUSTED) the filter is a no-op over the vector
    # recall pool — every KNN hit passes, so semantic recall is unchanged.
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=FakeEmbedder(dim=_DIM))
    await repo.initialize()
    await repo.save_fact(
        SemanticFact(
            ts=_ts(), category="pref", content="адрес владельца", visibility="owner_private"
        )
    )

    hits = await repo.vector_knn(await _query_vector("адрес владельца"), k=5)
    surfaced = filter_surfaceable(hits, Trust.TRUSTED)

    await repo.close()
    assert surfaced == tuple(hits)  # byte-identical, order preserved
