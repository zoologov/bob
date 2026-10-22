# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""``deploy/bootstrap.sh`` on a fresh host: config and understudy model by config (BOB-116 D8b).

The two BOB-116 steps of the bootstrap are EXECUTED: the script is sourced (its ``main``
does not run when sourced) and the step function is called, with ``sudo``, ``install`` and
``ollama`` replaced by recording stubs. ``deploy/check_config.py`` and ``sha256sum`` are
the real ones, so the decision «pull a model or not» is the same one the deploy makes.

BOB-126: the systemd files (Bob's units and the Ollama keep-alive drop-in) are installed
only when their content differs, into ``SYSTEMD_DIR`` — a temporary directory here, the
production default ``/etc/systemd/system`` otherwise. The ORDER of ``main`` is held by
running ``main`` itself with every step replaced by a recorder.

Not held here: apt, useradd, the real Ollama and systemd — the bodies of the other steps.
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
_DEPLOY_DIR = REPO_ROOT / "deploy"
_KEEP_ALIVE = "ollama.service.d/keep-alive.conf"
_UNITS = ("bob.service", "bob-backup.service", "bob-backup.timer")


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
    installed: dict[str, str] | None = None,
) -> StepRun:
    """Source the bootstrap and run ``step``; ``installed`` — files already in systemd."""
    home = _host(tmp_path, tracked or VPS_CONFIG.read_text(encoding="utf-8"), with_env=with_env)
    systemd = tmp_path / "etc-systemd-system"
    systemd.mkdir()
    for relative, content in (installed or {}).items():
        (systemd / relative).parent.mkdir(parents=True, exist_ok=True)
        (systemd / relative).write_text(content, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("sudo", "install", "ollama", "systemctl", "sleep"):
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
            "SYSTEMD_DIR": str(systemd),
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


def _tracked_with_understudy_off() -> str:
    config = yaml.safe_load(VPS_CONFIG.read_text(encoding="utf-8"))
    config["llm"].update(tier0_fallback="")
    return yaml.safe_dump(config, allow_unicode=True)


def test_bootstrap_pulls_the_model_the_tracked_config_turns_on(tmp_path: Path) -> None:
    # BOB-126: the production config itself turns the understudy on.
    run = _run_step(tmp_path, "ensure_understudy_model")

    assert run.returncode == 0, run.output
    assert "ollama pull qwen3.5:4b" in run.calls, run.calls


def test_bootstrap_pulls_no_model_while_the_config_keeps_the_understudy_off(
    tmp_path: Path,
) -> None:
    run = _run_step(tmp_path, "ensure_understudy_model", tracked=_tracked_with_understudy_off())

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


# --- systemd files (BOB-126) --------------------------------------------------------------


def _systemd(tmp_path: Path) -> Path:
    return tmp_path / "etc-systemd-system"


def _source(relative: str) -> str:
    name = "ollama-keep-alive.conf" if relative == _KEEP_ALIVE else relative
    return (_DEPLOY_DIR / name).read_text(encoding="utf-8")


def _installs(run: StepRun, target: str) -> list[str]:
    return [call for call in run.calls if call.startswith("install ") and call.endswith(target)]


def test_bootstrap_installs_the_keep_alive_and_restarts_ollama(tmp_path: Path) -> None:
    run = _run_step(tmp_path, "ensure_ollama_keep_alive")

    assert run.returncode == 0, run.output
    installed = (_systemd(tmp_path) / _KEEP_ALIVE).read_text(encoding="utf-8")
    assert installed == _source(_KEEP_ALIVE)
    install = run.calls.index(_installs(run, _KEEP_ALIVE)[0])
    reload_ = run.calls.index("systemctl daemon-reload")
    assert install < reload_ < run.calls.index("systemctl restart ollama"), run.calls


def test_bootstrap_waits_until_the_restarted_ollama_answers(tmp_path: Path) -> None:
    run = _run_step(tmp_path, "ensure_ollama_keep_alive", stub_env={"STUB_OLLAMA_DOWN_FOR": "2"})

    assert run.returncode == 0, run.output
    restart = run.calls.index("systemctl restart ollama")
    assert run.calls[restart + 1 :] == ["ollama ps"] * 3, run.calls


def test_bootstrap_fails_when_the_restarted_ollama_never_answers(tmp_path: Path) -> None:
    run = _run_step(tmp_path, "ensure_ollama_keep_alive", stub_env={"STUB_OLLAMA_DOWN_FOR": "-1"})

    assert run.returncode != 0
    assert "Ollama" in run.output


def test_bootstrap_leaves_an_unchanged_keep_alive_and_ollama_alone(tmp_path: Path) -> None:
    run = _run_step(
        tmp_path, "ensure_ollama_keep_alive", installed={_KEEP_ALIVE: _source(_KEEP_ALIVE)}
    )

    assert run.returncode == 0, run.output
    assert "keep-alive: без изменений" in run.output
    assert run.calls == [], run.calls


def test_bootstrap_puts_the_keep_alive_in_place_before_ollama_is_installed(
    tmp_path: Path,
) -> None:
    # The drop-in waits in ollama.service.d and applies once Ollama's own unit appears.
    run = _run_step(tmp_path, "ensure_ollama_keep_alive", ollama_installed=False)

    assert run.returncode == 0, run.output
    assert (_systemd(tmp_path) / _KEEP_ALIVE).is_file()
    assert "systemctl restart ollama" not in run.calls, run.calls


def test_bootstrap_installs_missing_units_and_reloads_systemd(tmp_path: Path) -> None:
    run = _run_step(tmp_path, "ensure_units")

    assert run.returncode == 0, run.output
    for unit in _UNITS:
        assert (_systemd(tmp_path) / unit).read_text(encoding="utf-8") == _source(unit), unit
    last_install = max(run.calls.index(_installs(run, unit)[0]) for unit in _UNITS)
    assert last_install < run.calls.index("systemctl daemon-reload"), run.calls


def test_bootstrap_does_not_reinstall_or_reload_unchanged_units(tmp_path: Path) -> None:
    run = _run_step(tmp_path, "ensure_units", installed={unit: _source(unit) for unit in _UNITS})

    assert run.returncode == 0, run.output
    assert [call for call in run.calls if call.startswith("install ")] == [], run.calls
    assert "systemctl daemon-reload" not in run.calls, run.calls


def test_bootstrap_reinstalls_only_the_unit_that_changed(tmp_path: Path) -> None:
    installed = {unit: _source(unit) for unit in _UNITS}
    installed["bob.service"] = "[Service]\nEnvironmentFile=/opt/bob/.env\n"

    run = _run_step(tmp_path, "ensure_units", installed=installed)

    assert run.returncode == 0, run.output
    assert [call for call in run.calls if call.startswith("install ")] == _installs(
        run, "bob.service"
    ), run.calls
    assert "systemctl daemon-reload" in run.calls, run.calls
    assert (_systemd(tmp_path) / "bob.service").read_text(encoding="utf-8") == _source(
        "bob.service"
    )


def test_bootstrap_main_sets_the_keep_alive_before_it_pulls_the_understudy(
    tmp_path: Path,
) -> None:
    # main itself runs, each step replaced by a recorder: the ORDER is what main does.
    record_steps = (
        'require_root() { :; }; '
        'for f in $(compgen -A function ensure_); do '
        'eval "$f() { echo $f >> \\"\\$STUB_LOG\\"; }"; done; main'
    )

    run = _run_step(tmp_path, record_steps)

    assert run.returncode == 0, run.output
    keep_alive = run.calls.index("ensure_ollama_keep_alive")
    assert keep_alive < run.calls.index("ensure_understudy_model"), run.calls
