# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""narrate — чистый мэппер stream-json событий Claude Code → нарратив (BOB-039 .1).

:func:`narrate` берёт ОДНО событие потока ``--output-format stream-json`` и возвращает
короткую русскую нарратив-строку ИЛИ ``None`` для шумных/внутренних событий (system-init,
навигация, чистый текст ассистента). Детерминированно, без I/O — раннер (.2) только
стримит события, а use-case (.3) шлёт ненулевые строки в чат owner'а.

🔴 Канон (BOB-041 .3): фактическое исполнение — работа **GUPPI** (сухого исполнителя,
которым дирижирует Боб), поэтому каждая ненулевая строка АТРИБУТИРОВАНА GUPPI префиксом
``GUPPI:`` («GUPPI: правлю `<file>`», «GUPPI: гоняю тесты», «GUPPI: тесты прошли»,
«GUPPI: готово», «GUPPI: ошибка: …»). Боб-голос на гейтах живёт отдельно в
:mod:`~bob.domain.coding.session_voice`; здесь — только пер-событийный нарратив GUPPI.
Шум по-прежнему → ``None`` (без префикса).

Поддержаны две формы события: вложенная (как отдаёт сам Claude Code — ``tool_use`` в
``assistant.message.content``, ``tool_result`` в ``user.message.content``) и
уплощённая (``type`` = ``tool_use`` / ``tool_result`` напрямую), чтобы narrate был
устойчив к нормализации раннера.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

__all__ = ["narrate"]

# Канон (BOB-041 .3): пер-событийный нарратив — работа GUPPI, поэтому каждая
# ненулевая строка атрибутируется ему этим префиксом (Боб дирижирует, GUPPI пашет).
_GUPPI_PREFIX = "GUPPI: "

_MAX_ERROR_LEN = 80
_WHITESPACE = re.compile(r"\s+")
_TEST_COMMAND = re.compile(r"\b(py)?test(s)?\b|\bunittest\b|\btox\b")
_TESTS_PASSED = re.compile(r"\b\d+\s+passed\b")

_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


def _narrate_tool_use_event(event: Mapping[str, object]) -> str | None:
    """Нарратив уплощённого ``tool_use`` события (type=tool_use напрямую)."""
    return _narrate_tool(str(event.get("name", "")), _as_mapping(event.get("input")))


def _narrate_error_event(event: Mapping[str, object]) -> str | None:
    """Нарратив явного ``error`` события."""
    return _error_line(_first_str(event, ("message", "error", "result")))


def _narrate_assistant(event: Mapping[str, object]) -> str | None:
    """Нарратив из ассистентского события: первый значимый ``tool_use`` (текст — шум)."""
    for block in _content_blocks(event):
        if block.get("type") == "tool_use":
            line = _narrate_tool(str(block.get("name", "")), _as_mapping(block.get("input")))
            if line is not None:
                return line
    return None


def _narrate_user(event: Mapping[str, object]) -> str | None:
    """Нарратив из пользовательского события: первый значимый ``tool_result``."""
    for block in _content_blocks(event):
        if block.get("type") == "tool_result":
            line = _narrate_tool_result(block)
            if line is not None:
                return line
    return None


def _narrate_tool(name: str, tool_input: Mapping[str, object]) -> str | None:
    """Нарратив вызова инструмента (правка/чтение/тесты); прочее — шум (``None``)."""
    if name in _EDIT_TOOLS:
        return f"правлю `{_basename(tool_input.get('file_path'))}`"
    if name == "Read":
        return f"читаю `{_basename(tool_input.get('file_path'))}`"
    if name == "Bash" and _TEST_COMMAND.search(str(tool_input.get("command", ""))):
        return "гоняю тесты"
    return None


def _narrate_tool_result(block: Mapping[str, object]) -> str | None:
    """Нарратив результата инструмента: ошибка / «тесты прошли» / шум (``None``)."""
    if _is_truthy(block.get("is_error")):
        return _error_line(_result_text(block))
    if _TESTS_PASSED.search(_result_text(block)):
        return "тесты прошли"
    return None


def _narrate_result(event: Mapping[str, object]) -> str | None:
    """Нарратив финального события: «готово» при успехе, иначе «ошибка: …»."""
    if _is_truthy(event.get("is_error")) or str(event.get("subtype", "success")) != "success":
        return _error_line(_first_str(event, ("result", "subtype")))
    return "готово"


# Таблица «тип события → обработчик»; отсутствующий тип (system, неизвестное) → шум.
_HANDLERS: dict[str, Callable[[Mapping[str, object]], str | None]] = {
    "assistant": _narrate_assistant,
    "user": _narrate_user,
    "tool_use": _narrate_tool_use_event,
    "tool_result": _narrate_tool_result,
    "result": _narrate_result,
    "error": _narrate_error_event,
}


def narrate(event: Mapping[str, object]) -> str | None:
    """Свести stream-json событие к короткой GUPPI-нарратив-строке или ``None`` (шум).

    Ненулевая строка атрибутируется GUPPI префиксом ``GUPPI:`` (канон BOB-041 .3:
    фактическое исполнение — его работа). Шум остаётся ``None`` (без префикса).
    """
    handler = _HANDLERS.get(str(event.get("type", "")))
    line = handler(event) if handler is not None else None
    return f"{_GUPPI_PREFIX}{line}" if line is not None else None


# --- Хелперы (чистые) ---------------------------------------------------------


def _content_blocks(event: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Список блоков ``message.content``, отфильтрованный до маппингов."""
    message = _as_mapping(event.get("message"))
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, Mapping)]


def _result_text(block: Mapping[str, object]) -> str:
    """Извлечь текст результата (строка или список текст-блоков) в одну строку."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, Mapping)
        ]
        return " ".join(parts)
    return ""


def _basename(path: object) -> str:
    """Базовое имя файла из пути (без директорий); пусто → «файл»."""
    text = str(path or "").replace("\\", "/")
    name = text.rsplit("/", 1)[-1]
    return name or "файл"


def _error_line(detail: str) -> str:
    """Короткая строка ошибки «ошибка: <detail>» (схлопнута и обрезана)."""
    short = _WHITESPACE.sub(" ", detail).strip()[:_MAX_ERROR_LEN]
    return f"ошибка: {short}" if short else "ошибка"


def _first_str(event: Mapping[str, object], keys: tuple[str, ...]) -> str:
    """Первое непустое строковое значение среди ``keys``."""
    for key in keys:
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _as_mapping(value: object) -> Mapping[str, object]:
    """Вернуть ``value`` как маппинг (или пустой, если это не маппинг)."""
    return value if isinstance(value, Mapping) else {}


def _is_truthy(value: object) -> bool:
    """Истинность флага события (``True`` / ненулевое)."""
    return bool(value)
