# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""GitClone — рабочее место Боба как ОТДЕЛЬНЫЙ КЛОН, а не linked worktree (BOB-089, срез A).

Инфраструктурный адаптер под теми же портами, что и :class:`~bob.coding.adapters.
git_worktree.GitWorktree` (:class:`~bob.coding.ports.Worktree` — ``create`` /
``commit_and_push`` / ``remove``, и :class:`~bob.coding.ports.PersistentWorkspace` —
``ensure``), поэтому use-case'ы не знают, в чём они работают: подмена происходит в
композиции по флагу ``coder.isolated_clone`` (default OFF). Формы git фиксированные и
shell-free; сами решения («какими командами», «переиспользовать ли», «какой URL
допустим») живут в чистом ядре :mod:`bob.coding.clone_plan`.

🔴 ЗАЧЕМ (и почему это не вкусовщина). Linked worktree делит ``.git`` с основным
репозиторием: те же объекты, те же **refs**, те же remotes и те же credentials owner'а.
Проверено на настоящем git (волна bob-5ao): ``git update-ref refs/heads/main <sha>``
двигает main owner'а без сети, без кредов и мимо любого push-барьера. У клона свой
``.git``, поэтому этой дороги нет вовсе — и это свойство доказано на настоящем git
(``tests/infrastructure/coding/test_git_clone_real_git.py``), а не предположено: у
``git clone`` иные правила, чем у ``git worktree add``.

Что даёт клон, а что нет (честная рамка среза A):

* ДА — свой ``.git``, свой склад объектов (ни хардлинков, ни alternates), свои refs; в
  рабочем дереве только ТРЕКНУТЫЕ файлы, поэтому приватных данных Боба (``data/soul/``,
  ``bob.db*``, ``.env*``, ``config/bob.yaml``, ``.secrets/``) в нём нет;
* ДА — единственный remote указывает на форк Боба (а если форк не настроен, remote'а нет
  вовсе); рабочая копия owner'а адресом для push не остаётся, апстрим не прописан;
* НЕТ — изоляции КРЕДОВ: пока окружение спавна наследует credential helper owner'а,
  дотянуться до апстрима по сети всё ещё можно. Это срез C, и без него срез A — половина
  гарантии.

ЦЕНА (замерено на этом репозитории, ``.git`` 602 МБ / 5694 рыхлых объекта): клон через
``file://`` — 3.8 с и 142 МБ на место. Для долгоживущего места клон один, для
посессионного он живёт до конца прогона; альтернативы и почему отвергнуты — в докстроке
:mod:`bob.coding.clone_plan`.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from bob.coding.adapters._branch import is_safe_branch
from bob.coding.adapters._exec import (
    DEFAULT_TIMEOUT_S,
    CommandRunner,
    ExecRunner,
)
from bob.coding.adapters._integrate import commit_and_push_branch
from bob.coding.adapters._paths import is_strict_child
from bob.coding.clone_plan import (
    WorkspaceVerdict,
    checkout_argv,
    clone_argv,
    is_credential_free_url,
    origin_argv,
    workspace_verdict,
)

__all__ = ["CloneError", "GitClone"]


class CloneError(Exception):
    """Операция над клон-рабочим местом отклонена (небезопасная ветка / путь / URL)."""


