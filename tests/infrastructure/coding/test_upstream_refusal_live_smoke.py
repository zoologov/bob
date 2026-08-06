# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 ЖИВОЙ негативный смоук: апстрим отказывает Бобу ПО ПРАВАМ (BOB-089, срез C).

Критерий приёмки эпика, а не «если останется время»: пока отказ не увиден от НАСТОЯЩЕГО
GitHub, неприкосновенность ``main`` держится на нашем предположении о правах, а не на
правах. Фейк здесь бесполезен по определению — проверяется именно вердикт чужого сервера.

Четыре вектора из PLAN, все из клона Боба его окружением:

1. ``git push`` ветки в апстрим токеном ``work`` → ``remote: Repository not found``
   (установки приложения на апстриме нет — GitHub скрывает существование репозитория);
2. ``git push --force HEAD:main`` в апстрим → тот же отказ, ничего особенного для ствола
   не требуется;
3. ``git remote set-url origin <апстрим>`` + ``git push origin`` → тот же отказ:
   переадресация remote'а изнутри ничего не даёт, потому что дело не в адресе, а в правах;
4. токеном ``propose`` (он на апстриме УСТАНОВЛЕН, но с ``contents: read``) →
   ``remote: Write access to repository not granted`` + ``403``. Это самая прямая
   формулировка «по правам», какую GitHub вообще выдаёт.

И легитимный путь: пуш ветки ``bob/<slug>`` в ФОРК Боба тем же токеном, тем же окружением,
тем же транспортом — **проходит**. 🔴 Именно эта пара и доказывает, что отказ приходит по
ПРАВАМ, а не от нашей вежливости: различается только репозиторий-адресат.

🔴 Проверяется ТЕКСТ, а не только код возврата. Каждый негативный тест утверждает две
вещи: отказ пришёл от GitHub по правам И это НЕ наша заглушка ``pushInsteadOf`` и НЕ
«кредов не нашлось» (``terminal prompts disabled``) — иначе тест был бы зелёным и в
конфигурации, где Боб просто не аутентифицировался.

Смоук **opt-in**: без ``BOB_LIVE_GITHUB_SMOKE=1`` и без реквизитов принципалов он
пропускается с ЯВНОЙ причиной — сеть в обычном прогоне и в CI не трогается, но и молчания
о непройденной проверке нет. Что он делает в сети: минтит installation-токены, создаёт и
УДАЛЯЕТ одну временную ветку в форке Боба; в апстрим не попадает ни один ref (это и
проверяется). Токен не печатается и ни в один ассерт не входит значением.

Прогон вживую (2026-08-06, dev-волна среза C) — фактические тексты в комментарии беады
``bob-a6b.3``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bob.coding.push_guard import PUSH_GUARD_STUB_URL, guarded_spawn_env
from bob.identity.adapters.installation_token import build_installation_tokens
from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles
from bob.identity.principals import Purpose
from bob.runtime.config import _REPO_ROOT

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

_OPT_IN = "BOB_LIVE_GITHUB_SMOKE"

#: Признаки того, что отказал GitHub ПО ПРАВАМ. Оба видены вживую: скрытие репозитория
#: (установки нет) и прямая формулировка про отсутствие права записи.
_RIGHTS_MARKERS = ("Repository not found", "Write access to repository not granted")

#: Признак того, что до прав дело не дошло — Боб просто не аутентифицировался. Зелёный
#: негативный тест с этим текстом означал бы «проверили не то».
_NO_CREDENTIALS = "terminal prompts disabled"


class _Clock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


def _section() -> dict[str, object]:
    """Секция конфига ``github`` из окружения — или skip с ЯВНОЙ причиной."""
    if os.environ.get(_OPT_IN) != "1":
        pytest.skip(f"живой смоук выключен: не задан {_OPT_IN}=1 (сеть не трогаем)")
    section: dict[str, object] = {
        key.removeprefix("BOB_GITHUB__").lower(): value
        for key, value in os.environ.items()
        if key.startswith("BOB_GITHUB__")
    }
    required = (
        "work_app_id",
        "work_app_key",
        "work_repo",
        "propose_app_id",
        "propose_app_key",
        "propose_repo",
    )
    missing = [
        f"BOB_GITHUB__{name.upper()}"
        for name in required
        if not str(section.get(name, "")).strip()
    ]
    if missing:
        pytest.skip(f"живой смоук пропущен: в окружении нет реквизитов {', '.join(missing)}")
    return section


def _url_of(section: dict[str, object], key: str) -> str:
    return f"https://github.com/{section[key]}.git"


