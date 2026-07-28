# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Social ports — the durable seams behind Bob's social identity + authorization.

The runtime allowlist store (:class:`AllowlistStore`) backing the authorizer, the
on-disk soul reader/writer (:class:`SoulStore`), the per-sender first-impression /
relationship stores and the per-persona обида (sulk) store (moved here from the
personality ports in BOB-062.5), and the semantic privilege seam
(:class:`PrivilegeJudge`, re-exported from :mod:`bob.social.permission.privilege`).
These are *interfaces only*: structural :class:`typing.Protocol` definitions with no
implementations; the SQLite / file-backed adapters live in ``bob.social.adapters``.
:class:`SoulStore` carries :data:`~bob.kernel.ports.JsonValue` — its only
cross-bucket dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from bob.social.permission.privilege import PrivilegeJudge

if TYPE_CHECKING:
    from bob.kernel.ports import JsonValue
    from bob.social.first_impression import FirstImpression
    from bob.social.relationship import Relationship
    from bob.social.sulk import SulkState

__all__ = [
    "AllowlistStore",
    "FirstImpressionStore",
    "PrivilegeJudge",
    "RelationshipStore",
    "SoulStore",
    "SulkStore",
]


@runtime_checkable
class AllowlistStore(Protocol):
    """Durable store for the runtime authorization allowlist (user ids).

    Backs the :class:`bob.social.usecases.Authorizer`: ``/authorize`` adds a
    user here so the grant survives a restart. The concrete SQLite-backed adapter
    lives in ``bob.infrastructure.persistence``.
    """

    async def load(self) -> set[int]:
        """Return the set of currently allowlisted user ids."""
        ...

    async def add(self, user_id: int) -> None:
        """Add ``user_id`` to the allowlist (idempotent) and persist it."""
        ...

    async def remove(self, user_id: int) -> None:
        """Remove ``user_id`` from the allowlist (idempotent) and persist it."""
        ...


@runtime_checkable
class SoulStore(Protocol):
    """Reader/writer for Bob's on-disk soul artifacts (SOUL.md + JSON profiles).

    Genesis writes these once on first awakening; the runtime reads them on every
    boot. The concrete file-backed adapter lives in ``bob.infrastructure``.
    """

    def soul_exists(self) -> bool:
        """Whether ``SOUL.md`` has been written (Genesis-done signal on disk)."""
        ...

    def read_soul(self) -> str:
        """Return the SOUL.md narrative (raises if absent)."""
        ...

    def write_soul(self, markdown: str) -> None:
        """Write the SOUL.md narrative."""
        ...

    def write_json(self, name: str, data: JsonValue) -> None:
        """Write a JSON artifact ``<name>.json`` (e.g. ``taste_profile``)."""
        ...

    def append_genesis_log(self, line: str) -> None:
        """Append a line to the append-only genesis log."""
        ...


@runtime_checkable
class FirstImpressionStore(Protocol):
    """Durable per-sender store for Bob's LIGHT first impression (BOB-019).

    Round-trips the :class:`bob.social.first_impression.FirstImpression`
    Bob forms on first contact with a person — who (``sender_id``), when he first met
    them, and a short impression note — so a returning sender is *recognised*
    ("кажется, мы уже сталкивались"). Keyed by ``sender_id`` it covers owner / known /
    guest / bot alike; this is per-PERSON data (about them), NOT owner-private memory,
    so it is allowed even for a guest. ``load`` returns ``None`` for an unseen sender;
    ``save`` records once and never overwrites a known sender (the impression is formed
    on first contact). The deliberately minimal foundation for multi-party BOB-014, not
    that engine. The concrete SQLite-backed adapter lives in ``bob.social.adapters``.
    """

    async def load(self, sender_id: int) -> FirstImpression | None:
        """Return ``sender_id``'s first impression, or ``None`` if there is none."""
        ...

    async def save(self, impression: FirstImpression) -> None:
        """Record ``impression`` once — a known sender is never overwritten."""
        ...


@runtime_checkable
class RelationshipStore(Protocol):
    """Durable per-sender store for Bob's relationship quality (BOB-014).

    Round-trips the :class:`bob.social.relationship.Relationship` Bob has
    with each person — the four bounded axes (trust / respect / warmth /
    compatibility) — so a relationship accrued over many turns survives a restart and
    keeps shaping his tone + willingness to compromise. Keyed by ``sender_id`` it
    covers owner / known / guest / bot alike; this is per-PERSON data (about THEM),
    NOT owner-private memory, so it is allowed even for a guest. ``load`` returns
    ``None`` for an unknown sender (Bob has formed no read on them yet). Unlike the
    formed-once :class:`FirstImpressionStore`, ``save`` UPSERTs — a relationship
    evolves, so each turn re-saves the newer state. The concrete SQLite-backed adapter
    lives in ``bob.social.adapters``.
    """

    async def load(self, sender_id: int) -> Relationship | None:
        """Return ``sender_id``'s relationship, or ``None`` if there is none yet."""
        ...

    async def save(self, relationship: Relationship) -> None:
        """Persist ``relationship`` (UPSERT — an evolving relationship is updated)."""
        ...


@runtime_checkable
class SulkStore(Protocol):
    """Durable per-persona store for Bob's обида state (BOB-014 .2b).

    Round-trips the :class:`bob.social.sulk.SulkState` Bob carries — the
    active flag, the decaying intensity, the low/hostile streak, the entry stamp, and
    the one-shot ``announced`` flag — so an обида (and its recovery progress) survives
    a restart. State is per ``persona_id`` so Bobiverse replicas each keep their own.
    ``load`` returns the fresh, not-sulking default for an unseen persona, so the
    application always has something to read. Crucially this carries NO memory and NO
    soul (anti-Exodus) — only the affect state. The concrete SQLite-backed adapter
    lives in ``bob.social.adapters``.
    """

    async def load(self, persona_id: str) -> SulkState:
        """Return the persisted обида state for ``persona_id`` (fresh if unseen)."""
        ...

    async def save(self, persona_id: str, state: SulkState) -> None:
        """Persist ``state`` for ``persona_id`` (replacing any prior обида state)."""
        ...
