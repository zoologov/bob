# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit-тесты выбора принципала по НАЗНАЧЕНИЮ операции (BOB-089, срез B).

Ядро отвечает на один вопрос: кем Боб представляется GitHub'у для этой операции. Двух
принципалов ровно два, и права у них РАЗНЫЕ — путать их нельзя: ``work`` умеет писать
контент, но только в форк; ``propose`` читает апстрим и не умеет писать вообще. Ошибка
выбора здесь — это либо мёртвый отказ по правам, либо (что хуже) запись тем токеном,
которым мы записывать не собирались.
"""

from __future__ import annotations

from bob.identity.principals import Principal, Purpose, principal_for


def test_pushing_a_branch_goes_under_the_work_principal() -> None:
    # Пуш ветки — единственная операция записи, и она разрешена ТОЛЬКО в форк Боба.
    assert principal_for(Purpose.PUSH_TO_FORK) is Principal.WORK


def test_reading_the_upstream_goes_under_the_propose_principal() -> None:
    # Чтение апстрима — принципал БЕЗ права записи контента: даже ошибка в коде выше не
    # превратится в запись в ствол owner'а.
    assert principal_for(Purpose.READ_UPSTREAM) is Principal.PROPOSE


def test_the_two_purposes_never_collapse_into_one_principal() -> None:
    # Смысл схемы — в РАЗНЫХ правах; если оба назначения приедут к одному принципалу,
    # разделения прав не существует.
    assert principal_for(Purpose.PUSH_TO_FORK) is not principal_for(Purpose.READ_UPSTREAM)


def test_a_principal_names_its_config_prefix() -> None:
    # По значению принципала читаются его ключи конфига (``work_app_id`` / …), поэтому
    # значение — часть контракта, а не деталь.
    assert Principal.WORK.value == "work"
    assert Principal.PROPOSE.value == "propose"
