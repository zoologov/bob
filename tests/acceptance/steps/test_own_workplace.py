# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions для сценариев «Боб работает у себя» (BOB-089).

Связывает ``own_workplace.feature`` с :mod:`tests.acceptance.own_workplace_harness`:
рабочее место заводит ПРОДАКШН-адаптер над НАСТОЯЩИМ git в одноразовом репозитории,
креды спрашиваются у настоящего git тем же механизмом, которым пользуется ``push``, а
развилку «открываю PR сам / отдаю ссылку» выбирает НАСТОЯЩАЯ композиция. Сценарии
утверждают наблюдаемое: sha ствола владельца, содержимое рабочего дерева, подпись в
``git log``, ответ ``git credential`` и реплики, которые владелец увидит в Telegram.

🔴 Почему не фейк (§0.3 п.4): всё содержание US-1/US-2 — это ПОВЕДЕНИЕ git, у которого
``clone`` и ``worktree add`` устроены по-разному; фейк доказал бы контракт фейка. Файл
пропускается с явной причиной, если ``git`` на хосте нет.

Сценарии синхронные (pytest-bdd), поэтому асинхронные вызовы адаптера идут через
``asyncio.run`` внутри харнесса.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.coding.adapters.git_worktree import GitWorktree
from bob.runtime.wiring.coding import _build_spawn_isolation, _build_workspace
from tests.acceptance.own_workplace_harness import (
    GH_PULL_URL,
    OWNER_SECRET,
    Handover,
    Integration,
    OwnerWorld,
    author_of_last_commit,
    author_of_the_fork_branch,
    bobs_branches_in_the_fork,
    commit_here,
    credentials_offered_here,
    files_here,
    hand_over_the_work,
    integrate_the_work,
    move_ref_here,
    owner_world,
    plant_in_the_workplace_config,
    raise_workplace,
    remotes_here,
    sha_of,
)

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

scenarios("../features/own_workplace.feature")

#: Опубликованные (трекнутые) файлы одноразового репозитория — ровно они и составляют
#: рабочее место Боба.
_PUBLISHED_FILES = frozenset({".gitignore", "README.md", "src/app.py"})


@dataclass(slots=True)
class _WorkplaceContext:
    """Черновик, который делят шаги сценария: мир владельца, рабочее место, итоги."""

    tmp_path: Path
    world: OwnerWorld | None = None
    workplace: Path | None = None
    trunk_before: str = ""
    unisolated: subprocess.CompletedProcess[str] | None = None
    isolated: subprocess.CompletedProcess[str] | None = None
    handover: Handover = field(default_factory=Handover)
    integration: Integration = field(default_factory=Integration)

    @property
    def owner_repo(self) -> Path:
        assert self.world is not None, "мир владельца не поднят"
        return self.world.work

    @property
    def place(self) -> Path:
        assert self.workplace is not None, "рабочее место не заведено"
        return self.workplace


@pytest.fixture
def workplace_context(tmp_path: Path) -> _WorkplaceContext:
    """Одноразовое хозяйство на сценарий (свой репозиторий, свой форк, свои каталоги)."""
    return _WorkplaceContext(tmp_path=tmp_path)


# --- Дано: настоящий репозиторий владельца + приватный форк Боба -----------------


@given("репозиторий владельца с приватными файлами и приватный форк Боба")
def an_owner_repository_and_bobs_fork(workplace_context: _WorkplaceContext) -> None:
    workplace_context.world = owner_world(workplace_context.tmp_path)
    workplace_context.trunk_before = sha_of(workplace_context.owner_repo, "main")
    # Контроль: приватные файлы РЕАЛЬНО лежат у владельца — иначе сценарий S2 доказывал бы
    # лишь то, что их там не было.
    assert (workplace_context.owner_repo / ".env").exists()
    assert (workplace_context.owner_repo / ".secrets/bob-ai-work.pem").exists()


# --- Когда: Боб заводит рабочее место / работа доезжает --------------------------


@when("Боб заводит рабочее место под задачу")
def bob_raises_his_workplace(workplace_context: _WorkplaceContext) -> None:
    assert workplace_context.world is not None
    workplace_context.workplace = raise_workplace(
        workplace_context.world, workplace_context.tmp_path / "clones"
    )


@when("внутри рабочего места ветку main переводят на новый коммит")
def main_is_moved_inside_the_workplace(workplace_context: _WorkplaceContext) -> None:
    # 🔴 Ровно эта команда в linked worktree двигала main владельца: ни сети, ни кредов,
    # мимо любого push-барьера. Модель внутри рабочего места вольна её выполнить.
    head = commit_here(workplace_context.place, filename="feature.py", message="claude work")
    assert move_ref_here(workplace_context.place, "refs/heads/main", head) == 0
    assert sha_of(workplace_context.place, "main") == head  # свой main сдвинулся


@when("в рабочем месте появляется коммит")
def a_commit_appears_in_the_workplace(workplace_context: _WorkplaceContext) -> None:
    commit_here(workplace_context.place, filename="feature.py", message="claude work")


