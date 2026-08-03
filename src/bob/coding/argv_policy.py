# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Argv-политика живого claude-сеанса — чистое доменное ядро (BOB-087.D1/D2, D4b).

ОДНА ответственность: чем ИМЕННО параметризуется интерактивный ``claude`` и что забирается
из его первого кадра. Два чистых решения этой политики:

* :func:`build_interactive_argv` — собрать argv спавна: фиксированная голова
  (stream-json в обе стороны + ``--permission-mode``), затем стратегия возобновления
  (``--resume <id>`` строго вперёд ``--continue``), затем санитайзнутые ``--add-dir``
  (:func:`bob.coding.sandbox_policy.extra_dir_argv`). Дефолт — ФРЕШ-базлайн BOB-083
  байт-в-байт: без флагов ничего не приписывается.
* :func:`extract_session_id` — вынуть claude-session-id из ``init``-события потока
  (и только из него): именно этот id нужен позднему ``--resume``. Чужое событие,
  отсутствующее поле, не-строка и пустая строка дают ``None`` — id не выдумывается.

I/O-free и детерминированно (mutation-цель). 🔴 Ядра живут в ДОМЕНЕ, а не рядом с
транспортом (:mod:`bob.coding.adapters.interactive_runner`, который их вызывает), ровно
потому, что конвенция mutmut исключает ``*/adapters/*``: в домене у объявленных
mutation-целей есть постоянный гейт, в адаптере его не было (BOB-087.D4b).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.coding.sandbox_policy import extra_dir_argv, is_safe_argv_value

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["build_interactive_argv", "extract_session_id"]

#: Фиксированная голова интерактивного спавна: долгоживущий ``claude``, читающий и пишущий
#: stream-json через открытый stdin. Флаги возобновления (BOB-087.D1) приписываются ПОСЛЕ
#: неё, поэтому дефолтный (без resume) argv остаётся байт-в-байт прежним.
_INTERACTIVE_FLAGS = (
    "-p",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-mode",
)


def build_interactive_argv(
    claude_bin: str,
    *,
    mode: str,
    resume_session_id: str | None = None,
    continue_session: bool = False,
    extra_dirs: Sequence[str] = (),
) -> list[str]:
    """Собрать argv интерактивного ``claude`` — чистая детерминированная функция.

    Три стратегии возобновления в строгом приоритете (BOB-087.D1):

    * непустой ``resume_session_id`` → ``--resume <id>`` (поднять ИМЕННО ту сессию); он
      выигрывает у ``continue_session`` — конкретный id точнее, чем «последняя»;
    * иначе ``continue_session`` → ``--continue`` (поднять последнюю сессию этого места);
    * иначе — ФРЕШ-базлайн, байт-в-байт равный до-D1 инлайновому argv.

    ``extra_dirs`` (BOB-087.D2, owner-флаг ``coder.extra_dirs``) приписывает санитайзнутые
    пары ``--add-dir`` ПОСЛЕДНИМИ — после флага возобновления, — поэтому каждое ослабление
    остаётся чистым суффиксом, а порядок стабилен при любой стратегии.

    Дефолт (без resume, без continue, без доп-директорий) — путь OFF: не приписывается
    ничего, живое поведение BOB-083 не меняется, пока D3/флаги не включены.

    🔴 ``resume_session_id`` САНИТАЙЗИТСЯ тем же примитивом argv-значения, что и
    ``--add-dir`` (:func:`~bob.coding.sandbox_policy.is_safe_argv_value`, BOB-087.D5b):
    id приходит из колонки ``coding_session.claude_session_id``, т.е. из файла на диске,
    который правится и руками. Пустой / пробельный / с ведущим ``-`` / с NUL id считается
    «сессии нет» — проваливаемся в continue/фреш, а не падаем и уж точно не отдаём
    флагоподобную строку в argv-слот. Годный id идёт обрезанным (окружающие пробелы —
    транспортный мусор, не часть сессии).
    """
    argv = [claude_bin, *_INTERACTIVE_FLAGS, mode]
    resume_id = (resume_session_id or "").strip()
    if is_safe_argv_value(resume_id):
        argv += ["--resume", resume_id]
    elif continue_session:
        argv += ["--continue"]
    return argv + extra_dir_argv(extra_dirs)


def extract_session_id(event: Mapping[str, object]) -> str | None:
    """Вернуть claude-session-id из ``init``-события stream-json, иначе ``None``.

    Чистая и I/O-free (mutation-цель). ``claude --output-format stream-json`` первым
    отдаёт кадр ``{"type": "system", "subtype": "init", "session_id": "…", …}``; несомый
    им id — это то, что нужно позднему ``--resume``. Id отдаёт ТОЛЬКО настоящее
    init-событие с НЕПУСТЫМ строковым ``session_id``; любое другое событие, отсутствующее
    поле или не-строка дают ``None`` (транспорт id не выдумывает).
    """
    if event.get("type") != "system" or event.get("subtype") != "init":
        return None
    session_id = event.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return None
