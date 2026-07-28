# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Social module («кто этот человек») — Bob's social identity + authorization vertical.

The full social slice in one bounded context (domain-first slice BOB-062.5): who is
writing (:mod:`interlocutor`), the per-person first impression / relationship and the
per-persona обида (sulk) value objects, the permission domain (``permission/``) and
the port protocols (``ports.py``); the ``usecases`` half (authorization / sender &
reactor perception, the privilege flow + execution, the first-impression / relationship
/ sulk source trackers, and Genesis); and the ``adapters`` half (the SQLite / file /
kv-backed identity stores + the Tier-0 privilege judge).

The package facade re-exports only the stable *ports* — the social contract the outer
layers depend on.
"""

from __future__ import annotations

from bob.social.ports import (
    AllowlistStore,
    FirstImpressionStore,
    PrivilegeJudge,
    RelationshipStore,
    SoulStore,
    SulkStore,
)

__all__ = [
    "AllowlistStore",
    "FirstImpressionStore",
    "PrivilegeJudge",
    "RelationshipStore",
    "SoulStore",
    "SulkStore",
]
