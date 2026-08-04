# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=infrastructure

"""Live-terminal infrastructure adapters (BOB-083 .2).

Realise the module's outward transport port
(:class:`~bob.coding.ports.InteractiveRunner`) with the same FIXED-form, shell-free
subprocess discipline as the gated coder: :class:`InteractiveClaudeRunner` holds a
LONG-LIVED ``claude -p --input-format stream-json`` process with an OPEN stdin, so the
owner can steer it in real time, and reads its NDJSON output through the shared
:mod:`bob.coding.stream_json` primitive.
"""
