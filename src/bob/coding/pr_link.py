# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Ссылка «ветка в форке Боба → форма создания PR» — чистое ядро (BOB-089, срез D).

ОДНА ответственность: собрать адрес, по которому owner создаёт PR одним нажатием, из того
же самого форка, куда Боб запушил ветку. Ни сети, ни процессов — только строки:

* :func:`repo_slug` — ``owner/repo`` форка из его git-адреса (тот же ``coder.fork_url``,
  куда уходит push: собери слаг из другого источника — и ссылка однажды укажет не туда,
  где лежит работа);
* :func:`compare_url` — предзаполненная форма сравнения апстрима с веткой форка.

🔴 ПОЧЕМУ ССЫЛКА, А НЕ ОТКРЫТЫЙ PR (не-цель PRD, обход не ищем). Cross-repo PR из
ПРИВАТНОГО форка Бобу недоступен: installation-токен скоупится на одну установку, а
создание PR требует читаемости обеих сторон ОДНИМ токеном. Проверены три способа (токен
апстрима, ``head_repo``, токен организации) — все отказывают. Решение owner'а (вариант A):
Боб доводит работу до ветки в своём форке и отдаёт ссылку, а «Create pull request» жмёт
owner — потеря автономности ровно в один клик, и ровно перед шагом, где owner всё равно
читает диф. Реплика к этой ссылке живёт в :func:`bob.coding.session_voice.ready_for_pr` и
НЕ притворяется, что PR открыт.

Форма головы — ``<fork-owner>:<fork-repo>:<branch>``: только она адресует ветку в ЧУЖОМ
репозитории. Короткая ``<owner>:<branch>`` указала бы на репозиторий самого owner'а, где
ветки Боба нет вовсе.
"""

from __future__ import annotations

import re
from urllib.parse import quote

__all__ = ["compare_url", "repo_slug"]

#: Единственный хост, для которого эта форма сравнения вообще существует. Чужой remote
#: (или локальный ``file://`` из тестов) слага не даёт: нерабочая ссылка хуже её отсутствия.
_GITHUB_HOST = "github.com"
#: ``owner/repo`` из git-адреса любой из трёх форм: ``git@host:owner/repo(.git)``,
#: ``https://host/owner/repo(.git)``, ``ssh://git@host/owner/repo(.git)``. Ни глубже, ни
#: короче: слаг собирается из точного совпадения, а не из догадки о форме пути.
_FORK_URL = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9+.\-]*://(?:[^/@]*@)?|[^/@]*@)"
    rf"(?P<host>{re.escape(_GITHUB_HOST)})[:/]"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


def repo_slug(url: str) -> str:
    """Вернуть ``owner/repo`` форка по его git-адресу (``""``, если адрес не той формы).

    Пустая строка означает «ссылку собрать не из чего» — форк не настроен, remote не на
    GitHub или путь неожиданной формы. Это НЕ ошибка: композиция в таком случае просто
    не заводит ссылочный путь (см. :mod:`bob.coding.adapters.fork_link`).
    """
    match = _FORK_URL.match(url)
    if match is None:
        return ""
    return f"{match.group('owner')}/{match.group('repo')}"


def compare_url(*, upstream: str, fork: str, branch: str, base: str) -> str:
    """Собрать предзаполненную форму создания PR из ``branch`` форка в ``base`` апстрима.

    ``upstream`` и ``fork`` — слаги ``owner/repo`` (апстрим owner'а и форк Боба), ``base``
    — ствол, куда PR будет нацелен. ``expand=1`` раскрывает форму сразу, поэтому owner
    видит диф и кнопку «Create pull request», а не промежуточный экран.

    Ветка экранируется, но слэш ``bob/<slug>`` остаётся как есть: он легален в пути и
    делает ссылку читаемой глазами (owner видит, ЧТО именно он собирается влить).
    """
    head = f"{fork.replace('/', ':')}:{quote(branch, safe='/')}"
    return f"https://{_GITHUB_HOST}/{upstream}/compare/{base}...{head}?expand=1"
