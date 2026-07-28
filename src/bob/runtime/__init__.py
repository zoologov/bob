# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition root + entrypoint — assemble every layer into the running GUPPI process.

The ONLY package allowed to depend on all layers at once: it loads config, builds the real
adapters, composes the application policy + heartbeat ticks, and starts the runtime.

🔴 Name collision (deliberate): this is ``bob.runtime`` — the composition root / entrypoint.
It is NOT ``bob.application.runtime``, which holds the async execution primitives
(``AgentRuntime`` / ``AsyncEventBus`` / ``periodic``) that this package *starts*. The two
stay separate: composition (here) vs. the running event loop (there).

Layout: :mod:`composition` (``build_application`` + ``Application``), :mod:`main`
(the entrypoint), :mod:`clock` (the time seams), :mod:`config` (tuned defaults + readers),
and :mod:`wiring` (the ``_build_*`` factories).
"""

from __future__ import annotations

from bob.runtime.clock import SystemClock
from bob.runtime.composition import (
    Application,
    _as_handler,
    _as_reaction_handler,
    build_application,
)

# NB: ``main`` is intentionally NOT re-exported here. Binding the ``main`` function into
# this package namespace would shadow the :mod:`bob.runtime.main` submodule (so
# ``import bob.runtime.main`` would resolve to the function, not the module). Import the
# entrypoint from its submodule: ``from bob.runtime.main import main``.

__all__ = [
    "Application",
    "SystemClock",
    "_as_handler",
    "_as_reaction_handler",
    "build_application",
]
