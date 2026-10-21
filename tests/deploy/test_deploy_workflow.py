# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The deploy step of ``deploy-bob.yml``, EXECUTED — not grepped (BOB-116 D8b).

The guard reads the workflow with ``yaml.safe_load``, takes the ``run`` script of the step
that deploys and restarts Bob, and runs it with bash exactly as the runner would — with
``ssh`` replaced by a stub that runs the remote half locally, and the server's commands
(``sudo``, ``git``, ``uv``, ``install``, ``systemctl``, ``ollama``, ``beadloom``) replaced
by stubs that record each call. ``deploy/check_config.py``, ``sha256sum`` and the loader
are the real ones.

What it holds is BEHAVIOUR (CLAUDE.md П.0.3 п.12): Bob is restarted only after the
``.env`` precondition and the config validation passed, the effective ``config/bob.yaml``
equals the tracked file byte for byte, the understudy model is pulled exactly when the
effective config turns the understudy on, and no value from ``.env`` reaches the log. A
step that is present in the text but not in the run — or present but after the restart —
fails here.

What it does NOT hold: the real ssh hop, the real systemd and Ollama, and the server's
paths — the remote script reads ``BOB_HOME``/``UV_BIN``/``UV_TOOLS``/``UV_TOOL_BINS``
from the environment only so that this test can point them at a temporary directory;
over real ssh none of them is passed, and the production defaults apply.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
import yaml

from tests.deploy.conftest import (
    CHECK_SCRIPT,
    PRODUCTION_ENV,
    REPO_ROOT,
    STUBS,
    VPS_CONFIG,
    leaked_values,
    write_env_file,
    write_executable,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-bob.yml"
_DEPLOY_STEP = "Deploy & restart on VPS"
_DEPLOY_REF = "v9.9.9"
_OLD_LIVE_CONFIG = "# рукописный конфиг до BOB-116\ntelegram:\n  poll_timeout: 10\n"
_TIMEOUT_S = 120

@dataclass(frozen=True)
class DeployRun:
    returncode: int
    output: str
    calls: list[str]
    live_config: bytes
    tracked_config: bytes
    # Never in the repr: a failed assertion prints the dataclass, and these hold secrets.
    env_before: bytes = field(repr=False)
    env_after: bytes = field(repr=False)

    def index(self, predicate: Callable[[str], bool]) -> int:
        """Position of the first recorded call matching ``predicate``; -1 when none."""
        return next((i for i, call in enumerate(self.calls) if predicate(call)), -1)

    def ran(self, fragment: str) -> int:
        return self.index(lambda call: fragment in call)


def _deploy_script() -> str:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy"]["steps"]
    matching = [step for step in steps if step.get("name") == _DEPLOY_STEP]
    assert len(matching) == 1, f"exactly one step named {_DEPLOY_STEP!r} in jobs.deploy"
    script = matching[0]["run"]
    assert isinstance(script, str)
    return script


def _server(tmp_path: Path, tracked: str) -> Path:
    """A fake /opt/bob: the checked-out code's check script, configs, venv python, .env."""
    home = tmp_path / "opt-bob"
    (home / "deploy").mkdir(parents=True)
    (home / "config").mkdir()
    (home / ".venv" / "bin").mkdir(parents=True)
    shutil.copyfile(CHECK_SCRIPT, home / "deploy" / "check_config.py")
    (home / "config" / "bob.vps.yaml").write_text(tracked, encoding="utf-8")
    (home / "config" / "bob.yaml").write_text(_OLD_LIVE_CONFIG, encoding="utf-8")
    write_executable(home / ".venv" / "bin" / "python", f'exec "{sys.executable}" "$@"\n')
    return home


def _deploy(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    tracked: str | None = None,
    stub_env: dict[str, str] | None = None,
) -> DeployRun:
    home = _server(tmp_path, tracked or VPS_CONFIG.read_text(encoding="utf-8"))
    env_values = PRODUCTION_ENV if env is None else env
    env_file = write_env_file(home / ".env", env_values)
    env_before = env_file.read_bytes()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        write_executable(bin_dir / name, body)
    state = tmp_path / "state"
    state.mkdir()
    tools = tmp_path / "uv-tools"
    tools.mkdir()
    log = tmp_path / "calls.log"
    log.touch()
    run_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "STUB_STATE": str(state),
        "VPS_HOST": "vps.example",
        "VPS_USER": "root",
        "DEPLOY_REF": _DEPLOY_REF,
        "BOB_HOME": str(home),
        "UV_BIN": str(bin_dir / "uv"),
        "UV_TOOLS": str(tools),
        "UV_TOOL_BINS": str(bin_dir),
        **(stub_env or {}),
    }
    result = subprocess.run(  # noqa: S603 — host bash runs the workflow's own step
        [_host_bash(), "-c", _deploy_script()],
        capture_output=True,
        text=True,
        env=run_env,
        cwd=tmp_path,
        timeout=_TIMEOUT_S,
        check=False,
    )
    return DeployRun(
        returncode=result.returncode,
        output=result.stdout + result.stderr,
        calls=log.read_text(encoding="utf-8").splitlines(),
        live_config=(home / "config" / "bob.yaml").read_bytes(),
        tracked_config=(home / "config" / "bob.vps.yaml").read_bytes(),
        env_before=env_before,
        env_after=env_file.read_bytes(),
    )


