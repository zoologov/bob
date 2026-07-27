# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты ActiveRulesReader — чтение APPROVED-правил для применения (BOB-028 .3).

Покрывают: фильтр active-only (APPROVED; PROPOSED/PAUSED/REJECTED/REMOVED не видны
applied-стороне — authz-before-autonomy) и best-effort (сбой стора → пусто, не падение).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)
from bob.proactivity.usecases.self_improvement_sources import ActiveRulesReader

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
_PERSONA = "bob"


def _rule(rid: str, *, state: RuleState) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation="o",
        adjustment="a",
        lever=Lever.TONE,
        magnitude=0.3,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_NOW,
        evidence="",
    )


@dataclass
class _FakeStore:
    rules: tuple[ImprovementRule, ...] = ()
    fail: bool = False

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:  # noqa: ARG002
        if self.fail:
            raise RuntimeError("store down")
        return self.rules


async def test_returns_only_approved_rules() -> None:
    store = _FakeStore(
        rules=(
            _rule("approved", state=RuleState.APPROVED),
            _rule("proposed", state=RuleState.PROPOSED),
            _rule("paused", state=RuleState.PAUSED),
            _rule("rejected", state=RuleState.REJECTED),
            _rule("removed", state=RuleState.REMOVED),
        )
    )
    reader = ActiveRulesReader(store=store, persona_id=_PERSONA)

    active = await reader.active()

    assert [r.id for r in active] == ["approved"]


async def test_store_failure_yields_no_rules() -> None:
    reader = ActiveRulesReader(store=_FakeStore(fail=True), persona_id=_PERSONA)

    # Best-effort: a flaky store must never break the turn — no rules applied.
    assert await reader.active() == ()
