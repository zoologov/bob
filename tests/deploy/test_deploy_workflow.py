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
fails here. So does a check pointed at the wrong FILE: a tracked file that is broken by
itself (with the live file and ``.env`` valid) must stop the deploy, and a broken live
file must not stop a valid tracked one (review M4: before those two cases, validating the
live file instead of the tracked one kept every test here green).

BOB-126 adds two systemd files the deploy owns: the Ollama keep-alive drop-in and Bob's
own unit. Each is installed only when its content differs from what the server has, the
drop-in before the understudy model is pulled (with ``daemon-reload`` and a restart of
Ollama), the unit before Bob is restarted (``daemon-reload``, no restart of its own). An
unchanged file must cause none of that — a deploy that restarts Ollama every time unloads
both models on every release.

What it does NOT hold: the real ssh hop, the real systemd and Ollama, and the server's
paths — the remote script reads ``BOB_HOME``/``UV_BIN``/``UV_TOOLS``/``UV_TOOL_BINS``/
``SYSTEMD_DIR`` from the environment only so that this test can point them at a temporary
directory; over real ssh none of them is passed, and the production defaults apply.
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
_UNIT_SOURCE = REPO_ROOT / "deploy" / "bob.service"
_KEEP_ALIVE_SOURCE = REPO_ROOT / "deploy" / "ollama-keep-alive.conf"
# Where the deploy installs them, relative to the systemd directory.
_UNIT = "bob.service"
_KEEP_ALIVE = "ollama.service.d/keep-alive.conf"
_OLD_UNIT = "[Service]\nEnvironmentFile=/opt/bob/.env\n"
_OLD_KEEP_ALIVE = "[Service]\nEnvironment=OLLAMA_KEEP_ALIVE=5m\n"

@dataclass(frozen=True)
class DeployRun:
    returncode: int
    output: str
    calls: list[str]
    live_config: bytes
    tracked_config: bytes
    # What the fake systemd directory holds after the run; ``None`` — the file is absent.
    installed_unit: bytes | None
    installed_keep_alive: bytes | None
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


def _server(tmp_path: Path, tracked: str, live: str) -> Path:
    """A fake /opt/bob: the checked-out code's check script, configs, venv python, .env."""
    home = tmp_path / "opt-bob"
    (home / "deploy").mkdir(parents=True)
    (home / "config").mkdir()
    (home / ".venv" / "bin").mkdir(parents=True)
    shutil.copyfile(CHECK_SCRIPT, home / "deploy" / "check_config.py")
    shutil.copyfile(_UNIT_SOURCE, home / "deploy" / "bob.service")
    shutil.copyfile(_KEEP_ALIVE_SOURCE, home / "deploy" / "ollama-keep-alive.conf")
    (home / "config" / "bob.vps.yaml").write_text(tracked, encoding="utf-8")
    (home / "config" / "bob.yaml").write_text(live, encoding="utf-8")
    write_executable(home / ".venv" / "bin" / "python", f'exec "{sys.executable}" "$@"\n')
    return home


def _deploy(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    tracked: str | None = None,
    live: str = _OLD_LIVE_CONFIG,
    stub_env: dict[str, str] | None = None,
    installed: dict[str, str] | None = None,
) -> DeployRun:
    """Run the deploy step; ``installed`` — files already in the server's systemd directory."""
    home = _server(tmp_path, tracked or VPS_CONFIG.read_text(encoding="utf-8"), live)
    systemd = tmp_path / "etc-systemd-system"
    systemd.mkdir()
    for relative, content in (installed or {}).items():
        (systemd / relative).parent.mkdir(parents=True, exist_ok=True)
        (systemd / relative).write_text(content, encoding="utf-8")
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
        "SYSTEMD_DIR": str(systemd),
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
        installed_unit=_read_if_present(systemd / _UNIT),
        installed_keep_alive=_read_if_present(systemd / _KEEP_ALIVE),
        env_before=env_before,
        env_after=env_file.read_bytes(),
    )


