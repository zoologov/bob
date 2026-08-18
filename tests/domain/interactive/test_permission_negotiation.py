# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Висящий вопрос о разрешении и его разрешение словами (BOB-088, срез 3).

Предмет: :class:`bob.interactive.permission_negotiation.PermissionNegotiation` — машина
ОДНОГО заданного владельцу вопроса «упёрся в запрет, разрешаешь?».

Правила те же три, что у вопроса «поднимаю?» (:mod:`bob.interactive.resume_negotiation`),
и все три — предохранители: вопрос один, вопрос адресный, вопрос не залипает. Разница
одна и названа: окно ответа ДЛИННЕЕ, потому что владелец у телефона не сидит, а конвейер
всё это время стоит.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.interactive.permission_negotiation import (
    PERMISSION_TTL,
    PermissionGranted,
    PermissionNegotiation,
    PermissionRefused,
)

_OWNER = 42
_STRANGER = 7
_START = datetime(2026, 8, 15, 18, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.moment = _START

    def now(self) -> datetime:
        return self.moment


def _armed(clock: _Clock, *, command: str = "git push origin master") -> PermissionNegotiation:
    negotiation = PermissionNegotiation(clock=clock)
    negotiation.ask(command=command, sender=_OWNER, session_id="live-1")
    return negotiation


def test_nothing_is_pending_until_bob_asks() -> None:
    negotiation = PermissionNegotiation(clock=_Clock())

    assert not negotiation.is_pending()
    assert negotiation.settle("да", _OWNER) is None


def test_a_yes_grants_exactly_the_command_that_was_asked_about() -> None:
    negotiation = _armed(_Clock(), command="rm -rf .worktrees/x")

    answer = negotiation.settle("да", _OWNER)

    assert answer == PermissionGranted(command="rm -rf .worktrees/x", session_id="live-1")


def test_a_no_is_a_refusal_and_not_a_silence() -> None:
    assert _armed(_Clock()).settle("нет", _OWNER) == PermissionRefused()


def test_only_the_one_who_was_asked_can_answer() -> None:
    negotiation = _armed(_Clock())

    assert negotiation.settle("да", _STRANGER) is None
    assert negotiation.is_pending()  # чужой ответ не снимает вопрос владельца


def test_the_question_never_sticks() -> None:
    # 🔴 «Да», сказанное потом совсем по другому поводу, ничего не разрешит.
    negotiation = _armed(_Clock())

    assert negotiation.settle("а что там с тестами?", _OWNER) is None
    assert not negotiation.is_pending()
    assert negotiation.settle("да", _OWNER) is None


def test_a_late_yes_does_not_run_an_irreversible_command() -> None:
    clock = _Clock()
    negotiation = _armed(clock)
    clock.moment = _START + PERMISSION_TTL + timedelta(seconds=1)

    assert negotiation.settle("да", _OWNER) is None


def test_the_window_is_wide_enough_for_a_person_away_from_the_phone() -> None:
    # Конвейер стоит и ждёт; пятиминутного окна «поднимаю?» здесь мало.
    clock = _Clock()
    negotiation = _armed(clock)
    clock.moment = _START + timedelta(minutes=20)

    assert negotiation.settle("да", _OWNER) == PermissionGranted(
        command="git push origin master", session_id="live-1"
    )


def test_a_new_question_displaces_the_old_one() -> None:
    clock = _Clock()
    negotiation = _armed(clock, command="git push origin master")
    negotiation.ask(command="rm -rf build", sender=_OWNER, session_id="live-1")

    assert negotiation.settle("да", _OWNER) == PermissionGranted(
        command="rm -rf build", session_id="live-1"
    )


def test_the_answer_remembers_which_session_asked() -> None:
    # Между вопросом и ответом сеанс мог смениться; «да» относится к ТОМУ сеансу.
    clock = _Clock()
    negotiation = PermissionNegotiation(clock=clock)
    negotiation.ask(command="rm -rf build", sender=_OWNER, session_id="live-7")

    answer = negotiation.settle("ага", _OWNER)

    assert isinstance(answer, PermissionGranted)
    assert answer.session_id == "live-7"


def test_a_yes_with_a_condition_is_not_a_yes() -> None:
    # 🔴 Предохранитель, унаследованный от «поднимаю?» осознанно: разрешение запускает
    # НЕОБРАТИМОЕ, поэтому «да, но сначала покажи дифф» — не «да». Вопрос при этом
    # снимается, и реплика идёт обычным путём (в сессию), а не толкует Бобом на свой лад.
    negotiation = _armed(_Clock())

    assert negotiation.settle("да, но сначала покажи дифф", _OWNER) is None
    assert not negotiation.is_pending()
