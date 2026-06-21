# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ApplyReflection — closing the Reflection -> Taste self-evolution loop.

A reflection is parsed into a signal (which axis, signed nudge) by an injectable
parser. A recognised signal reinforces the matching taste axis (bumping
experience_count); an unrecognised signal — or one naming an axis Bob has no
taste for — is a no-op (the relevance gate). The use-case is pure orchestration
over the domain; the parser is faked.
"""

from __future__ import annotations

from bob.application.usecases.apply_reflection import (
    ApplyReflection,
    ReflectionSignal,
)
from bob.domain.personality.mood import Mood, MoodDelta
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine


class FakeParser:
    """A parser returning a pre-set signal, recording the text it saw."""

    def __init__(self, signal: ReflectionSignal | None) -> None:
        self._signal = signal
        self.seen: list[str] = []
        self.topics_seen: tuple[str, ...] = ()

    def parse(
        self,
        reflection: str,
        *,
        topics: tuple[str, ...],
    ) -> ReflectionSignal | None:
        self.seen.append(reflection)
        self.topics_seen = topics
        return self._signal


def _soul(axis: TasteAxis | None = None) -> SOUL:
    axes = (axis,) if axis is not None else ()
    return SOUL(
        identity="Bob",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(axes=axes),
    )


def test_recognised_signal_reinforces_the_axis_and_changes() -> None:
    # Arrange: Bob has a weakly-held liking for jazz; reflection nudges it up.
    soul = _soul(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    parser = FakeParser(ReflectionSignal(topic="jazz", nudge=1.0))
    usecase = ApplyReflection(parser=parser)

    # Act
    result = usecase.run("I keep coming back to jazz lately.", soul)

    # Assert: changed, axis liking rose, experience ticked up.
    assert result.changed is True
    evolved = result.soul.taste.score  # the engine carries the reinforced axis
    assert evolved("jazz")  # smoke: still scorable
    axis = result.soul.taste.axes[0]
    assert axis.value > 0.2
    assert result.soul.experience_count == 1


def test_unrelated_axes_are_left_untouched() -> None:
    # Arrange: two axes; only one is targeted.
    soul = SOUL(
        identity="Bob",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(
            axes=(
                TasteAxis(name="jazz", value=0.2, conviction=0.1),
                TasteAxis(name="coffee", value=0.5, conviction=0.5),
            )
        ),
    )
    parser = FakeParser(ReflectionSignal(topic="jazz", nudge=1.0))
    usecase = ApplyReflection(parser=parser)

    # Act
    result = usecase.run("jazz again", soul)

    # Assert: coffee is byte-identical; jazz moved.
    by_name = {a.name: a for a in result.soul.taste.axes}
    assert by_name["coffee"].value == 0.5
    assert by_name["coffee"].conviction == 0.5
    assert by_name["jazz"].value > 0.2


def test_no_signal_is_a_noop() -> None:
    # Arrange: the parser recognises nothing in the reflection.
    soul = _soul(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    parser = FakeParser(None)
    usecase = ApplyReflection(parser=parser)

    # Act
    result = usecase.run("A vague, unclassifiable musing.", soul)

    # Assert: unchanged soul, no experience bump (relevance gate).
    assert result.changed is False
    assert result.soul is soul
    assert result.soul.experience_count == 0


def test_signal_for_unknown_axis_is_a_noop() -> None:
    # Arrange: a signal whose topic matches no existing taste axis.
    soul = _soul(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    parser = FakeParser(ReflectionSignal(topic="opera", nudge=1.0))
    usecase = ApplyReflection(parser=parser)

    # Act
    result = usecase.run("opera, perhaps?", soul)

    # Assert: nothing to reinforce -> no-op.
    assert result.changed is False
    assert result.soul is soul


def test_optional_baseline_delta_shifts_resting_mood() -> None:
    # Arrange: a signal carrying a small positive baseline nudge.
    soul = _soul(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    parser = FakeParser(
        ReflectionSignal(topic="jazz", nudge=1.0, baseline_delta=MoodDelta(valence=0.05))
    )
    usecase = ApplyReflection(parser=parser)

    # Act
    result = usecase.run("warm jazz thoughts", soul)

    # Assert: baseline valence nudged alongside the taste change.
    assert result.changed is True
    assert result.soul.mood_baseline.valence > 0.0