@when("владелец делает коммит у себя в репозитории")
def the_owner_commits_in_his_own_repository(workplace_context: _WorkplaceContext) -> None:
    commit_here(workplace_context.owner_repo, filename="owner-note.md", message="owner work")


@when("работа Боба доведена до ветки в его форке")
def the_work_reached_a_branch_in_bobs_fork(workplace_context: _WorkplaceContext) -> None:
    workplace_context.handover = hand_over_the_work(
        coder={"isolated_clone": True, "fork_url": "git@github.com:bobiverse-dev/bob.git"},
        github={"propose_repo": "zoologov/bob", "work_repo": "bobiverse-dev/bob"},
    )


@when("модель переписывает подпись в конфиге рабочего места на подпись владельца")
def the_model_re_signs_the_workplace(workplace_context: _WorkplaceContext) -> None:
    plant_in_the_workplace_config(workplace_context.place, "user.name", "Vladimir Zoologov")
    plant_in_the_workplace_config(workplace_context.place, "user.email", "owner@example.com")


@when("модель наводит рабочее дерево места на репозиторий владельца")
def the_model_points_the_working_tree_at_the_owner(
    workplace_context: _WorkplaceContext,
) -> None:
    # Черновик владельца — то, что уехало бы в форк: незакоммиченный файл в его дереве.
    (workplace_context.owner_repo / "черновик.md").write_text(
        "незакоммиченный черновик владельца\n", encoding="utf-8"
    )
    plant_in_the_workplace_config(
        workplace_context.place, "core.worktree", str(workplace_context.owner_repo)
    )


@when("Боб доводит работу до ветки в форке")
def bob_integrates_the_work(workplace_context: _WorkplaceContext) -> None:
    assert workplace_context.world is not None
    (workplace_context.place / "feature.py").write_text("print('работа')\n", encoding="utf-8")
    workplace_context.integration = integrate_the_work(
        workplace_context.world, workplace_context.tmp_path / "clones"
    )


@when("флаг отдельного рабочего места выключен")
def the_isolated_workplace_flag_is_off(workplace_context: _WorkplaceContext) -> None:
    # OFF-путь берётся из НАСТОЯЩЕЙ композиции с пустым конфигом — то есть ровно тем, что
    # получает владелец, не настроивший ничего.
    workplace_context.handover = hand_over_the_work(coder={}, github={})


# --- Тогда: наблюдаемое поведение -----------------------------------------------


@then("main владельца остаётся на прежнем коммите")
def the_owners_trunk_did_not_move(workplace_context: _WorkplaceContext) -> None:
    assert sha_of(workplace_context.owner_repo, "main") == workplace_context.trunk_before, (
        "ствол владельца сдвинулся из рабочего места Боба"
    )


@then("у рабочего места нет ни одного настроенного remote'а, ведущего в репозиторий владельца")
def no_configured_remote_leads_back_to_the_owner(workplace_context: _WorkplaceContext) -> None:
    # 🔴 Утверждается РОВНО то, что проверяется: настроенных remote'ов на репозиторий
    # владельца нет (`git remote -v`). Прежняя формулировка обещала «ни одного АДРЕСА» —
    # и была неверна: путь к репозиторию владельца остаётся в reflog клона, а под общим UID
    # намеренная дорога до ствола существует (доказано в том же дереве,
    # `test_git_clone_real_git.py`). Живой .feature — документ для владельца; обещать в нём
    # отозванную гарантию нельзя (ревью bob-a6b.6, MAJOR-3).
    remotes = remotes_here(workplace_context.place)
    assert str(workplace_context.owner_repo) not in remotes, (
        f"обратная дорога к репозиторию владельца осталась: {remotes!r}"
    )


@then("в рабочем месте лежат только опубликованные файлы репозитория")
def only_published_files_reached_the_workplace(workplace_context: _WorkplaceContext) -> None:
    # Перечисление, а не проверка известных путей: приватный файл, о котором сценарий не
    # догадался спросить, всё равно попадёт в это множество.
    assert files_here(workplace_context.place) == set(_PUBLISHED_FILES)


@then("этот коммит подписан «bob[ai]» с ботовским адресом")
def the_commit_is_signed_by_bob(workplace_context: _WorkplaceContext) -> None:
    name, email = author_of_last_commit(workplace_context.place)
    assert name == "bob[ai]", f"работа Боба подписана не его именем: {name!r}"
    assert email == "424242+bob-ai-work[bot]@users.noreply.github.com"


@then("коммит в форке подписан «bob[ai]» с ботовским адресом")
def the_fork_commit_is_signed_by_bob(workplace_context: _WorkplaceContext) -> None:
    # 🔴 Читается ФОРК, а не рабочее место: подпись, которую увидит владелец, — та, что
    # уехала. Подложенный моделью ``user.name`` её больше не решает (bob-a6b.16, MAJOR-8).
    assert workplace_context.world is not None
    assert workplace_context.integration.committed is True
    assert author_of_the_fork_branch(workplace_context.world, "bob/task") == (
        "bob[ai] <424242+bob-ai-work[bot]@users.noreply.github.com>"
    )


