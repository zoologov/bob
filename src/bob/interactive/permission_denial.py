# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=domain

"""permission_denial — прочитать в потоке отказ и назвать, ЧЕГО Боб не смог (срез 3).

ОДНА ответственность: смотреть события живого сеанса и на каждом ``system`` /
``permission_denied`` отдавать :class:`PermissionDenial` — то, о чём можно спросить
владельца человеческими словами. Ни транспорта, ни реплик, ни решений: текст говорит
:mod:`bob.interactive.denial_voice`, а что с ним делать — менеджер сеанса.

🔴 ЗАЧЕМ ЗДЕСЬ ПАМЯТЬ О ВЫЗОВАХ (и почему без неё ядро было бы враньём). Живой прогон
настоящего ``claude`` 2.1.233 (протокол в комментарии беады ``bob-c3r.3``) показал, что
поле ``message`` события отказа несёт команду ДАЛЕКО НЕ ВСЕГДА:

* ``Permission to use Bash with command git push origin master has been denied.`` — да,
  когда сработал наш шаблон запрета (``decision_reason_type: subcommandResults``);
* ``This command requires approval`` — когда отказал ВСТРОЕННЫЙ гейт CLI (он же приходит
  на ``sh -c "…"``, ``git add``, ``python3 -c``): команды в строке нет;
* ``Claude requested permissions to use WebFetch, but you haven't granted it yet`` — отказ
  инструменту целиком.

Поэтому «чего я хотел» берётся из ВЫЗОВА, связанного по ``tool_use_id``, а служебная
строка CLI не произносится вовсе. Это не придирка к стилю: подстановка чужого текста в
реплику — ровно тот дефект, который лечил :mod:`bob.proactivity.rule_voice` (BOB-096),
и здесь он был бы английской фразой внутри русского вопроса владельцу.

Память ОГРАНИЧЕНА (``remember``): живая сессия делает тысячи вызовов, а нужен всегда
только недавний.

🔴 Чего здесь СОЗНАТЕЛЬНО НЕТ: дедупликации отказов. Первая версия помнила, о чём уже
спрошено, — «поток ведь несёт отказ дважды, системным кадром и внутри ``tool_result``».
Проверка собственных же записей живого прогона это ОПРОВЕРГЛА: повтор приходит событием
``user`` с блоком ``tool_result``, а не вторым ``system``/``permission_denied``, то есть
дедупликация лечила то, чего не бывает. Убрана: неизмеренная машинерия — это ровно тот
класс, который этот эпик и ловит. «Не спрашивать дважды» держит гвардия ВЫШЕ, в менеджере
(один висящий вопрос за раз), и она измерена тестом.

Чисто и детерминированно (mutation-цель): ни I/O, ни часов, ни глобалов.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DenialWatch", "PermissionDenial"]

# Сколько последних вызовов помнить: отказ приходит следом за своим вызовом, так что
# глубина нужна лишь на всплеск параллельных tool_use в одном ходе.
_REMEMBERED_CALLS = 64


@dataclass(frozen=True, slots=True)
class PermissionDenial:
    """Отказ, как о нём можно спросить владельца: чем, по какому вызову и чего именно.

    ``command`` пуст, когда вызов не был командой (``WebFetch``) или его кадр до нас не
    дошёл: пустота честнее выдуманной команды, и голос это учитывает.
    """

    tool_name: str
    tool_use_id: str
    command: str


class DenialWatch:
    """Проследить поток и назвать отказ (память о недавних вызовах — внутри)."""

    def __init__(self, *, remember: int = _REMEMBERED_CALLS) -> None:
        self._calls: OrderedDict[str, str] = OrderedDict()
        self._remember = remember

    def see(self, event: Mapping[str, object]) -> PermissionDenial | None:
        """Посмотреть одно событие; вернуть отказ, если это он, иначе ``None``.

        Вызовы запоминаются по дороге (обе формы кадра — вложенная в ``assistant`` и
        уплощённая ``tool_use``), поэтому к моменту отказа Боб уже знает, чего хотел.
        """
        if _is_denial(event):
            return self._denial(event)
        for call_id, command in _calls_in(event):
            self._keep(call_id, command)
        return None

    def _denial(self, event: Mapping[str, object]) -> PermissionDenial:
        """Собрать отказ по событию, назвав чего Боб хотел (вызов помнится по id)."""
        tool_use_id = _text(event.get("tool_use_id"))
        return PermissionDenial(
            tool_name=_text(event.get("tool_name")),
            tool_use_id=tool_use_id,
            command=self._calls.get(tool_use_id, ""),
        )

    def _keep(self, call_id: str, command: str) -> None:
        """Запомнить вызов, вытеснив самый старый сверх ``remember``."""
        self._calls[call_id] = command
        self._calls.move_to_end(call_id)
        while len(self._calls) > self._remember:
            self._calls.popitem(last=False)


def _is_denial(event: Mapping[str, object]) -> bool:
    """Это ли отказ в разрешении — ОБА поля, а не только говорящий ``subtype``."""
    return event.get("type") == "system" and event.get("subtype") == "permission_denied"


def _calls_in(event: Mapping[str, object]) -> list[tuple[str, str]]:
    """Вызовы инструментов в событии: пары «id вызова → команда» (её может не быть)."""
    if event.get("type") == "tool_use":
        return _one_call(event)
    blocks = _content_blocks(event)
    calls: list[tuple[str, str]] = []
    for block in blocks:
        if block.get("type") == "tool_use":
            calls += _one_call(block)
    return calls


def _one_call(block: Mapping[str, object]) -> list[tuple[str, str]]:
    """Пара «id вызова → команда» из одного tool_use-блока (без id — не помним)."""
    call_id = _text(block.get("id"))
    if not call_id:
        return []
    payload = block.get("input")
    command = _text(payload.get("command")) if isinstance(payload, dict) else ""
    return [(call_id, command)]


def _content_blocks(event: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Блоки ``message.content`` события (не список / не маппинги — пусто)."""
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _text(value: object) -> str:
    """Строковое поле события; не-строка читается как отсутствующее, а не как текст."""
    return value if isinstance(value, str) else ""
