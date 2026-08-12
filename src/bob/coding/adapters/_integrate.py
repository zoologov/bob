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

* ``add -A`` — застейджить всё;
* ``status --porcelain`` — пусто значит claude не сделал НИЧЕГО: честный ``False`` без
  коммита (пустых коммитов не бывает);
* ``commit --no-verify -m <message>`` и
  ``push --no-verify <push_target> refs/heads/<branch>:refs/heads/<branch>``.

🔴 КАЖДАЯ КОМАНДА ИДЁТ ЗАКАЛЁННОЙ ФОРМОЙ (:func:`bob.coding.untrusted_repo.
hardened_git_argv`), и это содержание bob-a6b.14. Шаг выполняется в процессе САМОГО Боба —
намеренно вне изоляции спавна, то есть с кредами и ssh-ключом владельца — но в каталоге,
которым распоряжается модель. Ревьюер воспроизвёл на настоящем git, что из этого следовало:
подложенные ею ``.git/hooks/{pre-commit,post-commit,pre-push}`` ИСПОЛНИЛИСЬ в нашем
процессе. Пары в argv это закрывают; ``--no-verify`` — второй слой, и он НЕ равен первому
(с одним ``--no-verify`` ``post-commit`` всё равно исполняется — проверено).

🔴 ``push_target`` — АДРЕС, а не имя remote'а, когда адрес известен: локальный
``remote.origin.pushurl``, прописанный моделью, увёл ветку в АПСТРИМ, и имя remote'а
перестало что-либо значить. Клон пушит по ЗНАЧЕНИЮ ``coder.fork_url`` (по построению без
кредов — argv виден в ``ps``). Для linked worktree адреса нет: там remote — собственный
``origin`` ВЛАДЕЛЬЦА, и передаётся имя; но там же и весь ``.git`` общий с его репозиторием,
то есть по-настоящему этот класс закрывает переход на клон (флаг ``coder.isolated_clone``),
а не форма push'а.

🔴 ПОДПИСЬ ПРИКОЛОЧЕНА В ARGV, а не взята из конфига (``identity``; ревью bob-a6b.6,
MAJOR-8 — воспроизведено через настоящий ``GitClone.commit_and_push``): модель прописала в
клоне ``git config --local user.name <владелец>``, и коммит в форке уехал подписанным
ВЛАДЕЛЬЦЕМ — прямое попадание в US-2. Клон передаёт
:func:`bob.coding.clone_plan.identity_pins`; linked worktree передаёт ПУСТОЙ набор
сознательно: там репозиторий принадлежит владельцу и его подпись в нём законна.

🔴 ЧЕСТНО ОБ OFF-ПУТИ — ЗДЕСЬ ОНО И ВВОДИТСЯ (ревью bob-a6b.6, MAJOR-9). Шаг общий для
обоих адаптеров, поэтому закалка работает и при ``coder.isolated_clone=false``, и
обещание PRD «при OFF поведение байт-в-байт прежнее» с этой волны НЕВЕРНО в двух
местах — оба отклонения названы, чтобы их не искали:

* ХУКИ РЕПОЗИТОРИЯ НА КОММИТАХ БОБА НЕ ИСПОЛНЯЮТСЯ. В этом репозитории это значит, что
  ``beadloom install-hooks`` (pre-commit: lint + sync-check + ACTIVE/tracker coherence;
  pre-push: полный ``beadloom ci``) на них не срабатывает — прежняя форма argv исполняла
  все три. Обмен ОСОЗНАННЫЙ (решение координатора): в ОБЩЕМ ``.git/hooks`` linked
  worktree хук владельца от хука модели не отличить, поэтому worktree-режим без закалки
  был бы настоящей дырой. 🔴 Потерянный быстрый гейт НЕ заменяется, а исчезает:
  остаётся перепроверка координатором (реальна, каждую волну). ``beadloom ci`` на PR
  НЕ существует — в ``.github/workflows`` только ``deploy-site.yml``, а pre-push из
  основного репозитория предмет не покрывает, потому что ветку Боба пушит процесс Боба,
  и хуков он не исполняет (прежняя редакция этой строки обещала больше, чем есть);
* UPSTREAM У ВЕТКИ БОЛЬШЕ НЕ ПОЯВЛЯЕТСЯ: ``push -u origin <branch>`` заменён явным
  полностью квалифицированным refspec'ом (это же и закрывает подмену тегом/одноимённым
  ref'ом). Оба факта закреплены тестами на настоящем git —
  ``tests/infrastructure/coding/test_off_path_real_git.py`` и
  ``…/test_untrusted_repo_real_git.py``.

🔴 ``branch`` обязан быть УЖЕ провалидированным (:func:`bob.coding.adapters._branch.
is_safe_branch`) — вызывающий адаптер отказывает своей ошибкой ДО обращения сюда, так что
пути, способного запушить ``main``, физически нет. Refspec фиксирован и полностью
квалифицирован (``refs/heads/<branch>`` в оба конца), поэтому ни тег, ни одноимённый ref
не подменяют, что именно уезжает. Вынесено в общий модуль намеренно: это самая опасная
последовательность в обоих адаптерах, и второй её копии быть не должно.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.coding.untrusted_repo import hardened_git_argv

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
    push_target: str,
    identity: tuple[tuple[str, str], ...],
) -> bool:
    """Закоммитить и запушить изменения рабочего места в ``branch``; ``False`` — нечего.

    ``push_target`` — куда именно уезжает ветка: URL форка (клон) или имя remote'а
    (linked worktree). ``identity`` — подпись, приколоченная парами в argv
    (:func:`bob.coding.clone_plan.identity_pins` для клона, пустой набор для linked
    worktree); параметр обязательный намеренно, чтобы каждый адаптер НАЗЫВАЛ свой выбор, а
    не забывал подпись молча. Возвращает ``True``, когда настоящий коммит уехал, и
    ``False``, когда коммитить было нечего. Настоящий сбой git приходит наружу как
    ``CommandError`` раннера.
    """
    git = hardened_git_argv(git_bin, path=path, identity=identity)
    await runner([*git, "add", "-A"], timeout=timeout)
    status = await runner([*git, "status", "--porcelain"], timeout=timeout)
    if not status.strip():
        return False  # claude не внёс изменений — честный отказ, без пустого коммита
    await runner([*git, "commit", "--no-verify", "-m", message], timeout=timeout)
    ref = f"refs/heads/{branch}"
    await runner([*git, "push", "--no-verify", push_target, f"{ref}:{ref}"], timeout=timeout)
    return True
