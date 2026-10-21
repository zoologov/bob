# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Корень репозитория для тестов — один способ найти его.

ОДНА ответственность: подняться от этого файла до ближайшего каталога с ``pyproject.toml``.
Тест, который считает свои родительские каталоги сам (``Path(__file__).parents[3]``), верен
только на той глубине, на которой его написали; этот помощник верен на любой.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

__all__ = ["repository_root"]

_MANIFEST = "pyproject.toml"


@cache
def repository_root() -> Path:
    """Ближайший сверху каталог, в котором лежит ``pyproject.toml``."""
    here = Path(__file__).resolve()
    for directory in here.parents:
        if (directory / _MANIFEST).is_file():
            return directory
    msg = f"no {_MANIFEST} above {here}"
    raise FileNotFoundError(msg)