def _read_if_present(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _host_bash() -> str:
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to run the deploy guard"
    return bash


def _tracked_variant(**llm: str) -> str:
    """The tracked config with ``llm`` settings replaced."""
    config = yaml.safe_load(VPS_CONFIG.read_text(encoding="utf-8"))
    config["llm"].update(llm)
    return yaml.safe_dump(config, allow_unicode=True)


def _tracked_with_understudy(model: str) -> str:
    return _tracked_variant(tier0_fallback="ollama", tier0_fallback_model=model)


def _restarted(run: DeployRun) -> bool:
    return run.ran("systemctl restart bob") >= 0


def test_the_deploy_checks_then_copies_then_restarts_in_that_order(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    # BOB-125: a branch lands as `checkout -B <ref> origin/<ref>`, a tag/SHA as `checkout <ref>`.
    checkout = run.index(lambda call: "checkout" in call and _DEPLOY_REF in call)
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


# Configs that the loader cannot build even with a valid .env — the file ITSELF is broken.
_BROKEN_CONFIGS: dict[str, Callable[[], str]] = {
    "yaml-syntax": lambda: VPS_CONFIG.read_text(encoding="utf-8") + "\nbroken: [unclosed\n",
    "unknown-understudy": lambda: _tracked_variant(tier0_fallback="olama"),
}


def _validates(config_text: str, workdir: Path) -> bool:
    """Does ``check_config.py validate`` accept ``config_text`` with the production .env?"""
    workdir.mkdir()
    config = workdir / "config.yaml"
    config.write_text(config_text, encoding="utf-8")
    env_file = write_env_file(workdir / ".env", PRODUCTION_ENV)
    result = subprocess.run(  # noqa: S603 — the repository's own check script
        [sys.executable, str(CHECK_SCRIPT), "validate", "--config", str(config),
         "--env-file", str(env_file)],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.parametrize("broken", sorted(_BROKEN_CONFIGS))
def test_a_broken_tracked_file_stops_the_deploy_while_the_live_one_and_env_are_valid(
    tmp_path: Path, broken: str
) -> None:
    # Review M4: every other failing case breaks .env, which fails BOTH files, so a check
    # pointed at the wrong file passed them all. Here only the tracked file is broken: the
    # live one and .env are valid, so only a check of the TRACKED file can stop the deploy.
    tracked = _BROKEN_CONFIGS[broken]()
    assert _validates(_OLD_LIVE_CONFIG, tmp_path / "live-check"), "live+env must be valid"
    assert not _validates(tracked, tmp_path / "tracked-check"), "the tracked file must fail"

    run = _deploy(tmp_path / "deploy", tracked=tracked)

    assert run.returncode != 0
    assert not _restarted(run), run.calls
    assert run.index(lambda call: call.startswith("install ")) == -1, run.calls
    assert run.live_config.decode() == _OLD_LIVE_CONFIG
    assert leaked_values(run.output, PRODUCTION_ENV) == []


def test_a_broken_live_file_does_not_stop_a_deploy_of_a_valid_tracked_file(
    tmp_path: Path,
) -> None:
    # The inverse: the live file is what the deploy REPLACES, so its state must not decide.
    broken_live = _BROKEN_CONFIGS["yaml-syntax"]()
    assert not _validates(broken_live, tmp_path / "live-check"), "the live file must fail"

    run = _deploy(tmp_path / "deploy", live=broken_live)

    assert run.returncode == 0, run.output
    assert _restarted(run), run.calls
    assert run.live_config == run.tracked_config


def test_a_copy_that_differs_from_the_tracked_file_stops_the_restart(tmp_path: Path) -> None:
    run = _deploy(tmp_path, stub_env={"STUB_INSTALL_CORRUPT": "1"})

    assert run.returncode != 0
    assert not _restarted(run), run.calls
    assert "sha256" in run.output


def test_with_the_understudy_off_the_deploy_pulls_no_model(tmp_path: Path) -> None:
    run = _deploy(tmp_path, tracked=_tracked_variant(tier0_fallback=""))

    assert run.returncode == 0, run.output
    assert "дублёр выключен в конфиге — модель не тянем" in run.output
    assert run.index(lambda call: call.startswith(("ollama pull", "ollama list"))) == -1, (
        run.calls
    )


def test_the_tracked_config_has_the_deploy_pull_the_understudy_model(tmp_path: Path) -> None:
    # BOB-126: the production config itself turns the understudy on.
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    assert "модель дублёра на месте: qwen3.5:4b" in run.output
    assert -1 < run.ran("ollama pull qwen3.5:4b") < run.ran("systemctl restart bob"), run.calls


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


# --- systemd files the deploy owns (BOB-126) ---------------------------------------------


def _installs(run: DeployRun, target: str) -> int:
    """Position of the ``install`` call that writes ``target``; -1 when there is none."""
    return run.index(lambda call: call.startswith("install ") and call.endswith(target))


def _up_to_date() -> dict[str, str]:
    """The server already holds exactly what the repository ships."""
    return {
        _UNIT: _UNIT_SOURCE.read_text(encoding="utf-8"),
        _KEEP_ALIVE: _KEEP_ALIVE_SOURCE.read_text(encoding="utf-8"),
    }


def test_a_fresh_server_gets_the_keep_alive_and_ollama_restarts_before_the_pull(
    tmp_path: Path,
) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    assert run.installed_keep_alive == _KEEP_ALIVE_SOURCE.read_bytes()
    install = _installs(run, _KEEP_ALIVE)
    reload_ = run.ran("systemctl daemon-reload")
    restart_ollama = run.ran("systemctl restart ollama")
    pull = run.ran("ollama pull")
    assert -1 < install < reload_ < restart_ollama < pull < run.ran("systemctl restart bob"), (
        run.calls
    )


def test_a_fresh_server_gets_bobs_unit_reloaded_before_bob_restarts(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    assert run.installed_unit == _UNIT_SOURCE.read_bytes()
    install = _installs(run, _UNIT)
    restart = run.ran("systemctl restart bob")
    reloads = [i for i, call in enumerate(run.calls) if call == "systemctl daemon-reload"]
    assert install > -1, run.calls
    # A reload BETWEEN the install and the restart: one before the install would not count.
    assert any(install < i < restart for i in reloads), run.calls


def test_unchanged_systemd_files_are_neither_reinstalled_nor_reloaded(tmp_path: Path) -> None:
    run = _deploy(tmp_path, installed=_up_to_date())

    assert run.returncode == 0, run.output
    assert "keep-alive: без изменений" in run.output
    assert "unit bob: без изменений" in run.output
    assert _installs(run, _KEEP_ALIVE) == -1, run.calls
    assert _installs(run, _UNIT) == -1, run.calls
    assert run.ran("systemctl daemon-reload") == -1, run.calls
    assert run.ran("systemctl restart ollama") == -1, run.calls
    assert _restarted(run), run.calls


def test_a_changed_keep_alive_is_reinstalled_and_ollama_restarted(tmp_path: Path) -> None:
    run = _deploy(tmp_path, installed={**_up_to_date(), _KEEP_ALIVE: _OLD_KEEP_ALIVE})

    assert run.returncode == 0, run.output
    assert run.installed_keep_alive == _KEEP_ALIVE_SOURCE.read_bytes()
    assert -1 < _installs(run, _KEEP_ALIVE) < run.ran("systemctl restart ollama"), run.calls
    assert _installs(run, _UNIT) == -1, run.calls


def test_a_changed_unit_alone_reloads_systemd_without_touching_ollama(tmp_path: Path) -> None:
    run = _deploy(tmp_path, installed={**_up_to_date(), _UNIT: _OLD_UNIT})

    assert run.returncode == 0, run.output
    assert run.installed_unit == _UNIT_SOURCE.read_bytes()
    install = _installs(run, _UNIT)
    assert -1 < install < run.ran("systemctl daemon-reload") < run.ran("systemctl restart bob")
    assert run.ran("systemctl restart ollama") == -1, run.calls
    assert "keep-alive: без изменений" in run.output


def test_the_keep_alive_is_installed_even_with_the_understudy_off(tmp_path: Path) -> None:
    # The embedder bge-m3 reloads every ~5 minutes without it (BOB-121) — the understudy
    # is not the only model the drop-in serves.
    run = _deploy(tmp_path, tracked=_tracked_variant(tier0_fallback=""))

    assert run.returncode == 0, run.output
    assert run.installed_keep_alive == _KEEP_ALIVE_SOURCE.read_bytes()
    assert run.ran("systemctl restart ollama") > -1, run.calls


def test_the_pull_waits_until_the_restarted_ollama_answers(tmp_path: Path) -> None:
    # systemctl returns as soon as the process is started, not when it listens: a pull
    # straight after the restart would hit a closed port.
    run = _deploy(tmp_path, stub_env={"STUB_OLLAMA_DOWN_FOR": "3"})

    assert run.returncode == 0, run.output
    answered = max(i for i, call in enumerate(run.calls) if call == "ollama ps")
    tries = [call for call in run.calls if call == "ollama ps"]
    assert len(tries) == 4, run.calls
    assert run.ran("systemctl restart ollama") < answered < run.ran("ollama pull"), run.calls


def test_ollama_that_never_answers_after_the_restart_stops_the_deploy(tmp_path: Path) -> None:
    run = _deploy(tmp_path, stub_env={"STUB_OLLAMA_DOWN_FOR": "-1"})

    assert run.returncode != 0
    assert "Ollama" in run.output
    assert run.ran("ollama pull") == -1, run.calls
    assert not _restarted(run), run.calls


def _left_behind(run: DeployRun) -> dict[str, str]:
    """The systemd files a run left on the server — the next deploy starts from them."""
    left: dict[str, str] = {}
    if run.installed_unit is not None:
        left[_UNIT] = run.installed_unit.decode()
    if run.installed_keep_alive is not None:
        left[_KEEP_ALIVE] = run.installed_keep_alive.decode()
    return left


def test_a_keep_alive_whose_reload_failed_is_installed_again_by_the_next_deploy(
    tmp_path: Path,
) -> None:
    # Review m1: install succeeded, daemon-reload failed — the copy on disk must not make
    # the next deploy say «без изменений» while Ollama runs without it.
    failed = _deploy(tmp_path / "first", stub_env={"STUB_SYSTEMCTL_FAIL": "daemon-reload"})

    assert failed.returncode != 0
    assert not _restarted(failed), failed.calls
    assert failed.installed_keep_alive is None

    retry = _deploy(tmp_path / "second", installed=_left_behind(failed))

    assert retry.returncode == 0, retry.output
    assert _installs(retry, _KEEP_ALIVE) > -1, retry.calls
    assert retry.ran("systemctl restart ollama") > -1, retry.calls


def test_a_keep_alive_whose_ollama_restart_failed_is_installed_again_by_the_next_deploy(
    tmp_path: Path,
) -> None:
    failed = _deploy(tmp_path / "first", stub_env={"STUB_SYSTEMCTL_FAIL": "restart ollama"})

    assert failed.returncode != 0
    assert failed.installed_keep_alive is None

    retry = _deploy(tmp_path / "second", installed=_left_behind(failed))

    assert retry.returncode == 0, retry.output
    assert retry.ran("systemctl restart ollama") > -1, retry.calls


def test_a_unit_whose_reload_failed_is_put_back_and_installed_again_next_time(
    tmp_path: Path,
) -> None:
    failed = _deploy(
        tmp_path / "first",
        installed={**_up_to_date(), _UNIT: _OLD_UNIT},
        stub_env={"STUB_SYSTEMCTL_FAIL": "daemon-reload"},
    )

    assert failed.returncode != 0
    assert not _restarted(failed), failed.calls
    # The previous unit is back: the file matches what systemd still has loaded.
    assert failed.installed_unit == _OLD_UNIT.encode()

    retry = _deploy(tmp_path / "second", installed=_left_behind(failed))

    assert retry.returncode == 0, retry.output
    assert retry.installed_unit == _UNIT_SOURCE.read_bytes()
    assert -1 < _installs(retry, _UNIT) < retry.ran("systemctl restart bob"), retry.calls


def test_ollama_that_does_not_come_back_stops_the_deploy_before_bob_restarts(
    tmp_path: Path,
) -> None:
    run = _deploy(tmp_path, stub_env={"STUB_SYSTEMCTL_FAIL": "restart ollama"})

    assert run.returncode != 0
    assert "Ollama" in run.output
    assert not _restarted(run), run.calls


def test_the_deploy_never_writes_the_env_file(tmp_path: Path) -> None:
    run = _deploy(tmp_path)

    assert run.returncode == 0, run.output
    assert run.env_after == run.env_before


@pytest.mark.parametrize("tool", ["bash", "sha256sum"])
def test_the_host_tools_the_guard_relies_on_are_real(tool: str) -> None:
    # The guard is only as real as these two: say so instead of skipping silently.
    assert shutil.which(tool) is not None, f"{tool} is required to run the deploy guard"
