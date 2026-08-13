# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Шов канона: запрет о голосе вплетается в payload двери (BOB-096, срез 3).

Чистое ядро шва. Копипаста директивы по дверям — это ровно то, что уже сломалось
(запрет есть, но в одном месте), поэтому вплетение живёт ЗДЕСЬ, в единственном
месте, через которое проходит каждая дверь генерации, а сам текст канона приходит
инъекцией из :mod:`bob.personality.voice` (роутер домен не импортирует — обратное
ребро замкнуло бы цикл узлов).

Что пинается: канон доезжает до двери, которой он нужен; не доезжает до служебной;
не дублируется у той, что уже несёт его дословно (разговорный ход); машинной двери
достаётся формулировка без прозы; неподключённый шов оставляет payload байт-в-байт.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.generation_door import GenerationDoor
from bob.application.router.voice_canon import fold_voice_canon

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.kernel.ports import LLMMessage

_PROSE_CANON = "GUPPI ты не отыгрываешь: ни речи, ни мнения, ни поступков за него."
_MACHINE_CANON = "GUPPI — исполнитель без личности: речи и мнений у него нет."

_VOICE = GenerationDoor(speaks_as_bob=True, output_is_kept=True)
_MACHINE = GenerationDoor(
    speaks_as_bob=False, output_is_kept=True, answers_in_machine_format=True
)
_SERVICE = GenerationDoor(speaks_as_bob=False, output_is_kept=False)

_PROMPT: tuple[LLMMessage, ...] = (
    {"role": "system", "content": "Напиши одну короткую мысль."},
    {"role": "user", "content": "как оно?"},
)


def _canon(*, prose_answer: bool) -> str:
    return _PROSE_CANON if prose_answer else _MACHINE_CANON


def _contents(messages: Sequence[LLMMessage]) -> list[str]:
    return [message.get("content", "") for message in messages]


def test_the_canon_reaches_a_door_that_needs_it() -> None:
    folded = fold_voice_canon(_PROMPT, door=_VOICE, canon=_canon)

    assert _contents(folded) == [_PROSE_CANON, *_contents(_PROMPT)]
    # Роль системная — иначе модель прочтёт запрет как чужую реплику.
    assert folded[0]["role"] == "system"


def test_a_service_door_gets_the_payload_untouched() -> None:
    folded = fold_voice_canon(_PROMPT, door=_SERVICE, canon=_canon)

    assert _contents(folded) == _contents(_PROMPT)


def test_a_machine_format_door_gets_the_form_that_does_not_call_for_prose() -> None:
    folded = fold_voice_canon(_PROMPT, door=_MACHINE, canon=_canon)

    assert _contents(folded) == [_MACHINE_CANON, *_contents(_PROMPT)]


def test_a_door_that_already_carries_the_canon_gets_no_second_copy() -> None:
    # Разговорный ход несёт запрет дословно в базовой персоне (BOB-090.D3): шов обязан
    # ДОТЯГИВАТЬСЯ, а не удваивать уже сказанное.
    carrying: tuple[LLMMessage, ...] = (
        {"role": "system", "content": f"Ты Боб. {_PROSE_CANON} Отвечай в характере."},
        {"role": "user", "content": "привет"},
    )

    folded = fold_voice_canon(carrying, door=_VOICE, canon=_canon)

    assert _contents(folded) == _contents(carrying)


def test_an_unwired_seam_leaves_the_payload_byte_for_byte() -> None:
    folded = fold_voice_canon(_PROMPT, door=_VOICE, canon=None)

    assert _contents(folded) == _contents(_PROMPT)


def test_an_empty_canon_text_adds_no_empty_system_message() -> None:
    def blank(*, prose_answer: bool) -> str:
        del prose_answer
        return "   "

    folded = fold_voice_canon(_PROMPT, door=_VOICE, canon=blank)

    assert _contents(folded) == _contents(_PROMPT)


def test_a_message_without_content_does_not_blow_up_the_seam() -> None:
    # 🔴 Не всякое сообщение payload'а несёт текст: ход tool-loop'а кладёт ассистентский
    # ход с ``tool_calls`` и БЕЗ ``content``. Шов обязан его просто пропустить — иначе
    # проверка «уже несёт канон» роняла бы весь ход там, где ей нечего читать.
    contentless: tuple[LLMMessage, ...] = ({"role": "assistant"}, *_PROMPT)

    folded = fold_voice_canon(contentless, door=_VOICE, canon=_canon)

    assert _contents(folded[1:]) == _contents(contentless)
    assert folded[0]["content"] == _PROSE_CANON


def test_the_folded_payload_is_a_fresh_list() -> None:
    # Запрос заморожен, его ``messages`` переиспользуются при рескью-попытке — шов не
    # имеет права править исходную последовательность на месте.
    original = list(_PROMPT)

    fold_voice_canon(original, door=_VOICE, canon=_canon)

    assert _contents(original) == _contents(_PROMPT)
