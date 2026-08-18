# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Одноразовый ``coder.clone_root`` для тестов проводки — чтобы сборка не писала в дерево.

ОДНА ответственность: подставить конфигу каталог для файлов окружения спавна, если тест
его не задал. Сборка изоляции (``_build_spawn_isolation``) МАТЕРИАЛИЗУЕТ подменный
git-конфиг и пустой каталог ``gh`` на диске, а с bob-c3r.1 безопасная дорога — ДЕФОЛТ,
поэтому это делает КАЖДАЯ сборка кодера/интерактива, а не только та, где флаг задан явно.
Без этой подстановки такие тесты писали бы ``<репозиторий>/.clones/.spawn-env`` в рабочее
дерево (residue пред-существовал там, где флаг задавали явно, — теперь он был бы у всех).

Тесты, для которых КОРЕНЬ и есть предмет (``test_workspace_wiring``: относительный путь
привязан к корню репозитория, а не к текущему каталогу), задают ``clone_root`` сами — их
значение уважается как есть.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping

__all__ = ["with_a_throwaway_clone_root"]

#: Один каталог на прогон: содержимое обезличено (подменный конфиг + пустой ``gh``),
#: поэтому делить его между тестами безопасно, а плодить по каталогу на тест незачем.
_THROWAWAY_ROOT = tempfile.mkdtemp(prefix="bob-test-clone-root-")


def with_a_throwaway_clone_root(config: Mapping[str, object]) -> dict[str, object]:
    """Копия ``config``, где у секции ``coder`` есть ``clone_root`` вне рабочего дерева."""
    coder = config.get("coder")
    section = dict(coder) if isinstance(coder, Mapping) else {}
    section.setdefault("clone_root", _THROWAWAY_ROOT)
    return {**config, "coder": section}
