# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""ForkCompareLink — работа доведена до форка, PR создаёт owner по ссылке (BOB-089, срез D).

Адаптер под тем же портом :class:`~bob.coding.ports.PullRequestOpener`, что и
:class:`~bob.coding.adapters.gh_pr.GhPullRequestOpener`, но принципиально другой по
содержанию: он НИЧЕГО не выполняет. Ни ``gh``, ни сети, ни процесса — здесь нет даже
командного шва (:mod:`bob.coding.adapters._exec` не импортируется, и это инвариант,
проверяемый тестом). Его результат — предзаполненная форма сравнения, собранная чистым
ядром :func:`bob.coding.pr_link.compare_url`.

🔴 ПОЧЕМУ ТАК, А НЕ «ОТКРЫТЬ PR» (не-цель PRD, обход не ищем). Когда рабочее место Боба —
клон с единственным remote'ом на его ПРИВАТНЫЙ форк (``coder.isolated_clone``), открыть
cross-repo PR он не может: installation-токен скоупится на одну установку, а создание PR
требует читаемости обеих сторон одним токеном. Проверены три способа (токен апстрима,
``head_repo``, токен организации) — все отказывают. Решение owner'а — вариант A: Боб
доводит работу до ветки в форке и отдаёт ссылку, owner жмёт «Create pull request». Потеря
автономности ровно в один клик и ровно перед шагом, где owner всё равно читает диф.

Голос идёт ЗА фактом: терминальную реплику на этом пути даёт
:func:`bob.coding.session_voice.ready_for_pr`, которая не приписывает Бобу открытие PR.
Инвариант «Боб никогда не мержит» этот путь не ослабляет, а усиливает: у него нет даже
поверхности, чтобы что-то сделать в чужом репозитории.
"""

from __future__ import annotations

from bob.coding.adapters._branch import is_safe_branch
from bob.coding.adapters.gh_pr import PullRequestError
from bob.coding.pr_link import compare_url

__all__ = ["ForkCompareLink"]


class ForkCompareLink:
    """Собрать ссылку на создание PR из ветки форка в ствол апстрима (ничего не открывая)."""

    def __init__(self, *, upstream: str, fork: str, base: str = "main") -> None:
        """Запомнить координаты; половина координат отвергается на СБОРКЕ.

        ``upstream`` / ``fork`` — слаги ``owner/repo`` (апстрим owner'а и форк Боба; слаг
        форка добывается из того же ``coder.fork_url``, куда уходит push, чтобы ссылка не
        разошлась с местом, где реально лежит работа). Пустая половина дала бы ссылку в
        никуда, а owner доверяет присланному адресу — поэтому отказ громкий и до старта
        сессии (тот же принцип, что у :class:`~bob.coding.adapters.git_clone.GitClone` с
        кредами в URL). Композиция такой пары просто не собирает.
        """
        if not upstream or not fork:
            raise PullRequestError(
                "a fork compare link needs BOTH the upstream and the fork slug "
                "(owner/repo); refusing to hand the owner a link that goes nowhere"
            )
        self._upstream = upstream
        self._fork = fork
        self._base = base

    async def open(
        self,
        branch: str,
        title: str,  # noqa: ARG002 — форму заполняет owner: Боб не оформляет PR за него
        body: str,  # noqa: ARG002 — то же; текст PR остаётся решением owner'а
    ) -> str:
        """Вернуть предзаполненную форму создания PR для ``branch`` (PR НЕ открывается).

        Подпись — портовая (``branch`` / ``title`` / ``body``), поэтому use-case не
        различает этот путь и открытие PR через ``gh``; заголовок и тело здесь СОЗНАТЕЛЬНО
        не используются: форму заполняет owner, и подсовывать ему готовый текст от лица
        Боба значило бы оформлять PR за него.

        ``branch`` обязан быть безопасной ``bob/<slug>``-веткой — ссылка на ствол не
        собирается вовсе (тот же предохранитель, что у gh-адаптера).
        """
        if not is_safe_branch(branch):
            raise PullRequestError(
                f"branch {branch!r} is not a safe bob/<slug> coding branch"
            )
        return compare_url(
            upstream=self._upstream, fork=self._fork, branch=branch, base=self._base
        )
