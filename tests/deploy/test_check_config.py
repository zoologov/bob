# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""``deploy/check_config.py`` — the deploy's checks of the production config (BOB-116 D8b).

The script runs on the VPS as user ``bob`` against the REAL ``/opt/bob/.env``, before
``systemctl restart bob``; its output goes to the public deploy log. So every test runs it
as a real process, the way the deploy does, and every test that feeds it values also
asserts that not one value came back out.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from tests.deploy.conftest import (
    CHECK_SCRIPT,
    PRODUCTION_ENV,
    VPS_CONFIG,
    leaked_values,
    write_env_file,
)

if TYPE_CHECKING:
    from pathlib import Path

_RUNBOOK_POINTER = "deploy/RUNBOOK.md §9"
_TIMEOUT_S = 60


def _run(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), **(extra_env or {})}
    return subprocess.run(  # noqa: S603 — this interpreter and the repo's own script
        [sys.executable, str(CHECK_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_S,
        check=False,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _without(name: str) -> dict[str, str]:
    return {key: value for key, value in PRODUCTION_ENV.items() if key != name}


def _variant_config(tmp_path: Path, **llm: object) -> Path:
    config = yaml.safe_load(VPS_CONFIG.read_text(encoding="utf-8"))
    config["llm"].update(llm)
    path = tmp_path / "bob.variant.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


# --- require-env -------------------------------------------------------------------------


def test_require_env_passes_when_every_mandatory_name_is_set(env_file: Path) -> None:
    result = _run("require-env", "--env-file", str(env_file))

    assert result.returncode == 0, _output(result)
    assert leaked_values(_output(result), PRODUCTION_ENV) == []


@pytest.mark.parametrize("missing", sorted(PRODUCTION_ENV))
def test_require_env_names_the_missing_variable_and_points_at_the_runbook(
    tmp_path: Path, missing: str
) -> None:
    values = _without(missing)
    env_file = write_env_file(tmp_path / ".env", values)

    result = _run("require-env", "--env-file", str(env_file))

    assert result.returncode == 1
    assert missing in result.stderr
    assert _RUNBOOK_POINTER in result.stderr
    assert leaked_values(_output(result), values) == []


def test_require_env_counts_an_empty_value_as_missing(tmp_path: Path) -> None:
    env_file = write_env_file(tmp_path / ".env", {**PRODUCTION_ENV, "BOB_TELEGRAM__OWNER_ID": ""})

    result = _run("require-env", "--env-file", str(env_file))

    assert result.returncode == 1
    assert "BOB_TELEGRAM__OWNER_ID" in result.stderr


def test_require_env_reads_the_file_not_the_deploy_shell(tmp_path: Path) -> None:
    # systemd starts Bob with the FILE; a variable that only the deploy shell has
    # must not make the check pass.
    env_file = write_env_file(tmp_path / ".env", _without("BOB_TELEGRAM__OWNER_ID"))

    result = _run(
        "require-env",
        "--env-file",
        str(env_file),
        extra_env={"BOB_TELEGRAM__OWNER_ID": "555000222"},
    )

    assert result.returncode == 1
    assert "BOB_TELEGRAM__OWNER_ID" in result.stderr


def test_require_env_fails_when_the_env_file_is_absent(tmp_path: Path) -> None:
    result = _run("require-env", "--env-file", str(tmp_path / "missing.env"))

    assert result.returncode == 1
    assert _RUNBOOK_POINTER in result.stderr


def test_require_env_reads_systemd_style_quotes_and_comments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    lines = ["# comment", "; another comment", "   "]
    lines += [f'{key}="{value}"' for key, value in PRODUCTION_ENV.items()]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _run("validate", "--config", str(VPS_CONFIG), "--env-file", str(env_file))

    assert result.returncode == 0, _output(result)


# --- validate ----------------------------------------------------------------------------


def test_validate_loads_the_tracked_config_with_the_real_env(env_file: Path) -> None:
    result = _run("validate", "--config", str(VPS_CONFIG), "--env-file", str(env_file))

    assert result.returncode == 0, _output(result)
    assert "config OK" in result.stdout
    assert leaked_values(_output(result), PRODUCTION_ENV) == []


def test_validate_fails_on_a_value_the_loader_cannot_type_without_printing_it(
    tmp_path: Path,
) -> None:
    values = {**PRODUCTION_ENV, "BOB_TELEGRAM__CHAT_ID": "-100777abc111"}
    env_file = write_env_file(tmp_path / ".env", values)

    result = _run("validate", "--config", str(VPS_CONFIG), "--env-file", str(env_file))

    assert result.returncode == 1
    assert "BOB_TELEGRAM__CHAT_ID" in result.stderr
    assert "config OK" not in result.stdout
    assert leaked_values(_output(result), values) == []


@pytest.mark.parametrize(
    ("name", "value", "path"),
    [
        ("BOB_TELEGRAM__OWNER_ID", "0", "telegram.owner_id"),
        ("BOB_TELEGRAM__CHAT_ID", "0", "telegram.chat_id"),
        ("BOB_TELEGRAM__BOB__TOPIC_ID", "0", "telegram.bob.topic_id"),
        ("BOB_TELEGRAM__ALLOWED_CHAT_IDS", "", "telegram.allowed_chat_ids"),
        ("BOB_TELEGRAM__TOKEN", "", "telegram.bob.token"),
        ("GUPPI_TELEGRAM__TOKEN", "", "telegram.guppi.token"),
        ("BOB_LLM__TIER0_API_KEY", "", "llm.tier0_api_key"),
        ("BOB_LLM__TIER1_API_KEY", "", "llm.tier1_api_key"),
    ],
)
def test_validate_names_a_setting_bob_cannot_start_without(
    tmp_path: Path, name: str, value: str, path: str
) -> None:
    values = {**PRODUCTION_ENV, name: value}
    env_file = write_env_file(tmp_path / ".env", values)

    result = _run("validate", "--config", str(VPS_CONFIG), "--env-file", str(env_file))

    assert result.returncode == 1
    assert path in result.stderr
    assert leaked_values(_output(result), values) == []


def test_validate_rejects_an_unknown_understudy_backend(tmp_path: Path, env_file: Path) -> None:
    config = _variant_config(tmp_path, tier0_fallback="olama")

    result = _run("validate", "--config", str(config), "--env-file", str(env_file))

    assert result.returncode == 1
    assert "tier0_fallback" in result.stderr


def test_validate_fails_on_a_config_file_that_is_not_there(tmp_path: Path, env_file: Path) -> None:
    result = _run("validate", "--config", str(tmp_path / "nope.yaml"), "--env-file", str(env_file))

    assert result.returncode == 1


# --- understudy-model --------------------------------------------------------------------


def test_understudy_model_is_empty_while_the_tracked_config_keeps_it_off(env_file: Path) -> None:
    result = _run("understudy-model", "--config", str(VPS_CONFIG), "--env-file", str(env_file))

    assert result.returncode == 0, _output(result)
    assert result.stdout == ""


def test_understudy_model_names_the_model_when_the_config_turns_it_on(
    tmp_path: Path, env_file: Path
) -> None:
    config = _variant_config(tmp_path, tier0_fallback="ollama", tier0_fallback_model="qwen3:8b")

    result = _run("understudy-model", "--config", str(config), "--env-file", str(env_file))

    assert result.returncode == 0, _output(result)
    assert result.stdout == "qwen3:8b\n"


def test_understudy_model_honours_an_env_override_of_the_flag(tmp_path: Path) -> None:
    # The EFFECTIVE config decides, and .env sits above the file.
    env_file = write_env_file(
        tmp_path / ".env",
        {
            **PRODUCTION_ENV,
            "BOB_LLM__TIER0_FALLBACK": "ollama",
            "BOB_LLM__TIER0_FALLBACK_MODEL": "m:1",
        },
    )

    result = _run("understudy-model", "--config", str(VPS_CONFIG), "--env-file", str(env_file))

    assert result.stdout == "m:1\n"


def test_understudy_model_works_without_an_env_file_on_a_fresh_host(tmp_path: Path) -> None:
    # bootstrap.sh runs before the owner has put .env in place.
    config = _variant_config(tmp_path, tier0_fallback="ollama", tier0_fallback_model="qwen3:8b")

    result = _run("understudy-model", "--config", str(config))

    assert result.returncode == 0, _output(result)
    assert result.stdout == "qwen3:8b\n"


# --- compare-keys ------------------------------------------------------------------------


def test_compare_keys_lists_paths_and_never_values(tmp_path: Path) -> None:
    old = yaml.safe_load(VPS_CONFIG.read_text(encoding="utf-8"))
    old["telegram"]["owner_id"] = 555000222
    old["telegram"]["bob"] = {"token": "bob-token-SECRET-7f3a"}
    old["diagrams"] = {"mmdc_bin": "/usr/local/bin/mmdc-SENTINEL"}
    old["runtime"]["heartbeat_seconds"] = 4519
    old_path = tmp_path / "bob.yaml.pre-BOB-116"
    old_path.write_text(yaml.safe_dump(old, allow_unicode=True), encoding="utf-8")

    result = _run("compare-keys", "--old", str(old_path), "--new", str(VPS_CONFIG))
    out = _output(result)

    assert result.returncode == 0, out
    assert "telegram.owner_id" in out
    assert "telegram.bob.token" in out
    assert "diagrams.mmdc_bin" in out
    assert "runtime.heartbeat_seconds" in out
    for value in ("555000222", "bob-token-SECRET-7f3a", "mmdc-SENTINEL", "4519"):
        assert value not in out


def test_compare_keys_routes_ids_to_env_and_settings_to_the_tracked_file(tmp_path: Path) -> None:
    old = yaml.safe_load(VPS_CONFIG.read_text(encoding="utf-8"))
    old["telegram"]["owner_id"] = 555000222
    old["diagrams"] = {"mmdc_bin": "/usr/local/bin/mmdc"}
    old_path = tmp_path / "old.yaml"
    old_path.write_text(yaml.safe_dump(old, allow_unicode=True), encoding="utf-8")

    result = _run("compare-keys", "--old", str(old_path), "--new", str(VPS_CONFIG))
    lines = result.stdout.splitlines()

    owner = next(line for line in lines if "telegram.owner_id" in line)
    mmdc = next(line for line in lines if "diagrams.mmdc_bin" in line)
    assert ".env" in owner
    assert "bob.vps.yaml" in mmdc
