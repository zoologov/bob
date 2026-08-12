# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary harness для сценариев BOB-089 «своё рабочее место, своя подпись, ссылка».

Сценарии ``own_workplace.feature`` утверждают НАБЛЮДАЕМОЕ поведение через настоящие
границы — никогда внутреннее состояние:

* 🔴 граница **настоящего git** (:func:`owner_world`, :func:`raise_workplace`,
  :func:`commit_here`, :func:`author_of_last_commit`, :func:`sha_of`,
  :func:`move_ref_here`): всё содержание US-1/US-2 — это поведение git, а фейк доказал бы
  контракт фейка (§0.3 п.4). Поэтому рабочее место заводит ПРОДАКШН-адаптер
  (:class:`~bob.coding.adapters.git_clone.GitClone`) через продакшн ``ExecRunner`` в
  одноразовом репозитории, а утверждения читаются обычным git — тем же, которым владелец
  смотрел бы ``git log``;
* граница **выдачи кредов** (:func:`credentials_offered_here`): ``git credential fill`` —
  ровно тот механизм, которым пользуется ``git push``, только без сети. Что ответит он, то
  получил бы и push;
* граница **разговора** (:func:`hand_over_the_work`): реплики, которые владелец реально
  видит в Telegram, и строки панели. Развилку «открывает PR сам / отдаёт ссылку» выбирает
  НАСТОЯЩАЯ композиция (:func:`~bob.runtime.wiring.coding._build_pr_integration`), а на
  ссылочном пути работает и настоящий адаптер :class:`ForkCompareLink` (он чист — ни сети,
  ни процессов). Двойники здесь только у ``claude`` и у git-интеграции, то есть у того, что
  в сценарии про честность реплики роли не играет.

🔴 Источником клона всегда служит ОДНОРАЗОВЫЙ репозиторий, а не рабочее дерево Боба: клон
настоящего репозитория стоит 3.8 с и 142 МБ (замер среза A), и сценарию это не нужно.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.fork_link import ForkCompareLink
from bob.coding.adapters.git_clone import CloneError, GitClone
from bob.coding.push_guard import guarded_spawn_env
from bob.coding.usecases.coding_assistant import CodingAssistant
from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles
from bob.runtime.wiring.coding import _build_pr_integration

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

#: Адрес, по которому «открытый PR» вернул бы прежний gh-путь. Двойник, и это честно: сам
#: ``gh pr create`` — сетевой инструмент, а сценарий про то, ЧТО Боб при этом говорит.
GH_PULL_URL = "https://github.com/zoologov/bob/pull/42"

#: Приватные файлы репозитория (гитигнорены) — ни один не имеет права уехать в клон.
PRIVATE_FILES = (
    "data/soul/self_model.md",
    "bob.db",
    ".env",
    "config/bob.yaml",
    ".secrets/bob-ai-work.pem",
)

_GITIGNORE = "data/\nbob.db*\n.env\n.env.*\nconfig/bob.yaml\n.secrets/\n"

#: Хост, которого нет в DNS: ни один сценарий не может случайно уйти в сеть или в keychain
#: владельца за НАСТОЯЩИМИ кредами (та же мера, что в real-git тестах среза C).
_PROBE_HOST = "bob-workplace-probe.invalid"

#: Фиктивный «пароль владельца»: всплыл в выводе — значит инструмент дотянулся до чужих кредов.
OWNER_SECRET = "OWNERSECRET"

_OWNER_HELPER = "!f() { echo username=owner; echo password=" + OWNER_SECRET + "; }; f"


@dataclass(frozen=True, slots=True)
class OwnerWorld:
    """Одноразовое «хозяйство владельца»: его репозиторий на ``main`` + bare-форк Боба."""

    work: Path
    fork: Path


