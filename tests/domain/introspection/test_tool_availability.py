# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-111: Bob knows which of his capabilities are mute BEFORE he is asked.

Issues #62. Moving to the VPS silenced two capabilities at once — introspection (no
``beadloom`` binary) and the renderer (``mmdc_bin`` still pointing at the owner's
MacBook) — and nothing noticed until the owner asked for a diagram in the group and
got a fabricated excuse and an empty message (BOB-110).

🔴 The verdict is about REACHABILITY, never about the shape of the configured string.
The path that broke us was syntactically perfect — a valid absolute path, set
deliberately, explained in a comment beside it. Only "does it actually run on THIS
machine?" catches that, which is why every test here goes through a resolver.
"""

from __future__ import annotations

from bob.capabilities.tool_availability import (
    ToolRequirement,
    ToolResolver,
    assess_tools,
    describe_unavailable,
    unavailable,
)

_BEADLOOM = ToolRequirement(
    capability="схема архитектуры", tool="beadloom", configured="beadloom"
)
_MMDC_FROM_A_LAPTOP = ToolRequirement(
    capability="картинка из mermaid",
    tool="mmdc",
    configured="/Users/someone/.nvm/versions/node/v18.20.8/bin/mmdc",
)


def _resolver(present: set[str]) -> ToolResolver:
    """A resolver standing in for the host: only these values are reachable."""

    def resolve(configured: str) -> str | None:
        return configured if configured in present else None

    return resolve


def test_a_present_tool_is_available() -> None:
    # Arrange / Act
    verdicts = assess_tools([_BEADLOOM], resolve=_resolver({"beadloom"}))

    # Assert
    assert len(verdicts) == 1
    assert verdicts[0].available is True
    assert verdicts[0].requirement is _BEADLOOM
    # 🔴 An available verdict carries NO reason. Anything left in that field — stale
    # text, a placeholder, None — would surface in the operator's report as a problem
    # that does not exist. (Killed mutants assess_tools_17 / _22.)
    assert verdicts[0].reason == ""


def test_a_missing_tool_is_unavailable_and_says_why() -> None:
    # Arrange / Act: nothing resolves — the shape of the live VPS before BOB-110.
    verdicts = assess_tools([_BEADLOOM], resolve=_resolver(set()))

    # Assert: the verdict carries the capability, the tool AND a reason — a bare
    # boolean would leave the operator to guess, which is how this stayed unnoticed.
    assert verdicts[0].available is False
    assert "beadloom" in verdicts[0].reason
    assert verdicts[0].requirement.capability == "схема архитектуры"


def test_a_path_from_another_machine_is_unavailable() -> None:
    # Arrange / Act: the exact defect — a valid, deliberate, well-commented path that
    # simply does not exist on this host.
    verdicts = assess_tools([_MMDC_FROM_A_LAPTOP], resolve=_resolver(set()))

    # Assert
    assert verdicts[0].available is False
    assert "/Users/someone" in verdicts[0].reason, (
        "the reason must name the configured path — an operator reading 'mmdc missing' "
        "would look at PATH and find nothing wrong (Issues #62)"
    )


def test_unavailable_selects_only_the_broken_ones() -> None:
    # Arrange
    verdicts = assess_tools(
        [_BEADLOOM, _MMDC_FROM_A_LAPTOP], resolve=_resolver({"beadloom"})
    )

    # Act
    broken = unavailable(verdicts)

    # Assert
    assert [v.requirement.tool for v in broken] == ["mmdc"]


def test_everything_available_describes_nothing() -> None:
    # Arrange / Act
    verdicts = assess_tools([_BEADLOOM], resolve=_resolver({"beadloom"}))

    # Assert: silence is correct ONLY when there is genuinely nothing to say.
    assert describe_unavailable(verdicts) == ""


def test_the_description_names_capability_tool_and_reason() -> None:
    # Arrange / Act
    verdicts = assess_tools([_BEADLOOM, _MMDC_FROM_A_LAPTOP], resolve=_resolver(set()))
    text = describe_unavailable(verdicts)

    # Assert: unreadable-as-"all fine" is the whole point of this line existing.
    assert "схема архитектуры" in text
    assert "картинка из mermaid" in text
    assert "beadloom" in text
    assert "/Users/someone" in text
    # 🔴 One mute capability per LINE. Substring checks alone pass even when the two
    # reports are run together into one unreadable string — and a report nobody can
    # scan is the silence this bead exists to end. (Killed mutant
    # describe_unavailable_7, which corrupted the separator.)
    lines = text.splitlines()
    assert len(lines) == 2
    assert all(line.startswith("— ") for line in lines)


def test_no_requirements_is_not_reported_as_all_good() -> None:
    """🔴 Guard against a vacuous green (§0.3 п.6).

    An empty requirement list must not be describable as "everything is available" —
    that is a gate reporting success for work it never did. It yields no verdicts at
    all, and the caller can tell "nothing checked" from "nothing broken" by the count.
    """
    verdicts = assess_tools([], resolve=_resolver(set()))
    assert verdicts == ()
    assert unavailable(verdicts) == ()