class GitClone:
    """Завести / переиспользовать / убрать рабочее место-клон фиксированным git."""

    def __init__(
        self,
        clone_root: Path | str,
        *,
        source: Path | str,
        fork_url: str = "",
        runner: CommandRunner | None = None,
        git_bin: str = "git",
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        """Собрать адаптер; URL форка со встроенными кредами отвергается сразу.

        🔴 Отказ по кредам приходит на СБОРКЕ, а не на первом клоне: URL вида
        ``https://x-access-token:<токен>@host/...`` попал бы в argv, а argv виден в ``ps``
        любому процессу пользователя. Такую конфигурацию правильно ронять громко и до
        старта; секрет в текст ошибки не попадает (диагностика по факту, не по значению).
        """
        if not is_credential_free_url(fork_url):
            raise CloneError(
                "coder.fork_url carries embedded credentials (userinfo before the host); "
                "the fork must be addressed by a plain URL — credentials belong to the "
                "spawn environment, never to argv"
            )
        self._clone_root = Path(clone_root)
        self._source = Path(source).resolve()
        self._fork_url = fork_url
        self._runner: CommandRunner = runner or ExecRunner()
        self._git_bin = git_bin
        self._timeout = timeout

    async def create(self, branch: str) -> str:
        """Завести клон на НОВОЙ ветке ``branch`` и вернуть путь рабочего места.

        Паритет с ``GitWorktree.create``: ветка эфемерная, посессионная, создаётся на
        HEAD клона (то есть на том же базовом коммите, что дал бы ``worktree add -b``).
        """
        dest = self._destination(branch)
        await self._clone(dest, branch, reuse_accumulated=False)
        return str(dest)

    async def ensure(self, branch: str) -> str:
        """Вернуть путь ДОЛГОЖИВУЩЕГО клон-места на ``branch``, заведя его однажды.

        Идемпотентно, по вердикту чистого ядра
        (:func:`bob.coding.clone_plan.workspace_verdict`): существующий клон
        ПЕРЕИСПОЛЬЗУЕТСЯ как есть (работа в нём накапливается между сеансами и никогда не
        пересоздаётся), отсутствующий — заводится, а посторонний непустой каталог даёт
        громкий отказ (клонировать поверх git не даст, а удалять чужое молча нельзя).

        Если ветка уже известна источнику, клон стартует с ``origin/<branch>``, а не с
        HEAD: пересоздание такой ветки молча потеряло бы накопленную в ней работу
        (урок BOB-087.D5b).
        """
        dest = self._destination(branch)
        verdict = workspace_verdict(dest_exists=dest.exists(), is_repo=(dest / ".git").is_dir())
        if verdict is WorkspaceVerdict.REUSE:
            return str(dest)
        if verdict is WorkspaceVerdict.REFUSE:
            raise CloneError(
                f"workspace path {str(dest)!r} exists but is not a clone — refusing to "
                "clone over it or delete it"
            )
        await self._clone(dest, branch, reuse_accumulated=True)
        return str(dest)

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        """Застейджить, закоммитить и запушить изменения клона в его ветку.

        🔴 ``branch`` обязан быть безопасной ``bob/<slug>``-веткой — любая другая (в том
        числе ``main``) отклоняется ДО запуска git, поэтому пути, способного запушить
        ствол, физически нет. Сама последовательность — общий шаг интеграции
        (:func:`bob.coding.adapters._integrate.commit_and_push_branch`): ``True``, когда
        настоящий коммит уехал в ``origin`` (то есть в форк Боба), ``False``, когда
        коммитить было нечего.
        """
        if not is_safe_branch(branch):
            raise CloneError(f"refusing to push branch {branch!r}: not a safe bob/<slug> branch")
        return await commit_and_push_branch(
            self._runner,
            git_bin=self._git_bin,
            path=path,
            branch=branch,
            message=message,
            timeout=self._timeout,
        )

    async def remove(self, path: str) -> None:
        """Убрать клон по пути ``path`` (идемпотентно; посторонний путь отклоняется).

        У клона нет административной записи в основном репозитории, поэтому уборка — это
        удаление каталога, и предохранителей на ней два: путь обязан быть строгим
        потомком корня клонов, а сам каталог — быть клоном (внутри есть ``.git``). Уже
        исчезнувший путь — не ошибка: use-case зовёт уборку в ``finally``.
        """
        if not is_strict_child(path, self._clone_root):
            raise CloneError(f"clone path {path!r} is not under the configured clone root")
        target = Path(path)
        if not target.exists():
            return  # уже убрано — уборка в ``finally`` не должна падать
        if not (target / ".git").is_dir():
            raise CloneError(f"refusing to delete {path!r}: it is not a clone workspace")
        await asyncio.to_thread(shutil.rmtree, target)

    def _destination(self, branch: str) -> Path:
        """Путь рабочего места для ``branch`` (ветка валидируется ДО любого git)."""
        if not is_safe_branch(branch):
            raise CloneError(f"branch {branch!r} is not a safe bob/<slug> coding branch")
        return self._clone_root / branch.split("/", 1)[1]

    async def _clone(self, dest: Path, branch: str, *, reuse_accumulated: bool) -> None:
        """Клонировать источник в ``dest``, встать на ``branch`` и переадресовать remote."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        await self._run(clone_argv(self._git_bin, source=str(self._source), dest=str(dest)))
        on_origin = reuse_accumulated and await self._known_to_origin(dest, branch)
        await self._run(
            checkout_argv(self._git_bin, dest=str(dest), branch=branch, on_origin=on_origin)
        )
        await self._run(origin_argv(self._git_bin, dest=str(dest), fork_url=self._fork_url))

    async def _known_to_origin(self, dest: Path, branch: str) -> bool:
        """Есть ли у клона remote-ветка ``origin/<branch>`` (накопленная ранее работа).

        ``git branch --list --remotes`` выбран сознательно (как в ``GitWorktree``): он
        выходит с кодом 0 и при отсутствии ветки (пустой stdout), поэтому «ветки нет»
        никогда не приезжает как ``CommandError``, который пришлось бы глотать — а
        проглоченная ошибка ровно так и читается как «ветки нет».
        """
        listed = await self._run(
            [self._git_bin, "-C", str(dest), "branch", "--list", "--remotes", f"origin/{branch}"]
        )
        return bool(listed.strip())

    async def _run(self, argv: list[str]) -> str:
        return await self._runner(argv, timeout=self._timeout)
