# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""GroundedAddons — fold Bob's REAL inner life into the compose context (BOB-018/020/021).

The turn's «grounded add-on» concern in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 3, behavior-preserving). Behind the BOB-012 grounding
seam it folds a REAL, persisted piece of Bob's inner life into the reply-generation context:

* :meth:`with_grounded_addons` composes the three add-ons — a leaking-inner-life line (the
  latest reflection), a memory callback (a strong real past moment on the topic, occasionally
  reaching an OLD-but-relevant deep cut via the seeded ``surface_old`` draw), and a
  fascination mention (Bob's current, non-faded passion) — additively onto the context; and
* :meth:`safe` runs ONE optional add-on, dropping it silently on failure.

🔴 Every add-on is strictly anti-confabulation: with no real material it no-ops, so Bob never
invents a thought he did not have or a moment that did not happen. 🔴 Every add-on is
DECORATIVE (BOB-049 .3): :meth:`safe` swallows ANY failure and returns ``""`` — an add-on is
FLAVOUR, so a flaky reflection / recall / fascination read NEVER trips the essential-step
GUPPI outage notice; the full Bob reply still ships. 🔴 It shares the SAME injected ``Random``
as every other turn collaborator, so the per-turn seeded-draw order is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from random import Random

    from bob.application.usecases.handle_message import CurrentFascinationReader
    from bob.kernel.ports import MemoryRecall
    from bob.personality.expression import ExpressionPlan
    from bob.personality.ports import ReflectionReader

logger = logging.getLogger(__name__)

# A frequency floor: at frequency 0 the surface_old draw is a hard off (the default path
# never asks recall for the old blend).
_MIN_FREQ = 0.0

# How many memories to recall for a BOB-018 callback: just the single strongest real past
# moment on the topic (a tight, grounded steer — never a memory dump).
_CALLBACK_RECALL_K = 1

# Grounded add-on prefaces (BOB-018 wave 3 / BOB-020 wave 2). Each folds a REAL, persisted
# piece of Bob's inner life into the compose context behind the same grounding seam BOB-012
# uses — strictly anti-confabulation (no real material → no line). Russian persona voice
# (project language); Cyrillic look-alikes intentional, so the ambiguous-character lint is
# silenced for these literals.
_LEAK_PREFACE = (
    "То, о чём ты ловил себя на мысли, пока его не было (можешь обронить это "  # noqa: RUF001
    "к слову, естественно — не пересказывай дословно):"
)
_CALLBACK_PREFACE = (
    "Можешь к месту вспомнить это — реальный момент из вашего прошлого, "
    "не выдумывай деталей сверх него:"
)
_FASCINATION_PREFACE = (
    "Можешь к месту обронить, чем сейчас увлечён — это твоё реальное состояние, "
    "не пересказывай как факт, просто упомяни живо, если в тему:"
)


class GroundedAddons:
    """Fold Bob's real reflection / callback / fascination into the context (BOB-018 w3)."""

    def __init__(
        self,
        *,
        reflection: ReflectionReader | None,
        fascination: CurrentFascinationReader | None,
        recall: MemoryRecall,
        surface_old_freq: float,
        rng: Random,
    ) -> None:
        self._reflection = reflection
        self._fascination = fascination
        self._recall = recall
        self._surface_old_freq = surface_old_freq
        self._rng = rng

    async def with_grounded_addons(
        self, context: str, text: str, plan: ExpressionPlan, *, rng: Random | None = None
    ) -> str:
        """Fold the plan's grounded add-ons into the compose context (BOB-018 w3).

        Behind the existing grounding seam, when the plan sets ``leak_inner_life``
        and a real reflection exists, Bob's latest reflection is appended as a
        leaking-inner-life line; when it sets ``callback`` and a STRONG real past
        moment is recalled on the topic, that moment is appended as a callback; when
        it sets ``mention_fascination`` and a real current passion exists, its topic
        is appended. Both are strictly anti-confabulation: no real material → no line
        added (a clean no-op), so Bob never invents a thought or a shared past that is
        not there. Composes additively (voice/language/negotiation live elsewhere).
        """
        # 🔴 Each add-on is OPTIONAL flavour (BOB-049 .3): wrapped so a flaky reflection /
        # recall / fascination read DROPS the add-on (logged, returns "") and the core full
        # Bob reply still ships. A failing add-on must NEVER trip the GUPPI outage notice —
        # it is not an essential step.
        additions = [
            await self.safe(self._leak_inner_life(plan), name="inner-life leak"),
            await self.safe(self._callback(plan, text, rng=rng), name="memory callback"),
            await self.safe(
                self._mention_fascination(plan), name="fascination mention"
            ),
        ]
        suffix = "".join(f"\n{line}" for line in additions if line)
        return f"{context}{suffix}" if suffix else context

    async def safe(self, addon: Awaitable[str], *, name: str) -> str:
        """Run one OPTIONAL grounded add-on, dropping it silently on failure (BOB-049 .3).

        An add-on is FLAVOUR, never the core reply: if it raises (a flaky reflection /
        recall / fascination read), the error is logged and the add-on dropped so the full
        Bob reply still ships. Returns the add-on's line, or ``""`` when it had nothing OR
        failed — so a failing optional add-on can never trigger the honest outage notice.
        """
        try:
            return await addon
        except Exception:
            logger.exception("optional grounded add-on %r failed (dropped)", name)
            return ""

    async def _leak_inner_life(self, plan: ExpressionPlan) -> str:
        """The leak line for this turn, or ``""`` (no flag / no reader / no reflection)."""
        if not plan.leak_inner_life or self._reflection is None:
            return ""
        reflection = await self._reflection.latest_reflection_text()
        if not reflection:
            return ""
        return f"{_LEAK_PREFACE} {reflection}"

    async def _callback(
        self, plan: ExpressionPlan, text: str, *, rng: Random | None = None
    ) -> str:
        """The callback line for this turn, or ``""`` (no flag / weak-or-empty recall).

        Reuses the hybrid recall (BOB-011) on the current topic; a real past moment
        comes back → it is offered as a callback. Mirrors BOB-012 grounding: an
        empty recall yields nothing, so Bob never confabulates a shared moment.

        Occasionally (a small seeded draw, BOB-021 mechanism 1) the recall is asked
        with ``surface_old`` so the callback can reach an OLD-but-relevant deep cut
        ("что-то напомнило") instead of only the freshest hit — still grounded (a real
        recall hit) and a no-op when nothing relevant comes back. The draw rides ONLY
        the callback path and fires on a fraction of callbacks, never every turn.
        """
        if not plan.callback:
            return ""
        surface_old = self._draw_surface_old(rng)
        recalled = await self._recall.recall(
            text, k=_CALLBACK_RECALL_K, surface_old=surface_old
        )
        moment = next(
            (str(item.get("content", "")) for item in recalled if item.get("content")),
            "",
        )
        if not moment:
            return ""
        return f"{_CALLBACK_PREFACE} {moment}"

    def _draw_surface_old(self, rng: Random | None = None) -> bool:
        """Fire the rare surface_old draw for this callback (BOB-021, seeded RNG).

        A hard off at frequency ``0`` (the default path never asks for the old blend);
        otherwise an occasional ``True`` so a callback reaches an old-but-relevant deep
        cut on a small fraction of callbacks. 🔴 BOB-066 Срез 2.1: uses the per-turn
        ``TurnScope.rng`` threaded by the caller (INV-4 — concurrent chats never share a
        draw stream); omitted (a direct unit call) it falls back to the injected rng.
        """
        if self._surface_old_freq <= _MIN_FREQ:
            return False
        return (rng if rng is not None else self._rng).random() < self._surface_old_freq

    async def _mention_fascination(self, plan: ExpressionPlan) -> str:
        """The fascination line for this turn, or ``""`` (no flag / no reader / none).

        On a ``mention_fascination`` turn, asks the wired reader for Bob's current,
        non-faded passion; a real one is offered as something he can drop à propos.
        Strictly anti-confabulation: ``None`` (no reader, or no current fascination)
        yields nothing, so Bob never invents an interest he does not have.
        """
        if not plan.mention_fascination or self._fascination is None:
            return ""
        fascination = await self._fascination.current_fascination()
        if fascination is None:
            return ""
        return f"{_FASCINATION_PREFACE} {fascination.topic}"
