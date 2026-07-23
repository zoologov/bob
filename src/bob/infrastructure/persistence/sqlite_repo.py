# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SqliteMemoryRepo — the durable SQLite-backed store for Bob's memory & state.

Realises :class:`bob.domain.ports.MemoryRepo` and is the single home for SQL in
the codebase. The schema (``schema.sql``) is applied idempotently on
:meth:`initialize`, the connection runs in WAL mode for concurrent reads, and
every statement is parameterised (``?``) — never an f-string. Domain entities
(:class:`~bob.memory.entities.EpisodicEvent` /
:class:`~bob.memory.entities.SemanticFact`) are mapped to and from rows here so
the domain stays I/O-free.

This store is the memory adapter that temporarily lives in the shared
persistence kernel until the runtime slice (BOB-062.7) splits the connection
kernel from the ``MemoryRepo`` realisation. Its single reach into the memory
module — importing the entities above — is the deliberately-allowed
``kernel → bob.memory.entities`` edge (TODO-.7), marked in the boundary rules.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import TYPE_CHECKING

import aiosqlite

from bob.infrastructure.persistence.vector_store import MemoryVectorStore

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from pathlib import Path

    from bob.domain.ports import Embedder
    from bob.infrastructure.persistence.vector_store import VectorSource
    from bob.memory.entities import EpisodicEvent, SemanticFact

logger = logging.getLogger(__name__)

# A JSON-serialisable state blob (mood / relationship).
type StateBlob = Mapping[str, object]

_SCHEMA_RESOURCE = "schema.sql"
_MOOD_ROW_ID = 1
_RELATIONSHIP_ROW_ID = 1


