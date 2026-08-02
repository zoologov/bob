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

__all__ = ["chunk_for_telegram", "render_stream_event"]

_MAX_TEXT = 200
_MAX_CMD = 120
_MAX_ERROR = 100
# Щедрый (но конечный) кэп verbose tool-результата — курирование INV-3: показываем
# существенный кусок вывода, а не полный дамп.
_MAX_RESULT = 1500
# Верхняя граница одного Telegram plain-text сообщения (наследуем PLAIN_TEXT_LIMIT).
_TELEGRAM_PLAIN_LIMIT = 4096
_FENCE = "```"
_TRUNCATED_MARK = "…(обрезано)"
_WHITESPACE = re.compile(r"\s+")
_TEST_COMMAND = re.compile(r"\b(py)?test(s)?\b|\bunittest\b|\btox\b")
_TESTS_PASSED = re.compile(r"\b\d+\s+passed\b")
# Разбить текст на сегменты, чередующиеся «проза / fenced-код-блок» (нечётные — код).
_CODE_FENCE_SPLIT = re.compile(r"(```.*?```)", re.DOTALL)
_TRAILING_WS = re.compile(r"[ \t]+\n")
_MULTI_BLANK = re.compile(r"\n{3,}")

_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


def render_stream_event(event: Mapping[str, object], *, verbose: bool = False) -> str | None:
    """Свести stream-json событие к live-строке DM-стрима или ``None`` (шум).

    ``verbose=False`` (груп-нарратив BOB-082) — краткие строки байт-в-байт как раньше.
    ``verbose=True`` (интерактив-DM BOB-083) — курированный полный rich-рендер:
    assistant-текст целиком с markdown-passthrough, компактные rich-строки вызовов,
    tool-результат щедро капнут в ``` код-блоке ``` + читаемые ошибки (INV-1..3).
    """
    handler = _HANDLERS.get(str(event.get("type", "")))
    return handler(event, verbose=verbose) if handler is not None else None


# --- Обработчики по типу события ----------------------------------------------


