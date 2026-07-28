# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=infrastructure

"""Personality infrastructure adapters — the outward edges of the character seams.

Realise the personality ports over concrete backends: the Tier-0 LLM reaction judge
and the SQLite / kv-backed per-persona fascination store and light notable-reaction
store. Nothing here is imported by the pure ``ports`` / domain halves.
"""
