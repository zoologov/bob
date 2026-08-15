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
  вовсе); рабочая копия owner'а адресом для push не остаётся.

🔴 ИСПРАВЛЕНО ПО ФАКТУ ×2 (bob-a6b.17; обе ошибки оставлены ВИДИМЫМИ, а не переписаны
задним числом — Issues #49). В списке выше стояли ещё два пункта, оба неверные:

* «апстрим не прописан» — ВОСЬМОЙ повтор формы, снятой ревьюером на настоящем git
  (bob-a6b.6, MAJOR-7/8): модель дописывает ``remote.origin.pushurl`` локальным конфигом
  поверх нашего argv, а ``url.<апстрим>.pushInsteadOf`` уводит ветку даже при push'е по
  значению. Верно узко: ПРИ ЗАВЕДЕНИИ клона (:func:`bob.coding.clone_plan.origin_argv`,
  где разбор полный). Дальше каталогом распоряжается модель, поэтому ветка уходит по
  ЗНАЧЕНИЮ ``fork_url``, а незнакомый ключ в локальном конфиге останавливает интеграцию
  (:func:`bob.coding.untrusted_repo.unsafe_local_config`);
* «НЕТ — изоляции КРЕДОВ … это срез C, и без него срез A — половина гарантии» — устарело
  наоборот: срез C приехал ПОД ТЕМ ЖЕ флагом ``coder.isolated_clone``
  (:func:`bob.runtime.wiring.coding._build_spawn_isolation`), окружение спавна больше не
  наследует credential helper owner'а, и ходить по ssh git из него тоже не может
  (bob-a6b.10). Флаг один потому, что клон и изоляция — две половины ОДНОЙ гарантии:
  клон закрывает ЛОКАЛЬНУЮ дорогу к стволу, изоляция — АМБИЕНТНУЮ сетевую. Что осталось
  на доверии (общий UID: ПРЯМОЙ ``ssh``, файловый путь до репозитория owner'а) — названо
  в :mod:`bob.coding.push_guard` и в беаде BOB-093, а не спрятано.

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
    fetch_argv,
    identity_argv,
    identity_pins,
    is_credential_free_url,
    origin_argv,
    tracker_argv,
    workspace_verdict,
)
from bob.coding.untrusted_repo import (
    LOCAL_CONFIG_QUERY,
    hardened_git_argv,
    unsafe_local_config,
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
        app_user_id: str = "",
        runner: CommandRunner | None = None,
        git_bin: str = "git",
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        """Собрать адаптер; URL форка со встроенными кредами отвергается сразу.

        🔴 Отказ по кредам приходит на СБОРКЕ, а не на первом клоне: URL вида
        ``https://x-access-token:<токен>@host/...`` попал бы в argv, а argv виден в ``ps``
        любому процессу пользователя. Такую конфигурацию правильно ронять громко и до
        старта; секрет в текст ошибки не попадает (диагностика по факту, не по значению).

        ``app_user_id`` (``coder.app_user_id``, BOB-089.D) — числовой id пользователя
        GitHub App, который становится префиксом ботовского noreply-адреса в подписи
        коммитов. Пусто/не число → подпись ставится без префикса; имя ``bob[ai]``
        проставляется всегда (см. :func:`bob.coding.clone_plan.identity_argv`). Это НЕ
        секрет: id публичен, в отличие от токена, и в argv ему быть можно.
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
        self._app_user_id = app_user_id
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

        Если ветка уже есть В ФОРКЕ, клон стартует с ``origin/<branch>``, а не с HEAD:
        пересоздание такой ветки молча потеряло бы накопленную в ней работу (урок
        BOB-087.D5b). 🔴 Спрашивается именно форк — там, где работа копится, а не
        репозиторий владельца (ревью bob-a6b.6, MAJOR-2).
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
        настоящий коммит уехал в форк Боба, ``False``, когда коммитить было нечего.

        🔴 Ветка уезжает по ЗНАЧЕНИЮ ``coder.fork_url``, а не по имени remote'а
        (bob-a6b.14): прописанный моделью локально ``remote.origin.pushurl`` увёл ветку в
        АПСТРИМ — проверено на настоящем git. Форк не настроен вовсе → remote при
        заведении клона удалён, пушить некуда, и это отказ по КОНФИГУРАЦИИ, а не загадочная
        ошибка git.

        🔴 Подпись коммита приколочена ПАРАМИ В ARGV
        (:func:`bob.coding.clone_plan.identity_pins`), а не взята из конфига клона (ревью
        bob-a6b.6, MAJOR-8): модель прописала там ``user.name``/``user.email``, и коммит в
        форке уехал подписанным ВЛАДЕЛЬЦЕМ — прямое попадание в US-2. Локальная запись
        остаётся вторым слоем (её видит человек, открывший клон), но решает argv.

        И перед первой же командой в каталоге спрашивается его локальный конфиг: ключ,
        которого наша последовательность заведения там не оставляла, останавливает
        интеграцию ГРОМКО (:func:`bob.coding.untrusted_repo.unsafe_local_config`) — так
        закрыто то, чего форма argv закрыть не может вовсе: ``filter.<d>.clean``
        исполняется на ``add`` при любых парах, а ``url.*.pushInsteadOf`` перезаписывает
        адрес уже после разбора argv.
        """
        if not is_safe_branch(branch):
            raise CloneError(f"refusing to push branch {branch!r}: not a safe bob/<slug> branch")
        if not self._fork_url:
            raise CloneError(
                "refusing to push: coder.fork_url is not configured, so the clone has no "
                "remote at all — there is nowhere for Bob's branch to go"
            )
        await self._refuse_a_tampered_clone(path)
        return await commit_and_push_branch(
            self._runner,
            git_bin=self._git_bin,
            path=path,
            branch=branch,
            message=message,
            timeout=self._timeout,
            push_target=self._fork_url,
            identity=identity_pins(self._app_user_id),
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
        """Клонировать в ``dest``, встать на ``branch``, переадресовать remote и обустроить.

        Предпоследний шаг — подпись работы (BOB-089.D): в клоне ``user.name = bob[ai]`` и
        ботовский noreply-адрес, 🔴 **локально** (``git -C <клон> config --local``).
        Глобальная настройка переподписала бы коммиты owner'а в его собственном
        репозитории — ровно та путаница идентичностей, от которой уходим; форма из
        :func:`~bob.coding.clone_plan.identity_argv` глобальной области выразить не может.

        Последний — провизионирование под ТРЕКЕР (BOB-088, срез 2,
        :func:`~bob.coding.clone_plan.tracker_argv`): без ``beads.role`` ``bd`` предупреждает
        на каждый вызов, а конвейер зовёт его десятками раз за волну. Сам доступ к базе даёт
        не эта запись, а ``BEADS_DIR`` в окружении спавна — названная дыра в изоляции,
        разобранная в :data:`bob.identity.spawn_isolation.PURGED_SPAWN_VARS`.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        await self._run(clone_argv(self._git_bin, source=str(self._source), dest=str(dest)))
        # 🔴 ПОРЯДОК: remote переадресуется на форк ДО вопроса о ветке (ревью bob-a6b.6,
        # MAJOR-2). Пока origin указывает на репозиторий ВЛАДЕЛЬЦА, вопрос «есть ли такая
        # ветка» задаётся не тому: работа Боба копится в ФОРКЕ, туда её отправляет
        # ``commit_and_push``.
        await self._run(origin_argv(self._git_bin, dest=str(dest), fork_url=self._fork_url))
        on_origin = reuse_accumulated and await self._known_to_the_fork(dest, branch)
        await self._run(
            checkout_argv(self._git_bin, dest=str(dest), branch=branch, on_origin=on_origin)
        )
        for argv in identity_argv(
            self._git_bin, dest=str(dest), app_user_id=self._app_user_id
        ):
            await self._run(argv)
        await self._run(tracker_argv(self._git_bin, dest=str(dest)))

    async def _known_to_the_fork(self, dest: Path, branch: str) -> bool:
        """Есть ли ветка ``branch`` В ФОРКЕ (то есть накопленная ранее работа Боба).

        🔴 Спрашивается именно ФОРК, а не репозиторий владельца (ревью bob-a6b.6,
        MAJOR-2): работа долгоживущего места копится там, куда её отправляет
        ``commit_and_push``. Вопрос владельцу давал молчаливую поломку восстановления —
        ветки у него нет, клон встаёт на HEAD ``main``, а первый ``push -u`` без ``force``
        падает non-fast-forward, и так каждый следующий раз.

        Порядок из двух шагов: ``fetch --prune`` приводит локальный взгляд на ``origin``
        (уже переадресованный на форк) к состоянию форка — иначе refs, привезённые из
        репозитория владельца, отвечали бы за форк. Форк не настроен вовсе (remote'а нет)
        → накопленной работе негде быть, и сети не касаемся.

        ``git branch --list --remotes`` выбран сознательно (как в ``GitWorktree``): он
        выходит с кодом 0 и при отсутствии ветки (пустой stdout), поэтому «ветки нет»
        никогда не приезжает как ``CommandError``, который пришлось бы глотать — а
        проглоченная ошибка ровно так и читается как «ветки нет». Недоступный форк,
        наоборот, отказывает ГРОМКО (на ``fetch``), и это правильный обмен: молчаливое
        «начнём с нуля» стоит дороже.
        """
        if not self._fork_url:
            return False
        await self._run(fetch_argv(self._git_bin, dest=str(dest)))
        listed = await self._run(
            [
                *hardened_git_argv(self._git_bin, path=str(dest)),
                "branch",
                "--list",
                "--remotes",
                f"origin/{branch}",
            ]
        )
        return bool(listed.strip())

    async def _refuse_a_tampered_clone(self, path: str) -> None:
        """Отказать, если в локальном конфиге клона есть ключ, которого мы там не заводили.

        🔴 ЧЕСТНО О СИЛЕ МЕРЫ. Она закрывает ровно то, чего форма argv не закрывает:
        ``filter.<d>.clean`` исполнился на ``add -A`` при полном наборе пар, а
        ``url.<апстрим>.pushInsteadOf`` увёз ветку в апстрим даже при push'е по значению
        (оба факта воспроизведены на git 2.49). Но это проверка НА МОМЕНТ, а не пара в
        argv: живой сеанс ``claude`` вправе дописать ключ между опросом и ``add``. И она
        применима только к КЛОНУ, где конфиг завели мы сами; у linked worktree локальный
        конфиг — конфиг ВЛАДЕЛЬЦА, где законно живёт хоть ``merge.<d>.driver``, и отличить
        его правку от правки модели нечем. Полностью класс закрывает раздельный UID
        (BOB-093) — см. докстроку :mod:`bob.coding.untrusted_repo`.

        В сообщение уезжают только ИМЕНА ключей: значение вправе оказаться секретом.
        """
        listing = await self._run(
            [*hardened_git_argv(self._git_bin, path=path), *LOCAL_CONFIG_QUERY]
        )
        offending = unsafe_local_config(listing)
        if offending:
            raise CloneError(
                "refusing to integrate: the clone's local config carries keys Bob's setup "
                f"never writes ({', '.join(offending)}) — a repository that names commands "
                "or a second push address is not a workspace we run git in"
            )

    async def _run(self, argv: list[str]) -> str:
        return await self._runner(argv, timeout=self._timeout)
