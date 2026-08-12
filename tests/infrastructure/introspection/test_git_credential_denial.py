# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 bob-a6b.13: ATTEMPTS to fetch a credentialed git URL through the public entry.

MAJOR-6 was a RUN, not a code reading: the live introspector returned
``.git/config`` verbatim, token in the remote URL included, and would have shipped it to
the external LLM. So the fix is proved the same way — by letting REAL ``git`` write the
credentialed remote into a REAL ``.git/config`` (a fake would only prove the fake's
contract, CLAUDE.md §0.3 п.4) and then CALLING the tools a model actually reaches
(``read_file`` behind ``read_code``, ``list_dir``, ``find_file``). Nothing here inspects
the guard's internals.

Four things are asserted, in this order of importance:

1. **Refusal.** Every public path into the filesystem refuses git's service files —
   ``.git/config``, the whole ``.git`` subtree, a worktree's gitdir pointer, the clones
   Bob keeps under ``.clones/``, and the spawn-env's substitute ``gitconfig``.
2. **Backstop when the guard MISSES.** The same config text under an ORDINARY name IS
   read — and comes back with the password redacted and the host intact, because
   sanitize judges the URL GRAMMAR, not the key's name (the key is called ``url``).
3. **Zero collateral.** Every path ``git ls-files`` names in this repo is still allowed —
   the property the reviewer confirmed after bob-zmp, re-asserted against the live tree.
4. **BOB-067 intact.** ``.gitignore`` / ``.github`` / ``config/`` and ordinary source
   still read and list; the denial is pointed, not a retreat to a whitelist.

The credential is synthetic (``hunter2SUPERSECRET``) — never a live token.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    DeniedPathError,
    SubprocessRepoIntrospector,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard

# This file is tests/infrastructure/introspection/<file> → the repo root is three up.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The reviewer's fixture, verbatim: the password git parks in a https remote URL.
_URL_PASSWORD = "hunter2SUPERSECRET"  # noqa: S105 — synthetic, never a live token
_CREDENTIALED_REMOTE = f"https://bob:{_URL_PASSWORD}@github.com/owner/repo.git"

_needs_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not on PATH"
)


