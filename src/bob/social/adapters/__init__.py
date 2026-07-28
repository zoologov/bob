# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""Social infrastructure adapters — the outward edges of Bob's social identity seam.

Realise the social ports over concrete backends: the per-person first-impression /
relationship stores and the per-persona обида (sulk) store + the pending
permission-request store (all over the shared SQLite ``connection()`` seam), the kv
allowlist store, the file-backed soul store, and the Tier-0 LLM privilege judge.
Nothing here is imported by the pure ``ports`` / ``permission`` domain halves.
"""
