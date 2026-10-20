# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The shared kernel imports in isolation — BOB-113 (RFC C).

``bob.kernel`` is the neutral surface every module may import precisely because it
imports NO module back: the moment a kernel file reaches into ``bob.memory`` /
``bob.social`` / … the "inward-safe, no cycles" promise is gone, and the contracts
that moved here (intake events, memory/reply/tool-calling ports, rule modulators,
``Recalled``) would drag their old owners along with them.

The check is the BEHAVIOUR of the assembled package, not the form of its source: every
kernel module is imported in a fresh, isolated interpreter (``-I``, so neither the
working directory nor ``PYTHONPATH`` leaks a sibling in), and the set of loaded
``bob.*`` modules must be ``bob`` + ``bob.kernel.*`` and nothing else. A lazy or
``TYPE_CHECKING`` import that only fires at runtime is out of reach of this test by
design — the import-cycle gates cover those; this one owns "importing the kernel loads
no module".
"""

from __future__ import annotations

import json
import subprocess
import sys

# Imports every module of the ``bob.kernel`` package (discovered, not listed — a new
# kernel file is covered the day it lands) and prints the loaded ``bob`` modules.
_PROBE = """
import importlib, json, pkgutil, sys
import bob.kernel as kernel
for info in pkgutil.iter_modules(kernel.__path__, prefix="bob.kernel."):
    importlib.import_module(info.name)
print(json.dumps(sorted(m for m in sys.modules if m == "bob" or m.startswith("bob."))))
"""


def _loaded_bob_modules() -> list[str]:
    result = subprocess.run(  # noqa: S603 — fixed argv: this interpreter + a constant probe
        [sys.executable, "-I", "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded: list[str] = json.loads(result.stdout)
    return loaded


def test_importing_every_kernel_module_loads_no_other_bob_module() -> None:
    """Only ``bob`` and ``bob.kernel.*`` are loaded — the kernel pulls in no module."""
    loaded = _loaded_bob_modules()
    leaked = [m for m in loaded if m != "bob" and not m.startswith("bob.kernel")]
    assert leaked == []


def test_the_contracts_moved_by_bob_113_are_kernel_modules() -> None:
    """The probe really reached the new homes (a vacuous empty import would pass above)."""
    loaded = set(_loaded_bob_modules())
    assert {
        "bob.kernel.events",
        "bob.kernel.ports",
        "bob.kernel.modulators",
        "bob.kernel.episode_types",
    } <= loaded
