# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Безопасные имена ветки coding-сессии — чистая slug-функция (BOB-039 .1).

:func:`worktree_branch` превращает свободный текст задачи в безопасное имя ветки
``bob/<slug>``: lowercase, только ascii ``[a-z0-9]`` (рунические/кириллица
отбрасываются), любые иные символы (пробелы, точки, слэши, спецсимволы) схлопываются
в дефис, ведущие/хвостовые дефисы срезаются, длина ограничена. Это закрывает
path-инъекции (``..``, слэши, пробелы не попадают в имя) и даёт детерминированный,
git-валидный slug; пустой результат заменяется непустым fallback'ом.
"""

from __future__ import annotations

import re

__all__ = ["workspace_branch", "worktree_branch"]

_BRANCH_PREFIX = "bob"
# Namespace-инфикс долгоживущего workspace (BOB-087.D1): персистентная ветка
# ``bob/epic-<slug>`` живёт в своём пространстве и НИКОГДА не пересекается с эфемерной
# посессионной ``bob/<slug>``.
_WORKSPACE_INFIX = "epic"
_FALLBACK_SLUG = "task"
_SLUG_MAX_LEN = 40
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def worktree_branch(task: str) -> str:
    """Вернуть безопасное имя ветки ``bob/<slug>`` для ``task`` (чистая функция)."""
    return f"{_BRANCH_PREFIX}/{_slugify(task)}"


def workspace_branch(name: str) -> str:
    """Вернуть имя ветки ДОЛГОЖИВУЩЕГО workspace ``bob/epic-<slug>`` (чистая функция).

    BOB-087.D1: детерминированная политика «имя→ветка» для персистентного,
    накапливающего работу между сессиями worktree. Тот же безопасный slug, что и у
    эфемерной :func:`worktree_branch`, но в отдельном ``epic-`` namespace — так
    долгоживущий workspace не сталкивается с посессионной веткой того же имени, а
    результат остаётся валидной ``bob/<slug>``-формой (:func:`is_safe_branch`).
    """
    return f"{_BRANCH_PREFIX}/{_WORKSPACE_INFIX}-{_slugify(name)}"


def _slugify(task: str) -> str:
    """Свести ``task`` к безопасному ascii-slug (непустому, ограниченной длины)."""
    ascii_only = task.encode("ascii", "ignore").decode("ascii").lower()
    slug = _NON_SLUG.sub("-", ascii_only).strip("-")
    slug = slug[:_SLUG_MAX_LEN].strip("-")
    return slug or _FALLBACK_SLUG
