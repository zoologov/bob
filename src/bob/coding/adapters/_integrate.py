# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""Детерминированный шаг интеграции: застейджить, закоммитить и запушить ветку Боба.

Одна ответственность, общая для обоих адаптеров рабочего места (linked worktree и
отдельный клон, BOB-089 срез A): после того как ``claude`` применил одобренный план, он
НЕ коммитит (``acceptEdits`` авто-принимает правки файлов, но не git), поэтому Боб
коммитит и пушит ветку сам — из СВОЕГО процесса, фиксированной shell-free формой:

* ``git -C <path> add -A`` — застейджить всё;
* ``git -C <path> status --porcelain`` — пусто значит claude не сделал НИЧЕГО: честный
  ``False`` без коммита (пустых коммитов не бывает);
* ``git -C <path> commit -m <message>`` и ``git -C <path> push -u origin <branch>``.

🔴 ``branch`` обязан быть УЖЕ провалидированным (:func:`bob.coding.adapters._branch.
is_safe_branch`) — вызывающий адаптер отказывает своей ошибкой ДО обращения сюда, так что
пути, способного запушить ``main``, физически нет. Вынесено в общий модуль намеренно: это
самая опасная последовательность в обоих адаптерах, и второй её копии быть не должно.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.coding.adapters._exec import CommandRunner

__all__ = ["commit_and_push_branch"]


async def commit_and_push_branch(
    runner: CommandRunner,
    *,
    git_bin: str,
    path: str,
    branch: str,
    message: str,
    timeout: float,
) -> bool:
    """Закоммитить и запушить изменения рабочего места в ``branch``; ``False`` — нечего.

    Возвращает ``True``, когда настоящий коммит уехал в ``origin``, и ``False``, когда
    коммитить было нечего. Настоящий сбой git приходит наружу как ``CommandError``
    раннера.
    """
    await runner([git_bin, "-C", path, "add", "-A"], timeout=timeout)
    status = await runner([git_bin, "-C", path, "status", "--porcelain"], timeout=timeout)
    if not status.strip():
        return False  # claude не внёс изменений — честный отказ, без пустого коммита
    await runner([git_bin, "-C", path, "commit", "-m", message], timeout=timeout)
    await runner([git_bin, "-C", path, "push", "-u", "origin", branch], timeout=timeout)
    return True
