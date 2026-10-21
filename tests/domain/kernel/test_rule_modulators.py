# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""``RuleModulators.has_any`` (BOB-113, bob-etb.8): «есть ли что применять».

Нейтральное значение — «нет применения»; любой ОДИН рычаг, взведённый в одиночку, —
уже «есть». Каждый рычаг проверен отдельно: потеряй один из предиката — и одобренное
правило этого рычага молча перестанет действовать; тест назовёт рычаг.
"""

from __future__ import annotations

import pytest

from bob.kernel.modulators import RuleModulators


def test_the_neutral_value_has_nothing_to_apply() -> None:
    assert RuleModulators().has_any() is False


@pytest.mark.parametrize(
    "lever",
    [
        RuleModulators(voice_adjustments=("мягче",)),
        RuleModulators(length_step=-1),
        RuleModulators(length_step=1),
        RuleModulators(proactivity_bias=0.1),
        RuleModulators(addressivity_bias=0.1),
    ],
    ids=["voice", "shorter", "longer", "proactivity", "addressivity"],
)
def test_any_single_lever_alone_is_something_to_apply(lever: RuleModulators) -> None:
    assert lever.has_any() is True


def test_every_lever_at_once_is_something_to_apply() -> None:
    everything = RuleModulators(
        voice_adjustments=("мягче",), length_step=-1, proactivity_bias=0.2, addressivity_bias=0.3
    )

    assert everything.has_any() is True
