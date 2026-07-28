# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=infrastructure

"""Conversation infrastructure adapters — the outward edges of the turn seams.

Realise the conversation ports over concrete backends: the Tier-0 LLM response /
volatility / interim-line judges and the SQLite-backed conversation-floor store and
cross-session closer log. Nothing here is imported by the pure ``ports`` / domain
halves.
"""