def _render_assistant(event: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер ассистентского события: все значимые блоки (текст + tool_use) в строки."""
    lines = [_render_block(block, verbose=verbose) for block in _content_blocks(event)]
    kept = [line for line in lines if line is not None]
    return "\n".join(kept) if kept else None


def _render_user(event: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер пользовательского события: результаты инструментов (успех-тест/ошибка)."""
    lines = [
        _render_tool_result(block, verbose=verbose)
        for block in _content_blocks(event)
        if block.get("type") == "tool_result"
    ]
    kept = [line for line in lines if line is not None]
    return "\n".join(kept) if kept else None


def _render_tool_use_event(event: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер уплощённого ``tool_use`` события (type=tool_use напрямую)."""
    name = str(event.get("name", ""))
    return _render_tool(name, _as_mapping(event.get("input")), verbose=verbose)


def _render_result(event: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер финального события: «готово» при успехе, иначе «ошибка: …»."""
    if _is_truthy(event.get("is_error")) or str(event.get("subtype", "success")) != "success":
        return _error_line(_first_str(event, ("result", "subtype")), verbose=verbose)
    return "готово"


def _render_error(event: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер верхнеуровневого ``error`` события (в приватной личке показываем)."""
    return _error_line(_first_str(event, ("message", "error")), verbose=verbose)


# --- Рендер блоков / инструментов (чистые) ------------------------------------


def _render_block(block: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер одного блока ассистентского сообщения (tool_use → инструмент, text → текст)."""
    kind = block.get("type")
    if kind == "tool_use":
        name = str(block.get("name", ""))
        return _render_tool(name, _as_mapping(block.get("input")), verbose=verbose)
    if kind == "text":
        return _render_text(str(block.get("text", "")), verbose=verbose)
    return None


def _render_tool(name: str, tool_input: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер вызова инструмента (правка/чтение/тест/команда/поиск/прочее).

    В ``verbose`` — компактные rich-строки с эмодзи и путями/паттернами в моно/inline-код;
    иначе краткие груп-строки байт-в-байт.
    """
    if name in _EDIT_TOOLS:
        prefix = "✏️ правлю" if verbose else "правлю"
        return f"{prefix} `{_basename(tool_input.get('file_path'))}`"
    if name == "Read":
        prefix = "📄 читаю" if verbose else "читаю"
        return f"{prefix} `{_basename(tool_input.get('file_path'))}`"
    if name == "Bash":
        return _render_bash(str(tool_input.get("command", "")), verbose=verbose)
    if name == "Grep":
        prefix = "🔍 ищу" if verbose else "ищу"
        return f"{prefix} «{_truncate(str(tool_input.get('pattern', '')), _MAX_CMD)}»"
    if name == "Glob":
        prefix = "🔍 ищу файлы" if verbose else "ищу файлы"
        return f"{prefix} «{_truncate(str(tool_input.get('pattern', '')), _MAX_CMD)}»"
    return name or None


def _render_bash(command: str, *, verbose: bool) -> str | None:
    """Рендер Bash-вызова: «гоняю тесты» для тест-команды, иначе показать команду."""
    text = command.strip()
    if not text:
        return None
    if _TEST_COMMAND.search(text):
        return "🧪 гоняю тесты" if verbose else "гоняю тесты"
    truncated = _truncate(text, _MAX_CMD)
    return f"$ `{truncated}`" if verbose else f"$ {truncated}"


def _render_text(text: str, *, verbose: bool) -> str | None:
    """Рендер текста/прогресса ассистента; пусто → ``None``.

    В ``verbose`` — ЦЕЛИКОМ с markdown-passthrough (аккуратное схлопывание лишних пробелов
    без порчи fenced-код-блоков); иначе схлопнут в одну строку и обрезан до ``_MAX_TEXT``.
    """
    if verbose:
        collapsed = _collapse_prose(text)
        return collapsed or None
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return _truncate(collapsed, _MAX_TEXT) if collapsed else None


def _render_tool_result(block: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер результата инструмента.

    В ``verbose`` — щедро капнутый вывод в ``` код-блоке ``` (ошибка — с префиксом);
    иначе только ошибка / «тесты прошли», прочий успех — шум.
    """
    if verbose:
        return _render_tool_result_verbose(block)
    if _is_truthy(block.get("is_error")):
        return _error_line(_result_text(block), verbose=False)
    if _TESTS_PASSED.search(_result_text(block)):
        return "тесты прошли"
    return None


def _render_tool_result_verbose(block: Mapping[str, object]) -> str | None:
    """Verbose-рендер tool-результата: капнутый вывод в код-блоке; пусто → шум."""
    text = _result_text(block)
    if not text.strip():
        return None
    fenced = _fenced_block(_cap_result(text))
    return f"ошибка:\n{fenced}" if _is_truthy(block.get("is_error")) else fenced


def _render_tool_result_event(event: Mapping[str, object], *, verbose: bool) -> str | None:
    """Рендер уплощённого ``tool_result`` события (type=tool_result напрямую)."""
    return _render_tool_result(event, verbose=verbose)


# Таблица «тип события → обработчик»; отсутствующий тип (system-init, неизвестное) → шум.
_Handler = Callable[..., str | None]
_HANDLERS: dict[str, _Handler] = {
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


def _error_line(detail: str, *, verbose: bool) -> str:
    """Строка ошибки «ошибка: <detail>».

    В ``verbose`` — читаемо: детали в код-блоке, щедро капнуты (трейсбеки многострочны);
    иначе схлопнута в одну строку и обрезана до ``_MAX_ERROR``.
    """
    if verbose:
        cleaned = detail.strip()
        return f"ошибка:\n{_fenced_block(_cap_result(cleaned))}" if cleaned else "ошибка"
    short = _WHITESPACE.sub(" ", detail).strip()[:_MAX_ERROR]
    return f"ошибка: {short}" if short else "ошибка"


def _collapse_prose(text: str) -> str:
    """Схлопнуть лишние пробелы прозы, НЕ трогая fenced-код-блоки.

    Вне ``` ... ``` — снять хвостовые пробелы строк и схлопнуть 3+ пустых строки до одной
    пустой; код-блоки отдаются verbatim (двойные пробелы/отступы кода сохранены).
    """
    segments = _CODE_FENCE_SPLIT.split(text)
    rendered = [
        part if index % 2 == 1 else _MULTI_BLANK.sub("\n\n", _TRAILING_WS.sub("\n", part))
        for index, part in enumerate(segments)
    ]
    return "".join(rendered).strip()


def _fenced_block(text: str) -> str:
    """Обернуть ``text`` в fenced-код-блок (``` ... ```)."""
    return f"{_FENCE}\n{text}\n{_FENCE}"


def _cap_result(text: str) -> str:
    """Капнуть tool-вывод до ``_MAX_RESULT`` символов с маркером обрезки."""
    return text if len(text) <= _MAX_RESULT else f"{text[:_MAX_RESULT]}\n{_TRUNCATED_MARK}"


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


# --- Чанкинг для Telegram (чистый, mutation-цель BOB-085.1) -------------------


def chunk_for_telegram(text: str, *, limit: int = _TELEGRAM_PLAIN_LIMIT) -> list[str]:
    """Разбить ``text`` на куски ≤ ``limit`` символов по границам строк.

    Куски режутся по ``\\n`` (не посреди строки, если можно). Fenced-код-блок НЕ рвётся:
    если граница попадает внутрь открытого ``` блока, fence закрывается в конце куска и
    ПЕРЕОТКРЫВАЕТСЯ (с языковым тегом) в начале следующего — каждый кусок остаётся валидным
    markdown. Одиночная строка длиннее ``limit`` жёстко режется (последнее средство).
    Детерминированно, без I/O.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    in_fence = False
    fence_lang = ""
    for raw_line in text.split("\n"):
        for segment in _hard_split_line(raw_line, limit):
            separator = 1 if current else 0
            reserve = len(_FENCE) + 1 if in_fence else 0
            if current and current_len + separator + len(segment) + reserve > limit:
                if in_fence:
                    current.append(_FENCE)
                chunks.append("\n".join(current))
                if in_fence:
                    opener = _FENCE + fence_lang
                    current = [opener]
                    current_len = len(opener)
                else:
                    current = []
                    current_len = 0
                separator = 1 if current else 0
            current.append(segment)
            current_len += separator + len(segment)
            stripped = segment.strip()
            if stripped.startswith(_FENCE):
                in_fence = not in_fence
                fence_lang = "" if not in_fence else stripped[len(_FENCE) :]
    if current:
        chunks.append("\n".join(current))
    return chunks


def _hard_split_line(line: str, limit: int) -> list[str]:
    """Жёстко порезать одну сверхдлинную строку на куски ≤ ``limit`` (последнее средство)."""
    if len(line) <= limit:
        return [line]
    return [line[start : start + limit] for start in range(0, len(line), limit)]
