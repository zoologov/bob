# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=infrastructure

"""Capabilities infrastructure adapters — the outward edges of Bob's tool seam.

Realise the capability ports over concrete backends: ``web`` (aiohttp URL reader
behind an SSRF guard + its factory), ``diagrams`` (mermaid ``mmdc`` renderer),
``introspection`` (subprocess ``beadloom`` / ``bd`` / ``git`` read backend) and
``web_search_qwen`` (the Qwen MaaS web-search transport). Nothing here is imported
by the pure ``ports`` / ``diagrams`` / ``introspection`` domain halves.
"""