@then("интеграция отказывает, называя виновный ключ")
def the_integration_refuses_naming_the_key(workplace_context: _WorkplaceContext) -> None:
    refusal = workplace_context.integration.refusal
    assert "core.worktree" in refusal, f"отказ не назвал виновный ключ: {refusal!r}"
    assert workplace_context.integration.committed is False


@then("в форке нет ни одной ветки Боба, а черновик владельца остался у него")
def nothing_of_the_owners_work_left_for_the_fork(workplace_context: _WorkplaceContext) -> None:
    assert workplace_context.world is not None
    # Перечисление ВСЕХ ветвей форка, а не проверка известного имени.
    assert bobs_branches_in_the_fork(workplace_context.world) == []
    assert (workplace_context.owner_repo / "черновик.md").exists()


@then("коммит владельца по-прежнему подписан владельцем")
def the_owners_commit_is_still_his(workplace_context: _WorkplaceContext) -> None:
    # 🔴 Глобальная настройка подписи переподписала бы коммиты владельца как «bob[ai]» —
    # ровно та путаница идентичностей, от которой уходим. Утверждается ПОВЕДЕНИЕ (что
    # владелец увидит в `git log`), а не содержимое конфигурации.
    assert author_of_last_commit(workplace_context.owner_repo) == (
        "Owner",
        "owner@example.com",
    )


@then("без изоляции git отдаёт из этого места пароль владельца")
def unisolated_git_hands_over_the_owners_password(
    workplace_context: _WorkplaceContext,
) -> None:
    # Контроль дороги: без него зелёный сценарий доказывал бы лишь, что кредов не было и так.
    workplace_context.unisolated = credentials_offered_here(
        workplace_context.place, workplace_context.tmp_path, isolated=False
    )
    assert f"password={OWNER_SECRET}" in workplace_context.unisolated.stdout


@then(
    "в изолированном окружении не выдаётся ни одного пароля, и отказ приходит по отсутствию кредов"
)
def the_isolated_spawn_gets_no_password(workplace_context: _WorkplaceContext) -> None:
    result = credentials_offered_here(
        workplace_context.place, workplace_context.tmp_path, isolated=True
    )
    workplace_context.isolated = result
    assert result.returncode != 0
    assert OWNER_SECRET not in result.stdout
    assert "password=" not in result.stdout, f"креды всё-таки выданы: {result.stdout!r}"
    # 🔴 Отказ именно по ОТСУТСТВИЮ кредов, а не по зависшему запросу пароля.
    assert "terminal prompts disabled" in result.stderr


@then("владелец получает ссылку на создание PR из ветки форка в его репозиторий")
def the_owner_gets_a_compare_link(workplace_context: _WorkplaceContext) -> None:
    handover = workplace_context.handover
    assert handover.url.startswith("https://github.com/zoologov/bob/compare/main..."), (
        f"ссылка ведёт не в форму создания PR апстрима: {handover.url!r}"
    )
    # Голова формы — «владелец-форка:репозиторий:ветка»: только она адресует ветку в ЧУЖОМ
    # репозитории. Короткая форма указала бы на репозиторий владельца, где ветки Боба нет.
    assert "bobiverse-dev:bob:bob/" in handover.url
    assert handover.url.endswith("?expand=1")  # форма раскрыта: виден диф и кнопка
    assert handover.url in handover.transcript, "адрес до владельца не доехал"


@then("Боб не приписывает себе открытие PR")
def bob_claims_no_opened_pr(workplace_context: _WorkplaceContext) -> None:
    said = workplace_context.handover.transcript
    assert "открыл PR" not in said, f"Боб заявил открытый PR, которого не открывал: {said!r}"
    assert "PR открыт" not in said
    assert "Вот PR" not in said


@then("Боб честно называет причину — на запись прав у него нет")
def bob_names_the_reason(workplace_context: _WorkplaceContext) -> None:
    said = workplace_context.handover.transcript.casefold()
    assert "форк" in said, "Боб не сказал, где лежит работа"
    assert "только чтение" in said, "Боб не назвал причину, по которой PR не открыт"


@then("рабочее место — прежний linked worktree в прежнем каталоге")
def the_workplace_is_the_previous_worktree() -> None:
    # РАВЕНСТВО сборки, а не «похожесть»: тип адаптера и его аргумент. Уйди флаг в OFF-путь
    # хоть одним аргументом — этот шаг покраснел бы.
    workspace = _build_workspace({})
    assert type(workspace) is GitWorktree
    assert workspace._worktree_root == GitWorktree(".worktrees")._worktree_root


@then("окружение спавна не подменяется вовсе")
def the_spawn_environment_is_untouched() -> None:
    assert _build_spawn_isolation({}) is None


@then("владельцу говорится прежняя реплика об открытом PR")
def the_owner_hears_the_previous_pr_line(workplace_context: _WorkplaceContext) -> None:
    said = workplace_context.handover.transcript
    assert workplace_context.handover.integration == "GhPullRequestOpener"
    assert "Вот PR" in said
    assert GH_PULL_URL in said
    assert "Create pull request" not in said  # ссылочной формы на этом пути нет
