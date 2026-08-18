# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Приложение владеет логом и РЕАЛЬНО ротирует его по размеру (BOB-103).

Корень (BOB-103, измерен): лог писал НЕ Python, а shell-редирект лаунчера
(``./bob``: ``>> logs/bob.log 2>&1``), а ``_configure_logging`` делал
``basicConfig`` в stderr — поэтому ``RotatingFileHandler`` сам по себе не помогал
и файл рос без предела (2.7 ГБ). Здесь приложение БЕРЁТ владение логом: ставит
``RotatingFileHandler`` (``maxBytes`` + ``backupCount`` из ``runtime.log_*``),
пишущий прямо в файл — независимо от того, кто запустил процесс (правильно и для
VPS/systemd, BOB-094).

Проверяем РЕАЛЬНО (не на фейке): пишем > ``maxBytes``, видим, что файл
ротировался (появился ``.1``), и что двойной записи нет (ровно один handler на
корень — не два, суммирующих одну строку дважды).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from bob.runtime.main import _configure_logging

if TYPE_CHECKING:
    from pathlib import Path


def _reset_root_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)


def test_configure_logging_installs_a_rotating_file_handler(tmp_path: Path) -> None:
    _reset_root_logging()
    log_file = tmp_path / "bob.log"
    try:
        _configure_logging(
            "INFO", log_file=log_file, max_bytes=1024, backup_count=3
        )
        root = logging.getLogger()
        rotating = [
            h for h in root.handlers if isinstance(h, RotatingFileHandler)
        ]
        assert len(rotating) == 1, "приложение владеет логом ровно одним handler'ом"
        assert rotating[0].maxBytes == 1024
        assert rotating[0].backupCount == 3
    finally:
        _reset_root_logging()


def test_log_really_rotates_past_max_bytes(tmp_path: Path) -> None:
    _reset_root_logging()
    log_file = tmp_path / "bob.log"
    try:
        # maxBytes мал → запись заведомо больше него → обязана ротироваться.
        _configure_logging(
            "INFO", log_file=log_file, max_bytes=512, backup_count=2
        )
        logger = logging.getLogger("bob.test.rotation")

        # Act: пишем заведомо больше maxBytes.
        for i in range(200):
            logger.info("rotation probe line %04d — %s", i, "x" * 60)
        for h in logging.getLogger().handlers:
            h.flush()

        # Assert: файл РЕАЛЬНО ротировался — появился бэкап .1.
        assert log_file.exists()
        assert (tmp_path / "bob.log.1").exists(), "лог не ротировался по размеру"
        # backupCount=2 → не больше .1 и .2 (старьё выкидывается).
        assert not (tmp_path / "bob.log.3").exists()
    finally:
        _reset_root_logging()


def test_no_double_write_on_repeated_configure(tmp_path: Path) -> None:
    # Двойной вызов _configure_logging (или повторная инициализация) НЕ должен
    # оставить два handler'а на один файл — иначе каждая строка пишется дважды и
    # ротация гонит наперегонки. Приложение владеет логом ОДНИМ handler'ом.
    _reset_root_logging()
    log_file = tmp_path / "bob.log"
    try:
        _configure_logging(
            "INFO", log_file=log_file, max_bytes=4096, backup_count=1
        )
        _configure_logging(
            "INFO", log_file=log_file, max_bytes=4096, backup_count=1
        )
        root = logging.getLogger()
        rotating = [
            h for h in root.handlers if isinstance(h, RotatingFileHandler)
        ]
        assert len(rotating) == 1, "повторная настройка не должна плодить handler'ы"

        logger = logging.getLogger("bob.test.double")
        logger.warning("single line probe")
        for h in root.handlers:
            h.flush()
        occurrences = log_file.read_text(encoding="utf-8").count("single line probe")
        assert occurrences == 1, "строка не должна писаться дважды"
    finally:
        _reset_root_logging()


def test_stderr_only_when_no_log_file(tmp_path: Path) -> None:
    # Без log_file (напр. тест/ad-hoc запуск) — прежнее поведение: stderr, никакого
    # файлового handler'а, никакой ротации.
    _reset_root_logging()
    try:
        _configure_logging("INFO", log_file=None, max_bytes=1024, backup_count=1)
        root = logging.getLogger()
        assert not any(
            isinstance(h, RotatingFileHandler) for h in root.handlers
        )
    finally:
        _reset_root_logging()
