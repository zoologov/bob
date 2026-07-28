# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: the ``personality`` module keeps its layers pure.

After BOB-062.6a, ``bob.personality`` became a vertical bounded-context — «who Bob
is»: mood / taste / disposition / fascination / negotiation / expression / voice /
reaction-meaning / reflection. Its use-cases (``bob.personality.usecases``,
``layer=application`` — update_mood / apply_reflection / reappraise / evolve_* /
reflection_parser) and its pure domain core (``layer=domain``) left the reach of
:mod:`tests.application.test_layering` (rooted at ``bob.application``), mirroring
the ``social`` (see :mod:`tests.social.test_layering`), ``capabilities``,
``memory`` and ``proactivity`` slices.

Beadloom's AaC rules forbid these breaches at lint time, but that check only sees
*runtime* import edges — ``from __future__ import annotations`` makes
``TYPE_CHECKING``-only imports invisible to it. This source-text scan closes that
gap and pins the two cycle-breaks landed by BOB-062.6a / .5 / .3:

* **usecases (application) must not import infrastructure** — neither the shared
  ``bob.infrastructure`` kernel nor the module's own ``bob.personality.adapters``.
* **domain internals must not import infrastructure** — the pure identity core
  (``layer=domain``) must not reach infrastructure.
* **personality ↛ conversation (any position)** — the ``voice↔brevity``/
  ``expression`` cycle was broken by moving the ``Verbosity``/``EngagementLevel``
  enum *definitions* into ``personality.expression``; the surviving edge is
  one-way ``conversation → personality`` (pinned positively in
  :mod:`tests.conversation.test_layering`), so ``personality`` must never import
  ``bob.conversation`` — not at runtime, not under ``TYPE_CHECKING``.
* **personality ↛ social at runtime** — the personality↔social cycle was broken
  (BOB-062.5/.3): ``social.relationship`` colours warmth by negotiation
  ``Stance`` (social → personality). The reverse edge (personality → social) must
  stay a ``TYPE_CHECKING``-only annotation import, never a runtime one.

A ``:class:`` mention in a docstring is fine; only a real ``from``/``import``
statement is a breach.
"""

from __future__ import annotations

import re
from pathlib import Path

import bob.personality
from bob.personality.expression import EngagementLevel, Verbosity

_MODULE_ROOT = Path(bob.personality.__file__).parent
_USECASES_ROOT = _MODULE_ROOT / "usecases"
_ADAPTERS_ROOT = _MODULE_ROOT / "adapters"

# Matches an actual import statement pulling in the infrastructure kernel or the
# module's own infrastructure-layer adapters — NOT a docstring `:class:` ref.
_INFRA_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+bob\.(?:infrastructure|personality\.adapters)\b",
    re.MULTILINE,
)

# A module-level (column-0) import of the sibling bounded-context. Indented
# ``TYPE_CHECKING`` imports are excluded by design for the runtime-edge scans;
# for the conversation cycle-break we forbid *any* position (see below).
_CONVERSATION_IMPORT_ANY = re.compile(
    r"^\s*(?:from|import)\s+bob\.conversation\b",
    re.MULTILINE,
)
_SOCIAL_IMPORT_RUNTIME = re.compile(
    r"^(?:from|import)\s+bob\.social\b",
    re.MULTILINE,
)


def _offenders(root: Path, pattern: re.Pattern[str]) -> list[str]:
    return sorted(
        path.relative_to(_MODULE_ROOT).as_posix()
        for path in root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    )


def _domain_files() -> list[Path]:
    # The domain core is everything under the module EXCEPT its usecases/
    # (application) and adapters/ (infrastructure) subtrees.
    return [
        path
        for path in _MODULE_ROOT.rglob("*.py")
        if _USECASES_ROOT not in path.parents
        and _ADAPTERS_ROOT not in path.parents
    ]


def test_no_personality_usecase_imports_infrastructure() -> None:
    # Arrange / Act
    offenders = _offenders(_USECASES_ROOT, _INFRA_IMPORT)
    # Assert
    assert offenders == [], (
        "bob.personality.usecases (layer=application) must not import "
        "infrastructure (bob.infrastructure or bob.personality.adapters): "
        f"{offenders}"
    )


def test_no_personality_domain_imports_infrastructure() -> None:
    # Arrange
    domain_files = _domain_files()
    # Act
    offenders = sorted(
        path.relative_to(_MODULE_ROOT).as_posix()
        for path in domain_files
        if _INFRA_IMPORT.search(path.read_text(encoding="utf-8"))
    )
    # Assert
    assert offenders == [], (
        "bob.personality domain internals (layer=domain) must not import "
        "infrastructure (bob.infrastructure or bob.personality.adapters): "
        f"{offenders}"
    )


def test_personality_never_imports_conversation() -> None:
    # 🔴 BOB-062.6a cycle-break: the ``voice↔brevity`` cycle was fixed by moving
    # the Verbosity/EngagementLevel enum *definitions* into personality; the sole
    # legal direction is conversation → personality. personality must never reach
    # back into conversation — not even under TYPE_CHECKING (there is genuinely no
    # edge to annotate), or the cycle Beadloom's ``no-dependency-cycles`` rule
    # forbids (probe recorded on bob-8r4.6.4) returns.
    offenders = _offenders(_MODULE_ROOT, _CONVERSATION_IMPORT_ANY)
    assert offenders == [], (
        "bob.personality must never import bob.conversation (the one-way edge is "
        f"conversation → personality; reverse = cycle): {offenders}"
    )


def test_personality_never_imports_social_at_runtime() -> None:
    # 🔴 BOB-062.5/.3 cycle-break: social → personality is the legal direction
    # (relationship warmth reads negotiation Stance). personality → social is
    # allowed only as a TYPE_CHECKING annotation import; a *runtime* (column-0)
    # import would re-form the personality↔social cycle (probe on bob-8r4.6.4).
    offenders = _offenders(_MODULE_ROOT, _SOCIAL_IMPORT_RUNTIME)
    assert offenders == [], (
        "bob.personality must not import bob.social at runtime (TYPE_CHECKING "
        f"annotation imports only; reverse of social → personality): {offenders}"
    )


def test_voice_reads_expression_enums_not_conversation() -> None:
    # 🔴 Positive half of the cycle-break: voice colours its brevity/engagement
    # directives off Verbosity/EngagementLevel that now live in
    # personality.expression — an intra-personality edge, not a conversation one.
    voice_src = (_MODULE_ROOT / "voice.py").read_text(encoding="utf-8")
    assert (
        "from bob.personality.expression import EngagementLevel, Verbosity"
        in voice_src
    ), (
        "personality.voice must read Verbosity/EngagementLevel from "
        "personality.expression (moved there to break the voice↔brevity cycle)"
    )
    # And the enums are genuinely personality-owned vocabulary.
    assert Verbosity.__module__ == "bob.personality.expression"
    assert EngagementLevel.__module__ == "bob.personality.expression"
