# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=domain

"""Кем Боб представляется GitHub'у для этой операции — чистое ядро (BOB-089, срез B).

ОДНА ответственность: выбор принципала по НАЗНАЧЕНИЮ операции. Ни ключей, ни сети, ни
кэша — только решение.

🔴 ПОЧЕМУ ПРИНЦИПАЛОВ ДВА, А НЕ ОДИН. Права GitHub App одинаковы для ВСЕХ его установок:
сузить их «для этого репозитория» нельзя. Поэтому неприкосновенность ствола owner'а
держится не на аккуратности кода, а на том, что у Боба две РАЗНЫЕ учётные сущности:

* :attr:`Principal.WORK` («Bob AI Work») — ``contents: write``, установлен ТОЛЬКО на
  организацию с форком. Этим принципалом Боб пушит свою ветку — и физически не может
  записать что-либо в апстрим owner'а;
* :attr:`Principal.PROPOSE` («Bob AI Propose») — ``contents: read`` +
  ``pull_requests: write``. Этим принципалом читается апстрим. Негативный смоук owner'а
  (см. комментарии беады BOB-089): создание ветки, force-push в main и запись файла в
  апстрим — все три ``403 Resource not accessible by integration``.

Отсюда правило, которое это ядро и охраняет: назначение операции ВЫБИРАЕТ принципала, а не
наоборот. Ошибка выбора — это либо мёртвый отказ по правам, либо (что хуже) работа тем
токеном, которым работать не собирались.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["Principal", "Purpose", "principal_for"]


class Purpose(Enum):
    """Зачем Бобу понадобился токен — назначение операции, а не имя приложения."""

    #: Довести свою работу до ветки в ФОРКЕ (единственная операция записи).
    PUSH_TO_FORK = "push_to_fork"
    #: Прочитать апстрим owner'а (без права записи контента).
    READ_UPSTREAM = "read_upstream"


class Principal(Enum):
    """Учётная сущность Боба на GitHub. Значение — префикс её ключей в конфиге."""

    #: «Bob AI Work»: contents write, установка только на организацию с форком.
    WORK = "work"
    #: «Bob AI Propose»: contents read + pull_requests write.
    PROPOSE = "propose"


def principal_for(purpose: Purpose) -> Principal:
    """Выбрать принципала, которым выполняется ``purpose``.

    Запись возможна только в форк, поэтому пуш идёт под ``work``; всё остальное — чтение,
    и оно идёт под принципалом, у которого права на запись контента нет вовсе. Такой
    выбор — консервативный по умолчанию: новое назначение получит слабейшие права, пока
    его не разберут здесь явно.
    """
    if purpose is Purpose.PUSH_TO_FORK:
        return Principal.WORK
    return Principal.PROPOSE