def _host_bash() -> str:
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to run the deploy guard"
    return bash


def _tracked_with_understudy(model: str) -> str:
    config = yaml.safe_load(VPS_CONFIG.read_text(encoding="utf-8"))
    config["llm"].update(tier0_fallback="ollama", tier0_fallback_model=model)
    return yaml.safe_dump(config, allow_unicode=True)


def _restarted(run: DeployRun) -> bool:
    return run.ran("systemctl restart bob") >= 0


def test_the_deploy_checks_then_copies_then_restarts_in_that_order(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    checkout = run.ran(f"checkout {_DEPLOY_REF}")
    require_env = run.ran("check_config.py require-env")
    validate = run.ran("check_config.py validate")
    install = run.index(lambda call: call.startswith("install ") and "bob.vps.yaml" in call)
    understudy = run.ran("check_config.py understudy-model")
    restart = run.ran("systemctl restart bob")
    assert -1 < checkout < require_env < validate < install < understudy < restart, run.calls


def test_the_effective_config_equals_the_tracked_file(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    assert run.live_config == run.tracked_config
    assert "bob.vps.yaml" in run.output  # sha256sum of both is in the deploy log
    assert "config OK" in run.output


def test_the_deploy_log_carries_no_value_from_env(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert leaked_values(run.output, PRODUCTION_ENV) == []


def test_a_missing_identifier_in_env_stops_the_deploy_before_the_config_is_touched(
    tmp_path: Path,
) -> None:
    env = {key: value for key, value in PRODUCTION_ENV.items() if key != "BOB_TELEGRAM__OWNER_ID"}

    run = _deploy(tmp_path, env=env)

    assert run.returncode != 0
    assert "BOB_TELEGRAM__OWNER_ID" in run.output
    assert "deploy/RUNBOOK.md §9" in run.output
    assert not _restarted(run), run.calls
    assert run.live_config.decode() == _OLD_LIVE_CONFIG


def test_a_config_that_does_not_load_with_the_real_env_never_reaches_a_restart(
    tmp_path: Path,
) -> None:
    env = {**PRODUCTION_ENV, "BOB_TELEGRAM__CHAT_ID": "-100777abc111"}

    run = _deploy(tmp_path, env=env)

    assert run.returncode != 0
    assert not _restarted(run), run.calls
    assert run.live_config.decode() == _OLD_LIVE_CONFIG
    assert leaked_values(run.output, env) == []


def test_a_copy_that_differs_from_the_tracked_file_stops_the_restart(tmp_path: Path) -> None:
    run = _deploy(tmp_path, stub_env={"STUB_INSTALL_CORRUPT": "1"})

    assert run.returncode != 0
    assert not _restarted(run), run.calls
    assert "sha256" in run.output


def test_with_the_understudy_off_the_deploy_pulls_no_model(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    assert "дублёр выключен в конфиге — модель не тянем" in run.output
    assert run.ran("ollama ") == -1, run.calls


def test_with_the_understudy_on_the_deploy_pulls_its_model_before_the_restart(
    tmp_path: Path,
) -> None:
    run = _deploy(tmp_path, tracked=_tracked_with_understudy("qwen3:8b"))

    assert run.returncode == 0, run.output
    pull = run.ran("ollama pull qwen3:8b")
    listed = run.ran("ollama list")
    assert -1 < pull < listed < run.ran("systemctl restart bob"), run.calls


def test_a_model_missing_after_the_pull_stops_the_restart(tmp_path: Path) -> None:
    run = _deploy(
        tmp_path,
        tracked=_tracked_with_understudy("qwen3:8b"),
        stub_env={"STUB_OLLAMA_PULL_NOOP": "1"},
    )

    assert run.returncode != 0
    assert "qwen3:8b" in run.output
    assert not _restarted(run), run.calls


def test_the_deploy_never_writes_the_env_file(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    assert run.env_after == run.env_before


@pytest.mark.parametrize("tool", ["bash", "sha256sum"])
def test_the_host_tools_the_guard_relies_on_are_real(tool: str) -> None:
    # The guard is only as real as these two: say so instead of skipping silently.
    assert shutil.which(tool) is not None, f"{tool} is required to run the deploy guard"
