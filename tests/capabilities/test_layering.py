# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: the ``capabilities`` module keeps its layers pure.

After BOB-062.4, ``bob.capabilities`` became a vertical module: its use-cases
(``bob.capabilities.usecases``, ``layer=application``) and its pure domain core
(``ports`` / ``diagrams`` / ``introspection``, ``layer=domain``) left the reach of
:mod:`tests.application.test_layering` (rooted at ``bob.application``), mirroring
the ``memory`` (see :mod:`tests.memory.test_layering`) and ``proactivity`` (see
:mod:`tests.proactivity.test_layering`) slices.

The Beadloom AaC rules (``capabilities-usecases-no-adapters``,
``capabilities-usecases-no-infra``, ``capabilities-internals-no-adapters``) forbid
these breaches at lint time, but that check only sees *runtime* import edges —
``from __future__ import annotations`` makes ``TYPE_CHECKING``-only imports
invisible to it. This source-text scan closes that gap:

* **usecases (application) must not import infrastructure** — neither the shared
  ``bob.infrastructure`` kernel nor the module's own ``bob.capabilities.adapters``
  (``layer=infrastructure``), in runtime *or* ``TYPE_CHECKING`` position.
* **domain internals must not import infrastructure** — the pure ports/diagrams/
  introspection core (``layer=domain``) must not reach ``bob.infrastructure`` or
  ``bob.capabilities.adapters``.

A ``:class:`` mention in a docstring is fine; only a real ``from``/``import``
statement is a breach.
"""

from __future__ import annotations

import re
from pathlib import Path

import bob.capabilities

_MODULE_ROOT = Path(bob.capabilities.__file__).parent
_USECASES_ROOT = _MODULE_ROOT / "usecases"
_ADAPTERS_ROOT = _MODULE_ROOT / "adapters"

# Matches an actual import statement pulling in the infrastructure kernel or the
# module's own infrastructure-layer adapters — NOT a docstring `:class:` ref.
_INFRA_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+bob\.(?:infrastructure|capabilities\.adapters)\b",
    re.MULTILINE,
)


def _offenders(root: Path, pattern: re.Pattern[str]) -> list[str]:
    return sorted(
        path.relative_to(_MODULE_ROOT).as_posix()
        for path in root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    )


def test_no_capabilities_usecase_imports_infrastructure() -> None:
    # Arrange / Act
    offenders = _offenders(_USECASES_ROOT, _INFRA_IMPORT)
    # Assert
    assert offenders == [], (
        "bob.capabilities.usecases (layer=application) must not import "
        "infrastructure (bob.infrastructure or bob.capabilities.adapters): "
        f"{offenders}"
    )


def test_no_capabilities_domain_imports_infrastructure() -> None:
    # Arrange: the domain core is everything under the module EXCEPT its
    # usecases/ (application) and adapters/ (infrastructure) subtrees.
    domain_files = [
        path
        for path in _MODULE_ROOT.rglob("*.py")
        if _USECASES_ROOT not in path.parents
        and _ADAPTERS_ROOT not in path.parents
    ]
    # Act
    offenders = sorted(
        path.relative_to(_MODULE_ROOT).as_posix()
        for path in domain_files
        if _INFRA_IMPORT.search(path.read_text(encoding="utf-8"))
    )
    # Assert
    assert offenders == [], (
        "bob.capabilities domain internals (layer=domain) must not import "
        "infrastructure (bob.infrastructure or bob.capabilities.adapters): "
        f"{offenders}"
    )