def _git(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Одноразовый клон-подобный репозиторий Боба с одним коммитом на рабочей ветке."""
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "bob-ai-work[bot]@users.noreply.github.com")
    _git(repo, "config", "user.name", "bob[ai]")
    (repo / "smoke.txt").write_text("live smoke\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "работа Боба")
    return repo


@pytest.fixture
def branch() -> str:
    return f"bob/live-smoke-{int(time.time())}"


@pytest.fixture
async def bobs_env(tmp_path: Path) -> dict[str, str]:
    """Окружение спавна Боба с ЖИВЫМ installation-токеном принципала ``work``.

    Барьер ``pushInsteadOf`` здесь ВЫКЛЮЧЕН сознательно (``active=False``, прод-дефолт
    ``coder.allow_bypass``): иначе push умирал бы на заглушке и вердикт GitHub о правах мы
    бы вообще не увидели — то есть проверяли бы свою вежливость вместо прав.
    """
    section = _section()
    tokens = build_installation_tokens(section, clock=_Clock(), root=_REPO_ROOT)
    token = await tokens.token(Purpose.PUSH_TO_FORK)
    isolation = SpawnIsolationFiles(tmp_path / "spawn-env").materialize(
        fork_url=_url_of(section, "work_repo"), token=token
    )
    env = guarded_spawn_env(os.environ, active=False, isolation=isolation)
    assert env is not None
    return env


@pytest.fixture
async def proposing_env(tmp_path: Path) -> dict[str, str]:
    """То же окружение, но с токеном принципала ``propose`` (он на апстриме УСТАНОВЛЕН)."""
    section = _section()
    tokens = build_installation_tokens(section, clock=_Clock(), root=_REPO_ROOT)
    token = await tokens.token(Purpose.READ_UPSTREAM)
    isolation = SpawnIsolationFiles(tmp_path / "spawn-env-propose").materialize(
        fork_url=_url_of(section, "propose_repo"), token=token
    )
    env = guarded_spawn_env(os.environ, active=False, isolation=isolation)
    assert env is not None
    return env


def _assert_refused_by_rights(result: subprocess.CompletedProcess[str]) -> None:
    """Утвердить, что отказал GitHub ПО ПРАВАМ, а не наша заглушка и не отсутствие кредов."""
    assert result.returncode != 0
    text = result.stderr + result.stdout
    assert any(marker in text for marker in _RIGHTS_MARKERS), text
    # Не наша вежливость: заглушка pushInsteadOf в этом окружении не участвует.
    assert PUSH_GUARD_STUB_URL.split("://")[0] not in text
    # И не «Боб не аутентифицировался»: до прав дело дошло, значит креды были предъявлены.
    assert _NO_CREDENTIALS not in text


# --------------------------------------------------------------------------- #
# Легитимный путь: ветка в форк Боба — РАБОТАЕТ
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_bob_can_push_his_branch_to_his_own_fork(
    workspace: Path, branch: str, bobs_env: dict[str, str]
) -> None:
    fork = _url_of(_section(), "work_repo")

    pushed = _git(workspace, "push", fork, f"HEAD:refs/heads/{branch}", env=bobs_env)

    try:
        assert pushed.returncode == 0, pushed.stderr
        assert "new branch" in pushed.stderr
    finally:
        # Уборка тем же токеном: смоук не оставляет за собой веток в форке.
        _git(workspace, "push", fork, f":refs/heads/{branch}", env=bobs_env)


# --------------------------------------------------------------------------- #
# 🔴 Векторы в апстрим: отказ ПО ПРАВАМ, с проверкой текста
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_pushing_a_branch_to_the_upstream_is_refused_by_rights(
    workspace: Path, branch: str, bobs_env: dict[str, str]
) -> None:
    upstream = _url_of(_section(), "propose_repo")

    result = _git(workspace, "push", upstream, f"HEAD:refs/heads/{branch}", env=bobs_env)

    _assert_refused_by_rights(result)


@pytest.mark.integration
async def test_force_pushing_the_trunk_of_the_upstream_is_refused_by_rights(
    workspace: Path, bobs_env: dict[str, str]
) -> None:
    # Ствол не требует ничего особенного — и именно поэтому важно, что отказ приходит.
    upstream = _url_of(_section(), "propose_repo")

    result = _git(workspace, "push", "--force", upstream, "HEAD:refs/heads/main", env=bobs_env)

    _assert_refused_by_rights(result)


@pytest.mark.integration
async def test_repointing_the_remote_at_the_upstream_changes_nothing(
    workspace: Path, branch: str, bobs_env: dict[str, str]
) -> None:
    # 🔴 Известный обход барьера ``pushInsteadOf`` (проверено bob-5ao). Против прав он
    # бессмыслен: адрес меняется, права — нет.
    section = _section()
    _git(workspace, "remote", "add", "origin", _url_of(section, "work_repo"))
    _git(workspace, "remote", "set-url", "origin", _url_of(section, "propose_repo"))

    result = _git(workspace, "push", "origin", f"HEAD:refs/heads/{branch}", env=bobs_env)

    _assert_refused_by_rights(result)


@pytest.mark.integration
async def test_the_propose_principal_is_told_it_has_no_write_access(
    workspace: Path, branch: str, proposing_env: dict[str, str]
) -> None:
    # Принципал, который апстрим ВИДИТ (установка есть, ``contents: read``): здесь GitHub
    # говорит про права прямым текстом, без маскировки под «репозитория нет».
    upstream = _url_of(_section(), "propose_repo")

    result = _git(workspace, "push", upstream, f"HEAD:refs/heads/{branch}", env=proposing_env)

    assert result.returncode != 0
    assert "Write access to repository not granted" in result.stderr
    assert "403" in result.stderr
    assert _NO_CREDENTIALS not in result.stderr


# --------------------------------------------------------------------------- #
# 🔴 Вектор мимо сети: локальный ref — на НАСТОЯЩЕМ репозитории owner'а
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_moving_main_inside_bobs_clone_leaves_the_owners_real_main_untouched(
    tmp_path: Path,
) -> None:
    """``update-ref refs/heads/main`` в клоне НАСТОЯЩЕГО репозитория owner'а — sha до/после.

    Сети этот вектор не требует вовсе, поэтому правами он не закрывается: его закрыл срез
    A (свой ``.git``). Здесь он проверяется на РЕАЛЬНОМ репозитории, а не на одноразовом
    (тот же тест на одноразовом репозитории гоняется в обычном прогоне —
    ``test_git_clone_real_git.py``): критерий приёмки эпика требует сравнения sha именно в
    основном репозитории.

    Репозиторий owner'а тест только ЧИТАЕТ: пишет он в клон, лежащий в ``tmp_path``.
    """
    if os.environ.get(_OPT_IN) != "1":
        pytest.skip(f"смоук на настоящем репозитории выключен: не задан {_OPT_IN}=1")
    from bob.coding.adapters._exec import ExecRunner  # noqa: PLC0415 — только для смоука
    from bob.coding.adapters.git_clone import GitClone  # noqa: PLC0415

    trunk_before = _git(_REPO_ROOT, "rev-parse", "refs/heads/main").stdout.strip()
    head_before = _git(_REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
    assert trunk_before  # контроль: main у owner'а действительно существует

    clone = GitClone(tmp_path / "clones", source=_REPO_ROOT, runner=ExecRunner(), timeout=600)
    workplace = await clone.create("bob/live-smoke-updateref")
    (Path(workplace) / "probe.txt").write_text("claude edit\n", encoding="utf-8")
    _git(Path(workplace), "add", ".")
    _git(Path(workplace), "commit", "-q", "-m", "работа Боба в клоне")
    head = _git(Path(workplace), "rev-parse", "HEAD").stdout.strip()

    moved = _git(Path(workplace), "update-ref", "refs/heads/main", head)

    assert moved.returncode == 0  # внутри СВОЕГО репозитория это законная операция
    assert _git(Path(workplace), "rev-parse", "main").stdout.strip() == head
    # 🔴 И главное: у owner'а не сдвинулось ни ``main``, ни его рабочий HEAD.
    assert _git(_REPO_ROOT, "rev-parse", "refs/heads/main").stdout.strip() == trunk_before
    assert _git(_REPO_ROOT, "rev-parse", "HEAD").stdout.strip() == head_before


# --------------------------------------------------------------------------- #
# 🔴 Обход изоляции изнутри: что он в самом деле даёт
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_stripping_the_env_config_only_costs_bob_his_own_credentials(
    workspace: Path, branch: str, bobs_env: dict[str, str]
) -> None:
    # ``GIT_CONFIG_COUNT=0`` изнутри — известный способ снять меры, живущие в окружении.
    # Кредов owner'а он НЕ возвращает (их гасит подменный global-конфиг ФАЙЛОМ), зато
    # снимает и стор самого Боба: обход оставляет процесс вообще без кредов.
    upstream = _url_of(_section(), "propose_repo")

    result = _git(
        workspace,
        "push",
        upstream,
        f"HEAD:refs/heads/{branch}",
        env={**bobs_env, "GIT_CONFIG_COUNT": "0"},
    )

    assert result.returncode != 0
    assert _NO_CREDENTIALS in result.stderr
