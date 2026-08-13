# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""Доставка предложения правила owner'у — чистый вердикт (BOB-096 срез 1).

Одна ответственность: «про это правило ещё говорить — и услышал ли его owner?».
Модель правила и машина владельческих решений живут рядом, в
:mod:`bob.proactivity.self_improvement`; здесь только доставка.

ЗАЧЕМ ОТДЕЛЬНО ОТ :class:`~bob.proactivity.self_improvement.RuleState`. Доставка и
решение owner'а — две независимые оси. Правило остаётся ``PROPOSED``, пока owner не
ответил, вне зависимости от того, дошла ли до него реплика; а «дошла» ничего не
говорит о том, одобрит ли он. Поэтому доставка — два поля правила (``announced`` /
``announce_attempts``) и вердикты над ними, а не шестой член ``RuleState``: новый член
пришлось бы вносить в машину переходов, в дедуп «живых» правил и в owner-команды
``/rule`` — то есть менять смысл существующего PROPOSED ради бухгалтерии отправки.

ЧТО ЛОМАЛОСЬ (наблюдалось вживую шесть дней, 6–12 августа 2026). Пометка «проговорено»
была ``set`` в памяти процесса, и ставилась ПОСЛЕ успешной отправки. Отсюда два следа:
битая сеть → пометки нет → одно и то же предложение уходило на каждом reflect-тике (раз
в 5 минут); перезапуск → пометка обнулялась → owner получал заново ВСЕ предложения.
Ответ здесь — кап попыток (:data:`MAX_ANNOUNCE_ATTEMPTS`) и статус, который переживает
перезапуск, потому что живёт в строке правила.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from bob.proactivity.self_improvement import RuleState

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bob.proactivity.self_improvement import ImprovementRule

# Сколько раз Боб пробует доставить ОДНО предложение, прежде чем замолчать о нём.
# «Best-effort» означает «не роняем тик», а не «пробуем вечно»: reflect-тик идёт раз в
# 5 минут (heartbeat 30 с × 10), поэтому три попытки — это первая плюс два повтора в
# течение примерно четверти часа. Моргнувшая сеть в это окно укладывается; то, что не
# уложилось, — уже не моргание, а оглохший транспорт, и повторять по кругу бессмысленно
# (именно так вышло шесть дней подряд одним и тем же). Исчерпанное предложение не
# теряется молча: owner видит его в ``/rules`` помеченным как недоставленное.
#
# 🔴 ЭТО КОНСТАНТА, А НЕ КЛЮЧ КОНФИГА. Ключа ``self_improvement.max_announce_attempts``
# не существует, и параметр ``max_attempts`` ниже — ТЕСТОВЫЙ ШОВ (проверить границу капа,
# не переписывая константу), а не ручка для владельца. Названо прямо, чтобы следующий не
# искал настройку, которой нет: ровно в этом эпике рядом чинится мёртвый ключ
# ``detector_tier``, который читался как обещание механизма (§0.3 п.10).
MAX_ANNOUNCE_ATTEMPTS = 3

__all__ = [
    "MAX_ANNOUNCE_ATTEMPTS",
    "AnnounceStatus",
    "announce_status",
    "is_undelivered_proposal",
    "next_to_announce",
]


class AnnounceStatus(StrEnum):
    """Где находится доставка предложения — три состояния и только они.

    ``PENDING`` — сказать ещё нужно (попытки не исчерпаны); ``DELIVERED`` — owner
    услышал, повторять нечего; ``UNDELIVERED`` — попытки исчерпаны, owner так и не
    услышал: Боб об этом молчит, но ``/rules`` показывает это владельцу.
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"


def announce_status(
    rule: ImprovementRule, *, max_attempts: int = MAX_ANNOUNCE_ATTEMPTS
) -> AnnounceStatus:
    """Статус доставки ``rule`` (чистая функция от двух его полей).

    Успешная доставка сильнее исчерпанных попыток: правило, доехавшее с последней
    попытки, — ``DELIVERED``, а не «недоставленное». Попытки считаются ДО отправки,
    поэтому ``announce_attempts >= max_attempts`` без ``announced`` означает «пробовали
    столько раз, сколько разрешено, и ни разу не дошло».

    ``max_attempts`` — тестовый шов (см. :data:`MAX_ANNOUNCE_ATTEMPTS`), не конфиг.
    """
    if rule.announced:
        return AnnounceStatus.DELIVERED
    if rule.announce_attempts >= max_attempts:
        return AnnounceStatus.UNDELIVERED
    return AnnounceStatus.PENDING


def next_to_announce(
    rules: Iterable[ImprovementRule], *, max_attempts: int = MAX_ANNOUNCE_ATTEMPTS
) -> ImprovementRule | None:
    """Какое ОДНО правило Боб проговаривает сейчас (или ``None`` — молчание).

    Кандидат обязан быть ``PROPOSED`` (одобренное уже применяется, отклонённое или
    убранное owner закрыл, приостановленное он сам выключил) и в статусе ``PENDING``
    (не проговорённое и с непотраченными попытками). Из кандидатов берётся самое
    старое, тай-брейк по ``id`` — детерминированно, чтобы порядок не зависел от порядка
    строк в базе. Одно за раз: owner не получает пачку предложений сразу.

    ``max_attempts`` пробрасывается в :func:`announce_status` — кап, с которым спросили,
    и есть кап, по которому отбирают (тестовый шов, не конфиг).
    """
    pending = [
        rule
        for rule in rules
        if rule.state is RuleState.PROPOSED
        and announce_status(rule, max_attempts=max_attempts) is AnnounceStatus.PENDING
    ]
    if not pending:
        return None
    return min(pending, key=lambda rule: (rule.created_at, rule.id))


def is_undelivered_proposal(
    rule: ImprovementRule, *, max_attempts: int = MAX_ANNOUNCE_ATTEMPTS
) -> bool:
    """Ждёт ли ``rule`` решения owner'а, который о нём так и не услышал.

    Ровно то, что owner-facing список (``/rules``) помечает словами: предложение живо
    (``PROPOSED``), но попытки его проговорить исчерпаны. Правило, по которому owner уже
    решил, недоставленным не считается — его судьба больше не зависит от реплики.

    ``max_attempts`` пробрасывается в :func:`announce_status` — метка в списке считается
    по тому же капу, о котором спросили (тестовый шов, не конфиг).
    """
    return (
        rule.state is RuleState.PROPOSED
        and announce_status(rule, max_attempts=max_attempts)
        is AnnounceStatus.UNDELIVERED
    )
