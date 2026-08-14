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

from bob.proactivity.self_improvement import (
    RuleState,
    is_actionable_proposal,
    proposal_defect,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bob.proactivity.self_improvement import ImprovementRule, ProposalDefect

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
    "unactionable_reason",
]


class AnnounceStatus(StrEnum):
    """Что Бобу делать с этим предложением и что о нём знать владельцу.

    ``PENDING`` — сказать ещё нужно (попытки не исчерпаны); ``DELIVERED`` — owner
    услышал, повторять нечего; ``UNDELIVERED`` — попытки исчерпаны, owner так и не
    услышал: Боб об этом молчит, но ``/rules`` показывает это владельцу;
    ``NOT_ACTIONABLE`` — одобрять в предложении нечего (вырожденное или сверх
    потолка), поэтому его не проговаривают ВООБЩЕ, а ``/rules`` называет это прямо.

    🔴 ``NOT_ACTIONABLE`` — не про доставку, а про содержание, и потому это ОТДЕЛЬНЫЙ
    член, а не «не доставлено»: «мы пробовали, и не дошло» и «говорить не о чем» —
    разные факты, и второй нельзя называть первым (владелец решает по ним разное).
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"
    NOT_ACTIONABLE = "not_actionable"


def announce_status(
    rule: ImprovementRule,
    *,
    max_magnitude: float,
    max_attempts: int = MAX_ANNOUNCE_ATTEMPTS,
) -> AnnounceStatus:
    """Статус предложения ``rule``: есть ли что говорить — и услышал ли owner.

    Сперва содержание, потом бухгалтерия отправки. Предложение, в котором нечего
    одобрять (:func:`~bob.proactivity.self_improvement.is_actionable_proposal` —
    пустая поправка, нулевой наклон или величина сверх ``max_magnitude``), —
    ``NOT_ACTIONABLE`` независимо от того, сколько раз его пробовали сказать и
    говорили ли вообще: одобрять в нём нечего ни до отправки, ни после.

    Дальше — доставка. Успешная доставка сильнее исчерпанных попыток: правило,
    доехавшее с последней попытки, — ``DELIVERED``, а не «недоставленное». Попытки
    считаются ДО отправки, поэтому ``announce_attempts >= max_attempts`` без
    ``announced`` означает «пробовали столько раз, сколько разрешено, и ни разу не
    дошло».

    ``max_magnitude`` — потолок величины из конфига; параметр ОБЯЗАТЕЛЬНЫЙ и без
    дефолта намеренно. Ровно этот вердикт эпик уже умел выносить на рождении правила,
    но спросить его на выходе было не у кого — и пять правил, родившихся раньше,
    доехали до владельца прежним путём. Дефолт вернул бы ту же дыру: вызывающий, не
    знающий потолка, молча получал бы чужой ответ.

    ``max_attempts`` — тестовый шов (см. :data:`MAX_ANNOUNCE_ATTEMPTS`), не конфиг.
    """
    if not is_actionable_proposal(rule, max_magnitude=max_magnitude):
        return AnnounceStatus.NOT_ACTIONABLE
    if rule.announced:
        return AnnounceStatus.DELIVERED
    if rule.announce_attempts >= max_attempts:
        return AnnounceStatus.UNDELIVERED
    return AnnounceStatus.PENDING


def next_to_announce(
    rules: Iterable[ImprovementRule],
    *,
    max_magnitude: float,
    max_attempts: int = MAX_ANNOUNCE_ATTEMPTS,
) -> ImprovementRule | None:
    """Какое ОДНО правило Боб проговаривает сейчас (или ``None`` — молчание).

    Кандидат обязан быть ``PROPOSED`` (одобренное уже применяется, отклонённое или
    убранное owner закрыл, приостановленное он сам выключил) и в статусе ``PENDING``
    (есть что одобрять, не проговорено, попытки не потрачены). Из кандидатов берётся
    самое старое, тай-брейк по ``id`` — детерминированно, чтобы порядок не зависел от
    порядка строк в базе. Одно за раз: owner не получает пачку предложений сразу.

    🔴 Вырожденное предложение сюда не попадает, даже если оно УЖЕ лежит в базе:
    отбраковка на рождении лечит только будущее, а владелец живёт с наследством. Такое
    правило не выбрасывается и не помечается проговорённым — оно остаётся видимым в
    ``/rules`` (:func:`unactionable_reason` объясняет владельцу, почему Боб молчит).

    ``max_magnitude`` / ``max_attempts`` пробрасываются в :func:`announce_status` —
    потолок и кап, с которыми спросили, и есть те, по которым отбирают.
    """
    pending = [
        rule
        for rule in rules
        if rule.state is RuleState.PROPOSED
        and announce_status(rule, max_magnitude=max_magnitude, max_attempts=max_attempts)
        is AnnounceStatus.PENDING
    ]
    if not pending:
        return None
    return min(pending, key=lambda rule: (rule.created_at, rule.id))


def is_undelivered_proposal(
    rule: ImprovementRule,
    *,
    max_magnitude: float,
    max_attempts: int = MAX_ANNOUNCE_ATTEMPTS,
) -> bool:
    """Ждёт ли ``rule`` решения owner'а, который о нём так и не услышал.

    Ровно то, что owner-facing список (``/rules``) помечает словами: предложение живо
    (``PROPOSED``), в нём есть что одобрять, но попытки его проговорить исчерпаны.
    Правило, по которому owner уже решил, недоставленным не считается — его судьба
    больше не зависит от реплики. Вырожденное правило — тоже: про него честно сказать
    «нечего одобрять» / «просит больше разрешённого» (:func:`unactionable_reason`).

    ``max_magnitude`` / ``max_attempts`` пробрасываются в :func:`announce_status` —
    метка в списке считается по тем же потолку и капу, о которых спросили.
    """
    return (
        rule.state is RuleState.PROPOSED
        and announce_status(rule, max_magnitude=max_magnitude, max_attempts=max_attempts)
        is AnnounceStatus.UNDELIVERED
    )


def unactionable_reason(
    rule: ImprovementRule, *, max_magnitude: float
) -> ProposalDefect | None:
    """Почему Боб молчит о живом ``rule`` (``None`` — он о нём не молчит).

    То, чем owner-facing список объясняет молчание — и единственный след правила,
    доставшегося в наследство: Боб его не проговаривает (:func:`next_to_announce` не
    выбирает), но молчание не должно означать исчезновение. Правило остаётся в
    ``PROPOSED``, видно в ``/rules`` и ждёт решения владельца — удалить его за него
    значило бы решить вместо него.

    🔴 Возвращается ПРИЧИНА, а не «да/нет»: «одобрять нечего» и «просит больше
    разрешённого» — разные новости для владельца. Во втором случае содержание есть, и
    решение у него действенное (поднять потолок или отклонить осознанно); одна метка на
    оба случая называла бы осмысленное предложение мусором.

    Считается только для живого предложения: по правилу, судьбу которого owner уже
    решил, говорить не о чем в любом случае.
    """
    if rule.state is not RuleState.PROPOSED:
        return None
    return proposal_defect(rule, max_magnitude=max_magnitude)
