# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""ApplyReflection — close the Reflection -> Taste loop, with the relevance gate.

After a reflection is written as an episode, this use-case lets it *reshape* Bob:
it parses the reflection into a :class:`ReflectionSignal` (which taste axis, what
signed nudge, an optional baseline mood delta) via an injected
:class:`ReflectionParser`, then reinforces the matching axis through the pure
:func:`bob.personality.taste_evolution.reinforce` kernel and swaps it into
the soul (:meth:`SOUL.with_taste`, bumping ``experience_count``).

Guardrails live here too: the **relevance gate** makes an unrecognised signal —
or one naming an axis Bob has no taste for — a strict no-op (``changed=False``,
the same soul returned), so noise never perturbs the personality. The per-step
magnitude is bounded by the kernel's small learning rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from bob.personality.taste_evolution import ALPHA, BETA, reinforce

if TYPE_CHECKING:
    from bob.personality.mood import MoodDelta
    from bob.personality.soul import SOUL
    from bob.personality.taste import TasteAxis


@dataclass(frozen=True, slots=True)
class ReflectionSignal:
    """A parsed reflection: which taste axis to nudge, by how much, and an optional baseline shift.

    ``topic`` names the taste axis (matched case-insensitively against the soul's
    axes); ``nudge`` is the signed strength fed to the evolution kernel;
    ``baseline_delta`` optionally shifts the resting mood a touch.
    """

    topic: str
    nudge: float
    baseline_delta: MoodDelta | None = None


@dataclass(frozen=True, slots=True)
class ReflectionOutcome:
    """The result of applying a reflection: the (possibly unchanged) soul and a flag."""

    soul: SOUL
    changed: bool


class ReflectionParser(Protocol):
    """Parse a reflection into a :class:`ReflectionSignal` (or ``None`` if no signal).

    The contract is abstract on purpose: the default realisation is a
    deterministic keyword heuristic, but a Tier-0 LLM parser swaps in later
    without any consumer change. ``None`` engages the relevance gate (no-op).
    """

    def parse(
        self,
        reflection: str,
        *,
        topics: tuple[str, ...],
    ) -> ReflectionSignal | None:
        """Return the signal carried by ``reflection`` over Bob's ``topics``, or ``None``."""
        ...


class ApplyReflection:
    """Apply a reflection to the soul: parse -> reinforce -> with_taste (gated).

    Learning rates ``alpha`` / ``beta`` default to the kernel's conservative
    constants; ``bob.app`` overrides them from ``personality.evolution.{alpha,beta}``
    when configured, so the evolution pace is tunable without touching the domain.
    """

    def __init__(
        self,
        *,
        parser: ReflectionParser,
        alpha: float = ALPHA,
        beta: float = BETA,
    ) -> None:
        self._parser = parser
        self._alpha = alpha
        self._beta = beta

    def run(self, reflection: str, soul: SOUL) -> ReflectionOutcome:
        """Return the soul after applying ``reflection`` (no-op if no signal).

        Relevance gate: a ``None`` signal, or one whose ``topic`` matches no
        existing taste axis, returns ``soul`` unchanged (``changed=False``).
        """
        topics = tuple(axis.name for axis in soul.taste.axes)
        signal = self._parser.parse(reflection, topics=topics)
        if signal is None:
            return ReflectionOutcome(soul=soul, changed=False)

        evolved_axes = self._reinforced_axes(soul.taste.axes, signal)
        if evolved_axes is None:
            return ReflectionOutcome(soul=soul, changed=False)

        new_soul = soul.with_taste(evolved_axes)
        if signal.baseline_delta is not None:
            new_soul = new_soul.with_baseline(signal.baseline_delta)
        return ReflectionOutcome(soul=new_soul, changed=True)

    def _reinforced_axes(
        self,
        axes: tuple[TasteAxis, ...],
        signal: ReflectionSignal,
    ) -> tuple[TasteAxis, ...] | None:
        """Return ``axes`` with the matching axis reinforced, or ``None`` if no match."""
        key = signal.topic.strip().casefold()
        matched = False
        rebuilt: list[TasteAxis] = []
        for axis in axes:
            if axis.name.casefold() == key:
                rebuilt.append(
                    reinforce(axis, nudge=signal.nudge, alpha=self._alpha, beta=self._beta)
                )
                matched = True
            else:
                rebuilt.append(axis)
        return tuple(rebuilt) if matched else None
