# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: the ``proactivity`` module keeps its layers pure.

After BOB-062.3, ``bob.proactivity.usecases`` (``layer=application``) left the
reach of :mod:`tests.application.test_layering`, whose scan is rooted at
``bob.application`` and no longer covers the relocated use-cases (mirrors the
``memory`` slice, see :mod:`tests.memory.test_layering`). The Beadloom AaC rules
(``proactivity-usecases-no-adapters`` etc.) forbid the *usecases* breaches at
lint time, but that check only sees *runtime* import edges — ``from __future__
import annotations`` makes ``TYPE_CHECKING``-only imports invisible to it.

This source-text scan closes two gaps the lint caraff leaves open:

* **usecases (application) must not import infrastructure** — neither the shared
  ``bob.infrastructure`` kernel (deferred to slice .7) nor the module's own
  ``bob.proactivity.adapters`` (``layer=infrastructure``), in runtime *or*
  ``TYPE_CHECKING`` position. (Lint guards the runtime edges; this adds the
  ``TYPE_CHECKING`` ones.)
* **domain internals must not import infrastructure** — the pure drive/goals/
  self-improvement core (``layer=domain``) must not reach ``bob.infrastructure``
  or ``bob.proactivity.adapters``. There is *no* ``proactivity-internals-no-
  adapters`` AaC rule (a class-wide gap: no vertical has one), so this test is
  the only guard against a domain module importing its own adapters.

A ``:class:`` mention in a docstring is fine; only a real ``from``/``import``
statement is a breach.
"""

from __future__ import annotations

import re
from pathlib import Path

import bob.proactivity

_MODULE_ROOT = Path(bob.proactivity.__file__).parent
_USECASES_ROOT = _MODULE_ROOT / "usecases"
_ADAPTERS_ROOT = _MODULE_ROOT / "adapters"

# Matches an actual import statement pulling in the infrastructure kernel or the
# module's own infrastructure-layer adapters — NOT a docstring `:class:` ref.
_INFRA_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+bob\.(?:infrastructure|proactivity\.adapters)\b",
    re.MULTILINE,
)


def _offenders(root: Path, pattern: re.Pattern[str]) -> list[str]:
    return sorted(
        path.relative_to(_MODULE_ROOT).as_posix()
        for path in root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    )


def test_no_proactivity_usecase_imports_infrastructure() -> None:
    # Arrange / Act
    offenders = _offenders(_USECASES_ROOT, _INFRA_IMPORT)
    # Assert
    assert offenders == [], (
        "bob.proactivity.usecases (layer=application) must not import "
        "infrastructure (bob.infrastructure or bob.proactivity.adapters): "
        f"{offenders}"
    )


def test_no_proactivity_domain_imports_infrastructure() -> None:
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
        "bob.proactivity domain internals (layer=domain) must not import "
        "infrastructure (bob.infrastructure or bob.proactivity.adapters): "
        f"{offenders}"
    )
