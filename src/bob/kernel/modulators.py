# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Модуляторы самоулучшения — замороженное значение, которое применяют несколько модулей.

:class:`RuleModulators` собирает ``proactivity`` (``build_modulators`` из одобренных
правил BOB-028), а применяют его ``conversation``
(``turn_gate``, ``anti_repeat_guard``) и ``personality`` (``voice_composer``) — модули
НИЖЕ ``proactivity`` по runtime-порядку. Поэтому значение живёт в shared kernel
(BOB-113): объявленное в ``proactivity``, оно тянуло их сигнатуры ребром вверх.
Поведение (детектор, машина состояний, сборщик) остаётся в ``proactivity``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RuleModulators"]


@dataclass(frozen=True, slots=True)
class RuleModulators:
    """Набор мягких наклонов, собранных из ``active_rules`` — каждый в свою точку.

    Каждое поле — отдельный рычаг :class:`Lever`, который применяется В СВОЕЙ точке
    поведения (один рычаг → одна точка, без перекрёстных эффектов):

    * ``voice_adjustments`` — человекочитаемые поправки ТОНА / ЮМОРА (``adjustment``
      одобренных TONE/HUMOR-правил), которые ``voice.improvement_directive`` оборачивает
      в наклон-голоса для ``_system_prompt_for``. Пустой кортеж → ничего не добавляется
      (прозу владеет voice — домен отдаёт только данные).
    * ``length_step`` — целочисленный сдвиг ступени многословия (BOB-024): ``-1``
      короче, ``0`` без сдвига. Не больше одной ступени — мягкий наклон, не перехват;
      приёмник клиппит по краям лестницы.
    * ``proactivity_bias`` — байес к urge/governance (BOB-010) в ``[0, max_magnitude]``.
    * ``addressivity_bias`` — байес к порогам адресности (BOB-023/025) в
      ``[0, max_magnitude]``.

    Все величины уже закламплены к ``max_magnitude`` сборщиком. Дефолт (все поля
    нейтральны) — это «нет применения»: поведение ровно как до BOB-028.
    """

    voice_adjustments: tuple[str, ...] = ()
    length_step: int = 0
    proactivity_bias: float = 0.0
    addressivity_bias: float = 0.0

    def has_any(self) -> bool:
        """Есть ли хоть один ненулевой наклон (иначе применять нечего)."""
        return _has_any_lever(self)


# 🔴 Предикат вынесен из класса на уровень модуля: mutmut не мутирует НИ ОДИН метод
# декорированного класса (``@dataclass`` в том числе), и оставленный в теле класса он
# числился бы в ``[tool.mutmut].source_paths`` с нулём мутантов — фантомный гейт
# (bob-etb.8, §0.3 п.7). Здесь каждый ``or`` и каждый рычаг под мутацией.
def _has_any_lever(modulators: RuleModulators) -> bool:
    return bool(
        modulators.voice_adjustments
        or modulators.length_step
        or modulators.proactivity_bias
        or modulators.addressivity_bias
    )
