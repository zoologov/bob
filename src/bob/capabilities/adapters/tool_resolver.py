# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=infrastructure

"""Resolving a configured tool to something this host can actually execute.

The single point of filesystem contact behind
:func:`bob.capabilities.tool_availability.assess_tools`, kept out of the core so the
verdict stays pure and mutation-testable (§0.2).

🔴 ``shutil.which`` is used for BOTH shapes on purpose, because it answers the only
question that matters — can this be run here?
* a bare name (``beadloom``) is searched on ``PATH`` — the same ``PATH`` the process
  will hand to ``create_subprocess_exec``, so the check and the real call agree;
* an absolute path (``/Users/…/mmdc``) is returned only when it EXISTS and is
  EXECUTABLE, which is precisely how a path inherited from another machine is caught
  (Issues #62). Testing the string instead would have passed it: it was a perfectly
  well-formed path, just not one that exists on this host.
"""

from __future__ import annotations

import shutil


def resolve_tool(configured: str) -> str | None:
    """Return an executable path for ``configured``, or ``None`` if unreachable here."""
    if not configured.strip():
        return None
    return shutil.which(configured)
