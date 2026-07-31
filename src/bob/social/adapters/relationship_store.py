# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""SqliteRelationshipStore — the per-sender relationship adapter (BOB-014).

Realises :class:`bob.social.ports.RelationshipStore` over the ``person_relationship``
table (named to avoid the legacy single-row ``relationship`` owner-blob): one row per
``sender_id`` so Bob keeps a quality of relationship with each
person he talks to. The domain
:class:`~bob.social.relationship.Relationship` (the four bounded axes:
trust / respect / warmth / compatibility) is mapped to and from a row here, so the
domain stays I/O-free. An unknown sender has no row, so :meth:`load` returns ``None``.

Unlike the formed-once :class:`SqliteFirstImpressionStore`, a relationship EVOLVES:
:meth:`save` is an ``INSERT … ON CONFLICT DO UPDATE`` (an UPSERT), so each turn's
:func:`~bob.social.relationship.apply_interaction` result overwrites the
row with the newer state. Keyed by ``sender_id`` it covers owner / known / guest /
bot alike; this is per-PERSON data (about them), NOT owner-private memory. All SQL is
parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.social.gender import Gender, GenderRead
from bob.social.relationship import Relationship

if TYPE_CHECKING:
    import aiosqlite


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteRelationshipStore:
    """SQLite adapter for Bob's per-sender relationship quality (BOB-014)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, sender_id: int) -> Relationship | None:
        """Return the persisted relationship for ``sender_id``, or ``None``."""
        async with self._db().execute(
            "SELECT sender_id, trust, respect, warmth, compatibility "
            "FROM person_relationship WHERE sender_id = ?",
            (sender_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return Relationship(
            sender_id=int(row[0]),
            trust=float(row[1]),
            respect=float(row[2]),
            warmth=float(row[3]),
            compatibility=float(row[4]),
        )

    async def save(self, relationship: Relationship) -> None:
        """Persist ``relationship`` — UPSERT, so an evolving relationship is updated.

        ``INSERT … ON CONFLICT(sender_id) DO UPDATE``: each turn re-saves the newer
        state, so a relationship that has warmed or cooled over many turns is kept
        current (this is what lets it accrue).
        """
        await self._db().execute(
            "INSERT INTO person_relationship "
            "(sender_id, trust, respect, warmth, compatibility) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(sender_id) DO UPDATE SET "
            "trust = excluded.trust, "
            "respect = excluded.respect, "
            "warmth = excluded.warmth, "
            "compatibility = excluded.compatibility",
            (
                relationship.sender_id,
                relationship.trust,
                relationship.respect,
                relationship.warmth,
                relationship.compatibility,
            ),
        )
        await self._db().commit()

    async def load_gender(self, sender_id: int) -> Gender:
        """Return the self-identified :class:`Gender` for ``sender_id`` (BOB-078 A).

        Reads the persisted gender lean and resolves it (a lean past the threshold →
        FEM / MASC). An unknown sender, or a legacy row whose ``gender`` is ``NULL``,
        reads as :attr:`Gender.UNKNOWN` — Bob then addresses them neutrally, forcing
        no grammatical gender. 🔴 The lean is only ever accrued from a person's own
        self-presentation (see :meth:`observe_gender`), never from their name.
        """
        return GenderRead(await self._load_gender_lean(sender_id)).resolve()

    async def observe_gender(self, sender_id: int, text: str) -> None:
        """Fold ``text``'s self-presentation into ``sender_id``'s gender lean (BOB-078 A).

        Reads the current lean, accrues this message's committed self-signal via the
        pure :class:`~bob.social.gender.GenderRead` (a gendered 1st-person verb / an
        explicit «я сам»/«я сама» nudges it; a name or a 3rd-person verb does not), and
        UPSERTs it back — persisting ONLY the ``gender`` column so the four relationship
        axes are untouched (a not-yet-formed relationship keeps its neutral defaults).
        Keyed by ``sender_id``, per-PERSON data (about them), safe on a guest turn.
        """
        lean = GenderRead(await self._load_gender_lean(sender_id)).observe(text).lean
        await self._db().execute(
            "INSERT INTO person_relationship "
            "(sender_id, trust, respect, warmth, compatibility, gender) "
            "VALUES (?, 0.0, 0.0, 0.0, 0.0, ?) "
            "ON CONFLICT(sender_id) DO UPDATE SET gender = excluded.gender",
            (sender_id, lean),
        )
        await self._db().commit()

    async def _load_gender_lean(self, sender_id: int) -> float:
        """The raw stored gender lean for ``sender_id`` (``0.0`` when absent/NULL)."""
        async with self._db().execute(
            "SELECT gender FROM person_relationship WHERE sender_id = ?",
            (sender_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or row[0] is None:
            return 0.0
        return float(row[0])

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection
