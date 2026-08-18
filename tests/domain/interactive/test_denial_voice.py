# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Голос Боба, когда он упёрся в запрет (BOB-088, срез 3).

Предмет: :mod:`bob.interactive.denial_voice` — то, ЧТО владелец прочтёт в личке, когда
сессия не смогла что-то сделать без его слова.

Требование владельца от 2026-08-15 категорично и проверяется здесь как поведение, а не
как пожелание: «всё общение с Бобом должно быть живым и человечным», «давай все словами и
живой речью» — значит ни кнопок, ни слеш-команд, ответ словами. И раньше того (BOB-096)
владелец уже сказал про шаблонную сборку: «выглядит очень скриптовано, а не человечно».
Поэтому тесты смотрят не только «есть ли команда в тексте», но и на конструкцию: разные
запреты звучат РАЗНЫМИ словами Боба, пустых слотов не бывает, служебная строка CLI внутрь
реплики попасть не может.
"""

from __future__ import annotations

import re

import pytest

from bob.interactive.denial_voice import (
    permission_declined,
    permission_lifted,
    permission_question,
    permission_stuck,
    permission_unreachable,
)
from bob.interactive.permission_denial import PermissionDenial


def _denial(command: str, *, tool_name: str = "Bash") -> PermissionDenial:
    return PermissionDenial(tool_name=tool_name, tool_use_id="toolu_1", command=command)


_COMMANDS = [
    "git push origin bob/BOB-088",
    "gh pr merge 17 --squash",
    "rm -rf .worktrees/bob-088",
    "git reset --hard HEAD~1",
    "git remote set-url origin https://example.com/x.git",
    "curl -s https://example.com -o page.html",
    "python3 -c \"print(2+2)\"",
]


# --------------------------------------------------------------------------- #
# Вопрос владельцу: живая речь, без кнопок и слешей
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("command", _COMMANDS)
def test_the_question_says_exactly_what_bob_wanted_to_do(command: str) -> None:
    text = permission_question(_denial(command))

    assert command in text
    assert text.rstrip().endswith("?")


@pytest.mark.parametrize("command", _COMMANDS)
def test_the_question_asks_for_a_word_and_offers_nothing_to_press(command: str) -> None:
    # 🔴 Решение владельца: ни кнопок, ни слеш-команд. Слеш в тексте команды (например
    # в пути) допустим, но собственной команды-ответа Боб не предлагает.
    text = permission_question(_denial(command)).replace(command, "")

    assert "/" not in text
    for scripted in ("нажми", "кнопк", "approve", "да/нет", "[", "]"):
        assert scripted not in text.lower()


def test_different_denials_do_not_sound_like_one_template() -> None:
    # Скриптовость — это когда меняется только подстановка. Здесь меняются слова Боба.
    texts = [permission_question(_denial(command)) for command in _COMMANDS]
    without_commands = [
        text.replace(command, "") for text, command in zip(texts, _COMMANDS, strict=True)
    ]

    assert len(set(without_commands)) >= 5


def test_the_push_and_the_deletion_are_not_the_same_worry() -> None:
    push = permission_question(_denial("git push origin master"))
    delete = permission_question(_denial("rm -rf .git"))

    assert push != delete
    assert push.replace("git push origin master", "") != delete.replace("rm -rf .git", "")


def test_bob_speaks_of_himself_in_the_first_person() -> None:
    # Дефект BOB-096: реплика говорила о Бобе в третьем лице, потому что её текст
    # приходил снаружи. Здесь слова Боба — его собственные.
    text = permission_question(_denial("git push origin master"))

    assert re.search(r"\b(я|мне|хочу|упёрся|дошёл|надо)\b", text.lower())


# --------------------------------------------------------------------------- #
# Пустых слотов не бывает по конструкции
# --------------------------------------------------------------------------- #


def test_a_denial_bob_cannot_lift_is_told_without_a_pointless_question() -> None:
    # 🔴 WebFetch отказывают ЦЕЛИКОМ: команды нет, разрешать точечно нечего — значит и
    # «разрешаешь?» спрашивать нечестно, «да» тут ничего не изменит. Но и молчать нельзя:
    # молча вставший конвейер и есть дефект, который лечит этот срез.
    text = permission_stuck(_denial("", tool_name="WebFetch"))

    assert "WebFetch" in text
    assert "?" not in text
    assert ".." not in text
    assert "  " not in text


def test_a_denial_of_nothing_at_all_is_still_a_sentence() -> None:
    text = permission_stuck(_denial("", tool_name=""))

    assert text
    assert ".." not in text
    assert "  " not in text
    assert "``" not in text


def test_a_question_stays_a_question_even_on_a_degenerate_denial() -> None:
    # Тотальность ядра: сюда без команды не ходят, но форма от этого не зависит — и
    # проверяется ДОСЛОВНО, иначе «пустой кусок фразы» мог бы оказаться не пустым.
    assert permission_question(_denial("", tool_name="")) == (
        "Упёрся в запрет. Сам такое не решаю. Разрешишь?"
    )


def test_the_service_line_of_the_cli_cannot_reach_the_reply() -> None:
    # 🔴 СТРУКТУРНО: билдер принимает только разбор отказа, а в нём поля ``message``
    # нет вовсе — английская строка CLI не может стать телом фразы ни при какой
    # доработке вызывающего (тот же приём, что в rule_voice / request_voice).
    assert not hasattr(PermissionDenial(tool_name="Bash", tool_use_id="t", command="x"), "message")


# --------------------------------------------------------------------------- #
# Ответы на «да» и «нет»
# --------------------------------------------------------------------------- #


def test_a_yes_is_answered_by_doing_it_and_saying_what() -> None:
    text = permission_lifted("git push origin master")

    assert "git push origin master" in text
    assert "/" not in text.replace("git push origin master", "")


def test_a_no_is_answered_shortly_and_without_reproach() -> None:
    text = permission_declined()

    assert text
    assert "?" not in text
    assert "/" not in text


def test_an_answer_that_arrives_too_late_is_named_honestly() -> None:
    # 🔴 Ограничение CLI, названное вслух: доразрешить НА МЕСТЕ нельзя, а если сессии
    # уже нет — повторять нечего. Молчание здесь было бы обманом.
    text = permission_unreachable()

    assert text
    assert "/" not in text


# --------------------------------------------------------------------------- #
# Дословный контракт: что именно прочитает владелец
# --------------------------------------------------------------------------- #
#
# 🔴 Сознательный change-detector, по образцу первого кадра конвейера (срез 2). Реплика
# Боба — то, что человек читает в личке; менять её можно только осознанно, вместе с этим
# тестом. Он же делает mutation-гейт настоящим: подстрочная проверка не убивает мутанта
# ``"XX…XX"`` (обёртка встаёт по краям литерала, середина цела), а равенство — убивает.
# Заодно он утверждает САМО СООТВЕТСТВИЕ «что за запрет → какими словами Боб о нём
# говорит»: подмена признака в разборе роняет ровно ту строку, чей смысл уехал.


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "git push origin bob/x",
            "Дошёл до места, где ветку надо толкнуть наружу — `git push origin bob/x`. "
            "Наружу я без твоего слова не хожу. Отправлять?",
        ),
        (
            "gh pr merge 17 --squash",
            "Работа доехала до мёржа — `gh pr merge 17 --squash`. "
            "Сливать — твой ход, не мой. Сливаем?",
        ),
        (
            "rm -rf build",
            "Хочу снести вот это — `rm -rf build`. "
            "Удаление обратно не отыграешь, поэтому спрашиваю. Сносить?",
        ),
        (
            "git reset --hard HEAD~1",
            "Хочу откатить рабочее дерево — `git reset --hard HEAD~1`. "
            "Незакоммиченное при этом пропадёт. Откатывать?",
        ),
        (
            "git remote set-url origin u",
            "Понадобилось переписать, куда смотрит этот репозиторий — "
            "`git remote set-url origin u`. Такое молча не делаю. Разрешишь?",
        ),
        (
            "curl -s https://e.com",
            "Мне тут надо сходить в сеть — `curl -s https://e.com`. "
            "В сеть без спроса не лезу. Можно?",
        ),
        (
            "wget -q https://e.com",
            "Мне тут надо сходить в сеть — `wget -q https://e.com`. "
            "В сеть без спроса не лезу. Можно?",
        ),
        (
            'python3 -c "print(1)"',
            'Упёрся в запрет — `python3 -c "print(1)"`. Сам такое не решаю. Разрешишь?',
        ),
    ],
)
def test_the_question_is_worded_exactly_like_this(command: str, expected: str) -> None:
    assert permission_question(_denial(command)) == expected


def test_the_stuck_line_is_worded_exactly_like_this() -> None:
    assert permission_stuck(_denial("", tool_name="WebFetch")) == (
        "Упёрся в запрет на инструмент `WebFetch` и снять его сам не могу — это уже "
        "настройка на твоей стороне. Пока обхожусь без него."
    )
    assert permission_stuck(_denial("", tool_name="")) == (
        "Упёрся в запрет и снять его сам не могу — это уже настройка на твоей стороне. "
        "Пока обхожусь без него."
    )


def test_the_three_short_answers_are_worded_exactly_like_this() -> None:
    assert permission_lifted("git push origin master") == "Понял, делаю: `git push origin master`"
    assert permission_lifted("  ") == "Понял, возвращаюсь к тому месту."
    assert permission_declined() == "Понял, не трогаю. Пойду дальше без этого."
    assert permission_unreachable() == (
        "Твоё «да» принял, но возвращаться уже некуда — та сессия кончилась. "
        "Скажи, если поднять заново."
    )
