# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=router

"""Канон о голосе дотягивается до КАЖДОЙ двери генерации (BOB-096, срез 3).

Запрет отыгрывать GUPPI (:func:`~bob.personality.voice.guppi_no_roleplay_directive`,
BOB-090.D3) существовал и был приклеен безусловно — но к ОДНОЙ двери, разговорному ходу.
Рефлексия, переоценка, консолидация, проактивная реплика, work_journal и ``extract_facts``
шли мимо, а их вывод ложится в память и возвращается к модели как её собственный few-shot:
Боб писал себе примеры нарушения канона и потом добросовестно им подражал (BOB-074).

🔴 Лечение — НЕ копипаста директивы в каждую дверь: приклеить руками в шесть мест значит
повторить сломанное, потому что седьмая дверь снова её не получит. Лечение — ШОВ здесь, в
единственном месте, через которое проходит каждая дверь (:class:`~bob.application.router.
llm_router.LLMRouter` строит payload ровно один раз, и рескью-попытка отправляет ТОТ ЖЕ
payload). Дверь не может родиться без канона, потому что она не может родиться без
роутера, а роутер спрашивает про неё :func:`~bob.application.router.generation_door.
door_for`, у которого нет варианта «не знаю»: незнакомая дверь считается голосом.

Сам ТЕКСТ канона приходит инъекцией (:class:`VoiceCanon`): он принадлежит персоне
(``personality``), а ``personality`` уже зависит от роутера — обратный импорт замкнул бы
цикл узлов (та же причина, по которой :mod:`bob.application.router.voice_integrity` живёт
здесь и получает от роутера «простые факты»). Композиционный корень подаёт реализацию, и
это стережёт архитектурный тест; неподключённый шов (тесты роутера, которые про персону
ничего не знают) оставляет payload байт-в-байт.

Форма запроса у двери своя: у прозаической (рефлексия, реплика) — полный запрет о голосе,
у машинной (JSON фактов, JSON правил) — та же суть без прозаических указаний, чтобы не
ломать контракт ответа. Какая именно — решает шов по свойству двери, а формулировки
остаются в персоне: здесь ни одной буквы канона нет.

Чистый модуль: один предикат и одна сборка списка, ни I/O, ни состояния.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.router.generation_door import GenerationDoor
    from bob.kernel.ports import LLMMessage

__all__ = ["VoiceCanon", "fold_voice_canon"]


class VoiceCanon(Protocol):
    """Шов текста канона: запрет о ГОЛОСЕ в форме, пригодной для этой двери.

    ``prose_answer`` — читает ли ответ двери человек (проза) или разбирает код (JSON,
    слово-метка). Единственный факт, который роутеру позволено сообщать персоне: сам
    выбор формулировок остаётся за ней.
    """

    def __call__(self, *, prose_answer: bool) -> str: ...


def _already_carries(messages: Sequence[LLMMessage], canon: str) -> bool:
    """Несёт ли payload этот канон ДОСЛОВНО (разговорный ход — несёт)."""
    return any(canon in message.get("content", "") for message in messages)


def fold_voice_canon(
    messages: Sequence[LLMMessage],
    *,
    door: GenerationDoor,
    canon: VoiceCanon | None,
) -> list[LLMMessage]:
    """Вплести канон о голосе в payload двери; вернуть новый список сообщений.

    Ничего не меняется для служебной двери (её вердикт никого не учит говорить), для
    неподключённого шва и для пустого текста канона. Дверь, которая уже несёт запрет
    дословно, второй копии не получает — шов ДОТЯГИВАЕТСЯ, а не удваивает. В остальных
    случаях канон встаёт ПЕРВЫМ системным сообщением, до промпта самой двери.
    """
    if canon is None or not door.needs_voice_canon:
        return list(messages)
    text = canon(prose_answer=not door.answers_in_machine_format).strip()
    if not text or _already_carries(messages, text):
        return list(messages)
    canon_message: LLMMessage = {"role": "system", "content": text}
    return [canon_message, *messages]
