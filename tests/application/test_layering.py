# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: the application layer must not depend on infrastructure.

The declared hexagon is ``infrastructure → application → domain``: the
application orchestrates the pure domain through port protocols and never
imports ``bob.infrastructure`` (runtime or ``TYPE_CHECKING``). This test scans
every application source file (the source of truth, since ``from __future__
import annotations`` makes type-only imports invisible to ``sys.modules``) and
fails on any line that *imports* from ``bob.infrastructure``.
"""

from __future__ import annotations

import re
from pathlib import Path

import bob.application

_APP_ROOT = Path(bob.application.__file__).parent

# Matches `import bob.infrastructure...` or `from bob.infrastructure... import`,
# the actual layering breach — a mention in a docstring is fine.
_INFRA_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+bob\.infrastructure", re.MULTILINE
)


def test_no_application_module_imports_infrastructure() -> None:
    offenders = [
        path.relative_to(_APP_ROOT).as_posix()
        for path in _APP_ROOT.rglob("*.py")
        if _INFRA_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        f"application modules must not import from bob.infrastructure: {offenders}"
    )
