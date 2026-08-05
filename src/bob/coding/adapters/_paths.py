# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""Проверка вложенности пути перед разрушающей операцией (BOB-089, срез A).

Один предикат, общий для обоих адаптеров рабочего места (linked worktree и клон): путь,
который сейчас будет отдан удалению, обязан быть СТРОГИМ потомком настроенного корня.
Считается на symlink-разрешённых реальных путях, поэтому ни сам корень, ни побег из него
(``..``-траверсал, symlink наружу, абсолютный ``/etc``) удалению не подлежит.

Вынесено в общий модуль по образцу :mod:`bob.coding.adapters._branch`: проверка
одинаковая, а последствия ошибки — потеря данных owner'а, поэтому второй копии у неё быть
не должно.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["is_strict_child"]


def is_strict_child(path: str, root: Path | str) -> bool:
    """Разрешается ли ``path`` в строгого потомка ``root`` (пустой путь — нет)."""
    if not path:
        return False
    real_target = Path(os.path.realpath(path))
    real_root = Path(os.path.realpath(root))
    return real_root in real_target.parents
