# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: the ``social`` module keeps its layers pure.

After BOB-062.5, ``bob.social`` became a vertical module: its use-cases
(``bob.social.usecases``, ``layer=application`` — authorizer / permission flow /
genesis / *_sources / perception) and its pure domain core (``interlocutor`` /
``first_impression`` / ``relationship`` / ``sulk`` / ``ports`` / ``permission``,
``layer=domain``) left the reach of :mod:`tests.application.test_layering` (rooted
at ``bob.application``), mirroring the ``capabilities`` (see
:mod:`tests.capabilities.test_layering`), ``memory`` (see
:mod:`tests.memory.test_layering`) and ``proactivity`` (see
:mod:`tests.proactivity.test_layering`) slices.

The Beadloom AaC rules forbid these breaches at lint time, but that check only
sees *runtime* import edges — ``from __future__ import annotations`` makes
``TYPE_CHECKING``-only imports invisible to it. This source-text scan closes that
gap (it is also what keeps the ``soul_store`` ``JsonValue`` seam honest — its
infra type stays a ``TYPE_CHECKING`` import in adapters, never leaking into the
domain core):

* **usecases (application) must not import infrastructure** — neither the shared
  ``bob.infrastructure`` kernel nor the module's own ``bob.social.adapters``
  (``layer=infrastructure``), in runtime *or* ``TYPE_CHECKING`` position.
* **domain internals must not import infrastructure** — the pure identity /
  relationship / permission core (``layer=domain``) must not reach
  ``bob.infrastructure`` or ``bob.social.adapters``.

A ``:class:`` mention in a docstring is fine; only a real ``from``/``import``
statement is a breach.
"""

from __future__ import annotations

import re
from pathlib import Path

import bob.social

_MODULE_ROOT = Path(bob.social.__file__).parent
_USECASES_ROOT = _MODULE_ROOT / "usecases"
_ADAPTERS_ROOT = _MODULE_ROOT / "adapters"

# Matches an actual import statement pulling in the infrastructure kernel or the
# module's own infrastructure-layer adapters — NOT a docstring `:class:` ref.
_INFRA_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+bob\.(?:infrastructure|social\.adapters)\b",
    re.MULTILINE,
)


def _offenders(root: Path, pattern: re.Pattern[str]) -> list[str]:
    return sorted(
        path.relative_to(_MODULE_ROOT).as_posix()
        for path in root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    )


def test_no_social_usecase_imports_infrastructure() -> None:
    # Arrange / Act
    offenders = _offenders(_USECASES_ROOT, _INFRA_IMPORT)
    # Assert
    assert offenders == [], (
        "bob.social.usecases (layer=application) must not import "
        "infrastructure (bob.infrastructure or bob.social.adapters): "
        f"{offenders}"
    )


def test_no_social_domain_imports_infrastructure() -> None:
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
        "bob.social domain internals (layer=domain) must not import "
        "infrastructure (bob.infrastructure or bob.social.adapters): "
        f"{offenders}"
    )


def test_social_depends_on_personality_one_way_only() -> None:
    # 🔴 BOB-062.5 decision 1: the personality↔social cycle was broken by making
    # personality/voice.py read an already-computed kind *value* instead of
    # importing ``InterlocutorKind``. The surviving edge is one-way social →
    # personality (``relationship`` colours its warmth by negotiation
    # ``Stance``); the reverse edge (personality → social) must stay absent, or
    # the cycle returns. Beadloom's ``no-dependency-cycles`` rule enforces this
    # at lint time (see the probe recorded on bob-8r4.5.3); here we pin the
    # positive half of the invariant — the legal one-way edge is present, so the
    # guard above is proving "no reverse import", not "no coupling at all".
    relationship_src = (_MODULE_ROOT / "relationship.py").read_text(
        encoding="utf-8"
    )
    assert "from bob.domain.personality.negotiation import Stance" in (
        relationship_src
    ), (
        "social.relationship must keep its one-way runtime edge to "
        "personality.negotiation.Stance (the surviving, cycle-free direction)"
    )
