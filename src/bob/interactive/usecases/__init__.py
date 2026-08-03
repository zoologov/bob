# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:feature=interactive
# beadloom:layer=application

"""Interactive use-cases — orchestration of the live «Bob holds a terminal» session.

The application layer of the ``interactive`` module: it drives ONE live bidirectional
``claude`` session over the pure domain here and the shared coding ports
(:mod:`bob.coding.ports`), keeping I/O at the edges (``adapters/``) and the rules in
the pure domain.
"""