class SqliteMemoryRepo:
    """SQLite adapter for episodic/semantic memory and personality state."""

    def __init__(
        self,
        db_path: Path,
        *,
        embedder: Embedder | None = None,
        name_to_sender_id: Mapping[str, int] | None = None,
    ) -> None:
        self._db_path = db_path
        self._embedder = embedder
        # Best-effort backfill map (BOB-045): a content name-prefix -> known sender
        # id (owner display name -> owner_id, allowlisted names -> their ids). Empty
        # when no identity is wired, in which case the backfill is a graceful no-op.
        self._name_to_sender_id = dict(name_to_sender_id or {})
        self._conn: aiosqlite.Connection | None = None
        self._vectors: MemoryVectorStore | None = None

    async def initialize(self) -> None:
        """Open the connection (WAL), apply the schema, and embed the archive.

        Idempotent. The sqlite-vec extension is loaded onto the connection before
        the schema runs (the ``memory_vec`` vec0 table needs it), then existing
        facts/episodes are backfilled into the vector store via the injected
        embedder (a no-op when none is wired).
        """
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            self._vectors = MemoryVectorStore(self._conn, self._embedder)
            await self._vectors.load_extension()
        await self._conn.executescript(_load_schema())
        await self._migrate_episodic_consolidated()
        await self._migrate_episodic_sender_id()
        await self._migrate_episodic_bob_message_id()
        await self._migrate_semantic_superseded_by()
        await self._migrate_pursuit_stopped()
        await self._backfill_episodic_fts()
        await self._backfill_episodic_sender_id()
        await self._conn.commit()
        await self._vector_store().backfill()
        logger.info("SqliteMemoryRepo initialised at %s", self._db_path)

    async def _migrate_episodic_consolidated(self) -> None:
        """Add ``episodic_log.consolidated`` to a pre-existing DB (idempotent, BOB-021).

        ``CREATE TABLE IF NOT EXISTS`` never alters an already-present table, so a DB
        written before this column existed would lack it. This guarded ``ALTER`` adds
        it only when missing — additive and non-destructive: existing rows take the
        column default (0, i.e. un-consolidated). Skipped when the column is already
        there, so re-running ``initialize()`` is a clean no-op.
        """
        if "consolidated" in await self._episodic_columns():
            return
        await self._db().execute(
            "ALTER TABLE episodic_log ADD COLUMN consolidated INTEGER NOT NULL DEFAULT 0"
        )

    async def _migrate_episodic_sender_id(self) -> None:
        """Add ``episodic_log.sender_id`` + its index to a pre-existing DB (BOB-045).

        ``CREATE TABLE IF NOT EXISTS`` never alters an already-present table, so a DB
        written before this column existed would lack it. This guarded ``ALTER`` adds
        it only when missing — additive and non-destructive: existing rows take the
        column default (NULL, i.e. an unattributed turn). The ``idx_episodic_sender``
        index is created here (not in ``schema.sql``) because a column-less legacy DB
        runs the schema script before this ALTER, so a ``CREATE INDEX`` on
        ``sender_id`` there would reference a not-yet-existing column. ``CREATE INDEX
        IF NOT EXISTS`` keeps the whole step a clean no-op once present.
        """
        if "sender_id" not in await self._episodic_columns():
            await self._db().execute("ALTER TABLE episodic_log ADD COLUMN sender_id INTEGER")
        await self._db().execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_sender ON episodic_log (sender_id, ts)"
        )

    async def _migrate_episodic_bob_message_id(self) -> None:
        """Add ``episodic_log.bob_message_id`` + its index to a pre-existing DB (BOB-050).

        ``CREATE TABLE IF NOT EXISTS`` never alters an already-present table, so a DB
        written before this column existed would lack it. This guarded ``ALTER`` adds
        it only when missing -- additive and non-destructive: existing rows take the
        column default (NULL, i.e. no linked outgoing Bob message). The
        ``idx_episodic_bob_message_id`` index is created here (not in ``schema.sql``)
        because a column-less legacy DB runs the schema script before this ALTER, so a
        ``CREATE INDEX`` on ``bob_message_id`` there would reference a not-yet-existing
        column. ``CREATE INDEX IF NOT EXISTS`` keeps the whole step a clean no-op once
        present, so re-running ``initialize()`` is idempotent.
        """
        if "bob_message_id" not in await self._episodic_columns():
            await self._db().execute(
                "ALTER TABLE episodic_log ADD COLUMN bob_message_id INTEGER"
            )
        await self._db().execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_bob_message_id "
            "ON episodic_log (bob_message_id)"
        )

    async def _backfill_episodic_sender_id(self) -> None:
        """Best-effort, idempotent backfill of ``sender_id`` for legacy NULL rows (BOB-045).

        Rows written before the column existed carry the author only inside
        ``content`` (``"<name>: …\\nbob: …"``). For each row still missing a
        ``sender_id`` whose leading ``"<name>: "`` prefix resolves to a known sender
        (owner display name -> owner_id, allowlisted names -> their ids), set the id.
        Unmatched rows stay NULL (graceful — they simply do not replay per-person).

        Idempotent + non-destructive: it only ever fills a NULL, and is guarded so it
        does nothing once no NULL rows remain or no identity map is wired — so a
        second ``initialize()`` is a clean no-op. New turns are written attributed, so
        the NULL set only ever shrinks.
        """
        if not self._name_to_sender_id:
            return
        async with self._db().execute(
            "SELECT id, content FROM episodic_log WHERE sender_id IS NULL"
        ) as cursor:
            rows = await cursor.fetchall()
        updates = [
            (sender_id, int(row[0]))
            for row in rows
            if (sender_id := self._name_to_sender_id.get(_name_prefix(str(row[1])))) is not None
        ]
        if not updates:
            return
        await self._db().executemany(
            "UPDATE episodic_log SET sender_id = ? WHERE id = ?", updates
        )

    async def _episodic_columns(self) -> set[str]:
        """Names of the columns currently on ``episodic_log``."""
        async with self._db().execute("PRAGMA table_info(episodic_log)") as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _migrate_semantic_superseded_by(self) -> None:
        """Add ``semantic_memory.superseded_by`` to a pre-existing DB (idempotent, BOB-021).

        ``CREATE TABLE IF NOT EXISTS`` never alters an already-present table, so a DB
        written before this column existed would lack it. This guarded ``ALTER`` adds
        it only when missing — additive and non-destructive: existing rows take the
        column default (NULL, i.e. an active, un-superseded fact). Skipped when the
        column is already there, so re-running ``initialize()`` is a clean no-op.
        """
        if "superseded_by" in await self._semantic_columns():
            return
        await self._db().execute(
            "ALTER TABLE semantic_memory ADD COLUMN superseded_by INTEGER"
        )

    async def _semantic_columns(self) -> set[str]:
        """Names of the columns currently on ``semantic_memory``."""
        async with self._db().execute("PRAGMA table_info(semantic_memory)") as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _migrate_pursuit_stopped(self) -> None:
        """Add ``proactivity_state.pursuit_stopped`` to a pre-existing DB (BOB-015 .2).

        The goal-pursuit kill-switch flag (``/goals stop``). ``CREATE TABLE IF NOT
        EXISTS`` never alters an already-present table, so a DB written before this
        column existed would lack it. This guarded ``ALTER`` adds it only when
        missing — additive and non-destructive: existing rows take the column
        default (0, i.e. pursuit NOT stopped). A clean no-op once present.
        """
        if "pursuit_stopped" in await self._proactivity_columns():
            return
        await self._db().execute(
            "ALTER TABLE proactivity_state "
            "ADD COLUMN pursuit_stopped INTEGER NOT NULL DEFAULT 0"
        )

    async def _proactivity_columns(self) -> set[str]:
        """Names of the columns currently on ``proactivity_state``."""
        async with self._db().execute("PRAGMA table_info(proactivity_state)") as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _backfill_episodic_fts(self) -> None:
        """Reindex the whole episodic archive into ``episodic_fts`` (idempotent).

        The episodic FTS index (Fix A) ships after episodes were already being
        written, so a live db can hold turns that predate the index — they are
        invisible to recall until reindexed. FTS5's external-content ``rebuild``
        command reconstructs the index from ``episodic_log`` in one shot; it is
        idempotent (a no-op in effect when already in sync) and, at the MVP
        archive scale, cheap to run on every boot.
        """
        await self._db().execute("INSERT INTO episodic_fts (episodic_fts) VALUES ('rebuild')")

    async def close(self) -> None:
        """Close the underlying connection (idempotent)."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def journal_mode(self) -> str:
        """Return the active SQLite journal mode (expected ``wal``)."""
        async with self._db().execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        return "" if row is None else str(row[0])

    # --- Episodic memory ------------------------------------------------------

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        """Append one episodic event (raw mapping form); embed it on write."""
        cursor = await self._db().execute(
            "INSERT INTO episodic_log "
            "(ts, event_type, content, mood_snapshot, tags, sender_id, bob_message_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                episode["ts"],
                episode["event_type"],
                episode["content"],
                episode.get("mood_snapshot"),
                episode.get("tags", ""),
                episode.get("sender_id"),
                episode.get("bob_message_id"),
            ),
        )
        await self._db().commit()
        await self._embed_on_write(cursor.lastrowid, "episodic", episode["content"])

    async def save_episode_entity(self, event: EpisodicEvent) -> None:
        """Append an :class:`EpisodicEvent` domain entity."""
        await self.save_episode(
            {
                "ts": event.ts.isoformat(),
                "event_type": event.event_type,
                "content": event.content,
                "mood_snapshot": event.mood_snapshot,
                "tags": ",".join(event.tags),
                "sender_id": event.sender_id,
                "bob_message_id": event.bob_message_id,
            }
        )

    async def episode_by_bob_message_id(
        self, bob_message_id: int
    ) -> Mapping[str, object] | None:
        """Return the episode whose recorded outgoing Bob message is ``bob_message_id``.

        The BOB-050 link from a reaction back to what Bob said: a reaction carries the
        Telegram ``message_id`` it was placed on; this finds the episode that recorded
        that id as Bob's outgoing reply, so the perception use-case can read Bob's
        reply text. ``None`` when no episode matches (an old / non-Bob message), which
        the reaction filter treats as "not Bob's message" and drops. The most-recent
        match wins (a message_id is effectively unique per chat).
        """
        async with self._db().execute(
            "SELECT ts, event_type, content, mood_snapshot, tags, sender_id, "
            "bob_message_id FROM episodic_log WHERE bob_message_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (bob_message_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def load_episodes(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent episodes (newest first)."""
        async with self._db().execute(
            "SELECT ts, event_type, content, mood_snapshot, tags "
            "FROM episodic_log ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        """Return the last ``k`` episodes by recency, in chronological order.

        Selects the ``k`` newest rows, then reverses them so the result reads
        oldest-first — the natural order for replaying conversation history into a
        reply prompt. A non-positive ``k`` yields an empty sequence.
        """
        if k <= 0:
            return []
        async with self._db().execute(
            "SELECT ts, event_type, content, mood_snapshot, tags, sender_id "
            "FROM episodic_log ORDER BY ts DESC, id DESC LIMIT ?",
            (k,),
        ) as cursor:
            rows = list(await cursor.fetchall())
        rows.reverse()
        return [dict(row) for row in rows]

    async def recent_episodes_for(
        self, sender_id: int, k: int
    ) -> Sequence[Mapping[str, object]]:
        """Return the last ``k`` episodes WITH ``sender_id`` (chronological, BOB-045).

        The per-person read seam: selects the ``k`` newest rows attributed to one
        sender, then reverses them to oldest-first so the result replays that
        person's dialogue thread in order — mirrors :meth:`recent_episodes` but with
        a ``WHERE sender_id = ?`` filter. A non-positive ``k`` yields an empty
        sequence. Privacy follows by construction: each person sees only their own
        thread.
        """
        if k <= 0:
            return []
        async with self._db().execute(
            "SELECT ts, event_type, content, mood_snapshot, tags, sender_id "
            "FROM episodic_log WHERE sender_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
            (sender_id, k),
        ) as cursor:
            rows = list(await cursor.fetchall())
        rows.reverse()
        return [dict(row) for row in rows]

    # --- Consolidation (BOB-021) ----------------------------------------------

    async def select_consolidatable_episodes(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` OLD, un-consolidated, non-digest episodes (oldest first).

        The eligibility predicate is the consolidation guardrail: only episodes
        older than ``older_than`` that are not yet folded into a digest
        (``consolidated = 0``) and are not themselves a digest
        (``event_type != 'digest'``) — so a digest is never re-digested and a
        re-run with nothing eligible is a clean no-op. Oldest first so the digest
        provenance reads as a contiguous time window.
        """
        if limit <= 0:
            return []
        async with self._db().execute(
            "SELECT id, ts, event_type, content, mood_snapshot, tags "
            "FROM episodic_log "
            "WHERE consolidated = 0 AND event_type != 'digest' AND ts < ? "
            "ORDER BY ts ASC, id ASC LIMIT ?",
            (older_than.isoformat(), limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def save_digest(self, digest: Mapping[str, object]) -> None:
        """Write a digest as an ``episodic_log`` row (event_type='digest'); embed it.

        A digest is just an episode, so it is recalled by the hybrid the same as any
        other and the on-write embedding path (BOB-011) applies unchanged. The
        ``consolidated`` flag defaults to 0 but the select predicate excludes
        digests by ``event_type``, so it is never itself re-consolidated.
        """
        await self.save_episode(
            {
                "ts": digest["ts"],
                "event_type": "digest",
                "content": digest["content"],
                "mood_snapshot": digest.get("mood_snapshot"),
                "tags": digest.get("tags", ""),
            }
        )

    async def mark_consolidated(self, episode_ids: Sequence[int]) -> None:
        """Flag the given source episodes as folded into a digest (non-destructive).

        Sets ``consolidated = 1`` on each id — the originals are kept, only marked,
        so they drop out of future ``select_consolidatable_episodes`` calls. An
        empty id list is a no-op.
        """
        ids = list(episode_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        await self._db().execute(
            f"UPDATE episodic_log SET consolidated = 1 WHERE id IN ({placeholders})",  # noqa: S608
            ids,
        )
        await self._db().commit()

    # --- Fact dedup (BOB-021) -------------------------------------------------

    async def select_active_facts(self) -> Sequence[Mapping[str, object]]:
        """Return every ACTIVE (un-superseded) semantic fact, newest first.

        The dedup eligibility predicate: only facts not yet merged into a canonical
        one (``superseded_by IS NULL``) — so an already-merged duplicate is excluded
        and a re-run never re-merges it (idempotent). Each row carries ``id``, ``ts``
        and ``content`` so the use-case can embed, cluster by cosine and pick a
        canonical.
        """
        async with self._db().execute(
            "SELECT id, ts, category, content, confidence "
            "FROM semantic_memory WHERE superseded_by IS NULL "
            "ORDER BY ts DESC, id DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def supersede_facts(self, mapping: Mapping[int, int]) -> None:
        """Flag duplicate facts as superseded into their canonical fact (non-destructive).

        ``mapping`` is ``{duplicate_id: canonical_id}``: each duplicate's
        ``superseded_by`` is set to its canonical id — the row is kept (provenance
        intact), only marked, so it drops out of ``select_active_facts`` and recall.
        An empty mapping is a no-op.
        """
        if not mapping:
            return
        await self._db().executemany(
            "UPDATE semantic_memory SET superseded_by = ? WHERE id = ?",
            [(canonical_id, duplicate_id) for duplicate_id, canonical_id in mapping.items()],
        )
        await self._db().commit()

    # --- Semantic memory ------------------------------------------------------

    async def save_fact(self, fact: SemanticFact) -> None:
        """Persist a semantic fact (FTS via trigger); embed it on write."""
        cursor = await self._db().execute(
            "INSERT INTO semantic_memory (ts, category, content, confidence) VALUES (?, ?, ?, ?)",
            (fact.ts.isoformat(), fact.category, fact.content, fact.confidence),
        )
        await self._db().commit()
        await self._embed_on_write(cursor.lastrowid, "semantic", fact.content)

    async def load_facts(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent semantic facts (newest first)."""
        async with self._db().execute(
            "SELECT ts, category, content, confidence "
            "FROM semantic_memory ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Mood -----------------------------------------------------------------

    async def set_mood(self, state: StateBlob, *, at: datetime) -> None:
        """Replace the current mood and append a snapshot to history."""
        blob = json.dumps(dict(state))
        ts = at.isoformat()
        await self._db().execute(
            "INSERT INTO mood_state (id, state, ts) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state = excluded.state, ts = excluded.ts",
            (_MOOD_ROW_ID, blob, ts),
        )
        await self._db().execute(
            "INSERT INTO mood_history (state, ts) VALUES (?, ?)", (blob, ts)
        )
        await self._db().commit()

    async def get_mood(self) -> dict[str, object] | None:
        """Return the current mood blob, or ``None`` if never set."""
        async with self._db().execute(
            "SELECT state FROM mood_state WHERE id = ?", (_MOOD_ROW_ID,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _loads_object(row[0])

    async def mood_history(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent mood snapshots (newest first)."""
        async with self._db().execute(
            "SELECT state, ts FROM mood_history ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"state": _loads_object(row[0]), "ts": row[1]} for row in rows]

    # --- Taste axes -----------------------------------------------------------

    async def set_taste_axis(
        self,
        axis: str,
        *,
        value: float,
        conviction: float,
        experience_count: int,
    ) -> None:
        """Upsert one taste axis (no duplicate rows for the same axis)."""
        await self._db().execute(
            "INSERT INTO taste_axes (axis, value, conviction, experience_count) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(axis) DO UPDATE SET "
            "value = excluded.value, conviction = excluded.conviction, "
            "experience_count = excluded.experience_count",
            (axis, value, conviction, experience_count),
        )
        await self._db().commit()

    async def load_taste_axes(self) -> Sequence[Mapping[str, object]]:
        """Return all taste axes ordered by name."""
        async with self._db().execute(
            "SELECT axis, value, conviction, experience_count FROM taste_axes ORDER BY axis"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Relationship ---------------------------------------------------------

    async def set_relationship(self, state: StateBlob) -> None:
        """Replace the relationship state (single-row JSON blob)."""
        await self._db().execute(
            "INSERT INTO relationship (id, state) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state = excluded.state",
            (_RELATIONSHIP_ROW_ID, json.dumps(dict(state))),
        )
        await self._db().commit()

    async def get_relationship(self) -> dict[str, object] | None:
        """Return the relationship blob, or ``None`` if never set."""
        async with self._db().execute(
            "SELECT state FROM relationship WHERE id = ?", (_RELATIONSHIP_ROW_ID,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _loads_object(row[0])

    # --- Key/value ------------------------------------------------------------

    async def kv_set(self, key: str, value: str) -> None:
        """Set ``key`` to ``value`` in the generic key/value store."""
        await self._db().execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._db().commit()

    async def kv_get(self, key: str) -> str | None:
        """Return the value for ``key``, or ``None`` if absent."""
        async with self._db().execute("SELECT value FROM kv WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
        return None if row is None else str(row[0])

    # --- Vector store ---------------------------------------------------------

    async def vector_count(self, *, source: VectorSource | None = None) -> int:
        """Number of stored embeddings, optionally restricted to one source."""
        return await self._vector_store().count(source)

    async def vector_knn(
        self, vector: Sequence[float], *, k: int
    ) -> list[dict[str, object]]:
        """Top-``k`` nearest-neighbour memories to ``vector`` (semantic recall).

        Delegates to the vector store's KNN: each hit carries ``content``,
        ``source``, ``category`` and ``distance``. The hybrid-recall adapter fuses
        this with FTS5 keyword hits.
        """
        return await self._vector_store().knn(vector, k)

    async def _embed_on_write(
        self, src_id: int | None, source: VectorSource, content: object
    ) -> None:
        """Embed a just-inserted row's content into the vector store (best-effort)."""
        if src_id is None:
            return
        await self._vector_store().embed_row(source, src_id, str(content))

    def _vector_store(self) -> MemoryVectorStore:
        if self._vectors is None:
            raise RuntimeError("SqliteMemoryRepo used before initialize()")
        return self._vectors

    # --- Internals ------------------------------------------------------------

    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteMemoryRepo used before initialize()")
        return self._conn

    @property
    def connection(self) -> aiosqlite.Connection:
        """The live connection (for collaborators such as the recall adapter)."""
        return self._db()


def _load_schema() -> str:
    """Read the bundled ``schema.sql`` from the package."""
    return resources.files(__package__).joinpath(_SCHEMA_RESOURCE).read_text(encoding="utf-8")


def _name_prefix(content: str) -> str:
    """The leading ``"<name>: "`` author label of an episode's content (BOB-045 backfill).

    Episode content is ``"<name>: …\\nbob: …"``; the author name is the text before
    the first ``": "`` on the first line. Returns ``""`` when there is no such
    prefix (an unattributable row), which never matches a known sender id.
    """
    first_line = content.split("\n", 1)[0]
    name, sep, _rest = first_line.partition(": ")
    return name if sep else ""


def _loads_object(raw: object) -> dict[str, object]:
    """Decode a JSON object blob into a dict (defensive on row types)."""
    decoded = json.loads(str(raw))
    if not isinstance(decoded, dict):
        raise ValueError("expected a JSON object in state blob")
    return decoded
