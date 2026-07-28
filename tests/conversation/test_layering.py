# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: the ``conversation`` module keeps its layers pure.

After BOB-062.6a, ``bob.conversation`` became a vertical bounded-context — «how
the turn is conducted»: addressivity / floor / brevity / engagement / judges /
interim / anti-tic. Its use-cases (``bob.conversation.usecases``,
``layer=application`` — ``decide_response``) and its pure domain core
(``layer=domain``) left the reach of :mod:`tests.application.test_layering`,
mirroring the ``personality`` (see :mod:`tests.personality.test_layering`),
``social``, ``capabilities``, ``memory`` and ``proactivity`` slices.

Beadloom's AaC rules forbid these breaches at lint time, but that check only sees
*runtime* import edges — ``TYPE_CHECKING`` imports are invisible to it. This
source-text scan closes that gap and pins the cycle-break landed by BOB-062.6a:

* **usecases (application) must not import infrastructure** — neither the shared
  ``bob.infrastructure`` kernel nor the module's own ``bob.conversation.adapters``.
* **domain internals must not import infrastructure** — the pure turn-logic core
  (``layer=domain``) must not reach infrastructure.
* **conversation → personality is one-way (positive invariant)** — the
  ``voice↔brevity`` cycle was broken by moving ``Verbosity``/``EngagementLevel``
  into ``personality.expression``; the computing logic (``brevity``/``engagement``/
  ``zone_classifier``) stays here and now *returns* personality value-objects. So
  the legal edge conversation → personality must be present, while the reverse
  (personality → conversation) stays absent (pinned in
  :mod:`tests.personality.test_layering`).

A ``:class:`` mention in a docstring is fine; only a real ``from``/``import``
statement is a breach.
"""

from __future__ import annotations

import re
from pathlib import Path

import bob.conversation

_MODULE_ROOT = Path(bob.conversation.__file__).parent
_USECASES_ROOT = _MODULE_ROOT / "usecases"
_ADAPTERS_ROOT = _MODULE_ROOT / "adapters"

_INFRA_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+bob\.(?:infrastructure|conversation\.adapters)\b",
    re.MULTILINE,
)


def _offenders(root: Path, pattern: re.Pattern[str]) -> list[str]:
    return sorted(
        path.relative_to(_MODULE_ROOT).as_posix()
        for path in root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    )


def test_no_conversation_usecase_imports_infrastructure() -> None:
    # Arrange / Act
    offenders = _offenders(_USECASES_ROOT, _INFRA_IMPORT)
    # Assert
    assert offenders == [], (
        "bob.conversation.usecases (layer=application) must not import "
        "infrastructure (bob.infrastructure or bob.conversation.adapters): "
        f"{offenders}"
    )


def test_no_conversation_domain_imports_infrastructure() -> None:
    # Arrange: the domain core is everything EXCEPT usecases/ + adapters/.
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
        "bob.conversation domain internals (layer=domain) must not import "
        "infrastructure (bob.infrastructure or bob.conversation.adapters): "
        f"{offenders}"
    )


def test_conversation_depends_on_personality_one_way_only() -> None:
    # 🔴 BOB-062.6a decision: the voice↔brevity cycle was broken by moving the
    # Verbosity/EngagementLevel enum *definitions* into personality.expression.
    # The computing logic stays in conversation and now imports those enums back
    # from personality — the legal, cycle-free direction conversation →
    # personality. Here we pin the positive half of the invariant: the edge is
    # present (so the personality-side guard is proving "no reverse import", not
    # "no coupling at all"). Beadloom's ``no-dependency-cycles`` enforces the
    # absence of the reverse edge at lint time (probe on bob-8r4.6.4).
    brevity_src = (_MODULE_ROOT / "brevity.py").read_text(encoding="utf-8")
    engagement_src = (_MODULE_ROOT / "engagement.py").read_text(encoding="utf-8")
    assert "from bob.personality.expression import" in brevity_src, (
        "conversation.brevity must import its Verbosity result type from "
        "personality.expression (the one-way conversation → personality edge)"
    )
    assert "from bob.personality.expression import" in engagement_src, (
        "conversation.engagement must import its EngagementLevel result type "
        "from personality.expression (the one-way conversation → personality edge)"
    )
