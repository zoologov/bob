# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:feature=coding
# beadloom:layer=application

"""Coding use-cases — orchestration of the «Bob writes code» capability.

The application layer of the ``coding`` module: it drives the gated coding
session over the domain (through :mod:`bob.coding.ports`) and the ``adapters``
implementations, keeping I/O at the edges and rules in the pure domain.
"""
