# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Domain layer — pure logic, models, and port protocols.

The domain imports nothing outward (no ``bob.application`` / ``bob.infrastructure``,
no I/O, no transport, no LLM). Adapters realise the ports declared here and are
wired only in ``bob.app``.
"""
