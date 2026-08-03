# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Политика owner-ослаблений изоляции claude — чистое доменное ядро (BOB-087.D2).

ОДНА ответственность: решить, что вообще позволено передать процессу ``claude``, когда
owner сознательно ослабляет песочницу. Два ослабления, оба по умолчанию ВЫКЛЮЧЕНЫ:

* :func:`allowed_modes` / :func:`is_allowed_mode` — allowlist ``--permission-mode``.
  База — ``{plan, acceptEdits}`` (план без правок = гейт плана; применение правок внутри
  изолированного worktree). ``bypassPermissions`` появляется РОВНО при ``allow_bypass``
  — прежний абсолютный запрет «no bypassPermissions ever» снят ТОЛЬКО под явный
  owner-флаг ``coder.allow_bypass``, и флаг расширяет базу ровно на один режим, а не
  открывает allowlist целиком.
* :func:`extra_dir_argv` — доп-директории ``--add-dir`` (``coder.extra_dirs``). Это
  ослабляет worktree-изоляцию (claude видит пути ВНЕ worktree), поэтому вход
  санитайзится: пустые/пробельные отбрасываются, отбрасывается всё, что после strip
  начинается с ``-`` (иначе строка вида ``--dangerously-skip-permissions`` встала бы в
  argv-слот как ФЛАГ — argv-инъекция) или содержит NUL (невыразим в argv), остаток
  дедуплится с сохранением порядка и режется по кэпу.

I/O-free и детерминированно (mutation-цель). Пустой вход даёт ПУСТОЙ фрагмент, поэтому
дефолтный argv раннеров остаётся байт-в-байт прежним. Гарантия ослаблений — только
ВНУТРИ worktree: путь на main здесь не появляется (интеграция всегда через PR).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "BASE_PERMISSION_MODES",
    "BYPASS_PERMISSION_MODE",
    "MAX_EXTRA_DIRS",
    "allowed_modes",
    "extra_dir_argv",
    "is_allowed_mode",
    "is_safe_argv_value",
]

#: Базовый (всегда действующий) allowlist ``--permission-mode``.
BASE_PERMISSION_MODES: frozenset[str] = frozenset({"plan", "acceptEdits"})

#: Единственный режим, который добавляет owner-флаг ``coder.allow_bypass``.
BYPASS_PERMISSION_MODE = "bypassPermissions"

#: Кэп числа доп-директорий: ослабление изоляции остаётся ОГРАНИЧЕННЫМ.
MAX_EXTRA_DIRS = 8

_ADD_DIR_FLAG = "--add-dir"
_FLAG_PREFIX = "-"
_NUL = "\x00"


def allowed_modes(*, allow_bypass: bool) -> frozenset[str]:
    """Вернуть allowlist ``--permission-mode`` при данном owner-флаге (чистая функция)."""
    if allow_bypass:
        return BASE_PERMISSION_MODES | {BYPASS_PERMISSION_MODE}
    return BASE_PERMISSION_MODES


def is_allowed_mode(mode: str, *, allow_bypass: bool) -> bool:
    """Разрешён ли ``mode`` при данном owner-флаге (чистая функция).

    Совпадение ТОЧНОЕ: ни регистр, ни хвост (``plan; rm -rf /``), ни пустая строка не
    проходят — allowlist остаётся закрытым перечислением, а не префиксным матчем.
    """
    return mode in allowed_modes(allow_bypass=allow_bypass)


def extra_dir_argv(dirs: Sequence[str], *, max_dirs: int = MAX_EXTRA_DIRS) -> list[str]:
    """Свести доп-директории к argv-фрагменту ``["--add-dir", d, ...]`` (чистая функция).

    Санитайз (см. модульный докстринг): strip, отбрасывание пустых, флагоподобных
    (ведущий ``-``) и содержащих NUL записей, дедуп с сохранением порядка, кэп
    ``max_dirs`` на число ОСТАВЛЕННЫХ директорий (мусор лимит не съедает). Пустой вход
    (дефолт конфига) → пустой список: приписывать к argv нечего.
    """
    fragment: list[str] = []
    seen: set[str] = set()
    for raw in dirs:
        if len(seen) >= max_dirs:
            break
        candidate = raw.strip()
        if not is_safe_argv_value(candidate) or candidate in seen:
            continue
        seen.add(candidate)
        fragment += [_ADD_DIR_FLAG, candidate]
    return fragment


def is_safe_argv_value(candidate: str) -> bool:
    """Годится ли уже обрезанная строка как ЗНАЧЕНИЕ argv-слота (чистая функция).

    Общий примитив всего argv-семейства: не пустая, не начинается с ``-`` и не содержит
    NUL. Ведущий дефис — главное правило: строка вида ``--dangerously-skip-permissions``,
    поставленная в слот значения, парсером опций читается не как значение, а как
    ОТДЕЛЬНЫЙ ФЛАГ (argv-инъекция). NUL в argv невыразим.

    Используется обоими местами, где в argv попадает строка из внешнего источника:
    ``--add-dir`` (значение из конфига, :func:`extra_dir_argv`) и ``--resume`` (значение
    из колонки БД, :func:`bob.coding.argv_policy.build_interactive_argv` — BOB-087.D5b:
    у ``--resume`` этого guard'а не было, хотя слот ровно тот же).
    """
    if not candidate:
        return False
    if candidate.startswith(_FLAG_PREFIX):
        return False
    return _NUL not in candidate
