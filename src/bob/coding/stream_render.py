# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""stream_render — чистый ПОЛНЫЙ рендер stream-json событий в DM-лайв-стрим (BOB-082.3).

:func:`render_stream_event` берёт ОДНО событие потока ``--output-format stream-json`` и
возвращает короткую live-строку ИЛИ ``None`` только для ЧИСТОГО шума (system-init,
heartbeat, пустое/неизвестное событие). В отличие от lossy
:func:`~bob.coding.narrate.narrate` (глотает большинство → нужен для НЕфлудящего
группового топика), рендерер отдаёт строку на КАЖДЫЙ значимый вид события — потому что
это firehose в ПРИВАТНУЮ личку owner'а (dev-канал BOB-082), где поток уместен и полезен:

* вызов инструмента — правка/запись/чтение файла, запуск теста, произвольная Bash-команда
  (в отличие от narrate ПОКАЗЫВАЕМ команду — owner смотрит терминал), поиск (Grep/Glob),
  прочий именованный инструмент — его имя;
* текст/прогресс ассистента (narrate его глотает как шум — здесь показываем);
* результат инструмента — «тесты прошли» / ошибка (narrate ошибку ПОДАВЛЯЕТ — здесь, в
  приватной личке, показываем trial-and-error детали);
* финальный ``result`` и верхнеуровневый ``error`` — итог/ошибка сессии.

Детерминированно, без I/O (mutation-цель BOB-082.5). Поддержаны вложенная (``tool_use`` в
``assistant.message.content``, ``tool_result`` в ``user.message.content``) и уплощённая
(``type`` = ``tool_use`` / ``tool_result`` напрямую) формы события — как у narrate.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

__all__ = ["render_stream_event"]

_MAX_TEXT = 200
_MAX_CMD = 120
_MAX_ERROR = 100
_WHITESPACE = re.compile(r"\s+")
_TEST_COMMAND = re.compile(r"\b(py)?test(s)?\b|\bunittest\b|\btox\b")
_TESTS_PASSED = re.compile(r"\b\d+\s+passed\b")

_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


def render_stream_event(event: Mapping[str, object]) -> str | None:
    """Свести stream-json событие к короткой live-строке DM-стрима или ``None`` (шум)."""
    handler = _HANDLERS.get(str(event.get("type", "")))
    return handler(event) if handler is not None else None


# --- Обработчики по типу события ----------------------------------------------


def _render_assistant(event: Mapping[str, object]) -> str | None:
    """Рендер ассистентского события: все значимые блоки (текст + tool_use) в строки."""
    lines = [_render_block(block) for block in _content_blocks(event)]
    kept = [line for line in lines if line is not None]
    return "\n".join(kept) if kept else None


def _render_user(event: Mapping[str, object]) -> str | None:
    """Рендер пользовательского события: результаты инструментов (успех-тест/ошибка)."""
    lines = [
        _render_tool_result(block)
        for block in _content_blocks(event)
        if block.get("type") == "tool_result"
    ]
    kept = [line for line in lines if line is not None]
    return "\n".join(kept) if kept else None


def _render_tool_use_event(event: Mapping[str, object]) -> str | None:
    """Рендер уплощённого ``tool_use`` события (type=tool_use напрямую)."""
    return _render_tool(str(event.get("name", "")), _as_mapping(event.get("input")))


def _render_result(event: Mapping[str, object]) -> str | None:
    """Рендер финального события: «готово» при успехе, иначе «ошибка: …»."""
    if _is_truthy(event.get("is_error")) or str(event.get("subtype", "success")) != "success":
        return _error_line(_first_str(event, ("result", "subtype")))
    return "готово"


def _render_error(event: Mapping[str, object]) -> str | None:
    """Рендер верхнеуровневого ``error`` события (в приватной личке показываем)."""
    return _error_line(_first_str(event, ("message", "error")))


# --- Рендер блоков / инструментов (чистые) ------------------------------------


def _render_block(block: Mapping[str, object]) -> str | None:
    """Рендер одного блока ассистентского сообщения (tool_use → инструмент, text → текст)."""
    kind = block.get("type")
    if kind == "tool_use":
        return _render_tool(str(block.get("name", "")), _as_mapping(block.get("input")))
    if kind == "text":
        return _render_text(str(block.get("text", "")))
    return None


def _render_tool(name: str, tool_input: Mapping[str, object]) -> str | None:
    """Рендер вызова инструмента (правка/чтение/тест/команда/поиск/прочее)."""
    if name in _EDIT_TOOLS:
        return f"правлю `{_basename(tool_input.get('file_path'))}`"
    if name == "Read":
        return f"читаю `{_basename(tool_input.get('file_path'))}`"
    if name == "Bash":
        return _render_bash(str(tool_input.get("command", "")))
    if name == "Grep":
        return f"ищу «{_truncate(str(tool_input.get('pattern', '')), _MAX_CMD)}»"
    if name == "Glob":
        return f"ищу файлы «{_truncate(str(tool_input.get('pattern', '')), _MAX_CMD)}»"
    return name or None


def _render_bash(command: str) -> str | None:
    """Рендер Bash-вызова: «гоняю тесты» для тест-команды, иначе показать команду."""
    text = command.strip()
    if not text:
        return None
    if _TEST_COMMAND.search(text):
        return "гоняю тесты"
    return f"$ {_truncate(text, _MAX_CMD)}"


def _render_text(text: str) -> str | None:
    """Рендер текста/прогресса ассистента (схлопнут и обрезан); пусто → ``None``."""
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return _truncate(collapsed, _MAX_TEXT) if collapsed else None


def _render_tool_result(block: Mapping[str, object]) -> str | None:
    """Рендер результата инструмента: ошибка (показываем) / «тесты прошли» / шум."""
    if _is_truthy(block.get("is_error")):
        return _error_line(_result_text(block))
    if _TESTS_PASSED.search(_result_text(block)):
        return "тесты прошли"
    return None


def _render_tool_result_event(event: Mapping[str, object]) -> str | None:
    """Рендер уплощённого ``tool_result`` события (type=tool_result напрямую)."""
    return _render_tool_result(event)


# Таблица «тип события → обработчик»; отсутствующий тип (system-init, неизвестное) → шум.
_HANDLERS: dict[str, Callable[[Mapping[str, object]], str | None]] = {
    "assistant": _render_assistant,
    "user": _render_user,
    "tool_use": _render_tool_use_event,
    "tool_result": _render_tool_result_event,
    "result": _render_result,
    "error": _render_error,
}


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
        parts = [str(item.get("text", "")) for item in content if isinstance(item, Mapping)]
        return " ".join(parts)
    return ""


def _basename(path: object) -> str:
    """Базовое имя файла из пути (без директорий); пусто → «файл»."""
    text = str(path or "").replace("\\", "/")
    name = text.rsplit("/", 1)[-1]
    return name or "файл"


def _error_line(detail: str) -> str:
    """Короткая строка ошибки «ошибка: <detail>» (схлопнута и обрезана)."""
    short = _WHITESPACE.sub(" ", detail).strip()[:_MAX_ERROR]
    return f"ошибка: {short}" if short else "ошибка"


def _truncate(text: str, limit: int) -> str:
    """Обрезать ``text`` до ``limit`` символов (с многоточием, если урезали)."""
    return text if len(text) <= limit else f"{text[:limit]}…"


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
