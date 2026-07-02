# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Social ports — the durable authorization + soul-artifact seams.

The runtime allowlist store (:class:`AllowlistStore`) backing the authorizer, and
the on-disk soul reader/writer (:class:`SoulStore`). These are *interfaces only*:
structural :class:`typing.Protocol` definitions with no implementations; the
SQLite / file-backed adapters live in ``bob.infrastructure``. :class:`SoulStore`
carries :data:`~bob.domain.ports.kernel.JsonValue` — its only cross-bucket dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.domain.ports.kernel import JsonValue


@runtime_checkable
class AllowlistStore(Protocol):
    """Durable store for the runtime authorization allowlist (user ids).

    Backs the :class:`bob.application.authz.Authorizer`: ``/authorize`` adds a
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