def _git(repo: Path, *args: str) -> None:
    """Run a real ``git`` command in ``repo`` (no shell), failing loudly."""
    subprocess.run(  # noqa: S603 - fixed argv, no shell, test-local paths
        ["git", *args],  # noqa: S607 - resolved via PATH by design
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _init_repo_with_credentialed_remote(root: Path) -> Path:
    """``git init`` at ``root`` and let REAL git write the credentialed remote URL."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--quiet")
    _git(root, "remote", "add", "origin", _CREDENTIALED_REMOTE)
    config = root / ".git" / "config"
    # 🔴 The premise of every refusal below: git really put the secret on disk, so without
    # the fix this content WOULD have been returned.
    assert _URL_PASSWORD in config.read_text(encoding="utf-8")
    return config


def _introspector(root: Path) -> SubprocessRepoIntrospector:
    """A REAL introspector (no fake runner) rooted at ``root``."""
    return SubprocessRepoIntrospector(PrivacyGuard(root))


@pytest.fixture
def workplace(tmp_path: Path) -> Path:
    """A tree shaped like Bob's workplace: a repo, a clone under ``.clones``, a spawn-env."""
    _init_repo_with_credentialed_remote(tmp_path)
    _init_repo_with_credentialed_remote(tmp_path / ".clones" / "epic-bob-089")
    spawn_env = tmp_path / ".clones" / ".spawn-env"
    spawn_env.mkdir(parents=True, exist_ok=True)
    (spawn_env / "gitconfig").write_text(
        "[credential]\n\thelper = store --file /tmp/credentials\n", encoding="utf-8"
    )
    (spawn_env / "credentials").write_text(f"{_CREDENTIALED_REMOTE}\n", encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "mod.py").write_text(
        "def hello() -> str:\n    return 'hi'\n", encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    return tmp_path


# --- 1. REFUSAL: the tools a model reaches cannot fetch a credentialed URL -------


@_needs_git
@pytest.mark.parametrize(
    "target",
    [
        ".git/config",  # 🔴 the reproduced call, verbatim
        ".git/HEAD",  # anything else inside git's bookkeeping
        ".clones/epic-bob-089/.git/config",  # Bob's own long-lived workplace clone
        ".clones/.spawn-env/gitconfig",  # the substitute global config (credential helper)
        ".clones/.spawn-env/credentials",  # the 0600 store the spawn env writes
    ],
)
@pytest.mark.asyncio
async def test_read_file_refuses_git_service_files(workplace: Path, target: str) -> None:
    intro = _introspector(workplace)

    with pytest.raises(DeniedPathError):
        await intro.read_file(target, max_lines=200)


@_needs_git
@pytest.mark.asyncio
async def test_read_file_refuses_the_absolute_path_to_the_git_config_too(
    workplace: Path,
) -> None:
    # A model that spells the path absolutely gets the same refusal.
    intro = _introspector(workplace)

    with pytest.raises(DeniedPathError):
        await intro.read_file(str(workplace / ".git" / "config"), max_lines=200)


@_needs_git
@pytest.mark.asyncio
async def test_read_file_refuses_the_git_config_reached_through_dotdot(
    workplace: Path,
) -> None:
    # A detour cannot launder the path — the verdict is on the RESOLVED spelling.
    intro = _introspector(workplace)

    with pytest.raises(DeniedPathError):
        await intro.read_file("src/../.git/config", max_lines=200)


@_needs_git
@pytest.mark.asyncio
async def test_list_dir_refuses_the_git_directory(workplace: Path) -> None:
    # Otherwise the model finds the config's neighbours and asks for them by name.
    intro = _introspector(workplace)

    with pytest.raises(DeniedPathError):
        await intro.list_dir(".git")
    with pytest.raises(DeniedPathError):
        await intro.list_dir(".clones/epic-bob-089/.git")


def _hits(result: str) -> list[str]:
    """The path lines ``find_file`` returned (an honest-empty answer yields none)."""
    if result.startswith("No files matching"):
        return []
    return [line for line in result.splitlines() if line and not line.startswith("…")]


@_needs_git
@pytest.mark.asyncio
async def test_find_file_does_not_enumerate_git_service_files(workplace: Path) -> None:
    # The refusal to list must not be one glob away from being bypassed.
    intro = _introspector(workplace)

    found = [
        hit
        for pattern in ("config", ".git/config", "**/config", "gitconfig", "credentials")
        for hit in _hits(await intro.find_file(pattern))
    ]

    assert found == []


@_needs_git
@pytest.mark.asyncio
async def test_read_file_refuses_a_worktrees_gitdir_pointer(workplace: Path) -> None:
    """A linked worktree's ``.git`` is a FILE naming the real gitdir — refused as well.

    Bob's workplaces are clones today, but ``.worktrees/`` still exists in this repo; the
    pointer file leads straight to the credentialed config, so it must not be readable.
    """
    _git(workplace, "-c", "user.email=t@t", "-c", "user.name=t", "commit",
         "--allow-empty", "-m", "init", "--quiet")
    _git(workplace, "worktree", "add", "--quiet", ".worktrees/wt")
    pointer = workplace / ".worktrees" / "wt" / ".git"
    assert pointer.is_file()  # the premise: it really is the pointer FILE form
    intro = _introspector(workplace)

    with pytest.raises(DeniedPathError):
        await intro.read_file(".worktrees/wt/.git", max_lines=5)


@pytest.mark.asyncio
async def test_the_live_repos_git_config_is_denied() -> None:
    """🔴 The reviewer's repro against the LIVE tree, wired exactly as production is.

    The organisational half ("do not put tokens in your remote") must not be what protects
    us: this epic itself moved the example config from ssh to https, i.e. raised the chance
    a token sits here. The guard is rooted at the real repo root, as ``build_runtime`` wires
    it, and the live ``.git/config`` must be out of reach whatever it currently holds.
    """
    intro = _introspector(_REPO_ROOT)
    assert (_REPO_ROOT / ".git" / "config").is_file()  # the premise of the attempt

    with pytest.raises(DeniedPathError):
        await intro.read_file(".git/config", max_lines=200)
    with pytest.raises(DeniedPathError):
        await intro.list_dir(".git")


# --- 2. BACKSTOP: when the guard misses, sanitize must still save us ------------


@_needs_git
@pytest.mark.asyncio
async def test_a_git_config_copied_under_an_ordinary_name_comes_back_redacted(
    workplace: Path,
) -> None:
    # 🔴 The layer that matters most, because a path rule can always be dodged: the same
    # text pasted into a note (a backup, a paste of ``git remote -v``, a debug dump) IS
    # read — and the password is gone anyway. The key here is called ``url``: no
    # name-based rule can fire, so this proves the URL-grammar rule, not a lucky word.
    leaked = (workplace / ".git" / "config").read_text(encoding="utf-8")
    note = workplace / "docs" / "clone-notes.md"
    note.parent.mkdir(exist_ok=True)
    note.write_text(f"how the workplace is wired:\n{leaked}", encoding="utf-8")
    intro = _introspector(workplace)

    out = await intro.read_file("docs/clone-notes.md", max_lines=200)

    assert _URL_PASSWORD not in out
    assert "REDACTED" in out
    # …and Bob is not blinded: the surrounding prose and the HOST survive, so he can still
    # say where the remote points.
    assert "how the workplace is wired:" in out
    assert "github.com/owner/repo.git" in out


@_needs_git
@pytest.mark.asyncio
async def test_a_credential_store_line_under_an_ordinary_name_is_redacted(
    workplace: Path,
) -> None:
    # The store's single line is the same shape without any key at all.
    dump = workplace / "paste.txt"
    dump.write_text(f"{_CREDENTIALED_REMOTE}\n", encoding="utf-8")
    intro = _introspector(workplace)

    out = await intro.read_file("paste.txt", max_lines=5)

    assert _URL_PASSWORD not in out
    assert "REDACTED" in out


# --- 3. ZERO COLLATERAL: nothing tracked is hidden ------------------------------


@_needs_git
def test_the_shape_denial_hides_zero_tracked_files() -> None:
    """🔴 The property the reviewer confirmed after bob-zmp, re-asserted after this fix.

    A widened path rule is one sloppy pattern away from blinding Bob to his own repo, so
    the check is exhaustive rather than illustrative: EVERY path real ``git ls-files``
    names in this repo must still be allowed. ``.gitignore``, ``.github/``, ``config/``
    and ``src/bob/infrastructure/config/`` are the near-misses this would catch.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 - resolved via PATH by design
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    tracked = [entry for entry in listing.stdout.split("\0") if entry]
    assert len(tracked) > 1000  # the premise: this really is the whole repo

    guard = PrivacyGuard(_REPO_ROOT)
    hidden = [path for path in tracked if not guard.allows_path(Path(path))]

    assert hidden == []


# --- 4. BOB-067: full-repo navigation is untouched ------------------------------


@_needs_git
@pytest.mark.asyncio
async def test_git_lookalikes_and_ordinary_config_still_read(workplace: Path) -> None:
    intro = _introspector(workplace)
    (workplace / ".github" / "workflows").mkdir(parents=True)
    (workplace / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (workplace / "config").mkdir()
    (workplace / "config" / "bob.example.yaml").write_text("llm:\n  tier: 0\n", encoding="utf-8")

    ignore = await intro.read_file(".gitignore", max_lines=5)
    workflow = await intro.read_file(".github/workflows/ci.yml", max_lines=5)
    example = await intro.read_file("config/bob.example.yaml", max_lines=5)
    code = await intro.read_file("src/mod.py", max_lines=5)
    root_listing = await intro.list_dir(".")
    conf_listing = await intro.list_dir("config")

    assert "*.pyc" in ignore
    assert "on: push" in workflow
    assert "tier: 0" in example
    assert "def hello()" in code
    assert "src/" in root_listing
    assert "bob.example.yaml" in conf_listing


@pytest.mark.asyncio
async def test_the_live_repo_still_reads_its_own_git_adjacent_files() -> None:
    # In the LIVE tree (where production roots the guard) the near-misses still read.
    intro = _introspector(_REPO_ROOT)

    ignore = await intro.read_file(".gitignore", max_lines=200)
    loader = await intro.read_file(
        "src/bob/infrastructure/config/loader.py", max_lines=40
    )
    listing = await intro.list_dir(".")

    assert ignore.strip()
    assert "ConfigLoader" in loader  # the real module head, not a refusal
    assert "src/" in listing
