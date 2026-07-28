# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Application layer — GUPPI use-cases and orchestration.

Depends on the domain modules (through their port protocols); it never imports
``bob.infrastructure``. Concrete adapters are bound to ports in ``bob.app``.
"""
