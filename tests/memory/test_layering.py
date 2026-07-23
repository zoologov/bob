# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: the ``memory`` module's application layer stays pure.

After BOB-062.2, ``bob.memory.usecases`` (``layer=application``) left the reach
of :mod:`tests.application.test_layering`, whose scan is rooted at
``bob.application`` and no longer covers the relocated use-cases. The Beadloom
AaC rules (``memory-usecases-no-adapters`` etc.) forbid these breaches at lint
time, but that check only sees *runtime* import edges — ``from __future__ import
annotations`` makes ``TYPE_CHECKING``-only imports invisible to it.

This source-text scan closes that gap the same way the application guard does:
the memory use-cases orchestrate the pure ``bob.memory`` domain through port
protocols and must never *import* infrastructure — neither ``bob.infrastructure``
(the shared persistence kernel deferred to slice .7) nor the module's own
``bob.memory.adapters`` (``layer=infrastructure``) — in runtime **or**
``TYPE_CHECKING`` position. A ``:class:`` mention in a docstring is fine; only a
real ``from``/``import`` statement is a breach.
"""

from __future__ import annotations

import re
from pathlib import Path

import bob.memory.usecases

_USECASES_ROOT = Path(bob.memory.usecases.__file__).parent

# Matches an actual import statement pulling in the infrastructure kernel or the
# module's own infrastructure-layer adapters — NOT a docstring `:class:` ref.
_INFRA_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+bob\.(?:infrastructure|memory\.adapters)\b",
    re.MULTILINE,
)


def test_no_memory_usecase_imports_infrastructure() -> None:
    offenders = [
        path.relative_to(_USECASES_ROOT).as_posix()
        for path in _USECASES_ROOT.rglob("*.py")
        if _INFRA_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "bob.memory.usecases (layer=application) must not import infrastructure "
        f"(bob.infrastructure or bob.memory.adapters): {offenders}"
    )
