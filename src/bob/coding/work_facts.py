# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Аккумулятор ключевых фактов coding-сессии — чистое доменное ядро (BOB-087.B1).

:class:`WorkFactsAccumulator` сворачивает сырой поток stream-json событий, который сессия
и так порождает, в маленький ОГРАНИЧЕННЫЙ снимок :class:`SessionKeyFacts`: тронутые файлы
(дедуп, кэп), прошли/упали ли тесты и короткие «что сломалось» выжимки ошибок (дедуп, кэп).
Это ДИСТИЛЛЯТ существа сессии, а НЕ firehose (урок BOB-076 флуд): system-init, чистая
проза ассистента и неизвестные события — шум и игнорируются. I/O-free и детерминированно
(mutation-цель): парсит те же вложенную/уплощённую формы события, что :mod:`~bob.coding.narrate`.

Границы намеренны — сессия трогает много файлов и печатает много вывода; неограниченное
накопление вернуло бы флуд, поэтому списки дедуплятся и режутся по кэпу.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "SessionKeyFacts",
    "WorkFactsAccumulator",
    "WorkOutcome",
]

# Bounds — a session may touch many files and print a lot; keep the substance, drop the flood.
_MAX_FILES = 24
_MAX_ERRORS = 8
_MAX_ERROR_LEN = 200

_WHITESPACE = re.compile(r"\s+")
_TEST_COMMAND = re.compile(r"\b(py)?test(s)?\b|\bunittest\b|\btox\b")
_TESTS_PASSED = re.compile(r"\b\d+\s+passed\b")
_TESTS_FAILED = re.compile(r"\b\d+\s+(failed|errors?)\b")

# File-touching tools whose ``file_path`` names a file worked on this session.
_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
_FILE_TOOLS = _EDIT_TOOLS | {"Read"}


class WorkOutcome(StrEnum):
    """Как завершилась арка сессии (вход дистиллятора — рамка эпизода)."""

    FINISHED = "finished"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class SessionKeyFacts:
    """Ограниченный снимок существа сессии (вход дистиллятора).

    ``files`` — базовые имена тронутых файлов (дедуп, кэп); ``tests_passed`` /
    ``tests_failed`` — видели ли «N passed» / «N failed»; ``errors`` — короткие выжимки
    того, что сломалось (дедуп, кэп). Всё опционально: пустой снимок — «нечего дистиллировать».
    """

    files: tuple[str, ...] = ()
    tests_passed: bool = False
    tests_failed: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        """Нет ни одного факта — дистиллировать/писать нечего (best-effort пропуск)."""
        return not (self.files or self.tests_passed or self.tests_failed or self.errors)


class WorkFactsAccumulator:
    """Сворачивает поток stream-json событий в :class:`SessionKeyFacts` (bounded, I/O-free)."""

    def __init__(self) -> None:
        self._files: list[str] = []
        self._tests_passed = False
        self._tests_failed = False
        self._errors: list[str] = []

    def observe(self, event: Mapping[str, object]) -> None:
        """Учесть одно событие потока — извлечь КЛЮЧЕВЫЕ факты, не сырой лог.

        Поддержаны вложенная (``tool_use`` в ``assistant.message.content``, ``tool_result``
        в ``user.message.content``) и уплощённая (``type`` = ``tool_use`` / ``tool_result``)
        формы — как у :mod:`~bob.coding.narrate`. Шум (system-init, текст, неизвестное) — no-op.
        """
        kind = str(event.get("type", ""))
        if kind == "assistant":
            for block in _content_blocks(event):
                self._observe_tool_use(block)
        elif kind == "user":
            for block in _content_blocks(event):
                self._observe_tool_result(block)
        elif kind == "tool_use":
            self._observe_tool_use(event)
        elif kind == "tool_result":
            self._observe_tool_result(event)
        elif kind == "result":
            self._observe_result(event)
        elif kind == "error":
            self._add_error(_first_str(event, ("message", "error")))

    def snapshot(self) -> SessionKeyFacts:
        """Заморозить накопленное в неизменяемый снимок фактов."""
        return SessionKeyFacts(
            files=tuple(self._files),
            tests_passed=self._tests_passed,
            tests_failed=self._tests_failed,
            errors=tuple(self._errors),
        )

    # --- Internal folds -------------------------------------------------------

    def _observe_tool_use(self, block: Mapping[str, object]) -> None:
        """Учесть вызов инструмента: файл-инструмент → тронутый файл (прочее — шум)."""
        if str(block.get("name", "")) in _FILE_TOOLS:
            self._add_file(_basename(_as_mapping(block.get("input")).get("file_path")))

    def _observe_tool_result(self, block: Mapping[str, object]) -> None:
        """Учесть результат инструмента: pass/fail тестов + выжимку ошибки."""
        text = _result_text(block)
        if _is_truthy(block.get("is_error")):
            self._add_error(text)
        if _TESTS_PASSED.search(text):
            self._tests_passed = True
        if _TESTS_FAILED.search(text):
            self._tests_failed = True

    def _observe_result(self, event: Mapping[str, object]) -> None:
        """Учесть финальное событие: провал сессии → выжимка ошибки."""
        if _is_truthy(event.get("is_error")) or str(event.get("subtype", "success")) != "success":
            self._add_error(_first_str(event, ("result", "subtype")))

    def _add_file(self, name: str) -> None:
        """Добавить тронутый файл (дедуп, кэп ``_MAX_FILES``)."""
        if name and name not in self._files and len(self._files) < _MAX_FILES:
            self._files.append(name)

    def _add_error(self, text: str) -> None:
        """Добавить выжимку ошибки (схлопнута, обрезана, дедуп, кэп ``_MAX_ERRORS``)."""
        cleaned = _WHITESPACE.sub(" ", text).strip()[:_MAX_ERROR_LEN]
        if cleaned and cleaned not in self._errors and len(self._errors) < _MAX_ERRORS:
            self._errors.append(cleaned)


# --- Pure helpers (mirror narrate / stream_render event parsing) --------------


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
    """Базовое имя файла из пути (без директорий); пусто → ``""``."""
    text = str(path or "").replace("\\", "/")
    return text.rsplit("/", 1)[-1]


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
