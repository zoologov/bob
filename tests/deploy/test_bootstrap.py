# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""``deploy/bootstrap.sh`` on a fresh host: config and understudy model by config (BOB-116 D8b).

The two BOB-116 steps of the bootstrap are EXECUTED: the script is sourced (its ``main``
does not run when sourced) and the step function is called, with ``sudo``, ``install`` and
``ollama`` replaced by recording stubs. ``deploy/check_config.py`` and ``sha256sum`` are
the real ones, so the decision «pull a model or not» is the same one the deploy makes.

Not held here: apt, useradd, the real Ollama and systemd — the rest of ``main``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from tests.deploy.conftest import (
    CHECK_SCRIPT,
    PRODUCTION_ENV,
    REPO_ROOT,
    STUBS,
    VPS_CONFIG,
    write_env_file,
    write_executable,
)

if TYPE_CHECKING:
    from pathlib import Path

_BOOTSTRAP = REPO_ROOT / "deploy" / "bootstrap.sh"
_TIMEOUT_S = 60


@dataclass(frozen=True)
class StepRun:
    returncode: int
    output: str
    calls: list[str]


def _host(tmp_path: Path, tracked: str, *, with_env: bool) -> Path:
    home = tmp_path / "opt-bob"
    (home / "deploy").mkdir(parents=True)
    (home / "config").mkdir()
    (home / ".venv" / "bin").mkdir(parents=True)
    shutil.copyfile(CHECK_SCRIPT, home / "deploy" / "check_config.py")
    (home / "config" / "bob.vps.yaml").write_text(tracked, encoding="utf-8")
    write_executable(home / ".venv" / "bin" / "python", f'exec "{sys.executable}" "$@"\n')
    if with_env:
        write_env_file(home / ".env", PRODUCTION_ENV)
    return home


def _run_step(
    tmp_path: Path,
    step: str,
    *,
    tracked: str | None = None,
    with_env: bool = True,
    ollama_installed: bool = True,
    stub_env: dict[str, str] | None = None,
) -> StepRun:
    home = _host(tmp_path, tracked or VPS_CONFIG.read_text(encoding="utf-8"), with_env=with_env)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("sudo", "install", "ollama"):
        if name == "ollama" and not ollama_installed:
            continue
        write_executable(bin_dir / name, STUBS[name])
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "calls.log"
    log.touch()
    bash = shutil.which("bash")
    assert bash is not None
    # Only the stubs and the system basics: a developer's own ollama must not be found.
    path = os.pathsep.join([str(bin_dir), "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    result = subprocess.run(  # noqa: S603 — host bash sources the repo's own bootstrap
        [bash, "-c", f'source "{_BOOTSTRAP}" && {step}'],
        capture_output=True,
        text=True,
        env={
            "PATH": path,
            "HOME": str(tmp_path),
            "STUB_LOG": str(log),
            "STUB_STATE": str(state),
            "BOB_HOME": str(home),
            "BOB_USER": "bob",
            **(stub_env or {}),
        },
        cwd=tmp_path,
        timeout=_TIMEOUT_S,
        check=False,
    )
    return StepRun(
        returncode=result.returncode,
        output=result.stdout + result.stderr,
        calls=log.read_text(encoding="utf-8").splitlines(),
    )


def _tracked_with_understudy(model: str) -> str:
    config = yaml.safe_load(VPS_CONFIG.read_text(encoding="utf-8"))
    config["llm"].update(tier0_fallback="ollama", tier0_fallback_model=model)
    return yaml.safe_dump(config, allow_unicode=True)


def test_bootstrap_pulls_no_model_while_the_config_keeps_the_understudy_off(
    tmp_path: Path,
) -> None:
    run = _run_step(tmp_path, "ensure_understudy_model")

    assert run.returncode == 0, run.output
    assert "дублёр выключен в конфиге — модель не тянем" in run.output
    assert not any(call.startswith("ollama") for call in run.calls), run.calls


def test_bootstrap_pulls_the_configured_model_and_checks_it_is_listed(tmp_path: Path) -> None:
    run = _run_step(
        tmp_path, "ensure_understudy_model", tracked=_tracked_with_understudy("qwen3:8b")
    )

    assert run.returncode == 0, run.output
    pull = run.calls.index("ollama pull qwen3:8b")
    last_list = max(i for i, call in enumerate(run.calls) if call == "ollama list")
    assert pull < last_list, run.calls  # the model is checked in the list AFTER the pull


def test_bootstrap_decides_before_the_owner_has_put_env_in_place(tmp_path: Path) -> None:
    run = _run_step(
        tmp_path,
        "ensure_understudy_model",
        tracked=_tracked_with_understudy("qwen3:8b"),
        with_env=False,
    )

    assert run.returncode == 0, run.output
    assert "ollama pull qwen3:8b" in run.calls


def test_bootstrap_fails_when_the_understudy_is_on_and_ollama_is_absent(tmp_path: Path) -> None:
    run = _run_step(
        tmp_path,
        "ensure_understudy_model",
        tracked=_tracked_with_understudy("qwen3:8b"),
        ollama_installed=False,
    )

    assert run.returncode != 0
    assert "ollama" in run.output


def test_bootstrap_fails_when_the_pulled_model_is_not_listed(tmp_path: Path) -> None:
    run = _run_step(
        tmp_path,
        "ensure_understudy_model",
        tracked=_tracked_with_understudy("qwen3:8b"),
        stub_env={"STUB_OLLAMA_PULL_NOOP": "1"},
    )

    assert run.returncode != 0
    assert "qwen3:8b" in run.output


def test_bootstrap_installs_the_tracked_config_byte_for_byte(tmp_path: Path) -> None:
    run = _run_step(tmp_path, "ensure_config")

    home = tmp_path / "opt-bob" / "config"
    assert run.returncode == 0, run.output
    assert (home / "bob.yaml").read_bytes() == (home / "bob.vps.yaml").read_bytes()


def test_bootstrap_stops_on_a_config_copy_that_differs(tmp_path: Path) -> None:
    run = _run_step(tmp_path, "ensure_config", stub_env={"STUB_INSTALL_CORRUPT": "1"})

    assert run.returncode != 0
    assert "sha256" in run.output