def _git(cwd: Path, *args: str) -> str:
    """Выполнить одноразовую git-команду в ``cwd`` (подготовка и утверждения сценария)."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def owner_world(tmp_path: Path) -> OwnerWorld:
    """Поднять настоящий репозиторий владельца (с приватными файлами) и bare-форк Боба."""
    work = tmp_path / "owner-repo"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "owner@example.com")
    _git(work, "config", "user.name", "Owner")
    _write(work, ".gitignore", _GITIGNORE)
    _write(work, "README.md", "public readme\n")
    _write(work, "src/app.py", "def main() -> None: ...\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial tracked tree")
    for private in PRIVATE_FILES:
        _write(work, private, f"SECRET {private}\n")

    fork = tmp_path / "fork.git"
    fork.mkdir()
    _git(fork, "init", "--bare", "-b", "main")
    return OwnerWorld(work=work, fork=fork)


def _workplace_adapter(world: OwnerWorld, root: Path) -> GitClone:
    """Продакшн-адаптер рабочего места над настоящим git (одни и те же аргументы у всех шагов)."""
    return GitClone(
        root,
        source=world.work,
        fork_url=f"file://{world.fork}",
        app_user_id="424242",
        runner=ExecRunner(),
    )


def raise_workplace(world: OwnerWorld, root: Path, *, branch: str = "bob/task") -> Path:
    """Завести рабочее место Боба ПРОДАКШН-адаптером над настоящим git и вернуть путь."""
    return Path(asyncio.run(_workplace_adapter(world, root).create(branch)))


@dataclass(frozen=True, slots=True)
class Integration:
    """Итог шага интеграции Боба: работа уехала — или отказ, и что именно он сказал."""

    committed: bool = False
    refusal: str = ""


def integrate_the_work(
    world: OwnerWorld, root: Path, *, branch: str = "bob/task"
) -> Integration:
    """Довести работу до ветки форка ПРОДАКШН-шагом Боба (``GitClone.commit_and_push``).

    🔴 Именно продовым путём, а не обычным ``git commit``: подпись коммита и отказ по
    подложенному ключу — свойства ЭТОГО шага (bob-a6b.16), и проверять их надо через ту же
    границу, через которую работает Боб. Отказ возвращается текстом, а не исключением:
    сценарий утверждает, ЧТО он сказал.
    """
    adapter = _workplace_adapter(world, root)
    try:
        return Integration(committed=asyncio.run(adapter.commit_and_push(
            str(root / branch.split("/", 1)[1]), branch, "[bob] работа"
        )))
    except CloneError as refusal:
        return Integration(refusal=str(refusal))


def plant_in_the_workplace_config(place: Path, key: str, value: str) -> None:
    """«Модель» дописывает ключ в ЛОКАЛЬНЫЙ конфиг рабочего места — обычным ``git config``.

    Каталог целиком в её распоряжении, включая ``<место>/.git``, поэтому это ровно то, что
    ей доступно (и что ревьюер проделал на настоящем git).
    """
    _git(place, "config", "--local", key, value)


def author_of_the_fork_branch(world: OwnerWorld, branch: str) -> str:
    """``имя <адрес>`` автора верхнего коммита ветки В ФОРКЕ — то, что видит владелец."""
    return _git(world.fork, "log", "-1", "--format=%an <%ae>", branch).strip()


def bobs_branches_in_the_fork(world: OwnerWorld) -> list[str]:
    """Все ветки Боба, доехавшие до форка (перечисление, а не проверка известного имени)."""
    return _git(world.fork, "branch", "--list", "bob/*", "--format=%(refname:short)").split()


def files_here(root: Path) -> set[str]:
    """Перечислить ВСЁ содержимое рабочего дерева (без ``.git``) — как ``find``.

    Именно перечисление: приватный файл, о котором сценарий не догадался спросить, всё
    равно попадёт в это множество.
    """
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def commit_here(repo: Path, *, filename: str, message: str) -> str:
    """Сделать в ``repo`` обычный коммит обычным git и вернуть его sha.

    🔴 Без ``-c user.name`` и без переменных окружения: подпись берётся ровно оттуда, куда
    её положил (или не положил) адаптер, — иначе сценарий утверждал бы свою же подсказку.
    """
    (repo / filename).write_text("правка\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return sha_of(repo, "HEAD")


def author_of_last_commit(repo: Path) -> tuple[str, str]:
    """Имя и e-mail автора последнего коммита — то, что владелец видит в ``git log``."""
    return (
        _git(repo, "log", "-1", "--format=%an").strip(),
        _git(repo, "log", "-1", "--format=%ae").strip(),
    )


def sha_of(repo: Path, ref: str) -> str:
    """Коммит, на котором стоит ``ref`` (доказательство «ствол не сдвинулся» — по sha)."""
    return _git(repo, "rev-parse", ref).strip()


def move_ref_here(repo: Path, ref: str, sha: str) -> int:
    """Двинуть ``ref`` внутри ``repo`` через ``update-ref`` и вернуть код возврата.

    🔴 Именно эта команда в linked worktree двигала ``main`` владельца: ни сети, ни кредов,
    мимо любого push-барьера (проверено на настоящем git, волна bob-5ao).
    """
    return subprocess.run(
        ["git", "update-ref", ref, sha], cwd=repo, check=False, capture_output=True, text=True
    ).returncode


def remotes_here(repo: Path) -> str:
    """Все адреса, по которым ``repo`` вообще может что-то отправить."""
    return _git(repo, "remote", "-v")


def credentials_offered_here(
    repo: Path, tmp_path: Path, *, isolated: bool
) -> subprocess.CompletedProcess[str]:
    """Спросить у git креды для ``https://<probe>`` из ``repo`` — с изоляцией или без неё.

    ``isolated=False`` — контроль: дорога к кредам владельца РЕАЛЬНО есть (без контроля
    зелёный сценарий доказывал бы лишь, что кредов не было и так). ``isolated=True`` — то
    же самое в окружении, которое композиция даёт спавну при включённом флаге.
    """
    owner_env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path / "home"),
        "GIT_CONFIG_SYSTEM": str(_helper_config(tmp_path / "systemconfig")),
        "GIT_CONFIG_GLOBAL": str(_helper_config(tmp_path / "ownerconfig")),
    }
    env: Mapping[str, str] | None = owner_env
    if isolated:
        env = guarded_spawn_env(
            owner_env,
            active=False,
            isolation=SpawnIsolationFiles(tmp_path / "spawn-env").materialize(
                fork_url=f"https://{_PROBE_HOST}/bobiverse-dev/bob.git"
            ),
        )
    assert env is not None
    return subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        env=dict(env),
        input=f"protocol=https\nhost={_PROBE_HOST}\n\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _helper_config(path: Path) -> Path:
    """Написать git-конфиг с credential-хелпером владельца и вернуть его путь."""
    path.write_text(f'[credential]\n\thelper = "{_OWNER_HELPER}"\n', encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Граница разговора: что владелец услышал, когда работа доехала
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Handover:
    """Наблюдаемый итог доведённой работы: реплики владельцу, панель и выданный адрес."""

    said: list[str] = field(default_factory=list)
    panel: list[str] = field(default_factory=list)
    url: str = ""
    integration: str = ""

    @property
    def transcript(self) -> str:
        """Всё, что владелец увидел одним куском (реплики + панель)."""
        return "\n".join([*self.said, *self.panel])


class _FakeRunner:
    """Двойник ``claude``: сценарий про честность реплики, а не про работу модели."""

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        events: tuple[Mapping[str, object], ...] = (
            {"type": "result", "subtype": "success", "result": "Итоговый план"}
            if mode == "plan"
            else {"type": "result", "subtype": "success"},
        )
        for event in events:
            yield event


class _FakeWorkplace:
    """Двойник рабочего места: настоящий git проверяется отдельными сценариями (S1–S4)."""

    async def create(self, branch: str) -> str:
        return f"/clones/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        return True

    async def remove(self, path: str) -> None: ...


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        return tuple(self.sessions.values())


@dataclass
class _StubGhOpener:
    """Двойник ``gh pr create``: сеть в сценарии не участвует, адрес возвращается готовым."""

    async def open(self, branch: str, title: str, body: str) -> str:
        return GH_PULL_URL


@dataclass
class _RecordingNotifier:
    said: list[str]

    async def send(self, text: str) -> None:
        self.said.append(text)


@dataclass
class _RecordingPanel:
    lines: list[str]

    async def open(self, text: str) -> None:
        self.lines.append(text)

    async def update(self, text: str) -> None:
        self.lines.append(text)


class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _FakeClock:
    def now(self) -> datetime:
        return _NOW


def hand_over_the_work(*, coder: Mapping[str, object], github: Mapping[str, object]) -> Handover:
    """Довести coding-сессию до финала и вернуть то, что владелец услышал.

    Развилку выбирает НАСТОЯЩАЯ композиция по этому конфигу, и адаптер со флагом
    ``opens_pr`` приезжают ОДНОЙ парой — разведи их, и Боб заявил бы открытый PR там, где
    отдана лишь ссылка. На ссылочном пути работает настоящий :class:`ForkCompareLink`.
    """
    opener, opens_pr = _build_pr_integration(coder, github)
    handover = Handover(integration=type(opener).__name__)
    notifier = _RecordingNotifier(handover.said)
    assistant = CodingAssistant(
        runner=_FakeRunner(),
        worktree=_FakeWorkplace(),
        store=_FakeStore(),
        pr_opener=opener if isinstance(opener, ForkCompareLink) else _StubGhOpener(),
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        opens_pr=opens_pr,
        status_panel=_RecordingPanel(handover.panel),
    )
    outcome = asyncio.run(_drive(assistant, handover))
    handover.url = outcome
    return handover


async def _drive(assistant: CodingAssistant, handover: Handover) -> str:
    """Поставить задачу, одобрить план и вернуть адрес, доехавший до владельца."""
    await assistant.start("Починить парсер", _OWNER_ID)
    handover.said.clear()  # интересен ФИНАЛ: что сказано, когда работа доведена
    handover.panel.clear()
    result = await assistant.approve_plan(_OWNER_ID)
    if result.session is None or result.session.pr_url is None:
        return ""  # адрес не доехал — сценарий увидит это как пустую ссылку
    return result.session.pr_url
